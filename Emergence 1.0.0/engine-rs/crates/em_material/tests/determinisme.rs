//! Déterminisme de la référence CPU (entiers) : mêmes entrées, mêmes sorties, empreinte épinglée.

mod commun;

use commun::{table_reelle, vegetation_test};
use em_core::{Fnv64, VoxelCoord, VoxelValue};
use em_material::{EvalContext, MaterialEvaluator, eval_albedo_cpu, tint_stone, tint_vegetation, tint_wood};

/// Empreinte épinglée de l'évaluation de 4 096 voxels de chaque classe (albédo, rugosité, translucidité, émission).
/// L23p a ajouté la classe 36 « moss » : sans elle, les 35 autres classes redonnent l'ancienne empreinte
/// `0x4b2051d3d4d4da37` à la rampe de `cut_stone` près (L23p : rampe à joints bruns) ; le code du mode continu n'a pas bougé.
/// L35 à L37 : classes 37 à 57 ajoutées (palettes du bâti, props et rochers) ; ancienne empreinte `0x44cb47594b400546`.
const EMPREINTE_EVALUATION: u64 = 0xf3f3_0382_7839_21d6;

fn empreinte() -> u64 {
    let table = table_reelle();
    let veg = vegetation_test();
    let ev = MaterialEvaluator::new(&table, &veg);
    let mut h = Fnv64::new();
    for def in table.iter() {
        for i in 0..4_096i32 {
            let tint = match i % 4 {
                0 => tint_wood((i % 3) as u8, (i % 29) as u8),
                1 => tint_stone((i % 128) as u8),
                2 => tint_vegetation((i % 3) as u8, (i % 4) as u8),
                _ => (i % 128) as u8,
            };
            let v = VoxelCoord {
                x: (i * 7) % 211 - 105,
                y: (i * 13) % 97 - 20,
                z: (i * 29) % 307 - 150,
            };
            let s = ev.eval(&EvalContext::new(
                VoxelValue::new(def.id(), tint),
                v,
                (i % 3) as u8,
            ));
            for c in s.albedo().channels() {
                h.add_u64(c.raw() as u64);
            }
            h.add_u64(s.roughness().raw() as u64);
            h.add_u64(s.translucency().raw() as u64);
            h.add_u64(s.emission().raw() as u64);
        }
    }
    h.value()
}

#[test]
fn evaluation_deterministe() {
    assert_eq!(empreinte(), empreinte());
    let table = table_reelle();
    let veg = vegetation_test();
    let ctx = EvalContext::new(
        VoxelValue::new(table.by_name("leaves").unwrap(), 4),
        VoxelCoord { x: 9, y: 9, z: 9 },
        0,
    );
    assert_eq!(
        eval_albedo_cpu(&table, &veg, &ctx),
        MaterialEvaluator::new(&table, &veg).eval(&ctx).albedo()
    );
}

#[test]
fn empreinte_evaluation_epinglee() {
    assert_eq!(
        empreinte(),
        EMPREINTE_EVALUATION,
        "empreinte réelle : {:#018x}",
        empreinte()
    );
}

#[test]
fn l_air_est_transparent_et_noir() {
    let table = table_reelle();
    let veg = vegetation_test();
    let s = MaterialEvaluator::new(&table, &veg).eval(&EvalContext::new(
        VoxelValue::AIR,
        VoxelCoord { x: 0, y: 0, z: 0 },
        0,
    ));
    assert_eq!(s.albedo().channels()[0].raw(), 0);
    assert_eq!(s.emission().raw(), 0);
}

#[test]
fn les_feuilles_suivent_la_rampe_de_l_essence() {
    // sans rampe enregistrée, repli sur la rampe de la classe ; avec, la couleur change
    let table = table_reelle();
    let sans = em_material::VegetationRamps::new();
    let avec = vegetation_test();
    let ctx = EvalContext::new(
        VoxelValue::new(table.by_name("leaves").unwrap(), 0),
        VoxelCoord { x: 3, y: 3, z: 3 },
        0,
    );
    assert_ne!(
        eval_albedo_cpu(&table, &sans, &ctx),
        eval_albedo_cpu(&table, &avec, &ctx)
    );
}
