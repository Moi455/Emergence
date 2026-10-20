//! Lecture stricte du format `.vxm` v1 (docs/19a § 1), miroir de `tools/vegetation/read_vxm.py` : signature,
//! CRC32, version, drapeaux, en-tête JSON, sections de LOD (réservés, boîte, taille du corps, zlib, bornes,
//! sortes, rampes, ordre (y, z, x) strict), aucun octet en trop.

use std::io::Read;

use em_core::{LeReader, crc32};
use flate2::read::ZlibDecoder;

use super::kind::VxmKind;
use super::layer::{Cell, LodLayer};
use super::meta::VxmMeta;
use crate::error::VxmError;

const SIGNATURE: &[u8; 4] = b"VXM1";
const DRAPEAU_ZLIB: u16 = 1;
const DRAPEAU_CIEL: u16 = 2;
const DRAPEAU_PALETTE: u16 = 4;
/// Plus de voxels par niveau que cela : refusé (garde-fou contre une bombe de décompression).
const MAX_VOXELS_PAR_NIVEAU: u64 = 1 << 25;
/// Dimension maximale d'une boîte : les coordonnées relatives tiennent sur 16 bits.
const MAX_DIM: u32 = 1 << 16;
/// Valeur absolue maximale du coin d'une boîte (bien au-delà de tout arbre, sans risque de débordement).
const MAX_COIN: i32 = 1 << 20;

/// Résultat du décodage : drapeaux, en-tête, et les sections du fichier (niveau, couche) dans l'ordre.
pub(super) struct Decoded {
    pub flags: u16,
    pub meta: VxmMeta,
    pub layers: Vec<LodLayer>,
}

fn tronque<T>(r: Result<T, em_core::IoError>) -> Result<T, VxmError> {
    r.map_err(|_| VxmError::Tronque)
}

/// Décode un fichier `.vxm` entier.
pub(super) fn decode(data: &[u8]) -> Result<Decoded, VxmError> {
    if data.len() < 16 {
        return Err(VxmError::TropCourt(data.len()));
    }
    if &data[..4] != SIGNATURE {
        return Err(VxmError::Signature);
    }
    let (corps, pied) = data.split_at(data.len() - 4);
    let attendu = u32::from_le_bytes([pied[0], pied[1], pied[2], pied[3]]);
    let calcule = crc32(corps);
    if attendu != calcule {
        return Err(VxmError::Crc { attendu, calcule });
    }
    let mut r = LeReader::new(corps);
    tronque(r.bytes(4))?;
    let version = tronque(r.u16())?;
    if version != 1 {
        return Err(VxmError::VersionNonGeree(version));
    }
    let flags = tronque(r.u16())?;
    let inconnus = flags & !(DRAPEAU_ZLIB | DRAPEAU_CIEL | DRAPEAU_PALETTE);
    if inconnus != 0 {
        return Err(VxmError::DrapeauxInconnus(inconnus));
    }
    let json_len = tronque(r.u32())? as usize;
    let json = tronque(r.bytes(json_len))?;
    let meta = VxmMeta::parse(json, flags & DRAPEAU_PALETTE != 0)?;

    let mut layers = Vec::with_capacity(meta.lods().len());
    for &attendu in meta.lods() {
        layers.push(section(&mut r, flags, &meta, attendu)?);
    }
    if !r.is_finished() {
        return Err(VxmError::OctetsEnTrop(r.remaining()));
    }
    Ok(Decoded { flags, meta, layers })
}

/// Lit une section de LOD.
fn section(r: &mut LeReader<'_>, flags: u16, meta: &VxmMeta, attendu: u8) -> Result<LodLayer, VxmError> {
    let lod = tronque(r.u8())?;
    if tronque(r.bytes(3))? != [0, 0, 0] {
        return Err(VxmError::ReservesNonNuls(lod));
    }
    let min = [tronque(r.i32())?, tronque(r.i32())?, tronque(r.i32())?];
    let dims = [tronque(r.u32())?, tronque(r.u32())?, tronque(r.u32())?];
    let count = u64::from(tronque(r.u32())?);
    let body_len = tronque(r.u32())? as usize;
    if lod != attendu {
        return Err(VxmError::LodInattendu { lu: lod, attendu });
    }
    let corps_brut = tronque(r.bytes(body_len))?;
    // Un niveau vide (count = 0) est permis : le modèle le dérive du niveau plus fin.
    if count > 0 {
        validate_box(lod, min, dims, count)?;
    }

    let par_voxel = 8 + u64::from(flags & DRAPEAU_PALETTE != 0) + u64::from(flags & DRAPEAU_CIEL != 0);
    let attendu_octets = count * par_voxel;
    let corps: Vec<u8> = if flags & DRAPEAU_ZLIB != 0 {
        let mut sortie = Vec::new();
        ZlibDecoder::new(corps_brut)
            .take(attendu_octets + 1)
            .read_to_end(&mut sortie)
            .map_err(|e| VxmError::CorpsZlib {
                lod,
                raison: e.to_string(),
            })?;
        sortie
    } else {
        corps_brut.to_vec()
    };
    if corps.len() as u64 != attendu_octets {
        return Err(VxmError::CorpsTaille {
            lod,
            lu: corps.len() as u64,
            attendu: attendu_octets,
        });
    }
    let n = count as usize;
    let u16s = |debut: usize| -> Vec<u16> {
        corps[debut..debut + 2 * n]
            .as_chunks::<2>()
            .0
            .iter()
            .map(|b| u16::from_le_bytes(*b))
            .collect()
    };
    let (xs, ys, zs) = (u16s(0), u16s(2 * n), u16s(4 * n));
    let sortes = &corps[6 * n..7 * n];
    let rampes = &corps[7 * n..8 * n];

    let mut cells = Vec::with_capacity(n);
    let mut precedent: Option<(u16, u16, u16)> = None;
    for i in 0..n {
        let (x, y, z) = (xs[i], ys[i], zs[i]);
        for (axe, v, d) in [('x', x, dims[0]), ('y', y, dims[1]), ('z', z, dims[2])] {
            if u32::from(v) >= d {
                return Err(VxmError::CoordHorsBoite { lod, axe });
            }
        }
        let kind = VxmKind::from_code(sortes[i]).ok_or(VxmError::SorteInvalide {
            lod,
            sorte: sortes[i],
        })?;
        let rampe = rampes[i];
        if usize::from(rampe) >= meta.ramps().len() {
            return Err(VxmError::RampeHorsEnTete { lod, rampe });
        }
        // ordre (y, z, x) strictement croissant : trié et chaque cellule une seule fois
        if precedent.is_some_and(|p| p >= (y, z, x)) {
            return Err(VxmError::Ordre { lod, index: i });
        }
        precedent = Some((y, z, x));
        cells.push(Cell {
            x,
            y,
            z,
            kind,
            variant: meta.tint_variant(kind, rampe)?,
        });
    }
    let dims = if n == 0 { [0; 3] } else { dims };
    Ok(LodLayer::from_file(lod, min, dims, cells))
}

/// Vérifie la boîte annoncée : dimensions non nulles et bornées, coin raisonnable, nombre de voxels compatible.
fn validate_box(lod: u8, min: [i32; 3], dims: [u32; 3], count: u64) -> Result<(), VxmError> {
    let refus = |raison: &str| {
        Err(VxmError::BoiteInvalide {
            lod,
            raison: raison.to_owned(),
        })
    };
    if dims.iter().any(|&d| d == 0 || d > MAX_DIM) {
        return refus("dimension nulle ou supérieure à 65 536");
    }
    if min.iter().any(|&m| m.unsigned_abs() > MAX_COIN as u32) {
        return refus("coin hors de ±2^20");
    }
    let volume: u64 = dims.iter().map(|&d| u64::from(d)).product();
    if count > volume {
        return refus("plus de voxels que de cellules dans la boîte");
    }
    if count > MAX_VOXELS_PAR_NIVEAU {
        return refus("plus de 2^25 voxels dans un niveau");
    }
    Ok(())
}
