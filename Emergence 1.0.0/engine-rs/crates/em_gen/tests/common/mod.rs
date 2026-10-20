//! Fabrique de fichiers `.vxm` synthétiques pour les tests (écrivain minimal du format, docs/19a § 1).
#![allow(dead_code)]

use std::io::Write;

use em_core::{LeWriter, crc32};
use flate2::Compression;
use flate2::write::ZlibEncoder;

/// Un voxel à écrire : position locale (pivot = origine), sorte (1..=5), indice de rampe.
#[derive(Copy, Clone, Debug)]
pub struct V {
    pub p: [i32; 3],
    pub kind: u8,
    pub ramp: u8,
}

pub fn v(x: i32, y: i32, z: i32, kind: u8, ramp: u8) -> V {
    V {
        p: [x, y, z],
        kind,
        ramp,
    }
}

/// Options d'écriture.
#[derive(Clone)]
pub struct Opts {
    pub zlib: bool,
    pub version: u16,
    pub flags_extra: u16,
    pub roles: Vec<&'static str>,
    pub lods_header: Option<Vec<u8>>,
    pub voxel_m: &'static str,
}

impl Default for Opts {
    fn default() -> Self {
        Self {
            zlib: true,
            version: 1,
            flags_extra: 0,
            roles: vec!["bark", "bark_alt", "twig", "leaf", "flower", "flower", "fruit"],
            lods_header: None,
            voxel_m: "0.05",
        }
    }
}

pub fn json(opts: &Opts, lods: &[u8]) -> String {
    let ramps: Vec<String> = opts
        .roles
        .iter()
        .map(|_| "[[0,0,0],[100,100,100],[200,200,200]]".to_owned())
        .collect();
    let roles: Vec<String> = opts.roles.iter().map(|r| format!("\"{r}\"")).collect();
    let lods = opts.lods_header.clone().unwrap_or_else(|| lods.to_vec());
    format!(
        "{{\"format\":\"vxm-1\",\"generator\":\"test\",\"seed\":\"1\",\"seed_int\":1,\"species\":\"test\",\"nom\":\"Test\",\
         \"height_m\":1.0,\"season\":\"summer\",\"voxel_m\":{},\"lods\":{:?},\"steps\":30,\"ramps\":[{}],\"ramp_roles\":[{}]}}",
        opts.voxel_m,
        lods,
        ramps.join(","),
        roles.join(",")
    )
}

/// Écrit un fichier avec les sections `(lod, voxels)`. Les voxels sont triés par (y, z, x) ici.
pub fn fabrique(sections: &[(u8, Vec<V>)], opts: &Opts) -> Vec<u8> {
    let lods: Vec<u8> = sections.iter().map(|s| s.0).collect();
    let json = json(opts, &lods);
    let mut w = LeWriter::new();
    w.bytes(b"VXM1")
        .u16(opts.version)
        .u16((u16::from(opts.zlib)) | opts.flags_extra)
        .u32(json.len() as u32);
    w.bytes(json.as_bytes());
    for (lod, voxels) in sections {
        let mut vs = voxels.clone();
        vs.sort_by_key(|c| (c.p[1], c.p[2], c.p[0]));
        let (mut mn, mut mx) = ([i32::MAX; 3], [i32::MIN; 3]);
        for c in &vs {
            for i in 0..3 {
                mn[i] = mn[i].min(c.p[i]);
                mx[i] = mx[i].max(c.p[i]);
            }
        }
        if vs.is_empty() {
            mn = [0; 3];
            mx = [-1; 3];
        }
        let mut corps = Vec::new();
        for (axe, origine) in mn.iter().enumerate() {
            for c in &vs {
                corps.extend_from_slice(&((c.p[axe] - origine) as u16).to_le_bytes());
            }
        }
        corps.extend(vs.iter().map(|c| c.kind));
        corps.extend(vs.iter().map(|c| c.ramp));
        let stocke = if opts.zlib {
            let mut e = ZlibEncoder::new(Vec::new(), Compression::default());
            e.write_all(&corps).unwrap();
            e.finish().unwrap()
        } else {
            corps
        };
        w.u8(*lod).bytes(&[0, 0, 0]);
        for m in mn {
            w.i32(m);
        }
        for i in 0..3 {
            w.u32((mx[i] - mn[i] + 1) as u32);
        }
        w.u32(vs.len() as u32).u32(stocke.len() as u32).bytes(&stocke);
    }
    let mut octets = w.into_bytes();
    let crc = crc32(&octets);
    octets.extend_from_slice(&crc.to_le_bytes());
    octets
}

/// Recalcule le CRC en fin de fichier après une modification (pour tester les contrôles qui suivent le CRC).
pub fn recrc(mut octets: Vec<u8>) -> Vec<u8> {
    let n = octets.len() - 4;
    let crc = crc32(&octets[..n]);
    octets[n..].copy_from_slice(&crc.to_le_bytes());
    octets
}
