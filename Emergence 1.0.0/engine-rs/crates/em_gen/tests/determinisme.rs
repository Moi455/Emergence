//! Déterminisme et performance de la famille végétation : même rendu avec 1 et 8 fils, par fenêtres de 64³ ou d'un
//! seul tenant ; empreintes épinglées ; plan ≤ 30 ms et rastérisation du chêne mesurés.

use std::sync::Arc;
use std::time::Instant;

use em_core::{Fnv64, VoxelBox, VoxelCoord};
use em_gen::vegetation::measure::{GridSink, measure};
use em_gen::vegetation::{Season, SpeciesTable, TreeGenerator, TreeParams};
use em_gen::{GenPlan, Generator, VxmClasses};

fn chene(seed: u64, h_mm: u32) -> Arc<dyn GenPlan> {
    let g = TreeGenerator::new(Arc::new(SpeciesTable::embedded()), VxmClasses::standard());
    let p = TreeParams {
        species: "chene".into(),
        height_mm: h_mm,
        season: Season::Summer,
        leaf_density_permille: 1000,
    };
    g.plan(&p.to_params().unwrap(), seed).unwrap()
}

fn fenetres(b: VoxelBox) -> Vec<VoxelBox> {
    let (m, x) = (b.min(), b.max());
    let mut v = Vec::new();
    let mut y = m.y;
    while y < x.y {
        let mut z = m.z;
        while z < x.z {
            let mut a = m.x;
            while a < x.x {
                v.push(
                    VoxelBox::new(
                        VoxelCoord::new(a, y, z),
                        VoxelCoord::new((a + 64).min(x.x), (y + 64).min(x.y), (z + 64).min(x.z)),
                    )
                    .unwrap(),
                );
                a += 64;
            }
            z += 64;
        }
        y += 64;
    }
    v
}

/// Empreinte du rendu par fenêtres de 64³ réparties sur `fils` fils.
fn par_fenetres(plan: &Arc<dyn GenPlan>, lod: u8, fils: usize) -> (u64, u64) {
    let b = plan.bounds(lod);
    let ws = fenetres(b);
    let mut res = vec![(0_u64, 0_u64); ws.len()];
    std::thread::scope(|s| {
        for (c_ws, c_res) in ws
            .chunks(ws.len().div_ceil(fils))
            .zip(res.chunks_mut(ws.len().div_ceil(fils)))
        {
            let plan = plan.clone();
            s.spawn(move || {
                for (w, r) in c_ws.iter().zip(c_res.iter_mut()) {
                    let mut g = GridSink::new(*w);
                    plan.rasterize(lod, *w, &mut g);
                    let (m, x) = (w.min(), w.max());
                    let mut h = Fnv64::new();
                    let mut n = 0;
                    for y in m.y..x.y {
                        for z in m.z..x.z {
                            for a in m.x..x.x {
                                let v = g.get(VoxelCoord::new(a, y, z));
                                if !v.is_air() {
                                    n += 1;
                                    for c in [a, y, z] {
                                        h.add_u64(i64::from(c) as u64);
                                    }
                                    h.add_u64(u64::from(v.raw()));
                                }
                            }
                        }
                    }
                    *r = (h.value(), n);
                }
            });
        }
    });
    let mut h = Fnv64::new();
    let mut n = 0;
    for (e, c) in res {
        h.add_u64(e);
        n += c;
    }
    (h.value(), n)
}

#[test]
fn un_fil_egale_huit_fils_et_la_fenetre_ne_change_rien() {
    let plan = chene(42, 8000);
    for lod in [0_u8, 2] {
        let un = par_fenetres(&plan, lod, 1);
        let huit = par_fenetres(&plan, lod, 8);
        assert_eq!(un, huit, "niveau {lod}");
        let entier = measure(plan.as_ref(), lod, &VxmClasses::standard());
        assert_eq!(
            un.1, entier.voxels,
            "les fenêtres recomposent le sujet entier (niveau {lod})"
        );
    }
}

#[test]
fn empreintes_epinglees_du_chene_42() {
    let plan = chene(42, 8000);
    let c = VxmClasses::standard();
    let m0 = measure(plan.as_ref(), 0, &c);
    let m3 = measure(plan.as_ref(), 3, &c);
    println!(
        "EMPREINTES chene 42 / 8 m : niveau 0 {:#018x} ({} voxels), niveau 3 {:#018x} ({} voxels)",
        m0.fingerprint, m0.voxels, m3.fingerprint, m3.voxels
    );
    assert_eq!((m0.fingerprint, m0.voxels), (EMPREINTE_N0, VOXELS_N0));
    assert_eq!((m3.fingerprint, m3.voxels), (EMPREINTE_N3, VOXELS_N3));
}

const EMPREINTE_N0: u64 = 0xfe40_8243_3e15_e93a;
const VOXELS_N0: u64 = 93_601;
const EMPREINTE_N3: u64 = 0xd52f_056c_448c_9532;
const VOXELS_N3: u64 = 1_346;

#[test]
fn mesures_de_temps_du_chene_de_14_m() {
    let t = Instant::now();
    let plan = chene(42, 14_000);
    let t_plan = t.elapsed();
    let t = Instant::now();
    let m = measure(plan.as_ref(), 0, &VxmClasses::standard());
    println!(
        "TEMPS chêne 42 / 14 m : plan {t_plan:?}, raster+mesure {:?}, {} voxels",
        t.elapsed(),
        m.voxels
    );
    // plan ≤ 30 ms en release ; large en debug (opt-level 1)
    assert!(t_plan.as_millis() < 300, "plan {t_plan:?}");
}
