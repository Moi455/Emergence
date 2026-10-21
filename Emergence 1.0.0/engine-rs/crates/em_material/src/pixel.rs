//! Mode « VoxelPixel » (L23p) : la texture est faite de la variation de COULEUR ENTRE VOXELS, jamais d'un bruit
//! continu en coordonnées monde. Un trait `PixelRule` par famille de teinte (même esprit que `TintRule`), sans
//! `match` sur le nom d'une matière.
//!
//! Toute variation vient d'un hachage de ENTIERS : le numéro de pièce de la teinte (pierre), la colonne de fibre
//! et le tronçon de fibre (bois), le voxel lui-même (gigue). Deux voxels d'une même pierre ne diffèrent donc que
//! par la gigue voulue ; aucun champ ne varie « en douceur » d'un voxel au suivant.
//!
//! Le shader (`material.wgsl`, `eval_pixel_albedo`) est le port exact de ce fichier : mêmes hachages, mêmes
//! constantes de séparation de graine.

use crate::style::PixelParams;
use crate::tint::{GrainAxis, TintMode, untint_wood};
use em_core::coords::VoxelCoord;
use em_core::hash::{hash_combine, mix64};
use em_core::q16::Q16;

const MID: i64 = 32_768;
const UN: i64 = 65_536;

/// Longueur d'un tronçon de fibre : `1 << RUN_SHIFT` voxels (8 voxels = 40 cm).
pub const RUN_SHIFT: u32 = 3;

/// Ce qu'une règle VoxelPixel voit d'un voxel : sa teinte et sa position ENTIÈRE.
pub struct PixelInput<'a> {
    /// Graine de la classe.
    pub class_seed: u64,
    /// Teinte (7 bits).
    pub tint: u8,
    /// Voxel (coordonnées du niveau affiché).
    pub voxel: VoxelCoord,
    /// Réglages du mode pour la classe.
    pub params: &'a PixelParams,
}

/// Nuance choisie pour un voxel : position dans la rampe de la classe, et décalage chaud/froid.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct PixelTone {
    /// Position `t` dans la rampe (Q16, peut déborder de [0, 1] : la rampe borne).
    pub t: Q16,
    /// Décalage chaud (+) ou froid (-) en fraction de Q16 : le rouge monte et le bleu descend.
    pub warmth: Q16,
}

/// Interprète la teinte d'une classe en mode VoxelPixel : une implémentation par famille.
pub trait PixelRule: Send + Sync {
    /// Nuance du voxel (hors gigue par voxel, ajoutée par l'évaluateur).
    fn tone(&self, input: &PixelInput<'_>) -> PixelTone;
}

fn unit16(h: u64) -> i64 {
    (h >> 48) as i64
}

/// `(unité - 1/2) × 2 × amplitude`, entier signé en Q16 brut.
fn centre(unite: i64, amplitude: Q16) -> i64 {
    (unite - MID) * 2 * amplitude.raw() / UN
}

/// Pierre : la teinte est le numéro de pièce (0 = mortier). Chaque pierre a SON ton (clair/sombre) et SA chaleur,
/// constants sur toute la pierre ; le mortier est un ton sombre posé par la recette (joint d'un voxel).
pub struct StonePixelRule;

impl StonePixelRule {
    /// Graine d'une pièce (la même que le grain du mode continu).
    pub fn piece_seed(class_seed: u64, piece: u8) -> u64 {
        hash_combine(class_seed, 0x200 + u64::from(piece))
    }
}

impl PixelRule for StonePixelRule {
    fn tone(&self, i: &PixelInput<'_>) -> PixelTone {
        if i.tint == 0 {
            return PixelTone {
                t: i.params.joint_tone,
                warmth: Q16::from_raw(i.params.hue_spread.raw() / 2),
            };
        }
        let gs = Self::piece_seed(i.class_seed, i.tint);
        let ton = unit16(mix64(gs));
        let chaleur = unit16(hash_combine(gs, 0x77));
        PixelTone {
            t: Q16::from_raw(MID + centre(ton, i.params.block_spread)),
            warmth: Q16::from_raw(centre(chaleur, i.params.hue_spread)),
        }
    }
}

/// Bois : la teinte porte l'axe du fil et un numéro d'anneau/nœud posé par la recette. La texture vient de la
/// COLONNE de fibre (deux entiers de la section : un voxel de large, constante sur toute la longueur), d'un
/// TRONÇON de fibre (rupture de ton tous les 8 voxels, décalée par fibre), de la phase d'anneau et des nœuds.
pub struct WoodPixelRule;

impl WoodPixelRule {
    /// (position le long du fil, coordonnées de la section) d'un voxel pour cet axe ; `None` pour le bois de bout.
    pub fn along_and_cross(axis: GrainAxis, v: VoxelCoord) -> Option<(i32, i32, i32)> {
        match axis {
            GrainAxis::X => Some((v.x, v.y, v.z)),
            GrainAxis::Y => Some((v.y, v.x, v.z)),
            GrainAxis::Z => Some((v.z, v.x, v.y)),
            GrainAxis::End => None,
        }
    }
}

impl PixelRule for WoodPixelRule {
    fn tone(&self, i: &PixelInput<'_>) -> PixelTone {
        let (axe, variante) = untint_wood(i.tint);
        let fs = hash_combine(i.class_seed, 0x300 + axe as u64);
        let (hf, run) = match Self::along_and_cross(axe, i.voxel) {
            Some((s, c1, c2)) => {
                let hf = hash_combine(hash_combine(fs, i64::from(c1) as u64), i64::from(c2) as u64);
                let decalage = ((hf >> 40) & 7) as i64;
                let r = (i64::from(s) + decalage) >> RUN_SHIFT;
                (hf, unit16(hash_combine(hf, r as u64)))
            }
            None => {
                let h = hash_combine(
                    hash_combine(
                        hash_combine(fs, i64::from(i.voxel.x) as u64),
                        i64::from(i.voxel.y) as u64,
                    ),
                    i64::from(i.voxel.z) as u64,
                );
                (h, MID)
            }
        };
        let fibre = unit16(hf);
        let anneau = i64::from(variante & 15) * UN / 15;
        let noeud = i64::from((variante >> 4) & 1);
        let t = MID
            + centre(fibre, i.params.block_spread)
            + centre(run, i.params.run_contrast)
            + centre(anneau, i.params.ring_contrast)
            - noeud * i.params.joint_tone.raw();
        PixelTone {
            t: Q16::from_raw(t),
            warmth: Q16::from_raw(centre(fibre, i.params.hue_spread)),
        }
    }
}

/// Teinte lue directement comme nuance (rampe 128, terrain) : la recette pose le ton de chaque voxel ou de
/// chaque pièce (tuile, mousse), sans aucun champ continu.
pub struct DirectPixelRule;

impl PixelRule for DirectPixelRule {
    fn tone(&self, i: &PixelInput<'_>) -> PixelTone {
        PixelTone {
            t: Q16::from_raw((i64::from(i.tint) * UN / 127).clamp(0, UN)),
            warmth: Q16::ZERO,
        }
    }
}

impl TintMode {
    /// Règle VoxelPixel de ce mode. La végétation n'en a pas (ses feuilles sont déjà variées voxel par voxel,
    /// décision de Monsieur du 21 oct.) : `StyleSheet` la refuse, la règle directe n'est qu'un repli inerte.
    pub fn pixel_rule(self) -> Box<dyn PixelRule> {
        match self {
            TintMode::WoodAxis => Box::new(WoodPixelRule),
            TintMode::StonePiece => Box::new(StonePixelRule),
            TintMode::Ramp128 | TintMode::Terrain | TintMode::Vegetation => Box::new(DirectPixelRule),
        }
    }
}
