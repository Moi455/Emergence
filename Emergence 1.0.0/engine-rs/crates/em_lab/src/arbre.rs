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
    AdapterReport, AmbientOcclusionParams, AmbientOcclusionPass, BloomPass, ClipmapConfig, ClipmapStreamer,
    CloudParams, DebugView, DepthMergePass, FoliageLightParams, FoliageThicknessPass, FrameContext,
    FrameTarget, GpuContext, GpuMaterials, GpuProfiler, LightSettings, LightingPass, Partage, PostParams,
    Projection, Regeneration, RenderGraph, ShadowCascades, ShadowControl, ShadowParams, SkyBackgroundPass,
    SkyParams, SkyPass, SunModel, TonemapPass, VoxelCamera, VoxelGpuWorld, VoxelMaterialPass, VoxelTracePass,
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
    /// Scène « materiaux » (L23p) : mode de matière `continu`, `voxel`, ou `ab` (capture : les deux côte à côte).
    #[arg(long, default_value = "continu")]
    pub mode: String,
    /// Scène « materiaux » : écrit « A » / « B » et le mode sur l'image (forcé par `--mode ab`).
    #[arg(long)]
    pub etiquette: bool,
    /// Désactive les ombres du soleil (comparaison A/B, mesure du coût de l'éclairage seul).
    #[arg(long)]
    pub sans_ombres: bool,
    /// Banc : refait les cascades en continu (coût soutenu d'une génération permanente) au lieu du coût au repos.
    #[arg(long)]
    pub ombres_continu: bool,
    /// Tuiles de 128 × 128 texels remplies par image (défaut du préréglage `haut`).
    #[arg(long)]
    pub ombres_tuiles: Option<u32>,
    /// Nombre de cascades, 3 ou 4.
    #[arg(long)]
    pub ombres_cascades: Option<u32>,
    /// Côté des cascades en texels (puissance de 2, 256 à 2048).
    #[arg(long)]
    pub ombres_taille: Option<u32>,
    /// Texel de la cascade 0 en centimètres (défaut 1,25).
    #[arg(long)]
    pub ombres_texel_cm: Option<f32>,
    /// Rayon maximal de la pénombre en centimètres (0 = ombre dure).
    #[arg(long)]
    pub ombres_penombre_cm: Option<f32>,
    /// Échelle de la pénombre physique (0 à 1).
    #[arg(long)]
    pub ombres_echelle: Option<f32>,
    /// Décalage selon la normale, en texels.
    #[arg(long)]
    pub ombres_decalage: Option<f32>,
    /// Biais de profondeur constant en millimètres.
    #[arg(long)]
    pub ombres_biais_mm: Option<f32>,
    /// Biais de pente (texels × tangente).
    #[arg(long)]
    pub ombres_pente: Option<f32>,
    /// Désactive l'occlusion ambiante tracée (comparaison A/B, mesure du coût de l'éclairage seul).
    #[arg(long)]
    pub sans_ao: bool,
    /// Capture : deux rendus côte à côte, AVANT (sans occlusion ambiante) à gauche et APRÈS à droite.
    #[arg(long)]
    pub ao_ab: bool,
    /// Rayons d'occlusion par pixel (1 à 16 ; défaut 6).
    #[arg(long)]
    pub ao_rayons: Option<u32>,
    /// Portée des rayons d'occlusion en mètres (0,1 à 4 ; défaut 1,0).
    #[arg(long)]
    pub ao_portee: Option<f32>,
    /// Force de l'occlusion ambiante (0 à 2 ; défaut 1).
    #[arg(long)]
    pub ao_force: Option<f32>,
    /// Rayon du filtre bilatéral de l'occlusion en pixels (0 à 3 ; défaut 2).
    #[arg(long)]
    pub ao_filtre: Option<u32>,
    /// Diviseur de résolution du tracé des rayons d'occlusion : 1 ou 2 (défaut 2 : un jeu de rayons par bloc de 2 x 2 pixels).
    #[arg(long)]
    pub ao_diviseur: Option<u32>,
    /// Éteint la lumière du feuillage (translucidité, liseré, épaisseur) : comparaison A/B et mesure du coût.
    #[arg(long)]
    pub sans_feuillage: bool,
    /// Force de la translucidité des feuilles (0 à 4 ; défaut 1,1).
    #[arg(long)]
    pub feuillage_translucidite: Option<f32>,
    /// Longueur d'absorption du feuillage en mètres (0,05 à 2 ; défaut 1,0).
    #[arg(long)]
    pub feuillage_absorption: Option<f32>,
    /// Lobe vers l'avant de la translucidité (0 à 1 ; défaut 0,5).
    #[arg(long)]
    pub feuillage_avant: Option<f32>,
    /// Teinte de transmission `r,v,b` (chaque canal 0 à 2 ; défaut 0.7,1,0.2).
    #[arg(long, value_delimiter = ',')]
    pub feuillage_teinte: Option<Vec<f32>>,
    /// Force du liseré de contre-jour (0 à 4 ; défaut 0,3).
    #[arg(long)]
    pub feuillage_lisere: Option<f32>,
    /// Épaisseur de feuillage sous laquelle le liseré brille, en mètres (0,05 à 1 ; défaut 0,20).
    #[arg(long)]
    pub feuillage_lisere_epaisseur: Option<f32>,
    /// Saturation du feuillage (0,5 à 2 ; défaut 1,05).
    #[arg(long)]
    pub feuillage_saturation: Option<f32>,
    /// Soulèvement bleu-violet des ombres, part de l'éclairement du soleil (0 à 0,5 ; défaut 0,02).
    #[arg(long)]
    pub feuillage_ombres: Option<f32>,
    /// Teinte du soulèvement des ombres `r,v,b` (défaut 0.45,0.55,1).
    #[arg(long, value_delimiter = ',')]
    pub feuillage_ombres_teinte: Option<Vec<f32>>,
    /// Voxels comptés le long du soleil pour l'épaisseur (4 à 48 ; défaut 48).
    #[arg(long)]
    pub feuillage_zone: Option<u32>,
    /// Gain d'exposition du regard, multiplie `--exposure` (0,25 à 4 ; défaut 0,8).
    #[arg(long)]
    pub regard_exposition: Option<f32>,
    /// Saturation du regard AgX (0,5 à 2 ; défaut 1,1).
    #[arg(long)]
    pub regard_saturation: Option<f32>,
    /// Contraste du regard AgX, puissance (0,5 à 2 ; défaut 1,2).
    #[arg(long)]
    pub regard_contraste: Option<f32>,
    /// Chaleur du regard à la golden hour (0 à 0,3 ; défaut 0,10) : nulle au-dessus de 30° de soleil, pleine sous 5°.
    #[arg(long)]
    pub regard_chaleur: Option<f32>,
}

impl ArgsArbre {
    /// Occlusion ambiante : défauts de `AmbientOcclusionParams` modifiés par la ligne de commande, validés.
    pub fn parametres_ao(&self) -> anyhow::Result<AmbientOcclusionParams> {
        let d = AmbientOcclusionParams::default();
        Ok(AmbientOcclusionParams::new(
            self.ao_rayons.unwrap_or(d.rays()),
            self.ao_portee.unwrap_or(d.range_m()),
        )?
        .with_strength(self.ao_force.unwrap_or(d.strength()))?
        .with_filter(self.ao_filtre.unwrap_or(d.filter_px()))?
        .with_resolution_divisor(self.ao_diviseur.unwrap_or(d.resolution_divisor()))?)
    }

    /// Réglages d'ombre : préréglage `haut` modifié par les options de la ligne de commande, validés.
    pub fn parametres_ombres(&self) -> anyhow::Result<ShadowParams> {
        let d = ShadowParams::default();
        let mut p = ShadowParams::new(
            self.ombres_cascades.unwrap_or(d.cascades()),
            self.ombres_texel_cm.map_or(d.first_texel_m(), |cm| cm * 0.01),
            self.ombres_taille.unwrap_or(d.size()),
        )?;
        if let Some(n) = self.ombres_tuiles {
            p = p.with_tiles_per_frame(n)?;
        }
        p = p.with_bias(
            self.ombres_biais_mm.map_or(d.depth_bias_m(), |mm| mm * 0.001),
            self.ombres_pente.unwrap_or(d.slope_bias()),
        )?;
        p = p.with_normal_offset(self.ombres_decalage.unwrap_or(d.normal_offset()))?;
        p = p.with_penumbra(
            self.ombres_echelle.unwrap_or(d.penumbra_scale()),
            self.ombres_penombre_cm.map_or(d.penumbra_max_m(), |cm| cm * 0.01),
        )?;
        if self.ombres_continu {
            p = p.with_regeneration(Regeneration::Continue);
        }
        Ok(p)
    }
}

fn teinte(nom: &str, v: &Option<Vec<f32>>, defaut: [f32; 3]) -> anyhow::Result<[f32; 3]> {
    match v {
        Some(v) if v.len() == 3 => Ok([v[0], v[1], v[2]]),
        Some(_) => bail!("{nom} attend trois nombres r,v,b"),
        None => Ok(defaut),
    }
}

impl ArgsArbre {
    /// Lumière du feuillage : défauts de `FoliageLightParams` modifiés par la ligne de commande, validés.
    pub fn parametres_feuillage(&self) -> anyhow::Result<FoliageLightParams> {
        let d = FoliageLightParams::default();
        let p = FoliageLightParams::new(
            self.feuillage_translucidite.unwrap_or(d.translucency()),
            self.feuillage_absorption.unwrap_or(d.absorption_m()),
        )?
        .with_transmission(
            self.feuillage_avant.unwrap_or(d.forward()),
            teinte("--feuillage-teinte", &self.feuillage_teinte, d.tint())?,
        )?
        .with_rim(
            self.feuillage_lisere.unwrap_or(d.rim()),
            self.feuillage_lisere_epaisseur.unwrap_or(d.rim_thickness_m()),
        )?
        .with_color(
            self.feuillage_saturation.unwrap_or(d.saturation()),
            self.feuillage_ombres.unwrap_or(d.shadow_lift()),
            teinte(
                "--feuillage-ombres-teinte",
                &self.feuillage_ombres_teinte,
                d.shadow_tint(),
            )?,
        )?
        .with_zone(self.feuillage_zone.unwrap_or(d.zone_voxels()))?
        .with_grade(
            self.regard_exposition.unwrap_or(d.exposure_gain()),
            self.regard_saturation.unwrap_or(d.grade_saturation()),
            self.regard_contraste.unwrap_or(d.grade_contrast()),
            self.regard_chaleur.unwrap_or(d.grade_warmth()),
        )?;
        Ok(if self.sans_feuillage {
            // Éteint la translucidité et le liseré ; la saturation et le regard restent ceux demandés.
            FoliageLightParams::new(0.0, p.absorption_m())?
                .with_rim(0.0, p.rim_thickness_m())?
                .with_color(p.saturation(), p.shadow_lift(), p.shadow_tint())?
                .with_grade(
                    p.exposure_gain(),
                    p.grade_saturation(),
                    p.grade_contrast(),
                    p.grade_warmth(),
                )?
        } else {
            p
        })
    }
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
    ombres: Option<ShadowControl>,
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
        let feuillage = a.parametres_feuillage()?;
        let post = Partage::new(
            PostParams::new(ciel.exposure * feuillage.exposure_gain(), ciel.bloom)?.with_look(
                0.10,
                feuillage.grade_saturation(),
                feuillage.grade_contrast(),
                feuillage.warmth_at(elevation),
            )?,
        );
        let vue = DebugView::from_name(&a.vue).with_context(|| {
            format!(
                "vue « {} » inconnue (image, albedo, normales, distance, masque)",
                a.vue
            )
        })?;
        let lumiere = Partage::new(LightSettings::new(vue, a.ambiance)?.with_foliage(feuillage));

        let params_ombres = a.parametres_ombres()?;
        let monde = VoxelGpuWorld::new(gpu, ClipmapConfig::laboratoire())?;
        let mut graphe = RenderGraph::new();
        graphe.add(Box::new(SkyPass::new(partage_ciel.clone())))?;
        graphe.add(Box::new(SkyBackgroundPass::new()))?;
        // Ombres du soleil : cascades remplies par la traversée de la grille voxel, avant le tracé primaire.
        let ombres = if a.sans_ombres {
            None
        } else {
            let pass = ShadowCascades::new(params_ombres, partage_ciel.clone(), monde.bindings());
            let controle = pass.control();
            graphe.add(Box::new(pass))?;
            Some(controle)
        };
        graphe.add(Box::new(VoxelTracePass::new(monde.bindings())))?;
        graphe.add(Box::new(VoxelMaterialPass::new(materiaux.bindings())))?;
        graphe.add(Box::new(DepthMergePass::new()))?;
        // Occlusion ambiante tracée : lue par l'éclairage (elle n'assombrit que l'ambiance).
        let params_ao = a.parametres_ao()?;
        if !a.sans_ao {
            graphe.add(Box::new(AmbientOcclusionPass::new(
                Partage::new(params_ao),
                monde.bindings(),
            )))?;
        }
        if !a.sans_feuillage {
            // Épaisseur du feuillage le long du soleil : lue par l'éclairage (translucidité, liseré).
            graphe.add(Box::new(FoliageThicknessPass::new(
                lumiere.clone(),
                monde.bindings(),
                materiaux.bindings(),
            )))?;
        }
        graphe.add(Box::new(LightingPass::new(lumiere)))?;
        graphe.add(Box::new(BloomPass::new()))?;
        graphe.add(Box::new(TonemapPass::new(post)))?;
        let texte = if ciel.overlay {
            let t = OverlayText::new();
            t.set_lines(vec![
                "EMERGENCE - ARBRE (L10)".to_owned(),
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
            "foliage": if a.sans_feuillage { serde_json::Value::Null } else { serde_json::json!({
                "translucency": feuillage.translucency(),
                "absorption_m": feuillage.absorption_m(),
                "forward": feuillage.forward(),
                "tint": feuillage.tint(),
                "rim": feuillage.rim(),
                "rim_thickness_m": feuillage.rim_thickness_m(),
                "zone_voxels": feuillage.zone_voxels(),
            }) },
            "grade": {
                "exposure_gain": feuillage.exposure_gain(),
                "saturation": feuillage.grade_saturation(),
                "contrast": feuillage.grade_contrast(),
                "warmth": feuillage.warmth_at(elevation),
                "leaf_saturation": feuillage.saturation(),
                "shadow_lift": feuillage.shadow_lift(),
                "shadow_tint": feuillage.shadow_tint(),
            },
            "shadows": if a.sans_ombres { serde_json::Value::Null } else { serde_json::json!({
                "cascades": params_ombres.cascades(),
                "size": params_ombres.size(),
                "first_texel_m": params_ombres.first_texel_m(),
                "far_m": (0..params_ombres.cascades()).map(|c| params_ombres.far_m(c)).collect::<Vec<_>>(),
                "penumbra_max_m": params_ombres.penumbra_max_m(),
                "penumbra_scale": params_ombres.penumbra_scale(),
                "normal_offset_texels": params_ombres.normal_offset(),
                "depth_bias_m": params_ombres.depth_bias_m(),
                "slope_bias": params_ombres.slope_bias(),
                "continuous": a.ombres_continu,
            }) },
            "ambient_occlusion": ao_json(a.sans_ao, &params_ao),
            "view": a.vue,
            "voxel_mm": VOXEL_MM,
            "material_packet_fingerprint": format!("{:#018x}", materiaux.fingerprint()),
        });
        Ok(Self {
            graphe,
            camera,
            monde,
            streamer: ClipmapStreamer::new(1, ClipmapStreamer::BUDGET_PAR_DEFAUT),
            ombres,
            source,
            reglages,
            texte,
        })
    }
}

/// Réglages d'occlusion ambiante pour le JSON écrit à côté d'une capture (nul si elle est éteinte).
pub fn ao_json(sans_ao: bool, p: &AmbientOcclusionParams) -> serde_json::Value {
    if sans_ao {
        return serde_json::Value::Null;
    }
    serde_json::json!({
        "rays": p.rays(),
        "range_m": p.range_m(),
        "strength": p.strength(),
        "filter_px": p.filter_px(),
        "resolution_divisor": p.resolution_divisor(),
    })
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
            let mut l = vec!["EMERGENCE - ARBRE (L10)".to_owned()];
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
        let flux =
            self.streamer
                .update_until_complete(&self.camera, self.source.scene(), &mut self.monde, gpu)?;
        // Des chunks sont arrivés ou partis : leurs ombres ne sont pas dans les cascades, on les refait.
        if let Some(o) = &self.ombres
            && (flux.uploaded > 0 || flux.evicted > 0)
        {
            o.invalidate();
        }
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
