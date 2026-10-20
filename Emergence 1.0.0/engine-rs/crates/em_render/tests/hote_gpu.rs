//! Essais de l'hôte sur un vrai GPU. Sans adaptateur (CI, pilote non désigné), ils s'ignorent avec un message :
//! pour les exécuter sur la Quadro, passer par `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json cargo test`.

use em_render::hello::{OverlayText, SkyGradientPass, TextOverlayPass};
use em_render::{
    Camera, DeviceRequirements, FrameContext, GpuContext, GpuError, GpuProfiler, GpuRequest, OffscreenTarget,
    RenderGraph, read_texture,
};

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

fn rendre(gpu: &GpuContext, frames: u64) -> (Vec<u8>, GpuProfiler) {
    let mut graphe = RenderGraph::new();
    graphe.add(Box::new(SkyGradientPass::new())).unwrap();
    graphe
        .add(Box::new(TextOverlayPass::new(OverlayText::new(), 16, 2, 1)))
        .unwrap();
    let mut cible = OffscreenTarget::new(gpu, 256, 144).unwrap();
    let mut profil = GpuProfiler::new(gpu, 8);
    for i in 0..frames {
        let f = FrameContext::new(i, 0.0, 256, 144, Camera::default()).unwrap();
        graphe.render(gpu, &f, &mut cible, &mut profil).unwrap();
    }
    profil.vider(gpu);
    (
        read_texture(gpu, cible.texture()).unwrap().encoder_png().unwrap(),
        profil,
    )
}

#[test]
fn deux_rendus_donnent_le_meme_png_et_le_profil_compte_chaque_image() {
    let Some(gpu) = contexte() else { return };
    let (a, profil) = rendre(&gpu, 12);
    let (b, _) = rendre(&gpu, 12);
    assert_eq!(a, b, "PNG non reproductibles");
    let r = profil.report();
    assert_eq!(r.passes.len(), 2);
    assert!(
        r.passes
            .iter()
            .all(|p| p.n == 12 && p.median_ms >= 0.0 && p.p95_ms >= p.median_ms)
    );
}

#[test]
fn une_limite_impossible_est_refusee_clairement() {
    let Some(_) = contexte() else { return };
    let mut ex = DeviceRequirements::laboratoire();
    ex.storage_buffers_per_stage = u32::MAX;
    let req = GpuRequest {
        adapter_hint: "Quadro".into(),
        allow_any_adapter: true,
        validation: false,
    };
    match GpuContext::with_requirements(&req, &ex) {
        Err(GpuError::LimitesInsuffisantes { details, .. }) => {
            assert!(details.contains("tampons de stockage par étage"))
        }
        Err(e) => panic!("mauvaise erreur : {e}"),
        Ok(_) => panic!("la limite impossible aurait dû être refusée"),
    }
}

#[test]
fn un_nom_de_passe_en_double_est_refuse() {
    let mut graphe = RenderGraph::new();
    graphe.add(Box::new(SkyGradientPass::new())).unwrap();
    assert!(graphe.add(Box::new(SkyGradientPass::new())).is_err());
    assert!(graphe.set_enabled("ciel_degrade", false));
    assert!(!graphe.set_enabled("inconnue", true));
}
