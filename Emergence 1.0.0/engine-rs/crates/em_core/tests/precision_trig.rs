//! Erreurs maximales des fonctions trigonométriques et logarithmiques en Q16 (comparaison en `f64`,
//! réservée aux tests : la crate elle-même n'utilise aucun flottant).

use em_core::q16::{Q16, atan2_turns, cos_turns, qexp2, qlog2, qpow, qsqrt, sin_turns};

const TOLERANCE: f64 = 1.0 / 16_384.0; // 2^-14
const UN: f64 = 65_536.0;
const POINTS: i64 = 10_000;

/// Erreur maximale mesurée de `f` contre `reference` sur 10 000 points de `[debut, fin)` (valeurs brutes).
fn erreur_max(debut: i64, fin: i64, f: impl Fn(i64) -> f64, reference: impl Fn(f64) -> f64) -> f64 {
    let mut pire: f64 = 0.0;
    for i in 0..POINTS {
        let brut = debut + (fin - debut) * i / POINTS;
        let ecart = (f(brut) - reference(brut as f64 / UN)).abs();
        pire = pire.max(ecart);
    }
    pire
}

#[test]
fn sin_cos_tours() {
    let tau = std::f64::consts::TAU;
    let es = erreur_max(
        -65_536,
        2 * 65_536,
        |t| sin_turns(Q16(t)).0 as f64 / UN,
        |t| (t * tau).sin(),
    );
    let ec = erreur_max(
        -65_536,
        2 * 65_536,
        |t| cos_turns(Q16(t)).0 as f64 / UN,
        |t| (t * tau).cos(),
    );
    println!("[Mesuré] erreur max sin_turns = {es:.3e} ; cos_turns = {ec:.3e} (limite {TOLERANCE:.3e})");
    assert!(es <= TOLERANCE && ec <= TOLERANCE);
}

#[test]
fn atan2_tours() {
    let mut pire: f64 = 0.0;
    for i in 0..POINTS {
        // Angles sur tout le cercle et rayons variés (de 1 à ~65 000 en Q16 brut).
        let angle = (i as f64 + 0.5) / POINTS as f64 * std::f64::consts::TAU;
        let rayon = 1.0 + ((i * 7_919) % 1_000) as f64 * 65.0;
        let (x, y) = (
            (rayon * angle.cos()).round() as i64,
            (rayon * angle.sin()).round() as i64,
        );
        if x == 0 && y == 0 {
            continue;
        }
        let attendu = (y as f64).atan2(x as f64) / std::f64::consts::TAU;
        let mut ecart = (atan2_turns(Q16(y), Q16(x)).0 as f64 / UN - attendu).abs();
        ecart = ecart.min(1.0 - ecart); // le saut ±0,5 tour n'est pas une erreur
        // L'arrondi des entrées à l'entier grossit l'écart quand le rayon est petit : on le retranche.
        ecart = (ecart - 0.5 / rayon / std::f64::consts::TAU).max(0.0);
        pire = pire.max(ecart);
    }
    println!("[Mesuré] erreur max atan2_turns = {pire:.3e} (limite {TOLERANCE:.3e})");
    assert!(pire <= TOLERANCE);
    assert_eq!(atan2_turns(Q16::ZERO, Q16::ZERO), Q16::ZERO);
    assert_eq!(atan2_turns(Q16::ONE, Q16::ZERO), Q16(16_384));
    assert_eq!(atan2_turns(-Q16::ONE, Q16::ZERO), Q16(-16_384));
    assert_eq!(atan2_turns(Q16::ZERO, Q16::ONE), Q16::ZERO);
}

#[test]
fn log2_exp2_sqrt_pow() {
    let e = erreur_max(1, 1 << 30, |x| qlog2(Q16(x)).0 as f64 / UN, f64::log2);
    println!("[Mesuré] erreur max qlog2 = {e:.3e} (limite {TOLERANCE:.3e})");
    assert!(e <= TOLERANCE);
    // Valeurs exactes aux puissances de deux.
    assert_eq!(qlog2(Q16::ONE), Q16::ZERO);
    assert_eq!(qlog2(Q16::from_int(8)), Q16::from_int(3));
    assert_eq!(qlog2(Q16::HALF), Q16::from_int(-1));
    // qsqrt : erreur d'au plus un pas de Q16.
    let es = erreur_max(0, 1 << 40, |x| qsqrt(Q16(x)).0 as f64 / UN, f64::sqrt);
    println!("[Mesuré] erreur max qsqrt = {es:.3e}");
    assert!(es <= 1.0 / UN);
    // qpow : limitée par qexp2 (erreur relative ~1e-4).
    let (x, p) = (Q16::from_int(3), Q16::from_ratio(5, 2));
    let obtenu = qpow(x, p).0 as f64 / UN;
    let attendu = 3.0_f64.powf(2.5);
    assert!(
        (obtenu - attendu).abs() / attendu < 5e-4,
        "3^2,5 = {obtenu} au lieu de {attendu}"
    );
    assert_eq!(qexp2(Q16::from_int(3).0), Q16::from_int(8).0);
}
