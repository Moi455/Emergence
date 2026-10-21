//! La couleur PLATE d'un voxel, évaluée une fois par voxel visible (jamais par face) : un voxel = un aplat.
//!
//! [`VoxelColorer`] est le contrat du mailleur ; [`MaterialColorer`] l'implémente avec l'évaluateur de référence de
//! `em_material` (mode `VoxelPixel` compris, donc la granulométrie réglée par `granulometrie_force`) et le modèle de
//! surface (octet de porosité, réflexion, grain ; assombrissement d'un voxel mouillé).

use em_core::{Lod, VoxelCoord, VoxelValue};
use em_material::{
    EvalContext, MaterialEvaluator, MaterialFlags, MaterialTable, StyleSheet, SurfaceModel, VegetationRamps,
};

/// Ce que le mailleur retient d'un voxel visible.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct VoxelAppearance {
    /// Couleur sRGB8 plate.
    pub color: [u8; 3],
    /// Octet de paramètres de matière (`em_material::SurfaceParams::pack`).
    pub params: u8,
    /// Vrai pour du feuillage (translucide en contre-jour).
    pub foliage: bool,
}

/// Donne l'aspect d'un voxel à sa position (coordonnées du niveau `lod`). Pure : mêmes entrées, même sortie.
pub trait VoxelColorer: Sync {
    /// Aspect du voxel `value` situé en `voxel`.
    fn appearance(&self, value: VoxelValue, voxel: VoxelCoord, lod: Lod) -> VoxelAppearance;

    /// Vrai si la classe de `value` est du feuillage (sert à l'épaisseur sans évaluer la couleur).
    fn is_foliage(&self, value: VoxelValue) -> bool;
}

/// Colorieur de référence : `em_material` (couleur) et `SurfaceModel` (paramètres de surface).
pub struct MaterialColorer<'a> {
    evaluator: MaterialEvaluator<'a>,
    surface: SurfaceModel,
    table: &'a MaterialTable,
    foliage: Vec<bool>,
}

impl<'a> MaterialColorer<'a> {
    /// Construit le colorieur : la feuille de style fixe le mode (continu ou `VoxelPixel`) et la granulométrie de
    /// chaque classe, elle sert aussi au modèle de surface.
    pub fn new(table: &'a MaterialTable, vegetation: &'a VegetationRamps, style: StyleSheet) -> Self {
        let surface = SurfaceModel::new(table, &style);
        let mut foliage = vec![false; em_material::CLASS_COUNT];
        for def in table.iter() {
            foliage[usize::from(def.id().get())] = def.render().flags().contains(MaterialFlags::FOLIAGE);
        }
        Self {
            evaluator: MaterialEvaluator::with_style(table, vegetation, style),
            surface,
            table,
            foliage,
        }
    }

    /// Modèle de surface (essais, outils).
    pub fn surface(&self) -> &SurfaceModel {
        &self.surface
    }

    /// Table des matières.
    pub fn table(&self) -> &MaterialTable {
        self.table
    }
}

impl VoxelColorer for MaterialColorer<'_> {
    fn appearance(&self, value: VoxelValue, voxel: VoxelCoord, lod: Lod) -> VoxelAppearance {
        let echantillon = self.evaluator.eval(&EvalContext::new(value, voxel, lod));
        let surface = self.surface.evaluate(value, voxel, lod);
        let albedo = echantillon.albedo().scale(surface.tone());
        VoxelAppearance {
            color: self.table.srgb().encode(albedo),
            params: surface.params().pack(),
            foliage: self.is_foliage(value),
        }
    }

    fn is_foliage(&self, value: VoxelValue) -> bool {
        self.foliage[usize::from(value.material().get())]
    }
}
