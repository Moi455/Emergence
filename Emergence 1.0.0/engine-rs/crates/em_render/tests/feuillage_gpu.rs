//! Essais de la lumière du feuillage (L10 étendue) sur un vrai GPU : couleur du soleil (transmittance de l'atmosphère) et
//! translucidité des feuilles. Sans adaptateur ils s'ignorent avec un message :
//! `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json cargo test -p em_render --test feuillage_gpu`.
//! Les matières demandent le chêne de référence (`~/.local/share/emergence/lab_assets/trees/chene_42.vxm`) : sans lui
//! ces essais s'ignorent aussi.
//!
//! Scènes synthétiques (un `VoxelSource` de test, sans modèle) :
//! - sol plat + grand cube vu d'en haut en orthographique : le sol au soleil et le sol dans l'ombre du cube ne diffèrent que
//!   par l'éclairage direct, dont la couleur doit être celle de la transmittance de l'atmosphère (référence CPU) ;
//! - plaque de feuilles de 10 cm vue à contre-jour : la lumière ajoutée par la translucidité est comparée au calcul CPU
//!   (`FoliageLightParams::translucent_radiance`), puis nulle quand un solide barre le soleil, quand une autre feuille
//!   (au-delà de la zone comptée) l'ombrage, ou quand la face regarde le soleil ; moindre derrière deux plaques.

use em_core::{ChunkKey, Lod, MaterialId, VoxelValue};
use em_gen::{VxmModel, vegetation_ramps};
use em_material::MaterialTable;
use em_render::sky::noms as noms_ciel;
use em_render::voxel::{foliage, noms};
use em_render::wgpu;
use em_render::{
    AtmosphereReference, ClipmapConfig, ClipmapStreamer, DebugView, DepthMergePass, FoliageLightParams,
    FoliageThicknessPass, FrameContext, GpuContext, GpuMaterials, GpuProfiler, GpuRequest, LeafLightSample,
    LightSettings, LightingPass, OffscreenTarget, Partage, Projection, RenderGraph, ShadowCascades,
    ShadowParams, SkyBackgroundPass, SkyParams, SkyPass, VoxelCamera, VoxelGpuWorld, VoxelMaterialPass,
    VoxelTracePass,
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

/// Solide de test : nom de la matière du voxel dont le CENTRE est en (x, y, z) mètres relatifs à la scène.
type Solide = Box<dyn Fn(f64, f64, f64) -> Option<&'static str> + Send + Sync>;

/// Source de test : sol plat de turf (sous y = 0) et un solide de matières nommées.
struct SourceDeTest {
    solide: Solide,
    ids: Vec<(&'static str, MaterialId)>,
    zone: ([i32; 3], [i32; 3]),
}

impl SourceDeTest {
    fn new(t: &MaterialTable, solide: Solide) -> Self {
        let ids = ["leaves", "granite"]
            .into_iter()
            .map(|n| (n, t.by_name(n).unwrap_or_else(|| panic!("matière {n}"))))
            .collect();
        Self {
            solide,
            ids,
            zone: ([-80, 0, -80], [80, 200, 80]),
        }
    }

    fn id(&self, nom: &str) -> MaterialId {
        self.ids
            .iter()
            .find(|(n, _)| *n == nom)
            .expect("matière connue")
            .1
    }
}

impl VoxelSource for SourceDeTest {
    fn fill_chunk(&self, key: ChunkKey, _lod: Lod, out: &mut Chunk) {
        let turf = VoxelValue::new(MaterialId::new(1), 0);
        let (ox, oy, oz) = (key.x * 64, key.y * 64, key.z * 64);
        for z in 0..64_u32 {
            for y in 0..64_u32 {
                for x in 0..64_u32 {
                    let (vx, vy, vz) = (ox + x as i32, oy + y as i32, oz + z as i32);
                    let m = |v: i32, c: i32| (f64::from(v - c) + 0.5) * 0.05;
                    if vy < 0 {
                        out.set(x, y, z, turf);
                    } else if let Some(nom) = (self.solide)(m(vx, CENTRE), m(vy, 0), m(vz, CENTRE)) {
                        out.set(x, y, z, VoxelValue::new(self.id(nom), 0));
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
        11
    }
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
    lumiere: Partage<LightSettings>,
    taille: (u32, u32),
    index: u64,
}

fn monter(taille: (u32, u32)) -> Option<Banc> {
    let gpu = contexte()?;
    let modele = modele()?;
    let t = table();
    let veg = vegetation_ramps(modele.meta(), 0).unwrap();
    let materiaux = GpuMaterials::new(&gpu, &t, &veg);
    let monde = VoxelGpuWorld::new(&gpu, ClipmapConfig::laboratoire()).expect("monde GPU");
    let ciel = Partage::new(SkyParams::new(35.0, 200.0, 3.0, 0.3).unwrap());
    let lumiere = Partage::new(LightSettings::new(DebugView::Beauty, 1.0).unwrap());
    let ombres = ShadowParams::default().with_tiles_per_frame(1024).unwrap();
    let mut graphe = RenderGraph::new();
    graphe.add(Box::new(SkyPass::new(ciel.clone()))).unwrap();
    graphe.add(Box::new(SkyBackgroundPass::new())).unwrap();
    graphe
        .add(Box::new(ShadowCascades::new(
            ombres,
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
        .add(Box::new(FoliageThicknessPass::new(
            lumiere.clone(),
            monde.bindings(),
            materiaux.bindings(),
        )))
        .unwrap();
    graphe.add(Box::new(LightingPass::new(lumiere.clone()))).unwrap();
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
        lumiere,
        taille,
        index: 0,
    })
}

impl Banc {
    fn soleil(&self, elevation: f32, azimut_ciel: f32) {
        self.ciel
            // Brume nulle : la perspective aérienne ne mêle presque rien de l'horizon à la surface, ce qui
            // fausserait les rapports de couleurs de faible valeur (bleu du turf).
            .remplacer(SkyParams::new(elevation, azimut_ciel, 3.0, 0.0).unwrap());
    }

    fn feuillage(&self, p: FoliageLightParams) {
        self.lumiere.remplacer(
            LightSettings::new(DebugView::Beauty, 1.0)
                .unwrap()
                .with_foliage(p),
        );
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
        lire_texture(&self.gpu, tex, self.taille, octets_par_pixel)
    }

    /// HDR linéaire du pixel `(px, py)`.
    fn hdr(&self, px: u32, py: u32) -> [f32; 3] {
        let o = self.lire(noms_ciel::HDR, 8);
        let i = ((py * self.taille.0 + px) * 8) as usize;
        let h = |k: usize| demi_vers_f32(u16::from_le_bytes([o[i + 2 * k], o[i + 2 * k + 1]]));
        [h(0), h(1), h(2)]
    }

    /// Albédo linéaire du pixel, relu dans GB0 (sRGB 8 bits).
    fn albedo(&self, px: u32, py: u32) -> [f32; 3] {
        let o = self.lire(noms::GB0, 4);
        let i = ((py * self.taille.0 + px) * 4) as usize;
        let c = |k: usize| srgb_vers_lineaire(f32::from(o[i + k]) / 255.0);
        [c(0), c(1), c(2)]
    }

    /// Épaisseur de feuillage écrite par `FoliageThicknessPass` au pixel, en mètres.
    fn epaisseur(&self, px: u32, py: u32) -> f32 {
        let o = self.lire(foliage::noms::EPAISSEUR, 4);
        let i = ((py * self.taille.0 + px) * 4) as usize;
        f32::from_le_bytes([o[i], o[i + 1], o[i + 2], o[i + 3]])
    }
}

fn srgb_vers_lineaire(c: f32) -> f32 {
    if c <= 0.04045 {
        c / 12.92
    } else {
        ((c + 0.055) / 1.055).powf(2.4)
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

// ---------------------------------------------------------------------------------------------------------------
// Couleur du soleil
// ---------------------------------------------------------------------------------------------------------------

/// Rend le sol vu d'en haut (orthographique) avec un grand cube : un point du sol au soleil et un point dans l'ombre du
/// cube. Leur différence, après division de chacun par son albédo, est l'éclairage direct `E × cos / π` : sa couleur est celle de la
/// transmittance de l'atmosphère pour l'élévation du soleil.
#[test]
fn la_couleur_du_soleil_suit_la_transmittance_de_l_atmosphere() {
    let Some(mut banc) = monter((480, 270)) else {
        return;
    };
    let t = table();
    let src = SourceDeTest::new(
        &t,
        Box::new(|x, y, z| (x.abs() < 3.0 && z.abs() < 3.0 && y > 0.0 && y < 4.0).then_some("granite")),
    );
    let reference = AtmosphereReference::new(3.0).unwrap();
    // Caméra à 10 m au-dessus de la scène, tourné vers le bas ; orthographique de 20 m de haut : 13,5 px par mètre.
    let cam = VoxelCamera::new(
        pos_mm(0.0, 10.0, 0.0),
        0.0,
        -90.0,
        Projection::Orthographic { height_m: 20.0 },
    )
    .unwrap();
    let mut rapport = Vec::new();
    for elevation in [60.0_f32, 30.0, 14.0, 9.0, 4.0] {
        banc.soleil(elevation, 180.0); // soleil vers +z : l'ombre du cube tombe vers -z
        banc.rendre(&cam, &src);
        let (l, h) = banc.taille;
        // Haut de l'image = +z (lacet 0, tangage -90) ; px -> x, py -> -z. 13,5 px par mètre.
        let px_par_m = h as f32 / 20.0;
        let pixel = |x: f32, z: f32| -> (u32, u32) {
            (
                (l as f32 / 2.0 + x * px_par_m) as u32,
                (h as f32 / 2.0 - z * px_par_m) as u32,
            )
        };
        // Point au soleil : loin du cube, côté +z ; point à l'ombre : juste derrière le cube (côté -z), au milieu de
        // l'ombre quelle que soit l'élévation (cube haut de 4 m : ombre de 4 / tan(él) mètres, de 2,3 m à 57 m).
        let ombre_m = (4.0 / elevation.to_radians().tan()).min(6.0);
        let (sx, sy) = pixel(0.0, 8.0);
        let (ox, oy) = pixel(0.0, -(3.0 + ombre_m * 0.5).min(8.5));
        let (hs, ho) = (banc.hdr(sx, sy), banc.hdr(ox, oy));
        let (als, alo) = (banc.albedo(sx, sy), banc.albedo(ox, oy));
        let sin = elevation.to_radians().sin();
        let tr = reference.sun_transmittance(0.010, elevation);
        for c in 0..3 {
            // Chaque pixel est ramené à son propre albédo (le turf varie d'un point à l'autre) : la différence des
            // deux est l'éclairage direct, l'ambiance (sans occlusion) étant la même.
            let mesure = hs[c] / als[c] - ho[c] / alo[c];
            let attendu = tr[c] * SkyParams::ECLAIREMENT_DEFAUT * sin / std::f32::consts::PI;
            rapport.push((elevation, c, mesure, attendu));
            let tolerance = 0.06 * attendu + 4e-3;
            assert!(
                (mesure - attendu).abs() < tolerance,
                "soleil {elevation}°, canal {c} : mesuré {mesure}, attendu {attendu} (transmittance {tr:?})"
            );
        }
    }
    for (e, c, m, a) in rapport {
        eprintln!("soleil {e:>4}° canal {c} : GPU {m:.4} / transmittance CPU {a:.4}");
    }
}

/// La LUT de transmittance du GPU est celle de la référence CPU (même paramétrage, même intégration).
#[test]
fn la_lut_de_transmittance_egale_la_reference_cpu() {
    let Some(mut banc) = monter((64, 64)) else { return };
    let t = table();
    let src = SourceDeTest::new(&t, Box::new(|_, _, _| None));
    banc.soleil(20.0, 180.0);
    let cam = VoxelCamera::new(
        pos_mm(0.0, 2.0, -5.0),
        0.0,
        0.0,
        Projection::Perspective { fov_y_deg: 60.0 },
    )
    .unwrap();
    banc.rendre(&cam, &src);
    let tex = banc
        .graphe
        .resources()
        .texture(noms_ciel::TRANSMITTANCE)
        .expect("LUT de transmittance");
    let o = lire_texture(&banc.gpu, tex, (256, 64), 8);
    let reference = AtmosphereReference::new(3.0).unwrap();
    let mut pire: f32 = 0.0;
    for j in (0..64).step_by(3) {
        for i in (0..256).step_by(5) {
            let uv = [(i as f32 + 0.5) / 256.0, (j as f32 + 0.5) / 64.0];
            let (r, mu) = AtmosphereReference::lut_r_mu(uv);
            let attendu = reference.transmittance(r, mu);
            let k = (j * 256 + i) * 8;
            for c in 0..3 {
                let gpu = demi_vers_f32(u16::from_le_bytes([o[k + 2 * c], o[k + 2 * c + 1]]));
                pire = pire.max((gpu - attendu[c]).abs());
                assert!(
                    (gpu - attendu[c]).abs() < 0.01 + 0.02 * attendu[c],
                    "texel ({i}, {j}) canal {c} : GPU {gpu}, CPU {}",
                    attendu[c]
                );
            }
        }
    }
    eprintln!("LUT de transmittance : écart maximal GPU / CPU = {pire:.5}");
}

// ---------------------------------------------------------------------------------------------------------------
// Translucidité
// ---------------------------------------------------------------------------------------------------------------

/// Plaque de feuilles `x ∈ [-2, 2]`, `y ∈ [3, h]`, entre `z0` et `z1` (mètres).
fn plaque(z0: f64, z1: f64, h: f64) -> impl Fn(f64, f64, f64) -> bool {
    move |x, y, z| x.abs() < 2.0 && y > 3.0 && y < h && z > z0 && z < z1
}

struct Mesure {
    delta: [f32; 3],
    attendu: [f32; 3],
    epaisseur: f32,
}

/// Rend la scène avec et sans translucidité, et compare la lumière ajoutée au pixel central au calcul CPU.
/// `camera_z` : de quel côté de la plaque on regarde ; le soleil est vers +z, à 20° au-dessus de l'horizon.
fn mesurer(solide: Solide, camera_z: f64) -> Mesure {
    let banc = monter((480, 270));
    let Some(mut banc) = banc else {
        return Mesure {
            delta: [f32::NAN; 3],
            attendu: [f32::NAN; 3],
            epaisseur: f32::NAN,
        };
    };
    let t = table();
    let src = SourceDeTest::new(&t, solide);
    let elevation = 20.0_f32;
    banc.soleil(elevation, 180.0);
    let (regard, cos_vs_signe) = if camera_z < 0.0 { (0.0, 1.0) } else { (180.0, -1.0) };
    let cam = VoxelCamera::new(
        pos_mm(0.0, 4.5, camera_z),
        regard,
        0.0,
        Projection::Perspective { fov_y_deg: 40.0 },
    )
    .unwrap();
    let defaut = FoliageLightParams::default();
    let eteint = FoliageLightParams::new(0.0, defaut.absorption_m())
        .unwrap()
        .with_rim(0.0, defaut.rim_thickness_m())
        .unwrap();
    banc.feuillage(eteint);
    banc.rendre(&cam, &src);
    let (px, py) = (banc.taille.0 / 2, banc.taille.1 / 2);
    let sans = banc.hdr(px, py);
    banc.feuillage(defaut);
    banc.rendre(&cam, &src);
    let avec = banc.hdr(px, py);
    let delta = [avec[0] - sans[0], avec[1] - sans[1], avec[2] - sans[2]];
    let epaisseur = banc.epaisseur(px, py);
    let albedo = defaut.saturate_albedo(banc.albedo(px, py));
    let sun = banc.ciel.lire().0.sun_direction();
    let n = [0.0, 0.0, -cos_vs_signe]; // face tournée vers la caméra
    let cos_ns = n[2] * sun.z;
    let cos_vs = sun.z * cos_vs_signe;
    let tr = AtmosphereReference::new(3.0)
        .unwrap()
        .sun_transmittance(0.010, elevation);
    let e_sun = tr.map(|c| c * SkyParams::ECLAIREMENT_DEFAUT);
    let attendu = defaut.translucent_radiance(&LeafLightSample {
        sun: e_sun,
        albedo,
        leaf_translucency: 0.45,
        cos_ns,
        cos_vs,
        thickness_m: epaisseur,
        visibility: 1.0,
    });
    Mesure {
        delta,
        attendu,
        epaisseur,
    }
}

fn somme(c: [f32; 3]) -> f32 {
    c[0] + c[1] + c[2]
}

/// Un voxel de feuille à contre-jour reçoit la lumière du soleil qui la traverse (au calcul CPU près), plus qu'à l'ombre
/// d'une autre feuille, et rien si un solide barre le soleil ou si la face regarde le soleil.
#[test]
fn la_translucidite_a_contre_jour_depasse_l_ombre_et_est_nulle_si_occultee() {
    if monter((64, 64)).is_none() {
        return;
    }
    // A : une plaque de feuilles de 10 cm, vue de -z, soleil derrière elle (z > 0).
    let a = mesurer(
        Box::new(|x, y, z| plaque(0.0, 0.1, 6.0)(x, y, z).then_some("leaves")),
        -8.0,
    );
    eprintln!("A (plaque seule) : {:?}", a.delta);
    assert!(
        (a.epaisseur - 0.080).abs() < 0.012,
        "épaisseur de la plaque : {} m (attendu 0,080 : du centre du voxel touché à l'arrière de la plaque, le long du soleil)",
        a.epaisseur
    );
    assert!(
        somme(a.attendu) > 0.05,
        "le calcul CPU donne de la lumière : {:?}",
        a.attendu
    );
    for c in 0..3 {
        assert!(
            (a.delta[c] - a.attendu[c]).abs() < 0.06 * a.attendu[c] + 2e-3,
            "canal {c} : GPU {} / CPU {}",
            a.delta[c],
            a.attendu[c]
        );
    }
    assert!(
        a.delta[1] > a.delta[2] && a.delta[0] > a.delta[2],
        "vert-jaune, pas de bleu : {:?}",
        a.delta
    );

    // B : un bloc de granite entre la plaque et le soleil (dans la zone comptée) : le soleil est barré, rien ne passe.
    let b = mesurer(
        Box::new(|x, y, z| {
            if plaque(0.0, 0.1, 6.0)(x, y, z) {
                Some("leaves")
            } else {
                (x.abs() < 2.0 && y > 2.0 && y < 9.0 && z > 0.6 && z < 1.2).then_some("granite")
            }
        }),
        -8.0,
    );
    eprintln!(
        "B (solide devant le soleil) : {:?}, épaisseur {}",
        b.delta, b.epaisseur
    );
    assert!(b.epaisseur > 500.0, "code « soleil barré » : {}", b.epaisseur);
    assert!(
        somme(b.delta).abs() < 1e-4,
        "occulté : rien ne passe, GPU {:?}",
        b.delta
    );

    // C : une seconde plaque de feuilles à 3 m (au-delà de la zone de 2,4 m) : son ombre (cascades de L11) éteint la
    // transmission de la première.
    let c = mesurer(
        Box::new(|x, y, z| {
            (plaque(0.0, 0.1, 6.0)(x, y, z) || plaque(3.0, 3.1, 12.0)(x, y, z)).then_some("leaves")
        }),
        -8.0,
    );
    eprintln!("C (ombre d'une autre feuille) : {:?}", c.delta);
    assert!(
        somme(c.delta).abs() < 0.01 * somme(a.delta),
        "à l'ombre d'une autre feuille : GPU {:?} contre {:?} au soleil",
        c.delta,
        a.delta
    );

    // D : une seconde plaque à 50 cm (dans la zone, avec de l'air entre les deux) : l'épaisseur double, la lumière baisse
    // mais reste celle du calcul CPU.
    let d = mesurer(
        Box::new(|x, y, z| {
            (plaque(0.0, 0.1, 6.0)(x, y, z) || plaque(0.5, 0.6, 12.0)(x, y, z)).then_some("leaves")
        }),
        -8.0,
    );
    eprintln!("D (deux plaques) : {:?}, épaisseur {}", d.delta, d.epaisseur);
    // Le DDA exact compte 0,08 m dans la première plaque ; la seconde, à 11 voxels, est échantillonnée tous les 1,5
    // voxel : 1 ou 2 échantillons de 7,5 cm.
    assert!(
        (0.12..0.26).contains(&d.epaisseur),
        "épaisseur de deux plaques : {}",
        d.epaisseur
    );
    assert!(somme(d.delta) < 0.95 * somme(a.delta) && somme(d.delta) > 0.0);
    for k in 0..3 {
        assert!(
            (d.delta[k] - d.attendu[k]).abs() < 0.06 * d.attendu[k] + 2e-3,
            "canal {k} : GPU {} / CPU {}",
            d.delta[k],
            d.attendu[k]
        );
    }

    // E : on regarde la face qui regarde le soleil (caméra du côté de +z) : l'éclairage direct joue, pas la transmission.
    let e = mesurer(
        Box::new(|x, y, z| plaque(0.0, 0.1, 6.0)(x, y, z).then_some("leaves")),
        8.0,
    );
    eprintln!("E (face au soleil) : {:?}", e.delta);
    assert!(
        somme(e.delta).abs() < 1e-4,
        "face au soleil : pas de transmission, GPU {:?}",
        e.delta
    );
}
