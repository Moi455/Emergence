//! Essais de l'occlusion ambiante tracée (L14) sur un vrai GPU. Sans adaptateur ils s'ignorent avec un message :
//! `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json cargo test -p em_render --test ao_gpu`.
//!
//! Scènes synthétiques (un `VoxelSource` de test défini par une fonction des coordonnées entières, sans modèle) :
//! - coin de trois plans (sol et deux murs) et sol dégagé ;
//! - nuage de voxels au hasard : le GPU (un rayon par pixel, sans filtre) contre la référence CPU (`occlusion_cpu`, DDA
//!   `f64`) sur un échantillon de pixels ;
//! - cube sur un sol : le filtre ne mêle jamais le dessus du cube (dégagé) et le sol à son pied (occulté) ;
//! - pente de 30° en escaliers : uniformité mesurée ;
//! - lumière : l'occlusion n'assombrit pas le sol dégagé, assombrit le coin, et laisse sa couleur au creux ;
//! - reproductibilité : deux images d'indices différents donnent les mêmes octets.

use em_core::{ChunkKey, Lod, MaterialId, VoxelValue};
use em_material::{MaterialTable, VegetationRamps};
use em_render::sky::noms as noms_ciel;
use em_render::voxel::ao::{self, BruteAo, SurfacePoint, occlusion_cpu};
use em_render::voxel::noms;
use em_render::wgpu;
use em_render::{
    AmbientOcclusionParams, AmbientOcclusionPass, ClipmapConfig, ClipmapStreamer, DebugView, DepthMergePass,
    FrameContext, GpuContext, GpuMaterials, GpuProfiler, GpuRequest, LightSettings, LightingPass,
    OffscreenTarget, Partage, Projection, RenderGraph, SkyBackgroundPass, SkyParams, SkyPass, VoxelCamera,
    VoxelGpuWorld, VoxelMaterialPass, VoxelTracePass,
};
use em_voxel::{Chunk, ChunkHint, VoxelSource};
use std::path::PathBuf;
use std::sync::Arc;

/// Voxel (niveau 0) du centre de la scène : 10 km de l'origine, comme les autres scènes d'essai.
const CENTRE: i32 = 200_000;

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

/// Millimètres monde d'un point relatif au centre de la scène, en mètres.
fn pos_mm(x: f64, y: f64, z: f64) -> [i64; 3] {
    [
        10_000_000 + (x * 1000.0).round() as i64,
        (y * 1000.0).round() as i64,
        10_000_000 + (z * 1000.0).round() as i64,
    ]
}

/// Contenu d'une cellule relative au centre : 0 vide, 1 granite. Le sol (y < 0) est du turf, hors de cette fonction.
type Solide = Arc<dyn Fn(i32, i32, i32) -> u8 + Send + Sync>;

struct SourceDeTest {
    solide: Solide,
    granite: MaterialId,
}

impl VoxelSource for SourceDeTest {
    fn fill_chunk(&self, key: ChunkKey, _lod: Lod, out: &mut Chunk) {
        let turf = VoxelValue::new(MaterialId::new(1), 0);
        let (ox, oy, oz) = (key.x * 64, key.y * 64, key.z * 64);
        for z in 0..64_u32 {
            for y in 0..64_u32 {
                for x in 0..64_u32 {
                    let (vx, vy, vz) = (ox + x as i32, oy + y as i32, oz + z as i32);
                    if vy < 0 {
                        out.set(x, y, z, turf);
                    } else if (self.solide)(vx - CENTRE, vy, vz - CENTRE) != 0 {
                        out.set(x, y, z, VoxelValue::new(self.granite, 0));
                    }
                }
            }
        }
    }

    fn classify(&self, key: ChunkKey, _lod: Lod) -> ChunkHint {
        let (cx, cy, cz) = (key.x * 64, key.y * 64, key.z * 64);
        if cy + 63 < 0 {
            return ChunkHint::Solid(VoxelValue::new(MaterialId::new(1), 0));
        }
        let hors = |c: i32, l: i32, h: i32| c + 63 < CENTRE + l || c > CENTRE + h;
        if hors(cx, -200, 200) || cy > 200 || hors(cz, -200, 200) {
            ChunkHint::Air
        } else {
            ChunkHint::Unknown
        }
    }

    fn version_tag(&self) -> u64 {
        14
    }
}

struct Banc {
    gpu: GpuContext,
    graphe: RenderGraph,
    monde: VoxelGpuWorld,
    streamer: ClipmapStreamer,
    cible: OffscreenTarget,
    profil: GpuProfiler,
    taille: (u32, u32),
    index: u64,
    granite: MaterialId,
}

/// Graphe jusqu'à l'éclairage (sans bloom ni AgX : on lit la vraie valeur dans le HDR), avec ou sans occlusion.
fn monter(taille: (u32, u32), ao: Option<AmbientOcclusionParams>, vue: DebugView) -> Option<Banc> {
    let gpu = contexte()?;
    let t = table();
    let materiaux = GpuMaterials::new(&gpu, &t, &VegetationRamps::new());
    let monde = VoxelGpuWorld::new(&gpu, ClipmapConfig::laboratoire()).expect("monde GPU");
    let ciel = Partage::new(SkyParams::new(35.0, 200.0, 3.0, 0.0).unwrap());
    let lumiere = Partage::new(LightSettings::new(vue, 1.0).unwrap());
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
    if let Some(p) = ao {
        graphe
            .add(Box::new(AmbientOcclusionPass::new(
                Partage::new(p),
                monde.bindings(),
            )))
            .unwrap();
    }
    graphe.add(Box::new(LightingPass::new(lumiere))).unwrap();
    let cible = OffscreenTarget::new(&gpu, taille.0, taille.1).unwrap();
    let profil = GpuProfiler::new(&gpu, 32);
    let granite = t.by_name("granite").expect("granite");
    drop(materiaux);
    Some(Banc {
        gpu,
        graphe,
        monde,
        streamer: ClipmapStreamer::new(1, ClipmapStreamer::BUDGET_PAR_DEFAUT),
        cible,
        profil,
        taille,
        index: 0,
        granite,
    })
}

fn parametres(rayons: u32, force: f32, filtre: u32, diviseur: u32) -> AmbientOcclusionParams {
    AmbientOcclusionParams::new(rayons, 1.0)
        .unwrap()
        .with_strength(force)
        .unwrap()
        .with_filter(filtre)
        .unwrap()
        .with_resolution_divisor(diviseur)
        .unwrap()
}

impl Banc {
    fn rendre(&mut self, cam: &VoxelCamera, solide: Solide) {
        let src = SourceDeTest {
            solide,
            granite: self.granite,
        };
        self.streamer
            .update_until_complete(cam, &src, &mut self.monde, &self.gpu)
            .expect("diffusion de la clipmap");
        let f = FrameContext::new_voxel(self.index, 0.0, self.taille.0, self.taille.1, *cam).unwrap();
        self.index += 1;
        self.graphe
            .render(&self.gpu, &f, &mut self.cible, &mut self.profil)
            .unwrap();
    }

    fn lire(&self, nom: em_render::graph::ResourceName, taille: (u32, u32), octets: u32) -> Vec<u8> {
        let tex = self.graphe.resources().texture(nom).expect("ressource");
        lire_texture(&self.gpu, tex, taille, octets)
    }

    /// Impact de chaque pixel : (touché, voxel, face).
    fn impacts(&self) -> Vec<Option<([i32; 3], u32)>> {
        let o = self.lire(noms::HIT, self.taille, 16);
        (0..(self.taille.0 * self.taille.1) as usize)
            .map(|i| {
                let m =
                    |k: usize| u32::from_le_bytes(o[16 * i + 4 * k..16 * i + 4 * k + 4].try_into().unwrap());
                ((m(0) >> 20) & 1 == 1).then(|| ([m(1) as i32, m(2) as i32, m(3) as i32], (m(0) >> 16) & 7))
            })
            .collect()
    }

    /// Visibilité de l'ambiance (sortie du filtre) de chaque pixel.
    fn visibilite(&self) -> Vec<f32> {
        let o = self.lire(ao::noms::OCCLUSION, self.taille, 4);
        flottants(&o)
    }

    /// HDR linéaire de chaque pixel.
    fn hdr(&self) -> Vec<[f32; 3]> {
        let o = self.lire(noms_ciel::HDR, self.taille, 8);
        (0..(self.taille.0 * self.taille.1) as usize)
            .map(|i| {
                let h =
                    |k: usize| demi_vers_f32(u16::from_le_bytes([o[8 * i + 2 * k], o[8 * i + 2 * k + 1]]));
                [h(0), h(1), h(2)]
            })
            .collect()
    }
}

/// Octets little-endian -> flottants 32 bits.
fn flottants(o: &[u8]) -> Vec<f32> {
    o.as_chunks::<4>()
        .0
        .iter()
        .map(|b| f32::from_le_bytes(*b))
        .collect()
}

fn demi_vers_f32(h: u16) -> f32 {
    let s = if h & 0x8000 != 0 { -1.0 } else { 1.0 };
    let e = i32::from((h >> 10) & 0x1f);
    let m = f32::from(h & 0x3ff);
    if e == 0 {
        s * m * 2.0_f32.powi(-24)
    } else if e == 31 {
        f32::NAN
    } else {
        s * (1.0 + m / 1024.0) * 2.0_f32.powi(e - 15)
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

/// Lacet et tangage (degrés) qui font regarder `cible` depuis `pos` (lacet 0 = +z, 90 = +x).
fn regarder(pos: [f64; 3], cible: [f64; 3]) -> (f32, f32) {
    let (dx, dy, dz) = (cible[0] - pos[0], cible[1] - pos[1], cible[2] - pos[2]);
    (
        dx.atan2(dz).to_degrees() as f32,
        dy.atan2(dx.hypot(dz)).to_degrees() as f32,
    )
}

fn camera(pos: [f64; 3], cible: [f64; 3], fov: f32) -> VoxelCamera {
    let (lacet, tangage) = regarder(pos, cible);
    VoxelCamera::new(
        pos_mm(pos[0], pos[1], pos[2]),
        lacet,
        tangage,
        Projection::Perspective { fov_y_deg: fov },
    )
    .unwrap()
}

/// Sol et deux murs de 2 m (x < 0 et z < 0) : le coin est à l'origine.
fn coin() -> Solide {
    Arc::new(|x, y, z| u8::from((0..40).contains(&y) && (x < 0 || z < 0) && x > -80 && z > -80))
}

fn voxels_du_sol(imp: &[Option<([i32; 3], u32)>], f: impl Fn([i32; 3]) -> bool) -> Vec<usize> {
    imp.iter()
        .enumerate()
        .filter_map(|(i, h)| match h {
            Some((v, 3)) if v[1] == -1 && f([v[0] - CENTRE, v[1], v[2] - CENTRE]) => Some(i),
            _ => None,
        })
        .collect()
}

/// (1) Coin de trois plans : visibilité < 0,5 au pied des deux murs ; sol dégagé : > 0,95.
#[test]
fn le_coin_est_sombre_et_le_sol_degage_est_clair() {
    let Some(mut banc) = monter(
        (480, 270),
        Some(AmbientOcclusionParams::default()),
        DebugView::Beauty,
    ) else {
        return;
    };
    banc.rendre(&camera([3.2, 2.6, 3.2], [0.4, 0.0, 0.4], 55.0), coin());
    let (imp, vis) = (banc.impacts(), banc.visibilite());
    let coin_px = voxels_du_sol(&imp, |v| v[0] == 0 && v[2] == 0);
    assert!(!coin_px.is_empty(), "le voxel de sol du coin n'est pas visible");
    let au_coin = coin_px.iter().map(|&i| vis[i]).sum::<f32>() / coin_px.len() as f32;
    let libre_px = voxels_du_sol(&imp, |v| v[0] > 22 && v[2] > 22);
    assert!(libre_px.len() > 100, "pas de sol dégagé visible");
    let libre_min = libre_px.iter().map(|&i| vis[i]).fold(1.0_f32, f32::min);
    eprintln!(
        "coin : visibilité {au_coin:.3} ({} px) ; sol dégagé : min {libre_min:.3}",
        coin_px.len()
    );
    assert!(au_coin < 0.5, "coin trop clair : {au_coin}");
    assert!(libre_min > 0.95, "sol dégagé assombri : {libre_min}");
    // Le ciel et le fond ne reçoivent aucune occlusion.
    let (ciel, _) = imp
        .iter()
        .enumerate()
        .find(|(_, h)| h.is_none())
        .expect("des pixels de ciel");
    assert_eq!(vis[ciel], 1.0);
}

fn hachage(x: i32, y: i32, z: i32) -> u32 {
    let mut h = (x as u32).wrapping_mul(0x8da6_b343)
        ^ (y as u32).wrapping_mul(0xd816_3841)
        ^ (z as u32).wrapping_mul(0xcb1a_b31f);
    h ^= h >> 15;
    h = h.wrapping_mul(0x2c1b_3c6d);
    h ^= h >> 12;
    h
}

/// Nuage de voxels au hasard (30 %) dans une boîte de 4 m × 1,5 m × 4 m.
fn nuage() -> Solide {
    Arc::new(|x, y, z| {
        u8::from(
            (-40..40).contains(&x)
                && (0..30).contains(&y)
                && (-40..40).contains(&z)
                && hachage(x, y, z) % 100 < 30,
        )
    })
}

/// (2) Le GPU (un rayon par pixel, sans filtre, force 1) égale la référence CPU (DDA `f64`) sur un échantillon de pixels.
#[test]
fn l_occlusion_gpu_egale_la_reference_cpu() {
    let params = parametres(8, 1.0, 0, 1);
    let Some(mut banc) = monter((480, 270), Some(params), DebugView::Beauty) else {
        return;
    };
    let cam = camera([0.3, 2.6, -4.2], [0.0, 1.0, 0.0], 60.0);
    banc.rendre(&cam, nuage());
    let (imp, vis) = (banc.impacts(), banc.visibilite());
    let dist = {
        let o = banc.lire(noms::DIST, banc.taille, 4);
        flottants(&o)
    };
    let solide = nuage();
    let plein = move |c: [i32; 3]| c[1] < 0 || solide(c[0] - CENTRE, c[1], c[2] - CENTRE) != 0;
    let (l, h) = banc.taille;
    let pos = cam.pos_mm();
    let origine = [pos[0] as f64 / 50.0, pos[1] as f64 / 50.0, pos[2] as f64 / 50.0];
    let (d, u, a) = (
        cam.droite().to_array(),
        cam.haut().to_array(),
        cam.avant().to_array(),
    );
    let ty = f64::from((60.0_f32.to_radians() * 0.5).tan());
    let tx = ty * f64::from(l) / f64::from(h);
    let (mut n, mut somme, mut grands, mut pire, mut sombres) = (0_u32, 0.0_f64, 0_u32, 0.0_f32, 0_u32);
    for py in (0..h).step_by(3) {
        for px in (0..l).step_by(3) {
            let i = (py * l + px) as usize;
            let Some((voxel, face)) = imp[i] else { continue };
            let nx = (f64::from(px) + 0.5) / f64::from(l) * 2.0 - 1.0;
            let ny = 1.0 - (f64::from(py) + 0.5) / f64::from(h) * 2.0;
            let mut dir = [0.0_f64; 3];
            for k in 0..3 {
                dir[k] = f64::from(a[k]) + nx * tx * f64::from(d[k]) + ny * ty * f64::from(u[k]);
            }
            let norme = dir.iter().map(|x| x * x).sum::<f64>().sqrt();
            let t_vox = f64::from(dist[i]) / 0.05;
            let q = [0, 1, 2].map(|k| {
                (origine[k] + dir[k] / norme * t_vox - f64::from(voxel[k] - CENTRE) - f64::from(CENTRE))
                    as f32
            });
            let point = SurfacePoint::new(voxel, face, q);
            let occ = occlusion_cpu(&plein, &point, &params);
            let cpu = params.visibility(occ);
            let ecart = (cpu - vis[i]).abs();
            n += 1;
            somme += f64::from(ecart);
            pire = pire.max(ecart);
            grands += u32::from(ecart > 0.1);
            sombres += u32::from(cpu < 0.6);
        }
    }
    let moyen = somme / f64::from(n);
    eprintln!(
        "AO GPU/CPU : {n} pixels, écart moyen {moyen:.5}, pire {pire:.3}, > 0,1 : {grands} ({:.2} %), pixels sombres (CPU < 0,6) : {sombres}",
        100.0 * f64::from(grands) / f64::from(n)
    );
    assert!(
        n > 3000 && sombres > 200,
        "échantillon trop pauvre : {n} pixels, {sombres} sombres"
    );
    assert!(moyen < 0.01, "écart moyen {moyen}");
    assert!(
        f64::from(grands) / f64::from(n) < 0.01,
        "{grands} pixels à plus de 0,1"
    );
}

/// Reproductibilité : deux images d'indices différents (même caméra, même scène) donnent les mêmes octets, brut et filtré.
#[test]
fn l_occlusion_est_la_meme_a_chaque_image() {
    let Some(mut banc) = monter(
        (320, 180),
        Some(AmbientOcclusionParams::default()),
        DebugView::Beauty,
    ) else {
        return;
    };
    let cam = camera([0.3, 2.6, -4.2], [0.0, 1.0, 0.0], 60.0);
    banc.rendre(&cam, nuage());
    let taille_brute = (160, 90);
    let (a, b) = (
        banc.lire(ao::noms::OCCLUSION, banc.taille, 4),
        banc.lire(ao::noms::BRUTE, taille_brute, 4),
    );
    for _ in 0..5 {
        banc.rendre(&cam, nuage());
    }
    let (c, d) = (
        banc.lire(ao::noms::OCCLUSION, banc.taille, 4),
        banc.lire(ao::noms::BRUTE, taille_brute, 4),
    );
    assert!(a == c && b == d, "l'occlusion change d'une image à l'autre");
    assert!(flottants(&a).iter().any(|&v| v < 0.9), "scène sans occlusion");
    let mot = u32::from_le_bytes(b[..4].try_into().unwrap());
    let _ = BruteAo::decoder(mot);
}

/// (3) Le filtre ne traverse pas les arêtes : le dessus d'un cube (dégagé) reste clair jusqu'au bord, alors que le sol
/// à son pied (enfermé contre la paroi) est sombre.
#[test]
fn le_filtre_ne_traverse_pas_les_aretes_de_voxel() {
    let Some(mut banc) = monter(
        (640, 360),
        Some(AmbientOcclusionParams::default()),
        DebugView::Beauty,
    ) else {
        return;
    };
    let cube: Solide = Arc::new(|x, y, z| {
        u8::from((-20..20).contains(&x) && (0..20).contains(&y) && (-20..20).contains(&z))
    });
    banc.rendre(&camera([2.5, 3.2, -2.5], [0.0, 0.5, 0.0], 55.0), cube);
    let (imp, vis) = (banc.impacts(), banc.visibilite());
    let dessus: Vec<usize> = imp
        .iter()
        .enumerate()
        .filter_map(|(i, h)| match h {
            Some((v, 3)) if v[1] == 19 => Some(i),
            _ => None,
        })
        .collect();
    let pied: Vec<usize> = imp
        .iter()
        .enumerate()
        .filter_map(|(i, h)| match h {
            Some((v, 3)) if v[1] == -1 && ((v[0] - CENTRE).abs() <= 21 && (v[2] - CENTRE).abs() <= 21) => {
                Some(i)
            }
            _ => None,
        })
        .collect();
    assert!(
        dessus.len() > 500 && pied.len() > 30,
        "dessus {} pied {}",
        dessus.len(),
        pied.len()
    );
    let pire_dessus = dessus.iter().map(|&i| vis[i]).fold(1.0_f32, f32::min);
    let pire_pied = pied.iter().map(|&i| vis[i]).fold(1.0_f32, f32::min);
    eprintln!(
        "cube : dessus min {pire_dessus:.3} ({} px), pied min {pire_pied:.3} ({} px)",
        dessus.len(),
        pied.len()
    );
    assert!(
        pire_dessus > 0.93,
        "le dessus du cube est assombri par le filtre : {pire_dessus}"
    );
    assert!(pire_pied < 0.6, "le pied du cube n'est pas occulté : {pire_pied}");
}

/// (4) Pente de 30° en escaliers : dispersion de la visibilité sur les faces tournées vers le haut (mesure ; les
/// contremarches des marches occultent réellement leurs pieds, l'uniformité du critère de la spécification suppose la
/// peau lisse de L17).
#[test]
fn la_pente_de_30_degres_est_a_peu_pres_uniforme() {
    let Some(mut banc) = monter(
        (640, 360),
        Some(AmbientOcclusionParams::default()),
        DebugView::Beauty,
    ) else {
        return;
    };
    // Hauteur (en voxels) de la pente : x * tan 30° (marches de 1 voxel de haut tous les 1,73 voxel).
    let pente: Solide = Arc::new(|x, y, z| {
        let h = if x < 0 {
            0
        } else {
            (f64::from(x) * 30.0_f64.to_radians().tan()).floor() as i32 + 1
        };
        u8::from(y < h && y >= 0 && (-80..80).contains(&z) && x < 200)
    });
    banc.rendre(&camera([-0.5, 2.5, -3.0], [3.0, 1.0, 0.0], 60.0), pente);
    let (imp, vis) = (banc.impacts(), banc.visibilite());
    let valeurs: Vec<f32> = imp
        .iter()
        .enumerate()
        .filter_map(|(i, h)| match h {
            Some((v, 3)) if v[0] - CENTRE > 25 && v[0] - CENTRE < 140 && v[1] >= 10 => Some(vis[i]),
            _ => None,
        })
        .collect();
    assert!(valeurs.len() > 1000, "pente invisible : {} px", valeurs.len());
    let m = valeurs.iter().sum::<f32>() / valeurs.len() as f32;
    let ecart = (valeurs.iter().map(|v| (v - m) * (v - m)).sum::<f32>() / valeurs.len() as f32).sqrt();
    eprintln!(
        "pente de 30° : {} px, visibilité moyenne {m:.3}, écart type {ecart:.4}",
        valeurs.len()
    );
    assert!(m > 0.6 && ecart < 0.2, "moyenne {m}, écart type {ecart}");
}

/// (5) Lumière : le sol dégagé est identique avec et sans occlusion, le coin est plus sombre, et il garde sa couleur
/// (le vert du turf ne devient ni gris ni noir).
#[test]
fn l_occlusion_n_assombrit_que_l_ambiance_et_garde_la_couleur() {
    let (Some(mut avec), Some(mut sans)) = (
        monter(
            (480, 270),
            Some(AmbientOcclusionParams::default()),
            DebugView::Beauty,
        ),
        monter((480, 270), None, DebugView::Beauty),
    ) else {
        return;
    };
    let cam = camera([3.2, 2.6, 3.2], [0.4, 0.0, 0.4], 55.0);
    avec.rendre(&cam, coin());
    sans.rendre(&cam, coin());
    let (imp, h_avec, h_sans) = (avec.impacts(), avec.hdr(), sans.hdr());
    let libre = voxels_du_sol(&imp, |v| v[0] > 22 && v[2] > 22);
    let pire_libre = libre
        .iter()
        .map(|&i| {
            (0..3)
                .map(|c| (h_avec[i][c] - h_sans[i][c]).abs() / h_sans[i][c].max(1e-4))
                .fold(0.0_f32, f32::max)
        })
        .fold(0.0_f32, f32::max);
    assert!(pire_libre < 1e-3, "le sol dégagé change : {pire_libre}");
    let coin_px = voxels_du_sol(&imp, |v| v[0] == 0 && v[2] == 0);
    assert!(!coin_px.is_empty());
    for &i in &coin_px {
        let (a, s) = (h_avec[i], h_sans[i]);
        assert!(
            a[0] < s[0] && a[1] < s[1] && a[2] < s[2],
            "le coin n'est pas plus sombre : {a:?} contre {s:?}"
        );
        // Teinte : le rapport vert/rouge et vert/bleu du creux reste celui de la surface.
        let (vr_a, vr_s) = (a[1] / a[0], s[1] / s[0]);
        let (vb_a, vb_s) = (a[1] / a[2], s[1] / s[2]);
        assert!(
            vr_a > 0.9 * vr_s && vb_a > 0.9 * vb_s,
            "creux décoloré : {a:?} contre {s:?}"
        );
        assert!(a[1] > 0.05 * s[1], "creux noir : {a:?}");
    }
    let (a, s) = (h_avec[coin_px[0]], h_sans[coin_px[0]]);
    eprintln!("coin : HDR avec {a:?}, sans {s:?} ; sol dégagé : écart relatif max {pire_libre:.2e}");
}
