//! `FoliageThicknessPass` : épaisseur de feuillage le long du soleil, par pixel (docs/19 § 5.4, translucidité).
//!
//! Pour chaque pixel dont le voxel touché est du feuillage (drapeau `foliage` de la matière), on part du CENTRE du voxel
//! touché (toute sa face reçoit la même épaisseur : aplat net) et on suit le soleil de voxel en voxel (DDA d'Amanatides et Woo, borné à la zone de `FoliageLightParams`) en
//! cumulant la longueur parcourue dans des voxels de feuillage. Un solide qui n'est pas du feuillage (tronc, pierre)
//! sur le trajet barre le soleil : le pixel reçoit le code « occulté » ([`FoliageLightParams::BLOQUE_M`]). Au-delà de
//! la zone, c'est l'ombre en cascades de L11 qui juge (lue par l'éclairage).

use super::params::FoliageLightParams;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::{MiseEnPage, entree_tampon, entree_vue};
use crate::partage::Partage;
use crate::sky::noms as noms_ciel;
use crate::voxel::gbuffer::noms as noms_gb;
use crate::voxel::light::LightSettings;
use crate::voxel::materials::MaterialBindings;
use crate::voxel::shaders;
use crate::voxel::world::WorldBindings;
use wgpu::ShaderStages as Etage;

/// Ressources que la passe publie dans le graphe.
pub mod noms {
    use crate::graph::ResourceName;

    /// Épaisseur de feuillage le long du soleil, en mètres (`R32Float`) : 0 hors feuillage, 1000 si le soleil est barré.
    pub const EPAISSEUR: ResourceName = ResourceName::new("feuillage_epaisseur");
}

/// Format de l'épaisseur.
pub const FORMAT_EPAISSEUR: wgpu::TextureFormat = wgpu::TextureFormat::R32Float;

struct Gpu {
    pipeline: wgpu::ComputePipeline,
    groupe: wgpu::BindGroup,
    zone: wgpu::Buffer,
}

/// Passe d'épaisseur du feuillage (compute).
pub struct FoliageThicknessPass {
    reglages: Partage<LightSettings>,
    monde: WorldBindings,
    matieres: MaterialBindings,
    gpu: Option<Gpu>,
}

impl FoliageThicknessPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("voxel_epaisseur");

    /// Crée la passe sur les réglages partagés de l'éclairage, les liaisons du monde et celles des matières.
    pub fn new(reglages: Partage<LightSettings>, monde: WorldBindings, matieres: MaterialBindings) -> Self {
        Self {
            reglages,
            monde,
            matieres,
            gpu: None,
        }
    }
}

impl RenderPass for FoliageThicknessPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let (Some(frame_ciel), Some(vf), Some(hit)) = (
            res.buffer(noms_ciel::FRAME).cloned(),
            res.buffer(noms_gb::FRAME).cloned(),
            res.view(noms_gb::HIT),
        ) else {
            log::error!(
                "voxel_epaisseur : le ciel ou le G-buffer manquent (SkyPass et tracé doivent précéder)"
            );
            return;
        };
        let dev = g.device();
        let epaisseur = dev.create_texture(&wgpu::TextureDescriptor {
            label: Some("feuillage épaisseur"),
            size: wgpu::Extent3d {
                width: setup.size.0,
                height: setup.size.1,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: FORMAT_EPAISSEUR,
            usage: wgpu::TextureUsages::STORAGE_BINDING
                | wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let vue = epaisseur.create_view(&wgpu::TextureViewDescriptor::default());
        res.insert_texture(noms::EPAISSEUR, epaisseur);
        let zone = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("feuillage zone"),
            size: 16,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let c = Etage::COMPUTE;
        let bgl = MiseEnPage::new()
            .uniforme(c)
            .uniforme(c)
            .texture_uint(c)
            .uniforme(c)
            .stockage_ecriture(c, FORMAT_EPAISSEUR)
            .creer(dev, "feuillage épaisseur bgl");
        let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("feuillage épaisseur groupe"),
            layout: &bgl,
            entries: &[
                entree_tampon(0, &frame_ciel),
                entree_tampon(1, &vf),
                entree_vue(2, &hit),
                entree_tampon(3, &zone),
                entree_vue(4, &vue),
            ],
        });
        let module = shaders::epaisseur();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("feuillage épaisseur layout"),
            bind_group_layouts: &[
                Some(&bgl),
                Some(self.monde.layout()),
                Some(self.matieres.layout()),
            ],
            immediate_size: 0,
        });
        let pipeline = dev.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("feuillage épaisseur"),
            layout: Some(&layout),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        self.gpu = Some(Gpu {
            pipeline,
            groupe,
            zone,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let (r, _) = self.reglages.lire();
        let zone: [f32; 4] = [
            r.foliage().zone_voxels() as f32,
            FoliageLightParams::BLOQUE_M,
            r.foliage().cutoff_voxels(),
            0.0,
        ];
        ctx.gpu()
            .queue()
            .write_buffer(&gpu.zone, 0, bytemuck::bytes_of(&zone));
        let (l, h) = (ctx.frame().width(), ctx.frame().height());
        let mut pass = ctx.compute_pass("feuillage épaisseur");
        pass.set_pipeline(&gpu.pipeline);
        pass.set_bind_group(0, &gpu.groupe, &[]);
        pass.set_bind_group(1, self.monde.group(), &[]);
        pass.set_bind_group(2, self.matieres.group(), &[]);
        pass.dispatch_workgroups(l.div_ceil(8), h.div_ceil(8), 1);
    }
}
