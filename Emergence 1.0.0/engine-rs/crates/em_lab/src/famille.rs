//! Les scènes des familles bâtiments, props et rochers (L35 à L37) : mêmes rendus que « maison », colorées en mode
//! `VoxelPixel` (un voxel = une couleur plate) avec des classes émissives (flamme, braise) rendues lumineuses.

use em_core::{Lod, VoxelCoord, VoxelValue};
use em_material::MaterialTable;
use em_mesh::{VoxelAppearance, VoxelColorer};

/// Noms des scènes de ces familles.
pub const SCENES_FAMILLES: [&str; 3] = ["batiments", "props", "rochers"];

/// Vrai si `nom` est une scène de ces familles.
pub fn est_famille(nom: &str) -> bool {
    SCENES_FAMILLES.contains(&nom)
}

/// Enveloppe un colorieur : les classes dont `emission` est positive deviennent émissives.
pub struct EmissifColorer<'a> {
    base: &'a dyn VoxelColorer,
    emissive: Vec<bool>,
}

impl<'a> EmissifColorer<'a> {
    /// Repère les classes émissives de la table.
    pub fn new(base: &'a dyn VoxelColorer, table: &MaterialTable) -> Self {
        let mut emissive = vec![false; em_material::CLASS_COUNT];
        for def in table.iter() {
            emissive[usize::from(def.id().get())] = def.render().emission().raw() > 0;
        }
        Self { base, emissive }
    }
}

impl VoxelColorer for EmissifColorer<'_> {
    fn appearance(&self, value: VoxelValue, voxel: VoxelCoord, lod: Lod) -> VoxelAppearance {
        let mut a = self.base.appearance(value, voxel, lod);
        a.emissive = self.emissive[usize::from(value.material().get())];
        a
    }

    fn is_foliage(&self, value: VoxelValue) -> bool {
        self.base.is_foliage(value)
    }
}
