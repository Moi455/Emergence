//! Tests sur les arbres de référence de L04 (`~/.local/share/emergence/lab_assets/trees/*.vxm`) :
//! aller-retour du chêne 42, échantillon de 10 000 voxels égal à `read_vxm.py`, empreintes épinglées,
//! rastérisation en chunks, temps de chargement. Sans le dossier d'assets, chaque test s'ignore avec un message.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use em_core::{ChunkKey, Fnv64, MaterialId, VoxelCoord, VoxelValue};
use em_gen::{PlacedModel, StaticScene, VxmModel};
use em_material::tint_vegetation;
use em_voxel::{Chunk, VoxelSource};

fn dossier_assets() -> PathBuf {
    if let Some(d) = std::env::var_os("EM_LAB_ASSETS").filter(|d| !d.is_empty()) {
        return PathBuf::from(d).join("trees");
    }
    PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
        .join(".local/share/emergence/lab_assets/trees")
}

/// Chemin d'un arbre de référence, ou `None` (avec un message) s'il est absent.
fn arbre(nom: &str) -> Option<PathBuf> {
    let p = dossier_assets().join(format!("{nom}.vxm"));
    if p.is_file() {
        Some(p)
    } else {
        eprintln!(
            "IGNORÉ : {} absent (assets de référence de L04 non générés)",
            p.display()
        );
        None
    }
}

/// (nom, voxels au LOD 0, LOD présents) : `tools/vegetation/reference_assets.txt`.
const REFERENCES: [(&str, usize, &[u8]); 6] = [
    ("chene_42", 607_784, &[0, 1, 2, 3, 4, 5]),
    ("epicea_7", 315_585, &[0, 1, 2, 3, 4, 5]),
    ("bouleau_3", 24_029, &[0, 1, 2, 3, 4, 5]),
    ("peuplier_5", 118_752, &[0, 1, 2, 3, 4, 5]),
    ("buis_sphere_7", 8_545, &[0, 1, 2, 3, 4]),
    ("rosier_4", 3_845, &[0, 1, 2, 3, 4]),
];

#[test]
fn les_six_references_se_chargent_avec_les_comptes_de_l04() {
    for (nom, lod0, lods) in REFERENCES {
        let Some(p) = arbre(nom) else { continue };
        let m = VxmModel::load(&p).unwrap_or_else(|e| panic!("{nom} : {e}"));
        assert_eq!(m.voxel_count(0), lod0, "{nom} : voxels au LOD 0");
        assert_eq!(m.lods(), lods, "{nom} : niveaux écrits");
        // un niveau absent du fichier est dérivé, avec un avertissement ; sinon aucun
        assert_eq!(m.warnings().len(), 6 - lods.len(), "{nom} : avertissements");
        for lod in 0..6 {
            assert!(m.voxel_count(lod) > 0, "{nom} : LOD {lod} servi");
        }
        // le pied du tronc est la cellule (0, 0, 0) : la boîte commence à y = 0 et contient le pivot en x et z
        let b = m.bounds(0);
        assert_eq!(b.min().y, 0, "{nom}");
        assert!(
            b.min().x <= 0 && b.max().x > 0 && b.min().z <= 0 && b.max().z > 0,
            "{nom} : pivot dans la boîte"
        );
        assert!(m.has_palette_channel() && !m.has_sky_channel(), "{nom}");
    }
}

#[test]
fn chene_42_aller_retour_sur_la_grille_monde() {
    let Some(p) = arbre("chene_42") else { return };
    let m = Arc::new(VxmModel::load(&p).unwrap());
    // 607 784 voxels pleins au LOD 0 après rastérisation dans les chunks, aux 4 rotations
    for n in 0..4_u8 {
        let placed = PlacedModel::new(m.clone(), VoxelCoord::new(200_000, 0, 200_000), n, 2).unwrap();
        let b = placed.bounds(0);
        let (k0, k1) = (
            b.min().chunk(),
            VoxelCoord::new(b.max().x - 1, b.max().y - 1, b.max().z - 1).chunk(),
        );
        let mut pleins = 0_u64;
        for cx in k0.x..=k1.x {
            for cy in k0.y..=k1.y {
                for cz in k0.z..=k1.z {
                    let mut chunk = Chunk::new_air();
                    placed.fill_chunk(ChunkKey::new(cx, cy, cz), 0, &mut chunk);
                    pleins += u64::from(chunk.non_air_count());
                }
            }
        }
        assert_eq!(
            pleins, 607_784,
            "voxels pleins après rastérisation, {n} quart(s) de tour"
        );
    }
}

/// Même sortie que `read_vxm.py` : niveaux (compte, coin, dimensions) et 10 000 voxels échantillonnés
/// (position, sorte, variante de teinte), régénérés par `tests/vecteurs/gen_echantillon.py`.
#[test]
fn chene_42_echantillon_de_10000_voxels_egal_a_read_vxm_py() {
    let Some(p) = arbre("chene_42") else { return };
    let m = Arc::new(VxmModel::load(&p).unwrap());
    let ref_txt = include_str!("vecteurs/chene_42_echantillon.txt");
    let (mut niveaux, mut echantillon) = (Vec::new(), Vec::new());
    for ligne in ref_txt.lines() {
        let mut it = ligne.split_whitespace();
        let tag = it.next().unwrap();
        let nums: Vec<i64> = it.map(|s| s.parse().unwrap()).collect();
        match tag {
            "L" => niveaux.push(nums),
            "S" => echantillon.push(nums),
            autre => panic!("ligne inconnue {autre}"),
        }
    }
    assert_eq!(niveaux.len(), 6);
    assert_eq!(echantillon.len(), 10_000);
    for n in niveaux {
        let (lod, compte) = (n[0] as u8, n[1] as usize);
        assert_eq!(m.voxel_count(lod), compte, "LOD {lod} : compte");
        let b = m.bounds(lod);
        let (min, dims) = ([n[2], n[3], n[4]], [n[5], n[6], n[7]]);
        assert_eq!(
            [i64::from(b.min().x), i64::from(b.min().y), i64::from(b.min().z)],
            min,
            "LOD {lod} : coin"
        );
        assert_eq!(b.size(), dims, "LOD {lod} : dimensions");
    }
    // pose neutre : pivot en (0, 0, 0), aucune rotation, essence 4 (teinte = 4 << 2 | variante)
    let placed = PlacedModel::new(m, VoxelCoord::new(0, 0, 0), 0, 4).unwrap();
    let tous: Vec<(VoxelCoord, VoxelValue)> = placed.world_voxels(0).collect();
    let pas = tous.len() / 10_000;
    for (i, s) in echantillon.iter().enumerate() {
        let (pos, val) = tous[i * pas];
        assert_eq!(
            [i64::from(pos.x), i64::from(pos.y), i64::from(pos.z)],
            [s[0], s[1], s[2]],
            "voxel n° {i} : position"
        );
        let classe = match s[3] {
            1 | 3 => 31,
            2 => 30,
            4 => 34,
            _ => 35,
        };
        assert_eq!(val.material(), MaterialId::new(classe), "voxel n° {i} : classe");
        assert_eq!(
            val.tint(),
            tint_vegetation(4, s[4] as u8),
            "voxel n° {i} : teinte"
        );
    }
}

/// Empreinte FNV-1a de tous les voxels du chêne rastérisés dans les chunks (positions et valeurs, en ordre canonique).
fn empreinte_rasterisee(placed: &PlacedModel) -> u64 {
    let b = placed.bounds(0);
    let (k0, k1) = (
        b.min().chunk(),
        VoxelCoord::new(b.max().x - 1, b.max().y - 1, b.max().z - 1).chunk(),
    );
    let mut h = Fnv64::new();
    for cy in k0.y..=k1.y {
        for cz in k0.z..=k1.z {
            for cx in k0.x..=k1.x {
                let mut chunk = Chunk::new_air();
                placed.fill_chunk(ChunkKey::new(cx, cy, cz), 0, &mut chunk);
                h.add_u64(chunk.fingerprint_value());
            }
        }
    }
    h.value()
}

/// Empreintes épinglées du chêne 42 (L08). Elles changent seulement si le fichier de L04, les classes de
/// matière, la rotation ou la rastérisation changent : un changement doit être compris, pas rattrapé.
#[test]
fn chene_42_empreintes_epinglees() {
    let Some(p) = arbre("chene_42") else { return };
    let m = Arc::new(VxmModel::load(&p).unwrap());
    let contenu = m.fingerprint();
    let placed = PlacedModel::new(m.clone(), VoxelCoord::new(0, 0, 0), 0, 2).unwrap();
    let chunks = empreinte_rasterisee(&placed);
    let tourne = empreinte_rasterisee(&PlacedModel::new(m, VoxelCoord::new(0, 0, 0), 1, 2).unwrap());
    eprintln!("contenu {contenu:#018x} chunks {chunks:#018x} tourne {tourne:#018x}");
    assert_eq!(contenu, PIN_CONTENU, "empreinte du contenu (six niveaux)");
    assert_eq!(
        chunks, PIN_CHUNKS,
        "empreinte des chunks du LOD 0, 0 quart de tour"
    );
    assert_eq!(
        tourne, PIN_TOURNE,
        "empreinte des chunks du LOD 0, 1 quart de tour"
    );
}
const PIN_CONTENU: u64 = 0x75d9_86c2_b4b5_ddee;
const PIN_CHUNKS: u64 = 0xaea7_41cf_fc7a_91c7;
const PIN_TOURNE: u64 = 0x9bc5_c3a5_d1fc_fab3;

#[test]
fn scene_arbre_donne_ses_chunks() {
    let Some(p) = arbre("chene_42") else { return };
    let m = Arc::new(VxmModel::load(&p).unwrap());
    let scene =
        StaticScene::tree_on_turf(PlacedModel::new(m, VoxelCoord::new(0, 0, 0), 0, 2).unwrap()).unwrap();
    let mut chunk = Chunk::new_air();
    // le chunk du dessous est du sol plein de turf
    scene.fill_chunk(ChunkKey::new(0, -1, 0), 0, &mut chunk);
    assert_eq!(chunk.get(1, 63, 1).material(), MaterialId::new(1));
    // le chunk du pied du tronc contient l'arbre : plus rien que de l'air au-delà de la boîte
    scene.fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut chunk);
    assert!(chunk.non_air_count() > 0);
    let b = scene.models_bounds(0).unwrap();
    assert_eq!(b.min().y, 0);
    assert!(b.max().y >= 280, "le chêne de 14 m fait 280 voxels de haut");
}

/// Critère de L08 : chargement <= 300 ms. Le chronométrage ne vaut qu'en release (le profil de test est
/// peu optimisé) : ici une borne large ; la mesure officielle est `cargo run --release -p em_gen --example mesures`.
#[test]
fn chene_42_chargement_dans_le_budget() {
    let Some(p) = arbre("chene_42") else { return };
    let t = Instant::now();
    let m = VxmModel::load(&p).unwrap();
    let ms = t.elapsed().as_millis();
    eprintln!("chargement du chêne 42 : {ms} ms (profil de test)");
    assert_eq!(m.voxel_count(0), 607_784);
    let borne = if cfg!(debug_assertions) { 3000 } else { 300 };
    assert!(ms <= borne, "chargement en {ms} ms (> {borne} ms)");
}

#[test]
fn chaque_voxel_servi_est_dans_la_boite_et_les_classes_sont_celles_de_la_table() {
    let Some(p) = arbre("rosier_4") else { return };
    let m = Arc::new(VxmModel::load(&p).unwrap());
    let placed = PlacedModel::new(m, VoxelCoord::new(-5, 3, 9), 3, 7).unwrap();
    let mut par_classe: BTreeMap<u16, usize> = BTreeMap::new();
    for lod in 0..6 {
        let b = placed.bounds(lod);
        for (c, v) in placed.world_voxels(lod) {
            assert!(b.contains(c), "LOD {lod} : voxel hors de sa boîte");
            *par_classe.entry(v.material().get()).or_default() += 1;
        }
    }
    // le rosier a des fleurs (34), des feuilles (30) et de l'écorce (31), pas de fruit
    assert!(par_classe.contains_key(&30) && par_classe.contains_key(&31) && par_classe.contains_key(&34));
    assert!(!par_classe.contains_key(&35));
}
