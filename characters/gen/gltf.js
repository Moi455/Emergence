// Minimal glTF 2.0 binary writer for one villager: skeleton, skin, one mesh per outfit,
// animation clips. No extension required. Normals are omitted on purpose: glTF clients
// must then compute flat normals, which is exactly the voxel look.
//   encodePNG(w, h, rgbaBytes) -> Uint8Array   (injected: zlib in Node, canvas in browser)

export function writeGLB({ name, sk, voxel, outfits, clips, extras }, encodePNG) {
  const chunks = []; let byteLen = 0;
  const bufferViews = [], accessors = [];
  const pushView = (bytes, target) => {
    while (byteLen % 4) { chunks.push(new Uint8Array(1)); byteLen++; }
    const view = { buffer: 0, byteOffset: byteLen, byteLength: bytes.byteLength };
    if (target) view.target = target;
    chunks.push(new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength)); byteLen += bytes.byteLength;
    bufferViews.push(view); return bufferViews.length - 1;
  };
  const acc = (arr, type, componentType, count, extra = {}, target) => {
    const bv = pushView(arr, target);
    accessors.push({ bufferView: bv, componentType, count, type, ...extra });
    return accessors.length - 1;
  };
  const m = voxel; // character units -> metres
  // ---- nodes: bones
  const nodes = [];
  const boneNode = sk.bones.map((b, i) => {
    const p = b.parent >= 0 ? sk.bones[b.parent].head : [0, 0, 0];
    nodes.push({ name: b.name, translation: [(b.head[0] - p[0]) * m, (b.head[1] - p[1]) * m, (b.head[2] - p[2]) * m] });
    return i;
  });
  sk.bones.forEach((b, i) => { const kids = sk.bones.map((c, j) => c.parent === i ? j : -1).filter(j => j >= 0); if (kids.length) nodes[i].children = kids; });
  // inverse bind matrices: bones have identity rest rotation -> pure translation by -head
  const ibm = new Float32Array(sk.bones.length * 16);
  sk.bones.forEach((b, i) => { const o = i * 16; ibm[o] = ibm[o + 5] = ibm[o + 10] = ibm[o + 15] = 1; ibm[o + 12] = -b.head[0] * m; ibm[o + 13] = -b.head[1] * m; ibm[o + 14] = -b.head[2] * m; });
  const ibmAcc = acc(ibm, 'MAT4', 5126, sk.bones.length);
  const skins = [{ name: 'Skeleton', joints: boneNode, skeleton: 0, inverseBindMatrices: ibmAcc }];
  // ---- meshes, one per outfit
  const meshes = [], materials = [], textures = [], images = [], samplers = [{ magFilter: 9728, minFilter: 9728, wrapS: 33071, wrapT: 33071 }];
  const meshNodes = [];
  outfits.forEach((o, k) => {
    const M = o.mesh;
    const nv = M.positions.length / 3;
    const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < nv; i++) for (let a = 0; a < 3; a++) { const v = M.positions[i * 3 + a]; if (v < min[a]) min[a] = v; if (v > max[a]) max[a] = v; }
    const pos = acc(M.positions, 'VEC3', 5126, nv, { min, max }, 34962);
    const uv = acc(M.uvs, 'VEC2', 5126, nv, {}, 34962);
    const j8 = new Uint8Array(nv * 4), w8 = new Uint8Array(nv * 4);
    for (let i = 0; i < nv; i++) {
      let sum = 0, big = 0;
      for (let c = 0; c < 4; c++) { j8[i * 4 + c] = M.joints[i * 4 + c]; const w = Math.round(M.weights[i * 4 + c] * 255); w8[i * 4 + c] = w; sum += w; if (w > w8[i * 4 + big]) big = c; }
      w8[i * 4 + big] += 255 - sum; // exact normalisation
    }
    const jA = acc(j8, 'VEC4', 5121, nv, {}, 34962);
    const wA = acc(w8, 'VEC4', 5121, nv, { normalized: true }, 34962);
    const big = nv > 65535;
    const idx = big ? M.indices : Uint16Array.from(M.indices);
    const iA = acc(idx, 'SCALAR', big ? 5125 : 5123, M.indices.length, {}, 34963);
    const png = encodePNG(M.atlas.w, M.atlas.h, M.atlas.data);
    images.push({ name: o.name + '_atlas', mimeType: 'image/png', bufferView: pushView(png) });
    textures.push({ sampler: 0, source: images.length - 1 });
    materials.push({ name: name + '_' + o.name, pbrMetallicRoughness: { baseColorTexture: { index: textures.length - 1 }, metallicFactor: 0, roughnessFactor: 0.92 } });
    meshes.push({ name: name + '_' + o.name, primitives: [{ attributes: { POSITION: pos, TEXCOORD_0: uv, JOINTS_0: jA, WEIGHTS_0: wA }, indices: iA, material: materials.length - 1, mode: 4 }] });
    nodes.push({ name: 'Outfit_' + o.name, mesh: meshes.length - 1, skin: 0, extras: { outfit: o.name.replace(/_LOD\d$/, ''), lod: o.lod ?? 0, voxel_m: voxel * (1 << (o.lod ?? 0)), garments: o.garments, default: k === 0 } });
    meshNodes.push(nodes.length - 1);
  });
  // ---- animations
  const animations = [];
  for (const c of clips || []) {
    const samplersA = [], channels = [];
    for (const [bn, t] of Object.entries(c.tracks)) {
      const ni = sk.byName[bn]; if (ni === undefined) continue;
      const tIn = acc(Float32Array.from(t.times), 'SCALAR', 5126, t.times.length, { min: [t.times[0]], max: [t.times[t.times.length - 1]] });
      const tOut = acc(Float32Array.from(t.rotations.flat()), 'VEC4', 5126, t.rotations.length);
      samplersA.push({ input: tIn, output: tOut, interpolation: 'LINEAR' });
      channels.push({ sampler: samplersA.length - 1, target: { node: ni, path: 'rotation' } });
    }
    if (c.rootY) {
      const hips = sk.byName.Hips, base = nodes[hips].translation;
      const tIn = acc(Float32Array.from(c.rootY.times), 'SCALAR', 5126, c.rootY.times.length, { min: [c.rootY.times[0]], max: [c.rootY.times[c.rootY.times.length - 1]] });
      const vals = new Float32Array(c.rootY.values.length * 3);
      c.rootY.values.forEach((v, i) => { vals[i * 3] = base[0]; vals[i * 3 + 1] = base[1] + v; vals[i * 3 + 2] = base[2]; });
      const tOut = acc(vals, 'VEC3', 5126, c.rootY.values.length);
      samplersA.push({ input: tIn, output: tOut, interpolation: 'LINEAR' });
      channels.push({ sampler: samplersA.length - 1, target: { node: hips, path: 'translation' } });
    }
    animations.push({ name: c.name, samplers: samplersA, channels });
  }
  const rootNode = nodes.length;
  nodes.push({ name, children: [0], extras });
  const json = {
    asset: { version: '2.0', generator: 'Emergence villager generator' },
    scene: 0, scenes: [{ name, nodes: [rootNode, ...meshNodes] }], nodes, skins, meshes, materials, textures, images, samplers, accessors, bufferViews,
    animations, buffers: [{ byteLength: 0 }],
  };
  while (byteLen % 4) { chunks.push(new Uint8Array(1)); byteLen++; }
  json.buffers[0].byteLength = byteLen;
  const jsonBytes = new TextEncoder().encode(JSON.stringify(json));
  const jsonPad = (4 - (jsonBytes.length % 4)) % 4;
  const total = 12 + 8 + jsonBytes.length + jsonPad + 8 + byteLen;
  const out = new Uint8Array(total);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, 0x46546C67, true); dv.setUint32(4, 2, true); dv.setUint32(8, total, true);
  dv.setUint32(12, jsonBytes.length + jsonPad, true); dv.setUint32(16, 0x4E4F534A, true);
  out.set(jsonBytes, 20); for (let i = 0; i < jsonPad; i++) out[20 + jsonBytes.length + i] = 0x20;
  let o = 20 + jsonBytes.length + jsonPad;
  dv.setUint32(o, byteLen, true); dv.setUint32(o + 4, 0x004E4942, true); o += 8;
  for (const c of chunks) { out.set(c, o); o += c.byteLength; }
  return out;
}

// PNG encoder given a deflate function (zlib format)
export function makePNGEncoder(deflate) {
  const crcT = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; crcT[n] = c >>> 0; }
  const crc = (buf) => { let c = 0xffffffff; for (let i = 0; i < buf.length; i++) c = crcT[(c ^ buf[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (type, data) => {
    const out = new Uint8Array(12 + data.length), dv = new DataView(out.buffer);
    dv.setUint32(0, data.length);
    for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
    out.set(data, 8);
    dv.setUint32(8 + data.length, crc(out.subarray(4, 8 + data.length)));
    return out;
  };
  return (w, h, rgba) => {
    const raw = new Uint8Array((w * 4 + 1) * h);
    for (let y = 0; y < h; y++) { raw[y * (w * 4 + 1)] = 0; raw.set(rgba.subarray(y * w * 4, (y + 1) * w * 4), y * (w * 4 + 1) + 1); }
    const ihdr = new Uint8Array(13), dv = new DataView(ihdr.buffer);
    dv.setUint32(0, w); dv.setUint32(4, h); ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
    const parts = [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', deflate(raw)), chunk('IEND', new Uint8Array(0))];
    const len = parts.reduce((a, p) => a + p.length, 0), out = new Uint8Array(len);
    let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  };
}
