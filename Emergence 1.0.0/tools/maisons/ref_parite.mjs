// Référence de parité pour le port Rust de la maison (HouseGenerator) : extrait le générateur JavaScript de
// « nouvelle référence.html » (entre //GEN-START et //GEN-END), le lance sur une liste de graines et écrit en JSON
// les ENTIERS que le port doit retrouver exactement (paramètres dérivés, dimensions, portes, fenêtres, pièces, cloisons).
// Usage : node ref_parite.mjs <html> <sortie.json> <graine> [<graine> ...]
import fs from 'node:fs';

const [, , html, sortie, ...graines] = process.argv;
if (!html || !sortie || graines.length === 0) {
  console.error('usage : node ref_parite.mjs <html> <sortie.json> <graine>...');
  process.exit(2);
}
const texte = fs.readFileSync(html, 'utf8');
const d = texte.indexOf('//GEN-START');
const f = texte.indexOf('//GEN-END');
if (d < 0 || f < d) throw new Error('marqueurs GEN-START / GEN-END introuvables');
const src = texte.slice(d + '//GEN-START'.length, f);
const { derive, build } = new Function(`'use strict';${src}\nreturn{derive,build};`)();

const res = [];
for (const graine of graines) {
  const P = derive(graine);
  const o = build(P);
  const db = o.dbg;
  let pleins = 0;
  for (let i = 0; i < o.g.length; i++) if (o.g[i]) pleins++;
  res.push({
    seed: graine,
    params: P,
    grid: [o.NX, o.NY, o.NZ],
    size: { w: o.w, d: o.dp, h: o.h },
    doors_ext: o.doors.filter(q => q.kind === 'ext').length,
    doors_int: o.doors.filter(q => q.kind === 'int').length,
    windows: o.wobjs.length,
    rooms: o.rooms,
    furniture: o.nFur, beds: o.nBed, kitchens: o.nKit,
    lights: o.lights.length,
    cuts: db.cutsS.map(s => s.map(c => ({ ax: c.ax, c0: c.c0, c1: c.c1, a0: c.a0, a1: c.a1, door: c.door }))),
    strip: db.strip ? { sx0: db.strip.sx0, sx1: db.strip.sx1, p0: db.strip.p0, dir: db.strip.dir, d0: db.strip.d0 } : null,
    jd0: db.jd0, du0: db.du0,
    solid: pleins,
  });
}
fs.writeFileSync(sortie, JSON.stringify(res));
console.log(`${res.length} graines -> ${sortie}`);
