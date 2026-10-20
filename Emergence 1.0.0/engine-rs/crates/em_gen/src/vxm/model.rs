//! `VxmModel` : un modèle `.vxm` chargé, immuable, à six niveaux de détail.

use std::fmt;
use std::path::Path;
use std::sync::{Arc, OnceLock};

use em_core::{Fnv64, Lod, VoxelBox, VoxelCoord, VoxelValue};
use em_voxel::{PutMode, VoxelSink};

use super::classes::{TintTable, VxmClasses};
use super::layer::LodLayer;
use super::meta::VxmMeta;
use super::parse;
use crate::error::{GenError, VxmError};
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};

/// Nombre de niveaux servis : la clipmap en a six (LOD 0 à 5).
pub const LOD_COUNT: usize = 6;

/// Avertissement non fatal du chargement.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum VxmWarning {
    /// Le niveau `requested` manque (absent ou vide) : il est dérivé du niveau plus fin `from`.
    LodFallback {
        /// Niveau demandé.
        requested: Lod,
        /// Niveau plus fin dont il est dérivé.
        from: Lod,
    },
}

impl fmt::Display for VxmWarning {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            VxmWarning::LodFallback { requested, from } => write!(
                f,
                "LOD {requested} absent du fichier : dérivé du LOD {from} (réduction {}×)",
                1_u32 << (requested - from)
            ),
        }
    }
}

struct ModelData {
    meta: VxmMeta,
    flags: u16,
    file_bytes: usize,
    file_lods: Vec<Lod>,
    layers: Vec<LodLayer>,
    warnings: Vec<VxmWarning>,
    fingerprint: OnceLock<u64>,
}

/// Un arbre ou un arbuste chargé depuis un `.vxm`. Se clone à coût nul (données partagées).
#[derive(Clone)]
pub struct VxmModel {
    data: Arc<ModelData>,
}

impl fmt::Debug for VxmModel {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("VxmModel")
            .field("species", &self.data.meta.species())
            .field("lod0_voxels", &self.data.layers[0].voxel_count())
            .finish()
    }
}

impl VxmModel {
    /// Charge un fichier `.vxm` ; refuse tout fichier douteux (voir `VxmError`).
    pub fn load(path: &Path) -> Result<Self, GenError> {
        let octets = std::fs::read(path).map_err(|source| GenError::Io {
            chemin: path.to_owned(),
            source,
        })?;
        Self::from_bytes(&octets).map_err(|source| GenError::Vxm {
            chemin: path.to_owned(),
            source,
        })
    }

    /// Décode des octets `.vxm` déjà en mémoire.
    pub fn from_bytes(octets: &[u8]) -> Result<Self, VxmError> {
        let parse::Decoded {
            flags,
            meta,
            layers: du_fichier,
        } = parse::decode(octets)?;
        let file_lods: Vec<Lod> = du_fichier
            .iter()
            .filter(|l| l.voxel_count() > 0)
            .map(LodLayer::lod)
            .collect();
        if file_lods.first() != Some(&0) {
            return Err(VxmError::LodZeroAbsent);
        }
        let mut layers: Vec<LodLayer> = Vec::with_capacity(LOD_COUNT);
        let mut warnings = Vec::new();
        for lod in 0..LOD_COUNT as Lod {
            if let Some(l) = du_fichier.iter().find(|l| l.lod() == lod && l.voxel_count() > 0) {
                layers.push(l.clone());
                continue;
            }
            // repli : le plus proche niveau plus fin présent, réduit à l'échelle demandée
            let fin = du_fichier
                .iter()
                .rfind(|l| l.lod() < lod && l.voxel_count() > 0)
                .ok_or(VxmError::LodZeroAbsent)?;
            layers.push(fin.reduced(lod, u32::from(lod - fin.lod()))?);
            warnings.push(VxmWarning::LodFallback {
                requested: lod,
                from: fin.lod(),
            });
        }
        Ok(Self {
            data: Arc::new(ModelData {
                meta,
                flags,
                file_bytes: octets.len(),
                file_lods,
                layers,
                warnings,
                fingerprint: OnceLock::new(),
            }),
        })
    }

    /// Métadonnées de l'en-tête.
    pub fn meta(&self) -> &VxmMeta {
        &self.data.meta
    }

    /// Niveaux réellement écrits (non vides) dans le fichier.
    pub fn lods(&self) -> &[Lod] {
        &self.data.file_lods
    }

    /// Niveau `lod` (0..=5) ; les niveaux manquants sont dérivés. `None` au-delà de 5.
    pub fn layer(&self, lod: Lod) -> Option<&LodLayer> {
        self.data.layers.get(usize::from(lod))
    }

    /// Boîte locale (pivot au pied du tronc = (0, 0, 0)) au niveau `lod`, en voxels du niveau. Au-delà du
    /// LOD 5, une boîte vide à l'origine.
    pub fn bounds(&self, lod: Lod) -> VoxelBox {
        self.layer(lod).map_or_else(
            || VoxelBox::new(VoxelCoord::new(0, 0, 0), VoxelCoord::new(0, 0, 0)).expect("boîte vide valide"),
            LodLayer::bounds,
        )
    }

    /// Nombre de voxels pleins au niveau `lod` (0 au-delà du LOD 5).
    pub fn voxel_count(&self, lod: Lod) -> usize {
        self.layer(lod).map_or(0, LodLayer::voxel_count)
    }

    /// Avertissements du chargement (replis de LOD).
    pub fn warnings(&self) -> &[VxmWarning] {
        &self.data.warnings
    }

    /// Taille du fichier lu, en octets.
    pub fn file_bytes(&self) -> usize {
        self.data.file_bytes
    }

    /// Vrai si le fichier porte le canal `sky` (part de ciel).
    pub fn has_sky_channel(&self) -> bool {
        self.data.flags & 2 != 0
    }

    /// Vrai si le fichier porte la palette Python (canal `pal`).
    pub fn has_palette_channel(&self) -> bool {
        self.data.flags & 4 != 0
    }

    /// Mémoire occupée par les voxels des six niveaux, en octets.
    pub fn memory_bytes(&self) -> usize {
        self.data.layers.iter().map(LodLayer::memory_bytes).sum()
    }

    /// Empreinte FNV-1a de tout le contenu servi (niveaux, boîtes, voxels, sortes, variantes), calculée une fois.
    pub fn fingerprint(&self) -> u64 {
        *self.data.fingerprint.get_or_init(|| {
            let mut h = Fnv64::new();
            for (lod, l) in self.data.layers.iter().enumerate() {
                h.add_u64(lod as u64);
                h.add_u64(l.voxel_count() as u64);
                let b = l.bounds();
                for v in [b.min(), b.max()] {
                    h.add(&v.x.to_le_bytes());
                    h.add(&v.y.to_le_bytes());
                    h.add(&v.z.to_le_bytes());
                }
                for c in l.cells() {
                    let mut o = [0_u8; 8];
                    o[0..2].copy_from_slice(&c.x.to_le_bytes());
                    o[2..4].copy_from_slice(&c.y.to_le_bytes());
                    o[4..6].copy_from_slice(&c.z.to_le_bytes());
                    o[6] = c.kind.code();
                    o[7] = c.variant;
                    h.add(&o);
                }
            }
            h.value()
        })
    }
}

impl Generator for VxmModel {
    fn id(&self) -> GeneratorId {
        GeneratorId::VXM
    }

    fn version(&self) -> u32 {
        1
    }

    /// Le plan est le modèle chargé : aucun calcul. La graine est ignorée (le modèle est déjà figé) ;
    /// les paramètres donnent la case d'essence de la teinte.
    fn plan(&self, params: &GenParams, _seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let slot = params.vxm_species_slot()?;
        Ok(Arc::new(VxmPlan {
            model: self.clone(),
            tints: TintTable::new(&VxmClasses::standard(), slot)?,
        }))
    }
}

/// Plan d'un `VxmModel` : rastérise dans le repère local (sans rotation), pivot à l'origine.
pub struct VxmPlan {
    model: VxmModel,
    tints: TintTable,
}

impl VxmPlan {
    /// Valeur de voxel d'une sorte et d'une variante dans ce plan.
    pub fn tint(&self, kind: super::VxmKind, variant: u8) -> VoxelValue {
        self.tints.value(kind, variant)
    }
}

impl GenPlan for VxmPlan {
    fn bounds(&self, lod: Lod) -> VoxelBox {
        self.model.bounds(lod)
    }

    fn rasterize(&self, lod: Lod, window: VoxelBox, sink: &mut dyn VoxelSink) {
        let Some(layer) = self.model.layer(lod) else {
            return;
        };
        let (a, b) = (window.min(), window.max());
        let (lo, hi) = (
            [i64::from(a.x), i64::from(a.y), i64::from(a.z)],
            [i64::from(b.x), i64::from(b.y), i64::from(b.z)],
        );
        for (p, c) in layer.in_window(lo, hi) {
            sink.put(
                VoxelCoord::new(p[0], p[1], p[2]),
                self.tints.value(c.kind, c.variant),
                PutMode::Solid,
            );
        }
    }
}
