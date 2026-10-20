//! Essais du ciel sur un vrai GPU (L03). Sans adaptateur, ils s'ignorent avec un message :
//! `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json cargo test -p em_render`.

use em_render::sky::noms;
use em_render::{
    BloomPass, Camera, CloudParams, FrameContext, GpuContext, GpuProfiler, GpuRequest, OffscreenTarget,
    Partage, PostParams, RenderGraph, SkyBackgroundPass, SkyParams, SkyPass, SunModel, TonemapPass,
    read_texture,
};

const L: u32 = 256;
const H: u32 = 144;

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

fn graphe(ciel: Partage<SkyParams>) -> RenderGraph {
    let mut g = RenderGraph::new();
    g.add(Box::new(SkyPass::new(ciel))).unwrap();
    g.add(Box::new(SkyBackgroundPass::new())).unwrap();
    g.add(Box::new(BloomPass::new())).unwrap();
    g.add(Box::new(TonemapPass::new(Partage::new(PostParams::default()))))
        .unwrap();
    g
}

/// Lit la texture HDR (`Rgba16Float`) et renvoie les demi-flottants bruts.
fn lire_hdr(gpu: &GpuContext, g: &RenderGraph) -> Vec<u16> {
    let tex = g.resources().texture(noms::HDR).expect("texture hdr");
    let octets_ligne = L * 8;
    assert_eq!(octets_ligne % wgpu_alignement(), 0, "ligne alignée sur 256 o");
    let tampon = gpu.device().create_buffer(&em_render::wgpu::BufferDescriptor {
        label: Some("lecture hdr"),
        size: u64::from(octets_ligne * H),
        usage: em_render::wgpu::BufferUsages::COPY_DST | em_render::wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut enc = gpu
        .device()
        .create_command_encoder(&em_render::wgpu::CommandEncoderDescriptor { label: None });
    enc.copy_texture_to_buffer(
        tex.as_image_copy(),
        em_render::wgpu::TexelCopyBufferInfo {
            buffer: &tampon,
            layout: em_render::wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(octets_ligne),
                rows_per_image: Some(H),
            },
        },
        em_render::wgpu::Extent3d {
            width: L,
            height: H,
            depth_or_array_layers: 1,
        },
    );
    gpu.queue().submit([enc.finish()]);
    tampon
        .slice(..)
        .map_async(em_render::wgpu::MapMode::Read, |r| r.unwrap());
    gpu.attendre_fin();
    let vue = tampon.slice(..).get_mapped_range().unwrap();
    vue.as_chunks::<2>()
        .0
        .iter()
        .map(|b| u16::from_le_bytes(*b))
        .collect()
}

fn wgpu_alignement() -> u32 {
    em_render::wgpu::COPY_BYTES_PER_ROW_ALIGNMENT
}

/// Un demi-flottant est fini si son exposant n'est pas 31.
fn fini(h: u16) -> bool {
    (h & 0x7c00) != 0x7c00
}

fn rendre(gpu: &GpuContext, ciel: SkyParams, yaw: f32, pitch: f32) -> (Vec<u16>, Vec<u8>) {
    let partage = Partage::new(ciel);
    let mut g = graphe(partage);
    let mut cible = OffscreenTarget::new(gpu, L, H).unwrap();
    let mut profil = GpuProfiler::new(gpu, 32);
    let cam = Camera::new(em_render::glam::Vec3::new(0.0, 20.0, 0.0), yaw, pitch, 70.0).unwrap();
    for i in 0..4 {
        let f = FrameContext::new(i, 0.0, L, H, cam).unwrap();
        g.render(gpu, &f, &mut cible, &mut profil).unwrap();
    }
    profil.vider(gpu);
    let hdr = lire_hdr(gpu, &g);
    let png = read_texture(gpu, cible.texture()).unwrap().encoder_png().unwrap();
    (hdr, png)
}

#[test]
fn le_ciel_ne_produit_ni_nan_ni_infini_a_toutes_les_heures_et_dans_les_deux_sens() {
    let Some(gpu) = contexte() else { return };
    let modele = SunModel::new(46.0, 172).unwrap();
    // 6, 8, 12, 17,5, 19, 21 h, vers le soleil et à l'opposé, plus la nuit (3 h) et des nuages denses.
    for heure in [6.0_f32, 8.0, 12.0, 17.5, 19.0, 21.0, 3.0] {
        let (e, a) = modele.position(heure);
        let ciel = SkyParams::new(e, a, 3.0, 0.3)
            .unwrap()
            .with_clouds(CloudParams::new(1.5, 0.7, 3.0, 12.0, 0.6).unwrap());
        for lacet_deg in [-a, 180.0 - a] {
            let (hdr, _) = rendre(&gpu, ciel, lacet_deg.to_radians(), 0.1);
            assert!(
                hdr.iter().all(|&h| fini(h)),
                "valeur non finie dans le HDR à {heure} h (lacet {lacet_deg})"
            );
            assert!(
                hdr.as_chunks::<4>()
                    .0
                    .iter()
                    .any(|p| p[0] != 0 || p[1] != 0 || p[2] != 0),
                "image HDR vide à {heure} h"
            );
        }
    }
}

#[test]
fn deux_rendus_du_ciel_sont_identiques_octet_pour_octet() {
    let Some(gpu) = contexte() else { return };
    let ciel = SkyParams::new(4.0, 250.0, 3.0, 0.3).unwrap();
    let (h1, p1) = rendre(&gpu, ciel, -4.36, 0.2);
    let (h2, p2) = rendre(&gpu, ciel, -4.36, 0.2);
    assert_eq!(h1, h2, "HDR non reproductible");
    assert_eq!(p1, p2, "PNG non reproductible");
}

#[test]
fn les_lut_ne_sont_recalculees_que_si_le_soleil_ou_les_parametres_changent() {
    let Some(gpu) = contexte() else { return };
    let partage = Partage::new(SkyParams::new(10.0, 90.0, 3.0, 0.3).unwrap());
    let mut g = graphe(partage.clone());
    let mut cible = OffscreenTarget::new(&gpu, L, H).unwrap();
    let mut profil = GpuProfiler::new(&gpu, 32);
    let cam = Camera::default();
    let mut dessiner = |g: &mut RenderGraph, profil: &mut GpuProfiler, i: u64| {
        let f = FrameContext::new(i, 0.0, L, H, cam).unwrap();
        g.render(&gpu, &f, &mut cible, profil).unwrap();
    };
    for i in 0..6 {
        dessiner(&mut g, &mut profil, i);
    }
    profil.vider(&gpu);
    let n_lut = |p: &GpuProfiler| {
        p.report()
            .passes
            .iter()
            .find(|t| t.name == "ciel_lut")
            .map_or(0, |t| t.n)
    };
    assert_eq!(
        n_lut(&profil),
        1,
        "6 images sans changement : un seul calcul des LUT"
    );
    partage.remplacer(SkyParams::new(10.5, 90.0, 3.0, 0.3).unwrap());
    for i in 6..12 {
        dessiner(&mut g, &mut profil, i);
    }
    profil.vider(&gpu);
    assert_eq!(n_lut(&profil), 2, "un changement de soleil : un recalcul de plus");
}
