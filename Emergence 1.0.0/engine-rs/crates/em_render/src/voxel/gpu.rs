//! Dispositions GPU `#[repr(C)]` du rendu voxel (docs/19a § 5.1 et § 5.4). Rangées ici et JAMAIS utilisées
//! comme état : les objets de rendu les remplissent juste avant l'écriture dans un tampon.

use bytemuck::{Pod, Zeroable};

/// Nombre maximal de niveaux de la clipmap.
pub const NIVEAUX_MAX: usize = 6;
/// Chunks par axe et par niveau (adressage torique `& 15`).
pub const CHUNKS_PAR_AXE: u32 = 16;
/// Entrées de la table de chunks d'un niveau (16³).
pub const ENTREES_PAR_NIVEAU: u32 = CHUNKS_PAR_AXE * CHUNKS_PAR_AXE * CHUNKS_PAR_AXE;
/// Mots de 32 bits d'un `ChunkGpu` : deux masques de 512 bits (16 mots chacun) + 512 entrées de brique.
pub const MOTS_PAR_CHUNK: u32 = 16 + 16 + 512;
/// Octets d'un `ChunkGpu` (2 176).
pub const OCTETS_PAR_CHUNK: u64 = MOTS_PAR_CHUNK as u64 * 4;

/// Entrée vide (chunk ou brique).
pub const ENTREE_VIDE: u32 = 0xFFFF_FFFF;
/// Bit « uniforme plein » d'une entrée de chunk ou de brique.
pub const BIT_UNIFORME: u32 = 1 << 31;
/// Bit « peau » (brique : terrain non édité ; chunk : contient des briques de peau).
pub const BIT_PEAU: u32 = 1 << 30;
/// Bit « édité » d'une brique.
pub const BIT_EDITE: u32 = 1 << 29;
/// Bit d'entrée de chunk : contient des briques de peau.
pub const BIT_CHUNK_PEAU: u32 = 1 << 24;
/// Bit d'entrée de chunk : contient des briques visibles (non peau).
pub const BIT_CHUNK_VISIBLE: u32 = 1 << 25;
/// Case de brique réservée (jamais attribuée).
pub const CASE_BRIQUE_RESERVEE: u32 = 0x00FF_FFFF;

/// Miroir de `struct ClipLevel` (32 octets).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Pod, Zeroable)]
pub struct ClipLevel {
    /// Coin du cube en chunks DU NIVEAU.
    pub origin_chunk: [i32; 3],
    /// Niveau de détail.
    pub lod: u32,
    /// Décalage du niveau dans la table de chunks.
    pub table_offset: u32,
    /// Remplissage.
    pub _pad: [u32; 3],
}

/// Miroir de `struct VoxelFrame` de `voxel_common.wgsl` : tout en `vec4` (pas de piège d'alignement).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Pod, Zeroable)]
pub struct VoxelFrame {
    /// Perspective : droite × tan(champ x / 2). Orthographique : droite × demi-largeur en voxels.
    pub ray_right: [f32; 4],
    /// Perspective : haut × tan(champ y / 2). Orthographique : haut × demi-hauteur en voxels.
    pub ray_up: [f32; 4],
    /// Avant (xyz), w = 1 si orthographique.
    pub ray_fwd: [f32; 4],
    /// Voxel entier de la caméra ; w = numéro d'image.
    pub cam_voxel: [i32; 4],
    /// Fraction dans ce voxel, en voxels ; w = temps (s).
    pub cam_frac: [f32; 4],
    /// Largeur, hauteur, 1/largeur, 1/hauteur.
    pub screen: [f32; 4],
    /// x = plan proche (m), y = portée maximale (voxels), z, w = réservés.
    pub params: [f32; 4],
}

/// Uniforme de l'éclairage : vue de débogage, ambiance et lumière du feuillage (miroir de `struct LightU` de
/// `voxel_light.wgsl`). Le soleil vient de l'uniforme du ciel : une seule source de vérité.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Pod, Zeroable)]
pub struct LightUniform {
    /// x = vue (0 image, 1 albédo, 2 normales, 3 distance, 4 masque, 5 ombre, 6 cascades), y = échelle du ciel,
    /// z = 1 si l'épaisseur du feuillage est disponible, w = longueur de la zone d'épaisseur (m).
    pub vue: [f32; 4],
    /// x = force de la translucidité, y = longueur d'absorption (m), z = lobe avant, w = force du liseré.
    pub feuillage_a: [f32; 4],
    /// rgb = teinte de transmission, w = épaisseur du liseré (m).
    pub feuillage_b: [f32; 4],
    /// x = saturation du feuillage, y = soulèvement des ombres, zw réservés.
    pub feuillage_c: [f32; 4],
    /// rgb = teinte du soulèvement des ombres, w réservé.
    pub feuillage_d: [f32; 4],
}

/// Une cascade d'ombre vue par l'éclairage (miroir de `struct ShadowCascadeU` de `voxel_shadow_sample.wgsl`).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Pod, Zeroable)]
pub struct ShadowCascadeUniform {
    /// xyz : point du plan de départ au centre du texel (0, 0), en mètres RELATIFS à la caméra ; w : texel (m).
    pub origin: [f32; 4],
    /// xyz : axe u des texels ; w : couche de la génération avant dans le tableau de textures.
    pub right: [f32; 4],
    /// xyz : axe v des texels ; w : côté en texels.
    pub up: [f32; 4],
    /// xyz : direction vers le soleil ; w : 1 si la cascade est prête.
    pub sun: [f32; 4],
    /// x : portée pleine (m) ; yzw réservés.
    pub limits: [f32; 4],
}

/// Uniforme des ombres lu par l'éclairage (miroir de `struct ShadowU`).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Pod, Zeroable)]
pub struct ShadowUniform {
    /// x : nombre de cascades ; y : 1 si les ombres sont actives ; z : fraction de fondu ; w : tangente du
    /// demi-angle du soleil.
    pub cfg0: [f32; 4],
    /// x : décalage normal (texels) ; y : biais de profondeur (m) ; z : biais de pente ; w : échelle de pénombre.
    pub cfg1: [f32; 4],
    /// x : rayon maximal de pénombre (m) ; yzw réservés.
    pub cfg2: [f32; 4],
    /// Les cascades.
    pub cascades: [ShadowCascadeUniform; 4],
}

/// Une cascade en construction, vue par le remplissage (miroir de `struct FillCascade` de `voxel_shadow_fill.wgsl`).
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Pod, Zeroable)]
pub struct ShadowFillCascade {
    /// Voxel entier du texel (0, 0) sur le plan de départ.
    pub base: [i32; 4],
    /// Position dans ce voxel, en voxels.
    pub frac: [f32; 4],
    /// Pas d'un texel selon u, en voxels.
    pub du: [f32; 4],
    /// Pas d'un texel selon v, en voxels.
    pub dv: [f32; 4],
    /// Direction des rayons (du soleil vers la scène).
    pub dir: [f32; 4],
    /// x : couche écrite ; y : côté en texels ; zw réservés.
    pub meta: [u32; 4],
}

/// Une tuile à remplir : cascade, colonne, ligne de tuile.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Pod, Zeroable)]
pub struct ShadowTileGpu {
    /// x : cascade ; y : colonne ; z : ligne ; w réservé.
    pub tuile: [u32; 4],
}

const _: () = assert!(size_of::<ClipLevel>() == 32);
const _: () = assert!(size_of::<VoxelFrame>() == 7 * 16);
const _: () = assert!(size_of::<LightUniform>() == 5 * 16);
const _: () = assert!(size_of::<ShadowCascadeUniform>() == 80);
const _: () = assert!(size_of::<ShadowUniform>() == 48 + 4 * 80);
const _: () = assert!(size_of::<ShadowFillCascade>() == 96);
const _: () = assert!(size_of::<ShadowTileGpu>() == 16);
