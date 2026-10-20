//! En-tête JSON d'un `.vxm` (docs/19a § 1.2), lu une fois et exposé par accesseurs.

use serde::Deserialize;

use crate::error::VxmError;

/// Métadonnées d'un modèle : qui l'a produit, de quoi il s'agit, et ses rampes de couleur (sRGB).
#[derive(Clone, Debug, Deserialize)]
pub struct VxmMeta {
    format: String,
    generator: Option<String>,
    generator_sha256: Option<String>,
    seed: Option<String>,
    seed_int: i64,
    species: String,
    nom: Option<String>,
    height_m: Option<f64>,
    season: Option<String>,
    leaf_density: Option<f64>,
    topiary: Option<String>,
    voxel_m: f64,
    axes: Option<String>,
    lods: Vec<u8>,
    steps: u32,
    ramps: Vec<[[u8; 3]; 3]>,
    ramp_roles: Vec<String>,
    palette: Option<Vec<[u8; 3]>>,
    base_radius_m: Option<f64>,
}

impl VxmMeta {
    /// Décode et valide l'en-tête ; `palette_attendue` vient du drapeau 2 du fichier.
    pub(super) fn parse(json: &[u8], palette_attendue: bool) -> Result<Self, VxmError> {
        let meta: VxmMeta = serde_json::from_slice(json).map_err(|e| VxmError::EnTeteJson(e.to_string()))?;
        let invalide = |s: &str| Err(VxmError::EnTeteInvalide(s.to_owned()));
        if meta.format != "vxm-1" {
            return invalide("format différent de « vxm-1 »");
        }
        if meta.ramps.len() != meta.ramp_roles.len() {
            return invalide("ramps et ramp_roles de longueurs différentes");
        }
        if meta.ramps.len() > 256 {
            return invalide("plus de 256 rampes");
        }
        if meta.steps == 0 {
            return invalide("steps nul");
        }
        #[allow(clippy::float_cmp)]
        if meta.voxel_m != 0.05 {
            return Err(VxmError::VoxelHorsGrille(meta.voxel_m.to_string()));
        }
        if meta.lods.first() != Some(&0) {
            return invalide("la liste des LOD doit commencer par 0");
        }
        if meta.lods.windows(2).any(|w| w[0] >= w[1]) {
            return invalide("liste des LOD non strictement croissante");
        }
        if let Some(&l) = meta.lods.iter().find(|&&l| l > 5) {
            return Err(VxmError::LodHorsPlage(l));
        }
        match (&meta.palette, palette_attendue) {
            (Some(p), true) if p.len() == 256 => {}
            (_, true) => return invalide("drapeau pal sans palette de 256 couleurs dans l'en-tête"),
            _ => {}
        }
        Ok(meta)
    }

    /// Essence (`chene`, `rosier`…).
    pub fn species(&self) -> &str {
        &self.species
    }
    /// Nom d'affichage.
    pub fn display_name(&self) -> Option<&str> {
        self.nom.as_deref()
    }
    /// Graine entière du générateur.
    pub fn seed_int(&self) -> i64 {
        self.seed_int
    }
    /// Graine telle qu'écrite (chaîne).
    pub fn seed(&self) -> Option<&str> {
        self.seed.as_deref()
    }
    /// Programme qui a produit le modèle.
    pub fn generator(&self) -> Option<&str> {
        self.generator.as_deref()
    }
    /// Empreinte SHA-256 du programme producteur.
    pub fn generator_sha256(&self) -> Option<&str> {
        self.generator_sha256.as_deref()
    }
    /// Hauteur visée, en mètres.
    pub fn height_m(&self) -> Option<f64> {
        self.height_m
    }
    /// Saison du feuillage.
    pub fn season(&self) -> Option<&str> {
        self.season.as_deref()
    }
    /// Densité de feuillage.
    pub fn leaf_density(&self) -> Option<f64> {
        self.leaf_density
    }
    /// Forme taillée (buis, topiaire), s'il y en a une.
    pub fn topiary(&self) -> Option<&str> {
        self.topiary.as_deref()
    }
    /// Convention d'axes annoncée.
    pub fn axes(&self) -> Option<&str> {
        self.axes.as_deref()
    }
    /// Rayon du pied du tronc, en mètres.
    pub fn base_radius_m(&self) -> Option<f64> {
        self.base_radius_m
    }
    /// LOD écrits dans le fichier (croissants, commencent par 0).
    pub fn lods(&self) -> &[u8] {
        &self.lods
    }
    /// Nombre de nuances par rampe côté Python.
    pub fn steps(&self) -> u32 {
        self.steps
    }
    /// Rampes (sombre, moyen, clair) en sRGB.
    pub fn ramps(&self) -> &[[[u8; 3]; 3]] {
        &self.ramps
    }
    /// Rôle de chaque rampe (`bark`, `bark_alt`, `twig`, `leaf`, `flower`, `fruit`).
    pub fn ramp_roles(&self) -> &[String] {
        &self.ramp_roles
    }
    /// Palette Python de 256 couleurs, si le canal `pal` est présent.
    pub fn palette(&self) -> Option<&[[u8; 3]]> {
        self.palette.as_deref()
    }

    /// Variante de 2 bits de la teinte de végétation (docs/19a § 1.4), comme `tint_variant` de `read_vxm.py` :
    /// écorce 0, écorce secondaire 1, rameau 2 ; fleur et fruit : rang de la rampe dans son rôle ; feuille 0.
    pub(super) fn tint_variant(&self, kind: super::kind::VxmKind, ramp: u8) -> Result<u8, VxmError> {
        use super::kind::VxmKind;
        let role = &self.ramp_roles[usize::from(ramp)];
        match kind {
            VxmKind::Bark => Ok(u8::from(role == "bark_alt")),
            VxmKind::Twig => Ok(2),
            VxmKind::Leaf => Ok(0),
            VxmKind::Flower | VxmKind::Fruit => {
                let premier = self
                    .ramp_roles
                    .iter()
                    .position(|r| r == role)
                    .unwrap_or(usize::from(ramp));
                let rang = usize::from(ramp) - premier;
                u8::try_from(rang)
                    .ok()
                    .filter(|r| *r <= 3)
                    .ok_or(VxmError::RangDeRampeTropGrand(ramp))
            }
        }
    }
}
