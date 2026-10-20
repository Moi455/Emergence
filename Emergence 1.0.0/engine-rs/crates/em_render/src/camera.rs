//! Caméra libre de base et contexte d'image.

use crate::error::ParamError;
use crate::voxel::VoxelCamera;
use glam::Vec3;

/// Caméra libre : position, lacet, tangage, champ vertical. Invariants vérifiés à la construction.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Camera {
    position: Vec3,
    yaw: f32,
    pitch: f32,
    fov_y_deg: f32,
}

impl Camera {
    /// Tangage maximal (rad), pour ne jamais retourner la caméra.
    const TANGAGE_MAX: f32 = 1.553_343; // 89 degrés

    /// Construit une caméra. Lacet 0 regarde vers -Z, positif vers la gauche (anti-horaire vu d'en haut) ; tangage > 0 vers le haut.
    pub fn new(position: Vec3, yaw: f32, pitch: f32, fov_y_deg: f32) -> Result<Self, ParamError> {
        if !position.is_finite() || !yaw.is_finite() || !pitch.is_finite() {
            return Err(ParamError::Invalide(
                "caméra : position ou angles non finis".into(),
            ));
        }
        if !(10.0..=150.0).contains(&fov_y_deg) {
            return Err(ParamError::Invalide(format!(
                "caméra : champ vertical {fov_y_deg} hors de 10..150 degrés"
            )));
        }
        Ok(Self {
            position,
            yaw,
            pitch: pitch.clamp(-Self::TANGAGE_MAX, Self::TANGAGE_MAX),
            fov_y_deg,
        })
    }

    /// Position dans le monde (mètres).
    pub fn position(&self) -> Vec3 {
        self.position
    }

    /// Lacet (radians).
    pub fn yaw(&self) -> f32 {
        self.yaw
    }

    /// Tangage (radians).
    pub fn pitch(&self) -> f32 {
        self.pitch
    }

    /// Champ vertical (degrés).
    pub fn fov_y_deg(&self) -> f32 {
        self.fov_y_deg
    }

    /// Direction du regard (unitaire).
    pub fn avant(&self) -> Vec3 {
        let (sy, cy) = self.yaw.sin_cos();
        let (sp, cp) = self.pitch.sin_cos();
        Vec3::new(-sy * cp, sp, -cy * cp)
    }

    /// Droite de la caméra (horizontale, unitaire).
    pub fn droite(&self) -> Vec3 {
        self.avant().cross(Vec3::Y).normalize_or(Vec3::X)
    }

    /// Haut de la caméra (unitaire).
    pub fn haut(&self) -> Vec3 {
        self.droite().cross(self.avant()).normalize_or(Vec3::Y)
    }

    /// Tourne la caméra de `d_lacet` et `d_tangage` radians.
    pub fn tourner(&mut self, d_lacet: f32, d_tangage: f32) {
        self.yaw = (self.yaw + d_lacet).rem_euclid(std::f32::consts::TAU);
        self.pitch = (self.pitch + d_tangage).clamp(-Self::TANGAGE_MAX, Self::TANGAGE_MAX);
    }

    /// Déplace la caméra selon (avant, droite, haut) en mètres.
    pub fn deplacer(&mut self, avant: f32, droite: f32, haut: f32) {
        self.position += self.avant() * avant + self.droite() * droite + Vec3::Y * haut;
    }
}

impl Default for Camera {
    fn default() -> Self {
        Self {
            position: Vec3::new(0.0, 1.7, 0.0),
            yaw: 0.0,
            pitch: 0.12,
            fov_y_deg: 70.0,
        }
    }
}

/// Base de vue en mètres, en f32 : ce que les passes de ciel lisent (position, axes, champ vertical). Elle vient
/// de la caméra libre (repère droitier de L02) ou de la caméra voxel (repère gauche du monde, L09).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ViewBasis {
    position: Vec3,
    right: Vec3,
    up: Vec3,
    forward: Vec3,
    fov_y_deg: f32,
}

impl ViewBasis {
    /// Position en mètres.
    pub fn position(&self) -> Vec3 {
        self.position
    }

    /// Droite (unitaire).
    pub fn right(&self) -> Vec3 {
        self.right
    }

    /// Haut (unitaire).
    pub fn up(&self) -> Vec3 {
        self.up
    }

    /// Avant (unitaire).
    pub fn forward(&self) -> Vec3 {
        self.forward
    }

    /// Champ vertical, degrés (perspective ; 60 pour une vue orthographique).
    pub fn fov_y_deg(&self) -> f32 {
        self.fov_y_deg
    }
}

/// Contexte d'une image : numéro, temps, taille de sortie et caméra. Construit par l'appelant du graphe.
#[derive(Debug, Clone, Copy)]
pub struct FrameContext {
    index: u64,
    time_s: f32,
    width: u32,
    height: u32,
    camera: Camera,
    voxel_camera: Option<VoxelCamera>,
}

impl FrameContext {
    /// Construit le contexte ; les dimensions doivent être non nulles.
    pub fn new(index: u64, time_s: f32, width: u32, height: u32, camera: Camera) -> Result<Self, ParamError> {
        if width == 0 || height == 0 || !time_s.is_finite() {
            return Err(ParamError::Invalide(
                "contexte d'image : dimensions nulles ou temps non fini".into(),
            ));
        }
        Ok(Self {
            index,
            time_s,
            width,
            height,
            camera,
            voxel_camera: None,
        })
    }

    /// Contexte d'une scène voxel (L09) : la caméra voxel remplace la caméra libre, dont la position suit
    /// seulement pour les passes qui ne lisent que `camera()` (la base de vue passe par `view()`).
    pub fn new_voxel(
        index: u64,
        time_s: f32,
        width: u32,
        height: u32,
        camera: VoxelCamera,
    ) -> Result<Self, ParamError> {
        let libre = Camera::new(camera.position_m(), 0.0, camera.pitch_deg().to_radians(), 70.0)?;
        let mut f = Self::new(index, time_s, width, height, libre)?;
        f.voxel_camera = Some(camera);
        Ok(f)
    }

    /// Caméra voxel de l'image, s'il y en a une.
    pub fn voxel_camera(&self) -> Option<&VoxelCamera> {
        self.voxel_camera.as_ref()
    }

    /// Base de vue de l'image (caméra voxel si présente, sinon caméra libre).
    pub fn view(&self) -> ViewBasis {
        match &self.voxel_camera {
            Some(v) => ViewBasis {
                position: v.position_m(),
                right: v.droite(),
                up: v.haut(),
                forward: v.avant(),
                fov_y_deg: match v.projection() {
                    crate::voxel::Projection::Perspective { fov_y_deg } => fov_y_deg,
                    crate::voxel::Projection::Orthographic { .. } => 60.0,
                },
            },
            None => ViewBasis {
                position: self.camera.position(),
                right: self.camera.droite(),
                up: self.camera.haut(),
                forward: self.camera.avant(),
                fov_y_deg: self.camera.fov_y_deg(),
            },
        }
    }

    /// Numéro d'image.
    pub fn index(&self) -> u64 {
        self.index
    }

    /// Temps en secondes.
    pub fn time_s(&self) -> f32 {
        self.time_s
    }

    /// Largeur de sortie.
    pub fn width(&self) -> u32 {
        self.width
    }

    /// Hauteur de sortie.
    pub fn height(&self) -> u32 {
        self.height
    }

    /// Rapport largeur / hauteur.
    pub fn aspect(&self) -> f32 {
        self.width as f32 / self.height as f32
    }

    /// Caméra de l'image.
    pub fn camera(&self) -> &Camera {
        &self.camera
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn avant_par_defaut_regarde_vers_moins_z() {
        let c = Camera::new(Vec3::ZERO, 0.0, 0.0, 70.0).unwrap();
        assert!((c.avant() - Vec3::NEG_Z).length() < 1e-6);
        assert!((c.droite() - Vec3::X).length() < 1e-6);
    }

    #[test]
    fn construction_refuse_les_valeurs_invalides() {
        assert!(Camera::new(Vec3::NAN, 0.0, 0.0, 70.0).is_err());
        assert!(Camera::new(Vec3::ZERO, 0.0, 0.0, 5.0).is_err());
        assert!(FrameContext::new(0, 0.0, 0, 10, Camera::default()).is_err());
    }

    #[test]
    fn le_tangage_est_borne() {
        let mut c = Camera::default();
        c.tourner(0.0, 10.0);
        assert!(c.pitch() < 1.56);
    }
}
