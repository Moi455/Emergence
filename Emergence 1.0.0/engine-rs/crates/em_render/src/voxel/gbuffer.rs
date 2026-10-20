//! Ressources du G-buffer voxel (docs/19a § 5.2) : noms dans le graphe et création. Les formats sont ceux que le
//! compute ET le raster peuvent écrire (pas de sRGB matériel : l'encodage est fait à la main).

use crate::graph::{ResourceName, Resources};
use wgpu::TextureFormat as F;

/// Noms des ressources que le rendu voxel publie dans le graphe.
pub mod noms {
    use crate::graph::ResourceName;

    /// Uniforme d'image du rendu voxel (`VoxelFrame`), réécrit par la passe de tracé à chaque image.
    pub const FRAME: ResourceName = ResourceName::new("voxel_frame");
    /// Impact brut du tracé (`Rgba32Uint`) : valeur, face, drapeau, voxel touché.
    pub const HIT: ResourceName = ResourceName::new("voxel_hit");
    /// Distance du tracé en mètres (`R32Float`), 1e30 s'il n'y a rien.
    pub const DIST: ResourceName = ResourceName::new("voxel_dist");
    /// GB0 `Rgba8Unorm` : albédo sRGB, occlusion de matière.
    pub const GB0: ResourceName = ResourceName::new("gb0");
    /// GB1 `R32Uint` : normale octaédrique 2 × 16 bits.
    pub const GB1: ResourceName = ResourceName::new("gb1");
    /// GB2 `Rgba8Unorm` : rugosité, translucidité, émission, drapeaux.
    pub const GB2: ResourceName = ResourceName::new("gb2");
    /// Profondeur `Depth32Float`, Z inversé infini, effacée à 0.
    pub const PROFONDEUR: ResourceName = ResourceName::new("profondeur");
}

/// Format de l'impact brut.
pub const FORMAT_HIT: F = F::Rgba32Uint;
/// Format de la distance.
pub const FORMAT_DIST: F = F::R32Float;
/// Format de GB0.
pub const FORMAT_GB0: F = F::Rgba8Unorm;
/// Format de GB1.
pub const FORMAT_GB1: F = F::R32Uint;
/// Format de GB2.
pub const FORMAT_GB2: F = F::Rgba8Unorm;
/// Format de la profondeur.
pub const FORMAT_PROFONDEUR: F = F::Depth32Float;

fn texture(
    dev: &wgpu::Device,
    nom: &str,
    taille: (u32, u32),
    format: F,
    usage: wgpu::TextureUsages,
) -> wgpu::Texture {
    dev.create_texture(&wgpu::TextureDescriptor {
        label: Some(nom),
        size: wgpu::Extent3d {
            width: taille.0,
            height: taille.1,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage,
        view_formats: &[],
    })
}

/// Crée (ou recrée à un changement de taille) toutes les textures du G-buffer et l'uniforme d'image.
pub(crate) fn creer(dev: &wgpu::Device, taille: (u32, u32), res: &mut Resources) {
    use wgpu::TextureUsages as U;
    let ecriture_lecture = U::STORAGE_BINDING | U::TEXTURE_BINDING | U::COPY_SRC;
    let inserer = |res: &mut Resources, nom: ResourceName, format: F, usage: U| {
        res.insert_texture(nom, texture(dev, nom.as_str(), taille, format, usage));
    };
    inserer(res, noms::HIT, FORMAT_HIT, ecriture_lecture);
    inserer(res, noms::DIST, FORMAT_DIST, ecriture_lecture);
    inserer(res, noms::GB0, FORMAT_GB0, ecriture_lecture);
    inserer(res, noms::GB1, FORMAT_GB1, ecriture_lecture);
    inserer(res, noms::GB2, FORMAT_GB2, ecriture_lecture);
    inserer(
        res,
        noms::PROFONDEUR,
        FORMAT_PROFONDEUR,
        U::RENDER_ATTACHMENT | U::TEXTURE_BINDING | U::COPY_SRC,
    );
    res.insert_buffer(
        noms::FRAME,
        dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("voxel frame"),
            size: size_of::<super::gpu::VoxelFrame>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        }),
    );
}
