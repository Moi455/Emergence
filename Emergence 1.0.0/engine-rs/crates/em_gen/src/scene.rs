//! `StaticScene` : la scène statique minimale du labo (docs/19b L08) : un sol plat de turf et des modèles
//! posés. C'est une `VoxelSource` en lecture seule qui donne ses chunks au rendu (L09).

use std::sync::Arc;

use em_core::{ChunkKey, Lod, VoxelBox, VoxelCoord, VoxelValue, hash_combine};
use em_voxel::{Chunk, ChunkHint, CompositeLayer, CompositeMode, CompositeSource, FlatSource, VoxelSource};

use crate::bati::PlacedPlan;
use crate::error::GenError;
use crate::vxh::PlacedHouse;
use crate::vxm::PlacedModel;

/// Construit une `StaticScene` : les couches sont posées dans l'ordre (sol d'abord, puis les modèles).
#[derive(Default)]
pub struct StaticSceneBuilder {
    ground: Option<FlatSource>,
    models: Vec<Arc<PlacedModel>>,
    plans: Vec<Arc<PlacedPlan>>,
    houses: Vec<Arc<PlacedHouse>>,
}

impl StaticSceneBuilder {
    /// Sol plat : tout voxel dont l'arête basse est sous `height` (voxels de niveau 0) est plein de `solid`.
    pub fn ground(mut self, height: i32, solid: VoxelValue) -> Self {
        self.ground = Some(FlatSource::new(height, solid));
        self
    }

    /// Sol plat de turf (classe 1 du catalogue, teinte 0).
    pub fn turf_ground(self, height: i32) -> Self {
        let turf = VoxelValue::new(em_core::MaterialId::new(1), 0);
        self.ground(height, turf)
    }

    /// Pose un modèle.
    pub fn place(mut self, model: PlacedModel) -> Self {
        self.models.push(Arc::new(model));
        self
    }

    /// Pose un plan de générateur (recette du bâti), après les modèles déjà posés.
    pub fn place_plan(mut self, plan: PlacedPlan) -> Self {
        self.plans.push(Arc::new(plan));
        self
    }

    /// Pose une maison `.vxh` (L34), après les plans déjà posés.
    pub fn place_house(mut self, house: PlacedHouse) -> Self {
        self.houses.push(Arc::new(house));
        self
    }

    /// Termine ; refuse une scène sans aucune couche.
    pub fn build(self) -> Result<StaticScene, GenError> {
        let mut layers: Vec<CompositeLayer> = Vec::new();
        if let Some(g) = &self.ground {
            layers.push(CompositeLayer::new(Arc::new(g.clone()), CompositeMode::Overlay));
        }
        for m in &self.models {
            layers.push(CompositeLayer::new(m.clone(), CompositeMode::Overlay));
        }
        for p in &self.plans {
            layers.push(CompositeLayer::new(p.clone(), CompositeMode::Overlay));
        }
        for h in &self.houses {
            layers.push(CompositeLayer::new(h.clone(), CompositeMode::Overlay));
        }
        let composite = CompositeSource::new(layers).map_err(|e| GenError::BadParams(e.to_string()))?;
        Ok(StaticScene {
            ground: self.ground,
            models: self.models,
            plans: self.plans,
            houses: self.houses,
            composite,
        })
    }
}

/// Scène statique : sol plat et modèles posés.
pub struct StaticScene {
    ground: Option<FlatSource>,
    models: Vec<Arc<PlacedModel>>,
    plans: Vec<Arc<PlacedPlan>>,
    houses: Vec<Arc<PlacedHouse>>,
    composite: CompositeSource,
}

impl StaticScene {
    /// Début de construction.
    pub fn builder() -> StaticSceneBuilder {
        StaticSceneBuilder::default()
    }

    /// Scène « un arbre sur un sol plat de turf » : le pied du tronc est posé sur le sol (`y = 0`, sol sous 0).
    pub fn tree_on_turf(model: PlacedModel) -> Result<Self, GenError> {
        Self::builder().turf_ground(0).place(model).build()
    }

    /// Hauteur du sol plat (voxels de niveau 0), s'il y en a un.
    pub fn ground_height(&self) -> Option<i32> {
        self.ground.as_ref().map(FlatSource::height)
    }

    /// Modèles posés, dans l'ordre de pose.
    pub fn models(&self) -> impl Iterator<Item = &PlacedModel> + '_ {
        self.models.iter().map(Arc::as_ref)
    }

    /// Plans de générateur posés, dans l'ordre de pose.
    pub fn plans(&self) -> impl Iterator<Item = &PlacedPlan> + '_ {
        self.plans.iter().map(Arc::as_ref)
    }

    /// Maisons posées, dans l'ordre de pose.
    pub fn houses(&self) -> impl Iterator<Item = &PlacedHouse> + '_ {
        self.houses.iter().map(Arc::as_ref)
    }

    /// Union des boîtes des modèles au niveau `lod`, `None` sans modèle.
    pub fn models_bounds(&self, lod: Lod) -> Option<VoxelBox> {
        let mut it = self
            .models
            .iter()
            .map(|m| m.bounds(lod))
            .filter(|b| !b.is_empty());
        let premier = it.next()?;
        let (mut lo, mut hi) = (premier.min(), premier.max());
        for b in it {
            lo = VoxelCoord::new(lo.x.min(b.min().x), lo.y.min(b.min().y), lo.z.min(b.min().z));
            hi = VoxelCoord::new(hi.x.max(b.max().x), hi.y.max(b.max().y), hi.z.max(b.max().z));
        }
        VoxelBox::new(lo, hi).ok()
    }
}

impl VoxelSource for StaticScene {
    fn fill_chunk(&self, key: ChunkKey, lod: Lod, out: &mut Chunk) {
        self.composite.fill_chunk(key, lod, out);
    }

    fn classify(&self, key: ChunkKey, lod: Lod) -> ChunkHint {
        self.composite.classify(key, lod)
    }

    fn version_tag(&self) -> u64 {
        let mut h = hash_combine(0x5354_5343, self.composite.version_tag());
        h = hash_combine(h, self.models.len() as u64);
        h = hash_combine(h, self.plans.len() as u64);
        hash_combine(h, self.houses.len() as u64)
    }
}
