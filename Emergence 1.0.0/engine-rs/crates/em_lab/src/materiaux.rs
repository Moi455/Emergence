//! Scène « materiaux » (L23p) : un auvent de bâti (mur de pierre, deux poteaux, une poutre, un toit de bardeaux),
//! posé sur un sol de turf, rendu au choix en matière CONTINUE (A, mode actuel de L09) ou en VARIATION PAR VOXEL
//! (B, `VoxelPixel`) : la même scène, le même soleil, la même caméra. Monsieur tranche, par matière, sur les captures.
//!
//! ```text
//! lab.sh capture --scene materiaux --mode continu --shot pierre_pres --hour 10 --out a.png
//! lab.sh capture --scene materiaux --mode voxel   --shot pierre_pres --hour 10 --out b.png
//! lab.sh capture --scene materiaux --mode ab      --shot pierre_pres --hour 10 --out ab.png   (A à gauche, B à droite)
//! lab.sh bench   --scene materiaux --mode voxel   --shot ensemble_moyen
//! ```
//!
//! Ordre des passes : ciel (LUT), fond de ciel, tracé primaire, matière, profondeur, éclairage, bloom, AgX.

use crate::arbre::{ArgsArbre, Tir, ao_json, regarder};
use crate::chemins::{dossier_captures, dossier_racine};
use crate::ciel::ArgsCiel;
use crate::maillage::{OptionsMaillage, RenduDemande, RenduMaillage};
use crate::scene::Scene;
use crate::scene_statique::SceneStatique;
use anyhow::{Context, bail};
use em_core::VOXEL_MM;
use em_gen::BuildingClasses;
use em_material::{MaterialMode, MaterialTable, StyleSheet, VegetationRamps};
use em_mesh::MaterialColorer;
use em_render::hello::{OverlayText, TextOverlayPass};
use em_render::{
    AdapterReport, AmbientOcclusionPass, BloomPass, ClipmapConfig, ClipmapStreamer, CloudParams, DebugView,
    DepthMergePass, FrameContext, FrameTarget, GpuContext, GpuMaterials, GpuProfiler, LightSettings,
    LightingPass, OffscreenTarget, Partage, PostParams, Projection, RenderGraph, SkyBackgroundPass,
    SkyParams, SkyPass, SunModel, TonemapPass, VoxelCamera, VoxelGpuWorld, VoxelMaterialPass, VoxelTracePass,
    read_texture,
};
use serde::Deserialize;
use std::path::PathBuf;

/// Fichier de scène par défaut de `materiaux` (relatif à `engine-rs/`).
const FICHIER: &str = "lab/scenes/materiaux.toml";
/// Fichier de scène par défaut de `arbre` : s'il est resté tel quel, on prend celui de `materiaux`.
const FICHIER_ARBRE: &str = "lab/scenes/arbre.toml";

/// Le mode demandé en ligne de commande : un rendu, ou la comparaison de deux.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum ModeDemande {
    /// Un seul rendu, dans ce mode de matière.
    Seul(MaterialMode),
    /// Deux rendus, A (continu) et B (voxel), côte à côte (capture seulement).
    Comparaison,
}

impl ModeDemande {
    /// Lit `continu`, `voxel` ou `ab`.
    pub fn lire(nom: &str) -> anyhow::Result<Self> {
        if nom == "ab" {
            return Ok(Self::Comparaison);
        }
        match MaterialMode::from_name(nom) {
            Some(m) => Ok(Self::Seul(m)),
            None => bail!("mode « {nom} » inconnu (continu, voxel, ab)"),
        }
    }
}

#[derive(Deserialize)]
struct FichierTirs {
    origin_m: [f64; 3],
    #[serde(default)]
    shot: Vec<Tir>,
}

/// Mètres -> millimètres entiers (arrondi au plus proche).
fn mm(m: f64) -> i64 {
    (m * 1000.0).round() as i64
}

/// Ce que la scène garde du rendu choisi : le tracé compute (mémoire GPU de la grille et diffusion) ou le maillage.
enum Rendu {
    Trace {
        monde: Box<VoxelGpuWorld>,
        streamer: ClipmapStreamer,
    },
    Maillage {
        monde: Box<RenduMaillage>,
    },
}

/// La scène « materiaux ».
pub struct MateriauxScene {
    graphe: RenderGraph,
    camera: VoxelCamera,
    rendu: Rendu,
    source: SceneStatique,
    reglages: serde_json::Value,
    texte: Option<OverlayText>,
    etiquette: String,
}

impl MateriauxScene {
    /// Nom de la scène en ligne de commande.
    pub const NOM: &'static str = "materiaux";

    /// Construit la scène dans un mode de matière donné : charge la table, les recettes, monte les passes.
    pub fn new(
        gpu: &GpuContext,
        info: &AdapterReport,
        ciel: &ArgsCiel,
        a: &ArgsArbre,
        mode: MaterialMode,
    ) -> anyhow::Result<Self> {
        let racine = dossier_racine();
        let nom_fichier = if a.scene_fichier == FICHIER_ARBRE {
            FICHIER
        } else {
            &a.scene_fichier
        };
        let fichier = racine.join(nom_fichier);

        // matières : fichiers de données du dépôt ; les recettes utilisent les classes de cette table
        let donnees = racine.join("../engine/data");
        let table = MaterialTable::load(
            &donnees.join("materials.csv"),
            &donnees.join("material_render.toml"),
        )
        .context("table des matières")?;
        let classes = BuildingClasses::from_table(&table).context("classes du bâti")?;
        let source = SceneStatique::charger_avec(&fichier, &racine, classes)?;
        let texte_toml =
            std::fs::read_to_string(&fichier).with_context(|| format!("lecture de {}", fichier.display()))?;
        let tirs: FichierTirs = toml::from_str(&texte_toml).context("prises de vue de la scène")?;
        let mut config_style = source.style().clone();
        if let Some(g) = a.granulometrie {
            config_style.granulometrie_force = Some(g);
        }
        let style = StyleSheet::from_config(&config_style, &table, mode).context("style de la scène")?;
        let empreinte_style = style.fingerprint();
        let nb_classes_voxel = style.pixel_class_count();
        let force_granulo = style.granulometry_force();
        let rendu_demande = RenduDemande::lire(&a.rendu)?;
        if rendu_demande == RenduDemande::Comparaison {
            bail!("--rendu ab ne se capture qu'avec la commande `capture` (deux rendus côte à côte)");
        }
        let veg = VegetationRamps::new();
        // le colorieur du maillage prend la feuille de style (clonée : le paquet GPU du tracé la consomme)
        let colorier = (rendu_demande == RenduDemande::Maillage)
            .then(|| MaterialColorer::new(&table, &veg, style.clone()));
        let materiaux = (rendu_demande == RenduDemande::Trace)
            .then(|| GpuMaterials::with_style(gpu, &table, &veg, style));

        // prise de vue : nommée, ou construite à la main (mêmes options que la scène arbre)
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
            .unwrap_or([1.8, 1.6, -3.0]);
        let cible = triplet(&a.look_at, "--look-at")?.or(tir.as_ref().and_then(|t| t.look_at_m));
        let defaut = [1.8, 1.4, 0.0];
        let (lacet, tangage) = match (cible, a.yaw, a.pitch, &tir) {
            (Some(c), _, _, _) => regarder(pos_m, c),
            (None, Some(y), p, _) => (y, p.unwrap_or(0.0)),
            (None, None, Some(p), Some(t)) => (t.yaw_deg, p),
            (None, None, None, Some(t)) => (t.yaw_deg, t.pitch_deg),
            (None, None, p, None) => (regarder(pos_m, defaut).0, p.unwrap_or(regarder(pos_m, defaut).1)),
        };
        let fov = a.champ.or(tir.as_ref().map(|t| t.fov_deg)).unwrap_or(ciel.fov);
        let projection = match a.ortho_hauteur {
            Some(h) => Projection::Orthographic { height_m: h },
            None => Projection::Perspective { fov_y_deg: fov },
        };
        let o = tirs.origin_m;
        let pos_mm = [mm(o[0] + pos_m[0]), mm(o[1] + pos_m[1]), mm(o[2] + pos_m[2])];
        let camera = VoxelCamera::new(pos_mm, lacet, tangage, projection).context("caméra voxel")?;

        // soleil : même convention que la scène arbre
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
        let params_ciel_soleil = {
            let d = params_ciel.sun_direction();
            [d.x, d.y, d.z]
        };
        let partage_ciel = Partage::new(params_ciel);
        let post = Partage::new(PostParams::new(ciel.exposure, ciel.bloom)?);
        let vue = DebugView::from_name(&a.vue).with_context(|| {
            format!(
                "vue « {} » inconnue (image, albedo, normales, distance, masque)",
                a.vue
            )
        })?;
        let lumiere = Partage::new(LightSettings::new(vue, a.ambiance)?);

        let mut graphe = RenderGraph::new();
        graphe.add(Box::new(SkyPass::new(partage_ciel.clone())))?;
        graphe.add(Box::new(SkyBackgroundPass::new()))?;
        let params_ao = a.parametres_ao()?;
        let rendu = match (&colorier, &materiaux) {
            (Some(colorier), _) => {
                let s = params_ciel_soleil;
                let monde = RenduMaillage::construire(
                    gpu,
                    source.scene(),
                    colorier,
                    pos_mm,
                    s,
                    &OptionsMaillage {
                        rayon_m: a.maillage_rayon,
                        glouton: !a.sans_fusion,
                        zone_feuillage: 48,
                        creux: a.parametres_creux()?,
                    },
                )?;
                monde.ajouter_passes(
                    &mut graphe,
                    partage_ciel.clone(),
                    lumiere.clone(),
                    (!a.sans_ombres).then_some(a.parametres_ombres()?),
                    a.style_maillage()?,
                )?;
                Rendu::Maillage {
                    monde: Box::new(monde),
                }
            }
            (None, Some(materiaux)) => {
                let monde = VoxelGpuWorld::new(gpu, ClipmapConfig::laboratoire())?;
                graphe.add(Box::new(VoxelTracePass::new(monde.bindings())))?;
                graphe.add(Box::new(VoxelMaterialPass::new(materiaux.bindings())))?;
                graphe.add(Box::new(DepthMergePass::new()))?;
                if !a.sans_ao {
                    graphe.add(Box::new(AmbientOcclusionPass::new(
                        Partage::new(params_ao),
                        monde.bindings(),
                    )))?;
                }
                graphe.add(Box::new(LightingPass::new(lumiere)))?;
                Rendu::Trace {
                    monde: Box::new(monde),
                    streamer: ClipmapStreamer::new(1, ClipmapStreamer::BUDGET_PAR_DEFAUT),
                }
            }
            (None, None) => unreachable!("un rendu est toujours choisi"),
        };
        graphe.add(Box::new(BloomPass::new()))?;
        graphe.add(Box::new(TonemapPass::new(post)))?;
        let etiquette = match mode {
            MaterialMode::Continuous => "A  MATIERE CONTINUE".to_owned(),
            MaterialMode::VoxelPixel => "B  VARIATION PAR VOXEL".to_owned(),
        };
        let texte = if ciel.overlay || a.etiquette || a.mode == "ab" {
            let t = OverlayText::new();
            let mut lignes = vec![etiquette.clone()];
            if ciel.overlay {
                lignes.push(format!("GPU: {}", info.name));
                lignes.push(format!("SOLEIL: {elevation:.1} / {azimut:.1} DEG ({heure:.1} H)"));
            }
            t.set_lines(lignes);
            graphe.add(Box::new(TextOverlayPass::new(t.clone(), 56, 12, 3)))?;
            Some(t)
        } else {
            None
        };
        let reglages = serde_json::json!({
            "scene": source.nom(),
            "mode": mode.name(),
            "recipes": source.recettes(),
            "style_fingerprint": format!("{empreinte_style:#018x}"),
            "voxel_pixel_classes": nb_classes_voxel,
            "shot": tir.as_ref().map(|t| t.name.clone()),
            "camera_m": pos_m,
            "camera_mm_monde": pos_mm,
            "yaw_deg": camera.yaw_deg(),
            "pitch_deg": camera.pitch_deg(),
            "fov_y_deg": fov,
            "hour": heure,
            "sun_elevation_deg": elevation,
            "sun_azimuth_deg": azimut,
            "turbidity": ciel.turbidity,
            "haze": ciel.haze,
            "exposure": ciel.exposure,
            "bloom": ciel.bloom,
            "ambient": a.ambiance,
            "ambient_occlusion": ao_json(a.sans_ao, &params_ao),
            "view": a.vue,
            "voxel_mm": VOXEL_MM,
            "material_packet_fingerprint": materiaux.as_ref().map(|m| format!("{:#018x}", m.fingerprint())),
            "rendu": a.rendu,
            "granulometrie_force": force_granulo.raw() as f64 / 65_536.0,
        });
        Ok(Self {
            graphe,
            camera,
            rendu,
            source,
            reglages,
            texte,
            etiquette,
        })
    }
}

fn noms(tirs: &[Tir]) -> String {
    tirs.iter()
        .map(|t| t.name.as_str())
        .collect::<Vec<_>>()
        .join(", ")
}

impl Scene for MateriauxScene {
    fn reglages_json(&self) -> serde_json::Value {
        let mut j = self.reglages.clone();
        if let Rendu::Maillage { monde } = &self.rendu {
            j["mesh"] = serde_json::to_value(monde.resume()).unwrap_or_default();
        }
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
        let _ = self
            .camera
            .set_pose(nouveau, self.camera.yaw_deg(), self.camera.pitch_deg());
    }

    fn tourner(&mut self, d_lacet: f32, d_tangage: f32) {
        let _ = self.camera.set_pose(
            self.camera.pos_mm(),
            self.camera.yaw_deg() - d_lacet.to_degrees(),
            self.camera.pitch_deg() + d_tangage.to_degrees(),
        );
    }

    fn set_lignes_supplementaires(&self, extra: &[String]) {
        if let Some(t) = &self.texte {
            let mut l = vec![self.etiquette.clone()];
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
        if let Rendu::Trace { monde, streamer } = &mut self.rendu {
            streamer.update_until_complete(&self.camera, self.source.scene(), monde, gpu)?;
        }
        let (l, h) = cible.size();
        let image = FrameContext::new_voxel(index, temps_s, l, h, self.camera)?;
        self.graphe.render(gpu, &image, cible, profileur)?;
        Ok(())
    }
}

/// Capture de la comparaison A/B : le même instant, la même caméra, deux rendus (continu à gauche, voxel à droite),
/// écrits en trois PNG déterministes : `<nom>.png` (côte à côte), `<nom>_A.png` et `<nom>_B.png`.
pub fn capturer_ab(
    gpu: &GpuContext,
    ciel: &ArgsCiel,
    a: &ArgsArbre,
    largeur: u32,
    hauteur: u32,
    frames: u32,
    sortie: &std::path::Path,
) -> anyhow::Result<Vec<PathBuf>> {
    let mut images = Vec::new();
    let mut reglages = Vec::new();
    for mode in [MaterialMode::Continuous, MaterialMode::VoxelPixel] {
        let mut cible = OffscreenTarget::new(gpu, largeur, hauteur)?;
        let mut scene = MateriauxScene::new(gpu, gpu.info(), ciel, a, mode)?;
        let mut profil = GpuProfiler::new(gpu, 32);
        for i in 0..=u64::from(frames) {
            scene.dessiner(gpu, &mut cible, &mut profil, i, 0.0)?;
        }
        images.push(read_texture(gpu, cible.texture())?);
        reglages.push(scene.reglages_json());
    }
    let (ia, ib) = (&images[0], &images[1]);
    let stem = sortie
        .file_stem()
        .map_or_else(|| "ab".into(), |s| s.to_string_lossy().into_owned());
    let dossier = sortie
        .parent()
        .map_or_else(dossier_captures, std::path::Path::to_path_buf);
    std::fs::create_dir_all(&dossier)?;
    let chemins = vec![
        sortie.to_path_buf(),
        dossier.join(format!("{stem}_A.png")),
        dossier.join(format!("{stem}_B.png")),
    ];
    std::fs::write(&chemins[0], ia.juxtaposer(ib, 6)?.encoder_png()?)?;
    std::fs::write(&chemins[1], ia.encoder_png()?)?;
    std::fs::write(&chemins[2], ib.encoder_png()?)?;
    let json = serde_json::json!({
        "scene": MateriauxScene::NOM,
        "mode": "ab",
        "resolution_each": [largeur, hauteur],
        "warmup_frames": frames,
        "adapter": gpu.info().name,
        "A_continu": reglages[0],
        "B_voxel": reglages[1],
    });
    std::fs::write(
        sortie.with_extension("json"),
        serde_json::to_string_pretty(&json)?,
    )?;
    Ok(chemins)
}
