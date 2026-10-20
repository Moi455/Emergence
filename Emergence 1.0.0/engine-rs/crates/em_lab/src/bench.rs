//! Commande `bench` : ms GPU par passe sur la scène, rapport JSON de 19a § 6.6.

use crate::arbre::ArgsArbre;
use crate::chemins::dossier_captures;
use crate::ciel::ArgsCiel;
use crate::horloges::{EchantillonneurHorloges, GpuClocks};
use crate::scene::{self, HelloScene};
use clap::Args;
use em_render::{GpuContext, GpuProfiler, OffscreenTarget, PassTiming};
use serde::Serialize;
use std::path::PathBuf;

/// Arguments de `bench`.
#[derive(Args)]
pub struct ArgsBench {
    /// Scène à mesurer.
    #[arg(long, default_value = HelloScene::NOM)]
    pub scene: String,
    /// Nombre d'images mesurées.
    #[arg(long, default_value_t = 600)]
    pub frames: u32,
    /// Images de chauffe, non comptées.
    #[arg(long, default_value_t = 120)]
    pub warmup: u32,
    /// Largeur en pixels.
    #[arg(long, default_value_t = 1920)]
    pub largeur: u32,
    /// Hauteur en pixels.
    #[arg(long, default_value_t = 1080)]
    pub hauteur: u32,
    /// Fichier JSON de sortie (défaut : dossier des captures / bench_<scène>.json).
    #[arg(long)]
    pub out: Option<PathBuf>,
    /// Réglages de la scène « ciel ».
    #[command(flatten)]
    pub ciel: ArgsCiel,
    /// Réglages de la scène « arbre ».
    #[command(flatten)]
    pub arbre: ArgsArbre,
}

/// Rapport de banc (format de 19a § 6.6).
#[derive(Serialize)]
struct RapportBanc {
    scene: String,
    frames: u32,
    warmup: u32,
    resolution: [u32; 2],
    adapter: String,
    driver: String,
    passes: Vec<PassTiming>,
    total_median_ms: f64,
    total_p95_ms: f64,
    gpu_clocks: GpuClocks,
}

/// Exécute le banc.
pub fn executer(gpu: &GpuContext, a: &ArgsBench) -> anyhow::Result<()> {
    let mut cible = OffscreenTarget::new(gpu, a.largeur, a.hauteur)?;
    let mut scene = scene::creer(&a.scene, &a.ciel, &a.arbre, gpu)?;
    let mut profil = GpuProfiler::new(gpu, 32);
    let horloges = EchantillonneurHorloges::demarrer();
    for i in 0..u64::from(a.warmup) {
        scene.dessiner(gpu, &mut cible, &mut profil, i, 0.0)?;
    }
    profil.vider(gpu);
    profil.reinitialiser();
    for i in 0..u64::from(a.frames) {
        scene.dessiner(gpu, &mut cible, &mut profil, u64::from(a.warmup) + i, 0.0)?;
    }
    profil.vider(gpu);
    let horloges = horloges.terminer();
    let rapport = profil.report();
    println!("{rapport}");
    println!(
        "horloges : SM {} MHz, mémoire {} MHz, {} W, max {} °C ({} relevés)",
        horloges.sm_mhz_median,
        horloges.mem_mhz_median,
        horloges.power_w_median,
        horloges.temp_c_max,
        horloges.samples
    );
    let json = RapportBanc {
        scene: a.scene.clone(),
        frames: a.frames,
        warmup: a.warmup,
        resolution: [a.largeur, a.hauteur],
        adapter: gpu.info().name.clone(),
        driver: gpu.info().pilote(),
        passes: rapport.passes,
        total_median_ms: rapport.total_median_ms,
        total_p95_ms: rapport.total_p95_ms,
        gpu_clocks: horloges,
    };
    let chemin = a
        .out
        .clone()
        .unwrap_or_else(|| dossier_captures().join(format!("bench_{}.json", a.scene)));
    if let Some(p) = chemin.parent() {
        std::fs::create_dir_all(p)?;
    }
    std::fs::write(&chemin, serde_json::to_string_pretty(&json)?)?;
    println!("{}", chemin.display());
    Ok(())
}
