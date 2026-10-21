//! `ChunkMesher` : un chunk et sa bordure (`PaddedChunk`) vers ses faces visibles.
//!
//! Pour chaque voxel solide et chaque face dont le voisin est de l'air :
//! 1. la couleur plate du voxel est évaluée UNE fois (`VoxelColorer`), quel que soit le nombre de ses faces ;
//! 2. l'occlusion ambiante des quatre coins suit la règle de la référence : `s1`, `s2` les deux voisins de côté,
//!    `c` le voisin de coin ; niveau 0 si `s1` et `s2` sont pleins (quelle que soit `c`), sinon `3 - (s1 + s2 + c)` ;
//! 3. les cellules d'une tranche sont fusionnées gloutonnement SEULEMENT si couleur, paramètres de matière et
//!    occlusion sont identiques ET si l'occlusion est la même aux quatre coins (sinon l'interpolation changerait) ;
//!    le feuillage ne fusionne jamais (son épaisseur de translucidité est propre à chaque voxel).

use crate::appearance::{VoxelAppearance, VoxelColorer};
use crate::mesh::ChunkMesh;
use crate::padded::{PADDED_EDGE, PaddedChunk};
use crate::quad::{CHUNK_EDGE, Face, Quad, QuadSpec};
use em_core::{ChunkKey, Lod, VoxelCoord, VoxelValue};

/// Réglages du mailleur.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct MesherConfig {
    greedy: bool,
}

impl MesherConfig {
    /// Réglages explicites.
    pub const fn new(greedy: bool) -> Self {
        Self { greedy }
    }

    /// Fusion gloutonne active ?
    pub const fn greedy(&self) -> bool {
        self.greedy
    }
}

impl Default for MesherConfig {
    fn default() -> Self {
        Self { greedy: true }
    }
}

/// Une cellule d'une tranche : colonne, ligne et clé de fusion.
#[derive(Copy, Clone)]
struct Cellule {
    u: u8,
    v: u8,
    cle: u64,
}

const PRESENTE: u64 = 1 << 63;
const FUSIONNABLE: u64 = 1 << 49;
const BORD: usize = CHUNK_EDGE as usize;

/// Clé de fusion : deux cellules de même clé ont même aspect ET même occlusion uniforme.
fn cle(a: &VoxelAppearance, ao: [u8; 4], fusionnable: bool) -> u64 {
    PRESENTE
        | u64::from(a.color[0])
        | u64::from(a.color[1]) << 8
        | u64::from(a.color[2]) << 16
        | u64::from(a.params) << 24
        | u64::from(ao[0] | ao[1] << 2 | ao[2] << 4 | ao[3] << 6) << 32
        | u64::from(a.foliage) << 48
        | if fusionnable { FUSIONNABLE } else { 0 }
}

fn ao_de(cle: u64) -> [u8; 4] {
    let o = (cle >> 32) as u8;
    [o & 3, (o >> 2) & 3, (o >> 4) & 3, (o >> 6) & 3]
}

/// Niveau d'occlusion d'un coin : 0 (deux côtés pleins : le plus sombre) à 3 (dégagé).
const fn niveau(s1: bool, s2: bool, coin: bool) -> u8 {
    if s1 && s2 {
        0
    } else {
        3 - (s1 as u8 + s2 as u8 + coin as u8)
    }
}

/// Le mailleur de chunks. Possède ses réglages, emprunte le colorieur.
pub struct ChunkMesher<'a> {
    colorer: &'a dyn VoxelColorer,
    config: MesherConfig,
}

impl<'a> ChunkMesher<'a> {
    /// Crée un mailleur.
    pub fn new(colorer: &'a dyn VoxelColorer, config: MesherConfig) -> Self {
        Self { colorer, config }
    }

    /// Réglages.
    pub fn config(&self) -> MesherConfig {
        self.config
    }

    /// Maille un chunk. `lod` est le niveau du chunk (ses voxels mesurent 2^lod voxels de base) ; il n'intervient que
    /// dans la position donnée au colorieur.
    pub fn mesh(&self, key: ChunkKey, lod: Lod, padded: &PaddedChunk) -> ChunkMesh {
        if padded.non_air_count() == 0 {
            return ChunkMesh::empty(key, lod);
        }
        let origine = key.origin();
        // Occupation par rangée (y, z) : un bit par voxel de x = -1 à 64 (bit x + 1). Les expositions de chaque face
        // se déduisent d'opérations de bits sur les rangées voisines : seuls les voxels exposés sont visités.
        let rangees = padded.occupancy_rows();
        let rang = |y: i32, z: i32| rangees[(y + 1) as usize * PADDED_EDGE + (z + 1) as usize];
        // les seaux : les cellules visibles de chaque (face, tranche), dans l'ordre de balayage des voxels
        let mut seaux: Vec<Vec<Cellule>> = vec![Vec::new(); 6 * BORD];
        let mut faces = 0_u32;
        const INTERIEUR: u128 = ((1_u128 << BORD) - 1) << 1;
        for y in 0..BORD as i32 {
            for z in 0..BORD as i32 {
                let s = rang(y, z);
                let masques = [
                    s & !(s >> 1) & INTERIEUR,
                    s & !(s << 1) & INTERIEUR,
                    s & !rang(y + 1, z) & INTERIEUR,
                    s & !rang(y - 1, z) & INTERIEUR,
                    s & !rang(y, z + 1) & INTERIEUR,
                    s & !rang(y, z - 1) & INTERIEUR,
                ];
                let mut restant = masques.iter().fold(0_u128, |a, m| a | m);
                while restant != 0 {
                    let bit = restant.trailing_zeros();
                    restant &= restant - 1;
                    let x = bit as i32 - 1;
                    let i = PaddedChunk::index(x, y, z);
                    let aspect = self.colorer.appearance(
                        VoxelValue::from_raw(padded.raw_at(i)),
                        VoxelCoord::new(origine.x + x, origine.y + y, origine.z + z),
                        lod,
                    );
                    let p = [x, y, z];
                    for f in Face::ALL {
                        if masques[f.index()] >> bit & 1 == 0 {
                            continue;
                        }
                        let ao = Self::occlusion(padded, i, f);
                        // le feuillage ne fusionne jamais : son épaisseur (cuite après coup) est celle de CHAQUE voxel
                        let uniforme = ao[0] == ao[1] && ao[1] == ao[2] && ao[2] == ao[3] && !aspect.foliage;
                        let cellule = Cellule {
                            u: p[f.u_axis()] as u8,
                            v: p[f.v_axis()] as u8,
                            cle: cle(&aspect, ao, uniforme),
                        };
                        seaux[f.index() * BORD + p[f.axis()] as usize].push(cellule);
                        faces += 1;
                    }
                }
            }
        }
        let mut quads = Vec::new();
        let mut masque = vec![0_u64; BORD * BORD];
        for f in Face::ALL {
            for tranche in 0..BORD {
                let cellules = &seaux[f.index() * BORD + tranche];
                if cellules.is_empty() {
                    continue;
                }
                self.emettre(f, tranche as u8, cellules, &mut masque, &mut quads);
            }
        }
        ChunkMesh::from_quads(key, lod, quads, faces)
    }

    /// Niveaux d'occlusion des quatre coins de la face `f` du voxel d'indice `i`.
    fn occlusion(padded: &PaddedChunk, i: usize, f: Face) -> [u8; 4] {
        let stride = PaddedChunk::STRIDE;
        let (su, sv) = (stride[f.u_axis()], stride[f.v_axis()]);
        let j = i as isize + f.sign() as isize * stride[f.axis()];
        let plein = |decalage: isize| PaddedChunk::is_solid(padded.raw_at((j + decalage) as usize));
        let (um, up, vm, vp) = (plein(-su), plein(su), plein(-sv), plein(sv));
        let (mm, pm, mp, pp) = (plein(-su - sv), plein(su - sv), plein(-su + sv), plein(su + sv));
        // coins : 0 (-u,-v), 1 (+u,-v), 2 (+u,+v), 3 (-u,+v)
        [
            niveau(um, vm, mm),
            niveau(up, vm, pm),
            niveau(up, vp, pp),
            niveau(um, vp, mp),
        ]
    }

    /// Range les cellules d'une tranche en quads (fusion gloutonne ou un quad par cellule).
    fn emettre(&self, f: Face, tranche: u8, cellules: &[Cellule], masque: &mut [u64], quads: &mut Vec<Quad>) {
        let plan = tranche + u8::from(f.sign() > 0);
        let mut quad = |u: u8, v: u8, w: u8, h: u8, cle: u64| {
            let mut origine = [0_u8; 3];
            origine[f.axis()] = plan;
            origine[f.u_axis()] = u;
            origine[f.v_axis()] = v;
            quads.push(Quad::pack(QuadSpec {
                origin: origine,
                face: f,
                width: w,
                height: h,
                color: [cle as u8, (cle >> 8) as u8, (cle >> 16) as u8],
                params: (cle >> 24) as u8,
                ao: ao_de(cle),
                thickness: 0,
                foliage: (cle >> 48) & 1 == 1,
            }));
        };
        if !self.config.greedy {
            for c in cellules {
                quad(c.u, c.v, 1, 1, c.cle);
            }
            return;
        }
        let (mut u0, mut u1, mut v0, mut v1) = (u8::MAX, 0_u8, u8::MAX, 0_u8);
        for c in cellules {
            masque[usize::from(c.v) * BORD + usize::from(c.u)] = c.cle;
            (u0, u1, v0, v1) = (u0.min(c.u), u1.max(c.u), v0.min(c.v), v1.max(c.v));
        }
        for v in v0..=v1 {
            for u in u0..=u1 {
                let k = usize::from(v) * BORD + usize::from(u);
                let cle = masque[k];
                if cle == 0 {
                    continue;
                }
                let (mut w, mut h) = (1_u8, 1_u8);
                if cle & FUSIONNABLE != 0 {
                    while u + w <= u1 && masque[k + usize::from(w)] == cle {
                        w += 1;
                    }
                    'hauteur: while v + h <= v1 {
                        let ligne = (usize::from(v + h)) * BORD + usize::from(u);
                        for dx in 0..usize::from(w) {
                            if masque[ligne + dx] != cle {
                                break 'hauteur;
                            }
                        }
                        h += 1;
                    }
                }
                for dv in 0..usize::from(h) {
                    let ligne = (usize::from(v) + dv) * BORD + usize::from(u);
                    masque[ligne..ligne + usize::from(w)].fill(0);
                }
                quad(u, v, w, h, cle);
            }
        }
    }
}

const _: () = assert!(PADDED_EDGE == BORD + 2);
