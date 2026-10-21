//! Parité STATISTIQUE du port Rust avec `voxel_tree.py` / `voxel_bush.py` (docs/19b L30, L31, L32) : sur 20 graines
//! par essence à la hauteur médiane, été, densité pleine. Les nombres du Python sont dans
//! `tests/data/parite_python.json` (produit par `tools/vegetation/parity_stats.py`). Seuils : nœuds ±10 %, boîte de
//! couronne ±5 %, voxels ±10 %, part de feuilles ±3 points. On porte la sémantique, pas les bits : la comparaison
//! porte sur les MOYENNES de 20 sujets.

use std::collections::BTreeMap;
use std::sync::Arc;

use em_gen::VxmClasses;
use em_gen::vegetation::measure::measure;
use em_gen::vegetation::{BushGenerator, BushParams, Season, SpeciesTable, TreeGenerator, TreeParams};
use serde::Deserialize;

#[derive(Deserialize)]
struct Sujet {
    nodes: u64,
    voxels: u64,
    leaf: u64,
    #[serde(rename = "box")]
    boite: [f64; 3],
}

#[derive(Deserialize)]
struct Espece {
    height: f64,
    seeds: Vec<Sujet>,
}

/// Moyenne entière des 20 sujets Rust : (nœuds, voxels, feuilles, largeur moyenne x/y en cm, hauteur en cm).
fn rust_moyennes(cle: &str, h_m: f64, n: u64) -> (f64, f64, f64, f64, f64) {
    let table = Arc::new(SpeciesTable::embedded());
    let sp = table.get(cle).unwrap();
    let classes = VxmClasses::standard();
    let tp = TreeParams {
        species: cle.into(),
        height_mm: (h_m * 1000.0).round() as u32,
        season: Season::Summer,
        leaf_density_permille: 1000,
    };
    let bush = BushGenerator::new(table.clone(), classes);
    let tree = TreeGenerator::new(table.clone(), classes);
    let params = if sp.is_bush() {
        BushParams {
            plant: tp,
            topiary: None,
        }
        .to_params()
        .unwrap()
    } else {
        tp.to_params().unwrap()
    };
    let (mut nodes, mut vox, mut feu, mut larg, mut haut) = (0.0, 0.0, 0.0, 0.0, 0.0);
    let (mut dbg_wood, mut dbg_fl, mut dbg_fr) = (0.0, 0.0, 0.0);
    for seed in 0..n {
        let plan = if sp.is_bush() {
            bush.plant_plan(&params, seed).unwrap()
        } else {
            tree.plant_plan(&params, seed).unwrap()
        };
        let m = measure(plan.as_ref(), 0, &classes);
        nodes += plan.stats().nodes as f64;
        vox += m.voxels as f64;
        feu += m.leaf as f64;
        larg += (m.extent[0] + m.extent[2]) as f64 / 2.0;
        dbg_wood += m.wood as f64;
        dbg_fl += m.flower as f64;
        dbg_fr += m.fruit as f64;
        haut += m.extent[1] as f64;
    }
    let n = n as f64;
    println!(
        "  [{cle}] bois {:.0} fleurs {:.0} fruits {:.0}",
        dbg_wood / n,
        dbg_fl / n,
        dbg_fr / n
    );
    (nodes / n, vox / n, feu / n, larg / n * 5.0, haut / n * 5.0)
}

/// Tolérances : voxels ±10 %, part de feuilles ±3 points, boîte ±6 % ; nœuds ±15 % (la moyenne de 20 graines d'un
/// squelette à queue lourde bouge de ±8 % d'un tirage à l'autre : sur 100 graines l'écart au Python est de 1 à 4 %).
fn compare(cle: &str, e: &Espece, rapport: &mut Vec<String>, echecs: &mut Vec<String>) {
    let n = e.seeds.len() as f64;
    let moy = |f: &dyn Fn(&Sujet) -> f64| e.seeds.iter().map(f).sum::<f64>() / n;
    let py_nodes = moy(&|s| s.nodes as f64);
    let py_vox = moy(&|s| s.voxels as f64);
    let py_leaf = moy(&|s| s.leaf as f64);
    let py_larg = moy(&|s| (s.boite[0] + s.boite[1]) / 2.0) * 100.0;
    let py_haut = moy(&|s| s.boite[2]) * 100.0;
    let (rn, rv, rl, rw, rh) = rust_moyennes(cle, e.height, e.seeds.len() as u64);
    let rel = |a: f64, b: f64| (a - b) / b * 100.0;
    let part_py = py_leaf / py_vox * 100.0;
    let part_rs = rl / rv * 100.0;
    let ok = rel(rn, py_nodes).abs() <= 15.0
        && rel(rv, py_vox).abs() <= 10.0
        && (part_rs - part_py).abs() <= 3.0
        && rel(rw, py_larg).abs() <= 6.0
        && rel(rh, py_haut).abs() <= 6.0;
    if !ok {
        echecs.push(cle.to_owned());
    }
    rapport.push(format!(
        "{cle:10} H={:5.2} m | nœuds {rn:8.0} / {py_nodes:8.0} ({:+5.1} %) | voxels {rv:9.0} / {py_vox:9.0} ({:+5.1} %) | feuilles {part_rs:5.1} / {part_py:5.1} pts ({:+4.1}) | larg {rw:5.0} / {py_larg:5.0} ({:+5.1} %) | haut {rh:5.0} / {py_haut:5.0} ({:+5.1} %)",
        e.height,
        rel(rn, py_nodes),
        rel(rv, py_vox),
        part_rs - part_py,
        rel(rw, py_larg),
        rel(rh, py_haut)
    ));
}

#[test]
fn parite_statistique_avec_le_python() {
    let json = include_str!("data/parite_python.json");
    let ref_py: BTreeMap<String, Espece> = serde_json::from_str(json).unwrap();
    assert!(ref_py.len() >= 16, "les 16 essences du Python");
    let mut rapport = Vec::new();
    let mut echecs = Vec::new();
    for (cle, e) in &ref_py {
        compare(cle, e, &mut rapport, &mut echecs);
    }
    for l in &rapport {
        println!("{l}");
    }
    assert!(echecs.is_empty(), "hors tolérance : {echecs:?}");
}
