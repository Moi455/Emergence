//! Bruit de valeur entier (lissé), pour les plaques de mousse et les taches : une valeur 0..=65535 par point, calculée
//! par hachage de cellules de `cell` voxels et interpolation lissée. Tout est entier ; la même position donne
//! toujours la même valeur, quel que soit le découpage en chunks.

use super::rng::hh;

fn lisse(t: i64, d: i64) -> i64 {
    // 3t^2 - 2t^3 avec t = t/d, résultat sur 0..=65536
    let f = (t << 16) / d;
    (f * f * (3 * 65_536 - 2 * f)) >> 32
}

/// Bruit de valeur 2D, 0..=65535.
pub fn vnoise2(x: i32, z: i32, cell: i32, seed: i32) -> u32 {
    let cell = cell.max(1);
    let (xi, zi) = (x.div_euclid(cell), z.div_euclid(cell));
    let (fx, fz) = (i64::from(x.rem_euclid(cell)), i64::from(z.rem_euclid(cell)));
    let (u, v) = (lisse(fx, i64::from(cell)), lisse(fz, i64::from(cell)));
    let h = |a: i32, b: i32| i64::from(hh(a, b, seed, 0) >> 16);
    let (a, b, c, d) = (h(xi, zi), h(xi + 1, zi), h(xi, zi + 1), h(xi + 1, zi + 1));
    let ab = a + (((b - a) * u) >> 16);
    let cd = c + (((d - c) * u) >> 16);
    (ab + (((cd - ab) * v) >> 16)).clamp(0, 65_535) as u32
}

/// Bruit de valeur 3D, 0..=65535.
pub fn vnoise3(x: i32, y: i32, z: i32, cell: i32, seed: i32) -> u32 {
    let cell = cell.max(1);
    let (xi, yi, zi) = (x.div_euclid(cell), y.div_euclid(cell), z.div_euclid(cell));
    let f = |v: i32| i64::from(v.rem_euclid(cell));
    let (u, w, t) = (
        lisse(f(x), i64::from(cell)),
        lisse(f(y), i64::from(cell)),
        lisse(f(z), i64::from(cell)),
    );
    let h = |a: i32, b: i32, c: i32| i64::from(hh(a ^ seed.wrapping_mul(7919), b, c, seed) >> 16);
    let lerp = |a: i64, b: i64, k: i64| a + (((b - a) * k) >> 16);
    let c00 = lerp(h(xi, yi, zi), h(xi + 1, yi, zi), u);
    let c10 = lerp(h(xi, yi + 1, zi), h(xi + 1, yi + 1, zi), u);
    let c01 = lerp(h(xi, yi, zi + 1), h(xi + 1, yi, zi + 1), u);
    let c11 = lerp(h(xi, yi + 1, zi + 1), h(xi + 1, yi + 1, zi + 1), u);
    let c0 = lerp(c00, c10, w);
    let c1 = lerp(c01, c11, w);
    lerp(c0, c1, t).clamp(0, 65_535) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bruit_continu_et_borne() {
        let mut maxd = 0;
        for x in 0..200 {
            let (a, b) = (vnoise2(x, 5, 8, 3), vnoise2(x + 1, 5, 8, 3));
            maxd = maxd.max((i64::from(a) - i64::from(b)).abs());
            assert!(a <= 65_535);
        }
        assert!(maxd < 65_535 / 3, "pas de saut brutal : {maxd}");
        assert_eq!(vnoise2(-13, 7, 8, 1), vnoise2(-13, 7, 8, 1));
        assert!(vnoise3(1, 2, 3, 4, 5) <= 65_535);
    }
}
