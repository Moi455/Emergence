//! Le rendu par MAILLAGE RASTER de la scène (L33) : maille la région autour de la caméra avec `em_mesh`, cuit l'épaisseur
//! du feuillage pour le soleil de la scène, charge les quads sur le GPU et ajoute au graphe les passes d'ombres raster,
//! d'ambiance et de rendu. Le tracé compute (L09 à L14) reste disponible : `--rendu trace`.

use anyhow::bail;
use em_core::{ChunkKey, VOXEL_MM};
use em_mesh::{FoliageBaker, MesherConfig, VoxelColorer, WorldMesher};
use em_render::{
    LightSettings, MeshAmbientPass, MeshRenderer, MeshShadowPass, MeshWorld, Partage, RenderGraph,
    ShadowControl, ShadowParams, SkyParams,
};
use em_voxel::VoxelSource;
use serde::Serialize;
use std::time::Instant;

/// Rendu de base demandé en ligne de commande.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum RenduDemande {
    /// Maillage raster, occlusion baked (le rendu de base depuis L33).
    Maillage,
    /// Tracé compute de L09 à L14 (en option).
    Trace,
    /// Deux rendus côte à côte, AVANT (tracé) à gauche et APRÈS (maillage) à droite (capture seulement).
    Comparaison,
}

impl RenduDemande {
    /// Lit `maillage`, `trace` ou `ab`.
    pub fn lire(nom: &str) -> anyhow::Result<Self> {
        Ok(match nom {
            "maillage" => Self::Maillage,
            "trace" => Self::Trace,
            "ab" => Self::Comparaison,
            autre => bail!("rendu « {autre} » inconnu (maillage, trace, ab)"),
        })
    }
}

/// Réglages du maillage de la scène.
#[derive(Copy, Clone, Debug)]
pub struct OptionsMaillage {
    /// Rayon de la région maillée autour de la caméra, en mètres.
    pub rayon_m: f32,
    /// Fusion gloutonne.
    pub glouton: bool,
    /// Zone de comptage de l'épaisseur de feuillage, en voxels.
    pub zone_feuillage: u32,
}

/// Mesures du maillage de la scène (JSON des captures et du banc).
#[derive(Debug, Clone, Serialize)]
pub struct ResumeMaillage {
    /// Chunks maillés non vides.
    pub chunks: usize,
    /// Faces de voxel visibles avant fusion.
    pub faces: u64,
    /// Quads après fusion.
    pub quads: u64,
    /// Octets de quads sur le GPU.
    pub octets: u64,
    /// Remplissage des chunks depuis la source, ms.
    pub remplissage_ms: f64,
    /// Maillage (couleurs, occlusion, fusion), ms, tous les fils.
    pub maillage_ms: f64,
    /// Cuisson de l'épaisseur du feuillage, ms.
    pub feuillage_ms: f64,
    /// Fils de calcul disponibles.
    pub fils: usize,
    /// Fusion gloutonne active.
    pub glouton: bool,
}

/// Le monde de maillages d'une scène et ses mesures.
pub struct RenduMaillage {
    monde: MeshWorld,
    resume: ResumeMaillage,
}

/// Clés des chunks dont le centre est à moins de `rayon_m` de la caméra (en plan), du sol (chunk -1) jusqu'au ciel.
fn cles_autour(camera_mm: [i64; 3], rayon_m: f32) -> Vec<ChunkKey> {
    let r_mm = (f64::from(rayon_m) * 1000.0) as i64;
    let chunk_mm = VOXEL_MM * 64;
    let case = |mm: i64| mm.div_euclid(chunk_mm) as i32;
    let (x0, x1) = (case(camera_mm[0] - r_mm), case(camera_mm[0] + r_mm));
    let (z0, z1) = (case(camera_mm[2] - r_mm), case(camera_mm[2] + r_mm));
    let (y0, y1) = (case(camera_mm[1] - r_mm).max(-1), case(camera_mm[1] + r_mm));
    let demi_diag = f64::from(chunk_mm as f32) * 0.001 * 0.7072;
    let mut cles = Vec::new();
    for y in y0..=y1 {
        for z in z0..=z1 {
            for x in x0..=x1 {
                let centre =
                    |c: i32, cam: i64| ((i64::from(c) * chunk_mm + chunk_mm / 2 - cam) as f64) * 0.001;
                let d = centre(x, camera_mm[0]).hypot(centre(z, camera_mm[2]));
                if d <= f64::from(rayon_m) + demi_diag {
                    cles.push(ChunkKey::new(x, y, z));
                }
            }
        }
    }
    cles
}

impl RenduMaillage {
    /// Maille la région autour de la caméra et charge les quads sur le GPU.
    pub fn construire(
        gpu: &em_render::GpuContext,
        source: &dyn VoxelSource,
        colorier: &dyn VoxelColorer,
        camera_mm: [i64; 3],
        soleil: [f32; 3],
        opts: &OptionsMaillage,
    ) -> anyhow::Result<Self> {
        let cles = cles_autour(camera_mm, opts.rayon_m);
        let wm = WorldMesher::new(source, colorier, 0, MesherConfig::new(opts.glouton));
        let t0 = Instant::now();
        let chunks = wm.charger(&cles);
        let remplissage_ms = t0.elapsed().as_secs_f64() * 1e3;
        let t1 = Instant::now();
        let mut meshes = wm.mailler(&cles, &chunks);
        let maillage_ms = t1.elapsed().as_secs_f64() * 1e3;
        let t2 = Instant::now();
        FoliageBaker::new(colorier, &chunks).bake(&mut meshes, soleil, opts.zone_feuillage);
        let feuillage_ms = t2.elapsed().as_secs_f64() * 1e3;
        let monde = MeshWorld::new(gpu);
        monde.replace_with(&meshes, Some(opts.zone_feuillage));
        let resume = ResumeMaillage {
            chunks: meshes.len(),
            faces: meshes.iter().map(|m| u64::from(m.face_count())).sum(),
            quads: meshes.iter().map(|m| m.quad_count() as u64).sum(),
            octets: meshes.iter().map(|m| m.bytes() as u64).sum(),
            remplissage_ms,
            maillage_ms,
            feuillage_ms,
            fils: std::thread::available_parallelism().map_or(1, usize::from),
            glouton: opts.glouton,
        };
        log::info!(
            "maillage : {} chunks, {} quads ({:.1} Mo), remplissage {:.0} ms, maillage {:.0} ms, feuillage {:.0} ms",
            resume.chunks,
            resume.quads,
            resume.octets as f64 / 1e6,
            resume.remplissage_ms,
            resume.maillage_ms,
            resume.feuillage_ms
        );
        Ok(Self { monde, resume })
    }

    /// Mesures du maillage.
    pub fn resume(&self) -> &ResumeMaillage {
        &self.resume
    }

    /// Ajoute au graphe les passes du rendu par maillage : cascades d'ombre raster (si `ombres`), ambiance du ciel,
    /// rendu. Le ciel et son fond doivent précéder ; le bloom et la composition suivre.
    pub fn ajouter_passes(
        &self,
        graphe: &mut RenderGraph,
        ciel: Partage<SkyParams>,
        lumiere: Partage<LightSettings>,
        ombres: Option<ShadowParams>,
    ) -> anyhow::Result<Option<ShadowControl>> {
        let controle = match ombres {
            Some(p) => {
                let passe = MeshShadowPass::new(p, ciel, self.monde.clone());
                let c = passe.control();
                graphe.add(Box::new(passe))?;
                Some(c)
            }
            None => None,
        };
        graphe.add(Box::new(MeshAmbientPass::new()))?;
        graphe.add(Box::new(MeshRenderer::new(self.monde.clone(), lumiere)))?;
        Ok(controle)
    }
}
