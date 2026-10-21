//! `MeshRenderer` : la passe principale du rendu par maillage. Rastérise les quads des chunks visibles (cône de vision,
//! du plus proche au plus lointain) avec une profondeur (Z inversé infini) et calcule la lumière dans le fragment :
//! soleil de l'atmosphère et ombres en cascades raster, ambiance de l'hémisphère du ciel multipliée par l'occlusion
//! baked du sommet (jamais le soleil), spéculaire doux, translucidité du feuillage, perspective aérienne. Écrit dans la
//! cible HDR du fond de ciel ; le bloom et la composition AgX qui suivent sont ceux du tracé.

use super::ambient::AMBIANCE;
use super::frustum::Frustum;
use super::shaders;
use super::shadow::noms as noms_ombres;
use super::style::{MeshStyle, StyleUniform};
use super::world::MeshWorld;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::{HDR_FORMAT, MiseEnPage, echantillonneur_lineaire};
use crate::partage::Partage;
use crate::sky::noms as noms_ciel;
use crate::voxel::LightSettings;
use crate::voxel::gpu::{LightUniform, ShadowUniform};
use bytemuck::{Pod, Zeroable};
use wgpu::ShaderStages as Etage;

/// Ressources publiées par le rendu par maillage.
pub mod noms {
    use crate::graph::ResourceName;

    /// Profondeur `Depth32Float` du rendu par maillage, Z inversé infini, effacée à 0.
    pub const PROFONDEUR: ResourceName = ResourceName::new("mesh_profondeur");
}

/// Format de la profondeur.
const FORMAT_PROFONDEUR: wgpu::TextureFormat = wgpu::TextureFormat::Depth32Float;

/// Uniforme de l'image (miroir de `struct MeshFrame` de `mesh_main.wgsl`).
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct MeshFrame {
    view_proj: [f32; 16],
    screen: [f32; 4],
}

struct Gpu {
    pipeline: wgpu::RenderPipeline,
    groupe_ciel: wgpu::BindGroup,
    groupe_image: wgpu::BindGroup,
    groupe_ombres: wgpu::BindGroup,
    uniforme_image: wgpu::Buffer,
    uniforme_lumiere: wgpu::Buffer,
    hdr: wgpu::TextureView,
    profondeur: wgpu::TextureView,
}

/// Passe principale du rendu par maillage.
pub struct MeshRenderer {
    monde: MeshWorld,
    reglages: Partage<LightSettings>,
    occlusion: bool,
    style: MeshStyle,
    gpu: Option<Gpu>,
}

impl MeshRenderer {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("maillage_rendu");

    /// Crée la passe sur un monde de maillages et des réglages de lumière partagés avec la scène.
    pub fn new(monde: MeshWorld, reglages: Partage<LightSettings>) -> Self {
        Self {
            monde,
            reglages,
            occlusion: true,
            style: MeshStyle::new(),
            gpu: None,
        }
    }

    /// Style de L34 : relief froissé, occlusion creuse (tables), chaleur de l'ambiance.
    pub fn with_style(mut self, style: MeshStyle) -> Self {
        self.style = style;
        self
    }

    /// Allume ou éteint l'occlusion ambiante BAKÉE dans les sommets (comparaisons A/B, essais contre le tracé).
    pub fn with_occlusion(mut self, active: bool) -> Self {
        self.occlusion = active;
        self
    }
}

fn blend_fondu() -> wgpu::BlendState {
    // le fondu du sol au bord de la région maillée passe par la transparence de sortie, comme l'éclairage différé
    wgpu::BlendState {
        color: wgpu::BlendComponent {
            src_factor: wgpu::BlendFactor::SrcAlpha,
            dst_factor: wgpu::BlendFactor::OneMinusSrcAlpha,
            operation: wgpu::BlendOperation::Add,
        },
        alpha: wgpu::BlendComponent::REPLACE,
    }
}

impl RenderPass for MeshRenderer {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let (Some(frame_ciel), Some(trans), Some(vue_ciel), Some(hdr), Some(ambiance)) = (
            res.buffer(noms_ciel::FRAME).cloned(),
            res.view(noms_ciel::TRANSMITTANCE),
            res.view(noms_ciel::VUE_DU_CIEL),
            res.view(noms_ciel::HDR),
            res.view(AMBIANCE),
        ) else {
            log::error!(
                "maillage_rendu : le ciel ou l'ambiance manquent (SkyPass, fond et MeshAmbientPass doivent précéder)"
            );
            return;
        };
        let dev = g.device();
        let vf = Etage::VERTEX_FRAGMENT;
        let f = Etage::FRAGMENT;
        let bgl_ciel = MiseEnPage::new()
            .uniforme(vf)
            .texture(vf)
            .texture(vf)
            .echantillonneur(vf)
            .creer(dev, "maillage ciel bgl");
        let bgl_image = MiseEnPage::new()
            .uniforme(vf)
            .uniforme(f)
            .texture(f)
            .uniforme(vf)
            .creer(dev, "maillage image bgl");
        let uniforme_image = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("maillage image uniforme"),
            size: size_of::<MeshFrame>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let uniforme_lumiere = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("maillage lumière uniforme"),
            size: size_of::<LightUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let uniforme_style = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("maillage style uniforme"),
            size: size_of::<StyleUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        g.queue()
            .write_buffer(&uniforme_style, 0, bytemuck::bytes_of(&self.style.uniform()));
        let ech = echantillonneur_lineaire(dev);
        let entree = |binding: u32, resource| wgpu::BindGroupEntry { binding, resource };
        let groupe_ciel = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("maillage ciel groupe"),
            layout: &bgl_ciel,
            entries: &[
                entree(0, frame_ciel.as_entire_binding()),
                entree(1, wgpu::BindingResource::TextureView(&trans)),
                entree(2, wgpu::BindingResource::TextureView(&vue_ciel)),
                entree(3, wgpu::BindingResource::Sampler(&ech)),
            ],
        });
        let groupe_image = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("maillage image groupe"),
            layout: &bgl_image,
            entries: &[
                entree(0, uniforme_image.as_entire_binding()),
                entree(1, uniforme_lumiere.as_entire_binding()),
                entree(2, wgpu::BindingResource::TextureView(&ambiance)),
                entree(3, uniforme_style.as_entire_binding()),
            ],
        });
        // Ombres : celles de `MeshShadowPass` si elle précède, sinon un uniforme « inactif » et une profondeur factice.
        let (uniforme_ombres, vue_ombres) = match (
            res.buffer(noms_ombres::UNIFORME).cloned(),
            res.texture(noms_ombres::CASCADES).map(|t| {
                t.create_view(&wgpu::TextureViewDescriptor {
                    dimension: Some(wgpu::TextureViewDimension::D2Array),
                    aspect: wgpu::TextureAspect::DepthOnly,
                    ..Default::default()
                })
            }),
        ) {
            (Some(u), Some(v)) => (u, v),
            _ => {
                let u = dev.create_buffer(&wgpu::BufferDescriptor {
                    label: Some("maillage ombres uniforme factice"),
                    size: size_of::<ShadowUniform>() as u64,
                    usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                });
                g.queue()
                    .write_buffer(&u, 0, bytemuck::bytes_of(&ShadowUniform::default()));
                let t = dev.create_texture(&wgpu::TextureDescriptor {
                    label: Some("maillage ombres factice"),
                    size: wgpu::Extent3d {
                        width: 1,
                        height: 1,
                        depth_or_array_layers: 2,
                    },
                    mip_level_count: 1,
                    sample_count: 1,
                    dimension: wgpu::TextureDimension::D2,
                    format: wgpu::TextureFormat::Depth32Float,
                    usage: wgpu::TextureUsages::TEXTURE_BINDING,
                    view_formats: &[],
                });
                let v = t.create_view(&wgpu::TextureViewDescriptor {
                    dimension: Some(wgpu::TextureViewDimension::D2Array),
                    aspect: wgpu::TextureAspect::DepthOnly,
                    ..Default::default()
                });
                (u, v)
            }
        };
        let bgl_ombres = dev.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("maillage ombres bgl"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: f,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: f,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Depth,
                        view_dimension: wgpu::TextureViewDimension::D2Array,
                        multisampled: false,
                    },
                    count: None,
                },
            ],
        });
        let groupe_ombres = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("maillage ombres groupe"),
            layout: &bgl_ombres,
            entries: &[
                entree(0, uniforme_ombres.as_entire_binding()),
                entree(1, wgpu::BindingResource::TextureView(&vue_ombres)),
            ],
        });
        // Profondeur propre au rendu par maillage.
        let tex_profondeur = dev.create_texture(&wgpu::TextureDescriptor {
            label: Some("maillage profondeur"),
            size: wgpu::Extent3d {
                width: setup.size.0,
                height: setup.size.1,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: FORMAT_PROFONDEUR,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                | wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let profondeur = tex_profondeur.create_view(&wgpu::TextureViewDescriptor::default());
        res.insert_texture(noms::PROFONDEUR, tex_profondeur);

        let module = shaders::principal();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout_chunks = self.monde.lock().layout().clone();
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("maillage rendu layout"),
            bind_group_layouts: &[
                Some(&bgl_ciel),
                Some(&bgl_image),
                Some(&bgl_ombres),
                Some(&layout_chunks),
            ],
            immediate_size: 0,
        });
        let pipeline = dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("maillage rendu"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format: HDR_FORMAT,
                    blend: Some(blend_fondu()),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleStrip,
                front_face: wgpu::FrontFace::Cw,
                cull_mode: Some(wgpu::Face::Back),
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: FORMAT_PROFONDEUR,
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
            groupe_ciel,
            groupe_image,
            groupe_ombres,
            uniforme_image,
            uniforme_lumiere,
            hdr,
            profondeur,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let Some(cam) = ctx.frame().voxel_camera().copied() else {
            log::error!("maillage_rendu : le contexte d'image n'a pas de caméra voxel");
            return;
        };
        let aspect = ctx.frame().aspect();
        let vp = cam.view_proj_lh(aspect);
        let (l, h) = (ctx.frame().width() as f32, ctx.frame().height() as f32);
        let image = MeshFrame {
            view_proj: vp.to_cols_array(),
            screen: [l, h, 1.0 / l, 1.0 / h],
        };
        let (r, _) = self.reglages.lire();
        let f = r.foliage();
        let (zone_m, cuit) = {
            let m = self.monde.lock();
            (m.foliage_zone_m(), m.foliage_baked())
        };
        let active = if cuit { 1.0 } else { 0.0 };
        let u = LightUniform {
            vue: [
                r.view().code_public(),
                r.ambient(),
                active,
                zone_m.unwrap_or(f.zone_m()),
            ],
            feuillage_a: [f.translucency(), f.absorption_m(), f.forward(), f.rim()],
            feuillage_b: [f.tint()[0], f.tint()[1], f.tint()[2], f.rim_thickness_m()],
            feuillage_c: [
                f.saturation(),
                f.shadow_lift(),
                0.0,
                if self.occlusion { 0.0 } else { 1.0 },
            ],
            feuillage_d: [f.shadow_tint()[0], f.shadow_tint()[1], f.shadow_tint()[2], 0.0],
        };
        let q = ctx.gpu().queue();
        q.write_buffer(&gpu.uniforme_image, 0, bytemuck::bytes_of(&image));
        q.write_buffer(&gpu.uniforme_lumiere, 0, bytemuck::bytes_of(&u));
        let mut monde = self.monde.lock();
        monde.begin_frame(ctx.gpu().queue(), ctx.frame().index(), cam.pos_mm());
        let cone = Frustum::from_view_proj(vp);
        let liste = monde.visible_in(&cone);
        let mut pass = ctx.render_pass_color_depth("maillage rendu", &gpu.hdr, &gpu.profondeur);
        let Some(groupe_chunks) = monde.group() else {
            return;
        };
        pass.set_pipeline(&gpu.pipeline);
        pass.set_bind_group(0, &gpu.groupe_ciel, &[]);
        pass.set_bind_group(1, &gpu.groupe_image, &[]);
        pass.set_bind_group(2, &gpu.groupe_ombres, &[]);
        for d in &liste {
            pass.set_bind_group(3, groupe_chunks, &[d.offset()]);
            pass.draw(0..4, d.instances());
        }
    }
}
