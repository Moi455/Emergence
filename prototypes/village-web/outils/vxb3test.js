// compares the VXB2 world with the VXB3 world after conversion: same modules, same voxels (class exact, tint exact unless remapped)
const fs = require('fs'), zlib = require('zlib'), vm = require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[2] + '/shared.js', 'utf8'));
const ld = (f) => { const b = zlib.gunzipSync(fs.readFileSync(f)); return VX.parseVXB(b.buffer.slice(b.byteOffset, b.byteOffset + b.length)); };
let t = Date.now(); const A = ld(process.argv[3]); const ta = Date.now() - t; t = Date.now(); const B = ld(process.argv[4]); const tb = Date.now() - t;
let tot = 0, clsDiff = 0, tintDiff = 0, occDiff = 0;
for (let m = 0; m < A.mods.length; m++) {
  const a = A.mods[m], b = B.mods[m];
  if (a.name !== b.name || a.ox !== b.ox || a.oy !== b.oy || a.dx !== b.dx || a.dy !== b.dy) { console.log('header diff', a.name, [a.ox,a.oy,a.oz,a.dx,a.dy,a.dz], [b.ox,b.oy,b.oz,b.dx,b.dy,b.dz]); continue; }
  for (let z = 0; z < a.dz; z++) for (let y = 0; y < a.dy; y++) for (let x = 0; x < a.dx; x++) {
    const va = VX.getLocal(a, a.bricks, A.pool, x + a.ox, y + a.oy, z + a.oz);
    const zb = z;
    const vb = zb >= 0 && zb < b.dz ? VX.getLocal(b, b.bricks, B.pool, x + a.ox, y + a.oy, z + a.oz) : 0;
    if (!va && !vb) continue; tot++;
    if (!va !== !vb) occDiff++; else if ((va >> 7) !== (vb >> 7)) clsDiff++; else if (va !== vb) tintDiff++;
  }
}
console.log('parse ms', ta, tb, 'voxels', tot, 'occupancy diff', occDiff, 'class diff', clsDiff, 'tint diff', tintDiff, 'mixed', A.pool.n, B.pool.n);
console.log('palette equal', Buffer.compare(Buffer.from(A.palette.slice(0, B.palette.length)), Buffer.from(B.palette)) === 0);
