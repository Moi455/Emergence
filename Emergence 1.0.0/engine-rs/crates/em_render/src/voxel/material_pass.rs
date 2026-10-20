//! `VoxelMaterialPass` : évalue la couleur du voxel touché EN COORDONNÉES MONDE avec le paquet de matières et écrit
//! le G-buffer (docs/19 § 4.6). Aucun biseau, aucune coordonnée locale au voxel : un tronc paraît UN seul bois.

use super::gbuffer::{self, noms};
use super::materials::MaterialBindings;
use super::shaders;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::{MiseEnPage, entree_vue};
use wgpu::ShaderStages as Etage;

struct Gpu {
    pipeline: wgpu::ComputePipeline,
    groupe: wgpu::BindGroup,
}

/// Passe de matière (compute).
pub struct VoxelMaterialPass {
    matieres: MaterialBindings,
    gpu: Option<Gpu>,
}

impl VoxelMaterialPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("voxel_matiere");

    /// Crée la passe sur les liaisons des matières.
    pub fn new(matieres: MaterialBindings) -> Self {
        Self { matieres, gpu: None }
    }
}

impl RenderPass for VoxelMaterialPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, _setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let (Some(frame), Some(hit), Some(gb0), Some(gb1), Some(gb2)) = (
            res.buffer(noms::FRAME).cloned(),
            res.view(noms::HIT),
            res.view(noms::GB0),
            res.view(noms::GB1),
            res.view(noms::GB2),
        ) else {
            log::error!("voxel_matiere : le G-buffer manque (VoxelTracePass doit précéder cette passe)");
            return;
        };
        let dev = g.device();
        let c = Etage::COMPUTE;
        let bgl = MiseEnPage::new()
            .uniforme(c)
            .texture_uint(c)
            .stockage_ecriture(c, gbuffer::FORMAT_GB0)
            .stockage_ecriture(c, gbuffer::FORMAT_GB1)
            .stockage_ecriture(c, gbuffer::FORMAT_GB2)
            .creer(dev, "voxel matière bgl");
        let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("voxel matière groupe"),
            layout: &bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: frame.as_entire_binding(),
                },
                entree_vue(1, &hit),
                entree_vue(2, &gb0),
                entree_vue(3, &gb1),
                entree_vue(4, &gb2),
            ],
        });
        let module = shaders::matiere();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("voxel matière layout"),
            bind_group_layouts: &[Some(&bgl), Some(self.matieres.layout())],
            immediate_size: 0,
        });
        let pipeline = dev.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("voxel matière"),
            layout: Some(&layout),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        self.gpu = Some(Gpu { pipeline, groupe });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let (l, h) = (ctx.frame().width(), ctx.frame().height());
        let mut pass = ctx.compute_pass("voxel matière");
        pass.set_pipeline(&gpu.pipeline);
        pass.set_bind_group(0, &gpu.groupe, &[]);
        pass.set_bind_group(1, self.matieres.group(), &[]);
        pass.dispatch_workgroups(l.div_ceil(8), h.div_ceil(8), 1);
    }
}
