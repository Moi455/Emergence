//! Coût de plan et de rastérisation par fenêtres de 64³ (1 fil et 8 fils) : `veg_bench chene 14 42`.
use std::sync::Arc;
use std::time::Instant;

use em_core::{VoxelBox, VoxelCoord, VoxelValue};
use em_gen::vegetation::{Season, SpeciesTable, TreeGenerator, TreeParams};
use em_gen::{GenPlan, Generator, VxmClasses};
use em_voxel::{PutMode, VoxelSink};

#[derive(Default)]
struct Compte(u64);
impl VoxelSink for Compte {
    fn put(&mut self, _: VoxelCoord, _: VoxelValue, _: PutMode) {
        self.0 += 1;
    }
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let cle = a.get(1).map_or("chene", String::as_str);
    let h: f64 = a.get(2).and_then(|s| s.parse().ok()).unwrap_or(14.0);
    let seed: u64 = a.get(3).and_then(|s| s.parse().ok()).unwrap_or(42);
    let g = TreeGenerator::new(Arc::new(SpeciesTable::embedded()), VxmClasses::standard());
    let p = TreeParams {
        species: cle.into(),
        height_mm: (h * 1000.0) as u32,
        season: Season::Summer,
        leaf_density_permille: a.get(4).and_then(|s| s.parse().ok()).unwrap_or(1000),
    };
    let params = p.to_params().unwrap();
    let t = Instant::now();
    let plan: Arc<dyn GenPlan> = g.plan(&params, seed).unwrap();
    println!("plan : {:.2} ms", t.elapsed().as_secs_f64() * 1e3);
    for lod in [0_u8, 1, 3] {
        let b = plan.bounds(lod);
        let (m, x) = (b.min(), b.max());
        let mut ws = Vec::new();
        for y in (m.y..x.y).step_by(64) {
            for z in (m.z..x.z).step_by(64) {
                for xx in (m.x..x.x).step_by(64) {
                    ws.push(
                        VoxelBox::new(
                            VoxelCoord::new(xx, y, z),
                            VoxelCoord::new((xx + 64).min(x.x), (y + 64).min(x.y), (z + 64).min(x.z)),
                        )
                        .unwrap(),
                    );
                }
            }
        }
        for fils in [1_usize, 8] {
            let t = Instant::now();
            let total: u64 = std::thread::scope(|s| {
                let hs: Vec<_> = ws
                    .chunks(ws.len().div_ceil(fils))
                    .map(|c| {
                        let plan = plan.clone();
                        s.spawn(move || {
                            let mut n = Compte::default();
                            for w in c {
                                plan.rasterize(lod, *w, &mut n);
                            }
                            n.0
                        })
                    })
                    .collect();
                hs.into_iter().map(|h| h.join().unwrap()).sum()
            });
            println!(
                "niveau {lod}, {fils} fil(s) : {:.1} ms, {} écritures, {} fenêtres",
                t.elapsed().as_secs_f64() * 1e3,
                total,
                ws.len()
            );
        }
    }
}
