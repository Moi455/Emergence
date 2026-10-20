//! Essais du rendu voxel sur un vrai GPU (L09). Sans adaptateur ils s'ignorent avec un message :
//! `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json cargo test -p em_render --test voxel_gpu`.
//! Sans le chêne de référence (`~/.local/share/emergence/lab_assets/trees/chene_42.vxm`) les essais qui en ont
//! besoin s'ignorent aussi.

use em_core::{ChunkKey, Lod, MaterialId, VoxelCoord, VoxelValue};
use em_gen::{PlacedModel, StaticScene, VxmModel, vegetation_ramps};
use em_material::{EvalContext, MaterialEvaluator, MaterialTable};
use em_render::sky::noms as noms_ciel;
use em_render::voxel::noms;
use em_render::wgpu;
use em_render::{
    BloomPass, ClipmapConfig, ClipmapStreamer, DebugView, DepthMergePass, FrameContext, GpuContext,
    GpuMaterials, GpuProfiler, GpuRequest, LightSettings, LightingPass, OffscreenTarget, Partage, PostParams,
    Projection, RenderGraph, SkyBackgroundPass, SkyParams, SkyPass, TonemapPass, VoxelCamera, VoxelGpuWorld,
    VoxelMaterialPass, VoxelTracePass, read_texture,
};
use em_voxel::{Chunk, VoxelSource};
use std::path::PathBuf;
use std::sync::Arc;

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

/// Pivot du pied du chêne : au milieu du monde, comme la scène `arbre` (10 km de l'origine).
const PIVOT: VoxelCoord = VoxelCoord::new(200_000, 0, 200_000);

fn scene_chene(m: &Arc<VxmModel>) -> (StaticScene, PlacedModel) {
    let p = PlacedModel::new(m.clone(), PIVOT, 0, 0).unwrap();
    let s = StaticScene::builder()
        .turf_ground(0)
        .place(PlacedModel::new(m.clone(), PIVOT, 0, 0).unwrap())
        .build()
        .unwrap();
    (s, p)
}

/// Position monde en mm d'un point relatif au pied du tronc, en mètres.
fn pos_mm(x: f64, y: f64, z: f64) -> [i64; 3] {
    [
        10_000_000 + (x * 1000.0).round() as i64,
        (y * 1000.0).round() as i64,
        10_000_000 + (z * 1000.0).round() as i64,
    ]
}

/// Tout ce qu'il faut pour rendre une source : monde GPU, streamer, matières, graphe complet.
struct Banc {
    gpu: GpuContext,
    graphe: RenderGraph,
    monde: VoxelGpuWorld,
    streamer: ClipmapStreamer,
    cible: OffscreenTarget,
    profil: GpuProfiler,
    taille: (u32, u32),
    index: u64,
}

fn monter(
    gpu: GpuContext,
    taille: (u32, u32),
    table: &MaterialTable,
    veg: &em_material::VegetationRamps,
    vue: DebugView,
) -> Banc {
    let materiaux = GpuMaterials::new(&gpu, table, veg);
    let monde = VoxelGpuWorld::new(&gpu, ClipmapConfig::laboratoire()).expect("monde GPU");
    let ciel = Partage::new(SkyParams::new(35.0, 200.0, 3.0, 0.3).unwrap());
    let mut graphe = RenderGraph::new();
    graphe.add(Box::new(SkyPass::new(ciel))).unwrap();
    graphe.add(Box::new(SkyBackgroundPass::new())).unwrap();
    graphe
        .add(Box::new(VoxelTracePass::new(monde.bindings())))
        .unwrap();
    graphe
        .add(Box::new(VoxelMaterialPass::new(materiaux.bindings())))
        .unwrap();
    graphe.add(Box::new(DepthMergePass::new())).unwrap();
    graphe
        .add(Box::new(LightingPass::new(Partage::new(
            LightSettings::new(vue, 1.0).unwrap(),
        ))))
        .unwrap();
    graphe.add(Box::new(BloomPass::new())).unwrap();
    graphe
        .add(Box::new(TonemapPass::new(Partage::new(PostParams::default()))))
        .unwrap();
    let cible = OffscreenTarget::new(&gpu, taille.0, taille.1).unwrap();
    let profil = GpuProfiler::new(&gpu, 32);
    // les matières doivent rester en vie tant que le groupe de liaisons sert : le banc les garde via le graphe (Arc
    // interne de wgpu) ; on les laisse tomber ici sans risque.
    drop(materiaux);
    Banc {
        gpu,
        graphe,
        monde,
        streamer: ClipmapStreamer::new(1, ClipmapStreamer::BUDGET_PAR_DEFAUT),
        cible,
        profil,
        taille,
        index: 0,
    }
}

impl Banc {
    fn rendre(&mut self, cam: &VoxelCamera, src: &dyn VoxelSource) {
        self.streamer
            .update_until_complete(cam, src, &mut self.monde, &self.gpu)
            .expect("diffusion de la clipmap");
        let f = FrameContext::new_voxel(self.index, 0.0, self.taille.0, self.taille.1, *cam).unwrap();
        self.index += 1;
        self.graphe
            .render(&self.gpu, &f, &mut self.cible, &mut self.profil)
            .unwrap();
    }

    /// Octets bruts d'une ressource du graphe (lignes alignées sur 256 octets, puis dépaquetées).
    fn lire(&self, nom: em_render::graph::ResourceName, octets_par_pixel: u32) -> Vec<u8> {
        let tex = self.graphe.resources().texture(nom).expect("ressource");
        lire_texture(&self.gpu, tex, self.taille, octets_par_pixel)
    }
}

fn lire_texture(gpu: &GpuContext, tex: &wgpu::Texture, taille: (u32, u32), bpp: u32) -> Vec<u8> {
    let ligne = taille.0 * bpp;
    let alignee = ligne.div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT) * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
    let tampon = gpu.device().create_buffer(&wgpu::BufferDescriptor {
        label: Some("lecture essai"),
        size: u64::from(alignee * taille.1),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut enc = gpu
        .device()
        .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
    enc.copy_texture_to_buffer(
        tex.as_image_copy(),
        wgpu::TexelCopyBufferInfo {
            buffer: &tampon,
            layout: wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(alignee),
                rows_per_image: Some(taille.1),
            },
        },
        wgpu::Extent3d {
            width: taille.0,
            height: taille.1,
            depth_or_array_layers: 1,
        },
    );
    gpu.queue().submit([enc.finish()]);
    tampon.slice(..).map_async(wgpu::MapMode::Read, |r| r.unwrap());
    gpu.attendre_fin();
    let vue = tampon.slice(..).get_mapped_range().unwrap();
    let mut sortie = Vec::with_capacity((ligne * taille.1) as usize);
    for y in 0..taille.1 as usize {
        let d = y * alignee as usize;
        sortie.extend_from_slice(&vue[d..d + ligne as usize]);
    }
    sortie
}

fn mots(octets: &[u8]) -> Vec<u32> {
    octets
        .as_chunks::<4>()
        .0
        .iter()
        .map(|b| u32::from_le_bytes(*b))
        .collect()
}

// ---------------------------------------------------------------------------------------------------------------

/// (2) Silhouette : vue orthographique de côté, masque du tracé comparé au masque calculé sur le CPU depuis les
/// voxels du `.vxm`. Critère de L09 : IoU >= 0,99.
#[test]
fn silhouette_du_chene_egale_le_masque_cpu() {
    let (Some(gpu), Some(modele)) = (contexte(), chene()) else {
        return;
    };
    let t = table();
    let veg = vegetation_ramps(modele.meta(), 0).unwrap();
    let (scene, placed) = scene_chene(&modele);
    let (l, h) = (640_u32, 360_u32);
    let mut banc = monter(gpu, (l, h), &t, &veg, DebugView::Mask);
    // Vue de côté, depuis le sud, regardant le nord ; 16 m de haut, centrée sur y = 7 m. Le décalage de quelques
    // millimètres évite que des centres de pixel tombent EXACTEMENT sur une arête de voxel (égalité que chaque
    // carte départage à sa manière : le critère mesure la silhouette, pas l'arrondi).
    let hauteur_m = 16.0_f32;
    let cam = VoxelCamera::new(
        pos_mm(0.0073, 7.0031, -20.0),
        0.0,
        0.0,
        Projection::Orthographic { height_m: hauteur_m },
    )
    .unwrap();
    banc.rendre(&cam, &scene);
    let hit = mots(&banc.lire(noms::HIT, 16));
    let gpu_masque: Vec<bool> = (0..(l * h) as usize)
        .map(|i| (hit[4 * i] >> 20) & 1 == 1)
        .collect();

    // Masque CPU : pour chaque pixel, le centre est au point (x, y) de la vue ; il touche la silhouette si une
    // colonne de voxels (x, y) du modèle le contient (un voxel mesure 0,05 m, centré par cellule).
    use std::collections::BTreeSet;
    let colonnes: BTreeSet<(i32, i32)> = placed.world_voxels(0).map(|(v, _)| (v.x, v.y)).collect();
    let aspect = l as f64 / h as f64;
    let (mut inter, mut union_) = (0_u64, 0_u64);
    for py in 0..h {
        for px in 0..l {
            let ndc_x = (f64::from(px) + 0.5) / f64::from(l) * 2.0 - 1.0;
            let ndc_y = 1.0 - (f64::from(py) + 0.5) / f64::from(h) * 2.0;
            let x_m = 10_000.007_3 + ndc_x * f64::from(hauteur_m) * 0.5 * aspect;
            let y_m = 7.003_1 + ndc_y * f64::from(hauteur_m) * 0.5;
            let cpu = if y_m < 0.0 {
                true // le sol (turf) est plein sous y = 0 : il fait partie du masque du tracé
            } else {
                colonnes.contains(&((x_m / 0.05).floor() as i32, (y_m / 0.05).floor() as i32))
            };
            let g = gpu_masque[(py * l + px) as usize];
            inter += u64::from(cpu && g);
            union_ += u64::from(cpu || g);
        }
    }
    let iou = inter as f64 / union_ as f64;
    eprintln!("IoU de la silhouette : {iou:.5} ({inter} / {union_})");
    assert!(iou >= 0.99, "IoU = {iou}");
}

/// ΔE de CIE76 entre deux couleurs sRGB 8 bits.
fn delta_e(a: [u8; 3], b: [f32; 3]) -> f32 {
    fn lab(rgb: [f32; 3]) -> [f32; 3] {
        let lin = |c: f32| {
            if c <= 0.04045 {
                c / 12.92
            } else {
                ((c + 0.055) / 1.055).powf(2.4)
            }
        };
        let (r, g, bl) = (lin(rgb[0]), lin(rgb[1]), lin(rgb[2]));
        let x = (0.4124 * r + 0.3576 * g + 0.1805 * bl) / 0.95047;
        let y = 0.2126 * r + 0.7152 * g + 0.0722 * bl;
        let z = (0.0193 * r + 0.1192 * g + 0.9505 * bl) / 1.08883;
        let f = |t: f32| {
            if t > 0.008856 {
                t.cbrt()
            } else {
                7.787 * t + 16.0 / 116.0
            }
        };
        let (fx, fy, fz) = (f(x), f(y), f(z));
        [116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)]
    }
    let a = lab([
        f32::from(a[0]) / 255.0,
        f32::from(a[1]) / 255.0,
        f32::from(a[2]) / 255.0,
    ]);
    let b = lab(b);
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
}

fn linear_to_srgb(c: f32) -> f32 {
    let c = c.clamp(0.0, 1.0);
    if c <= 0.003_130_8 {
        c * 12.92
    } else {
        1.055 * c.powf(1.0 / 2.4) - 0.055
    }
}

/// Matière : sur 10 000 pixels, l'albédo écrit par le shader égale celui de la référence CPU de `em_material`.
/// Critère : ΔE max <= 1 (quantification 8 bits comprise).
#[test]
fn albedo_gpu_egale_la_reference_cpu() {
    let (Some(gpu), Some(modele)) = (contexte(), chene()) else {
        return;
    };
    let t = table();
    let veg = vegetation_ramps(modele.meta(), 0).unwrap();
    let (scene, _) = scene_chene(&modele);
    let (l, h) = (960_u32, 540_u32);
    let mut banc = monter(gpu, (l, h), &t, &veg, DebugView::Beauty);
    let cam = VoxelCamera::new(
        pos_mm(5.0, 3.0, -7.0),
        324.0,
        14.0,
        Projection::Perspective { fov_y_deg: 70.0 },
    )
    .unwrap();
    banc.rendre(&cam, &scene);
    let hit = mots(&banc.lire(noms::HIT, 16));
    let gb0 = banc.lire(noms::GB0, 4);
    let evaluateur = MaterialEvaluator::new(&t, &veg);
    let (mut vus, mut pire, mut somme) = (0_u32, 0.0_f32, 0.0_f64);
    let mut par_classe = std::collections::BTreeMap::<u16, (u32, f32)>::new();
    let touches: Vec<usize> = (0..(l * h) as usize)
        .filter(|i| (hit[4 * i] >> 20) & 1 == 1)
        .collect();
    let pas = (touches.len() / 10_000).max(1);
    for &i in touches.iter().step_by(pas) {
        let rec = &hit[4 * i..4 * i + 4];
        {
            let valeur = VoxelValue::from_raw((rec[0] & 0xFFFF) as u16);
            let voxel = VoxelCoord::new(rec[1] as i32, rec[2] as i32, rec[3] as i32);
            let attendu = evaluateur
                .eval(&EvalContext::new(valeur, voxel, 0 as Lod))
                .albedo();
            let c = attendu.channels();
            let cpu = [
                linear_to_srgb(c[0].raw() as f32 / 65_536.0),
                linear_to_srgb(c[1].raw() as f32 / 65_536.0),
                linear_to_srgb(c[2].raw() as f32 / 65_536.0),
            ];
            let g = [gb0[4 * i], gb0[4 * i + 1], gb0[4 * i + 2]];
            let de = delta_e(g, cpu);
            pire = pire.max(de);
            somme += f64::from(de);
            vus += 1;
            let e = par_classe.entry(valeur.material().get()).or_insert((0, 0.0));
            e.0 += 1;
            e.1 = e.1.max(de);
        }
    }
    eprintln!(
        "albédo GPU/CPU : {vus} pixels, ΔE max {pire:.3}, moyen {:.4}, par classe {par_classe:?}",
        somme / f64::from(vus)
    );
    assert!(vus >= 9_000, "trop peu de pixels touchés : {vus}");
    assert!(pire <= 1.0, "ΔE max = {pire}");
}

/// (4) Aucune valeur non finie dans la cible HDR après éclairage.
#[test]
fn pas_de_nan_dans_le_hdr() {
    let (Some(gpu), Some(modele)) = (contexte(), chene()) else {
        return;
    };
    let t = table();
    let veg = vegetation_ramps(modele.meta(), 0).unwrap();
    let (scene, _) = scene_chene(&modele);
    let taille = (640_u32, 360_u32);
    let mut banc = monter(gpu, taille, &t, &veg, DebugView::Beauty);
    for (pos, lacet, tangage) in [
        (pos_mm(0.0, 2.0, -20.0), 0.0, 5.0),
        (pos_mm(0.5, 1.6, -3.0), 0.0, 0.0),
        (pos_mm(0.0, 30.0, 0.0), 0.0, -89.0), // de très haut, à la verticale
    ] {
        let cam = VoxelCamera::new(pos, lacet, tangage, Projection::Perspective { fov_y_deg: 60.0 }).unwrap();
        banc.rendre(&cam, &scene);
        let hdr = banc.graphe.resources().texture(noms_ciel::HDR).expect("hdr");
        let octets = lire_texture(&banc.gpu, hdr, taille, 8);
        let demi: Vec<u16> = octets
            .as_chunks::<2>()
            .0
            .iter()
            .map(|b| u16::from_le_bytes(*b))
            .collect();
        let non_finis = demi.iter().filter(|h| (**h & 0x7c00) == 0x7c00).count();
        assert_eq!(non_finis, 0, "valeurs non finies dans le HDR");
        let dist = lire_f32(&banc.lire(noms::DIST, 4));
        assert!(dist.iter().all(|d| d.is_finite()), "distance non finie");
    }
}

fn lire_f32(o: &[u8]) -> Vec<f32> {
    o.as_chunks::<4>()
        .0
        .iter()
        .map(|b| f32::from_le_bytes(*b))
        .collect()
}

/// (5) Caméra dans un voxel plein : pas de plantage, la face d'entrée est vue au centre.
#[test]
fn camera_dans_un_voxel_plein() {
    let (Some(gpu), Some(modele)) = (contexte(), chene()) else {
        return;
    };
    let t = table();
    let veg = vegetation_ramps(modele.meta(), 0).unwrap();
    let (scene, placed) = scene_chene(&modele);
    let taille = (160_u32, 90_u32);
    let mut banc = monter(gpu, taille, &t, &veg, DebugView::Beauty);
    // un voxel plein du tronc, bas : on met la caméra à son centre
    let (voxel, _) = placed
        .world_voxels(0)
        .filter(|(v, _)| v.y == 10)
        .min_by_key(|(v, _)| {
            (
                i64::from(v.x - 200_000).pow(2) + i64::from(v.z - 200_000).pow(2),
                *v,
            )
        })
        .expect("un voxel du tronc");
    let centre = [
        i64::from(voxel.x) * 50 + 25,
        i64::from(voxel.y) * 50 + 25,
        i64::from(voxel.z) * 50 + 25,
    ];
    let cam = VoxelCamera::new(centre, 30.0, 10.0, Projection::Perspective { fov_y_deg: 60.0 }).unwrap();
    banc.rendre(&cam, &scene);
    let hit = mots(&banc.lire(noms::HIT, 16));
    let milieu = (taille.1 / 2 * taille.0 + taille.0 / 2) as usize;
    assert_eq!(
        (hit[4 * milieu] >> 20) & 1,
        1,
        "le pixel central doit voir le voxel plein"
    );
    let dist = lire_f32(&banc.lire(noms::DIST, 4));
    assert!(
        dist[milieu] < 0.06,
        "distance de la face d'entrée : {}",
        dist[milieu]
    );
    assert_eq!(
        [
            hit[4 * milieu + 1] as i32,
            hit[4 * milieu + 2] as i32,
            hit[4 * milieu + 3] as i32
        ],
        [voxel.x, voxel.y, voxel.z]
    );
}

/// (6) Deux rendus de la même image sur la même carte : identiques octet pour octet.
#[test]
fn deux_rendus_sont_identiques_octet_pour_octet() {
    let (Some(gpu), Some(modele)) = (contexte(), chene()) else {
        return;
    };
    let t = table();
    let veg = vegetation_ramps(modele.meta(), 0).unwrap();
    let (scene, _) = scene_chene(&modele);
    let taille = (480_u32, 270_u32);
    let mut banc = monter(gpu, taille, &t, &veg, DebugView::Beauty);
    let cam = VoxelCamera::new(
        pos_mm(10.0, 2.0, -12.0),
        320.0,
        10.0,
        Projection::Perspective { fov_y_deg: 55.0 },
    )
    .unwrap();
    let mut images = Vec::new();
    for _ in 0..2 {
        // même numéro d'image (le tramage de la composition en dépend) : seul le contenu peut différer
        banc.index = 7;
        for _ in 0..3 {
            banc.index = 7;
            banc.rendre(&cam, &scene);
        }
        images.push(
            read_texture(&banc.gpu, banc.cible.texture())
                .expect("lecture")
                .pixels()
                .to_vec(),
        );
    }
    assert!(images[0] == images[1], "deux captures différentes");
}

/// Source de l'essai d'orientation : une plaque, un cube « rouge » à l'est (+x) et un cube « bleu » au nord (+z).
struct Orientation {
    rouge: VoxelValue,
    bleu: VoxelValue,
    plaque: VoxelValue,
}

impl VoxelSource for Orientation {
    fn fill_chunk(&self, key: ChunkKey, _lod: Lod, out: &mut Chunk) {
        *out = Chunk::new_air();
        // le monde de l'essai : x, z de 200 000 à 200 000 + 63, y de 0 à 63 ; plaque épaisse de 2 voxels à y = 0
        if key != ChunkKey::new(3125, 0, 3125) {
            return;
        }
        for z in 0..64 {
            for x in 0..64 {
                for y in 0..2 {
                    out.set(x, y, z, self.plaque);
                }
            }
        }
        for z in 28..36 {
            for x in 46..54 {
                for y in 2..10 {
                    out.set(x, y, z, self.rouge);
                }
            }
        }
        for z in 46..54 {
            for x in 28..36 {
                for y in 2..10 {
                    out.set(x, y, z, self.bleu);
                }
            }
        }
    }

    fn version_tag(&self) -> u64 {
        7
    }
}

/// (7) Vue d'en haut, nord en haut : le cube de l'est est à droite, celui du nord est en haut de l'image.
#[test]
fn orientation_vue_d_en_haut_rouge_a_droite_bleu_en_haut() {
    let Some(gpu) = contexte() else { return };
    let t = table();
    let veg = em_material::VegetationRamps::new();
    let src = Orientation {
        rouge: VoxelValue::new(MaterialId::new(31), 1),
        bleu: VoxelValue::new(MaterialId::new(31), 2),
        plaque: VoxelValue::new(MaterialId::new(1), 0),
    };
    let taille = (320_u32, 240_u32);
    let mut banc = monter(gpu, taille, &t, &veg, DebugView::Mask);
    // le monde de l'essai commence au voxel 200 000 (chunk 3125) ; centre à +32 voxels = 1,6 m
    let cam = VoxelCamera::new(
        [10_000_000 + 1600, 4_000, 10_000_000 + 1600],
        0.0,
        -89.0,
        Projection::Orthographic { height_m: 3.2 },
    )
    .unwrap();
    banc.rendre(&cam, &src);
    let hit = mots(&banc.lire(noms::HIT, 16));
    let centroide = |v: VoxelValue| {
        let (mut sx, mut sy, mut n) = (0.0_f64, 0.0_f64, 0.0_f64);
        for i in 0..(taille.0 * taille.1) as usize {
            if (hit[4 * i] >> 20) & 1 == 1 && (hit[4 * i] & 0xFFFF) as u16 == v.raw() {
                sx += (i as u32 % taille.0) as f64;
                sy += (i as u32 / taille.0) as f64;
                n += 1.0;
            }
        }
        assert!(n > 100.0, "cube introuvable");
        (sx / n, sy / n)
    };
    let (rx, ry) = centroide(src.rouge);
    let (bx, by) = centroide(src.bleu);
    let (cx, cy) = (f64::from(taille.0) / 2.0, f64::from(taille.1) / 2.0);
    assert!(
        rx > cx + 20.0 && (ry - cy).abs() < 10.0,
        "le rouge (est) doit être à droite : ({rx}, {ry})"
    );
    assert!(
        by < cy - 20.0 && (bx - cx).abs() < 10.0,
        "le bleu (nord) doit être en haut : ({bx}, {by})"
    );
}

/// Mises à jour incrémentales : modifier un seul chunk ne retéléverse que lui ; l'éviction libère la mémoire.
#[test]
fn mise_a_jour_incrementale_par_bloc_modifie() {
    let Some(gpu) = contexte() else { return };
    let mut monde = VoxelGpuWorld::new(&gpu, ClipmapConfig::laboratoire()).unwrap();
    let origine = ChunkKey::new(3117, -8, 3117);
    monde.set_level_origin(&gpu, 0, origine).unwrap();
    let k = ChunkKey::new(3125, 0, 3125);
    let mut c = Chunk::new_air();
    for i in 0..40 {
        c.set(i, 5, 7, VoxelValue::new(MaterialId::new(31), 3));
    }
    let drapeaux = em_render::ChunkFlags::sans_peau();
    let premier = monde.upload_chunk(&gpu, 0, k, &c, drapeaux).unwrap();
    assert!(matches!(
        premier,
        em_render::voxel::UploadOutcome::Uploaded { .. }
    ));
    let s1 = monde.stats();
    assert_eq!(
        (s1.chunks_pool, s1.bricks),
        (1, 5),
        "40 voxels sur 5 briques de 8"
    );
    // même contenu : rien n'est écrit
    assert_eq!(
        monde.upload_chunk(&gpu, 0, k, &c, drapeaux).unwrap(),
        em_render::voxel::UploadOutcome::Unchanged
    );
    assert_eq!(monde.stats().bytes_uploaded, s1.bytes_uploaded);
    // un seul voxel change : le chunk est réécrit, la mémoire reste la même (l'ancienne est libérée avant)
    c.set(0, 5, 7, VoxelValue::new(MaterialId::new(30), 3));
    assert!(matches!(
        monde.upload_chunk(&gpu, 0, k, &c, drapeaux).unwrap(),
        em_render::voxel::UploadOutcome::Uploaded { .. }
    ));
    let s2 = monde.stats();
    // la brique modifiée passe de 2 à 3 valeurs : 1 bit -> 2 bits, soit 18 -> 34 mots
    assert_eq!(
        (s2.chunks_pool, s2.bricks, s2.payload_words),
        (1, 5, s1.payload_words + 16)
    );
    // hors de la fenêtre : refusé
    assert!(
        monde
            .upload_chunk(&gpu, 0, ChunkKey::new(0, 0, 0), &c, drapeaux)
            .is_err()
    );
    // la fenêtre glisse hors du chunk : il est évincé et la mémoire redevient vide
    monde
        .set_level_origin(&gpu, 0, ChunkKey::new(3200, -8, 3200))
        .unwrap();
    let s3 = monde.stats();
    assert_eq!((s3.chunks_pool, s3.bricks, s3.payload_words), (0, 0, 0));
}

/// Le streamer ne relit que les blocs marqués sales quand la source ne change pas d'étiquette, et recharge ce qui
/// manque quand la caméra franchit une frontière de chunk.
#[test]
fn le_streamer_charge_et_fait_glisser_la_fenetre() {
    let (Some(gpu), Some(modele)) = (contexte(), chene()) else {
        return;
    };
    let (scene, _) = scene_chene(&modele);
    let mut monde = VoxelGpuWorld::new(&gpu, ClipmapConfig::laboratoire()).unwrap();
    let mut streamer = ClipmapStreamer::new(1, ClipmapStreamer::BUDGET_PAR_DEFAUT);
    let cam = VoxelCamera::new(
        pos_mm(0.0, 8.0, 0.0),
        0.0,
        0.0,
        Projection::Perspective { fov_y_deg: 60.0 },
    )
    .unwrap();
    let r = streamer
        .update_until_complete(&cam, &scene, &mut monde, &gpu)
        .unwrap();
    let s = monde.stats();
    eprintln!("chargement initial : {r:?} {s:?}");
    assert!(
        r.uploaded > 0 && s.bricks == 4_450,
        "le chêne (4 450 briques au LOD 0) doit être chargé en entier : {s:?}"
    );
    // rien ne bouge : un deuxième passage n'écrit rien
    let r2 = streamer.update(&cam, &scene, &mut monde, &gpu).unwrap();
    assert_eq!((r2.uploaded, r2.bytes, r2.pending), (0, 0, 0));
    // la caméra avance de 2 chunks vers le nord : des chunks sortent, d'autres entrent, le chêne reste chargé
    let cam2 = VoxelCamera::new(
        pos_mm(0.0, 8.0, 6.4),
        0.0,
        0.0,
        Projection::Perspective { fov_y_deg: 60.0 },
    )
    .unwrap();
    let r3 = streamer
        .update_until_complete(&cam2, &scene, &mut monde, &gpu)
        .unwrap();
    assert!(
        r3.processed > 0 && r3.processed < 2_000,
        "seule la tranche neuve est traitée : {r3:?}"
    );
    assert!(monde.stats().bricks > 4_000);
}

/// Mosaïque de 8 × 8 tuiles de 6 × 6 voxels : 16 classes × 4 teintes, une valeur par tuile.
struct Mosaique {
    valeurs: Vec<VoxelValue>,
}

impl VoxelSource for Mosaique {
    fn fill_chunk(&self, key: ChunkKey, _lod: Lod, out: &mut Chunk) {
        *out = Chunk::new_air();
        if key != ChunkKey::new(3125, 0, 3125) {
            return;
        }
        for (n, v) in self.valeurs.iter().enumerate() {
            let (x0, z0) = ((n % 8) as u32 * 8, (n / 8) as u32 * 8);
            for z in z0..z0 + 6 {
                for x in x0..x0 + 6 {
                    out.set(x, 0, z, *v);
                }
            }
        }
    }

    fn version_tag(&self) -> u64 {
        11
    }
}

/// Les cinq modes de teinte (rampe, terrain, bois, pierre, végétation avec ses quatre rôles) : l'albédo du shader
/// égale la référence CPU à ΔE <= 1 sur un échantillon de pixels de chaque classe.
#[test]
fn albedo_de_tous_les_modes_de_teinte_egale_la_reference_cpu() {
    let Some(gpu) = contexte() else { return };
    let t = table();
    let mut veg = em_material::VegetationRamps::new();
    let r = |a: [u8; 3], b: [u8; 3], c: [u8; 3]| [a, b, c];
    let feuilles = [
        r([22, 48, 14], [58, 110, 32], [120, 170, 60]),
        r([30, 60, 16], [84, 130, 40], [150, 190, 70]),
        r([20, 40, 12], [50, 90, 28], [100, 150, 50]),
    ];
    veg.register("chene", em_material::RampRole::Leaves, &feuilles)
        .unwrap();
    veg.register(
        "chene",
        em_material::RampRole::Bark,
        &[
            r([40, 30, 22], [90, 70, 50], [130, 108, 80]),
            r([50, 40, 30], [104, 86, 64], [140, 120, 92]),
        ],
    )
    .unwrap();
    veg.register(
        "chene",
        em_material::RampRole::Flowers,
        &[r([200, 150, 160], [240, 190, 200], [255, 230, 235])],
    )
    .unwrap();
    veg.register(
        "chene",
        em_material::RampRole::Fruits,
        &[r([120, 20, 20], [190, 50, 40], [230, 100, 80])],
    )
    .unwrap();
    let noms = [
        "turf",
        "dirt",
        "sand",
        "limestone",
        "granite",
        "oak_planks",
        "wood_trim",
        "plaster",
        "slate",
        "bark",
        "leaves",
        "vine",
        "petal",
        "fruit",
        "cobblestone",
        "brick",
    ];
    let mut valeurs = Vec::new();
    for nom in noms {
        let id = t
            .by_name(nom)
            .unwrap_or_else(|| panic!("classe « {nom} » absente"));
        let vegetale = matches!(nom, "bark" | "leaves" | "vine" | "petal" | "fruit");
        for tint in if vegetale {
            [0_u8, 1, 2, 3]
        } else {
            [0, 33, 66, 127]
        } {
            valeurs.push(VoxelValue::new(id, tint));
        }
    }
    let src = Mosaique {
        valeurs: valeurs.clone(),
    };
    let taille = (512_u32, 512_u32);
    let mut banc = monter(gpu, taille, &t, &veg, DebugView::Albedo);
    let cam = VoxelCamera::new(
        [10_000_000 + 1600, 4_000, 10_000_000 + 1600],
        0.0,
        -89.0,
        Projection::Orthographic { height_m: 3.2 },
    )
    .unwrap();
    banc.rendre(&cam, &src);
    let hit = mots(&banc.lire(noms::HIT, 16));
    let gb0 = banc.lire(noms::GB0, 4);
    let evaluateur = MaterialEvaluator::new(&t, &veg);
    let mut par_valeur = std::collections::BTreeMap::<u16, (u32, f32)>::new();
    let mut pire = 0.0_f32;
    let touches: Vec<usize> = (0..(taille.0 * taille.1) as usize)
        .filter(|i| (hit[4 * i] >> 20) & 1 == 1)
        .collect();
    for &i in touches.iter().step_by((touches.len() / 20_000).max(1)) {
        let valeur = VoxelValue::from_raw((hit[4 * i] & 0xFFFF) as u16);
        let voxel = VoxelCoord::new(
            hit[4 * i + 1] as i32,
            hit[4 * i + 2] as i32,
            hit[4 * i + 3] as i32,
        );
        let c = evaluateur
            .eval(&EvalContext::new(valeur, voxel, 0))
            .albedo()
            .channels();
        let cpu = [
            linear_to_srgb(c[0].raw() as f32 / 65_536.0),
            linear_to_srgb(c[1].raw() as f32 / 65_536.0),
            linear_to_srgb(c[2].raw() as f32 / 65_536.0),
        ];
        let de = delta_e([gb0[4 * i], gb0[4 * i + 1], gb0[4 * i + 2]], cpu);
        pire = pire.max(de);
        let e = par_valeur.entry(valeur.raw()).or_insert((0, 0.0));
        e.0 += 1;
        e.1 = e.1.max(de);
    }
    eprintln!(
        "mosaïque : {} valeurs vues sur {}, ΔE max {pire:.3}",
        par_valeur.len(),
        valeurs.len()
    );
    assert!(
        par_valeur.len() >= valeurs.len() - 2,
        "des tuiles manquent : {} sur {}",
        par_valeur.len(),
        valeurs.len()
    );
    assert!(pire <= 1.0, "ΔE max = {pire} ; détail : {par_valeur:?}");
}

/// Lancer de rayons de référence sur le CPU (Amanatides et Woo en f64, voxel par voxel) : `Some((voxel, face))`
/// du premier voxel plein touché dans la fenêtre de la clipmap, `None` sinon. Le sol est le demi-espace y < 0.
fn trace_cpu(
    pleins: &std::collections::HashSet<(i32, i32, i32)>,
    fenetre: ([i32; 3], [i32; 3]),
    origine_voxels: [f64; 3],
    dir: [f64; 3],
) -> Option<([i32; 3], u32)> {
    let (wmin, wmax) = fenetre;
    let mut c = [0_i32; 3];
    let mut t_max_axe = [f64::INFINITY; 3];
    let mut delta = [f64::INFINITY; 3];
    let mut pas = [0_i32; 3];
    for a in 0..3 {
        c[a] = origine_voxels[a].floor() as i32;
        pas[a] = if dir[a] >= 0.0 { 1 } else { -1 };
        if dir[a].abs() > 1e-12 {
            let bord = if dir[a] > 0.0 {
                f64::from(c[a] + 1)
            } else {
                f64::from(c[a])
            };
            t_max_axe[a] = (bord - origine_voxels[a]) / dir[a];
            delta[a] = (1.0 / dir[a]).abs();
        }
    }
    let dedans = |c: &[i32; 3]| (0..3).all(|a| c[a] >= wmin[a] && c[a] < wmax[a]);
    let plein = |c: &[i32; 3]| c[1] < 0 || pleins.contains(&(c[0], c[1], c[2]));
    let mut face = 6;
    for _ in 0..4_000 {
        if !dedans(&c) {
            return None;
        }
        if plein(&c) {
            return Some((c, face));
        }
        let a = if t_max_axe[0] <= t_max_axe[1] && t_max_axe[0] <= t_max_axe[2] {
            0
        } else if t_max_axe[1] <= t_max_axe[2] {
            1
        } else {
            2
        };
        c[a] += pas[a];
        t_max_axe[a] += delta[a];
        face = (a as u32) * 2 + u32::from(pas[a] < 0);
    }
    None
}

/// Le tracé GPU égale un tracé de référence CPU sur tous les pixels d'une vue en perspective : même voxel touché,
/// même face (tolérance : 0,3 % de pixels, aux arêtes où le flottant départage deux cellules).
#[test]
fn le_trace_gpu_egale_un_trace_cpu_de_reference() {
    let (Some(gpu), Some(modele)) = (contexte(), chene()) else {
        return;
    };
    let t = table();
    let veg = vegetation_ramps(modele.meta(), 0).unwrap();
    let (scene, placed) = scene_chene(&modele);
    let (l, h) = (480_u32, 270_u32);
    let mut banc = monter(gpu, (l, h), &t, &veg, DebugView::Mask);
    let fov = 62.0_f32;
    let cam = VoxelCamera::new(
        pos_mm(-6.0, 3.5, -11.0),
        28.0,
        9.0,
        Projection::Perspective { fov_y_deg: fov },
    )
    .unwrap();
    banc.rendre(&cam, &scene);
    let hit = mots(&banc.lire(noms::HIT, 16));
    let pleins: std::collections::HashSet<(i32, i32, i32)> =
        placed.world_voxels(0).map(|(v, _)| (v.x, v.y, v.z)).collect();
    let v = cam.voxel();
    let origine_chunk = [(v[0] >> 6) - 8, (v[1] >> 6) - 8, (v[2] >> 6) - 8];
    let fenetre = (
        origine_chunk.map(|c| c * 64),
        origine_chunk.map(|c| c * 64 + 1024),
    );
    // origine du rayon en voxels (f64), depuis les millimètres exacts
    let pos = cam.pos_mm();
    let origine = [pos[0] as f64 / 50.0, pos[1] as f64 / 50.0, pos[2] as f64 / 50.0];
    let (d, u, a) = (cam.droite(), cam.haut(), cam.avant());
    let ty = f64::from((fov.to_radians() * 0.5).tan());
    let tx = ty * f64::from(l) / f64::from(h);
    let (mut ecarts, mut touches_cpu, mut touches_gpu) = (0_u32, 0_u32, 0_u32);
    for py in 0..h {
        for px in 0..l {
            let nx = (f64::from(px) + 0.5) / f64::from(l) * 2.0 - 1.0;
            let ny = 1.0 - (f64::from(py) + 0.5) / f64::from(h) * 2.0;
            let mut dir = [0.0_f64; 3];
            let (dv, uv, av) = (d.to_array(), u.to_array(), a.to_array());
            for k in 0..3 {
                dir[k] = f64::from(av[k]) + nx * tx * f64::from(dv[k]) + ny * ty * f64::from(uv[k]);
            }
            let n = (dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]).sqrt();
            let dir = dir.map(|x| x / n);
            let cpu = trace_cpu(&pleins, fenetre, origine, dir);
            let i = (py * l + px) as usize;
            let gpu_touche = (hit[4 * i] >> 20) & 1 == 1;
            let gpu_voxel = [
                hit[4 * i + 1] as i32,
                hit[4 * i + 2] as i32,
                hit[4 * i + 3] as i32,
            ];
            let gpu_face = (hit[4 * i] >> 16) & 7;
            touches_cpu += u32::from(cpu.is_some());
            touches_gpu += u32::from(gpu_touche);
            let pareil = match cpu {
                Some((vx, f)) => gpu_touche && gpu_voxel == vx && gpu_face == f,
                None => !gpu_touche,
            };
            if !pareil {
                ecarts += 1;
            }
        }
    }
    let part = f64::from(ecarts) / f64::from(l * h);
    eprintln!(
        "tracé GPU/CPU : {ecarts} pixels différents sur {} ({:.4} %), touches CPU {touches_cpu}, GPU {touches_gpu}",
        l * h,
        part * 100.0
    );
    assert!(
        part < 0.003,
        "trop d'écarts : {ecarts} pixels ({:.3} %)",
        part * 100.0
    );
}
