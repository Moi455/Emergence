//! Référence CPU de la matière (docs/19 § 4.6) : couleur et propriétés d'un voxel à sa position monde,
//! en entiers et Q16, SANS flottant. Sert de vérité aux tests du shader (pixel par pixel).
//!
//! La couleur est un champ continu en coordonnées monde, évalué AU CENTRE du voxel du niveau affiché :
//! aucune coordonnée locale au voxel n'intervient, donc aucun biseau et aucune couture.

use crate::color::LinearRgb;
use crate::noise::{Frequency, ValueNoise, WorldPoint};
use crate::table::MaterialTable;
use crate::tint::{RampSelect, Shade, ShadeInput, TintMode, TintRule};
use crate::vegetation::VegetationRamps;
use em_core::coords::{Lod, VOXEL_MM, VoxelCoord};
use em_core::hash::{hash_combine, hash3};
use em_core::ids::VoxelValue;
use em_core::q16::Q16;

/// Un voxel à évaluer : sa valeur, sa position (coordonnées du niveau) et son niveau de détail.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct EvalContext {
    value: VoxelValue,
    voxel: VoxelCoord,
    lod: Lod,
    plane_neighbors: [Option<VoxelValue>; 4],
}

impl EvalContext {
    /// Contexte sans voisins connus (pas de joint de pierre).
    pub const fn new(value: VoxelValue, voxel: VoxelCoord, lod: Lod) -> Self {
        EvalContext {
            value,
            voxel,
            lod,
            plane_neighbors: [None; 4],
        }
    }
    /// Ajoute les quatre voisins dans le plan de la face (pour le joint entre deux pièces).
    pub const fn with_plane_neighbors(mut self, n: [Option<VoxelValue>; 4]) -> Self {
        self.plane_neighbors = n;
        self
    }
    /// Valeur du voxel.
    pub const fn value(&self) -> VoxelValue {
        self.value
    }
    /// Coordonnées du voxel (voxels du niveau).
    pub const fn voxel(&self) -> VoxelCoord {
        self.voxel
    }
    /// Niveau de détail (un voxel du niveau `n` mesure 50 mm × 2ⁿ).
    pub const fn lod(&self) -> Lod {
        self.lod
    }
    /// Centre du voxel en millimètres monde : (2c + 1) × 25 mm × 2ˡᵒᵈ.
    pub fn center_mm(&self) -> [i64; 3] {
        let c = |v: i32| ((2 * i64::from(v) + 1) * (VOXEL_MM / 2)) << self.lod;
        [c(self.voxel.x), c(self.voxel.y), c(self.voxel.z)]
    }
}

/// Résultat de l'évaluation d'un voxel.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct VoxelSample {
    albedo: LinearRgb,
    roughness: Q16,
    translucency: Q16,
    emission: Q16,
}

impl VoxelSample {
    /// Albédo linéaire.
    pub const fn albedo(&self) -> LinearRgb {
        self.albedo
    }
    /// Rugosité (Q16, 0..1).
    pub const fn roughness(&self) -> Q16 {
        self.roughness
    }
    /// Translucidité (Q16, 0..1).
    pub const fn translucency(&self) -> Q16 {
        self.translucency
    }
    /// Émission (Q16, HDR).
    pub const fn emission(&self) -> Q16 {
        self.emission
    }
}

/// Évalue la matière d'un voxel : possède les règles de teinte (une par mode) et emprunte la table et les rampes.
pub struct MaterialEvaluator<'a> {
    table: &'a MaterialTable,
    vegetation: &'a VegetationRamps,
    regles: Vec<Box<dyn TintRule>>,
}

impl<'a> MaterialEvaluator<'a> {
    /// Crée l'évaluateur avec ses collaborateurs.
    pub fn new(table: &'a MaterialTable, vegetation: &'a VegetationRamps) -> Self {
        MaterialEvaluator {
            table,
            vegetation,
            regles: TintMode::ALL.iter().map(|m| m.rule()).collect(),
        }
    }

    /// Couleur et propriétés du voxel. L'air donne un échantillon nul.
    pub fn eval(&self, ctx: &EvalContext) -> VoxelSample {
        let value = ctx.value;
        let def = self.table.get(value.material());
        let r = def.render();
        let point = WorldPoint::from_mm(ctx.center_mm());
        let class_seed = def.class_seed();
        // gigue de grain : dépend du voxel, d'amplitude faible, jamais d'une coordonnée locale à la face
        let h = hash3(
            hash_combine(class_seed, u64::from(ctx.lod)),
            i64::from(ctx.voxel.x),
            i64::from(ctx.voxel.y),
            i64::from(ctx.voxel.z),
        );
        let voxel_unit = Q16::from_raw((h >> 48) as i64);
        let entree = ShadeInput {
            class: value.material(),
            class_seed,
            tint: value.tint(),
            point,
            voxel_unit,
            plane_neighbors: ctx.plane_neighbors,
            role: r.veg_role(),
            vegetation: self.vegetation,
        };
        let ombre = self.regles[r.tint_mode().code() as usize].shade(&entree);
        // champ continu commun : luminance et teinte, indépendants du voxel
        let lent = ValueNoise::new(hash_combine(class_seed, 0xA1))
            .sample(point, Frequency::uniform(Q16::from_int(2)));
        let chaud = ValueNoise::new(hash_combine(class_seed, 0xA2))
            .sample(point, Frequency::uniform(Q16::from_ratio(7, 10)));
        let centre = |v: Q16| v.raw() - 32_768; // [-0,5, 0,5)
        let decalage = centre(lent) * 2 * r.albedo_var().raw() / 65_536
            + centre(voxel_unit) * 2 * r.voxel_jitter().raw() / 65_536;
        let (ramp, t) = match ombre {
            Shade::Class { t } => (*def.ramp(), t),
            Shade::Species {
                species,
                role,
                select,
                t,
            } => {
                let rampes = self.vegetation.ramps(species, role);
                let choix = match select {
                    RampSelect::Index(i) => usize::from(i).min(rampes.len().saturating_sub(1)),
                    RampSelect::Pick(p) => {
                        ((p.raw() as usize) * rampes.len() / 65_537).min(rampes.len().saturating_sub(1))
                    }
                };
                (rampes.get(choix).copied().unwrap_or(*def.ramp()), t)
            }
        };
        let couleur = ramp.sample(Q16::from_raw(t.raw() + decalage));
        // variation de teinte : chaud/froid (rouge monte, bleu descend)
        let k = centre(chaud) * 2 * r.hue_var().raw() / 65_536;
        let [cr, cg, cb] = couleur.channels();
        let albedo = LinearRgb::new(
            Q16::from_raw(cr.raw() + cr.raw() * k / 65_536),
            cg,
            Q16::from_raw(cb.raw() - cb.raw() * k / 65_536),
        );
        let rug = ValueNoise::new(hash_combine(class_seed, 0xA3))
            .sample(point, Frequency::uniform(Q16::from_int(3)));
        let roughness = Q16::from_raw(
            (r.roughness().raw() + centre(rug) * 2 * r.roughness_var().raw() / 65_536).clamp(0, 65_536),
        );
        if value.is_air() {
            return VoxelSample {
                albedo: LinearRgb::BLACK,
                roughness: Q16::ZERO,
                translucency: Q16::ZERO,
                emission: Q16::ZERO,
            };
        }
        VoxelSample {
            albedo,
            roughness,
            translucency: r.translucency(),
            emission: r.emission(),
        }
    }
}

/// Albédo linéaire d'un voxel, référence CPU du shader (`em_material::eval_albedo_cpu`, docs/19 § 4.6).
pub fn eval_albedo_cpu(table: &MaterialTable, vegetation: &VegetationRamps, ctx: &EvalContext) -> LinearRgb {
    MaterialEvaluator::new(table, vegetation).eval(ctx).albedo()
}
