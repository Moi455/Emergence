//! Empaquetage d'une brique et d'un chunk au format GPU (docs/19a § 5.1). Fonctions pures, sans GPU, donc
//! testables : `decode_voxel` est le miroir CPU exact de la lecture du shader.

use super::alloc::{MOTS_PAR_CLASSE, classe_de_bits};
use super::gpu::{BIT_EDITE, BIT_UNIFORME, ENTREE_VIDE};
use em_core::VoxelValue;
use em_voxel::Brick;

/// Une brique prête à être écrite sur le GPU.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PackedBrick {
    /// Brique d'air : entrée vide, rien d'alloué.
    Empty,
    /// Brique pleine d'une seule valeur : entrée uniforme, rien d'alloué.
    Uniform(VoxelValue),
    /// Brique à palette : masque d'occupation, métadonnées et mots du tas.
    Palette {
        /// Masque d'occupation de 512 bits (16 mots), voxel `i = x + 8z + 64y` au bit `i`.
        occupancy: [u32; 16],
        /// Bits par indice : 1, 2, 4, 8 ou 16.
        bits: u8,
        /// Mots du tas : palette (deux `u16` par mot) puis indices, ou valeurs brutes à 16 bits.
        words: Vec<u32>,
        /// Longueur de la palette (0 à 16 bits).
        palette_len: u16,
    },
}

/// Mots réservés à la palette dans la classe de taille de ce nombre de bits (les indices suivent).
pub const fn mots_de_palette(bits: u8) -> u32 {
    match bits {
        1 => 2,
        2 => 2,
        4 => 8,
        8 => 128,
        _ => 0,
    }
}

impl PackedBrick {
    /// Empaquette une brique du CPU, sans la décoder : la palette et les indices sont recopiés.
    pub fn from_brick(b: &Brick) -> Self {
        if let Some(v) = b.is_uniform() {
            return if v.is_air() { Self::Empty } else { Self::Uniform(v) };
        }
        let bits = b.bits();
        let occ64 = b.occupancy();
        let mut occupancy = [0_u32; 16];
        for (i, m) in occ64.iter().enumerate() {
            occupancy[2 * i] = *m as u32;
            occupancy[2 * i + 1] = (*m >> 32) as u32;
        }
        let taille = MOTS_PAR_CLASSE[classe_de_bits(bits)] as usize;
        let mut words = vec![0_u32; taille];
        let pal = b.palette();
        let debut_indices = mots_de_palette(bits) as usize;
        for (i, v) in pal.iter().enumerate() {
            words[i / 2] |= u32::from(v.raw()) << (16 * (i % 2));
        }
        for (k, octet) in b.packed_indices().iter().enumerate() {
            words[debut_indices + k / 4] |= u32::from(*octet) << (8 * (k % 4));
        }
        Self::Palette {
            occupancy,
            bits,
            words,
            palette_len: pal.len() as u16,
        }
    }

    /// Entrée de brique de la table du chunk (hors case de brique, que l'allocation attribue).
    pub fn entree_sans_case(&self, edite: bool) -> u32 {
        let e = if edite { BIT_EDITE } else { 0 };
        match self {
            Self::Empty => ENTREE_VIDE,
            Self::Uniform(v) => BIT_UNIFORME | e | u32::from(v.raw()),
            Self::Palette { .. } => e,
        }
    }

    /// Mot 1 de `brick_meta` : `log2(bits)` dans les bits 0-3, `palette_len - 1` dans les bits 8-15.
    pub fn meta1(&self) -> u32 {
        match self {
            Self::Palette {
                bits, palette_len, ..
            } => {
                let log2 = bits.trailing_zeros();
                let pl = if *bits == 16 {
                    0
                } else {
                    u32::from(*palette_len).saturating_sub(1)
                };
                log2 | (pl << 8)
            }
            _ => 0,
        }
    }
}

/// Miroir CPU de la lecture du shader : voxel `i` (0..512) d'une brique à palette, depuis ses mots.
pub fn decode_voxel(bits: u8, words: &[u32], i: u32) -> u16 {
    if bits == 16 {
        let w = words[(i >> 1) as usize];
        return ((w >> ((i & 1) * 16)) & 0xFFFF) as u16;
    }
    let pos = i * u32::from(bits);
    let w = words[(mots_de_palette(bits) + (pos >> 5)) as usize];
    let masque = (1_u32 << bits) - 1;
    let idx = (w >> (pos & 31)) & masque;
    let pw = words[(idx >> 1) as usize];
    ((pw >> ((idx & 1) * 16)) & 0xFFFF) as u16
}

#[cfg(test)]
mod tests {
    use super::*;
    use em_core::MaterialId;
    use em_voxel::BRICK_VOLUME;

    fn v(m: u16, t: u8) -> VoxelValue {
        VoxelValue::new(MaterialId::new(m), t)
    }

    fn brique_de(n_valeurs: usize) -> Brick {
        let mut d = [VoxelValue::AIR; BRICK_VOLUME];
        for (i, x) in d.iter_mut().enumerate() {
            let k = (i * 7 + i / 5) % n_valeurs;
            *x = if k == 0 {
                VoxelValue::AIR
            } else {
                v(30 + (k as u16 % 100), (k % 100) as u8)
            };
        }
        Brick::from_dense(&d)
    }

    #[test]
    fn le_decodage_cpu_retrouve_chaque_voxel_a_toutes_les_largeurs() {
        for n in [2_usize, 3, 4, 9, 16, 17, 200, 256, 300] {
            let b = brique_de(n);
            let PackedBrick::Palette {
                bits,
                words,
                occupancy,
                ..
            } = PackedBrick::from_brick(&b)
            else {
                panic!("brique à palette attendue pour {n} valeurs");
            };
            assert_eq!(words.len() as u32, MOTS_PAR_CLASSE[classe_de_bits(bits)]);
            for i in 0..512_u32 {
                assert_eq!(
                    decode_voxel(bits, &words, i),
                    b.get(i as u16).raw(),
                    "n={n} bits={bits} i={i}"
                );
                let occ = (occupancy[(i >> 5) as usize] >> (i & 31)) & 1;
                assert_eq!(occ == 1, !b.get(i as u16).is_air(), "occupation n={n} i={i}");
            }
        }
    }

    #[test]
    fn les_briques_uniformes_n_allouent_rien() {
        assert_eq!(PackedBrick::from_brick(&Brick::air()), PackedBrick::Empty);
        let b = Brick::uniform(v(1, 3));
        let p = PackedBrick::from_brick(&b);
        assert_eq!(p, PackedBrick::Uniform(v(1, 3)));
        let e = p.entree_sans_case(false);
        assert_eq!(e & BIT_UNIFORME, BIT_UNIFORME);
        assert_ne!(e, ENTREE_VIDE);
        assert_eq!(e & 0xFFFF, u32::from(v(1, 3).raw()));
    }

    #[test]
    fn la_meta_porte_le_log2_et_la_longueur_de_palette() {
        let p = PackedBrick::from_brick(&brique_de(3));
        let PackedBrick::Palette {
            bits, palette_len, ..
        } = p.clone()
        else {
            panic!()
        };
        assert_eq!((bits, palette_len), (2, 3));
        assert_eq!(p.meta1(), 1 | (2 << 8));
    }
}
