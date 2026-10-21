//! Bruit de valeur 3D en entiers, continu en coordonnées MONDE (docs/19 § 4.6).
//!
//! Les positions sont en mètres Q16. Le bruit n'a aucune notion de voxel : deux points voisins ont des
//! valeurs voisines, quel que soit le voxel qui les contient (c'est la garantie « pas de mosaïque »).

use em_core::hash::hash3;
use em_core::q16::{Q16, qlerp};

/// Position en mètres Q16 (x est, y haut, z nord).
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct WorldPoint([Q16; 3]);

impl WorldPoint {
    /// Convertit une position en millimètres (entiers) en mètres Q16 (arrondi vers moins l'infini).
    pub fn from_mm(mm: [i64; 3]) -> Self {
        let c = |v: i64| Q16::from_raw((v << 16).div_euclid(1_000));
        WorldPoint([c(mm[0]), c(mm[1]), c(mm[2])])
    }
    /// Les trois coordonnées en mètres Q16.
    pub const fn coords(self) -> [Q16; 3] {
        self.0
    }
}

/// Fréquences par axe, en cycles par mètre (Q16) : permet des bruits étirés (veines du bois, fissures d'écorce).
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Frequency([Q16; 3]);

impl Frequency {
    /// Même fréquence sur les trois axes.
    pub fn uniform(cycles_per_m: Q16) -> Self {
        Frequency([cycles_per_m; 3])
    }
    /// Fréquences distinctes par axe.
    pub fn per_axis(x: Q16, y: Q16, z: Q16) -> Self {
        Frequency([x, y, z])
    }
}

/// Lissage de Hermite de `t` dans [0, 65 535] : IDENTIQUE au bit près à `qsmoothstep(0, 65_536, t)`, sans la division
/// 128 bits de la rampe (`qramp(0, 1, t) = t`). Le maillage évalue des millions de voxels : c'est le point chaud.
fn lissage(t: i64) -> i64 {
    let t = i128::from(t);
    let t2 = (t * t) >> 16;
    ((t2 * (3 * 65_536 - 2 * t)) >> 16) as i64
}

/// Bruit de valeur gradué par une graine ; renvoie des valeurs dans [0, 1) en Q16.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct ValueNoise {
    seed: u64,
}

impl ValueNoise {
    /// Crée un bruit à partir d'une graine.
    pub const fn new(seed: u64) -> Self {
        ValueNoise { seed }
    }

    /// Valeur du réseau entier (0..65 535) au nœud donné.
    fn node(&self, x: i64, y: i64, z: i64) -> i64 {
        (hash3(self.seed, x, y, z) >> 48) as i64
    }

    /// Échantillon au point `p` pour la fréquence `f`, dans [0, 1].
    pub fn sample(&self, p: WorldPoint, f: Frequency) -> Q16 {
        let mut base = [0i64; 3];
        let mut lissee = [0i64; 3];
        for i in 0..3 {
            let g = p.0[i].mul(f.0[i]).raw();
            base[i] = g >> 16;
            lissee[i] = lissage(g & 0xFFFF);
        }
        let n = |dx: i64, dy: i64, dz: i64| self.node(base[0] + dx, base[1] + dy, base[2] + dz);
        let bas = |dy: i64, dz: i64| qlerp(n(0, dy, dz), n(1, dy, dz), lissee[0]);
        let plan = |dz: i64| qlerp(bas(0, dz), bas(1, dz), lissee[1]);
        Q16::from_raw(qlerp(plan(0), plan(1), lissee[2]))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn le_lissage_rapide_egale_qsmoothstep() {
        for t in 0..65_536_i64 {
            assert_eq!(lissage(t), em_core::q16::qsmoothstep(0, 65_536, t));
        }
    }

    #[test]
    fn dans_0_1_et_deterministe() {
        let b = ValueNoise::new(42);
        let f = Frequency::uniform(Q16::from_int(3));
        for i in -50..50 {
            let p = WorldPoint::from_mm([i * 137, i * -91, i * 53]);
            let v = b.sample(p, f);
            assert!((0..=65_536).contains(&v.raw()));
            assert_eq!(v, b.sample(p, f));
        }
    }

    #[test]
    fn continu_en_coordonnees_monde() {
        // un pas de 5 cm à 8 cycles/m ne change la valeur que d'une fraction bornée
        let b = ValueNoise::new(7);
        let f = Frequency::uniform(Q16::from_int(8));
        let mut pire = 0;
        for i in -400..400 {
            let a = b.sample(WorldPoint::from_mm([i * 50, 10, 20]), f).raw();
            let c = b.sample(WorldPoint::from_mm([(i + 1) * 50, 10, 20]), f).raw();
            pire = pire.max((a - c).abs());
        }
        // pente maximale du lissage ≈ 1,5 × fréquence × pas = 1,5 × 8 × 0,05 = 0,6 (de l'amplitude du nœud)
        assert!(pire < 40_000, "{pire}");
    }
}
