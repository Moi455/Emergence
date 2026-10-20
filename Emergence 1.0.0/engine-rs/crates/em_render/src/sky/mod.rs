//! Ciel de Hillaire, nuages, disque solaire, perspective aérienne (port de `web-ocean`, MIT).
//!
//! - [`SkyPass`] : les LUT d'atmosphère (transmittance, diffusion multiple, vue du ciel), recalculées
//!   SEULEMENT quand le soleil ou les paramètres changent ; écrit aussi l'uniforme `Frame` partagé ;
//! - [`SkyBackgroundPass`] : dessine le fond (ciel, nuages, soleil, crêtes, sol, étoiles) en HDR.
//!
//! Ce que les passes suivantes lisent (ressources nommées du graphe) : [`noms`].

mod fond;
mod gpu;
mod lut;
mod params;
pub mod shaders;

pub use fond::SkyBackgroundPass;
pub use gpu::SkyFrame;
pub use lut::SkyPass;
pub use params::{CloudParams, SkyParams, SunModel};

/// Ressources que le ciel publie dans le graphe.
pub mod noms {
    use crate::graph::ResourceName;

    /// Cible HDR (`Rgba16Float`, taille de sortie) : écrite par le fond de ciel, lue par bloom et composition.
    pub const HDR: ResourceName = ResourceName::new("hdr");
    /// Uniforme `Frame` du ciel (176 o), réécrit à chaque image par `SkyPass`.
    pub const FRAME: ResourceName = ResourceName::new("ciel_frame");
    /// LUT de transmittance, 256 x 64 : lumière du soleil atténuée jusqu'à un point (r, mu).
    pub const TRANSMITTANCE: ResourceName = ResourceName::new("ciel_transmittance");
    /// LUT 1D des crêtes lointaines (4096 azimuts), calculée une fois par `SkyPass`.
    pub const CRETES: ResourceName = ResourceName::new("ciel_cretes");
    /// LUT de vue du ciel, 256 x 144 : radiance du ciel par direction ; sert aussi la perspective aérienne.
    pub const VUE_DU_CIEL: ResourceName = ResourceName::new("ciel_vue");
}
