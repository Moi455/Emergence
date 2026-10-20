//! Mesures de `em_voxel` : mémoire par chunk et débit lecture/écriture. À lancer en release :
//! `cargo run --release -p em_voxel --example mesures`. Les chiffres rendus portent [Mesuré].

use std::hint::black_box;
use std::sync::Arc;
use std::time::Instant;

use em_core::{ChunkKey, Lod, MaterialId, VoxelCoord, VoxelValue};
use em_voxel::*;

fn val(m: u16, t: u8) -> VoxelValue {
    VoxelValue::new(MaterialId::new(m), t)
}

struct Sphere {
    c: VoxelCoord,
    r2: i64,
    v: VoxelValue,
}

impl VoxelSource for Sphere {
    fn fill_chunk(&self, key: ChunkKey, _lod: Lod, out: &mut Chunk) {
        *out = Chunk::new_air();
        let o = key.origin();
        let mut w = ChunkWriter::new(out, key);
        for z in 0..64 {
            for y in 0..64 {
                for x in 0..64 {
                    let (dx, dy, dz) = (
                        i64::from(o.x + x - self.c.x),
                        i64::from(o.y + y - self.c.y),
                        i64::from(o.z + z - self.c.z),
                    );
                    if dx * dx + dy * dy + dz * dz <= self.r2 {
                        w.put(VoxelCoord::new(o.x + x, o.y + y, o.z + z), self.v, PutMode::Solid);
                    }
                }
            }
        }
    }
    fn version_tag(&self) -> u64 {
        1
    }
}

fn chronometre<F: FnMut()>(tours: u32, mut f: F) -> f64 {
    f(); // échauffement
    let t = Instant::now();
    for _ in 0..tours {
        f();
    }
    t.elapsed().as_secs_f64() / f64::from(tours)
}

fn main() {
    // --- Mémoire par chunk ---
    let mut relief = vec![VoxelValue::AIR; CHUNK_VOLUME];
    for y in 0..64_usize {
        for z in 0..64_usize {
            for x in 0..64_usize {
                let h = 20 + (x * 3 + z * 5) % 9;
                relief[x + 64 * z + 4096 * y] = if y >= h {
                    VoxelValue::AIR
                } else if y + 4 >= h {
                    val(2, (x % 5) as u8)
                } else {
                    val(1, 0)
                };
            }
        }
    }
    let mut bruit = vec![VoxelValue::AIR; CHUNK_VOLUME];
    let mut g = em_core::SplitMix64::new(1);
    for v in bruit.iter_mut() {
        *v = VoxelValue::from_raw(g.below(65_536) as u16);
    }
    let mut plat = Chunk::new_air();
    FlatSource::new(20, val(1, 0)).fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut plat);
    let cas: Vec<(&str, Chunk)> = vec![
        ("air", Chunk::new_air()),
        ("plein uniforme", Chunk::uniform(val(1, 0))),
        ("sol plat (surface dans le chunk)", plat),
        ("relief 3 matières", Chunk::from_dense(&relief).unwrap()),
        ("bruit (pire cas, 16 bits)", Chunk::from_dense(&bruit).unwrap()),
    ];
    println!(
        "Mémoire par chunk 64³ [Mesuré] (dense de référence : {} octets à 2 o/voxel)",
        CHUNK_VOLUME * 2
    );
    for (nom, c) in &cas {
        println!(
            "  {nom:<34} {:>8} octets, {:>3} briques à palette",
            c.memory_bytes(),
            c.palette_brick_count()
        );
    }

    // --- Débit ---
    let relief_chunk = &cas[3].1;
    let mut sortie = 0_u64;
    let t_lecture = chronometre(20, || {
        let mut s = 0_u64;
        for y in 0..64 {
            for z in 0..64 {
                for x in 0..64 {
                    s += u64::from(relief_chunk.get(x, y, z).raw());
                }
            }
        }
        sortie ^= black_box(s);
    });
    let t_ecriture = chronometre(10, || {
        let mut c = Chunk::new_air();
        let mut w = ChunkWriter::new(&mut c, ChunkKey::new(0, 0, 0));
        for y in 0..64 {
            for z in 0..64 {
                for x in 0..64 {
                    w.put(
                        VoxelCoord::new(x, y, z),
                        val(1 + (x as u16 & 3), 0),
                        PutMode::Solid,
                    );
                }
            }
        }
        w.finish();
        black_box(&c);
    });
    let t_dense = chronometre(50, || {
        black_box(Chunk::from_dense(black_box(&relief)).unwrap());
    });
    let t_empreinte = chronometre(100, || {
        black_box(relief_chunk.fingerprint_value());
    });
    let mut octets = em_core::LeWriter::new();
    relief_chunk.encode(&mut octets);
    let t_encode = chronometre(100, || {
        let mut w = em_core::LeWriter::new();
        relief_chunk.encode(&mut w);
        black_box(w);
    });
    let t_decode = chronometre(100, || {
        black_box(Chunk::decode(octets.as_bytes()).unwrap());
    });
    let mvox = |t: f64| (CHUNK_VOLUME as f64) / t / 1.0e6;
    println!(
        "Débit, 1 fil, release [Mesuré] (relief 3 matières, {} octets encodés)",
        octets.len()
    );
    println!(
        "  lecture voxel par voxel      : {:.0} Mvoxels/s ({:.1} us/chunk)",
        mvox(t_lecture),
        t_lecture * 1e6
    );
    println!(
        "  écriture via ChunkWriter     : {:.0} Mvoxels/s ({:.1} us/chunk)",
        mvox(t_ecriture),
        t_ecriture * 1e6
    );
    println!(
        "  construction depuis dense    : {:.0} Mvoxels/s ({:.1} us/chunk)",
        mvox(t_dense),
        t_dense * 1e6
    );
    println!(
        "  empreinte FNV                : {:.1} us/chunk",
        t_empreinte * 1e6
    );
    println!(
        "  encodage EMCK / décodage     : {:.1} us / {:.1} us",
        t_encode * 1e6,
        t_decode * 1e6
    );

    // --- Acceptation (5) : CompositeSource de 3 couches, chunk mixte, 1 fil ---
    // Les couches « sphère » rastérisent voxel par voxel : c'est le pire cas ; le sol plat est le cas courant.
    let comp = CompositeSource::new(vec![
        CompositeLayer::new(Arc::new(FlatSource::new(40, val(1, 0))), CompositeMode::Overlay),
        CompositeLayer::new(
            Arc::new(FlatSource::new(46, val(3, 0))),
            CompositeMode::ReplaceBricks,
        ),
        CompositeLayer::new(Arc::new(FlatSource::new(52, val(2, 3))), CompositeMode::Overlay),
    ])
    .unwrap();
    let mut out = Chunk::new_air();
    let t_comp = chronometre(2000, || {
        comp.fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut out);
        black_box(&out);
    });
    println!(
        "CompositeSource de 3 couches (sols plats), chunk mixte [Mesuré] : {:.3} ms/chunk (seuil 0,3 ms : {})",
        t_comp * 1e3,
        if t_comp * 1e3 <= 0.3 { "tenu" } else { "NON TENU" }
    );
    let comp_s = CompositeSource::new(vec![
        CompositeLayer::new(Arc::new(FlatSource::new(40, val(1, 0))), CompositeMode::Overlay),
        CompositeLayer::new(
            Arc::new(Sphere {
                c: VoxelCoord::new(32, 40, 32),
                r2: 225,
                v: val(2, 7),
            }),
            CompositeMode::Overlay,
        ),
        CompositeLayer::new(Arc::new(FlatSource::new(46, val(3, 0))), CompositeMode::Overlay),
    ])
    .unwrap();
    let t_comp_s = chronometre(200, || {
        comp_s.fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut out);
        black_box(&out);
    });
    println!(
        "CompositeSource avec une couche sphère rastérisée voxel par voxel [Mesuré] : {:.3} ms/chunk",
        t_comp_s * 1e3
    );

    // --- Monde creux ---
    let mut monde = SparseWorld::new(Arc::new(FlatSource::new(40, val(1, 0))));
    let t = Instant::now();
    for i in 0..1000 {
        monde.set_voxel(VoxelCoord::new(i % 97, 30 + i % 17, (i * 7) % 89), val(5, 0));
    }
    println!(
        "SparseWorld : 1000 set_voxel en {:.2} ms, {} briques réécrites sur {} chunk(s)",
        t.elapsed().as_secs_f64() * 1e3,
        monde.edited_brick_count(),
        monde.edited_chunk_count()
    );
    black_box(sortie);
}
