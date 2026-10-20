//! Rampes de végétation de l'essence d'un modèle, lues dans l'en-tête `.vxm` (docs/19a § 1.2 et § 5.3).

use em_material::{RampRole, VegetationRamps};

use super::meta::VxmMeta;
use crate::error::GenError;

/// Construit le registre de rampes de l'essence du modèle, à la case `species_slot`.
///
/// Rôles de l'en-tête : `bark`, `bark_alt` et `twig` forment les trois variantes de l'écorce (dans cet ordre,
/// variante 0, 1, 2), `leaf` les rampes des feuilles, `flower` et `fruit` celles des fleurs et des fruits.
/// Les cases d'essence se prennent dans l'ordre d'enregistrement : les cases avant `species_slot` sont comblées
/// par des essences vides pour que l'essence tombe exactement sur la case demandée.
pub fn vegetation_ramps(meta: &VxmMeta, species_slot: u8) -> Result<VegetationRamps, GenError> {
    let mut veg = VegetationRamps::new();
    let refus = |m: String| GenError::BadParams(m);
    for i in 0..species_slot {
        veg.register(&format!("_vide{i}"), RampRole::Bark, &[])
            .map_err(|e| refus(e.to_string()))?;
    }
    let par_role = |noms: &[&str]| -> Vec<[[u8; 3]; 3]> {
        meta.ramps()
            .iter()
            .zip(meta.ramp_roles())
            .filter(|(_, r)| noms.contains(&r.as_str()))
            .map(|(rampe, _)| *rampe)
            .collect()
    };
    let espece = meta.species();
    let mut case = None;
    for (role, noms) in [
        (RampRole::Bark, &["bark", "bark_alt", "twig"][..]),
        (RampRole::Leaves, &["leaf"][..]),
        (RampRole::Flowers, &["flower"][..]),
        (RampRole::Fruits, &["fruit"][..]),
    ] {
        let rampes = par_role(noms);
        if !rampes.is_empty() {
            case = Some(
                veg.register(espece, role, &rampes)
                    .map_err(|e| refus(e.to_string()))?,
            );
        }
    }
    match case {
        Some(c) if c == species_slot => Ok(veg),
        Some(c) => Err(refus(format!(
            "l'essence « {espece} » a pris la case {c}, la scène voulait {species_slot}"
        ))),
        None => Err(refus(format!(
            "le modèle « {espece} » ne porte aucune rampe de végétation"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::VxmModel;
    use std::path::PathBuf;

    #[test]
    fn le_chene_de_reference_a_trois_variantes_d_ecorce_et_trois_feuillages() {
        let chemin = PathBuf::from(std::env::var("HOME").unwrap_or_default())
            .join(".local/share/emergence/lab_assets/trees/chene_42.vxm");
        if !chemin.is_file() {
            eprintln!("IGNORÉ : chene_42.vxm absent");
            return;
        }
        let m = VxmModel::load(&chemin).unwrap();
        let v = vegetation_ramps(m.meta(), 0).unwrap();
        assert_eq!(v.ramps(0, RampRole::Bark).len(), 3);
        assert_eq!(v.ramps(0, RampRole::Leaves).len(), 3);
        // sur la case 2, l'essence prend bien la case 2
        let v2 = vegetation_ramps(m.meta(), 2).unwrap();
        assert_eq!(v2.species_case(m.meta().species()), Some(2));
        assert!(vegetation_ramps(m.meta(), 32).is_err());
    }
}
