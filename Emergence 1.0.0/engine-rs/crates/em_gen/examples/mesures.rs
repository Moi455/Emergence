//! Mesures de L08 : temps de chargement et mémoire du chêne 42 (et des autres arbres de référence).
//! À lancer en release : `cargo run --release -p em_gen --example mesures`. Les chiffres rendus portent [Mesuré].

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use em_core::{ChunkKey, VoxelCoord};
use em_gen::{PlacedModel, VxmModel};
use em_voxel::{Chunk, VoxelSource};

fn main() {
    let dossier = std::env::args_os().nth(1).map_or_else(
        || {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
                .join(".local/share/emergence/lab_assets/trees")
        },
        PathBuf::from,
    );
    for nom in [
        "chene_42",
        "epicea_7",
        "peuplier_5",
        "bouleau_3",
        "buis_sphere_7",
        "rosier_4",
    ] {
        let chemin = dossier.join(format!("{nom}.vxm"));
        if !chemin.is_file() {
            eprintln!("IGNORÉ : {} absent", chemin.display());
            continue;
        }
        // chargement : 1 passe de chauffe (cache disque) puis 15 mesures
        let mut temps = Vec::new();
        let mut modele = VxmModel::load(&chemin).expect("chargement");
        for _ in 0..15 {
            let t = Instant::now();
            modele = VxmModel::load(&chemin).expect("chargement");
            temps.push(t.elapsed().as_secs_f64() * 1000.0);
        }
        temps.sort_by(f64::total_cmp);
        let (mini, med, maxi) = (temps[0], temps[temps.len() / 2], temps[temps.len() - 1]);
        println!(
            "{nom} : {} octets, {} voxels LOD0, chargement min {mini:.1} / médiane {med:.1} / max {maxi:.1} ms (n = 15), voxels en mémoire {:.2} Mo (6 niveaux)",
            modele.file_bytes(),
            modele.voxel_count(0),
            modele.memory_bytes() as f64 / 1e6
        );
        // rastérisation de chaque niveau dans des chunks : briques et octets
        let modele = Arc::new(modele);
        let placed = PlacedModel::new(modele.clone(), VoxelCoord::new(200_000, 0, 200_000), 0, 2).unwrap();
        for lod in [0_u8, 1, 2] {
            let b = placed.bounds(lod);
            let (k0, k1) = (
                b.min().chunk(),
                VoxelCoord::new(b.max().x - 1, b.max().y - 1, b.max().z - 1).chunk(),
            );
            let t = Instant::now();
            let (mut chunks, mut briques, mut palette, mut octets, mut pleins) = (0, 0, 0, 0, 0_u64);
            for cx in k0.x..=k1.x {
                for cy in k0.y..=k1.y {
                    for cz in k0.z..=k1.z {
                        let mut c = Chunk::new_air();
                        placed.fill_chunk(ChunkKey::new(cx, cy, cz), lod, &mut c);
                        if c.non_air_count() == 0 {
                            continue;
                        }
                        chunks += 1;
                        briques += c.bricks().filter(|b| !b.is_air()).count();
                        palette += c.palette_brick_count();
                        octets += c.memory_bytes();
                        pleins += u64::from(c.non_air_count());
                    }
                }
            }
            let ms = t.elapsed().as_secs_f64() * 1000.0;
            println!(
                "  LOD {lod} : {pleins} voxels, {chunks} chunks, {briques} briques non vides ({palette} à palette), {:.2} Mo de chunks, rastérisation {ms:.1} ms",
                octets as f64 / 1e6
            );
        }
    }
}
