//! Mesures du maillage (L33) : temps de remplissage et de maillage du chêne, re-maillage d'un chunk 64³ modifié,
//! mémoire des quads. `cargo run --release -p em_mesh --example mesures`.

use em_core::{ChunkKey, VoxelCoord, VoxelValue};
use em_gen::{PlacedModel, StaticScene, VxmModel};
use em_material::{MaterialMode, MaterialTable, StyleConfig, StyleSheet};
use em_mesh::{ChunkMesher, MaterialColorer, MesherConfig, PaddedChunk, WorldMesher};
use em_voxel::{Chunk, VoxelSource};
use std::sync::Arc;
use std::time::Instant;

fn main() -> anyhow_free::Result {
    let racine = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let d = racine.join("engine/data");
    let table =
        MaterialTable::load(&d.join("materials.csv"), &d.join("material_render.toml")).expect("table");
    let home = std::env::var_os("HOME").unwrap_or_default();
    let f = std::path::PathBuf::from(home).join(".local/share/emergence/lab_assets/trees/chene_42.vxm");
    let modele = Arc::new(VxmModel::load(&f).expect("chêne"));
    let veg = em_gen::vegetation_ramps(modele.meta(), 0).expect("rampes");
    let pivot = VoxelCoord::new(200_000, 0, 200_000);
    let scene =
        StaticScene::tree_on_turf(PlacedModel::new(modele, pivot, 0, 0).expect("posé")).expect("scène");
    let b = scene.models_bounds(0).expect("boîte");
    let lo = b.min().chunk();
    let hi = VoxelCoord::new(b.max().x - 1, b.max().y - 1, b.max().z - 1).chunk();
    let mut cles = Vec::new();
    for y in lo.y - 1..=hi.y {
        for z in lo.z..=hi.z {
            for x in lo.x..=hi.x {
                cles.push(ChunkKey::new(x, y, z));
            }
        }
    }
    let colorier = MaterialColorer::new(&table, &veg, StyleSheet::continuous());
    for greedy in [false, true] {
        let wm = WorldMesher::new(&scene, &colorier, 0, MesherConfig::new(greedy));
        let t0 = Instant::now();
        let chunks = wm.charger(&cles);
        let t_fill = t0.elapsed();
        let t1 = Instant::now();
        let meshes = wm.mailler(&cles, &chunks);
        let t_mesh = t1.elapsed();
        let quads: usize = meshes.iter().map(|m| m.quad_count()).sum();
        let faces: u32 = meshes.iter().map(|m| m.face_count()).sum();
        let octets: usize = meshes.iter().map(|m| m.bytes()).sum();
        println!(
            "chêne greedy={greedy} : {} chunks maillés, {faces} faces, {quads} quads, {:.2} Mo, remplissage {:.1} ms, maillage parallèle {:.1} ms",
            meshes.len(),
            octets as f64 / 1e6,
            t_fill.as_secs_f64() * 1e3,
            t_mesh.as_secs_f64() * 1e3
        );
        // un cœur : chaque chunk maillé séparément, le plus lent et la médiane
        let mailleur = ChunkMesher::new(&colorier, MesherConfig::new(greedy));
        let mut temps = Vec::new();
        for k in &cles {
            let cherche = |c: ChunkKey| chunks.get(&c);
            let t = Instant::now();
            let p = PaddedChunk::gather(*k, &cherche);
            let m = mailleur.mesh(*k, 0, &p);
            let dt = t.elapsed().as_secs_f64() * 1e3;
            if !m.is_empty() {
                temps.push((dt, m.quad_count(), *k));
            }
        }
        temps.sort_by(|a, b| a.0.total_cmp(&b.0));
        let (med, max) = (temps[temps.len() / 2], temps[temps.len() - 1]);
        println!(
            "  un coeur, un chunk : médiane {:.2} ms ({} quads), le plus lent {:.2} ms ({} quads, chunk {:?})",
            med.0, med.1, max.0, max.1, max.2
        );
    }
    // re-maillage d'un chunk modifié : un voxel posé dans le chunk le plus chargé, puis maillage seul d'un cœur
    let (mut meilleur, mut cle) = (0_u32, cles[0]);
    let chunks = WorldMesher::new(&scene, &colorier, 0, MesherConfig::default()).charger(&cles);
    for k in &cles {
        let n = chunks[k].non_air_count();
        if n > meilleur {
            (meilleur, cle) = (n, *k);
        }
    }
    let mut edite: Chunk = chunks[&cle].clone();
    edite.set(31, 31, 31, VoxelValue::AIR);
    let mut copie = chunks.clone();
    copie.insert(cle, edite);
    let mailleur = ChunkMesher::new(&colorier, MesherConfig::default());
    let mut dts = Vec::new();
    for _ in 0..20 {
        let cherche = |c: ChunkKey| copie.get(&c);
        let t = Instant::now();
        let m = mailleur.mesh(cle, 0, &PaddedChunk::gather(cle, &cherche));
        dts.push((t.elapsed().as_secs_f64() * 1e3, m.quad_count()));
    }
    dts.sort_by(|a, b| a.0.total_cmp(&b.0));
    println!(
        "re-maillage du chunk le plus dense {cle:?} ({meilleur} voxels non vides) : médiane {:.2} ms, {} quads, un coeur",
        dts[10].0, dts[10].1
    );
    // mode voxel : la même chose avec la granulométrie renforcée sur une classe (coût de la couleur)
    let cfg = StyleConfig {
        pixel_classes: vec!["cut_stone".into()],
        params: Default::default(),
        granulometrie_force: None,
    };
    let _ = StyleSheet::from_config(&cfg, &table, MaterialMode::VoxelPixel).expect("style");
    let _ = scene.version_tag();
    Ok(())
}

mod anyhow_free {
    pub type Result = std::result::Result<(), String>;
}
