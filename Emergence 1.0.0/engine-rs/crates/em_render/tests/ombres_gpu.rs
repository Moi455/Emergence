//! Essais des ombres du soleil en cascades (L11) sur un vrai GPU. Sans adaptateur ils s'ignorent avec un message :
//! `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json cargo test -p em_render --test ombres_gpu`.
//! Les matières demandent le chêne de référence (`~/.local/share/emergence/lab_assets/trees/chene_42.vxm`) : sans lui
//! ces essais s'ignorent aussi.
//!
//! Scènes synthétiques (un `VoxelSource` de test, sans modèle) : sol plat + cube de 2 m, puis pente de 30° en escalier.
//! On lit la vue « ombre » de l'éclairage (visibilité du soleil en gris) et on la compare à la géométrie exacte.

use em_core::{ChunkKey, Lod, MaterialId, VoxelValue};
use em_gen::{VxmModel, vegetation_ramps};
use em_material::MaterialTable;
use em_render::sky::noms as noms_ciel;
use em_render::voxel::noms;
use em_render::wgpu;
use em_render::{
    ClipmapConfig, ClipmapStreamer, DebugView, DepthMergePass, FrameContext, GpuContext, GpuMaterials,
    GpuProfiler, GpuRequest, LightSettings, LightingPass, OffscreenTarget, Partage, Projection, RenderGraph,
    ShadowCascades, ShadowParams, SkyBackgroundPass, SkyParams, SkyPass, VoxelCamera, VoxelGpuWorld,
    VoxelMaterialPass, VoxelTracePass,
};
use em_voxel::{Chunk, ChunkHint, VoxelSource};
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

fn modele() -> Option<Arc<VxmModel>> {
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

/// Voxel (niveau 0) du centre de la scène : 10 km de l'origine, comme la scène `arbre`.
const CENTRE: i32 = 200_000;

/// Millimètres monde d'un point relatif au centre de la scène, en mètres.
fn pos_mm(x: f64, y: f64, z: f64) -> [i64; 3] {
    [
        10_000_000 + (x * 1000.0).round() as i64,
        (y * 1000.0).round() as i64,
        10_000_000 + (z * 1000.0).round() as i64,
    ]
}

/// Source de test : sol plat (voxels sous y = 0) et un solide donné par un prédicat sur le CENTRE du voxel, en
/// mètres relatifs au centre de la scène. `zone` borne le solide (voxels, relatifs au centre) pour classer les chunks.
struct SourceDeTest {
    solide: Box<dyn Fn(f64, f64, f64) -> bool + Send + Sync>,
    zone: ([i32; 3], [i32; 3]),
}

impl VoxelSource for SourceDeTest {
    fn fill_chunk(&self, key: ChunkKey, _lod: Lod, out: &mut Chunk) {
        let turf = VoxelValue::new(MaterialId::new(1), 0);
        let (ox, oy, oz) = (key.x * 64, key.y * 64, key.z * 64);
        for z in 0..64_u32 {
            for y in 0..64_u32 {
                for x in 0..64_u32 {
                    let (vx, vy, vz) = (ox + x as i32, oy + y as i32, oz + z as i32);
                    let sol = vy < 0;
                    let m = |v: i32, c: i32| (f64::from(v - c) + 0.5) * 0.05;
                    if sol || (self.solide)(m(vx, CENTRE), m(vy, 0), m(vz, CENTRE)) {
                        out.set(x, y, z, turf);
                    }
                }
            }
        }
    }

    fn classify(&self, key: ChunkKey, _lod: Lod) -> ChunkHint {
        let (lo, hi) = self.zone;
        let (cx, cy, cz) = (key.x * 64, key.y * 64, key.z * 64);
        if cy + 63 < 0 {
            return ChunkHint::Solid(VoxelValue::new(MaterialId::new(1), 0));
        }
        let hors = |c: i32, l: i32, h: i32| c + 63 < CENTRE + l || c > CENTRE + h;
        let hors_y = cy + 63 < lo[1] || cy > hi[1];
        if hors(cx, lo[0], hi[0]) || hors_y || hors(cz, lo[2], hi[2]) {
            ChunkHint::Air
        } else {
            ChunkHint::Unknown
        }
    }

    fn version_tag(&self) -> u64 {
        7
    }
}

/// Cube de 2 m de côté posé sur le sol, centré sur l'origine de la scène.
fn scene_cube() -> SourceDeTest {
    SourceDeTest {
        solide: Box::new(|x, y, z| x.abs() < 1.0 && z.abs() < 1.0 && y > 0.0 && y < 2.0),
        zone: ([-30, 0, -30], [30, 50, 30]),
    }
}

/// Pente de 30° montant vers +x entre x = -3 et x = 3 (escalier de voxels), puis plateau à 3,46 m.
fn scene_pente() -> SourceDeTest {
    let t30 = 30.0_f64.to_radians().tan();
    SourceDeTest {
        solide: Box::new(move |x, y, z| {
            z.abs() < 4.0 && x > -3.0 && y > 0.0 && y < ((x.min(3.0) + 3.0) * t30)
        }),
        zone: ([-60, 0, -80], [120, 80, 80]),
    }
}

/// Réglages par défaut, mais toutes les tuiles d'une génération en une image (un essai rend une image par soleil).
fn instantane() -> ShadowParams {
    ShadowParams::default().with_tiles_per_frame(1024).unwrap()
}

/// Banc : graphe complet jusqu'à l'éclairage (sans bloom ni AgX : on lit la vraie valeur dans le HDR).
struct Banc {
    gpu: GpuContext,
    graphe: RenderGraph,
    monde: VoxelGpuWorld,
    streamer: ClipmapStreamer,
    cible: OffscreenTarget,
    profil: GpuProfiler,
    ciel: Partage<SkyParams>,
    taille: (u32, u32),
    index: u64,
}

fn monter(gpu: GpuContext, taille: (u32, u32), params: ShadowParams, vue: DebugView) -> Option<Banc> {
    let modele = modele()?;
    let t = table();
    let veg = vegetation_ramps(modele.meta(), 0).unwrap();
    let materiaux = GpuMaterials::new(&gpu, &t, &veg);
    let monde = VoxelGpuWorld::new(&gpu, ClipmapConfig::laboratoire()).expect("monde GPU");
    let ciel = Partage::new(SkyParams::new(35.0, 200.0, 3.0, 0.3).unwrap());
    let mut graphe = RenderGraph::new();
    graphe.add(Box::new(SkyPass::new(ciel.clone()))).unwrap();
    graphe.add(Box::new(SkyBackgroundPass::new())).unwrap();
    graphe
        .add(Box::new(ShadowCascades::new(
            params,
            ciel.clone(),
            monde.bindings(),
        )))
        .unwrap();
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
    let cible = OffscreenTarget::new(&gpu, taille.0, taille.1).unwrap();
    let profil = GpuProfiler::new(&gpu, 32);
    drop(materiaux);
    Some(Banc {
        gpu,
        graphe,
        monde,
        streamer: ClipmapStreamer::new(1, ClipmapStreamer::BUDGET_PAR_DEFAUT),
        cible,
        profil,
        ciel,
        taille,
        index: 0,
    })
}

impl Banc {
    fn soleil(&self, elevation: f32, azimut_ciel: f32) {
        self.ciel
            .remplacer(SkyParams::new(elevation, azimut_ciel, 3.0, 0.3).unwrap());
    }

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

    fn lire(&self, nom: em_render::graph::ResourceName, octets_par_pixel: u32) -> Vec<u8> {
        let tex = self.graphe.resources().texture(nom).expect("ressource");
        lire_couche(&self.gpu, tex, self.taille, octets_par_pixel, 0)
    }

    /// Visibilité écrite par la vue « ombre » : `None` sur les faces tournées à l'opposé du soleil.
    fn visibilites(&self) -> Vec<Option<f32>> {
        let hdr = self.lire(noms_ciel::HDR, 8);
        let demi: Vec<u16> = hdr
            .as_chunks::<2>()
            .0
            .iter()
            .map(|b| u16::from_le_bytes(*b))
            .collect();
        demi.chunks(4)
            .map(|p| {
                let (r, g, b) = (demi_vers_f32(p[0]), demi_vers_f32(p[1]), demi_vers_f32(p[2]));
                if (r - 0.25).abs() < 0.01 && g.abs() < 0.01 && (b - 0.25).abs() < 0.01 {
                    None
                } else {
                    Some(r)
                }
            })
            .collect()
    }
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

fn lire_couche(gpu: &GpuContext, tex: &wgpu::Texture, taille: (u32, u32), bpp: u32, couche: u32) -> Vec<u8> {
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
    let mut copie = tex.as_image_copy();
    copie.origin.z = couche;
    enc.copy_texture_to_buffer(
        copie,
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

fn flottants(octets: &[u8]) -> Vec<f32> {
    octets
        .as_chunks::<4>()
        .0
        .iter()
        .map(|b| f32::from_le_bytes(*b))
        .collect()
}

/// Rayon du pixel `(px, py)` d'une caméra en perspective : direction unitaire en repère monde (gauche).
fn direction(cam: &VoxelCamera, taille: (u32, u32), px: u32, py: u32) -> [f64; 3] {
    let aspect = taille.0 as f32 / taille.1 as f32;
    let (tx, ty) = cam.demi_tangentes(aspect);
    let nx = (px as f32 + 0.5) / taille.0 as f32 * 2.0 - 1.0;
    let ny = 1.0 - (py as f32 + 0.5) / taille.1 as f32 * 2.0;
    let d = cam.avant() + cam.droite() * (nx * tx) + cam.haut() * (ny * ty);
    let d = d.normalize();
    [f64::from(d.x), f64::from(d.y), f64::from(d.z)]
}

/// Le rayon `o + t d` (t > 0) touche-t-il la boîte `[lo, hi]` ?
fn touche_la_boite(o: [f64; 3], d: [f64; 3], lo: [f64; 3], hi: [f64; 3]) -> bool {
    let (mut t0, mut t1) = (0.0_f64, f64::INFINITY);
    for a in 0..3 {
        if d[a].abs() < 1e-12 {
            if o[a] < lo[a] || o[a] > hi[a] {
                return false;
            }
        } else {
            let (mut a0, mut a1) = ((lo[a] - o[a]) / d[a], (hi[a] - o[a]) / d[a]);
            if a0 > a1 {
                std::mem::swap(&mut a0, &mut a1);
            }
            t0 = t0.max(a0);
            t1 = t1.min(a1);
            if t0 > t1 {
                return false;
            }
        }
    }
    true
}

fn normale_de_face(face: u32) -> [f64; 3] {
    let mut n = [0.0; 3];
    n[(face / 2) as usize] = if face % 2 == 1 { 1.0 } else { -1.0 };
    n
}

/// Mesure d'une vue d'essai : pixels éclairés qui devraient l'être mais sont assombris (acné), pixels sombres qui
/// devraient l'être mais sont éclairés (décollement ou fuite).
#[derive(Debug, Default, Clone, Copy)]
struct Bilan {
    sur_eclaires: u32,
    acne: u32,
    sur_ombres: u32,
    decollement: u32,
    faces_eclairees: u32,
    faces_acne: u32,
    sur_ombres_loin: u32,
    decollement_loin: u32,
}

/// Texel de la cascade qui sert un point à `t` mètres de la caméra (les cascades se suivent par doublement).
fn texel_a(t: f64, p: &ShadowParams) -> f64 {
    (0..p.cascades())
        .find(|c| t < p.far_m(*c))
        .map_or_else(|| p.texel_m(p.cascades() - 1), |c| p.texel_m(c))
}

/// Rend la scène du cube sous un soleil donné et compare la visibilité à la géométrie exacte, avec une marge de
/// jugement de `max(3 cm, 2,2 texels de la cascade qui sert le pixel)` : on ne juge pas ce que la résolution de la
/// cascade ne peut pas montrer. Le décollement n'est jugé qu'au pied du cube (à moins de 60 cm), là où l'œil le voit ;
/// le raccourcissement du bout d'une longue ombre est compté à part (`decollement_loin`).
fn mesurer_cube(
    banc: &mut Banc,
    params: &ShadowParams,
    elevation: f32,
    azimut: f32,
    camera: [f64; 4],
) -> Bilan {
    banc.soleil(elevation, azimut);
    let s = banc.ciel.lire().0.sun_direction();
    let s = [f64::from(s.x), f64::from(s.y), f64::from(s.z)];
    let cam = VoxelCamera::new(
        pos_mm(camera[0] + 0.0073, camera[1] + 0.0031, camera[2]),
        0.0,
        camera[3] as f32,
        Projection::Perspective { fov_y_deg: 75.0 },
    )
    .unwrap();
    banc.rendre(&cam, &scene_cube());
    let (l, h) = banc.taille;
    let hit = mots(&banc.lire(noms::HIT, 16));
    let dist = flottants(&banc.lire(noms::DIST, 4));
    let vis = banc.visibilites();
    let o_cam = [camera[0] + 0.0073, camera[1] + 0.0031, camera[2]];
    let mut b = Bilan::default();
    let mut image = vec![0_u8; (l * h * 3) as usize];
    for py in 0..h {
        for px in 0..l {
            let i = (py * l + px) as usize;
            if (hit[4 * i] >> 20) & 1 == 0 {
                continue;
            }
            let Some(v) = vis[i] else { continue };
            let gris = (v.clamp(0.0, 1.0) * 255.0) as u8;
            image[3 * i..3 * i + 3].copy_from_slice(&[gris, gris, gris]);
            let d = direction(&cam, (l, h), px, py);
            let t = f64::from(dist[i]);
            let p = [o_cam[0] + d[0] * t, o_cam[1] + d[1] * t, o_cam[2] + d[2] * t];
            let n = normale_de_face((hit[4 * i] >> 16) & 7);
            if p[1] < 0.02 && n[1] > 0.9 {
                // Sol : sûrement éclairé si le rayon vers le soleil rate le cube GONFLÉ de la marge, sûrement
                // dans l'ombre s'il touche le cube RÉTRÉCI de la marge. Entre les deux : l'arête, non jugée.
                let marge = (2.2 * texel_a(t, params)).max(0.03);
                let o = [p[0], 0.0, p[2]];
                let gros = touche_la_boite(
                    o,
                    s,
                    [-1.0 - marge, 0.0, -1.0 - marge],
                    [1.0 + marge, 2.0 + marge, 1.0 + marge],
                );
                let petit = touche_la_boite(
                    o,
                    s,
                    [-1.0 + marge, 0.0, -1.0 + marge],
                    [1.0 - marge, 2.0 - marge, 1.0 - marge],
                );
                // distance horizontale au pied du cube
                let pied = (p[0].abs() - 1.0).max(0.0).hypot((p[2].abs() - 1.0).max(0.0));
                if !gros {
                    b.sur_eclaires += 1;
                    if v < 0.99 {
                        b.acne += 1;
                        if std::env::var("EM_ESSAI_DUMP").is_ok() {
                            eprintln!("acné px ({px}, {py}) p = {p:?} v = {v} marge = {marge}");
                        }
                        image[3 * i..3 * i + 3].copy_from_slice(&[0, 0, 255]);
                    }
                } else if petit {
                    if pied <= 0.6 {
                        b.sur_ombres += 1;
                        b.decollement += u32::from(v > 0.02);
                    } else {
                        b.sur_ombres_loin += 1;
                        b.decollement_loin += u32::from(v > 0.02);
                    }
                    if v > 0.02 {
                        image[3 * i..3 * i + 3].copy_from_slice(&[255, 0, 0]);
                    }
                }
            } else if p[1] > 0.02 {
                // Face du cube tournée vers le soleil : aucun occulteur possible.
                b.faces_eclairees += 1;
                b.faces_acne += u32::from(v < 0.99);
            }
        }
    }
    // Débogage : EM_ESSAI_DUMP=<dossier> écrit l'image (gris = visibilité, rouge = trop éclairé, bleu = trop sombre).
    if let Ok(dossier) = std::env::var("EM_ESSAI_DUMP") {
        let nom = format!("{dossier}/cube_{elevation}_{azimut}_{}.png", camera[1]);
        let _ = image::save_buffer(nom, &image, l, h, image::ColorType::Rgb8);
    }
    b
}

/// Les deux prises de vue : de près (tout dans la cascade 0) et de loin (cascades 1 et 2).
const PRISES: [[f64; 4]; 2] = [[0.0, 4.0, -4.5, -35.0], [0.0, 9.0, -7.0, -55.0]];

const SOLEILS: [(f32, f32); 5] = [
    (12.0, 160.0),
    (25.0, 200.0),
    (45.0, 150.0),
    (70.0, 215.0),
    (85.0, 90.0),
];

/// Acné et décollement sur sol plat + cube, de 12° à 85° de hauteur de soleil, de près et de loin. Deux jeux de
/// réglages : l'ombre DURE (pénombre nulle : on juge acné et décollement) et le défaut (pénombre physique plafonnée à
/// 4 cm : la pénombre éclaire légèrement les bords de l'ombre, on ne juge que l'acné).
#[test]
fn pas_d_acne_ni_de_decollement_sur_sol_plat_et_cube() {
    let Some(gpu) = contexte() else { return };
    let dure = instantane().with_penumbra(0.0, 0.0).unwrap();
    let Some(mut banc) = monter(gpu, (480, 270), dure, DebugView::Shadow) else {
        return;
    };
    for prise in PRISES {
        for (elevation, azimut) in SOLEILS {
            let b = mesurer_cube(&mut banc, &dure, elevation, azimut, prise);
            eprintln!("ombre dure, caméra {prise:?}, soleil {elevation}° / {azimut}° : {b:?}");
            assert!(b.sur_eclaires > 2_000, "trop peu de sol éclairé jugé : {b:?}");
            assert_eq!(b.acne, 0, "acné sur le sol : {b:?}");
            assert_eq!(
                b.faces_acne, 0,
                "pixel éclairé du cube assombri par lui-même : {b:?}"
            );
            if elevation < 80.0 {
                assert!(b.sur_ombres > 100, "trop peu de sol dans l'ombre jugé : {b:?}");
                assert!(
                    f64::from(b.decollement) <= 0.002 * f64::from(b.sur_ombres),
                    "décollement de l'ombre au pied du cube : {b:?}"
                );
            }
        }
    }
    drop(banc);
    let defaut = instantane();
    let Some(mut banc) = monter(contexte().unwrap(), (480, 270), defaut, DebugView::Shadow) else {
        return;
    };
    for prise in PRISES {
        for (elevation, azimut) in SOLEILS {
            let b = mesurer_cube(&mut banc, &defaut, elevation, azimut, prise);
            eprintln!("pénombre par défaut, caméra {prise:?}, soleil {elevation}° / {azimut}° : {b:?}");
            assert_eq!(b.acne, 0, "acné sur le sol : {b:?}");
            assert_eq!(
                b.faces_acne, 0,
                "pixel éclairé du cube assombri par lui-même : {b:?}"
            );
        }
    }
}

/// Balayage des biais (à lancer à la main : `-- --ignored --nocapture balayage`) : acné et décollement par réglage.
#[test]
#[ignore = "calibrage manuel"]
fn balayage_des_biais() {
    let mut essais = vec![
        (1.5_f32, 2.0_f32, 1.5_f32),
        (1.0, 1.0, 1.0),
        (1.0, 1.0, 0.5),
        (0.7, 1.0, 0.5),
        (1.0, 0.5, 0.3),
        (0.5, 0.5, 0.3),
        (1.5, 1.0, 0.0),
        (0.0, 1.0, 1.0),
    ];
    // EM_BALAYAGE="décalage,biais_mm,pente" : un seul réglage (avec EM_ESSAI_DUMP pour voir les pixels fautifs)
    if let Ok(v) = std::env::var("EM_BALAYAGE") {
        let n: Vec<f32> = v.split(',').filter_map(|s| s.parse().ok()).collect();
        essais = vec![(n[0], n[1], n[2])];
    }
    for (decalage, biais_mm, pente) in essais {
        let p = instantane()
            .with_penumbra(0.0, 0.0)
            .unwrap()
            .with_normal_offset(decalage)
            .unwrap()
            .with_bias(biais_mm * 0.001, pente)
            .unwrap();
        let Some(mut banc) = monter(contexte().unwrap(), (480, 270), p, DebugView::Shadow) else {
            return;
        };
        let mut ligne = String::new();
        for prise in PRISES {
            for (elevation, azimut) in SOLEILS {
                let b = mesurer_cube(&mut banc, &p, elevation, azimut, prise);
                ligne += &format!(
                    " | {elevation}° a{}+{} d{:.1}/{:.0}%",
                    b.acne,
                    b.faces_acne,
                    100.0 * f64::from(b.decollement) / f64::from(b.sur_ombres.max(1)),
                    100.0 * f64::from(b.decollement_loin) / f64::from(b.sur_ombres_loin.max(1))
                );
            }
            ligne += " ||";
        }
        eprintln!("décalage {decalage} biais {biais_mm} mm pente {pente}{ligne}");
    }
}

/// Pente de 30° en escalier de voxels, soleil de face : aucun pixel tourné vers le soleil n'est assombri.
#[test]
fn pas_d_acne_sur_une_pente_de_30_degres() {
    let Some(gpu) = contexte() else { return };
    let Some(mut banc) = monter(gpu, (480, 270), instantane(), DebugView::Shadow) else {
        return;
    };
    // soleil dans le plan x-y, côté -x (azimut du ciel 270°) : 35° (presque rasant sur la pente), 50° et 60° (normale)
    for elevation in [35.0_f32, 50.0, 60.0] {
        banc.soleil(elevation, 270.0);
        let cam = VoxelCamera::new(
            pos_mm(-7.0, 6.0, -9.0),
            35.0,
            -28.0,
            Projection::Perspective { fov_y_deg: 70.0 },
        )
        .unwrap();
        banc.rendre(&cam, &scene_pente());
        let hit = mots(&banc.lire(noms::HIT, 16));
        let vis = banc.visibilites();
        let (mut jugees, mut sombres, mut pente) = (0_u32, 0_u32, 0_u32);
        let (l, h) = banc.taille;
        let mut image = vec![0_u8; (l * h * 3) as usize];
        for (i, v) in vis.iter().enumerate() {
            if (hit[4 * i] >> 20) & 1 == 0 {
                continue;
            }
            if let Some(v) = v {
                // face presque parallèle aux rayons du soleil (ndl < 0,15) : non jugée, l'ombre y est affaire de millimètres
                let n = normale_de_face((hit[4 * i] >> 16) & 7);
                let s = banc.ciel.lire().0.sun_direction();
                if n[0] * f64::from(s.x) + n[1] * f64::from(s.y) + n[2] * f64::from(s.z) < 0.15 {
                    continue;
                }
                if (hit[4 * i + 2] as i32) < 0 || (hit[4 * i + 1] as i32 - CENTRE) < -60 {
                    continue; // sol : jugé par l'essai du cube
                }
                jugees += 1;
                sombres += u32::from(*v < 0.99);
                if *v < 0.99 && std::env::var("EM_ESSAI_DUMP").is_ok() {
                    eprintln!(
                        "sombre face {} voxel {} {} {} v {v}",
                        (hit[4 * i] >> 16) & 7,
                        hit[4 * i + 1] as i32 - CENTRE,
                        hit[4 * i + 2] as i32,
                        hit[4 * i + 3] as i32 - CENTRE
                    );
                }
                let g = (v.clamp(0.0, 1.0) * 255.0) as u8;
                let face = (hit[4 * i] >> 16) & 7;
                image[3 * i..3 * i + 3].copy_from_slice(&if *v < 0.99 {
                    [255, 0, face as u8 * 40]
                } else {
                    [g, g, g]
                });
                // un voxel de la pente (au-dessus du sol) : y > 0 (coordonnée du voxel touché)
                pente += u32::from(hit[4 * i + 2] as i32 >= 0);
            }
        }
        eprintln!(
            "pente, soleil {elevation}° : {jugees} pixels jugés dont {pente} sur la pente, {sombres} assombris"
        );
        if let Ok(dossier) = std::env::var("EM_ESSAI_DUMP") {
            let _ = image::save_buffer(
                format!("{dossier}/pente_{elevation}.png"),
                &image,
                l,
                h,
                image::ColorType::Rgb8,
            );
        }
        assert!(pente > 1_000, "la pente doit être vue");
        // À 35° (5° au-dessus de la pente) le filtre de pénombre touche les arêtes des marches : on tolère 4 % de pixels
        // légèrement assombris (mesuré : 2,7 %), au-dessus de 45° 1 % (mesuré : 0 % à 50°, 0,5 % à 60°).
        let tolere = if elevation < 45.0 {
            jugees / 25
        } else {
            jugees / 100
        };
        assert!(
            sombres <= tolere,
            "{sombres} pixels tournés vers le soleil assombris par eux-mêmes"
        );
    }
}

/// Octets de la couche `c` du tableau des cascades (génération avant au premier remplissage : couche `c`).
fn couche_des_cascades(banc: &Banc, c: u32, cote: u32) -> Vec<f32> {
    let tex = banc
        .graphe
        .resources()
        .texture(em_render::voxel::shadow::noms::CASCADES)
        .expect("cascades");
    flottants(&lire_couche(&banc.gpu, tex, (cote, cote), 4, c))
}

/// Deux captures dont la caméra est décalée de moins d'un texel donnent les MÊMES cascades (aux arrondis près
/// du départ des rayons) ; une caméra qui franchit un cran de calage décale la fenêtre d'un nombre ENTIER de
/// texels et la valeur de chaque texel reste la même ; une caméra qui tourne sur place ne refait rien.
#[test]
fn les_cascades_sont_stables() {
    use em_render::voxel::shadow::{CascadePlacement, SunBasis};
    let Some(gpu) = contexte() else { return };
    let params = ShadowParams::new(4, 0.0125, 1024).unwrap();
    let Some(mut banc) = monter(gpu, (160, 90), params, DebugView::Beauty) else {
        return;
    };
    banc.soleil(32.0, 250.0);
    let sun = banc.ciel.lire().0.sun_direction();
    let base = SunBasis::new(glam_f64(sun));
    let quantum = params.quantum();
    let lance = |banc: &mut Banc, x: f64, y: f64, z: f64, lacet: f32| {
        let cam = VoxelCamera::new(
            pos_mm(x, y, z),
            lacet,
            -10.0,
            Projection::Perspective { fov_y_deg: 60.0 },
        )
        .unwrap();
        banc.rendre(&cam, &scene_cube());
    };
    let placements = |x: f64, y: f64, z: f64| -> Vec<CascadePlacement> {
        let cam = glam_f64_xyz(10_000.0 + x, y, 10_000.0 + z);
        (0..4)
            .map(|c| CascadePlacement::around(&base, cam, params.texel_m(c), params.size(), quantum))
            .collect()
    };
    let cote = params.size();
    let comparer = |a: &[f32], b: &[f32], dk: usize, dm: usize| -> (u64, u64) {
        // b[i - dk][j - dm] contre a[i][j] sur le recouvrement ; (texels comparés, texels qui diffèrent de > 5 mm)
        let n = cote as usize;
        let (mut total, mut diff) = (0_u64, 0_u64);
        for j in dm..n {
            for i in dk..n {
                let (va, vb) = (a[j * n + i], b[(j - dm) * n + (i - dk)]);
                total += 1;
                let ecart = if va > 1e8 && vb > 1e8 {
                    0.0
                } else {
                    (va - vb).abs()
                };
                diff += u64::from(ecart > 0.005);
            }
        }
        (total, diff)
    };

    // A : première capture ; B : décalée de 0,3 texel dans le plan des texels, sans franchir de cran.
    let (xa, ya, za) = (0.40, 1.7, -3.1);
    let pa = placements(xa, ya, za);
    // décalage de 0,3 texel de la cascade 0 le long de `right`, vérifié sans changement de calage
    let r = base.right();
    let dec = 0.3 * params.texel_m(0);
    let (xb, zb) = (xa + r.x * dec, za + r.z * dec);
    let pb = placements(xb, ya, zb);
    assert_eq!(
        pa, pb,
        "le décalage de 0,3 texel ne doit franchir aucun cran (choisir un autre point)"
    );
    lance(&mut banc, xa, ya, za, 0.0);
    let a: Vec<Vec<f32>> = (0..4).map(|c| couche_des_cascades(&banc, c, cote)).collect();
    let mut banc_b = monter(contexte().unwrap(), (160, 90), params, DebugView::Beauty).unwrap();
    banc_b.soleil(32.0, 250.0);
    lance(&mut banc_b, xb, ya, zb, 123.0);
    for c in 0..4_u32 {
        let b = couche_des_cascades(&banc_b, c, cote);
        let (total, diff) = comparer(&a[c as usize], &b, 0, 0);
        eprintln!("décalage < 1 texel, cascade {c} : {diff} texels sur {total} diffèrent de plus de 5 mm");
        assert!(diff * 100_000 <= total, "cascade {c} : {diff} / {total}");
    }

    // C : caméra qui franchit un cran de la cascade 0 : même calage pour les autres cascades ou décalage entier.
    // On se place à 0,25 texel avant la frontière d'arrondi du cran, puis 0,25 texel après.
    let q = f64::from(quantum);
    let ts = params.texel_m(0);
    let u_frontiere =
        ((glam_f64_xyz(10_000.0 + xa, ya, 10_000.0 + za).dot(base.right()) / ts / q).floor() + 0.5) * q * ts;
    let origine = glam_f64_xyz(10_000.0 + xa, ya, 10_000.0 + za);
    let avant = origine + base.right() * (u_frontiere - 0.25 * ts - origine.dot(base.right()));
    let apres = origine + base.right() * (u_frontiere + 0.25 * ts - origine.dot(base.right()));
    let (p_av, p_ap) = (
        CascadePlacement::around(&base, avant, ts, params.size(), quantum),
        CascadePlacement::around(&base, apres, ts, params.size(), quantum),
    );
    let dk = p_ap.k0() - p_av.k0();
    assert_eq!(
        dk,
        i64::from(quantum),
        "la caméra doit franchir exactement un cran"
    );
    assert_eq!(p_ap.m0(), p_av.m0());
    let mut banc_c = monter(contexte().unwrap(), (160, 90), params, DebugView::Beauty).unwrap();
    banc_c.soleil(32.0, 250.0);
    lance(&mut banc_c, avant.x - 10_000.0, avant.y, avant.z - 10_000.0, 10.0);
    let c_av = couche_des_cascades(&banc_c, 0, cote);
    let mut banc_d = monter(contexte().unwrap(), (160, 90), params, DebugView::Beauty).unwrap();
    banc_d.soleil(32.0, 250.0);
    lance(
        &mut banc_d,
        apres.x - 10_000.0,
        apres.y,
        apres.z - 10_000.0,
        200.0,
    );
    let c_ap = couche_des_cascades(&banc_d, 0, cote);
    // texel absolu K : indice i = K - k0 ; avant : i, après : i - dk. On compare c_av[i] à c_ap[i - dk].
    let (total, diff) = comparer(&c_av, &c_ap, dk as usize, 0);
    eprintln!(
        "cran franchi (0,5 texel de déplacement), cascade 0 : {diff} texels sur {total} diffèrent de plus de 5 mm"
    );
    assert!(
        diff * 100_000 <= total,
        "cascade 0 après un cran : {diff} / {total}"
    );

    // D : rotation sur place de 360° : aucune tuile refaite, les cascades ne changent pas d'un octet.
    let avant_rotation: Vec<Vec<f32>> = (0..4).map(|c| couche_des_cascades(&banc, c, cote)).collect();
    for k in 1..=24 {
        lance(&mut banc, xa, ya, za, 15.0 * k as f32);
    }
    for c in 0..4_u32 {
        let apres_rotation = couche_des_cascades(&banc, c, cote);
        assert_eq!(
            avant_rotation[c as usize], apres_rotation,
            "cascade {c} modifiée par une rotation de la caméra"
        );
    }
}

fn glam_f64(v: em_render::glam::Vec3) -> em_render::glam::DVec3 {
    em_render::glam::DVec3::new(f64::from(v.x), f64::from(v.y), f64::from(v.z))
}

fn glam_f64_xyz(x: f64, y: f64, z: f64) -> em_render::glam::DVec3 {
    em_render::glam::DVec3::new(x, y, z)
}

/// Stabilité à l'écran : la caméra tourne de 360° en 600 images (10 s à 60 i/s) sur une scène fixe ; d'une image à
/// l'autre, la part des pixels du sol déjà visibles dont l'état d'ombre change doit rester ≤ 0,5 %. Les pixels
/// sont reliés par re-projection du point du monde vu à l'image n + 1 dans l'image n (la caméra ne bouge pas, elle
/// tourne : les positions relatives suffisent).
#[test]
fn l_etat_d_ombre_ne_scintille_pas_pendant_une_rotation_de_360_degres() {
    let Some(gpu) = contexte() else { return };
    let Some(mut banc) = monter(gpu, (256, 144), ShadowParams::default(), DebugView::Shadow) else {
        return;
    };
    banc.soleil(38.0, 215.0);
    let (l, h) = banc.taille;
    let fov = 75.0_f32;
    let pos = pos_mm(0.0, 1.7, -4.5);
    let camera =
        |lacet: f32| VoxelCamera::new(pos, lacet, -12.0, Projection::Perspective { fov_y_deg: fov }).unwrap();
    let source = scene_cube();
    // état d'une image : visibilité, distance, touché
    let etat = |banc: &mut Banc, cam: &VoxelCamera| {
        banc.rendre(cam, &source);
        let hit = mots(&banc.lire(noms::HIT, 16));
        let dist = flottants(&banc.lire(noms::DIST, 4));
        let vis = banc.visibilites();
        (hit, dist, vis)
    };
    let images = 600;
    let pas = 360.0 / images as f32;
    let mut precedent = {
        let c = camera(0.0);
        (c, etat(&mut banc, &c))
    };
    let (mut compares, mut changes, mut pire) = (0_u64, 0_u64, 0.0_f64);
    for k in 1..=images {
        let c = camera(pas * k as f32);
        let courant = etat(&mut banc, &c);
        let (cam_p, (hit_p, dist_p, vis_p)) = &precedent;
        let (mut cmp, mut chg) = (0_u64, 0_u64);
        let (fx, fy) = {
            let (tx, ty) = c.demi_tangentes(l as f32 / h as f32);
            (tx, ty)
        };
        let _ = (fx, fy);
        for py in 0..h {
            for px in 0..l {
                let i = (py * l + px) as usize;
                if (courant.0[4 * i] >> 20) & 1 == 0 {
                    continue;
                }
                let Some(v_n) = courant.2[i] else { continue };
                let d = direction(&c, (l, h), px, py);
                let t = f64::from(courant.1[i]);
                let w = [d[0] * t, d[1] * t, d[2] * t];
                // projection dans l'image précédente
                let (a, r, u) = (cam_p.avant(), cam_p.droite(), cam_p.haut());
                let wf = w[0] * f64::from(a.x) + w[1] * f64::from(a.y) + w[2] * f64::from(a.z);
                if wf <= 0.1 {
                    continue;
                }
                let wr = w[0] * f64::from(r.x) + w[1] * f64::from(r.y) + w[2] * f64::from(r.z);
                let wu = w[0] * f64::from(u.x) + w[1] * f64::from(u.y) + w[2] * f64::from(u.z);
                let (tx, ty) = cam_p.demi_tangentes(l as f32 / h as f32);
                let nx = wr / wf / f64::from(tx);
                let ny = wu / wf / f64::from(ty);
                let (qx, qy) = ((nx + 1.0) * 0.5 * f64::from(l), (1.0 - ny) * 0.5 * f64::from(h));
                if qx < 0.0 || qy < 0.0 || qx >= f64::from(l) || qy >= f64::from(h) {
                    continue;
                }
                let j = (qy as u32 * l + qx as u32) as usize;
                if (hit_p[4 * j] >> 20) & 1 == 0 || (f64::from(dist_p[j]) - t).abs() > 0.02 {
                    continue;
                }
                let Some(v_p) = vis_p[j] else { continue };
                cmp += 1;
                chg += u64::from((v_n > 0.5) != (v_p > 0.5));
            }
        }
        compares += cmp;
        changes += chg;
        if cmp > 500 {
            pire = pire.max(chg as f64 / cmp as f64);
        }
        precedent = (c, courant);
    }
    let part = changes as f64 / compares as f64;
    eprintln!(
        "rotation de 360° en {images} images : {changes} changements d'état sur {compares} pixels comparés = {:.4} % (pire image : {:.4} %)",
        part * 100.0,
        pire * 100.0
    );
    assert!(compares > 100_000, "trop peu de pixels comparés : {compares}");
    assert!(
        part <= 0.005,
        "{:.3} % des pixels changent d'état d'ombre",
        part * 100.0
    );
}
