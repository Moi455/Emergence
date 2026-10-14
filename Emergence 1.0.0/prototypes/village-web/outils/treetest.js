const fs=require('fs'),zlib=require('zlib'),vm=require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[2]+'/shared.js','utf8'));
const raw=zlib.gunzipSync(fs.readFileSync(process.argv[2]+'/world.vxb'));
const W=VX.parseVXB(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.length)); const n0=W.pool.n;
let t=Date.now(); VX.addTrees(W,1337,4); console.log('trees ms',Date.now()-t,'bricks',W.pool.n-n0);
for (const m of W.mods.slice(-4)) { let q=0; const ncx=Math.ceil(m.dx/32),ncy=Math.ceil(m.dy/32),ncz=Math.ceil(m.dz/32); t=Date.now();
 for(let cz=0;cz<ncz;cz++)for(let cy=0;cy<ncy;cy++)for(let cx=0;cx<ncx;cx++){const r=VX.meshModuleChunk(m,m.bricks,W.pool,cx,cy,cz); if(r) q+=r.byteLength/32;}
 console.log(m.name,m.nvox,'trace quads',q,'ms',Date.now()-t); }
