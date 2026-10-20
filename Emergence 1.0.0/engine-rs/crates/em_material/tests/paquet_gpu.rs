//! Paquet GPU : tailles, disposition, déterminisme octet pour octet, empreinte épinglée.
#![cfg(feature = "gpu")]

mod commun;

use commun::{table_reelle, vegetation_test};
use em_material::gpu::NO_DETAIL;
use em_material::{CLASS_COUNT, GpuMaterialPacket, MaterialGpu, VegetationRamps};

/// Empreinte épinglée du paquet des vraies données + rampes de `vegetation_test`.
/// Si elle change : soit une donnée d'aspect a changé exprès (mettre à jour), soit c'est un bug de déterminisme.
const EMPREINTE_PAQUET: u64 = 0xd446_0f47_e8c9_ae23;

#[test]
fn disposition_64_octets() {
    assert_eq!(std::mem::size_of::<MaterialGpu>(), 64);
    assert_eq!(std::mem::align_of::<MaterialGpu>(), 4);
    let p = GpuMaterialPacket::new(&table_reelle(), &vegetation_test());
    assert_eq!(p.material_bytes().len(), 512 * 64);
    assert_eq!(p.class_ramp_bytes().len(), 512 * 3 * 16);
    assert_eq!(p.veg_ramp_bytes().len(), 32 * 4 * 4 * 3 * 16);
    assert_eq!(p.veg_seed_bytes().len(), 32 * 4);
    assert_eq!(p.total_bytes(), 32_768 + 24_576 + 24_576 + 128);
}

#[test]
fn entrees_conformes_a_la_table() {
    let t = table_reelle();
    let e = t.gpu_entries();
    assert_eq!(e.len(), CLASS_COUNT);
    let leaves = e[t.by_name("leaves").unwrap().get() as usize];
    assert_eq!(leaves.tint_mode, 3);
    assert_eq!(leaves.flags, 1);
    assert_eq!(leaves.translucency, 0.45_f32.round_to_q16());
    let bois = e[t.by_name("wood_trim").unwrap().get() as usize];
    assert_eq!(bois.tint_mode, 1);
    assert_ne!(bois.detail_layer, NO_DETAIL);
    assert_eq!(t.detail_names()[bois.detail_layer as usize], "wood_fine");
    assert_eq!(e[0].detail_layer, NO_DETAIL);
    // une classe non définie est magenta (repère visible)
    let libre = e[500];
    assert!(libre.albedo_linear[0] > 0.9 && libre.albedo_linear[1] < 0.01);
    assert_eq!(t.class_ramps().len(), 512 * 3);
}

trait ArrondiQ16 {
    fn round_to_q16(self) -> f32;
}
impl ArrondiQ16 for f32 {
    /// La valeur flottante telle que le paquet la porte : décimal -> Q16 -> f32.
    fn round_to_q16(self) -> f32 {
        ((self * 65_536.0).round()) / 65_536.0
    }
}

#[test]
fn rampes_de_vegetation_indexees_comme_19a() {
    let v = vegetation_test();
    let d = v.gpu_data();
    assert_eq!(d.len(), 32 * 4 * 4 * 3);
    // pommier = essence 1, fruits = rôle 3, rampe 0, couleur moyenne
    let i = ((4 + 3) * 4) * 3 + 1;
    let moyen = v.mid_color(1, em_material::RampRole::Fruits, 0).channels();
    assert_eq!(d[i][0], moyen[0].raw() as f32 / 65_536.0);
    // une rampe absente vaut zéro
    assert_eq!(d[((2 * 4 + 1) * 4) * 3], [0.0; 4]);
    assert_eq!(v.gpu_seeds().len(), 32);
    assert_ne!(v.gpu_seeds()[0], v.gpu_seeds()[1]);
}

#[test]
fn paquet_identique_octet_pour_octet() {
    let (t1, t2) = (table_reelle(), table_reelle());
    let (v1, v2) = (vegetation_test(), vegetation_test());
    let (a, b) = (GpuMaterialPacket::new(&t1, &v1), GpuMaterialPacket::new(&t2, &v2));
    assert_eq!(a.material_bytes(), b.material_bytes());
    assert_eq!(a.class_ramp_bytes(), b.class_ramp_bytes());
    assert_eq!(a.veg_ramp_bytes(), b.veg_ramp_bytes());
    assert_eq!(a.veg_seed_bytes(), b.veg_seed_bytes());
    assert_eq!(a.fingerprint(), b.fingerprint());
}

#[test]
fn empreinte_du_paquet_epinglee() {
    let p = GpuMaterialPacket::new(&table_reelle(), &vegetation_test());
    assert_eq!(
        p.fingerprint(),
        EMPREINTE_PAQUET,
        "empreinte réelle : {:#018x}",
        p.fingerprint()
    );
}

#[test]
fn changer_de_saison_change_le_paquet() {
    let t = table_reelle();
    let ete = vegetation_test();
    let mut automne = VegetationRamps::new();
    automne
        .register(
            "chene",
            em_material::RampRole::Leaves,
            &[[[80, 30, 10], [170, 90, 20], [220, 160, 50]]],
        )
        .unwrap();
    let a = GpuMaterialPacket::new(&t, &ete);
    let b = GpuMaterialPacket::new(&t, &automne);
    assert_eq!(a.material_bytes(), b.material_bytes());
    assert_ne!(a.fingerprint(), b.fingerprint());
}
