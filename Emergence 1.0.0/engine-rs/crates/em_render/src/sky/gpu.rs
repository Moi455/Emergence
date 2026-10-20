//! Dispositions GPU du ciel (uniformes `#[repr(C)]`), rangées à part et jamais utilisées comme état.

use super::params::SkyParams;
use crate::camera::FrameContext;
use bytemuck::{Pod, Zeroable};

/// Miroir de `struct Frame` de `shaders/sky/frame.wgsl` : 11 vec4, 176 octets.
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct SkyFrame {
    cam_pos: [f32; 4],
    cam_right: [f32; 4],
    cam_up: [f32; 4],
    cam_fwd: [f32; 4],
    sun_dir: [f32; 4],
    screen: [f32; 4],
    post: [f32; 4],
    atmo: [f32; 4],
    water_col: [f32; 4],
    fog_ext: [f32; 4],
    cloud_p: [f32; 4],
}

impl SkyFrame {
    /// Altitude minimale de la caméra pour l'atmosphère (km) : 10 m, comme `web-ocean`.
    const ALTITUDE_MIN_KM: f32 = 0.010;

    /// Compose l'uniforme de l'image à partir des paramètres du ciel et de la caméra.
    pub fn compose(p: &SkyParams, f: &FrameContext) -> Self {
        let vue = f.view();
        let t_y = (vue.fov_y_deg().to_radians() * 0.5).tan();
        let t_x = t_y * f.aspect();
        let (d, h, a) = (vue.right(), vue.up(), vue.forward());
        let pos = vue.position();
        let s = p.sun_direction();
        let c = p.clouds();
        let (w, hh) = (f.width() as f32, f.height() as f32);
        let mie = p.turbidity();
        Self {
            cam_pos: [pos.x, pos.y, pos.z, f.time_s()],
            cam_right: [d.x * t_x, d.y * t_x, d.z * t_x, 0.0],
            cam_up: [h.x * t_y, h.y * t_y, h.z * t_y, 0.0],
            cam_fwd: [a.x, a.y, a.z, 0.0],
            sun_dir: [s.x, s.y, s.z, p.sun_illuminance()],
            screen: [w, hh, 1.0 / w, 1.0 / hh],
            post: [1.0, 0.0, f.index() as f32, 0.0],
            atmo: [mie, Self::altitude_km(pos.y), c.veil(), 0.9],
            water_col: [0.0, 0.0, 0.0, 0.0],
            // extinction par mètre au sol : Rayleigh + Mie (turbidité), en km^-1 -> m^-1
            fog_ext: [
                (5.802e-3 + 4.40e-3 * mie) * 1e-3,
                (13.558e-3 + 4.40e-3 * mie) * 1e-3,
                (33.1e-3 + 4.40e-3 * mie) * 1e-3,
                p.haze_floor_per_m(),
            ],
            cloud_p: [c.altitude_km(), c.coverage(), c.density(), c.wind_time()],
        }
    }

    /// Altitude de la caméra en km, plancher à 10 m.
    pub fn altitude_km(y_m: f32) -> f32 {
        (y_m * 0.001).max(Self::ALTITUDE_MIN_KM)
    }
}

/// Uniforme des LUT d'atmosphère : `x` = multiplicateur de Mie.
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct AtmoUniforme {
    pub haze: [f32; 4],
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn les_dispositions_gpu_ont_la_taille_du_wgsl() {
        assert_eq!(std::mem::size_of::<SkyFrame>(), 11 * 16);
        assert_eq!(std::mem::size_of::<AtmoUniforme>(), 16);
    }
}
