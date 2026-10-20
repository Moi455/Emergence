//! Graphe de rendu orienté objet : des passes possédées, des ressources nommées, aucune globale.
//! Les tâches suivantes y branchent leurs passes en implémentant `RenderPass`.

use crate::camera::FrameContext;
use crate::error::GraphError;
use crate::gpu::GpuContext;
use crate::profiler::GpuProfiler;
use crate::target::{FrameTarget, TargetFrame};
use std::collections::BTreeMap;

/// Nom d'une passe (identifiant de profil et de bascule). Jamais vide.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct PassName(&'static str);

impl PassName {
    /// Crée un nom de passe ; panique si le nom est vide (erreur de programmation, détectée au démarrage).
    pub const fn new(nom: &'static str) -> Self {
        assert!(!nom.is_empty(), "un nom de passe ne peut pas être vide");
        Self(nom)
    }

    /// Le texte du nom.
    pub const fn as_str(self) -> &'static str {
        self.0
    }
}

/// Nom d'une ressource du graphe (G-buffer, HDR, profondeur…). Jamais vide.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ResourceName(&'static str);

impl ResourceName {
    /// Crée un nom de ressource ; panique si vide.
    pub const fn new(nom: &'static str) -> Self {
        assert!(!nom.is_empty(), "un nom de ressource ne peut pas être vide");
        Self(nom)
    }

    /// Le texte du nom.
    pub const fn as_str(self) -> &'static str {
        self.0
    }
}

/// Textures nommées partagées entre les passes ; le graphe en est propriétaire.
#[derive(Default)]
pub struct Resources {
    textures: BTreeMap<ResourceName, wgpu::Texture>,
    buffers: BTreeMap<ResourceName, wgpu::Buffer>,
}

impl Resources {
    /// Ensemble vide.
    pub fn new() -> Self {
        Self::default()
    }

    /// Enregistre (ou remplace) une texture sous ce nom.
    pub fn insert_texture(&mut self, nom: ResourceName, texture: wgpu::Texture) {
        self.textures.insert(nom, texture);
    }

    /// Texture de ce nom, si elle existe.
    pub fn texture(&self, nom: ResourceName) -> Option<&wgpu::Texture> {
        self.textures.get(&nom)
    }

    /// Vue par défaut de la texture de ce nom.
    pub fn view(&self, nom: ResourceName) -> Option<wgpu::TextureView> {
        self.texture(nom)
            .map(|t| t.create_view(&wgpu::TextureViewDescriptor::default()))
    }

    /// Enregistre (ou remplace) un tampon sous ce nom (uniformes partagés entre passes, par exemple).
    pub fn insert_buffer(&mut self, nom: ResourceName, tampon: wgpu::Buffer) {
        self.buffers.insert(nom, tampon);
    }

    /// Tampon de ce nom, s'il existe.
    pub fn buffer(&self, nom: ResourceName) -> Option<&wgpu::Buffer> {
        self.buffers.get(&nom)
    }

    /// Retire toutes les ressources (changement de taille de sortie).
    pub fn clear(&mut self) {
        self.textures.clear();
        self.buffers.clear();
    }
}

/// Ce que la cible impose aux passes : format et taille de sortie.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PassSetup {
    /// Format de la texture de sortie.
    pub format: wgpu::TextureFormat,
    /// Dimensions de la sortie.
    pub size: (u32, u32),
}

/// Contexte donné à une passe pendant l'encodage d'une image.
pub struct PassContext<'a> {
    gpu: &'a GpuContext,
    frame: &'a FrameContext,
    resources: &'a mut Resources,
    target: &'a TargetFrame,
    encoder: &'a mut wgpu::CommandEncoder,
    profiler: &'a mut GpuProfiler,
    name: PassName,
}

impl<'a> PassContext<'a> {
    /// Contexte GPU.
    pub fn gpu(&self) -> &GpuContext {
        self.gpu
    }

    /// Contexte de l'image (caméra, temps, taille).
    pub fn frame(&self) -> &FrameContext {
        self.frame
    }

    /// Ressources nommées du graphe.
    pub fn resources(&mut self) -> &mut Resources {
        self.resources
    }

    /// Image de sortie.
    pub fn target(&self) -> &TargetFrame {
        self.target
    }

    /// Ouvre une passe de rendu sur la sortie, MESURÉE sous le nom de la passe : le profil ne s'oublie pas.
    pub fn render_pass(&mut self, label: &str, load: wgpu::LoadOp<wgpu::Color>) -> wgpu::RenderPass<'_> {
        let horodatages = self.profiler.render_scope(self.name.as_str());
        self.encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some(label),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: self.target.view(),
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: horodatages,
            occlusion_query_set: None,
            multiview_mask: None,
        })
    }

    /// Ouvre une passe de rendu sur une vue INTERMÉDIAIRE (HDR, niveau de bloom…), MESURÉE sous le nom de
    /// la passe : plusieurs portées d'une même passe s'additionnent dans le profil (voir `GpuProfiler`).
    pub fn render_pass_to<'v>(
        &'v mut self,
        label: &str,
        vue: &'v wgpu::TextureView,
        load: wgpu::LoadOp<wgpu::Color>,
    ) -> wgpu::RenderPass<'v> {
        let horodatages = self.profiler.render_scope(self.name.as_str());
        self.encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some(label),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: vue,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: horodatages,
            occlusion_query_set: None,
            multiview_mask: None,
        })
    }

    /// Ouvre une passe de rendu qui n'écrit QUE la profondeur (effacée à 0 : Z inversé), MESURÉE sous le nom de la passe.
    pub fn render_pass_depth<'v>(
        &'v mut self,
        label: &str,
        profondeur: &'v wgpu::TextureView,
    ) -> wgpu::RenderPass<'v> {
        let horodatages = self.profiler.render_scope(self.name.as_str());
        self.encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some(label),
            color_attachments: &[],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: profondeur,
                depth_ops: Some(wgpu::Operations {
                    load: wgpu::LoadOp::Clear(0.0),
                    store: wgpu::StoreOp::Store,
                }),
                stencil_ops: None,
            }),
            timestamp_writes: horodatages,
            occlusion_query_set: None,
            multiview_mask: None,
        })
    }

    /// Ouvre une passe de calcul, MESURÉE sous le nom de la passe.
    pub fn compute_pass(&mut self, label: &str) -> wgpu::ComputePass<'_> {
        let horodatages = self.profiler.compute_scope(self.name.as_str());
        self.encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
            label: Some(label),
            timestamp_writes: horodatages,
        })
    }
}

/// Une passe du graphe. Elle possède ses pipelines et ses tampons.
pub trait RenderPass {
    /// Nom unique de la passe dans le graphe.
    fn name(&self) -> PassName;

    /// Crée ou recrée pipelines et ressources quand le format ou la taille de sortie change
    /// (appelée avant le premier `encode`, puis à chaque changement).
    fn prepare(&mut self, gpu: &GpuContext, setup: &PassSetup, resources: &mut Resources);

    /// Encode la passe de l'image courante.
    fn encode(&mut self, ctx: &mut PassContext<'_>);
}

/// Case du graphe : la passe, son interrupteur, la configuration pour laquelle elle est prête.
struct Entree {
    passe: Box<dyn RenderPass>,
    active: bool,
    prete_pour: Option<PassSetup>,
}

/// Graphe de rendu : passes ordonnées et ressources nommées.
#[derive(Default)]
pub struct RenderGraph {
    entrees: Vec<Entree>,
    resources: Resources,
}

impl RenderGraph {
    /// Graphe vide.
    pub fn new() -> Self {
        Self::default()
    }

    /// Ajoute une passe à la fin ; refuse un nom déjà pris.
    pub fn add(&mut self, pass: Box<dyn RenderPass>) -> Result<(), GraphError> {
        let nom = pass.name();
        if self.entrees.iter().any(|e| e.passe.name() == nom) {
            return Err(GraphError::NomEnDouble(nom.as_str().to_owned()));
        }
        self.entrees.push(Entree {
            passe: pass,
            active: true,
            prete_pour: None,
        });
        Ok(())
    }

    /// Active ou coupe une passe (bascule F1..F12 sans recompiler). Renvoie `false` si le nom est inconnu.
    pub fn set_enabled(&mut self, name: &str, on: bool) -> bool {
        match self.entrees.iter_mut().find(|e| e.passe.name().as_str() == name) {
            Some(e) => {
                e.active = on;
                true
            }
            None => false,
        }
    }

    /// Ressources nommées (lecture seule) : les essais y relisent la texture HDR.
    pub fn resources(&self) -> &Resources {
        &self.resources
    }

    /// Noms des passes dans l'ordre d'exécution, avec leur état.
    pub fn passes(&self) -> impl Iterator<Item = (PassName, bool)> + '_ {
        self.entrees.iter().map(|e| (e.passe.name(), e.active))
    }

    /// Dessine une image : prépare les passes si la sortie a changé, encode les passes actives,
    /// résout le profil, soumet, présente, puis lance la lecture différée des mesures.
    pub fn render(
        &mut self,
        gpu: &GpuContext,
        frame: &FrameContext,
        target: &mut dyn FrameTarget,
        prof: &mut GpuProfiler,
    ) -> Result<(), GraphError> {
        let image = target.acquire()?;
        let setup = PassSetup {
            format: image.format(),
            size: image.size(),
        };
        for e in &mut self.entrees {
            if e.prete_pour != Some(setup) {
                e.passe.prepare(gpu, &setup, &mut self.resources);
                e.prete_pour = Some(setup);
            }
        }
        let mut enc = gpu
            .device()
            .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("image") });
        for e in self.entrees.iter_mut().filter(|e| e.active) {
            let mut ctx = PassContext {
                gpu,
                frame,
                resources: &mut self.resources,
                target: &image,
                encoder: &mut enc,
                profiler: prof,
                name: e.passe.name(),
            };
            e.passe.encode(&mut ctx);
        }
        prof.resolve(&mut enc);
        gpu.queue().submit([enc.finish()]);
        target.present(image);
        prof.end_frame(gpu);
        Ok(())
    }
}
