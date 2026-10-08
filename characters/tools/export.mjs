// Usage: node tools/export.mjs <seed> [outDir] [village]  -> writes <outDir>/villager_<seed>.glb
import fs from 'fs';
import zlib from 'zlib';
import { generateVillager, composeOutfit, meshOutfit } from '../gen/villager.js';
import { OCCASIONS } from '../gen/wardrobe.js';
import { makeClips } from '../gen/anim.js';
import { writeGLB, makePNGEncoder } from '../gen/gltf.js';
const here = new URL('..', import.meta.url).pathname;
const cat = JSON.parse(fs.readFileSync(here + 'data/catalog.json'));
const png = makePNGEncoder(b => zlib.deflateSync(b, { level: 9 }));

export function exportVillager(seed, opts = {}) {
  const v = generateVillager(seed, cat, opts);
  const outfits = [];
  for (const occ of OCCASIONS) {
    const grid = composeOutfit(v, occ, cat);
    outfits.push({ name: occ, garments: v.wardrobe.outfits[occ], mesh: meshOutfit(v.base, grid) });
    if (opts.lods !== false) for (const lod of [1, 2, 3]) outfits.push({ name: occ + '_LOD' + lod, lod, garments: v.wardrobe.outfits[occ], mesh: meshOutfit(v.base, grid, lod) });
  }
  const clips = makeClips(v.base.sk, v.bp);
  const glb = writeGLB({ name: 'Villager_' + seed, sk: v.base.sk, voxel: v.base.voxel, outfits, clips, extras: { seed } }, png);
  return { v, glb, outfits };
}

if (process.argv[1] && process.argv[1].endsWith('export.mjs')) {
  const seed = +process.argv[2], dir = process.argv[3] || 'out';
  fs.mkdirSync(dir, { recursive: true });
  const t = Date.now();
  const village = process.argv[4];
  const { glb, outfits } = exportVillager(seed, village ? { village } : {});
  fs.writeFileSync(`${dir}/villager_${seed}.glb`, glb);
  console.log(`villager_${seed}.glb`, (glb.length / 1024).toFixed(0) + ' KB', outfits.map(o => o.name + ':' + o.mesh.indices.length / 3).join(' '), (Date.now() - t) + ' ms');
}
