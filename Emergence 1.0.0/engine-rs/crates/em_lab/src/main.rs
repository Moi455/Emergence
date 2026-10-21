//! Binaire du laboratoire : scènes, captures, bancs, fenêtre, panneau de style.
//!
//! Lancer par `engine-rs/scripts/lab.sh` : il désigne le pilote NVIDIA (sans cela Vulkan ne liste que l'Intel).

#![forbid(unsafe_code)]

mod arbre;
mod bench;
mod capture;
mod chemins;
mod ciel;
mod famille;
mod fenetre;
mod horloges;
mod maillage;
mod maison;
mod materiaux;
mod scene;
// Scène statique de L08 (sol + modèles `.vxm`) : branchée à l'hôte de rendu par la scène « arbre » (L09).
mod scene_statique;

use clap::{Parser, Subcommand};
use em_render::{GpuContext, GpuRequest};

/// Laboratoire de style d'Emergence.
#[derive(Parser)]
#[command(name = "em_lab", version, about)]
struct Cli {
    /// Accepte un adaptateur autre que le discret demandé (Intel, logiciel) : mesures sans valeur.
    #[arg(long, global = true)]
    allow_any_adapter: bool,
    /// Active les couches de validation de wgpu (lent).
    #[arg(long, global = true)]
    validation: bool,
    #[command(subcommand)]
    commande: Commande,
}

#[derive(Subcommand)]
enum Commande {
    /// Rend une scène hors écran et écrit un PNG déterministe (et un JSON à côté).
    Capture(capture::ArgsCapture),
    /// Mesure les ms GPU par passe sur une scène et écrit un rapport JSON.
    Bench(bench::ArgsBench),
    /// Ouvre la fenêtre interactive (caméra libre, Échap quitte, F12 capture).
    Window(fenetre::ArgsFenetre),
}

fn lancer() -> anyhow::Result<()> {
    let cli = Cli::parse();
    let requete = GpuRequest::depuis_environnement(cli.allow_any_adapter, cli.validation);
    let gpu = GpuContext::new(&requete)?;
    match cli.commande {
        Commande::Capture(a) => capture::executer(&gpu, &a),
        Commande::Bench(a) => bench::executer(&gpu, &a),
        Commande::Window(a) => fenetre::executer(gpu, &a),
    }
}

fn main() {
    env_logger::Builder::from_env(
        env_logger::Env::default().default_filter_or("warn,em_lab=info,em_render=info"),
    )
    .format_timestamp(None)
    .init();
    if let Err(e) = lancer() {
        eprintln!("erreur : {e:#}");
        std::process::exit(2);
    }
}
