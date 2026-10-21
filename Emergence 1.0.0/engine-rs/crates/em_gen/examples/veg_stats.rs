//! Mesures de parité : `cargo run --release -p em_gen --example veg_stats -- chene 20 [hauteur_m]`.
use std::sync::Arc;
use std::time::Instant;

use em_gen::vegetation::measure::measure;
use em_gen::vegetation::{BushGenerator, BushParams, Season, SpeciesTable, TreeGenerator, TreeParams};
use em_gen::{Generator, VxmClasses};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let cle = args.get(1).map_or("chene", String::as_str);
    let n: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(5);
    let h_mm: u32 = args
        .get(3)
        .and_then(|s| s.parse::<f64>().ok())
        .map_or(0, |m| (m * 1000.0) as u32);
    let table = Arc::new(SpeciesTable::embedded());
    let sp = table.get(cle).expect("essence");
    let classes = VxmClasses::standard();
    for seed in 0..n {
        let tp = TreeParams {
            species: cle.into(),
            height_mm: h_mm,
            season: Season::Summer,
            leaf_density_permille: 1000,
        };
        let (generator, params): (Box<dyn Generator>, _) = if sp.is_bush() {
            (
                Box::new(BushGenerator::new(table.clone(), classes)),
                BushParams {
                    plant: tp,
                    topiary: None,
                }
                .to_params()
                .unwrap(),
            )
        } else {
            (
                Box::new(TreeGenerator::new(table.clone(), classes)),
                tp.to_params().unwrap(),
            )
        };
        let t0 = Instant::now();
        let plan = generator.plan(&params, seed).expect("plan");
        let t_plan = t0.elapsed();
        let t1 = Instant::now();
        let m = measure(plan.as_ref(), 0, &classes);
        let t_r = t1.elapsed();
        println!(
            "{cle} graine {seed} : plan {:.1} ms, raster+mesure {:.0} ms, voxels {}, feuilles {} ({:.1} %), boîte {:?}",
            t_plan.as_secs_f64() * 1e3,
            t_r.as_secs_f64() * 1e3,
            m.voxels,
            m.leaf,
            100.0 * m.leaf as f64 / m.voxels.max(1) as f64,
            m.extent
        );
    }
}
