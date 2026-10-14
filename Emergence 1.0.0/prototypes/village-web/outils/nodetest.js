const fs=require('fs'),zlib=require('zlib'),vm=require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[2]+'/shared.js','utf8'));
const raw=zlib.gunzipSync(fs.readFileSync(process.argv[2]+'/world.vxb'));
const ab=()=>raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.length);
let t=Date.now();const W=VX.parseVXB(ab());console.log('parse ms',Date.now()-t,'mods',W.mods.length,'pool',W.pool.n);
const h=VX.makeHandler(); h({type:'init',buf:ab(),terrain:{seed:1337,cx:8192,cz:8192,pads:[],streets:[{ax:8000,az:8192,bx:8400,bz:8192,w:85}]}},()=>{});
let tq=0,tt=Date.now();
for (const m0 of W.mods) { h({type:'module',id:m0.id},(m)=>{let q=0;for(const c of m.chunks)q+=c.v.byteLength/32; tq+=q; if(/Wall_Plaster_Straight|6x8|Floor_Wood|Prop_Crate/.test(m0.name)) console.log(m0.name,m0.nvox,'ms',m.ms.toFixed(0),'lod0 quads',q, 'coarse', m.coarse.map(c=>c?c.byteLength/32:0));}); }
console.log('all modules ms', Date.now()-tt, 'total lod0 quads', tq);
for (const [S,s] of [[128,1],[256,2],[512,4],[4096,32]]) h({type:'terrain',x0:8192,z0:8192,S,s},(m)=>console.log('terrain',S,s,'quads',m.v?m.v.byteLength/32:0));
h({type:'terrain',x0:8192,z0:8192,S:128,removed:new Uint32Array([5+128*(5+128*190)])},(m)=>console.log('terrain edited quads',m.v?m.v.byteLength/32:0));
