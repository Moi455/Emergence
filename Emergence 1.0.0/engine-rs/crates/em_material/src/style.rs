//! Mode de matière PAR CLASSE (L23p) : `Continuous` (champ continu en coordonnées monde, docs/19 § 4.6) ou
//! `VoxelPixel` (la texture est la variation de couleur entre voxels, `pixel.rs`). Le choix est une configuration
//! validée à la construction d'une `StyleSheet`, jamais une globale : l'évaluateur CPU et le paquet GPU la reçoivent.

use crate::error::MaterialError;
use crate::table::{CLASS_COUNT, MaterialTable};
use crate::tint::TintMode;
use em_core::digest::Fnv64;
use em_core::ids::MaterialId;
use em_core::q16::Q16;
use serde::Deserialize;
use std::collections::BTreeMap;

/// Mode de rendu de la matière d'une classe.
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MaterialMode {
    /// Matière continue en coordonnées monde (le rendu de L09 : bruit continu au centre du voxel).
    #[default]
    Continuous = 0,
    /// Variation de couleur voxel par voxel : numéro de pierre, colonne de fibre, tuile, gigue.
    VoxelPixel = 1,
}

impl MaterialMode {
    /// Code transmis au shader (`class_extra.w`).
    pub const fn code(self) -> u32 {
        self as u32
    }
    /// Nom en ligne de commande et dans les scènes (`continu`, `voxel`).
    pub const fn name(self) -> &'static str {
        match self {
            MaterialMode::Continuous => "continu",
            MaterialMode::VoxelPixel => "voxel",
        }
    }
    /// Lit un nom de mode.
    pub fn from_name(nom: &str) -> Option<MaterialMode> {
        [MaterialMode::Continuous, MaterialMode::VoxelPixel]
            .into_iter()
            .find(|m| m.name() == nom)
    }
}

/// Force de granulométrie par défaut (décision du 21 oct. 2026 : écarts plus tranchés entre voxels voisins, comme
/// `bon pierre.png`). 1,0 redonne les réglages d'origine de L23p.
pub const GRANULOMETRIE_DEFAUT: f64 = 1.6;
/// Plus grande force de granulométrie acceptée.
pub const GRANULOMETRIE_MAX: f64 = 3.0;

/// Réglages du mode `VoxelPixel` d'une classe (fractions Q16 de 0 à 1). Configuration validée par `validate`.
/// Chaque famille de teinte lit les champs qui la concernent et ignore les autres.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct PixelParams {
    /// Pierre : écart de ton entre blocs. Bois : contraste entre colonnes de fibre.
    pub block_spread: Q16,
    /// Pierre : écart chaud/froid entre blocs. Bois : chaleur propre à chaque fibre.
    pub hue_spread: Q16,
    /// Gigue par voxel (pierre : à l'intérieur d'un bloc ; partout : le grain pixel).
    pub voxel_jitter: Q16,
    /// Pierre : nuance du mortier (0 = très sombre). Bois : assombrissement d'un nœud.
    pub joint_tone: Q16,
    /// Bois : contraste des anneaux de croissance.
    pub ring_contrast: Q16,
    /// Bois : contraste des tronçons de fibre (rupture de ton tous les 8 voxels).
    pub run_contrast: Q16,
}

impl PixelParams {
    /// Réglages par défaut de la famille de teinte.
    pub fn default_for(mode: TintMode) -> Self {
        let q = |n: i64| Q16::from_ratio(n, 100);
        match mode {
            TintMode::StonePiece => PixelParams {
                block_spread: q(28),
                hue_spread: q(8),
                voxel_jitter: q(5),
                joint_tone: q(4),
                ring_contrast: Q16::ZERO,
                run_contrast: Q16::ZERO,
            },
            TintMode::WoodAxis => PixelParams {
                block_spread: q(17),
                hue_spread: q(5),
                voxel_jitter: q(5),
                joint_tone: q(25),
                ring_contrast: q(10),
                run_contrast: q(12),
            },
            TintMode::Ramp128 | TintMode::Terrain | TintMode::Vegetation => PixelParams {
                block_spread: Q16::ZERO,
                hue_spread: Q16::ZERO,
                voxel_jitter: q(6),
                joint_tone: Q16::ZERO,
                ring_contrast: Q16::ZERO,
                run_contrast: Q16::ZERO,
            },
        }
    }

    /// Réglages rendus plus FRANCS par une force de granulométrie (1 = inchangés) : les écarts entre pièces, entre
    /// fibres, entre anneaux et entre tronçons sont multipliés par la force ; la gigue par voxel (le grain pixel,
    /// ce qui sépare deux voxels voisins d'une même pièce) l'est davantage (`1 + 1,5 (force - 1)`), car c'est elle
    /// que l'oeil lit d'abord de près. Le mortier et les nuds (tons posés) restent tels quels. Tout est borné à 1.
    pub fn with_granulometry(self, force: Q16) -> Self {
        let borne = |v: i64| Q16::from_raw(v.clamp(0, 65_536));
        let f = force.raw();
        let mul = |q: Q16, m: i64| borne(q.raw() * m / 65_536);
        let jitter_m = 65_536 + 3 * (f - 65_536) / 2;
        PixelParams {
            block_spread: mul(self.block_spread, f),
            hue_spread: mul(self.hue_spread, f),
            voxel_jitter: mul(self.voxel_jitter, jitter_m),
            joint_tone: self.joint_tone,
            ring_contrast: mul(self.ring_contrast, f),
            run_contrast: mul(self.run_contrast, f),
        }
    }

    /// Les six champs sont des fractions de 0 à 1.
    pub fn validate(&self, classe: &str) -> Result<(), MaterialError> {
        for (champ, q) in [
            ("block_spread", self.block_spread),
            ("hue_spread", self.hue_spread),
            ("voxel_jitter", self.voxel_jitter),
            ("joint_tone", self.joint_tone),
            ("ring_contrast", self.ring_contrast),
            ("run_contrast", self.run_contrast),
        ] {
            if !(0..=65_536).contains(&q.raw()) {
                return Err(MaterialError::StyleValeur {
                    classe: classe.to_owned(),
                    champ,
                    raison: "hors de 0..=1".into(),
                });
            }
        }
        Ok(())
    }
}

/// Surcharge facultative des réglages d'une classe, telle qu'écrite dans le TOML d'une scène.
#[derive(Deserialize, Default, Clone, Debug, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PixelOverride {
    block_spread: Option<f64>,
    hue_spread: Option<f64>,
    voxel_jitter: Option<f64>,
    joint_tone: Option<f64>,
    ring_contrast: Option<f64>,
    run_contrast: Option<f64>,
}

/// Convertit un décimal du TOML en Q16 (seul point de la crate qui touche un flottant, comme `table.rs`).
#[allow(clippy::float_arithmetic)]
fn decimal_vers_q16(v: f64) -> Option<Q16> {
    v.is_finite()
        .then(|| Q16::from_raw((v * 65_536.0).round() as i64))
}

impl PixelOverride {
    /// Lit une surcharge depuis un fragment TOML (outils et tests).
    pub fn from_toml(texte: &str) -> Result<Self, MaterialError> {
        toml::from_str(texte).map_err(|e| MaterialError::Toml(e.to_string()))
    }

    fn appliquer(&self, base: PixelParams, classe: &str) -> Result<PixelParams, MaterialError> {
        let lire = |v: Option<f64>, defaut: Q16, champ: &'static str| match v {
            None => Ok(defaut),
            Some(x) => decimal_vers_q16(x).ok_or_else(|| MaterialError::StyleValeur {
                classe: classe.to_owned(),
                champ,
                raison: "nombre fini attendu".into(),
            }),
        };
        let p = PixelParams {
            block_spread: lire(self.block_spread, base.block_spread, "block_spread")?,
            hue_spread: lire(self.hue_spread, base.hue_spread, "hue_spread")?,
            voxel_jitter: lire(self.voxel_jitter, base.voxel_jitter, "voxel_jitter")?,
            joint_tone: lire(self.joint_tone, base.joint_tone, "joint_tone")?,
            ring_contrast: lire(self.ring_contrast, base.ring_contrast, "ring_contrast")?,
            run_contrast: lire(self.run_contrast, base.run_contrast, "run_contrast")?,
        };
        p.validate(classe)?;
        Ok(p)
    }
}

/// Choix de style d'une scène (section `[style]` du TOML) : quelles classes PEUVENT passer en `VoxelPixel`
/// et avec quels réglages. L'option de scène (`--mode`) décide si elles y passent.
#[derive(Deserialize, Default, Clone, Debug, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct StyleConfig {
    /// Noms des classes rendues en `VoxelPixel` quand le mode voxel est demandé.
    #[serde(default)]
    pub pixel_classes: Vec<String>,
    /// Surcharges des réglages, par nom de classe.
    #[serde(default)]
    pub params: BTreeMap<String, PixelOverride>,
    /// Force de granulométrie (0 à 3 ; défaut `GRANULOMETRIE_DEFAUT`) : amplitude de la variation de couleur entre
    /// voxels voisins, appliquée aux réglages par défaut de chaque famille AVANT les surcharges de `params`.
    #[serde(default)]
    pub granulometrie_force: Option<f64>,
}

/// Mode et réglages de chacune des 512 classes. Construite validée, lue par l'évaluateur CPU et téléversée au GPU.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StyleSheet {
    modes: Vec<MaterialMode>,
    params: Vec<PixelParams>,
    granulometry: Q16,
}

impl StyleSheet {
    /// Toutes les classes en mode continu (le comportement de L09).
    pub fn continuous() -> Self {
        StyleSheet {
            modes: vec![MaterialMode::Continuous; CLASS_COUNT],
            params: vec![PixelParams::default_for(TintMode::Ramp128); CLASS_COUNT],
            granulometry: Q16::ONE,
        }
    }

    /// Construit la feuille : avec `choix = Continuous`, tout reste continu ; avec `VoxelPixel`, les classes de
    /// `config.pixel_classes` passent en voxel. Refuse un nom inconnu, un doublon, une classe de végétation
    /// (déjà variée voxel par voxel) et une surcharge de réglage hors de 0 à 1.
    pub fn from_config(
        config: &StyleConfig,
        table: &MaterialTable,
        choix: MaterialMode,
    ) -> Result<Self, MaterialError> {
        let mut feuille = Self::continuous();
        let force = config.granulometrie_force.unwrap_or(GRANULOMETRIE_DEFAUT);
        let force_q16 = if force.is_finite() && (0.0..=GRANULOMETRIE_MAX).contains(&force) {
            decimal_vers_q16(force)
        } else {
            None
        }
        .ok_or_else(|| MaterialError::StyleValeur {
            classe: "(style)".to_owned(),
            champ: "granulometrie_force",
            raison: format!("{force} hors de 0..={GRANULOMETRIE_MAX}"),
        })?;
        feuille.granulometry = force_q16;
        let mut vus = std::collections::BTreeSet::new();
        for nom in &config.pixel_classes {
            let id = table
                .by_name(nom)
                .ok_or_else(|| MaterialError::StyleClasseInconnue(nom.clone()))?;
            if !vus.insert(id) {
                return Err(MaterialError::StyleDoublon(nom.clone()));
            }
            let mode_teinte = table.get(id).render().tint_mode();
            if mode_teinte == TintMode::Vegetation {
                return Err(MaterialError::StyleNonSupporte {
                    classe: nom.clone(),
                    raison: "la végétation est déjà variée voxel par voxel (rampes d'essence)".into(),
                });
            }
            let base = PixelParams::default_for(mode_teinte).with_granulometry(force_q16);
            let params = match config.params.get(nom) {
                Some(o) => o.appliquer(base, nom)?,
                None => base,
            };
            let i = usize::from(id.get());
            feuille.params[i] = params;
            if choix == MaterialMode::VoxelPixel {
                feuille.modes[i] = MaterialMode::VoxelPixel;
            }
        }
        if let Some(nom) = config.params.keys().find(|k| !config.pixel_classes.contains(k)) {
            return Err(MaterialError::StyleClasseInconnue(format!(
                "{nom} (réglages donnés à une classe absente de pixel_classes)"
            )));
        }
        Ok(feuille)
    }

    /// Mode d'une classe.
    pub fn mode_of(&self, classe: MaterialId) -> MaterialMode {
        self.modes
            .get(usize::from(classe.get()))
            .copied()
            .unwrap_or_default()
    }

    /// Réglages `VoxelPixel` d'une classe.
    pub fn params_of(&self, classe: MaterialId) -> &PixelParams {
        &self.params[usize::from(classe.get()).min(CLASS_COUNT - 1)]
    }

    /// Force de granulométrie appliquée aux réglages par défaut (1 pour une feuille toute continue).
    pub fn granulometry_force(&self) -> Q16 {
        self.granulometry
    }

    /// Nombre de classes en mode `VoxelPixel`.
    pub fn pixel_class_count(&self) -> usize {
        self.modes
            .iter()
            .filter(|m| **m == MaterialMode::VoxelPixel)
            .count()
    }

    /// Les 512 codes de mode (`class_extra.w` du GPU).
    pub fn gpu_modes(&self) -> Vec<u32> {
        self.modes.iter().map(|m| m.code()).collect()
    }

    /// Empreinte FNV-64 des modes et des réglages (à consigner dans le JSON des captures).
    pub fn fingerprint(&self) -> u64 {
        let mut h = Fnv64::new();
        for (m, p) in self.modes.iter().zip(&self.params) {
            h.add_u64(u64::from(m.code()));
            for q in [
                p.block_spread,
                p.hue_spread,
                p.voxel_jitter,
                p.joint_tone,
                p.ring_contrast,
                p.run_contrast,
            ] {
                h.add_u64(q.raw() as u64);
            }
        }
        h.value()
    }
}

impl Default for StyleSheet {
    fn default() -> Self {
        Self::continuous()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn table() -> MaterialTable {
        let d = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../engine/data");
        MaterialTable::load(&d.join("materials.csv"), &d.join("material_render.toml")).unwrap()
    }

    fn config(classes: &[&str]) -> StyleConfig {
        StyleConfig {
            pixel_classes: classes.iter().map(|s| (*s).to_owned()).collect(),
            params: BTreeMap::new(),
            granulometrie_force: None,
        }
    }

    #[test]
    fn le_mode_continu_ne_change_aucune_classe() {
        let f = StyleSheet::from_config(&config(&["cut_stone"]), &table(), MaterialMode::Continuous).unwrap();
        assert_eq!(f.pixel_class_count(), 0);
        assert_eq!(f.gpu_modes(), StyleSheet::continuous().gpu_modes());
    }

    #[test]
    fn le_mode_voxel_ne_touche_que_les_classes_listees() {
        let t = table();
        let f = StyleSheet::from_config(&config(&["cut_stone", "oak_raw"]), &t, MaterialMode::VoxelPixel)
            .unwrap();
        assert_eq!(f.pixel_class_count(), 2);
        assert_eq!(
            f.mode_of(t.by_name("cut_stone").unwrap()),
            MaterialMode::VoxelPixel
        );
        assert_eq!(f.mode_of(t.by_name("granite").unwrap()), MaterialMode::Continuous);
    }

    #[test]
    fn la_configuration_est_validee() {
        let t = table();
        assert!(matches!(
            StyleSheet::from_config(&config(&["nexiste_pas"]), &t, MaterialMode::VoxelPixel),
            Err(MaterialError::StyleClasseInconnue(_))
        ));
        assert!(matches!(
            StyleSheet::from_config(&config(&["cut_stone", "cut_stone"]), &t, MaterialMode::VoxelPixel),
            Err(MaterialError::StyleDoublon(_))
        ));
        assert!(matches!(
            StyleSheet::from_config(&config(&["leaves"]), &t, MaterialMode::VoxelPixel),
            Err(MaterialError::StyleNonSupporte { .. })
        ));
        let mut c = config(&["cut_stone"]);
        c.params.insert(
            "cut_stone".into(),
            PixelOverride {
                block_spread: Some(1.5),
                ..PixelOverride::default()
            },
        );
        assert!(matches!(
            StyleSheet::from_config(&c, &t, MaterialMode::VoxelPixel),
            Err(MaterialError::StyleValeur { .. })
        ));
    }

    #[test]
    fn la_granulometrie_renforcee_est_le_defaut_et_se_valide() {
        let t = table();
        let pierre = t.by_name("cut_stone").unwrap();
        let defaut = StyleSheet::from_config(&config(&["cut_stone"]), &t, MaterialMode::VoxelPixel).unwrap();
        let mut c1 = config(&["cut_stone"]);
        c1.granulometrie_force = Some(1.0);
        let origine = StyleSheet::from_config(&c1, &t, MaterialMode::VoxelPixel).unwrap();
        let (d, o) = (defaut.params_of(pierre), origine.params_of(pierre));
        assert_eq!(
            o.block_spread,
            Q16::from_ratio(28, 100),
            "force 1 = réglages d'origine"
        );
        assert!(d.block_spread > o.block_spread && d.voxel_jitter > o.voxel_jitter);
        assert!(
            d.voxel_jitter.raw() * 10 > o.voxel_jitter.raw() * 15,
            "la gigue gagne plus que les écarts"
        );
        assert_eq!(d.joint_tone, o.joint_tone, "le mortier ne bouge pas");
        assert_eq!(defaut.granulometry_force(), Q16::from_raw(104_858)); // 1,6 arrondi
        // les bornes : jamais au-delà de 1, force refusée hors de 0..=3 et non finie
        let mut fort = config(&["cut_stone"]);
        fort.granulometrie_force = Some(3.0);
        let f = StyleSheet::from_config(&fort, &t, MaterialMode::VoxelPixel).unwrap();
        assert!(f.params_of(pierre).block_spread.raw() <= 65_536);
        for mauvais in [-0.1, 3.1, f64::NAN, f64::INFINITY] {
            let mut c = config(&["cut_stone"]);
            c.granulometrie_force = Some(mauvais);
            assert!(matches!(
                StyleSheet::from_config(&c, &t, MaterialMode::VoxelPixel),
                Err(MaterialError::StyleValeur {
                    champ: "granulometrie_force",
                    ..
                })
            ));
        }
        // force nulle : plus aucun écart entre pièces ni entre voxels
        let mut zero = config(&["cut_stone"]);
        zero.granulometrie_force = Some(0.0);
        let z = StyleSheet::from_config(&zero, &t, MaterialMode::VoxelPixel).unwrap();
        assert_eq!(z.params_of(pierre).block_spread, Q16::ZERO);
        assert_eq!(z.params_of(pierre).voxel_jitter, Q16::ZERO);
    }

    #[test]
    fn les_noms_de_mode_font_l_aller_retour() {
        for m in [MaterialMode::Continuous, MaterialMode::VoxelPixel] {
            assert_eq!(MaterialMode::from_name(m.name()), Some(m));
        }
        assert_eq!(MaterialMode::from_name("autre"), None);
    }
}
