//! `PlacedHouse` : une maison posée sur la grille monde, servie en lecture seule (`VoxelSource`).
//!
//! Repère : la grille du générateur est droitière (three.js : y haut, z vers le spectateur) ; le monde du labo est
//! gaucher (x est, y haut, z nord). Pour que la maison garde sa chiralité (façade vue de la caméra de la démo, cheminée
//! du même côté), l'axe z est INVERSÉ à la pose : `z_monde = ancre.z - (z_grille - z_ancre)`. `x` et `y` se décalent
//! seulement. La couche `ground_layers - 1` (herbe) tombe sous le plan `y = ancre.y`.

use std::sync::Arc;

use em_core::{ChunkKey, Lod, VoxelBox, VoxelCoord, VoxelValue, hash_combine};
use em_voxel::{Chunk, ChunkHint, ChunkWriter, VoxelSource};

use super::classes::HouseClasses;
use super::model::{VxhCell, VxhModel};

/// Une maison `.vxh` posée dans le monde (niveau 0 seulement : le laboratoire n'a qu'un niveau).
#[derive(Clone, Debug)]
pub struct PlacedHouse {
    model: Arc<VxhModel>,
    classes: HouseClasses,
    /// Cellule de la grille qui tombe sur `world_anchor` (x, niveau 0 des murs, z).
    grid_anchor: [u32; 3],
    world_anchor: VoxelCoord,
    bounds: VoxelBox,
}

impl PlacedHouse {
    /// Pose `model` : la cellule `(grid_anchor.x, ground_layers, grid_anchor.z)` de la grille devient `world_anchor`
    /// (le pied du mur à l'angle choisi, `world_anchor.y` étant le plan du sol). `grid_anchor` doit être dans la grille.
    pub fn new(
        model: Arc<VxhModel>,
        classes: HouseClasses,
        grid_anchor_xz: [u32; 2],
        world_anchor: VoxelCoord,
    ) -> Self {
        let [nx, ny, nz] = model.dims();
        let ax = grid_anchor_xz[0].min(nx - 1);
        let az = grid_anchor_xz[1].min(nz - 1);
        let sol = model.ground_layers().min(ny);
        // Boîte monde : x droit, y décalé, z inversé.
        let (ax, az, sol) = (i64::from(ax), i64::from(az), i64::from(sol));
        let mon = |v: i64| v as i32;
        let x0 = i64::from(world_anchor.x) - ax;
        let x1 = x0 + i64::from(nx);
        let y0 = i64::from(world_anchor.y) - sol;
        let y1 = y0 + i64::from(ny);
        let z_hi = i64::from(world_anchor.z) + az; // z_grille = 0
        let z_lo = z_hi - (i64::from(nz) - 1); // z_grille = nz - 1
        let bounds = VoxelBox::new(
            VoxelCoord::new(mon(x0), mon(y0), mon(z_lo)),
            VoxelCoord::new(mon(x1), mon(y1), mon(z_hi + 1)),
        )
        .expect("boîte de maison valide");
        Self {
            model,
            classes,
            grid_anchor: [ax as u32, sol as u32, az as u32],
            world_anchor,
            bounds,
        }
    }

    /// La maison chargée.
    pub fn model(&self) -> &Arc<VxhModel> {
        &self.model
    }

    /// Classes de matière utilisées.
    pub fn classes(&self) -> &HouseClasses {
        &self.classes
    }

    /// Boîte de la maison dans le monde (niveau 0, demi-ouverte).
    pub fn bounds(&self) -> VoxelBox {
        self.bounds
    }

    /// Coordonnées de grille d'un voxel monde (x droit, z inversé).
    pub fn grid_of(&self, w: VoxelCoord) -> [i64; 3] {
        [
            i64::from(w.x) - i64::from(self.world_anchor.x) + i64::from(self.grid_anchor[0]),
            i64::from(w.y) - i64::from(self.world_anchor.y) + i64::from(self.grid_anchor[1]),
            i64::from(self.grid_anchor[2]) - (i64::from(w.z) - i64::from(self.world_anchor.z)),
        ]
    }

    /// Voxel monde d'une cellule de grille.
    pub fn world_of(&self, g: [i64; 3]) -> VoxelCoord {
        VoxelCoord::new(
            (i64::from(self.world_anchor.x) + g[0] - i64::from(self.grid_anchor[0])) as i32,
            (i64::from(self.world_anchor.y) + g[1] - i64::from(self.grid_anchor[1])) as i32,
            (i64::from(self.world_anchor.z) - (g[2] - i64::from(self.grid_anchor[2]))) as i32,
        )
    }

    /// Cellule pleine au voxel monde `w` (couleur exacte du générateur, matériau, drapeaux), `None` hors de la maison
    /// ou dans le vide.
    pub fn cell_at(&self, w: VoxelCoord) -> Option<VxhCell> {
        if !self.bounds.contains(w) {
            return None;
        }
        let g = self.grid_of(w);
        self.model.cell(g[0], g[1], g[2])
    }

    /// Vrai si le voxel monde est du verre (même vide).
    pub fn is_glass_at(&self, w: VoxelCoord) -> bool {
        if !self.bounds.contains(w) {
            return false;
        }
        let g = self.grid_of(w);
        self.model.is_glass(g[0], g[1], g[2])
    }

    /// Valeur de voxel d'une cellule.
    pub fn value_of(&self, cell: VxhCell) -> VoxelValue {
        self.classes.value_of(cell)
    }
}

impl VoxelSource for PlacedHouse {
    fn fill_chunk(&self, key: ChunkKey, lod: Lod, out: &mut Chunk) {
        *out = Chunk::new_air();
        if lod != 0 || self.classify(key, lod) == ChunkHint::Air {
            return;
        }
        let o = key.origin();
        let (b0, b1) = (self.bounds.min(), self.bounds.max());
        let lo = |a: i32, b: i32| a.max(b);
        let hi = |a: i32, b: i32| (a + 64).min(b);
        let mut writer = ChunkWriter::new(out, key);
        for y in lo(o.y, b0.y)..hi(o.y, b1.y) {
            for z in lo(o.z, b0.z)..hi(o.z, b1.z) {
                for x in lo(o.x, b0.x)..hi(o.x, b1.x) {
                    let w = VoxelCoord::new(x, y, z);
                    if let Some(cell) = self.cell_at(w) {
                        writer.set(w, self.classes.value_of(cell));
                    }
                }
            }
        }
        writer.finish();
    }

    fn classify(&self, key: ChunkKey, lod: Lod) -> ChunkHint {
        let (o, m, n) = (key.origin(), self.bounds.max(), self.bounds.min());
        let disjoint = lod != 0
            || o.x + 64 <= n.x
            || o.x >= m.x
            || o.y + 64 <= n.y
            || o.y >= m.y
            || o.z + 64 <= n.z
            || o.z >= m.z;
        if disjoint {
            ChunkHint::Air
        } else {
            ChunkHint::Unknown
        }
    }

    fn version_tag(&self) -> u64 {
        let mut h = hash_combine(0x5658_4801, self.model.fingerprint());
        for v in [self.world_anchor.x, self.world_anchor.y, self.world_anchor.z] {
            h = hash_combine(h, i64::from(v) as u64);
        }
        for v in self.grid_anchor {
            h = hash_combine(h, u64::from(v));
        }
        h
    }
}
