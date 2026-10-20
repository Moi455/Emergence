//! Continuité : deux voxels voisins de même matière ne présentent AUCUNE discontinuité due au voxel
//! (docs/19 § 4.6 : champ continu en coordonnées monde, pas de chanfrein, pas de mosaïque).

mod commun;

use commun::{dossier_donnees, table_reelle, vegetation_test};
use em_core::{MaterialId, VoxelCoord, VoxelValue};
use em_material::{
    EvalContext, MaterialEvaluator, MaterialFlags, MaterialTable, TintMode, tint_stone, tint_vegetation,
    tint_wood,
};

/// Table identique à la vraie, sans gigue par voxel : ne reste que le champ continu.
fn table_sans_gigue() -> MaterialTable {
    let d = dossier_donnees();
    let csv = std::fs::read_to_string(d.join("materials.csv")).unwrap();
    let toml: String = std::fs::read_to_string(d.join("material_render.toml"))
        .unwrap()
        .lines()
        .map(|l| {
            if l.starts_with("voxel_jitter") {
                "voxel_jitter = 0"
            } else {
                l
            }
        })
        .collect::<Vec<_>>()
        .join("\n");
    MaterialTable::from_sources(&csv, &toml).unwrap()
}

fn tint_de_test(mode: TintMode) -> Vec<u8> {
    match mode {
        TintMode::Ramp128 => vec![64],
        TintMode::WoodAxis => vec![tint_wood(0, 3), tint_wood(1, 3), tint_wood(2, 9), tint_wood(3, 9)],
        TintMode::StonePiece => vec![tint_stone(0), tint_stone(5), tint_stone(77)],
        TintMode::Vegetation => vec![tint_vegetation(0, 0), tint_vegetation(1, 1)],
        TintMode::Terrain => vec![10, 100],
    }
}

fn voxel(i: i32, axe: usize) -> VoxelCoord {
    let mut v = [-37, 12, 205];
    v[axe] += i;
    VoxelCoord {
        x: v[0],
        y: v[1],
        z: v[2],
    }
}

/// Moyenne et maximum des écarts de luminance... du canal le plus écarté, entre voxels séparés de `pas`.
fn ecarts(ev: &MaterialEvaluator, valeur: VoxelValue, axe: usize, pas: i32) -> (i64, i64) {
    let n = 400;
    let (mut somme, mut max) = (0i64, 0i64);
    for i in 0..n {
        let a = ev.eval(&EvalContext::new(valeur, voxel(i, axe), 0)).albedo();
        let b = ev
            .eval(&EvalContext::new(valeur, voxel(i + pas, axe), 0))
            .albedo();
        let d = a.max_abs_diff(b).raw();
        somme += d;
        max = max.max(d);
    }
    (somme / i64::from(n), max)
}

#[test]
fn voisins_continus_pour_chaque_classe_et_chaque_axe() {
    let table = table_sans_gigue();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::new(&table, &veg);
    for def in table.iter().filter(|d| d.id() != MaterialId::AIR) {
        let mode = def.render().tint_mode();
        for tint in tint_de_test(mode) {
            let valeur = VoxelValue::new(def.id(), tint);
            for axe in 0..3 {
                let (moy_voisin, max_voisin) = ecarts(&ev, valeur, axe, 1);
                let (moy_loin, _) = ecarts(&ev, valeur, axe, 40); // 2 m plus loin : décorrélé
                let etiquette = format!("{} teinte {tint} axe {axe}", def.name());
                // une mosaïque donnerait des écarts voisins égaux aux écarts lointains (rapport 1) ; un champ à 8-12 cycles/m,
                // échantillonné tous les 5 cm, en donne environ la moitié
                // exception voulue : le feuillage garde la gigue de nuance ±0,14 du `voxel_tree.py` validé (docs/19 § 4.6)
                let feuillage = def.render().flags().contains(MaterialFlags::FOLIAGE);
                assert!(
                    feuillage || moy_voisin * 4 <= moy_loin.max(400) * 3,
                    "{etiquette}: voisin {moy_voisin}, loin {moy_loin}"
                );
                // et aucun saut brutal : moins du quart de la plage de la couleur entre deux voxels
                assert!(max_voisin < 16_384, "{etiquette}: saut {max_voisin}");
            }
        }
    }
}

#[test]
fn le_fil_du_bois_court_sur_toute_la_poutre() {
    let table = table_sans_gigue();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::new(&table, &veg);
    let bois = table.by_name("oak_planks").unwrap();
    for axe in 0..3 {
        let valeur = VoxelValue::new(bois, tint_wood(axe as u8, 4));
        let (_, max_le_long) = ecarts(&ev, valeur, axe, 1);
        let (_, max_en_travers) = ecarts(&ev, valeur, (axe + 1) % 3, 1);
        assert!(
            max_le_long * 3 < max_en_travers.max(1) * 2 || max_le_long < 600,
            "axe {axe}: {max_le_long} contre {max_en_travers}"
        );
    }
}

#[test]
fn la_gigue_par_voxel_reste_un_grain_faible() {
    let reel = table_reelle();
    let sans = table_sans_gigue();
    let veg = vegetation_test();
    let (e_reel, e_sans) = (
        MaterialEvaluator::new(&reel, &veg),
        MaterialEvaluator::new(&sans, &veg),
    );
    for def in reel.iter().filter(|d| d.id() != MaterialId::AIR) {
        let gigue = def.render().voxel_jitter().raw();
        for tint in tint_de_test(def.render().tint_mode()) {
            let valeur = VoxelValue::new(def.id(), tint);
            for i in 0..200 {
                let ctx = EvalContext::new(valeur, voxel(i, 0), 0);
                let d = e_reel
                    .eval(&ctx)
                    .albedo()
                    .max_abs_diff(e_sans.eval(&ctx).albedo())
                    .raw();
                // décalage de nuance ≤ gigue, la rampe change d'au plus 2 par unité de nuance ; marge d'arrondi
                assert!(
                    d <= 2 * gigue + 8,
                    "{} : écart {d} pour une gigue {gigue}",
                    def.name()
                );
            }
        }
    }
}

#[test]
fn le_champ_ne_depend_que_de_la_position_monde() {
    // même centre en millimètres => même couleur, quel que soit le niveau qui l'a produit (sans gigue)
    let table = table_sans_gigue();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::new(&table, &veg);
    let v = VoxelValue::new(table.by_name("granite").unwrap(), 33);
    // voxel (0,0,0) du niveau 1 : centre à 50 mm ; il n'a pas de voxel du niveau 0 de même centre,
    // mais le voxel (1,1,1) du niveau 0 est centré à 75 mm et (0,0,0) à 25 mm : on vérifie la formule du centre
    assert_eq!(
        EvalContext::new(v, VoxelCoord { x: 0, y: 0, z: 0 }, 1).center_mm(),
        [50, 50, 50]
    );
    assert_eq!(
        EvalContext::new(v, VoxelCoord { x: -1, y: 0, z: 3 }, 0).center_mm(),
        [-25, 25, 175]
    );
    let a = ev.eval(&EvalContext::new(v, VoxelCoord { x: 4, y: 5, z: 6 }, 0));
    let b = ev.eval(&EvalContext::new(v, VoxelCoord { x: 4, y: 5, z: 6 }, 0));
    assert_eq!(a, b);
}

#[test]
fn joint_de_pierre_seulement_entre_deux_pieces_differentes() {
    let table = table_reelle();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::new(&table, &veg);
    let pierre = table.by_name("cut_stone").unwrap();
    let a = VoxelValue::new(pierre, tint_stone(40));
    let b = VoxelValue::new(pierre, tint_stone(7));
    let mortier = VoxelValue::new(pierre, tint_stone(0));
    let pos = VoxelCoord { x: 3, y: 4, z: 5 };
    let seul = ev.eval(&EvalContext::new(a, pos, 0)).albedo();
    let meme_piece = ev
        .eval(&EvalContext::new(a, pos, 0).with_plane_neighbors([Some(a), Some(a), None, Some(a)]))
        .albedo();
    let autre_piece = ev
        .eval(&EvalContext::new(a, pos, 0).with_plane_neighbors([Some(b), None, None, None]))
        .albedo();
    let avec_mortier = ev
        .eval(&EvalContext::new(a, pos, 0).with_plane_neighbors([Some(mortier), None, None, None]))
        .albedo();
    assert_eq!(seul, meme_piece, "aucun joint entre deux voxels d'une même pièce");
    assert_eq!(seul, avec_mortier, "le mortier est déjà le joint");
    assert!(
        autre_piece.luminance() < seul.luminance(),
        "joint assombri entre deux pièces"
    );
    // un seul côté du joint est assombri : la pièce au plus petit numéro garde sa couleur
    let petit = ev
        .eval(&EvalContext::new(b, pos, 0).with_plane_neighbors([Some(a), None, None, None]))
        .albedo();
    let petit_seul = ev.eval(&EvalContext::new(b, pos, 0)).albedo();
    assert_eq!(petit, petit_seul);
}
