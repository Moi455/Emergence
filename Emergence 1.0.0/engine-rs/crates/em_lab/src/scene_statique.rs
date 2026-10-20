//! Scène statique du labo lue dans `lab/scenes/<nom>.toml` (docs/19a § 6.4) : un sol plat de turf et des modèles
//! `.vxm` posés. Donne à L09 sa source de voxels (`StaticScene`). Ce module est le seul à manipuler des
//! flottants (mètres) : ils sont convertis en voxels entiers ici, la crate de vérité `em_gen` n'en voit pas.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{Context, bail};
use em_core::{VOXEL_MM, VoxelCoord, hash_combine};
use em_gen::{BuildingClasses, GenParams, GeneratorRegistry, PlacedModel, PlacedPlan, StaticScene, VxmModel};
use em_material::StyleConfig;
use serde::Deserialize;

/// Un modèle de la scène (section `[[model]]`).
#[derive(Debug, Deserialize)]
pub struct ModelConfig {
    /// Chemin du `.vxm`, relatif à `engine-rs/`.
    pub path: String,
    /// Position du pied du tronc par rapport à l'origine de la scène, en mètres (multiple de 5 cm).
    pub at_m: [f64; 3],
    /// Quarts de tour, de l'est vers le nord.
    #[serde(default)]
    pub quarter_turns: u8,
    /// Case d'essence de la teinte (0..=31).
    #[serde(default)]
    pub species_slot: u8,
}

/// Une recette de générateur posée dans la scène (section `[[recipe]]`, L23p) : le générateur est désigné par son nom
/// dans le registre, les paramètres sont ceux de sa configuration (`[recipe.params]`).
#[derive(Debug, Deserialize)]
pub struct RecipeConfig {
    /// Nom du générateur (`stone_wall`, `beam`, `post`, `roof`).
    pub generator: String,
    /// Graine de la recette.
    #[serde(default)]
    pub seed: u64,
    /// Position de l'origine locale du plan par rapport à l'origine de la scène, en mètres (multiple de 5 cm).
    pub at_m: [f64; 3],
    /// Paramètres du générateur (champs de sa configuration ; absents = valeurs par défaut).
    #[serde(default)]
    pub params: toml::Table,
}

/// Contenu d'une scène (les sections `[[shot]]` appartiennent à l'hôte de captures et sont ignorées ici).
#[derive(Debug, Deserialize)]
pub struct SceneConfig {
    /// Nom de la scène.
    pub name: String,
    /// Coin de la scène dans le monde, en mètres (multiple de 5 cm).
    pub origin_m: [f64; 3],
    /// Paysage : `flat_turf` (seul pris en charge par L08).
    pub landscape: String,
    /// Modèles posés.
    #[serde(default)]
    pub model: Vec<ModelConfig>,
    /// Recettes de générateur posées (L23p).
    #[serde(default)]
    pub recipe: Vec<RecipeConfig>,
    /// Choix du mode de matière par classe (L23p).
    #[serde(default)]
    pub style: StyleConfig,
}

/// Une scène chargée : sa description et sa source de voxels.
pub struct SceneStatique {
    nom: String,
    scene: StaticScene,
    style: StyleConfig,
    recettes: Vec<String>,
}

impl SceneStatique {
    /// Charge `lab/scenes/<nom>.toml` ; `racine` est `engine-rs/`.
    pub fn charger(fichier: &Path, racine: &Path) -> anyhow::Result<Self> {
        Self::charger_avec(fichier, racine, BuildingClasses::standard())
    }

    /// Comme `charger`, avec les classes de matière des recettes (celles de la vraie table des matières).
    pub fn charger_avec(fichier: &Path, racine: &Path, classes: BuildingClasses) -> anyhow::Result<Self> {
        let texte =
            std::fs::read_to_string(fichier).with_context(|| format!("lecture de {}", fichier.display()))?;
        Self::depuis_texte_avec(&texte, racine, classes)
            .with_context(|| format!("scène {}", fichier.display()))
    }

    /// Construit la scène depuis le texte TOML (classes standard) ; sert aux essais.
    #[cfg(test)]
    pub fn depuis_texte(texte: &str, racine: &Path) -> anyhow::Result<Self> {
        Self::depuis_texte_avec(texte, racine, BuildingClasses::standard())
    }

    /// Construit la scène depuis le texte TOML avec les classes de matière des recettes.
    pub fn depuis_texte_avec(texte: &str, racine: &Path, classes: BuildingClasses) -> anyhow::Result<Self> {
        let cfg: SceneConfig = toml::from_str(texte).context("TOML de scène invalide")?;
        if cfg.landscape != "flat_turf" {
            bail!(
                "paysage « {} » non pris en charge (seul flat_turf l'est)",
                cfg.landscape
            );
        }
        let origine = voxels(cfg.origin_m, "origin_m")?;
        let mut builder = StaticScene::builder().turf_ground(origine.y);
        for m in &cfg.model {
            let chemin = resoudre(&m.path, racine);
            let modele = Arc::new(VxmModel::load(&chemin)?);
            for avert in modele.warnings() {
                log::warn!("{} : {avert}", chemin.display());
            }
            let at = voxels(m.at_m, "at_m")?;
            let pivot = VoxelCoord::new(origine.x + at.x, origine.y + at.y, origine.z + at.z);
            builder = builder.place(PlacedModel::new(modele, pivot, m.quarter_turns, m.species_slot)?);
        }
        // recettes : le générateur est choisi par son nom dans le registre ; le plan est posé comme une source
        let registre = GeneratorRegistry::bati(classes);
        let mut recettes = Vec::new();
        for r in &cfg.recipe {
            let generateur = registre.get(&r.generator)?;
            let octets = serde_json::to_vec(&serde_json::to_value(&r.params)?)?;
            let params = GenParams::new(generateur.id(), generateur.version(), octets.clone());
            let plan = generateur
                .plan(&params, r.seed)
                .with_context(|| format!("recette « {} » (graine {})", r.generator, r.seed))?;
            let at = voxels(r.at_m, "recipe.at_m")?;
            let pivot = VoxelCoord::new(origine.x + at.x, origine.y + at.y, origine.z + at.z);
            let mut tag = hash_combine(u64::from(generateur.id().raw()), u64::from(generateur.version()));
            tag = hash_combine(tag, r.seed);
            for o in octets {
                tag = hash_combine(tag, u64::from(o));
            }
            recettes.push(format!("{}#{}", r.generator, r.seed));
            builder = builder.place_plan(PlacedPlan::new(plan, pivot, tag));
        }
        Ok(Self {
            nom: cfg.name,
            scene: builder.build()?,
            style: cfg.style,
            recettes,
        })
    }

    /// Choix de style (classes pouvant passer en mode voxel) de la scène.
    pub fn style(&self) -> &StyleConfig {
        &self.style
    }

    /// Recettes posées, `nom#graine`, dans l'ordre de pose.
    pub fn recettes(&self) -> &[String] {
        &self.recettes
    }

    /// Nom de la scène.
    pub fn nom(&self) -> &str {
        &self.nom
    }

    /// La source de voxels de la scène.
    pub fn scene(&self) -> &StaticScene {
        &self.scene
    }
}

/// Mètres -> voxels de 5 cm ; refuse une position qui n'est pas un multiple du voxel.
fn voxels(m: [f64; 3], champ: &str) -> anyhow::Result<VoxelCoord> {
    let par_voxel = 1000.0 / VOXEL_MM as f64;
    let mut v = [0_i32; 3];
    for (i, x) in m.iter().enumerate() {
        let n = x * par_voxel;
        if (n - n.round()).abs() > 1e-6 || n.abs() > 1e7 {
            bail!("{champ}[{i}] = {x} m n'est pas un multiple de 5 cm");
        }
        v[i] = n.round() as i32;
    }
    Ok(VoxelCoord::new(v[0], v[1], v[2]))
}

/// Chemin d'un modèle : relatif à `engine-rs/` ; à défaut, le dossier d'assets des arbres de référence
/// (`$EM_LAB_ASSETS/trees` ou `~/.local/share/emergence/lab_assets/trees`, L04).
fn resoudre(chemin: &str, racine: &Path) -> PathBuf {
    let direct = racine.join(chemin);
    if direct.is_file() {
        return direct;
    }
    let assets = std::env::var_os("EM_LAB_ASSETS")
        .filter(|d| !d.is_empty())
        .map_or_else(
            || {
                PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
                    .join(".local/share/emergence/lab_assets")
            },
            PathBuf::from,
        );
    match Path::new(chemin).file_name() {
        Some(nom) => assets.join("trees").join(nom),
        None => direct,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use em_core::{ChunkKey, MaterialId};
    use em_voxel::{Chunk, VoxelSource};

    const ARBRE: &str = r#"
name = "arbre"
origin_m = [10000.0, 0.0, 10000.0]
landscape = "flat_turf"
[[model]]
path = "lab/models/chene_42.vxm"
at_m = [0.0, 0.0, 0.0]
quarter_turns = 0
[[shot]]
name = "face"
pos_m = [12.0, 1.7, -8.0]
"#;

    fn racine() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
    }

    #[test]
    fn metres_en_voxels() {
        assert_eq!(
            voxels([10_000.0, 0.0, -1.25], "t").unwrap(),
            VoxelCoord::new(200_000, 0, -25)
        );
        assert!(voxels([0.03, 0.0, 0.0], "t").is_err());
    }

    #[test]
    fn paysage_inconnu_refuse() {
        let t = ARBRE.replace("flat_turf", "lab_landscape");
        assert!(SceneStatique::depuis_texte(&t, &racine()).is_err());
    }

    #[test]
    fn scene_arbre_du_toml() {
        let assets_ok = resoudre("lab/models/chene_42.vxm", &racine()).is_file();
        if !assets_ok {
            eprintln!("IGNORÉ : chene_42.vxm absent (assets de référence de L04 non générés)");
            return;
        }
        let s = SceneStatique::depuis_texte(ARBRE, &racine()).unwrap();
        assert_eq!(s.nom(), "arbre");
        let scene = s.scene();
        let pivot = scene.models().next().unwrap().pivot();
        assert_eq!(pivot, VoxelCoord::new(200_000, 0, 200_000));
        let mut chunk = Chunk::new_air();
        scene.fill_chunk(pivot.chunk(), 0, &mut chunk);
        assert!(chunk.non_air_count() > 0);
        scene.fill_chunk(ChunkKey::new(pivot.chunk().x, -1, pivot.chunk().z), 0, &mut chunk);
        assert_eq!(chunk.get(0, 63, 0).material(), MaterialId::new(1));
    }
}
