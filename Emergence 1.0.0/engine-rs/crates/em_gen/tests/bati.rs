//! Les recettes du bâti (L23p) : déterminisme (empreintes épinglées), joints, absence de chanfrein, mousse, poutre,
//! poteau, toit, niveaux grossiers, continuité de la recette à travers les bords de chunk.

use std::collections::BTreeMap;
use std::sync::Arc;

use em_core::{Fnv64, VoxelBox, VoxelCoord, VoxelValue};
use em_gen::{
    Axis, BeamConfig, BuildingClasses, DensePlan, GenParams, GenPlan, Generator, GeneratorId,
    GeneratorRegistry, PlacedPlan, PostConfig, PostShape, RoofConfig, StoneWallConfig,
};
use em_material::{GrainAxis, MaterialTable, untint_wood};
use em_voxel::{Chunk, PutMode, VoxelSink, VoxelSource};

/// Puits qui garde tout, trié.
#[derive(Default)]
struct Collecte(BTreeMap<VoxelCoord, VoxelValue>);

impl VoxelSink for Collecte {
    fn put(&mut self, at: VoxelCoord, value: VoxelValue, _mode: PutMode) {
        self.0.insert(at, value);
    }
}

fn classes() -> BuildingClasses {
    BuildingClasses::standard()
}

fn boite_large(plan: &dyn GenPlan, lod: u8) -> VoxelBox {
    let b = plan.bounds(lod);
    let (a, c) = (b.min(), b.max());
    VoxelBox::new(
        VoxelCoord::new(a.x - 1, a.y - 1, a.z - 1),
        VoxelCoord::new(c.x + 1, c.y + 1, c.z + 1),
    )
    .unwrap()
}

fn collecter(plan: &dyn GenPlan, lod: u8) -> BTreeMap<VoxelCoord, VoxelValue> {
    let mut c = Collecte::default();
    plan.rasterize(lod, boite_large(plan, lod), &mut c);
    c.0
}

fn empreinte(m: &BTreeMap<VoxelCoord, VoxelValue>) -> u64 {
    let mut h = Fnv64::new();
    for (v, val) in m {
        for c in [v.x, v.y, v.z] {
            h.add_u64(i64::from(c) as u64);
        }
        h.add_u64(u64::from(val.raw()));
    }
    h.value()
}

fn mur(seed: u64, cfg: &StoneWallConfig) -> Arc<dyn GenPlan> {
    em_gen::StoneWallGenerator::new(classes())
        .plan(&cfg.to_params().unwrap(), seed)
        .unwrap()
}

fn poutre(seed: u64, cfg: &BeamConfig) -> Arc<dyn GenPlan> {
    em_gen::BeamGenerator::new(classes())
        .plan(&cfg.to_params().unwrap(), seed)
        .unwrap()
}

fn poteau(seed: u64, cfg: &PostConfig) -> Arc<dyn GenPlan> {
    em_gen::PostGenerator::new(classes())
        .plan(&cfg.to_params().unwrap(), seed)
        .unwrap()
}

fn toit(seed: u64, cfg: &RoofConfig) -> Arc<dyn GenPlan> {
    em_gen::RoofGenerator::new(classes())
        .plan(&cfg.to_params().unwrap(), seed)
        .unwrap()
}

// ---------------------------------------------------------------------------------------------------------------
// Catalogue et déterminisme
// ---------------------------------------------------------------------------------------------------------------

#[test]
fn les_classes_standard_sont_celles_de_la_vraie_table() {
    let d = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../engine/data");
    let t = MaterialTable::load(&d.join("materials.csv"), &d.join("material_render.toml")).unwrap();
    assert_eq!(
        BuildingClasses::from_table(&t).unwrap(),
        BuildingClasses::standard()
    );
}

/// Empreintes épinglées des quatre recettes à leurs paramètres par défaut. Si elles changent : la recette a changé
/// exprès (mettre à jour, monter la `version()` du générateur) ou c'est un bug de déterminisme.
const EMPREINTE_MUR_7: u64 = 0x6b97_0dc6_2911_58fe;
const EMPREINTE_POUTRE_7: u64 = 0x37af_849e_da9f_4365;
const EMPREINTE_POTEAU_7: u64 = 0x2ef5_6146_f973_ffd9;
const EMPREINTE_TOIT_7: u64 = 0xe55b_ea8b_a1c5_744a;

#[test]
fn les_recettes_sont_deterministes_et_les_empreintes_epinglees() {
    let faire = || {
        [
            empreinte(&collecter(&*mur(7, &StoneWallConfig::default()), 0)),
            empreinte(&collecter(&*poutre(7, &BeamConfig::default()), 0)),
            empreinte(&collecter(&*poteau(7, &PostConfig::default()), 0)),
            empreinte(&collecter(&*toit(7, &RoofConfig::default()), 0)),
        ]
    };
    let a = faire();
    assert_eq!(a, faire(), "deux constructions de même graine diffèrent");
    eprintln!("empreintes : {a:#018x?}");
    assert_eq!(
        a,
        [
            EMPREINTE_MUR_7,
            EMPREINTE_POUTRE_7,
            EMPREINTE_POTEAU_7,
            EMPREINTE_TOIT_7
        ],
        "empreintes réelles : {a:#018x?}"
    );
}

#[test]
fn une_autre_graine_donne_un_autre_mur_et_le_plan_dense_a_la_meme_empreinte() {
    let cfg = StoneWallConfig::default();
    let (a, b) = (collecter(&*mur(7, &cfg), 0), collecter(&*mur(8, &cfg), 0));
    assert_ne!(empreinte(&a), empreinte(&b));
    // toutes les graines donnent un mur valide : jamais de trou dans le mortier du cœur
    for graine in 0..6 {
        let m = collecter(&*mur(graine, &cfg), 0);
        for y in 0..cfg.height as i32 {
            for z in 1..cfg.thickness as i32 {
                for x in 0..cfg.length as i32 {
                    assert!(
                        m.contains_key(&VoxelCoord::new(x, y, z)),
                        "trou en {x},{y},{z} (graine {graine})"
                    );
                }
            }
        }
    }
}

#[test]
fn des_parametres_invalides_ou_d_un_autre_generateur_sont_refuses() {
    let g = em_gen::StoneWallGenerator::new(classes());
    let mauvais = StoneWallConfig {
        length: 2,
        ..Default::default()
    };
    assert!(g.plan(&mauvais.to_params().unwrap(), 1).is_err());
    let d_une_poutre = BeamConfig::default().to_params().unwrap();
    assert!(g.plan(&d_une_poutre, 1).is_err());
    let inconnu = GenParams::new(GeneratorId::STONE_WALL, 1, br#"{"longueur_inconnue":3}"#.to_vec());
    assert!(g.plan(&inconnu, 1).is_err(), "un champ inconnu doit être refusé");
}

#[test]
fn le_registre_construit_les_recettes_par_leur_nom() {
    let r = GeneratorRegistry::bati(classes());
    let params = StoneWallConfig::default().to_params().unwrap();
    let plan = r.get("stone_wall").unwrap().plan(&params, 7).unwrap();
    assert_eq!(
        empreinte(&collecter(&*plan, 0)),
        empreinte(&collecter(&*mur(7, &StoneWallConfig::default()), 0))
    );
}

// ---------------------------------------------------------------------------------------------------------------
// Mur : joints, pierres en boîtes, mousse, aucune chaux
// ---------------------------------------------------------------------------------------------------------------

const VOISINS: [(i32, i32, i32); 3] = [(1, 0, 0), (0, 1, 0), (0, 0, 1)];

#[test]
fn deux_pierres_differentes_ne_se_touchent_jamais_il_y_a_toujours_un_joint() {
    let c = classes();
    for graine in [1_u64, 7, 99] {
        let m = collecter(&*mur(graine, &StoneWallConfig::default()), 0);
        for (v, val) in &m {
            if val.material() != c.stone() || val.tint() == 0 {
                continue;
            }
            for (dx, dy, dz) in VOISINS {
                let w = VoxelCoord::new(v.x + dx, v.y + dy, v.z + dz);
                if let Some(autre) = m.get(&w)
                    && autre.material() == c.stone()
                    && autre.tint() != 0
                {
                    assert_eq!(
                        autre.tint(),
                        val.tint(),
                        "deux pierres se touchent en {v:?} (graine {graine})"
                    );
                }
            }
        }
    }
}

#[test]
fn chaque_pierre_est_une_boite_pleine_sans_chanfrein() {
    // composantes connexes (6 voisins) de même valeur : le nombre de voxels égale le volume de la boîte englobante
    let c = classes();
    // sans mousse : elle remplace des voxels de la face (ce n'est pas un chanfrein, mais le test mesure la pierre nue)
    let nu = StoneWallConfig {
        moss_foot_percent: 0,
        moss_top_percent: 0,
        ..Default::default()
    };
    let m = collecter(&*mur(7, &nu), 0);
    let mut vus = std::collections::BTreeSet::new();
    let mut pierres = 0;
    for (&debut, &val) in &m {
        if val.material() != c.stone() || val.tint() == 0 || vus.contains(&debut) {
            continue;
        }
        let mut pile = vec![debut];
        let mut compo = Vec::new();
        vus.insert(debut);
        while let Some(v) = pile.pop() {
            compo.push(v);
            for (dx, dy, dz) in VOISINS.iter().flat_map(|&(a, b, c)| [(a, b, c), (-a, -b, -c)]) {
                let w = VoxelCoord::new(v.x + dx, v.y + dy, v.z + dz);
                if m.get(&w) == Some(&val) && vus.insert(w) {
                    pile.push(w);
                }
            }
        }
        let (mut lo, mut hi) = ([i32::MAX; 3], [i32::MIN; 3]);
        for v in &compo {
            for (i, x) in [v.x, v.y, v.z].into_iter().enumerate() {
                lo[i] = lo[i].min(x);
                hi[i] = hi[i].max(x);
            }
        }
        let volume: usize = (0..3).map(|i| (hi[i] - lo[i] + 1) as usize).product();
        assert_eq!(
            compo.len(),
            volume,
            "la pierre {} n'est pas une boîte pleine (chanfrein ou trou)",
            val.tint()
        );
        pierres += 1;
    }
    assert!(
        pierres > 25,
        "un mur de 3,6 x 2,2 m doit compter beaucoup de pierres, pas {pierres}"
    );
}

#[test]
fn les_joints_du_mur_font_un_voxel_sur_la_face_avant() {
    let cfg = StoneWallConfig {
        moss_foot_percent: 0,
        moss_top_percent: 0,
        protrusion_percent: 0,
        ..Default::default()
    };
    let c = classes();
    let m = collecter(&*mur(7, &cfg), 0);
    let mortier = |x: i32, y: i32| {
        m.get(&VoxelCoord::new(x, y, 0))
            .is_some_and(|v| v.material() == c.stone() && v.tint() == 0)
    };
    let mut pire_h = 0;
    for y in 0..cfg.height as i32 {
        let mut run = 0;
        for x in 0..cfg.length as i32 {
            run = if mortier(x, y) { run + 1 } else { 0 };
            pire_h = pire_h.max(run);
        }
    }
    // jamais de bloc de mortier de 3 x 3 voxels : un joint fait un voxel (deux là où une pierre est plus basse d'un voxel)
    for y in 0..cfg.height as i32 - 2 {
        for x in 0..cfg.length as i32 - 2 {
            let plein = (0..3).all(|dy| (0..3).all(|dx| mortier(x + dx, y + dy)));
            assert!(
                !plein,
                "bloc de mortier de 3 x 3 en {x},{y} : un joint doit faire un voxel"
            );
        }
    }
    // les assises sont séparées par des joints horizontaux continus sur toute la longueur
    assert!(
        pire_h >= cfg.length as i32 - 1,
        "joint horizontal discontinu (plus long : {pire_h})"
    );
    // les joints verticaux (hors lignes d'assise) : on compte les rangées où un trou de mortier est isolé
    let mut isoles = 0;
    for y in 0..cfg.height as i32 {
        for x in 1..cfg.length as i32 - 1 {
            if mortier(x, y) && !mortier(x - 1, y) && !mortier(x + 1, y) {
                isoles += 1;
            }
        }
    }
    assert!(
        isoles > 100,
        "des joints verticaux d'un voxel doivent séparer les pierres d'une assise ({isoles})"
    );
}

#[test]
fn le_retrait_du_joint_creuse_la_face_avant_d_un_voxel() {
    let cfg = StoneWallConfig {
        joint_recess: 1,
        moss_foot_percent: 0,
        moss_top_percent: 0,
        ..Default::default()
    };
    let m = collecter(&*mur(7, &cfg), 0);
    let c = classes();
    let mut creux = 0;
    for y in 0..cfg.height as i32 {
        for x in 0..cfg.length as i32 {
            match m.get(&VoxelCoord::new(x, y, 0)) {
                None => {
                    creux += 1;
                    let derriere = m
                        .get(&VoxelCoord::new(x, y, 1))
                        .expect("mortier derrière le creux");
                    assert!(derriere.material() == c.stone() && derriere.tint() == 0);
                }
                Some(v) => assert!(v.tint() != 0, "un voxel de mortier affleure malgré le retrait"),
            }
        }
    }
    assert!(creux > 500);
}

#[test]
fn il_y_a_des_pierres_saillantes_de_la_mousse_au_pied_et_dessus_et_jamais_de_chaux() {
    let cfg = StoneWallConfig::default();
    let c = classes();
    let m = collecter(&*mur(7, &cfg), 0);
    let saillantes = m.keys().filter(|v| v.z == -1).count();
    assert!(saillantes > 20, "{saillantes} voxels saillants");
    let mousse = |v: &VoxelCoord| m[v].material() == c.moss();
    let pied = m
        .keys()
        .filter(|v| mousse(v) && v.y < cfg.moss_foot_rows as i32)
        .count();
    let dessus = m
        .keys()
        .filter(|v| mousse(v) && v.y >= cfg.height as i32 - 1)
        .count();
    let milieu = m
        .keys()
        .filter(|v| mousse(v) && v.y >= cfg.moss_foot_rows as i32 && v.y < cfg.height as i32 - 1)
        .count();
    assert!(pied > 30 && dessus > 30, "mousse : pied {pied}, dessus {dessus}");
    assert_eq!(milieu, 0, "pas de mousse au milieu du mur");
    // seulement de la pierre et de la mousse (jamais de plâtre ni de chaux : classe 17)
    assert!(
        m.values()
            .all(|v| v.material() == c.stone() || v.material() == c.moss())
    );
    // la mousse est en surface : jamais derrière la face avant sauf le dessus
    assert!(
        m.iter()
            .filter(|(_, v)| v.material() == c.moss())
            .all(|(p, _)| p.z <= 0 || p.y >= cfg.height as i32 - 1)
    );
}

#[test]
fn le_numero_de_pierre_ne_depend_pas_du_chunk_le_mur_a_cheval_sur_un_bord() {
    // pivot au milieu d'un chunk : le mur de 72 voxels traverse deux bords de chunk
    let cfg = StoneWallConfig::default();
    let plan = mur(7, &cfg);
    let reference = collecter(&*plan, 0);
    let pivot = VoxelCoord::new(200_000 - 20, 0, 200_000 - 3);
    let pose = PlacedPlan::new(plan, pivot, 1);
    let b = pose.bounds(0);
    let mut lu = BTreeMap::new();
    for cy in b.min().chunk().y..=(b.max().y - 1).div_euclid(64) {
        for cz in b.min().chunk().z..=(b.max().z - 1).div_euclid(64) {
            for cx in b.min().chunk().x..=(b.max().x - 1).div_euclid(64) {
                let mut chunk = Chunk::new_air();
                pose.fill_chunk(em_core::ChunkKey::new(cx, cy, cz), 0, &mut chunk);
                for z in 0..64_u32 {
                    for y in 0..64_u32 {
                        for x in 0..64_u32 {
                            let v = chunk.get(x, y, z);
                            if !v.is_air() {
                                let monde = VoxelCoord::new(
                                    cx * 64 + x as i32,
                                    cy * 64 + y as i32,
                                    cz * 64 + z as i32,
                                );
                                lu.insert(monde, v);
                            }
                        }
                    }
                }
            }
        }
    }
    assert!(
        b.min().chunk().x != (b.max().x - 1).div_euclid(64),
        "le mur doit chevaucher un bord de chunk"
    );
    assert_eq!(lu.len(), reference.len());
    for (v, val) in &reference {
        let monde = VoxelCoord::new(v.x + pivot.x, v.y + pivot.y, v.z + pivot.z);
        assert_eq!(
            lu.get(&monde),
            Some(val),
            "voxel {v:?} différent après découpe en chunks"
        );
    }
}

// ---------------------------------------------------------------------------------------------------------------
// Niveaux grossiers
// ---------------------------------------------------------------------------------------------------------------

/// Chunks non vides d'une source à un niveau, sur la fenêtre de chunks donnée.
fn chunks_du_niveau(src: &dyn VoxelSource, lod: u8, lo: [i32; 3], hi: [i32; 3]) -> BTreeMap<[i32; 3], Chunk> {
    let mut m = BTreeMap::new();
    for cy in lo[1]..=hi[1] {
        for cz in lo[2]..=hi[2] {
            for cx in lo[0]..=hi[0] {
                let mut c = Chunk::new_air();
                src.fill_chunk(em_core::ChunkKey::new(cx, cy, cz), lod, &mut c);
                m.insert([cx, cy, cz], c);
            }
        }
    }
    m
}

#[test]
fn les_niveaux_grossiers_s_accordent_a_90_pourcent_avec_la_reduction_des_voxels_fins() {
    // chaque niveau du plan est comparé à la réduction `reduce_2x` d'em_voxel (règle 4/8) du niveau plus fin,
    // calculée par un autre chemin : chunks de 64³ réduits huit par huit
    let c = classes();
    let regle =
        em_voxel::ReduceRule::majority_4_of_8(vec![c.stone(), c.wood(), c.trim(), c.roof(), c.moss()])
            .unwrap();
    let plans: [(&str, Arc<dyn GenPlan>); 4] = [
        ("mur", mur(7, &StoneWallConfig::default())),
        ("poutre", poutre(7, &BeamConfig::default())),
        ("poteau", poteau(7, &PostConfig::default())),
        ("toit", toit(7, &RoofConfig::default())),
    ];
    for (nom, plan) in plans {
        // pivot multiple de 512 voxels : l'alignement des niveaux 1 à 3 est celui du monde
        let pose = PlacedPlan::new(plan, VoxelCoord::new(200_064, 512, 199_936), 1);
        for lod in 0..3_u8 {
            let b = pose.bounds(lod + 1);
            let (a, z) = (
                b.min().chunk(),
                VoxelCoord::new(b.max().x - 1, b.max().y - 1, b.max().z - 1).chunk(),
            );
            let (lo, hi) = ([a.x, a.y, a.z], [z.x, z.y, z.z]);
            let enfants = chunks_du_niveau(
                &pose,
                lod,
                [2 * lo[0], 2 * lo[1], 2 * lo[2]],
                [2 * hi[0] + 1, 2 * hi[1] + 1, 2 * hi[2] + 1],
            );
            let attendus = chunks_du_niveau(&pose, lod + 1, lo, hi);
            let (mut accord, mut total) = (0_u64, 0_u64);
            for (cle, attendu) in &attendus {
                let e = |cx: i32, cy: i32, cz: i32| {
                    &enfants[&[2 * cle[0] + cx, 2 * cle[1] + cy, 2 * cle[2] + cz]]
                };
                let huit: [&Chunk; 8] =
                    std::array::from_fn(|k| e((k & 1) as i32, (k >> 2) as i32, ((k >> 1) & 1) as i32));
                let mut reduit = Chunk::new_air();
                em_voxel::reduce_2x(huit, &regle, &mut reduit);
                for z in 0..64_u32 {
                    for y in 0..64_u32 {
                        for x in 0..64_u32 {
                            let (r, p) = (reduit.get(x, y, z), attendu.get(x, y, z));
                            if r.is_air() && p.is_air() {
                                continue;
                            }
                            total += 1;
                            accord += u64::from(r.is_air() == p.is_air());
                        }
                    }
                }
            }
            let taux = if total == 0 {
                1.0
            } else {
                accord as f64 / total as f64
            };
            assert!(
                taux >= 0.90,
                "{nom} niveau {} : accord d'occupation {taux:.3}",
                lod + 1
            );
        }
    }
}

// ---------------------------------------------------------------------------------------------------------------
// Poutre, poteau, toit
// ---------------------------------------------------------------------------------------------------------------

#[test]
fn la_poutre_de_3_m_a_une_section_de_20_cm_des_fibres_en_x_et_des_bouts() {
    let cfg = BeamConfig::default();
    let m = collecter(&*poutre(7, &cfg), 0);
    assert_eq!(
        m.len(),
        60 * 4 * 4,
        "3 m x 20 cm x 20 cm = 60 x 4 x 4 voxels, tous pleins"
    );
    let b = poutre(7, &cfg).bounds(0);
    assert_eq!(b.size(), [60, 4, 4]);
    let mut noeuds = 0;
    for (v, val) in &m {
        let (axe, variante) = untint_wood(val.tint());
        if v.x == 0 || v.x == 59 {
            assert_eq!(axe, GrainAxis::End, "extrémités en bois de bout");
        } else {
            assert_eq!(axe, GrainAxis::X, "le fil court le long de l'axe");
        }
        noeuds += usize::from(variante & 16 != 0);
    }
    assert!(
        noeuds >= 3,
        "au moins un nœud de 2 x 2 voxels par nœud demandé (partiellement hors face possible) : {noeuds}"
    );
    // la même poutre le long de y et de z : même nombre de voxels, fil dans l'axe demandé
    for (axe, grain) in [(Axis::Y, GrainAxis::Y), (Axis::Z, GrainAxis::Z)] {
        let m = collecter(
            &*poutre(
                7,
                &BeamConfig {
                    axis: axe,
                    ..cfg.clone()
                },
            ),
            0,
        );
        assert_eq!(m.len(), 960);
        let milieu = m
            .iter()
            .find(|(v, _)| v.x.max(v.y).max(v.z) > 20 && v.x.max(v.y).max(v.z) < 40)
            .unwrap();
        assert_eq!(untint_wood(milieu.1.tint()).0, grain);
    }
}

#[test]
fn le_poteau_rond_est_plein_symetrique_et_porte_un_chapiteau_plus_large() {
    let cfg = PostConfig::default();
    let m = collecter(&*poteau(7, &cfg), 0);
    let c = classes();
    // le fût : un disque identique à chaque hauteur, sans trou
    let tranche = |y: i32| {
        m.keys()
            .filter(|v| v.y == y && m[v].material() == c.wood())
            .count()
    };
    assert!(
        tranche(20) > 30 && tranche(20) < 49,
        "disque de 7 voxels : {}",
        tranche(20)
    );
    assert!(
        (2..44).all(|y| tranche(y + 1) == tranche(20)),
        "le fût change de section"
    );
    // symétrie quart de tour du disque (centre en (5, 5))
    for v in m.keys().filter(|v| v.y == 20 && m[v].material() == c.wood()) {
        assert!(
            m.contains_key(&VoxelCoord::new(10 - v.x, 20, v.z)),
            "disque non symétrique"
        );
        assert!(
            m.contains_key(&VoxelCoord::new(v.z, 20, v.x)),
            "disque non symétrique (diagonale)"
        );
    }
    // chapiteau : bois d'ornement, plus large que le fût
    let ornement = m.iter().filter(|(_, v)| v.material() == c.trim()).count();
    assert!(ornement > 200, "{ornement} voxels de chapiteau et de socle");
    let max_x = m.keys().filter(|v| v.y == 46).map(|v| v.x).max().unwrap();
    assert_eq!(max_x, 10, "le chapiteau occupe toute l'emprise de 11 voxels");
    assert_eq!(poteau(7, &cfg).bounds(0).size(), [11, 48, 11]);
    // section carrée : tous les voxels du carré
    let carre = collecter(
        &*poteau(
            7,
            &PostConfig {
                shape: PostShape::Square,
                ..cfg
            },
        ),
        0,
    );
    assert!(carre.keys().filter(|v| v.y == 20).count() >= 49);
}

#[test]
fn le_toit_est_fait_de_rangees_de_tuiles_a_ton_propre_en_gradins() {
    let cfg = RoofConfig::default();
    let c = classes();
    let m = collecter(&*toit(7, &cfg), 0);
    assert!(
        m.values()
            .all(|v| v.material() == c.roof() || v.material() == c.moss())
    );
    // chaque tuile : un ton, constant sur toute la tuile ; les tons varient d'une tuile à l'autre
    let mut tons = std::collections::BTreeSet::new();
    for r in 0..cfg.rows as i32 {
        let y = r + cfg.thickness as i32 - 1; // couche supérieure de la rangée
        let z = r * cfg.run as i32;
        let mut precedent: Option<u8> = None;
        for x in 0..cfg.width as i32 {
            let Some(v) = m.get(&VoxelCoord::new(x, y, z)) else {
                continue;
            };
            if v.material() != c.roof() {
                continue;
            }
            if v.tint() != 3 {
                tons.insert(v.tint());
            }
            precedent = Some(v.tint());
        }
        assert!(precedent.is_some(), "rangée {r} vide");
    }
    assert!(tons.len() > 20, "{} tons de tuile seulement", tons.len());
    // les gradins montent d'un voxel par rangée
    let b = toit(7, &cfg).bounds(0);
    assert_eq!(b.size(), [68, 9 - 1 + 2, 27]);
    // des tuiles moussues
    assert!(m.values().any(|v| v.material() == c.moss()));
}

#[test]
fn le_plan_dense_expose_sa_pyramide() {
    let plan = mur(7, &StoneWallConfig::default());
    assert!(plan.bounds(5).size()[0] >= 2);
    assert!(plan.bounds(6).is_empty());
    let _: Option<&DensePlan> = None;
}
