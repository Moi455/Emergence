//! Grille dense d'un plan de bâti et sa pyramide de niveaux de détail.
//!
//! Une recette remplit une `PlanGrid` (repère local, voxels de 5 cm) ; `DensePlan` en tire les niveaux 0 à 5 par
//! la règle 4/8 d'`em_voxel` (la même que la réduction des chunks), donc l'occupation d'un niveau grossier est
//! celle de la réduction des voxels fins (docs/19 § 3.8). `DensePlan` implémente `GenPlan`.

use em_core::{Fnv64, Lod, MaterialId, VoxelBox, VoxelCoord, VoxelValue, floor_div};
use em_voxel::{PutMode, ReduceRule, VoxelSink};

use crate::error::GenError;
use crate::generator::GenPlan;

/// Dernier niveau de détail servi (les LOD vont de 0 à 5 comme les modèles `.vxm`).
pub const MAX_LOD: Lod = 5;

/// Grille dense de voxels : une boîte de voxels et leurs valeurs. L'air hors de la boîte.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlanGrid {
    bounds: VoxelBox,
    size: [usize; 3],
    cells: Vec<VoxelValue>,
}

impl PlanGrid {
    /// Grille d'air couvrant `bounds` ; refuse une boîte vide ou de plus de 16 millions de voxels.
    pub fn new(bounds: VoxelBox) -> Result<Self, GenError> {
        if bounds.is_empty() {
            return Err(GenError::BadParams("grille de plan vide".into()));
        }
        let [sx, sy, sz] = bounds.size();
        let volume = sx
            .checked_mul(sy)
            .and_then(|v| v.checked_mul(sz))
            .unwrap_or(i64::MAX);
        if volume > 16_000_000 {
            return Err(GenError::BadParams(format!(
                "plan trop grand : {sx} x {sy} x {sz} voxels (16 millions au plus)"
            )));
        }
        Ok(Self {
            bounds,
            size: [sx as usize, sy as usize, sz as usize],
            cells: vec![VoxelValue::AIR; volume as usize],
        })
    }

    /// Boîte de la grille.
    pub const fn bounds(&self) -> VoxelBox {
        self.bounds
    }

    fn index(&self, v: VoxelCoord) -> Option<usize> {
        if !self.bounds.contains(v) {
            return None;
        }
        let m = self.bounds.min();
        let (x, y, z) = ((v.x - m.x) as usize, (v.y - m.y) as usize, (v.z - m.z) as usize);
        Some(x + self.size[0] * (z + self.size[2] * y))
    }

    /// Valeur d'un voxel (air hors de la boîte).
    pub fn get(&self, v: VoxelCoord) -> VoxelValue {
        self.index(v).map_or(VoxelValue::AIR, |i| self.cells[i])
    }

    /// Écrit un voxel ; renvoie faux (sans rien écrire) hors de la boîte.
    pub fn set(&mut self, v: VoxelCoord, value: VoxelValue) -> bool {
        match self.index(v) {
            Some(i) => {
                self.cells[i] = value;
                true
            }
            None => false,
        }
    }

    /// Nombre de voxels qui ne sont pas de l'air.
    pub fn solid_count(&self) -> usize {
        self.cells.iter().filter(|c| !c.is_air()).count()
    }

    /// Tous les voxels pleins, dans l'ordre (y, z, x).
    pub fn solids(&self) -> impl Iterator<Item = (VoxelCoord, VoxelValue)> + '_ {
        let m = self.bounds.min();
        let [sx, _, sz] = self.size;
        self.cells
            .iter()
            .enumerate()
            .filter(|(_, c)| !c.is_air())
            .map(move |(i, c)| {
                let (x, rest) = (i % sx, i / sx);
                let (z, y) = (rest % sz, rest / sz);
                (
                    VoxelCoord::new(m.x + x as i32, m.y + y as i32, m.z + z as i32),
                    *c,
                )
            })
    }

    /// Empreinte FNV-64 : boîte, puis chaque voxel plein dans l'ordre (y, z, x).
    pub fn fingerprint(&self) -> u64 {
        let mut h = Fnv64::new();
        let (a, b) = (self.bounds.min(), self.bounds.max());
        for c in [a.x, a.y, a.z, b.x, b.y, b.z] {
            h.add_u64(i64::from(c) as u64);
        }
        for (v, value) in self.solids() {
            for c in [v.x, v.y, v.z] {
                h.add_u64(i64::from(c) as u64);
            }
            h.add_u64(u64::from(value.raw()));
        }
        h.value()
    }

    /// Réduit de moitié par la règle 4/8 : chaque voxel du niveau suivant résume 2 x 2 x 2 voxels.
    fn reduced(&self, rule: &ReduceRule) -> Result<PlanGrid, GenError> {
        let (a, b) = (self.bounds.min(), self.bounds.max());
        let bas = |v: i32| floor_div(i64::from(v), 2) as i32;
        let haut = |v: i32| floor_div(i64::from(v) - 1, 2) as i32 + 1;
        let boite = VoxelBox::new(
            VoxelCoord::new(bas(a.x), bas(a.y), bas(a.z)),
            VoxelCoord::new(haut(b.x), haut(b.y), haut(b.z)),
        )
        .map_err(|e| GenError::BadParams(e.to_string()))?;
        let mut sortie = PlanGrid::new(boite)?;
        let m = boite.min();
        let n = boite.max();
        for y in m.y..n.y {
            for z in m.z..n.z {
                for x in m.x..n.x {
                    // ordre attendu par `reduce8` : x, puis z, puis y
                    let huit: [VoxelValue; 8] = std::array::from_fn(|k| {
                        let (dx, dz, dy) = ((k & 1) as i32, ((k >> 1) & 1) as i32, (k >> 2) as i32);
                        self.get(VoxelCoord::new(2 * x + dx, 2 * y + dy, 2 * z + dz))
                    });
                    sortie.set(VoxelCoord::new(x, y, z), rule.reduce8(huit));
                }
            }
        }
        Ok(sortie)
    }
}

/// Plan matérialisé : les six niveaux de détail d'une grille.
#[derive(Clone, Debug)]
pub struct DensePlan {
    levels: Vec<PlanGrid>,
}

impl DensePlan {
    /// Bâtit la pyramide ; `priority` ordonne les matières à égalité dans la règle 4/8 (sans doublon).
    pub fn new(grid: PlanGrid, priority: Vec<MaterialId>) -> Result<Self, GenError> {
        let rule = ReduceRule::majority_4_of_8(priority)
            .ok_or_else(|| GenError::BadParams("priorité de réduction avec un doublon".into()))?;
        let mut levels = vec![grid];
        for _ in 0..MAX_LOD {
            let suivant = levels.last().expect("au moins un niveau").reduced(&rule)?;
            levels.push(suivant);
        }
        Ok(Self { levels })
    }

    /// La grille d'un niveau (`None` au-delà du LOD 5).
    pub fn level(&self, lod: Lod) -> Option<&PlanGrid> {
        self.levels.get(usize::from(lod))
    }

    /// Empreinte du niveau 0 (la vérité ; les autres en dérivent).
    pub fn fingerprint(&self) -> u64 {
        self.levels[0].fingerprint()
    }
}

impl GenPlan for DensePlan {
    fn bounds(&self, lod: Lod) -> VoxelBox {
        match self.level(lod) {
            Some(g) => g.bounds(),
            None => {
                let o = self.levels[0].bounds().min();
                VoxelBox::new(o, o).expect("boîte vide valide")
            }
        }
    }

    fn rasterize(&self, lod: Lod, window: VoxelBox, sink: &mut dyn VoxelSink) {
        let Some(g) = self.level(lod) else { return };
        let (a, b, w0, w1) = (g.bounds().min(), g.bounds().max(), window.min(), window.max());
        let lo = VoxelCoord::new(a.x.max(w0.x), a.y.max(w0.y), a.z.max(w0.z));
        let hi = VoxelCoord::new(b.x.min(w1.x), b.y.min(w1.y), b.z.min(w1.z));
        for y in lo.y..hi.y {
            for z in lo.z..hi.z {
                for x in lo.x..hi.x {
                    let v = VoxelCoord::new(x, y, z);
                    let value = g.get(v);
                    if !value.is_air() {
                        sink.put(v, value, PutMode::Solid);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn boite(a: [i32; 3], b: [i32; 3]) -> VoxelBox {
        VoxelBox::new(
            VoxelCoord::new(a[0], a[1], a[2]),
            VoxelCoord::new(b[0], b[1], b[2]),
        )
        .unwrap()
    }

    #[test]
    fn grille_lecture_ecriture_et_bornes() {
        let mut g = PlanGrid::new(boite([-2, 0, 0], [3, 2, 2])).unwrap();
        let v = VoxelValue::new(MaterialId::new(20), 5);
        assert!(g.set(VoxelCoord::new(-2, 1, 1), v));
        assert!(!g.set(VoxelCoord::new(3, 0, 0), v));
        assert_eq!(g.get(VoxelCoord::new(-2, 1, 1)), v);
        assert!(g.get(VoxelCoord::new(99, 0, 0)).is_air());
        assert_eq!(g.solid_count(), 1);
        assert!(PlanGrid::new(boite([0, 0, 0], [0, 5, 5])).is_err());
    }

    #[test]
    fn la_pyramide_garde_l_occupation_des_blocs_pleins() {
        let mut g = PlanGrid::new(boite([0, 0, 0], [8, 8, 8])).unwrap();
        let v = VoxelValue::new(MaterialId::new(20), 1);
        for y in 0..8 {
            for z in 0..8 {
                for x in 0..8 {
                    g.set(VoxelCoord::new(x, y, z), v);
                }
            }
        }
        let p = DensePlan::new(g, vec![MaterialId::new(20)]).unwrap();
        assert_eq!(p.level(1).unwrap().solid_count(), 64);
        assert_eq!(p.level(2).unwrap().solid_count(), 8);
        assert_eq!(p.level(3).unwrap().solid_count(), 1);
        assert!(p.bounds(9).is_empty());
    }

    #[test]
    fn deux_constructions_donnent_la_meme_empreinte() {
        let faire = || {
            let mut g = PlanGrid::new(boite([0, 0, 0], [5, 5, 5])).unwrap();
            g.set(VoxelCoord::new(1, 2, 3), VoxelValue::new(MaterialId::new(15), 7));
            g.fingerprint()
        };
        assert_eq!(faire(), faire());
    }
}
