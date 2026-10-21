//! Cône de vision et test de boîte (CPU) pour l'élimination des chunks hors champ.

use glam::{Mat4, Vec3, Vec4};

/// Six plans extraits d'une matrice vue-projection (volume de clip de wgpu : x, y dans [-w, w], z dans [0, w]).
/// Un point `p` est dedans si `plan · (p, 1) >= 0` pour les six. La projection à Z inversé infini donne un plan
/// éloigné trivial (toujours vrai) : il reste un plan proche, `w - z >= 0`.
#[derive(Debug, Clone, Copy)]
pub struct Frustum {
    plans: [Vec4; 6],
}

impl Frustum {
    /// Extrait les plans d'une matrice vue-projection (méthode de Gribb et Hartmann).
    pub fn from_view_proj(m: Mat4) -> Self {
        let (r0, r1, r2, r3) = (m.row(0), m.row(1), m.row(2), m.row(3));
        Self {
            plans: [r3 + r0, r3 - r0, r3 + r1, r3 - r1, r2, r3 - r2],
        }
    }

    /// Vrai si la boîte `[min, max]` (mêmes unités que la matrice) touche le volume : elle n'est rejetée que si elle
    /// est entièrement derrière un plan.
    pub fn intersects_box(&self, min: Vec3, max: Vec3) -> bool {
        self.plans.iter().all(|p| {
            let n = p.truncate();
            let sommet = Vec3::new(
                if n.x >= 0.0 { max.x } else { min.x },
                if n.y >= 0.0 { max.y } else { min.y },
                if n.z >= 0.0 { max.z } else { min.z },
            );
            n.dot(sommet) + p.w >= 0.0
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vue() -> Frustum {
        let vp = Mat4::perspective_infinite_reverse_lh(60_f32.to_radians(), 1.0, 0.05)
            * Mat4::look_to_lh(Vec3::ZERO, Vec3::Z, Vec3::Y);
        Frustum::from_view_proj(vp)
    }

    #[test]
    fn devant_oui_derriere_et_cote_non() {
        let f = vue();
        let boite = |c: Vec3| f.intersects_box(c - Vec3::splat(0.5), c + Vec3::splat(0.5));
        assert!(boite(Vec3::new(0.0, 0.0, 10.0)));
        assert!(boite(Vec3::new(0.0, 0.0, 1000.0)), "pas de plan éloigné");
        assert!(!boite(Vec3::new(0.0, 0.0, -10.0)), "derrière la caméra");
        assert!(!boite(Vec3::new(30.0, 0.0, 10.0)), "loin à droite");
        assert!(!boite(Vec3::new(0.0, -30.0, 10.0)), "loin en bas");
        // une grande boîte qui contient la caméra est dedans
        assert!(f.intersects_box(Vec3::splat(-5.0), Vec3::splat(5.0)));
    }
}
