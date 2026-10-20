//! Tests du chargeur `.vxm` sur des fichiers synthétiques et sur la scène d'orientation de L04 :
//! validation stricte, repli de LOD, conversion sorte + rampe -> `VoxelValue`, orientation, rotations.

mod common;

use std::collections::BTreeMap;
use std::sync::Arc;

use common::{Opts, fabrique, recrc, v};
use em_core::{ChunkKey, MaterialId, VoxelCoord, VoxelValue};
use em_gen::{
    GenError, GenParams, Generator, PlacedModel, QuarterTurns, StaticScene, VxmError, VxmModel, VxmWarning,
};
use em_material::tint_vegetation;
use em_voxel::{Chunk, VoxelSource};

fn charge(octets: &[u8]) -> Result<VxmModel, VxmError> {
    VxmModel::from_bytes(octets)
}

/// Un fichier minimal à un seul LOD.
fn petit() -> Vec<u8> {
    fabrique(
        &[(0, vec![v(0, 0, 0, 1, 0), v(1, 0, 0, 2, 3), v(0, 1, 0, 2, 3)])],
        &Opts::default(),
    )
}

// ---------------------------------------------------------------- validation stricte

#[test]
fn fichier_minimal_valide() {
    let m = charge(&petit()).unwrap();
    assert_eq!(m.voxel_count(0), 3);
    assert_eq!(m.lods(), &[0]);
    assert_eq!(m.meta().species(), "test");
}

#[test]
fn refus_signature_crc_version_drapeaux() {
    let ok = petit();
    assert!(matches!(charge(&ok[..10]), Err(VxmError::TropCourt(10))));
    let mut mauvais = ok.clone();
    mauvais[0] = b'X';
    assert_eq!(charge(&mauvais).unwrap_err(), VxmError::Signature);
    let mut crc = ok.clone();
    let milieu = crc.len() / 2;
    crc[milieu] ^= 0x55;
    assert!(matches!(charge(&crc), Err(VxmError::Crc { .. })));
    // version future et version zéro : refusées après un CRC correct
    for version in [0_u16, 2, 99] {
        let mut o = ok.clone();
        o[4..6].copy_from_slice(&version.to_le_bytes());
        assert_eq!(charge(&recrc(o)).unwrap_err(), VxmError::VersionNonGeree(version));
    }
    let mut o = ok.clone();
    o[6] |= 0x08; // drapeau inconnu (bit 3)
    assert!(matches!(charge(&recrc(o)), Err(VxmError::DrapeauxInconnus(8))));
}

#[test]
fn refus_fichier_tronque_a_toute_longueur() {
    let ok = petit();
    for n in 0..ok.len() {
        assert!(
            charge(&ok[..n]).is_err(),
            "la troncature à {n} octet(s) doit être refusée"
        );
    }
}

#[test]
fn refus_octets_en_trop() {
    let mut o = petit();
    let n = o.len() - 4;
    o.splice(n..n, [1, 2, 3]);
    assert!(matches!(charge(&recrc(o)), Err(VxmError::OctetsEnTrop(3))));
}

#[test]
fn refus_entete() {
    let o = Opts {
        voxel_m: "0.1",
        ..Opts::default()
    };
    let f = fabrique(&[(0, vec![v(0, 0, 0, 1, 0)])], &o);
    assert!(matches!(charge(&f), Err(VxmError::VoxelHorsGrille(_))));
    let o = Opts {
        lods_header: Some(vec![1]),
        ..Opts::default()
    };
    let f = fabrique(&[(1, vec![v(0, 0, 0, 1, 0)])], &o);
    assert!(
        matches!(charge(&f), Err(VxmError::EnTeteInvalide(_))),
        "le LOD 0 est obligatoire"
    );
    let o = Opts {
        lods_header: Some(vec![0, 6]),
        ..Opts::default()
    };
    let f = fabrique(&[(0, vec![v(0, 0, 0, 1, 0)]), (6, vec![v(0, 0, 0, 1, 0)])], &o);
    assert_eq!(charge(&f).unwrap_err(), VxmError::LodHorsPlage(6));
    let o = Opts {
        lods_header: Some(vec![0, 0]),
        ..Opts::default()
    };
    let f = fabrique(&[(0, vec![v(0, 0, 0, 1, 0)]), (0, vec![v(0, 0, 0, 1, 0)])], &o);
    assert!(matches!(charge(&f), Err(VxmError::EnTeteInvalide(_))));
}

#[test]
fn refus_json_illisible() {
    let mut o = petit();
    o[12] = b'}'; // casse l'accolade ouvrante du JSON
    assert!(matches!(charge(&recrc(o)), Err(VxmError::EnTeteJson(_))));
}

#[test]
fn refus_sections() {
    // section annoncée pour un autre LOD que l'en-tête
    let o = Opts {
        lods_header: Some(vec![0, 1]),
        ..Opts::default()
    };
    let f = fabrique(&[(0, vec![v(0, 0, 0, 1, 0)]), (2, vec![v(0, 0, 0, 1, 0)])], &o);
    assert_eq!(
        charge(&f).unwrap_err(),
        VxmError::LodInattendu { lu: 2, attendu: 1 }
    );
    // sorte hors de 1..=5
    let f = fabrique(&[(0, vec![v(0, 0, 0, 9, 0)])], &Opts::default());
    assert!(matches!(
        charge(&f),
        Err(VxmError::SorteInvalide { sorte: 9, .. })
    ));
    // rampe hors de l'en-tête (7 rampes : 0..=6)
    let f = fabrique(&[(0, vec![v(0, 0, 0, 1, 7)])], &Opts::default());
    assert!(matches!(
        charge(&f),
        Err(VxmError::RampeHorsEnTete { rampe: 7, .. })
    ));
    // fleur dont le rang dans son rôle dépasse 3
    let o = Opts {
        roles: vec!["flower"; 6],
        ..Opts::default()
    };
    let f = fabrique(&[(0, vec![v(0, 0, 0, 4, 5)])], &o);
    assert_eq!(charge(&f).unwrap_err(), VxmError::RangDeRampeTropGrand(5));
}

#[test]
fn refus_corps_incoherents() {
    let ok = petit();
    // corps non compressé de mauvaise taille : on retire un octet du corps et on corrige body_len
    let o = Opts {
        zlib: false,
        ..Opts::default()
    };
    let mut f = fabrique(&[(0, vec![v(0, 0, 0, 1, 0), v(1, 0, 0, 2, 3)])], &o);
    let fin = f.len() - 4;
    f.remove(fin - 1);
    let json_len = u32::from_le_bytes(f[8..12].try_into().unwrap()) as usize;
    let body_len_pos = 12 + json_len + 4 + 12 + 12 + 4;
    let body_len = u32::from_le_bytes(f[body_len_pos..body_len_pos + 4].try_into().unwrap()) - 1;
    f[body_len_pos..body_len_pos + 4].copy_from_slice(&body_len.to_le_bytes());
    assert!(matches!(charge(&recrc(f)), Err(VxmError::CorpsTaille { .. })));
    // zlib corrompu : on écrase le flux compressé
    let json_len = u32::from_le_bytes(ok[8..12].try_into().unwrap()) as usize;
    let debut_corps = 12 + json_len + 4 + 12 + 12 + 8;
    let mut z = ok.clone();
    for b in &mut z[debut_corps..debut_corps + 4] {
        *b = 0xFF;
    }
    assert!(matches!(
        charge(&recrc(z)),
        Err(VxmError::CorpsZlib { .. } | VxmError::CorpsTaille { .. })
    ));
    // octets réservés non nuls
    let mut r = ok.clone();
    r[12 + json_len + 1] = 7;
    assert!(matches!(charge(&recrc(r)), Err(VxmError::ReservesNonNuls(0))));
}

#[test]
fn refus_ordre_et_doublons() {
    // on fabrique à la main un corps non trié : x, y, z, sortes, rampes en désordre
    let o = Opts {
        zlib: false,
        ..Opts::default()
    };
    let mut f = fabrique(&[(0, vec![v(0, 0, 0, 1, 0), v(1, 0, 0, 1, 0)])], &o);
    let json_len = u32::from_le_bytes(f[8..12].try_into().unwrap()) as usize;
    let debut = 12 + json_len + 4 + 12 + 12 + 8;
    // x[0..2] = 0, 1 -> on les inverse : (1, 0) puis (0, 0) n'est plus croissant
    f.swap(debut, debut + 2);
    assert!(matches!(charge(&recrc(f)), Err(VxmError::Ordre { index: 1, .. })));
    // cellule en double : x = 0, 0
    let mut g = fabrique(&[(0, vec![v(0, 0, 0, 1, 0), v(1, 0, 0, 1, 0)])], &o);
    g[debut + 2] = 0;
    assert!(matches!(charge(&recrc(g)), Err(VxmError::Ordre { index: 1, .. })));
}

#[test]
fn erreur_de_fichier_absent_est_io() {
    let e = VxmModel::load(std::path::Path::new("/chemin/qui/n/existe/pas.vxm")).unwrap_err();
    assert!(matches!(e, GenError::Io { .. }));
}

// ---------------------------------------------------------------- teintes et classes

#[test]
fn sorte_et_rampe_donnent_classe_et_teinte() {
    // rôles : 0 bark, 1 bark_alt, 2 twig, 3 leaf, 4 flower, 5 flower, 6 fruit
    let voxels = vec![
        v(0, 0, 0, 1, 0), // écorce
        v(1, 0, 0, 1, 1), // écorce secondaire
        v(2, 0, 0, 3, 2), // rameau
        v(3, 0, 0, 2, 3), // feuille
        v(4, 0, 0, 4, 4), // fleur, rampe 4 : rang 0 du rôle flower
        v(5, 0, 0, 4, 5), // fleur, rampe 5 : rang 1
        v(6, 0, 0, 5, 6), // fruit
    ];
    let m = Arc::new(charge(&fabrique(&[(0, voxels)], &Opts::default())).unwrap());
    let p = PlacedModel::new(m, VoxelCoord::new(0, 0, 0), 0, 9).unwrap();
    let valeurs: Vec<VoxelValue> = p.world_voxels(0).map(|(_, v)| v).collect();
    let attendu = [
        (31, 0), // bark, variante 0
        (31, 1), // bark, variante 1
        (31, 2), // bark (rameau), variante 2
        (30, 0), // leaves : la rampe est tirée au shader
        (34, 0), // petal
        (34, 1),
        (35, 0), // fruit
    ];
    for (got, (classe, variante)) in valeurs.iter().zip(attendu) {
        assert_eq!(got.material(), MaterialId::new(classe));
        assert_eq!(
            got.tint(),
            tint_vegetation(9, variante),
            "teinte = essence 9 + variante"
        );
    }
}

#[test]
fn essence_hors_case_refusee() {
    let m = Arc::new(charge(&petit()).unwrap());
    assert!(matches!(
        PlacedModel::new(m.clone(), VoxelCoord::new(0, 0, 0), 0, 32),
        Err(GenError::UnknownSpecies(32))
    ));
    assert!(matches!(
        PlacedModel::new(m, VoxelCoord::new(0, 0, 0), 4, 0),
        Err(GenError::BadParams(_))
    ));
    assert!(QuarterTurns::new(4).is_err());
}

// ---------------------------------------------------------------- orientation

fn orientation() -> Arc<VxmModel> {
    let octets = std::fs::read(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/fixtures/orientation.vxm"
    ))
    .unwrap();
    Arc::new(charge(&octets).unwrap())
}

/// Rouge (fleur) à l'est (+x), bleu (fruit) au nord (+z), pivot gris (écorce) : la scène de L04, relue par Rust.
#[test]
fn orientation_rouge_x_bleu_z() {
    let m = orientation();
    let p = PlacedModel::new(m, VoxelCoord::new(100, 5, -40), 0, 0).unwrap();
    let par_classe: BTreeMap<u16, VoxelCoord> =
        p.world_voxels(0).map(|(c, v)| (v.material().get(), c)).collect();
    assert_eq!(par_classe[&31], VoxelCoord::new(100, 5, -40), "pivot");
    assert_eq!(
        par_classe[&34],
        VoxelCoord::new(101, 5, -40),
        "rouge (fleur) à l'est : +x"
    );
    assert_eq!(
        par_classe[&35],
        VoxelCoord::new(100, 5, -39),
        "bleu (fruit) au nord : +z"
    );
}

/// Vu d'en haut, le nord en haut, repère GAUCHER : l'image a x à droite et z en haut, donc le rouge
/// est à droite du pivot et le bleu au-dessus. On rastérise la scène dans un chunk puis on « photographie »
/// la vue de dessus (colonne la plus haute) avec les conventions de l'image : colonne = x, ligne = -z.
#[test]
fn orientation_vue_de_dessus() {
    let p = PlacedModel::new(orientation(), VoxelCoord::new(10, 0, 10), 0, 0).unwrap();
    let mut chunk = Chunk::new_air();
    p.fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut chunk);
    // image 3 x 3 centrée sur le pivot : ligne 0 = nord (z+1), colonne 2 = est (x+1)
    let mut image = [[' '; 3]; 3];
    for (ligne, dz) in [1_i32, 0, -1].into_iter().enumerate() {
        for (colonne, dx) in [-1_i32, 0, 1].into_iter().enumerate() {
            let v = chunk.get((10 + dx) as u32, 0, (10 + dz) as u32);
            image[ligne][colonne] = match v.material().get() {
                31 => 'G',
                34 => 'R',
                35 => 'B',
                _ => '.',
            };
        }
    }
    assert_eq!(image[1][2], 'R', "rouge à droite du pivot");
    assert_eq!(image[0][1], 'B', "bleu au-dessus du pivot");
    assert_eq!(image[1][1], 'G');
    let (r, b) = (
        image.iter().flatten().filter(|c| **c == 'R').count(),
        image.iter().flatten().filter(|c| **c == 'B').count(),
    );
    assert_eq!((r, b), (1, 1));
}

/// Quarts de tour autour du centre de la cellule pivot : l'est (+x) va au nord (+z), puis à l'ouest, puis au sud.
#[test]
fn quarts_de_tour_du_rouge_et_du_bleu() {
    let m = orientation();
    let pivot = VoxelCoord::new(7, 2, -3);
    // (rouge, bleu) attendus pour 0, 1, 2, 3 quarts de tour
    let attendu = [
        ((1, 0), (0, 1)),
        ((0, 1), (-1, 0)),
        ((-1, 0), (0, -1)),
        ((0, -1), (1, 0)),
    ];
    for (n, (rouge, bleu)) in attendu.into_iter().enumerate() {
        let p = PlacedModel::new(m.clone(), pivot, n as u8, 0).unwrap();
        let par_classe: BTreeMap<u16, VoxelCoord> =
            p.world_voxels(0).map(|(c, v)| (v.material().get(), c)).collect();
        assert_eq!(
            par_classe[&34],
            VoxelCoord::new(7 + rouge.0, 2, -3 + rouge.1),
            "rouge, {n} quart(s)"
        );
        assert_eq!(
            par_classe[&35],
            VoxelCoord::new(7 + bleu.0, 2, -3 + bleu.1),
            "bleu, {n} quart(s)"
        );
        assert_eq!(par_classe[&31], pivot, "le pivot ne bouge pas");
    }
}

/// Même compte et boîte tournée exacte pour 0..3 quarts de tour (boîte asymétrique pour voir les erreurs d'un voxel).
#[test]
fn quarts_de_tour_boites_et_comptes() {
    let voxels = vec![
        v(-3, 0, -1, 1, 0),
        v(4, 2, 0, 2, 3),
        v(0, 5, 2, 2, 3),
        v(1, 1, -2, 3, 2),
        v(0, 0, 0, 1, 0),
    ];
    let m = Arc::new(charge(&fabrique(&[(0, voxels.clone())], &Opts::default())).unwrap());
    for n in 0..4_u8 {
        let p = PlacedModel::new(m.clone(), VoxelCoord::new(50, 10, -20), n, 0).unwrap();
        assert_eq!(p.world_voxels(0).count(), 5, "même compte à {n} quart(s)");
        let rot = |x: i32, z: i32| match n {
            0 => (x, z),
            1 => (-z, x),
            2 => (-x, -z),
            _ => (z, -x),
        };
        let monde: Vec<[i32; 3]> = voxels
            .iter()
            .map(|c| {
                let (x, z) = rot(c.p[0], c.p[2]);
                [50 + x, 10 + c.p[1], -20 + z]
            })
            .collect();
        let b = p.bounds(0);
        for i in 0..3 {
            let lo = monde.iter().map(|c| c[i]).min().unwrap();
            let hi = monde.iter().map(|c| c[i]).max().unwrap() + 1;
            let (bmin, bmax) = (
                [b.min().x, b.min().y, b.min().z],
                [b.max().x, b.max().y, b.max().z],
            );
            assert_eq!((bmin[i], bmax[i]), (lo, hi), "boîte, axe {i}, {n} quart(s)");
        }
        // chaque voxel servi est dans la boîte et dans l'ensemble attendu
        let mut vus: Vec<[i32; 3]> = p.world_voxels(0).map(|(c, _)| [c.x, c.y, c.z]).collect();
        let mut att = monde.clone();
        vus.sort();
        att.sort();
        assert_eq!(vus, att, "positions, {n} quart(s)");
    }
}

/// La rastérisation par chunks (traversant les bords de chunk) sert exactement `world_voxels`, pour chaque rotation.
#[test]
fn rasterisation_par_chunks_egale_world_voxels() {
    let mut voxels = Vec::new();
    for i in 0..200 {
        voxels.push(v(
            (i * 7) % 90 - 40,
            i / 5 % 70,
            (i * 13) % 80 - 30,
            1 + (i % 5) as u8 % 5,
            0,
        ));
    }
    voxels.sort_by_key(|c| (c.p[1], c.p[2], c.p[0]));
    voxels.dedup_by_key(|c| c.p);
    let o = Opts {
        roles: vec!["bark", "bark_alt", "twig", "leaf", "flower", "flower", "fruit"],
        ..Opts::default()
    };
    // rampes cohérentes avec la sorte pour passer la validation du rang
    for c in &mut voxels {
        c.ramp = match c.kind {
            1 => 0,
            2 => 3,
            3 => 2,
            4 => 4,
            _ => 6,
        };
    }
    let m = Arc::new(charge(&fabrique(&[(0, voxels.clone())], &o)).unwrap());
    for n in 0..4_u8 {
        let p = PlacedModel::new(m.clone(), VoxelCoord::new(-3, 60, 61), n, 5).unwrap();
        let attendu: BTreeMap<VoxelCoord, VoxelValue> = p.world_voxels(0).collect();
        let b = p.bounds(0);
        let mut obtenu = BTreeMap::new();
        let (k0, k1) = (
            b.min().chunk(),
            VoxelCoord::new(b.max().x - 1, b.max().y - 1, b.max().z - 1).chunk(),
        );
        for cx in k0.x..=k1.x {
            for cy in k0.y..=k1.y {
                for cz in k0.z..=k1.z {
                    let key = ChunkKey::new(cx, cy, cz);
                    let mut chunk = Chunk::new_air();
                    p.fill_chunk(key, 0, &mut chunk);
                    let o = key.origin();
                    for z in 0..64 {
                        for y in 0..64 {
                            for x in 0..64 {
                                let val = chunk.get(x, y, z);
                                if !val.is_air() {
                                    obtenu.insert(
                                        VoxelCoord::new(o.x + x as i32, o.y + y as i32, o.z + z as i32),
                                        val,
                                    );
                                }
                            }
                        }
                    }
                }
            }
        }
        assert_eq!(obtenu, attendu, "rotation {n}");
    }
}

// ---------------------------------------------------------------- niveaux de détail

#[test]
fn pivot_aux_niveaux_grossiers_floor_div() {
    let m = Arc::new(charge(&petit()).unwrap());
    let p = PlacedModel::new(m, VoxelCoord::new(-1, -9, 17), 0, 0).unwrap();
    assert_eq!(p.pivot_at(0), VoxelCoord::new(-1, -9, 17));
    assert_eq!(
        p.pivot_at(1),
        VoxelCoord::new(-1, -5, 8),
        "floor_div, jamais une troncature vers zéro"
    );
    assert_eq!(p.pivot_at(3), VoxelCoord::new(-1, -2, 2));
    assert_eq!(p.pivot_at(5), VoxelCoord::new(-1, -1, 0));
}

#[test]
fn lod_absent_se_replie_sur_le_plus_fin_avec_avertissement() {
    // LOD 0 et 2 seulement : 1 dérivé du 0, 3 à 5 dérivés du 2
    let l0 = vec![
        v(0, 0, 0, 1, 0),
        v(1, 0, 0, 2, 3),
        v(2, 0, 0, 2, 3),
        v(3, 1, 0, 1, 0),
        v(-1, 0, -1, 3, 2),
    ];
    let l2 = vec![v(0, 0, 0, 1, 0), v(1, 0, 0, 2, 3)];
    let o = Opts {
        lods_header: Some(vec![0, 2]),
        ..Opts::default()
    };
    let m = charge(&fabrique(&[(0, l0), (2, l2)], &o)).unwrap();
    assert_eq!(m.lods(), &[0, 2]);
    assert_eq!(
        m.warnings(),
        &[
            VxmWarning::LodFallback {
                requested: 1,
                from: 0
            },
            VxmWarning::LodFallback {
                requested: 3,
                from: 2
            },
            VxmWarning::LodFallback {
                requested: 4,
                from: 2
            },
            VxmWarning::LodFallback {
                requested: 5,
                from: 2
            },
        ]
    );
    assert!(m.warnings()[0].to_string().contains("LOD 1 absent"));
    // LOD 1 dérivé : (0,0,0),(1,0,0)->(0,0,0) ; (2,0,0)->(1,0,0) ; (3,1,0)->(1,0,0) ; (-1,0,-1)->(-1,0,-1) : 3 cellules
    assert_eq!(m.voxel_count(1), 3);
    // même échelle que le fichier : le niveau 3 dérivé du niveau 2 est celui du niveau 2 réduit de 2
    assert_eq!(
        m.voxel_count(3),
        1,
        "les deux voxels du LOD 2 tombent dans la même cellule du LOD 3"
    );
    // au-delà du LOD 5 : rien
    assert_eq!(m.voxel_count(6), 0);
    assert!(m.bounds(6).is_empty());
}

#[test]
fn lod_vide_dans_le_fichier_est_traite_comme_absent() {
    let o = Opts {
        lods_header: Some(vec![0, 1]),
        ..Opts::default()
    };
    let m = charge(&fabrique(
        &[(0, vec![v(0, 0, 0, 1, 0), v(1, 0, 0, 1, 0)]), (1, vec![])],
        &o,
    ))
    .unwrap();
    assert_eq!(m.lods(), &[0], "le niveau vide n'est pas compté comme écrit");
    assert_eq!(m.voxel_count(1), 1);
    assert_eq!(
        m.warnings()[0],
        VxmWarning::LodFallback {
            requested: 1,
            from: 0
        }
    );
}

#[test]
fn reduction_garde_la_sorte_prioritaire() {
    // quatre voxels du LOD 0 dans une même cellule du LOD 1 : l'écorce l'emporte sur la feuille
    let l0 = vec![
        v(0, 0, 0, 2, 3),
        v(1, 0, 0, 1, 0),
        v(0, 0, 1, 2, 3),
        v(1, 0, 1, 2, 3),
    ];
    let m = Arc::new(charge(&fabrique(&[(0, l0)], &Opts::default())).unwrap());
    let p = PlacedModel::new(m, VoxelCoord::new(0, 0, 0), 0, 0).unwrap();
    let niveau1: Vec<_> = p.world_voxels(1).collect();
    assert_eq!(niveau1.len(), 1);
    assert_eq!(niveau1[0].1.material(), MaterialId::new(31));
}

// ---------------------------------------------------------------- générateur et scène

#[test]
fn le_modele_est_un_generateur_dont_le_plan_est_lui_meme() {
    let m = charge(&petit()).unwrap();
    assert_eq!(m.id(), em_gen::GeneratorId::VXM);
    let plan = m.plan(&GenParams::vxm(3).unwrap(), 0).unwrap();
    assert_eq!(plan.bounds(0), m.bounds(0));
    // rastérisation dans un chunk par la fenêtre locale
    let mut chunk = Chunk::new_air();
    {
        let mut w = em_voxel::ChunkWriter::new(&mut chunk, ChunkKey::new(0, 0, 0));
        plan.rasterize(0, m.bounds(0), &mut w);
    }
    assert_eq!(chunk.non_air_count(), 3);
    assert_eq!(chunk.get(0, 0, 0).tint(), tint_vegetation(3, 0));
    // paramètres d'un autre générateur ou mal formés : refusés
    let autres = GenParams::new(em_gen::GeneratorId::VXM, 1, vec![40]);
    assert!(matches!(m.plan(&autres, 0), Err(GenError::BadParams(_))));
    assert!(matches!(GenParams::vxm(32), Err(GenError::UnknownSpecies(32))));
}

#[test]
fn scene_statique_sol_plus_arbre() {
    let m = Arc::new(charge(&petit()).unwrap());
    let p = PlacedModel::new(m, VoxelCoord::new(10, 0, 10), 0, 0).unwrap();
    let s = StaticScene::tree_on_turf(p).unwrap();
    assert_eq!(s.ground_height(), Some(0));
    assert_eq!(s.models().count(), 1);
    let mut chunk = Chunk::new_air();
    s.fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut chunk);
    assert_eq!(
        chunk.get(10, 0, 10).material(),
        MaterialId::new(31),
        "le pied du tronc est posé sur le sol"
    );
    assert_eq!(chunk.get(0, 0, 0), VoxelValue::AIR, "au-dessus du sol : air");
    // le sol est sous y = 0 : on le lit dans le chunk du dessous
    s.fill_chunk(ChunkKey::new(0, -1, 0), 0, &mut chunk);
    assert_eq!(chunk.get(5, 63, 5).material(), MaterialId::new(1), "turf");
    assert!(
        StaticScene::builder().build().is_err(),
        "une scène vide est refusée"
    );
}

#[test]
fn etiquette_de_version_depend_de_la_pose() {
    let m = Arc::new(charge(&petit()).unwrap());
    let a = PlacedModel::new(m.clone(), VoxelCoord::new(0, 0, 0), 0, 0).unwrap();
    let b = PlacedModel::new(m.clone(), VoxelCoord::new(1, 0, 0), 0, 0).unwrap();
    let c = PlacedModel::new(m.clone(), VoxelCoord::new(0, 0, 0), 1, 0).unwrap();
    let d = PlacedModel::new(m, VoxelCoord::new(0, 0, 0), 0, 1).unwrap();
    let tags = [a.version_tag(), b.version_tag(), c.version_tag(), d.version_tag()];
    for i in 0..4 {
        for j in i + 1..4 {
            assert_ne!(tags[i], tags[j]);
        }
    }
    assert_eq!(a.version_tag(), a.clone().version_tag());
}

/// Les numéros de classe en dur de `VxmClasses::standard` sont ceux de la vraie table de matières du dépôt.
#[test]
fn classes_standard_egales_a_la_table_du_depot() {
    let donnees = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../engine/data");
    let table = em_material::MaterialTable::load(
        &donnees.join("materials.csv"),
        &donnees.join("material_render.toml"),
    )
    .expect("table de matières du dépôt");
    assert_eq!(
        em_gen::VxmClasses::from_table(&table).unwrap(),
        em_gen::VxmClasses::standard()
    );
}
