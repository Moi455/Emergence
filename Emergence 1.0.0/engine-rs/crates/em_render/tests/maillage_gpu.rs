//! Essais GPU du rendu par maillage (L33) contre le tracé compute de L09 à L14, sur le chêne de référence : sans ombres,
//! sans occlusion et sans translucidité (ce que le maillage fait autrement : ombres raster, occlusion baked, épaisseur
//! cuite), les deux rendus doivent être le même tableau. Sans adaptateur ils s'ignorent ; sans le chêne
//! (`~/.local/share/emergence/lab_assets/trees/chene_42.vxm`) aussi.
//!
//! - silhouette : IoU de la vue « masque » >= 0,99 ;
//! - couleur : ΔE moyen (CIE76) <= 4 sur la vue « image » hors ombres, occlusion et translucidité ;
//! - albédo seul : ΔE moyen <= 1 (les couleurs plates des voxels sont celles du shader de matière) ;
//! - le rendu par maillage est reproductible octet pour octet.

use em_core::{ChunkKey, VoxelCoord};
use em_gen::{PlacedModel, StaticScene, VxmModel, vegetation_ramps};
use em_material::{MaterialTable, StyleSheet};
use em_mesh::{FoliageBaker, MaterialColorer, MesherConfig, WorldMesher};
use em_render::{
    BloomPass, ClipmapConfig, ClipmapStreamer, DebugView, DepthMergePass, FoliageLightParams, FrameContext,
    GpuContext, GpuMaterials, GpuProfiler, GpuRequest, LightSettings, LightingPass, MeshAmbientPass,
    MeshRenderer, MeshShadowPass, MeshWorld, OffscreenTarget, Partage, PostParams, Projection, RenderGraph,
    RgbaImage, ShadowParams, SkyBackgroundPass, SkyParams, SkyPass, TonemapPass, VoxelCamera, VoxelGpuWorld,
    VoxelMaterialPass, VoxelTracePass, read_texture,
};
use std::path::PathBuf;
use std::sync::Arc;

const LARGEUR: u32 = 640;
const HAUTEUR: u32 = 360;

fn contexte() -> Option<GpuContext> {
    match GpuContext::new(&GpuRequest {
        adapter_hint: "Quadro".into(),
        allow_any_adapter: true,
        validation: true,
    }) {
        Ok(g) => Some(g),
        Err(e) => {
            eprintln!("essai GPU ignoré : {e}");
            None
        }
    }
}

fn chene() -> Option<Arc<VxmModel>> {
    let chemin = PathBuf::from(std::env::var("HOME").unwrap_or_default())
        .join(".local/share/emergence/lab_assets/trees/chene_42.vxm");
    if !chemin.is_file() {
        eprintln!("essai ignoré : chene_42.vxm absent");
        return None;
    }
    Some(Arc::new(VxmModel::load(&chemin).expect("chargement du chêne")))
}

fn table() -> MaterialTable {
    let d = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../engine/data");
    MaterialTable::load(&d.join("materials.csv"), &d.join("material_render.toml"))
        .expect("table des matières")
}

/// Le chêne 42 sur un sol de turf, au pivot de la scène « arbre ».
fn scene(modele: &Arc<VxmModel>) -> StaticScene {
    let pivot = VoxelCoord::new(200_000, 0, 200_000);
    StaticScene::tree_on_turf(PlacedModel::new(modele.clone(), pivot, 0, 0).expect("modèle posé"))
        .expect("scène")
}

/// Caméra de la prise « face » de la scène arbre (0, 2, -19) vers (0, 7, 0), champ 50°.
fn camera() -> VoxelCamera {
    let (lacet, tangage) = (0.0_f64, (5.0_f64 / 19.0).atan().to_degrees());
    VoxelCamera::new(
        [10_000_000, 2_000, 10_000_000 - 19_000],
        lacet as f32,
        tangage as f32,
        Projection::Perspective { fov_y_deg: 50.0 },
    )
    .expect("caméra")
}

fn ciel() -> Partage<SkyParams> {
    // soleil à 35° de hauteur, du sud-est : lumière franche, ombres nettes
    Partage::new(SkyParams::new(35.0, 40.0, 2.0, 0.3).expect("ciel"))
}

/// Éclairage sans translucidité ni liseré : seul reste le soleil lambertien et le ciel.
fn lumiere(vue: DebugView) -> Partage<LightSettings> {
    let f = FoliageLightParams::new(0.0, 1.0)
        .and_then(|f| f.with_rim(0.0, 0.2))
        .expect("feuillage éteint");
    Partage::new(LightSettings::new(vue, 1.0).expect("lumière").with_foliage(f))
}

enum Rendu {
    Trace,
    Maillage { ombres: bool, occlusion: bool },
}

fn rendre(gpu: &GpuContext, modele: &Arc<VxmModel>, rendu: &Rendu, vue: DebugView) -> RgbaImage {
    let t = table();
    let veg = vegetation_ramps(modele.meta(), 0).expect("rampes");
    let sc = scene(modele);
    let cam = camera();
    let ciel = ciel();
    let mut g = RenderGraph::new();
    g.add(Box::new(SkyPass::new(ciel.clone()))).unwrap();
    g.add(Box::new(SkyBackgroundPass::new())).unwrap();
    let mut monde_trace = None;
    match rendu {
        Rendu::Trace => {
            let materiaux = GpuMaterials::new(gpu, &t, &veg);
            let monde = VoxelGpuWorld::new(gpu, ClipmapConfig::laboratoire()).unwrap();
            g.add(Box::new(VoxelTracePass::new(monde.bindings()))).unwrap();
            g.add(Box::new(VoxelMaterialPass::new(materiaux.bindings())))
                .unwrap();
            g.add(Box::new(DepthMergePass::new())).unwrap();
            g.add(Box::new(LightingPass::new(lumiere(vue)))).unwrap();
            monde_trace = Some(monde);
        }
        Rendu::Maillage { ombres, occlusion } => {
            let colorier = MaterialColorer::new(&t, &veg, StyleSheet::continuous());
            // la même région que la clipmap : 25 m autour de la caméra
            let cles = {
                let c = cam.pos_mm();
                let case = |mm: i64, d: i64| (mm + d).div_euclid(3200) as i32;
                let mut v = Vec::new();
                for y in -1..=case(c[1], 25_000) {
                    for z in case(c[2], -25_000)..=case(c[2], 25_000) {
                        for x in case(c[0], -25_000)..=case(c[0], 25_000) {
                            v.push(ChunkKey::new(x, y, z));
                        }
                    }
                }
                v
            };
            let wm = WorldMesher::new(&sc, &colorier, 0, MesherConfig::default());
            let chunks = wm.charger(&cles);
            let mut meshes = wm.mailler(&cles, &chunks);
            FoliageBaker::new(&colorier, &chunks).bake(&mut meshes, [0.5, 0.6, 0.6], 48);
            let monde = MeshWorld::new(gpu);
            monde.replace_with(&meshes, Some(48));
            if *ombres {
                g.add(Box::new(MeshShadowPass::new(
                    ShadowParams::default(),
                    ciel.clone(),
                    monde.clone(),
                )))
                .unwrap();
            }
            g.add(Box::new(MeshAmbientPass::new())).unwrap();
            g.add(Box::new(
                MeshRenderer::new(monde, lumiere(vue)).with_occlusion(*occlusion),
            ))
            .unwrap();
        }
    }
    g.add(Box::new(BloomPass::new())).unwrap();
    g.add(Box::new(TonemapPass::new(Partage::new(
        PostParams::new(1.0, 0.0).unwrap(),
    ))))
    .unwrap();
    let mut cible = OffscreenTarget::new(gpu, LARGEUR, HAUTEUR).unwrap();
    let mut profil = GpuProfiler::new(gpu, 32);
    let mut streamer = ClipmapStreamer::new(1, ClipmapStreamer::BUDGET_PAR_DEFAUT);
    for i in 0..3_u64 {
        if let Some(m) = monde_trace.as_mut() {
            streamer.update_until_complete(&cam, &sc, m, gpu).unwrap();
        }
        let f = FrameContext::new_voxel(i, 0.0, LARGEUR, HAUTEUR, cam).unwrap();
        g.render(gpu, &f, &mut cible, &mut profil).unwrap();
    }
    read_texture(gpu, cible.texture()).expect("lecture")
}

fn srgb_vers_lab(p: &[u8]) -> [f64; 3] {
    let lin = |v: u8| {
        let c = f64::from(v) / 255.0;
        if c <= 0.04045 {
            c / 12.92
        } else {
            ((c + 0.055) / 1.055).powf(2.4)
        }
    };
    let (r, g, b) = (lin(p[0]), lin(p[1]), lin(p[2]));
    let x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
    let y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    let z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
    let f = |t: f64| {
        if t > 0.008856 {
            t.cbrt()
        } else {
            7.787 * t + 16.0 / 116.0
        }
    };
    let (fx, fy, fz) = (f(x), f(y), f(z));
    [116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)]
}

/// ΔE76 moyen sur les pixels où `garde` est vrai, et nombre de ces pixels.
fn delta_e_moyen(a: &RgbaImage, b: &RgbaImage, garde: impl Fn(usize) -> bool) -> (f64, usize) {
    let (mut somme, mut n) = (0.0, 0_usize);
    for i in 0..(a.width() * a.height()) as usize {
        if !garde(i) {
            continue;
        }
        let (la, lb) = (
            srgb_vers_lab(&a.pixels()[i * 4..]),
            srgb_vers_lab(&b.pixels()[i * 4..]),
        );
        somme += ((la[0] - lb[0]).powi(2) + (la[1] - lb[1]).powi(2) + (la[2] - lb[2]).powi(2)).sqrt();
        n += 1;
    }
    (if n == 0 { 0.0 } else { somme / n as f64 }, n)
}

/// Masque d'un rendu en vue « masque » : pixel blanc (sans bloom, le blanc est saturé après AgX).
fn masque(img: &RgbaImage) -> Vec<bool> {
    img.pixels()
        .as_chunks::<4>()
        .0
        .iter()
        .map(|p| p[0] > 200 && p[1] > 200 && p[2] > 200)
        .collect()
}

#[test]
fn le_maillage_rend_la_meme_silhouette_et_les_memes_couleurs_que_le_trace() {
    let (Some(gpu), Some(modele)) = (contexte(), chene()) else {
        return;
    };
    // silhouette
    let a = masque(&rendre(&gpu, &modele, &Rendu::Trace, DebugView::Mask));
    let b = masque(&rendre(
        &gpu,
        &modele,
        &Rendu::Maillage {
            ombres: false,
            occlusion: false,
        },
        DebugView::Mask,
    ));
    let inter = a.iter().zip(&b).filter(|(x, y)| **x && **y).count();
    let union = a.iter().zip(&b).filter(|(x, y)| **x || **y).count();
    let iou = inter as f64 / union as f64;
    eprintln!("IoU de silhouette : {iou:.5} ({inter} / {union} pixels)");
    assert!(iou >= 0.99, "IoU {iou}");

    // albédo seul : les couleurs plates sont celles du shader de matière
    let ta = rendre(&gpu, &modele, &Rendu::Trace, DebugView::Albedo);
    let ma = rendre(
        &gpu,
        &modele,
        &Rendu::Maillage {
            ombres: false,
            occlusion: false,
        },
        DebugView::Albedo,
    );
    let (de_albedo, n) = delta_e_moyen(&ta, &ma, |i| a[i] && b[i]);
    eprintln!("ΔE moyen de l'albédo : {de_albedo:.3} sur {n} pixels");
    assert!(de_albedo <= 1.0, "ΔE albédo {de_albedo}");

    // image éclairée, hors ombres, occlusion et translucidité
    let ti = rendre(&gpu, &modele, &Rendu::Trace, DebugView::Beauty);
    let mi = rendre(
        &gpu,
        &modele,
        &Rendu::Maillage {
            ombres: false,
            occlusion: false,
        },
        DebugView::Beauty,
    );
    let (de, n) = delta_e_moyen(&ti, &mi, |i| a[i] && b[i]);
    eprintln!("ΔE moyen de l'image sans ombres ni occlusion : {de:.3} sur {n} pixels");
    assert!(de <= 4.0, "ΔE image {de}");
    // avec ombres et occlusion : on mesure l'écart (informatif)
    let mo = rendre(
        &gpu,
        &modele,
        &Rendu::Maillage {
            ombres: true,
            occlusion: true,
        },
        DebugView::Beauty,
    );
    let (de_o, _) = delta_e_moyen(&ti, &mo, |i| a[i] && b[i]);
    eprintln!("ΔE moyen avec ombres et occlusion baked contre le tracé SANS : {de_o:.3}");
}

#[test]
fn le_maillage_est_reproductible_octet_pour_octet() {
    let (Some(gpu), Some(modele)) = (contexte(), chene()) else {
        return;
    };
    let r = Rendu::Maillage {
        ombres: true,
        occlusion: true,
    };
    let a = rendre(&gpu, &modele, &r, DebugView::Beauty);
    let b = rendre(&gpu, &modele, &r, DebugView::Beauty);
    assert_eq!(a.pixels(), b.pixels());
}
