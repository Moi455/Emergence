//! Nœuds par ordre d'un squelette, pour comparer au Python : `veg_orders hetre 15`.
use em_gen::vegetation::SpeciesTable;
use em_gen::vegetation::fx::{UN, VOX_PAR_M};
use em_gen::vegetation::skeleton::grow_skeleton;

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let t = SpeciesTable::embedded();
    let sp = t.get(&a[1]).unwrap();
    let h_m: f64 = a[2].parse().unwrap();
    const N: u64 = 100;
    let mut tot = [0_usize; 5];
    let mut leafy = 0;
    let mut bloom = 0;
    let mut tips = 0;
    for seed in 0..N {
        let sk = grow_skeleton(sp, (h_m * (VOX_PAR_M * UN) as f64) as i64, seed);
        for n in &sk.nodes {
            tot[n.order as usize] += 1;
        }
        leafy += sk.leafy.len();
        bloom += sk.bloom.len();
        tips += sk.leafy.iter().filter(|(i, _)| sk.nodes[*i].t >= 47_186).count()
            + sk.bloom.iter().filter(|i| sk.nodes[**i].t >= 47_186).count();
    }
    println!(
        "{:?} {} bloom {} bouts {}",
        tot.map(|x| x / N as usize),
        leafy / N as usize,
        bloom / N as usize,
        tips / N as usize
    );
}
