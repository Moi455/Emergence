//! La table de matières : physique (`engine/data/materials.csv`) + aspect (`engine/data/material_render.toml`).
//!
//! Tout est entier : les propriétés d'aspect sont des `Q16`, la couleur de base est convertie une seule fois
//! en linéaire à la construction. Les flottants du fichier TOML ne servent qu'à lire du texte décimal
//! (`flottant_vers_q16`), seul point de la crate où un flottant existe avant la frontière GPU.

use crate::color::{Ramp3, SrgbTable};
use crate::error::MaterialError;
use crate::tint::TintMode;
use crate::vegetation::RampRole;
use em_core::digest::Fnv64;
use em_core::hash::hash_combine;
use em_core::ids::MaterialId;
use em_core::q16::Q16;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::path::Path;

/// Version du schéma accepté pour les deux fichiers.
const SCHEMA: u32 = 1;
/// Nombre de classes représentables (9 bits).
pub const CLASS_COUNT: usize = 512;
/// Graine de base du bruit de matière ; la graine d'une classe en est dérivée (`class_seed`).
const GRAINE_MATIERE: u64 = 0x4D41_5445_5249_414C; // « MATERIAL »

/// Drapeaux d'aspect d'une classe (bits transmis au shader).
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq)]
pub struct MaterialFlags(u32);

impl MaterialFlags {
    /// Feuillage : translucidité en contre-jour, épaisseur par occupation voisine.
    pub const FOLIAGE: u32 = 1;
    /// Mousse possible sur les faces tournées vers le ciel.
    pub const MOSS: u32 = 2;
    /// Peau de terrain (non éditée).
    pub const SKIN: u32 = 4;
    /// Émission scintillante (braises, lanterne).
    pub const FLICKER: u32 = 8;

    /// Aucun drapeau.
    pub const fn empty() -> Self {
        MaterialFlags(0)
    }
    /// Lit un nom de drapeau du TOML.
    pub fn bit_of(nom: &str) -> Option<u32> {
        match nom {
            "foliage" => Some(Self::FOLIAGE),
            "moss" => Some(Self::MOSS),
            "skin" => Some(Self::SKIN),
            "flicker" => Some(Self::FLICKER),
            _ => None,
        }
    }
    /// Les bits bruts.
    pub const fn bits(self) -> u32 {
        self.0
    }
    /// Vrai si tous les bits de `masque` sont présents.
    pub const fn contains(self, masque: u32) -> bool {
        self.0 & masque == masque
    }
}

/// Propriétés d'aspect d'une classe. Lecture seule ; construit et validé par la table.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RenderProps {
    albedo_var: Q16,
    hue_var: Q16,
    voxel_jitter: Q16,
    roughness: Q16,
    roughness_var: Q16,
    relief: Q16,
    detail_strength: Q16,
    detail_scale_m: Q16,
    translucency: Q16,
    emission: Q16,
    detail: Option<String>,
    tint_mode: TintMode,
    flags: MaterialFlags,
    veg_role: Option<RampRole>,
    ramp: Option<[[u8; 3]; 3]>,
}

macro_rules! accesseurs_q16 {
    ($($nom:ident : $doc:literal),* $(,)?) => {
        $(#[doc = $doc] pub const fn $nom(&self) -> Q16 { self.$nom })*
    };
}

impl RenderProps {
    accesseurs_q16! {
        albedo_var: "Amplitude du champ continu de luminance (fraction, Q16).",
        hue_var: "Amplitude de la variation de teinte (Q16).",
        voxel_jitter: "Gigue par voxel : le grain pixel, sans mosaïque (Q16).",
        roughness: "Rugosité de base (Q16, 0..1).",
        roughness_var: "Variation de rugosité (Q16).",
        relief: "Force du relief par différences finies (Q16).",
        detail_strength: "Force du détail bitmap sous-voxel (Q16).",
        detail_scale_m: "Taille d'un motif du détail, en mètres (Q16).",
        translucency: "Translucidité (feuilles, verre ; Q16, 0..1).",
        emission: "Émission HDR (Q16, 0..16).",
    }
    /// Couche de détail demandée (nom de l'atlas de textures), `None` si aucune.
    pub fn detail(&self) -> Option<&str> {
        self.detail.as_deref()
    }
    /// Mode d'interprétation des 7 bits de teinte.
    pub const fn tint_mode(&self) -> TintMode {
        self.tint_mode
    }
    /// Drapeaux.
    pub const fn flags(&self) -> MaterialFlags {
        self.flags
    }
    /// Rôle de rampe d'essence (classes à teinte de végétation).
    pub const fn veg_role(&self) -> Option<RampRole> {
        self.veg_role
    }
    /// Rampe sRGB imposée par le TOML (sinon dérivée de la couleur de base).
    pub const fn ramp_override(&self) -> Option<[[u8; 3]; 3]> {
        self.ramp
    }
}

/// Définition complète d'une classe de matière. Champs privés ; construite seulement par `MaterialTable`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MaterialDef {
    id: MaterialId,
    name: String,
    category: String,
    density_kg_m3: u32,
    hardness: u8,
    flammability: u8,
    base_srgb: [u8; 3],
    ramp: Ramp3,
    render: RenderProps,
}

impl MaterialDef {
    /// Numéro de classe (jamais renuméroté : il est dans les sauvegardes).
    pub const fn id(&self) -> MaterialId {
        self.id
    }
    /// Nom de la classe.
    pub fn name(&self) -> &str {
        &self.name
    }
    /// Catégorie (`soil`, `rock`, `wood`, `building`, `plant`…).
    pub fn category(&self) -> &str {
        &self.category
    }
    /// Densité en kg/m³.
    pub const fn density_kg_m3(&self) -> u32 {
        self.density_kg_m3
    }
    /// Dureté 0..100.
    pub const fn hardness(&self) -> u8 {
        self.hardness
    }
    /// Inflammabilité 0..100.
    pub const fn flammability(&self) -> u8 {
        self.flammability
    }
    /// Couleur de base en sRGB 8 bits.
    pub const fn base_srgb(&self) -> [u8; 3] {
        self.base_srgb
    }
    /// Rampe de couleurs de la classe (sombre, moyen, clair), en linéaire.
    pub const fn ramp(&self) -> &Ramp3 {
        &self.ramp
    }
    /// Propriétés d'aspect.
    pub const fn render(&self) -> &RenderProps {
        &self.render
    }
    /// Graine de bruit propre à la classe (hachage du numéro de classe).
    pub fn class_seed(&self) -> u64 {
        hash_combine(GRAINE_MATIERE, u64::from(self.id.get()))
    }
}

// ---------------------------------------------------------------------------------------------------
// Lecture du TOML d'aspect
// ---------------------------------------------------------------------------------------------------

/// Nombre TOML : entier ou décimal.
#[derive(Deserialize, Copy, Clone, Debug)]
#[serde(untagged)]
enum Nombre {
    Entier(i64),
    Decimal(f64),
}

/// Convertit un nombre lu dans le TOML en Q16 (arrondi au plus proche). Seul endroit de la crate de vérité
/// qui touche à un flottant : la conversion d'un texte décimal en entier, exacte et identique sur toute machine IEEE.
#[allow(clippy::float_arithmetic)]
fn flottant_vers_q16(n: Nombre) -> Option<Q16> {
    match n {
        Nombre::Entier(v) => v.checked_mul(65_536).map(Q16::from_raw),
        Nombre::Decimal(v) if v.is_finite() => Some(Q16::from_raw((v * 65_536.0).round() as i64)),
        Nombre::Decimal(_) => None,
    }
}

#[derive(Deserialize, Default, Clone, Debug)]
#[serde(deny_unknown_fields)]
struct RawRender {
    albedo_var: Option<Nombre>,
    hue_var: Option<Nombre>,
    voxel_jitter: Option<Nombre>,
    roughness: Option<Nombre>,
    roughness_var: Option<Nombre>,
    relief: Option<Nombre>,
    detail: Option<String>,
    detail_strength: Option<Nombre>,
    detail_scale_m: Option<Nombre>,
    translucency: Option<Nombre>,
    emission: Option<Nombre>,
    tint_mode: Option<String>,
    flags: Option<Vec<String>>,
    veg_role: Option<String>,
    ramp: Option<Vec<String>>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawFile {
    schema_version: u32,
    default: RawRender,
    #[serde(default)]
    material: BTreeMap<String, RawRender>,
    /// Classes propres au rendu, ajoutées APRÈS le CSV du jeu (lecture seule) : jamais de collision de numéro.
    #[serde(default)]
    extra_class: Vec<RawExtra>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawExtra {
    id: u16,
    name: String,
    category: String,
    density_kg_m3: u32,
    hardness: u8,
    flammability: u8,
    color: String,
}

/// Résout un champ Q16 : la classe, sinon `[default]`, sinon erreur ; borne vérifiée.
fn q16_champ(
    section: &str,
    champ: &'static str,
    surcharge: Option<Nombre>,
    defaut: Option<Nombre>,
    min: i64,
    max: i64,
) -> Result<Q16, MaterialError> {
    let n = surcharge.or(defaut).ok_or(MaterialError::ChampManquant(champ))?;
    let q = flottant_vers_q16(n).ok_or_else(|| MaterialError::Valeur {
        section: section.to_owned(),
        champ,
        raison: "nombre non fini".into(),
    })?;
    if q.raw() < min * 65_536 || q.raw() > max * 65_536 {
        return Err(MaterialError::Valeur {
            section: section.to_owned(),
            champ,
            raison: format!("hors de {min}..={max}"),
        });
    }
    Ok(q)
}

fn hex_vers_srgb(texte: &str) -> Option<[u8; 3]> {
    let h = texte.trim().trim_start_matches('#');
    if h.len() != 6 || !h.is_ascii() {
        return None;
    }
    let c = |i: usize| u8::from_str_radix(&h[i..i + 2], 16).ok();
    Some([c(0)?, c(2)?, c(4)?])
}

fn resoudre(section: &str, sur: &RawRender, def: &RawRender) -> Result<RenderProps, MaterialError> {
    let q = |champ, s: Option<Nombre>, d: Option<Nombre>, min, max| q16_champ(section, champ, s, d, min, max);
    let erreur = |champ: &'static str, raison: String| MaterialError::Valeur {
        section: section.to_owned(),
        champ,
        raison,
    };
    let nom_mode = sur
        .tint_mode
        .as_ref()
        .or(def.tint_mode.as_ref())
        .ok_or(MaterialError::ChampManquant("tint_mode"))?;
    let tint_mode = TintMode::from_name(nom_mode)
        .ok_or_else(|| erreur("tint_mode", format!("mode inconnu « {nom_mode} »")))?;
    let mut bits = 0;
    for nom in sur
        .flags
        .as_ref()
        .or(def.flags.as_ref())
        .map_or(&[][..], |v| v.as_slice())
    {
        bits |= MaterialFlags::bit_of(nom)
            .ok_or_else(|| erreur("flags", format!("drapeau inconnu « {nom} »")))?;
    }
    let veg_role = match sur.veg_role.as_ref().or(def.veg_role.as_ref()) {
        None => None,
        Some(n) => {
            Some(RampRole::from_name(n).ok_or_else(|| erreur("veg_role", format!("rôle inconnu « {n} »")))?)
        }
    };
    if tint_mode == TintMode::Vegetation && veg_role.is_none() {
        return Err(erreur(
            "veg_role",
            "obligatoire quand tint_mode = vegetation".into(),
        ));
    }
    let ramp = match &sur.ramp {
        None => None,
        Some(v) if v.len() == 3 => {
            let c = |i: usize| hex_vers_srgb(&v[i]);
            Some([
                c(0).ok_or_else(|| erreur("ramp", "couleur #rrggbb invalide".into()))?,
                c(1).ok_or_else(|| erreur("ramp", "couleur #rrggbb invalide".into()))?,
                c(2).ok_or_else(|| erreur("ramp", "couleur #rrggbb invalide".into()))?,
            ])
        }
        Some(_) => return Err(erreur("ramp", "trois couleurs attendues".into())),
    };
    let detail = sur
        .detail
        .as_ref()
        .or(def.detail.as_ref())
        .filter(|s| !s.is_empty())
        .cloned();
    Ok(RenderProps {
        albedo_var: q("albedo_var", sur.albedo_var, def.albedo_var, 0, 1)?,
        hue_var: q("hue_var", sur.hue_var, def.hue_var, 0, 1)?,
        voxel_jitter: q("voxel_jitter", sur.voxel_jitter, def.voxel_jitter, 0, 1)?,
        roughness: q("roughness", sur.roughness, def.roughness, 0, 1)?,
        roughness_var: q("roughness_var", sur.roughness_var, def.roughness_var, 0, 1)?,
        relief: q("relief", sur.relief, def.relief, 0, 4)?,
        detail_strength: q("detail_strength", sur.detail_strength, def.detail_strength, 0, 1)?,
        detail_scale_m: q("detail_scale_m", sur.detail_scale_m, def.detail_scale_m, 0, 64)?,
        translucency: q("translucency", sur.translucency, def.translucency, 0, 1)?,
        emission: q("emission", sur.emission, def.emission, 0, 16)?,
        detail,
        tint_mode,
        flags: MaterialFlags(bits),
        veg_role,
        ramp,
    })
}

// ---------------------------------------------------------------------------------------------------
// La table
// ---------------------------------------------------------------------------------------------------

/// Ligne brute du CSV.
struct LigneCsv {
    id: u16,
    name: String,
    category: String,
    density: u32,
    hardness: u8,
    flammability: u8,
    color: [u8; 3],
}

fn lire_csv(texte: &str) -> Result<Vec<LigneCsv>, MaterialError> {
    let mut lignes = Vec::new();
    let mut entete = false;
    for (n, brut) in texte.lines().enumerate() {
        let ligne = n + 1;
        let l = brut.trim();
        if l.is_empty() || l.starts_with('#') {
            continue;
        }
        let err = |raison: &str| MaterialError::Csv {
            ligne,
            raison: raison.to_owned(),
        };
        let champs: Vec<&str> = l.split(',').map(str::trim).collect();
        if champs[0] == "schema_version" {
            if champs.get(1).copied() != Some("1") {
                return Err(err("schema_version 1 attendu"));
            }
            continue;
        }
        if champs[0] == "id" {
            if champs
                != [
                    "id",
                    "name",
                    "category",
                    "density_kg_m3",
                    "hardness",
                    "flammability",
                    "color",
                ]
            {
                return Err(err("en-tête inattendu"));
            }
            entete = true;
            continue;
        }
        if !entete || champs.len() != 7 {
            return Err(err("7 colonnes attendues après l'en-tête"));
        }
        let nombre = |s: &str, nom: &str| s.parse::<u32>().map_err(|_| err(&format!("{nom} invalide")));
        let id = u16::try_from(nombre(champs[0], "id")?).map_err(|_| err("id invalide"))?;
        if usize::from(id) >= CLASS_COUNT {
            return Err(err("classe au-delà de 511"));
        }
        let borne100 = |s: &str, nom: &str| {
            nombre(s, nom).and_then(|v| {
                u8::try_from(v)
                    .ok()
                    .filter(|&b| b <= 100)
                    .ok_or_else(|| err(&format!("{nom} hors de 0..=100")))
            })
        };
        lignes.push(LigneCsv {
            id,
            name: champs[1].to_owned(),
            category: champs[2].to_owned(),
            density: nombre(champs[3], "densité")?,
            hardness: borne100(champs[4], "dureté")?,
            flammability: borne100(champs[5], "inflammabilité")?,
            color: hex_vers_srgb(champs[6]).ok_or_else(|| err("couleur hexadécimale invalide"))?,
        });
    }
    if !entete {
        return Err(MaterialError::Csv {
            ligne: 0,
            raison: "en-tête manquant".into(),
        });
    }
    Ok(lignes)
}

/// La table de matières complète : une définition par classe, indexée par `MaterialId`.
#[derive(Clone, Debug)]
pub struct MaterialTable {
    defs: Vec<MaterialDef>,
    par_nom: BTreeMap<String, MaterialId>,
    inconnue: MaterialDef,
    srgb: SrgbTable,
    details: Vec<String>,
    version: u32,
}

impl MaterialTable {
    /// Charge les deux fichiers de données.
    pub fn load(csv: &Path, render_toml: &Path) -> Result<Self, MaterialError> {
        let lire = |p: &Path| {
            std::fs::read_to_string(p).map_err(|e| MaterialError::Lecture {
                chemin: p.to_owned(),
                raison: e.to_string(),
            })
        };
        Self::from_sources(&lire(csv)?, &lire(render_toml)?)
    }

    /// Construit la table depuis le texte des deux fichiers. Vérifie : numéros et noms uniques, air = 0,
    /// toute entrée `[material.x]` désigne une classe du CSV, tous les champs d'aspect dans leurs bornes.
    pub fn from_sources(csv_text: &str, render_text: &str) -> Result<Self, MaterialError> {
        let mut lignes = lire_csv(csv_text)?;
        let fichier: RawFile = toml::from_str(render_text).map_err(|e| MaterialError::Toml(e.to_string()))?;
        for e in &fichier.extra_class {
            let erreur =
                |raison: String| MaterialError::Toml(format!("[[extra_class]] « {} » : {raison}", e.name));
            if usize::from(e.id) >= CLASS_COUNT {
                return Err(erreur("classe au-delà de 511".into()));
            }
            if e.hardness > 100 || e.flammability > 100 {
                return Err(erreur("dureté ou inflammabilité hors de 0..=100".into()));
            }
            if lignes.iter().any(|l| l.id == e.id || l.name == e.name) {
                return Err(erreur(format!(
                    "collision de numéro ({}) ou de nom avec une classe existante",
                    e.id
                )));
            }
            let color =
                hex_vers_srgb(&e.color).ok_or_else(|| erreur("couleur hexadécimale invalide".into()))?;
            lignes.push(LigneCsv {
                id: e.id,
                name: e.name.clone(),
                category: e.category.clone(),
                density: e.density_kg_m3,
                hardness: e.hardness,
                flammability: e.flammability,
                color,
            });
        }
        if fichier.schema_version != SCHEMA {
            return Err(MaterialError::Toml(format!("schema_version {SCHEMA} attendu")));
        }
        for nom in fichier.material.keys() {
            if !lignes.iter().any(|l| &l.name == nom) {
                return Err(MaterialError::MatiereInconnue(nom.clone()));
            }
        }
        let srgb = SrgbTable::new();
        let mut par_id: BTreeMap<u16, MaterialDef> = BTreeMap::new();
        let mut par_nom = BTreeMap::new();
        let mut details = std::collections::BTreeSet::new();
        for l in &lignes {
            let id = MaterialId::new(l.id);
            if par_id.contains_key(&l.id) || par_nom.insert(l.name.clone(), id).is_some() {
                return Err(MaterialError::Csv {
                    ligne: 0,
                    raison: format!("numéro ou nom en double : {} {}", l.id, l.name),
                });
            }
            let sur = fichier.material.get(&l.name).cloned().unwrap_or_default();
            let render = resoudre(&format!("material.{}", l.name), &sur, &fichier.default)?;
            if let Some(d) = render.detail() {
                details.insert(d.to_owned());
            }
            let ramp = match render.ramp_override() {
                Some(r) => Ramp3::new(srgb.convert(r[0]), srgb.convert(r[1]), srgb.convert(r[2])),
                None => Ramp3::derived_from(srgb.convert(l.color)),
            };
            par_id.insert(
                l.id,
                MaterialDef {
                    id,
                    name: l.name.clone(),
                    category: l.category.clone(),
                    density_kg_m3: l.density,
                    hardness: l.hardness,
                    flammability: l.flammability,
                    base_srgb: l.color,
                    ramp,
                    render,
                },
            );
        }
        if par_id.get(&0).map(|d| d.name.as_str()) != Some("air") {
            return Err(MaterialError::Csv {
                ligne: 0,
                raison: "la classe 0 doit être « air »".into(),
            });
        }
        // classe de repli pour un numéro absent du CSV : magenta bien visible, aspect par défaut
        let inconnue = {
            let sur = RawRender::default();
            let render = resoudre("default", &sur, &fichier.default)?;
            let magenta = srgb.convert([255, 0, 255]);
            MaterialDef {
                id: MaterialId::AIR,
                name: "inconnue".into(),
                category: "unknown".into(),
                density_kg_m3: 0,
                hardness: 0,
                flammability: 0,
                base_srgb: [255, 0, 255],
                ramp: Ramp3::new(magenta, magenta, magenta),
                render,
            }
        };
        let mut h = Fnv64::new();
        h.add(csv_text.as_bytes());
        h.add(&[0xFF]);
        h.add(render_text.as_bytes());
        let version = (h.value() ^ (h.value() >> 32)) as u32;
        Ok(MaterialTable {
            defs: par_id.into_values().collect(),
            par_nom,
            inconnue,
            srgb,
            details: details.into_iter().collect(),
            version,
        })
    }

    /// Classe d'une matière par son nom.
    pub fn by_name(&self, n: &str) -> Option<MaterialId> {
        self.par_nom.get(n).copied()
    }
    /// Définition d'une classe ; une classe absente du CSV donne la classe de repli (magenta).
    pub fn get(&self, id: MaterialId) -> &MaterialDef {
        self.try_get(id).unwrap_or(&self.inconnue)
    }
    /// Définition d'une classe, `None` si absente du CSV.
    pub fn try_get(&self, id: MaterialId) -> Option<&MaterialDef> {
        // `defs` est trié par numéro ; les numéros peuvent avoir des trous
        self.defs
            .binary_search_by_key(&id.get(), |d| d.id.get())
            .ok()
            .map(|i| &self.defs[i])
    }
    /// Toutes les définitions, par numéro croissant.
    pub fn iter(&self) -> impl Iterator<Item = &MaterialDef> {
        self.defs.iter()
    }
    /// Nombre de classes définies.
    pub fn len(&self) -> usize {
        self.defs.len()
    }
    /// Vrai si la table est vide (jamais après `load`, l'air y est toujours).
    pub fn is_empty(&self) -> bool {
        self.defs.is_empty()
    }
    /// Noms des couches de détail demandées, triés ; leur rang est le `detail_layer` du paquet GPU
    /// (L22 les associe aux couches de l'atlas de textures).
    pub fn detail_names(&self) -> &[String] {
        &self.details
    }
    /// Table de conversion sRGB -> linéaire de cette table.
    pub fn srgb(&self) -> &SrgbTable {
        &self.srgb
    }
    /// Empreinte FNV des deux fichiers (changer une donnée change la version).
    pub const fn version(&self) -> u32 {
        self.version
    }
}
