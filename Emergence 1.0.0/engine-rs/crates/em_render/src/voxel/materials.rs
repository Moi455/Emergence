//! Tampons de matières côté GPU (docs/19a § 5.3) : le paquet de `em_material` (matières, rampes de classe,
//! rampes d'essence, graines d'essence) plus les deux tampons ajoutés par L09 (graines et rôles de classe,
//! nombre de rampes par essence). `GpuMaterials` POSSÈDE les tampons ; les passes reçoivent des liaisons.

use crate::gpu::GpuContext;
use crate::liaisons::{MiseEnPage, entree_tampon};
use em_material::{GpuMaterialPacket, MaterialTable, VegetationRamps};
use wgpu::ShaderStages as Etage;

/// Liaisons des matières pour une passe (copie bon marché).
#[derive(Clone)]
pub struct MaterialBindings {
    layout: wgpu::BindGroupLayout,
    group: wgpu::BindGroup,
}

impl MaterialBindings {
    /// Mise en page (groupe 1 de la passe de matière).
    pub fn layout(&self) -> &wgpu::BindGroupLayout {
        &self.layout
    }

    /// Groupe de liaisons.
    pub fn group(&self) -> &wgpu::BindGroup {
        &self.group
    }
}

/// Les tampons de matières sur le GPU.
pub struct GpuMaterials {
    materials: wgpu::Buffer,
    class_ramps: wgpu::Buffer,
    veg_ramps: wgpu::Buffer,
    veg_seeds: wgpu::Buffer,
    class_extra: wgpu::Buffer,
    veg_counts: wgpu::Buffer,
    liaisons: MaterialBindings,
    empreinte: u64,
}

impl GpuMaterials {
    /// Construit et téléverse les tampons depuis la table et les rampes de la saison courante.
    pub fn new(gpu: &GpuContext, table: &MaterialTable, veg: &VegetationRamps) -> Self {
        let paquet = GpuMaterialPacket::new(table, veg);
        let dev = gpu.device();
        let cree = |nom: &str, octets: &[u8]| {
            let b = dev.create_buffer(&wgpu::BufferDescriptor {
                label: Some(nom),
                size: (octets.len() as u64).max(16),
                usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            gpu.queue().write_buffer(&b, 0, octets);
            b
        };
        let extra = table.gpu_class_extra();
        let counts = veg.gpu_counts();
        let materials = cree("matières", paquet.material_bytes());
        let class_ramps = cree("rampes de classe", paquet.class_ramp_bytes());
        let veg_ramps = cree("rampes d'essence", paquet.veg_ramp_bytes());
        let veg_seeds = cree("graines d'essence", paquet.veg_seed_bytes());
        let class_extra = cree("graines et rôles de classe", bytemuck::cast_slice(&extra));
        let veg_counts = cree("rampes par essence", bytemuck::cast_slice(&counts));
        let c = Etage::COMPUTE;
        let layout = MiseEnPage::new()
            .stockage_tampon_lecture(c)
            .stockage_tampon_lecture(c)
            .stockage_tampon_lecture(c)
            .stockage_tampon_lecture(c)
            .stockage_tampon_lecture(c)
            .stockage_tampon_lecture(c)
            .creer(dev, "matières bgl");
        let group = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("matières groupe"),
            layout: &layout,
            entries: &[
                entree_tampon(0, &materials),
                entree_tampon(1, &class_ramps),
                entree_tampon(2, &veg_ramps),
                entree_tampon(3, &veg_seeds),
                entree_tampon(4, &class_extra),
                entree_tampon(5, &veg_counts),
            ],
        });
        Self {
            materials,
            class_ramps,
            veg_ramps,
            veg_seeds,
            class_extra,
            veg_counts,
            liaisons: MaterialBindings { layout, group },
            empreinte: paquet.fingerprint(),
        }
    }

    /// Réécrit les rampes de végétation (changement de saison) : la mise en page ne change pas.
    pub fn set_vegetation(&mut self, gpu: &GpuContext, table: &MaterialTable, veg: &VegetationRamps) {
        let paquet = GpuMaterialPacket::new(table, veg);
        let q = gpu.queue();
        q.write_buffer(&self.veg_ramps, 0, paquet.veg_ramp_bytes());
        q.write_buffer(&self.veg_seeds, 0, paquet.veg_seed_bytes());
        q.write_buffer(&self.veg_counts, 0, bytemuck::cast_slice(&veg.gpu_counts()));
        q.write_buffer(&self.materials, 0, paquet.material_bytes());
        q.write_buffer(&self.class_ramps, 0, paquet.class_ramp_bytes());
        q.write_buffer(
            &self.class_extra,
            0,
            bytemuck::cast_slice(&table.gpu_class_extra()),
        );
        self.empreinte = paquet.fingerprint();
    }

    /// Liaisons à confier à la passe de matière.
    pub fn bindings(&self) -> MaterialBindings {
        self.liaisons.clone()
    }

    /// Empreinte du paquet téléversé (celle de `em_material`).
    pub fn fingerprint(&self) -> u64 {
        self.empreinte
    }
}
