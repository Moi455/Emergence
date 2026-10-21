//! Cultures, champignons et fougères : le TRÈS PETIT, en voxels de 2 cm (`voxel_mm = 20`), pixel art soigné.
//!
//! Un plan de 2 cm a sa propre grille, non alignée sur celle de 5 cm : le moteur le pose en millimètres comme un
//! objet à part (voir `GenPlan::voxel_mm`). Seul le niveau 0 existe ; les niveaux lointains passent par l'instanciation
//! et la silhouette (champ = aplat, voir le rapport L32). Repère local : x est, y haut, z nord, origine au coin
//! sud-ouest de la parcelle, y = 0 au sol.
//!
//! - `Wheat` : rangs de blé (tiges d'un voxel, épis, bords de rang, sillons) ;
//! - `Cabbages` : choux en quinconce (pomme, feuilles extérieures ondulées) ;
//! - `Vines` : vigne sur échalas (pieux, cep, feuillage, grappes) ;
//! - `Plowed` : champ labouré (billons de 40 cm, mottes) ;
//! - `Stamped` : petits motifs posés une fois (touffes de champignons, fougères).

use std::collections::BTreeMap;
use std::sync::Arc;

use em_core::{Lod, MaterialId, VoxelBox, VoxelCoord, VoxelValue};
use em_material::{GrainAxis, tint_wood};
use em_voxel::{PutMode, VoxelSink};
use serde::{Deserialize, Serialize};

use super::fx::{self, Stream, UN};
use super::species::SpeciesTable;
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};
use crate::vxm::{TintTable, VxmClasses, VxmKind};

/// Côté d'un voxel de culture, en millimètres.
pub const VOXEL_MM: u32 = 20;

/// Le contenu d'une cellule de culture : sorte de matière et variante.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum Cell {
    /// Feuille ou tige verte (rampes de feuilles de l'essence).
    Leaf(u8),
    /// Fruit : épi, pomme de chou, grappe, chapeau.
    Fruit(u8),
    /// Fleur : points blancs de l'amanite.
    Petal(u8),
    /// Écorce : cep de vigne, pied de champignon.
    Bark(u8),
    /// Bois brut d'axe vertical (échalas), variante.
    Stake(u8),
    /// Terre labourée, teinte.
    Soil(u8),
}

/// Classes de matière des cultures : celles de la végétation, plus le bois brut et la terre.
#[derive(Copy, Clone, Debug)]
pub struct CropClasses {
    veg: VxmClasses,
    wood: MaterialId,
    soil: MaterialId,
}

impl CropClasses {
    /// Numéros du catalogue : `oak_raw` 15, `dirt` 2 (`materials.csv`), plus les classes de la végétation.
    pub const fn standard() -> Self {
        Self {
            veg: VxmClasses::standard(),
            wood: MaterialId::new(15),
            soil: MaterialId::new(2),
        }
    }
}

/// Une forme de culture : sa boîte et les cellules d'une fenêtre.
pub trait CropShape: Send + Sync {
    /// Dimensions `[x, y, z]` en voxels de 2 cm.
    fn size(&self) -> [i32; 3];
    /// Appelle `put(x, y, z, cellule)` pour chaque cellule pleine de la fenêtre `[lo, hi)` (déjà bornée à la boîte).
    fn fill(&self, lo: [i32; 3], hi: [i32; 3], put: &mut dyn FnMut(i32, i32, i32, Cell));
}

fn u(seed: u64, x: i32, y: i32, z: i32, k: i32) -> i64 {
    fx::hash_unit(
        seed ^ (k as u64).wrapping_mul(0x9E37_79B9),
        i64::from(x),
        i64::from(y),
        i64::from(z),
    )
}

/// Rangs de blé : une tige d'un voxel par cellule de rang, des épis dorés, quelques tiges couchées par le vent.
#[derive(Debug, Clone)]
pub struct Wheat {
    seed: u64,
    size: [i32; 3],
}

impl Wheat {
    const RANG: i32 = 8; // 16 cm entre rangs
    const HAUTEUR_MAX: i32 = 56;

    /// Hauteur totale (épi compris) de la tige de la cellule `(x, z)`, ou `None` s'il n'y en a pas.
    fn tige(&self, x: i32, z: i32) -> Option<(i32, bool)> {
        let zr = z.rem_euclid(Self::RANG);
        let p = match zr {
            1..=4 => UN * 52 / 100,
            0 | 5 => UN * 20 / 100,
            _ => 0, // sillon
        };
        if u(self.seed, x, 0, z, 0) >= p {
            return None;
        }
        // hauteur : 80 cm à 1,08 m, avec une ondulation lente du champ
        let lent = fx::value_noise(i64::from(x) * 2_000, 0, i64::from(z) * 2_000, self.seed ^ 77);
        let h = 40 + ((u(self.seed, x, 0, z, 1) * 9) >> 16) as i32 + ((lent * 6) >> 16) as i32;
        let couchee = u(self.seed, x, 0, z, 2) < UN * 35 / 100;
        Some((h.min(Self::HAUTEUR_MAX - 2), couchee))
    }
}

impl CropShape for Wheat {
    fn size(&self) -> [i32; 3] {
        self.size
    }

    fn fill(&self, lo: [i32; 3], hi: [i32; 3], put: &mut dyn FnMut(i32, i32, i32, Cell)) {
        let dans = |x: i32, y: i32, z: i32| {
            x >= lo[0] && x < hi[0] && y >= lo[1] && y < hi[1] && z >= lo[2] && z < hi[2]
        };
        for z in lo[2] - 4..hi[2] + 4 {
            for x in lo[0] - 1..hi[0] {
                if x < 0 || z < 0 || x >= self.size[0] || z >= self.size[2] {
                    continue;
                }
                let Some((h, couchee)) = self.tige(x, z) else {
                    continue;
                };
                // tige verte puis épi doré (déporté d'un voxel vers l'est si la tige est couchée)
                for y in lo[1].max(0)..hi[1].min(h - 4) {
                    if dans(x, y, z) {
                        put(x, y, z, Cell::Leaf(0));
                    }
                }
                let xe = x + i32::from(couchee);
                let var = (u(self.seed, x, 0, z, 3) >> 15) as u8; // 0 ou 1
                for y in h - 4..h {
                    if dans(xe, y, z) {
                        put(xe, y, z, Cell::Fruit(var));
                    }
                }
                if u(self.seed, x, 0, z, 4) < UN / 2 && dans(xe, h, z) {
                    put(xe, h, z, Cell::Fruit(var)); // barbe
                }
                // épi plus large : un second voxel de grain sur le côté, sur la moitié des épis
                if u(self.seed, x, 0, z, 6) < UN / 2 {
                    for y in h - 3..h - 1 {
                        if dans(xe, y, z + 1) {
                            put(xe, y, z + 1, Cell::Fruit(var));
                        }
                    }
                }
                // feuille étendard : une lame qui s'écarte vers le nord à mi-hauteur
                if u(self.seed, x, 0, z, 5) < UN * 7 / 10 {
                    let yb = h * 55 / 100;
                    let (sens, v) = if u(self.seed, x, 0, z, 7) < UN / 2 {
                        (1, 0)
                    } else {
                        (-1, 1)
                    };
                    for (k, dy) in [(1, 0), (2, 1), (3, 1), (4, 0)] {
                        if dans(x, yb + dy, z + sens * k) {
                            put(x, yb + dy, z + sens * k, Cell::Leaf(v));
                        }
                    }
                }
            }
        }
    }
}

/// Choux en quinconce tous les 48 cm : pomme ronde, feuilles extérieures ondulées.
#[derive(Debug, Clone)]
pub struct Cabbages {
    seed: u64,
    size: [i32; 3],
}

impl Cabbages {
    const PAS: i32 = 24;
}

impl CropShape for Cabbages {
    fn size(&self) -> [i32; 3] {
        self.size
    }

    fn fill(&self, lo: [i32; 3], hi: [i32; 3], put: &mut dyn FnMut(i32, i32, i32, Cell)) {
        for z in lo[2]..hi[2] {
            for x in lo[0]..hi[0] {
                let j = z.div_euclid(Self::PAS);
                // quinconce : une rangée sur deux décalée d'un demi-pas
                let decal = if j & 1 == 1 { Self::PAS / 2 } else { 0 };
                let i = (x - decal).div_euclid(Self::PAS);
                let (cx, cz) = (
                    i * Self::PAS + decal + Self::PAS / 2,
                    j * Self::PAS + Self::PAS / 2,
                );
                let (dx, dz) = (x - cx, z - cz);
                let r2 = dx * dx + dz * dz;
                let rayon_pomme = 8 + ((u(self.seed, i, 0, j, 0) * 3) >> 16) as i32; // 16 à 22 cm
                let violet = u(self.seed, i, 0, j, 1) < UN / 6;
                for y in lo[1].max(0)..hi[1] {
                    let dy = y - rayon_pomme + 1;
                    let d2 = r2 + dy * dy;
                    if d2 <= rayon_pomme * rayon_pomme {
                        // pomme : cœur clair, les voxels du bord alternent avec les feuilles serrées
                        let bord = d2 > (rayon_pomme - 2) * (rayon_pomme - 2);
                        if bord && u(self.seed, x, y, z, 2) < UN * 35 / 100 {
                            put(x, y, z, Cell::Leaf(0));
                        } else {
                            put(x, y, z, Cell::Fruit(u8::from(violet)));
                        }
                    } else if y <= 3 {
                        // jupe de grandes feuilles basses, bord ondulé selon l'azimut
                        let ang = fx::atan2(i64::from(dz), i64::from(dx));
                        let onde = 12 + ((u(self.seed, i, ang, j, 3) * 4) >> 16) as i32;
                        let creux = 3 - (r2 / 18).min(3);
                        if r2 <= onde * onde && y < creux.max(1) + i32::from(r2 < 100) {
                            put(x, y, z, Cell::Leaf(u8::from(u(self.seed, x, y, z, 4) < UN / 3)));
                        }
                    }
                }
            }
        }
    }
}

/// Vigne sur échalas : rangs d'un mètre, pieu tous les 60 cm, cep noueux, feuillage et grappes.
#[derive(Debug, Clone)]
pub struct Vines {
    seed: u64,
    size: [i32; 3],
}

impl Vines {
    const RANG: i32 = 50;
    const PIEU: i32 = 30;
}

impl CropShape for Vines {
    fn size(&self) -> [i32; 3] {
        self.size
    }

    fn fill(&self, lo: [i32; 3], hi: [i32; 3], put: &mut dyn FnMut(i32, i32, i32, Cell)) {
        for z in lo[2]..hi[2] {
            let j = z.div_euclid(Self::RANG);
            let cz = j * Self::RANG + Self::RANG / 2;
            if (z - cz).abs() > 12 {
                continue;
            }
            for x in lo[0]..hi[0] {
                let i = (x + Self::PIEU / 2).div_euclid(Self::PIEU);
                let cx = i * Self::PIEU;
                let (dx, dz) = (x - cx, z - cz);
                for y in lo[1].max(0)..hi[1] {
                    // pieu de 2 x 2 voxels, 1 m de haut
                    if (0..2).contains(&dx) && (0..2).contains(&dz) && y < 50 {
                        put(
                            x,
                            y,
                            z,
                            Cell::Stake(((u(self.seed, i, y / 6, j, 0) * 6) >> 16) as u8),
                        );
                        continue;
                    }
                    // cep : tronc tordu de 3 voxels qui longe le pieu
                    let tors = ((u(self.seed, i, 1, j, 1) * 3) >> 16) as i32 - 1;
                    let (tx, tz) = (cx - 3 + (y / 8) % 2 * tors, cz);
                    if y < 24
                        && (x - tx).abs() <= 1
                        && (z - tz).abs() <= 1
                        && (x - tx).abs() + (z - tz).abs() <= 1 + i32::from(y < 6)
                    {
                        put(x, y, z, Cell::Bark(0));
                        continue;
                    }
                    // feuillage : nappe d'ellipsoïdes autour du fil, par plaques
                    let (fy, ry) = (36, 13);
                    let e = (dx * dx) * 100 / (15 * 15)
                        + ((y - fy) * (y - fy)) * 100 / (ry * ry)
                        + (dz * dz) * 100 / (8 * 8);
                    if e <= 100 && y >= 22 && u(self.seed, x, y, z, 2) < UN * 52 / 100 {
                        put(x, y, z, Cell::Leaf(u8::from(u(self.seed, x, y, z, 3) < UN / 3)));
                        continue;
                    }
                    // grappes : gouttes de 7 voxels de haut sous le feuillage, d'un côté ou de l'autre du pieu
                    for (k, cote) in [(0, -6), (1, 7)] {
                        if u(self.seed, i, k + 10, j, 4) < UN * 55 / 100 {
                            let (gx, gz, gy) = (
                                cx + cote,
                                cz + ((u(self.seed, i, k, j, 5) * 5) >> 16) as i32 - 2,
                                31,
                            );
                            let (ex, ez, ey) = (x - gx, z - gz, y - gy);
                            let rayon = 3 - (-ey).clamp(0, 3) / 2 * i32::from(ey < 0);
                            if (-6..=2).contains(&ey) && ex * ex + ez * ez <= rayon.max(1) * rayon.max(1) {
                                put(x, y, z, Cell::Fruit(u8::from(u(self.seed, i, 20, j, 6) < UN / 5)));
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Champ labouré : billons de 40 cm le long de x, mottes à la surface.
#[derive(Debug, Clone)]
pub struct Plowed {
    seed: u64,
    size: [i32; 3],
}

impl CropShape for Plowed {
    fn size(&self) -> [i32; 3] {
        self.size
    }

    fn fill(&self, lo: [i32; 3], hi: [i32; 3], put: &mut dyn FnMut(i32, i32, i32, Cell)) {
        for z in lo[2]..hi[2] {
            let phase = z.rem_euclid(20);
            let crete = 1 + (3 * (10 - (phase - 10).abs()) + 5) / 10; // 1 (fond de sillon) à 4 (crête)
            for x in lo[0]..hi[0] {
                // les billons ondulent un peu le long du rang
                let onde = ((fx::value_noise(i64::from(x) * 3_000, 0, i64::from(z) * 3_000, self.seed) * 2)
                    >> 16) as i32;
                let motte = i32::from(u(self.seed, x, 0, z, 0) < UN * 28 / 100)
                    + i32::from(u(self.seed, x, 1, z, 1) < UN / 14);
                let h = (crete + onde - 1 + motte).clamp(1, 6);
                for y in lo[1].max(0)..hi[1].min(h) {
                    let teinte = 8 + ((u(self.seed, x, y, z, 2) * 10) >> 16) as u8 + (y as u8) * 3;
                    put(x, y, z, Cell::Soil(teinte));
                }
            }
        }
    }
}

/// Un petit motif posé une fois, rangé dans une table (champignons, fougères).
#[derive(Debug, Clone)]
pub struct Stamped {
    cells: BTreeMap<(i32, i32, i32), Cell>,
    size: [i32; 3],
}

impl Stamped {
    fn new() -> Self {
        Self {
            cells: BTreeMap::new(),
            size: [1, 1, 1],
        }
    }

    fn set(&mut self, p: (i32, i32, i32), c: Cell) {
        if p.0 >= 0 && p.1 >= 0 && p.2 >= 0 {
            self.size = [
                self.size[0].max(p.0 + 1),
                self.size[1].max(p.1 + 1),
                self.size[2].max(p.2 + 1),
            ];
            self.cells.insert(p, c);
        }
    }
}

impl CropShape for Stamped {
    fn size(&self) -> [i32; 3] {
        self.size
    }

    fn fill(&self, lo: [i32; 3], hi: [i32; 3], put: &mut dyn FnMut(i32, i32, i32, Cell)) {
        for (&(x, y, z), &c) in &self.cells {
            if x >= lo[0] && x < hi[0] && y >= lo[1] && y < hi[1] && z >= lo[2] && z < hi[2] {
                put(x, y, z, c);
            }
        }
    }
}

/// Un asset de 2 cm posé dans une scène : son plan et son origine en millimètres monde (hors de la grille de 5 cm).
#[derive(Clone)]
pub struct SmallAsset {
    /// Le plan (`voxel_mm() == 20`).
    pub plan: Arc<dyn GenPlan>,
    /// Origine locale du plan (coin sud-ouest, au sol), en millimètres monde.
    pub origin_mm: [i64; 3],
}

/// Un plan de culture : une forme, ses teintes, sa grille de 2 cm.
pub struct CropPlan {
    shape: Box<dyn CropShape>,
    tint: TintTable,
    wood: MaterialId,
    soil: MaterialId,
}

impl CropPlan {
    fn valeur(&self, c: Cell) -> VoxelValue {
        match c {
            Cell::Leaf(v) => self.tint.value(VxmKind::Leaf, v),
            Cell::Fruit(v) => self.tint.value(VxmKind::Fruit, v),
            Cell::Petal(v) => self.tint.value(VxmKind::Flower, v),
            Cell::Bark(v) => self.tint.value(VxmKind::Bark, v),
            Cell::Stake(v) => VoxelValue::new(self.wood, tint_wood(GrainAxis::Y as u8, v.min(31))),
            Cell::Soil(t) => VoxelValue::new(self.soil, t.min(127)),
        }
    }

    /// Dimensions en voxels de 2 cm.
    pub fn size(&self) -> [i32; 3] {
        self.shape.size()
    }
}

impl GenPlan for CropPlan {
    fn bounds(&self, lod: Lod) -> VoxelBox {
        let s = self.shape.size();
        let (a, b) = if lod == 0 {
            (VoxelCoord::new(s[0], s[1], s[2]), 1)
        } else {
            (VoxelCoord::new(1, 1, 1), 0)
        };
        let _ = b;
        VoxelBox::new(VoxelCoord::new(0, 0, 0), a).unwrap_or_else(|_| {
            VoxelBox::new(VoxelCoord::new(0, 0, 0), VoxelCoord::new(1, 1, 1)).expect("boîte unité")
        })
    }

    fn rasterize(&self, lod: Lod, window: VoxelBox, sink: &mut dyn VoxelSink) {
        if lod != 0 {
            return;
        }
        let s = self.shape.size();
        let (a, b) = (window.min(), window.max());
        let lo = [a.x.max(0), a.y.max(0), a.z.max(0)];
        let hi = [b.x.min(s[0]), b.y.min(s[1]), b.z.min(s[2])];
        if lo[0] >= hi[0] || lo[1] >= hi[1] || lo[2] >= hi[2] {
            return;
        }
        self.shape.fill(lo, hi, &mut |x, y, z, c| {
            sink.put(VoxelCoord::new(x, y, z), self.valeur(c), PutMode::Solid)
        });
    }

    fn voxel_mm(&self) -> u32 {
        VOXEL_MM
    }
}

/// Genre de culture d'une parcelle.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CropKind {
    /// Rangs de blé.
    Wheat,
    /// Choux.
    Cabbage,
    /// Vigne sur échalas.
    Vine,
    /// Champ labouré.
    Plowed,
}

impl CropKind {
    fn species(self) -> &'static str {
        match self {
            CropKind::Wheat => "ble",
            CropKind::Cabbage => "chou",
            CropKind::Vine => "vigne",
            CropKind::Plowed => "ble",
        }
    }
}

/// Paramètres d'une parcelle de culture (jusqu'à 20 m × 20 m).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CropParams {
    /// Genre de culture.
    pub kind: CropKind,
    /// Largeur est-ouest en millimètres (20 000 au plus).
    #[serde(default = "parcelle")]
    pub width_mm: u32,
    /// Profondeur sud-nord en millimètres (20 000 au plus).
    #[serde(default = "parcelle")]
    pub depth_mm: u32,
}

fn parcelle() -> u32 {
    20_000
}

impl CropParams {
    /// Paramètres de générateur.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(GeneratorId::CROP, 1, self)
    }
}

/// Générateur de parcelles de culture de 2 cm.
#[derive(Clone, Debug)]
pub struct CropGenerator {
    table: Arc<SpeciesTable>,
    classes: CropClasses,
}

impl CropGenerator {
    /// Générateur sur une table d'essences et des classes injectées.
    pub fn new(table: Arc<SpeciesTable>, classes: CropClasses) -> Self {
        Self { table, classes }
    }
}

fn plan_de(
    table: &SpeciesTable,
    classes: &CropClasses,
    espece: &str,
    shape: Box<dyn CropShape>,
) -> Result<Arc<dyn GenPlan>, GenError> {
    let sp = table.get(espece)?;
    Ok(Arc::new(CropPlan {
        shape,
        tint: TintTable::new(&classes.veg, sp.slot)?,
        wood: classes.wood,
        soil: classes.soil,
    }))
}

impl Generator for CropGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::CROP
    }
    fn version(&self) -> u32 {
        1
    }
    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let p: CropParams = params.decode_json(GeneratorId::CROP)?;
        if !(500..=20_000).contains(&p.width_mm) || !(500..=20_000).contains(&p.depth_mm) {
            return Err(GenError::BadParams(
                "culture : parcelle de 0,5 à 20 m de côté".into(),
            ));
        }
        let (w, d) = ((p.width_mm / VOXEL_MM) as i32, (p.depth_mm / VOXEL_MM) as i32);
        let shape: Box<dyn CropShape> = match p.kind {
            CropKind::Wheat => Box::new(Wheat {
                seed,
                size: [w, 56, d],
            }),
            CropKind::Cabbage => Box::new(Cabbages {
                seed,
                size: [w, 24, d],
            }),
            CropKind::Vine => Box::new(Vines {
                seed,
                size: [w, 52, d],
            }),
            CropKind::Plowed => Box::new(Plowed {
                seed,
                size: [w, 8, d],
            }),
        };
        plan_de(&self.table, &self.classes, p.kind.species(), shape)
    }
}

/// Paramètres d'une touffe de champignons.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MushroomParams {
    /// `cepe` (chapeau brun) ou `amanite` (chapeau rouge à points blancs).
    pub kind: String,
    /// Nombre de champignons (1 à 16).
    #[serde(default = "huit")]
    pub count: u32,
    /// Rayon de la touffe en millimètres.
    #[serde(default = "rayon_touffe")]
    pub radius_mm: u32,
}

fn huit() -> u32 {
    8
}
fn rayon_touffe() -> u32 {
    300
}

/// Générateur de touffes de champignons (voxels de 2 cm).
#[derive(Clone, Debug)]
pub struct MushroomGenerator {
    table: Arc<SpeciesTable>,
    classes: CropClasses,
}

impl MushroomGenerator {
    /// Générateur sur une table d'essences et des classes injectées.
    pub fn new(table: Arc<SpeciesTable>, classes: CropClasses) -> Self {
        Self { table, classes }
    }
}

impl Generator for MushroomGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::MUSHROOMS
    }
    fn version(&self) -> u32 {
        1
    }
    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let p: MushroomParams = params.decode_json(GeneratorId::MUSHROOMS)?;
        let amanite = match p.kind.as_str() {
            "cepe" => false,
            "amanite" => true,
            autre => {
                return Err(GenError::BadParams(format!(
                    "champignon « {autre} » inconnu (cepe, amanite)"
                )));
            }
        };
        if !(1..=16).contains(&p.count) || !(100..=2000).contains(&p.radius_mm) {
            return Err(GenError::BadParams(
                "champignons : 1 à 16 pieds, rayon de 100 à 2000 mm".into(),
            ));
        }
        let mut rng = Stream::new(seed, 0x4D55_5348);
        let r = (p.radius_mm / VOXEL_MM) as i32;
        let mut s = Stamped::new();
        for k in 0..p.count {
            let ang = rng.unit();
            let dist = fx::mul(fx::sqrt(rng.unit()), i64::from(r) * UN) >> 16;
            let (cx, cz) = (
                r + 8 + ((fx::cos(ang) * dist) >> 16) as i32,
                r + 8 + ((fx::sin(ang) * dist) >> 16) as i32,
            );
            let hs = 5 + rng.integers(0, 8) as i32;
            let rc = 3 + rng.integers(0, 4) as i32;
            let rs = if rc >= 5 { 2 } else { 1 };
            // pied
            for y in 0..hs {
                for dx in -rs..=rs {
                    for dz in -rs..=rs {
                        if dx * dx + dz * dz <= rs * rs + i32::from(rs > 1) {
                            s.set((cx + dx, y, cz + dz), Cell::Bark(0));
                        }
                    }
                }
            }
            // chapeau : demi-ellipsoïde surbaissé
            let ry = (rc * 7 / 10).max(2);
            for dy in 0..=ry {
                for dx in -rc..=rc {
                    for dz in -rc..=rc {
                        let e =
                            dx * dx * 100 / (rc * rc) + dz * dz * 100 / (rc * rc) + dy * dy * 100 / (ry * ry);
                        if e <= 100 {
                            let dessus = e > 78;
                            let point = amanite && dessus && dy >= 1 && rng.chance(UN * 14 / 100);
                            let c = if point {
                                Cell::Petal(0)
                            } else {
                                Cell::Fruit(u8::from(amanite))
                            };
                            s.set((cx + dx, hs - 1 + dy, cz + dz), c);
                        }
                    }
                }
            }
            let _ = k;
        }
        plan_de(&self.table, &self.classes, "champignon", Box::new(s))
    }
}

/// Paramètres d'une touffe de fougères.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FernParams {
    /// Nombre de frondes (4 à 16).
    #[serde(default = "dix")]
    pub fronds: u32,
    /// Longueur d'une fronde en millimètres.
    #[serde(default = "longueur_fronde")]
    pub length_mm: u32,
}

fn dix() -> u32 {
    10
}
fn longueur_fronde() -> u32 {
    700
}

/// Générateur de fougères (voxels de 2 cm) : frondes arquées à pennes alternées.
#[derive(Clone, Debug)]
pub struct FernGenerator {
    table: Arc<SpeciesTable>,
    classes: CropClasses,
}

impl FernGenerator {
    /// Générateur sur une table d'essences et des classes injectées.
    pub fn new(table: Arc<SpeciesTable>, classes: CropClasses) -> Self {
        Self { table, classes }
    }
}

impl Generator for FernGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::FERNS
    }
    fn version(&self) -> u32 {
        1
    }
    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let p: FernParams = params.decode_json(GeneratorId::FERNS)?;
        if !(4..=16).contains(&p.fronds) || !(200..=1500).contains(&p.length_mm) {
            return Err(GenError::BadParams(
                "fougère : 4 à 16 frondes, 200 à 1500 mm".into(),
            ));
        }
        let mut rng = Stream::new(seed, 0x4645_524E);
        let long = (p.length_mm / VOXEL_MM) as i32;
        let c = long + 4;
        let mut s = Stamped::new();
        let n = i64::from(p.fronds);
        for k in 0..n {
            let ang = UN * k / n + fx::mul(rng.normal(), UN / 60);
            let l = ((i64::from(long) * rng.uniform(UN * 7 / 10, UN)) >> 16) as i32;
            let teinte = rng.integers(0, 2) as u8;
            let (ca, sa) = (fx::cos(ang), fx::sin(ang));
            let (pa, pb) = (-sa, ca); // perpendiculaire horizontale
            for t in 0..=l {
                // arc : monte, puis retombe
                let dist = i64::from(t);
                let y = 2 + (l * 6 / 10) * 4 * t * (l - t) / (l * l).max(1) + t / 5;
                let (px, pz) = (c + ((ca * dist) >> 16) as i32, c + ((sa * dist) >> 16) as i32);
                s.set((px, y.max(0), pz), Cell::Leaf(teinte));
                // pennes de chaque côté, plus courtes vers la pointe, un cran plus basses (elles retombent)
                if t > 2 && t % 2 == 0 {
                    let larg = (((4 * fx::sin(UN * i64::from(t) / i64::from(l.max(1)) / 2)) >> 16) as i32)
                        .max(1)
                        + 1;
                    for w in 1..=larg {
                        for cote in [-1_i64, 1] {
                            let (ox, oz) = (
                                ((pa * cote * i64::from(w)) >> 16) as i32,
                                ((pb * cote * i64::from(w)) >> 16) as i32,
                            );
                            s.set(
                                (px + ox, (y - i32::from(w > 2)).max(0), pz + oz),
                                Cell::Leaf(teinte),
                            );
                        }
                    }
                }
            }
        }
        plan_de(&self.table, &self.classes, "fougere", Box::new(s))
    }
}
