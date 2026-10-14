//! Cost of the simulation window on synthetic, very mountainous terrain.
//! usage: bench [fine_radius_m=20] [coarse_radius_m=64] [springs=8] [spring_m3s=0.03] [sim_seconds=120] [d_min_m=0.0005]
use em_water::*;
use std::time::Instant;

fn hash(ix: i64, iz: i64) -> f64 {
    let mut h = (ix as u64).wrapping_mul(0x9E3779B97F4A7C15) ^ (iz as u64).wrapping_mul(0xC2B2AE3D27D4EB4F);
    h ^= h >> 29; h = h.wrapping_mul(0xBF58476D1CE4E5B9); h ^= h >> 32;
    (h >> 11) as f64 / (1u64 << 53) as f64
}
fn vnoise(x: f64, z: f64) -> f64 {
    let (ix, iz) = (x.floor(), z.floor());
    let (fx, fz) = (x - ix, z - iz);
    let (sx, sz) = (fx * fx * (3.0 - 2.0 * fx), fz * fz * (3.0 - 2.0 * fz));
    let (ix, iz) = (ix as i64, iz as i64);
    let a = hash(ix, iz); let b = hash(ix + 1, iz); let c = hash(ix, iz + 1); let d = hash(ix + 1, iz + 1);
    (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sz
}
/// ridged multifractal: sharp crests, gorges, no plains (relief ~ 100 m over 128 m)
fn terrain(x: f64, z: f64) -> f64 {
    let (mut amp, mut f, mut h, mut w) = (60.0, 1.0 / 90.0, 0.0, 1.0);
    for _ in 0..7 {
        let n = 1.0 - (2.0 * vnoise(x * f + 17.3, z * f + 4.1) - 1.0).abs();
        let n = n * n * w;
        h += n * amp; w = (n * 1.8).min(1.0);
        amp *= 0.5; f *= 2.05;
    }
    h
}

fn main() {
    let a: Vec<f64> = std::env::args().skip(1).map(|s| s.parse().unwrap()).collect();
    let rf = *a.get(0).unwrap_or(&20.0);
    let rc = *a.get(1).unwrap_or(&64.0);
    let springs = *a.get(2).unwrap_or(&8.0) as usize;
    let rate = *a.get(3).unwrap_or(&0.03);
    let secs = *a.get(4).unwrap_or(&120.0);
    let dmin = *a.get(5).unwrap_or(&0.0005);
    let n = ((2.0 * rc / VOX) as usize / 5) * 5;
    let c = n / 2;
    let fr = (rf / VOX) as usize;
    let rect = [(c - fr) / 5 * 5, (c - fr) / 5 * 5, (c + fr) / 5 * 5, (c + fr) / 5 * 5];
    let t0 = Instant::now();
    let top: Vec<f32> = heights(n, n, terrain).into_iter().map(|h| ((h as f64 / VOX).round() * VOX) as f32).collect();
    let (mut lo, mut hi) = (f32::MAX, f32::MIN);
    for &h in &top { lo = lo.min(h); hi = hi.max(h); }
    let mut s = { let mut p = Params::default(); p.d_min = dmin; Sim::new(Layout::with_fine(n, n, rect), top.clone(), p) };
    println!("window {n}x{n} voxels ({:.0} m), fine rect {:?}; terrain {:.0}..{:.0} m; build {:.2} s", n as f64 * VOX, rect, lo, hi, t0.elapsed().as_secs_f64());
    println!("cells {} (fine {} + coarse {}), edges {}, openings {}", s.n_cells(), (rect[2]-rect[0])*(rect[3]-rect[1]), s.n_cells() - (rect[2]-rect[0])*(rect[3]-rect[1]), s.n_edges(), s.n_openings());
    // springs: the highest columns of the fine window, on a coarse grid so they are spread out
    let mut cand: Vec<(f32, usize, usize)> = Vec::new();
    for z in (rect[1] + 10..rect[3] - 10).step_by(40) { for x in (rect[0] + 10..rect[2] - 10).step_by(40) { cand.push((top[z * n + x], x, z)); } }
    cand.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    for &(_, x, z) in cand.iter().take(springs) { s.add_source(vec![s.cell_at(x, z) as u32], rate); }
    // drains: the whole boundary of the window (water leaves the simulated area)
    let mut sinks = Vec::new();
    for i in 0..n { for &(x, z) in &[(i, 0), (i, n - 1), (0, i), (n - 1, i)] { sinks.push(s.cell_at(x, z) as u32); } }
    sinks.sort(); sinks.dedup();
    s.add_sinks(&sinks);
    println!("{} springs x {} m3/s, sim {} s", springs, rate, secs);
    let v0 = s.total_volume_mm3();
    let mut wall_total = 0.0; let mut steps_total = 0u64;
    let mut worst = 0.0f64;
    let slice = 10.0;
    let mut t = 0.0;
    while t < secs {
        let w = Instant::now();
        let st = s.advance(slice);
        let dt = w.elapsed().as_secs_f64();
        wall_total += dt; steps_total += st; worst = worst.max(dt / slice);
        t += slice;
        if ((t / slice) as i64) % 2 == 0 {
            println!("t={:>5.0} s  stored {:>8.2} m3  active cells {:>7}  active edges {:>7}  steps {:>6}  wall {:>6.1} ms per sim-s", t, s.total_volume_m3(), s.n_active_cells(), s.n_active_edges(), st, dt / slice * 1e3);
        }
    }
    let _ = v0;
    println!("TOTAL: {:.2} s wall for {:.0} s simulated = {:.1} ms per simulated second = {:.1} % of ONE core at real time (worst slice {:.1} %)", wall_total, secs, wall_total / secs * 1e3, wall_total / secs * 100.0, worst * 100.0);
    println!("avg {:.0} steps per sim-s; avg dt {:.2} ms", steps_total as f64 / secs, secs / steps_total as f64 * 1e3);
}
