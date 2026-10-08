// Wardrobe: picks village, job, wealth and the garment records of one villager, and
// the outfits (lists of garment ids) for each occasion. Pure data, no voxels.
import { Rng, hashCombine } from './rng.js';

// The eight outfit keys of interfaces.md § 4 (order fixed, add at the end only).
export const OCCASIONS = ['everyday', 'work', 'travel', 'festive', 'mourning', 'cold', 'court', 'night'];
const MOURNING = ['black', 'charcoal', 'darkbrown', 'grey'];

function parseRule(rule) {
  const parts = rule.split(':');
  const slot = parts[0];
  const choices = parts[1].split('|').map(c => { const [name, sex] = c.split('@'); return { name, sex }; });
  const p = parts.length > 2 ? parseFloat(parts[2]) : 1;
  return { slot, choices, p };
}

function resolveParam(r, v) {
  if (Array.isArray(v)) {
    if (v.length === 2 && typeof v[0] === 'number' && typeof v[1] === 'number') return Math.round(r.range(v[0], v[1]) * 1000) / 1000;
    return r.pick(v);
  }
  return v;
}

export function makeWardrobe(base, catalog, opts = {}) {
  const bp = base.bp;
  const r = new Rng(hashCombine(base.seed, 'wardrobe'));
  const villages = Object.keys(catalog.villages);
  const village = opts.village ?? r.pick(villages);
  const V = catalog.villages[village];
  let job = opts.job;
  if (!job) {
    if (bp.ageClass === 'child') job = 'child';
    else if (bp.ageClass === 'elder' && r.chance(0.5)) job = 'elder';
    else job = r.wpick(V.jobs);
  }
  const J = catalog.jobs[job];
  const wealth = Math.round(r.range(J.wealth[0], J.wealth[1]) * 100) / 100;
  const sexKey = bp.ageClass === 'child' ? 'child' : bp.sex;
  const dye = name => catalog.dyes[name][0];
  const affordable = (list, boost = 0) => {
    const ok = list.filter(n => catalog.dyes[n][1] <= (wealth + boost) * 3 + 0.6);
    return ok.length ? ok : list;
  };
  let occNow = null; // occasion being built: mourning dyes cloth dark, court spends more
  const dyeList = spec => {
    if (occNow === 'mourning' && spec === 'palette') return affordable(MOURNING);
    return spec === 'palette' ? affordable(V.palette, occNow === 'court' ? 0.35 : 0) : spec;
  };
  const garments = [];
  const byType = new Map();
  const make = (type, slot, occasion) => {
    const key = type + (occasion === 'mourning' || occasion === 'court' ? '#' + occasion : '');
    if (byType.has(key)) return byType.get(key);
    const D = catalog.garments[type];
    if (!D) throw new Error('unknown garment ' + type);
    const gr = r.fork(type, garments.length);
    const main = gr.pick(dyeList(D.dyes));
    const colors = { main: dye(main) };
    if (D.trimDyes) { const opts = dyeList(D.trimDyes).filter(n => n !== main); colors.trim = dye(gr.pick(opts.length ? opts : dyeList(D.trimDyes))); }
    if (D.accentDyes) colors.accent = dye(gr.pick(D.accentDyes));
    else if (D.trimDyes) colors.accent = dye(gr.pick(['gold', 'weld', 'bleached', 'madder']));
    if (D.metalDyes) colors.metal = dye(gr.pick(D.metalDyes));
    if (/fur/.test(D.trimMaterial || '') || D.params.collar === 'fur') colors.fur = dye(gr.pick(['fur_light', 'fur_dark']));
    if (D.params.collar && Array.isArray(D.params.collar)) colors.fur = dye(gr.pick(['fur_light', 'fur_dark']));
    let pattern = null;
    if (D.pattern) {
      const kind = resolveParam(gr, D.pattern.kind);
      if (kind !== 'plain') {
        pattern = { kind };
        if (D.pattern.period) pattern.period = Math.round(resolveParam(gr, D.pattern.period));
        if (D.pattern.c2dye) { const l = dyeList(D.pattern.c2dye).filter(n => n !== main); pattern.c2 = dye(gr.pick(l.length ? l : dyeList(D.pattern.c2dye))); }
        if (D.pattern.c3dye) pattern.c3 = dye(gr.pick(dyeList(D.pattern.c3dye)));
      }
    }
    const params = {};
    for (const [k, v] of Object.entries(D.params)) params[k] = resolveParam(gr, v);
    let wear = Math.max(0, Math.min(1, (1 - wealth) * 0.5 + (J.dirt ?? 0.2) * (occasion === 'work' ? 0.6 : 0.2) + gr.range(-0.1, 0.15)));
    if (occasion === 'festive' || occasion === 'night' || occasion === 'mourning') wear *= 0.2;
    if (occasion === 'court') wear *= 0.05;
    const g = { id: 'g' + garments.length, type, slot: D.slot, builder: D.builder, material: D.material, colors, pattern, params, wear: Math.round(wear * 100) / 100, seed: gr.u32() };
    if (D.trimMaterial) g.trimMaterial = D.trimMaterial;
    if (D.embroider) g.embroider = gr.pick(D.embroider);
    garments.push(g);
    byType.set(key, g);
    return g;
  };
  const pickRule = (rule, occ) => {
    const R = parseRule(rule);
    if (!r.chance(R.p)) return { slot: R.slot, id: null };
    const ok = R.choices.filter(c => !c.sex || c.sex === bp.sex);
    if (!ok.length) return { slot: R.slot, id: null };
    const c = r.pick(ok);
    if (c.name === 'none') return { slot: R.slot, id: null };
    return { slot: R.slot, id: make(c.name, R.slot, occ).id };
  };
  const build = (rules, occ, start = {}) => {
    occNow = occ;
    const out = { ...start };
    for (const rule of rules) { const { slot, id } = pickRule(rule, occ); out[slot] = id; }
    return out;
  };
  const baseRules = catalog.base[sexKey];
  const everyday = build(baseRules.everyday, 'everyday');
  const work = job === 'child' || job === 'elder' ? build(J.work, 'work', {}) : build(J.work, 'work', {});
  const festive = build(catalog.base.festive, 'festive', { ...everyday });
  if (bp.ageClass === 'child') { festive.neck = null; }
  const travel = build(catalog.base.travel, 'travel', { ...everyday });
  // mourning: the everyday cut remade in dark dyes, head covered
  const mourning = build([...baseRules.everyday, ...catalog.base.mourning], 'mourning');
  // court: best clothes the household can afford, a step above the festive ones
  const court = build(catalog.base.court, 'court', bp.ageClass === 'child' ? { ...festive } : build(baseRules.everyday, 'court'));
  const cold = build(catalog.base.cold, 'cold', { ...(job === 'child' ? everyday : work) });
  if (cold.acc) cold.acc = null; // no backpack under a cloak
  const night = build(baseRules.night, 'night');
  const clean = o => Object.values(o).filter(Boolean);
  const outfits = { everyday: clean(everyday), work: clean(work), travel: clean(travel), festive: clean(festive), mourning: clean(mourning), cold: clean(cold), court: clean(court), night: clean(night) };
  // drop garments never used (can happen when a slot was overridden)
  const used = new Set(Object.values(outfits).flat());
  const kept = garments.filter(g => used.has(g.id));
  return { schema_version: 1, village, villageName: V.name, job, wealth, garments: kept, outfits };
}
