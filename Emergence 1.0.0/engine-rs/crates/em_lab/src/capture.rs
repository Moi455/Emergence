//! Commande `capture` : rendu hors écran, PNG déterministe, JSON à côté.

use crate::arbre::ArgsArbre;
use crate::chemins::dossier_captures;
use crate::ciel::ArgsCiel;
use crate::maillage::RenduDemande;
use crate::materiaux::{self, MateriauxScene, ModeDemande};
use crate::scene::{self, HelloScene};
use anyhow::Context;
use clap::Args;
use em_render::{GpuContext, GpuProfiler, OffscreenTarget, read_texture, read_texture_png};
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
    if a.scene == MateriauxScene::NOM && ModeDemande::lire(&a.arbre.mode)? == ModeDemande::Comparaison {
        let sortie = a
            .out
            .clone()
            .unwrap_or_else(|| dossier_captures().join("materiaux_ab.png"));
        let chemins =
            materiaux::capturer_ab(gpu, &a.ciel, &a.arbre, a.largeur, a.hauteur, a.frames, &sortie)?;
        log::info!("comparaison A/B écrite en {:.2} s", debut.elapsed().as_secs_f64());
        for c in chemins {
            println!("{}", c.display());
        }
        return Ok(());
    }
    if a.arbre.ao_ab {
        return capturer_ab(
            gpu,
            a,
            "ao_ab",
            [
                ("AVANT : SANS OCCLUSION", |x: &mut ArgsArbre| x.sans_ao = true),
                ("APRES : AVEC OCCLUSION", |x: &mut ArgsArbre| x.sans_ao = false),
            ],
        );
    }
    if RenduDemande::lire(&a.arbre.rendu)? == RenduDemande::Comparaison {
        return capturer_ab(
            gpu,
            a,
            "rendu_ab",
            [
                ("AVANT : TRACE COMPUTE", |x: &mut ArgsArbre| {
                    x.rendu = "trace".to_owned()
                }),
                ("APRES : MAILLAGE RASTER", |x: &mut ArgsArbre| {
                    x.rendu = "maillage".to_owned()
                }),
            ],
        );
    }
    if a.arbre.relief_ab {
        return capturer_ab(
            gpu,
            a,
            "relief_ab",
            [
                ("AVANT : SANS RELIEF", |x: &mut ArgsArbre| x.sans_relief = true),
                ("APRES : AVEC RELIEF", |x: &mut ArgsArbre| x.sans_relief = false),
            ],
        );
    }
    if a.arbre.creux_ab {
        return capturer_ab(
            gpu,
            a,
            "creux_ab",
            [
                ("AVANT : OCCLUSION DE L33", |x: &mut ArgsArbre| {
                    x.ao_creux = Some(0.0)
                }),
                ("APRES : OCCLUSION CREUSE", |x: &mut ArgsArbre| {
                    if x.ao_creux == Some(0.0) {
                        x.ao_creux = None
                    }
                }),
            ],
        );
    }
    if a.arbre.granulometrie_ab {
        return capturer_ab(
            gpu,
            a,
            "granulometrie_ab",
            [
                ("AVANT : GRANULOMETRIE 1.0", |x: &mut ArgsArbre| {
                    x.granulometrie = Some(1.0)
                }),
                ("APRES : GRANULOMETRIE RENFORCEE", |x: &mut ArgsArbre| {
                    x.granulometrie = None
                }),
            ],
        );
    }
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

/// Une variante de comparaison : l'étiquette écrite sur l'image et la modification des arguments.
type Variante<'a> = (&'a str, fn(&mut ArgsArbre));

/// Comparaison AVANT/APRÈS : la même scène, le même soleil, la même caméra, rendue avec deux variantes de réglages
/// (`modifs`, appliquées à une copie des arguments). Écrit trois PNG déterministes : `<nom>.png` (AVANT à gauche, APRÈS
/// à droite), `<nom>_AVANT.png` et `<nom>_APRES.png`, et le JSON des deux réglages à côté.
fn capturer_ab(gpu: &GpuContext, a: &ArgsCapture, defaut: &str, modifs: [Variante; 2]) -> anyhow::Result<()> {
    let sortie = a
        .out
        .clone()
        .unwrap_or_else(|| dossier_captures().join(format!("{}_{defaut}.png", a.scene)));
    let mut images = Vec::new();
    let mut reglages = Vec::new();
    for (etiquette, modif) in &modifs {
        let mut args = a.arbre.clone();
        modif(&mut args);
        let mut ciel = a.ciel.clone();
        ciel.overlay = true;
        let mut cible = OffscreenTarget::new(gpu, a.largeur, a.hauteur)?;
        let mut scene = scene::creer(&a.scene, &ciel, &args, gpu)?;
        scene.set_lignes_supplementaires(&[(*etiquette).to_owned()]);
        let mut profil = GpuProfiler::new(gpu, 32);
        for i in 0..=u64::from(a.frames) {
            scene.dessiner(gpu, &mut cible, &mut profil, i, 0.0)?;
        }
        images.push(read_texture(gpu, cible.texture())?);
        reglages.push(scene.reglages_json());
    }
    let stem = sortie
        .file_stem()
        .map_or_else(|| defaut.into(), |s| s.to_string_lossy().into_owned());
    let dossier = sortie
        .parent()
        .map_or_else(dossier_captures, std::path::Path::to_path_buf);
    std::fs::create_dir_all(&dossier)?;
    let (avant, apres) = (
        dossier.join(format!("{stem}_AVANT.png")),
        dossier.join(format!("{stem}_APRES.png")),
    );
    std::fs::write(&sortie, images[0].juxtaposer(&images[1], 6)?.encoder_png()?)?;
    std::fs::write(&avant, images[0].encoder_png()?)?;
    std::fs::write(&apres, images[1].encoder_png()?)?;
    let json = serde_json::json!({
        "scene": a.scene,
        "resolution_each": [a.largeur, a.hauteur],
        "warmup_frames": a.frames,
        "adapter": gpu.info().name,
        "AVANT": reglages[0],
        "APRES": reglages[1],
    });
    std::fs::write(
        sortie.with_extension("json"),
        serde_json::to_string_pretty(&json)?,
    )?;
    for c in [&sortie, &avant, &apres] {
        println!("{}", c.display());
    }
    Ok(())
}
