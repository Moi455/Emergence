//! Assemblage des shaders du ciel : modules de `web-ocean` (extraits par `scripts/extract_web_ocean.py`,
//! jamais édités à la main) + fichiers du moteur (`shaders/sky/`). Le marqueur `//@FRAME_WGSL` laissé par
//! l'extraction est remplacé par la struct `Frame` réécrite pour le moteur.

/// Struct `Frame` du moteur.
pub const FRAME: &str = include_str!("../../shaders/sky/frame.wgsl");

const MARQUEUR_FRAME: &str = "//@FRAME_WGSL";

macro_rules! web_ocean {
    ($nom:literal) => {
        include_str!(concat!("../../shaders/third_party/web-ocean/", $nom))
    };
}

const ATMO_CORE: &str = web_ocean!("atmo_core.wgsl");
const SKY_RENDER_FUNCS: &str = web_ocean!("sky_render_funcs.wgsl");
const SKY_CLOUD_FUNCS: &str = web_ocean!("sky_cloud_funcs.wgsl");
const BINDINGS_FOND: &str = include_str!("../../shaders/sky/bindings_fond.wgsl");
const AERIAL: &str = include_str!("../../shaders/sky/aerial.wgsl");
const CRETES: &str = include_str!("../../shaders/sky/cretes.wgsl");
const CRETE_LUT: &str = include_str!("../../shaders/sky/crete_lut.wgsl");
const NOISE: &str = web_ocean!("noise.wgsl");
const FOND: &str = include_str!("../../shaders/sky/fond.wgsl");

/// Un module WGSL assemblé, nommé (pour les messages d'erreur et le test de validation).
pub struct ModuleWgsl {
    nom: &'static str,
    source: String,
}

impl ModuleWgsl {
    fn depuis(nom: &'static str, source: &str) -> Self {
        Self {
            nom,
            source: source.replace(MARQUEUR_FRAME, FRAME),
        }
    }

    /// Module assemblé ailleurs (le rendu voxel assemble ses propres morceaux de WGSL).
    pub(crate) fn assemble(nom: &'static str, source: String) -> Self {
        Self { nom, source }
    }

    /// Nom du module.
    pub fn nom(&self) -> &'static str {
        self.nom
    }

    /// Texte WGSL complet.
    pub fn source(&self) -> &str {
        &self.source
    }
}

/// Transmittance de l'atmosphère (256 x 64).
pub fn transmittance() -> ModuleWgsl {
    ModuleWgsl::depuis("trans_lut", web_ocean!("trans_lut.wgsl"))
}

/// Diffusion multiple (32 x 32).
pub fn diffusion_multiple() -> ModuleWgsl {
    ModuleWgsl::depuis("ms_lut", web_ocean!("ms_lut.wgsl"))
}

/// LUT de vue du ciel (256 x 144).
pub fn vue_du_ciel() -> ModuleWgsl {
    ModuleWgsl::depuis("skyview_lut", web_ocean!("skyview_lut.wgsl"))
}

/// Fond de ciel : Hillaire + nuages + soleil + sol, crêtes, étoiles, perspective aérienne.
pub fn fond_de_ciel() -> ModuleWgsl {
    let source = [
        FRAME,
        ATMO_CORE,
        BINDINGS_FOND,
        SKY_RENDER_FUNCS,
        SKY_CLOUD_FUNCS,
        AERIAL,
        FOND,
    ]
    .join("\n");
    ModuleWgsl::depuis("fond_de_ciel", &source)
}

/// Base du ciel pour un éclairage différé (L09) : struct `Frame`, atmosphère, fonctions de rendu du ciel
/// (`skyAtmo`, `sunIlluminance`, `planetShadow`). Sans liaisons (l'appelant déclare `F`, `transLUT`, `skyLUT`,
/// `sampC`), sans nuages ni fond. Le marqueur `Frame` est déjà résolu.
pub fn base_pour_eclairage() -> String {
    [FRAME, ATMO_CORE, SKY_RENDER_FUNCS]
        .join("\n")
        .replace(MARQUEUR_FRAME, FRAME)
}

/// LUT 1D des crêtes lointaines (calcul unique).
pub fn cretes() -> ModuleWgsl {
    ModuleWgsl::depuis("crete_lut", &[NOISE, CRETES, CRETE_LUT].join("\n"))
}

/// Descente du bloom (filtre double de Karis).
pub fn bloom_descente() -> ModuleWgsl {
    ModuleWgsl::depuis("bloom_down", web_ocean!("bloom_down.wgsl"))
}

/// Remontée du bloom.
pub fn bloom_remontee() -> ModuleWgsl {
    ModuleWgsl::depuis("bloom_up", web_ocean!("bloom_up.wgsl"))
}

/// Composition AgX + vignette + tramage.
pub fn composition() -> ModuleWgsl {
    ModuleWgsl::depuis("composite", web_ocean!("composite.wgsl"))
}

/// Tous les modules (le test `shaders_validate` les passe à `naga`). Les modules `env_cube`, `cube_mips` et
/// `sun_vis` sont extraits pour L21 (eau) mais pas encore branchés : ils sont validés quand même.
pub fn tous() -> Vec<ModuleWgsl> {
    vec![
        transmittance(),
        diffusion_multiple(),
        vue_du_ciel(),
        fond_de_ciel(),
        cretes(),
        bloom_descente(),
        bloom_remontee(),
        composition(),
        ModuleWgsl::depuis("env_cube", web_ocean!("env_cube.wgsl")),
        ModuleWgsl::depuis("cube_mips", web_ocean!("cube_mips.wgsl")),
        ModuleWgsl::depuis("sun_vis", web_ocean!("sun_vis.wgsl")),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Chaque shader extrait ou écrit pour le ciel passe l'analyse et la validation de `naga`.
    #[test]
    fn shaders_validate() {
        for m in tous() {
            assert!(
                !m.source().contains(MARQUEUR_FRAME),
                "{} : marqueur Frame resté",
                m.nom()
            );
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
}
