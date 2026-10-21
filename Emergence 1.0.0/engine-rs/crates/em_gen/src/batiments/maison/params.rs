//! `HouseParams` : la graine dérivée en paramètres, port exact de `derive(seed)` de « nouvelle référence.html ».
//!
//! Chaque partie de la maison est pilotée par un bloc de paramètres (corps principal, aile, murs, toit, fenêtres,
//! porte, cheminée, appentis, décor). L'ORDRE des tirages est celui du JavaScript : un tirage de plus ou de moins
//! décalerait tous les suivants. Les flottants du JavaScript (`f2`, pentes, pourcentages) deviennent des centièmes.

use serde::{Deserialize, Serialize};

use crate::batiments::kit::rng::{JsRng, hs};

/// Plan au sol.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum PlanKind {
    /// Un seul corps.
    Rect,
    /// Corps principal et aile en équerre.
    L,
    /// Aile centrée.
    T,
}

/// Style des murs.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum WallStyle {
    /// Pierre apparente.
    Stone,
    /// Colombage et remplissage de pierre.
    TimberStone,
    /// Colombage et remplissage de plâtre.
    TimberPlaster,
}

/// Teinte de la pierre.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum StoneTone {
    /// Chaude.
    Warm,
    /// Grise.
    Grey,
    /// Sombre.
    Dark,
}

/// Couverture.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum TileKind {
    /// Ardoise.
    Slate,
    /// Bardeaux de bois.
    Shingle,
    /// Tuiles rouges.
    Terracotta,
    /// Chaume.
    Thatch,
}

/// Couleur des volets et de la porte.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Accent {
    /// Bois brun.
    Brown,
    /// Vert.
    Green,
    /// Bleu.
    Blue,
    /// Rouge.
    Red,
}

/// Côté de la cheminée.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Side {
    /// Est (x croissant).
    E,
    /// Ouest.
    W,
}

/// Dimensions d'un corps de bâtiment (voxels).
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MainBody {
    /// Largeur (le faîtage court le long de x).
    pub w: i32,
    /// Profondeur.
    pub d: i32,
}

/// L'aile.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Wing {
    /// Largeur de l'aile.
    pub w: i32,
    /// Longueur dépassant du corps principal.
    pub len: i32,
    /// 0 : contre le bord ouest, 1 : contre le bord est (plan en L).
    pub at: i32,
    /// +1 : vers le sud (façade), -1 : vers le nord.
    pub dir: i32,
}

/// Murs.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WallParams {
    /// Style.
    pub style: WallStyle,
    /// Teinte de la pierre.
    pub stone: StoneTone,
    /// Espacement des poteaux du colombage (voxels).
    pub posts: i32,
}

/// Toit.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RoofParams {
    /// Pente en centièmes (100 à 150 : un voxel de montée pour 1 à 1,5 de course).
    pub slope100: i32,
    /// Débord d'égout.
    pub eave: i32,
    /// Débord de pignon.
    pub rake: i32,
    /// Couverture.
    pub tile: TileKind,
    /// Part de mousse en centièmes.
    pub moss100: i32,
}

/// Fenêtres.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WindowParams {
    /// Largeur.
    pub w: i32,
    /// Hauteur.
    pub h: i32,
    /// Hauteur d'allège.
    pub sill: i32,
    /// Cintrées.
    pub arch: bool,
    /// Avec volets.
    pub shutters: bool,
    /// Avec jardinière.
    pub box_: bool,
    /// Couleur des volets.
    pub color: Accent,
    /// Part de fenêtres allumées, en centièmes.
    pub lit100: i32,
    /// Espacement visé entre fenêtres.
    pub gap: i32,
}

/// Porte d'entrée.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DoorParams {
    /// Largeur.
    pub w: i32,
    /// Hauteur.
    pub h: i32,
    /// Cintrée.
    pub arch: bool,
    /// Position le long de la façade, en centièmes.
    pub at100: i32,
    /// Avec auvent (perron).
    pub porch: bool,
    /// Couleur.
    pub color: Accent,
}

/// Décor.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecoParams {
    /// Tonneaux devant la façade (1 à 3).
    pub barrels: i32,
    /// Densité de fleurs, en centièmes.
    pub flowers100: i32,
    /// Densité d'herbes hautes, en centièmes.
    pub grass100: i32,
}

/// Tous les paramètres d'une maison.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct HouseParams {
    /// Texte de la graine (le JavaScript hache une chaîne).
    pub seed: String,
    /// Nombre d'étages (1 ou 2).
    pub stories: i32,
    /// Corps principal.
    pub main: MainBody,
    /// Plan au sol.
    pub plan: PlanKind,
    /// Aile.
    pub wing: Wing,
    /// Murs.
    pub wall: WallParams,
    /// Toit.
    pub roof: RoofParams,
    /// Fenêtres.
    pub win: WindowParams,
    /// Porte.
    pub door: DoorParams,
    /// Côté de la cheminée.
    pub chimney: Side,
    /// Appentis à bois.
    pub shed: bool,
    /// Décor.
    pub deco: DecoParams,
}

impl HouseParams {
    /// `derive(seed)`.
    pub fn derive(seed: &str) -> Self {
        let mut r = JsRng::new(hs(seed));
        let d = r.int(88, 112);
        let stories = r.pick(&[1, 2, 2]);
        let main = MainBody {
            w: r.int(116, 152),
            d,
        };
        let plan = r.pick(&[PlanKind::Rect, PlanKind::L, PlanKind::L, PlanKind::T]);
        let wing = Wing {
            w: r.int(56, 76.min(d * 78 / 100)),
            len: r.int(46, 84),
            at: r.pick(&[0, 1]),
            dir: r.pick(&[1, -1]),
        };
        let wall = WallParams {
            style: r.pick(&[
                WallStyle::Stone,
                WallStyle::Stone,
                WallStyle::TimberStone,
                WallStyle::TimberPlaster,
            ]),
            stone: r.pick(&[StoneTone::Warm, StoneTone::Grey, StoneTone::Dark]),
            posts: r.int(40, 56),
        };
        let roof = RoofParams {
            slope100: r.hundredths(100, 150),
            eave: r.int(8, 12),
            rake: r.int(5, 8),
            tile: r.pick(&[
                TileKind::Slate,
                TileKind::Slate,
                TileKind::Shingle,
                TileKind::Terracotta,
            ]),
            moss100: r.hundredths(15, 55),
        };
        let accents = [Accent::Brown, Accent::Green, Accent::Blue, Accent::Red];
        let win = WindowParams {
            w: r.pick(&[14, 16, 18]),
            h: r.int(20, 24),
            sill: r.int(16, 20),
            arch: r.percent(35),
            shutters: r.percent(75),
            box_: r.percent(60),
            color: r.pick(&accents),
            lit100: r.hundredths(50, 95),
            gap: r.int(44, 58),
        };
        let door = DoorParams {
            w: 20,
            h: 40,
            arch: r.half(),
            at100: r.hundredths(30, 70),
            porch: r.percent(85),
            color: r.pick(&accents),
        };
        let chimney = r.pick(&[Side::E, Side::W]);
        let shed = r.percent(80);
        let deco = DecoParams {
            barrels: r.int(1, 3),
            flowers100: r.hundredths(1, 5),
            grass100: r.hundredths(4, 12),
        };
        Self {
            seed: seed.to_owned(),
            stories,
            main,
            plan,
            wing,
            wall,
            roof,
            win,
            door,
            chimney,
            shed,
            deco,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gravit_derive_comme_le_javascript() {
        let p = HouseParams::derive("gravit");
        assert_eq!((p.stories, p.main.w, p.main.d), (1, 150, 97));
        assert_eq!(p.plan, PlanKind::Rect);
        assert_eq!(
            p.wing,
            Wing {
                w: 71,
                len: 75,
                at: 0,
                dir: 1
            }
        );
        assert_eq!(
            (p.wall.style, p.wall.stone, p.wall.posts),
            (WallStyle::Stone, StoneTone::Grey, 51)
        );
        assert_eq!(
            (p.roof.slope100, p.roof.eave, p.roof.rake, p.roof.tile),
            (116, 11, 8, TileKind::Slate)
        );
        assert_eq!(p.roof.moss100, 22);
        assert_eq!((p.win.w, p.win.h, p.win.sill, p.win.arch), (16, 23, 18, true));
        assert_eq!(p.win.lit100, 79);
        assert_eq!(
            (p.door.arch, p.door.at100, p.door.porch, p.door.color),
            (true, 33, true, Accent::Red)
        );
        assert_eq!((p.chimney, p.shed), (Side::W, true));
        assert_eq!((p.deco.barrels, p.deco.flowers100, p.deco.grass100), (1, 4, 8));
    }
}
