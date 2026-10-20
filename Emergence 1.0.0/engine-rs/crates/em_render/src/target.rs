//! Cibles d'image : hors écran (texture) ou fenêtre (surface). Le même code d'image passe derrière
//! le trait `FrameTarget` (docs/19 § 7.2).

use crate::error::TargetError;
use crate::gpu::GpuContext;

/// Image à dessiner : la vue de la texture de sortie (fenêtre ou hors écran).
pub struct TargetFrame {
    view: wgpu::TextureView,
    format: wgpu::TextureFormat,
    size: (u32, u32),
    surface_texture: Option<wgpu::SurfaceTexture>,
}

impl TargetFrame {
    /// Vue à utiliser comme pièce jointe de couleur.
    pub fn view(&self) -> &wgpu::TextureView {
        &self.view
    }

    /// Format de la texture de sortie.
    pub fn format(&self) -> wgpu::TextureFormat {
        self.format
    }

    /// Dimensions en pixels.
    pub fn size(&self) -> (u32, u32) {
        self.size
    }
}

/// Destination des images du graphe.
pub trait FrameTarget {
    /// Dimensions en pixels.
    fn size(&self) -> (u32, u32);
    /// Format de couleur de la sortie (toujours sRGB : le matériel encode à l'écriture).
    fn format(&self) -> wgpu::TextureFormat;
    /// Prend l'image à dessiner.
    fn acquire(&mut self) -> Result<TargetFrame, TargetError>;
    /// Rend l'image après soumission des commandes.
    fn present(&mut self, frame: TargetFrame);
}

fn verifie_dimensions(gpu: &GpuContext, largeur: u32, hauteur: u32) -> Result<(), TargetError> {
    let maximum = gpu.device().limits().max_texture_dimension_2d;
    if largeur == 0 || hauteur == 0 || largeur > maximum || hauteur > maximum {
        return Err(TargetError::Dimensions {
            largeur,
            hauteur,
            maximum,
        });
    }
    Ok(())
}

/// Cible hors écran : une texture sRGB lisible (`COPY_SRC`), sans fenêtre.
pub struct OffscreenTarget {
    texture: wgpu::Texture,
    format: wgpu::TextureFormat,
    size: (u32, u32),
}

impl OffscreenTarget {
    /// Format hors écran par défaut.
    pub const FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8UnormSrgb;

    /// Crée une cible `largeur` x `hauteur` au format par défaut.
    pub fn new(gpu: &GpuContext, largeur: u32, hauteur: u32) -> Result<Self, TargetError> {
        Self::avec_format(gpu, largeur, hauteur, Self::FORMAT)
    }

    /// Crée une cible avec un format sRGB donné (la capture depuis la fenêtre reprend celui de la surface).
    pub fn avec_format(
        gpu: &GpuContext,
        largeur: u32,
        hauteur: u32,
        format: wgpu::TextureFormat,
    ) -> Result<Self, TargetError> {
        verifie_dimensions(gpu, largeur, hauteur)?;
        let texture = gpu.device().create_texture(&wgpu::TextureDescriptor {
            label: Some("cible hors écran"),
            size: wgpu::Extent3d {
                width: largeur,
                height: hauteur,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        Ok(Self {
            texture,
            format,
            size: (largeur, hauteur),
        })
    }

    /// Texture de sortie (pour la lecture et le PNG).
    pub fn texture(&self) -> &wgpu::Texture {
        &self.texture
    }
}

impl FrameTarget for OffscreenTarget {
    fn size(&self) -> (u32, u32) {
        self.size
    }

    fn format(&self) -> wgpu::TextureFormat {
        self.format
    }

    fn acquire(&mut self) -> Result<TargetFrame, TargetError> {
        Ok(TargetFrame {
            view: self.texture.create_view(&wgpu::TextureViewDescriptor::default()),
            format: self.format,
            size: self.size,
            surface_texture: None,
        })
    }

    fn present(&mut self, _frame: TargetFrame) {}
}

/// Cible fenêtre : une surface `wgpu` configurée en sRGB.
pub struct WindowTarget {
    surface: wgpu::Surface<'static>,
    config: wgpu::SurfaceConfiguration,
    device: wgpu::Device,
    queue: wgpu::Queue,
}

impl WindowTarget {
    /// Crée la cible sur une surface déjà créée avec l'instance du `GpuContext`.
    pub fn new(
        gpu: &GpuContext,
        surface: wgpu::Surface<'static>,
        largeur: u32,
        hauteur: u32,
    ) -> Result<Self, TargetError> {
        verifie_dimensions(gpu, largeur.max(1), hauteur.max(1))?;
        if !gpu.adapter().is_surface_supported(&surface) {
            return Err(TargetError::Surface(
                "l'adaptateur retenu ne peut pas présenter dans cette fenêtre (essayer __NV_PRIME_RENDER_OFFLOAD=1)".into(),
            ));
        }
        let caps = surface.get_capabilities(gpu.adapter());
        let format = caps
            .formats
            .iter()
            .copied()
            .find(|f| {
                matches!(
                    f,
                    wgpu::TextureFormat::Bgra8UnormSrgb | wgpu::TextureFormat::Rgba8UnormSrgb
                )
            })
            .ok_or_else(|| {
                TargetError::Surface(format!("aucun format sRGB 8 bits parmi {:?}", caps.formats))
            })?;
        let mode = if caps.present_modes.contains(&wgpu::PresentMode::Fifo) {
            wgpu::PresentMode::Fifo
        } else {
            caps.present_modes[0]
        };
        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            width: largeur.max(1),
            height: hauteur.max(1),
            present_mode: mode,
            desired_maximum_frame_latency: 2,
            alpha_mode: caps.alpha_modes[0],
            view_formats: vec![],
            color_space: wgpu::SurfaceColorSpace::default(),
        };
        surface.configure(gpu.device(), &config);
        Ok(Self {
            surface,
            config,
            device: gpu.device().clone(),
            queue: gpu.queue().clone(),
        })
    }

    /// Reconfigure la surface après un changement de taille de la fenêtre.
    pub fn redimensionner(&mut self, largeur: u32, hauteur: u32) {
        if largeur == 0 || hauteur == 0 {
            return;
        }
        self.config.width = largeur;
        self.config.height = hauteur;
        self.surface.configure(&self.device, &self.config);
    }
}

impl FrameTarget for WindowTarget {
    fn size(&self) -> (u32, u32) {
        (self.config.width, self.config.height)
    }

    fn format(&self) -> wgpu::TextureFormat {
        self.config.format
    }

    fn acquire(&mut self) -> Result<TargetFrame, TargetError> {
        use wgpu::CurrentSurfaceTexture as S;
        let st = match self.surface.get_current_texture() {
            S::Success(t) => t,
            S::Suboptimal(t) => {
                // Dessinable ; on reconfigure à la prochaine occasion pour retrouver la taille exacte.
                self.surface.configure(&self.device, &self.config);
                t
            }
            S::Timeout => return Err(TargetError::Sautee("délai d'attente de la surface")),
            S::Occluded => return Err(TargetError::Sautee("fenêtre masquée")),
            S::Outdated => {
                self.surface.configure(&self.device, &self.config);
                return Err(TargetError::Sautee("surface périmée, reconfigurée"));
            }
            S::Lost => return Err(TargetError::Surface("surface perdue".into())),
            S::Validation => {
                return Err(TargetError::Surface(
                    "erreur de validation à l'acquisition".into(),
                ));
            }
        };
        Ok(TargetFrame {
            view: st.texture.create_view(&wgpu::TextureViewDescriptor::default()),
            format: self.config.format,
            size: (self.config.width, self.config.height),
            surface_texture: Some(st),
        })
    }

    fn present(&mut self, mut frame: TargetFrame) {
        if let Some(st) = frame.surface_texture.take() {
            self.queue.present(st);
        }
    }
}
