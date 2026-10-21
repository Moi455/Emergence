//! Le générateur de MAISON (L35) : port Rust de `derive` et `build` de « nouvelle référence.html ». Une graine (texte)
//! donne des `HouseParams` ; le planificateur (`planner`) décide tout (emprise, murs, toit, porte, fenêtres, cloisons,
//! pièces, meubles) avec le hasard du JavaScript ; les parties (`parts`, `parts2`) peignent à la demande.

mod extras;
pub mod furniture;
pub mod look;
pub mod params;
pub mod parts;
pub mod parts2;
pub mod planner;

use std::sync::Arc;

use serde::{Deserialize, Serialize};

pub use look::{HouseOptions, Look};
pub use params::{HouseParams, PlanKind, WallStyle};
pub use planner::{HousePlan, RoomType, planifier};

use super::ids;
use super::kit::matieres::Matieres;
use super::kit::plan::{Part, Placement, ShapePlan};
use super::kit::window::Window;
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};
use parts::{ChimneyPart, Ctx, DoorPart, RoofPart, ShedPart, WallsPart};
use parts2::{BarrelPart, CutPart, GardenPart, HearthPart, InteriorPart, StairsPart, VentPart, WindowPart};

/// Configuration de la recette de maison.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct HouseConfig {
    /// Texte de la graine du générateur JavaScript ; vide : le nombre de la graine de recette.
    pub seed_text: String,
    /// Vitrage dans les fenêtres.
    pub glazing: bool,
    /// Battant dans la porte d'entrée.
    pub door_leaf: bool,
    /// Sol du jardin (chemin, herbe, fleurs).
    pub garden: bool,
    /// Repère brut du JavaScript (x vers l'est, z vers le sud, origine au coin) au lieu du repère du monde (centre au
    /// sol, porte vers le sud = z négatif).
    pub raw_frame: bool,
    /// Étages (1 ou 2) ; 0 : tirés de la graine.
    pub stories: i32,
    /// Plan (`rect`, `l`, `t`) ; vide : tiré de la graine.
    pub plan: String,
    /// Murs (`stone`, `timber_stone`, `timber_plaster`) ; vide : tirés de la graine.
    pub walls: String,
    /// Couverture (`slate`, `shingle`, `terracotta`) ; vide : tirée de la graine.
    pub tile: String,
    /// Largeur du corps principal ; 0 : tirée de la graine.
    pub width: i32,
    /// Profondeur du corps principal ; 0 : tirée de la graine.
    pub depth: i32,
    /// Appentis : `auto` (graine), `oui`, `non`.
    pub shed: String,
    /// Détails ajoutés selon la fonction du bâtiment : vide, `taverne`, `boulangerie`, `mairie`.
    pub extras: String,
}

impl Default for HouseConfig {
    fn default() -> Self {
        Self {
            seed_text: String::new(),
            glazing: true,
            door_leaf: true,
            garden: false,
            raw_frame: false,
            stories: 0,
            plan: String::new(),
            walls: String::new(),
            tile: String::new(),
            width: 0,
            depth: 0,
            shed: String::new(),
            extras: String::new(),
        }
    }
}

impl HouseConfig {
    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(ids::HOUSE, 1, self)
    }

    /// Applique les forçages de la configuration aux paramètres tirés de la graine (le hasard du plan n'en est pas
    /// affecté : les tirages gardent leur ordre).
    pub fn apply(&self, p: &mut HouseParams) -> Result<(), GenError> {
        use params::{TileKind, WallStyle as W};
        if self.stories > 0 {
            p.stories = self.stories.min(2);
        }
        p.plan = match self.plan.as_str() {
            "" => p.plan,
            "rect" => PlanKind::Rect,
            "l" => PlanKind::L,
            "t" => PlanKind::T,
            autre => {
                return Err(GenError::BadParams(format!(
                    "plan « {autre} » inconnu (rect, l, t)"
                )));
            }
        };
        p.wall.style = match self.walls.as_str() {
            "" => p.wall.style,
            "stone" => W::Stone,
            "timber_stone" => W::TimberStone,
            "timber_plaster" => W::TimberPlaster,
            autre => return Err(GenError::BadParams(format!("murs « {autre} » inconnus"))),
        };
        p.roof.tile = match self.tile.as_str() {
            "" => p.roof.tile,
            "slate" => TileKind::Slate,
            "shingle" => TileKind::Shingle,
            "terracotta" => TileKind::Terracotta,
            autre => return Err(GenError::BadParams(format!("couverture « {autre} » inconnue"))),
        };
        if self.width > 0 {
            p.main.w = self.width.clamp(90, 200);
        }
        if self.depth > 0 {
            p.main.d = self.depth.clamp(70, 140);
        }
        p.wing.w = p.wing.w.min(p.main.d * 78 / 100).min(p.main.w - 40);
        match self.shed.as_str() {
            "oui" => p.shed = true,
            "non" => p.shed = false,
            _ => {}
        }
        Ok(())
    }

    fn options(&self) -> HouseOptions {
        HouseOptions {
            glazing: self.glazing,
            door_leaf: self.door_leaf,
            garden: self.garden,
        }
    }
}

/// Une maison construite : son plan de décisions (pièces, portes, fenêtres) et son plan de rastérisation.
pub struct HouseModel {
    /// Le plan de décisions (lisible : pièces, meubles, fenêtres).
    pub layout: Arc<Ctx>,
    /// Le plan rastérisable.
    pub shape: ShapePlan,
}

impl HouseModel {
    /// Le plan de décisions.
    pub fn plan(&self) -> &HousePlan {
        &self.layout.plan
    }
}

/// Le générateur de maison.
#[derive(Clone, Debug)]
pub struct HouseGenerator {
    matieres: Matieres,
}

impl HouseGenerator {
    /// Crée le générateur avec ses classes de matière (injectées).
    pub fn new(matieres: Matieres) -> Self {
        Self { matieres }
    }

    /// Construit la maison d'une graine texte.
    pub fn build(&self, seed_text: &str, cfg: &HouseConfig) -> HouseModel {
        let mut params = HouseParams::derive(seed_text);
        cfg.apply(&mut params)
            .expect("forçages valides (vérifiés par `try_build`)");
        let plan = planifier(&params);
        let look = Look::new(self.matieres, &params);
        let ctx = Arc::new(Ctx {
            plan,
            look,
            opts: cfg.options(),
        });
        let mut parts = Self::parts(&ctx);
        parts.extend(extras::extras(&ctx, &cfg.extras, self.matieres));
        let p = &ctx.plan;
        let placement = if cfg.raw_frame {
            Placement::IDENTITE
        } else {
            let x0 = p.bodies.iter().map(|b| b.x0).min().unwrap_or(0);
            let x1 = p.bodies.iter().map(|b| b.x1).max().unwrap_or(0);
            let z0 = p.bodies.iter().map(|b| b.z0).min().unwrap_or(0);
            let z1 = p.bodies.iter().map(|b| b.z1).max().unwrap_or(0);
            Placement {
                dx: -((x0 + x1) / 2),
                dy: 0,
                dz: (z0 + z1) / 2,
                mirror_z: true,
            }
        };
        let shape = ShapePlan::new(parts, placement, 50, self.matieres.priority());
        HouseModel { layout: ctx, shape }
    }

    /// Comme `build`, en refusant des forçages invalides au lieu de paniquer.
    pub fn try_build(&self, seed_text: &str, cfg: &HouseConfig) -> Result<HouseModel, GenError> {
        let mut p = HouseParams::derive(seed_text);
        cfg.apply(&mut p)?;
        if !["", "taverne", "boulangerie", "mairie"].contains(&cfg.extras.as_str()) {
            return Err(GenError::BadParams(format!("extras « {} » inconnus", cfg.extras)));
        }
        Ok(self.build(seed_text, cfg))
    }

    fn parts(ctx: &Arc<Ctx>) -> Vec<Box<dyn Part>> {
        let p = &ctx.plan;
        let mut v: Vec<Box<dyn Part>> = Vec::new();
        if ctx.opts.garden {
            v.push(Box::new(GardenPart::new(ctx.clone(), false)));
        }
        v.push(Box::new(WallsPart::new(ctx.clone())));
        for b in 0..p.bodies.len() {
            v.push(Box::new(RoofPart::new(ctx.clone(), b)));
        }
        v.push(Box::new(DoorPart::new(ctx.clone())));
        v.push(Box::new(ChimneyPart::new(ctx.clone())));
        v.push(Box::new(ShedPart::new(ctx.clone())));
        for (s, cuts) in p.cuts.iter().enumerate() {
            for c in cuts {
                v.push(Box::new(CutPart::new(ctx.clone(), *c, s as i32)));
            }
        }
        v.push(Box::new(StairsPart::new(ctx.clone())));
        for w in &p.wins {
            v.push(Box::new(WindowPart::new(ctx.clone(), *w)));
        }
        for vent in &p.vents {
            v.push(Box::new(VentPart::new(ctx.clone(), vent)));
        }
        v.push(Box::new(HearthPart::new(ctx.clone())));
        v.push(Box::new(InteriorPart::new(ctx.clone())));
        // tonneaux : posés si l'emplacement est dégagé (emprise et voxels de la hauteur 0 déjà peints)
        let barrels = [(-28, -14), (p.params.door.w + 40, -16), (-46, -12)];
        for (k, (du, d)) in barrels.iter().enumerate() {
            if k as i32 >= p.params.deco.barrels.min(3) {
                break;
            }
            let u = p.du0 + du;
            if u < 6 || u > p.dfr.len - 6 {
                continue;
            }
            let (cx, cz) = p.dfr.xz(u, *d);
            let boite = em_core::VoxelBox::new(
                em_core::VoxelCoord::new(cx - 9, 0, cz - 9),
                em_core::VoxelCoord::new(cx + 10, 1, cz + 10),
            )
            .expect("boîte");
            let mut w = Window::new(boite);
            for part in &v {
                let b = part.bounds();
                let (a, c) = (b.min(), b.max());
                if a.x < cx + 10 && c.x > cx - 9 && a.z < cz + 10 && c.z > cz - 9 && a.y < 1 && c.y > 0 {
                    part.paint(&mut w);
                }
            }
            let mut ok = true;
            for a in (-8..=8).step_by(4) {
                for c in (-8..=8).step_by(4) {
                    if p.in_f(cx + a, cz + c) || !w.get(cx + a, 0, cz + c).is_air() {
                        ok = false;
                    }
                }
            }
            if ok {
                v.push(Box::new(BarrelPart::new(ctx.clone(), cx, cz)));
            }
        }
        if ctx.opts.garden {
            v.push(Box::new(GardenPart::new(ctx.clone(), true)));
        }
        v
    }
}

impl Generator for HouseGenerator {
    fn id(&self) -> GeneratorId {
        ids::HOUSE
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let cfg: HouseConfig = params.decode_json(ids::HOUSE)?;
        let texte = if cfg.seed_text.is_empty() {
            seed.to_string()
        } else {
            cfg.seed_text.clone()
        };
        Ok(Arc::new(self.try_build(&texte, &cfg)?.shape))
    }
}
