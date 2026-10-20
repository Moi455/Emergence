//! Un niveau de détail d'un modèle : voxels pleins triés par (y, z, x), repère local (pivot = (0, 0, 0)).

use em_core::{VoxelBox, VoxelCoord, floor_div};

use super::kind::VxmKind;
use crate::error::VxmError;

/// Un voxel plein du fichier : position relative au coin de la boîte du niveau, sorte et variante de teinte.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub(crate) struct Cell {
    pub x: u16,
    pub y: u16,
    pub z: u16,
    pub kind: VxmKind,
    pub variant: u8,
}

/// Niveau de détail d'un modèle : lu dans le fichier ou **dérivé** du niveau plus fin quand le fichier ne l'a pas.
#[derive(Clone, Debug)]
pub struct LodLayer {
    source: u8,
    derived: bool,
    min: [i32; 3],
    dims: [u32; 3],
    cells: Vec<Cell>,
}

impl LodLayer {
    /// Niveau lu dans le fichier. Les cellules sont déjà validées (ordre, bornes) par le lecteur.
    pub(super) fn from_file(lod: u8, min: [i32; 3], dims: [u32; 3], cells: Vec<Cell>) -> Self {
        Self {
            source: lod,
            derived: false,
            min,
            dims,
            cells,
        }
    }

    /// Niveau `lod` obtenu en réduisant ce niveau plus fin de `ecart` crans : une cellule du niveau grossier est
    /// pleine si l'un de ses `2^ecart` cubes fins l'est ; en cas de conflit la sorte la plus prioritaire gagne.
    /// Le pivot (0, 0, 0) du niveau fin devient le pivot (0, 0, 0) du niveau grossier (`floor_div`).
    pub(super) fn reduced(&self, lod: u8, ecart: u32) -> Result<Self, VxmError> {
        let pas = 1_i64 << ecart;
        let abs = |c: &Cell| {
            [
                floor_div(i64::from(self.min[0]) + i64::from(c.x), pas),
                floor_div(i64::from(self.min[1]) + i64::from(c.y), pas),
                floor_div(i64::from(self.min[2]) + i64::from(c.z), pas),
            ]
        };
        let mut min = [i64::MAX; 3];
        let mut max = [i64::MIN; 3];
        for c in &self.cells {
            let a = abs(c);
            for i in 0..3 {
                min[i] = min[i].min(a[i]);
                max[i] = max[i].max(a[i]);
            }
        }
        if self.cells.is_empty() {
            return Ok(Self {
                source: lod,
                derived: true,
                min: [0; 3],
                dims: [0; 3],
                cells: Vec::new(),
            });
        }
        let dims = [
            (max[0] - min[0] + 1) as u32,
            (max[1] - min[1] + 1) as u32,
            (max[2] - min[2] + 1) as u32,
        ];
        let mut cells: Vec<Cell> = self
            .cells
            .iter()
            .map(|c| {
                let a = abs(c);
                Cell {
                    x: (a[0] - min[0]) as u16,
                    y: (a[1] - min[1]) as u16,
                    z: (a[2] - min[2]) as u16,
                    kind: c.kind,
                    variant: c.variant,
                }
            })
            .collect();
        cells.sort_unstable_by_key(|c| (c.y, c.z, c.x, c.kind.priority()));
        cells.dedup_by(|b, a| (a.y, a.z, a.x) == (b.y, b.z, b.x));
        Ok(Self {
            source: lod,
            derived: true,
            min: [min[0] as i32, min[1] as i32, min[2] as i32],
            dims,
            cells,
        })
    }

    /// Niveau de détail que ce niveau représente.
    pub const fn lod(&self) -> u8 {
        self.source
    }

    /// Vrai si le niveau a été dérivé d'un niveau plus fin (repli).
    pub const fn is_derived(&self) -> bool {
        self.derived
    }

    /// Nombre de voxels pleins.
    pub fn voxel_count(&self) -> usize {
        self.cells.len()
    }

    /// Boîte locale du niveau (pivot = (0, 0, 0)), en voxels du niveau.
    pub fn bounds(&self) -> VoxelBox {
        let max = [
            self.min[0] + self.dims[0] as i32,
            self.min[1] + self.dims[1] as i32,
            self.min[2] + self.dims[2] as i32,
        ];
        VoxelBox::new(
            VoxelCoord::new(self.min[0], self.min[1], self.min[2]),
            VoxelCoord::new(max[0], max[1], max[2]),
        )
        .expect("dimensions positives : boîte valide")
    }

    /// Mémoire occupée par les voxels, en octets.
    pub fn memory_bytes(&self) -> usize {
        self.cells.len() * std::mem::size_of::<Cell>()
    }

    pub(crate) fn cells(&self) -> &[Cell] {
        &self.cells
    }

    /// Position locale (pivot = origine) d'une cellule.
    pub(crate) fn local_of(&self, c: &Cell) -> [i32; 3] {
        [
            self.min[0] + i32::from(c.x),
            self.min[1] + i32::from(c.y),
            self.min[2] + i32::from(c.z),
        ]
    }

    /// Cellules dont la position locale est dans `[lo, hi)` : coupe en y par recherche dichotomique
    /// (les cellules sont triées par y), puis filtre x et z.
    pub(crate) fn in_window(
        &self,
        lo: [i64; 3],
        hi: [i64; 3],
    ) -> impl Iterator<Item = ([i32; 3], &Cell)> + '_ {
        let rel = |v: i64, axe: usize| v - i64::from(self.min[axe]);
        let (ya, yb) = (rel(lo[1], 1), rel(hi[1], 1));
        let debut = self.cells.partition_point(|c| i64::from(c.y) < ya);
        let fin = self.cells.partition_point(|c| i64::from(c.y) < yb);
        let (xa, xb, za, zb) = (rel(lo[0], 0), rel(hi[0], 0), rel(lo[2], 2), rel(hi[2], 2));
        self.cells[debut..fin]
            .iter()
            .filter(move |c| (xa..xb).contains(&i64::from(c.x)) && (za..zb).contains(&i64::from(c.z)))
            .map(|c| (self.local_of(c), c))
    }
}
