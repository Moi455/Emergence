//! `FoliageBaker` : l'épaisseur de feuillage le long du soleil, cuite dans chaque quad de feuillage (translucidité du
//! feuillage SANS tracé au rendu).
//!
//! Choix (docs/19b L33 phase 4) : une épaisseur PAR FACE (par voxel : les quads de feuillage ne fusionnent jamais),
//! mesurée depuis le CENTRE du voxel, exactement comme `voxel_foliage_thickness.wgsl` de L10 (un voxel = un aplat, toute
//! sa face reçoit la même épaisseur), au lieu d'un octet par sommet : un sommet n'ajouterait qu'un dégradé que les
//! voxels plats refusent, et coûterait quatre fois plus de rayons. La direction est CELLE DU SOLEIL au moment de la
//! cuisson (pas une direction moyenne : à la golden hour, soleil à 10°, une direction moyenne se tromperait de 2 à 3 m
//! d'épaisseur) ; le shader module par l'angle courant et par l'ombre. Quand le soleil a tourné de quelques degrés, on
//! recuit (cher : voir `mesures`), le maillage géométrique ne bouge pas.
//!
//! Code de l'octet : 0 = non cuit (face tournée vers le soleil) ; 1 à 254 = épaisseur en quarts de voxel ; 255 = le
//! soleil est barré par un solide qui n'est pas du feuillage (tronc, pierre, sol).

use crate::appearance::VoxelColorer;
use crate::mesh::ChunkMesh;
use em_core::ChunkKey;
use em_voxel::{Chunk, ChunkClass};
use rayon::prelude::*;
use std::collections::BTreeMap;

/// Code « soleil barré ».
pub const BLOCKED_CODE: u8 = 255;
/// Au-delà de ce `n · soleil`, la face est tournée vers le soleil : elle ne transmet rien, on ne cuit pas.
const COS_MAX: f32 = 0.45;
/// Mots de 64 bits d'une grille de chunk (64³ bits).
const MOTS: usize = 64 * 64 * 64 / 64;

/// Occupation d'un chunk : un bit « solide » et un bit « feuillage » par voxel, indice `x + 64 z + 4096 y`.
struct Bits {
    solide: Vec<u64>,
    feuille: Vec<u64>,
}

impl Bits {
    fn depuis(chunk: &Chunk, colorier: &dyn VoxelColorer) -> Option<Self> {
        match chunk.classify() {
            ChunkClass::Air => return None,
            // uniforme (le sol) : tout plein, tout feuillage ou rien, sans lire les briques
            ChunkClass::Uniform(v) => {
                let f = if colorier.is_foliage(v) { u64::MAX } else { 0 };
                return Some(Self {
                    solide: vec![u64::MAX; MOTS],
                    feuille: vec![f; MOTS],
                });
            }
            ChunkClass::Mixed => {}
        }
        let mut solide = vec![0_u64; MOTS];
        let mut feuille = vec![0_u64; MOTS];
        for (i, v) in chunk.to_dense().iter().enumerate() {
            if v.is_air() {
                continue;
            }
            solide[i >> 6] |= 1 << (i & 63);
            if colorier.is_foliage(*v) {
                feuille[i >> 6] |= 1 << (i & 63);
            }
        }
        Some(Self { solide, feuille })
    }
}

/// Cuiseur d'épaisseur : lit les chunks chargés (occupation et feuillage), écrit dans les quads.
pub struct FoliageBaker {
    grilles: BTreeMap<ChunkKey, Bits>,
}

/// État d'une cellule traversée par le rayon.
#[derive(Copy, Clone, PartialEq, Eq)]
enum Cellule {
    Vide,
    Feuille,
    Barre,
}

impl FoliageBaker {
    /// Construit les grilles d'occupation de tous les chunks (en parallèle, résultat ordonné par clé).
    pub fn new(colorier: &dyn VoxelColorer, chunks: &BTreeMap<ChunkKey, Chunk>) -> Self {
        let liste: Vec<(&ChunkKey, &Chunk)> = chunks.iter().collect();
        let grilles = liste
            .par_iter()
            .filter_map(|(k, c)| Bits::depuis(c, colorier).map(|b| (**k, b)))
            .collect::<Vec<_>>()
            .into_iter()
            .collect();
        Self { grilles }
    }

    fn cellule<'a>(&'a self, cache: &mut Option<(ChunkKey, Option<&'a Bits>)>, c: [i32; 3]) -> Cellule {
        let cle = ChunkKey::new(c[0] >> 6, c[1] >> 6, c[2] >> 6);
        let bits = match cache {
            Some((k, b)) if *k == cle => *b,
            _ => {
                let b = self.grilles.get(&cle);
                *cache = Some((cle, b));
                b
            }
        };
        let Some(b) = bits else { return Cellule::Vide };
        let i = (c[0] & 63) as usize + 64 * (c[2] & 63) as usize + 4096 * (c[1] & 63) as usize;
        if (b.solide[i >> 6] >> (i & 63)) & 1 == 0 {
            Cellule::Vide
        } else if (b.feuille[i >> 6] >> (i & 63)) & 1 == 1 {
            Cellule::Feuille
        } else {
            Cellule::Barre
        }
    }

    /// Épaisseur de feuillage du voxel `cellule` (coordonnées monde, niveau 0) le long de `soleil` (unitaire, vers le
    /// soleil), en voxels ; `None` si un solide qui n'est pas du feuillage barre la zone. DDA d'Amanatides et Woo
    /// depuis le centre du voxel, borné à `zone` voxels.
    pub fn thickness(&self, cellule: [i32; 3], soleil: [f32; 3], zone: f32) -> Option<f32> {
        let s = soleil;
        let pas = s.map(|v| if v >= 0.0 { 1_i32 } else { -1 });
        let inv = s.map(|v| {
            if v.abs() < 1e-6 {
                f32::INFINITY
            } else {
                (1.0 / v).abs()
            }
        });
        let mut tmax = [0_f32; 3];
        for a in 0..3 {
            tmax[a] = 0.5 * inv[a];
        }
        let mut c = cellule;
        let mut t = 0.0_f32;
        let mut epais = 0.0_f32;
        let mut cache = None;
        loop {
            let a = if tmax[0] < tmax[1] && tmax[0] < tmax[2] {
                0
            } else if tmax[1] < tmax[2] {
                1
            } else {
                2
            };
            let te = tmax[a];
            // la cellule courante est du feuillage (le départ l'est, puis chaque cellule d'entrée acceptée)
            epais += (te.min(zone) - t).max(0.0);
            if te >= zone {
                return Some(epais);
            }
            t = te;
            c[a] += pas[a];
            tmax[a] += inv[a];
            match self.cellule(&mut cache, c) {
                Cellule::Vide => {
                    // traverse du vide jusqu'à la prochaine cellule pleine : seules les cellules de feuillage comptent
                    loop {
                        let b = if tmax[0] < tmax[1] && tmax[0] < tmax[2] {
                            0
                        } else if tmax[1] < tmax[2] {
                            1
                        } else {
                            2
                        };
                        let te2 = tmax[b];
                        if te2 >= zone {
                            return Some(epais);
                        }
                        t = te2;
                        c[b] += pas[b];
                        tmax[b] += inv[b];
                        match self.cellule(&mut cache, c) {
                            Cellule::Vide => {}
                            Cellule::Feuille => break,
                            Cellule::Barre => return None,
                        }
                    }
                }
                Cellule::Feuille => {}
                Cellule::Barre => return None,
            }
        }
    }

    /// Cuit l'épaisseur dans tous les quads de feuillage des maillages, pour ce soleil (direction VERS le soleil, y
    /// haut) et cette zone de comptage en voxels. Les faces tournées vers le soleil gardent 0.
    pub fn bake(&self, meshes: &mut [ChunkMesh], soleil: [f32; 3], zone_voxels: u32) {
        let norme = soleil.iter().map(|v| v * v).sum::<f32>().sqrt().max(1e-6);
        let s = soleil.map(|v| v / norme);
        let zone = zone_voxels as f32;
        meshes.par_iter_mut().for_each(|m| {
            let o = m.key().origin();
            for q in m.quads_mut() {
                if !q.is_foliage() {
                    continue;
                }
                let f = q.face();
                let n = f.normal();
                let cos_ns: f32 = (0..3).map(|a| n[a] as f32 * s[a]).sum();
                if cos_ns >= COS_MAX {
                    q.set_thickness(0);
                    continue;
                }
                let p = q.origin();
                let mut v = [i32::from(p[0]), i32::from(p[1]), i32::from(p[2])];
                if f.sign() > 0 {
                    v[f.axis()] -= 1;
                }
                let cellule = [o.x + v[0], o.y + v[1], o.z + v[2]];
                let code = match self.thickness(cellule, s, zone) {
                    None => BLOCKED_CODE,
                    Some(e) => ((e * 4.0).round() as u32).clamp(1, 254) as u8,
                };
                q.set_thickness(code);
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::appearance::VoxelAppearance;
    use crate::quad::Face;
    use em_core::{Lod, MaterialId, VoxelCoord, VoxelValue};

    /// Classe 30 = feuille, le reste = solide dur.
    struct Feuilles;
    impl VoxelColorer for Feuilles {
        fn appearance(&self, v: VoxelValue, _p: VoxelCoord, _l: Lod) -> VoxelAppearance {
            VoxelAppearance {
                color: [1, 2, 3],
                params: 0,
                foliage: self.is_foliage(v),
            }
        }
        fn is_foliage(&self, v: VoxelValue) -> bool {
            v.material().get() == 30
        }
    }

    fn feuille() -> VoxelValue {
        VoxelValue::new(MaterialId::new(30), 0)
    }
    fn pierre() -> VoxelValue {
        VoxelValue::new(MaterialId::new(20), 0)
    }

    fn monde(poses: &[([u32; 3], VoxelValue)]) -> BTreeMap<ChunkKey, Chunk> {
        let mut c = Chunk::new_air();
        for (p, v) in poses {
            c.set(p[0], p[1], p[2], *v);
        }
        BTreeMap::from([(ChunkKey::new(0, 0, 0), c)])
    }

    #[test]
    fn l_epaisseur_compte_les_voxels_de_feuille_le_long_du_soleil() {
        // une colonne de 5 feuilles, soleil au zénith : depuis le centre du voxel du bas, 0,5 + 4 = 4,5 voxels
        let colonne: Vec<_> = (0..5).map(|y| ([10, 10 + y, 10], feuille())).collect();
        let b = FoliageBaker::new(&Feuilles, &monde(&colonne));
        let e = b.thickness([10, 10, 10], [0.0, 1.0, 0.0], 48.0).unwrap();
        assert!((e - 4.5).abs() < 1e-4, "{e}");
        // le dernier voxel : 0,5
        let e = b.thickness([10, 14, 10], [0.0, 1.0, 0.0], 48.0).unwrap();
        assert!((e - 0.5).abs() < 1e-4, "{e}");
        // un trou de deux voxels d'air au milieu ne compte pas
        let troue = [
            ([10, 10, 10], feuille()),
            ([10, 13, 10], feuille()),
            ([10, 14, 10], feuille()),
        ];
        let b = FoliageBaker::new(&Feuilles, &monde(&troue));
        let e = b.thickness([10, 10, 10], [0.0, 1.0, 0.0], 48.0).unwrap();
        assert!((e - 2.5).abs() < 1e-4, "0,5 + 2 voxels après le trou : {e}");
        // un solide qui n'est pas du feuillage barre le soleil
        let barre = [
            ([10, 10, 10], feuille()),
            ([10, 11, 10], feuille()),
            ([10, 12, 10], pierre()),
        ];
        let b = FoliageBaker::new(&Feuilles, &monde(&barre));
        assert_eq!(b.thickness([10, 10, 10], [0.0, 1.0, 0.0], 48.0), None);
    }

    #[test]
    fn la_cuisson_ecrit_le_code_dans_les_faces_qui_tournent_le_dos_au_soleil() {
        use crate::mesher::{ChunkMesher, MesherConfig};
        use crate::padded::PaddedChunk;
        let colonne: Vec<_> = (0..5).map(|y| ([10, 10 + y, 10], feuille())).collect();
        let chunks = monde(&colonne);
        let cle = ChunkKey::new(0, 0, 0);
        let mailleur = ChunkMesher::new(&Feuilles, MesherConfig::default());
        let cherche = |k: ChunkKey| chunks.get(&k);
        let mut m = mailleur.mesh(cle, 0, &PaddedChunk::gather(cle, &cherche));
        assert!(m.quads().iter().all(|q| q.is_foliage() && q.thickness() == 0));
        FoliageBaker::new(&Feuilles, &chunks).bake(std::slice::from_mut(&mut m), [0.0, 1.0, 0.0], 48);
        let dessous = m.quads().iter().find(|q| q.face() == Face::NegY).unwrap();
        assert_eq!(dessous.thickness(), 18, "4,5 voxels = 18 quarts");
        let dessus = m.quads().iter().find(|q| q.face() == Face::PosY).unwrap();
        assert_eq!(dessus.thickness(), 0, "face tournée vers le soleil : non cuite");
        // une pierre au-dessus barre le soleil : code 255
        let barre: Vec<_> = (0..3)
            .map(|y| ([10, 10 + y, 10], feuille()))
            .chain([([10, 13, 10], pierre())])
            .collect();
        let chunks = monde(&barre);
        let cherche = |k: ChunkKey| chunks.get(&k);
        let mut m = mailleur.mesh(cle, 0, &PaddedChunk::gather(cle, &cherche));
        FoliageBaker::new(&Feuilles, &chunks).bake(std::slice::from_mut(&mut m), [0.0, 1.0, 0.0], 48);
        let dessous = m
            .quads()
            .iter()
            .find(|q| q.face() == Face::NegY && q.is_foliage())
            .unwrap();
        assert_eq!(dessous.thickness(), BLOCKED_CODE);
    }

    #[test]
    fn la_zone_borne_l_epaisseur() {
        let colonne: Vec<_> = (0..30).map(|y| ([10, y, 10], feuille())).collect();
        let b = FoliageBaker::new(&Feuilles, &monde(&colonne));
        let e = b.thickness([10, 0, 10], [0.0, 1.0, 0.0], 8.0).unwrap();
        assert!((e - 8.0).abs() < 1e-4, "{e}");
    }
}
