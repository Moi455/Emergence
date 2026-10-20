//! Identifiants : `EntityId` (22 bits de case + 10 bits de génération, comme `engine/act/entity_id.h`),
//! `MaterialId` (classe de matière sur 9 bits) et `VoxelValue` (classe 9 bits << 7 | teinte 7 bits).
//! Les champs sont privés : l'invariant est vérifié à la construction.

use crate::error::CoreError;

/// Nombre de bits de la case dans un `EntityId`.
const BITS_CASE: u32 = 22;
/// Masque de la case.
const MASQUE_CASE: u32 = (1 << BITS_CASE) - 1;
/// Plus grande génération (10 bits).
const GENERATION_MAX: u32 = (1 << 10) - 1;

/// Identifiant objectif et stable d'une entité : `génération << 22 | case`, case ≥ 1 (0 = « aucune »).
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct EntityId(u32);

impl EntityId {
    /// Aucune entité (valeur brute 0).
    pub const NONE: EntityId = EntityId(0);

    /// Construit un identifiant. Panique si la case n'est pas dans 1..=4 194 303 ou si la génération dépasse 1023.
    pub const fn new(slot: u32, generation: u32) -> Self {
        assert!(
            slot != 0 && slot <= MASQUE_CASE,
            "case d'entité hors de 1..=4194303"
        );
        assert!(
            generation <= GENERATION_MAX,
            "génération d'entité hors de 0..=1023"
        );
        EntityId((generation << BITS_CASE) | slot)
    }
    /// Variante sans panique de `new`.
    pub fn try_new(slot: u32, generation: u32) -> Result<Self, CoreError> {
        if !(1..=MASQUE_CASE).contains(&slot) {
            return Err(CoreError::CaseEntiteInvalide(slot));
        }
        if generation > GENERATION_MAX {
            return Err(CoreError::GenerationInvalide(generation));
        }
        Ok(EntityId((generation << BITS_CASE) | slot))
    }
    /// Reconstruit depuis les 32 bits bruts (charge d'opération, fichier). 0 donne `NONE`.
    pub fn try_from_raw(raw: u32) -> Result<Self, CoreError> {
        if raw == 0 || raw & MASQUE_CASE != 0 {
            Ok(EntityId(raw))
        } else {
            Err(CoreError::IdentifiantBrutInvalide(raw))
        }
    }
    /// Les 32 bits bruts.
    pub const fn raw(self) -> u32 {
        self.0
    }
    /// Numéro de case (1-based ; 0 pour `NONE`).
    pub const fn slot(self) -> u32 {
        self.0 & MASQUE_CASE
    }
    /// Génération de la case.
    pub const fn generation(self) -> u32 {
        self.0 >> BITS_CASE
    }
    /// Vrai pour `NONE`.
    pub const fn is_none(self) -> bool {
        self.0 == 0
    }
}

/// Classe de matière (9 bits, 0 = air).
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct MaterialId(u16);

impl MaterialId {
    /// Plus grande classe représentable.
    pub const MAX: u16 = 511;
    /// L'air.
    pub const AIR: MaterialId = MaterialId(0);

    /// Construit une classe. Panique au-delà de 511.
    pub const fn new(classe: u16) -> Self {
        assert!(classe <= Self::MAX, "classe de matière hors de 0..=511");
        MaterialId(classe)
    }
    /// Variante sans panique de `new`.
    pub fn try_new(classe: u16) -> Result<Self, CoreError> {
        if classe > Self::MAX {
            Err(CoreError::MatiereInvalide(classe))
        } else {
            Ok(MaterialId(classe))
        }
    }
    /// Valeur numérique de la classe.
    pub const fn get(self) -> u16 {
        self.0
    }
}

/// Valeur d'un voxel : classe de matière (9 bits) << 7 | teinte (7 bits).
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct VoxelValue(u16);

impl VoxelValue {
    /// L'air (classe 0, teinte 0).
    pub const AIR: VoxelValue = VoxelValue(0);
    /// Plus grande teinte (7 bits).
    pub const TINT_MAX: u8 = 127;

    /// Assemble une matière et une teinte. Panique si la teinte dépasse 127.
    pub const fn new(m: MaterialId, tint: u8) -> Self {
        assert!(tint <= Self::TINT_MAX, "teinte hors de 0..=127");
        VoxelValue((m.0 << 7) | tint as u16)
    }
    /// Reconstruit depuis les 16 bits bruts (tout `u16` est valide).
    pub const fn from_raw(raw: u16) -> Self {
        VoxelValue(raw)
    }
    /// Les 16 bits bruts.
    pub const fn raw(self) -> u16 {
        self.0
    }
    /// Classe de matière.
    pub const fn material(self) -> MaterialId {
        MaterialId(self.0 >> 7)
    }
    /// Teinte (7 bits).
    pub const fn tint(self) -> u8 {
        (self.0 & 0x7F) as u8
    }
    /// Vrai pour l'air (classe 0), quelle que soit la teinte.
    pub const fn is_air(self) -> bool {
        self.0 >> 7 == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn entite_aller_retour() {
        let id = EntityId::new(123, 5);
        assert_eq!((id.slot(), id.generation()), (123, 5));
        assert_eq!(EntityId::try_from_raw(id.raw()), Ok(id));
        assert!(EntityId::try_new(0, 0).is_err());
        assert!(EntityId::try_new(1, 1024).is_err());
        assert!(EntityId::try_from_raw(1 << 22).is_err());
        assert!(EntityId::NONE.is_none());
    }

    #[test]
    fn voxel_valeur() {
        let v = VoxelValue::new(MaterialId::new(31), 100);
        assert_eq!((v.material().get(), v.tint()), (31, 100));
        assert!(VoxelValue::AIR.is_air());
        assert!(MaterialId::try_new(512).is_err());
    }
}
