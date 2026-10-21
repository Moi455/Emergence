//! `MeshShadowPass` : les cascades d'ombre du soleil remplies par RASTÉRISATION des quads (L33), à la place du tracé
//! compute de L11. Le placement est celui de L11, inchangé : `ShadowPlanner` décide (CPU, `f64`) quelles cascades
//! refaire, `CascadePlacement` ancre le réseau de texels dans le MONDE (la fenêtre ne glisse que par crans entiers de
//! `taille / 32` texels, la valeur d'un texel ne change jamais : rien ne scintille quand la caméra bouge), la base du
//! soleil tourne en continu. Seul le remplissage change : une passe de profondeur orthographique par cascade refaite.
//!
//! Une génération entière est rendue en UNE image (budget de tuiles porté au maximum) : le planificateur voit toutes
//! ses tuiles finies et échange les couches. L'ombre est lue par l'échantillonnage de L11 (`voxel_shadow_sample.wgsl`,
//! PCF doux borné à 4 cm de pénombre) : seules la texture (profondeur Z inversé) et sa lecture changent.

use super::shaders::{self, PORTEE_OMBRES_M};
use super::world::{ChunkBox, MeshWorld};
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::partage::Partage;
use crate::sky::SkyParams;
use crate::voxel::gpu::{ShadowCascadeUniform, ShadowUniform};
use crate::voxel::shadow::{Generation, ShadowControl, ShadowParams, ShadowPlanner};
use glam::{DVec3, Mat4, Vec3, Vec4};

/// Tangente du demi-angle du disque solaire (0,2665°), comme L11.
const TAN_DEMI_SOLEIL: f32 = 0.004_651;

/// Ressources publiées par les ombres du maillage.
pub mod noms {
    use crate::graph::ResourceName;

    /// Uniforme des cascades (`ShadowUniform`), réécrit à chaque image.
    pub const UNIFORME: ResourceName = ResourceName::new("mesh_ombres_uniforme");
    /// Tableau de profondeurs `Depth32Float` : `2 × cascades` couches (génération avant et arrière).
    pub const CASCADES: ResourceName = ResourceName::new("mesh_ombres_cascades");
}

struct Gpu {
    pipeline: wgpu::RenderPipeline,
    couches: Vec<wgpu::TextureView>,
    vues: Vec<wgpu::Buffer>,
    groupes: Vec<wgpu::BindGroup>,
    uniforme: wgpu::Buffer,
    vide: wgpu::TextureView,
}

/// Cascades d'ombre rastérisées.
pub struct MeshShadowPass {
    params: ShadowParams,
    planner: ShadowPlanner,
    ciel: Partage<SkyParams>,
    monde: MeshWorld,
    controle: ShadowControl,
    revision_vue: u64,
    gpu: Option<Gpu>,
}

impl MeshShadowPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("maillage_ombres");

    /// Crée la passe. Le budget de tuiles est porté au maximum : une génération se remplit en une image.
    pub fn new(params: ShadowParams, ciel: Partage<SkyParams>, monde: MeshWorld) -> Self {
        let params = params
            .with_tiles_per_frame(1024)
            .expect("1024 tuiles par image est dans les bornes");
        Self {
            planner: ShadowPlanner::new(params),
            params,
            ciel,
            monde,
            controle: ShadowControl::new(),
            revision_vue: u64::MAX,
            gpu: None,
        }
    }

    /// Poignée pour invalider les cascades depuis la scène (le monde de maillages remplacé les invalide aussi).
    pub fn control(&self) -> ShadowControl {
        self.controle.clone()
    }

    /// Réglages.
    pub fn params(&self) -> &ShadowParams {
        &self.params
    }
}

fn dvec(v: glam::Vec3) -> DVec3 {
    DVec3::new(f64::from(v.x), f64::from(v.y), f64::from(v.z))
}

fn f4(v: DVec3, w: f32) -> [f32; 4] {
    [v.x as f32, v.y as f32, v.z as f32, w]
}

/// Ce que l'éclairage lit d'une génération avant : repère CAMÉRA (le rendu travaille relatif à la caméra).
fn cote_eclairage(g: &Generation, camera: DVec3, far_m: f64) -> ShadowCascadeUniform {
    let p = g.placement();
    let b = g.basis();
    ShadowCascadeUniform {
        origin: f4(p.origin(b) - camera, p.texel_m() as f32),
        right: f4(b.right(), g.layer() as f32),
        up: f4(b.up(), p.size() as f32),
        sun: f4(b.sun(), 1.0),
        limits: [far_m as f32, 0.0, 0.0, 0.0],
    }
}

/// Matrice « repère caméra -> clip » d'une cascade : orthographique, texels alignés sur ceux de L11 (le centre du
/// texel `(i, j)` est au centre du pixel `(i, j)`), profondeur Z inversé `1 - distance / PORTEE`.
pub fn matrice_cascade(g: &Generation, camera: DVec3) -> Mat4 {
    let p = g.placement();
    let b = g.basis();
    let o = p.origin(b) - camera;
    let (r, u, s) = (b.right(), b.up(), b.sun());
    let taille = f64::from(p.size());
    let a = 2.0 / (p.texel_m() * taille);
    let portee = f64::from(PORTEE_OMBRES_M);
    let cx = -a * o.dot(r) + 1.0 / taille - 1.0;
    let cy = a * o.dot(u) + 1.0 - 1.0 / taille;
    let cz = 1.0 - o.dot(s) / portee;
    // lignes de la matrice (clip = M · (p, 1)), puis transposition en colonnes pour glam
    let lignes = [
        Vec4::new((a * r.x) as f32, (a * r.y) as f32, (a * r.z) as f32, cx as f32),
        Vec4::new((-a * u.x) as f32, (-a * u.y) as f32, (-a * u.z) as f32, cy as f32),
        Vec4::new(
            (s.x / portee) as f32,
            (s.y / portee) as f32,
            (s.z / portee) as f32,
            cz as f32,
        ),
        Vec4::new(0.0, 0.0, 0.0, 1.0),
    ];
    Mat4::from_cols(
        Vec4::new(lignes[0].x, lignes[1].x, lignes[2].x, lignes[3].x),
        Vec4::new(lignes[0].y, lignes[1].y, lignes[2].y, lignes[3].y),
        Vec4::new(lignes[0].z, lignes[1].z, lignes[2].z, lignes[3].z),
        Vec4::new(lignes[0].w, lignes[1].w, lignes[2].w, lignes[3].w),
    )
}

/// Vrai si la boîte touche la fenêtre de la cascade (x et y de clip dans [-1, 1], profondeur ignorée).
pub fn boite_dans_fenetre(m: &Mat4, b: &ChunkBox) -> bool {
    let (mut x0, mut x1, mut y0, mut y1) = (f32::MAX, f32::MIN, f32::MAX, f32::MIN);
    for i in 0..8 {
        let c = Vec3::new(
            if i & 1 == 0 { b.min.x } else { b.max.x },
            if i & 2 == 0 { b.min.y } else { b.max.y },
            if i & 4 == 0 { b.min.z } else { b.max.z },
        );
        let q = *m * c.extend(1.0);
        x0 = x0.min(q.x);
        x1 = x1.max(q.x);
        y0 = y0.min(q.y);
        y1 = y1.max(q.y);
    }
    x1 >= -1.0 && x0 <= 1.0 && y1 >= -1.0 && y0 <= 1.0
}

impl RenderPass for MeshShadowPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, _setup: &PassSetup, res: &mut Resources) {
        use wgpu::TextureUsages as U;
        let dev = g.device();
        self.planner = ShadowPlanner::new(self.params);
        self.revision_vue = u64::MAX;
        let n = self.params.cascades();
        let taille = self.params.size();
        let couches = 2 * n;
        let texture = dev.create_texture(&wgpu::TextureDescriptor {
            label: Some("maillage ombres cascades"),
            size: wgpu::Extent3d {
                width: taille,
                height: taille,
                depth_or_array_layers: couches,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Depth32Float,
            usage: U::RENDER_ATTACHMENT | U::TEXTURE_BINDING | U::COPY_SRC,
            view_formats: &[],
        });
        let couche = |i: u32| {
            texture.create_view(&wgpu::TextureViewDescriptor {
                label: Some("maillage ombres couche"),
                dimension: Some(wgpu::TextureViewDimension::D2),
                aspect: wgpu::TextureAspect::DepthOnly,
                base_array_layer: i,
                array_layer_count: Some(1),
                ..Default::default()
            })
        };
        let couches_vues: Vec<wgpu::TextureView> = (0..couches).map(couche).collect();
        let uniforme = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("maillage ombres uniforme"),
            size: size_of::<ShadowUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        res.insert_texture(noms::CASCADES, texture);
        res.insert_buffer(noms::UNIFORME, uniforme.clone());
        let vide_tex = dev.create_texture(&wgpu::TextureDescriptor {
            label: Some("maillage ombres vide"),
            size: wgpu::Extent3d {
                width: 1,
                height: 1,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Depth32Float,
            usage: U::RENDER_ATTACHMENT,
            view_formats: &[],
        });
        let vide = vide_tex.create_view(&wgpu::TextureViewDescriptor::default());

        // Une matrice par couche (chaque cascade refaite écrit la sienne), un groupe par couche.
        let bgl = dev.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("maillage ombres vue bgl"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        });
        let vues: Vec<wgpu::Buffer> = (0..couches)
            .map(|_| {
                dev.create_buffer(&wgpu::BufferDescriptor {
                    label: Some("maillage ombres vue"),
                    size: 64,
                    usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                })
            })
            .collect();
        let groupes: Vec<wgpu::BindGroup> = vues
            .iter()
            .map(|b| {
                dev.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: Some("maillage ombres vue groupe"),
                    layout: &bgl,
                    entries: &[wgpu::BindGroupEntry {
                        binding: 0,
                        resource: b.as_entire_binding(),
                    }],
                })
            })
            .collect();
        let module = shaders::ombres();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout_chunks = self.monde.lock().layout().clone();
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("maillage ombres layout"),
            bind_group_layouts: &[Some(&bgl), None, None, Some(&layout_chunks)],
            immediate_size: 0,
        });
        let pipeline = dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("maillage ombres"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_shadow"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            fragment: None,
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleStrip,
                cull_mode: None,
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth32Float,
                depth_write_enabled: Some(true),
                depth_compare: Some(wgpu::CompareFunction::Greater),
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState::default(),
            multiview_mask: None,
            cache: None,
        });
        self.gpu = Some(Gpu {
            pipeline,
            couches: couches_vues,
            vues,
            groupes,
            uniforme,
            vide,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let Some(cam) = ctx.frame().voxel_camera().copied() else {
            log::error!("maillage_ombres : le contexte d'image n'a pas de caméra voxel");
            return;
        };
        let image = ctx.frame().index();
        let revision = {
            let mut m = self.monde.lock();
            m.begin_frame(ctx.gpu().queue(), image, cam.pos_mm());
            m.revision()
        };
        if self.controle.prendre() || revision != self.revision_vue {
            self.planner.invalidate();
            self.revision_vue = revision;
        }
        let (ciel, _) = self.ciel.lire();
        let camera_m = DVec3::from_array(cam.pos_mm().map(|v| v as f64 * 0.001));
        let plan = self.planner.plan(dvec(ciel.sun_direction()), camera_m);

        let n = self.params.cascades() as usize;
        let mut lumiere = ShadowUniform {
            cfg0: [n as f32, 0.0, self.params.blend_fraction(), TAN_DEMI_SOLEIL],
            cfg1: [
                self.params.normal_offset(),
                self.params.depth_bias_m(),
                self.params.slope_bias(),
                self.params.penumbra_scale(),
            ],
            cfg2: [self.params.penumbra_max_m(), PORTEE_OMBRES_M, 0.0, 0.0],
            ..Default::default()
        };
        let mut a_remplir: Vec<(usize, Mat4)> = Vec::new();
        for c in 0..n {
            if let Some(g) = plan.front(c) {
                lumiere.cfg0[1] = 1.0;
                lumiere.cascades[c] = cote_eclairage(g, camera_m, self.params.far_m(c as u32));
            }
            if plan.jobs().iter().any(|j| j.cascade() as usize == c)
                && let Some(g) = plan.building(c)
            {
                a_remplir.push((g.layer() as usize, matrice_cascade(g, camera_m)));
            }
        }
        let q = ctx.gpu().queue();
        q.write_buffer(&gpu.uniforme, 0, bytemuck::bytes_of(&lumiere));
        for (couche, m) in &a_remplir {
            q.write_buffer(&gpu.vues[*couche], 0, bytemuck::bytes_of(&m.to_cols_array()));
        }
        let monde = self.monde.lock();
        let Some(groupe_chunks) = monde.group() else {
            drop(monde);
            // aucun maillage : la passe reste ouverte (profil ~0 ms), sur la texture vide
            let _ = ctx.render_pass_depth("maillage ombres (vide)", &gpu.vide);
            return;
        };
        if a_remplir.is_empty() {
            drop(monde);
            let _ = ctx.render_pass_depth("maillage ombres (rien à refaire)", &gpu.vide);
            return;
        }
        for (couche, m) in &a_remplir {
            let liste = monde.visible(&|b| boite_dans_fenetre(m, b));
            let mut pass = ctx.render_pass_depth("maillage ombres", &gpu.couches[*couche]);
            pass.set_pipeline(&gpu.pipeline);
            pass.set_bind_group(0, &gpu.groupes[*couche], &[]);
            for d in &liste {
                pass.set_bind_group(3, groupe_chunks, &[d.offset()]);
                pass.draw(0..4, d.instances());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::voxel::shadow::{ShadowPlanner, SunBasis};

    #[test]
    fn le_centre_du_texel_tombe_au_centre_du_pixel_et_la_profondeur_est_celle_de_l11() {
        let mut p = ShadowPlanner::new(ShadowParams::default());
        let soleil = DVec3::new(0.3, 0.6, -0.4).normalize();
        let camera = DVec3::new(10_000.25, 1.7, 9_981.5);
        let plan = p.plan(soleil, camera);
        let g = plan.building(0).expect("génération en construction");
        let m = matrice_cascade(g, camera);
        let pl = g.placement();
        let b: &SunBasis = g.basis();
        // le centre du texel absolu (k0 + 100, m0 + 40) est le centre du pixel (100, 40), à la profondeur du plan
        let centre = pl.texel_center(b, pl.k0() + 100, pl.m0() + 40) - camera;
        let q = m * Vec3::new(centre.x as f32, centre.y as f32, centre.z as f32).extend(1.0);
        let taille = pl.size() as f32;
        let (px, py) = ((q.x + 1.0) * 0.5 * taille, (1.0 - q.y) * 0.5 * taille);
        assert!(
            (px - 100.5).abs() < 0.02 && (py - 40.5).abs() < 0.02,
            "pixel ({px}, {py})"
        );
        assert!(
            (q.z - 1.0).abs() < 1e-5,
            "sur le plan de départ : distance nulle, profondeur 1 ({})",
            q.z
        );
        // un point à 10 m derrière le plan (du côté opposé au soleil) : profondeur 1 - 10 / portée
        let loin = centre - b.sun() * 10.0;
        let q = m * Vec3::new(loin.x as f32, loin.y as f32, loin.z as f32).extend(1.0);
        assert!((q.z - (1.0 - 10.0 / PORTEE_OMBRES_M)).abs() < 1e-4, "{}", q.z);
    }
}
