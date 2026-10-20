//! Repères : la SEULE conversion entre le repère monde et le repère du moteur d'actions (docs/19a § 3).
//!
//! Monde : x est, y haut, z nord (gaucher). Moteur d'actions (`engine/act`) : x est, y nord, z haut.
//! Les positions sont en millimètres. `(x, y, z)_monde = (x, z, y)_act`. La permutation est son propre inverse.
//! Aucune autre fonction du dépôt ne doit échanger y et z.

/// Position en mm du repère act (z haut) vers le repère monde (y haut).
pub const fn act_mm_to_world_mm(p: [i32; 3]) -> [i32; 3] {
    [p[0], p[2], p[1]]
}

/// Position en mm du repère monde (y haut) vers le repère act (z haut).
pub const fn world_mm_to_act_mm(p: [i32; 3]) -> [i32; 3] {
    [p[0], p[2], p[1]]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aller_retour() {
        let p = [10, -20, 30];
        assert_eq!(world_mm_to_act_mm(act_mm_to_world_mm(p)), p);
        assert_eq!(act_mm_to_world_mm(p), [10, 30, -20]);
    }
}
