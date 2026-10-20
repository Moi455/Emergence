//! Rampes de végétation par essence (docs/19a § 5.3) : l'essence tient sur 5 bits de teinte (32 cases),
//! chaque essence a quatre rôles (écorce, feuilles, fleurs, fruits) et jusqu'à quatre rampes par rôle.

use crate::color::{LinearRgb, Ramp3, SrgbTable};
use crate::error::MaterialError;
use em_core::digest::Fnv64;

/// Nombre maximal d'essences (5 bits de teinte).
pub const MAX_SPECIES: usize = 32;
/// Nombre maximal de rampes par rôle (2 bits de teinte).
pub const MAX_RAMPS_PER_ROLE: usize = 4;
/// Nombre maximal de rampes de fruits (la rampe de fruit ne dépasse pas 2).
pub const MAX_FRUIT_RAMPS: usize = 2;

/// Rôle d'une rampe de végétation. L'ordre (0 à 3) est celui du tampon GPU.
#[derive(Copy, Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RampRole {
    /// Écorce (variantes : écorce, écorce secondaire, rameau).
    Bark = 0,
    /// Feuilles (rampe tirée au shader par un bruit lent).
    Leaves = 1,
    /// Fleurs (jusqu'à quatre rampes).
    Flowers = 2,
    /// Fruits (jusqu'à deux rampes).
    Fruits = 3,
}

impl RampRole {
    /// Tous les rôles, dans l'ordre du tampon GPU.
    pub const ALL: [RampRole; 4] = [
        RampRole::Bark,
        RampRole::Leaves,
        RampRole::Flowers,
        RampRole::Fruits,
    ];

    /// Indice 0..3 du rôle.
    pub const fn index(self) -> usize {
        self as usize
    }
    /// Nombre maximal de rampes pour ce rôle.
    pub const fn max_ramps(self) -> usize {
        match self {
            RampRole::Fruits => MAX_FRUIT_RAMPS,
            _ => MAX_RAMPS_PER_ROLE,
        }
    }
    /// Lit le nom écrit dans `material_render.toml` (`veg_role`).
    pub fn from_name(nom: &str) -> Option<RampRole> {
        RampRole::ALL.into_iter().find(|r| r.name() == nom)
    }
    /// Nom du rôle dans les fichiers de données.
    pub const fn name(self) -> &'static str {
        match self {
            RampRole::Bark => "bark",
            RampRole::Leaves => "leaves",
            RampRole::Flowers => "flowers",
            RampRole::Fruits => "fruits",
        }
    }
}

/// Une essence : sa clé, sa graine de matière et ses rampes par rôle (couleurs déjà en linéaire).
#[derive(Clone, Debug, PartialEq, Eq)]
struct Species {
    key: String,
    seed: u32,
    roles: [Vec<Ramp3>; 4],
}

/// Registre des rampes de végétation pour la saison courante. Une saison réécrit les rampes
/// (même clé et même rôle : remplacement) ; la case d'une essence ne change jamais une fois attribuée.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VegetationRamps {
    srgb: SrgbTable,
    species: Vec<Species>,
}

impl VegetationRamps {
    /// Registre vide.
    pub fn new() -> Self {
        VegetationRamps {
            srgb: SrgbTable::new(),
            species: Vec::new(),
        }
    }

    /// Enregistre (ou remplace) les rampes d'un rôle pour l'essence `species_key` et renvoie sa case (0..31).
    /// Chaque rampe est `[sombre, moyen, clair]` en sRGB 8 bits. Erreur claire au-delà de 32 essences
    /// ou si le rôle reçoit trop de rampes.
    pub fn register(
        &mut self,
        species_key: &str,
        role: RampRole,
        ramps: &[[[u8; 3]; 3]],
    ) -> Result<u8, MaterialError> {
        if ramps.len() > role.max_ramps() {
            return Err(MaterialError::TropDeRampes {
                cle: species_key.to_owned(),
                demande: ramps.len(),
                max: role.max_ramps(),
            });
        }
        let case = match self.species.iter().position(|s| s.key == species_key) {
            Some(i) => i,
            None => {
                if self.species.len() >= MAX_SPECIES {
                    return Err(MaterialError::TropDEssences {
                        max: MAX_SPECIES,
                        cle: species_key.to_owned(),
                        rang: self.species.len() + 1,
                    });
                }
                let mut h = Fnv64::new();
                h.add(species_key.as_bytes());
                self.species.push(Species {
                    key: species_key.to_owned(),
                    seed: h.value() as u32,
                    roles: Default::default(),
                });
                self.species.len() - 1
            }
        };
        let converties: Vec<Ramp3> = ramps
            .iter()
            .map(|r| {
                Ramp3::new(
                    self.srgb.convert(r[0]),
                    self.srgb.convert(r[1]),
                    self.srgb.convert(r[2]),
                )
            })
            .collect();
        self.species[case].roles[role.index()] = converties;
        Ok(case as u8)
    }

    /// Nombre d'essences enregistrées.
    pub fn species_count(&self) -> usize {
        self.species.len()
    }
    /// Case d'une essence par sa clé.
    pub fn species_case(&self, key: &str) -> Option<u8> {
        self.species.iter().position(|s| s.key == key).map(|i| i as u8)
    }
    /// Graine de matière de l'essence (hachage de son nom) ; 0 pour une case non attribuée.
    pub fn seed_of(&self, case: u8) -> u32 {
        self.species.get(usize::from(case)).map_or(0, |s| s.seed)
    }
    /// Rampes d'un rôle pour une case ; vide si la case ou le rôle n'est pas enregistré.
    pub fn ramps(&self, case: u8, role: RampRole) -> &[Ramp3] {
        self.species
            .get(usize::from(case))
            .map_or(&[][..], |s| &s.roles[role.index()])
    }
    /// Vrai tant qu'aucune essence n'est enregistrée.
    pub fn is_empty(&self) -> bool {
        self.species.is_empty()
    }
    /// Couleur moyenne d'une rampe, ou noir si absente (aide de test).
    pub fn mid_color(&self, case: u8, role: RampRole, ramp: usize) -> LinearRgb {
        self.ramps(case, role)
            .get(ramp)
            .map_or(LinearRgb::BLACK, |r| r.colors()[1])
    }
}

impl Default for VegetationRamps {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const R: [[u8; 3]; 3] = [[20, 40, 10], [60, 120, 30], [140, 200, 80]];

    #[test]
    fn cases_stables_et_remplacement() {
        let mut v = VegetationRamps::new();
        assert_eq!(v.register("chene", RampRole::Leaves, &[R, R]).unwrap(), 0);
        assert_eq!(v.register("bouleau", RampRole::Leaves, &[R]).unwrap(), 1);
        assert_eq!(v.register("chene", RampRole::Bark, &[R]).unwrap(), 0);
        assert_eq!(v.ramps(0, RampRole::Leaves).len(), 2);
        v.register("chene", RampRole::Leaves, &[R, R, R]).unwrap();
        assert_eq!(v.ramps(0, RampRole::Leaves).len(), 3);
        assert_eq!(v.species_case("bouleau"), Some(1));
        assert!(v.seed_of(0) != v.seed_of(1));
        assert_eq!(v.seed_of(9), 0);
    }

    #[test]
    fn trente_deux_essences_au_plus() {
        let mut v = VegetationRamps::new();
        for i in 0..MAX_SPECIES {
            v.register(&format!("e{i}"), RampRole::Bark, &[R]).unwrap();
        }
        let e = v.register("de_trop", RampRole::Bark, &[R]).unwrap_err();
        assert!(matches!(e, MaterialError::TropDEssences { max: 32, .. }));
        assert!(e.to_string().contains("33"));
        // une essence déjà connue reste modifiable
        assert!(v.register("e3", RampRole::Leaves, &[R]).is_ok());
    }

    #[test]
    fn rampes_par_role_bornees() {
        let mut v = VegetationRamps::new();
        assert!(v.register("pommier", RampRole::Fruits, &[R, R, R]).is_err());
        assert!(
            v.register("pommier", RampRole::Flowers, &[R, R, R, R, R])
                .is_err()
        );
        assert!(v.register("pommier", RampRole::Fruits, &[R, R]).is_ok());
        assert!(v.is_empty() || v.species_count() == 1);
    }
}
