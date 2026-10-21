//! La FENÊTRE de rastérisation : un tampon dense, borné, de la boîte demandée (au plus quelques chunks), dans lequel les
//! parties d'un plan peignent À TOUR DE RÔLE. Ce n'est jamais une grille du bâtiment entier : le plan ne garde que la
//! recette ; les voxels n'existent que le temps d'une fenêtre.
//!
//! Écrire de l'air creuse (porte, fenêtre, fumée) ; lire rend ce qu'une partie précédente a peint (« ne pose que sur
//! du vide », « garde ce qui est là »). Toute écriture hors de la fenêtre est ignorée : une partie peut donc itérer
//! sur son domaine sans connaître le découpage en chunks, et le résultat ne dépend pas de la fenêtre.

use em_core::{VoxelBox, VoxelCoord, VoxelValue};

/// Tampon dense d'une boîte de voxels.
#[derive(Clone, Debug)]
pub struct Window {
    min: [i32; 3],
    max: [i32; 3],
    taille: [usize; 3],
    cellules: Vec<VoxelValue>,
}

impl Window {
    /// Fenêtre d'air couvrant `boite`.
    pub fn new(boite: VoxelBox) -> Self {
        let (a, b) = (boite.min(), boite.max());
        let taille = [
            (b.x - a.x).max(0) as usize,
            (b.y - a.y).max(0) as usize,
            (b.z - a.z).max(0) as usize,
        ];
        Self {
            min: [a.x, a.y, a.z],
            max: [b.x, b.y, b.z],
            taille,
            cellules: vec![VoxelValue::AIR; taille[0] * taille[1] * taille[2]],
        }
    }

    /// Boîte couverte.
    pub fn bounds(&self) -> VoxelBox {
        VoxelBox::new(
            VoxelCoord::new(self.min[0], self.min[1], self.min[2]),
            VoxelCoord::new(self.max[0], self.max[1], self.max[2]),
        )
        .expect("fenêtre valide")
    }

    /// Coin minimal.
    pub const fn min(&self) -> [i32; 3] {
        self.min
    }

    /// Coin maximal (exclu).
    pub const fn max(&self) -> [i32; 3] {
        self.max
    }

    #[inline]
    fn index(&self, x: i32, y: i32, z: i32) -> Option<usize> {
        if x < self.min[0]
            || x >= self.max[0]
            || y < self.min[1]
            || y >= self.max[1]
            || z < self.min[2]
            || z >= self.max[2]
        {
            return None;
        }
        let (dx, dy, dz) = (
            (x - self.min[0]) as usize,
            (y - self.min[1]) as usize,
            (z - self.min[2]) as usize,
        );
        Some(dx + self.taille[0] * (dz + self.taille[2] * dy))
    }

    /// Valeur d'un voxel (air hors de la fenêtre).
    #[inline]
    pub fn get(&self, x: i32, y: i32, z: i32) -> VoxelValue {
        self.index(x, y, z).map_or(VoxelValue::AIR, |i| self.cellules[i])
    }

    /// Pose un voxel (de l'air creuse) ; ignoré hors de la fenêtre.
    #[inline]
    pub fn put(&mut self, x: i32, y: i32, z: i32, v: VoxelValue) {
        if let Some(i) = self.index(x, y, z) {
            self.cellules[i] = v;
        }
    }

    /// Creuse un voxel.
    #[inline]
    pub fn carve(&mut self, x: i32, y: i32, z: i32) {
        self.put(x, y, z, VoxelValue::AIR);
    }

    /// Pose seulement si le voxel est vide.
    #[inline]
    pub fn put_if_empty(&mut self, x: i32, y: i32, z: i32, v: VoxelValue) {
        if let Some(i) = self.index(x, y, z)
            && self.cellules[i].is_air()
        {
            self.cellules[i] = v;
        }
    }

    /// Intersection de la boîte `[x0,x1) x [y0,y1) x [z0,z1)` avec la fenêtre : `(lo, hi)` ou `None` si vide.
    pub fn clip(&self, lo: [i32; 3], hi: [i32; 3]) -> Option<([i32; 3], [i32; 3])> {
        let a = [
            lo[0].max(self.min[0]),
            lo[1].max(self.min[1]),
            lo[2].max(self.min[2]),
        ];
        let b = [
            hi[0].min(self.max[0]),
            hi[1].min(self.max[1]),
            hi[2].min(self.max[2]),
        ];
        (a[0] < b[0] && a[1] < b[1] && a[2] < b[2]).then_some((a, b))
    }

    /// Remplit une boîte (bornes demi-ouvertes) d'une valeur constante.
    pub fn fill(&mut self, lo: [i32; 3], hi: [i32; 3], v: VoxelValue) {
        if let Some((a, b)) = self.clip(lo, hi) {
            for y in a[1]..b[1] {
                for z in a[2]..b[2] {
                    for x in a[0]..b[0] {
                        self.put(x, y, z, v);
                    }
                }
            }
        }
    }

    /// Parcourt les voxels pleins, dans l'ordre (y, z, x).
    pub fn solids(&self) -> impl Iterator<Item = (VoxelCoord, VoxelValue)> + '_ {
        let [sx, _, sz] = self.taille;
        self.cellules
            .iter()
            .enumerate()
            .filter(|(_, c)| !c.is_air())
            .map(move |(i, c)| {
                let (x, reste) = (i % sx, i / sx);
                let (z, y) = (reste % sz, reste / sz);
                (
                    VoxelCoord::new(
                        self.min[0] + x as i32,
                        self.min[1] + y as i32,
                        self.min[2] + z as i32,
                    ),
                    *c,
                )
            })
    }

    /// Nombre de voxels pleins.
    pub fn solid_count(&self) -> usize {
        self.cellules.iter().filter(|c| !c.is_air()).count()
    }

    /// Vrai si la fenêtre ne contient aucun voxel plein.
    pub fn is_empty(&self) -> bool {
        self.cellules.iter().all(|c| c.is_air())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use em_core::MaterialId;

    fn boite(a: [i32; 3], b: [i32; 3]) -> VoxelBox {
        VoxelBox::new(
            VoxelCoord::new(a[0], a[1], a[2]),
            VoxelCoord::new(b[0], b[1], b[2]),
        )
        .unwrap()
    }

    #[test]
    fn ecriture_hors_fenetre_ignoree_et_air_creuse() {
        let mut w = Window::new(boite([0, 0, 0], [4, 4, 4]));
        let v = VoxelValue::new(MaterialId::new(20), 3);
        w.put(1, 1, 1, v);
        w.put(9, 9, 9, v);
        assert_eq!(w.solid_count(), 1);
        w.carve(1, 1, 1);
        assert!(w.is_empty());
        w.fill([-3, 0, 0], [2, 1, 1], v);
        assert_eq!(w.solid_count(), 2);
        w.put_if_empty(0, 0, 0, VoxelValue::new(MaterialId::new(15), 0));
        assert_eq!(w.get(0, 0, 0), v);
    }
}
