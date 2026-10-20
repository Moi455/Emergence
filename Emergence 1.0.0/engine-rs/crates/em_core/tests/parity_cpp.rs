//! Parité bit à bit avec le C++ : les vecteurs de `cpp_vectors.inc.rs` sont produits par
//! `engine-rs/scripts/gen_cpp_vectors.sh` en compilant les vrais en-têtes du moteur.

use em_core::q16::{isqrt64, qdiv, qexp2, qlerp, qmul, qramp, qsmoothstep};
use em_core::{
    EntityId, Fnv64, Layer, SplitMix64, crc32, floor_div, hash_combine, hash2, hash3, layer_seed, mix64,
};

include!("vecteurs/cpp_vectors.inc.rs");

#[test]
fn mix64_egal_au_cpp() {
    for (x, attendu) in MIX64 {
        assert_eq!(mix64(x), attendu, "mix64({x:#x})");
    }
}

#[test]
fn hachages_egaux_au_cpp() {
    for (h, v, attendu) in HASH_COMBINE {
        assert_eq!(hash_combine(h, v), attendu);
    }
    for (s, x, y, attendu) in HASH2 {
        assert_eq!(hash2(s, x, y), attendu, "hash2({s:#x}, {x}, {y})");
    }
    for (s, x, y, z, attendu) in HASH3 {
        assert_eq!(hash3(s, x, y, z), attendu, "hash3({s:#x}, {x}, {y}, {z})");
    }
}

#[test]
fn graines_de_couche_egales_au_cpp() {
    for (s, couche, attendu) in LAYER_SEED {
        assert_eq!(layer_seed(s, couche), attendu);
    }
    // L'énumération Rust porte les mêmes numéros que le C++.
    assert_eq!(Layer::Frontier.id(), 1);
    assert_eq!(Layer::Strata.id(), 13);
    assert_eq!(Layer::Forest.seed(42), layer_seed(42, 5));
}

#[test]
fn splitmix_egal_a_la_formule_cpp() {
    for bloc in SPLITMIX.chunks(8) {
        let mut generateur = SplitMix64::new(bloc[0].0);
        for &(_, attendu) in bloc {
            assert_eq!(generateur.next_u64(), attendu);
        }
    }
}

#[test]
fn point_fixe_egal_au_cpp() {
    for (a, b, r) in QMUL {
        assert_eq!(qmul(a, b), r, "qmul({a}, {b})");
    }
    for (a, b, r) in QDIV {
        assert_eq!(qdiv(a, b), r, "qdiv({a}, {b})");
    }
    for (a, b, t, r) in QLERP {
        assert_eq!(qlerp(a, b, t), r);
    }
    for (e0, e1, x, r) in QSMOOTHSTEP {
        assert_eq!(qsmoothstep(e0, e1, x), r, "qsmoothstep({e0}, {e1}, {x})");
    }
    for (e0, e1, x, r) in QRAMP {
        assert_eq!(qramp(e0, e1, x), r);
    }
    for (x, r) in QEXP2 {
        assert_eq!(qexp2(x), r, "qexp2({x})");
    }
    for (v, r) in ISQRT64 {
        assert_eq!(isqrt64(v), r, "isqrt64({v})");
    }
    for (a, b, r) in FLOOR_DIV {
        assert_eq!(floor_div(a, b), r, "floor_div({a}, {b})");
    }
}

#[test]
fn empreintes_egales_au_cpp() {
    for (octets, attendu) in CRC32 {
        assert_eq!(crc32(octets), attendu);
    }
    assert_eq!(crc32(b"123456789"), 0xCBF4_3926);
    for (octets, attendu) in FNV64 {
        let mut f = Fnv64::new();
        f.add(octets);
        assert_eq!(f.value(), attendu);
    }
    for (v, attendu) in FNV64_U64 {
        let mut f = Fnv64::new();
        f.add_u64(v);
        f.add_u64(7);
        assert_eq!(f.value(), attendu);
    }
}

#[test]
fn identifiants_d_entite_egaux_au_cpp() {
    for (case, generation, brut) in ENTITY_ID {
        let id = EntityId::new(case, generation);
        assert_eq!(id.raw(), brut);
        assert_eq!((id.slot(), id.generation()), (case, generation));
    }
}
