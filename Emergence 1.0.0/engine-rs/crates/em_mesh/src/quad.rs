//! Le quad : une face visible de voxel (ou un rectangle de faces identiques fusionnées), en 12 octets.
//!
//! ```text
//!  mot 0 : x (7 bits) | y (7) | z (7) | face (3) | épaisseur de feuillage (8)        position du coin 0 en voxels locaux 0..=64
//!  mot 1 : r (8) | v (8) | b (8) | octet de rendu (8)                                couleur sRGB8 PLATE + octet de rendu
//!  mot 2 : largeur-1 (6) | hauteur-1 (6) | occlusion des 4 coins (4 x 2 bits) | feuillage (1)
//!          | creux des 4 coins (4 x 2 bits) | réservé (3)
//! ```
//!
//! L'octet de rendu (L34) est celui que lit le shader : bits 0-2 réflexion (0..7), bits 3-5 relief sous-voxel (0 lisse
//! à 7 froissé), bit 6 face intérieure (atténuée), bit 7 émissif. Le « creux » est l'occlusion à plus grande portée :
//! PROFONDEUR 0 (dégagé, valeur par défaut d'un quad à zéro) à 3 (très encaissé).
//!
//! Un quad est lu par le GPU (tampon de stockage : le sommet reconstruit lui-même ses quatre coins, sans tampon
//! d'indices) ; [`Quad::vertex`] donne la même chose côté CPU, pour les tests et les outils.

use crate::error::MeshError;
use bytemuck::{Pod, Zeroable};

/// Arête d'un chunk en voxels.
pub const CHUNK_EDGE: u8 = 64;

/// Facteur d'ambiance de l'occlusion par sommet, par niveau 0..3 (3 = dégagé) : celui de la référence de Monsieur.
pub const AO_FACTOR: [f32; 4] = [0.5, 0.72, 0.88, 1.0];

/// L'octet de rendu d'un quad (voir le module) : réflexion, relief, intérieur, émissif.
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq)]
pub struct RenderByte(u8);

impl RenderByte {
    /// Assemble ; chaque champ est borné (réflexion et relief à 0..7).
    pub const fn new(reflection: u8, relief: u8, interior: bool, emissive: bool) -> Self {
        let r = if reflection > 7 { 7 } else { reflection };
        let k = if relief > 7 { 7 } else { relief };
        Self(r | k << 3 | (interior as u8) << 6 | (emissive as u8) << 7)
    }

    /// Lit un octet de quad (tout octet est valide).
    pub const fn from_byte(b: u8) -> Self {
        Self(b)
    }

    /// L'octet.
    pub const fn byte(self) -> u8 {
        self.0
    }

    /// Réflexion 0..7.
    pub const fn reflection(self) -> u8 {
        self.0 & 7
    }

    /// Relief sous-voxel 0..7.
    pub const fn relief(self) -> u8 {
        (self.0 >> 3) & 7
    }

    /// Face intérieure (éclairage ambiant atténué).
    pub const fn interior(self) -> bool {
        self.0 & 64 != 0
    }

    /// Émissif.
    pub const fn emissive(self) -> bool {
        self.0 & 128 != 0
    }
}

/// Une des six faces d'un voxel : l'axe (x, y, z) et le sens.
#[derive(Copy, Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Face {
    /// Normale +x.
    PosX = 0,
    /// Normale -x.
    NegX = 1,
    /// Normale +y (le dessus).
    PosY = 2,
    /// Normale -y.
    NegY = 3,
    /// Normale +z.
    PosZ = 4,
    /// Normale -z.
    NegZ = 5,
}

impl Face {
    /// Les six faces dans l'ordre canonique (celui des sorties du mailleur).
    pub const ALL: [Face; 6] = [
        Face::PosX,
        Face::NegX,
        Face::PosY,
        Face::NegY,
        Face::PosZ,
        Face::NegZ,
    ];

    /// Face d'indice 0..6 (`index`), `None` au-delà.
    pub const fn from_index(i: u32) -> Option<Face> {
        match i {
            0 => Some(Face::PosX),
            1 => Some(Face::NegX),
            2 => Some(Face::PosY),
            3 => Some(Face::NegY),
            4 => Some(Face::PosZ),
            5 => Some(Face::NegZ),
            _ => None,
        }
    }

    /// Indice 0..6 : `2 axe + (sens négatif)`.
    pub const fn index(self) -> usize {
        self as usize
    }

    /// Axe de la normale : 0 x, 1 y, 2 z.
    pub const fn axis(self) -> usize {
        self as usize / 2
    }

    /// Sens de la normale : +1 ou -1.
    pub const fn sign(self) -> i32 {
        if (self as usize).is_multiple_of(2) { 1 } else { -1 }
    }

    /// Axe de la largeur du quad (`axe + 1` modulo 3).
    pub const fn u_axis(self) -> usize {
        (self.axis() + 1) % 3
    }

    /// Axe de la hauteur du quad (`axe + 2` modulo 3).
    pub const fn v_axis(self) -> usize {
        (self.axis() + 2) % 3
    }

    /// Normale entière.
    pub const fn normal(self) -> [i32; 3] {
        let mut n = [0; 3];
        n[self.axis()] = self.sign();
        n
    }
}

/// Description d'un quad à ranger (champs validés par [`Quad::new`]).
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct QuadSpec {
    /// Coin 0 du quad en voxels locaux (0..=64 sur chaque axe).
    pub origin: [u8; 3],
    /// Face.
    pub face: Face,
    /// Largeur en voxels (1..=64), le long de `Face::u_axis`.
    pub width: u8,
    /// Hauteur en voxels (1..=64), le long de `Face::v_axis`.
    pub height: u8,
    /// Couleur sRGB8 plate.
    pub color: [u8; 3],
    /// Octet de rendu (`RenderByte`).
    pub params: u8,
    /// Niveau d'occlusion des quatre coins (0..=3, 3 = dégagé).
    pub ao: [u8; 4],
    /// Épaisseur de feuillage le long du soleil, en voxels (0 : aucune ou non cuite).
    pub thickness: u8,
    /// Vrai pour une face de feuillage.
    pub foliage: bool,
}

/// Un sommet d'un quad.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Vertex {
    /// Position locale au chunk, en voxels.
    pub position: [u8; 3],
    /// Normale (composantes -1, 0, 1).
    pub normal: [i8; 3],
    /// Couleur sRGB8.
    pub color: [u8; 3],
    /// Niveau d'occlusion 0..=3.
    pub ao: u8,
    /// Profondeur du creux (occlusion à grande portée) 0..=3, 0 = dégagé.
    pub creux: u8,
    /// Octet de rendu.
    pub params: u8,
}

/// Un quad de 12 octets (voir le module).
#[repr(C)]
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, Pod, Zeroable)]
pub struct Quad {
    words: [u32; 3],
}

impl Quad {
    /// Taille d'un quad en octets.
    pub const BYTES: usize = 12;

    /// Construit un quad ; refuse un champ qui ne tient pas dans le format.
    pub fn new(s: QuadSpec) -> Result<Self, MeshError> {
        if s.origin.iter().any(|v| *v > CHUNK_EDGE) {
            return Err(MeshError::QuadInvalide(format!(
                "origine {:?} hors de 0..=64",
                s.origin
            )));
        }
        if !(1..=CHUNK_EDGE).contains(&s.width) || !(1..=CHUNK_EDGE).contains(&s.height) {
            return Err(MeshError::QuadInvalide(format!(
                "taille {} x {} hors de 1..=64",
                s.width, s.height
            )));
        }
        if s.ao.iter().any(|v| *v > 3) {
            return Err(MeshError::QuadInvalide(format!(
                "occlusion {:?} hors de 0..=3",
                s.ao
            )));
        }
        Ok(Self::pack(s))
    }

    /// Pose la profondeur du creux des quatre coins (0..=3, bornée à 3).
    pub fn with_creux(mut self, creux: [u8; 4]) -> Self {
        let c = creux
            .iter()
            .enumerate()
            .fold(0_u32, |a, (k, v)| a | u32::from((*v).min(3)) << (2 * k));
        self.words[2] = (self.words[2] & !(0xFF << 21)) | c << 21;
        self
    }

    /// Rangement sans validation (le mailleur ne produit que des champs valides, vérifiés en essais).
    pub(crate) fn pack(s: QuadSpec) -> Self {
        let w0 = u32::from(s.origin[0])
            | u32::from(s.origin[1]) << 7
            | u32::from(s.origin[2]) << 14
            | (s.face as u32) << 21
            | u32::from(s.thickness) << 24;
        let w1 = u32::from(s.color[0])
            | u32::from(s.color[1]) << 8
            | u32::from(s.color[2]) << 16
            | u32::from(s.params) << 24;
        let ao =
            s.ao.iter()
                .enumerate()
                .fold(0_u32, |a, (k, v)| a | u32::from(*v & 3) << (2 * k));
        let w2 =
            u32::from(s.width - 1) | u32::from(s.height - 1) << 6 | ao << 12 | u32::from(s.foliage) << 20;
        Quad { words: [w0, w1, w2] }
    }

    /// Les trois mots bruts (ce que le GPU lit).
    pub const fn words(&self) -> [u32; 3] {
        self.words
    }

    /// Coin 0 du quad, en voxels locaux.
    pub const fn origin(&self) -> [u8; 3] {
        let w = self.words[0];
        [(w & 127) as u8, ((w >> 7) & 127) as u8, ((w >> 14) & 127) as u8]
    }

    /// Face du quad.
    pub fn face(&self) -> Face {
        Face::from_index((self.words[0] >> 21) & 7).unwrap_or(Face::PosX)
    }

    /// Épaisseur de feuillage le long du soleil (voxels).
    pub const fn thickness(&self) -> u8 {
        (self.words[0] >> 24) as u8
    }

    /// Remplace l'épaisseur de feuillage (cuisson, `FoliageBaker`).
    pub fn set_thickness(&mut self, t: u8) {
        self.words[0] = (self.words[0] & 0x00FF_FFFF) | u32::from(t) << 24;
    }

    /// Couleur sRGB8.
    pub const fn color(&self) -> [u8; 3] {
        let w = self.words[1];
        [w as u8, (w >> 8) as u8, (w >> 16) as u8]
    }

    /// Octet de rendu (voir [`RenderByte`]).
    pub const fn params(&self) -> u8 {
        (self.words[1] >> 24) as u8
    }

    /// Largeur en voxels.
    pub const fn width(&self) -> u8 {
        (self.words[2] & 63) as u8 + 1
    }

    /// Hauteur en voxels.
    pub const fn height(&self) -> u8 {
        ((self.words[2] >> 6) & 63) as u8 + 1
    }

    /// Niveaux d'occlusion des quatre coins.
    pub const fn ao(&self) -> [u8; 4] {
        let w = self.words[2] >> 12;
        [
            (w & 3) as u8,
            ((w >> 2) & 3) as u8,
            ((w >> 4) & 3) as u8,
            ((w >> 6) & 3) as u8,
        ]
    }

    /// Vrai pour une face de feuillage.
    pub const fn is_foliage(&self) -> bool {
        (self.words[2] >> 20) & 1 == 1
    }

    /// Profondeur du creux (occlusion à grande portée) des quatre coins, 0 = dégagé.
    pub const fn creux(&self) -> [u8; 4] {
        let w = self.words[2] >> 21;
        [
            (w & 3) as u8,
            ((w >> 2) & 3) as u8,
            ((w >> 4) & 3) as u8,
            ((w >> 6) & 3) as u8,
        ]
    }

    /// L'octet de rendu décodé.
    pub const fn render(&self) -> RenderByte {
        RenderByte::from_byte(self.params())
    }

    /// Nombre de faces de voxel que couvre le quad.
    pub const fn face_count(&self) -> u32 {
        self.width() as u32 * self.height() as u32
    }

    /// Position du coin `k` (0..4) : `k = 0` au minimum, 1 le long de la largeur, 2 en diagonale, 3 le long de la hauteur.
    pub fn corner(&self, k: usize) -> [u8; 3] {
        let f = self.face();
        let (su, sv) = (u8::from(k == 1 || k == 2), u8::from(k >= 2));
        let mut p = self.origin();
        p[f.u_axis()] += su * self.width();
        p[f.v_axis()] += sv * self.height();
        p
    }

    /// Sommet `k` (0..4).
    pub fn vertex(&self, k: usize) -> Vertex {
        let n = self.face().normal();
        Vertex {
            position: self.corner(k),
            normal: [n[0] as i8, n[1] as i8, n[2] as i8],
            color: self.color(),
            ao: self.ao()[k],
            creux: self.creux()[k],
            params: self.params(),
        }
    }

    /// Vrai si le quad se coupe selon la diagonale 0-2 (coins 0 et 2 les plus dégagés), faux selon 1-3 : la règle de
    /// la référence, qui évite l'anisotropie d'une interpolation toujours coupée du même côté.
    pub fn splits_on_0_2(&self) -> bool {
        let a = self.ao();
        a[0] + a[2] > a[1] + a[3]
    }

    /// Les quatre coins dans l'ordre d'une BANDE de triangles (ce que dessine le GPU, une instance par quad) : les
    /// triangles sont `(b0, b1, b2)` et `(b2, b1, b3)`, l'arête commune `b1`-`b2` est la diagonale choisie, et
    /// l'enroulement est celui de [`Quad::triangles`] à une rotation près.
    pub fn strip(&self) -> [u8; 4] {
        match (self.splits_on_0_2(), self.face().sign() > 0) {
            (true, true) => [1, 2, 0, 3],
            (false, true) => [2, 3, 1, 0],
            (true, false) => [1, 0, 2, 3],
            (false, false) => [2, 1, 3, 0],
        }
    }

    /// Les deux triangles (indices de coins), enroulés pour que la normale géométrique (produit vectoriel droitier
    /// des deux premiers côtés) soit celle de la face.
    pub fn triangles(&self) -> [[u8; 3]; 2] {
        let positif = self.face().sign() > 0;
        match (self.splits_on_0_2(), positif) {
            (true, true) => [[0, 1, 2], [0, 2, 3]],
            (true, false) => [[0, 2, 1], [0, 3, 2]],
            (false, true) => [[1, 2, 3], [1, 3, 0]],
            (false, false) => [[1, 3, 2], [1, 0, 3]],
        }
    }
}
