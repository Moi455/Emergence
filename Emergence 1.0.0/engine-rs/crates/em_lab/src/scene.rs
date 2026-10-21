//! Scène « hello » du laboratoire : ciel de test + surimpression. Le même objet sert la capture,
//! le banc et la fenêtre (docs/19 § 7.2 : même code d'image).

use crate::arbre::{ArbreScene, ArgsArbre};
use crate::ciel::{ArgsCiel, CielScene};
use crate::materiaux::{MateriauxScene, ModeDemande};
use anyhow::bail;
use em_render::hello::{OverlayText, SkyGradientPass, TextOverlayPass};
use em_render::{AdapterReport, Camera, FrameContext, FrameTarget, GpuContext, GpuProfiler, RenderGraph};

/// Une scène du laboratoire : le même objet sert la capture, le banc et la fenêtre (docs/19 § 7.2).
pub trait Scene {
    /// Déplace la caméra selon (avant, droite, haut) en mètres.
    fn deplacer(&mut self, avant: f32, droite: f32, haut: f32);

    /// Tourne la caméra de `d_lacet` (vers la gauche, positif) et `d_tangage` radians.
    fn tourner(&mut self, d_lacet: f32, d_tangage: f32);

    /// Réglages de la scène pour le JSON écrit à côté d'une capture (nul par défaut).
    fn reglages_json(&self) -> serde_json::Value {
        serde_json::Value::Null
    }

    /// Ajoute des lignes (mesures, aide) à la surimpression, si la scène en a une.
    fn set_lignes_supplementaires(&self, extra: &[String]);

    /// Dessine une image sur la cible.
    fn dessiner(
        &mut self,
        gpu: &GpuContext,
        cible: &mut dyn FrameTarget,
        profileur: &mut GpuProfiler,
        index: u64,
        temps_s: f32,
    ) -> anyhow::Result<()>;
}

/// Noms des scènes connues, pour les messages d'erreur.
pub const SCENES: &str = "hello, ciel, arbre, maison, materiaux";

/// Construit la scène nommée ; refuse un nom inconnu en listant les scènes disponibles.
pub fn creer(
    nom: &str,
    ciel: &ArgsCiel,
    arbre: &ArgsArbre,
    gpu: &GpuContext,
) -> anyhow::Result<Box<dyn Scene>> {
    let info = gpu.info();
    match nom {
        HelloScene::NOM => Ok(Box::new(HelloScene::new(info)?)),
        CielScene::NOM => Ok(Box::new(CielScene::new(info, ciel)?)),
        ArbreScene::NOM => Ok(Box::new(ArbreScene::new(gpu, info, ciel, arbre)?)),
        ArbreScene::NOM_MAISON => Ok(Box::new(ArbreScene::maison(gpu, info, ciel, arbre)?)),
        MateriauxScene::NOM => match ModeDemande::lire(&arbre.mode)? {
            ModeDemande::Seul(mode) => Ok(Box::new(MateriauxScene::new(gpu, info, ciel, arbre, mode)?)),
            ModeDemande::Comparaison => {
                bail!("--mode ab ne se capture qu'avec la commande `capture` (deux rendus côte à côte)")
            }
        },
        autre => bail!("scène inconnue « {autre} » (disponibles : {SCENES})"),
    }
}

/// Scène de test de l'hôte.
pub struct HelloScene {
    graphe: RenderGraph,
    texte: OverlayText,
    camera: Camera,
    en_tete: Vec<String>,
}

impl HelloScene {
    /// Nom de la scène en ligne de commande.
    pub const NOM: &'static str = "hello";

    /// Construit la scène pour cet adaptateur (son nom figure dans la surimpression).
    pub fn new(info: &AdapterReport) -> anyhow::Result<Self> {
        let texte = OverlayText::new();
        let mut graphe = RenderGraph::new();
        graphe.add(Box::new(SkyGradientPass::new()))?;
        graphe.add(Box::new(TextOverlayPass::new(texte.clone(), 56, 12, 2)))?;
        let en_tete = vec![
            "EMERGENCE - LABORATOIRE DE STYLE".to_owned(),
            "HOTE DE RENDU L02 (SCENE HELLO)".to_owned(),
            format!("GPU: {}", info.name),
            format!("PILOTE: {} ({})", info.pilote(), info.backend),
        ];
        texte.set_lines(en_tete.clone());
        Ok(Self {
            graphe,
            texte,
            camera: Camera::default(),
            en_tete,
        })
    }
}

impl Scene for HelloScene {
    fn deplacer(&mut self, avant: f32, droite: f32, haut: f32) {
        self.camera.deplacer(avant, droite, haut);
    }

    fn tourner(&mut self, d_lacet: f32, d_tangage: f32) {
        self.camera.tourner(d_lacet, d_tangage);
    }

    fn set_lignes_supplementaires(&self, extra: &[String]) {
        let mut l = self.en_tete.clone();
        l.extend_from_slice(extra);
        self.texte.set_lines(l);
    }

    fn dessiner(
        &mut self,
        gpu: &GpuContext,
        cible: &mut dyn FrameTarget,
        profileur: &mut GpuProfiler,
        index: u64,
        temps_s: f32,
    ) -> anyhow::Result<()> {
        let (l, h) = cible.size();
        let image = FrameContext::new(index, temps_s, l, h, self.camera)?;
        self.graphe.render(gpu, &image, cible, profileur)?;
        Ok(())
    }
}
