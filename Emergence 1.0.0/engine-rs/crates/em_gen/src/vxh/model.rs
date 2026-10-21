//! `VxhModel` : une maison `.vxh` chargée, immuable.
//!
//! Format (README_TECHNIQUE § 3 du générateur) : `VXH1`, `nx ny nz` (u32), `voxel_m` (f32 = 0,05), `ground_layers`
//! (u32), 8 octets réservés, puis un flux zlib de `[u16 x N couleurs RGB565][u8 x N matériau][u8 x N drapeaux]`.
//! Index : `i = (y * nz + z) * nx + x`. Couleur 0 = vide. Invariant : couleur != 0 <=> matériau != 0.

use std::io::Read;
use std::path::Path;

use em_core::Fnv64;
use flate2::read::ZlibDecoder;

use crate::error::{GenError, VxhError};

const SIGNATURE: &[u8; 4] = b"VXH1";
const ENTETE: usize = 32;
/// Dimension maximale par axe (la plus grande maison cuite mesure environ 330).
pub const DIM_MAX: u32 = 1024;
/// Nombre maximal de cellules : 2^25 (33 millions, 134 Mo denses) ; au-delà, refusé (bombe de décompression).
pub const CELLULES_MAX: u64 = 1 << 25;
/// Bits de drapeaux connus (émissif, verre, intérieur, mou).
const DRAPEAUX_CONNUS: u8 = 0x0F;

/// Matériau du générateur de maisons (plan `MT`).
#[derive(Copy, Clone, Debug, PartialEq, Eq, Hash)]
pub enum VxhMaterial {
    /// Pierre ou métal (le fer se reconnaît à sa teinte sombre et neutre).
    Stone = 1,
    /// Bois.
    Wood = 2,
    /// Plâtre.
    Plaster = 3,
    /// Végétal ou sol.
    Ground = 4,
    /// Toit.
    Roof = 5,
}

impl VxhMaterial {
    /// Décode un code 1..=5.
    pub const fn from_code(code: u8) -> Option<Self> {
        match code {
            1 => Some(Self::Stone),
            2 => Some(Self::Wood),
            3 => Some(Self::Plaster),
            4 => Some(Self::Ground),
            5 => Some(Self::Roof),
            _ => None,
        }
    }

    /// Code du fichier.
    pub const fn code(self) -> u8 {
        self as u8
    }
}

/// Drapeaux d'une cellule.
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq)]
pub struct VxhFlags(u8);

impl VxhFlags {
    /// Émissif (braises, lampes, lanterne).
    pub const EMISSIVE: u8 = 1;
    /// Verre.
    pub const GLASS: u8 = 2;
    /// Face intérieure (voxel adjacent à un volume habité).
    pub const INTERIOR: u8 = 4;
    /// « Mou » : herbe et fleurs, sans collision.
    pub const SOFT: u8 = 8;

    /// Construit depuis l'octet du fichier ; refuse les bits inconnus.
    pub const fn from_bits(bits: u8) -> Option<Self> {
        if bits & !DRAPEAUX_CONNUS == 0 {
            Some(Self(bits))
        } else {
            None
        }
    }

    /// L'octet.
    pub const fn bits(self) -> u8 {
        self.0
    }

    /// Émissif ?
    pub const fn emissive(self) -> bool {
        self.0 & Self::EMISSIVE != 0
    }

    /// Verre ?
    pub const fn glass(self) -> bool {
        self.0 & Self::GLASS != 0
    }

    /// Face intérieure ?
    pub const fn interior(self) -> bool {
        self.0 & Self::INTERIOR != 0
    }

    /// Mou (herbe, fleurs) ?
    pub const fn soft(self) -> bool {
        self.0 & Self::SOFT != 0
    }
}

/// Une cellule pleine de la maison.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct VxhCell {
    color565: u16,
    material: VxhMaterial,
    flags: VxhFlags,
}

impl VxhCell {
    /// Assemble une cellule ; la couleur doit être non nulle (0 = vide).
    pub const fn new(color565: u16, material: VxhMaterial, flags: VxhFlags) -> Option<Self> {
        if color565 == 0 {
            None
        } else {
            Some(Self {
                color565,
                material,
                flags,
            })
        }
    }

    /// Couleur RGB565 telle que le générateur l'a écrite.
    pub const fn color565(&self) -> u16 {
        self.color565
    }

    /// Couleur sRGB8 : chaque canal est étendu en recopiant ses bits de poids fort (5 -> 8 et 6 -> 8 bits).
    pub const fn rgb8(&self) -> [u8; 3] {
        let c = self.color565;
        let (r5, g6, b5) = ((c >> 11) as u8, ((c >> 5) & 63) as u8, (c & 31) as u8);
        [r5 << 3 | r5 >> 2, g6 << 2 | g6 >> 4, b5 << 3 | b5 >> 2]
    }

    /// Matériau du générateur.
    pub const fn material(&self) -> VxhMaterial {
        self.material
    }

    /// Drapeaux.
    pub const fn flags(&self) -> VxhFlags {
        self.flags
    }
}

/// Une maison chargée (grille dense), immuable.
pub struct VxhModel {
    nx: u32,
    ny: u32,
    nz: u32,
    ground_layers: u32,
    colors: Vec<u16>,
    materials: Vec<u8>,
    flags: Vec<u8>,
    solid: usize,
    file_bytes: usize,
}

impl std::fmt::Debug for VxhModel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("VxhModel")
            .field("dims", &[self.nx, self.ny, self.nz])
            .field("voxels", &self.solid)
            .finish()
    }
}

fn u32_le(o: &[u8], debut: usize) -> u32 {
    u32::from_le_bytes([o[debut], o[debut + 1], o[debut + 2], o[debut + 3]])
}

impl VxhModel {
    /// Charge un fichier `.vxh` ; refuse tout fichier douteux (voir `VxhError`).
    pub fn load(path: &Path) -> Result<Self, GenError> {
        let octets = std::fs::read(path).map_err(|source| GenError::Io {
            chemin: path.to_owned(),
            source,
        })?;
        Self::from_bytes(&octets).map_err(|source| GenError::Vxh {
            chemin: path.to_owned(),
            source,
        })
    }

    /// Décode des octets `.vxh` déjà en mémoire.
    pub fn from_bytes(octets: &[u8]) -> Result<Self, VxhError> {
        if octets.len() < ENTETE {
            return Err(VxhError::TropCourt(octets.len()));
        }
        if &octets[..4] != SIGNATURE {
            return Err(VxhError::Signature);
        }
        let (nx, ny, nz) = (u32_le(octets, 4), u32_le(octets, 8), u32_le(octets, 12));
        for (axe, valeur) in [('x', nx), ('y', ny), ('z', nz)] {
            if valeur == 0 || valeur > DIM_MAX {
                return Err(VxhError::Dimension {
                    axe,
                    valeur,
                    max: DIM_MAX,
                });
            }
        }
        let cellules = u64::from(nx) * u64::from(ny) * u64::from(nz);
        if cellules > CELLULES_MAX {
            return Err(VxhError::TropDeCellules(cellules));
        }
        let voxel_bits = u32_le(octets, 16);
        if voxel_bits != 0.05_f32.to_bits() {
            return Err(VxhError::VoxelHorsGrille(voxel_bits));
        }
        let ground_layers = u32_le(octets, 20);
        if ground_layers > ny {
            return Err(VxhError::SolHorsGrille {
                couches: ground_layers,
                ny,
            });
        }
        if octets[24..ENTETE].iter().any(|&b| b != 0) {
            return Err(VxhError::ReservesNonNuls);
        }
        // Lecture bornée : jamais plus d'octets que ne l'impose la grille (+1 pour détecter l'excès).
        let attendu = cellules * 4;
        let mut corps = Vec::new();
        ZlibDecoder::new(&octets[ENTETE..])
            .take(attendu + 1)
            .read_to_end(&mut corps)
            .map_err(|e| VxhError::CorpsZlib(e.to_string()))?;
        if corps.len() as u64 != attendu {
            return Err(VxhError::CorpsTaille {
                lu: corps.len() as u64,
                attendu,
            });
        }
        let n = cellules as usize;
        let colors: Vec<u16> = corps[..2 * n]
            .as_chunks::<2>()
            .0
            .iter()
            .map(|b| u16::from_le_bytes(*b))
            .collect();
        let materials = corps[2 * n..3 * n].to_vec();
        let flags = corps[3 * n..].to_vec();
        let mut solid = 0_usize;
        for i in 0..n {
            let (c, m, f) = (colors[i], materials[i], flags[i]);
            if m > 5 {
                return Err(VxhError::MateriauInvalide {
                    index: i,
                    materiau: m,
                });
            }
            if (c != 0) != (m != 0) {
                return Err(VxhError::Invariant {
                    index: i,
                    couleur: c,
                    materiau: m,
                });
            }
            // Le verre peut être « vide » (README § 6) ; tout autre drapeau exige une cellule pleine.
            let sur_vide_permis = f & !VxhFlags::GLASS == 0;
            if f & !DRAPEAUX_CONNUS != 0 || (c == 0 && !sur_vide_permis) {
                return Err(VxhError::DrapeauxInvalides {
                    index: i,
                    drapeaux: f,
                });
            }
            solid += usize::from(c != 0);
        }
        Ok(Self {
            nx,
            ny,
            nz,
            ground_layers,
            colors,
            materials,
            flags,
            solid,
            file_bytes: octets.len(),
        })
    }

    /// Dimensions (x, y, z) en voxels.
    pub const fn dims(&self) -> [u32; 3] {
        [self.nx, self.ny, self.nz]
    }

    /// Couches de sol : l'herbe est en `y = ground_layers - 1`, le niveau 0 des murs commence à `y = ground_layers`.
    pub const fn ground_layers(&self) -> u32 {
        self.ground_layers
    }

    /// Nombre de voxels pleins.
    pub const fn voxel_count(&self) -> usize {
        self.solid
    }

    /// Taille du fichier lu, en octets.
    pub const fn file_bytes(&self) -> usize {
        self.file_bytes
    }

    fn index(&self, x: u32, y: u32, z: u32) -> usize {
        (y as usize * self.nz as usize + z as usize) * self.nx as usize + x as usize
    }

    /// Cellule pleine en `(x, y, z)` de la grille, `None` si vide ou hors grille.
    pub fn cell(&self, x: i64, y: i64, z: i64) -> Option<VxhCell> {
        let dedans = |v: i64, n: u32| (0..i64::from(n)).contains(&v);
        if !(dedans(x, self.nx) && dedans(y, self.ny) && dedans(z, self.nz)) {
            return None;
        }
        let i = self.index(x as u32, y as u32, z as u32);
        let material = VxhMaterial::from_code(self.materials[i])?;
        Some(VxhCell {
            color565: self.colors[i],
            material,
            flags: VxhFlags(self.flags[i]),
        })
    }

    /// Vrai si la cellule est du verre (même vide : le plan du verre peut être vide).
    pub fn is_glass(&self, x: i64, y: i64, z: i64) -> bool {
        let dedans = |v: i64, n: u32| (0..i64::from(n)).contains(&v);
        dedans(x, self.nx)
            && dedans(y, self.ny)
            && dedans(z, self.nz)
            && self.flags[self.index(x as u32, y as u32, z as u32)] & VxhFlags::GLASS != 0
    }

    /// Empreinte du contenu (couleurs, matériaux, drapeaux, dimensions).
    pub fn fingerprint(&self) -> u64 {
        let mut h = Fnv64::new();
        for d in [self.nx, self.ny, self.nz, self.ground_layers] {
            h.add_u64(u64::from(d));
        }
        for c in &self.colors {
            h.add(&c.to_le_bytes());
        }
        h.add(&self.materials);
        h.add(&self.flags);
        h.value()
    }
}
