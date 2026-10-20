//! Brique 8³ à palette : l'unité de stockage creux (docs/19 § 3.1, docs/19a § 2.5).
//!
//! Forme canonique, donc égalité et empreinte indépendantes de l'historique des écritures :
//! une brique d'une seule valeur est `Uniform` (aucune allocation) ; sinon la palette est triée,
//! sans doublon, et le nombre de bits par indice est le plus petit de {1, 2, 4, 8} qui la contient ;
//! au-delà de 256 valeurs distinctes, la brique stocke les valeurs brutes sur 16 bits (palette vide).

use em_core::{Fnv64, LeReader, LeWriter, VoxelValue, voxel_index};

use crate::error::DecodeError;

/// Nombre de voxels d'une brique.
pub const BRICK_VOLUME: usize = 512;
/// Plus grande palette (indices sur 8 bits).
const PALETTE_MAX: usize = 256;

/// Brique 8³ de voxels. Le contenu est privé : on la construit par `uniform`, `from_dense` ou `decode`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Brick {
    repr: Repr,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Repr {
    /// Les 512 voxels ont la même valeur : rien n'est alloué.
    Uniform(VoxelValue),
    /// Palette et indices ; boîte pour que `Brick` ne pèse que 16 octets.
    Palette(Box<PaletteData>),
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct PaletteData {
    /// 1, 2, 4, 8 ou 16.
    bits: u8,
    /// Triée, sans doublon ; vide quand `bits == 16`.
    palette: Box<[VoxelValue]>,
    /// 512 indices de `bits` bits, bit de poids faible d'abord (16 bits : valeurs brutes petit-boutistes).
    indices: Box<[u8]>,
}

impl PaletteData {
    fn get(&self, i: usize) -> VoxelValue {
        match self.bits {
            16 => VoxelValue::from_raw(u16::from_le_bytes([self.indices[2 * i], self.indices[2 * i + 1]])),
            8 => self.palette[usize::from(self.indices[i])],
            b => {
                let pos = i * usize::from(b);
                let masque = (1_u8 << b) - 1;
                let idx = (self.indices[pos >> 3] >> (pos & 7)) & masque;
                self.palette[usize::from(idx)]
            }
        }
    }
}

/// Plus petit nombre de bits qui indexe `n` valeurs distinctes (n ≥ 2).
const fn bits_pour(n: usize) -> u8 {
    match n {
        0..=2 => 1,
        3..=4 => 2,
        5..=16 => 4,
        17..=PALETTE_MAX => 8,
        _ => 16,
    }
}

impl Brick {
    /// Brique dont les 512 voxels valent `v` (aucune allocation).
    pub const fn uniform(v: VoxelValue) -> Self {
        Self {
            repr: Repr::Uniform(v),
        }
    }

    /// Brique d'air.
    pub const fn air() -> Self {
        Self::uniform(VoxelValue::AIR)
    }

    /// Valeur unique si la brique est uniforme.
    pub fn is_uniform(&self) -> Option<VoxelValue> {
        match &self.repr {
            Repr::Uniform(v) => Some(*v),
            Repr::Palette(_) => None,
        }
    }

    /// Bits par indice : 0 (uniforme), 1, 2, 4, 8 ou 16.
    pub fn bits(&self) -> u8 {
        match &self.repr {
            Repr::Uniform(_) => 0,
            Repr::Palette(p) => p.bits,
        }
    }

    /// Palette triée (une seule valeur pour une brique uniforme ; vide à 16 bits).
    pub fn palette(&self) -> &[VoxelValue] {
        match &self.repr {
            Repr::Uniform(v) => std::slice::from_ref(v),
            Repr::Palette(p) => &p.palette,
        }
    }

    /// Indices empaquetés tels que stockés (bit de poids faible d'abord ; à 16 bits, valeurs brutes
    /// petit-boutistes) : vide pour une brique uniforme. Sert au téléversement GPU, qui recopie sans décoder.
    pub fn packed_indices(&self) -> &[u8] {
        match &self.repr {
            Repr::Uniform(_) => &[],
            Repr::Palette(p) => &p.indices,
        }
    }

    /// Octets alloués sur le tas par cette brique (0 si uniforme).
    pub fn heap_bytes(&self) -> usize {
        match &self.repr {
            Repr::Uniform(_) => 0,
            Repr::Palette(p) => {
                size_of::<PaletteData>() + p.palette.len() * size_of::<VoxelValue>() + p.indices.len()
            }
        }
    }

    /// Voxel d'indice dense `i` (`x + 8z + 64y`). Panique si `i >= 512`.
    pub fn get(&self, i: u16) -> VoxelValue {
        assert!(
            usize::from(i) < BRICK_VOLUME,
            "indice de voxel hors de la brique 8³"
        );
        match &self.repr {
            Repr::Uniform(v) => *v,
            Repr::Palette(p) => p.get(usize::from(i)),
        }
    }

    /// Voxel de coordonnées locales (chacune dans 0..8).
    pub fn get_xyz(&self, x: u32, y: u32, z: u32) -> VoxelValue {
        self.get(voxel_index(x, y, z))
    }

    /// Nouvelle brique identique, sauf le voxel `i` qui vaut `v`.
    pub fn with_voxel(&self, i: u16, v: VoxelValue) -> Self {
        if let Some(u) = self.is_uniform() {
            if u == v {
                return self.clone();
            }
        } else if self.get(i) == v {
            return self.clone();
        }
        let mut dense = [VoxelValue::AIR; BRICK_VOLUME];
        self.to_dense(&mut dense);
        dense[usize::from(i)] = v;
        Self::from_dense(&dense)
    }

    /// Construit la brique canonique d'un tableau dense (ordre x, puis z, puis y).
    pub fn from_dense(d: &[VoxelValue; BRICK_VOLUME]) -> Self {
        let premier = d[0];
        if d.iter().all(|&v| v == premier) {
            return Self::uniform(premier);
        }
        // Balayage rapide : au plus 16 valeurs distinctes retenues sans tri.
        let mut trouvees = [VoxelValue::AIR; 16];
        let mut n = 0_usize;
        let mut trop = false;
        for &v in d.iter() {
            if trouvees[..n].contains(&v) {
                continue;
            }
            if n == trouvees.len() {
                trop = true;
                break;
            }
            trouvees[n] = v;
            n += 1;
        }
        let palette: Vec<VoxelValue> = if trop {
            let mut bruts: Vec<u16> = d.iter().map(|v| v.raw()).collect();
            bruts.sort_unstable();
            bruts.dedup();
            bruts.into_iter().map(VoxelValue::from_raw).collect()
        } else {
            let mut p = trouvees[..n].to_vec();
            p.sort_unstable();
            p
        };
        let bits = bits_pour(palette.len());
        if bits == 16 {
            let mut indices = Vec::with_capacity(BRICK_VOLUME * 2);
            for v in d {
                indices.extend_from_slice(&v.raw().to_le_bytes());
            }
            return Self {
                repr: Repr::Palette(Box::new(PaletteData {
                    bits,
                    palette: Box::new([]),
                    indices: indices.into_boxed_slice(),
                })),
            };
        }
        let mut indices = vec![0_u8; BRICK_VOLUME * usize::from(bits) / 8];
        for (i, v) in d.iter().enumerate() {
            let idx = palette
                .binary_search(v)
                .unwrap_or_else(|_| unreachable!("valeur absente de sa palette"));
            if bits == 8 {
                indices[i] = idx as u8;
            } else {
                let pos = i * usize::from(bits);
                indices[pos >> 3] |= (idx as u8) << (pos & 7);
            }
        }
        Self {
            repr: Repr::Palette(Box::new(PaletteData {
                bits,
                palette: palette.into_boxed_slice(),
                indices: indices.into_boxed_slice(),
            })),
        }
    }

    /// Écrit les 512 voxels dans `out` (ordre x, z, y).
    pub fn to_dense(&self, out: &mut [VoxelValue; BRICK_VOLUME]) {
        match &self.repr {
            Repr::Uniform(v) => out.fill(*v),
            Repr::Palette(p) => {
                for (i, o) in out.iter_mut().enumerate() {
                    *o = p.get(i);
                }
            }
        }
    }

    /// Vrai si les 512 voxels sont de l'air (valeur exactement égale à `AIR`).
    pub fn is_air(&self) -> bool {
        self.is_uniform() == Some(VoxelValue::AIR)
    }

    /// Occupation : un mot de 64 bits par couche y, le bit `x + 8z` est 1 si le voxel n'est pas de l'air.
    pub fn occupancy(&self) -> [u64; 8] {
        match &self.repr {
            Repr::Uniform(v) => [if v.is_air() { 0 } else { u64::MAX }; 8],
            Repr::Palette(p) => {
                let mut mots = [0_u64; 8];
                for i in 0..BRICK_VOLUME {
                    if !p.get(i).is_air() {
                        mots[i >> 6] |= 1 << (i & 63);
                    }
                }
                mots
            }
        }
    }

    /// Nombre de voxels qui ne sont pas de l'air.
    pub fn non_air_count(&self) -> u32 {
        self.occupancy().iter().map(|m| m.count_ones()).sum()
    }

    /// Ajoute la brique à une empreinte FNV-1a, sur sa forme canonique (jamais sur une itération non ordonnée).
    pub fn fingerprint(&self, h: &mut Fnv64) {
        match &self.repr {
            Repr::Uniform(v) => {
                h.add(&[0]);
                h.add(&v.raw().to_le_bytes());
            }
            Repr::Palette(p) => {
                h.add(&[1, p.bits]);
                h.add(&(p.palette.len() as u16).to_le_bytes());
                for v in p.palette.iter() {
                    h.add(&v.raw().to_le_bytes());
                }
                h.add(&p.indices);
            }
        }
    }

    /// Écrit la brique au format EMBK (docs/19a § 2.5).
    pub fn encode(&self, w: &mut LeWriter) {
        match &self.repr {
            Repr::Uniform(v) => {
                w.u8(0).u16(v.raw());
            }
            Repr::Palette(p) => {
                w.u8(1).u8(p.bits).u16(p.palette.len() as u16);
                for v in p.palette.iter() {
                    w.u16(v.raw());
                }
                w.bytes(&p.indices);
            }
        }
    }

    /// Lit une brique EMBK. Refus fermé : tronquée, étiquette ou bits inconnus, indice hors palette.
    /// Une brique valide mais non canonique (palette en désordre, doublons) est normalisée.
    pub fn decode(r: &mut LeReader<'_>) -> Result<Self, DecodeError> {
        match r.u8()? {
            0 => Ok(Self::uniform(VoxelValue::from_raw(r.u16()?))),
            1 => {
                let bits = r.u8()?;
                if !matches!(bits, 1 | 2 | 4 | 8 | 16) {
                    return Err(DecodeError::BitsInvalides(bits));
                }
                let longueur = r.u16()?;
                let valide = if bits == 16 {
                    longueur == 0
                } else {
                    (1..=PALETTE_MAX as u16).contains(&longueur)
                };
                if !valide {
                    return Err(DecodeError::PaletteInvalide { bits, longueur });
                }
                let mut palette = Vec::with_capacity(usize::from(longueur));
                for _ in 0..longueur {
                    palette.push(VoxelValue::from_raw(r.u16()?));
                }
                let octets = r.bytes(BRICK_VOLUME * usize::from(bits) / 8)?;
                let mut dense = [VoxelValue::AIR; BRICK_VOLUME];
                for (i, o) in dense.iter_mut().enumerate() {
                    let idx = match bits {
                        16 => {
                            *o = VoxelValue::from_raw(u16::from_le_bytes([octets[2 * i], octets[2 * i + 1]]));
                            continue;
                        }
                        8 => u16::from(octets[i]),
                        b => {
                            let pos = i * usize::from(b);
                            u16::from((octets[pos >> 3] >> (pos & 7)) & ((1_u8 << b) - 1))
                        }
                    };
                    *o = *palette
                        .get(usize::from(idx))
                        .ok_or(DecodeError::IndiceHorsPalette {
                            indice: idx,
                            longueur,
                        })?;
                }
                Ok(Self::from_dense(&dense))
            }
            autre => Err(DecodeError::EtiquetteInconnue(autre)),
        }
    }
}

impl Default for Brick {
    fn default() -> Self {
        Self::air()
    }
}
