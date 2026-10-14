// Writes the character sheets of interfaces.md § 5 (schema_version 1), one per villager,
// from data/villagers.json. Each garment recipe gets its contract slot, its layer and the
// mask of body zones it covers (measured on that villager's own body).
// Usage: node tools/fiches.mjs [from] [to]   -> data/fiches.json (or data/fiches_<from>_<to>.json)
import fs from 'fs';
import { generateVillager } from '../gen/villager.js';
import { dressOutfit } from '../gen/garments.js';
import { LAYER } from '../gen/head.js';
import { MODE_SKIRT } from '../gen/body.js';
const here = new URL('..', import.meta.url).pathname;
const cat = JSON.parse(fs.readFileSync(here + 'data/catalog.json'));
const pop = JSON.parse(fs.readFileSync(here + 'data/villagers.json'));

export const VILLAGE_ID = { mer: 'sea_village', foret: 'forest_village', montagne: 'mountain_village', desert: 'desert_village', bourg: 'market_town' };
// internal layer -> contract slot (§ 4); a slot may hold several garments, ordered by `layer`
const SLOT = { legs: 'legs', feet: 'feet', shirt: 'torso', over: 'torso', vest: 'over', belt: 'belt', apron: 'over', hands: 'hands', cloak: 'outer', head: 'head', acc: 'back', neck: 'neck' };
// body zones, bit order of interfaces.md § 4
const ZONES = ['head', 'neck', 'torso_upper', 'torso_lower', 'upper_arm_l', 'upper_arm_r', 'forearm_l', 'forearm_r', 'hand_l', 'hand_r', 'pelvis', 'thigh_l', 'thigh_r', 'shin_l', 'shin_r', 'feet'];
function zoneOf(name) {
  const side = name.startsWith('Left') ? 0 : 1;
  if (/^(Head|Jaw|LeftEye|RightEye)$/.test(name)) return 0;
  if (name === 'Neck') return 1;
  if (/^(Chest|UpperChest)$|Shoulder/.test(name)) return 2;
  if (name === 'Spine') return 3;
  if (/UpperArm/.test(name)) return 4 + side;
  if (/LowerArm/.test(name)) return 6 + side;
  if (/Hand|Thumb|Index|Middle|Ring|Little/.test(name)) return 8 + side;
  if (name === 'Hips') return 10;
  if (/UpperLeg/.test(name)) return 11 + side;
  if (/LowerLeg/.test(name)) return 13 + side;
  if (/Foot|Toes/.test(name)) return 15;
  return -1;
}
const rgb = h => { const n = parseInt(h.slice(1), 16); return [(n >> 16) / 255, (n >> 8 & 255) / 255, (n & 255) / 255].map(v => Math.round(v * 1000) / 1000); };

function covers(base, g) {
  const grid = base.grid.clone();
  dressOutfit(base, grid, { garments: [g], outfits: { x: [g.id] } }, 'x');
  const L = LAYER[g.slot], cnt = new Int32Array(16), names = base.sk.bones.map(b => b.name);
  const yHip = base.P.yHip * base.U, yK = base.P.yK * base.U;
  for (let i = 0; i < grid.col.length; i++) if (grid.col[i] && grid.layer[i] === L) {
    let z = zoneOf(names[grid.bone[i]]);
    if (grid.mode[i] === MODE_SKIRT) { // a skirt hangs from the hips: zone by height and side
      const y = Math.floor(i / grid.nx) % grid.ny + 0.5, side = i % grid.nx < grid.ox ? 1 : 0;
      z = y > yHip ? 10 : y > yK ? 11 + side : 13 + side;
    }
    if (z >= 0) cnt[z]++;
  }
  let m = 0; for (let z = 0; z < 16; z++) if (cnt[z] >= 24) m |= 1 << z;
  return m;
}

export function sheet(rec) {
  const v = generateVillager(rec.seed, cat, { village: rec.village });
  const a = rec.appearance, gs = new Map();
  for (const g of rec.garments) {
    const colors = [g.colors.main, g.colors.trim, g.colors.accent].filter(Boolean).map(rgb);
    gs.set(g.id, {
      slot: SLOT[g.slot], layer: LAYER[g.slot], type: g.type, id: g.type + '_v1', material: g.material, colors,
      pattern: g.pattern ? g.pattern.kind : 'plain', wear: g.wear, seed: g.seed, covers: covers(v.base, g),
      generator: { builder: g.builder, slot: g.slot, colors: g.colors, pattern: g.pattern, params: g.params, trimMaterial: g.trimMaterial, embroider: g.embroider },
    });
  }
  const outfits = {};
  for (const [k, ids] of Object.entries(rec.outfits)) outfits[k] = ids.map(id => gs.get(id)).sort((x, y) => x.layer - y.layer);
  return {
    schema_version: 1, id: rec.id, seed: rec.seed,
    age_category: a.ageClass, age_years: a.age, sex: a.sex === 'f' ? 'female' : 'male', height_m: a.height,
    body: { base: 'human_base_v1', shapes: { weight: a.build, muscle: a.muscle, jaw: Math.round(a.jaw * 1000) / 1000, ...(a.sex === 'f' && (a.ageClass === 'adult' || a.ageClass === 'elder') ? { bust: Math.round(a.bust * 1000) / 1000 } : {}) } },
    skin_tone: Math.round(a.skinIndex / 8 * 1000) / 1000,
    hair: { style: a.hairStyle, color: rgb(a.hairColor), beard: a.beard },
    eyes: { color: rgb(a.eyes) },
    village: VILLAGE_ID[rec.village], job: rec.job, wealth: rec.wealth,
    outfits,
  };
}

if (process.argv[1] && process.argv[1].endsWith('fiches.mjs')) {
  const from = +(process.argv[2] ?? 0), to = +(process.argv[3] ?? pop.villagers.length);
  const t = Date.now(), out = [];
  for (let i = from; i < to; i++) out.push(sheet(pop.villagers[i]));
  const doc = { schema_version: 1, generator_version: pop.generator_version, world_seed: pop.world_seed, voxel_size_m: pop.voxel_size_m, zones: ZONES, count: out.length, characters: out };
  const f = here + 'data/' + (process.argv[2] ? `fiches_${from}_${to}.json` : 'fiches.json');
  fs.writeFileSync(f, JSON.stringify(doc));
  console.log(out.length, 'sheets', (fs.statSync(f).size / 1024).toFixed(0), 'KB', ((Date.now() - t) / 1000).toFixed(1), 's');
}
