//! Aides communes aux tests d'intégration : chargement des vrais fichiers de données du dépôt.
#![allow(dead_code)]

use em_material::{MaterialTable, RampRole, VegetationRamps};
use std::path::PathBuf;

pub fn dossier_donnees() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../engine/data")
}

pub fn table_reelle() -> MaterialTable {
    let d = dossier_donnees();
    MaterialTable::load(&d.join("materials.csv"), &d.join("material_render.toml"))
        .expect("chargement des données")
}

/// Rampes de végétation de test : deux essences, saison « été ».
pub fn vegetation_test() -> VegetationRamps {
    let mut v = VegetationRamps::new();
    let feuilles = [
        [[22, 48, 14], [58, 110, 32], [120, 170, 60]],
        [[30, 60, 16], [84, 130, 40], [150, 190, 70]],
    ];
    v.register("chene", RampRole::Leaves, &feuilles).unwrap();
    v.register(
        "chene",
        RampRole::Bark,
        &[
            [[40, 30, 22], [90, 70, 50], [130, 108, 80]],
            [[50, 40, 30], [104, 86, 64], [140, 120, 92]],
        ],
    )
    .unwrap();
    v.register("pommier", RampRole::Leaves, &feuilles[..1]).unwrap();
    v.register(
        "pommier",
        RampRole::Flowers,
        &[[[200, 150, 160], [240, 190, 200], [255, 230, 235]]],
    )
    .unwrap();
    v.register(
        "pommier",
        RampRole::Fruits,
        &[[[120, 20, 20], [190, 50, 40], [230, 100, 80]]],
    )
    .unwrap();
    v
}
