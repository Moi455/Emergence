//! `ShadowPlanner` : la machine à états CPU qui décide, image par image, quelles tuiles de quelles cascades on
//! remplit, et quelle génération l'éclairage doit lire. Aucun accès GPU : testable sans carte graphique.
//!
//! Chaque cascade a une génération AVANT (lue par l'éclairage) et peut en construire une ARRIÈRE (tuile par tuile).
//! Les deux vivent dans des couches différentes du tableau de textures (`c` et `c + cascades`) : on ne lit jamais
//! une couche à moitié remplie. La génération arrière devient avant quand sa dernière tuile est écrite.

use super::grid::{CascadePlacement, SOLEIL_Y_MIN, SunBasis};
use super::params::{Regeneration, ShadowParams};
use glam::DVec3;

/// Une tuile à remplir cette image.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TileJob {
    cascade: u32,
    tx: u32,
    ty: u32,
}

impl TileJob {
    /// Cascade de la tuile.
    pub fn cascade(&self) -> u32 {
        self.cascade
    }

    /// Colonne de la tuile.
    pub fn tx(&self) -> u32 {
        self.tx
    }

    /// Ligne de la tuile.
    pub fn ty(&self) -> u32 {
        self.ty
    }
}

/// Une génération de cascade : où elle est, avec quel soleil, dans quelle couche.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Generation {
    placement: CascadePlacement,
    basis: SunBasis,
    layer: u32,
}

impl Generation {
    /// Calage.
    pub fn placement(&self) -> &CascadePlacement {
        &self.placement
    }

    /// Base du soleil.
    pub fn basis(&self) -> &SunBasis {
        &self.basis
    }

    /// Couche du tableau de textures.
    pub fn layer(&self) -> u32 {
        self.layer
    }
}

struct Building {
    generation: Generation,
    next_tile: u32,
}

#[derive(Default)]
struct CascadeState {
    front: Option<Generation>,
    building: Option<Building>,
    /// 0 ou 1 : couche de la génération avant (`c + parité × cascades`).
    parity: u32,
    /// Une édition a touché cette cascade : refaire dès que possible.
    stale: bool,
}

/// Ce que le passe doit faire cette image.
#[derive(Debug, Clone, Default)]
pub struct FramePlan {
    jobs: Vec<TileJob>,
    /// Génération en construction de chaque cascade (utile seulement si elle a des tuiles dans `jobs`).
    building: Vec<Option<Generation>>,
    /// Génération avant de chaque cascade APRÈS les échanges de cette image.
    front: Vec<Option<Generation>>,
}

impl FramePlan {
    /// Tuiles à remplir.
    pub fn jobs(&self) -> &[TileJob] {
        &self.jobs
    }

    /// Génération en construction de la cascade `c`.
    pub fn building(&self, c: usize) -> Option<&Generation> {
        self.building.get(c).and_then(Option::as_ref)
    }

    /// Génération que l'éclairage lit pour la cascade `c`.
    pub fn front(&self, c: usize) -> Option<&Generation> {
        self.front.get(c).and_then(Option::as_ref)
    }
}

/// Planificateur des cascades.
pub struct ShadowPlanner {
    params: ShadowParams,
    cascades: Vec<CascadeState>,
}

impl ShadowPlanner {
    /// Planificateur pour ces réglages (aucune génération au départ).
    pub fn new(params: ShadowParams) -> Self {
        let cascades = (0..params.cascades()).map(|_| CascadeState::default()).collect();
        Self { params, cascades }
    }

    /// Réglages.
    pub fn params(&self) -> &ShadowParams {
        &self.params
    }

    /// Une édition a changé le monde : toutes les cascades sont refaites dès que possible.
    pub fn invalidate(&mut self) {
        for c in &mut self.cascades {
            c.stale = true;
        }
    }

    fn placement(&self, base: &SunBasis, camera: DVec3, c: u32) -> CascadePlacement {
        CascadePlacement::around(
            base,
            camera,
            self.params.texel_m(c),
            self.params.size(),
            self.params.quantum(),
        )
    }

    /// Planifie une image : `sun` est la direction VERS le soleil, `camera` la position monde absolue en mètres.
    pub fn plan(&mut self, sun: DVec3, camera: DVec3) -> FramePlan {
        let n = self.cascades.len();
        let mut plan = FramePlan {
            jobs: Vec::new(),
            building: vec![None; n],
            front: vec![None; n],
        };
        if !sun.is_finite() || sun.normalize_or_zero().y < SOLEIL_Y_MIN {
            // Soleil sous l'horizon : on oublie tout, l'éclairage ne lit plus d'ombre.
            for c in &mut self.cascades {
                *c = CascadeState::default();
            }
            return plan;
        }
        let base = SunBasis::new(sun);
        let cote = self.params.tiles_per_side();
        let par_cascade = cote * cote;
        let mut budget = self.params.tiles_per_frame();
        for ci in 0..n {
            let c = ci as u32;
            let voulu = self.placement(&base, camera, c);
            let etat = &self.cascades[ci];
            if etat.building.is_none() {
                let a_refaire = match &etat.front {
                    None => true,
                    Some(f) => {
                        etat.stale
                            || self.params.regeneration() == Regeneration::Continue
                            || f.basis.angle_deg(&base) > f64::from(self.params.sun_step_deg())
                            || self.placement(&f.basis, camera, c) != f.placement
                    }
                };
                if a_refaire {
                    let layer = c + (1 - etat.parity) * self.params.cascades();
                    let etat = &mut self.cascades[ci];
                    etat.stale = false;
                    etat.building = Some(Building {
                        generation: Generation {
                            placement: voulu,
                            basis: base,
                            layer,
                        },
                        next_tile: 0,
                    });
                }
            }
            let etat = &mut self.cascades[ci];
            if let Some(b) = &mut etat.building {
                // Sans génération avant, tout se remplit tout de suite (première image, captures reproductibles).
                let sans_avant = etat.front.is_none();
                plan.building[ci] = Some(b.generation);
                while b.next_tile < par_cascade && (sans_avant || budget > 0) {
                    plan.jobs.push(TileJob {
                        cascade: c,
                        tx: b.next_tile % cote,
                        ty: b.next_tile / cote,
                    });
                    b.next_tile += 1;
                    if !sans_avant {
                        budget -= 1;
                    }
                }
                if b.next_tile == par_cascade {
                    etat.front = Some(b.generation);
                    etat.parity = 1 - etat.parity;
                    etat.building = None;
                }
            }
            plan.front[ci] = etat.front;
        }
        plan
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn soleil(hauteur_deg: f64, azimut_deg: f64) -> DVec3 {
        let (se, ce) = hauteur_deg.to_radians().sin_cos();
        let (sa, ca) = azimut_deg.to_radians().sin_cos();
        DVec3::new(sa * ce, se, -ca * ce)
    }

    fn camera() -> DVec3 {
        DVec3::new(10_000.0, 1.7, 9_981.0)
    }

    #[test]
    fn la_premiere_image_remplit_tout() {
        let mut p = ShadowPlanner::new(ShadowParams::default());
        let plan = p.plan(soleil(40.0, 200.0), camera());
        assert_eq!(plan.jobs().len() as u32, p.params().tiles_per_generation());
        assert!((0..4).all(|c| plan.front(c).is_some()));
    }

    #[test]
    fn une_scene_immobile_ne_coute_rien() {
        let mut p = ShadowPlanner::new(ShadowParams::default());
        let s = soleil(40.0, 200.0);
        let _ = p.plan(s, camera());
        for _ in 0..100 {
            assert!(p.plan(s, camera()).jobs().is_empty());
        }
    }

    #[test]
    fn la_rotation_de_la_camera_ne_declenche_rien() {
        // Le planificateur ne reçoit que la position : une caméra qui tourne sur place ne refait aucune tuile.
        let mut p = ShadowPlanner::new(ShadowParams::default());
        let s = soleil(40.0, 200.0);
        let _ = p.plan(s, camera());
        for i in 0..360 {
            let _ = i;
            assert!(p.plan(s, camera()).jobs().is_empty());
        }
    }

    #[test]
    fn un_demi_texel_ne_declenche_rien_mais_un_cran_oui() {
        let params = ShadowParams::default();
        let mut p = ShadowPlanner::new(params);
        let s = soleil(40.0, 200.0);
        let _ = p.plan(s, camera());
        let b = SunBasis::new(s);
        let demi_texel = b.right() * (0.5 * params.texel_m(0));
        assert!(p.plan(s, camera() + demi_texel).jobs().is_empty());
        // un déplacement de 3 m (plusieurs crans de la cascade 0 : 0,4 m) refait la cascade 0, tuile par tuile
        let loin = camera() + b.right() * 3.0;
        let plan = p.plan(s, loin);
        assert!(!plan.jobs().is_empty());
        assert!(plan.jobs().len() as u32 <= params.tiles_per_frame());
        assert!(
            plan.jobs().iter().all(|j| j.cascade() == 0),
            "seule la cascade 0 a bougé d'un cran"
        );
    }

    #[test]
    fn le_soleil_qui_tourne_refait_apres_un_pas_et_une_generation_tient_en_30_images() {
        let params = ShadowParams::default();
        let mut p = ShadowPlanner::new(params);
        let _ = p.plan(soleil(40.0, 200.0), camera());
        // en dessous du pas : rien
        assert!(p.plan(soleil(40.0, 200.01), camera()).jobs().is_empty());
        // au-dessus du pas : une génération complète en ≤ 30 images
        let s = soleil(40.0, 200.2);
        let mut images = 0;
        let mut total = 0;
        loop {
            let plan = p.plan(s, camera());
            total += plan.jobs().len() as u32;
            images += 1;
            if plan.jobs().is_empty() || total >= params.tiles_per_generation() {
                break;
            }
            assert!(images < 100);
        }
        assert_eq!(total, params.tiles_per_generation());
        assert!(images <= 30, "{images} images pour une génération");
    }

    #[test]
    fn la_generation_avant_reste_lisible_pendant_la_construction() {
        let params = ShadowParams::default();
        let mut p = ShadowPlanner::new(params);
        let _ = p.plan(soleil(40.0, 200.0), camera());
        let avant = *p.plan(soleil(40.0, 200.0), camera()).front(0).unwrap();
        let plan = p.plan(soleil(40.0, 201.0), camera());
        // la cascade 0 construit dans l'AUTRE couche et l'éclairage lit encore l'ancienne
        assert_eq!(plan.front(0).unwrap().layer(), avant.layer());
        assert_ne!(plan.building(0).unwrap().layer(), avant.layer());
    }

    #[test]
    fn le_soleil_sous_l_horizon_oublie_les_cascades() {
        let mut p = ShadowPlanner::new(ShadowParams::default());
        let _ = p.plan(soleil(40.0, 200.0), camera());
        let nuit = p.plan(soleil(-10.0, 200.0), camera());
        assert!(nuit.jobs().is_empty() && (0..4).all(|c| nuit.front(c).is_none()));
    }

    #[test]
    fn l_invalidation_et_le_mode_continu_refont_les_cascades() {
        let mut p = ShadowPlanner::new(ShadowParams::default());
        let s = soleil(40.0, 200.0);
        let _ = p.plan(s, camera());
        p.invalidate();
        assert!(!p.plan(s, camera()).jobs().is_empty());
        let continu = ShadowParams::default().with_regeneration(Regeneration::Continue);
        let mut q = ShadowPlanner::new(continu);
        let _ = q.plan(s, camera());
        assert!(!q.plan(s, camera()).jobs().is_empty());
    }
}
