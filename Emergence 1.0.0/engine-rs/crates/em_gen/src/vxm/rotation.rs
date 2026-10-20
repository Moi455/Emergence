//! Quarts de tour autour de l'axe vertical (docs/19 § 2.6).

use crate::error::GenError;

/// Nombre de quarts de tour (0..=3) de l'est vers le nord, vu d'en haut, autour du **centre** de la cellule pivot.
///
/// Le repère monde est gaucher (x est, y haut, z nord) mais la rotation est définie physiquement (est vers
/// nord) : un voxel à `(1, 0)` (est du pivot) arrive à `(0, 1)` (nord du pivot). Tourner autour du centre
/// d'une cellule envoie les cellules sur des cellules : aucun décalage d'un voxel (piège de L08).
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, Hash)]
pub struct QuarterTurns(u8);

impl QuarterTurns {
    /// Aucune rotation.
    pub const NONE: QuarterTurns = QuarterTurns(0);

    /// Construit ; refuse plus de 3 quarts de tour.
    pub fn new(n: u8) -> Result<Self, GenError> {
        if n > 3 {
            return Err(GenError::BadParams(format!("quarts de tour {n} hors de 0..=3")));
        }
        Ok(Self(n))
    }

    /// Valeur 0..=3.
    pub const fn get(self) -> u8 {
        self.0
    }

    /// Rotation inverse.
    pub const fn inverse(self) -> QuarterTurns {
        QuarterTurns((4 - self.0) & 3)
    }

    /// Image de l'écart `(dx, dz)` au pivot (est, nord).
    pub const fn rotate(self, dx: i64, dz: i64) -> (i64, i64) {
        match self.0 {
            0 => (dx, dz),
            1 => (-dz, dx),
            2 => (-dx, -dz),
            _ => (dz, -dx),
        }
    }

    /// Boîte `[min, max)` (x, z seulement) tournée : bornes de l'image des cellules extrêmes.
    pub fn rotate_box(self, min: [i64; 2], max_excl: [i64; 2]) -> ([i64; 2], [i64; 2]) {
        let (ax, az) = self.rotate(min[0], min[1]);
        let (bx, bz) = self.rotate(max_excl[0] - 1, max_excl[1] - 1);
        ([ax.min(bx), az.min(bz)], [ax.max(bx) + 1, az.max(bz) + 1])
    }
}
