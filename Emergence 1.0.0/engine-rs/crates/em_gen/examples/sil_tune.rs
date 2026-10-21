//! Réglage de la silhouette : meilleure (enveloppe, densité) par essence au niveau 3.
use std::collections::BTreeSet;
use std::sync::Arc;

use em_core::VoxelCoord;
use em_gen::vegetation::extra::silhouette_plan_reglee;
use em_gen::vegetation::measure::GridSink;
use em_gen::vegetation::{Season, SpeciesTable, TreeGenerator, TreeParams};
use em_gen::{GenPlan, Generator, VxmClasses};

fn occ(plan: &dyn GenPlan) -> BTreeSet<(i32, i32, i32)> {
    let b = plan.bounds(3);
    let mut g = GridSink::new(b);
    plan.rasterize(3, b, &mut g);
    let (m, x) = (b.min(), b.max());
    let mut s = BTreeSet::new();
    for y in m.y..x.y {
        for z in m.z..x.z {
            for a in m.x..x.x {
                if !g.get(VoxelCoord::new(a, y, z)).is_air() {
                    s.insert((a, y, z));
                }
            }
        }
    }
    s
}

fn main() {
    let table = Arc::new(SpeciesTable::embedded());
    let c = VxmClasses::standard();
    let arbre = TreeGenerator::new(table.clone(), c);
    for cle in ["chene", "hetre", "bouleau", "epicea", "peuplier", "pin", "erable"] {
        let sp = table.get(cle).unwrap();
        let p = TreeParams {
            species: cle.into(),
            height_mm: 15_000,
            season: Season::Summer,
            leaf_density_permille: 1000,
        };
        let ref_: Vec<_> = (0..6_u64)
            .map(|s| occ(arbre.plan(&p.to_params().unwrap(), s).unwrap().as_ref()))
            .collect();
        let mut best = (0.0, 0, 0);
        for env in (40..=110).step_by(10) {
            for dens in [30_i64, 60, 100, 150, 250] {
                let mut somme = 0.0;
                for (s, a) in ref_.iter().enumerate() {
                    let sil = silhouette_plan_reglee(
                        sp,
                        15 * 20 * 65536,
                        Season::Summer,
                        s as u64,
                        &c,
                        65536 * env / 100,
                        65536 * dens / 100,
                    )
                    .unwrap();
                    let b = occ(&sil);
                    somme += a.intersection(&b).count() as f64 / a.union(&b).count() as f64;
                }
                let iou = somme / 6.0;
                if iou > best.0 {
                    best = (iou, env, dens);
                }
            }
        }
        println!(
            "{cle}: IoU {:.3} avec enveloppe {} % densité {}",
            best.0, best.1, best.2
        );
    }
}
