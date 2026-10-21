//! L'occlusion « creuse » (L34) : une deuxième composante d'occlusion, à plus grande portée que celle des quatre
//! voisins du sommet, calculée au maillage et multipliée à l'ambiance du ciel.
//!
//! Pour chaque sommet d'une face, on compte la part de voxels pleins dans une dalle devant la face : `2 r x 2 r` voxels
//! autour du sommet dans le plan de la face, sur `r` couches devant elle (`r` = la portée, 1 à 3 voxels). Un mur plat
//! donne 0 ; un angle rentrant 25 à 50 % ; le cœur d'un houppier beaucoup plus. La part est rangée sur 2 bits (la
//! PROFONDEUR du creux, 0 = dégagé à 3 = très encaissé) ; le shader la convertit en facteur selon [`CreuxAoParams`].
//!
//! Le comptage se fait par une somme cumulée en 3D du voisinage (`CreuxField`), bâtie une fois par chunk : huit
//! lectures par sommet, déterministes, bornées par la bordure du `PaddedChunk`.

use crate::error::ParamError;
use crate::padded::{PAD, PADDED_EDGE, PaddedChunk};
use crate::quad::{AO_FACTOR, Face};

/// Portée maximale (voxels) : la bordure du chunk.
pub const PORTEE_MAX: u8 = PAD as u8;

/// Niveaux de l'occlusion par sommet creusés (L34) : plus sombres que ceux de la référence ([`AO_FACTOR`]).
pub const AO_FACTOR_CREUX: [f32; 4] = [0.35, 0.6, 0.82, 1.0];

/// Facteurs de l'ambiance par profondeur de creux 0..3 quand la force est 1 (0 = dégagé : aucun effet).
pub const CREUX_FACTOR: [f32; 4] = [1.0, 0.86, 0.70, 0.54];

/// Seuils de la part de voxels pleins (en 1/1000) qui séparent les profondeurs 0|1, 1|2 et 2|3.
const SEUILS_MILLIEMES: [u32; 3] = [60, 200, 380];

/// Réglages validés de l'occlusion creuse. Champs privés, construction par `new` puis `with_*`.
#[derive(Copy, Clone, Debug, PartialEq)]
pub struct CreuxAoParams {
    strength: f32,
    reach: u8,
}

impl CreuxAoParams {
    /// Force maximale (au-delà de 1 le creux dépasse les facteurs de référence).
    pub const FORCE_MAX: f32 = 2.0;

    /// Réglage éteint : l'occlusion de la référence seule (la base de L33), le mailleur ne calcule rien de plus.
    pub const fn disabled() -> Self {
        Self {
            strength: 0.0,
            reach: 2,
        }
    }

    /// Construit avec une force 0 à 2 (0 = éteint ; 1 = les valeurs plus basses `[.35, .6, .82, 1]` et la dalle pleine).
    pub fn new(strength: f32) -> Result<Self, ParamError> {
        if !(0.0..=Self::FORCE_MAX).contains(&strength) {
            return Err(ParamError::HorsPlage {
                nom: "ao-creux",
                valeur: strength,
                min: 0.0,
                max: Self::FORCE_MAX,
            });
        }
        Ok(Self { strength, reach: 2 })
    }

    /// Fixe la portée de la dalle, 1 à 3 voxels (5 à 15 cm).
    pub fn with_reach(mut self, reach: u8) -> Result<Self, ParamError> {
        if !(1..=PORTEE_MAX).contains(&reach) {
            return Err(ParamError::HorsPlage {
                nom: "ao-creux-portee",
                valeur: f32::from(reach),
                min: 1.0,
                max: f32::from(PORTEE_MAX),
            });
        }
        self.reach = reach;
        Ok(self)
    }

    /// Force 0 à 2.
    pub const fn strength(&self) -> f32 {
        self.strength
    }

    /// Portée de la dalle en voxels.
    pub const fn reach(&self) -> u8 {
        self.reach
    }

    /// Vrai si la composante est active.
    pub fn enabled(&self) -> bool {
        self.strength > 0.0
    }

    /// Portée à confier au mailleur : `None` quand le creux est éteint (rien n'est calculé).
    pub fn mesher_reach(&self) -> Option<u8> {
        self.enabled().then_some(self.reach)
    }

    /// Facteurs de l'occlusion par sommet (niveaux 0 à 3) : la table de la référence, glissée vers les valeurs plus
    /// basses `[.35, .6, .82, 1]` à mesure que la force passe de 0 à 1.
    pub fn vertex_levels(&self) -> [f32; 4] {
        let t = self.strength.min(1.0);
        std::array::from_fn(|k| AO_FACTOR[k] + (AO_FACTOR_CREUX[k] - AO_FACTOR[k]) * t)
    }

    /// Facteurs de l'ambiance par profondeur de creux (0 à 3) : `1 - force x (1 - CREUX_FACTOR)`, jamais sous 0,2.
    pub fn creux_levels(&self) -> [f32; 4] {
        std::array::from_fn(|k| (1.0 - self.strength * (1.0 - CREUX_FACTOR[k])).max(0.2))
    }
}

impl Default for CreuxAoParams {
    /// Défaut du labo : force 1, portée 2 voxels.
    fn default() -> Self {
        Self {
            strength: 1.0,
            reach: 2,
        }
    }
}

const COTE: usize = PADDED_EDGE + 1;

/// Somme cumulée 3D de l'occupation d'un `PaddedChunk`.
pub struct CreuxField {
    cumul: Vec<u32>,
}

impl CreuxField {
    /// Bâtit la somme cumulée : `cumul[(y * COTE + z) * COTE + x]` compte les voxels pleins strictement avant `(x, y, z)`
    /// dans le repère du tableau (indices 0..EDGE).
    pub fn new(padded: &PaddedChunk) -> Self {
        let mut cumul = vec![0_u32; COTE * COTE * COTE];
        for y in 0..PADDED_EDGE {
            for z in 0..PADDED_EDGE {
                let mut ligne = 0_u32;
                for x in 0..PADDED_EDGE {
                    let brut = padded.raw_at(x + PADDED_EDGE * z + PADDED_EDGE * PADDED_EDGE * y);
                    ligne += u32::from(PaddedChunk::is_solid(brut));
                    let ici = ((y + 1) * COTE + (z + 1)) * COTE + (x + 1);
                    let dessous = ((y + 1) * COTE + z) * COTE + (x + 1);
                    let derriere = (y * COTE + (z + 1)) * COTE + (x + 1);
                    let diag = (y * COTE + z) * COTE + (x + 1);
                    cumul[ici] = ligne + cumul[dessous] + cumul[derriere] - cumul[diag];
                }
            }
        }
        Self { cumul }
    }

    /// Voxels pleins dans `[a, b)` (indices du tableau, 0..=EDGE).
    fn somme(&self, a: [usize; 3], b: [usize; 3]) -> u32 {
        let g = |x: usize, y: usize, z: usize| self.cumul[(y * COTE + z) * COTE + x];
        g(b[0], b[1], b[2]) + g(a[0], a[1], b[2]) + g(a[0], b[1], a[2]) + g(b[0], a[1], a[2])
            - g(a[0], b[1], b[2])
            - g(b[0], a[1], b[2])
            - g(b[0], b[1], a[2])
            - g(a[0], a[1], a[2])
    }

    /// Profondeurs du creux (0..=3) des quatre coins de la face `f` du voxel `(x, y, z)` (coordonnées locales au chunk),
    /// dans l'ordre des coins de l'occlusion : (-u,-v), (+u,-v), (+u,+v), (-u,+v).
    pub fn depths(&self, x: i32, y: i32, z: i32, f: Face, reach: u8) -> [u8; 4] {
        let r = i32::from(reach);
        let p = [x, y, z];
        let a = f.axis();
        let (u, v) = (f.u_axis(), f.v_axis());
        // couches devant la face : r voxels à partir de la case voisine
        let (d0, d1) = if f.sign() > 0 {
            (p[a] + 1, p[a] + 1 + r)
        } else {
            (p[a] - r, p[a])
        };
        let volume = (4 * r * r * r) as u32;
        let mut sortie = [0_u8; 4];
        for (k, (cu, cv)) in [(0, 0), (1, 0), (1, 1), (0, 1)].into_iter().enumerate() {
            let (pu, pv) = (p[u] + cu, p[v] + cv);
            let mut lo = [0_usize; 3];
            let mut hi = [0_usize; 3];
            let dec = PAD as i32;
            lo[a] = (d0 + dec) as usize;
            hi[a] = (d1 + dec) as usize;
            lo[u] = (pu - r + dec) as usize;
            hi[u] = (pu + r + dec) as usize;
            lo[v] = (pv - r + dec) as usize;
            hi[v] = (pv + r + dec) as usize;
            let n = self.somme(lo, hi);
            let milliemes = n * 1000 / volume;
            sortie[k] = SEUILS_MILLIEMES.iter().filter(|s| milliemes >= **s).count() as u8;
        }
        sortie
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn la_force_zero_eteint_et_valide_les_plages() {
        assert!(CreuxAoParams::new(0.0).unwrap().mesher_reach().is_none());
        assert_eq!(CreuxAoParams::new(1.0).unwrap().mesher_reach(), Some(2));
        assert!(CreuxAoParams::new(-0.1).is_err() && CreuxAoParams::new(2.5).is_err());
        assert!(CreuxAoParams::new(f32::NAN).is_err());
        let p = CreuxAoParams::default();
        assert!(p.with_reach(0).is_err() && p.with_reach(4).is_err());
        assert_eq!(p.with_reach(3).unwrap().reach(), 3);
    }

    #[test]
    fn les_tables_sont_monotones_et_la_force_zero_rend_la_reference() {
        let off = CreuxAoParams::disabled();
        assert_eq!(off.vertex_levels(), AO_FACTOR);
        assert_eq!(off.creux_levels(), [1.0; 4]);
        let on = CreuxAoParams::default();
        assert_eq!(on.vertex_levels(), AO_FACTOR_CREUX);
        let v = on.vertex_levels();
        assert!(
            v.windows(2).all(|w| w[0] <= w[1]),
            "niveaux d'occlusion croissants : {v:?}"
        );
        let c = on.creux_levels();
        assert!(
            c.windows(2).all(|w| w[0] >= w[1]),
            "profondeurs décroissantes : {c:?}"
        );
        let fort = CreuxAoParams::new(2.0).unwrap().creux_levels();
        assert!(fort[3] >= 0.2 && fort[3] < on.creux_levels()[3]);
    }
}
