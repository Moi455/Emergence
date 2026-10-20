//! Rendu wgpu : contexte GPU, cibles, graphe de passes, profileur, captures, passes de lumière.
//!
//! L03 : ciel de Hillaire (`sky`), bloom et composition AgX (`post`), portés de `web-ocean` (MIT).
//!
//! L02 : hôte de rendu (adaptateur explicite, limites explicites, cibles hors écran et fenêtre,
//! profileur par horodatages, PNG déterministe, graphe de passes orienté objet).

#![forbid(unsafe_code)]

pub mod camera;
pub mod capture;
pub mod error;
mod exec;
pub mod gpu;
pub mod graph;
pub mod hello;
mod liaisons;
pub mod partage;
pub mod post;
pub mod profiler;
pub mod sky;
pub mod target;
pub mod voxel;

pub use camera::{Camera, FrameContext, ViewBasis};
pub use capture::{RgbaImage, read_texture, read_texture_png};
pub use error::{CaptureError, GpuError, GraphError, ParamError, TargetError, WorldError};
pub use glam;
pub use gpu::{AdapterReport, DeviceRequirements, GpuContext, GpuRequest};
pub use graph::{PassContext, PassName, PassSetup, RenderGraph, RenderPass, ResourceName, Resources};
pub use liaisons::HDR_FORMAT;
pub use partage::Partage;
pub use post::{BloomPass, PostParams, TonemapPass};
pub use profiler::{GpuProfiler, PassTiming, ProfileReport};
pub use sky::{CloudParams, SkyBackgroundPass, SkyParams, SkyPass, SunModel};
pub use target::{FrameTarget, OffscreenTarget, TargetFrame, WindowTarget};
pub use voxel::{
    ChunkFlags, ClipmapConfig, ClipmapStreamer, DebugView, DepthMergePass, GpuMaterials, LightSettings,
    LightingPass, Projection, VoxelCamera, VoxelGpuWorld, VoxelMaterialPass, VoxelTracePass,
};
pub use wgpu;
