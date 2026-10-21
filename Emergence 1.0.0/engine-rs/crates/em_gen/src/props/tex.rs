//! Les TEXTURES des props et des rochers : une règle `(x, y, z) -> voxel` (classe + teinte), à la manière des
//! recettes de L23p : la variation vient de la teinte posée voxel par voxel (numéro de pierre, variante du fil du
//! bois, nuance de la rampe), par hachage de la POSITION ENTIÈRE.

use em_core::VoxelValue;

use crate::batiments::kit::matieres::{Matieres, bois, pierre, val};
use crate::batiments::kit::rng::hh;
use em_core::MaterialId;

/// Une texture.
#[derive(Copy, Clone, Debug)]
pub enum Tex {
    /// Bois de chêne brut ; l'axe du fil (0 x, 1 y, 2 z).
    Oak(u8),
    /// Bois sombre.
    Timber(u8),
    /// Bois d'ornement.
    Trim(u8),
    /// Planches.
    Planks,
    /// Pierre à pièces numérotées de cette classe.
    Stone(MaterialId),
    /// Pierre à gros blocs (rochers) : pièces de `bloc` voxels.
    Block(MaterialId, i32),
    /// Rampe de cette classe, ton de base et étendue (0..127).
    Ramp(MaterialId, u8, u8),
    /// Valeur fixe.
    Flat(VoxelValue),
}

impl Tex {
    /// Voxel de cette texture à la position (x, y, z).
    pub fn at(&self, m: &Matieres, x: i32, y: i32, z: i32) -> VoxelValue {
        let h = hh(x, y, z, 77);
        match *self {
            Tex::Oak(a) => bois(m.oak_raw, a, 3 + (h % 11) as u8),
            Tex::Timber(a) => bois(m.timber, a, 2 + (h % 8) as u8),
            Tex::Trim(a) => bois(m.wood_trim, a, 3 + (h % 10) as u8),
            Tex::Planks => val(m.oak_planks, 40 + (h % 36) as u8),
            Tex::Stone(c) => pierre(
                c,
                1 + (hh(x.div_euclid(6), y.div_euclid(4), z.div_euclid(6), 78) % 126) as u8,
            ),
            Tex::Block(c, b) => {
                let b = b.max(1);
                pierre(
                    c,
                    1 + (hh(x.div_euclid(b), y.div_euclid(b), z.div_euclid(b), 79) % 126) as u8,
                )
            }
            Tex::Ramp(c, base, spread) => val(
                c,
                base.saturating_add((h % u32::from(spread.max(1))) as u8).min(127),
            ),
            Tex::Flat(v) => v,
        }
    }
}
