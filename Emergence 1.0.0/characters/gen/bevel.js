// Every texel of a villager's atlas is one voxel face. A small bevel on each one makes it read
// as a little cube (the knitted, mosaic look of the reference images) at no geometry cost:
// a tangent-space normal tile repeated once per texel. Shared by every villager.
//   n: tile size in pixels, b: bevel width (fraction of the cell), s: bevel slope.
// Green follows +v (three.js derivative tangents); glTF wants +Y up, so the exporter flips it.
export function bevelTile(n = 16, b = 0.22, s = 1.1, flipGreen = false) {
  const out = new Uint8Array(n * n * 4);
  const t = c => c < b ? -(b - c) / b : c > 1 - b ? (c - (1 - b)) / b : 0;
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    let x = t((i + 0.5) / n) * s, y = t((j + 0.5) / n) * s;
    if (flipGreen) y = -y;
    const l = Math.sqrt(x * x + y * y + 1), o = (i + n * j) * 4;
    out[o] = Math.round((x / l * 0.5 + 0.5) * 255); out[o + 1] = Math.round((y / l * 0.5 + 0.5) * 255);
    out[o + 2] = Math.round((1 / l * 0.5 + 0.5) * 255); out[o + 3] = 255;
  }
  return out;
}

// The same bevel baked over a whole atlas (k pixels per texel), for engines that cannot repeat
// a tile per texel: it depends only on the atlas size, so villagers can share it.
export function bevelAtlas(w, h, k = 4, flipGreen = true) {
  const tile = bevelTile(k, 0.3, 1.1, flipGreen), W = w * k, H = h * k, out = new Uint8Array(W * H * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) out.set(tile.subarray(((x % k) + k * (y % k)) * 4, ((x % k) + k * (y % k)) * 4 + 4), (x + W * y) * 4);
  return { w: W, h: H, data: out };
}
