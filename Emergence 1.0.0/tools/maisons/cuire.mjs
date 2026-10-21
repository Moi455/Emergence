// Cuisson des maisons de Monsieur : extrait le générateur de « nouvelle référence.html » (entre //GEN-START et
// //GEN-END), le rend capable de renseigner le MATÉRIAU de chaque voxel (plan MT), et l'exporte en .vxh + .json.
//
// Usage : node cuire.mjs <html> <dossier_sortie> <graine> [<graine> ...]
//
// Le bloc de la nouvelle référence ne connaît pas MT (la version « gen_core(1).js » l'avait). On PATCHE donc
// l'extraction (remplacements exacts, chacun doit s'appliquer UNE fois, sinon on s'arrête) :
//   - S() reçoit le matériau du contexte courant (CM) ; à défaut, il est dérivé de la couleur (autoM, comme
//     gen_core(1).js : vert -> 4 végétal, gris peu saturé -> 1 pierre/métal, sinon 2 bois) ;
//   - contexte explicite : mur (pierre 1 / bois 2 / plâtre 3 selon la branche de wallC), toit (bord et premier
//     rang : bois 2, tuiles 5), sol du jardin (4) ;
//   - l'herbe et les fleurs (« mous ») sont forcées à 4 à l'export.
// Invariant vérifié avant l'écriture : couleur != 0 <=> matériau != 0 (sinon erreur, rien n'est écrit).
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const [, , html, sortie, ...graines] = process.argv;
if (!html || !sortie || graines.length === 0) {
  console.error('usage : node cuire.mjs <html> <dossier_sortie> <graine>...');
  process.exit(2);
}

/** Remplace `a` par `b` exactement une fois dans `src`, sinon lève une erreur (le générateur a changé). */
function patch(src, a, b) {
  const n = src.split(a).length - 1;
  if (n !== 1) throw new Error(`patch : motif trouvé ${n} fois (attendu 1) : ${a.slice(0, 70)}`);
  return src.replace(a, () => b);
}

const texte = fs.readFileSync(html, 'utf8');
const d = texte.indexOf('//GEN-START');
const f = texte.indexOf('//GEN-END');
if (d < 0 || f < d) throw new Error('marqueurs GEN-START / GEN-END introuvables');
let src = texte.slice(d + '//GEN-START'.length, f);

// 1. plan MT + contexte de matériau
src = patch(src, 'const g=new Uint16Array(NX*NY*NZ),EM=new Set()',
  'const g=new Uint16Array(NX*NY*NZ),MT=new Uint8Array(NX*NY*NZ),EM=new Set()');
src = patch(src, ' const S=(x,v,z,c,em)=>{',
  ' let CM=0,LM=0;const autoM0=c=>{const r=c[0],g_=c[1],b=c[2],mxv=Math.max(r,g_,b),mnv=Math.min(r,g_,b);if(g_>r*1.06&&g_>b*1.25)return 4;if(mxv-mnv<28)return 1;return 2};\n const S=(x,v,z,c,em)=>{');
src = patch(src, 'g[i]=c?pk(c):0;if(em===2)', 'g[i]=c?pk(c):0;MT[i]=c?(CM||autoM0(c)):0;if(em===2)');

// 2. murs : pierre (1) par défaut ; bois (2) et plâtre (3) selon la branche de wallC
src = patch(src, "const u=(f<2?z:x)+300+f*37,sty=WL.style;", "const u=(f<2?z:x)+300+f*37,sty=WL.style;LM=1;");
src = patch(src, 'if(bm)return wood(v,d,2);', 'if(bm){LM=2;return wood(v,d,2)}');
src = patch(src, 'if(cor||u%WL.posts<5)return wood(u,d,1);', 'if(cor||u%WL.posts<5){LM=2;return wood(u,d,1)}');
src = patch(src, "if(sty==='timber-plaster'){if(d<1)return null;return J(", "if(sty==='timber-plaster'){if(d<1)return null;LM=3;return J(");
src = patch(src, 'for(let v=0;v<top;v++){const c=wallC(x,z,v,d,f,cor);if(c)S(x,v,z,c)}',
  'for(let v=0;v<top;v++){LM=1;const c=wallC(x,z,v,d,f,cor);if(c){CM=LM;S(x,v,z,c)}}CM=0;');
// 3. toit : bois (2) pour le premier rang et les bords, tuiles (5) ailleurs
src = patch(src, 'for(let v=r.bot;v<=r.top;v++)S(x,v,z,v===r.bot?WOODD:edge?wood(x,v,z):tc||rtile(r.sl,r.al+1000,x,z));',
  'for(let v=r.bot;v<=r.top;v++){CM=(v===r.bot||edge)?2:5;S(x,v,z,v===r.bot?WOODD:edge?wood(x,v,z):tc||rtile(r.sl,r.al+1000,x,z))}CM=0;');
// 4. sol du jardin (écrit directement dans g) : végétal / sol (4)
src = patch(src, 'for(let y=2;y<G-1;y++)g[(y*NZ+Z)*NX+X]=pk(sc([92,68,46],.9+hh(x,y,z)*.2));\n  g[((G-1)*NZ+Z)*NX+X]=pk(top);',
  'for(let y=2;y<G-1;y++){g[(y*NZ+Z)*NX+X]=pk(sc([92,68,46],.9+hh(x,y,z)*.2));MT[(y*NZ+Z)*NX+X]=4}\n  g[((G-1)*NZ+Z)*NX+X]=pk(top);MT[((G-1)*NZ+Z)*NX+X]=4;');
// 5. exposer MT
src = patch(src, ' return{INS,Hw,soft,GL,', ' return{MT,INS,Hw,soft,GL,');

const { derive, build, VS, G } = new Function(`'use strict';${src}\nreturn{derive,build,VS,G};`)();

fs.mkdirSync(sortie, { recursive: true });
for (const graine of graines) {
  const t0 = Date.now();
  const P = derive(graine), o = build(P), N = o.NX * o.NY * o.NZ;
  const FL = new Uint8Array(N);
  for (const i of o.EM) FL[i] |= 1;
  for (const i of o.GL) FL[i] |= 2;
  for (let Z = 0; Z < o.NZ; Z++) for (let X = 0; X < o.NX; X++) if (o.INS[Z * o.NX + X])
    for (let Y = 0; Y < o.NY; Y++) { const i = (Y * o.NZ + Z) * o.NX + X; if (o.g[i] && Y - G >= 0 && Y - G < o.Hw - 3 && !(FL[i] & 3)) FL[i] |= 4; }
  for (const i of o.soft) { FL[i] |= 8; if (o.g[i]) o.MT[i] = 4; }
  // Invariant du format : couleur != 0 <=> matériau != 0.
  let pleins = 0;
  for (let i = 0; i < N; i++) {
    if ((o.g[i] !== 0) !== (o.MT[i] !== 0)) throw new Error(`invariant couleur/matériau violé au voxel ${i} (graine ${graine})`);
    if (o.g[i]) pleins++;
  }
  const hdr = Buffer.alloc(32);
  hdr.write('VXH1', 0, 'ascii'); hdr.writeUInt32LE(o.NX, 4); hdr.writeUInt32LE(o.NY, 8); hdr.writeUInt32LE(o.NZ, 12);
  hdr.writeFloatLE(VS, 16); hdr.writeUInt32LE(G, 20);
  const corps = Buffer.concat([Buffer.from(o.g.buffer, o.g.byteOffset, o.g.byteLength), Buffer.from(o.MT), Buffer.from(FL)]);
  const base = path.join(sortie, `maison_${graine}`);
  fs.writeFileSync(base + '.vxh', Buffer.concat([hdr, zlib.deflateSync(corps, { level: 9 })]));
  const rgb = c => [c >> 16 & 255, c >> 8 & 255, c & 255];
  const histo = [0, 0, 0, 0, 0, 0]; for (let i = 0; i < N; i++) histo[o.MT[i]]++;
  const meta = {
    seed: graine, params: P,
    grid: { nx: o.NX, ny: o.NY, nz: o.NZ, voxel_m: VS, ground_layers: G, index: '(y*nz+z)*nx+x' },
    size_vox: { w: o.w, d: o.dp, h: o.h }, center_xz: [o.cx, o.cz], spawn: o.spawn,
    voxels_pleins: pleins, materiaux: { pierre_metal: histo[1], bois: histo[2], platre: histo[3], vegetal_sol: histo[4], toit: histo[5] },
    doors: o.doors.map(d => ({ kind: d.kind, storey: d.s, hinge: [d.hx, d.hz], y: d.y, u: [d.ux, d.uz], n: [d.nx, d.nz], w: d.w, h: d.h, arch: !!d.arch, color: d.col, cells: d.cells })),
    windows: o.wobjs.map(w => ({ y: w.y, w: w.w, h: w.h, arch: !!w.arch, lit: !!w.lit, n: [w.nx, w.nz], center: [w.cx, w.cz], cells: w.cells, leaves: w.parts.map(p => ({ hinge: [p.hx, p.hz], u: [p.ux, p.uz], w: p.w, reverse: p.rev })) })),
    lights: o.lights.map(l => ({ pos: l.p, color: rgb(l.c), intensity: l.i, radius: l.r, decay_dist: l.d || null, exterior: !!l.o })),
    rooms: o.rooms, counts: { furniture: o.nFur, beds: o.nBed, kitchens: o.nKit },
  };
  fs.writeFileSync(base + '.json', JSON.stringify(meta));
  console.log(`${base}.vxh  ${o.NX}x${o.NY}x${o.NZ}  ${pleins} voxels pleins  MT=${histo.slice(1).join('/')}  ${fs.statSync(base + '.vxh').size} o  ${Date.now() - t0} ms`);
}
