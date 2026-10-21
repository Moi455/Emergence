//! Bâtiments, props et rochers (L35 à L37) : catalogue des recettes nommées, empreintes ÉPINGLÉES par recette
//! (identiques avec 1 et 8 fils), bords de chunk, invariants des maisons (pièces connexes, un lit et une cuisine,
//! murs d'épaisseur non nulle, cheminée creuse), parité d'occupation de la maison de Monsieur.

use std::path::PathBuf;

use em_core::MaterialId;
use em_gen::batiments::maison::{HouseConfig, HouseGenerator, HouseParams, planifier};
use em_gen::batiments::{AssetCatalogue, Matieres, registre_complet};
use em_gen::{BuildingClasses, GenParams, GeneratorRegistry};

fn racine() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

/// Les recettes de MA famille (le dossier `engine/data/assets` contient aussi celles de la végétation).
fn catalogue() -> AssetCatalogue {
    let mut c = AssetCatalogue::new();
    for f in ["batiments", "props", "rochers"] {
        let t = std::fs::read_to_string(racine().join(format!("engine/data/assets/{f}.toml")))
            .expect("fichier de recettes");
        c.add_text(&t).expect("recettes valides");
    }
    c
}

fn registre() -> GeneratorRegistry {
    registre_complet(BuildingClasses::standard(), Matieres::standard())
}

/// Les classes de `Matieres::standard()` sont celles de la vraie table (par nom).
#[test]
fn les_classes_standard_sont_celles_de_la_vraie_table() {
    let d = racine().join("engine/data");
    let t =
        em_material::MaterialTable::load(&d.join("materials.csv"), &d.join("material_render.toml")).unwrap();
    assert_eq!(Matieres::from_table(&t).unwrap(), Matieres::standard());
    let ids: Vec<MaterialId> = Matieres::standard().priority();
    assert_eq!(ids.len(), Matieres::NOMS.len());
}

#[test]
fn toutes_les_recettes_du_catalogue_se_construisent() {
    let (c, r) = (catalogue(), registre());
    assert!(c.len() >= 60, "{} recettes seulement", c.len());
    for id in c.ids() {
        c.plan(id, &r)
            .unwrap_or_else(|e| panic!("recette « {id} » : {e}"));
    }
}

/// Empreintes épinglées (FNV-64 du niveau 0). Si une change : la recette a changé exprès (mettre à jour, monter la
/// `version()` du générateur) ou c'est un bug de déterminisme. `EM_EMPREINTES=1 cargo test ... -- --nocapture` les imprime.
const EMPREINTES: &[(&str, u64)] = &[
    ("boulangerie_1", 0x9d068838c32a109f),
    ("cabane_bucheron_1", 0x8eda1c0ad212fe97),
    ("chapelle_1", 0x1e3732e48e3faa8d),
    ("eglise_1", 0x27fce45003f25a13),
    ("etable_1", 0x6ed8ebf864e419f4),
    ("forge_1", 0xf9b667e61160d026),
    ("grange_1", 0xf2e28da43d21a8c0),
    ("grange_2", 0x7abebe93e07c946f),
    ("halle_1", 0x772632b6382c4c83),
    ("mairie_1", 0xce416d0e820223de),
    ("maison_a", 0xfad0651f2e63bd45),
    ("maison_colombage", 0x0cebf1b17006ce52),
    ("maison_gravit", 0x3c52daf22dc4fe9a),
    ("moulin_eau_1", 0x0df9c5dad67e8c1d),
    ("moulin_vent_1", 0x76bc1d87e1d5ed46),
    ("pont_bois_1", 0xcdf33f04ed662532),
    ("pont_bois_2", 0xb2daff04562b30ca),
    ("pont_pierre_1", 0xf234bed9e69ab609),
    ("pont_pierre_2", 0xd8db82101df5cc14),
    ("prop_banc", 0x8e71fa697f4417e0),
    ("prop_bougie", 0x48a24af209769844),
    ("prop_caisse", 0x719100e812183414),
    ("prop_caisse_s5", 0x34e3b0cfe184e3ab),
    ("prop_chaise", 0xfa2eaed9f6abd731),
    ("prop_charrette", 0x5231177e64d26db5),
    ("prop_charrette_s9", 0x4d3f803516cb08d0),
    ("prop_cle", 0xec624964f69863e3),
    ("prop_cloture_bois", 0xa53b0a47b4a90a1a),
    ("prop_cloture_bois_s4", 0x0c9369db0fe991ed),
    ("prop_cloture_pierre", 0x39cf8ecfbd7e7ed8),
    ("prop_cloture_pierre_s6", 0x36eefe81ef133eda),
    ("prop_echelle", 0x86b480c592009b56),
    ("prop_enseigne", 0x251e90843f07434e),
    ("prop_enseigne_s2", 0xc7950df67ebbfe19),
    ("prop_enseigne_s3", 0xc749247c84255993),
    ("prop_enseigne_s5", 0x702fe516f39a0c7d),
    ("prop_etal", 0xe273aed495909f8c),
    ("prop_etal_s3", 0x15c7494c24ef1a3b),
    ("prop_etal_s9", 0x96171e618d750051),
    ("prop_feu_camp", 0x9b8b91334e8f4368),
    ("prop_foin", 0x36fd971323177c06),
    ("prop_fruits", 0x5e3b8c506b0ff653),
    ("prop_lanterne", 0x703f0e27662ba62d),
    ("prop_livre", 0xe9732d89e05188d1),
    ("prop_outils", 0x650aa128c4d7546d),
    ("prop_pain", 0x2684a6e86faf7a1d),
    ("prop_panneau", 0xc1e9bd58d6b9e52a),
    ("prop_portail", 0x27ead078188528d4),
    ("prop_puits_deco", 0xd9b6435adf43677d),
    ("prop_ratelier", 0x63b0088b3974c53c),
    ("prop_ruche", 0x7e07e8df372c3c50),
    ("prop_ruche_s4", 0x9cc5d2f1372fb0f5),
    ("prop_sacs", 0xc88407367f61f8cd),
    ("prop_table", 0xa98a0268d9685c35),
    ("prop_tas_bois", 0x0014f25c104a523d),
    ("prop_tombe", 0x01b8cd54ec2b70b9),
    ("prop_tombe_s8", 0x3e7706db0a992982),
    ("prop_tonneau", 0xb9020f9dff06d965),
    ("prop_tonneau_s11", 0x860496caf9738084),
    ("prop_tonneau_s7", 0xc9e3b0ddeb4a27a0),
    ("prop_treillis", 0xfcf18b5738133cee),
    ("prop_vaisselle", 0x77b8ea35472394f9),
    ("puits_1", 0x20d222dfeb82f789),
    ("rempart_porte_1", 0x183526367ac2b668),
    ("roche_arche_1", 0x07f48629ffe307a3),
    ("roche_bloc_chaud", 0xb8b783f806e07a1a),
    ("roche_bloc_grand", 0x858b4da0bf5ddca1),
    ("roche_bloc_gris", 0x610d5580eecbecf0),
    ("roche_colonne_brisee_1", 0xf9d3712f2451deb6),
    ("roche_cromlech_1", 0x5919888b7890ac5c),
    ("roche_dalles_1", 0xa3a15d8390435835),
    ("roche_falaise_1", 0xe3cff9a3b667b342),
    ("roche_falaise_chaude", 0x1151af0afe9590f1),
    ("roche_galets_1", 0xb73160c32f589d8b),
    ("roche_grotte_1", 0x5869be1b0c26bb36),
    ("roche_menhir_1", 0x7e89507d57242024),
    ("roche_ruine_mur_1", 0x28c4c99db13af436),
    ("taverne_1", 0x69f90d1cf1c251e2),
    ("tour_guet_1", 0x3995c16b88027816),
];

#[test]
fn empreintes_epinglees_et_identiques_avec_1_et_8_fils() {
    let (c, r) = (catalogue(), registre());
    let imprimer = std::env::var_os("EM_EMPREINTES").is_some();
    let mut manquantes = Vec::new();
    for id in c.ids() {
        let a = &c.get(id).unwrap().generator;
        let _ = a;
        // les plans de GenPlan n'exposent pas `fingerprint` : on passe par un plan construit directement
        let (f1, f8) = empreintes(&c, &r, id);
        assert_eq!(f1, f8, "{id} : 1 fil et 8 fils diffèrent");
        if imprimer {
            println!("    (\"{id}\", {f1:#018x}),");
        }
        match EMPREINTES.iter().find(|(n, _)| *n == id) {
            Some((_, p)) => assert_eq!(f1, *p, "{id} : empreinte épinglée {p:#018x}, réelle {f1:#018x}"),
            None => manquantes.push(id.to_owned()),
        }
    }
    assert!(
        imprimer || manquantes.is_empty(),
        "recettes sans empreinte épinglée : {manquantes:?}"
    );
}

fn empreintes(c: &AssetCatalogue, r: &GeneratorRegistry, id: &str) -> (u64, u64) {
    let a = c.get(id).unwrap();
    let g = r.get(&a.generator).unwrap();
    let octets = serde_json::to_vec(&serde_json::to_value(&a.params).unwrap()).unwrap();
    let params = GenParams::new(g.id(), g.version(), octets);
    let plan = g.plan(&params, a.seed).unwrap();
    // on rastérise nous-mêmes par fenêtres de 64 et on hache comme `ShapePlan::fingerprint`, en 1 et en 8 fils
    (empreinte_fils(plan.as_ref(), 1), empreinte_fils(plan.as_ref(), 8))
}

fn empreinte_fils(plan: &dyn em_gen::GenPlan, fils: usize) -> u64 {
    use em_core::{Fnv64, VoxelBox, VoxelCoord, floor_div};
    use em_voxel::{PutMode, VoxelSink};
    struct Collecte(Vec<(VoxelCoord, u16)>);
    impl VoxelSink for Collecte {
        fn put(&mut self, at: VoxelCoord, value: em_core::VoxelValue, _m: PutMode) {
            self.0.push((at, value.raw()));
        }
    }
    let b = plan.bounds(0);
    let (a, c) = (b.min(), b.max());
    let t = 64_i64;
    let mut origines = Vec::new();
    let mut y = floor_div(i64::from(a.y), t) * t;
    while y < i64::from(c.y) {
        let mut z = floor_div(i64::from(a.z), t) * t;
        while z < i64::from(c.z) {
            let mut x = floor_div(i64::from(a.x), t) * t;
            while x < i64::from(c.x) {
                origines.push([x as i32, y as i32, z as i32]);
                x += t;
            }
            z += t;
        }
        y += t;
    }
    let hacher = |o: &[i32; 3]| -> u64 {
        let fen = VoxelBox::new(
            VoxelCoord::new(o[0], o[1], o[2]),
            VoxelCoord::new(o[0] + 64, o[1] + 64, o[2] + 64),
        )
        .unwrap();
        let mut s = Collecte(Vec::new());
        plan.rasterize(0, fen, &mut s);
        if s.0.is_empty() {
            return 0;
        }
        s.0.sort_by_key(|(v, _)| (v.y, v.z, v.x));
        let mut h = Fnv64::new();
        for (v, raw) in &s.0 {
            for k in [v.x, v.y, v.z] {
                h.add_u64(i64::from(k) as u64);
            }
            h.add_u64(u64::from(*raw));
        }
        h.value()
    };
    let mut partiels = vec![0_u64; origines.len()];
    let par = origines.len().div_ceil(fils.max(1)).max(1);
    std::thread::scope(|s| {
        for (po, pp) in origines.chunks(par).zip(partiels.chunks_mut(par)) {
            s.spawn(move || {
                for (o, p) in po.iter().zip(pp.iter_mut()) {
                    *p = hacher(o);
                }
            });
        }
    });
    let mut h = Fnv64::new();
    for k in [a.x, a.y, a.z, c.x, c.y, c.z] {
        h.add_u64(i64::from(k) as u64);
    }
    for (o, p) in origines.iter().zip(&partiels) {
        if *p != 0 {
            for k in o {
                h.add_u64(i64::from(*k) as u64);
            }
            h.add_u64(*p);
        }
    }
    h.value()
}

/// Les voxels d'une boîte coupée en deux (à une coordonnée impaire) sont ceux de la boîte entière.
#[test]
fn bords_de_chunk_sans_couture() {
    use em_core::{VoxelBox, VoxelCoord};
    use em_voxel::{PutMode, VoxelSink};
    struct Compte(u64);
    impl VoxelSink for Compte {
        fn put(&mut self, at: VoxelCoord, value: em_core::VoxelValue, _m: PutMode) {
            let cle = (at.x as u64) ^ ((at.y as u64) << 7) ^ ((at.z as u64) << 14);
            self.0 = self
                .0
                .wrapping_add(u64::from(value.raw()).wrapping_mul(cle.wrapping_add(1)));
        }
    }
    let (c, r) = (catalogue(), registre());
    for id in [
        "maison_a",
        "grange_1",
        "moulin_vent_1",
        "eglise_1",
        "prop_etal",
        "prop_charrette",
        "roche_falaise_1",
        "roche_arche_1",
    ] {
        let a = c.get(id).unwrap();
        let g = r.get(&a.generator).unwrap();
        let octets = serde_json::to_vec(&serde_json::to_value(&a.params).unwrap()).unwrap();
        let plan = g
            .plan(&GenParams::new(g.id(), g.version(), octets), a.seed)
            .unwrap();
        let b = plan.bounds(0);
        let (lo, hi) = (b.min(), b.max());
        let boite = |x0, x1, y0, y1, z0, z1| {
            VoxelBox::new(VoxelCoord::new(x0, y0, z0), VoxelCoord::new(x1, y1, z1)).unwrap()
        };
        let mut tout = Compte(0);
        plan.rasterize(0, boite(lo.x, hi.x, lo.y, hi.y, lo.z, hi.z), &mut tout);
        let (mx, mz) = ((lo.x + (hi.x - lo.x) / 2) | 1, (lo.z + (hi.z - lo.z) / 2) | 1);
        let mut morceaux = Compte(0);
        for (x0, x1) in [(lo.x, mx), (mx, hi.x)] {
            for (z0, z1) in [(lo.z, mz), (mz, hi.z)] {
                plan.rasterize(0, boite(x0, x1, lo.y, hi.y, z0, z1), &mut morceaux);
            }
        }
        assert_eq!(tout.0, morceaux.0, "{id} : couture au bord de fenêtre");
    }
}

fn graines_maison() -> Vec<String> {
    let mut v: Vec<String> = ["gravit", "a", "ferme", "hameau"].map(String::from).to_vec();
    v.extend((0..60).map(|i| format!("graine{i}")));
    v
}

/// Chaque étage : toutes les pièces sont reliées par les portes ; au moins un lit et une cuisine par maison.
#[test]
fn les_maisons_sont_habitables() {
    for g in graines_maison() {
        let plan = planifier(&HouseParams::derive(&g));
        assert!(plan.n_beds >= 1, "{g} : aucun lit");
        assert!(plan.n_kitchens >= 1, "{g} : aucune cuisine");
        for s in 0..plan.st as usize {
            let ids: Vec<usize> = plan
                .rooms
                .iter()
                .filter(|r| r.s as usize == s && r.cells.len() >= 150)
                .map(|r| r.id)
                .collect();
            if ids.len() < 2 {
                continue;
            }
            let mut compo: Vec<usize> = (0..plan.rooms.len()).collect();
            fn racine(c: &mut Vec<usize>, i: usize) -> usize {
                if c[i] != i {
                    let r = racine(c, c[i]);
                    c[i] = r;
                }
                c[i]
            }
            for d in plan.int_doors.iter().filter(|d| d.s as usize == s) {
                let mid = d.d + 7;
                let (a, b) = if d.ax == 0 {
                    (plan.room_at(s, d.c0 - 2, mid), plan.room_at(s, d.c1 + 1, mid))
                } else {
                    (plan.room_at(s, mid, d.c0 - 2), plan.room_at(s, mid, d.c1 + 1))
                };
                if let (Some(a), Some(b)) = (a, b) {
                    let (ra, rb) = (racine(&mut compo, a), racine(&mut compo, b));
                    compo[ra] = rb;
                }
            }
            let r0 = racine(&mut compo, ids[0]);
            for i in &ids {
                assert_eq!(
                    racine(&mut compo, *i),
                    r0,
                    "{g} : la pièce {i} de l'étage {s} n'est reliée par aucune porte"
                );
            }
        }
    }
}

/// Cheminée creuse, murs non nuls : lus dans les voxels de la maison rastérisée (repère brut du JavaScript).
#[test]
fn cheminee_creuse_et_murs_epais() {
    for g in ["gravit", "a", "graine3", "graine8"] {
        let cfg = HouseConfig {
            glazing: false,
            door_leaf: false,
            raw_frame: true,
            ..HouseConfig::default()
        };
        let m = HouseGenerator::new(Matieres::standard()).build(g, &cfg);
        let p = m.plan();
        let b = m.shape.bounds_box();
        let w = m
            .shape
            .render(0, [b.0[0], 0, b.0[2]], [b.1[0], p.top_y + 12, b.1[2]]);
        // conduit de fumée : air au milieu de la cheminée, pierre dans sa paroi, à 5 voxels sous le sommet
        let (uc, y) = (p.chim_uc, p.chim_top - 5);
        let (fx, fz) = p.cfr.xz(uc, -8);
        assert!(w.get(fx, y, fz).is_air(), "{g} : le conduit n'est pas creux");
        let (px, pz) = p.cfr.xz(uc + 9, -8);
        assert!(
            !w.get(px, y, pz).is_air(),
            "{g} : la paroi de la cheminée est vide"
        );
        // épaisseur des murs au rez-de-chaussée (soubassement, y = 4) : jamais une paroi de 0 voxel
        let mut trop_minces = 0;
        for z in b.0[2]..b.1[2] {
            for x in b.0[0]..b.1[0] {
                let i = p.ix(x, z);
                if p.fm[i] == 1 && p.ds[i] == 3 {
                    // cellule à 3 voxels de la face extérieure : le mur y est plein (les joints sont en retrait de 2)
                    let pleine = !w.get(x, 4, z).is_air();
                    let porte = (x - p.dxw).abs() < 16 && z >= p.dz1 - 7;
                    if !pleine && !porte {
                        trop_minces += 1;
                    }
                }
            }
        }
        assert_eq!(
            trop_minces, 0,
            "{g} : {trop_minces} cellules de mur à épaisseur nulle"
        );
    }
}

/// Budget de calcul : plan (décisions) et rastérisation du niveau 0 d'une maison complète. Les bornes sont larges
/// (profil de test) ; `--nocapture` imprime les valeurs, à relever avec `cargo test --release`.
#[test]
fn budget_de_calcul_d_une_maison() {
    use std::time::Instant;
    for g in ["gravit", "a"] {
        let t0 = Instant::now();
        let m = HouseGenerator::new(Matieres::standard()).build(g, &HouseConfig::default());
        let plan_ms = t0.elapsed().as_millis();
        let t1 = Instant::now();
        let n = m.shape.solid_count();
        let raster_ms = t1.elapsed().as_millis();
        println!(
            "{g} : plan {plan_ms} ms, rastérisation du niveau 0 en un fil {raster_ms} ms, {n} voxels pleins"
        );
        assert!(plan_ms < 3_000 && raster_ms < 30_000, "{g} : budget dépassé");
    }
}
