'use strict';
// Usage: node export_house.js <graine> [sortie_sans_extension]
// Produit <sortie>.vxh (grille binaire, deflate) + <sortie>.json (métadonnées).
const fs=require('fs'),zlib=require('zlib'),{derive,build,VS,G}=require('./gen_core.js');
const seed=process.argv[2]||'gravit',out=process.argv[3]||('house_'+seed);
const P=derive(seed),o=build(P),N=o.NX*o.NY*o.NZ;
// Plans : g u16 LE (RGB565, 0=vide), MT u8 (0 vide,1 pierre/métal,2 bois,3 plâtre,4 végétal/sol,5 toit), FL u8 (bit0 émissif, bit1 verre, bit2 intérieur, bit3 mou/sans collision)
const FL=new Uint8Array(N);
for(const i of o.EM)FL[i]|=1;for(const i of o.GL)FL[i]|=2;
for(let Z=0;Z<o.NZ;Z++)for(let X=0;X<o.NX;X++)if(o.INS[Z*o.NX+X])for(let Y=0;Y<o.NY;Y++){const i=(Y*o.NZ+Z)*o.NX+X;if(o.g[i]&&Y-G>=0&&Y-G<o.Hw-3&&!(FL[i]&3))FL[i]|=4}
for(const i of o.soft)FL[i]|=8;
const hdr=Buffer.alloc(32);hdr.write('VXH1',0,'ascii');hdr.writeUInt32LE(o.NX,4);hdr.writeUInt32LE(o.NY,8);hdr.writeUInt32LE(o.NZ,12);hdr.writeFloatLE(VS,16);hdr.writeUInt32LE(G,20);
const body=Buffer.concat([Buffer.from(o.g.buffer,o.g.byteOffset,o.g.byteLength),Buffer.from(o.MT),Buffer.from(FL)]);
fs.writeFileSync(out+'.vxh',Buffer.concat([hdr,zlib.deflateSync(body,{level:9})]));
const rgb=c=>[c>>16&255,c>>8&255,c&255];
const meta={seed,params:P,grid:{nx:o.NX,ny:o.NY,nz:o.NZ,voxel_m:VS,ground_layers:G,index:'(y*nz+z)*nx+x'},
 size_vox:{w:o.w,d:o.dp,h:o.h},center_xz:[o.cx,o.cz],spawn:o.spawn,
 doors:o.doors.map(d=>({kind:d.kind,storey:d.s,hinge:[d.hx,d.hz],y:d.y,u:[d.ux,d.uz],n:[d.nx,d.nz],w:d.w,h:d.h,arch:!!d.arch,color:d.col,cells:d.cells})),
 windows:o.wobjs.map(w=>({y:w.y,w:w.w,h:w.h,arch:!!w.arch,lit:!!w.lit,n:[w.nx,w.nz],center:[w.cx,w.cz],cells:w.cells,leaves:w.parts.map(p=>({hinge:[p.hx,p.hz],u:[p.ux,p.uz],w:p.w,reverse:p.rev}))})),
 lights:o.lights.map(l=>({pos:l.p,color:rgb(l.c),intensity:l.i,radius:l.r,decay_dist:l.d||null,exterior:!!l.o})),
 rooms:o.rooms,counts:{furniture:o.nFur,beds:o.nBed,kitchens:o.nKit}};
fs.writeFileSync(out+'.json',JSON.stringify(meta));
console.log(out,o.NX,o.NY,o.NZ,'bytes',fs.statSync(out+'.vxh').size);
