// Writes the population data: one record per villager (appearance + wardrobe + outfits).
// Usage: node tools/batch.mjs <outDir>
import fs from 'fs';
import { appearance } from '../gen/villager.js';
import { makeWardrobe } from '../gen/wardrobe.js';
import { population, appearanceRecord, WORLD_SEED } from '../gen/population.js';
import { GENERATOR_VERSION, DEFAULT_VOXEL } from '../gen/villager.js';
const here = new URL('..', import.meta.url).pathname;
const cat = JSON.parse(fs.readFileSync(here + 'data/catalog.json'));
const dir = process.argv[2] || 'out';
fs.mkdirSync(dir, { recursive: true });
const recs = [];
for (const p of population(cat)) {
  const bp = appearance(p.seed);
  const w = makeWardrobe({ bp, seed: p.seed }, cat, { village: p.village });
  recs.push({ id: p.id, seed: p.seed, appearance: appearanceRecord(bp), village: w.village, villageName: w.villageName, job: w.job, wealth: w.wealth, garments: w.garments, outfits: w.outfits, worn: 'everyday' });
}
const doc = { schema_version: 1, generator_version: GENERATOR_VERSION, world_seed: WORLD_SEED, voxel_size_m: DEFAULT_VOXEL, count: recs.length, villagers: recs };
fs.writeFileSync(dir + '/villagers.json', JSON.stringify(doc));
const jobs = {}; for (const r of recs) jobs[r.job] = (jobs[r.job] || 0) + 1;
const ages = {}; for (const r of recs) ages[r.appearance.ageClass] = (ages[r.appearance.ageClass] || 0) + 1;
const types = new Set(recs.flatMap(r => r.garments.map(g => g.type)));
console.log(recs.length, 'villagers;', (fs.statSync(dir + '/villagers.json').size / 1024).toFixed(0), 'KB; garments', recs.reduce((a, r) => a + r.garments.length, 0), '; types used', types.size);
console.log(JSON.stringify(ages), JSON.stringify(jobs));
