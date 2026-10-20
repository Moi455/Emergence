//! Assemblage des shaders du rendu voxel : morceaux de WGSL (`shaders/voxel/`), fragment de matière
//! (`em_material::MATERIAL_WGSL`) et modules du ciel (`sky::shaders`). Un test les passe tous à `naga`.

use crate::sky::shaders::{self as ciel, ModuleWgsl};
use em_material::MATERIAL_WGSL;

const FRAME: &str = include_str!("../../shaders/voxel/voxel_frame.wgsl");
const MONDE: &str = include_str!("../../shaders/voxel/voxel_world.wgsl");
const TRACE: &str = include_str!("../../shaders/voxel/voxel_trace.wgsl");
const MATIERE: &str = include_str!("../../shaders/voxel/voxel_material.wgsl");
const PROFONDEUR: &str = include_str!("../../shaders/voxel/voxel_depth.wgsl");
const LUMIERE: &str = include_str!("../../shaders/voxel/voxel_light.wgsl");
const EPAISSEUR: &str = include_str!("../../shaders/voxel/voxel_foliage_thickness.wgsl");
const OCCLUSION: &str = include_str!("../../shaders/voxel/voxel_ao.wgsl");
const OCCLUSION_FILTRE: &str = include_str!("../../shaders/voxel/voxel_ao_filter.wgsl");
const OMBRES_REMPLISSAGE: &str = include_str!("../../shaders/voxel/voxel_shadow_fill.wgsl");
const OMBRES_ECHANTILLON: &str = include_str!("../../shaders/voxel/voxel_shadow_sample.wgsl");
const AERIAL: &str = include_str!("../../shaders/sky/aerial.wgsl");

fn assemble(nom: &'static str, morceaux: &[&str]) -> ModuleWgsl {
    ModuleWgsl::assemble(nom, morceaux.join("\n"))
}

/// Tracé primaire : uniforme d'image, monde, DDA hiérarchique, point d'entrée.
pub fn trace() -> ModuleWgsl {
    assemble("voxel_trace", &[FRAME, MONDE, TRACE])
}

/// Passe de matière : uniforme d'image, matières de `em_material`, évaluation, écriture du G-buffer.
pub fn matiere() -> ModuleWgsl {
    assemble("voxel_material", &[FRAME, MATERIAL_WGSL, MATIERE])
}

/// Épaisseur de feuillage le long du soleil : struct `Frame` du ciel (soleil), uniforme d'image, monde, matières.
pub fn epaisseur() -> ModuleWgsl {
    assemble(
        "voxel_foliage_thickness",
        &[ciel::FRAME, FRAME, MONDE, MATERIAL_WGSL, EPAISSEUR],
    )
}

/// Occlusion ambiante tracée : uniforme d'image, monde, DDA partagé, point d'entrée.
pub fn occlusion() -> ModuleWgsl {
    assemble("voxel_ao", &[FRAME, MONDE, OCCLUSION])
}

/// Filtre bilatéral de l'occlusion ambiante.
pub fn occlusion_filtre() -> ModuleWgsl {
    assemble("voxel_ao_filter", &[FRAME, OCCLUSION_FILTRE])
}

/// Fusion des profondeurs.
pub fn profondeur() -> ModuleWgsl {
    assemble("voxel_depth", &[FRAME, PROFONDEUR])
}

/// Éclairage différé : ciel de Hillaire (struct `Frame`, atmosphère, fonctions du ciel, perspective aérienne) puis éclairage.
pub fn lumiere() -> ModuleWgsl {
    let base = ciel::base_pour_eclairage();
    assemble(
        "voxel_light",
        &[&base, AERIAL, FRAME, OMBRES_ECHANTILLON, LUMIERE],
    )
}

/// Remplissage des cascades d'ombre : uniforme d'image (constantes), monde, DDA partagé, point d'entrée.
pub fn ombres_remplissage() -> ModuleWgsl {
    assemble("voxel_shadow_fill", &[FRAME, MONDE, OMBRES_REMPLISSAGE])
}

/// Tous les modules du rendu voxel (le test `shaders_voxel_validate` les passe à `naga`).
pub fn tous() -> Vec<ModuleWgsl> {
    vec![
        trace(),
        matiere(),
        epaisseur(),
        profondeur(),
        lumiere(),
        ombres_remplissage(),
        occlusion(),
        occlusion_filtre(),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Chaque shader du rendu voxel passe l'analyse et la validation de `naga`.
    #[test]
    fn shaders_voxel_validate() {
        for m in tous() {
            let module = naga::front::wgsl::parse_str(m.source())
                .unwrap_or_else(|e| panic!("{} : analyse WGSL : {}", m.nom(), e.emit_to_string(m.source())));
            naga::valid::Validator::new(
                naga::valid::ValidationFlags::all(),
                naga::valid::Capabilities::all(),
            )
            .validate(&module)
            .unwrap_or_else(|e| panic!("{} : validation : {e:?}", m.nom()));
        }
    }

    /// Les fréquences du shader sont celles du CPU (`Q16::from_ratio`/`from_int`).
    #[test]
    fn les_frequences_du_shader_egalent_celles_du_cpu() {
        use em_core::Q16;
        let attendu: [(&str, i64); 14] = [
            ("FQ_0_2", Q16::from_ratio(1, 5).raw()),
            ("FQ_0_3", Q16::from_ratio(3, 10).raw()),
            ("FQ_0_5", Q16::from_ratio(1, 2).raw()),
            ("FQ_0_55", Q16::from_ratio(55, 100).raw()),
            ("FQ_0_7", Q16::from_ratio(7, 10).raw()),
            ("FQ_1_0", Q16::ONE.raw()),
            ("FQ_1_3", Q16::from_ratio(13, 10).raw()),
            ("FQ_2_0", Q16::from_int(2).raw()),
            ("FQ_4_0", Q16::from_int(4).raw()),
            ("FQ_5_0", Q16::from_int(5).raw()),
            ("FQ_6_0", Q16::from_int(6).raw()),
            ("FQ_8_0", Q16::from_int(8).raw()),
            ("FQ_9_0", Q16::from_int(9).raw()),
            ("FQ_12_0", Q16::from_int(12).raw()),
        ];
        for (nom, valeur) in attendu {
            let ligne = format!("const {nom}: u32 = {valeur}u;");
            assert!(
                MATERIAL_WGSL.contains(&ligne),
                "{ligne} absent du WGSL de matière"
            );
        }
    }
}
