//! Essais du mailleur sur le chêne de référence et le vrai paquet de matières : déterminisme quel que soit le nombre
//! de fils, couleur plate par voxel (indépendante de la face), granulométrie renforcée, paramètres de surface.
//! Le chêne vient des assets de L04 (`~/.local/share/emergence/lab_assets/trees`) ; sans lui, ces essais s'ignorent.

use em_core::{ChunkKey, MaterialId, VoxelCoord, VoxelValue};
use em_gen::{PlacedModel, StaticScene, VxmModel};
use em_material::{
    MaterialMode, MaterialTable, PixelOverride, StyleConfig, StyleSheet, SurfaceParams, VegetationRamps,
};
use em_mesh::{ChunkMesh, MaterialColorer, MesherConfig, VoxelColorer, WorldMesher};
use std::path::PathBuf;
use std::sync::Arc;

fn donnees() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../engine/data")
}

fn table() -> MaterialTable {
    let d = donnees();
    MaterialTable::load(&d.join("materials.csv"), &d.join("material_render.toml"))
        .expect("table des matières")
}

fn chene() -> Option<PathBuf> {
    let dossier = std::env::var_os("EM_LAB_ASSETS").map_or_else(
        || {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
                .join(".local/share/emergence/lab_assets")
        },
        PathBuf::from,
    );
    let f = dossier.join("trees/chene_42.vxm");
    f.is_file().then_some(f)
}

fn scene_chene(f: &std::path::Path) -> (StaticScene, VegetationRamps) {
    let modele = Arc::new(VxmModel::load(f).expect("chêne"));
    let veg = em_gen::vegetation_ramps(modele.meta(), 0).expect("rampes");
    let pivot = VoxelCoord::new(200_000, 0, 200_000);
    let scene =
        StaticScene::tree_on_turf(PlacedModel::new(modele, pivot, 0, 0).expect("posé")).expect("scène");
    (scene, veg)
}

fn cles_du_chene(scene: &StaticScene) -> Vec<ChunkKey> {
    let b = scene.models_bounds(0).expect("boîte du chêne");
    let (lo, hi) = (
        b.min().chunk(),
        VoxelCoord::new(b.max().x - 1, b.max().y - 1, b.max().z - 1).chunk(),
    );
    let mut v = Vec::new();
    for y in lo.y - 1..=hi.y {
        for z in lo.z..=hi.z {
            for x in lo.x..=hi.x {
                v.push(ChunkKey::new(x, y, z));
            }
        }
    }
    v
}

fn empreinte(m: &[ChunkMesh]) -> Vec<u64> {
    m.iter().map(ChunkMesh::fingerprint).collect()
}

#[test]
fn le_chene_se_maille_identiquement_avec_un_ou_quatre_fils() {
    let Some(f) = chene() else {
        eprintln!("IGNORÉ : chene_42.vxm absent");
        return;
    };
    let t = table();
    let (scene, veg) = scene_chene(&f);
    let style = StyleSheet::continuous();
    let colorier = MaterialColorer::new(&t, &veg, style);
    let cles = cles_du_chene(&scene);
    let mailler = |fils: usize| {
        let pool = rayon::ThreadPoolBuilder::new().num_threads(fils).build().unwrap();
        pool.install(|| WorldMesher::new(&scene, &colorier, 0, MesherConfig::default()).mesh_chunks(&cles))
    };
    let (a, b) = (mailler(1), mailler(4));
    assert!(!a.is_empty());
    assert_eq!(
        empreinte(&a),
        empreinte(&b),
        "le nombre de fils ne change aucun octet"
    );
    for (x, y) in a.iter().zip(&b) {
        assert_eq!(x.as_bytes(), y.as_bytes());
    }
    let quads: usize = a.iter().map(ChunkMesh::quad_count).sum();
    let faces: u32 = a.iter().map(ChunkMesh::face_count).sum();
    assert!(quads > 10_000 && quads as u32 <= faces);
}

#[test]
fn la_couleur_d_un_voxel_est_plate_et_stable() {
    let t = table();
    let veg = VegetationRamps::new();
    let colorier = MaterialColorer::new(&t, &veg, StyleSheet::continuous());
    let v = VoxelValue::new(t.by_name("granite").unwrap(), 3);
    let p = VoxelCoord::new(10, 20, 30);
    // le colorieur n'a pas de notion de face : même voxel, même aspect, et deux voxels voisins peuvent différer
    assert_eq!(colorier.appearance(v, p, 0), colorier.appearance(v, p, 0));
    let autre = colorier.appearance(v, VoxelCoord::new(11, 20, 30), 0);
    let _ = autre;
}

fn variance_entre_voisins(force: Option<f64>) -> f64 {
    let t = table();
    let veg = VegetationRamps::new();
    let config = StyleConfig {
        pixel_classes: vec!["oak_raw".to_owned()],
        params: Default::default(),
        granulometrie_force: force,
    };
    let style = StyleSheet::from_config(&config, &t, MaterialMode::VoxelPixel).unwrap();
    let colorier = MaterialColorer::new(&t, &veg, style);
    // du bois : il ne se mouille pas, donc aucun assombrissement par cellule ne se mêle à la gigue mesurée
    let pierre = t.by_name("oak_raw").unwrap();
    // une rangée de voxels d'une même fibre : seuls la gigue et les tronçons de fibre les séparent
    let lum = |c: [u8; 3]| 0.2126 * f64::from(c[0]) + 0.7152 * f64::from(c[1]) + 0.0722 * f64::from(c[2]);
    let l: Vec<f64> = (0..400)
        .map(|x| {
            lum(colorier
                .appearance(VoxelValue::new(pierre, 0), VoxelCoord::new(x, 5, 7), 0)
                .color)
        })
        .collect();
    let moy: f64 = l.windows(2).map(|w| (w[0] - w[1]).abs()).sum::<f64>() / (l.len() - 1) as f64;
    moy
}

#[test]
fn la_granulometrie_renforcee_rend_les_voxels_voisins_plus_tranches() {
    let origine = variance_entre_voisins(Some(1.0));
    let defaut = variance_entre_voisins(None);
    let fort = variance_entre_voisins(Some(2.5));
    assert!(origine > 0.5, "le mode voxel varie : {origine}");
    assert!(defaut > origine * 1.4, "défaut {defaut} contre origine {origine}");
    assert!(fort > defaut);
    // et sans granulométrie, aucune différence entre deux voxels d'une même fibre
    assert!(variance_entre_voisins(Some(0.0)) < 1e-9);
    let _ = PixelOverride::default();
}

#[test]
fn les_parametres_de_surface_distinguent_pierre_mouillee_metal_et_bois_sec() {
    let t = table();
    let veg = VegetationRamps::new();
    let colorier = MaterialColorer::new(&t, &veg, StyleSheet::continuous());
    let parametres = |nom: &str, x: i32| -> SurfaceParams {
        let id: MaterialId = t.by_name(nom).unwrap();
        SurfaceParams::unpack(
            colorier
                .appearance(VoxelValue::new(id, 1), VoxelCoord::new(x, 0, 0), 0)
                .params,
        )
    };
    // le fer brille toujours, le bois sec jamais
    let fer = parametres("iron", 0);
    let bois = parametres("oak_planks", 0);
    assert!(fer.reflection() >= 4, "fer : {fer:?}");
    assert!(bois.reflection() <= 2, "bois sec : {bois:?}");
    assert_eq!(fer.porosity(), 0);
    assert!(bois.porosity() >= 3);
    // la pierre : sèche = mate, mouillée (une cellule de 40 cm sur deux environ) = brillante et plus sombre
    let sec = (0..400)
        .map(|x| parametres("limestone", x * 8))
        .map(|p| p.reflection())
        .min()
        .unwrap();
    let mouille = (0..400)
        .map(|x| parametres("limestone", x * 8))
        .map(|p| p.reflection())
        .max()
        .unwrap();
    assert!(mouille >= sec + 3, "pierre sèche {sec}, mouillée {mouille}");
    // l'assombrissement : un voxel mouillé est plus sombre qu'un sec de même classe et même teinte
    let lum = |x: i32| {
        let c = colorier
            .appearance(
                VoxelValue::new(t.by_name("limestone").unwrap(), 1),
                VoxelCoord::new(x * 8, 0, 0),
                0,
            )
            .color;
        u32::from(c[0]) + u32::from(c[1]) + u32::from(c[2])
    };
    let (clair, sombre) = ((0..400).map(lum).max().unwrap(), (0..400).map(lum).min().unwrap());
    assert!(sombre * 10 < clair * 9, "mouillé {sombre} contre sec {clair}");
}
