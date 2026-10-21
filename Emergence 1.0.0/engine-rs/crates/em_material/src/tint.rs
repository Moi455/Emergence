//! Sens des 7 bits de teinte, PAR classe (docs/19a § 5.3) : un trait `TintRule` par mode, jamais un `match`
//! sur le nom d'une matière. Chaque règle renvoie une « nuance » (position dans une rampe) à partir de la
//! teinte et d'un champ continu en coordonnées monde.

use crate::noise::{Frequency, ValueNoise, WorldPoint};
use crate::vegetation::{RampRole, VegetationRamps};
use em_core::hash::{hash_combine, mix64};
use em_core::ids::{MaterialId, VoxelValue};
use em_core::q16::Q16;

/// Mode d'interprétation des 7 bits de teinte d'une classe.
#[derive(Copy, Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TintMode {
    /// 7 bits : nuance 0..127 dans la rampe de la classe.
    Ramp128 = 0,
    /// Axe du fil (2 bits) et variante (5 bits).
    WoodAxis = 1,
    /// Numéro de pièce (7 bits), 0 = mortier.
    StonePiece = 2,
    /// Essence (5 bits) et variante / rampe (2 bits).
    Vegetation = 3,
    /// Variante lente (strates, humidité).
    Terrain = 4,
}

impl TintMode {
    /// Tous les modes, dans l'ordre de leur code GPU.
    pub const ALL: [TintMode; 5] = [
        TintMode::Ramp128,
        TintMode::WoodAxis,
        TintMode::StonePiece,
        TintMode::Vegetation,
        TintMode::Terrain,
    ];
    /// Code transmis au shader (`tint_mode`).
    pub const fn code(self) -> u32 {
        self as u32
    }
    /// Nom dans `material_render.toml`.
    pub const fn name(self) -> &'static str {
        match self {
            TintMode::Ramp128 => "ramp128",
            TintMode::WoodAxis => "wood_axis",
            TintMode::StonePiece => "stone_piece",
            TintMode::Vegetation => "vegetation",
            TintMode::Terrain => "terrain",
        }
    }
    /// Lit le nom d'un mode.
    pub fn from_name(nom: &str) -> Option<TintMode> {
        TintMode::ALL.into_iter().find(|m| m.name() == nom)
    }
    /// La règle qui interprète la teinte pour ce mode.
    pub fn rule(self) -> Box<dyn TintRule> {
        match self {
            TintMode::Ramp128 => Box::new(Ramp128Rule),
            TintMode::WoodAxis => Box::new(WoodAxisRule),
            TintMode::StonePiece => Box::new(StonePieceRule),
            TintMode::Vegetation => Box::new(VegetationRule),
            TintMode::Terrain => Box::new(TerrainRule),
        }
    }
}

/// Axe du fil du bois dans la teinte.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum GrainAxis {
    /// Fil le long de x (est).
    X = 0,
    /// Fil le long de y (haut).
    Y = 1,
    /// Fil le long de z (nord).
    Z = 2,
    /// Bois de bout (coupe perpendiculaire au fil).
    End = 3,
}

impl GrainAxis {
    /// Décode les 2 bits d'axe.
    pub const fn from_bits(b: u8) -> GrainAxis {
        match b & 3 {
            0 => GrainAxis::X,
            1 => GrainAxis::Y,
            2 => GrainAxis::Z,
            _ => GrainAxis::End,
        }
    }
}

/// Teinte d'une pièce de bois : axe (0..3) dans les bits 5-6, variante (0..31) dans les bits 0-4.
/// Panique si l'axe dépasse 3 ou la variante 31.
pub const fn tint_wood(axis: u8, variant: u8) -> u8 {
    assert!(axis < 4, "axe du fil hors de 0..=3");
    assert!(variant < 32, "variante de bois hors de 0..=31");
    (axis << 5) | variant
}
/// Axe et variante d'une teinte de bois.
pub const fn untint_wood(tint: u8) -> (GrainAxis, u8) {
    (GrainAxis::from_bits(tint >> 5), tint & 31)
}
/// Teinte d'une pierre : son numéro de pièce (0 = mortier, 1..127). Panique au-delà de 127.
pub const fn tint_stone(piece: u8) -> u8 {
    assert!(piece <= VoxelValue::TINT_MAX, "numéro de pièce hors de 0..=127");
    piece
}
/// Teinte de végétation : essence (0..31) dans les bits 2-6, variante ou rampe (0..3) dans les bits 0-1.
/// Panique si l'essence dépasse 31 ou la rampe 3.
pub const fn tint_vegetation(species: u8, ramp: u8) -> u8 {
    assert!(species < 32, "case d'essence hors de 0..=31");
    assert!(ramp < 4, "rampe ou variante hors de 0..=3");
    (species << 2) | ramp
}
/// Essence et rampe d'une teinte de végétation.
pub const fn untint_vegetation(tint: u8) -> (u8, u8) {
    (tint >> 2, tint & 3)
}

/// Choix de la rampe d'une essence.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum RampSelect {
    /// Numéro de rampe explicite (variante de la teinte).
    Index(u8),
    /// Tirage continu dans [0, 1] converti en numéro par le nombre de rampes disponibles.
    Pick(Q16),
}

/// Résultat d'une règle de teinte : où lire la couleur.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum Shade {
    /// Position `t` (Q16, 0..1) dans la rampe de la classe.
    Class { t: Q16 },
    /// Position `t` dans une rampe d'essence.
    Species {
        species: u8,
        role: RampRole,
        select: RampSelect,
        t: Q16,
    },
}

/// Ce qu'une règle de teinte voit d'un voxel.
pub struct ShadeInput<'a> {
    /// Classe de matière du voxel.
    pub class: MaterialId,
    /// Graine de la classe.
    pub class_seed: u64,
    /// Teinte (7 bits).
    pub tint: u8,
    /// Centre du voxel, en mètres Q16.
    pub point: WorldPoint,
    /// Tirage propre au voxel dans [0, 1) (gigue de grain).
    pub voxel_unit: Q16,
    /// Les quatre voisins dans le plan de la face (+u, -u, +v, -v), `None` s'ils ne sont pas connus.
    pub plane_neighbors: [Option<VoxelValue>; 4],
    /// Rôle de rampe de la classe (végétation).
    pub role: Option<RampRole>,
    /// Rampes d'essence.
    pub vegetation: &'a VegetationRamps,
}

/// Interprète les 7 bits de teinte d'un mode. Une implémentation par mode ; le polymorphisme remplace tout `match` sur la classe.
pub trait TintRule: Send + Sync {
    /// Le mode que cette règle interprète.
    fn mode(&self) -> TintMode;
    /// Nuance du voxel.
    fn shade(&self, input: &ShadeInput<'_>) -> Shade;
}

/// Fraction `n/d` en Q16 brut.
const fn frac(n: i64, d: i64) -> i64 {
    n * 65_536 / d
}
const MID: i64 = 32_768;

fn clamp01(v: i64) -> Q16 {
    Q16::from_raw(v.clamp(0, 65_536))
}

fn bruit(graine: u64, etiquette: u64) -> ValueNoise {
    ValueNoise::new(hash_combine(graine, etiquette))
}

/// Mode `ramp128` : la teinte est directement la nuance.
pub struct Ramp128Rule;
impl TintRule for Ramp128Rule {
    fn mode(&self) -> TintMode {
        TintMode::Ramp128
    }
    fn shade(&self, i: &ShadeInput<'_>) -> Shade {
        Shade::Class {
            t: clamp01(i64::from(i.tint) * 65_536 / 127),
        }
    }
}

/// Mode `terrain` : variante lente par bruit large, décalée par la teinte.
pub struct TerrainRule;
impl TintRule for TerrainRule {
    fn mode(&self) -> TintMode {
        TintMode::Terrain
    }
    fn shade(&self, i: &ShadeInput<'_>) -> Shade {
        let lent = bruit(i.class_seed, 0x7E44)
            .sample(i.point, Frequency::uniform(Q16::from_ratio(1, 5)))
            .raw();
        let variante = i64::from(i.tint) * 65_536 / 127;
        let t = MID + (variante - MID) * 6 / 10 + (lent - MID) * 4 / 10;
        Shade::Class { t: clamp01(t) }
    }
}

/// Mode `wood_axis` : veines étirées le long de l'axe du fil, nuance de planche par variante.
pub struct WoodAxisRule;
impl TintRule for WoodAxisRule {
    fn mode(&self) -> TintMode {
        TintMode::WoodAxis
    }
    fn shade(&self, i: &ShadeInput<'_>) -> Shade {
        let (axe, variante) = untint_wood(i.tint);
        let long = Q16::from_ratio(3, 10); // ≈ 0,3 cycle/m le long du fil
        let large = Q16::from_int(8); // ≈ 8 cycles/m en travers
        let f = match axe {
            GrainAxis::X => Frequency::per_axis(long, large, large),
            GrainAxis::Y => Frequency::per_axis(large, long, large),
            GrainAxis::Z => Frequency::per_axis(large, large, long),
            GrainAxis::End => Frequency::uniform(Q16::from_int(6)),
        };
        let graine = hash_combine(i.class_seed, 0x100 + u64::from(variante));
        let veine = ValueNoise::new(graine).sample(i.point, f).raw();
        let planche = (mix64(graine) >> 48) as i64; // nuance propre à la planche ou à la pièce
        let t = MID + (planche - MID) * frac(2, 10) / 65_536 + (veine - MID) * frac(45, 100) / 65_536;
        Shade::Class { t: clamp01(t) }
    }
}

/// Mode `stone_piece` : chaque pièce a sa nuance et son grain ; joint seulement entre deux pièces différentes.
pub struct StonePieceRule;
impl StonePieceRule {
    /// Vrai si ce voxel porte le joint avec un voisin du plan : le voisin est de la même classe, d'une autre pièce
    /// (ni mortier, qui est déjà le joint), et le numéro de ce voxel est le plus grand (un seul côté assombri).
    fn joint(i: &ShadeInput<'_>) -> bool {
        i.tint != 0
            && i.plane_neighbors
                .iter()
                .flatten()
                .any(|v| v.material() == i.class && v.tint() != 0 && v.tint() != i.tint && i.tint > v.tint())
    }
}
impl TintRule for StonePieceRule {
    fn mode(&self) -> TintMode {
        TintMode::StonePiece
    }
    fn shade(&self, i: &ShadeInput<'_>) -> Shade {
        let grain_seed = hash_combine(i.class_seed, 0x200 + u64::from(i.tint));
        let grain = ValueNoise::new(grain_seed)
            .sample(i.point, Frequency::uniform(Q16::from_int(12)))
            .raw();
        let t = if i.tint == 0 {
            frac(12, 100) + (grain - MID) / 10 // mortier : sombre, grain discret
        } else {
            let nuance = (mix64(grain_seed) >> 48) as i64;
            let base = frac(3, 10) + nuance * 55 / 100 + (grain - MID) / 5;
            if Self::joint(i) {
                base - frac(22, 100)
            } else {
                base
            }
        };
        Shade::Class { t: clamp01(t) }
    }
}

/// Mode `vegetation` : essence et rampe ; feuilles tirées par bruit lent, écorce fissurée verticalement.
pub struct VegetationRule;
impl TintRule for VegetationRule {
    fn mode(&self) -> TintMode {
        TintMode::Vegetation
    }
    fn shade(&self, i: &ShadeInput<'_>) -> Shade {
        let (species, ramp) = untint_vegetation(i.tint);
        let Some(role) = i.role else {
            return Shade::Class { t: Q16::HALF };
        };
        // graine par essence : deux essences voisines ont des champs différents
        let graine = hash_combine(i.class_seed, u64::from(i.vegetation.seed_of(species)));
        let n = |etiq: u64, f: Frequency| bruit(graine, etiq).sample(i.point, f).raw();
        let (select, t) = match role {
            RampRole::Leaves => {
                // reprend voxel_tree.py : choix lent à 0,55 et 1,3 m⁻¹, nuance = 0,10 + 0,80 × 0,6 + (bruit 5 m⁻¹ − 0,5) × 0,22 + gigue × 0,14
                let lent = n(1, Frequency::uniform(Q16::from_ratio(55, 100)));
                let moyen = n(2, Frequency::uniform(Q16::from_ratio(13, 10)));
                let fin = n(3, Frequency::uniform(Q16::from_int(5)));
                let gigue = i.voxel_unit.raw() - MID;
                let t = frac(58, 100) + (fin - MID) * 22 / 100 + gigue * 28 / 100;
                (RampSelect::Pick(clamp01((lent + moyen) / 2)), t)
            }
            RampRole::Bark => {
                // fissures : bruit étiré verticalement à 4 et 9 m⁻¹ en travers
                let a = n(
                    4,
                    Frequency::per_axis(Q16::from_int(4), Q16::from_ratio(1, 2), Q16::from_int(4)),
                );
                let b = n(
                    5,
                    Frequency::per_axis(Q16::from_int(9), Q16::ONE, Q16::from_int(9)),
                );
                (RampSelect::Index(ramp), frac(45, 100) + ((a + b) / 2 - MID) / 2)
            }
            RampRole::Flowers => (
                RampSelect::Index(ramp),
                MID + (n(6, Frequency::uniform(Q16::from_int(6))) - MID) * 3 / 10,
            ),
            RampRole::Fruits => (
                RampSelect::Index(ramp.min(1)),
                MID + (n(7, Frequency::uniform(Q16::from_int(6))) - MID) * 3 / 10,
            ),
        };
        Shade::Species {
            species,
            role,
            select,
            t: clamp01(t),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn teintes_aller_retour() {
        assert_eq!(untint_wood(tint_wood(2, 17)), (GrainAxis::Z, 17));
        assert_eq!(untint_wood(tint_wood(3, 31)).0, GrainAxis::End);
        assert_eq!(untint_vegetation(tint_vegetation(31, 3)), (31, 3));
        assert_eq!(tint_stone(127), 127);
        // toute teinte reste sur 7 bits
        assert!(tint_wood(3, 31) <= 127 && tint_vegetation(31, 3) <= 127);
    }

    #[test]
    #[should_panic(expected = "essence")]
    fn essence_trop_grande() {
        let _ = tint_vegetation(32, 0);
    }

    #[test]
    fn modes_nommes_et_regles() {
        for m in TintMode::ALL {
            assert_eq!(TintMode::from_name(m.name()), Some(m));
            assert_eq!(m.rule().mode(), m);
        }
        assert_eq!(TintMode::from_name("inconnu"), None);
    }
}
