// villager_worker.js — génère les villageois dans un worker, avec le générateur du fil
// « Skins des villageois » (personnages/gen, utilisé tel quel). Le jeu ne stocke que la
// graine et la garde-robe ; le maillage est produit au chargement.
// Premier message : { base } (dossier du générateur, ex. 'personnages/').
// Ensuite : { seed, village, outfit, lod }  ->  { seed, outfit, lod, skel?, clips?, bp?, job?, mesh }
let gen = null, anim = null, catalog = null;
const cache = new Map();   // seed -> { v, grids: Map(outfit -> grid) }
let ready = null;

self.onmessage = async (e) => {
  const q = e.data;
  if (q.base !== undefined) {
    ready = (async () => {
      gen = await import(new URL(q.base + 'gen/villager.js', q.origin).href);
      anim = await import(new URL(q.base + 'gen/anim.js', q.origin).href);
      catalog = await (await fetch(new URL(q.base + 'data/catalog.json', q.origin))).json();
    })();
    return;
  }
  try {
    await ready;
    let c = cache.get(q.seed), first = false;
    if (!c) { c = { v: gen.generateVillager(q.seed, catalog, { village: q.village }), grids: new Map() }; cache.set(q.seed, c); first = true; }
    let grid = c.grids.get(q.outfit);
    if (!grid) { grid = gen.composeOutfit(c.v, q.outfit, catalog); c.grids.set(q.outfit, grid); }
    const m = gen.meshOutfit(c.v.base, grid, q.lod);
    const out = { seed: q.seed, outfit: q.outfit, lod: q.lod, mesh: {
      positions: m.positions, normals: m.normals, uvs: m.uvs, joints: Float32Array.from(m.joints), weights: Float32Array.from(m.weights),
      indices: Uint32Array.from(m.indices), atlas: { w: m.atlas.w, h: m.atlas.h, data: m.atlas.data } } };
    const tr = [out.mesh.positions.buffer, out.mesh.normals.buffer, out.mesh.uvs.buffer, out.mesh.joints.buffer, out.mesh.weights.buffer, out.mesh.indices.buffer, m.atlas.data.buffer];
    if (first) {
      const sk = c.v.base.sk, vx = c.v.base.voxel;
      out.skel = { names: sk.bones.map((b) => b.name), parents: sk.bones.map((b) => b.parent), heads: sk.bones.map((b) => b.head.map((x) => x * vx)) };
      out.clips = anim.makeClips(sk, c.v.bp);
      out.bp = { sex: c.v.bp.sex, ageClass: c.v.bp.ageClass, age: c.v.bp.age, height: c.v.bp.height };
      out.job = c.v.wardrobe && c.v.wardrobe.job;
    }
    self.postMessage(out, [...new Set(tr)]);
  } catch (err) { self.postMessage({ seed: q.seed, outfit: q.outfit, lod: q.lod, error: String(err && err.stack || err) }); }
};
