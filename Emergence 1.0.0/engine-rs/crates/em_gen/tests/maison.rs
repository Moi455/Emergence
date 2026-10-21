//! Parité du port Rust de la maison avec le générateur JavaScript de Monsieur (`nouvelle référence.html`) : sur 20
//! graines, les entiers dérivés (paramètres, dimensions, portes, fenêtres, pièces, cloisons, meubles) doivent
//! être EXACTEMENT ceux du JavaScript (référence : `tools/maisons/ref_parite.mjs`).

use em_gen::batiments::maison::{HouseParams, planifier};
use serde_json::Value;

fn reference() -> Vec<Value> {
    let texte = include_str!("fixtures/maison_reference_js.json");
    serde_json::from_str(texte).expect("référence JSON")
}

#[test]
fn parametres_derives_comme_le_javascript() {
    for r in reference() {
        let graine = r["seed"].as_str().unwrap();
        let p = HouseParams::derive(graine);
        let j = &r["params"];
        assert_eq!(
            i64::from(p.stories),
            j["stories"].as_i64().unwrap(),
            "{graine} étages"
        );
        assert_eq!(
            i64::from(p.main.w),
            j["main"]["w"].as_i64().unwrap(),
            "{graine} largeur"
        );
        assert_eq!(
            i64::from(p.main.d),
            j["main"]["d"].as_i64().unwrap(),
            "{graine} profondeur"
        );
        assert_eq!(
            i64::from(p.wing.w),
            j["wing"]["w"].as_i64().unwrap(),
            "{graine} aile"
        );
        assert_eq!(i64::from(p.wing.len), j["wing"]["len"].as_i64().unwrap());
        assert_eq!(i64::from(p.wall.posts), j["wall"]["posts"].as_i64().unwrap());
        assert_eq!(i64::from(p.roof.eave), j["roof"]["eave"].as_i64().unwrap());
        assert_eq!(
            i64::from(p.roof.slope100),
            (j["roof"]["slope"].as_f64().unwrap() * 100.0).round() as i64
        );
        assert_eq!(i64::from(p.win.gap), j["win"]["gap"].as_i64().unwrap());
        assert_eq!(
            i64::from(p.win.lit100),
            (j["win"]["lit"].as_f64().unwrap() * 100.0).round() as i64
        );
        assert_eq!(
            i64::from(p.door.at100),
            (j["door"]["at"].as_f64().unwrap() * 100.0).round() as i64
        );
        assert_eq!(i64::from(p.deco.barrels), j["deco"]["barrels"].as_i64().unwrap());
        assert_eq!(p.shed, j["shed"].as_bool().unwrap());
    }
}

#[test]
fn plan_aux_memes_entiers_que_le_javascript() {
    let mut ecarts = Vec::new();
    for r in reference() {
        let graine = r["seed"].as_str().unwrap().to_owned();
        let plan = planifier(&HouseParams::derive(&graine));
        macro_rules! verifier {
            ($nom:expr, $rust:expr, $js:expr) => {{
                let (rust, js): (i64, i64) = ($rust, $js);
                if rust != js {
                    ecarts.push(format!("{graine} {} : Rust {rust}, JS {js}", $nom));
                }
            }};
        }
        verifier!("grille x", i64::from(plan.nx), r["grid"][0].as_i64().unwrap());
        verifier!("grille z", i64::from(plan.nz), r["grid"][2].as_i64().unwrap());
        verifier!("fenêtres", plan.wins.len() as i64, r["windows"].as_i64().unwrap());
        verifier!(
            "portes int.",
            plan.int_doors.len() as i64,
            r["doors_int"].as_i64().unwrap()
        );
        verifier!(
            "pièces",
            plan.rooms.len() as i64,
            r["rooms"].as_array().unwrap().len() as i64
        );
        verifier!(
            "meubles",
            i64::from(plan.n_furniture),
            r["furniture"].as_i64().unwrap()
        );
        verifier!("lits", i64::from(plan.n_beds), r["beds"].as_i64().unwrap());
        verifier!(
            "cuisines",
            i64::from(plan.n_kitchens),
            r["kitchens"].as_i64().unwrap()
        );
        verifier!("porte u0", i64::from(plan.du0), r["du0"].as_i64().unwrap());
        for (s, cuts) in r["cuts"].as_array().unwrap().iter().enumerate() {
            let js = cuts.as_array().unwrap();
            verifier!(
                &format!("cloisons étage {s}"),
                plan.cuts[s.min(1)].len() as i64,
                js.len() as i64
            );
            for (k, c) in js.iter().enumerate() {
                if let Some(rc) = plan.cuts[s.min(1)].get(k) {
                    let jc: Vec<i64> = c
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|v| v.as_i64().unwrap())
                        .collect();
                    let rv = [
                        rc.ax as i64,
                        rc.c0 as i64,
                        rc.c1 as i64,
                        rc.a0 as i64,
                        rc.a1 as i64,
                        rc.door as i64,
                    ];
                    if rv.to_vec() != jc {
                        ecarts.push(format!("{graine} cloison {s}/{k} : Rust {rv:?}, JS {jc:?}"));
                    }
                }
            }
        }
        for (i, q) in r["rooms"].as_array().unwrap().iter().enumerate() {
            if let Some(rr) = plan.rooms.get(i) {
                let n = q[2].as_i64().unwrap();
                if rr.cells.len() as i64 != n {
                    ecarts.push(format!("{graine} pièce {i} : Rust {}, JS {n}", rr.cells.len()));
                }
            }
        }
    }
    assert!(
        ecarts.is_empty(),
        "{} écarts :\n{}",
        ecarts.len(),
        ecarts.join("\n")
    );
}

/// Parité voxel par voxel (occupation) avec les `.vxh` cuits de `gravit` et `a` : écarts hors sol et hors plantes.
#[test]
fn occupation_comme_les_vxh_cuits() {
    use em_gen::VxhModel;
    use em_gen::batiments::{HouseConfig, HouseGenerator, Matieres};
    let dossier = std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
        .join(".local/share/emergence/lab_assets/maisons");
    for graine in ["gravit", "a"] {
        let Ok(vxh) = VxhModel::load(&dossier.join(format!("maison_{graine}.vxh"))) else {
            eprintln!("IGNORÉ : maison_{graine}.vxh absente");
            continue;
        };
        let cfg = HouseConfig {
            glazing: false,
            door_leaf: false,
            garden: false,
            raw_frame: true,
            ..Default::default()
        };
        let m = HouseGenerator::new(Matieres::standard()).build(graine, &cfg);
        let p = m.plan();
        let [nx, ny, nz] = vxh.dims();
        let (mut egal, mut seul_js, mut seul_rust) = (0_u64, 0_u64, 0_u64);
        let w = m.shape.render(
            0,
            [-p.ox, 0, -p.oz],
            [nx as i32 - p.ox, ny as i32 - 6, nz as i32 - p.oz],
        );
        let mut exemples = Vec::new();
        for y in 6..i64::from(ny) {
            for z in 0..i64::from(nz) {
                for x in 0..i64::from(nx) {
                    let js = vxh.cell(x, y, z);
                    if js.is_some_and(|c| c.flags().soft()) {
                        continue;
                    }
                    let rs = !w.get(x as i32 - p.ox, y as i32 - 6, z as i32 - p.oz).is_air();
                    match (js.is_some(), rs) {
                        (true, true) | (false, false) => egal += 1,
                        (true, false) => {
                            seul_js += 1;
                            if exemples.len() < 8 {
                                exemples.push(format!(
                                    "JS seul ({}, {}, {})",
                                    x - i64::from(p.ox),
                                    y - 6,
                                    z - i64::from(p.oz)
                                ));
                            }
                        }
                        (false, true) => {
                            seul_rust += 1;
                            if exemples.len() < 16 {
                                exemples.push(format!(
                                    "Rust seul ({}, {}, {})",
                                    x - i64::from(p.ox),
                                    y - 6,
                                    z - i64::from(p.oz)
                                ));
                            }
                        }
                    }
                }
            }
        }
        let pleins = seul_js + seul_rust;
        eprintln!("{graine} : égaux {egal}, JS seul {seul_js}, Rust seul {seul_rust} ; {exemples:?}");
        assert!(
            pleins * 1000 < egal.max(1),
            "{graine} : trop d'écarts d'occupation"
        );
    }
}
