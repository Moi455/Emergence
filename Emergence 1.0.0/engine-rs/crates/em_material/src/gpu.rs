//! Paquet GPU de matières (docs/19a § 5.3). Les flottants apparaissent ICI et seulement ici : chaque `f32` est
//! une valeur Q16 divisée par 65 536 (division exacte), donc le paquet est identique octet pour octet partout.
#![allow(clippy::float_arithmetic)]

use crate::color::{LinearRgb, Ramp3};
use crate::table::{CLASS_COUNT, MaterialTable};
use crate::tint::TintMode;
use crate::vegetation::{MAX_RAMPS_PER_ROLE, MAX_SPECIES, RampRole, VegetationRamps};
use em_core::digest::Fnv64;
use em_core::q16::Q16;

/// Texte WGSL de la matière (struct miroir, constantes, décodage des teintes, rampes), complété par L10 et L22.
pub const MATERIAL_WGSL: &str = include_str!("material.wgsl");

/// Valeur de `detail_layer` quand la classe n'a pas de détail.
pub const NO_DETAIL: u32 = u32::MAX;

/// Disposition GPU d'une matière : 64 octets, 512 entrées, indice = classe (docs/19a § 5.3).
#[repr(C)]
#[derive(Copy, Clone, Debug, Default, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub struct MaterialGpu {
    pub albedo_linear: [f32; 3],
    pub albedo_var: f32,
    pub hue_var: f32,
    pub voxel_jitter: f32,
    pub roughness: f32,
    pub roughness_var: f32,
    pub relief: f32,
    pub detail_strength: f32,
    pub detail_scale_m: f32,
    pub translucency: f32,
    pub emission: f32,
    pub detail_layer: u32,
    pub tint_mode: u32,
    pub flags: u32,
}

/// Q16 -> f32, exact (les valeurs d'aspect tiennent sur moins de 24 bits).
fn f(q: Q16) -> f32 {
    q.raw() as f32 / 65_536.0
}

fn vec4(c: LinearRgb) -> [f32; 4] {
    let [r, g, b] = c.channels();
    [f(r), f(g), f(b), 0.0]
}

fn ramp_vec4(r: &Ramp3) -> [[f32; 4]; 3] {
    let c = r.colors();
    [vec4(c[0]), vec4(c[1]), vec4(c[2])]
}

impl MaterialTable {
    /// Les 512 entrées du tampon `materials` (indice = classe). Une classe absente du CSV reçoit la classe de repli.
    pub fn gpu_entries(&self) -> Vec<MaterialGpu> {
        (0..CLASS_COUNT as u16)
            .map(|c| {
                let id = em_core::ids::MaterialId::new(c);
                let def = self.get(id);
                let r = def.render();
                let mid = def.ramp().colors()[1].channels();
                let detail_layer = r
                    .detail()
                    .and_then(|d| self.detail_names().iter().position(|n| n == d))
                    .map_or(NO_DETAIL, |i| i as u32);
                MaterialGpu {
                    albedo_linear: [f(mid[0]), f(mid[1]), f(mid[2])],
                    albedo_var: f(r.albedo_var()),
                    hue_var: f(r.hue_var()),
                    voxel_jitter: f(r.voxel_jitter()),
                    roughness: f(r.roughness()),
                    roughness_var: f(r.roughness_var()),
                    relief: f(r.relief()),
                    detail_strength: f(r.detail_strength()),
                    detail_scale_m: f(r.detail_scale_m()),
                    translucency: f(r.translucency()),
                    emission: f(r.emission()),
                    detail_layer,
                    tint_mode: r.tint_mode().code(),
                    flags: r.flags().bits(),
                }
            })
            .collect()
    }

    /// Le tampon `class_ramps` : 3 couleurs (sombre, moyen, clair) par classe, soit 1 536 `vec4`.
    pub fn class_ramps(&self) -> Vec<[f32; 4]> {
        (0..CLASS_COUNT as u16)
            .flat_map(|c| ramp_vec4(self.get(em_core::ids::MaterialId::new(c)).ramp()))
            .collect()
    }
}

/// Rôle « aucun » dans `class_extra` : la classe n'a pas de rampe de végétation.
pub const NO_ROLE: u32 = 255;

impl MaterialTable {
    /// Le tampon `class_extra` (L09) : par classe, `[graine basse, graine haute, rôle de rampe, 0]`. La graine
    /// de classe est un `u64` (le shader n'a pas d'entier 64 bits : deux mots), le rôle vaut 0 à 3
    /// (écorce, feuilles, fleurs, fruits) ou [`NO_ROLE`]. Hors du paquet : son empreinte épinglée ne bouge pas.
    pub fn gpu_class_extra(&self) -> Vec<[u32; 4]> {
        (0..CLASS_COUNT as u16)
            .map(|c| {
                let def = self.get(em_core::ids::MaterialId::new(c));
                let graine = def.class_seed();
                let role = def.render().veg_role().map_or(NO_ROLE, |r| r.index() as u32);
                [graine as u32, (graine >> 32) as u32, role, 0]
            })
            .collect()
    }
}

impl MaterialTable {
    /// Comme `gpu_class_extra`, avec le MODE de matière de chaque classe dans le mot `w` (0 continu, 1 VoxelPixel).
    pub fn gpu_class_extra_styled(&self, style: &crate::style::StyleSheet) -> Vec<[u32; 4]> {
        let mut extra = self.gpu_class_extra();
        for (e, mode) in extra.iter_mut().zip(style.gpu_modes()) {
            e[3] = mode;
        }
        extra
    }
}

impl crate::style::StyleSheet {
    /// Le tampon `pixel_params` : deux `vec4` par classe, `[block_spread, hue_spread, voxel_jitter, joint_tone]`
    /// puis `[ring_contrast, run_contrast, 0, 0]` (Q16 / 65 536, exact).
    pub fn gpu_pixel_params(&self) -> Vec<[f32; 4]> {
        (0..CLASS_COUNT as u16)
            .flat_map(|c| {
                let p = self.params_of(em_core::ids::MaterialId::new(c));
                [
                    [
                        f(p.block_spread),
                        f(p.hue_spread),
                        f(p.voxel_jitter),
                        f(p.joint_tone),
                    ],
                    [f(p.ring_contrast), f(p.run_contrast), 0.0, 0.0],
                ]
            })
            .collect()
    }
}

impl VegetationRamps {
    /// Nombre de rampes par (essence, rôle), indice `essence × 4 + rôle` (32 × 4 `u32`) : le shader en a besoin
    /// pour convertir le tirage continu des feuilles en numéro de rampe, et pour borner un numéro explicite.
    pub fn gpu_counts(&self) -> Vec<u32> {
        let mut out = vec![0_u32; MAX_SPECIES * RampRole::ALL.len()];
        for espece in 0..self.species_count() {
            for role in RampRole::ALL {
                out[espece * 4 + role.index()] = self.ramps(espece as u8, role).len() as u32;
            }
        }
        out
    }

    /// Le tampon `veg_ramps` : indice `((essence × 4 + rôle) × 4 + rampe) × 3 + couleur`, 32 × 4 × 4 × 3 `vec4`
    /// (19a § 5.3). Les rampes absentes valent zéro.
    pub fn gpu_data(&self) -> Vec<[f32; 4]> {
        let mut out = vec![[0.0; 4]; MAX_SPECIES * RampRole::ALL.len() * MAX_RAMPS_PER_ROLE * 3];
        for espece in 0..self.species_count() {
            for role in RampRole::ALL {
                for (r, rampe) in self.ramps(espece as u8, role).iter().enumerate() {
                    let base = ((espece * 4 + role.index()) * 4 + r) * 3;
                    out[base..base + 3].copy_from_slice(&ramp_vec4(rampe));
                }
            }
        }
        out
    }
    /// Une graine de matière par essence (32 `u32`, 0 pour une case non attribuée).
    pub fn gpu_seeds(&self) -> Vec<u32> {
        (0..MAX_SPECIES).map(|i| self.seed_of(i as u8)).collect()
    }
}

/// L'ensemble des tampons de matière prêts à téléverser : les octets sont déterministes.
#[derive(Clone, Debug)]
pub struct GpuMaterialPacket {
    materials: Vec<MaterialGpu>,
    class_ramps: Vec<[f32; 4]>,
    veg_ramps: Vec<[f32; 4]>,
    veg_seeds: Vec<u32>,
    version: u32,
}

impl GpuMaterialPacket {
    /// Assemble le paquet depuis la table et les rampes de végétation de la saison courante.
    pub fn new(table: &MaterialTable, vegetation: &VegetationRamps) -> Self {
        GpuMaterialPacket {
            materials: table.gpu_entries(),
            class_ramps: table.class_ramps(),
            veg_ramps: vegetation.gpu_data(),
            veg_seeds: vegetation.gpu_seeds(),
            version: table.version(),
        }
    }
    /// Octets du tampon `materials` (512 × 64).
    pub fn material_bytes(&self) -> &[u8] {
        bytemuck::cast_slice(&self.materials)
    }
    /// Octets du tampon `class_ramps`.
    pub fn class_ramp_bytes(&self) -> &[u8] {
        bytemuck::cast_slice(&self.class_ramps)
    }
    /// Octets du tampon `veg_ramps`.
    pub fn veg_ramp_bytes(&self) -> &[u8] {
        bytemuck::cast_slice(&self.veg_ramps)
    }
    /// Octets du tampon des graines d'essence.
    pub fn veg_seed_bytes(&self) -> &[u8] {
        bytemuck::cast_slice(&self.veg_seeds)
    }
    /// Version des fichiers de données dont le paquet est issu.
    pub const fn version(&self) -> u32 {
        self.version
    }
    /// Taille totale des quatre tampons, en octets.
    pub fn total_bytes(&self) -> usize {
        self.material_bytes().len()
            + self.class_ramp_bytes().len()
            + self.veg_ramp_bytes().len()
            + self.veg_seed_bytes().len()
    }
    /// Empreinte FNV-64 des quatre tampons (avec leurs longueurs) et de la version : à épingler dans les tests.
    pub fn fingerprint(&self) -> u64 {
        let mut h = Fnv64::new();
        h.add_u64(u64::from(self.version));
        for tampon in [
            self.material_bytes(),
            self.class_ramp_bytes(),
            self.veg_ramp_bytes(),
            self.veg_seed_bytes(),
        ] {
            h.add_u64(tampon.len() as u64);
            h.add(tampon);
        }
        h.value()
    }
}

/// Garde de compilation : le code GPU des modes de teinte suit `TintMode::code`.
const _: () = assert!(TintMode::Terrain as u32 == 4);
const _: () = assert!(std::mem::size_of::<MaterialGpu>() == 64);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wgsl_miroir_de_la_struct() {
        // 14 champs dans la struct WGSL (vec3 + 13 scalaires = 16 mots)
        assert!(MATERIAL_WGSL.contains("struct MaterialGpu"));
        for champ in [
            "albedo_linear",
            "albedo_var",
            "hue_var",
            "voxel_jitter",
            "roughness",
            "roughness_var",
            "relief",
            "detail_strength",
            "detail_scale_m",
            "translucency",
            "emission",
            "detail_layer",
            "tint_mode",
            "flags",
        ] {
            assert!(MATERIAL_WGSL.contains(champ), "{champ}");
        }
    }
}
