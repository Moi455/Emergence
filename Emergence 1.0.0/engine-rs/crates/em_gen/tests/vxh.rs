//! Tests du chargeur `.vxh` (L34) : validation stricte (en-tête, zlib borné, tailles, invariant couleur/matériau,
//! drapeaux), classes de matière, pose (z inversé) et chunks. Les vraies maisons cuites sont lues si elles existent.

use std::io::Write;
use std::sync::Arc;

use em_core::{ChunkKey, MaterialId, VoxelCoord};
use em_gen::{HouseClasses, PlacedHouse, VxhCell, VxhError, VxhFlags, VxhMaterial, VxhModel};
use em_material::MaterialTable;
use em_voxel::{Chunk, VoxelSource};
use flate2::Compression;
use flate2::write::ZlibEncoder;

/// Une grille à fabriquer : couleurs, matériaux, drapeaux (index `(y * nz + z) * nx + x`).
struct Grille {
    d: [u32; 3],
    sol: u32,
    couleurs: Vec<u16>,
    materiaux: Vec<u8>,
    drapeaux: Vec<u8>,
}

impl Grille {
    fn vide(d: [u32; 3]) -> Self {
        let n = (d[0] * d[1] * d[2]) as usize;
        Self {
            d,
            sol: 1,
            couleurs: vec![0; n],
            materiaux: vec![0; n],
            drapeaux: vec![0; n],
        }
    }

    fn pose(&mut self, x: u32, y: u32, z: u32, c: u16, m: u8, f: u8) {
        let i = ((y * self.d[2] + z) * self.d[0] + x) as usize;
        (self.couleurs[i], self.materiaux[i], self.drapeaux[i]) = (c, m, f);
    }

    fn corps(&self) -> Vec<u8> {
        let mut c: Vec<u8> = self.couleurs.iter().flat_map(|v| v.to_le_bytes()).collect();
        c.extend_from_slice(&self.materiaux);
        c.extend_from_slice(&self.drapeaux);
        c
    }

    fn octets(&self) -> Vec<u8> {
        entete_et_corps(self.d, self.sol, &self.corps())
    }
}

fn zlib(corps: &[u8]) -> Vec<u8> {
    let mut e = ZlibEncoder::new(Vec::new(), Compression::default());
    e.write_all(corps).unwrap();
    e.finish().unwrap()
}

fn entete_et_corps(d: [u32; 3], sol: u32, corps: &[u8]) -> Vec<u8> {
    let mut o = b"VXH1".to_vec();
    for v in d {
        o.extend_from_slice(&v.to_le_bytes());
    }
    o.extend_from_slice(&0.05_f32.to_le_bytes());
    o.extend_from_slice(&sol.to_le_bytes());
    o.extend_from_slice(&[0; 8]);
    o.extend_from_slice(&zlib(corps));
    o
}

fn petite() -> Grille {
    let mut g = Grille::vide([4, 3, 5]);
    g.pose(1, 1, 1, 0xF800, 1, 0); // pierre rouge
    g.pose(2, 1, 1, 0x07E0, 4, VxhFlags::SOFT); // herbe
    g.pose(1, 2, 3, 0xFFE0, 2, VxhFlags::EMISSIVE | VxhFlags::INTERIOR);
    g.pose(3, 0, 4, 0x0000, 0, VxhFlags::GLASS); // verre vide
    g
}

#[test]
fn fichier_minimal_valide() {
    let m = VxhModel::from_bytes(&petite().octets()).unwrap();
    assert_eq!(m.dims(), [4, 3, 5]);
    assert_eq!(m.voxel_count(), 3);
    assert_eq!(m.ground_layers(), 1);
    let c = m.cell(1, 1, 1).unwrap();
    assert_eq!((c.color565(), c.material()), (0xF800, VxhMaterial::Stone));
    assert_eq!(c.rgb8(), [255, 0, 0]);
    assert!(m.cell(2, 1, 1).unwrap().flags().soft());
    let l = m.cell(1, 2, 3).unwrap().flags();
    assert!(l.emissive() && l.interior() && !l.glass());
    assert!(m.cell(0, 0, 0).is_none() && m.cell(-1, 0, 0).is_none() && m.cell(4, 0, 0).is_none());
    assert!(m.is_glass(3, 0, 4) && m.cell(3, 0, 4).is_none());
}

#[test]
fn entete_invalide() {
    let bon = petite().octets();
    assert_eq!(
        VxhModel::from_bytes(&bon[..10]).unwrap_err(),
        VxhError::TropCourt(10)
    );
    let mut mauvais = bon.clone();
    mauvais[0] = b'Y';
    assert_eq!(VxhModel::from_bytes(&mauvais).unwrap_err(), VxhError::Signature);
    // dimension nulle puis démesurée
    for (axe, v) in [(4_usize, 0_u32), (8, 5000), (12, 0)] {
        let mut m = bon.clone();
        m[axe..axe + 4].copy_from_slice(&v.to_le_bytes());
        assert!(matches!(
            VxhModel::from_bytes(&m).unwrap_err(),
            VxhError::Dimension { .. }
        ));
    }
    // voxel de 10 cm
    let mut m = bon.clone();
    m[16..20].copy_from_slice(&0.1_f32.to_le_bytes());
    assert!(matches!(
        VxhModel::from_bytes(&m).unwrap_err(),
        VxhError::VoxelHorsGrille(_)
    ));
    // sol plus haut que la grille
    let mut m = bon.clone();
    m[20..24].copy_from_slice(&9_u32.to_le_bytes());
    assert!(matches!(
        VxhModel::from_bytes(&m).unwrap_err(),
        VxhError::SolHorsGrille { couches: 9, ny: 3 }
    ));
    // réservés non nuls
    let mut m = bon;
    m[30] = 1;
    assert_eq!(VxhModel::from_bytes(&m).unwrap_err(), VxhError::ReservesNonNuls);
}

#[test]
fn trop_de_cellules_refuse_avant_toute_decompression() {
    // 1024 x 1024 x 64 = 2^26 cellules > 2^25 : refusé sur l'en-tête seul
    let mut o = b"VXH1".to_vec();
    for v in [1024_u32, 64, 1024] {
        o.extend_from_slice(&v.to_le_bytes());
    }
    o.extend_from_slice(&0.05_f32.to_le_bytes());
    o.extend_from_slice(&0_u32.to_le_bytes());
    o.extend_from_slice(&[0; 8]);
    assert!(matches!(
        VxhModel::from_bytes(&o).unwrap_err(),
        VxhError::TropDeCellules(_)
    ));
}

#[test]
fn bombe_zlib_et_tailles_incoherentes() {
    // une bombe : 200 Mo de zéros pour une grille de 60 octets (4 x 3 x 5 x 4 = 240)
    let bombe = vec![0_u8; 200 << 20];
    let o = entete_et_corps([4, 3, 5], 1, &bombe);
    assert!(o.len() < 1 << 20, "la bombe compresse très bien");
    match VxhModel::from_bytes(&o).unwrap_err() {
        VxhError::CorpsTaille { lu, attendu } => assert_eq!((lu, attendu), (241, 240)),
        autre => panic!("bombe : {autre:?}"),
    }
    // corps trop court
    let o = entete_et_corps([4, 3, 5], 1, &vec![0; 239]);
    assert!(matches!(
        VxhModel::from_bytes(&o).unwrap_err(),
        VxhError::CorpsTaille {
            lu: 239,
            attendu: 240
        }
    ));
    // flux qui n'est pas du zlib
    let mut o = petite().octets();
    let n = o.len();
    o[32..n].fill(0xAB);
    assert!(matches!(
        VxhModel::from_bytes(&o).unwrap_err(),
        VxhError::CorpsZlib(_)
    ));
    // flux zlib tronqué
    let o = petite().octets();
    assert!(matches!(
        VxhModel::from_bytes(&o[..o.len() - 6]).unwrap_err(),
        VxhError::CorpsZlib(_) | VxhError::CorpsTaille { .. }
    ));
}

#[test]
fn invariant_couleur_materiau() {
    // couleur sans matériau
    let mut g = petite();
    g.pose(0, 0, 0, 0x1234, 0, 0);
    assert!(matches!(
        VxhModel::from_bytes(&g.octets()).unwrap_err(),
        VxhError::Invariant {
            couleur: 0x1234,
            materiau: 0,
            ..
        }
    ));
    // matériau sans couleur
    let mut g = petite();
    g.pose(0, 0, 0, 0, 3, 0);
    assert!(matches!(
        VxhModel::from_bytes(&g.octets()).unwrap_err(),
        VxhError::Invariant { materiau: 3, .. }
    ));
    // matériau hors de 1..=5
    let mut g = petite();
    g.pose(0, 0, 0, 0x1234, 6, 0);
    assert!(matches!(
        VxhModel::from_bytes(&g.octets()).unwrap_err(),
        VxhError::MateriauInvalide { materiau: 6, .. }
    ));
}

#[test]
fn drapeaux_inconnus_ou_sur_une_cellule_vide() {
    let mut g = petite();
    g.pose(0, 0, 0, 0x1234, 1, 0x10);
    assert!(matches!(
        VxhModel::from_bytes(&g.octets()).unwrap_err(),
        VxhError::DrapeauxInvalides { drapeaux: 0x10, .. }
    ));
    // émissif sur du vide : refusé (seul le verre peut être vide)
    let mut g = petite();
    g.pose(0, 0, 0, 0, 0, VxhFlags::EMISSIVE);
    assert!(matches!(
        VxhModel::from_bytes(&g.octets()).unwrap_err(),
        VxhError::DrapeauxInvalides { .. }
    ));
}

fn cellule(c: u16, m: VxhMaterial, f: u8) -> VxhCell {
    VxhCell::new(c, m, VxhFlags::from_bits(f).unwrap()).unwrap()
}

fn rgb565(r: u8, g: u8, b: u8) -> u16 {
    u16::from(r >> 3) << 11 | u16::from(g >> 2) << 5 | u16::from(b >> 3)
}

#[test]
fn classes_selon_materiau_et_teinte() {
    let k = HouseClasses::standard();
    let id = |n: u16| MaterialId::new(n);
    let tout = |r, g, b, m, f| k.class_of(cellule(rgb565(r, g, b), m, f));
    assert_eq!(tout(150, 146, 138, VxhMaterial::Stone, 0), id(20), "pierre");
    assert_eq!(
        tout(46, 44, 48, VxhMaterial::Stone, 0),
        id(27),
        "fer : sombre et neutre"
    );
    assert_eq!(
        tout(68, 60, 52, VxhMaterial::Stone, 0),
        id(20),
        "mortier brun : pierre"
    );
    assert_eq!(tout(88, 60, 38, VxhMaterial::Wood, 0), id(15));
    assert_eq!(tout(208, 192, 160, VxhMaterial::Plaster, 0), id(17));
    assert_eq!(
        tout(96, 128, 52, VxhMaterial::Ground, VxhFlags::SOFT),
        id(1),
        "herbe"
    );
    assert_eq!(tout(92, 68, 46, VxhMaterial::Ground, 0), id(2), "terre");
    assert_eq!(
        tout(238, 198, 72, VxhMaterial::Ground, VxhFlags::SOFT),
        id(34),
        "fleur"
    );
    assert_eq!(tout(78, 84, 94, VxhMaterial::Roof, 0), id(11), "ardoise");
    assert_eq!(tout(124, 94, 68, VxhMaterial::Roof, 0), id(22), "bardeau");
    assert_eq!(tout(172, 94, 62, VxhMaterial::Roof, 0), id(18), "tuile");
    assert_eq!(
        tout(168, 200, 208, VxhMaterial::Stone, VxhFlags::GLASS),
        id(28),
        "verre"
    );
}

#[test]
fn les_classes_standard_sont_celles_de_la_vraie_table() {
    let donnees = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../engine/data");
    let table = MaterialTable::load(
        &donnees.join("materials.csv"),
        &donnees.join("material_render.toml"),
    )
    .unwrap();
    assert_eq!(
        HouseClasses::from_table(&table).unwrap(),
        HouseClasses::standard()
    );
}

#[test]
fn la_pose_inverse_z_et_decale_x_et_y() {
    let m = Arc::new(VxhModel::from_bytes(&petite().octets()).unwrap());
    // ancre : cellule (x 1, niveau des murs y = 1, z 1) -> monde (100, 7, 200)
    let h = PlacedHouse::new(m, HouseClasses::standard(), [1, 1], VoxelCoord::new(100, 7, 200));
    assert_eq!(h.world_of([1, 1, 1]), VoxelCoord::new(100, 7, 200));
    assert_eq!(h.world_of([2, 2, 3]), VoxelCoord::new(101, 8, 198), "z inversé");
    assert_eq!(h.world_of([1, 2, 3]), VoxelCoord::new(100, 8, 198));
    let b = h.bounds();
    assert_eq!(
        (b.min(), b.max()),
        (VoxelCoord::new(99, 6, 197), VoxelCoord::new(103, 9, 202))
    );
    for g in [[1, 1, 1], [2, 1, 1], [1, 2, 3], [0, 0, 0], [3, 2, 4]] {
        assert_eq!(h.grid_of(h.world_of(g)), g);
    }
    let pierre = h.cell_at(VoxelCoord::new(100, 7, 200)).unwrap();
    assert_eq!(pierre.material(), VxhMaterial::Stone);
    assert_eq!(
        h.cell_at(VoxelCoord::new(100, 8, 198)).unwrap().color565(),
        0xFFE0
    );
    assert!(h.cell_at(VoxelCoord::new(0, 0, 0)).is_none());
    assert!(h.is_glass_at(h.world_of([3, 0, 4])));
}

#[test]
fn les_chunks_portent_la_classe_et_la_teinte_de_luminance() {
    let m = Arc::new(VxhModel::from_bytes(&petite().octets()).unwrap());
    let h = PlacedHouse::new(m, HouseClasses::standard(), [1, 1], VoxelCoord::new(100, 7, 200));
    let cle = VoxelCoord::new(100, 7, 200).chunk();
    let mut chunk = Chunk::new_air();
    h.fill_chunk(cle, 0, &mut chunk);
    assert_eq!(chunk.non_air_count(), 3);
    let [x, y, z] = VoxelCoord::new(100, 7, 200).local_in_chunk();
    let v = chunk.get(x, y, z);
    assert_eq!(v.material(), MaterialId::new(20));
    assert_eq!(
        v.tint(),
        ((255 * 77) >> 9) as u8,
        "luminance du rouge pur sur 7 bits"
    );
    // un chunk loin de la maison est de l'air, et le niveau 1 est vide
    assert_eq!(h.classify(ChunkKey::new(50, 0, 50), 0), em_voxel::ChunkHint::Air);
    h.fill_chunk(cle, 1, &mut chunk);
    assert_eq!(chunk.non_air_count(), 0);
    // déterminisme : même maison, même étiquette ; autre pose, autre étiquette
    let m2 = Arc::new(VxhModel::from_bytes(&petite().octets()).unwrap());
    let h2 = PlacedHouse::new(
        m2.clone(),
        HouseClasses::standard(),
        [1, 1],
        VoxelCoord::new(100, 7, 200),
    );
    let h3 = PlacedHouse::new(m2, HouseClasses::standard(), [1, 1], VoxelCoord::new(101, 7, 200));
    assert_eq!(h.version_tag(), h2.version_tag());
    assert_ne!(h.version_tag(), h3.version_tag());
}

/// Les maisons cuites par `tools/maisons/cuire.sh` (hors dépôt) : elles se chargent, respectent l'invariant et le
/// verre. Ignoré si elles n'ont pas été cuites.
#[test]
fn les_maisons_cuites_se_chargent() {
    let dossier = std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
        .join(".local/share/emergence/lab_assets/maisons");
    let mut vues = 0;
    for graine in ["gravit", "a", "ferme", "hameau"] {
        let f = dossier.join(format!("maison_{graine}.vxh"));
        if !f.is_file() {
            eprintln!("IGNORÉ : {} absent (lancer tools/maisons/cuire.sh)", f.display());
            continue;
        }
        let m = VxhModel::load(&f).unwrap_or_else(|e| panic!("{e}"));
        assert!(m.voxel_count() > 100_000, "{graine} : {} voxels", m.voxel_count());
        assert_eq!(m.ground_layers(), 6);
        vues += 1;
    }
    eprintln!("{vues} maison(s) cuite(s) vérifiée(s)");
}
