//! Essais du mailleur de chunks, sans GPU : un cube = 6 faces, deux cubes adjacents cachent leur face commune,
//! le coin creux vaut 0,5, symétrie, déterminisme octet pour octet, bords de chunk, fusion gloutonne, quad et
//! sommets cohérents (enroulement des triangles, diagonale).

use em_core::{ChunkKey, Lod, MaterialId, VoxelCoord, VoxelValue};
use em_mesh::{
    AO_FACTOR, ChunkMesh, ChunkMesher, Face, MesherConfig, PaddedChunk, Quad, QuadSpec, VoxelAppearance,
    VoxelColorer,
};
use em_voxel::Chunk;
use std::collections::BTreeMap;

/// Colorieur d'essai : la couleur vient de la teinte du voxel (donc contrôlable), pas de la position.
struct Teinte;

impl VoxelColorer for Teinte {
    fn appearance(&self, v: VoxelValue, _p: VoxelCoord, _l: Lod) -> VoxelAppearance {
        VoxelAppearance {
            color: [v.tint(), v.material().get() as u8, 9],
            params: 0,
            foliage: false,
        }
    }
    fn is_foliage(&self, _v: VoxelValue) -> bool {
        false
    }
}

fn pierre(teinte: u8) -> VoxelValue {
    VoxelValue::new(MaterialId::new(20), teinte)
}

/// Monde d'essai : des chunks créés à la demande, voxels posés en coordonnées monde.
#[derive(Default)]
struct Monde {
    chunks: BTreeMap<ChunkKey, Chunk>,
}

impl Monde {
    fn pose(&mut self, x: i32, y: i32, z: i32, v: VoxelValue) {
        let c = VoxelCoord::new(x, y, z);
        let [lx, ly, lz] = c.local_in_chunk();
        self.chunks.entry(c.chunk()).or_default().set(lx, ly, lz, v);
    }

    fn mesh(&self, key: ChunkKey, greedy: bool) -> ChunkMesh {
        let colorier = Teinte;
        let m = ChunkMesher::new(&colorier, MesherConfig::new(greedy));
        let cherche = |k: ChunkKey| self.chunks.get(&k);
        m.mesh(key, 0, &PaddedChunk::gather(key, &cherche))
    }
}

const ORIGINE: ChunkKey = ChunkKey::new(0, 0, 0);

fn un_cube() -> Monde {
    let mut m = Monde::default();
    m.pose(10, 10, 10, pierre(1));
    m
}

#[test]
fn un_cube_a_six_faces() {
    for greedy in [false, true] {
        let mesh = un_cube().mesh(ORIGINE, greedy);
        assert_eq!(mesh.quad_count(), 6, "greedy = {greedy}");
        assert_eq!(mesh.face_count(), 6);
        assert_eq!(mesh.vertex_count(), 24);
        let mut faces: Vec<usize> = mesh.quads().iter().map(|q| q.face().index()).collect();
        faces.sort_unstable();
        assert_eq!(faces, vec![0, 1, 2, 3, 4, 5], "une face par direction");
        // un cube isolé est dégagé partout : aucune occlusion
        assert!(mesh.quads().iter().all(|q| q.ao() == [3; 4]));
        assert_eq!(mesh.bounds(), [[10, 10, 10], [11, 11, 11]]);
    }
}

#[test]
fn deux_cubes_adjacents_cachent_leur_face_commune() {
    let mut m = Monde::default();
    m.pose(10, 10, 10, pierre(1));
    m.pose(11, 10, 10, pierre(2));
    let mesh = m.mesh(ORIGINE, false);
    assert_eq!(mesh.face_count(), 10, "12 faces moins les deux faces collées");
    assert_eq!(mesh.quad_count(), 10);
    // aucune face +x du premier cube ni -x du second
    let a_cache = |face: Face, x: u8| {
        mesh.quads()
            .iter()
            .any(|q| q.face() == face && q.origin()[0] == x && q.origin()[1] == 10 && q.origin()[2] == 10)
    };
    assert!(!a_cache(Face::PosX, 11) && !a_cache(Face::NegX, 11));
}

#[test]
fn la_fusion_gloutonne_ne_fusionne_que_des_aspects_identiques() {
    // un mur 4 x 3 d'une seule couleur : 6 quads (une face par direction)
    let mut uni = Monde::default();
    for x in 10..14 {
        for y in 10..13 {
            uni.pose(x, y, 10, pierre(5));
        }
    }
    let gl = uni.mesh(ORIGINE, true);
    let nu = uni.mesh(ORIGINE, false);
    assert_eq!(nu.quad_count() as u32, nu.face_count());
    assert_eq!(gl.face_count(), nu.face_count(), "même surface couverte");
    assert_eq!(gl.quad_count(), 6, "la dalle n'a que six rectangles");
    let grand = gl.quads().iter().find(|q| q.face() == Face::PosZ).unwrap();
    assert_eq!(
        (grand.width(), grand.height()),
        (4, 3),
        "largeur le long de x, hauteur le long de y"
    );
    let total: u32 = gl.quads().iter().map(Quad::face_count).sum();
    assert_eq!(total, gl.face_count(), "la fusion conserve les faces");

    // une pierre d'une autre couleur dans le mur coupe le rectangle
    let mut tache = Monde::default();
    for x in 10..14 {
        for y in 10..13 {
            tache.pose(x, y, 10, pierre(if (x, y) == (11, 11) { 9 } else { 5 }));
        }
    }
    let t = tache.mesh(ORIGINE, true);
    assert!(
        t.quad_count() > 6,
        "la couleur différente brise la fusion ({})",
        t.quad_count()
    );
    let surface = |m: &ChunkMesh, f: Face| -> u32 {
        m.quads()
            .iter()
            .filter(|q| q.face() == f)
            .map(Quad::face_count)
            .sum()
    };
    assert_eq!(
        surface(&t, Face::PosZ),
        12,
        "la surface de la face avant reste de 12 voxels"
    );
}

#[test]
fn le_coin_creux_vaut_un_demi() {
    // sol + deux murs qui se rejoignent : le coin du sol contre les deux murs a ses deux côtés pleins
    let mut m = Monde::default();
    for x in 8..14 {
        for z in 8..14 {
            m.pose(x, 10, z, pierre(1));
        }
    }
    for y in 11..14 {
        for t in 8..14 {
            m.pose(8, y, t, pierre(1)); // mur à x = 8
            m.pose(t, y, 8, pierre(1)); // mur à z = 8
        }
    }
    let mesh = m.mesh(ORIGINE, false);
    // la face du dessus du voxel (9, 10, 9) est collée aux deux murs : un de ses coins a les deux côtés pleins
    let dessus = mesh
        .quads()
        .iter()
        .find(|q| q.face() == Face::PosY && q.origin() == [9, 11, 9])
        .expect("face du dessus du voxel du creux");
    let niveaux = dessus.ao();
    assert_eq!(
        niveaux.iter().min(),
        Some(&0),
        "le coin du creux est au niveau 0 : {niveaux:?}"
    );
    assert!(
        (AO_FACTOR[0] - 0.5).abs() < 1e-6,
        "le niveau 0 vaut 0,5 d'ambiance"
    );
    // un voxel du sol loin des murs est dégagé
    let libre = mesh
        .quads()
        .iter()
        .find(|q| q.face() == Face::PosY && q.origin() == [12, 11, 12])
        .unwrap();
    assert_eq!(libre.ao(), [3; 4]);
    // le long d'un seul mur : les deux coins du côté du mur ont le côté plein ET le coin plein : 3 - 2 = 1
    let long_mur = mesh
        .quads()
        .iter()
        .find(|q| q.face() == Face::PosY && q.origin() == [9, 11, 12])
        .unwrap();
    let mut tri = long_mur.ao();
    tri.sort_unstable();
    assert_eq!(tri, [1, 1, 3, 3], "{:?}", long_mur.ao());
}

#[test]
fn le_niveau_du_coin_suit_la_regle_de_la_reference() {
    // un voxel de coin seul (diagonale) : s1 = s2 = 0, c = 1 -> niveau 2 ; deux côtés sans coin -> 0
    let mut m = Monde::default();
    m.pose(20, 10, 20, pierre(1)); // le voxel dont on regarde le dessus
    m.pose(21, 11, 21, pierre(1)); // coin seul (+u,+v) au-dessus : s1 = s2 = vide, c = plein
    let q = m
        .mesh(ORIGINE, false)
        .quads()
        .iter()
        .copied()
        .find(|q| q.face() == Face::PosY && q.origin() == [20, 11, 20])
        .unwrap();
    // face +y : u = z, v = x ; le coin (+u, +v) est le coin 2
    assert_eq!(q.ao(), [3, 3, 2, 3]);
    let mut m2 = Monde::default();
    m2.pose(20, 10, 20, pierre(1));
    m2.pose(21, 11, 20, pierre(1)); // côté +x plein
    m2.pose(20, 11, 21, pierre(1)); // côté +z plein, sans le coin
    let q2 = m2
        .mesh(ORIGINE, false)
        .quads()
        .iter()
        .copied()
        .find(|q| q.face() == Face::PosY && q.origin() == [20, 11, 20])
        .unwrap();
    assert_eq!(q2.ao()[2], 0, "deux côtés pleins : niveau 0 même sans le coin");
}

#[test]
fn la_symetrie_miroir_conserve_les_niveaux_d_occlusion() {
    // une scène quelconque et son miroir en x : mêmes nombres de faces, mêmes niveaux d'occlusion
    let (xmin, xmax) = (6, 25);
    let mut a = Monde::default();
    let mut b = Monde::default();
    let mut graine = 12345_u64;
    for y in 8..14 {
        for z in 8..20 {
            for x in xmin..xmax {
                graine = graine
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                if (graine >> 33).is_multiple_of(3) {
                    a.pose(x, y, z, pierre(1));
                    b.pose(xmin + xmax - 1 - x, y, z, pierre(1));
                }
            }
        }
    }
    let (ma, mb) = (a.mesh(ORIGINE, false), b.mesh(ORIGINE, false));
    assert_eq!(ma.face_count(), mb.face_count());
    let somme = |m: &ChunkMesh, f: Face| -> u32 {
        m.quads()
            .iter()
            .filter(|q| q.face() == f)
            .map(|q| q.ao().iter().map(|v| u32::from(*v)).sum::<u32>())
            .sum()
    };
    for (f, g) in [
        (Face::PosY, Face::PosY),
        (Face::NegY, Face::NegY),
        (Face::PosZ, Face::PosZ),
        (Face::NegZ, Face::NegZ),
        (Face::PosX, Face::NegX),
        (Face::NegX, Face::PosX),
    ] {
        assert_eq!(
            somme(&ma, f),
            somme(&mb, g),
            "occlusion de {f:?} contre {g:?} du miroir"
        );
    }
    // et la distribution fine des niveaux
    let histo = |m: &ChunkMesh| {
        let mut h = [0_u32; 4];
        for q in m.quads() {
            for n in q.ao() {
                h[usize::from(n)] += 1;
            }
        }
        h
    };
    assert_eq!(histo(&ma), histo(&mb));
}

#[test]
fn le_maillage_est_identique_octet_pour_octet() {
    let mut m = Monde::default();
    let mut graine = 99_u64;
    for y in 0..30 {
        for z in 0..40 {
            for x in 0..50 {
                graine = graine
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                if !(graine >> 33).is_multiple_of(4) {
                    m.pose(x, y, z, pierre(((graine >> 20) % 4) as u8));
                }
            }
        }
    }
    for greedy in [false, true] {
        let a = m.mesh(ORIGINE, greedy);
        let b = m.mesh(ORIGINE, greedy);
        assert_eq!(a.as_bytes(), b.as_bytes());
        assert_eq!(a.fingerprint(), b.fingerprint());
        assert!(!a.is_empty());
    }
    // la fusion ne change pas la surface couverte
    let (g, n) = (m.mesh(ORIGINE, true), m.mesh(ORIGINE, false));
    assert_eq!(g.face_count(), n.face_count());
    assert!(g.quad_count() <= n.quad_count());
    assert_eq!(
        g.quads().iter().map(Quad::face_count).sum::<u32>(),
        n.quads().iter().map(Quad::face_count).sum::<u32>()
    );
}

#[test]
fn aux_bords_du_chunk_les_voisins_sont_lus() {
    // un mur plein sur deux chunks voisins en x : pas de face à la couture
    let mut m = Monde::default();
    m.pose(63, 10, 10, pierre(1));
    m.pose(64, 10, 10, pierre(1));
    let gauche = m.mesh(ORIGINE, false);
    let droite = m.mesh(ChunkKey::new(1, 0, 0), false);
    assert_eq!(
        gauche.face_count(),
        5,
        "la face +x du voxel 63 est cachée par le voisin"
    );
    assert_eq!(droite.face_count(), 5);
    assert!(gauche.quads().iter().all(|q| q.face() != Face::PosX));
    assert!(droite.quads().iter().all(|q| q.face() != Face::NegX));
    // l'occlusion lit le voisin : un voxel voisin au-dessus, de l'autre côté de la couture, assombrit le coin
    let mut m = Monde::default();
    m.pose(63, 10, 10, pierre(1));
    m.pose(64, 11, 10, pierre(1)); // dans le chunk voisin, au-dessus-à-droite
    let q = m
        .mesh(ORIGINE, false)
        .quads()
        .iter()
        .copied()
        .find(|q| q.face() == Face::PosY)
        .unwrap();
    // face +y : u = z, v = x ; le côté +x (v) est plein pour les coins 2 et 3, sans voisin de côté u : niveau 2
    assert_eq!(q.ao(), [3, 3, 2, 2]);
    // un chunk voisin absent est opaque : pas de face contre le trou
    let mut m = Monde::default();
    m.pose(63, 10, 10, pierre(1));
    let seul = m.mesh(ORIGINE, false);
    assert_eq!(
        seul.face_count(),
        5,
        "voisin +x absent (hors du chargé) : pas de face vers lui"
    );
}

#[test]
fn les_sommets_ont_la_normale_la_couleur_et_les_triangles_de_la_face() {
    let mut m = Monde::default();
    m.pose(5, 5, 5, pierre(7));
    m.pose(6, 6, 6, pierre(7)); // casse la symétrie de l'occlusion de plusieurs faces
    let mesh = m.mesh(ORIGINE, false);
    for q in mesh.quads() {
        let n = q.face().normal();
        for k in 0..4 {
            let v = q.vertex(k);
            assert_eq!(v.normal.map(i32::from), n);
            assert_eq!(v.color, [7, 20, 9]);
            assert_eq!(v.ao, q.ao()[k]);
        }
        // les deux triangles ont la normale géométrique de la face et couvrent les quatre coins
        let mut vus = [false; 4];
        for t in q.triangles() {
            let p: Vec<[i32; 3]> = t
                .iter()
                .map(|k| q.corner(usize::from(*k)).map(i32::from))
                .collect();
            let (a, b) = (
                [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]],
                [p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]],
            );
            let croix = [
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0],
            ];
            let dot: i32 = (0..3).map(|i| croix[i] * n[i]).sum();
            assert!(dot > 0, "triangle {t:?} de {:?} retourné", q.face());
            for k in t {
                vus[usize::from(k)] = true;
            }
        }
        assert!(vus.iter().all(|v| *v));
    }
}

#[test]
fn la_bande_du_gpu_donne_les_memes_triangles_que_le_cpu() {
    // pour toutes les occlusions possibles et les deux signes : (b0 b1 b2) et (b2 b1 b3) sont les triangles du CPU,
    // à une rotation près (même enroulement, même diagonale)
    let tourne =
        |t: [u8; 3]| -> Vec<[u8; 3]> { (0..3).map(|i| [t[i], t[(i + 1) % 3], t[(i + 2) % 3]]).collect() };
    for f in [Face::PosY, Face::NegY] {
        for code in 0..256_u32 {
            let ao = [
                (code & 3) as u8,
                ((code >> 2) & 3) as u8,
                ((code >> 4) & 3) as u8,
                ((code >> 6) & 3) as u8,
            ];
            let q = Quad::new(QuadSpec {
                origin: [0; 3],
                face: f,
                width: 1,
                height: 1,
                color: [0; 3],
                params: 0,
                ao,
                thickness: 0,
                foliage: false,
            })
            .unwrap();
            let b = q.strip();
            let (t0, t1) = ([b[0], b[1], b[2]], [b[2], b[1], b[3]]);
            let cpu = q.triangles();
            assert!(
                tourne(cpu[0]).contains(&t0) && tourne(cpu[1]).contains(&t1),
                "{f:?} {ao:?}"
            );
        }
    }
}

#[test]
fn la_diagonale_suit_l_occlusion() {
    let spec = |ao: [u8; 4]| {
        Quad::new(QuadSpec {
            origin: [1, 2, 3],
            face: Face::PosY,
            width: 1,
            height: 1,
            color: [1, 2, 3],
            params: 0xA5,
            ao,
            thickness: 17,
            foliage: true,
        })
        .unwrap()
    };
    // coins 1 et 3 sombres : on coupe selon la diagonale 0-2 (les coins clairs)
    assert!(spec([3, 0, 3, 0]).splits_on_0_2());
    assert!(!spec([0, 3, 0, 3]).splits_on_0_2());
    assert!(
        !spec([3, 3, 3, 3]).splits_on_0_2(),
        "égalité : diagonale 1-3, comme la référence"
    );
    let q = spec([1, 2, 3, 0]);
    assert_eq!(
        (
            q.origin(),
            q.face(),
            q.color(),
            q.params(),
            q.ao(),
            q.thickness(),
            q.is_foliage()
        ),
        ([1, 2, 3], Face::PosY, [1, 2, 3], 0xA5, [1, 2, 3, 0], 17, true)
    );
    // validation du format
    let mauvais = QuadSpec {
        origin: [65, 0, 0],
        face: Face::PosX,
        width: 1,
        height: 1,
        color: [0; 3],
        params: 0,
        ao: [0; 4],
        thickness: 0,
        foliage: false,
    };
    assert!(Quad::new(mauvais).is_err());
    assert!(
        Quad::new(QuadSpec {
            origin: [64, 64, 64],
            width: 65,
            ..mauvais
        })
        .is_err()
    );
    assert!(
        Quad::new(QuadSpec {
            origin: [0; 3],
            ao: [4, 0, 0, 0],
            ..mauvais
        })
        .is_err()
    );
    assert_eq!(size_of::<Quad>(), 12);
}

#[test]
fn les_quads_du_mailleur_sont_valides_et_dans_le_chunk() {
    let mut m = Monde::default();
    // loin des bords : un voisin absent est opaque et assombrirait les coins de la bordure
    for x in 8..56 {
        for z in 8..56 {
            m.pose(x, 4, z, pierre(((x / 8 + z / 8) % 3) as u8));
        }
    }
    let mesh = m.mesh(ORIGINE, true);
    for q in mesh.quads() {
        let o = q.origin();
        assert!(o.iter().all(|v| *v <= 64));
        assert!(q.width() >= 1 && q.height() >= 1);
        let c = q.corner(2);
        assert!(c.iter().all(|v| *v <= 64));
    }
    // un dallage par carrés de 8 x 8 de même teinte : un rectangle par carré, sans plus
    let dessus = mesh.quads().iter().filter(|q| q.face() == Face::PosY).count();
    assert_eq!(dessus, 36, "un rectangle par carré de teinte (6 x 6 carrés)");
}
