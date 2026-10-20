//! Relevé des horloges, de la température et de la puissance du GPU par `nvidia-smi` pendant un banc
//! (une carte de portable varie avec la chaleur : docs/19 § 7.3).

use serde::Serialize;
use std::process::Command;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread::JoinHandle;
use std::time::Duration;

/// Résumé des relevés (rapport en lecture seule).
#[derive(Debug, Clone, Default, Serialize)]
pub struct GpuClocks {
    /// Nombre de relevés réussis.
    pub samples: u32,
    /// Médiane de l'horloge des multiprocesseurs, MHz.
    pub sm_mhz_median: u32,
    /// Médiane de l'horloge mémoire, MHz.
    pub mem_mhz_median: u32,
    /// Température maximale, °C.
    pub temp_c_max: u32,
    /// Médiane de la puissance, W.
    pub power_w_median: f64,
}

fn mediane<T: PartialOrd + Copy + Default>(v: &mut [T]) -> T {
    if v.is_empty() {
        return T::default();
    }
    v.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    v[v.len() / 2]
}

/// Un relevé de `nvidia-smi`.
struct Releve {
    sm: u32,
    mem: u32,
    temp: u32,
    puissance: f64,
}

/// Prend un relevé ; `None` si `nvidia-smi` est absent ou illisible.
fn releve() -> Option<Releve> {
    let sortie = Command::new("nvidia-smi")
        .args([
            "--query-gpu=clocks.sm,clocks.mem,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ])
        .output()
        .ok()?;
    let texte = String::from_utf8(sortie.stdout).ok()?;
    let champs: Vec<&str> = texte.lines().next()?.split(',').map(str::trim).collect();
    Some(Releve {
        sm: champs.first()?.parse().ok()?,
        mem: champs.get(1)?.parse().ok()?,
        temp: champs.get(2)?.parse().ok()?,
        puissance: champs.get(3)?.parse().ok()?,
    })
}

/// Échantillonneur en arrière-plan : démarre à la création, s'arrête à `terminer`.
pub struct EchantillonneurHorloges {
    arret: Arc<AtomicBool>,
    fil: Option<JoinHandle<Vec<Releve>>>,
}

impl EchantillonneurHorloges {
    /// Lance le relevé toutes les 250 ms.
    pub fn demarrer() -> Self {
        let arret = Arc::new(AtomicBool::new(false));
        let a2 = Arc::clone(&arret);
        let fil = std::thread::spawn(move || {
            let mut mesures = Vec::new();
            while !a2.load(Ordering::Acquire) {
                if let Some(m) = releve() {
                    mesures.push(m);
                }
                std::thread::sleep(Duration::from_millis(250));
            }
            mesures
        });
        Self {
            arret,
            fil: Some(fil),
        }
    }

    /// Arrête et résume ; vide si `nvidia-smi` est absent.
    pub fn terminer(mut self) -> GpuClocks {
        self.arret.store(true, Ordering::Release);
        let mut mesures = self.fil.take().and_then(|f| f.join().ok()).unwrap_or_default();
        // Relevé final : un banc court n'aurait sinon qu'un point.
        mesures.extend(releve());
        let mut sm: Vec<u32> = mesures.iter().map(|m| m.sm).collect();
        let mut mem: Vec<u32> = mesures.iter().map(|m| m.mem).collect();
        let mut pw: Vec<f64> = mesures.iter().map(|m| m.puissance).collect();
        GpuClocks {
            samples: mesures.len() as u32,
            sm_mhz_median: mediane(&mut sm),
            mem_mhz_median: mediane(&mut mem),
            temp_c_max: mesures.iter().map(|m| m.temp).max().unwrap_or(0),
            power_w_median: mediane(&mut pw),
        }
    }
}
