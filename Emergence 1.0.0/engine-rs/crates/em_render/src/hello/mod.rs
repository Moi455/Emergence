//! Scène « hello » : ciel de test (dégradé, pas encore Hillaire) et surimpression de texte.
//! Elle exerce tout l'hôte : deux passes, profil par passe, cible hors écran ou fenêtre.

pub mod font;

use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use font::TexteRaster;
use std::sync::{Arc, Mutex};
use wgpu::util::DeviceExt;

/// Dispositions GPU de la scène (uniformes), rangées à part.
mod gpu {
    use bytemuck::{Pod, Zeroable};

    /// Uniformes du ciel : base de la caméra, paramètres, direction du soleil.
    #[repr(C)]
    #[derive(Clone, Copy, Pod, Zeroable)]
    pub struct CielUniformes {
        pub droite: [f32; 4],
        pub haut: [f32; 4],
        pub avant: [f32; 4],
        pub params: [f32; 4],
        pub soleil: [f32; 4],
    }

    /// Rectangle de la surimpression en coordonnées normalisées.
    #[repr(C)]
    #[derive(Clone, Copy, Pod, Zeroable)]
    pub struct RectUniforme {
        pub rect: [f32; 4],
    }
}

/// Ciel de test : un triangle plein écran qui colore selon la direction du regard.
pub struct SkyGradientPass {
    pipeline: Option<wgpu::RenderPipeline>,
    uniformes: Option<wgpu::Buffer>,
    groupe: Option<wgpu::BindGroup>,
}

impl SkyGradientPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("ciel_degrade");

    /// Passe non préparée (le graphe appelle `prepare`).
    pub fn new() -> Self {
        Self {
            pipeline: None,
            uniformes: None,
            groupe: None,
        }
    }
}

impl Default for SkyGradientPass {
    fn default() -> Self {
        Self::new()
    }
}

impl RenderPass for SkyGradientPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, setup: &PassSetup, _res: &mut Resources) {
        let dev = g.device();
        let module = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("hello_ciel"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../../shaders/hello_ciel.wgsl").into()),
        });
        let buf = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("ciel uniformes"),
            size: std::mem::size_of::<gpu::CielUniformes>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let bgl = dev.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("ciel bgl"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        });
        let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("ciel groupe"),
            layout: &bgl,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: buf.as_entire_binding(),
            }],
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("ciel layout"),
            bind_group_layouts: &[Some(&bgl)],
            immediate_size: 0,
        });
        self.pipeline = Some(dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("ciel"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &module,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            fragment: Some(wgpu::FragmentState {
                module: &module,
                entry_point: Some("fs"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format: setup.format,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview_mask: None,
            cache: None,
        }));
        self.uniformes = Some(buf);
        self.groupe = Some(groupe);
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let (Some(pipeline), Some(buf), Some(groupe)) = (&self.pipeline, &self.uniformes, &self.groupe)
        else {
            return;
        };
        let f = ctx.frame();
        let vue = f.view();
        let (d, h, a) = (vue.right(), vue.up(), vue.forward());
        let u = gpu::CielUniformes {
            droite: [d.x, d.y, d.z, 0.0],
            haut: [h.x, h.y, h.z, 0.0],
            avant: [a.x, a.y, a.z, 0.0],
            params: [
                (vue.fov_y_deg().to_radians() * 0.5).tan(),
                f.aspect(),
                f.time_s(),
                0.0,
            ],
            soleil: [0.45, 0.28, -0.85, 0.0],
        };
        ctx.gpu().queue().write_buffer(buf, 0, bytemuck::bytes_of(&u));
        let mut pass = ctx.render_pass("ciel", wgpu::LoadOp::Clear(wgpu::Color::BLACK));
        pass.set_pipeline(pipeline);
        pass.set_bind_group(0, groupe, &[]);
        pass.draw(0..3, 0..1);
    }
}

/// Texte de la surimpression, partagé entre la scène (qui le change) et la passe (qui le dessine).
#[derive(Clone, Default)]
pub struct OverlayText {
    lignes: Arc<Mutex<Vec<String>>>,
}

impl OverlayText {
    /// Texte vide.
    pub fn new() -> Self {
        Self::default()
    }

    /// Remplace les lignes affichées.
    pub fn set_lines(&self, lignes: Vec<String>) {
        // Un verrou empoisonné ne peut venir que d'une panique ailleurs ; le texte reste utilisable.
        *self.lignes.lock().unwrap_or_else(|e| e.into_inner()) = lignes;
    }

    fn copie(&self) -> Vec<String> {
        self.lignes.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }
}

/// Surimpression de texte 8 x 8 agrandie, dessinée par-dessus la cible.
pub struct TextOverlayPass {
    texte: OverlayText,
    colonnes: u32,
    rangees: u32,
    echelle: u32,
    derniere: Vec<String>,
    pipeline: Option<wgpu::RenderPipeline>,
    texture: Option<wgpu::Texture>,
    rect: Option<wgpu::Buffer>,
    groupe: Option<wgpu::BindGroup>,
}

impl TextOverlayPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("surimpression_texte");

    /// Crée la passe sur un texte partagé ; `colonnes` et `rangees` comptent des caractères, `echelle` ≥ 1.
    pub fn new(texte: OverlayText, colonnes: u32, rangees: u32, echelle: u32) -> Self {
        assert!(
            colonnes >= 1 && rangees >= 1 && echelle >= 1,
            "surimpression : dimensions nulles"
        );
        Self {
            texte,
            colonnes,
            rangees,
            echelle,
            derniere: vec![String::from("\u{0}")],
            pipeline: None,
            texture: None,
            rect: None,
            groupe: None,
        }
    }
}

impl RenderPass for TextOverlayPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, setup: &PassSetup, _res: &mut Resources) {
        let dev = g.device();
        let module = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("hello_texte"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../../shaders/hello_texte.wgsl").into()),
        });
        let (w, h) = (self.colonnes * 8, self.rangees * font::TexteRaster::PAS_LIGNE);
        let texture = dev.create_texture(&wgpu::TextureDescriptor {
            label: Some("texte"),
            size: wgpu::Extent3d {
                width: w,
                height: h,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::R8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let (sw, sh) = (setup.size.0 as f32, setup.size.1 as f32);
        let marge = 16.0;
        let (px_w, px_h) = ((w * self.echelle) as f32, (h * self.echelle) as f32);
        let r = gpu::RectUniforme {
            rect: [
                marge / sw * 2.0 - 1.0,
                1.0 - (marge + px_h) / sh * 2.0,
                (marge + px_w) / sw * 2.0 - 1.0,
                1.0 - marge / sh * 2.0,
            ],
        };
        let rect = dev.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("texte rect"),
            contents: bytemuck::bytes_of(&r),
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let echant = dev.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("texte échantillonneur"),
            mag_filter: wgpu::FilterMode::Nearest,
            min_filter: wgpu::FilterMode::Nearest,
            ..Default::default()
        });
        let bgl = dev.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("texte bgl"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
            ],
        });
        let vue = texture.create_view(&wgpu::TextureViewDescriptor::default());
        let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("texte groupe"),
            layout: &bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: rect.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&vue),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::Sampler(&echant),
                },
            ],
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("texte layout"),
            bind_group_layouts: &[Some(&bgl)],
            immediate_size: 0,
        });
        self.pipeline = Some(dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("texte"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &module,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            fragment: Some(wgpu::FragmentState {
                module: &module,
                entry_point: Some("fs"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format: setup.format,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleStrip,
                ..Default::default()
            },
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview_mask: None,
            cache: None,
        }));
        self.texture = Some(texture);
        self.rect = Some(rect);
        self.groupe = Some(groupe);
        // Force le renvoi du texte dans la nouvelle texture.
        self.derniere = vec![String::from("\u{0}")];
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let (Some(pipeline), Some(texture), Some(groupe)) = (&self.pipeline, &self.texture, &self.groupe)
        else {
            return;
        };
        let lignes = self.texte.copie();
        if lignes != self.derniere {
            let raster = TexteRaster::new(&lignes, self.colonnes, self.rangees);
            ctx.gpu().queue().write_texture(
                texture.as_image_copy(),
                raster.octets(),
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(raster.largeur()),
                    rows_per_image: Some(raster.hauteur()),
                },
                wgpu::Extent3d {
                    width: raster.largeur(),
                    height: raster.hauteur(),
                    depth_or_array_layers: 1,
                },
            );
            self.derniere = lignes;
        }
        let mut pass = ctx.render_pass("texte", wgpu::LoadOp::Load);
        pass.set_pipeline(pipeline);
        pass.set_bind_group(0, groupe, &[]);
        pass.draw(0..4, 0..1);
    }
}
