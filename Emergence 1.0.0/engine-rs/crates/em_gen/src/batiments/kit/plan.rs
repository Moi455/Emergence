//! `ShapePlan` : un plan fait de PARTIES ordonnées, rastérisé fenêtre par fenêtre à tout niveau de détail.
//!
//! Le plan ne stocke aucun voxel : seulement la recette (des parties, chacune une boîte et une règle de peinture).
//! `rasterize(lod, fenetre)` peint les parties qui touchent la fenêtre, dans l'ordre, dans un tampon `Window`, puis
//! écrit les voxels pleins. Les niveaux grossiers sont la réduction 4/8 d'`em_voxel` des voxels fins, calculée par
//! morceaux de 32 voxels : un chunk lointain coûte le volume fin qu'il résume, jamais une grille entière.
//!
//! Le plan peut être MIROITÉ en z (le générateur JavaScript a son sud en +z, le monde en -z) et décalé : la
//! conversion se fait à l'écriture du niveau 0, jamais dans les parties.

use em_core::{Fnv64, Lod, MaterialId, VoxelBox, VoxelCoord, VoxelValue, floor_div};
use em_voxel::{PutMode, ReduceRule, VoxelSink};

use super::window::Window;
use crate::generator::GenPlan;

/// Dernier niveau de détail servi.
pub const MAX_LOD: Lod = 5;
/// Arête d'un morceau de réduction (en voxels du niveau demandé).
const MORCEAU: i32 = 32;

/// Une partie d'un plan : une boîte (où elle peut écrire) et sa peinture.
pub trait Part: Send + Sync {
    /// Boîte (repère du plan, demi-ouverte) hors de laquelle la partie n'écrit jamais.
    fn bounds(&self) -> VoxelBox;
    /// Peint dans la fenêtre (écritures hors fenêtre ignorées). Fonction pure : ne dépend que de la partie.
    fn paint(&self, fenetre: &mut Window);
}

/// Placement du repère de la recette dans le repère du plan servi.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Placement {
    /// Décalage ajouté à x (repère recette -> plan).
    pub dx: i32,
    /// Décalage ajouté à y.
    pub dy: i32,
    /// Décalage ajouté à z (après miroir éventuel).
    pub dz: i32,
    /// Miroir en z : `z_plan = -z_recette - 1 + dz`.
    pub mirror_z: bool,
}

impl Placement {
    /// Aucune transformation.
    pub const IDENTITE: Placement = Placement {
        dx: 0,
        dy: 0,
        dz: 0,
        mirror_z: false,
    };

    fn vers_plan(&self, v: [i32; 3]) -> [i32; 3] {
        let z = if self.mirror_z { -v[2] - 1 } else { v[2] };
        [v[0] + self.dx, v[1] + self.dy, z + self.dz]
    }

    /// Boîte du plan correspondant à une boîte de la recette.
    fn boite_vers_plan(&self, lo: [i32; 3], hi: [i32; 3]) -> ([i32; 3], [i32; 3]) {
        if self.mirror_z {
            // [lo, hi) en z devient [-hi + dz, -lo + dz)
            (
                [lo[0] + self.dx, lo[1] + self.dy, -hi[2] + self.dz],
                [hi[0] + self.dx, hi[1] + self.dy, -lo[2] + self.dz],
            )
        } else {
            (
                [lo[0] + self.dx, lo[1] + self.dy, lo[2] + self.dz],
                [hi[0] + self.dx, hi[1] + self.dy, hi[2] + self.dz],
            )
        }
    }

    /// Boîte de la recette correspondant à une boîte du plan.
    fn boite_vers_recette(&self, lo: [i32; 3], hi: [i32; 3]) -> ([i32; 3], [i32; 3]) {
        if self.mirror_z {
            (
                [lo[0] - self.dx, lo[1] - self.dy, -(hi[2] - self.dz)],
                [hi[0] - self.dx, hi[1] - self.dy, -(lo[2] - self.dz)],
            )
        } else {
            (
                [lo[0] - self.dx, lo[1] - self.dy, lo[2] - self.dz],
                [hi[0] - self.dx, hi[1] - self.dy, hi[2] - self.dz],
            )
        }
    }
}

/// Le plan : parties ordonnées + boîte + placement + échelle du voxel.
pub struct ShapePlan {
    parts: Vec<Box<dyn Part>>,
    bounds0: VoxelBox,
    placement: Placement,
    voxel_mm: u32,
    regle: ReduceRule,
}

fn boite(lo: [i32; 3], hi: [i32; 3]) -> VoxelBox {
    VoxelBox::new(
        VoxelCoord::new(lo[0], lo[1], lo[2]),
        VoxelCoord::new(hi[0], hi[1], hi[2]),
    )
    .expect("boîte ordonnée")
}

impl ShapePlan {
    /// Construit le plan ; la boîte est l'union des parties. `priorite` ordonne les matières à égalité dans la
    /// réduction (sans doublon : les doublons sont retirés).
    pub fn new(
        parts: Vec<Box<dyn Part>>,
        placement: Placement,
        voxel_mm: u32,
        priorite: Vec<MaterialId>,
    ) -> Self {
        let mut lo = [i32::MAX; 3];
        let mut hi = [i32::MIN; 3];
        for p in &parts {
            let b = p.bounds();
            if b.is_empty() {
                continue;
            }
            let (a, c) = (b.min(), b.max());
            for (k, (u, v)) in [(a.x, c.x), (a.y, c.y), (a.z, c.z)].into_iter().enumerate() {
                lo[k] = lo[k].min(u);
                hi[k] = hi[k].max(v);
            }
        }
        if lo[0] > hi[0] {
            lo = [0; 3];
            hi = [0; 3];
        }
        let (plo, phi) = placement.boite_vers_plan(lo, hi);
        let mut vus = Vec::new();
        let priorite: Vec<MaterialId> = priorite
            .into_iter()
            .filter(|m| {
                let neuf = !vus.contains(m);
                vus.push(*m);
                neuf
            })
            .collect();
        Self {
            parts,
            bounds0: boite(plo, phi),
            placement,
            voxel_mm,
            regle: ReduceRule::majority_4_of_8(priorite).expect("priorité sans doublon"),
        }
    }

    /// Boîte du niveau 0 : (minimum, maximum exclu).
    pub fn bounds_box(&self) -> ([i32; 3], [i32; 3]) {
        let (a, c) = (self.bounds0.min(), self.bounds0.max());
        ([a.x, a.y, a.z], [c.x, c.y, c.z])
    }

    /// Taille du voxel de ce plan, en millimètres (50 par défaut, 20 pour le petit).
    pub const fn voxel_mm(&self) -> u32 {
        self.voxel_mm
    }

    /// Nombre de parties.
    pub fn part_count(&self) -> usize {
        self.parts.len()
    }

    /// Peint la boîte `[lo, hi)` du niveau 0 (repère du plan servi).
    fn rendre_niveau0(&self, lo: [i32; 3], hi: [i32; 3]) -> Window {
        let mut sortie = Window::new(boite(lo, hi));
        let (rlo, rhi) = self.placement.boite_vers_recette(lo, hi);
        let mut local = Window::new(boite(rlo, rhi));
        for p in &self.parts {
            let b = p.bounds();
            let (a, c) = (b.min(), b.max());
            if a.x >= rhi[0]
                || c.x <= rlo[0]
                || a.y >= rhi[1]
                || c.y <= rlo[1]
                || a.z >= rhi[2]
                || c.z <= rlo[2]
            {
                continue;
            }
            p.paint(&mut local);
        }
        for (v, valeur) in local.solids() {
            let q = self.placement.vers_plan([v.x, v.y, v.z]);
            sortie.put(q[0], q[1], q[2], valeur);
        }
        sortie
    }

    /// Fenêtre du niveau `lod` sur `[lo, hi)` : réduction récursive des voxels fins.
    pub fn render(&self, lod: Lod, lo: [i32; 3], hi: [i32; 3]) -> Window {
        if lod == 0 {
            return self.rendre_niveau0(lo, hi);
        }
        let mut sortie = Window::new(boite(lo, hi));
        let mut z0 = lo[2];
        while z0 < hi[2] {
            let z1 = (z0 + MORCEAU).min(hi[2]);
            let mut y0 = lo[1];
            while y0 < hi[1] {
                let y1 = (y0 + MORCEAU).min(hi[1]);
                let mut x0 = lo[0];
                while x0 < hi[0] {
                    let x1 = (x0 + MORCEAU).min(hi[0]);
                    let enfant = self.render(lod - 1, [2 * x0, 2 * y0, 2 * z0], [2 * x1, 2 * y1, 2 * z1]);
                    if !enfant.is_empty() {
                        for y in y0..y1 {
                            for z in z0..z1 {
                                for x in x0..x1 {
                                    let huit: [VoxelValue; 8] = std::array::from_fn(|k| {
                                        let (dx, dz, dy) =
                                            ((k & 1) as i32, ((k >> 1) & 1) as i32, (k >> 2) as i32);
                                        enfant.get(2 * x + dx, 2 * y + dy, 2 * z + dz)
                                    });
                                    let r = self.regle.reduce8(huit);
                                    if !r.is_air() {
                                        sortie.put(x, y, z, r);
                                    }
                                }
                            }
                        }
                    }
                    x0 = x1;
                }
                y0 = y1;
            }
            z0 = z1;
        }
        sortie
    }

    /// Empreinte FNV-64 du niveau 0 : fenêtres de 64 voxels dans l'ordre (y, z, x) de leur origine, chacune hachée
    /// sur ses voxels pleins (y, z, x). `fils` répartit les fenêtres ; l'empreinte ne dépend pas de `fils`.
    pub fn fingerprint(&self, fils: usize) -> u64 {
        let b = self.bounds0;
        let (a, c) = (b.min(), b.max());
        let tuile = 64;
        let (ox, oy, oz) = (
            floor_div(i64::from(a.x), tuile) * tuile,
            floor_div(i64::from(a.y), tuile) * tuile,
            floor_div(i64::from(a.z), tuile) * tuile,
        );
        let mut origines = Vec::new();
        let mut y = oy;
        while y < i64::from(c.y) {
            let mut z = oz;
            while z < i64::from(c.z) {
                let mut x = ox;
                while x < i64::from(c.x) {
                    origines.push([x as i32, y as i32, z as i32]);
                    x += tuile;
                }
                z += tuile;
            }
            y += tuile;
        }
        let hacher = |o: &[i32; 3]| -> u64 {
            let w = self.rendre_niveau0(*o, [o[0] + 64, o[1] + 64, o[2] + 64]);
            let mut h = Fnv64::new();
            let mut vide = true;
            for (v, valeur) in w.solids() {
                vide = false;
                for k in [v.x, v.y, v.z] {
                    h.add_u64(i64::from(k) as u64);
                }
                h.add_u64(u64::from(valeur.raw()));
            }
            if vide { 0 } else { h.value() }
        };
        let fils = fils.max(1);
        let mut partiels = vec![0_u64; origines.len()];
        if fils == 1 {
            for (i, o) in origines.iter().enumerate() {
                partiels[i] = hacher(o);
            }
        } else {
            std::thread::scope(|s| {
                let par = origines.len().div_ceil(fils).max(1);
                for (parts_o, parts_p) in origines.chunks(par).zip(partiels.chunks_mut(par)) {
                    s.spawn(move || {
                        for (o, p) in parts_o.iter().zip(parts_p.iter_mut()) {
                            *p = hacher(o);
                        }
                    });
                }
            });
        }
        let mut h = Fnv64::new();
        for k in [a.x, a.y, a.z, c.x, c.y, c.z] {
            h.add_u64(i64::from(k) as u64);
        }
        for (o, p) in origines.iter().zip(&partiels) {
            if *p != 0 {
                for k in o {
                    h.add_u64(i64::from(*k) as u64);
                }
                h.add_u64(*p);
            }
        }
        h.value()
    }

    /// Nombre de voxels pleins du niveau 0 (tout le plan, par fenêtres de 64).
    pub fn solid_count(&self) -> usize {
        let b = self.bounds0;
        let (a, c) = (b.min(), b.max());
        let mut n = 0;
        let mut y = a.y;
        while y < c.y {
            let mut z = a.z;
            while z < c.z {
                let mut x = a.x;
                while x < c.x {
                    n += self
                        .rendre_niveau0(
                            [x, y, z],
                            [(x + 64).min(c.x), (y + 64).min(c.y), (z + 64).min(c.z)],
                        )
                        .solid_count();
                    x += 64;
                }
                z += 64;
            }
            y += 64;
        }
        n
    }
}

fn niveau(v: i32, lod: Lod, haut: bool) -> i32 {
    let pas = 1_i64 << lod.min(31);
    let v = i64::from(v);
    (if haut {
        floor_div(v - 1, pas) + 1
    } else {
        floor_div(v, pas)
    }) as i32
}

impl GenPlan for ShapePlan {
    fn bounds(&self, lod: Lod) -> VoxelBox {
        if lod > MAX_LOD {
            let o = self.bounds0.min();
            return VoxelBox::new(o, o).expect("boîte vide valide");
        }
        let (a, c) = (self.bounds0.min(), self.bounds0.max());
        boite(
            [
                niveau(a.x, lod, false),
                niveau(a.y, lod, false),
                niveau(a.z, lod, false),
            ],
            [
                niveau(c.x, lod, true),
                niveau(c.y, lod, true),
                niveau(c.z, lod, true),
            ],
        )
    }

    fn rasterize(&self, lod: Lod, window: VoxelBox, sink: &mut dyn VoxelSink) {
        if lod > MAX_LOD {
            return;
        }
        let b = self.bounds(lod);
        let (wa, wb, ba, bb) = (window.min(), window.max(), b.min(), b.max());
        let lo = [wa.x.max(ba.x), wa.y.max(ba.y), wa.z.max(ba.z)];
        let hi = [wb.x.min(bb.x), wb.y.min(bb.y), wb.z.min(bb.z)];
        if lo[0] >= hi[0] || lo[1] >= hi[1] || lo[2] >= hi[2] {
            return;
        }
        let w = self.render(lod, lo, hi);
        for (v, valeur) in w.solids() {
            sink.put(v, valeur, PutMode::Solid);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Cube {
        lo: [i32; 3],
        hi: [i32; 3],
        v: VoxelValue,
    }

    impl Part for Cube {
        fn bounds(&self) -> VoxelBox {
            boite(self.lo, self.hi)
        }
        fn paint(&self, w: &mut Window) {
            w.fill(self.lo, self.hi, self.v);
        }
    }

    fn plan(placement: Placement) -> ShapePlan {
        let pierre = VoxelValue::new(MaterialId::new(20), 1);
        let creux = VoxelValue::AIR;
        ShapePlan::new(
            vec![
                Box::new(Cube {
                    lo: [0, 0, 0],
                    hi: [40, 20, 30],
                    v: pierre,
                }),
                Box::new(Cube {
                    lo: [10, 5, 0],
                    hi: [14, 12, 30],
                    v: creux,
                }),
            ],
            placement,
            50,
            vec![MaterialId::new(20)],
        )
    }

    #[test]
    fn la_fenetre_creuse_et_l_empreinte_ne_depend_pas_des_fils() {
        let p = plan(Placement::IDENTITE);
        assert_eq!(p.solid_count(), 40 * 20 * 30 - 4 * 7 * 30);
        assert_eq!(p.fingerprint(1), p.fingerprint(8));
    }

    #[test]
    fn le_miroir_conserve_le_volume_et_garde_la_chiralite() {
        let m = plan(Placement {
            mirror_z: true,
            ..Placement::IDENTITE
        });
        assert_eq!(m.solid_count(), 40 * 20 * 30 - 4 * 7 * 30);
        let b = m.bounds(0);
        assert_eq!((b.min().z, b.max().z), (-30, 0));
    }

    #[test]
    fn un_chunk_cote_a_cote_donne_les_memes_voxels_que_la_boite_entiere() {
        let p = plan(Placement::IDENTITE);
        let tout = p.render(0, [0, 0, 0], [64, 64, 64]);
        let a = p.render(0, [0, 0, 0], [20, 64, 64]);
        let b = p.render(0, [20, 0, 0], [64, 64, 64]);
        assert_eq!(a.solid_count() + b.solid_count(), tout.solid_count());
    }

    #[test]
    fn les_niveaux_grossiers_viennent_de_la_reduction() {
        let p = plan(Placement::IDENTITE);
        let n1 = p.render(1, [0, 0, 0], [32, 32, 32]);
        assert!(n1.solid_count() > 0);
        let b = p.bounds(1);
        assert_eq!((b.min().x, b.max().x), (0, 20));
    }
}
