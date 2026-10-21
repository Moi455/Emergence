//! Les essences (`engine/data/species.toml`, exportées de `voxel_tree.py` / `voxel_bush.py`) converties en
//! entiers : longueurs en Q16 de voxel, angles en tours Q16, rapports en Q16. Le TOML est la seule place où
//! des décimaux existent ; la conversion se fait une fois, au chargement, de façon déterministe.

use std::collections::BTreeMap;

use em_material::{RampRole, VegetationRamps};
use serde::Deserialize;

use super::fx::{UN, VOX_PAR_M};
use crate::error::GenError;

/// Une rampe de couleurs `[sombre, moyen, clair]` en sRGB 8 bits.
pub type RampRgb = [[u8; 3]; 3];

/// Les essences embarquées (fichier du dépôt, lu à la compilation).
pub const SPECIES_TOML: &str = include_str!("../../../../../engine/data/species.toml");

/// Saison de la scène : densité du feuillage, fleurs, fruits et rampes de couleurs.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Hash, serde::Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Season {
    /// Été (référence).
    Summer,
    /// Printemps : feuillage clairsemé et rampes éclaircies.
    Spring,
    /// Automne : rampes d'automne.
    Autumn,
    /// Hiver : pas de feuilles caduques.
    Winter,
}

impl Season {
    /// Les quatre saisons.
    pub const ALL: [Season; 4] = [Season::Summer, Season::Spring, Season::Autumn, Season::Winter];

    /// Nom dans les fichiers de données.
    pub const fn name(self) -> &'static str {
        match self {
            Season::Summer => "summer",
            Season::Spring => "spring",
            Season::Autumn => "autumn",
            Season::Winter => "winter",
        }
    }
}

/// Architecture de l'axe : une flèche qui se fourche, une flèche centrale ou une touffe de tiges.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ArchKind {
    /// Tronc qui se fourche en charpentières (feuillus).
    Decurrent,
    /// Flèche centrale (conifères, peuplier).
    Excurrent,
    /// Plusieurs tiges issues du sol (arbustes).
    Multistem,
}

/// Silhouette de la couronne.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CrownShape {
    /// Cône (épicéa).
    Conique,
    /// Colonne (peuplier d'Italie).
    Colonne,
    /// Ovale.
    Ovale,
    /// Dôme.
    Dome,
}

/// Règle de l'écorce secondaire.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AltRule {
    /// Mousse au pied.
    Moss,
    /// Marques sombres (bouleau).
    Marks,
    /// Partie haute (pin).
    Upper,
    /// Aucune.
    None,
}

#[derive(Debug, Deserialize)]
struct RawFeature {
    seasons: Vec<Season>,
    frac: f64,
    r: f64,
    stretch: f64,
    off: f64,
    fill: f64,
    tip: f64,
    mix: bool,
    ramps: Vec<RampRgb>,
}

#[derive(Debug, Deserialize)]
struct RawColors {
    bark: RampRgb,
    bark_alt: RampRgb,
    twig: RampRgb,
    leaves: Vec<RampRgb>,
    autumn: Vec<RampRgb>,
}

#[derive(Debug, Deserialize)]
struct RawSpecies {
    #[serde(default = "env_defaut")]
    sil_env: f64,
    #[serde(default = "dens_defaut")]
    sil_dens: f64,
    key: String,
    nom: String,
    h_range: [f64; 2],
    arch: ArchKind,
    trunk_frac: [f64; 2],
    bole: [f64; 2],
    trunk_k: f64,
    taper: f64,
    crown_r: f64,
    crown_shape: CrownShape,
    max_order: usize,
    density: [f64; 5],
    whorl: u32,
    angle: [f64; 5],
    angle_var: f64,
    len_ratio: [f64; 5],
    step: [f64; 5],
    min_len: [f64; 5],
    wobble: [f64; 5],
    tropism: [f64; 5],
    up_bias: [f64; 5],
    min_dz: f64,
    crowd: [u32; 5],
    leaders: [i64; 2],
    leader_angle: [f64; 2],
    stubs: f64,
    leaf_min_order: usize,
    leaf_start: f64,
    leaf_end: f64,
    leaf_r: [f64; 5],
    leaf_dens: f64,
    leaf_spacing: f64,
    leaf_stretch: f64,
    leaf_flat: f64,
    leaf_droop: f64,
    leaf_big: f64,
    evergreen: bool,
    multistem: [i64; 2],
    stem_lean: [f64; 2],
    stem_len: [f64; 2],
    roots: bool,
    spring_leaf: f64,
    alt_rule: AltRule,
    bark_rough: f64,
    flower: RawFeature,
    fruit: RawFeature,
    colors: RawColors,
}

fn env_defaut() -> f64 {
    0.8
}
fn dens_defaut() -> f64 {
    1.5
}

#[derive(Debug, Deserialize)]
struct RawFile {
    species: Vec<RawSpecies>,
}

/// Conversions décimal -> Q16 : exécutées au chargement des données, jamais dans un générateur.
#[allow(clippy::float_arithmetic)]
mod conv {
    use super::{UN, VOX_PAR_M};

    /// Rapport sans unité -> Q16.
    pub fn q(x: f64) -> i64 {
        (x * UN as f64).round() as i64
    }
    /// Mètres -> Q16 de voxel.
    pub fn vox(m: f64) -> i64 {
        (m * UN as f64 * VOX_PAR_M as f64).round() as i64
    }
    /// Degrés -> tours Q16.
    pub fn tours(deg: f64) -> i64 {
        (deg / 360.0 * UN as f64).round() as i64
    }
    /// Q16 par mètre (par exemple l'effilement) : inchangé, c'est un rapport par mètre.
    pub fn arr<const N: usize>(a: [f64; N], f: fn(f64) -> i64) -> [i64; N] {
        std::array::from_fn(|i| f(a[i]))
    }
}

/// Fleurs ou fruits d'une essence.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Feature {
    /// Saisons où l'organe est présent.
    pub seasons: Vec<Season>,
    /// Part des bouquets de feuilles qui le portent (Q16).
    pub frac: i64,
    /// Rayon (Q16 de voxel).
    pub r: i64,
    /// Allongement le long de la tige (Q16).
    pub stretch: i64,
    /// Décalage vers l'extrémité (Q16 de voxel).
    pub off: i64,
    /// Remplissage : points par voxel (Q16).
    pub fill: i64,
    /// Seulement au-delà de cette fraction de la branche (Q16).
    pub tip: i64,
    /// Plusieurs teintes par plante (sinon une seule, tirée par la graine).
    pub mix: bool,
    /// Rampes de couleur.
    pub ramps: Vec<RampRgb>,
}

impl Feature {
    fn from_raw(r: RawFeature) -> Self {
        Self {
            seasons: r.seasons,
            frac: conv::q(r.frac),
            r: conv::vox(r.r),
            stretch: conv::q(r.stretch),
            off: conv::vox(r.off),
            fill: conv::q(r.fill),
            tip: conv::q(r.tip),
            mix: r.mix,
            ramps: r.ramps,
        }
    }

    /// Présent à cette saison, avec au moins une rampe.
    pub fn active(&self, season: Season) -> bool {
        self.seasons.contains(&season) && !self.ramps.is_empty()
    }
}

/// Une essence, en entiers.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Species {
    /// Clé stable (`chene`).
    pub key: String,
    /// Nom d'usage.
    pub nom: String,
    /// Case d'essence (0..=31) : rang dans `species.toml`.
    pub slot: u8,
    /// Échelle de l'enveloppe de la silhouette lointaine (Q16).
    pub sil_env: i64,
    /// Densité des disques de la silhouette lointaine (Q16).
    pub sil_dens: i64,
    /// Hauteur minimale et maximale d'un sujet (Q16 de voxel).
    pub h_range: (i64, i64),
    /// Architecture.
    pub arch: ArchKind,
    /// Part de H atteinte par le fût avant la fourche (Q16).
    pub trunk_frac: (i64, i64),
    /// Part de H sans branches (Q16).
    pub bole: (i64, i64),
    /// Rayon à la base ≈ `trunk_k` · H (Q16).
    pub trunk_k: i64,
    /// Effilement par mètre de branche (Q16).
    pub taper: i64,
    /// Rayon maximal de couronne / H (Q16).
    pub crown_r: i64,
    /// Silhouette de la couronne.
    pub crown_shape: CrownShape,
    /// Ordre maximal des branches.
    pub max_order: usize,
    /// Enfants par mètre selon l'ordre du parent (Q16).
    pub density: [i64; 5],
    /// Nombre de branches par verticille.
    pub whorl: u32,
    /// Angle d'insertion selon l'ordre de l'enfant (tours Q16).
    pub angle: [i64; 5],
    /// Variation relative de l'angle (Q16).
    pub angle_var: i64,
    /// Longueur relative selon l'ordre de l'enfant (Q16).
    pub len_ratio: [i64; 5],
    /// Pas de croissance par ordre (Q16 de voxel).
    pub step: [i64; 5],
    /// Longueur minimale d'une branche par ordre (Q16 de voxel).
    pub min_len: [i64; 5],
    /// Agitation par ordre (Q16, par racine de mètre).
    pub wobble: [i64; 5],
    /// Tropisme par ordre (Q16, par mètre).
    pub tropism: [i64; 5],
    /// Biais vers le haut des enfants (Q16).
    pub up_bias: [i64; 5],
    /// Pente verticale minimale de la direction (Q16).
    pub min_dz: i64,
    /// Seuil d'auto-élagage par ordre (nombre de touches dans la cellule).
    pub crowd: [u32; 5],
    /// Nombre de charpentières maîtresses (min, max).
    pub leaders: (i64, i64),
    /// Angle des charpentières maîtresses (tours Q16).
    pub leader_angle: (i64, i64),
    /// Chicots sur le fût (Q16).
    pub stubs: i64,
    /// Premier ordre qui porte des feuilles.
    pub leaf_min_order: usize,
    /// Le feuillage commence à cette fraction de la branche (Q16).
    pub leaf_start: i64,
    /// Le feuillage s'arrête à cette fraction (Q16).
    pub leaf_end: i64,
    /// Rayon d'un amas par ordre (Q16 de voxel).
    pub leaf_r: [i64; 5],
    /// Densité de points par voxel dans un amas (Q16).
    pub leaf_dens: i64,
    /// Espacement des amas en rayons (Q16).
    pub leaf_spacing: i64,
    /// Allongement des amas le long de la branche (Q16).
    pub leaf_stretch: i64,
    /// Aplatissement vertical (Q16).
    pub leaf_flat: i64,
    /// Affaissement du centre (fraction du rayon, Q16).
    pub leaf_droop: i64,
    /// Part des points qui débordent d'un voxel (grandes feuilles, Q16).
    pub leaf_big: i64,
    /// Persistant.
    pub evergreen: bool,
    /// Nombre de tiges issues du sol (min, max) ; (0, 0) = arbre à tronc.
    pub multistem: (i64, i64),
    /// Inclinaison des tiges (tours Q16).
    pub stem_lean: (i64, i64),
    /// Longueur des tiges / H (Q16).
    pub stem_len: (i64, i64),
    /// Racines de surface.
    pub roots: bool,
    /// Densité du feuillage au printemps (Q16).
    pub spring_leaf: i64,
    /// Règle de l'écorce secondaire.
    pub alt_rule: AltRule,
    /// Rugosité de l'écorce (Q16).
    pub bark_rough: i64,
    /// Fleurs.
    pub flower: Feature,
    /// Fruits.
    pub fruit: Feature,
    /// Écorce.
    pub bark: RampRgb,
    /// Écorce secondaire.
    pub bark_alt: RampRgb,
    /// Rameaux.
    pub twig: RampRgb,
    /// Feuillages d'été.
    pub leaves: Vec<RampRgb>,
    /// Feuillages d'automne.
    pub autumn: Vec<RampRgb>,
}

impl Species {
    fn from_raw(r: RawSpecies, slot: u8) -> Self {
        use conv::{arr, q, tours, vox};
        Self {
            key: r.key,
            nom: r.nom,
            slot,
            sil_env: q(r.sil_env),
            sil_dens: q(r.sil_dens),
            h_range: (vox(r.h_range[0]), vox(r.h_range[1])),
            arch: r.arch,
            trunk_frac: (q(r.trunk_frac[0]), q(r.trunk_frac[1])),
            bole: (q(r.bole[0]), q(r.bole[1])),
            trunk_k: q(r.trunk_k),
            taper: q(r.taper),
            crown_r: q(r.crown_r),
            crown_shape: r.crown_shape,
            max_order: r.max_order,
            density: arr(r.density, q),
            whorl: r.whorl.max(1),
            angle: arr(r.angle, tours),
            angle_var: q(r.angle_var),
            len_ratio: arr(r.len_ratio, q),
            step: arr(r.step, vox),
            min_len: arr(r.min_len, vox),
            wobble: arr(r.wobble, q),
            tropism: arr(r.tropism, q),
            up_bias: arr(r.up_bias, q),
            min_dz: q(r.min_dz),
            crowd: r.crowd,
            leaders: (r.leaders[0], r.leaders[1]),
            leader_angle: (tours(r.leader_angle[0]), tours(r.leader_angle[1])),
            stubs: q(r.stubs),
            leaf_min_order: r.leaf_min_order,
            leaf_start: q(r.leaf_start),
            leaf_end: q(r.leaf_end),
            leaf_r: arr(r.leaf_r, vox),
            leaf_dens: q(r.leaf_dens),
            leaf_spacing: q(r.leaf_spacing),
            leaf_stretch: q(r.leaf_stretch),
            leaf_flat: q(r.leaf_flat),
            leaf_droop: q(r.leaf_droop),
            leaf_big: q(r.leaf_big),
            evergreen: r.evergreen,
            multistem: (r.multistem[0], r.multistem[1]),
            stem_lean: (tours(r.stem_lean[0]), tours(r.stem_lean[1])),
            stem_len: (q(r.stem_len[0]), q(r.stem_len[1])),
            roots: r.roots,
            spring_leaf: q(r.spring_leaf),
            alt_rule: r.alt_rule,
            bark_rough: q(r.bark_rough),
            flower: Feature::from_raw(r.flower),
            fruit: Feature::from_raw(r.fruit),
            bark: r.colors.bark,
            bark_alt: r.colors.bark_alt,
            twig: r.colors.twig,
            leaves: r.colors.leaves,
            autumn: r.colors.autumn,
        }
    }

    /// Arbuste (touffe multi-tiges) ?
    pub const fn is_bush(&self) -> bool {
        self.multistem.1 > 0
    }

    /// Les rampes de feuilles de la saison, dans l'ordre de `ramp_table` de `voxel_tree.py` : en automne les
    /// trois rampes d'automne puis la première verte (taches), au printemps les rampes éclaircies vers le
    /// vert frais (170, 205, 70) à 45 %, sinon les rampes d'été. Les persistants gardent leurs rampes.
    pub fn leaf_ramps(&self, season: Season) -> Vec<RampRgb> {
        if self.evergreen {
            return self.leaves.clone();
        }
        match season {
            Season::Autumn => {
                let mut v = self.autumn.clone();
                v.push(self.leaves[0]);
                v
            }
            Season::Spring => self
                .leaves
                .iter()
                .map(|r| {
                    let fresh = [170_u32, 205, 70];
                    let mut out = [[0_u8; 3]; 3];
                    for (o, col) in out.iter_mut().zip(r) {
                        for c in 0..3 {
                            // int(c × 0,55 + f × 0,45) du Python, en centièmes entiers
                            o[c] = ((u32::from(col[c]) * 55 + fresh[c] * 45) / 100) as u8;
                        }
                    }
                    out
                })
                .collect(),
            _ => self.leaves.clone(),
        }
    }

    /// Multiplicateur de densité du feuillage selon la saison (permille, Q16 = 1,0 en été).
    pub fn season_leaf_factor(&self, season: Season) -> i64 {
        if self.evergreen {
            return UN;
        }
        match season {
            Season::Summer => UN,
            Season::Spring => self.spring_leaf,
            Season::Autumn => UN * 85 / 100,
            Season::Winter => 0,
        }
    }
}

/// Toutes les essences, par clé et par case.
#[derive(Clone, Debug)]
pub struct SpeciesTable {
    list: Vec<Species>,
    by_key: BTreeMap<String, usize>,
}

impl SpeciesTable {
    /// Les essences embarquées.
    pub fn embedded() -> Self {
        Self::from_toml(SPECIES_TOML).expect("species.toml embarqué valide")
    }

    /// Lit un texte TOML ; refuse plus de 32 essences (5 bits de teinte) ou une clé en double.
    pub fn from_toml(texte: &str) -> Result<Self, GenError> {
        let f: RawFile =
            toml::from_str(texte).map_err(|e| GenError::BadParams(format!("species.toml : {e}")))?;
        if f.species.len() > 32 {
            return Err(GenError::BadParams("species.toml : plus de 32 essences".into()));
        }
        let mut list = Vec::new();
        let mut by_key = BTreeMap::new();
        for (i, r) in f.species.into_iter().enumerate() {
            if r.leaf_min_order > 4 || r.max_order > 4 {
                return Err(GenError::BadParams(format!(
                    "essence « {} » : ordre hors de 0..=4",
                    r.key
                )));
            }
            if r.colors.leaves.is_empty() || r.colors.autumn.is_empty() {
                return Err(GenError::BadParams(format!(
                    "essence « {} » sans rampe de feuilles",
                    r.key
                )));
            }
            if by_key.insert(r.key.clone(), i).is_some() {
                return Err(GenError::BadParams(format!("essence « {} » en double", r.key)));
            }
            list.push(Species::from_raw(r, i as u8));
        }
        Ok(Self { list, by_key })
    }

    /// L'essence de cette clé.
    pub fn get(&self, key: &str) -> Result<&Species, GenError> {
        self.by_key.get(key).map(|&i| &self.list[i]).ok_or_else(|| {
            GenError::BadParams(format!(
                "essence « {key} » inconnue (disponibles : {})",
                self.keys().collect::<Vec<_>>().join(", ")
            ))
        })
    }

    /// Les clés, dans l'ordre des cases.
    pub fn keys(&self) -> impl Iterator<Item = &str> {
        self.list.iter().map(|s| s.key.as_str())
    }

    /// Toutes les essences, dans l'ordre des cases.
    pub fn all(&self) -> &[Species] {
        &self.list
    }

    /// Le registre de rampes de végétation de toutes les essences pour une saison (cases = rang dans le TOML).
    /// Écorce : trois variantes (écorce, écorce secondaire, rameau) ; feuilles : rampes de la saison ; fleurs et
    /// fruits : leurs rampes (les fleurs, jusqu'à 4 ; les fruits, jusqu'à 2).
    pub fn vegetation_ramps(&self, season: Season) -> Result<VegetationRamps, GenError> {
        let mut veg = VegetationRamps::new();
        let refus = |m: String| GenError::BadParams(m);
        for s in &self.list {
            let ecorce = [s.bark, s.bark_alt, s.twig];
            let cases = [
                (RampRole::Bark, ecorce.to_vec()),
                (RampRole::Leaves, s.leaf_ramps(season)),
                (RampRole::Flowers, s.flower.ramps.clone()),
                (RampRole::Fruits, s.fruit.ramps.clone()),
            ];
            for (role, rampes) in cases {
                let case = veg
                    .register(&s.key, role, &rampes)
                    .map_err(|e| refus(e.to_string()))?;
                if case != s.slot {
                    return Err(refus(format!(
                        "essence « {} » : case {case} au lieu de {}",
                        s.key, s.slot
                    )));
                }
            }
        }
        Ok(veg)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn le_fichier_embarque_contient_les_essences_du_python_dans_l_ordre() {
        let t = SpeciesTable::embedded();
        let cles: Vec<&str> = t.keys().collect();
        assert_eq!(
            &cles[..16],
            [
                "chene",
                "hetre",
                "bouleau",
                "epicea",
                "pin",
                "peuplier",
                "erable",
                "buis",
                "rosier",
                "lavande",
                "lilas",
                "hortensia",
                "forsythia",
                "houx",
                "genevrier",
                "ronce"
            ]
        );
        assert!(t.get("chene").unwrap().h_range.1 == 20 * 20 * UN);
        assert!(t.get("buis").unwrap().is_bush());
        assert!(!t.get("chene").unwrap().is_bush());
        assert!(t.get("sequoia").is_err());
    }

    #[test]
    fn les_rampes_de_chaque_saison_entrent_dans_le_registre() {
        let t = SpeciesTable::embedded();
        for s in Season::ALL {
            let v = t.vegetation_ramps(s).expect("rampes");
            assert_eq!(v.species_count(), t.all().len());
        }
        let v = t.vegetation_ramps(Season::Autumn).unwrap();
        assert_eq!(v.ramps(0, RampRole::Leaves).len(), 4);
    }
}
