//! Les vrais fichiers de données : `engine/data/materials.csv` et `engine/data/material_render.toml`.

mod commun;

use commun::{dossier_donnees, table_reelle};
use em_core::MaterialId;
use em_material::{MaterialError, MaterialTable, TintMode};

/// Les 34 premières classes, telles que figées le 20 oct. : leurs numéros sont dans les sauvegardes.
const NOMS_20_OCT: [&str; 34] = [
    "air",
    "turf",
    "dirt",
    "clay",
    "sand",
    "gravel",
    "forest_floor",
    "snow",
    "limestone",
    "sandstone",
    "granite",
    "slate",
    "basalt",
    "salt",
    "iron_ore",
    "oak_raw",
    "oak_planks",
    "plaster",
    "roof_tile",
    "thatch",
    "cut_stone",
    "wood_trim",
    "wood_trim_worn",
    "rock_trim",
    "brick",
    "red_brick",
    "rubble_masonry",
    "iron",
    "glass",
    "vine",
    "leaves",
    "bark",
    "cobblestone",
    "cloth",
];

#[test]
fn trente_six_lignes_et_numeros_figes() {
    let t = table_reelle();
    assert_eq!(t.len(), 58); // 36 + la mousse (classe 36, L23p) + les 21 classes de L35 à L37 (37 à 57)
    for (i, nom) in NOMS_20_OCT.iter().enumerate() {
        let id = MaterialId::new(i as u16);
        assert_eq!(t.get(id).name(), *nom, "classe {i}");
        assert_eq!(t.by_name(nom), Some(id));
    }
    assert_eq!(t.by_name("petal"), Some(MaterialId::new(34)));
    assert_eq!(t.by_name("fruit"), Some(MaterialId::new(35)));
    assert_eq!(t.by_name("moss"), Some(MaterialId::new(36)));
    assert_eq!(t.get(MaterialId::new(34)).category(), "plant");
    assert_eq!(t.get(MaterialId::new(35)).category(), "plant");
    // les valeurs physiques lues
    let granite = t.get(t.by_name("granite").unwrap());
    assert_eq!(
        (
            granite.density_kg_m3(),
            granite.hardness(),
            granite.flammability()
        ),
        (2700, 80, 0)
    );
    assert_eq!(granite.base_srgb(), [0x8f, 0x8a, 0x86]);
}

#[test]
fn chaque_classe_a_un_aspect_valide() {
    let t = table_reelle();
    for d in t.iter() {
        let r = d.render();
        // héritage de [default] ou entrée propre : tous les champs sont dans leurs bornes
        assert!(
            r.roughness().raw() <= 65_536 && r.translucency().raw() <= 65_536,
            "{}",
            d.name()
        );
        assert!(r.detail_scale_m().raw() > 0, "{}", d.name());
    }
    // [default] : une classe sans entrée l'hérite (iron_ore a une entrée, air n'en a pas)
    let air = t.get(MaterialId::AIR).render();
    assert_eq!(air.tint_mode(), TintMode::Ramp128);
    assert_eq!(air.voxel_jitter().raw(), 1966); // 0,03 en Q16
    // modes de teinte par classe
    let mode = |n: &str| t.get(t.by_name(n).unwrap()).render().tint_mode();
    assert_eq!(mode("oak_planks"), TintMode::WoodAxis);
    assert_eq!(mode("cut_stone"), TintMode::StonePiece);
    assert_eq!(mode("leaves"), TintMode::Vegetation);
    assert_eq!(mode("bark"), TintMode::Vegetation);
    assert_eq!(mode("granite"), TintMode::Terrain);
}

#[test]
fn fichier_toml_sans_classe_inconnue_ni_champ_fautif() {
    let d = dossier_donnees();
    let csv = std::fs::read_to_string(d.join("materials.csv")).unwrap();
    let toml = std::fs::read_to_string(d.join("material_render.toml")).unwrap();
    let mauvais = format!("{toml}\n[material.mithril]\nrelief = 1\n");
    assert!(matches!(
        MaterialTable::from_sources(&csv, &mauvais),
        Err(MaterialError::MatiereInconnue(_))
    ));
    let faute = toml.replace("translucency = 0.45", "translucence = 0.45");
    assert!(matches!(
        MaterialTable::from_sources(&csv, &faute),
        Err(MaterialError::Toml(_))
    ));
    let hors = toml.replace("roughness = 0.8\n", "roughness = 1.5\n");
    assert!(matches!(
        MaterialTable::from_sources(&csv, &hors),
        Err(MaterialError::Valeur { .. })
    ));
    // numéro en double
    let double = format!("{csv}\n35,fruit2,plant,1,1,1,ffffff\n34,petal,plant,1,1,1,ffffff\n");
    assert!(MaterialTable::from_sources(&double, &toml).is_err());
}

#[test]
fn la_version_suit_les_fichiers() {
    let d = dossier_donnees();
    let csv = std::fs::read_to_string(d.join("materials.csv")).unwrap();
    let toml = std::fs::read_to_string(d.join("material_render.toml")).unwrap();
    let a = MaterialTable::from_sources(&csv, &toml).unwrap();
    let b = MaterialTable::from_sources(&csv, &toml.replace("relief = 0.3\n", "relief = 0.31\n")).unwrap();
    assert_eq!(a.version(), table_reelle().version());
    assert_ne!(a.version(), b.version());
}

#[test]
fn srgb_converti_une_seule_fois() {
    let t = table_reelle();
    // la couleur moyenne de la rampe est la couleur de base convertie par la table sRGB de la table
    let turf = t.get(t.by_name("turf").unwrap());
    assert_eq!(turf.ramp().colors()[1], t.srgb().convert(turf.base_srgb()));
}

#[test]
fn classes_d_extension_sans_collision() {
    let d = dossier_donnees();
    let csv = std::fs::read_to_string(d.join("materials.csv")).unwrap();
    let toml = std::fs::read_to_string(d.join("material_render.toml")).unwrap();
    // le CSV du jeu n'a que les 34 classes du 20 oct. ; petal et fruit viennent du TOML
    assert!(!csv.contains("petal"));
    let collision = toml.replace("id = 35", "id = 33");
    assert!(MaterialTable::from_sources(&csv, &collision).is_err());
}
