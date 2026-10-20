//! Empreintes entières identiques à `engine/ops/src/digest.cpp` : CRC-32 (IEEE, réfléchi) et FNV-1a 64 bits.

/// Table du CRC-32 (polynôme 0xEDB88320), calculée à la compilation.
const TABLE_CRC: [u32; 256] = construire_table();

const fn construire_table() -> [u32; 256] {
    let mut t = [0_u32; 256];
    let mut i = 0;
    while i < 256 {
        let mut c = i as u32;
        let mut k = 0;
        while k < 8 {
            c = if c & 1 != 0 {
                0xEDB8_8320 ^ (c >> 1)
            } else {
                c >> 1
            };
            k += 1;
        }
        t[i] = c;
        i += 1;
    }
    t
}

/// CRC-32 (même valeur que le `crc32()` de zlib).
pub fn crc32(bytes: &[u8]) -> u32 {
    let mut c = 0xFFFF_FFFF_u32;
    for &b in bytes {
        c = TABLE_CRC[((c ^ u32::from(b)) & 0xFF) as usize] ^ (c >> 8);
    }
    c ^ 0xFFFF_FFFF
}

/// FNV-1a 64 bits, incrémental.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Fnv64 {
    h: u64,
}

impl Fnv64 {
    const BASE: u64 = 0xcbf2_9ce4_8422_2325;
    const PREMIER: u64 = 0x0000_0100_0000_01b3;

    /// Démarre depuis la base FNV.
    pub const fn new() -> Self {
        Self { h: Self::BASE }
    }
    /// Reprend depuis un état obtenu par `value()`.
    pub const fn resume(etat: u64) -> Self {
        Self { h: etat }
    }
    /// Ajoute des octets.
    pub fn add(&mut self, b: &[u8]) {
        for &o in b {
            self.h ^= u64::from(o);
            self.h = self.h.wrapping_mul(Self::PREMIER);
        }
    }
    /// Ajoute un `u64` en huit octets petit-boutistes.
    pub fn add_u64(&mut self, v: u64) {
        self.add(&v.to_le_bytes());
    }
    /// Valeur courante de l'empreinte.
    pub const fn value(&self) -> u64 {
        self.h
    }
}

impl Default for Fnv64 {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc32_verification_classique() {
        assert_eq!(crc32(b"123456789"), 0xCBF4_3926);
        assert_eq!(crc32(b""), 0);
    }

    #[test]
    fn fnv_reprise_equivaut_a_continuer() {
        let mut a = Fnv64::new();
        a.add(b"abc");
        let mut b = Fnv64::resume(a.value());
        b.add_u64(5);
        a.add_u64(5);
        assert_eq!(a, b);
    }
}
