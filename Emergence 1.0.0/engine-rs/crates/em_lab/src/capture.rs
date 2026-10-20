//! Commande `capture` : rendu hors écran, PNG déterministe, JSON à côté.

use crate::arbre::ArgsArbre;
use crate::chemins::dossier_captures;
use crate::ciel::ArgsCiel;
use crate::scene::{self, HelloScene};
use anyhow::Context;
use clap::Args;
use em_render::{GpuContext, GpuProfiler, OffscreenTarget, read_texture_png};
use std::path::PathBuf;
use std::time::Instant;

/// Arguments de `capture`.
#[derive(Args)]
pub struct ArgsCapture {
    /// Scène à rendre.
    #[arg(long, default_value = HelloScene::NOM)]
    pub scene: String,
    /// Largeur en pixels.
    #[arg(long, default_value_t = 1920)]
    pub largeur: u32,
    /// Hauteur en pixels.
    #[arg(long, default_value_t = 1080)]
    pub hauteur: u32,
    /// Images de chauffe avant la lecture (TAA, sondes… convergés avec la même gigue).
    #[arg(long, default_value_t = 4)]
    pub frames: u32,
    /// Fichier PNG de sortie (défaut : dossier des captures / <scène>.png).
    #[arg(long)]
    pub out: Option<PathBuf>,
    /// Réglages de la scène « ciel ».
    #[command(flatten)]
    pub ciel: ArgsCiel,
    /// Réglages de la scène « arbre ».
    #[command(flatten)]
    pub arbre: ArgsArbre,
}

/// Exécute la capture.
pub fn executer(gpu: &GpuContext, a: &ArgsCapture) -> anyhow::Result<()> {
    let debut = Instant::now();
    let mut cible = OffscreenTarget::new(gpu, a.largeur, a.hauteur)?;
    let mut scene = scene::creer(&a.scene, &a.ciel, &a.arbre, gpu)?;
    let mut profil = GpuProfiler::new(gpu, 32);
    for i in 0..=u64::from(a.frames) {
        // Temps figé : l'image ne dépend que du numéro de scène et de la caméra.
        scene.dessiner(gpu, &mut cible, &mut profil, i, 0.0)?;
    }
    let chemin = a
        .out
        .clone()
        .unwrap_or_else(|| dossier_captures().join(format!("{}.png", a.scene)));
    read_texture_png(gpu, cible.texture(), &chemin)
        .with_context(|| format!("écriture de {}", chemin.display()))?;
    profil.vider(gpu);
    let json = serde_json::json!({
        "scene": a.scene,
        "scene_settings": scene.reglages_json(),
        "resolution": [a.largeur, a.hauteur],
        "warmup_frames": a.frames,
        "adapter": gpu.info().name,
        "driver": gpu.info().pilote(),
        "driver_info": gpu.info().driver_info,
        "granted_limits": gpu.info().granted,
        "profile": profil.report(),
    });
    std::fs::write(
        chemin.with_extension("json"),
        serde_json::to_string_pretty(&json)?,
    )?;
    log::info!(
        "capture {} écrite en {:.2} s",
        chemin.display(),
        debut.elapsed().as_secs_f64()
    );
    println!("{}", chemin.display());
    Ok(())
}
