//! `LightingPass` : soleil lambertien (couleur de la transmittance de l'atmosphère de Hillaire, ombres en cascades de
//! L11 si `ShadowCascades` précède), ambiance de l'hémisphère du ciel, translucidité et liseré du feuillage (L10 étendue,
//! épaisseur de `FoliageThicknessPass` si elle précède), occlusion ambiante de `AmbientOcclusionPass` (L14) si elle précède (elle n'assombrit que l'ambiance, jamais le soleil), sans indirect (L15). Écrit dans la cible
//! HDR du fond de ciel, là où le tracé a touché un voxel.

use super::ao::noms as noms_ao;
use super::foliage::{FoliageLightParams, noms as noms_feuillage};
use super::gbuffer::{self, noms};
use super::gpu::{LightUniform, ShadowUniform, VoxelFrame};
use super::shaders;
use super::shadow::noms as ombres;
use crate::error::ParamError;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::{HDR_FORMAT, MiseEnPage, echantillonneur_lineaire};
use crate::partage::Partage;
use crate::sky::noms as noms_ciel;
use wgpu::ShaderStages as Etage;

/// Vue affichée par la passe d'éclairage (débogage et captures de contrôle).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum DebugView {
    /// Image éclairée.
    #[default]
    Beauty,
    /// Albédo seul (sans lumière).
    Albedo,
    /// Normales de face (couleur = normale × 0,5 + 0,5).
    Normals,
    /// Distance en niveaux de gris (blanc à 40 m).
    Distance,
    /// Masque : blanc là où le tracé a touché un voxel (silhouette) ; lancer avec `--bloom 0` pour un bord net.
    Mask,
    /// Visibilité du soleil seule (blanc = éclairé, noir = dans l'ombre) sur les surfaces tournées vers lui.
    Shadow,
    /// Cascade d'ombre qui sert chaque pixel (teinte par cascade ; gris : aucune).
    Cascades,
    /// Visibilité de l'ambiance (occlusion ambiante de L14) en niveaux de gris : blanc libre, noir enfermé.
    Occlusion,
}

impl DebugView {
    fn code(self) -> f32 {
        match self {
            Self::Beauty => 0.0,
            Self::Albedo => 1.0,
            Self::Normals => 2.0,
            Self::Distance => 3.0,
            Self::Mask => 4.0,
            Self::Shadow => 5.0,
            Self::Cascades => 6.0,
            Self::Occlusion => 7.0,
        }
    }

    /// Lit un nom de vue de la ligne de commande.
    pub fn from_name(nom: &str) -> Option<Self> {
        Some(match nom {
            "image" | "beauty" => Self::Beauty,
            "albedo" => Self::Albedo,
            "normales" | "normals" => Self::Normals,
            "distance" => Self::Distance,
            "masque" | "mask" => Self::Mask,
            "ombre" | "ombres" | "shadow" => Self::Shadow,
            "cascades" => Self::Cascades,
            "ao" | "occlusion" => Self::Occlusion,
            _ => return None,
        })
    }
}

/// Réglages de l'éclairage, validés à la construction.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct LightSettings {
    view: DebugView,
    ambient: f32,
    foliage: FoliageLightParams,
}

impl LightSettings {
    /// `ambient` : échelle de la lumière du ciel, dans [0, 4] (1 = physique).
    pub fn new(view: DebugView, ambient: f32) -> Result<Self, ParamError> {
        if !(ambient.is_finite() && (0.0..=4.0).contains(&ambient)) {
            return Err(ParamError::Invalide(format!(
                "ambiance = {ambient} hors de [0, 4]"
            )));
        }
        Ok(Self {
            view,
            ambient,
            foliage: FoliageLightParams::default(),
        })
    }

    /// Remplace les réglages de la lumière du feuillage.
    pub fn with_foliage(mut self, foliage: FoliageLightParams) -> Self {
        self.foliage = foliage;
        self
    }

    /// Réglages de la lumière du feuillage.
    pub fn foliage(&self) -> FoliageLightParams {
        self.foliage
    }

    /// Vue affichée.
    pub fn view(&self) -> DebugView {
        self.view
    }

    /// Échelle de la lumière du ciel.
    pub fn ambient(&self) -> f32 {
        self.ambient
    }
}

impl Default for LightSettings {
    fn default() -> Self {
        Self {
            view: DebugView::Beauty,
            ambient: 1.0,
            foliage: FoliageLightParams::default(),
        }
    }
}

struct Gpu {
    pipeline: wgpu::RenderPipeline,
    groupe_ciel: wgpu::BindGroup,
    groupe_gbuffer: wgpu::BindGroup,
    groupe_ombres: wgpu::BindGroup,
    uniforme: wgpu::Buffer,
    hdr: wgpu::TextureView,
    /// `true` si `FoliageThicknessPass` a publié l'épaisseur (sinon la translucidité est éteinte).
    epaisseur_active: bool,
    /// `true` si `AmbientOcclusionPass` a publié l'occlusion (sinon l'ambiance n'est pas assombrie).
    ao_active: bool,
}

/// Éclairage différé v0.
pub struct LightingPass {
    reglages: Partage<LightSettings>,
    gpu: Option<Gpu>,
}

impl LightingPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("voxel_lumiere");

    /// Crée la passe sur des réglages partagés avec la scène. Le soleil vient de la ressource `ciel_frame`.
    pub fn new(reglages: Partage<LightSettings>) -> Self {
        Self { reglages, gpu: None }
    }
}

impl RenderPass for LightingPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, _setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let (Some(frame_ciel), Some(vf), Some(trans), Some(vue_ciel), Some(hdr)) = (
            res.buffer(noms_ciel::FRAME).cloned(),
            res.buffer(noms::FRAME).cloned(),
            res.view(noms_ciel::TRANSMITTANCE),
            res.view(noms_ciel::VUE_DU_CIEL),
            res.view(noms_ciel::HDR),
        ) else {
            log::error!(
                "voxel_lumiere : le ciel ou le G-buffer manquent (SkyPass, fond de ciel et tracé doivent précéder)"
            );
            return;
        };
        let (Some(gb0), Some(gb1), Some(gb2), Some(dist)) = (
            res.view(noms::GB0),
            res.view(noms::GB1),
            res.view(noms::GB2),
            res.view(noms::DIST),
        ) else {
            return;
        };
        let dev = g.device();
        let f = Etage::FRAGMENT;
        // Le sommet lit aussi le ciel et l'uniforme : il précalcule l'ambiance des six faces d'un voxel.
        let vf_etage = Etage::VERTEX_FRAGMENT;
        let bgl_ciel = MiseEnPage::new()
            .uniforme(vf_etage)
            .texture(vf_etage)
            .texture(vf_etage)
            .echantillonneur(vf_etage)
            .creer(dev, "lumière ciel bgl");
        let bgl_gb = MiseEnPage::new()
            .uniforme(f)
            .uniforme(vf_etage)
            .texture(f)
            .texture_uint(f)
            .texture(f)
            .texture_float_brute(f)
            .texture_float_brute(f)
            .texture_float_brute(f)
            .creer(dev, "lumière gbuffer bgl");
        let uniforme = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("lumière uniforme"),
            size: size_of::<LightUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        // Épaisseur du feuillage : celle de `FoliageThicknessPass` si elle précède, sinon une texture factice et la
        // translucidité éteinte.
        let factice = |nom: &str| {
            let t = dev.create_texture(&wgpu::TextureDescriptor {
                label: Some(nom),
                size: wgpu::Extent3d {
                    width: 1,
                    height: 1,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::R32Float,
                usage: wgpu::TextureUsages::TEXTURE_BINDING,
                view_formats: &[],
            });
            t.create_view(&wgpu::TextureViewDescriptor::default())
        };
        let (vue_epaisseur, epaisseur_active) = match res.view(noms_feuillage::EPAISSEUR) {
            Some(v) => (v, true),
            None => (factice("épaisseur factice"), false),
        };
        // Occlusion ambiante : celle de `AmbientOcclusionPass` si elle précède, sinon une texture factice.
        let (vue_ao, ao_active) = match res.view(noms_ao::OCCLUSION) {
            Some(v) => (v, true),
            None => (factice("occlusion factice"), false),
        };
        let ech = echantillonneur_lineaire(dev);
        let entree = |binding: u32, resource| wgpu::BindGroupEntry { binding, resource };
        let groupe_ciel = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("lumière ciel groupe"),
            layout: &bgl_ciel,
            entries: &[
                entree(0, frame_ciel.as_entire_binding()),
                entree(1, wgpu::BindingResource::TextureView(&trans)),
                entree(2, wgpu::BindingResource::TextureView(&vue_ciel)),
                entree(3, wgpu::BindingResource::Sampler(&ech)),
            ],
        });
        let groupe_gbuffer = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("lumière gbuffer groupe"),
            layout: &bgl_gb,
            entries: &[
                entree(0, vf.as_entire_binding()),
                entree(1, uniforme.as_entire_binding()),
                entree(2, wgpu::BindingResource::TextureView(&gb0)),
                entree(3, wgpu::BindingResource::TextureView(&gb1)),
                entree(4, wgpu::BindingResource::TextureView(&gb2)),
                entree(5, wgpu::BindingResource::TextureView(&dist)),
                entree(6, wgpu::BindingResource::TextureView(&vue_epaisseur)),
                entree(7, wgpu::BindingResource::TextureView(&vue_ao)),
            ],
        });
        // Ombres : les cascades de `ShadowCascades` si la passe précède, sinon un uniforme « inactif » et une texture
        // factice (la lumière reste celle de L09, sans ombres).
        let (uniforme_ombres, vue_ombres) =
            match (res.buffer(ombres::UNIFORME).cloned(), res.view(ombres::CASCADES)) {
                (Some(u), Some(v)) => (u, v),
                _ => {
                    let u = dev.create_buffer(&wgpu::BufferDescriptor {
                        label: Some("ombres uniforme factice"),
                        size: size_of::<ShadowUniform>() as u64,
                        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                        mapped_at_creation: false,
                    });
                    g.queue()
                        .write_buffer(&u, 0, bytemuck::bytes_of(&ShadowUniform::default()));
                    let t = dev.create_texture(&wgpu::TextureDescriptor {
                        label: Some("ombres texture factice"),
                        size: wgpu::Extent3d {
                            width: 1,
                            height: 1,
                            depth_or_array_layers: 2,
                        },
                        mip_level_count: 1,
                        sample_count: 1,
                        dimension: wgpu::TextureDimension::D2,
                        format: wgpu::TextureFormat::R32Float,
                        usage: wgpu::TextureUsages::TEXTURE_BINDING,
                        view_formats: &[],
                    });
                    let v = t.create_view(&wgpu::TextureViewDescriptor {
                        dimension: Some(wgpu::TextureViewDimension::D2Array),
                        ..Default::default()
                    });
                    (u, v)
                }
            };
        let bgl_ombres = dev.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("lumière ombres bgl"),
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
                        sample_type: wgpu::TextureSampleType::Float { filterable: false },
                        view_dimension: wgpu::TextureViewDimension::D2Array,
                        multisampled: false,
                    },
                    count: None,
                },
            ],
        });
        let groupe_ombres = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("lumière ombres groupe"),
            layout: &bgl_ombres,
            entries: &[
                entree(0, uniforme_ombres.as_entire_binding()),
                entree(1, wgpu::BindingResource::TextureView(&vue_ombres)),
            ],
        });
        let module = shaders::lumiere();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("voxel lumière layout"),
            bind_group_layouts: &[Some(&bgl_ciel), Some(&bgl_gb), Some(&bgl_ombres)],
            immediate_size: 0,
        });
        let pipeline = dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("voxel lumière"),
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
                    // le fondu du sol au bord de la clipmap passe par la transparence de sortie
                    blend: Some(wgpu::BlendState {
                        color: wgpu::BlendComponent {
                            src_factor: wgpu::BlendFactor::SrcAlpha,
                            dst_factor: wgpu::BlendFactor::OneMinusSrcAlpha,
                            operation: wgpu::BlendOperation::Add,
                        },
                        alpha: wgpu::BlendComponent::REPLACE,
                    }),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview_mask: None,
            cache: None,
        });
        let _ = (gbuffer::FORMAT_GB0, size_of::<VoxelFrame>());
        self.gpu = Some(Gpu {
            pipeline,
            groupe_ciel,
            groupe_gbuffer,
            groupe_ombres,
            uniforme,
            hdr,
            epaisseur_active,
            ao_active,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let (r, _) = self.reglages.lire();
        let f = r.foliage();
        let active = if gpu.epaisseur_active { 1.0 } else { 0.0 };
        let ao = if gpu.ao_active { 1.0 } else { 0.0 };
        let u = LightUniform {
            vue: [r.view().code(), r.ambient(), active, f.zone_m()],
            feuillage_a: [f.translucency(), f.absorption_m(), f.forward(), f.rim()],
            feuillage_b: [f.tint()[0], f.tint()[1], f.tint()[2], f.rim_thickness_m()],
            feuillage_c: [f.saturation(), f.shadow_lift(), ao, 0.0],
            feuillage_d: [f.shadow_tint()[0], f.shadow_tint()[1], f.shadow_tint()[2], 0.0],
        };
        ctx.gpu()
            .queue()
            .write_buffer(&gpu.uniforme, 0, bytemuck::bytes_of(&u));
        let mut pass = ctx.render_pass_to("voxel lumière", &gpu.hdr, wgpu::LoadOp::Load);
        pass.set_pipeline(&gpu.pipeline);
        pass.set_bind_group(0, &gpu.groupe_ciel, &[]);
        pass.set_bind_group(1, &gpu.groupe_gbuffer, &[]);
        pass.set_bind_group(2, &gpu.groupe_ombres, &[]);
        pass.draw(0..3, 0..1);
    }
}
