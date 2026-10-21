//! Mode de matière VoxelPixel (L23p) sur un vrai GPU : l'albédo du shader (`eval_pixel_albedo`) égale la référence
//! CPU d'`em_material` (ΔE <= 1) pour la pierre (pièces et mortier), les trois axes du bois et le bois de bout, les
//! tuiles et la mousse ; et le mode continu n'a pas bougé. Sans adaptateur ils s'ignorent.

use em_core::{ChunkKey, Lod, VoxelCoord, VoxelValue};
use em_material::{
    EvalContext, MaterialEvaluator, MaterialMode, MaterialTable, StyleConfig, StyleSheet, VegetationRamps,
    tint_wood,
};
use em_render::voxel::noms;
use em_render::wgpu;
use em_render::{
    BloomPass, ClipmapConfig, ClipmapStreamer, DebugView, DepthMergePass, FrameContext, GpuContext,
    GpuMaterials, GpuProfiler, GpuRequest, LightSettings, LightingPass, OffscreenTarget, Partage, PostParams,
    Projection, RenderGraph, SkyBackgroundPass, SkyParams, SkyPass, TonemapPass, VoxelCamera, VoxelGpuWorld,
    VoxelMaterialPass, VoxelTracePass,
};
use em_voxel::{Chunk, VoxelSource};
use std::path::PathBuf;

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

fn table() -> MaterialTable {
    let d = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../engine/data");
    MaterialTable::load(&d.join("materials.csv"), &d.join("material_render.toml"))
        .expect("table des matières")
}

/// Pivot du pied du chêne : au milieu du monde, comme la scène `arbre` (10 km de l'origine).
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
    veg: &VegetationRamps,
    style: StyleSheet,
    vue: DebugView,
) -> Banc {
    let materiaux = GpuMaterials::with_style(&gpu, table, veg, style);
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
fn style(table: &MaterialTable, mode: MaterialMode) -> StyleSheet {
    let config = StyleConfig {
        pixel_classes: ["cut_stone", "oak_raw", "wood_trim", "slate", "moss"]
            .iter()
            .map(|s| (*s).to_owned())
            .collect(),
        params: Default::default(),
        granulometrie_force: Some(1.0), // réglages d'origine de L23p : les empreintes épinglées en dépendent
    };
    StyleSheet::from_config(&config, table, mode).expect("style valide")
}

/// Rend une mosaïque de valeurs vue d'en haut et compare, pixel par pixel, l'albédo du G-buffer à la référence CPU
/// avec la même feuille de style. Renvoie le ΔE max et le nombre de valeurs vues.
fn comparer(mode: MaterialMode, valeurs: &[VoxelValue]) -> (f32, usize) {
    let Some(gpu) = contexte() else {
        return (0.0, usize::MAX);
    };
    let t = table();
    let veg = VegetationRamps::new();
    let feuille = style(&t, mode);
    let src = Mosaique {
        valeurs: valeurs.to_vec(),
    };
    let taille = (512_u32, 512_u32);
    let mut banc = monter(gpu, taille, &t, &veg, feuille.clone(), DebugView::Albedo);
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
    let ev = MaterialEvaluator::with_style(&t, &veg, feuille);
    let mut pire = 0.0_f32;
    let mut vues = std::collections::BTreeSet::new();
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
        let c = ev.eval(&EvalContext::new(valeur, voxel, 0)).albedo().channels();
        let cpu = [
            linear_to_srgb(c[0].raw() as f32 / 65_536.0),
            linear_to_srgb(c[1].raw() as f32 / 65_536.0),
            linear_to_srgb(c[2].raw() as f32 / 65_536.0),
        ];
        pire = pire.max(delta_e([gb0[4 * i], gb0[4 * i + 1], gb0[4 * i + 2]], cpu));
        vues.insert(valeur.raw());
    }
    (pire, vues.len())
}

fn valeurs_pixel(t: &MaterialTable) -> Vec<VoxelValue> {
    let mut v = Vec::new();
    for nom in ["cut_stone", "slate", "moss"] {
        let id = t.by_name(nom).unwrap();
        v.extend([0_u8, 1, 17, 64, 127].map(|tint| VoxelValue::new(id, tint)));
    }
    for nom in ["oak_raw", "wood_trim"] {
        let id = t.by_name(nom).unwrap();
        for axe in 0..4_u8 {
            v.extend([0_u8, 5, 16 + 7, 31].map(|var| VoxelValue::new(id, tint_wood(axe, var))));
        }
    }
    v
}

#[test]
fn albedo_voxel_pixel_gpu_egale_la_reference_cpu() {
    let t = table();
    let valeurs = valeurs_pixel(&t);
    let (pire, vues) = comparer(MaterialMode::VoxelPixel, &valeurs);
    if vues == usize::MAX {
        return;
    }
    eprintln!(
        "VoxelPixel : {vues} valeurs vues sur {}, ΔE max {pire:.3}",
        valeurs.len()
    );
    assert!(
        vues >= valeurs.len() - 2,
        "des tuiles manquent : {vues} sur {}",
        valeurs.len()
    );
    assert!(pire <= 1.0, "ΔE max = {pire}");
}

#[test]
fn le_mode_continu_reste_egal_a_la_reference_cpu() {
    let t = table();
    let valeurs = valeurs_pixel(&t);
    let (pire, vues) = comparer(MaterialMode::Continuous, &valeurs);
    if vues == usize::MAX {
        return;
    }
    eprintln!("Continu : {vues} valeurs vues, ΔE max {pire:.3}");
    assert!(pire <= 1.0, "ΔE max = {pire}");
}
