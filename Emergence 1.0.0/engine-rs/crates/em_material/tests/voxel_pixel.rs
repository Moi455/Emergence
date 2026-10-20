//! Mode « VoxelPixel » (L23p) : la texture vient de la variation de couleur ENTRE voxels, jamais d'un bruit
//! continu en coordonnées monde. Les tests le PROUVENT : à gigue nulle, deux voxels de la même pièce ont
//! exactement la même couleur, où qu'ils soient ; à gigue non nulle, l'écart est borné par la gigue voulue.

mod commun;

use commun::{table_reelle, vegetation_test};
use em_core::{Fnv64, VoxelCoord, VoxelValue};
use em_material::{
    EvalContext, MaterialEvaluator, MaterialMode, MaterialTable, PixelOverride, StyleConfig, StyleSheet,
    VegetationRamps, tint_wood,
};
use std::collections::BTreeMap;

/// Empreinte épinglée du mode VoxelPixel (pierre, bois sur les trois axes et de bout, tuile, mousse).
const EMPREINTE_PIXEL: u64 = 0xbc8e_1aa4_77b7_23db;

const CLASSES_PIXEL: [&str; 5] = ["cut_stone", "oak_raw", "wood_trim", "slate", "moss"];

fn feuille(table: &MaterialTable, jitter_nulle: bool) -> StyleSheet {
    let mut params = BTreeMap::new();
    if jitter_nulle {
        for c in CLASSES_PIXEL {
            params.insert(
                c.to_owned(),
                PixelOverride::from_toml("voxel_jitter = 0.0").expect("surcharge valide"),
            );
        }
    }
    let config = StyleConfig {
        pixel_classes: CLASSES_PIXEL.iter().map(|s| (*s).to_owned()).collect(),
        params,
    };
    StyleSheet::from_config(&config, table, MaterialMode::VoxelPixel).expect("style valide")
}

fn albedo(ev: &MaterialEvaluator<'_>, valeur: VoxelValue, v: (i32, i32, i32), lod: u8) -> [i64; 3] {
    let c = ev
        .eval(&EvalContext::new(valeur, VoxelCoord::new(v.0, v.1, v.2), lod))
        .albedo()
        .channels();
    [c[0].raw(), c[1].raw(), c[2].raw()]
}

fn ecart(a: [i64; 3], b: [i64; 3]) -> i64 {
    (0..3).map(|i| (a[i] - b[i]).abs()).max().unwrap()
}

#[test]
fn deux_voxels_d_une_meme_pierre_sont_identiques_sans_gigue() {
    let t = table_reelle();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::with_style(&t, &veg, feuille(&t, true));
    let pierre = t.by_name("cut_stone").unwrap();
    for piece in [1_u8, 17, 64, 127] {
        let v = VoxelValue::new(pierre, piece);
        let ref_ = albedo(&ev, v, (0, 0, 0), 0);
        // loin, près, négatif, autre niveau : aucune coordonnée n'intervient (hors gigue, ici nulle)
        for p in [
            (1, 0, 0),
            (7, 3, 2),
            (-100, 55, 9),
            (199_999, 40, -30_000),
            (3, 3, 3),
        ] {
            assert_eq!(albedo(&ev, v, p, 0), ref_, "pièce {piece} en {p:?}");
        }
        assert_eq!(albedo(&ev, v, (5, 5, 5), 2), ref_, "autre niveau de détail");
    }
}

#[test]
fn les_pierres_voisines_ont_chacune_leur_ton() {
    let t = table_reelle();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::with_style(&t, &veg, feuille(&t, true));
    let pierre = t.by_name("cut_stone").unwrap();
    let tons: std::collections::BTreeSet<[i64; 3]> = (1..=127_u8)
        .map(|p| albedo(&ev, VoxelValue::new(pierre, p), (0, 0, 0), 0))
        .collect();
    assert!(
        tons.len() >= 120,
        "127 pierres, seulement {} tons distincts",
        tons.len()
    );
}

#[test]
fn l_ecart_dans_un_bloc_est_borne_par_la_gigue_voulue() {
    let t = table_reelle();
    let veg = vegetation_test();
    let sans = MaterialEvaluator::with_style(&t, &veg, feuille(&t, true));
    let avec = MaterialEvaluator::with_style(&t, &veg, feuille(&t, false));
    let pierre = t.by_name("cut_stone").unwrap();
    let v = VoxelValue::new(pierre, 42);
    let base = albedo(&sans, v, (0, 0, 0), 0);
    let mut pire = 0;
    let mut distincts = std::collections::BTreeSet::new();
    for i in 0..400_i32 {
        let a = albedo(&avec, v, (i * 3 - 200, i % 7, i * 11 % 53), 0);
        pire = pire.max(ecart(a, base));
        distincts.insert(a);
    }
    // la gigue existe (grain pixel) ...
    assert!(distincts.len() > 50, "la gigue par voxel est absente");
    // ... et elle est bornée : ±5 % de la rampe (écart de t ≤ 0,05 × 2 × amplitude d'une rampe de 3 couleurs)
    assert!(pire < 65_536 / 4, "écart intra-bloc trop grand : {pire}");
}

#[test]
fn le_mortier_est_plus_sombre_que_toute_pierre() {
    let t = table_reelle();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::with_style(&t, &veg, feuille(&t, true));
    let pierre = t.by_name("cut_stone").unwrap();
    let lum = |p: u8| {
        let a = albedo(&ev, VoxelValue::new(pierre, p), (0, 0, 0), 0);
        a[0] * 21 + a[1] * 72 + a[2] * 7
    };
    let mortier = lum(0);
    assert!(
        (1..=127_u8).all(|p| lum(p) > mortier),
        "le mortier doit être plus sombre que toute pierre"
    );
}

#[test]
fn le_mode_pixel_ignore_les_voisins_et_le_bruit_monde() {
    let t = table_reelle();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::with_style(&t, &veg, feuille(&t, false));
    let pierre = t.by_name("cut_stone").unwrap();
    let v = VoxelValue::new(pierre, 9);
    let seul = EvalContext::new(v, VoxelCoord::new(5, 6, 7), 0);
    let entoure = seul.with_plane_neighbors([
        Some(VoxelValue::new(pierre, 50)),
        Some(VoxelValue::new(pierre, 3)),
        None,
        Some(VoxelValue::new(pierre, 0)),
    ]);
    assert_eq!(
        ev.eval(&seul),
        ev.eval(&entoure),
        "le joint vient de la recette, pas des voisins"
    );
}

#[test]
fn le_bois_a_des_fibres_le_long_de_l_axe() {
    let t = table_reelle();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::with_style(&t, &veg, feuille(&t, true));
    let chene = t.by_name("oak_raw").unwrap();
    let v = VoxelValue::new(chene, tint_wood(0, 5)); // fil le long de x
    // dans un même tronçon (8 voxels) d'une même colonne (y, z) : strictement la même couleur
    let colonne: Vec<[i64; 3]> = (0..60).map(|x| albedo(&ev, v, (x, 3, 4), 0)).collect();
    let changements = colonne.windows(2).filter(|w| w[0] != w[1]).count();
    assert!(
        changements <= 60 / 8 + 1,
        "{changements} ruptures en 60 voxels : les tronçons font 8 voxels"
    );
    // d'une colonne à l'autre, les couleurs diffèrent (les fibres se voient)
    let voisines: std::collections::BTreeSet<[i64; 3]> = (0..4)
        .flat_map(|y| (0..4).map(move |z| (y, z)))
        .map(|(y, z)| albedo(&ev, v, (0, y, z), 0))
        .collect();
    assert!(
        voisines.len() >= 10,
        "16 colonnes de fibre, {} tons",
        voisines.len()
    );
}

#[test]
fn le_bois_est_correle_le_long_du_fil_mais_pas_en_travers() {
    // critère de L22 : corrélation des voxels voisins le long du fil ≥ 0,8 (une mosaïque aléatoire : ≤ 0,3)
    let t = table_reelle();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::with_style(&t, &veg, feuille(&t, false));
    let chene = t.by_name("oak_raw").unwrap();
    let v = VoxelValue::new(chene, tint_wood(0, 5));
    let lum = |p: (i32, i32, i32)| {
        let a = albedo(&ev, v, p, 0);
        (a[0] * 21 + a[1] * 72 + a[2] * 7) as f64 / 100.0
    };
    let correlation = |paires: Vec<(f64, f64)>| {
        let n = paires.len() as f64;
        let (ma, mb) = (
            paires.iter().map(|p| p.0).sum::<f64>() / n,
            paires.iter().map(|p| p.1).sum::<f64>() / n,
        );
        let cov: f64 = paires.iter().map(|p| (p.0 - ma) * (p.1 - mb)).sum();
        let (va, vb): (f64, f64) = (
            paires.iter().map(|p| (p.0 - ma).powi(2)).sum(),
            paires.iter().map(|p| (p.1 - mb).powi(2)).sum(),
        );
        cov / (va * vb).sqrt()
    };
    let mut le_long = Vec::new();
    let mut en_travers = Vec::new();
    for y in 0..8 {
        for z in 0..8 {
            for x in 0..59 {
                le_long.push((lum((x, y, z)), lum((x + 1, y, z))));
            }
        }
    }
    for x in 0..60 {
        for y in 0..8 {
            for z in 0..7 {
                en_travers.push((lum((x, y, z)), lum((x, y, z + 1))));
            }
        }
    }
    let (cl, ct) = (correlation(le_long), correlation(en_travers));
    eprintln!("corrélation le long du fil : {cl:.3} ; en travers : {ct:.3}");
    assert!(cl >= 0.8, "le long du fil : {cl}");
    assert!(ct <= 0.3, "en travers : {ct}");
}

#[test]
fn les_classes_non_listees_et_le_mode_continu_sont_inchanges() {
    let t = table_reelle();
    let veg = vegetation_test();
    let continu = MaterialEvaluator::new(&t, &veg);
    let mixte = MaterialEvaluator::with_style(&t, &veg, feuille(&t, false));
    for nom in ["turf", "granite", "leaves", "bark", "cobblestone", "oak_planks"] {
        let id = t.by_name(nom).unwrap();
        for i in 0..200_i32 {
            let ctx = EvalContext::new(
                VoxelValue::new(id, (i % 100) as u8),
                VoxelCoord::new(i, i % 13, -i),
                0,
            );
            assert_eq!(
                continu.eval(&ctx),
                mixte.eval(&ctx),
                "{nom} aurait dû rester continu"
            );
        }
    }
    // une feuille de style toute continue égale l'évaluateur d'origine, classe listée ou non
    let tout_continu = MaterialEvaluator::with_style(
        &t,
        &veg,
        StyleSheet::from_config(
            &StyleConfig {
                pixel_classes: CLASSES_PIXEL.iter().map(|s| (*s).to_owned()).collect(),
                params: BTreeMap::new(),
            },
            &t,
            MaterialMode::Continuous,
        )
        .unwrap(),
    );
    let pierre = t.by_name("cut_stone").unwrap();
    for i in 0..200_i32 {
        let ctx = EvalContext::new(
            VoxelValue::new(pierre, (i % 120) as u8),
            VoxelCoord::new(i, 2, 3),
            0,
        );
        assert_eq!(continu.eval(&ctx), tout_continu.eval(&ctx));
    }
    // et la pierre en mode voxel diffère bien de la pierre continue
    let ctx = EvalContext::new(VoxelValue::new(pierre, 33), VoxelCoord::new(10, 2, 3), 0);
    assert_ne!(continu.eval(&ctx), mixte.eval(&ctx));
}

fn empreinte(table: &MaterialTable, veg: &VegetationRamps) -> u64 {
    let ev = MaterialEvaluator::with_style(table, veg, feuille(table, false));
    let mut h = Fnv64::new();
    for nom in CLASSES_PIXEL {
        let id = table.by_name(nom).unwrap();
        for i in 0..2_048_i32 {
            let tint = match i % 3 {
                0 => tint_wood((i % 4) as u8, (i % 32) as u8),
                _ => (i % 128) as u8,
            };
            let a = albedo(
                &ev,
                VoxelValue::new(id, tint),
                (i * 7 % 211 - 105, i * 13 % 97, i * 29 % 307 - 150),
                (i % 3) as u8,
            );
            for c in a {
                h.add_u64(c as u64);
            }
        }
    }
    h.value()
}

#[test]
fn empreinte_du_mode_pixel_epinglee() {
    let t = table_reelle();
    let veg = vegetation_test();
    assert_eq!(empreinte(&t, &veg), empreinte(&t, &veg));
    assert_eq!(
        empreinte(&t, &veg),
        EMPREINTE_PIXEL,
        "empreinte réelle : {:#018x}",
        empreinte(&t, &veg)
    );
}
