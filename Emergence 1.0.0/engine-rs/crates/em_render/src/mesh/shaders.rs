//! Assemblage des shaders du rendu par maillage (`shaders/mesh/`), avec le ciel de Hillaire et l'échantillonnage des
//! ombres de L11. Un test les passe tous à `naga`.

use crate::sky::shaders::{self as ciel, ModuleWgsl};

const QUAD: &str = include_str!("../../shaders/mesh/mesh_quad.wgsl");
const OMBRE_REMPLISSAGE: &str = include_str!("../../shaders/mesh/mesh_shadow.wgsl");
const AIDES_CIEL: &str = include_str!("../../shaders/mesh/mesh_sky.wgsl");
const AMBIANCE: &str = include_str!("../../shaders/mesh/mesh_ambient.wgsl");
const PRINCIPAL: &str = include_str!("../../shaders/mesh/mesh_main.wgsl");
const OMBRES_ECHANTILLON: &str = include_str!("../../shaders/voxel/voxel_shadow_sample.wgsl");
const AERIAL: &str = include_str!("../../shaders/sky/aerial.wgsl");

/// Les deux textes de l'échantillonnage de L11 que la version raster remplace : la texture (distances `R32Float`
/// remplies en compute) devient une texture de PROFONDEUR (Z inversé) remplie en raster, lue par `textureLoad`.
const TEXTURE_COMPUTE: &str = "@group(2) @binding(1) var sh_tex: texture_2d_array<f32>;";
const TEXTURE_RASTER: &str = "@group(2) @binding(1) var sh_tex: texture_depth_2d_array;";
const LECTURE_COMPUTE: &str =
    "return textureLoad(sh_tex, clamp(ij, vec2<i32>(0), vec2<i32>(size - 1)), layer, 0).x;";
const LECTURE_RASTER: &str =
    "return (1.0 - textureLoad(sh_tex, clamp(ij, vec2<i32>(0), vec2<i32>(size - 1)), layer, 0)) * SU.cfg2.y;";

/// Portée de la profondeur des cascades raster, en mètres : la profondeur stockée est `1 - distance / PORTEE`, où la
/// distance part du plan de départ (jusqu'à `PLAN_M` + la moitié de la clipmap + le calage ≈ 130 m).
pub const PORTEE_OMBRES_M: f32 = 192.0;

/// L'échantillonnage de L11, dont la lecture des distances est celle de la texture de profondeur raster. Panique si
/// le texte d'origine a changé (le test `shaders_mesh_validate` le rattrape avant).
pub fn echantillon_ombres_raster() -> String {
    assert!(
        OMBRES_ECHANTILLON.contains(TEXTURE_COMPUTE) && OMBRES_ECHANTILLON.contains(LECTURE_COMPUTE),
        "voxel_shadow_sample.wgsl a changé : adapter mesh/shaders.rs"
    );
    OMBRES_ECHANTILLON
        .replace(TEXTURE_COMPUTE, TEXTURE_RASTER)
        .replace(LECTURE_COMPUTE, LECTURE_RASTER)
}

fn assemble(nom: &'static str, morceaux: &[&str]) -> ModuleWgsl {
    ModuleWgsl::assemble(nom, morceaux.join("\n"))
}

/// Éclairage du maillage : ciel, perspective aérienne, quads, aides, ombres raster, fragment.
pub fn principal() -> ModuleWgsl {
    let base = ciel::base_pour_eclairage();
    let ombres = echantillon_ombres_raster();
    assemble(
        "mesh_main",
        &[&base, AERIAL, QUAD, AIDES_CIEL, &ombres, PRINCIPAL],
    )
}

/// Remplissage d'une cascade d'ombre : quads et sommet d'ombre seulement.
pub fn ombres() -> ModuleWgsl {
    assemble("mesh_shadow", &[QUAD, OMBRE_REMPLISSAGE])
}

/// Texture d'ambiance du ciel (7 x 1) calculée une fois par image.
pub fn ambiance() -> ModuleWgsl {
    let base = ciel::base_pour_eclairage();
    assemble("mesh_ambient", &[&base, AIDES_CIEL, AMBIANCE])
}

/// Tous les modules du rendu par maillage.
pub fn tous() -> Vec<ModuleWgsl> {
    vec![principal(), ombres(), ambiance()]
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Chaque shader du maillage passe l'analyse et la validation de `naga`.
    #[test]
    fn shaders_mesh_validate() {
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

    /// La constante `BANDES` du WGSL range les bandes de `Quad::strip` : huit bits par (signe, diagonale).
    #[test]
    fn les_bandes_du_wgsl_sont_celles_du_mailleur() {
        use em_mesh::{Face, Quad, QuadSpec};
        let mut attendu = 0_u32;
        for (choix, (face, ao)) in [
            (Face::PosY, [3, 0, 3, 0]), // + diagonale 0-2
            (Face::PosY, [0, 3, 0, 3]), // + diagonale 1-3
            (Face::NegY, [3, 0, 3, 0]), // - diagonale 0-2
            (Face::NegY, [0, 3, 0, 3]), // - diagonale 1-3
        ]
        .into_iter()
        .enumerate()
        {
            let q = Quad::new(QuadSpec {
                origin: [0; 3],
                face,
                width: 1,
                height: 1,
                color: [0; 3],
                params: 0,
                ao,
                thickness: 0,
                foliage: false,
            })
            .unwrap();
            let octet = q
                .strip()
                .iter()
                .enumerate()
                .fold(0_u32, |a, (i, k)| a | u32::from(*k) << (2 * i));
            attendu |= octet << (8 * choix);
        }
        assert!(
            QUAD.contains(&format!("const BANDES: u32 = {attendu:#010X}u;")),
            "BANDES attendu : {attendu:#010X}"
        );
    }

    #[test]
    fn l_echantillon_raster_remplace_les_deux_lectures() {
        let s = echantillon_ombres_raster();
        assert!(s.contains("texture_depth_2d_array") && s.contains("SU.cfg2.y;"));
        assert!(!s.contains("texture_2d_array<f32>"));
    }
}
