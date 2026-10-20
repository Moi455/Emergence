//! Dossiers de sortie : `EM_CAPTURE_DIR`, sinon `engine-rs/lab/captures/AAAA-MM-JJ/`.

use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

/// Date civile (UTC) AAAA-MM-JJ à partir des jours depuis 1970 (algorithme de Howard Hinnant).
fn date_civile(jours: i64) -> (i64, u32, u32) {
    let z = jours + 719_468;
    let ere = z.div_euclid(146_097);
    let jde = z.rem_euclid(146_097);
    let ade = (jde - jde / 1460 + jde / 36_524 - jde / 146_096) / 365;
    let annee = ade + ere * 400;
    let jda = jde - (365 * ade + ade / 4 - ade / 100);
    let mp = (5 * jda + 2) / 153;
    let jour = (jda - (153 * mp + 2) / 5 + 1) as u32;
    let mois = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (annee + i64::from(mois <= 2), mois, jour)
}

/// Racine d'`engine-rs/` (les chemins des scènes et des modèles en partent).
pub fn dossier_racine() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// Dossier des captures du jour.
pub fn dossier_captures() -> PathBuf {
    if let Some(d) = std::env::var_os("EM_CAPTURE_DIR").filter(|d| !d.is_empty()) {
        return PathBuf::from(d);
    }
    let secondes = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs());
    let (a, m, j) = date_civile((secondes / 86_400) as i64);
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../lab/captures")
        .join(format!("{a:04}-{m:02}-{j:02}"))
}

#[cfg(test)]
mod tests {
    use super::date_civile;

    #[test]
    fn dates_connues() {
        assert_eq!(date_civile(0), (1970, 1, 1));
        assert_eq!(date_civile(20_746), (2026, 10, 20));
    }
}
