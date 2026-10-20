//! Les deux traits d'un générateur paramétrique (docs/19 § 2.5) : un plan coûteux fait une fois, une
//! rastérisation paresseuse fenêtre par fenêtre. Le chargeur `.vxm` est le premier générateur : son plan
//! est le modèle déjà chargé, sans calcul.

use std::sync::Arc;

use em_core::{Lod, VoxelBox};
use em_voxel::VoxelSink;

use crate::error::GenError;

/// Identifiant d'un générateur. Registre **en ajout seul** : on ne renumérote jamais.
#[derive(Copy, Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct GeneratorId(u16);

impl GeneratorId {
    /// Le chargeur de modèles `.vxm` (pont avec les générateurs Python).
    pub const VXM: GeneratorId = GeneratorId(1);

    /// Valeur brute (pour les paquets et les journaux).
    pub const fn raw(self) -> u16 {
        self.0
    }
}

/// Paramètres décodés d'un générateur : le générateur visé, sa version et des octets bruts **privés**,
/// lus par des accesseurs typés propres à chaque générateur (docs/19a § 8).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GenParams {
    generator: GeneratorId,
    version: u32,
    bytes: Vec<u8>,
}

impl GenParams {
    /// Paramètres bruts d'un générateur.
    pub fn new(generator: GeneratorId, version: u32, bytes: Vec<u8>) -> Self {
        Self {
            generator,
            version,
            bytes,
        }
    }

    /// Paramètres du chargeur `.vxm` : la case d'essence (5 bits de teinte, 0..=31).
    pub fn vxm(species_slot: u8) -> Result<Self, GenError> {
        if species_slot > 31 {
            return Err(GenError::UnknownSpecies(species_slot));
        }
        Ok(Self::new(GeneratorId::VXM, 1, vec![species_slot]))
    }

    /// Générateur visé.
    pub const fn generator(&self) -> GeneratorId {
        self.generator
    }

    /// Version des paramètres.
    pub const fn version(&self) -> u32 {
        self.version
    }

    /// Case d'essence d'un paquet de paramètres `.vxm`.
    pub fn vxm_species_slot(&self) -> Result<u8, GenError> {
        match (self.generator, self.bytes.as_slice()) {
            (GeneratorId::VXM, [slot]) if *slot <= 31 => Ok(*slot),
            (GeneratorId::VXM, _) => Err(GenError::BadParams(
                "paramètres .vxm : un octet de case d'essence (0..=31) attendu".into(),
            )),
            (autre, _) => Err(GenError::BadParams(format!(
                "paramètres du générateur {} donnés au chargeur .vxm",
                autre.raw()
            ))),
        }
    }
}

/// Un générateur paramétrique.
pub trait Generator: Send + Sync {
    /// Identifiant dans le registre en ajout seul.
    fn id(&self) -> GeneratorId;
    /// Change quand la sortie change (invalide les caches).
    fn version(&self) -> u32;
    /// Plan pour ces paramètres et cette graine.
    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError>;
}

/// Le plan d'un générateur : de quoi rastériser à n'importe quel niveau.
pub trait GenPlan: Send + Sync {
    /// Boîte du plan au niveau `lod`, repère local (pivot au pied du tronc), en voxels du niveau.
    fn bounds(&self, lod: Lod) -> VoxelBox;
    /// Écrit dans `sink` les voxels du niveau `lod` qui tombent dans `window` (repère local, voxels du niveau).
    fn rasterize(&self, lod: Lod, window: VoxelBox, sink: &mut dyn VoxelSink);
}
