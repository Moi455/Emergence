//! L'ASPECT de la maison : traduit les couleurs RVB du JavaScript en (classe de matière, teinte). Un voxel reste UNE
//! couleur plate ; la variation entre voxels vient de la teinte (numéro de pierre, variante du fil du bois, nuance de la
//! rampe) posée ici par hachage de la POSITION ENTIÈRE, jamais d'un bruit sous-voxel.

use em_core::{MaterialId, VoxelValue};

use super::furniture::Paint;
use super::params::{Accent, HouseParams, StoneTone, TileKind};
use crate::batiments::kit::matieres::{Matieres, Ton, bois, pierre, ton, val};
use crate::batiments::kit::rng::{hh, hh_below, hh_lt};

/// Options de rendu de la maison (n'ont pas d'effet sur le plan).
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct HouseOptions {
    /// Pose un vitrage (verre et petits bois) dans les fenêtres ; sinon trous nus (parité avec les `.vxh`).
    pub glazing: bool,
    /// Pose un battant de bois dans la porte d'entrée.
    pub door_leaf: bool,
    /// Pose le sol du jardin (chemin, herbe) ; sinon rien (le terrain s'en charge).
    pub garden: bool,
}

impl HouseOptions {
    /// Réglages des recettes du village : vitres, porte, sans jardin.
    pub const fn village() -> Self {
        Self {
            glazing: true,
            door_leaf: true,
            garden: false,
        }
    }

    /// Réglages de la parité avec les `.vxh` (trous nus, pas de battant).
    pub const fn parite() -> Self {
        Self {
            glazing: false,
            door_leaf: false,
            garden: false,
        }
    }
}

/// Table de traduction d'une maison.
#[derive(Copy, Clone, Debug)]
pub struct Look {
    /// Classes de matière.
    pub m: Matieres,
    /// Classe de la pierre des murs.
    pub stone: MaterialId,
    /// Classe de la couverture.
    pub tile: MaterialId,
    /// Type de couverture.
    pub tile_kind: TileKind,
    /// Accent (volets et porte).
    pub window_accent: Accent,
    /// Accent de la porte.
    pub door_accent: Accent,
}

impl Look {
    /// Aspect explicite (bâtiments autres que la maison).
    pub fn custom(
        m: Matieres,
        stone: StoneTone,
        tile: TileKind,
        window_accent: Accent,
        door_accent: Accent,
    ) -> Self {
        Self {
            m,
            stone: match stone {
                StoneTone::Warm => m.cut_stone,
                StoneTone::Grey => m.stone_grey,
                StoneTone::Dark => m.stone_dark,
            },
            tile: match tile {
                TileKind::Slate => m.slate,
                TileKind::Shingle => m.leather,
                TileKind::Terracotta => m.roof_tile,
                TileKind::Thatch => m.thatch,
            },
            tile_kind: tile,
            window_accent,
            door_accent,
        }
    }

    /// Aspect de ces paramètres.
    pub fn new(m: Matieres, p: &HouseParams) -> Self {
        Self {
            m,
            stone: match p.wall.stone {
                StoneTone::Warm => m.cut_stone,
                StoneTone::Grey => m.stone_grey,
                StoneTone::Dark => m.stone_dark,
            },
            tile: match p.roof.tile {
                TileKind::Slate => m.slate,
                TileKind::Shingle => m.leather,
                TileKind::Terracotta => m.roof_tile,
                TileKind::Thatch => m.thatch,
            },
            tile_kind: p.roof.tile,
            window_accent: p.win.color,
            door_accent: p.door.color,
        }
    }

    /// Bois de charpente (colombage, poutres), `axe` : 0 x, 1 y, 2 z.
    pub fn timber(&self, a: i32, b: i32, c: i32, axe: u8) -> VoxelValue {
        bois(self.m.timber, axe, (hh(a, b, c, 1) % 11) as u8 + 3)
    }

    /// Bois sombre (sous-faces, joints).
    pub fn timber_dark(&self, axe: u8) -> VoxelValue {
        bois(self.m.timber, axe, 0)
    }

    /// Bois clair (tonneaux, rampes).
    pub fn wood_light(&self, a: i32, b: i32, c: i32, axe: u8) -> VoxelValue {
        bois(self.m.oak_raw, axe, (hh(a, b, c, 2) % 12) as u8 + 2)
    }

    /// Fer.
    pub fn iron(&self, a: i32, b: i32, c: i32) -> VoxelValue {
        val(self.m.iron, 30 + (hh(a, b, c, 3) % 22) as u8)
    }

    /// Pierre d'encadrement (appuis, linteaux, marches).
    pub fn trim_stone(&self, a: i32, b: i32, c: i32) -> VoxelValue {
        pierre(
            self.stone,
            1 + (hh(a.div_euclid(6), b.div_euclid(4), c.div_euclid(5), 4) % 126) as u8,
        )
    }

    /// Une peinture d'accent (volet, porte) ; `v` : variation 0..30.
    pub fn accent(&self, a: Accent, axe: u8, v: u8, p: (i32, i32, i32)) -> VoxelValue {
        let t = 40 + (hh(p.0, p.1, p.2, 5) % 30) as u8 + v;
        match a {
            Accent::Brown => bois(self.m.wood_trim, axe, (hh(p.0, p.1, p.2, 6) % 12) as u8 + 6),
            Accent::Green => val(self.m.paint_green, t),
            Accent::Blue => val(self.m.paint_blue, t),
            Accent::Red => val(self.m.paint_red, t),
        }
    }

    /// Plâtre du colombage, plus sale près du sol.
    pub fn plaster(&self, x: i32, v: i32, z: i32, bas: i32) -> VoxelValue {
        let sale = ((bas - v).max(0) * 60 / bas.max(1)).min(60);
        val(
            self.m.plaster,
            (112 - sale + (hh(x, v, z, 7) % 8) as i32).clamp(10, 127) as u8,
        )
    }

    /// Plancher (sol de rez-de-chaussée et d'étage).
    pub fn floor(&self, x: i32, z: i32) -> VoxelValue {
        let t = if (x + z * 3).rem_euclid(11) == 0 {
            28
        } else {
            55 + (hh(x, 0, z, 8) % 14) as u8
        };
        val(self.m.oak_planks, t)
    }

    /// Plafond / plancher d'étage vu d'en dessous.
    pub fn ceiling(&self, x: i32, v: i32, z: i32) -> VoxelValue {
        val(self.m.oak_planks, 40 + (hh(x, v, z, 9) % 14) as u8)
    }

    /// Cloison de plâtre beige.
    pub fn partition(&self, x: i32, v: i32, z: i32) -> VoxelValue {
        val(self.m.plaster, 70 + (hh(x, v, z, 10) % 8) as u8)
    }

    /// Marche d'escalier (`dessus` : la tranche claire).
    pub fn step(&self, x: i32, v: i32, z: i32, dessus: bool) -> VoxelValue {
        if dessus {
            val(self.m.oak_planks, 80 + (hh(x, v, z, 11) % 10) as u8)
        } else {
            val(self.m.oak_planks, 36 + (hh(x, v, z, 11) % 10) as u8)
        }
    }

    /// Tuile de couverture : `sl_k` longueur oblique en 1/2^20 voxel, `col` colonne, (x, z) cellule.
    pub fn roof_tile(&self, sl_k: i64, col: i32, x: i32, z: i32, moss100: i32) -> VoxelValue {
        let un = 1_i64 << 20;
        let row = sl_k.div_euclid(5 * un);
        let fr = sl_k - row * 5 * un;
        let off = col + (row as i32 & 1) * 3;
        let t = hh(row as i32, off.div_euclid(6), 4, 0);
        let base = match hh_below(t, 100) {
            0..=39 => 50,
            40..=74 => 28,
            _ => 82,
        };
        let joint = fr < un || off.rem_euclid(6) == 0;
        let teinte = if joint {
            6
        } else {
            base + (hh(x, row as i32, z, 12) % 10) as u8
        };
        // mousse : taches lisses, plus rares sur les pentes sèches
        let n = u64::from(crate::batiments::kit::noise::vnoise2(x * 2, z * 2, 14, 5)) * 70
            + u64::from(crate::batiments::kit::noise::vnoise2(x * 3, z * 3, 10, 6)) * 30;
        let seuil = (100 - u64::try_from(moss100).unwrap_or(0) * 9 / 10) * 65_536;
        if !joint && n > seuil {
            return val(self.m.moss, 44 + (hh(x, row as i32, z, 13) % 50) as u8);
        }
        val(self.tile, teinte)
    }

    /// Faîtière.
    pub fn ridge(&self, x: i32, v: i32, z: i32) -> VoxelValue {
        val(self.tile, 12 + (hh(x, v, z, 14) % 8) as u8)
    }

    /// Résout une intention de peinture de meuble.
    pub fn paint(&self, p: Paint, pos: (i32, i32, i32), tone: u8) -> (VoxelValue, bool) {
        let h = hh(pos.0, pos.1, pos.2, 21);
        let m = &self.m;
        let v = match p {
            Paint::Wood => bois(m.oak_raw, 1, 4 + tone * 2 + (h % 6) as u8),
            Paint::WoodDark => bois(m.timber, 1, 1 + tone),
            Paint::WoodLight => bois(m.oak_raw, 1, 5 + (h % 8) as u8),
            Paint::Iron => val(m.iron, 30 + (h % 14) as u8),
            Paint::IronDark => val(m.iron, 6 + (h % 8) as u8),
            Paint::Steel => val(m.iron, 100 + (h % 14) as u8),
            Paint::Linen => val(m.cloth, 100 + (h % 8) as u8),
            Paint::Pillow => val(m.cloth, 124 + (h % 4) as u8),
            Paint::Fabric(n) => fabric(m, n, 0),
            Paint::FabricDark(n) => fabric(m, n, 1),
            Paint::Brass => val(m.brass, 70 + (h % 20) as u8),
            Paint::StoneTop => pierre(m.stone_grey, 1 + (h % 4) as u8 * 3),
            Paint::StoneDark => pierre(m.stone_dark, 1 + (h % 90) as u8),
            Paint::Coal => val(m.coal, 20 + (h % 20) as u8),
            Paint::Ember => return (val(m.ember, 40 + (h % 80) as u8), true),
            Paint::Wax => val(m.wax, 70 + (h % 40) as u8),
            Paint::Flame => return (ton(m.glow, Ton::Moyen), true),
            Paint::Ceramic(t) => val(m.ceramic, t.saturating_add((h % 12) as u8).min(127)),
            Paint::Bread => val(m.hay, 70 + (h % 20) as u8),
            Paint::Leaf => val(m.moss, 55 + (h % 55) as u8),
            Paint::Soil => val(m.dirt, 10 + (h % 20) as u8),
            Paint::Water => val(m.paint_blue, 100 + (h % 20) as u8),
            Paint::Glass => val(m.glass, 64),
            Paint::Plaster => val(m.plaster, 118 + (h % 8) as u8),
            Paint::PaintBlue => val(m.paint_blue, 100 + (h % 25) as u8),
            Paint::PaintGreen => val(m.paint_green, 90 + (h % 30) as u8),
            Paint::PaintRed => val(m.paint_red, 60 + (h % 30) as u8),
            Paint::Leather => val(m.leather, 30 + (h % 20) as u8),
            Paint::FruitRed => ton(m.flower_b, Ton::Moyen),
            Paint::FruitYellow => ton(m.flower_a, Ton::Moyen),
        };
        (v, false)
    }

    /// Couleur d'une fleur de jardinière : blanc, jaune, rose, violet.
    pub fn flower(&self, n: u32) -> VoxelValue {
        match n % 4 {
            0 => ton(self.m.flower_a, Ton::Sombre),
            1 => ton(self.m.flower_a, Ton::Moyen),
            2 => ton(self.m.flower_a, Ton::Clair),
            _ => ton(self.m.flower_b, Ton::Sombre),
        }
    }

    /// Feuillage de jardinière.
    pub fn leaf(&self, a: i32, b: i32, c: i32) -> VoxelValue {
        val(self.m.moss, 50 + (hh(a, b, c, 15) % 60) as u8)
    }
}

fn fabric(m: &Matieres, n: u8, sombre: u8) -> VoxelValue {
    let (cls, t) = match n % 6 {
        0 => (m.fabric_a, Ton::Sombre),
        1 => (m.fabric_a, Ton::Moyen),
        2 => (m.fabric_a, Ton::Clair),
        3 => (m.fabric_b, Ton::Sombre),
        4 => (m.fabric_b, Ton::Moyen),
        _ => (m.fabric_b, Ton::Clair),
    };
    let v = ton(cls, t);
    if sombre == 1 {
        // teinte voisine, un peu plus sombre
        val(cls, v.tint().saturating_sub(10))
    } else {
        v
    }
}

/// Aide : `hh(...) < pct` sur trois entiers et un sel.
pub fn rare(a: i32, b: i32, c: i32, sel: i32, pct: u32) -> bool {
    hh_lt(hh(a, b, c, sel), pct)
}
