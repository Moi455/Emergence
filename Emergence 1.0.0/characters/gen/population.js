// The village population: 120 villagers per village, each a seed plus its village.
import { hashCombine } from './rng.js';
import { appearance, buildBase } from './villager.js';

export const WORLD_SEED = 'emergence-v1';
export const PER_VILLAGE = 120;

export function population(catalog) {
  const villages = Object.keys(catalog.villages);
  const out = [];
  villages.forEach((v, vi) => {
    for (let k = 0; k < PER_VILLAGE; k++) {
      const id = vi * PER_VILLAGE + k;
      out.push({ id, seed: hashCombine(WORLD_SEED, id), village: v });
    }
  });
  return out;
}

// serialisable appearance record (colors as #rrggbb)
export function appearanceRecord(bp) {
  const o = {};
  for (const [k, v] of Object.entries(bp)) {
    if (['skin', 'hairColor', 'eyes', 'beardTint', 'stubbleColor', 'tieColor'].includes(k)) o[k] = '#' + v.toString(16).padStart(6, '0');
    else o[k] = v;
  }
  return o;
}
