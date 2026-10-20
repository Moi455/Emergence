//! Profileur GPU par horodatages (docs/19 § 7.3) : début et fin de chaque passe écrits dans un
//! `QuerySet`, résolus dans un tampon, lus avec un RETARD de quelques images (anneau de 3), convertis
//! en millisecondes par `Queue::get_timestamp_period()`.

use crate::gpu::GpuContext;
use serde::Serialize;
use std::fmt;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

/// Nombre d'images en vol dans l'anneau de lecture : les mesures arrivent 2 images plus tard.
pub const ANNEAU: usize = 3;

/// Statistiques d'une passe (rapport en lecture seule).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PassTiming {
    /// Nom de la passe.
    pub name: String,
    /// Médiane en millisecondes.
    pub median_ms: f64,
    /// 95e centile (rang le plus proche) en millisecondes.
    pub p95_ms: f64,
    /// Nombre d'échantillons.
    pub n: u64,
}

/// Rapport de profil : ms par passe, lisible et sérialisable (format de 19a § 6.6).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ProfileReport {
    /// Une entrée par passe, dans l'ordre de première apparition.
    pub passes: Vec<PassTiming>,
    /// Médiane du temps GPU total par image (somme des passes), en ms.
    pub total_median_ms: f64,
    /// 95e centile du total par image, en ms.
    pub total_p95_ms: f64,
}

impl fmt::Display for ProfileReport {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        writeln!(
            f,
            "{:<24} {:>10} {:>10} {:>7}",
            "passe", "médiane ms", "p95 ms", "n"
        )?;
        for p in &self.passes {
            writeln!(
                f,
                "{:<24} {:>10.4} {:>10.4} {:>7}",
                p.name, p.median_ms, p.p95_ms, p.n
            )?;
        }
        write!(
            f,
            "{:<24} {:>10.4} {:>10.4}",
            "TOTAL", self.total_median_ms, self.total_p95_ms
        )
    }
}

/// Médiane et 95e centile d'un échantillon (tableau trié en place). Vide : (0, 0).
fn mediane_et_p95(valeurs: &mut [f64]) -> (f64, f64) {
    if valeurs.is_empty() {
        return (0.0, 0.0);
    }
    valeurs.sort_by(|a, b| a.total_cmp(b));
    let n = valeurs.len();
    let mediane = if n % 2 == 1 {
        valeurs[n / 2]
    } else {
        0.5 * (valeurs[n / 2 - 1] + valeurs[n / 2])
    };
    let rang = ((0.95 * n as f64).ceil() as usize).clamp(1, n);
    (mediane, valeurs[rang - 1])
}

/// État d'une case de l'anneau.
struct Case {
    resolu: wgpu::Buffer,
    lecture: wgpu::Buffer,
    noms: Vec<&'static str>,
    pret: Option<Arc<AtomicBool>>,
}

/// Profileur GPU. Il possède ses requêtes et ses tampons ; aucune globale.
pub struct GpuProfiler {
    actif: bool,
    max_scopes: u32,
    periode_ns: f64,
    requetes: Option<wgpu::QuerySet>,
    cases: Vec<Case>,
    courante: usize,
    echantillons: Vec<(&'static str, Vec<f64>)>,
    totaux: Vec<f64>,
    avertit_plein: bool,
}

impl GpuProfiler {
    /// Crée un profileur pour au plus `max_scopes` portées par image (au moins 1).
    pub fn new(gpu: &GpuContext, max_scopes: u32) -> Self {
        let max_scopes = max_scopes.max(1);
        let device = gpu.device();
        let requetes = device.create_query_set(&wgpu::QuerySetDescriptor {
            label: Some("profileur"),
            ty: wgpu::QueryType::Timestamp,
            count: max_scopes * 2 * ANNEAU as u32,
        });
        let octets = u64::from(max_scopes) * 16;
        let cases = (0..ANNEAU)
            .map(|i| Case {
                resolu: device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some(&format!("profileur résolu {i}")),
                    size: octets,
                    usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                    mapped_at_creation: false,
                }),
                lecture: device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some(&format!("profileur lecture {i}")),
                    size: octets,
                    usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                }),
                noms: Vec::new(),
                pret: None,
            })
            .collect();
        Self {
            actif: true,
            max_scopes,
            periode_ns: f64::from(gpu.queue().get_timestamp_period()),
            requetes: Some(requetes),
            cases,
            courante: 0,
            echantillons: Vec::new(),
            totaux: Vec::new(),
            avertit_plein: false,
        }
    }

    /// Active ou coupe la mesure (coupée : plus aucune portée n'est donnée aux passes).
    pub fn set_enabled(&mut self, actif: bool) {
        self.actif = actif;
    }

    /// Réserve une portée pour la passe `name` et renvoie les indices (début, fin) de requête.
    fn reserver(&mut self, name: &'static str) -> Option<(u32, u32)> {
        if !self.actif {
            return None;
        }
        let case = &mut self.cases[self.courante];
        if case.noms.len() as u32 >= self.max_scopes {
            if !self.avertit_plein {
                log::warn!(
                    "profileur plein ({} portées) : la passe « {name} » n'est pas mesurée",
                    self.max_scopes
                );
                self.avertit_plein = true;
            }
            return None;
        }
        let base = self.courante as u32 * self.max_scopes * 2 + case.noms.len() as u32 * 2;
        case.noms.push(name);
        Some((base, base + 1))
    }

    /// Horodatages à brancher sur une passe de rendu.
    pub fn render_scope(&mut self, name: &'static str) -> Option<wgpu::RenderPassTimestampWrites<'_>> {
        let (debut, fin) = self.reserver(name)?;
        let query_set = self.requetes.as_ref()?;
        Some(wgpu::RenderPassTimestampWrites {
            query_set,
            beginning_of_pass_write_index: Some(debut),
            end_of_pass_write_index: Some(fin),
        })
    }

    /// Horodatages à brancher sur une passe de calcul.
    pub fn compute_scope(&mut self, name: &'static str) -> Option<wgpu::ComputePassTimestampWrites<'_>> {
        let (debut, fin) = self.reserver(name)?;
        let query_set = self.requetes.as_ref()?;
        Some(wgpu::ComputePassTimestampWrites {
            query_set,
            beginning_of_pass_write_index: Some(debut),
            end_of_pass_write_index: Some(fin),
        })
    }

    /// Résout les requêtes de l'image dans le tampon de lecture ; à appeler avant `finish()` de l'encodeur.
    pub fn resolve(&mut self, enc: &mut wgpu::CommandEncoder) {
        let Some(requetes) = self.requetes.as_ref() else {
            return;
        };
        let case = &self.cases[self.courante];
        let n = case.noms.len() as u32;
        if n == 0 {
            return;
        }
        let base = self.courante as u32 * self.max_scopes * 2;
        enc.resolve_query_set(requetes, base..base + 2 * n, &case.resolu, 0);
        enc.copy_buffer_to_buffer(&case.resolu, 0, &case.lecture, 0, u64::from(n) * 16);
    }

    /// Fin d'image, APRÈS la soumission : demande la lecture, récolte les images anciennes terminées,
    /// puis passe à la case suivante (en attendant si elle est encore occupée).
    pub fn end_frame(&mut self, gpu: &GpuContext) {
        let n = self.cases[self.courante].noms.len();
        if n > 0 {
            let drapeau = Arc::new(AtomicBool::new(false));
            let d2 = Arc::clone(&drapeau);
            self.cases[self.courante]
                .lecture
                .slice(0..(n as u64) * 16)
                .map_async(wgpu::MapMode::Read, move |r| {
                    if r.is_ok() {
                        d2.store(true, Ordering::Release);
                    }
                });
            self.cases[self.courante].pret = Some(drapeau);
        }
        // Un sondage non bloquant fait avancer les rappels des images déjà finies.
        let _ = gpu.device().poll(wgpu::PollType::Poll);
        self.courante = (self.courante + 1) % ANNEAU;
        for decalage in 0..ANNEAU {
            let i = (self.courante + decalage) % ANNEAU;
            let Some(drapeau) = self.cases[i].pret.clone() else {
                continue;
            };
            if drapeau.load(Ordering::Acquire) {
                self.recolter(i);
            } else if i == self.courante {
                // La case que l'on va réutiliser est encore en vol : on attend (rare, anneau de 3).
                while !drapeau.load(Ordering::Acquire) {
                    if gpu.device().poll(wgpu::PollType::wait_indefinitely()).is_err() {
                        break;
                    }
                }
                if drapeau.load(Ordering::Acquire) {
                    self.recolter(i);
                }
            }
        }
        self.cases[self.courante].noms.clear();
    }

    /// Lit une case terminée et ajoute ses durées aux échantillons.
    fn recolter(&mut self, i: usize) {
        let n = self.cases[i].noms.len();
        let mut total = 0.0;
        {
            let Ok(vue) = self.cases[i].lecture.slice(0..(n as u64) * 16).get_mapped_range() else {
                log::error!("profileur : lecture de la case {i} impossible");
                return;
            };
            // Une passe peut ouvrir plusieurs portées dans la même image (bloom : 15 passes de rendu) :
            // leurs durées s'ADDITIONNENT, c'est le coût de la passe pour cette image.
            let mut par_nom: Vec<(&'static str, f64)> = Vec::new();
            for (k, nom) in self.cases[i].noms.iter().enumerate() {
                let lire = |o: usize| u64::from_le_bytes(vue[o..o + 8].try_into().expect("8 octets"));
                let (debut, fin) = (lire(k * 16), lire(k * 16 + 8));
                let ms = fin.saturating_sub(debut) as f64 * self.periode_ns * 1e-6;
                total += ms;
                match par_nom.iter_mut().find(|(n2, _)| n2 == nom) {
                    Some((_, somme)) => *somme += ms,
                    None => par_nom.push((nom, ms)),
                }
            }
            for (nom, ms) in par_nom {
                match self.echantillons.iter_mut().find(|(n2, _)| *n2 == nom) {
                    Some((_, v)) => v.push(ms),
                    None => self.echantillons.push((nom, vec![ms])),
                }
            }
        }
        self.cases[i].lecture.unmap();
        self.cases[i].pret = None;
        if i != self.courante {
            self.cases[i].noms.clear();
        }
        self.totaux.push(total);
    }

    /// Attend et récolte toutes les images en vol (fin de banc).
    pub fn vider(&mut self, gpu: &GpuContext) {
        gpu.attendre_fin();
        for i in 0..ANNEAU {
            if self.cases[i]
                .pret
                .as_ref()
                .is_some_and(|d| d.load(Ordering::Acquire))
            {
                self.recolter(i);
            }
        }
    }

    /// Oublie les mesures déjà récoltées (après l'échauffement).
    pub fn reinitialiser(&mut self) {
        self.echantillons.clear();
        self.totaux.clear();
    }

    /// Rapport courant : médiane, p95 et n par passe.
    pub fn report(&self) -> ProfileReport {
        let passes = self
            .echantillons
            .iter()
            .map(|(nom, v)| {
                let mut copie = v.clone();
                let (median_ms, p95_ms) = mediane_et_p95(&mut copie);
                PassTiming {
                    name: (*nom).to_owned(),
                    median_ms,
                    p95_ms,
                    n: v.len() as u64,
                }
            })
            .collect();
        let mut totaux = self.totaux.clone();
        let (total_median_ms, total_p95_ms) = mediane_et_p95(&mut totaux);
        ProfileReport {
            passes,
            total_median_ms,
            total_p95_ms,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::mediane_et_p95;

    #[test]
    fn mediane_et_centile() {
        let mut v: Vec<f64> = (1..=100).map(f64::from).collect();
        let (m, p) = mediane_et_p95(&mut v);
        assert!((m - 50.5).abs() < 1e-12);
        assert!((p - 95.0).abs() < 1e-12);
        assert_eq!(mediane_et_p95(&mut []), (0.0, 0.0));
        let mut un = [3.0];
        assert_eq!(mediane_et_p95(&mut un), (3.0, 3.0));
    }
}
