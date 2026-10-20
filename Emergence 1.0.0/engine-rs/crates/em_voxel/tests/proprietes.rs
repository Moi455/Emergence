//! Tests de propriété de `em_voxel` : tirages par `SplitMix64` (jamais `rand`), aucune dépendance à l'ordre.

use std::sync::Arc;

use em_core::{ChunkKey, Fnv64, LeReader, LeWriter, Lod, MaterialId, SplitMix64, VoxelCoord, VoxelValue};
use em_voxel::*;

fn val(m: u16, t: u8) -> VoxelValue {
    VoxelValue::new(MaterialId::new(m), t)
}

/// Brique aléatoire avec exactement `k` valeurs distinctes (k ≤ 512).
fn brique_a_k_valeurs(g: &mut SplitMix64, k: usize) -> [VoxelValue; 512] {
    let mut valeurs: Vec<VoxelValue> = Vec::new();
    while valeurs.len() < k {
        let v = VoxelValue::from_raw(g.below(65_536) as u16);
        if !valeurs.contains(&v) {
            valeurs.push(v);
        }
    }
    let mut d = [VoxelValue::AIR; 512];
    // Les k premières cases portent chaque valeur une fois, le reste est tiré parmi elles.
    for (i, o) in d.iter_mut().enumerate() {
        *o = if i < k {
            valeurs[i]
        } else {
            valeurs[g.below(k as u64) as usize]
        };
    }
    // Mélange de Fisher-Yates déterministe.
    for i in (1..512).rev() {
        d.swap(i, g.below(i as u64 + 1) as usize);
    }
    d
}

#[test]
fn aller_retour_dense_palette_pour_tous_les_nombres_de_bits() {
    let mut g = SplitMix64::new(0xB41C);
    let cas: [(usize, u8); 7] = [(1, 0), (2, 1), (4, 2), (16, 4), (256, 8), (257, 16), (512, 16)];
    let mut total = 0;
    for tour in 0..1000 {
        let (k, bits) = cas[tour % cas.len()];
        let d = brique_a_k_valeurs(&mut g, k);
        let b = Brick::from_dense(&d);
        assert_eq!(b.bits(), bits, "k = {k}");
        let mut relu = [VoxelValue::AIR; 512];
        b.to_dense(&mut relu);
        assert_eq!(relu, d);
        for i in [0_u16, 1, 63, 64, 511] {
            assert_eq!(b.get(i), d[usize::from(i)]);
        }
        // Palette canonique : triée, sans doublon ; vide à 16 bits.
        let p = b.palette();
        if bits == 16 {
            assert!(p.is_empty());
        } else if bits > 0 {
            assert!(p.windows(2).all(|w| w[0] < w[1]));
            assert_eq!(p.len(), k);
        }
        total += 1;
    }
    assert_eq!(total, 1000);
}

#[test]
fn brique_uniforme_sans_allocation() {
    let b = Brick::uniform(val(5, 3));
    assert_eq!(b.is_uniform(), Some(val(5, 3)));
    assert_eq!(b.heap_bytes(), 0);
    assert_eq!(b.bits(), 0);
    assert_eq!(size_of::<Brick>(), 16);
    // Une brique dense dont toutes les valeurs sont égales redevient uniforme.
    assert_eq!(Brick::from_dense(&[val(5, 3); 512]), b);
}

#[test]
fn occupation_de_brique() {
    let b = Brick::air().with_voxel(em_core::voxel_index(3, 2, 5), val(1, 0));
    let occ = b.occupancy();
    assert_eq!(occ[2], 1 << (3 + 8 * 5));
    assert_eq!(b.non_air_count(), 1);
    assert_eq!(Brick::uniform(val(1, 0)).non_air_count(), 512);
}

#[test]
fn embk_aller_retour_et_refus_des_tronquees() {
    let mut g = SplitMix64::new(77);
    for k in [1_usize, 2, 3, 9, 100, 300] {
        let b = Brick::from_dense(&brique_a_k_valeurs(&mut g, k));
        let mut w = LeWriter::new();
        b.encode(&mut w);
        let octets = w.into_bytes();
        let mut r = LeReader::new(&octets);
        assert_eq!(Brick::decode(&mut r).unwrap(), b);
        assert!(r.is_finished());
        for coupe in 0..octets.len() {
            assert!(
                Brick::decode(&mut LeReader::new(&octets[..coupe])).is_err(),
                "k={k} coupe={coupe}"
            );
        }
    }
}

#[test]
fn embk_refuse_les_charges_invalides() {
    assert_eq!(
        Brick::decode(&mut LeReader::new(&[9])),
        Err(DecodeError::EtiquetteInconnue(9))
    );
    assert_eq!(
        Brick::decode(&mut LeReader::new(&[1, 3, 2, 0])),
        Err(DecodeError::BitsInvalides(3))
    );
    // 2 entrées de palette, 1 bit, mais un indice 1 est permis ; ici palette annoncée de 0 entrée.
    assert!(matches!(
        Brick::decode(&mut LeReader::new(&[1, 1, 0, 0])),
        Err(DecodeError::PaletteInvalide { .. })
    ));
    // Palette d'une entrée à 1 bit, mais un indice vaut 1.
    let mut w = LeWriter::new();
    w.u8(1).u8(1).u16(1).u16(7).bytes(&[0b1; 64]);
    assert!(matches!(
        Brick::decode(&mut LeReader::new(w.as_bytes())),
        Err(DecodeError::IndiceHorsPalette { .. })
    ));
}

#[test]
fn embk_non_canonique_est_normalisee() {
    // Palette en désordre avec doublon, indices tous 0 ou 1 : doit décoder vers la forme canonique.
    let mut w = LeWriter::new();
    w.u8(1).u8(1).u16(2).u16(9).u16(9);
    w.bytes(&[0b0101_0101; 64]);
    let b = Brick::decode(&mut LeReader::new(w.as_bytes())).unwrap();
    assert_eq!(b, Brick::uniform(VoxelValue::from_raw(9)));
}

/// Chunk synthétique : relief déterministe en trois matières.
fn chunk_synthetique() -> Chunk {
    let mut d = vec![VoxelValue::AIR; CHUNK_VOLUME];
    for y in 0..64_usize {
        for z in 0..64_usize {
            for x in 0..64_usize {
                let h = 20 + (x * 3 + z * 5) % 9;
                d[x + 64 * z + 4096 * y] = if y >= h {
                    VoxelValue::AIR
                } else if y + 4 >= h {
                    val(2, (x % 5) as u8)
                } else {
                    val(1, 0)
                };
            }
        }
    }
    Chunk::from_dense(&d).unwrap()
}

#[test]
fn empreinte_epinglee_d_un_chunk_synthetique() {
    let c = chunk_synthetique();
    // Épinglée : toute modification du format de hachage ou de la forme canonique doit la changer volontairement.
    assert_eq!(c.fingerprint_value(), 5_106_723_541_043_882_283);
}

#[test]
fn empreinte_independante_de_la_representation() {
    // Même contenu logique : chunk uniforme sans table, et chunk dont toutes les briques sont posées une à une.
    let a = Chunk::uniform(val(3, 1));
    let mut b = Chunk::new_air();
    for i in 0..512_u16 {
        b.set_brick(i, Brick::uniform(val(3, 1)));
    }
    assert_eq!(a, b);
    assert_eq!(a.fingerprint_value(), b.fingerprint_value());
    assert!(a.memory_bytes() < b.memory_bytes());
    b.compact();
    assert!(a.memory_bytes() == b.memory_bytes());
}

#[test]
fn chunk_dense_aller_retour_et_classement() {
    let c = chunk_synthetique();
    assert_eq!(c.classify(), ChunkClass::Mixed);
    let d = c.to_dense();
    assert_eq!(Chunk::from_dense(&d).unwrap(), c);
    assert!(Chunk::from_dense(&d[..10]).is_err());
    assert_eq!(c.get(5, 0, 7), val(1, 0));
    assert_eq!(c.get(5, 63, 7), VoxelValue::AIR);
    assert_eq!(Chunk::new_air().classify(), ChunkClass::Air);
    assert_eq!(
        Chunk::uniform(val(4, 0)).classify(),
        ChunkClass::Uniform(val(4, 0))
    );
}

#[test]
fn chunk_ecriture_lecture_avec_crc() {
    for c in [Chunk::new_air(), Chunk::uniform(val(8, 2)), chunk_synthetique()] {
        let mut w = LeWriter::new();
        c.encode(&mut w);
        let octets = w.into_bytes();
        assert_eq!(Chunk::decode(&octets).unwrap(), c);
        // Un octet corrompu au milieu est refusé.
        let mut mauvais = octets.clone();
        let m = mauvais.len() / 2;
        mauvais[m] ^= 0x10;
        assert!(Chunk::decode(&mauvais).is_err());
        // Tronqué ou avec octets en trop.
        assert!(Chunk::decode(&octets[..octets.len() - 1]).is_err());
        let mut long = octets.clone();
        long.push(0);
        assert!(Chunk::decode(&long).is_err());
    }
    assert_eq!(
        Chunk::decode(b"XXXX\x01\x00\x00\x00\x00\x00\x00"),
        Err(DecodeError::SignatureInvalide)
    );
}

#[test]
fn colonnes_d_occupation_egales_au_chunk() {
    let c = chunk_synthetique();
    let o = OccupancyColumns::from_chunk(&c);
    for z in (0..64).step_by(3) {
        for x in (0..64).step_by(5) {
            for y in 0..64 {
                assert_eq!(o.is_solid(x, y, z), !c.get(x, y, z).is_air());
            }
        }
    }
    assert_eq!(o.solid_count(), c.non_air_count());
    assert_eq!(
        OccupancyColumns::from_chunk(&Chunk::uniform(val(1, 0))).solid_count(),
        262_144
    );
}

// ---------- Réduction ----------

fn regle(priorite: &[u16]) -> ReduceRule {
    ReduceRule::majority_4_of_8(priorite.iter().map(|&m| MaterialId::new(m)).collect()).unwrap()
}

#[test]
fn reduction_cas_ecrits_a_la_main() {
    let pierre = val(10, 0);
    let terre = val(20, 5);
    let a = VoxelValue::AIR;
    let r = regle(&[]);
    // Mur mince d'un voxel (4 sur 8 : un plan x = 0) : plein.
    assert_eq!(r.reduce8([pierre, a, pierre, a, pierre, a, pierre, a]), pierre);
    // 3 sur 8 : air.
    assert_eq!(r.reduce8([pierre, pierre, pierre, a, a, a, a, a]), a);
    // 4 sur 8 : plein.
    assert_eq!(r.reduce8([pierre, pierre, pierre, pierre, a, a, a, a]), pierre);
    // Majorité de matière : 3 terre contre 2 pierre.
    assert_eq!(r.reduce8([pierre, terre, terre, pierre, terre, a, a, a]), terre);
    // Égalité 2-2 : la priorité tranche (pierre d'abord, puis terre d'abord).
    let egal = [terre, pierre, terre, pierre, a, a, a, a];
    assert_eq!(regle(&[10, 20]).reduce8(egal), pierre);
    assert_eq!(regle(&[20, 10]).reduce8(egal), terre);
    // Égalité sans priorité : la plus petite classe.
    assert_eq!(regle(&[]).reduce8(egal), pierre);
    // Priorité absente pour l'une : l'autre gagne.
    assert_eq!(regle(&[20]).reduce8(egal), terre);
    // Doublon de priorité refusé.
    assert!(ReduceRule::majority_4_of_8(vec![MaterialId::new(1), MaterialId::new(1)]).is_none());
    // Teinte du premier voxel de la matière gagnante.
    let t1 = val(20, 9);
    assert_eq!(r.reduce8([a, t1, terre, terre, terre, a, a, a]), t1);
}

#[test]
fn reduction_de_chunks() {
    let pierre = val(10, 0);
    let air = Chunk::new_air();
    let plein = Chunk::uniform(pierre);
    let r = regle(&[]);
    // Tous pleins : parent plein et uniforme. Tous air : air.
    let mut sortie = Chunk::new_air();
    reduce_2x([&plein; 8], &r, &mut sortie);
    assert_eq!(sortie.classify(), ChunkClass::Uniform(pierre));
    reduce_2x([&air; 8], &r, &mut sortie);
    assert_eq!(sortie.classify(), ChunkClass::Air);
    // Enfants du bas pleins (cy = 0 : indices 0..4), du haut vides : la moitié inférieure du parent est pleine.
    let enfants = [&plein, &plein, &plein, &plein, &air, &air, &air, &air];
    reduce_2x(enfants, &r, &mut sortie);
    assert_eq!(sortie.get(10, 31, 10), pierre);
    assert_eq!(sortie.get(10, 32, 10), VoxelValue::AIR);
    assert_eq!(sortie.get(63, 0, 63), pierre);
    // Enfant i = cx + 2cz + 4cy : seul l'enfant 1 (cx = 1) plein remplit l'octant x ≥ 32, y < 32, z < 32.
    let enfants = [&air, &plein, &air, &air, &air, &air, &air, &air];
    reduce_2x(enfants, &r, &mut sortie);
    assert_eq!(sortie.get(32, 0, 0), pierre);
    assert_eq!(sortie.get(31, 0, 0), VoxelValue::AIR);
    assert_eq!(sortie.get(32, 0, 32), VoxelValue::AIR);
    assert_eq!(sortie.get(32, 32, 0), VoxelValue::AIR);
    assert_eq!(sortie.non_air_count(), 32 * 32 * 32);
    // Un enfant fait d'un plan de 1 voxel d'épaisseur sur x pair : 4/8, donc plein partout.
    let mut d = vec![VoxelValue::AIR; CHUNK_VOLUME];
    for y in 0..64 {
        for z in 0..64 {
            for x in (0..64).step_by(2) {
                d[x + 64 * z + 4096 * y] = pierre;
            }
        }
    }
    let mince = Chunk::from_dense(&d).unwrap();
    reduce_2x(
        [&mince, &air, &air, &air, &air, &air, &air, &air],
        &r,
        &mut sortie,
    );
    assert_eq!(sortie.non_air_count(), 32 * 32 * 32);
}

// ---------- Rastérisation d'un volume, indépendante de l'ordre ----------

fn dans_sphere(p: VoxelCoord, c: VoxelCoord, r2: i64) -> bool {
    let (dx, dy, dz) = (i64::from(p.x - c.x), i64::from(p.y - c.y), i64::from(p.z - c.z));
    dx * dx + dy * dy + dz * dz <= r2
}

#[test]
fn rasterisation_d_un_volume_independante_de_l_ordre() {
    let cle = ChunkKey::new(-1, 0, 2);
    let o = cle.origin();
    let centre = VoxelCoord::new(o.x + 30, o.y + 33, o.z + 28);
    let r2 = 20_i64 * 20;
    let mut points = Vec::new();
    for dz in -22..=22 {
        for dy in -22..=22 {
            for dx in -22..=22 {
                let p = VoxelCoord::new(centre.x + dx, centre.y + dy, centre.z + dz);
                if dans_sphere(p, centre, r2) {
                    points.push(p);
                }
            }
        }
    }
    let ecrire = |ordre: &[VoxelCoord]| {
        let mut c = Chunk::new_air();
        let mut w = ChunkWriter::new(&mut c, cle);
        for &p in ordre {
            w.put(p, val(6, (p.x & 7) as u8), PutMode::Solid);
        }
        w.finish();
        c
    };
    let a = ecrire(&points);
    // Ordre inverse puis mélange déterministe.
    let mut inverse = points.clone();
    inverse.reverse();
    let mut g = SplitMix64::new(5);
    let mut melange = points.clone();
    for i in (1..melange.len()).rev() {
        melange.swap(i, g.below(i as u64 + 1) as usize);
    }
    let b = ecrire(&inverse);
    let c = ecrire(&melange);
    assert_eq!(a, b);
    assert_eq!(a, c);
    assert_eq!(a.fingerprint_value(), c.fingerprint_value());
    // Le chunk correspond au volume analytique, voxel par voxel.
    for y in 0..64_u32 {
        for z in 0..64_u32 {
            for x in 0..64_u32 {
                let p = VoxelCoord::new(o.x + x as i32, o.y + y as i32, o.z + z as i32);
                let attendu = dans_sphere(p, centre, r2);
                assert_eq!(!a.get(x, y, z).is_air(), attendu);
            }
        }
    }
    // Creuser une sphère plus petite en mode CarveAir.
    let mut creuse = a.clone();
    let mut w = ChunkWriter::new(&mut creuse, cle);
    for &p in points.iter().filter(|p| dans_sphere(**p, centre, 25)) {
        w.put(p, val(1, 0), PutMode::CarveAir);
    }
    w.finish();
    assert_eq!(creuse.get(30, 33, 28), VoxelValue::AIR);
    assert!(creuse.non_air_count() < a.non_air_count());
    // Les voxels hors du chunk sont comptés puis ignorés.
    let mut hors = Chunk::new_air();
    let mut w = ChunkWriter::new(&mut hors, cle);
    w.put(VoxelCoord::new(0, 0, 0), val(1, 0), PutMode::Solid);
    assert_eq!(w.ignored(), 1);
    drop(w);
    assert_eq!(hors.classify(), ChunkClass::Air);
}

// ---------- Sources ----------

#[test]
fn source_plate_a_tous_les_niveaux() {
    let s = FlatSource::new(100, val(1, 0));
    let mut c = Chunk::new_air();
    // Niveau 0, chunk y = 1 : voxels y = 64..127, plein sous 100.
    s.fill_chunk(ChunkKey::new(3, 1, -2), 0, &mut c);
    assert_eq!(c.get(0, 35, 0), val(1, 0));
    assert_eq!(c.get(0, 36, 0), VoxelValue::AIR);
    assert_eq!(s.classify(ChunkKey::new(0, 1, 0), 0), ChunkHint::Unknown);
    assert_eq!(s.classify(ChunkKey::new(0, 0, 0), 0), ChunkHint::Solid(val(1, 0)));
    assert_eq!(s.classify(ChunkKey::new(0, 2, 0), 0), ChunkHint::Air);
    // Niveau 2 : le voxel j couvre j*4, plein si j*4 < 100 donc j ≤ 24.
    s.fill_chunk(ChunkKey::new(0, 0, 0), 2, &mut c);
    assert_eq!(c.get(1, 24, 1), val(1, 0));
    assert_eq!(c.get(1, 25, 1), VoxelValue::AIR);
    // Sous le niveau de la mer des négatifs.
    s.fill_chunk(ChunkKey::new(0, -1, 0), 0, &mut c);
    assert_eq!(c.classify(), ChunkClass::Uniform(val(1, 0)));
    assert_eq!(s.voxel_at(VoxelCoord::new(-5, 99, 7), 0), val(1, 0));
    assert_eq!(s.voxel_at(VoxelCoord::new(-5, 100, 7), 0), VoxelValue::AIR);
}

/// Source de test : une sphère pleine de `valeur` (niveau 0 seulement), pour composer des couches.
struct SphereSource {
    centre: VoxelCoord,
    rayon2: i64,
    valeur: VoxelValue,
}

impl VoxelSource for SphereSource {
    fn fill_chunk(&self, key: ChunkKey, _lod: Lod, out: &mut Chunk) {
        *out = Chunk::new_air();
        let o = key.origin();
        let mut w = ChunkWriter::new(out, key);
        for z in 0..64 {
            for y in 0..64 {
                for x in 0..64 {
                    let p = VoxelCoord::new(o.x + x, o.y + y, o.z + z);
                    if dans_sphere(p, self.centre, self.rayon2) {
                        w.put(p, self.valeur, PutMode::Solid);
                    }
                }
            }
        }
    }
    fn version_tag(&self) -> u64 {
        self.valeur.raw().into()
    }
}

fn composite_a_trois_couches() -> CompositeSource {
    CompositeSource::new(vec![
        CompositeLayer::new(Arc::new(FlatSource::new(40, val(1, 0))), CompositeMode::Overlay),
        CompositeLayer::new(
            Arc::new(SphereSource {
                centre: VoxelCoord::new(32, 40, 32),
                rayon2: 15 * 15,
                valeur: val(2, 7),
            }),
            CompositeMode::Overlay,
        ),
        CompositeLayer::new(
            Arc::new(SphereSource {
                centre: VoxelCoord::new(40, 45, 32),
                rayon2: 8 * 8,
                valeur: val(3, 1),
            }),
            CompositeMode::Overlay,
        ),
    ])
    .unwrap()
}

#[test]
fn composite_de_trois_couches_ordre_fixe() {
    let comp = composite_a_trois_couches();
    assert_eq!(comp.layer_count(), 3);
    let mut c = Chunk::new_air();
    comp.fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut c);
    for (x, y, z) in [
        (5, 5, 5),
        (32, 40, 32),
        (40, 45, 32),
        (60, 60, 60),
        (0, 39, 63),
        (0, 40, 63),
        (47, 45, 32),
    ] {
        let p = VoxelCoord::new(x as i32, y as i32, z as i32);
        let attendu = if dans_sphere(p, VoxelCoord::new(40, 45, 32), 64) {
            val(3, 1)
        } else if dans_sphere(p, VoxelCoord::new(32, 40, 32), 225) {
            val(2, 7)
        } else if y < 40 {
            val(1, 0)
        } else {
            VoxelValue::AIR
        };
        assert_eq!(c.get(x, y, z), attendu, "({x},{y},{z})");
    }
    assert!(CompositeSource::new(Vec::new()).is_err());
    // Même résultat en remplissant deux fois (pureté).
    let mut c2 = Chunk::new_air();
    comp.fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut c2);
    assert_eq!(c, c2);
    assert_ne!(comp.version_tag(), 0);
}

#[test]
fn composite_remplacement_de_briques() {
    let base = Arc::new(FlatSource::new(64, val(1, 0)));
    let dessus = Arc::new(SphereSource {
        centre: VoxelCoord::new(4, 4, 4),
        rayon2: 1,
        valeur: val(9, 0),
    });
    let comp = CompositeSource::new(vec![
        CompositeLayer::new(base, CompositeMode::Overlay),
        CompositeLayer::new(dessus, CompositeMode::ReplaceBricks),
    ])
    .unwrap();
    let mut c = Chunk::new_air();
    comp.fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut c);
    // La brique (0,0,0) du dessus remplace entièrement celle du dessous : le reste de la brique devient air.
    assert_eq!(c.get(4, 4, 4), val(9, 0));
    assert_eq!(c.get(0, 0, 0), VoxelValue::AIR);
    assert_eq!(c.get(8, 0, 0), val(1, 0));
}

// ---------- Monde creux ----------

fn nouveau_monde() -> SparseWorld {
    SparseWorld::new(Arc::new(FlatSource::new(40, val(1, 0))))
}

fn editions() -> Vec<(VoxelCoord, VoxelValue)> {
    let mut g = SplitMix64::new(2026);
    (0..400)
        .map(|_| {
            let p = VoxelCoord::new(
                g.below(300) as i32 - 100,
                g.below(80) as i32 - 20,
                g.below(300) as i32 - 100,
            );
            (
                p,
                if g.below(3) == 0 {
                    VoxelValue::AIR
                } else {
                    val(2 + g.below(5) as u16, 0)
                },
            )
        })
        .collect()
}

#[test]
fn monde_creux_empreinte_independante_de_l_ordre() {
    let mut liste = editions();
    // Une seule édition par voxel, sinon l'ordre déciderait de la dernière valeur écrite.
    liste.sort_by_key(|(p, _)| *p);
    liste.dedup_by_key(|(p, _)| *p);
    let mut a = nouveau_monde();
    for (p, v) in &liste {
        a.set_voxel(*p, *v);
    }
    let mut g = SplitMix64::new(11);
    let mut melange = liste.clone();
    for i in (1..melange.len()).rev() {
        melange.swap(i, g.below(i as u64 + 1) as usize);
    }
    let mut b = nouveau_monde();
    for (p, v) in &melange {
        b.set_voxel(*p, *v);
    }
    assert_eq!(a.fingerprint(), b.fingerprint());
    assert_eq!(a.edited_brick_count(), b.edited_brick_count());
    assert_eq!(a.version_tag(), b.version_tag());
    for (p, v) in &liste {
        assert_eq!(a.voxel(*p), *v);
    }
    // Les chunks composés sont identiques voxel pour voxel.
    for key in [
        ChunkKey::new(0, 0, 0),
        ChunkKey::new(1, 0, 1),
        ChunkKey::new(-1, -1, 0),
    ] {
        let (mut ca, mut cb) = (Chunk::new_air(), Chunk::new_air());
        a.fill_chunk(key, 0, &mut ca);
        b.fill_chunk(key, 0, &mut cb);
        assert_eq!(ca, cb);
    }
    assert!(a.region_count() >= 1 && a.edited_chunk_count() >= 1);
}

#[test]
fn monde_creux_retire_les_briques_redevenues_egales_a_la_base() {
    let mut m = nouveau_monde();
    let p = VoxelCoord::new(3, 10, 3);
    let vide = m.fingerprint();
    m.set_voxel(p, val(5, 0));
    assert_eq!(m.edited_brick_count(), 1);
    assert_ne!(m.fingerprint(), vide);
    m.set_voxel(p, val(1, 0)); // retour à la valeur de la base
    assert_eq!(m.edited_brick_count(), 0);
    assert_eq!(m.region_count(), 0);
    assert_eq!(m.fingerprint(), vide);
    // Aucune allocation par voxel : une édition d'un voxel réécrit au plus une brique.
    m.set_voxel(VoxelCoord::new(100, 50, 100), val(5, 0));
    assert_eq!(m.edited_brick_count(), 1);
}

#[test]
fn monde_creux_ecriture_lecture_des_editions() {
    let mut a = nouveau_monde();
    let cle = ChunkKey::new(0, 0, 0);
    let n = a.edit_chunk(cle, |w| {
        for i in 0..30 {
            w.put(VoxelCoord::new(i, 20 + i % 5, 10), val(7, 0), PutMode::Solid);
            w.put(VoxelCoord::new(i, 10, 10), val(7, 0), PutMode::CarveAir);
        }
    });
    assert!(n >= 4);
    let mut w = LeWriter::new();
    a.encode_chunk_edits(cle, &mut w);
    let charge = w.into_bytes();
    let mut b = nouveau_monde();
    b.load_chunk_edits(cle, &charge).unwrap();
    assert_eq!(a.fingerprint(), b.fingerprint());
    let (mut ca, mut cb) = (Chunk::new_air(), Chunk::new_air());
    a.fill_chunk(cle, 0, &mut ca);
    b.fill_chunk(cle, 0, &mut cb);
    assert_eq!(ca, cb);
    // Charge tronquée : refusée, le monde reste inchangé.
    let avant = b.fingerprint();
    assert!(b.load_chunk_edits(cle, &charge[..charge.len() - 3]).is_err());
    assert_eq!(b.fingerprint(), avant);
    // Chunk sans édition : charge de 4 octets (n = 0).
    let mut w = LeWriter::new();
    a.encode_chunk_edits(ChunkKey::new(9, 9, 9), &mut w);
    assert_eq!(w.as_bytes(), &[0, 0, 0, 0]);
    // Charge d'édition vide : efface les éditions du chunk.
    b.load_chunk_edits(cle, &[0, 0, 0, 0]).unwrap();
    assert_eq!(b.edited_brick_count(), 0);
}

#[test]
fn lecture_identique_avec_plusieurs_fils() {
    let mut m = nouveau_monde();
    for (p, v) in editions() {
        m.set_voxel(p, v);
    }
    let m = Arc::new(m);
    let cles: Vec<ChunkKey> = (-2..3)
        .flat_map(|x| (-1..2).flat_map(move |y| (-2..3).map(move |z| ChunkKey::new(x, y, z))))
        .collect();
    let empreinte = |m: &SparseWorld, k: &ChunkKey| {
        let mut c = Chunk::new_air();
        m.fill_chunk(*k, 0, &mut c);
        let mut h = Fnv64::new();
        c.fingerprint(&mut h);
        h.value()
    };
    let seul: Vec<u64> = cles.iter().map(|k| empreinte(&m, k)).collect();
    for fils in [2_usize, 8] {
        let mut resultats = vec![0_u64; cles.len()];
        std::thread::scope(|s| {
            for (num, morceau) in resultats.chunks_mut(cles.len().div_ceil(fils)).enumerate() {
                let (m, cles) = (&m, &cles);
                let pas = cles.len().div_ceil(fils);
                s.spawn(move || {
                    // Parcours à l'envers pour changer l'ordre d'appel.
                    for (j, r) in morceau.iter_mut().enumerate().rev() {
                        *r = empreinte(m, &cles[num * pas + j]);
                    }
                });
            }
        });
        assert_eq!(resultats, seul, "{fils} fils");
    }
}

#[test]
fn memoire_des_chunks_creux() {
    // Les bornes de temps sont vérifiées par `examples/mesures.rs` (release) ; ici seulement la mémoire.
    let air = Chunk::new_air();
    assert!(air.memory_bytes() <= 64);
    let plein = Chunk::uniform(val(1, 0));
    assert!(plein.memory_bytes() <= 64);
    let mut c = Chunk::new_air();
    FlatSource::new(20, val(1, 0)).fill_chunk(ChunkKey::new(0, 0, 0), 0, &mut c);
    // Sol plat sur 20 voxels : 16 rangées de briques pleines + 8 de briques mixtes à 1 bit, soit bien moins que 64³ × 2 octets.
    assert!(c.memory_bytes() < 64 * 64 * 64 * 2 / 8);
}
