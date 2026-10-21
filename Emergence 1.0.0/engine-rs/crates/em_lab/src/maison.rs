//! Les maisons de Monsieur dans le labo (L34) : chargement des `.vxh` cuits par `tools/maisons/cuire.sh`, métadonnées
//! (centre) et colorieur qui rend la COULEUR EXACTE du générateur (la teinte compte) pendant que la classe de
//! matière du voxel donne rugosité, relief et réflexion.

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Context;
use em_core::{Lod, VoxelCoord, VoxelValue};
use em_gen::{StaticScene, VxhModel};
use em_mesh::{VoxelAppearance, VoxelColorer};
use serde::Deserialize;

/// Métadonnées d'une maison cuite (le `.json` à côté du `.vxh`).
#[derive(Debug, Clone, Deserialize)]
pub struct MetaMaison {
    /// Centre de la maison dans la grille (x, z).
    pub center_xz: [f64; 2],
}

/// Dossier des maisons cuites : `$EM_LAB_ASSETS/maisons`, sinon `~/.local/share/emergence/lab_assets/maisons`.
pub fn dossier_maisons() -> PathBuf {
    let assets = std::env::var_os("EM_LAB_ASSETS")
        .filter(|d| !d.is_empty())
        .map_or_else(
            || {
                PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
                    .join(".local/share/emergence/lab_assets")
            },
            PathBuf::from,
        );
    assets.join("maisons")
}

/// Charge la maison de graine `graine` (`maison_<graine>.vxh` et `.json`).
pub fn charger(graine: &str) -> anyhow::Result<(Arc<VxhModel>, MetaMaison)> {
    anyhow::ensure!(
        !graine.is_empty()
            && graine
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-'),
        "graine de maison « {graine} » invalide (lettres, chiffres, _ et - seulement)"
    );
    let base = dossier_maisons().join(format!("maison_{graine}"));
    let vxh = base.with_extension("vxh");
    let modele = VxhModel::load(&vxh).with_context(|| {
        format!(
            "maison {} (lancer tools/maisons/cuire.sh {graine})",
            vxh.display()
        )
    })?;
    let json = base.with_extension("json");
    let meta: MetaMaison = serde_json::from_slice(
        &std::fs::read(&json).with_context(|| format!("lecture de {}", json.display()))?,
    )
    .with_context(|| format!("métadonnées {}", json.display()))?;
    Ok((Arc::new(modele), meta))
}

/// Colorieur des scènes à maisons : dans l'emprise d'une maison, la couleur est celle du générateur (RGB565 étendu en
/// sRGB8), l'intérieur et l'émissif viennent de ses drapeaux ; le reste (ou tout voxel hors d'une maison) est évalué par
/// le colorieur de base. Pur : même voxel, même aspect.
pub struct MaisonColorer<'a> {
    base: &'a dyn VoxelColorer,
    scene: &'a StaticScene,
}

impl<'a> MaisonColorer<'a> {
    /// Enveloppe `base` pour les maisons de `scene`.
    pub fn new(base: &'a dyn VoxelColorer, scene: &'a StaticScene) -> Self {
        Self { base, scene }
    }
}

impl VoxelColorer for MaisonColorer<'_> {
    fn appearance(&self, value: VoxelValue, voxel: VoxelCoord, lod: Lod) -> VoxelAppearance {
        let mut aspect = self.base.appearance(value, voxel, lod);
        if lod == 0 {
            for maison in self.scene.houses() {
                if let Some(cellule) = maison.cell_at(voxel) {
                    aspect.color = cellule.rgb8();
                    aspect.interior = cellule.flags().interior();
                    aspect.emissive = cellule.flags().emissive();
                    break;
                }
            }
        }
        aspect
    }

    fn is_foliage(&self, value: VoxelValue) -> bool {
        self.base.is_foliage(value)
    }
}
