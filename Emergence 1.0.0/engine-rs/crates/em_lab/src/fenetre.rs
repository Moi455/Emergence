//! Commande `window` : fenêtre interactive (winit), caméra libre, Échap quitte, F12 capture.
//! Souris : clic gauche pour capturer le pointeur (Échap quitte toujours). ZQSD/WASD (touches
//! physiques), Espace/Ctrl montent et descendent, Maj ×5, molette = vitesse.

use crate::arbre::ArgsArbre;
use crate::chemins::dossier_captures;
use crate::ciel::ArgsCiel;
use crate::scene::{self, HelloScene, Scene};
use anyhow::Context;
use clap::Args;
use em_render::{FrameTarget, GpuContext, GpuProfiler, OffscreenTarget, WindowTarget, read_texture_png};
use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Instant;
use winit::application::ApplicationHandler;
use winit::dpi::LogicalSize;
use winit::event::{DeviceEvent, DeviceId, ElementState, MouseScrollDelta, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::keyboard::{KeyCode, PhysicalKey};
use winit::window::{CursorGrabMode, Window, WindowId};

/// Arguments de `window`.
#[derive(Args)]
pub struct ArgsFenetre {
    /// Scène à afficher.
    #[arg(long, default_value = HelloScene::NOM)]
    pub scene: String,
    /// Quitte seul après ce nombre d'images (essais automatiques).
    #[arg(long)]
    pub exit_after_frames: Option<u64>,
    /// Capture F12 automatique à cette image (essais automatiques).
    #[arg(long)]
    pub capture_at_frame: Option<u64>,
    /// Réglages de la scène « ciel ».
    #[command(flatten)]
    pub ciel: ArgsCiel,
    /// Réglages de la scène « arbre ».
    #[command(flatten)]
    pub arbre: ArgsArbre,
}

/// État de l'application de fenêtre.
struct Application {
    gpu: GpuContext,
    scene: Box<dyn Scene>,
    profil: GpuProfiler,
    args_sortie: Option<u64>,
    args_capture: Option<u64>,
    fenetre: Option<Arc<Window>>,
    cible: Option<WindowTarget>,
    touches: BTreeSet<KeyCode>,
    vitesse: f32,
    pointeur_capture: bool,
    image: u64,
    debut: Instant,
    derniere: Instant,
    compteur_capture: u32,
    erreur: Option<anyhow::Error>,
}

impl Application {
    fn creer_fenetre(&mut self, boucle: &ActiveEventLoop) -> anyhow::Result<()> {
        let attributs = Window::default_attributes()
            .with_title("Emergence : laboratoire de style")
            .with_inner_size(LogicalSize::new(1280.0, 720.0));
        let fenetre = Arc::new(
            boucle
                .create_window(attributs)
                .context("création de la fenêtre")?,
        );
        let surface = self
            .gpu
            .instance()
            .create_surface(Arc::clone(&fenetre))
            .context("création de la surface")?;
        let taille = fenetre.inner_size();
        self.cible = Some(WindowTarget::new(
            &self.gpu,
            surface,
            taille.width,
            taille.height,
        )?);
        fenetre.request_redraw();
        self.fenetre = Some(fenetre);
        Ok(())
    }

    fn capturer_pointeur(&mut self, oui: bool) {
        let Some(f) = &self.fenetre else { return };
        if oui {
            let ok = f
                .set_cursor_grab(CursorGrabMode::Locked)
                .or_else(|_| f.set_cursor_grab(CursorGrabMode::Confined))
                .is_ok();
            f.set_cursor_visible(!ok);
            self.pointeur_capture = ok;
        } else {
            let _ = f.set_cursor_grab(CursorGrabMode::None);
            f.set_cursor_visible(true);
            self.pointeur_capture = false;
        }
    }

    fn deplacer(&mut self, dt: f32) {
        let t = |k: KeyCode| f32::from(u8::from(self.touches.contains(&k)));
        let avant = t(KeyCode::KeyW) - t(KeyCode::KeyS);
        let droite = t(KeyCode::KeyD) - t(KeyCode::KeyA);
        let haut = t(KeyCode::Space) - t(KeyCode::ControlLeft);
        let rapide = if self.touches.contains(&KeyCode::ShiftLeft) {
            5.0
        } else {
            1.0
        };
        let pas = self.vitesse * rapide * dt;
        self.scene.deplacer(avant * pas, droite * pas, haut * pas);
    }

    /// F12 : même chemin qu'une capture hors écran, depuis la caméra courante.
    fn capturer(&mut self) -> anyhow::Result<()> {
        let format = self.cible.as_ref().context("pas de cible")?.format();
        let mut hors = OffscreenTarget::avec_format(&self.gpu, 1920, 1080, format)?;
        let t = self.debut.elapsed().as_secs_f32();
        for _ in 0..2 {
            self.scene
                .dessiner(&self.gpu, &mut hors, &mut self.profil, self.image, t)?;
        }
        self.compteur_capture += 1;
        let chemin = dossier_captures().join(format!("fenetre_{:03}.png", self.compteur_capture));
        read_texture_png(&self.gpu, hors.texture(), &chemin)?;
        log::info!("capture F12 : {}", chemin.display());
        Ok(())
    }

    fn dessiner_image(&mut self, boucle: &ActiveEventLoop) {
        let maintenant = Instant::now();
        let dt = (maintenant - self.derniere).as_secs_f32().min(0.1);
        self.derniere = maintenant;
        self.deplacer(dt);
        if self.image.is_multiple_of(30) {
            let r = self.profil.report();
            let mut l: Vec<String> = vec![String::new()];
            for p in &r.passes {
                l.push(format!("{}: {:.3} MS", p.name, p.median_ms));
            }
            l.push(format!("TOTAL: {:.3} MS (MEDIANE)", r.total_median_ms));
            l.push("ECHAP QUITTE - F12 CAPTURE - CLIC: SOURIS".to_owned());
            self.scene.set_lignes_supplementaires(&l);
        }
        let Some(cible) = self.cible.as_mut() else { return };
        let t = self.debut.elapsed().as_secs_f32();
        match self
            .scene
            .dessiner(&self.gpu, cible, &mut self.profil, self.image, t)
        {
            Ok(()) => self.image += 1,
            Err(e) => {
                // Une image sautée (fenêtre masquée…) n'est pas une erreur ; le reste arrête la boucle.
                if e.to_string().starts_with("image sautée") {
                    log::debug!("{e}");
                } else {
                    self.erreur = Some(e);
                    boucle.exit();
                    return;
                }
            }
        }
        if self.args_capture == Some(self.image)
            && let Err(e) = self.capturer()
        {
            self.erreur = Some(e);
            boucle.exit();
            return;
        }
        if self.args_sortie.is_some_and(|n| self.image >= n) {
            boucle.exit();
            return;
        }
        if let Some(f) = &self.fenetre {
            f.request_redraw();
        }
    }
}

impl ApplicationHandler for Application {
    fn resumed(&mut self, boucle: &ActiveEventLoop) {
        if self.fenetre.is_none()
            && let Err(e) = self.creer_fenetre(boucle)
        {
            self.erreur = Some(e);
            boucle.exit();
        }
    }

    fn window_event(&mut self, boucle: &ActiveEventLoop, _id: WindowId, evenement: WindowEvent) {
        match evenement {
            WindowEvent::CloseRequested => boucle.exit(),
            WindowEvent::Resized(t) => {
                if let Some(c) = self.cible.as_mut() {
                    c.redimensionner(t.width, t.height);
                }
            }
            WindowEvent::KeyboardInput { event, .. } => {
                if let PhysicalKey::Code(code) = event.physical_key {
                    match event.state {
                        ElementState::Pressed => {
                            if code == KeyCode::Escape {
                                boucle.exit();
                            } else if code == KeyCode::F12
                                && !event.repeat
                                && let Err(e) = self.capturer()
                            {
                                log::error!("capture F12 impossible : {e:#}");
                            }
                            self.touches.insert(code);
                        }
                        ElementState::Released => {
                            self.touches.remove(&code);
                        }
                    }
                }
            }
            WindowEvent::MouseInput {
                state: ElementState::Pressed,
                button: winit::event::MouseButton::Left,
                ..
            } => {
                self.capturer_pointeur(true);
            }
            WindowEvent::Focused(false) => self.capturer_pointeur(false),
            WindowEvent::MouseWheel { delta, .. } => {
                let pas = match delta {
                    MouseScrollDelta::LineDelta(_, y) => y,
                    MouseScrollDelta::PixelDelta(p) => p.y as f32 / 40.0,
                };
                self.vitesse = (self.vitesse * 1.2_f32.powf(pas)).clamp(0.1, 500.0);
            }
            WindowEvent::RedrawRequested => self.dessiner_image(boucle),
            _ => {}
        }
    }

    fn device_event(&mut self, _boucle: &ActiveEventLoop, _id: DeviceId, evenement: DeviceEvent) {
        if let (DeviceEvent::MouseMotion { delta: (dx, dy) }, true) = (evenement, self.pointeur_capture) {
            const SENSIBILITE: f32 = 0.0025;
            self.scene
                .tourner(-(dx as f32) * SENSIBILITE, -(dy as f32) * SENSIBILITE);
        }
    }
}

/// Ouvre la fenêtre et boucle jusqu'à la fermeture.
pub fn executer(gpu: GpuContext, a: &ArgsFenetre) -> anyhow::Result<()> {
    let scene = scene::creer(&a.scene, &a.ciel, &a.arbre, &gpu)?;
    let profil = GpuProfiler::new(&gpu, 32);
    let boucle = EventLoop::new().context("ouverture de la boucle d'événements")?;
    boucle.set_control_flow(ControlFlow::Poll);
    let maintenant = Instant::now();
    let mut app = Application {
        gpu,
        scene,
        profil,
        args_sortie: a.exit_after_frames,
        args_capture: a.capture_at_frame,
        fenetre: None,
        cible: None,
        touches: BTreeSet::new(),
        vitesse: 3.0,
        pointeur_capture: false,
        image: 0,
        debut: maintenant,
        derniere: maintenant,
        compteur_capture: 0,
        erreur: None,
    };
    boucle.run_app(&mut app).context("boucle d'événements")?;
    if let Some(e) = app.erreur.take() {
        return Err(e);
    }
    app.gpu.attendre_fin();
    Ok(())
}
