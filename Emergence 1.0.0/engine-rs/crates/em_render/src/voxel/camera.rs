//! Caméra du monde voxel : position EXACTE en millimètres entiers (voxel entier + fraction), repère GAUCHE
//! du monde (x est, y haut, z nord ; docs/19 § 2.6), lacet 0 = nord et croissant dans le sens horaire vu d'en haut.
//!
//! La caméra libre de L02 (`crate::Camera`, repère droitier, f32) reste celle des scènes de ciel ; celle-ci sert
//! les scènes voxel : aucune perte de précision à 20 km de l'origine, puisque le tracé travaille en voxels
//! entiers relatifs à la caméra (docs/19 § 4.5).

use crate::error::ParamError;
use glam::{Mat4, Vec3};

/// Taille d'un voxel de niveau 0, en millimètres (miroir de `em_core::VOXEL_MM`).
const VOXEL_MM: i64 = em_core::VOXEL_MM;

/// Projection de la caméra.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Projection {
    /// Perspective : champ vertical en degrés, Z inversé infini.
    Perspective {
        /// Champ vertical, degrés.
        fov_y_deg: f32,
    },
    /// Orthographique : hauteur visible en mètres (sert au masque de silhouette et aux vues de contrôle).
    Orthographic {
        /// Hauteur de la vue, mètres.
        height_m: f32,
    },
}

/// Caméra voxel. Champs privés : le constructeur vérifie les invariants (valeurs finies, champ plausible).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct VoxelCamera {
    pos_mm: [i64; 3],
    yaw_deg: f32,
    pitch_deg: f32,
    projection: Projection,
}

impl VoxelCamera {
    /// Tangage maximal (degrés), pour ne jamais retourner la caméra.
    pub const TANGAGE_MAX_DEG: f32 = 89.0;
    /// Plan proche de la perspective, en mètres.
    pub const PROCHE_M: f32 = 0.05;

    /// Construit une caméra. `pos_mm` est la position MONDE en millimètres ; lacet 0° = nord (+z), horaire vu
    /// d'en haut ; tangage > 0 vers le haut (borné à ±89°).
    pub fn new(
        pos_mm: [i64; 3],
        yaw_deg: f32,
        pitch_deg: f32,
        projection: Projection,
    ) -> Result<Self, ParamError> {
        if !yaw_deg.is_finite() || !pitch_deg.is_finite() {
            return Err(ParamError::Invalide("caméra voxel : angles non finis".into()));
        }
        match projection {
            Projection::Perspective { fov_y_deg } if !(10.0..=150.0).contains(&fov_y_deg) => {
                return Err(ParamError::Invalide(format!(
                    "caméra voxel : champ vertical {fov_y_deg} hors de 10..150 degrés"
                )));
            }
            Projection::Orthographic { height_m } if !(height_m.is_finite() && height_m > 0.0) => {
                return Err(ParamError::Invalide(format!(
                    "caméra voxel : hauteur orthographique {height_m} invalide"
                )));
            }
            _ => {}
        }
        // Le tracé calcule en i32 : la position doit tenir dans le monde (docs/19a, 400 000 voxels de côté, marge).
        if pos_mm.iter().any(|v| v.abs() > 2_000_000_000) {
            return Err(ParamError::Invalide(
                "caméra voxel : position hors du monde".into(),
            ));
        }
        Ok(Self {
            pos_mm,
            yaw_deg: yaw_deg.rem_euclid(360.0),
            pitch_deg: pitch_deg.clamp(-Self::TANGAGE_MAX_DEG, Self::TANGAGE_MAX_DEG),
            projection,
        })
    }

    /// Nouvelle pose (mêmes contrôles qu'à la construction), la projection ne change pas.
    pub fn set_pose(&mut self, pos_mm: [i64; 3], yaw_deg: f32, pitch_deg: f32) -> Result<(), ParamError> {
        *self = Self::new(pos_mm, yaw_deg, pitch_deg, self.projection)?;
        Ok(())
    }

    /// Position monde, millimètres.
    pub fn pos_mm(&self) -> [i64; 3] {
        self.pos_mm
    }

    /// Lacet, degrés dans [0, 360).
    pub fn yaw_deg(&self) -> f32 {
        self.yaw_deg
    }

    /// Tangage, degrés.
    pub fn pitch_deg(&self) -> f32 {
        self.pitch_deg
    }

    /// Projection.
    pub fn projection(&self) -> Projection {
        self.projection
    }

    /// Voxel entier (niveau 0) qui contient la caméra.
    pub fn voxel(&self) -> [i32; 3] {
        self.pos_mm.map(|v| v.div_euclid(VOXEL_MM) as i32)
    }

    /// Position dans ce voxel, en voxels (dans [0, 1)).
    pub fn fraction_voxels(&self) -> [f32; 3] {
        self.pos_mm
            .map(|v| v.rem_euclid(VOXEL_MM) as f32 / VOXEL_MM as f32)
    }

    /// Position monde en mètres (f32 : ciel et débogage seulement, jamais pour le tracé).
    pub fn position_m(&self) -> Vec3 {
        Vec3::new(
            self.pos_mm[0] as f32 * 0.001,
            self.pos_mm[1] as f32 * 0.001,
            self.pos_mm[2] as f32 * 0.001,
        )
    }

    /// Direction du regard (unitaire) : (sin lacet cos tangage, sin tangage, cos lacet cos tangage).
    pub fn avant(&self) -> Vec3 {
        let (sy, cy) = self.yaw_deg.to_radians().sin_cos();
        let (sp, cp) = self.pitch_deg.to_radians().sin_cos();
        Vec3::new(sy * cp, sp, cy * cp)
    }

    /// Droite de la caméra (unitaire, horizontale) : repère gauche, `Y x avant`.
    pub fn droite(&self) -> Vec3 {
        Vec3::Y.cross(self.avant()).normalize_or(Vec3::X)
    }

    /// Haut de la caméra (unitaire).
    pub fn haut(&self) -> Vec3 {
        self.avant().cross(self.droite()).normalize_or(Vec3::Y)
    }

    /// Demi-tangentes (x, y) du champ pour un rapport `aspect` ; (0, 0) en orthographique.
    pub fn demi_tangentes(&self, aspect: f32) -> (f32, f32) {
        match self.projection {
            Projection::Perspective { fov_y_deg } => {
                let ty = (fov_y_deg.to_radians() * 0.5).tan();
                (ty * aspect, ty)
            }
            Projection::Orthographic { .. } => (0.0, 0.0),
        }
    }

    /// Matrice vue-projection RELATIVE à la caméra (l'origine est la caméra), repère gauche. Perspective : Z
    /// inversé infini (profondeur 1 au plan proche, 0 à l'infini). Orthographique : Z inversé sur 0..1000 m.
    pub fn view_proj_lh(&self, aspect: f32) -> Mat4 {
        let vue = Mat4::look_to_lh(Vec3::ZERO, self.avant(), Vec3::Y);
        let proj = match self.projection {
            Projection::Perspective { fov_y_deg } => {
                Mat4::perspective_infinite_reverse_lh(fov_y_deg.to_radians(), aspect, Self::PROCHE_M)
            }
            Projection::Orthographic { height_m } => {
                let demi_h = height_m * 0.5;
                Mat4::orthographic_lh(-demi_h * aspect, demi_h * aspect, -demi_h, demi_h, 1000.0, 0.0)
            }
        };
        proj * vue
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn persp(yaw: f32, pitch: f32) -> VoxelCamera {
        VoxelCamera::new(
            [200_000_000, 1700, 200_000_000],
            yaw,
            pitch,
            Projection::Perspective { fov_y_deg: 60.0 },
        )
        .unwrap()
    }

    #[test]
    fn lacet_zero_regarde_le_nord_et_90_l_est() {
        assert!((persp(0.0, 0.0).avant() - Vec3::Z).length() < 1e-6);
        assert!((persp(90.0, 0.0).avant() - Vec3::X).length() < 1e-6);
        // repère gauche : en regardant le nord, l'est est à droite
        assert!((persp(0.0, 0.0).droite() - Vec3::X).length() < 1e-6);
        assert!((persp(90.0, 0.0).droite() - Vec3::NEG_Z).length() < 1e-6);
    }

    #[test]
    fn voxel_et_fraction_sont_exacts_loin_de_l_origine() {
        let c = persp(0.0, 0.0);
        assert_eq!(c.voxel(), [4_000_000, 34, 4_000_000]);
        let f = c.fraction_voxels();
        assert!(f[0] == 0.0 && (f[1] - 0.0).abs() < 1e-6, "{f:?}");
        let n = VoxelCamera::new(
            [-1, -51, 49],
            0.0,
            0.0,
            Projection::Perspective { fov_y_deg: 60.0 },
        )
        .unwrap();
        assert_eq!(n.voxel(), [-1, -2, 0]);
        assert!((n.fraction_voxels()[0] - 0.98).abs() < 1e-6);
    }

    #[test]
    fn la_projection_inversee_met_le_proche_a_un_et_le_loin_pres_de_zero() {
        let c = persp(0.0, 0.0);
        let m = c.view_proj_lh(16.0 / 9.0);
        let proche = m.project_point3(Vec3::new(0.0, 0.0, VoxelCamera::PROCHE_M));
        let loin = m.project_point3(Vec3::new(0.0, 0.0, 1000.0));
        assert!((proche.z - 1.0).abs() < 1e-4, "{proche:?}");
        assert!(loin.z > 0.0 && loin.z < 1e-3, "{loin:?}");
        // un point à droite de l'axe est à x > 0 : la droite du repère gauche est bien à droite de l'écran
        let droite = m.project_point3(Vec3::new(1.0, 0.0, 5.0));
        assert!(droite.x > 0.0);
    }

    #[test]
    fn les_valeurs_invalides_sont_refusees() {
        assert!(
            VoxelCamera::new([0; 3], f32::NAN, 0.0, Projection::Perspective { fov_y_deg: 60.0 }).is_err()
        );
        assert!(VoxelCamera::new([0; 3], 0.0, 0.0, Projection::Perspective { fov_y_deg: 5.0 }).is_err());
        assert!(VoxelCamera::new([0; 3], 0.0, 0.0, Projection::Orthographic { height_m: 0.0 }).is_err());
        assert!(
            VoxelCamera::new(
                [i64::MAX, 0, 0],
                0.0,
                0.0,
                Projection::Orthographic { height_m: 1.0 }
            )
            .is_err()
        );
    }
}
