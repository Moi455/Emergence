//! Contexte GPU : choix EXPLICITE de l'adaptateur et demande EXPLICITE des limites (docs/19 § 7.1).
//!
//! Les valeurs par défaut de `wgpu` 30 sont trop basses pour le plan (4 textures de stockage et
//! 8 tampons de stockage par étage, 16 Kio de mémoire partagée, 128 Mio par liaison) : l'hôte demande
//! ce dont les passes ont besoin et s'arrête avec un message clair si l'adaptateur refuse.
//! Pas de repli silencieux : l'Intel intégré ou `llvmpipe` sont refusés sauf `allow_any_adapter`.

use crate::error::GpuError;
use crate::exec::attendre;
use serde::Serialize;

/// Demande de contexte (configuration validée par `GpuContext::new`).
#[derive(Debug, Clone)]
pub struct GpuRequest {
    /// Sous-chaîne (insensible à la casse) du nom de l'adaptateur discret voulu ; env `EM_ADAPTER`, défaut « Quadro ».
    pub adapter_hint: String,
    /// Accepte tout adaptateur (Intel, logiciel) si le discret manque.
    pub allow_any_adapter: bool,
    /// Active les couches de validation de `wgpu`.
    pub validation: bool,
}

impl GpuRequest {
    /// Nom d'adaptateur par défaut.
    pub const ADAPTATEUR_PAR_DEFAUT: &'static str = "Quadro";

    /// Demande lue dans l'environnement (`EM_ADAPTER`), les autres champs étant fournis par l'appelant.
    pub fn depuis_environnement(allow_any_adapter: bool, validation: bool) -> Self {
        let adapter_hint = std::env::var("EM_ADAPTER")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .unwrap_or_else(|| Self::ADAPTATEUR_PAR_DEFAUT.to_owned());
        Self {
            adapter_hint,
            allow_any_adapter,
            validation,
        }
    }
}

impl Default for GpuRequest {
    fn default() -> Self {
        Self::depuis_environnement(false, false)
    }
}

/// Exigences de l'hôte sur l'appareil (docs/19 § 7.1) ; un plancher, jamais un repli.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DeviceRequirements {
    /// Textures de stockage par étage de shader.
    pub storage_textures_per_stage: u32,
    /// Tampons de stockage par étage de shader.
    pub storage_buffers_per_stage: u32,
    /// Mémoire partagée d'un groupe de calcul, en octets.
    pub workgroup_storage_bytes: u32,
    /// Taille maximale d'une liaison de tampon de stockage, en octets.
    pub storage_binding_bytes: u64,
    /// Taille maximale d'un tampon, en octets.
    pub buffer_bytes: u64,
    /// Côté maximal d'une texture 2D.
    pub texture_dimension_2d: u32,
}

impl DeviceRequirements {
    /// Exigences de `docs/19` § 7.1 : 8 textures, 16 tampons, 32 Kio partagés, 1 Gio par liaison.
    pub const fn laboratoire() -> Self {
        Self {
            storage_textures_per_stage: 8,
            storage_buffers_per_stage: 16,
            workgroup_storage_bytes: 32 * 1024,
            storage_binding_bytes: 1 << 30,
            buffer_bytes: 1 << 30,
            texture_dimension_2d: 8192,
        }
    }

    /// Limites `wgpu` à demander : les défauts, relevés aux exigences.
    pub fn limites_demandees(&self) -> wgpu::Limits {
        let mut l = wgpu::Limits::default();
        l.max_storage_textures_per_shader_stage = l
            .max_storage_textures_per_shader_stage
            .max(self.storage_textures_per_stage);
        l.max_storage_buffers_per_shader_stage = l
            .max_storage_buffers_per_shader_stage
            .max(self.storage_buffers_per_stage);
        l.max_compute_workgroup_storage_size = l
            .max_compute_workgroup_storage_size
            .max(self.workgroup_storage_bytes);
        l.max_storage_buffer_binding_size = l.max_storage_buffer_binding_size.max(self.storage_binding_bytes);
        l.max_buffer_size = l.max_buffer_size.max(self.buffer_bytes);
        l.max_texture_dimension_2d = l.max_texture_dimension_2d.max(self.texture_dimension_2d);
        l
    }

    /// Compare les exigences aux limites offertes ; renvoie une ligne par manque.
    pub fn manques(&self, offert: &wgpu::Limits) -> Vec<String> {
        let mut m = Vec::new();
        let mut verifie = |nom: &str, voulu: u64, a: u64| {
            if a < voulu {
                m.push(format!("{nom} : demandé {voulu}, offert {a}"));
            }
        };
        verifie(
            "textures de stockage par étage",
            self.storage_textures_per_stage.into(),
            offert.max_storage_textures_per_shader_stage.into(),
        );
        verifie(
            "tampons de stockage par étage",
            self.storage_buffers_per_stage.into(),
            offert.max_storage_buffers_per_shader_stage.into(),
        );
        verifie(
            "mémoire partagée (o)",
            self.workgroup_storage_bytes.into(),
            offert.max_compute_workgroup_storage_size.into(),
        );
        verifie(
            "liaison de tampon de stockage (o)",
            self.storage_binding_bytes,
            offert.max_storage_buffer_binding_size,
        );
        verifie("taille de tampon (o)", self.buffer_bytes, offert.max_buffer_size);
        verifie(
            "côté de texture 2D",
            self.texture_dimension_2d.into(),
            offert.max_texture_dimension_2d.into(),
        );
        m
    }
}

impl Default for DeviceRequirements {
    fn default() -> Self {
        Self::laboratoire()
    }
}

/// Rapport en lecture seule sur l'adaptateur retenu et l'appareil créé.
#[derive(Debug, Clone, Serialize)]
pub struct AdapterReport {
    /// Nom de la carte.
    pub name: String,
    /// Version du pilote.
    pub driver: String,
    /// Détail du pilote.
    pub driver_info: String,
    /// Type (`DiscreteGpu`, `IntegratedGpu`, `Cpu`…).
    pub device_type: String,
    /// API graphique.
    pub backend: String,
    /// Exigences demandées.
    pub requested: DeviceRequirements,
    /// Limites réellement accordées à l'appareil.
    pub granted: DeviceRequirements,
    /// Période d'horloge des horodatages, en nanosecondes par tick.
    pub timestamp_period_ns: f32,
    /// Horodatage de passes disponible.
    pub timestamps: bool,
}

impl AdapterReport {
    /// Pilote lisible : nom et version (« NVIDIA 615.71.09 »).
    pub fn pilote(&self) -> String {
        format!("{} {}", self.driver, self.driver_info).trim().to_owned()
    }
}

/// Choisit l'indice de l'adaptateur selon la règle de § 7.1 ; fonction pure, testable sans GPU.
///
/// `candidats` : (nom, type). Renvoie l'indice ou le message d'erreur (qui liste les adaptateurs vus).
pub(crate) fn choisir_adaptateur(
    candidats: &[(String, wgpu::DeviceType)],
    indice: &str,
    allow_any: bool,
) -> Result<usize, String> {
    let indice_min = indice.to_lowercase();
    let discret = candidats
        .iter()
        .position(|(nom, t)| *t == wgpu::DeviceType::DiscreteGpu && nom.to_lowercase().contains(&indice_min));
    if let Some(i) = discret {
        return Ok(i);
    }
    let vus = if candidats.is_empty() {
        "aucun adaptateur Vulkan visible".to_owned()
    } else {
        candidats
            .iter()
            .map(|(n, t)| format!("« {n} » ({t:?})"))
            .collect::<Vec<_>>()
            .join(", ")
    };
    if allow_any {
        let materiel = candidats.iter().position(|(_, t)| *t != wgpu::DeviceType::Cpu);
        if let Some(i) = materiel.or(if candidats.is_empty() { None } else { Some(0) }) {
            return Ok(i);
        }
        return Err(format!(
            "aucun adaptateur utilisable, même avec --allow-any-adapter ({vus})"
        ));
    }
    Err(format!(
        "aucun adaptateur discret dont le nom contient « {indice} » (vus : {vus}). Sur ce portable hybride, le \
         pilote NVIDIA n'est listé par Vulkan que s'il est désigné : lancer par engine-rs/scripts/lab.sh, ou \
         exporter VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json. Pour accepter un autre \
         adaptateur (déconseillé : mesures sans valeur), ajouter --allow-any-adapter. Le nom voulu se change par EM_ADAPTER."
    ))
}

/// Contexte GPU : instance, adaptateur, appareil, file et rapport. Champs privés.
pub struct GpuContext {
    instance: wgpu::Instance,
    adapter: wgpu::Adapter,
    device: wgpu::Device,
    queue: wgpu::Queue,
    report: AdapterReport,
}

impl GpuContext {
    /// Crée le contexte avec les exigences du laboratoire.
    pub fn new(req: &GpuRequest) -> Result<Self, GpuError> {
        Self::with_requirements(req, &DeviceRequirements::laboratoire())
    }

    /// Crée le contexte avec des exigences explicites (les tests y forcent une limite impossible).
    pub fn with_requirements(req: &GpuRequest, exigences: &DeviceRequirements) -> Result<Self, GpuError> {
        let mut desc = wgpu::InstanceDescriptor::new_without_display_handle();
        desc.backends = wgpu::Backends::VULKAN;
        if req.validation {
            desc.flags = wgpu::InstanceFlags::debugging();
        }
        let instance = wgpu::Instance::new(desc);
        let adapters = attendre(instance.enumerate_adapters(wgpu::Backends::VULKAN));
        let candidats: Vec<(String, wgpu::DeviceType)> = adapters
            .iter()
            .map(|a| {
                let i = a.get_info();
                (i.name, i.device_type)
            })
            .collect();
        let idx = choisir_adaptateur(&candidats, &req.adapter_hint, req.allow_any_adapter)
            .map_err(GpuError::AdapterIntrouvable)?;
        let adapter = adapters
            .into_iter()
            .nth(idx)
            .expect("indice valide par construction");
        let info = adapter.get_info();

        let manques = exigences.manques(&adapter.limits());
        let mut details = manques;
        let utile = adapter.features();
        if !utile.contains(wgpu::Features::TIMESTAMP_QUERY) {
            details.push("fonction TIMESTAMP_QUERY (profileur GPU) absente".to_owned());
        }
        if !details.is_empty() {
            return Err(GpuError::LimitesInsuffisantes {
                adaptateur: info.name,
                details: details.join(" ; "),
            });
        }
        let mut fonctions = wgpu::Features::TIMESTAMP_QUERY;
        if utile.contains(wgpu::Features::TIMESTAMP_QUERY_INSIDE_ENCODERS) {
            fonctions |= wgpu::Features::TIMESTAMP_QUERY_INSIDE_ENCODERS;
        }
        let limites = exigences.limites_demandees();
        log::info!(
            "adaptateur retenu : « {} » ({:?}, {:?}), pilote {} {}",
            info.name,
            info.device_type,
            info.backend,
            info.driver,
            info.driver_info
        );
        log::info!(
            "limites demandées : {} textures et {} tampons de stockage par étage, {} o partagés, {} o par liaison, {} o par tampon, texture 2D {}",
            limites.max_storage_textures_per_shader_stage,
            limites.max_storage_buffers_per_shader_stage,
            limites.max_compute_workgroup_storage_size,
            limites.max_storage_buffer_binding_size,
            limites.max_buffer_size,
            limites.max_texture_dimension_2d
        );
        let (device, queue) = attendre(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("em_lab"),
            required_features: fonctions,
            required_limits: limites,
            ..Default::default()
        }))
        .map_err(|e| GpuError::AppareilRefuse(e.to_string()))?;

        let accordees = device.limits();
        let report = AdapterReport {
            name: info.name.clone(),
            driver: info.driver.clone(),
            driver_info: info.driver_info.clone(),
            device_type: format!("{:?}", info.device_type),
            backend: format!("{:?}", info.backend),
            requested: exigences.clone(),
            granted: DeviceRequirements {
                storage_textures_per_stage: accordees.max_storage_textures_per_shader_stage,
                storage_buffers_per_stage: accordees.max_storage_buffers_per_shader_stage,
                workgroup_storage_bytes: accordees.max_compute_workgroup_storage_size,
                storage_binding_bytes: accordees.max_storage_buffer_binding_size,
                buffer_bytes: accordees.max_buffer_size,
                texture_dimension_2d: accordees.max_texture_dimension_2d,
            },
            timestamp_period_ns: queue.get_timestamp_period(),
            timestamps: true,
        };
        Ok(Self {
            instance,
            adapter,
            device,
            queue,
            report,
        })
    }

    /// Appareil logique.
    pub fn device(&self) -> &wgpu::Device {
        &self.device
    }

    /// File de commandes.
    pub fn queue(&self) -> &wgpu::Queue {
        &self.queue
    }

    /// Rapport sur l'adaptateur et les limites.
    pub fn info(&self) -> &AdapterReport {
        &self.report
    }

    /// Instance (pour créer une surface de fenêtre sur le même adaptateur).
    pub fn instance(&self) -> &wgpu::Instance {
        &self.instance
    }

    /// Adaptateur retenu.
    pub fn adapter(&self) -> &wgpu::Adapter {
        &self.adapter
    }

    /// Attend la fin de tout le travail soumis.
    pub fn attendre_fin(&self) {
        // L'échec d'une attente ne peut venir que d'un appareil perdu : on le journalise sans paniquer.
        if let Err(e) = self.device.poll(wgpu::PollType::wait_indefinitely()) {
            log::error!("attente du GPU échouée : {e}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wgpu::DeviceType::{Cpu, DiscreteGpu, IntegratedGpu};

    fn v(l: &[(&str, wgpu::DeviceType)]) -> Vec<(String, wgpu::DeviceType)> {
        l.iter().map(|(n, t)| ((*n).to_owned(), *t)).collect()
    }

    #[test]
    fn choisit_la_quadro_parmi_plusieurs() {
        let c = v(&[("Intel UHD", IntegratedGpu), ("Quadro RTX 3000", DiscreteGpu)]);
        assert_eq!(choisir_adaptateur(&c, "Quadro", false), Ok(1));
    }

    #[test]
    fn refuse_l_intel_seul_avec_message_clair() {
        let c = v(&[("Intel UHD", IntegratedGpu), ("llvmpipe", Cpu)]);
        let e = choisir_adaptateur(&c, "Quadro", false).unwrap_err();
        assert!(
            e.contains("VK_DRIVER_FILES") && e.contains("--allow-any-adapter") && e.contains("Intel UHD")
        );
    }

    #[test]
    fn allow_any_prefere_le_materiel_au_logiciel() {
        let c = v(&[("llvmpipe", Cpu), ("Intel UHD", IntegratedGpu)]);
        assert_eq!(choisir_adaptateur(&c, "Quadro", true), Ok(1));
    }

    #[test]
    fn une_limite_impossible_est_refusee_avec_le_detail() {
        let mut ex = DeviceRequirements::laboratoire();
        ex.storage_buffers_per_stage = u32::MAX;
        let manques = ex.manques(&wgpu::Limits::default());
        assert!(
            manques
                .iter()
                .any(|l| l.contains("tampons de stockage par étage"))
        );
        // Les exigences du laboratoire dépassent bien les défauts de wgpu 30.
        assert!(
            !DeviceRequirements::laboratoire()
                .manques(&wgpu::Limits::default())
                .is_empty()
        );
    }

    #[test]
    fn limites_demandees_couvrent_les_exigences() {
        let ex = DeviceRequirements::laboratoire();
        assert!(ex.manques(&ex.limites_demandees()).is_empty());
    }
}
