//! Le hasard du générateur de maison de Monsieur (`nouvelle référence.html`), porté EXACTEMENT en entiers :
//! `mul` (mulberry32), `hs` (hachage d'une chaîne) et `hh` (hachage de quatre entiers). Ces trois fonctions sont
//! la sémantique du JavaScript (`Math.imul`, `|0`, `>>>`), reproduite avec `wrapping_mul` ; aucun flottant : les
//! tirages « `R() * n` » et « `R() < p` » deviennent des produits et des comparaisons d'entiers.

/// Mulberry32 : `mul(seed)` du JavaScript. Chaque appel à `next_u32` est un `R() * 2^32`.
#[derive(Clone, Debug)]
pub struct JsRng {
    etat: i32,
}

impl JsRng {
    /// `mul(a)`.
    pub const fn new(a: u32) -> Self {
        Self { etat: a as i32 }
    }

    /// Prochain tirage, entier de 32 bits : `R()` vaut `n / 2^32`.
    pub fn next_u32(&mut self) -> u32 {
        self.etat = self.etat.wrapping_add(0x6D2B_79F5);
        let a = self.etat;
        let mut t = (a ^ (((a as u32) >> 15) as i32)).wrapping_mul(1 | a);
        let u = (t ^ (((t as u32) >> 7) as i32)).wrapping_mul(61 | t);
        t = t.wrapping_add(u) ^ t;
        // `(t ^ t >>> 14) >>> 0`
        (t ^ (((t as u32) >> 14) as i32)) as u32
    }

    /// `Math.floor(R() * n)`.
    pub fn below(&mut self, n: u32) -> u32 {
        ((u64::from(self.next_u32()) * u64::from(n)) >> 32) as u32
    }

    /// `R() < pourcent / 100`.
    pub fn percent(&mut self, pourcent: u32) -> bool {
        u64::from(self.next_u32()) * 100 < u64::from(pourcent) << 32
    }

    /// `R() < 0.5`.
    pub fn half(&mut self) -> bool {
        self.next_u32() < (1 << 31)
    }

    /// `Math.floor(a + R() * (b - a + 0.999))` : l'entier `i(a, b)` de `derive`, calculé sans flottant.
    pub fn int(&mut self, a: i32, b: i32) -> i32 {
        let n = u128::from(self.next_u32());
        let etendue = (i128::from(b) - i128::from(a)) * 1000 + 999;
        let q = (n as i128 * etendue) / (1000_i128 << 32);
        a + q as i32
    }

    /// `+(a + R() * (b - a)).toFixed(2)` en centièmes (`a` et `b` en centièmes).
    pub fn hundredths(&mut self, a: i32, b: i32) -> i32 {
        let n = i64::from(self.next_u32());
        a + (((n * i64::from(b - a)) + (1 << 31)) >> 32) as i32
    }

    /// Un élément de la liste (`pc` : `a[i(0, len - 1)]`).
    pub fn pick<T: Copy>(&mut self, liste: &[T]) -> T {
        let i = self.int(0, liste.len() as i32 - 1) as usize;
        liste[i]
    }
}

/// `hs(s)` : hachage 32 bits d'une chaîne (unités UTF-16, comme `charCodeAt`).
pub fn hs(s: &str) -> u32 {
    let longueur = s.encode_utf16().count() as u32;
    let mut h: i32 = (1_779_033_703_u32 ^ longueur) as i32;
    for c in s.encode_utf16() {
        h = (h ^ i32::from(c)).wrapping_mul(3_432_918_353_u32 as i32);
        h = (h as u32).rotate_left(13) as i32;
    }
    h as u32
}

/// `hh(a, b, c, d)` : hachage de quatre entiers, `u32` (le JavaScript le divise par 2^32).
pub fn hh(a: i32, b: i32, c: i32, d: i32) -> u32 {
    let mut h = a.wrapping_mul(374_761_393)
        ^ b.wrapping_mul(668_265_263)
        ^ c.wrapping_mul(1_274_126_177)
        ^ d.wrapping_mul(2_246_822_519_u32 as i32);
    h = (h ^ ((h as u32) >> 15) as i32).wrapping_mul(2_246_822_519_u32 as i32);
    h = (h ^ ((h as u32) >> 13) as i32).wrapping_mul(3_266_489_917_u32 as i32);
    h ^= ((h as u32) >> 16) as i32;
    h as u32
}

/// `hh(a, b, c) < pourcent / 100`.
pub fn hh_lt(h: u32, pourcent: u32) -> bool {
    u64::from(h) * 100 < u64::from(pourcent) << 32
}

/// `Math.floor(hh(...) * n)`.
pub fn hh_below(h: u32, n: u32) -> u32 {
    ((u64::from(h) * u64::from(n)) >> 32) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hs_et_mulberry_valent_le_javascript() {
        // valeurs de référence calculées avec node (voir tools/maisons/ref_parite.mjs)
        assert_eq!(hs("gravit"), HS_GRAVIT);
        let mut r = JsRng::new(hs("gravit"));
        assert_eq!(r.next_u32(), R_GRAVIT[0]);
        assert_eq!(r.next_u32(), R_GRAVIT[1]);
        assert_eq!(hh(1, 2, 3, 4), HH_1234);
        assert_eq!(hh(-7, 100, 0, 3), HH_NEG);
    }

    const HS_GRAVIT: u32 = 1_395_179_722;
    const R_GRAVIT: [u32; 2] = [1_618_334_632, 346_990_434];
    const HH_1234: u32 = 2_573_771_039;
    const HH_NEG: u32 = 3_419_327_764;
}
