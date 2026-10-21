//! Mesures d'un plan rastérisé en entier : sert aux essais de parité avec le Python, aux bancs et aux empreintes.

use em_core::{Fnv64, Lod, VoxelBox, VoxelCoord, VoxelValue};
use em_voxel::{PutMode, VoxelSink};

use crate::generator::GenPlan;
use crate::vxm::VxmClasses;

/// Puits dense : garde la dernière valeur écrite de chaque case d'une boîte.
pub struct GridSink {
    bounds: VoxelBox,
    size: [usize; 3],
    cells: Vec<u16>,
}

impl GridSink {
    /// Grille d'air sur `bounds`.
    pub fn new(bounds: VoxelBox) -> Self {
        let [sx, sy, sz] = bounds.size();
        let (sx, sy, sz) = (sx as usize, sy as usize, sz as usize);
        Self {
            bounds,
            size: [sx, sy, sz],
            cells: vec![0; sx * sy * sz],
        }
    }

    /// Valeur d'une case (air hors de la boîte).
    pub fn get(&self, v: VoxelCoord) -> VoxelValue {
        if !self.bounds.contains(v) {
            return VoxelValue::AIR;
        }
        let m = self.bounds.min();
        let (x, y, z) = ((v.x - m.x) as usize, (v.y - m.y) as usize, (v.z - m.z) as usize);
        VoxelValue::from_raw(self.cells[(y * self.size[2] + z) * self.size[0] + x])
    }
}

impl VoxelSink for GridSink {
    fn put(&mut self, at: VoxelCoord, value: VoxelValue, mode: PutMode) {
        if !self.bounds.contains(at) {
            return;
        }
        let m = self.bounds.min();
        let (x, y, z) = (
            (at.x - m.x) as usize,
            (at.y - m.y) as usize,
            (at.z - m.z) as usize,
        );
        let i = (y * self.size[2] + z) * self.size[0] + x;
        self.cells[i] = match mode {
            PutMode::Solid => value.raw(),
            PutMode::CarveAir => 0,
        };
    }
}

/// Mesures d'un sujet rastérisé.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Measure {
    /// Voxels pleins (chacun une fois).
    pub voxels: u64,
    /// Voxels de feuilles.
    pub leaf: u64,
    /// Voxels d'écorce et de rameaux.
    pub wood: u64,
    /// Voxels de fleurs.
    pub flower: u64,
    /// Voxels de fruits.
    pub fruit: u64,
    /// Boîte réellement occupée, en voxels (x est, y haut, z nord).
    pub extent: [i64; 3],
    /// Empreinte FNV-64 des voxels pleins (position et valeur), dans l'ordre y, z, x.
    pub fingerprint: u64,
}

/// Rastérise tout le niveau `lod` d'un plan d'un seul tenant et le mesure.
pub fn measure(plan: &dyn GenPlan, lod: Lod, classes: &VxmClasses) -> Measure {
    let b = plan.bounds(lod);
    let mut g = GridSink::new(b);
    plan.rasterize(lod, b, &mut g);
    let (m, mx) = (b.min(), b.max());
    let mut r = Measure {
        voxels: 0,
        leaf: 0,
        wood: 0,
        flower: 0,
        fruit: 0,
        extent: [0; 3],
        fingerprint: 0,
    };
    let mut lo = [i32::MAX; 3];
    let mut hi = [i32::MIN; 3];
    let mut h = Fnv64::new();
    let (leaf, bark, petal, fruit) = (
        classes.class_of(crate::vxm::VxmKind::Leaf),
        classes.class_of(crate::vxm::VxmKind::Bark),
        classes.class_of(crate::vxm::VxmKind::Flower),
        classes.class_of(crate::vxm::VxmKind::Fruit),
    );
    for y in m.y..mx.y {
        for z in m.z..mx.z {
            for x in m.x..mx.x {
                let v = g.get(VoxelCoord::new(x, y, z));
                if v.is_air() {
                    continue;
                }
                r.voxels += 1;
                match v.material() {
                    c if c == leaf => r.leaf += 1,
                    c if c == bark => r.wood += 1,
                    c if c == petal => r.flower += 1,
                    c if c == fruit => r.fruit += 1,
                    _ => {}
                }
                lo = [lo[0].min(x), lo[1].min(y), lo[2].min(z)];
                hi = [hi[0].max(x), hi[1].max(y), hi[2].max(z)];
                for c in [x, y, z] {
                    h.add_u64(i64::from(c) as u64);
                }
                h.add_u64(u64::from(v.raw()));
            }
        }
    }
    if r.voxels > 0 {
        r.extent = [
            i64::from(hi[0] - lo[0] + 1),
            i64::from(hi[1] - lo[1] + 1),
            i64::from(hi[2] - lo[2] + 1),
        ];
    }
    r.fingerprint = h.value();
    r
}
