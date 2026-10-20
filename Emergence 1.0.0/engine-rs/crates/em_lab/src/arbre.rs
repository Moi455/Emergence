//! Scène « arbre » (L09) : le chêne 42 sur un sol plat de turf, rendu par le lancer de rayons voxel.
//! `lab.sh capture --scene arbre --shot face --hour 17.5 --out …` ou, à la main,
//! `lab.sh capture --scene arbre --camera 12,1.7,-8 --look-at 0,6,0 --hour 17.5`.
//!
//! Ordre des passes : ciel (LUT), fond de ciel, tracé primaire, matière, profondeur, éclairage, bloom, AgX.

use crate::chemins::dossier_racine;
use crate::ciel::ArgsCiel;
use crate::scene::Scene;
use crate::scene_statique::SceneStatique;
use anyhow::{Context, bail};
use clap::Args;
use em_core::VOXEL_MM;
use em_material::MaterialTable;
use em_render::hello::{OverlayText, TextOverlayPass};
use em_render::{
    AdapterReport, BloomPass, ClipmapConfig, ClipmapStreamer, CloudParams, DebugView, DepthMergePass,
    FrameContext, FrameTarget, GpuContext, GpuMaterials, GpuProfiler, LightSettings, LightingPass, Partage,
    PostParams, Projection, RenderGraph, SkyBackgroundPass, SkyParams, SkyPass, SunModel, TonemapPass,
    VoxelCamera, VoxelGpuWorld, VoxelMaterialPass, VoxelTracePass,
};
use serde::Deserialize;

/// Réglages de la scène « arbre » (ligne de commande de `capture`, `bench` et `window`). Le soleil, l'exposition,
/// le bloom et le champ de vision viennent des options du ciel (`--hour`, `--exposure`, `--bloom`, `--fov`).
#[derive(Args, Clone, Debug)]
pub struct ArgsArbre {
    /// Prise de vue nommée de `lab/scenes/arbre.toml` (face, trois_quarts, feuillage, tronc, cime…).
    #[arg(long)]
    pub shot: Option<String>,
    /// Position de la caméra en mètres, relative à l'origine de la scène : `x,y,z` (remplace celle de la prise).
    #[arg(long, value_delimiter = ',', allow_negative_numbers = true)]
    pub camera: Option<Vec<f64>>,
    /// Point regardé en mètres, relatif à l'origine de la scène : `x,y,z` (calcule lacet et tangage).
    #[arg(long, value_delimiter = ',', allow_negative_numbers = true)]
    pub look_at: Option<Vec<f64>>,
    /// Lacet en degrés (0 = nord, 90 = est), si `--look-at` n'est pas donné.
    #[arg(long, allow_negative_numbers = true)]
    pub yaw: Option<f32>,
    /// Tangage en degrés, si `--look-at` n'est pas donné.
    #[arg(long, allow_negative_numbers = true)]
    pub pitch: Option<f32>,
    /// Vue orthographique de cette hauteur en mètres (silhouette, orientation) au lieu de la perspective.
    #[arg(long)]
    pub ortho_hauteur: Option<f32>,
    /// Vue affichée : image, albedo, normales, distance, masque.
    #[arg(long, default_value = "image")]
    pub vue: String,
    /// Champ vertical en degrés (remplace celui de la prise).
    #[arg(long)]
    pub champ: Option<f32>,
    /// Échelle de la lumière du ciel (1 = physique), de 0 à 4.
    #[arg(long, default_value_t = 1.0)]
    pub ambiance: f32,
    /// Fichier de scène (relatif à engine-rs/).
    #[arg(long, default_value = "lab/scenes/arbre.toml")]
    pub scene_fichier: String,
}

/// Une prise de vue de `[[shot]]` (docs/19a § 6.4).
#[derive(Debug, Clone, Deserialize)]
pub struct Tir {
    /// Nom de la prise.
    pub name: String,
    /// Position relative à l'origine de la scène, en mètres.
    pub pos_m: [f64; 3],
    /// Point regardé (prioritaire sur lacet et tangage).
    #[serde(default)]
    pub look_at_m: Option<[f64; 3]>,
    /// Lacet en degrés.
    #[serde(default)]
    pub yaw_deg: f32,
    /// Tangage en degrés.
    #[serde(default)]
    pub pitch_deg: f32,
    /// Champ vertical en degrés.
    #[serde(default = "Tir::fov_defaut")]
    pub fov_deg: f32,
    /// Heures conseillées.
    #[serde(default)]
    pub hours: Vec<f32>,
}

impl Tir {
    fn fov_defaut() -> f32 {
        60.0
    }
}

#[derive(Deserialize)]
struct FichierTirs {
    origin_m: [f64; 3],
    #[serde(default)]
    shot: Vec<Tir>,
}

/// Lacet et tangage (degrés) qui font regarder `cible` depuis `pos` (lacet 0 = nord +z, 90 = est +x).
pub fn regarder(pos: [f64; 3], cible: [f64; 3]) -> (f32, f32) {
    let (dx, dy, dz) = (cible[0] - pos[0], cible[1] - pos[1], cible[2] - pos[2]);
    let lacet = dx.atan2(dz).to_degrees();
    let tangage = dy.atan2(dx.hypot(dz)).to_degrees();
    (lacet as f32, tangage as f32)
}

/// Mètres -> millimètres entiers (arrondi au plus proche).
fn mm(m: f64) -> i64 {
    (m * 1000.0).round() as i64
}

/// La scène « arbre ».
pub struct ArbreScene {
    graphe: RenderGraph,
    camera: VoxelCamera,
    monde: VoxelGpuWorld,
    streamer: ClipmapStreamer,
    source: SceneStatique,
    reglages: serde_json::Value,
    texte: Option<OverlayText>,
}

impl ArbreScene {
    /// Nom de la scène en ligne de commande.
    pub const NOM: &'static str = "arbre";

    /// Construit la scène : charge le modèle et les matières, monte la mémoire GPU et les passes.
    pub fn new(
        gpu: &GpuContext,
        info: &AdapterReport,
        ciel: &ArgsCiel,
        a: &ArgsArbre,
    ) -> anyhow::Result<Self> {
        let racine = dossier_racine();
        let fichier = racine.join(&a.scene_fichier);
        let source = SceneStatique::charger(&fichier, &racine)?;
        let texte_toml =
            std::fs::read_to_string(&fichier).with_context(|| format!("lecture de {}", fichier.display()))?;
        let tirs: FichierTirs = toml::from_str(&texte_toml).context("prises de vue de la scène")?;

        // Matières : fichiers de données du dépôt + rampes de l'essence du premier modèle.
        let donnees = racine.join("../engine/data");
        let table = MaterialTable::load(
            &donnees.join("materials.csv"),
            &donnees.join("material_render.toml"),
        )
        .context("table des matières")?;
        let modele = source
            .scene()
            .models()
            .next()
            .context("la scène n'a aucun modèle")?;
        let veg = em_gen::vegetation_ramps(modele.model().meta(), modele.species_slot())?;
        let materiaux = GpuMaterials::new(gpu, &table, &veg);

        // Prise de vue : nommée, ou construite à la main.
        let tir = match &a.shot {
            Some(nom) => Some(
                tirs.shot
                    .iter()
                    .find(|t| &t.name == nom)
                    .with_context(|| format!("prise « {nom} » absente (disponibles : {})", noms(&tirs.shot)))?
                    .clone(),
            ),
            None if a.camera.is_none() => tirs.shot.first().cloned(),
            None => None,
        };
        let triplet = |v: &Option<Vec<f64>>, nom: &str| -> anyhow::Result<Option<[f64; 3]>> {
            match v {
                Some(v) if v.len() == 3 => Ok(Some([v[0], v[1], v[2]])),
                Some(_) => bail!("{nom} attend trois nombres x,y,z"),
                None => Ok(None),
            }
        };
        let pos_m = triplet(&a.camera, "--camera")?
            .or(tir.as_ref().map(|t| t.pos_m))
            .unwrap_or([12.0, 1.7, -8.0]);
        let cible = triplet(&a.look_at, "--look-at")?.or(tir.as_ref().and_then(|t| t.look_at_m));
        let (lacet, tangage) = match (cible, a.yaw, a.pitch, &tir) {
            (Some(c), _, _, _) => regarder(pos_m, c),
            (None, Some(y), p, _) => (y, p.unwrap_or(0.0)),
            (None, None, Some(p), Some(t)) => (t.yaw_deg, p),
            (None, None, None, Some(t)) => (t.yaw_deg, t.pitch_deg),
            (None, None, p, None) => (
                regarder(pos_m, [0.0, 6.0, 0.0]).0,
                p.unwrap_or(regarder(pos_m, [0.0, 6.0, 0.0]).1),
            ),
        };
        let fov = a.champ.or(tir.as_ref().map(|t| t.fov_deg)).unwrap_or(ciel.fov);
        let projection = match a.ortho_hauteur {
            Some(h) => Projection::Orthographic { height_m: h },
            None => Projection::Perspective { fov_y_deg: fov },
        };
        let origine = triplet(&Some(tirs.origin_m.to_vec()), "origin_m")?.expect("trois composantes");
        let pos_mm = [
            mm(origine[0] + pos_m[0]),
            mm(origine[1] + pos_m[1]),
            mm(origine[2] + pos_m[2]),
        ];
        let camera = VoxelCamera::new(pos_mm, lacet, tangage, projection).context("caméra voxel")?;

        // Soleil : l'heure solaire vraie fixe élévation et azimut (astronomique : 0 = nord). Le ciel de L03 mesure
        // l'azimut depuis -Z ; le monde voxel a son nord en +z : on passe de l'un à l'autre par 180° - azimut.
        let heure = ciel
            .hour
            .or_else(|| tir.as_ref().and_then(|t| t.hours.first().copied()))
            .unwrap_or(17.5);
        let (elevation, azimut) = SunModel::new(ciel.latitude, ciel.day)?.position(heure);
        let nuages = CloudParams::new(1.5, ciel.clouds, 2.2, ciel.wind_time, ciel.veil)?;
        let params_ciel = SkyParams::new(
            elevation,
            (180.0 - azimut).rem_euclid(360.0),
            ciel.turbidity,
            ciel.haze,
        )?
        .with_clouds(nuages);
        let partage_ciel = Partage::new(params_ciel);
        let post = Partage::new(PostParams::new(ciel.exposure, ciel.bloom)?);
        let vue = DebugView::from_name(&a.vue).with_context(|| {
            format!(
                "vue « {} » inconnue (image, albedo, normales, distance, masque)",
                a.vue
            )
        })?;
        let lumiere = Partage::new(LightSettings::new(vue, a.ambiance)?);

        let monde = VoxelGpuWorld::new(gpu, ClipmapConfig::laboratoire())?;
        let mut graphe = RenderGraph::new();
        graphe.add(Box::new(SkyPass::new(partage_ciel)))?;
        graphe.add(Box::new(SkyBackgroundPass::new()))?;
        graphe.add(Box::new(VoxelTracePass::new(monde.bindings())))?;
        graphe.add(Box::new(VoxelMaterialPass::new(materiaux.bindings())))?;
        graphe.add(Box::new(DepthMergePass::new()))?;
        graphe.add(Box::new(LightingPass::new(lumiere)))?;
        graphe.add(Box::new(BloomPass::new()))?;
        graphe.add(Box::new(TonemapPass::new(post)))?;
        let texte = if ciel.overlay {
            let t = OverlayText::new();
            t.set_lines(vec![
                "EMERGENCE - ARBRE (L09)".to_owned(),
                format!("GPU: {}", info.name),
                format!("SOLEIL: {elevation:.1} / {azimut:.1} DEG ({heure:.1} H)"),
            ]);
            graphe.add(Box::new(TextOverlayPass::new(t.clone(), 56, 12, 2)))?;
            Some(t)
        } else {
            None
        };
        let reglages = serde_json::json!({
            "scene": source.nom(),
            "shot": tir.as_ref().map(|t| t.name.clone()),
            "camera_m": pos_m,
            "camera_mm_monde": pos_mm,
            "yaw_deg": camera.yaw_deg(),
            "pitch_deg": camera.pitch_deg(),
            "fov_y_deg": fov,
            "ortho_height_m": a.ortho_hauteur,
            "hour": heure,
            "sun_elevation_deg": elevation,
            "sun_azimuth_deg": azimut,
            "turbidity": ciel.turbidity,
            "haze": ciel.haze,
            "exposure": ciel.exposure,
            "bloom": ciel.bloom,
            "ambient": a.ambiance,
            "view": a.vue,
            "voxel_mm": VOXEL_MM,
            "material_packet_fingerprint": format!("{:#018x}", materiaux.fingerprint()),
        });
        Ok(Self {
            graphe,
            camera,
            monde,
            streamer: ClipmapStreamer::new(1, ClipmapStreamer::BUDGET_PAR_DEFAUT),
            source,
            reglages,
            texte,
        })
    }
}

fn noms(tirs: &[Tir]) -> String {
    tirs.iter()
        .map(|t| t.name.as_str())
        .collect::<Vec<_>>()
        .join(", ")
}

impl Scene for ArbreScene {
    fn reglages_json(&self) -> serde_json::Value {
        let s = self.monde.stats();
        let mut j = self.reglages.clone();
        j["gpu_world"] = serde_json::json!({
            "chunks_pool": s.chunks_pool,
            "chunks_uniform": s.chunks_uniform,
            "bricks": s.bricks,
            "payload_words": s.payload_words,
            "bytes_uploaded": s.bytes_uploaded,
            "bytes_reserved": s.bytes_reserved,
        });
        j
    }

    fn deplacer(&mut self, avant: f32, droite: f32, haut: f32) {
        let (a, d) = (self.camera.avant(), self.camera.droite());
        let v = a * avant + d * droite + em_render::glam::Vec3::Y * haut;
        let p = self.camera.pos_mm();
        let nouveau = [
            p[0] + (v.x * 1000.0).round() as i64,
            p[1] + (v.y * 1000.0).round() as i64,
            p[2] + (v.z * 1000.0).round() as i64,
        ];
        // Un déplacement refusé (hors du monde) laisse la caméra où elle est.
        let _ = self
            .camera
            .set_pose(nouveau, self.camera.yaw_deg(), self.camera.pitch_deg());
    }

    fn tourner(&mut self, d_lacet: f32, d_tangage: f32) {
        // Convention de la fenêtre : lacet positif vers la gauche ; le lacet voxel croît vers la droite.
        let _ = self.camera.set_pose(
            self.camera.pos_mm(),
            self.camera.yaw_deg() - d_lacet.to_degrees(),
            self.camera.pitch_deg() + d_tangage.to_degrees(),
        );
    }

    fn set_lignes_supplementaires(&self, extra: &[String]) {
        if let Some(t) = &self.texte {
            let mut l = vec!["EMERGENCE - ARBRE (L09)".to_owned()];
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
        // La clipmap suit la caméra : tout se charge avant la première image (capture reproductible), puis
        // seules les fenêtres qui glissent travaillent.
        self.streamer
            .update_until_complete(&self.camera, self.source.scene(), &mut self.monde, gpu)?;
        let (l, h) = cible.size();
        let image = FrameContext::new_voxel(index, temps_s, l, h, self.camera)?;
        self.graphe.render(gpu, &image, cible, profileur)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn regarder_donne_le_lacet_du_nord_et_de_l_est() {
        let (nord, _) = regarder([0.0, 0.0, 0.0], [0.0, 0.0, 10.0]);
        let (est, _) = regarder([0.0, 0.0, 0.0], [10.0, 0.0, 0.0]);
        let (sud, _) = regarder([0.0, 0.0, 0.0], [0.0, 0.0, -10.0]);
        assert!(nord.abs() < 1e-4 && (est - 90.0).abs() < 1e-4 && (sud.abs() - 180.0).abs() < 1e-4);
        let (_, monte) = regarder([0.0, 0.0, 0.0], [0.0, 10.0, 10.0]);
        assert!((monte - 45.0).abs() < 1e-4, "tangage positif vers le haut");
    }

    #[test]
    fn la_scene_arbre_declare_ses_prises_et_garde_l_arbre_dans_la_fenetre() {
        let racine = crate::chemins::dossier_racine();
        let texte = std::fs::read_to_string(racine.join("lab/scenes/arbre.toml")).expect("arbre.toml");
        let f: FichierTirs = toml::from_str(&texte).expect("prises de vue");
        let noms: Vec<&str> = f.shot.iter().map(|t| t.name.as_str()).collect();
        for voulu in ["face", "trois_quarts", "contrejour", "feuillage", "tronc"] {
            assert!(noms.contains(&voulu), "prise « {voulu} » absente");
        }
        // La clipmap n'a qu'un niveau (25 m autour de la caméra) : l'arbre (x -5 à 4,3, z -3,9 à 5,9) doit y tenir.
        for t in &f.shot {
            let (dx, dz) = (t.pos_m[0], t.pos_m[2]);
            let loin = [
                (-5.0 - dx).abs(),
                (4.3 - dx).abs(),
                (-3.9 - dz).abs(),
                (5.9 - dz).abs(),
            ];
            assert!(
                loin.iter().all(|d| *d < 25.0),
                "la prise « {} » sort l'arbre de la fenêtre",
                t.name
            );
        }
    }
}
