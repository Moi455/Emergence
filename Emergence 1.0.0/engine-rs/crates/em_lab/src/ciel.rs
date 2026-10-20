//! Scène « ciel » (L03) : ciel de Hillaire, nuages, soleil, crêtes lointaines, sol, étoiles, bloom et AgX.
//! `lab.sh capture --scene ciel --sun-elevation 4 --sun-azimuth 250 --out …`

use crate::scene::Scene;
use anyhow::Context;
use clap::Args;
use em_render::glam::Vec3;
use em_render::hello::{OverlayText, TextOverlayPass};
use em_render::{
    AdapterReport, BloomPass, Camera, CloudParams, FrameContext, FrameTarget, GpuContext, GpuProfiler,
    Partage, PostParams, RenderGraph, SkyBackgroundPass, SkyParams, SkyPass, SunModel, TonemapPass,
};

/// Réglages de la scène « ciel » (ligne de commande de `capture`, `bench` et `window`).
#[derive(Args, Clone, Debug)]
pub struct ArgsCiel {
    /// Élévation du soleil en degrés, de -30 à 90.
    #[arg(long, default_value_t = 35.0, allow_negative_numbers = true)]
    pub sun_elevation: f32,
    /// Azimut du soleil en degrés (0 = vers -Z, 90 = vers +X).
    #[arg(long, default_value_t = 135.0, allow_negative_numbers = true)]
    pub sun_azimuth: f32,
    /// Heure solaire vraie (0 à 24) : remplace élévation et azimut (avec --latitude et --day).
    #[arg(long)]
    pub hour: Option<f32>,
    /// Latitude du lieu pour --hour (degrés, nord positif).
    #[arg(long, default_value_t = 46.0, allow_negative_numbers = true)]
    pub latitude: f32,
    /// Jour de l'année pour --hour (172 = solstice de juin).
    #[arg(long, default_value_t = 172)]
    pub day: u16,
    /// Turbidité (multiplicateur des aérosols), de 0,5 à 15.
    #[arg(long, default_value_t = 3.0)]
    pub turbidity: f32,
    /// Brume au sol (perspective aérienne), de 0 à 1.
    #[arg(long, default_value_t = 0.3)]
    pub haze: f32,
    /// Couverture de la couche basse de nuages, de 0 à 1.
    #[arg(long, default_value_t = 0.40)]
    pub clouds: f32,
    /// Couverture du voile de nuages hauts, de 0 à 1.
    #[arg(long, default_value_t = 0.36)]
    pub veil: f32,
    /// Temps de vent des nuages (déplace le motif).
    #[arg(long, default_value_t = 0.0)]
    pub wind_time: f32,
    /// Exposition (multiplicateur linéaire avant AgX).
    #[arg(long, default_value_t = 1.35)]
    pub exposure: f32,
    /// Force du bloom, de 0 à 1.
    #[arg(long, default_value_t = 0.10)]
    pub bloom: f32,
    /// Azimut du regard de la caméra (défaut : celui du soleil).
    #[arg(long, allow_negative_numbers = true)]
    pub cam_azimuth: Option<f32>,
    /// Hauteur du regard au-dessus de l'horizon, en degrés.
    #[arg(long, default_value_t = 6.0, allow_negative_numbers = true)]
    pub cam_elevation: f32,
    /// Hauteur de la caméra au-dessus du sol, en mètres (plus haut : brume de l'horizon plus étagée).
    #[arg(long, default_value_t = 1.7)]
    pub cam_height: f32,
    /// Champ vertical en degrés.
    #[arg(long, default_value_t = 70.0)]
    pub fov: f32,
    /// Banc : fait bouger le soleil à chaque image pour mesurer le recalcul des LUT.
    #[arg(long)]
    pub moving_sun: bool,
    /// Affiche la surimpression de texte (ms par passe).
    #[arg(long)]
    pub overlay: bool,
}

/// La scène « ciel ».
pub struct CielScene {
    graphe: RenderGraph,
    camera: Camera,
    ciel: Partage<SkyParams>,
    base: SkyParams,
    soleil_mobile: bool,
    texte: Option<OverlayText>,
    reglages: serde_json::Value,
}

impl CielScene {
    /// Nom de la scène en ligne de commande.
    pub const NOM: &'static str = "ciel";

    /// Construit la scène : paramètres validés, passes dans l'ordre ciel, fond, bloom, composition.
    pub fn new(info: &AdapterReport, a: &ArgsCiel) -> anyhow::Result<Self> {
        let (elevation, azimut) = match a.hour {
            Some(h) => SunModel::new(a.latitude, a.day)?.position(h),
            None => (a.sun_elevation, a.sun_azimuth),
        };
        let nuages = CloudParams::new(1.5, a.clouds, 2.2, a.wind_time, a.veil)?;
        let base = SkyParams::new(elevation, azimut, a.turbidity, a.haze)?.with_clouds(nuages);
        let ciel = Partage::new(base);
        let post = Partage::new(PostParams::new(a.exposure, a.bloom)?);
        let mut graphe = RenderGraph::new();
        graphe.add(Box::new(SkyPass::new(ciel.clone())))?;
        graphe.add(Box::new(SkyBackgroundPass::new()))?;
        graphe.add(Box::new(BloomPass::new()))?;
        graphe.add(Box::new(TonemapPass::new(post)))?;
        let texte = if a.overlay {
            let t = OverlayText::new();
            t.set_lines(vec![
                "EMERGENCE - CIEL (L03)".to_owned(),
                format!("GPU: {}", info.name),
                format!("SOLEIL: {elevation:.1} / {azimut:.1} DEG"),
            ]);
            graphe.add(Box::new(TextOverlayPass::new(t.clone(), 56, 12, 2)))?;
            Some(t)
        } else {
            None
        };
        // Compas : l'azimut 0 regarde vers -Z, positif vers +X ; la caméra tourne à gauche pour un lacet positif.
        let regard = a.cam_azimuth.unwrap_or(azimut);
        let camera = Camera::new(
            Vec3::new(0.0, a.cam_height, 0.0),
            (-regard).to_radians(),
            a.cam_elevation.to_radians(),
            a.fov,
        )
        .context("caméra de la scène ciel")?;
        Ok(Self {
            graphe,
            camera,
            ciel,
            base,
            soleil_mobile: a.moving_sun,
            texte,
            reglages: serde_json::json!({
                "sun_elevation_deg": elevation,
                "sun_azimuth_deg": azimut,
                "hour": a.hour,
                "turbidity": a.turbidity,
                "haze": a.haze,
                "clouds": a.clouds,
                "veil": a.veil,
                "wind_time": a.wind_time,
                "exposure": a.exposure,
                "bloom": a.bloom,
                "cam_azimuth_deg": regard,
                "cam_elevation_deg": a.cam_elevation,
                "cam_height_m": a.cam_height,
                "fov_y_deg": a.fov,
            }),
        })
    }
}

impl Scene for CielScene {
    fn reglages_json(&self) -> serde_json::Value {
        self.reglages.clone()
    }

    fn deplacer(&mut self, avant: f32, droite: f32, haut: f32) {
        self.camera.deplacer(avant, droite, haut);
    }

    fn tourner(&mut self, d_lacet: f32, d_tangage: f32) {
        self.camera.tourner(d_lacet, d_tangage);
    }

    fn set_lignes_supplementaires(&self, extra: &[String]) {
        if let Some(t) = &self.texte {
            let mut l = vec!["EMERGENCE - CIEL (L03)".to_owned()];
            l.extend_from_slice(extra);
            t.set_lines(l);
        }
    }

    fn dessiner(
        &mut self,
        gpu: &GpuContext,
        cible: &mut dyn FrameTarget,
        profileur: &mut GpuProfiler,
        index: u64,
        temps_s: f32,
    ) -> anyhow::Result<()> {
        if self.soleil_mobile {
            // Balancement de ±3° autour de l'élévation choisie : de quoi forcer le recalcul de la LUT de vue.
            let e = (self.base.sun_elevation_deg() + 3.0 * (index as f32 * 0.37).sin()).clamp(-30.0, 90.0);
            let p = SkyParams::new(
                e,
                self.base.sun_azimuth_deg(),
                self.base.turbidity(),
                self.base.haze(),
            )?
            .with_clouds(*self.base.clouds());
            self.ciel.remplacer(p);
        }
        let (l, h) = cible.size();
        let image = FrameContext::new(index, temps_s, l, h, self.camera)?;
        self.graphe.render(gpu, &image, cible, profileur)?;
        Ok(())
    }
}
