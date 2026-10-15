'use strict';
// Générateur de maison voxel (extrait tel quel de maison-voxel.html, sans changement de logique).

/* ============ Générateur de maison en voxels de 5 cm ============ */
const VS=.05,G=6,T=6,SH=54,PL=8,VMAX=320,UM=1100;
const mul=a=>()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296};
const hs=s=>{let h=1779033703^s.length;for(let i=0;i<s.length;i++){h=Math.imul(h^s.charCodeAt(i),3432918353);h=h<<13|h>>>19}return h>>>0};
const hh=(a,b=0,c=0,d=0)=>{let h=Math.imul(a|0,374761393)^Math.imul(b|0,668265263)^Math.imul(c|0,1274126177)^Math.imul(d|0,2246822519);h=Math.imul(h^h>>>15,2246822519);h=Math.imul(h^h>>>13,3266489917);h^=h>>>16;return(h>>>0)/4294967296};
const vn=(x,y,s=0)=>{const xi=Math.floor(x),yi=Math.floor(y),fx=x-xi,fy=y-yi,u=fx*fx*(3-2*fx),v=fy*fy*(3-2*fy),a=hh(xi,yi,s),b=hh(xi+1,yi,s),c=hh(xi,yi+1,s),d=hh(xi+1,yi+1,s);return a+(b-a)*u+(c-a)*v+(a-b-c+d)*u*v};
const sc=(c,f)=>[c[0]*f,c[1]*f,c[2]*f],mx=(a,b,t)=>[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t];
const J=(c,x,y,z,a=.06)=>sc(c,1+(hh(x,y,z,3)-.5)*2*a);
const cl=v=>v<0?0:v>255?255:v|0;
const pk=c=>((cl(c[0])>>3)<<11|(cl(c[1])>>2)<<5|cl(c[2])>>3)||1;
const WOOD=[88,60,38],WOODD=[58,40,28],WOODL=[124,90,58],IRON=[46,44,48],MORT=[68,60,52],PLAS=[208,192,160],STN=[150,146,138],AMB=[255,198,104];
const SP={warm:[[150,130,106],[128,108,88],[170,150,120]],grey:[[134,132,126],[110,108,104],[158,154,144]],dark:[[106,104,102],[86,84,84],[128,122,114]]};
const TPAL={slate:[[54,58,66],[40,45,54],[72,76,82]],shingle:[[104,78,56],[80,58,42],[126,96,68]],terracotta:[[150,82,56],[122,62,44],[172,106,72]]};
const PC={brown:[100,68,42],green:[62,92,66],blue:[64,92,118],red:[112,52,44]};
const FL=[[238,234,224],[238,198,72],[218,122,164],[146,112,196]];

/* --- Graine -> paramètres (chaque partie est pilotée par un bloc de paramètres) --- */
function derive(seed){
 const R=mul(hs(seed)),r=(a,b)=>a+R()*(b-a),i=(a,b)=>Math.floor(r(a,b+.999)),pc=a=>a[i(0,a.length-1)],f2=x=>+x.toFixed(2);
 const P={seed},d=i(88,112);
 P.stories=pc([1,2,2]);
 P.main={w:i(116,152),d};
 P.plan=pc(['rect','L','L','T']);
 P.wing={w:i(56,Math.min(76,d*.78|0)),len:i(46,84),at:pc([0,1]),dir:pc([1,-1])};
 P.wall={style:pc(['stone','stone','timber-stone','timber-plaster']),stone:pc(['warm','grey','dark']),posts:i(40,56)};
 P.roof={slope:f2(r(1,1.5)),eave:i(8,12),rake:i(5,8),tile:pc(['slate','slate','shingle','terracotta']),moss:f2(r(.15,.55))};
 P.win={w:pc([14,16,18]),h:i(20,24),sill:i(16,20),arch:R()<.35,shutters:R()<.75,box:R()<.6,color:pc(['brown','green','blue','red']),lit:f2(r(.5,.95)),gap:i(44,58)};
 P.door={w:20,h:40,arch:R()<.5,at:f2(r(.3,.7)),porch:R()<.85,color:pc(['brown','green','blue','red'])};
 P.chimney={side:pc(['E','W'])};
 P.shed=R()<.8;
 P.deco={barrels:i(1,3),flowers:f2(r(.01,.05)),grass:f2(r(.04,.12))};
 return P;
}

function build(P){
 const R=mul(hs(P.seed+'/d')),M=P.main,Wg=P.wing,st=P.stories,Hw=st*SH,RF=P.roof,WL=P.wall,WN=P.win,DR=P.door,EV=RF.eave,RK=RF.rake,TH=6,SL=RF.slope,sq=Math.sqrt(1+SL*SL);
 /* Volumes : corps principal (faîtage selon X) + aile éventuelle (faîtage selon Z) */
 const boxes=[{x0:0,x1:M.w,z0:0,z1:M.d,m:1}];
 if(P.plan!=='rect'){const x0=P.plan==='T'?(M.w-Wg.w>>1):(Wg.at?M.w-Wg.w:0);
  boxes.push({x0,x1:x0+Wg.w,z0:Wg.dir>0?M.d-24:-Wg.len,z1:Wg.dir>0?M.d+Wg.len:24,m:0,dir:Wg.dir})}
 for(const b of boxes){
  if(b.m){b.rx0=b.x0-RK;b.rx1=b.x1+RK;b.rz0=b.z0-EV;b.rz1=b.z1+EV}
  else{const hw=(b.x1-b.x0)/2|0;b.rx0=b.x0-EV;b.rx1=b.x1+EV;if(b.dir>0){b.rz0=M.d-hw-6;b.rz1=b.z1+RK}else{b.rz0=b.z0-RK;b.rz1=hw+6}}
 }
 const MG=64,X0=Math.min(...boxes.map(b=>b.rx0)),X1=Math.max(...boxes.map(b=>b.rx1)),Z0=Math.min(...boxes.map(b=>b.rz0)),Z1=Math.max(...boxes.map(b=>b.rz1));
 const OX=MG-X0,OZ=MG-Z0,NX=X1-X0+2*MG,NZ=Z1-Z0+2*MG,NY=G+Hw+Math.ceil(SL*M.d/2)+TH+44;
 const g=new Uint16Array(NX*NY*NZ),MT=new Uint8Array(NX*NY*NZ),EM=new Set(),GL=new Set(),lights=[];let CM=0,LM=0;
 const autoM=c=>{const r=c[0],g_=c[1],b=c[2],mxv=Math.max(r,g_,b),mnv=Math.min(r,g_,b);if(g_>r*1.06&&g_>b*1.25)return 4;if(mxv-mnv<28)return 1;return 2};
 const gi=(x,v,z)=>((v+G)*NZ+z+OZ)*NX+x+OX,ix=(x,z)=>(z+OZ)*NX+x+OX;
 const S=(x,v,z,c,em)=>{const X=x+OX,Y=v+G,Z=z+OZ;if(X<2||X>=NX-2||Y<2||Y>=NY-2||Z<2||Z>=NZ-2)return;const i=(Y*NZ+Z)*NX+X;g[i]=c?pk(c):0;MT[i]=c?(CM||autoM(c)):0;if(em===2){GL.add(i);if(EM.size)EM.delete(i)}else{if(GL.size)GL.delete(i);if(em)EM.add(i);else if(EM.size)EM.delete(i)}};
 const at=(x,v,z)=>g[gi(x,v,z)];
 const FM=new Uint8Array(NX*NZ);
 for(const b of boxes)for(let z=b.z0;z<b.z1;z++)for(let x=b.x0;x<b.x1;x++)FM[ix(x,z)]=1;
 const inF=(x,z)=>FM[ix(x,z)]===1;
 /* distance au vide (épaisseur des murs) + orientation de la face */
 const DS=new Uint8Array(NX*NZ),FC=new Uint8Array(NX*NZ),q=[],D4=[1,-1,NX,-NX];
 for(let i=0;i<NX*NZ;i++)if(FM[i])for(let k=0;k<4;k++)if(!FM[i+D4[k]]){DS[i]=1;FC[i]=k;q.push(i);break}
 for(let h=0;h<q.length;h++){const i=q[h];if(DS[i]>T)continue;for(let k=0;k<4;k++){const j=i+D4[k];if(FM[j]&&!DS[j]){DS[j]=DS[i]+1;FC[j]=FC[i];q.push(j)}}}
 /* Repère local d'une façade : u le long (vu de l'extérieur, gauche->droite), v hauteur, d profondeur (d<0 = extérieur). f: 0=E 1=O 2=S 3=N */
 const SF=(b,f)=>({b,f,len:f<2?b.z1-b.z0:b.x1-b.x0,xz:[(u,d)=>[b.x1-1-d,b.z1-1-u],(u,d)=>[b.x0+d,b.z0+u],(u,d)=>[b.x0+u,b.z1-1-d],(u,d)=>[b.x1-1-u,b.z0+d]][f]});
 const put=(fr,u,v,d,c,em)=>{const p=fr.xz(u,d);S(p[0],v,p[1],c,em)};
 const ext=(fr,u0,u1)=>{for(let u=u0;u<u1;u++){if(u<0||u>=fr.len)return false;const a=fr.xz(u,0),b=fr.xz(u,-1);if(!inF(a[0],a[1])||inF(b[0],b[1]))return false}return true};
 const freeOut=(fr,u0,u1,dd)=>{for(let u=u0;u<u1;u+=2)for(let d=1;d<=dd;d++){const p=fr.xz(u,-d);if(inF(p[0],p[1]))return false}return true};
 const occ=[],busy=(fr,u0,u1,v)=>occ.some(o=>o.b===fr.b&&o.f===fr.f&&u1>o.u0&&u0<o.u1&&v<o.vm),mark=(fr,u0,u1,vm)=>occ.push({b:fr.b,f:fr.f,u0,u1,vm});
 const doors=[],wobjs=[],cs=P.chimney.side,sW=cs==='E',intr=(x,z)=>{const i=ix(x,z);return FM[i]===1&&(!DS[i]||DS[i]>T)};
 const uR=(b,f,c0,c1)=>f===2?[c0-b.x0,c1-b.x0]:f===3?[b.x1-c1,b.x1-c0]:f===0?[b.z1-c1,b.z1-c0]:[c0-b.z0,c1-b.z0];

 /* ---- Porte : position (sert aussi au chemin) ---- */
 const db=(P.plan!=='rect'&&Wg.dir>0)?boxes[1]:boxes[0],dfr=SF(db,2);
 let du0=Math.max(16,Math.min(dfr.len-DR.w-16,Math.round((dfr.len-DR.w)*DR.at)));
 /* Géométrie intérieure : cage d'escalier (si étage) le long du pignon de l'appentis, cloison de jonction avec l'aile */
 const TP=3,DW=14,DHT=36,SW=30,NS=14,mx0=T,mx1=M.w-T,mz0=T,mz1=M.d-T,mainB=boxes[0],FT=[];
 const pickD=(a0,a1,forb)=>{const c=[];for(let k=a0+4;k<=a1-4-DW;k+=2)if(!forb.some(f=>k-2<f[1]&&k+DW+2>f[0]))c.push(k);return c.length?c[Math.floor(R()*c.length)]:null};
 const strip=st>1?{sx0:sW?mx0:mx1-16,sx1:sW?mx0+16:mx1,p0:sW?mx0+SW:mx1-SW-TP,dir:boxes[1]?(boxes[1].dir>0?-1:1):(R()<.5?1:-1)}:null;
 if(strip)strip.d0=pickD(mz0,mz1,[]);
 const RR0=strip&&sW?mx0+SW+TP:mx0,RR1=strip&&!sW?mx1-SW-TP:mx1;
 if(strip&&db===mainB)du0=Math.max(sW?mx0+SW+TP+4:16,Math.min(sW?dfr.len-DR.w-16:mx1-SW-TP-4-DR.w,du0));
 const hz0=strip?(strip.dir>0?mz0+22:mz1-14-4*NS):0,hz1=strip?(strip.dir>0?mz0+14+4*NS:mz1-22):0;
 const inHole=(x,z)=>!!strip&&x>=strip.sx0&&x<strip.sx1&&z>=hz0&&z<hz1;
 const dxw=dfr.xz(du0+(DR.w>>1),0)[0],dz1=db.z1;
 const jun=boxes[1]?{wb:boxes[1],c0:boxes[1].dir>0?mz1:mz0-TP}:null;let jd0=0;
 if(strip){const[a,b2]=sW?[0,mx0+SW+TP+4]:[mx1-SW-TP-4,M.w];for(const f of[2,3]){const r=uR(mainB,f,a,b2);mark(SF(mainB,f),r[0],r[1],999)}mark(SF(mainB,sW?1:0),0,1e4,999)}
 if(jun){const wb=jun.wb;jd0=pickD(wb.x0+T+2,wb.x1-T-2,strip?[[strip.p0-3,strip.p0+TP+3]]:[]);if(jd0===null)jd0=wb.x0+T+6+Math.floor(R()*(wb.x1-wb.x0-2*T-12-DW+1));
  for(const f of[0,1]){const r=uR(wb,f,jun.c0-5,jun.c0+TP+5);mark(SF(wb,f),r[0],r[1],999)}
  const fj=wb.dir>0?2:3,r=uR(mainB,fj,jd0-4,jd0+DW+4);FT.push({b:mainB,f:fj,u0:r[0],u1:r[1],s:-1})}

 /* ---- Sol : herbe par plaques, terre nue, chemin de pierres plates ---- */
 for(let Z=2;Z<NZ-2;Z++)for(let X=2;X<NX-2;X++){const x=X-OX,z=Z-OZ,n=vn(x*.045,z*.045,11),n3=vn(x*.2,z*.2,12),n2=hh(x,z,13);
  const dx=Math.abs(x-(dxw+5*Math.sin(z*.06))),pw=8+2*Math.sin(z*.13)+vn(z*.2,3.1,15)*3-1.5-(z-dz1>60?(z-dz1-60)/12:0);
  let top;
  if(z>=dz1-2&&dx<pw&&!(dx>pw-2&&n2>.45)){const cx=Math.floor((x+vn(z*.3,1,16)*3)/6),cz=Math.floor((z+vn(x*.3,2,17)*3)/5),sv=hh(cx,cz,14),ed=(x+z*7)%6===0&&n2>.6;
   top=ed?[78,66,52]:sc(sv<.25?[138,120,98]:sv<.55?[112,98,80]:sv<.8?[150,134,108]:[98,88,74],.9+n2*.18)}
  else{const dry=vn(x*.03,z*.03,18)>.62,dirt=vn(x*.07,z*.07,19)>.72&&Math.abs(x-dxw)<60;
   top=dirt?sc([98,76,52],.9+n2*.2):sc(mx(mx([62,92,38],[104,128,50],n),dry?[150,140,70]:[60,84,36],dry?.5:n3*.4),.88+n2*.2)}
  for(let y=2;y<G-1;y++){const i=(y*NZ+Z)*NX+X;g[i]=pk(sc([84,62,42],.9+hh(x,y,z)*.2));MT[i]=4}
  {const i=((G-1)*NZ+Z)*NX+X;g[i]=pk(top);MT[i]=4}
 }

 /* ---- Toit : rangs de hauteur variable, tuiles de largeur variable avec nez relevé, affaissement léger ---- */
 const NR=48,RW=[],RHt=[],ROW=new Uint8Array(1400),TCOL=[],TOFF=[];
 {let q_=0;for(let i=0;i<NR;i++){const h=(RF.tile==='terracotta'?5:4)+Math.floor(R()*2.6);RW.push(q_);RHt.push(h);for(let k=0;k<h&&q_+k<1400;k++)ROW[q_+k]=i;q_+=h}
  for(let i=0;i<NR;i++){const bd=new Uint16Array(1600),o=Math.floor(R()*9);let p_=-o,id=0;const w0=RF.tile==='terracotta'?7:5;
   while(p_<1700){const w=w0+Math.floor(R()*5);for(let k=Math.max(0,p_);k<Math.min(1600,p_+w);k++)bd[k]=id;TOFF.push(0);p_+=w;id++}TCOL.push(bd)}}
 const roofAt=(b,x,z)=>{
  if(x<b.rx0||x>=b.rx1||z<b.rz0||z>=b.rz1)return null;
  const h=b.m?(b.z1-b.z0)/2:(b.x1-b.x0)/2,p=h-Math.abs((b.m?z+.5-(b.z0+b.z1)/2:x+.5-(b.x0+b.x1)/2)),t0=Math.floor(Hw+TH-1+SL*p),sl=(p+EV)*sq,cap=p>h-2.5,al=b.m?x:z;
  const col=al+1000,r0=ROW[Math.min(1399,Math.floor(sl))],tid=TCOL[r0][Math.max(0,Math.min(1599,col))],sh=hh(r0,tid,41)*2.2,sl2=Math.max(0,sl+sh),r1=ROW[Math.min(1399,Math.floor(sl2))],fr=sl2-RW[r1],
   nose=fr<1?2:fr<2?1:0,wave=Math.round((vn(al*.022,5.5,5)-.5)*1.8+(vn(al*.09,sl*.06,6)-.5)*.9),jit=hh(r1,TCOL[r1][Math.max(0,Math.min(1599,col))],42)<.3?1:0;
  return{p,h,bot:t0-TH+1,top:t0+(cap?1+(((al>>2)&1)):nose+jit+wave),sl,cap,al,r1,fr:Math.floor(fr),tid:TCOL[r1][Math.max(0,Math.min(1599,col))],jt:TCOL[r1][Math.max(0,Math.min(1599,col))]!==TCOL[r1][Math.max(0,Math.min(1599,col-1))]}};
 const RB=new Int16Array(NX*NZ).fill(-32000);
 for(const b of boxes)for(let z=b.rz0;z<b.rz1;z++)for(let x=b.rx0;x<b.rx1;x++){const r=roofAt(b,x,z);if(r){const i=ix(x,z);if(r.bot>RB[i])RB[i]=r.bot}}
 const TCV=(r,x,z)=>{const pal=TPAL[RF.tile],t=hh(r.r1,r.tid,4);let c=t<.3?pal[0]:t<.62?pal[1]:t<.88?pal[2]:sc(pal[2],1.18);
  c=mx(c,[120,108,92],hh(r.r1,r.tid,43)*.18);
  if(r.fr===0)c=sc(c,1.1);else if(r.fr===1)c=sc(c,.95);else c=sc(c,.8+.04*Math.min(3,r.fr));
  if(r.jt)c=sc(c,.5);
  const n=vn(x*.06,z*.06,5)*.65+vn(x*.28,z*.28,6)*.35,th=1-RF.moss*.9;
  if(n>th)c=mx(c,mx([52,72,34],[92,106,50],vn(x*.31,z*.31,8)),Math.min(.85,(n-th)*6));
  else if(vn(x*.5,z*.5,7)>.8)c=mx(c,[150,150,110],.35);
  return J(c,x,r.r1,z,.07)};
 const rtile=(sl,col,x,z)=>{const r0=ROW[Math.min(1399,Math.max(0,Math.floor(sl)))],tid=TCOL[r0][Math.max(0,Math.min(1599,col))];const rr={r1:r0,tid,fr:Math.floor(sl-RW[r0]),jt:TCOL[r0][Math.max(0,Math.min(1599,col))]!==TCOL[r0][Math.max(0,Math.min(1599,col-1))]};return TCV(rr,x,z)};

 /* ---- Pierre : assises de 3 à 5 voxels, pierres de 5 à 13 voxels, arrondies, en relief variable, joints profonds ---- */
 const CV=new Uint16Array(VMAX),CF=new Uint16Array(VMAX),CH=[],SID=[],SB=[];
 for(let v=0,c=0;v<VMAX;c++){const h=v<PL?4:3+Math.floor(R()*3)+(R()<.1?1:0);for(let k=0;k<h&&v+k<VMAX;k++){CV[v+k]=c;CF[v+k]=k}CH[c]=h;
  const sid=new Uint16Array(UM),sb=[];let p=-Math.floor(R()*14);sb.push(p);
  while(p<UM+40){p+=(c>1?5+R()*8:8+R()*9)|0;sb.push(p)}
  for(let u=0,s_=0;u<UM;u++){while(sb[s_+1]<=u)s_++;sid[u]=s_}
  SID[c]=sid;SB[c]=sb;v+=h}
 const SC5=[[142,126,104],[118,104,88],[160,142,112],[128,118,108],[104,94,84],[150,128,96],[172,156,128]];
 const stoneC=(u,v,d,x,z,ex,solid)=>{LM=1;
  const c=CV[v],cf=CF[v],h=CH[c],s_=SID[c][u],a_=SB[c][s_],b_=SB[c][s_+1],W=b_-a_;
  const lu=(u-a_+.5)/W*2-1,lv=(cf+.5)/h*2-1,q=Math.pow(Math.abs(lu),2.3)+Math.pow(Math.abs(lv),2.3),hs=hh(c,s_,7);
  let pr=hs<.28?1.4:hs<.72?2.3:3.1;pr+=(hh(c,s_,8)-.5)*lu*1.1+(hh(c,s_,9)-.5)*lv*.8;
  let prot=q>=1.05||cf===0||u===a_?0:Math.round(pr*(1-Math.pow(Math.min(1,q),1.5))+.35);
  if(prot>0&&q>.4&&hh(x,v,z,41)<.08)prot--;
  const def=vn(u*.045,v*.06,22)>.64?1:0;
  if(!solid&&d<3-prot+ex+def)return null;
  if(prot<=0)return J([58,50,44],x,v,z,.12);
  const t=hh(c,s_,1),base=SC5[Math.floor(t*SC5.length)];
  let col=sc(mx(base,SC5[Math.floor(hh(c,s_,2)*SC5.length)],.3),(.86+vn(u*.13,v*.17,2)*.26)*(1-.22*Math.pow(Math.min(1,q),2)));
  if(v<PL+10&&vn(u*.2,v*.25,3)>.5)col=mx(col,[70,96,44],.5);
  else if(vn(u*.11,v*.13,23)>.78)col=mx(col,[150,146,92],.3);
  if(v<PL)col=sc(col,.85);
  return J(col,x,v,z,.09)};
 const wood=(a,b,c)=>J(sc(WOOD,.68+vn(a*.35+b*.05,c*.35+b*.3,9)*.42+hh(a,b,c)*.14),a,b,c,.05);
 const wallC=(x,z,v,d,f,cor)=>{
  const u=(f<2?z:x)+300+f*37,sty=WL.style;
  if(sty!=='stone'&&v>=PL){
   let bm=v<PL+3;for(let k=1;k<=st;k++){const c0=k===st?Hw-5:k*SH-2;if(v>=c0&&v<c0+(k===st?5:4))bm=true}
   if(bm)return wood(v,d,2);
   if(cor||u%WL.posts<5)return wood(u,d,1);
   if(sty==='timber-plaster'){
    if(v<PL+14&&vn(u*.16+v*.01,v*.2,32)*.6+vn(u*.05,v*.07,35)*.4>.6+(v-PL)*.02)return stoneC(u,v,d,x,z,1);
    if(d<1)return null;LM=3;
    let c=mx(PLAS,[132,112,86],Math.max(0,(PL+14-v)/(PL+14))*.6);c=sc(c,.86+.26*vn(u*.12,v*.12,34));c=mx(c,[168,146,112],Math.max(0,vn(u*.05,v*.035,33)-.45)*1.1);
    return J(c,x,v,z,.05)}
   return stoneC(u,v,d,x,z,1)}
  return stoneC(u,v,d,x,z,0)};

 /* ---- Murs, sols ---- */
 for(let Z=0;Z<NZ;Z++)for(let X=0;X<NX;X++){const i=Z*NX+X;if(!FM[i])continue;const x=X-OX,z=Z-OZ;
  if(!DS[i]||DS[i]>T){
   S(x,-1,z,J([142,106,72],x,0,z,.07));if((x+z*3)%11===0)S(x,-1,z,[96,70,46]);
   for(let k=1;k<=st;k++){if(k===1&&inHole(x,z))continue;for(let v=k*SH-3;v<k*SH;v++)S(x,v,z,J([132,98,66],x,v,z,.07))}
   continue}
  const f=FC[i],d=DS[i]-1,top=RB[i]===-32000?Hw:RB[i];
  let ox=false,oz=false;for(let k=1;k<=6;k++){if(!inF(x+k,z)||!inF(x-k,z))ox=true;if(!inF(x,z+k)||!inF(x,z-k))oz=true}
  const cor=ox&&oz;
  for(let v=0;v<top;v++){LM=2;const c=wallC(x,z,v,d,f,cor);if(c){CM=LM;S(x,v,z,c)}}CM=0;
 }
 /* ---- Toit : remplissage + bords en bois + chevrons apparents ---- */
 for(const b of boxes)for(let z=b.rz0;z<b.rz1;z++)for(let x=b.rx0;x<b.rx1;x++){const r=roofAt(b,x,z);if(!r)continue;
  const edge=r.p<-EV+2||r.al<(b.m?b.rx0:b.rz0)+2||r.al>=(b.m?b.rx1:b.rz1)-2,tc=r.cap?sc(TPAL[RF.tile][1],.7):null;
  for(let v=r.bot;v<=r.top;v++){CM=v===r.bot||edge?2:5;S(x,v,z,v===r.bot?WOODD:edge?wood(x,v,z):tc?J(sc(tc,.85+((r.al>>1)&1)*.2),x,v,z,.08):TCV(r,x,z))}CM=0;
  if(r.p<0&&!inF(x,z)&&!(Math.abs(x-dxw)<24&&z>=dz1-1)&&((b.m?x:z)%10+10)%10<2)for(let v=r.bot-3;v<r.bot;v++)if(!at(x,v,z)&&v>=0)S(x,v,z,wood(x,v,z))}

 /* ---- Fenêtres ---- */
 const op=(uu,vv,w,h,a,e)=>{if(uu<-e||uu>=w+e||vv<-e)return false;if(a){const r=w/2,cy=h-r;if(vv<cy)return true;return(uu+.5-r)**2+(vv+.5-cy)**2<=(r+e)**2}return vv<h+e};
 const SHC=PC[WN.color];
 function win(fr,u0,v0,w,h,arch,full){
  const lit=hh(fr.b.x0+u0,v0,fr.f,17)<WN.lit;
  for(let uu=-5;uu<w+5;uu++)for(let vv=-5;vv<h+5;vv++){const o=op(uu,vv,w,h,arch,0),rg=op(uu,vv,w,h,arch,2),u=u0+uu,v=v0+vv;
   if(rg&&!o){for(let d=0;d<T;d++)put(fr,u,v,d,wood(u,v,d))}
   else if(o){for(let d=0;d<T;d++)put(fr,u,v,d,0)}}
  if(!full)return;
  {const a=fr.xz(0,0),b=fr.xz(1,0),c=fr.xz(0,1),U=[b[0]-a[0],b[1]-a[1]],N=[c[0]-a[0],c[1]-a[1]],hw=w>>1,cells=[],cc=(u,d)=>{const q=fr.xz(u,d);return[q[0]+.5,q[1]+.5]};
   for(let uu=0;uu<w;uu++)for(let vv=0;vv<h;vv++)if(op(uu,vv,w,h,arch,0)){const q=fr.xz(u0+uu,T-3);cells.push(gi(q[0],v0+vv,q[1]))}
   const L0=cc(u0,T-3),R0=cc(u0+w-1,T-3);
   wobjs.push({kind:'win',y:G+v0,h,w,arch,lit,nx:N[0],nz:N[1],cells,cx:(L0[0]+R0[0])/2,cz:(L0[1]+R0[1])/2,
    parts:[{hx:L0[0]-U[0]*.5,hz:L0[1]-U[1]*.5,ux:U[0],uz:U[1],rev:false,w:hw},{hx:R0[0]+U[0]*.5,hz:R0[1]+U[1]*.5,ux:-U[0],uz:-U[1],rev:true,w:w-hw}]})}
  for(let uu=-5;uu<w+5;uu++){for(let d=-2;d<=1;d++){if(arch||true){put(fr,u0+uu,v0-4,d,J(STN,uu,d,v0,.07));put(fr,u0+uu,v0-3,d,J(STN,uu,d,v0,.07))}}
   if(!arch)for(let vv=h+2;vv<h+5;vv++)for(let d=-1;d<=1;d++)put(fr,u0+uu,v0+vv,d,J(STN,uu,vv,d,.07))}
  if(WN.shutters){const sw=(w>>1)+1;
   for(const s0 of[-3-sw,w+3])for(let uu=0;uu<sw;uu++)for(let vv=-2;vv<h+2;vv++){const u=u0+s0+uu,v=v0+vv,gap=uu%4===3,bat=vv===4||vv===h-3;
    put(fr,u,v,-1,gap?sc(SHC,.55):J(SHC,u,v,1,.08));if(bat)put(fr,u,v,-2,sc(SHC,.8))}}
  if(WN.box){for(let uu=-3;uu<w+3;uu++)for(let d=-5;d<=-1;d++)for(let vv=-11;vv<-5;vv++){const edge=uu<-2||uu>=w+2||d===-5||vv===-11;if(edge||vv===-6)put(fr,u0+uu,v0+vv,d,edge?wood(uu,vv,d):[58,40,28])}
   for(let uu=-2;uu<w+2;uu++)for(let d=-4;d<=-3;d++){const hgt=2+Math.floor(hh(u0+uu,d,fr.f,8)*4);
    for(let k=0;k<hgt;k++){const fl=k===hgt-1&&hh(u0+uu,d,fr.f,9)>.4;put(fr,u0+uu,v0-5+k,d,fl?FL[Math.floor(hh(u0+uu,d,2,3)*4)]:J([70,110,48],uu,k,d,.15))}}}
 }
 const d_0=(a,b)=>a*31+b;

 /* ---- Porte, perron, auvent, lanterne ---- */
 if(true){const w=DR.w,h=DR.h,u0=du0,fr=dfr,dcells=[];
  for(let uu=-6;uu<w+6;uu++)for(let vv=0;vv<h+6;vv++){const o=op(uu,vv,w,h,DR.arch,0),rg=op(uu,vv,w,h,DR.arch,3),u=u0+uu;
   if(rg&&!o){for(let d=0;d<T;d++)put(fr,u,vv,d,J(STN,u,vv,d,.1))}
   else if(o){for(let d=0;d<T;d++)put(fr,u,vv,d,0);dcells.push([u,vv])}}
  {const a=fr.xz(0,0),b=fr.xz(1,0),c=fr.xz(0,1),ux=b[0]-a[0],uz=b[1]-a[1],nx=c[0]-a[0],nz=c[1]-a[1],p=fr.xz(u0,T-3),cells=[];
   for(const[u,vv]of dcells)for(let d=T-3;d<=T-2;d++){const q=fr.xz(u,d);cells.push(gi(q[0],vv,q[1]))}
   const hx=p[0]+.5+nx*.5-ux*.5,hz=p[1]+.5+nz*.5-uz*.5;
   doors.push({kind:'ext',s:0,hx,hz,y:G,ux,uz,nx,nz,w,h,arch:DR.arch,col:PC[DR.color],cells,cx:hx+ux*w/2,cz:hz+uz*w/2})}
  for(let uu=-8;uu<w+8;uu++)for(let d=-12;d<=-1;d++)for(let v=0;v<3;v++)put(fr,u0+uu,v,d,J([128,124,118],uu,d,v,.1));
  mark(fr,u0-22,u0+w+22,999);
  if(DR.porch){const pu0=u0-16,pu1=u0+w+16,PD=30,pt=Math.min(h+14,Hw-3),bt=d=>pt-Math.floor((-d-1)*.25);
   for(let u=pu0;u<pu1;u++)for(let d=-1;d>=-PD;d--){const t=bt(d),p=fr.xz(u,d),sl=(PD-1-(-d-1))*1.03,edge=u<pu0+2||u>=pu1-2||d<-PD+2;
    for(let v=t-3;v<=t;v++)S(p[0],v,p[1],v===t-3?WOODD:edge?wood(u,v,d):rtile(sl,u+1000,p[0],p[1]))}
   for(const pu of[pu0+3,pu1-7]){const top=bt(-PD+3)-3;
    for(let a=0;a<4;a++)for(let c=0;c<4;c++)for(let v=0;v<top;v++)put(fr,pu+a,v,-PD+2+c,wood(pu+a,v,c));
    const dir=pu<u0?1:-1,x0=dir>0?pu+4:pu-1;
    for(let k=1;k<=9;k++)for(let c=0;c<4;c++){put(fr,x0+dir*(k-1),top-k,-PD+2+c,WOOD);put(fr,x0+dir*(k-1),top-k-1,-PD+2+c,WOOD)}}
   const lu=u0+w+5,ld=-14,lb=bt(ld)-3;
   for(let v=lb-3;v<lb;v++)put(fr,lu+1,v,ld-1,IRON);
   for(let a=0;a<4;a++)for(let c=0;c<4;c++)for(let k=0;k<6;k++){const corner=(a===0||a===3)&&(c===0||c===3),cap=k===0||k===5;
    put(fr,lu+a,lb-3-k-1,ld-c,corner||cap?IRON:[255,206,112],!(corner||cap))}
   const lp=fr.xz(lu+2,ld-2);lights.push({p:[lp[0]+OX,lb-6+G,lp[1]+OZ],c:0xffb45a,i:.9,r:10,o:1})}
 }

 /* ---- Cheminée, appentis à bois ---- */
 const cfr=SF(boxes[0],cs==='E'?0:1);
 {const uc=cfr.len>>1,top=Hw+TH-1+Math.ceil(SL*M.d/2)+12;mark(cfr,uc-26,uc+26,999);FT.push({b:mainB,f:cfr.f,u0:uc-30,u1:uc+30,s:-1});
  const sc2=(x,z,v)=>stoneC((x+z)+600,v,0,x,z,0,true);
  for(let v=0;v<top+8;v++){const wide=v<Hw-4,hw=wide?13:11,dd=wide?18:15;
   for(let u=uc-hw;u<=uc+hw;u++)for(let d=-dd;d<=-1;d++){const p=cfr.xz(u,d);
    if(v<top)S(p[0],v,p[1],sc2(p[0],p[1],v));
    else if(v<top+3){}}}
  const cw=13,cd=17;
  for(let v=top;v<top+8;v++)for(let u=uc-cw;u<=uc+cw;u++)for(let d=-cd;d<=-1;d++){const p=cfr.xz(u,d);
   if(v<top+3)S(p[0],v,p[1],J(STN,u,v,d,.08));
   else{const ring=Math.abs(u-uc)>cw-4||d<-cd+3;if(ring&&Math.abs(u-uc)>2&&Math.abs(d+9)>2)S(p[0],v,p[1],J(STN,u,v,d,.1))}}}
 const sfr=SF(boxes[0],cs==='E'?1:0),Ls=Math.min(72,sfr.len-50),Ds=34;let shU=null;
 if(P.shed&&Ls>=40)for(const us of[(sfr.len-Ls>>1),Math.max(8,sfr.len-Ls-14),14])if(ext(sfr,us,us+Ls)&&freeOut(sfr,us,us+Ls,Ds+2)){shU=us;break}
 if(shU!==null){const us=shU,ue=us+Ls,va=min2(Hw-6,48);
  mark(sfr,us-8,ue+8,SH);
  for(let u=us-4;u<ue+4;u++)for(let k=0;k<Ds+2;k++){const d=-1-k,t=va+2-Math.floor(k*.26),p=sfr.xz(u,d),sl=(Ds+1-k)*1.03,edge=u<us-2||u>=ue+2||k>=Ds;
   for(let v=t-3;v<=t;v++)S(p[0],v,p[1],v===t-3?WOODD:edge?wood(u,v,d):rtile(sl,u+1000,p[0],p[1]))}
  const posts=[us,ue-4];if(Ls>60)posts.push((us+ue)/2|0);
  for(const pu of posts)for(let a=0;a<4;a++)for(let c=0;c<4;c++){const d=-Ds+c+1,t=va+2-Math.floor((Ds-c)*.26)-4;for(let v=0;v<t;v++)put(sfr,pu+a,v,d,wood(pu+a,v,c))}
  for(let u=us+2;u<ue-2;u++){const tp=20+Math.floor(hh(Math.floor(u/6),1,5)*7);
   for(let v=0;v<tp;v++){const j=Math.floor(v/5.2),sh=j&1?3:0,cx=Math.round((u-sh)/6)*6+sh,cy=j*5.2+3,dd=Math.hypot(u-cx,v-cy);
    for(let d=-16;d<=-1;d++){let c;if(dd<2.9){c=d===-16?(dd<.9?[216,186,134]:dd<2?[178,138,92]:[100,72,46]):J([94,68,46],u,v,d,.12)}else c=[34,26,20];put(sfr,u,v,d,c)}}}}
 function min2(a,b){return a<b?a:b}

 /* ---- Fenêtres : sélection (façade libre, extérieur dégagé, pièce derrière, hors cloisons/porte/cheminée/escalier) ---- */
 FT.push({b:db,f:2,u0:du0-8,u1:du0+DR.w+8,s:0});
 const wins=[],vents=[];let nl=0;
 for(const b of boxes)for(let f=0;f<4;f++){const fr=SF(b,f),n=Math.max(1,Math.round(fr.len/WN.gap)),gab=b.m?f<2:f>=2;
  for(let s=0;s<st;s++)for(let k=0;k<n;k++){const uc=Math.round((k+.5)*fr.len/n),u0=uc-(WN.w>>1),v0=s*SH+WN.sill,m=WN.shutters?(WN.w>>1)+6:6;
   if(u0-m<8||u0+WN.w+m>fr.len-8||!ext(fr,u0-m,u0+WN.w+m)||!freeOut(fr,u0-m,u0+WN.w+m,6)||busy(fr,u0-m,u0+WN.w+m,v0))continue;
   let ok=true;for(let u=u0;u<u0+WN.w&&ok;u+=2)for(let d=T;d<=T+2;d++){const p=fr.xz(u,d);if(!intr(p[0],p[1]))ok=false}
   if(!ok)continue;
   wins.push({fr,u0,v0,s});FT.push({b,f,u0:u0-6,u1:u0+WN.w+6,s});
   if(b===db&&f===2&&nl<3&&hh(b.x0+u0,v0,f,17)<WN.lit){nl++;const p=fr.xz(uc,-10);lights.push({p:[p[0]+OX,v0+(WN.h>>1)+G,p[1]+OZ],c:0xffb050,i:.6,r:7,o:1})}}
  if(gab){const uc=fr.len>>1,v0=Hw+8;if(!busy(fr,uc-12,uc+12,v0)&&ext(fr,uc-8,uc+8))vents.push({fr,uc,v0})}}

 /* ---- Intérieur : cloisons (BSP) avec une porte par cloison => graphe de pièces connexe, escalier, rambarde ---- */
 const cutsS=[[],[]],PMc=[new Uint8Array(NX*NZ),new Uint8Array(NX*NZ)],rnd=(a,b)=>a+Math.floor(R()*(b-a+1));
 const conflict=(c,s)=>{const fs=c.ax===0?[...(c.a1>=mz1?[2]:[]),...(c.a0<=mz0?[3]:[])]:[...(c.a1>=mx1?[0]:[]),...(c.a0<=mx0?[1]:[])];
  return fs.some(f=>{const r=uR(mainB,f,c.c0,c.c1);return FT.some(t=>t.b===mainB&&t.f===f&&(t.s<0||t.s===s)&&r[1]>t.u0&&r[0]<t.u1)})};
 for(let s=0;s<st;s++){const cc=cutsS[s];
  if(strip)cc.push({ax:0,c0:strip.p0,c1:strip.p0+TP,a0:mz0,a1:mz1,door:strip.d0});
  if(jun)cc.push({ax:1,c0:jun.c0,c1:jun.c0+TP,a0:jun.wb.x0,a1:jun.wb.x1,door:jd0});
  let c1=null;
  if(RR1-RR0>=70&&(s===0||R()<.8))for(let t=0;t<12&&!c1;t++){const px=rnd(RR0+32,RR1-32-TP),c={ax:0,c0:px,c1:px+TP,a0:mz0,a1:mz1};if(!conflict(c,s)){c.door=pickD(mz0,mz1,[]);if(c.door!==null)c1=c}}
  if(c1)cc.push(c1);
  if(R()<.6){const pcs=c1?[[RR0,c1.c0],[c1.c1,RR1]]:[[RR0,RR1]],pc=pcs[Math.floor(R()*pcs.length)],pa=pc[0],pb=pc[1];
   if(pb-pa>=40){const forb=[];
    if(strip&&((sW&&pa===RR0)||(!sW&&pb===RR1)))forb.push([strip.d0-3,strip.d0+DW+3]);
    if(c1&&(pa===c1.c1||pb===c1.c0))forb.push([c1.door-3,c1.door+DW+3]);
    for(let t=0;t<12;t++){const pz=rnd(mz0+30,mz1-30-TP);
     if(forb.some(f=>pz<f[1]&&pz+TP>f[0]))continue;
     const c={ax:1,c0:pz,c1:pz+TP,a0:pa,a1:pb};if(conflict(c,s))continue;
     c.door=pickD(pa,pb,[]);if(c.door!==null){cc.push(c);break}}}}
 }
 const PCOL=[198,182,152];
 function fillCut(c,s){
  const v0=s*SH,v1=(s+1)*SH-3,xr=c.ax===0?[c.c0,c.c1]:[c.a0,c.a1],zr=c.ax===0?[c.a0,c.a1]:[c.c0,c.c1];
  for(let z=zr[0];z<zr[1];z++)for(let x=xr[0];x<xr[1];x++){if(!intr(x,z))continue;PMc[s][ix(x,z)]=1;for(let v=v0;v<v1;v++)S(x,v,z,v<v0+3?J(WOOD,x,v,z,.1):J(PCOL,x,v,z,.04))}
  const d=c.door;
  for(let a=d-2;a<d+DW+2;a++)for(let t=c.c0;t<c.c1;t++){const x=c.ax===0?t:a,z=c.ax===0?a:t;if(!intr(x,z))continue;
   const open=a>=d&&a<d+DW;
   for(let v=v0;v<v0+DHT+3;v++){if(open&&v<v0+DHT){S(x,v,z,0);PMc[s][ix(x,z)]=0}else S(x,v,z,wood(x,v,z))}}
  {const hi=R()<.5,t0=c.c0+1.5,sg=R()<.5?1:-1,cells=[],xz=[];let hx,hz,ux,uz,nx,nz;
   if(c.ax===0){hx=t0;hz=hi?d+DW:d;ux=0;uz=hi?-1:1;nx=sg;nz=0}else{hz=t0;hx=hi?d+DW:d;uz=0;ux=hi?-1:1;nz=sg;nx=0}
   for(let a=d;a<d+DW;a++)for(let t=c.c0;t<c.c1;t++){const x=c.ax===0?t:a,z=c.ax===0?a:t;if(!intr(x,z))continue;xz.push([x,z]);for(let v=v0;v<v0+DHT;v++)cells.push(gi(x,v,z))}
   doors.push({kind:'int',s,hx,hz,y:G+v0,ux,uz,nx,nz,w:DW,h:DHT,arch:false,col:[112,80,52],cells,xz,cx:hx+ux*DW/2,cz:hz+uz*DW/2,ax:c.ax,c0:c.c0,c1:c.c1,d})}}
 for(let s=0;s<st;s++)for(const c of cutsS[s])fillCut(c,s);
 let start1=null;
 if(strip){
  for(let i=0;i<NS;i++){const h=Math.round((i+1)*SH/NS),zs=strip.dir>0?mz0+14+4*i:mz1-14-4*(i+1);
   for(let z=zs;z<zs+4;z++)for(let x=strip.sx0;x<strip.sx1;x++)for(let v=0;v<h;v++)S(x,v,z,v===h-1?J([150,108,70],x,v,z,.08):J([112,78,50],x,v,z,.08))}
  const rx=sW?strip.sx1:strip.sx0-1,za=strip.dir>0?hz0-1:hz0+10,zb=strip.dir>0?hz1-11:hz1;
  const rail=(x,z)=>{PMc[1][ix(x,z)]=1;for(let v=SH;v<SH+19;v++)if(((x+z)%6<2)||v>=SH+16)S(x,v,z,wood(x,v,z))};
  for(let z=za;z<=zb;z++)rail(rx,z);
  const zr=strip.dir>0?hz0-1:hz1;for(let x=strip.sx0;x<strip.sx1;x++)rail(x,zr);
  start1=[sW?strip.sx1+5:strip.sx0-6,(hz0+hz1)>>1];
 }
 for(const w of wins)win(w.fr,w.u0,w.v0,WN.w,WN.h,WN.arch,true);
 for(const vt of vents){const u0=vt.uc-5;for(let uu=-1;uu<11;uu++)for(let vv=-1;vv<13;vv++){const o=op(uu,vv,10,12,true,0),r=op(uu,vv,10,12,true,1);
  if(r)for(let d=0;d<2;d++)put(vt.fr,u0+uu,vt.v0+vv,d,o?(vv%3===0?WOODD:J(WOOD,uu,vv,d,.1)):WOODL)}}

 /* ---- Pièces (flood fill), foyer, lampes, meubles ---- */
 const INS=new Uint8Array(NX*NZ);for(let i=0;i<NX*NZ;i++)if(FM[i]&&(!DS[i]||DS[i]>T))INS[i]=1;
 const RM=[new Int16Array(NX*NZ).fill(-1),new Int16Array(NX*NZ).fill(-1)],PMd=[new Uint8Array(NX*NZ),new Uint8Array(NX*NZ)],OCC=[new Uint8Array(NX*NZ),new Uint8Array(NX*NZ)],OH=[new Uint8Array(NX*NZ),new Uint8Array(NX*NZ)],rooms=[];
 const stairZ0=strip?(strip.dir>0?mz0+14:mz1-14-4*NS):0,stairZ1=strip?stairZ0+4*NS:0;
 const inStair=(x,z)=>!!strip&&x>=strip.sx0&&x<strip.sx1&&z>=stairZ0&&z<stairZ1;
 for(const d of doors)if(d.kind==='int')for(const q of d.xz)PMd[d.s][ix(q[0],q[1])]=1;
 const fx0=Math.min(...boxes.map(b=>b.x0)),fx1=Math.max(...boxes.map(b=>b.x1)),fz0=Math.min(...boxes.map(b=>b.z0)),fz1=Math.max(...boxes.map(b=>b.z1));
 const frees=(s,x,z)=>{const c=ix(x,z);return INS[c]===1&&!PMc[s][c]&&!PMd[s][c]&&!(s===1&&inHole(x,z))&&!(s===0&&inStair(x,z))};
 for(let s=0;s<st;s++)for(let z=fz0;z<fz1;z++)for(let x=fx0;x<fx1;x++){const c=ix(x,z);if(RM[s][c]>=0||!frees(s,x,z))continue;
  const id=rooms.length,Rm={id,s,x0:x,x1:x+1,z0:z,z1:z+1,cells:[],anch:[],type:null},q=[c];RM[s][c]=id;
  for(let h=0;h<q.length;h++){const k=q[h],kx=k%NX-OX,kz=((k/NX)|0)-OZ;Rm.cells.push(k);if(kx<Rm.x0)Rm.x0=kx;if(kx+1>Rm.x1)Rm.x1=kx+1;if(kz<Rm.z0)Rm.z0=kz;if(kz+1>Rm.z1)Rm.z1=kz+1;
   for(const dd of[1,-1,NX,-NX]){const n=k+dd;if(RM[s][n]<0&&frees(s,n%NX-OX,((n/NX)|0)-OZ)){RM[s][n]=id;q.push(n)}}}
  rooms.push(Rm)}
 const anchor=(s,x,z)=>{const id=RM[s][ix(x,z)];if(id>=0)rooms[id].anch.push(ix(x,z))};
 for(const d of doors)if(d.kind==='int'){const mx=Math.floor(d.cx),mz=Math.floor(d.cz);if(d.ax===0){anchor(d.s,d.c0-2,mz);anchor(d.s,d.c1+1,mz)}else{anchor(d.s,mx,d.c0-2);anchor(d.s,mx,d.c1+1)}}
 const ec=dfr.xz(du0+(DR.w>>1),T+3);anchor(0,ec[0],ec[1]);
 /* sens d'ouverture des portes : vers la plus grande pièce (jamais vers le couloir d'escalier), charnière côté mur le plus proche */
 {const area=(s,x,z)=>{const id=RM[s][ix(x,z)];if(id<0)return 0;const r=rooms[id];return r.cells.length*(r.type==='hall'?.2:1)};
  const run=(s,x,z,dx,dz)=>{let n=0;while(n<40&&frees(s,x+dx*n,z+dz*n))n++;return n};
  for(const d of doors){if(d.kind!=='int')continue;const mid=Math.floor(d.d+DW/2);let xa,za,xb,zb;
   if(d.ax===0){xa=d.c0-2;za=mid;xb=d.c1+1;zb=mid}else{xa=mid;za=d.c0-2;xb=mid;zb=d.c1+1}
   const side=area(d.s,xb,zb)>=area(d.s,xa,za)?1:-1,px=side>0?xb:xa,pz=side>0?zb:za;let lo,hi;
   if(d.ax===0){lo=run(d.s,px,d.d-1,0,-1);hi=run(d.s,px,d.d+DW,0,1)}else{lo=run(d.s,d.d-1,pz,-1,0);hi=run(d.s,d.d+DW,pz,1,0)}
   const low=lo<hi||(lo===hi&&R()<.5),t0=d.c0+1.5;
   if(d.ax===0){d.hx=t0;d.hz=low?d.d:d.d+DW;d.ux=0;d.uz=low?1:-1;d.nx=side;d.nz=0}else{d.hz=t0;d.hx=low?d.d:d.d+DW;d.uz=0;d.ux=low?1:-1;d.nz=side;d.nx=0}
   d.cx=d.hx+d.ux*DW/2;d.cz=d.hz+d.uz*DW/2}
  const d=doors.find(q=>q.kind==='ext');if(d){const a0=dfr.xz(0,0),a1=dfr.xz(1,0),a2=dfr.xz(0,1),U=[a1[0]-a0[0],a1[1]-a0[1]],N=[a2[0]-a0[0],a2[1]-a0[1]],w=DR.w;
   const run2=(u,du)=>{let n=0;while(n<40){const q=dfr.xz(u+du*n,T+1);if(!frees(0,q[0],q[1]))break;n++}return n};
   const leftH=run2(du0-1,-1)<=run2(du0+w,1),base=leftH?dfr.xz(du0,T-3):dfr.xz(du0+w-1,T-3),sg=leftH?-1:1;
   d.hx=base[0]+.5+N[0]*.5+sg*U[0]*.5;d.hz=base[1]+.5+N[1]*.5+sg*U[1]*.5;d.ux=leftH?U[0]:-U[0];d.uz=leftH?U[1]:-U[1]}}
 const rsv=(s,x0,x1,z0,z1)=>{for(let z=z0;z<z1;z++)for(let x=x0;x<x1;x++)OCC[s][ix(x,z)]=2};
 for(const d of doors)if(d.kind==='int'){if(d.ax===0)rsv(d.s,d.c0-16,d.c1+16,d.d-1,d.d+DW+1);else rsv(d.s,d.d-1,d.d+DW+1,d.c0-16,d.c1+16)}
 const rsvF=(s,fr,u0,u1,d0,d1,val=2)=>{for(let u=u0;u<u1;u++)for(let d=d0;d<d1;d++){const q=fr.xz(u,d);OCC[s][ix(q[0],q[1])]=val}};
 rsvF(0,dfr,du0-1,du0+DR.w+1,T,T+24);
 for(const w of wins)rsvF(w.s,w.fr,w.u0-1,w.u0+WN.w+1,T,T+7,4);
 /* foyer intérieur (côté cheminée, rez-de-chaussée) */
 {const uc=cfr.len>>1;
  for(let u=uc-8;u<uc+8;u++)for(let v=1;v<17;v++)for(let d=T-3;d<T;d++)put(cfr,u,v,d,0);
  for(let u=uc-8;u<uc+8;u++)for(let v=1;v<17;v++)put(cfr,u,v,T-4,J([40,36,34],u,v,0,.15));
  for(let u=uc-7;u<uc+7;u++)for(let d=T-3;d<T;d++){if(hh(u,d,31)<.55)put(cfr,u,1,d,[255,110+hh(u,d,32)*80,36],true);else if(hh(u,d,33)<.7)put(cfr,u,1,d,sc(WOOD,.8))}
  for(let u=uc-12;u<uc+12;u++)for(let d=T;d<T+5;d++)for(let v=0;v<22;v++){const hole=u>=uc-8&&u<uc+8&&v>=1&&v<17;put(cfr,u,v,d,hole?0:J(STN,u,v,d,.1))}
  for(let u=uc-14;u<uc+14;u++)for(let d=T;d<T+7;d++)for(let v=22;v<25;v++)put(cfr,u,v,d,wood(u,v,d));
  {const topC=Hw+TH-1+Math.ceil(SL*M.d/2)+12;/* conduit de fumée creux : du foyer jusqu'au sommet de la cheminée */
   for(let u=uc-4;u<uc+4;u++){for(let d=-4;d<T-3;d++)for(let v=13;v<17;v++)put(cfr,u,v,d,0);
    for(let d=-12;d<=-4;d++)for(let v=13;v<topC+9;v++)put(cfr,u,v,d,0)}
   for(let v=13;v<topC;v++)for(const[u,d]of[[uc-5,-8],[uc+4,-8],[uc-1,-13],[uc,-13],[uc-1,-3],[uc,-3]]){const q=cfr.xz(u,d);if(at(q[0],v,q[1]))S(q[0],v,q[1],J([54,48,44],u,v,d,.2))}}
  rsvF(0,cfr,uc-16,uc+16,T,T+18);rsvF(0,cfr,uc-14,uc+14,T,T+7,1);
  const q=cfr.xz(uc,T+2);lights.push({p:[q[0]+OX+.5,G+7,q[1]+OZ+.5],c:0xff7a30,i:2.6,r:6,d:6})}
 const hallC=start1?ix(start1[0],start1[1]):-1,entC=ix(ec[0],ec[1]);
 let wingId=-1;if(jun){const wb=jun.wb,wx=(wb.x0+wb.x1)>>1,wz=wb.dir>0?wb.z1-T-8:wb.z0+T+8;wingId=RM[0][ix(wx,wz)]}
 let bi=0;
 for(let s=0;s<st;s++){const rs=rooms.filter(r=>r.s===s&&r.cells.length>=150).sort((a,b)=>b.cells.length-a.cells.length);let kit=false;
  if(s===0&&wingId>=0&&wingId!==RM[0][entC]){rooms[wingId].type='kitchen';kit=true}
  for(const r of rs){if(r.type)continue;
   if(hallC>=0&&r.id===RM[s][hallC])r.type='hall';
   else if(s===0&&r.id===RM[0][entC])r.type='living';
   else if(s===0&&!kit){r.type='kitchen';kit=true}
   else if(s===0&&st>1)r.type='store';
   else r.type=(bi++%3===2)?'study':'bedroom'}}
 /* bibliothèque de meubles : w = largeur le long du mur, dp = profondeur depuis le mur, j = hauteur */
 let FWD=[124,90,58],FD=sc(FWD,.68);const BLK=[[150,52,48],[52,84,140],[62,112,72],[176,134,52],[110,60,120],[200,200,190],[70,60,60]];
 const cyl=(L,cx,cz,r,j0,j1,c,a)=>{for(let i=Math.floor(cx-r);i<=Math.ceil(cx+r);i++)for(let k=Math.floor(cz-r);k<=Math.ceil(cz+r);k++)if(i>=0&&k>=0&&Math.hypot(i-cx,k-cz)<=r)for(let j=j0;j<j1;j++)L(i,j,k,a?J(c,i,j,k,a):c)};
 const tableDeco=(L,ci,ck,j,q)=>{const k=q%5;
  if(k===0){for(let t=0;t<2;t++)L(ci,j+t,ck,[236,226,196]);L(ci,j+2,ck,[255,200,90],true)}
  else if(k===1){cyl(L,ci,ck,3.2,j,j+1,[150,100,60]);for(let t=0;t<7;t++)L(Math.round(ci+Math.cos(t)*1.8),j+1,Math.round(ck+Math.sin(t)*1.8),[[200,50,40],[230,190,50],[120,170,60]][t%3])}
  else if(k===2){cyl(L,ci-4,ck,2.6,j,j+1,[230,226,214]);cyl(L,ci+4,ck,2.6,j,j+1,[230,226,214]);L(ci-4,j+1,ck,[170,60,40]);L(ci+4,j+1,ck,[200,150,60])}
  else if(k===3){cyl(L,ci,ck,1.8,j,j+5,[150,92,60],.08);L(ci+2,j+3,ck,[150,92,60])}
  else{for(let i=ci-3;i<ci+3;i++)for(let kk=ck-2;kk<ck+2;kk++){L(i,j,kk,[150,50,50]);if(i<ci+2&&kk<ck+1)L(i,j+1,kk,[222,206,160])}}};
 const bx=(L,i0,i1,j0,j1,k0,k1,c,a)=>{for(let i=i0;i<i1;i++)for(let j=j0;j<j1;j++)for(let k=k0;k<k1;k++)L(i,j,k,a?J(c,i,j,k,a):c)};
 const IT={
  bed:{w:22,dp:40,draw(L,q){const bl=BLK[q%5];bx(L,0,22,5,7,0,40,FWD,.06);for(const[i,k]of[[0,0],[20,0],[0,38],[20,38]])bx(L,i,i+2,0,5,k,k+2,FD);
   bx(L,0,22,5,18,0,2,FD,.06);bx(L,0,22,5,11,38,40,FD,.06);bx(L,1,21,7,10,2,38,[228,220,202],.03);bx(L,1,21,10,11,14,38,bl,.06);bx(L,4,18,10,12,3,10,[240,236,226],.03)}},
  ward:{w:22,dp:10,draw(L){bx(L,0,22,0,40,0,10,FWD,.06);bx(L,0,22,38,40,0,10,FD);bx(L,11,12,1,38,9,10,FD);for(const i of[9,13]){L(i,20,9,IRON);L(i,21,9,IRON)}}},
  chest:{w:16,dp:9,draw(L){bx(L,0,16,0,9,0,9,FWD,.07);bx(L,3,4,0,9,0,9,IRON);bx(L,12,13,0,9,0,9,IRON);bx(L,7,9,5,7,8,9,[200,170,70])}},
  table:{w:34,dp:18,draw(L,q){bx(L,0,34,13,15,0,18,FWD,.06);for(const[i,k]of[[1,1],[31,1],[1,15],[31,15]])bx(L,i,i+2,0,13,k,k+2,FD);bx(L,3,31,10,11,8,10,FD);
   tableDeco(L,12,9,15,q);if(q&8)tableDeco(L,24,9,15,q>>3)}},
  stool:{w:7,dp:7,draw(L){bx(L,0,7,7,9,0,7,FWD,.06);for(const[i,k]of[[0,0],[5,0],[0,5],[5,5]])bx(L,i,i+2,0,7,k,k+2,FD)}},
  chair:{w:8,dp:8,draw(L){bx(L,0,8,8,9,0,8,FWD,.06);for(const[i,k]of[[0,0],[6,0],[0,6],[6,6]])bx(L,i,i+2,0,8,k,k+2,FD);bx(L,0,2,9,18,0,2,FD);bx(L,6,8,9,18,0,2,FD);bx(L,2,6,13,17,0,1,FWD)}},
  bench:{w:28,dp:7,draw(L){bx(L,0,28,7,9,0,7,FWD,.06);for(const i of[1,25])bx(L,i,i+2,0,7,1,6,FD)}},
  shelf:{w:24,dp:6,draw(L,q){bx(L,0,24,0,36,0,1,FD);bx(L,0,2,0,36,0,6,FWD);bx(L,22,24,0,36,0,6,FWD);for(const j of[0,9,18,27,34])bx(L,0,24,j,j+2,0,6,FWD,.05);
   for(let c=0;c<4;c++)for(let i=2;i<22;i+=2){if(hh(q,i,c,2)<.15)continue;bx(L,i,i+2,c*9+2,c*9+2+4+Math.floor(hh(q,i,c)*3),1,5,BLK[Math.floor(hh(q,i,c,3)*5)],.1)}}},
  counter:{w:30,dp:12,draw(L){bx(L,0,30,0,16,0,12,FWD,.06);for(let i=10;i<30;i+=10)bx(L,i,i+1,1,15,11,12,FD);bx(L,0,30,16,18,0,12,[150,146,138],.06);bx(L,3,11,18,19,3,9,[190,150,100]);cyl(L,19,6,2.5,18,19,[170,110,80]);cyl(L,25,5,1.8,18,23,[150,92,60],.08)}},
  crate:{w:10,dp:10,draw(L){bx(L,0,10,0,10,0,10,FWD,.09);bx(L,0,10,4,6,0,10,FD);bx(L,4,6,0,10,0,10,FD)}},
  barrel:{w:13,dp:13,draw(L){for(let j=0;j<14;j++){const bl=6.4-Math.pow((j-6.5)/7,2)*1.3;for(let i=0;i<13;i++)for(let k=0;k<13;k++){const r=Math.hypot(i-6,k-6);if(r>bl)continue;
   L(i,j,k,j===13?(r>bl-1.2?WOODL:[70,50,34]):(j===3||j===10)?[52,50,54]:J(sc(WOODL,.8+hh(Math.floor((Math.atan2(k-6,i-6)+3.2)*3.2),j>>2,1)*.3),i,j,k,.04))}}}},
  night:{w:9,dp:9,draw(L){bx(L,0,9,0,10,0,9,FWD,.07);bx(L,0,9,10,11,0,9,FD);bx(L,4,5,11,14,4,5,[236,226,196]);L(4,14,4,[255,200,90],true)}},
  bedS:{w:16,dp:34,h:14,draw(L,q){const bl=BLK[q%5];bx(L,0,16,4,6,0,34,FWD,.06);for(const[i,k]of[[0,0],[14,0],[0,32],[14,32]])bx(L,i,i+2,0,4,k,k+2,FD);bx(L,0,16,4,14,0,2,FD,.06);bx(L,1,15,6,8,2,34,[228,220,202],.03);bx(L,1,15,8,9,12,34,bl,.06);bx(L,3,13,8,10,2,9,[240,236,226],.03)}},
  bedD:{w:30,dp:40,h:32,draw(L,q){const bl=BLK[q%5],cu=BLK[(q+2)%5];bx(L,0,30,5,7,0,40,FWD,.06);for(const[i,k]of[[0,0],[28,0],[0,38],[28,38]])bx(L,i,i+2,0,32,k,k+2,FD);
   bx(L,0,30,7,20,0,2,FD,.06);bx(L,0,30,5,11,38,40,FD,.06);bx(L,2,28,7,10,2,38,[228,220,202],.03);bx(L,2,28,10,11,12,38,bl,.06);bx(L,3,14,10,12,3,10,[240,236,226],.03);bx(L,16,27,10,12,3,10,[240,236,226],.03);bx(L,2,28,30,32,0,2,cu,.05)}},
  cot:{w:12,dp:20,h:10,draw(L,q){bx(L,0,12,2,3,0,20,FWD,.06);bx(L,0,12,2,8,0,1,FD);bx(L,0,12,2,8,19,20,FD);bx(L,0,1,2,8,0,20,FD);bx(L,11,12,2,8,0,20,FD);bx(L,1,11,3,4,1,19,[236,230,214]);bx(L,1,11,4,5,6,19,BLK[q%5],.05);bx(L,0,12,0,2,2,4,FD);bx(L,0,12,0,2,16,18,FD)}},
  armchair:{w:12,dp:12,h:20,draw(L,q){const cu=BLK[q%5];bx(L,0,12,0,6,0,12,FD);bx(L,1,11,6,9,1,12,cu,.06);bx(L,1,11,9,20,0,3,cu,.06);bx(L,0,2,6,14,0,12,FWD,.06);bx(L,10,12,6,14,0,12,FWD,.06);bx(L,2,10,9,11,3,11,sc(cu,1.15),.05)}},
  settle:{w:30,dp:9,h:22,draw(L,q){const cu=BLK[q%5];bx(L,0,30,0,7,0,9,FD);bx(L,1,29,7,9,1,9,cu,.06);bx(L,0,30,9,22,0,2,FWD,.06);bx(L,0,2,7,15,0,9,FWD);bx(L,28,30,7,15,0,9,FWD);bx(L,2,28,9,15,2,3,sc(cu,.85),.05)}},
  dresser:{w:28,dp:10,h:29,draw(L){bx(L,0,28,0,22,0,10,FWD,.06);bx(L,0,28,22,24,0,10,FD);for(const j of[7,14])bx(L,0,28,j,j+1,9,10,FD);for(const j of[3,10,17])for(const i of[7,20])bx(L,i,i+2,j,j+1,9,10,[200,170,70]);cyl(L,22,5,2.5,24,28,[170,110,80],.08)}},
  cupboard:{w:20,dp:9,h:34,draw(L,q){bx(L,0,20,0,34,0,9,FWD,.06);bx(L,0,20,0,12,8,9,FD);bx(L,3,17,14,31,8,9,[150,190,205]);bx(L,3,17,14,31,1,8,0);
   for(let j=18;j<31;j+=6){bx(L,2,18,j,j+1,1,8,FD);for(let i=4;i<17;i+=3)bx(L,i,i+2,j+1,j+3,3,5,BLK[Math.floor(hh(q,i,j)*5)],.1)}}},
  bookL:{w:20,dp:6,h:20,draw(L,q){bx(L,0,20,0,20,0,1,FD);bx(L,0,2,0,20,0,6,FWD);bx(L,18,20,0,20,0,6,FWD);for(const j of[0,9,18])bx(L,0,20,j,j+2,0,6,FWD,.05);
   for(let c=0;c<2;c++)for(let i=2;i<18;i+=2){if(hh(q,i,c,2)<.2)continue;bx(L,i,i+2,c*9+2,c*9+6+Math.floor(hh(q,i,c)*3),1,5,BLK[Math.floor(hh(q,i,c,3)*5)],.1)}}},
  stove:{w:18,dp:15,h:50,draw(L){bx(L,0,18,0,18,0,15,[120,116,110],.07);bx(L,0,18,18,20,0,15,IRON);bx(L,5,13,4,12,14,15,[30,28,28]);for(let i=6;i<12;i++)L(i,5,14,[255,130,40],true);
   cyl(L,5,7,3,20,25,[40,38,42]);bx(L,7,10,20,50,10,13,IRON)}},
  bench2:{w:36,dp:14,h:24,draw(L){bx(L,0,36,14,17,0,14,FWD,.07);for(const[i,k]of[[1,1],[33,1],[1,11],[33,11]])bx(L,i,i+2,0,14,k,k+2,FD);bx(L,2,34,6,8,2,4,FD);bx(L,2,34,6,8,10,12,FD);
   bx(L,4,8,17,19,3,9,IRON);bx(L,12,20,17,18,4,6,[170,170,175]);bx(L,24,32,17,19,3,9,FD);bx(L,26,29,19,21,4,7,FWD)}},
  anvil:{w:12,dp:8,h:11,draw(){}},
  sacks:{w:12,dp:10,h:11,draw(L){for(const[i,k,j]of[[0,0,0],[6,0,0],[3,5,0],[3,1,5]]){bx(L,i,i+6,j,j+5,k,k+5,[200,180,140],.08);bx(L,i+2,i+4,j+5,j+6,k+1,k+3,[170,150,110])}}},
  crateS:{w:12,dp:10,h:18,draw(L){bx(L,0,10,0,8,0,10,FWD,.09);bx(L,0,10,3,4,0,10,FD);bx(L,4,5,0,8,0,10,FD);bx(L,2,9,8,14,1,8,FWD,.09);bx(L,2,9,10,11,1,8,FD);bx(L,10,12,0,5,3,8,FWD,.09)}},
  bucket:{w:7,dp:7,h:8,draw(L){for(let j=0;j<7;j++)cyl(L,3,3,2.6+j*.12,j,j+1,j%3===2?IRON:FWD,.05);cyl(L,3,3,2,5,6,[70,100,130])}},
  plant:{w:8,dp:8,h:16,draw(L,q){cyl(L,3.5,3.5,3,0,5,[168,96,66],.08);cyl(L,3.5,3.5,2.3,5,6,[60,42,30]);for(let j=6;j<11;j++)L(3,j,3,[70,110,48]);
   for(let k=0;k<22;k++){const a=hh(q,k)*6.28,rr=hh(q,k,1)*3.2,j=6+Math.floor(hh(q,k,2)*9);L(Math.round(3.5+Math.cos(a)*rr),j,Math.round(3.5+Math.sin(a)*rr),[62+hh(q,k,3)*40,120,50])}}},
  globe:{w:10,dp:10,h:18,draw(L){bx(L,3,7,0,2,3,7,FD);bx(L,4,6,2,8,4,6,FD);for(let i=0;i<10;i++)for(let j=8;j<18;j++)for(let k=0;k<10;k++)if(Math.hypot(i-4.5,j-12.5,k-4.5)<=4.6)L(i,j,k,hh(i,j,k)<.35?[90,140,70]:[60,100,170])}},
  lectern:{w:10,dp:10,h:24,draw(L){bx(L,3,7,0,18,3,7,FD);bx(L,1,9,0,2,1,9,FD);for(let k=0;k<8;k++){const j=18+(k>>1);bx(L,0,10,j,j+1,k+1,k+2,FWD);bx(L,1,9,j+1,j+2,k+1,k+2,[236,228,200])}}},
  roundT:{w:22,dp:22,h:20,draw(L,q){cyl(L,10.5,10.5,10.8,13,15,FWD,.06);bx(L,9,12,0,13,9,12,FD);cyl(L,10.5,10.5,5,0,2,FD);tableDeco(L,10,10,15,q)}},
  wheel:{w:16,dp:12,h:20,draw(L){bx(L,0,16,0,2,2,3,FD);bx(L,0,16,0,2,9,10,FD);bx(L,12,14,0,12,2,10,FWD);for(let t=0;t<44;t++){const a=t*.1428;L(Math.round(6+Math.cos(a)*5),Math.round(11+Math.sin(a)*5.5),5,FWD)}bx(L,5,7,10,12,4,7,IRON);bx(L,8,13,12,14,3,8,FWD)}},
  mirror:{w:12,dp:5,h:34,draw(L){bx(L,1,11,0,2,0,5,FD);bx(L,0,12,2,34,1,3,FWD,.06);bx(L,2,10,5,31,2,3,[170,196,210])}},
  painting:{w:12,dp:1,j0:24,h:10,draw(L,q){bx(L,0,12,0,10,0,1,[150,110,50]);bx(L,1,11,1,9,0,1,[120,170,220]);bx(L,1,11,1,4,0,1,[90,140,70]);bx(L,3+q%3,7+q%3,3,6,0,1,BLK[q%5]);bx(L,4+q%3,6+q%3,6,7,0,1,[120,60,50])}},
  banner:{w:8,dp:1,j0:12,h:26,draw(L,q){const c=BLK[q%5];bx(L,0,8,24,26,0,1,FD);bx(L,1,7,4,24,0,1,c,.05);for(let i=1;i<7;i++)bx(L,i,i+1,3-Math.min(3,Math.abs(i-3.5)|0),4,0,1,c);bx(L,3,5,12,18,0,1,[220,190,90])}},
  shield:{w:10,dp:2,j0:24,h:10,draw(L,q){const a=BLK[q%5];for(let i=0;i<10;i++)for(let j=0;j<10;j++){const r=Math.hypot(i-4.5,j-4.5);if(r>4.8)continue;L(i,j,0,r>3.9?IRON:((i<5)!==(j<5)?a:[225,225,225]));if(r<1.5)L(i,j,1,IRON)}}},
  herbs:{w:10,dp:2,j0:30,h:10,draw(L,q){bx(L,0,10,9,10,0,1,FD);for(const i of[1,4,7]){bx(L,i,i+1,3,9,0,1,[110,86,56]);bx(L,Math.max(0,i-1),i+2,0,4,0,2,[80+hh(q,i)*60,120,50],.15)}}},
  swords:{w:16,dp:2,j0:26,h:14,draw(L){for(let t=0;t<14;t++){L(1+t,t,0,[190,190,200]);L(14-t,t,0,[190,190,200])}bx(L,0,5,2,3,0,1,[200,170,70]);bx(L,11,16,2,3,0,1,[200,170,70])}},
  mapD:{w:14,dp:1,j0:22,h:11,draw(L,q){bx(L,0,14,0,11,0,1,[222,206,160],.05);for(let i=1;i<13;i+=2)L(i,3+Math.floor(hh(q,i)*5),0,[110,90,60]);L(8,6,0,[170,50,40]);bx(L,0,14,0,1,0,1,FD);bx(L,0,14,10,11,0,1,FD)}},
  sconce:{w:3,dp:3,j0:28,h:6,draw(L){bx(L,1,2,0,2,0,1,IRON);bx(L,0,3,2,3,0,3,IRON);bx(L,1,2,3,5,1,2,[236,226,196]);L(1,5,1,[255,200,90],true)}}};
 IT.anvil.draw=L=>{bx(L,3,9,0,5,2,6,FD);bx(L,2,10,5,8,1,7,IRON);bx(L,0,12,8,11,2,6,[70,70,78]);bx(L,10,12,9,10,3,5,[70,70,78])};
 const HT={bed:18,ward:40,chest:9,table:20,stool:9,chair:18,bench:9,shelf:36,counter:21,crate:10,barrel:14,night:15};for(const k in IT)IT[k].n=k;
 const sh=a=>{for(let i=a.length-1;i>0;i--){const j=Math.floor(R()*(i+1));[a[i],a[j]]=[a[j],a[i]]}return a};
 const VIS=new Int32Array(NX*NZ);let vstamp=0;
 const rInfo=r=>{const W=r.x1-r.x0+10,H=r.z1-r.z0+10,ox=r.x0-5,oz=r.z0-5,W1=W+1,Q=new Int32Array((W+1)*(H+1)),s_=r.s;
  const bl=(x,y)=>{const X=ox+x,Z=oz+y,c=ix(X,Z);return(!INS[c]||PMc[s_][c]||OCC[s_][c]===1||(s_===1&&inHole(X,Z))||(s_===0&&inStair(X,Z)))?1:0};
  for(let y=0;y<H;y++){let row=0;for(let x=0;x<W;x++){row+=bl(x,y);Q[(y+1)*W1+x+1]=Q[y*W1+x+1]+row}}
  const ok=(x,y)=>x>=3&&y>=3&&x<W-4&&y<H-4&&Q[(y+4)*W1+x+4]-Q[(y-3)*W1+x+4]-Q[(y+4)*W1+x-3]+Q[(y-3)*W1+x-3]===0;
  const near=a=>{const x0_=a%NX-OX-ox,y0_=((a/NX)|0)-OZ-oz,vis=new Uint8Array(W*H),qq=[y0_*W+x0_];vis[qq[0]]=1;
   for(let h=0;h<qq.length&&h<900;h++){const k=qq[h],x=k%W,y=(k/W)|0;if(ok(x,y))return[k];
    for(const[dx,dy]of[[1,0],[-1,0],[0,1],[0,-1]]){const nx=x+dx,ny=y+dy;if(nx<0||ny<0||nx>=W||ny>=H)continue;const n=ny*W+nx;if(!vis[n]&&!bl(nx,ny)){vis[n]=1;qq.push(n)}}}return[]};
  if(!r.anch.length)return[true,0];
  const sd=near(r.anch[0]);if(!sd.length)return[false,0];
  const seen=new Uint8Array(W*H),q=[];for(const k of sd){seen[k]=1;q.push(k)}
  for(let h=0;h<q.length;h++){const k=q[h],x=k%W,y=(k/W)|0;for(const[dx,dy]of[[1,0],[-1,0],[0,1],[0,-1]]){const nx=x+dx,ny=y+dy;if(nx<0||ny<0||nx>=W||ny>=H)continue;const n=ny*W+nx;if(!seen[n]&&ok(nx,ny)){seen[n]=1;q.push(n)}}}
  let un=0;for(let y=0;y<H;y++)for(let x=0;x<W;x++)if(RM[s_][ix(ox+x,oz+y)]===r.id&&ok(x,y)&&!seen[y*W+x])un++;
  return[r.anch.every(a=>near(a).some(k=>seen[k])),un]};
 const fitM=(r,it,map,soft)=>{const cells=[];for(let i=0;i<it.w;i++)for(let k=0;k<it.dp;k++){const q=map(i,k),c=ix(q[0],q[1]),o_=OCC[r.s][c];if(RM[r.s][c]!==r.id||(o_&&!(soft&&o_===4)))return null;cells.push(c)}return{cells,map}};
 const putIt=(r,it,f)=>{if(!r.base)r.base=rInfo(r);for(const c of f.cells)OCC[r.s][c]=1;const ri=rInfo(r);if((r.base[0]&&!ri[0])||ri[1]>r.base[1]+8){for(const c of f.cells)OCC[r.s][c]=0;return false}
  const ht=it.h||HT[it.n]||30;for(const c of f.cells)OH[r.s][c]=ht;
  const q=Math.floor(R()*1000),base=r.s*SH;it.draw((i,j,k,c,em)=>{const m=f.map(i,k);S(m[0],base+j,m[1],c,em)},q);return true};
 const wallMap=(r,side,a,ko)=>side==='N'?(i,k)=>[a+i,r.z0+ko+k]:side==='S'?(i,k)=>[a+i,r.z1-1-ko-k]:side==='W'?(i,k)=>[r.x0+ko+k,a+i]:(i,k)=>[r.x1-1-ko-k,a+i];
 const wallPlace=(r,it,ko=0,soft=false)=>{const cs_=[];for(const side of['N','S','W','E']){const hz=side==='N'||side==='S',lo=hz?r.x0:r.z0,hi=hz?r.x1:r.z1;for(let a=lo;a<=hi-it.w;a+=2)cs_.push([side,a])}
  for(const[side,a]of sh(cs_)){const m=wallMap(r,side,a,ko),f=fitM(r,it,m,soft);if(!f)continue;
   if(ko===0){let wl=0;for(let i=0;i<it.w;i++){const q=m(i,-1);if(RM[r.s][ix(q[0],q[1])]!==r.id)wl++}if(wl<it.w*.7)continue}
   if(putIt(r,it,f))return{side,a}}return null};
 const ringOK=(r,x0,z0,w,d,g_)=>{for(let z=z0-g_;z<z0+d+g_;z++)for(let x=x0-g_;x<x0+w+g_;x++){const c=ix(x,z);if(RM[r.s][c]!==r.id||OCC[r.s][c]===1)return false}return true};
 const freePlace=(r,it,ring)=>{const cx=(r.x0+r.x1)/2,cz=(r.z0+r.z1)/2,cs_=[];
  for(const rot of[0,1])for(let x=r.x0+4;x<r.x1-4;x+=2)for(let z=r.z0+4;z<r.z1-4;z+=2)cs_.push([rot,x,z,Math.hypot(x+(rot?it.dp:it.w)/2-cx,z+(rot?it.w:it.dp)/2-cz)+R()*6]);
  cs_.sort((a,b)=>a[3]-b[3]);
  for(const[rot,x,z]of cs_.slice(0,500)){const m=rot?(i,k)=>[x+k,z+i]:(i,k)=>[x+i,z+k],f=fitM(r,it,m);
   if(f&&ringOK(r,x,z,rot?it.dp:it.w,rot?it.w:it.dp,ring)&&putIt(r,it,f))return{rot,x,z,tw:rot?it.dp:it.w,td:rot?it.w:it.dp}}return null};
 const around=(r,t)=>{const{rot,x,z}=t,tw=rot?18:34,td=rot?34:18,pl_=(it,m)=>{const f=fitM(r,it,m);if(f)putIt(r,it,f)};
  if(!rot){for(const i0 of[4,22]){pl_(IT.chair,(i,k)=>[x+i0+i,z-9+k]);pl_(IT.chair,(i,k)=>[x+i0+i,z+td+1+(7-k)])}pl_(IT.stool,(i,k)=>[x-8+i,z+5+k]);pl_(IT.stool,(i,k)=>[x+tw+1+i,z+5+k])}
  else{for(const i0 of[4,22]){pl_(IT.chair,(i,k)=>[x-9+k,z+i0+i]);pl_(IT.chair,(i,k)=>[x+tw+1+(7-k),z+i0+i])}pl_(IT.stool,(i,k)=>[x+5+i,z-8+k]);pl_(IT.stool,(i,k)=>[x+5+i,z+td+1+k])}};

 const rug=(r,t,rnd)=>{const c1=BLK[Math.floor(R()*5)],c2=sc(c1,.6),base=r.s*SH,x0=t.x-5,z0=t.z-5,w=t.tw+10,d=t.td+10;
  for(let z=z0;z<z0+d;z++)for(let x=x0;x<x0+w;x++){const c=ix(x,z);if(RM[r.s][c]!==r.id||OCC[r.s][c]===1||at(x,base,z))continue;
   let e;if(rnd){const u=(x+.5-x0)/w*2-1,v=(z+.5-z0)/d*2-1,q=Math.hypot(u,v);if(q>1)continue;e=(1-q)*Math.min(w,d)/2}else e=Math.min(x-x0,x0+w-1-x,z-z0,z0+d-1-z);
   S(x,base,z,J(e<2?[220,196,120]:e<4?c2:c1,x,0,z,.05))}};
 const aroundR=(r,t)=>{for(const[dx,dz]of[[-8,7],[23,7],[7,-8],[7,23]]){const f=fitM(r,IT.stool,(i,k)=>[t.x+dx+i,t.z+dz+k]);if(f)putIt(r,IT.stool,f)}};
 const floorRug=r=>{const cx=(r.x0+r.x1)>>1,cz=(r.z0+r.z1)>>1,w=24+Math.floor(R()*10),d=18+Math.floor(R()*8);rug(r,{x:cx-(w>>1)+5,z:cz-(d>>1)+5,tw:w-10,td:d-10},R()<.5)};
 /* décors muraux : accrochés au mur, au-dessus des meubles bas, jamais devant fenêtre / porte / foyer */
 const decor=(r,it)=>{const cs_=[];for(const side of['N','S','W','E']){const hz=side==='N'||side==='S',lo=hz?r.x0:r.z0,hi=hz?r.x1:r.z1;for(let a=lo;a<=hi-it.w;a+=2)cs_.push([side,a])}
  for(const[side,a]of sh(cs_)){const m=wallMap(r,side,a,0),cells=[];let ok=true;
   for(let i=0;i<it.w&&ok;i++){const q=m(i,-1);if(RM[r.s][ix(q[0],q[1])]===r.id){ok=false;break}
    for(let k=0;k<it.dp;k++){const p=m(i,k),c=ix(p[0],p[1]);if(RM[r.s][c]!==r.id||OCC[r.s][c]>=2||(OCC[r.s][c]===1&&OH[r.s][c]>=it.j0-1)){ok=false;break}cells.push(c)}}
   if(!ok)continue;
   if(!r.base)r.base=rInfo(r);const chg=cells.filter(c=>!OCC[r.s][c]);for(const c of chg)OCC[r.s][c]=1;
   const ri=rInfo(r);if((r.base[0]&&!ri[0])||ri[1]>r.base[1]+8){for(const c of chg)OCC[r.s][c]=0;continue}
   for(const c of cells)OH[r.s][c]=Math.max(OH[r.s][c],it.j0+it.h);
   const q=Math.floor(R()*1000),base=r.s*SH+it.j0;it.draw((i,j,k,c,em)=>{const p=m(i,k);S(p[0],base+j,p[1],c,em)},q);return true}return false};
 const lamp=r=>{const cx=(r.x0+r.x1)>>1,cz=(r.z0+r.z1)>>1;let best=null,bd=1e9;for(const c of r.cells){const x=c%NX-OX,z=((c/NX)|0)-OZ,d=(x-cx)**2+(z-cz)**2;if(d<bd){bd=d;best=[x,z]}}
  if(!best)return;const x=best[0],z=best[1],vc=(r.s+1)*SH-3;
  if(r.type==='living'||(r.cells.length>3500&&R()<.5)){
   for(let v=vc-8;v<vc;v++)S(x,v,z,IRON);
   for(let t=0;t<24;t++){const a=t/24*6.283;S(x+Math.round(Math.cos(a)*6),vc-9,z+Math.round(Math.sin(a)*6),IRON)}
   S(x,vc-9,z,IRON);for(let t=0;t<6;t++){const a=t/6*6.283,px=x+Math.round(Math.cos(a)*6),pz=z+Math.round(Math.sin(a)*6);S(px,vc-8,pz,[236,226,196]);S(px,vc-7,pz,[255,200,90],true)}
   lights.push({p:[x+OX+.5,vc-8+G,z+OZ+.5],c:0xffc47a,i:3,r:6,d:7});return}
  for(let v=vc-9;v<vc;v++)S(x,v,z,IRON);
  for(let a=-1;a<=1;a++)for(let b=-1;b<=1;b++)for(let k=0;k<5;k++){const edge=a!==0&&b!==0,cap=k===0||k===4;S(x+a,vc-14+k,z+b,edge||cap?IRON:[255,208,120],!(edge||cap))}
  lights.push({p:[x+OX+.5,vc-12+G,z+OZ+.5],c:0xffc47a,i:2.4,r:5,d:5.5})};
 let nFur=0,nBed=0,nKit=0;
 const placeBed=(r,A,soft)=>{const bi=R()<.5?IT.bedD:IT.bedS;let b=wallPlace(r,bi,0,soft),bt=bi;if(!b){b=wallPlace(r,IT.bedS,0,soft);bt=IT.bedS}if(!b)return false;nFur++;nBed++;
  for(const a of[b.a+bt.w+1,b.a-IT.night.w-1]){const f1=fitM(r,IT.night,wallMap(r,b.side,a,0));if(f1&&putIt(r,IT.night,f1)){nFur++;if(R()<.5)break}}
  const f2=fitM(r,IT.chest,wallMap(r,b.side,b.a+((bt.w-IT.chest.w)>>1),bt.dp+1));if(f2&&putIt(r,IT.chest,f2))nFur++;
  if(A>3600&&R()<.6&&wallPlace(r,IT.bedS)){nFur++;nBed++}return true};
 const placeKit=(r,soft)=>{if(!wallPlace(r,IT.stove,0,soft))return false;nFur++;nKit++;if(wallPlace(r,IT.counter,0,soft))nFur++;if(R()<.5&&wallPlace(r,IT.counter,0,soft))nFur++;return true};
 const pick=a=>a[Math.floor(R()*a.length)],WT=[[124,90,58],[104,74,48],[138,102,68],[92,64,42],[150,116,80]];
 const DECS={living:['painting','banner','shield','swords','sconce','sconce'],kitchen:['herbs','herbs','painting','sconce'],bedroom:['painting','painting','banner','sconce'],study:['mapD','mapD','painting','shield','sconce'],store:['swords','shield','sconce'],hall:['banner','painting','sconce']};
 /* passe prioritaire : cuisine (fourneau) et lit placés AVANT le reste du mobilier, pour que chaque maison en ait toujours */
 if(P.deco.furn!==false){
  const setW0=r=>{FWD=WT[Math.floor(hh(r.id,r.s,91)*WT.length)];FD=sc(FWD,.68)},cand=r=>r.cells.length>=150&&r.type&&r.type!=='hall',byA=(a,b)=>b.cells.length-a.cells.length;
  const kc=[...rooms.filter(r=>cand(r)&&r.type==='kitchen').sort(byA),...rooms.filter(r=>cand(r)&&r.type!=='kitchen').sort(byA)];
  for(const soft of[false,true]){if(nKit)break;for(const r of kc){setW0(r);if(placeKit(r,soft)){r.kit=true;break}}}
  const bc=[...rooms.filter(r=>cand(r)&&r.type==='bedroom').sort(byA),...rooms.filter(r=>cand(r)&&r.type!=='bedroom'&&r.type!=='kitchen').sort(byA),...rooms.filter(r=>cand(r)&&r.type==='kitchen').sort(byA)];
  for(const soft of[false,true]){if(nBed)break;for(const r of bc){setW0(r);if(placeBed(r,r.cells.length,soft)){r.bed=true;break}}}}
 for(const r of rooms){if(P.deco.furn===false)break;if(r.cells.length<150||!r.type)continue;const A=r.cells.length;
  FWD=WT[Math.floor(hh(r.id,r.s,91)*WT.length)];FD=sc(FWD,.68);lamp(r);
  const w_=(it,n=1,pr=1)=>{for(let i=0;i<n;i++)if(R()<pr&&wallPlace(r,it))nFur++};
  const tbl=()=>{const rnd=R()<.35,it=rnd?IT.roundT:IT.table,t=freePlace(r,it,9)||freePlace(r,it,4)||freePlace(r,it,0);if(t){nFur++;rug(r,t,rnd);rnd?aroundR(r,t):around(r,t)}return t};
  if(r.type==='living'){tbl();w_(pick([IT.settle,IT.bench]));w_(IT.armchair,1+(R()<.5?1:0));w_(pick([IT.bookL,IT.shelf]),1+(A>2500?1:0));w_(pick([IT.dresser,IT.cupboard]));w_(IT.chest,1,.7);w_(pick([IT.barrel,IT.sacks]),1,.8);w_(IT.plant,1+(R()<.5?1:0),.9)}
  else if(r.type==='kitchen'){if(!r.kit)placeKit(r);tbl();w_(IT.cupboard,1,.6);w_(IT.shelf);w_(IT.barrel,1,.8);w_(IT.sacks);w_(IT.crateS);w_(IT.bucket,1,.7);w_(IT.plant,1,.5)}
  else if(r.type==='bedroom'){if(!r.bed)placeBed(r,A);w_(pick([IT.ward,IT.dresser]));w_(IT.mirror,1,.6);w_(IT.armchair,1,.5);w_(IT.wheel,1,.3);w_(IT.cot,1,.25);w_(IT.bookL,1,.4);w_(IT.plant,1,.6);w_(IT.chest,1,.4);floorRug(r)}
  else if(r.type==='study'){tbl();w_(pick([IT.bookL,IT.shelf]),2+(R()<.5?1:0));w_(IT.globe);w_(IT.lectern,1,.6);w_(IT.armchair);w_(IT.chest,1,.6);w_(IT.plant,1,.6)}
  else if(r.type==='store'){w_(IT.bench2);w_(IT.anvil,1,.5);w_(IT.crateS,2);w_(IT.barrel,2);w_(IT.sacks,2);w_(IT.shelf);w_(IT.bucket,1,.6);w_(IT.chest,1,.5)}
  else if(r.type!=='hall'){w_(IT.barrel,2);w_(IT.crateS,2);w_(IT.shelf);w_(IT.chest)}
}
 if(P.deco.furn!==false){
  /* garanties : au moins une cuisine (fourneau) et un lit dans chaque maison */
  const big=rooms.filter(r=>r.cells.length>=150&&r.type!=='hall').sort((a,b)=>b.cells.length-a.cells.length),setW=r=>{FWD=WT[Math.floor(hh(r.id,r.s,91)*WT.length)];FD=sc(FWD,.68)};
  if(!nKit)for(const r of big){setW(r);if(placeKit(r,true))break}
  if(!nBed)for(const r of big){setW(r);if(placeBed(r,r.cells.length,true))break}
  for(const r of rooms){if(r.cells.length<150||!r.type)continue;setW(r);let nd=0;for(const k of sh((DECS[r.type]||[]).slice())){if(nd>=5)break;if(decor(r,IT[k])){nd++;nFur++}}}}

 /* ---- Tonneaux, fleurs, herbes ---- */
 const soft=new Set(),SPL=(x,v,z,c)=>{S(x,v,z,c);soft.add(gi(x,v,z))};
 const barrel=(cx,cz)=>{const h=14;for(let v=0;v<h;v++){const bl=6.4-Math.pow((v-h/2+.5)/(h/2),2)*1.3;
  for(let dx=-7;dx<=7;dx++)for(let dz=-7;dz<=7;dz++){const r=Math.hypot(dx,dz);if(r>bl)continue;
   let c;if(v===h-1)c=r>bl-1.2?WOODL:[70,50,34];else if(v===3||v===h-4)c=[52,50,54];else c=sc(WOODL,.78+hh(Math.floor((Math.atan2(dz,dx)+3.2)*3.2),v>>2,1)*.3);
   S(cx+dx,v,cz+dz,J(c,dx,v,dz,.04))}}};
 const bc=[[du0-28,-14],[du0+DR.w+40,-16],[du0-46,-12]];
 for(let k=0;k<P.deco.barrels&&k<3;k++){const[u,d]=bc[k];if(u<6||u>dfr.len-6)continue;const p=dfr.xz(u,d);let ok=true;
  for(let a=-8;a<=8&&ok;a+=4)for(let c=-8;c<=8;c+=4)if(inF(p[0]+a,p[1]+c)||at(p[0]+a,0,p[1]+c))ok=false;
  if(ok)barrel(p[0],p[1])}
  /* ---- Clôture de bois (portail ouvert sur le chemin) et poteau à lanterne ---- */
 {const fx0=X0-46,fx1=X1+46,fz1=Z1+48,fz0=Math.floor((Z0+Z1)/2)+10,px=z=>dxw+5*Math.sin(z*.06),FWc=[86,66,48],gate=13;
  const post=(x,z,hg)=>{for(let v=0;v<hg;v++)for(let a=0;a<4;a++)for(let b=0;b<4;b++){if(v>=hg-2&&(a+b)%3===0)continue;S(x+a,v,z+b,J(sc(FWc,.78+.32*hh(x,v,z,2)),a,v,b,.08))}};
  const rl=(x,z,alongX,len,v0,dv)=>{for(let t=0;t<len;t++){const sag=Math.round(Math.sin(t/len*Math.PI)*-1.2);for(let k=0;k<2;k++)for(let w=0;w<2;w++)S(alongX?x+t:x+w,v0+dv+sag+k,alongX?z+w:z+t,J(sc(FWc,.68+.4*hh(x,t,z,3)),t,k,w,.1))}};
  const line=(a0,a1,fixed,alongX)=>{const ps=[];for(let a=a0;a<=a1;a+=26+((hh(a,fixed,5)*5)|0))ps.push(a);ps.push(a1);
   const inGate=(a)=>alongX&&Math.abs(a+2-px(fixed))<gate;
   ps.forEach((a,i)=>{const hgt=15+((hh(a,fixed,6)*3)|0);if(!inGate(a))post(alongX?a:fixed,alongX?fixed:a,hgt);
    if(i<ps.length-1){const b=ps[i+1],mid=(a+b)/2;if(alongX&&(inGate(a)||inGate(b)||inGate(mid)))return;
     rl(alongX?a+4:fixed,alongX?fixed:a+4,alongX,b-a-4,5,(hh(a,fixed,7)*3|0)-1);rl(alongX?a+4:fixed,alongX?fixed:a+4,alongX,b-a-4,11,(hh(a,fixed,8)*3|0)-1)}})};
  line(fx0,fx1,fz1,true);line(fz0,fz1,fx0,false);line(fz0,fz1,fx1,false);
  for(const s of[-1,1]){const gx=Math.round(px(fz1))+s*gate-2;post(gx,fz1,21)}
  /* poteau à lanterne près du chemin */
  const lx=Math.round(px(Z1+32))+62,lz=Z1+32,ph=46;
  for(let v=0;v<ph;v++)for(let a=0;a<4;a++)for(let b=0;b<4;b++)S(lx+a,v,lz+b,J(sc(FWc,.8+.3*hh(lx,v,lz,9)),a,v,b,.08));
  for(let t=-14;t<4;t++)for(let k=0;k<3;k++)for(let w=0;w<3;w++)S(lx+t,ph-3+k,lz+w,J(sc(FWc,.9),t,k,w,.08));
  for(let t=0;t<9;t++)for(let w=0;w<3;w++)S(lx-t-1,ph-4-t,lz+w,J(sc(FWc,.8),t,0,w,.08));
  const llx=lx-13,llz=lz;for(let v=0;v<2;v++)S(llx+1,ph-4-v,llz+1,IRON);
  for(let v=0;v<8;v++)for(let a=0;a<5;a++)for(let b=0;b<5;b++){const e=(a===0||a===4)&&(b===0||b===4),sh=a===0||a===4||b===0||b===4;if(v===0||v===7){if(e||!sh)S(llx-1+a,ph-14+v,llz-1+b,IRON)}else if(e)S(llx-1+a,ph-14+v,llz-1+b,IRON);else S(llx-1+a,ph-14+v,llz-1+b,mx(AMB,[255,226,150],hh(a,v,b)*.5),sh?1:1)}
  lights.push({p:[llx+1.5+OX,ph-10+G,llz+1.5+OZ],c:0xffb45a,i:1.5,r:9,d:8,o:1})}
 const FLC=[[232,228,212],[228,196,92],[168,148,204],[214,150,168],[236,236,224],[206,86,70]];
 for(let Z=4;Z<NZ-4;Z++)for(let X=4;X<NX-4;X++){const x=X-OX,z=Z-OZ;if(FM[Z*NX+X]||g[(G*NZ+Z)*NX+X])continue;
  const pth=z>=dz1-2&&Math.abs(x-(dxw+5*Math.sin(z*.06)))<7;if(pth)continue;
  const r1=hh(x,z,21),cl=vn(x*.05,z*.05,9),fl=vn(x*.035+7,z*.035,10),dens=P.deco.grass*(.25+cl*1.9);
  if(r1<dens){const h=2+Math.floor(hh(x,z,22)*4),bend=hh(x,z,26)<.5?0:hh(x,z,27)<.5?1:-1,hue=hh(x,z,28);
   for(let k=0;k<h;k++){const t=k/h,cx=k>=h-2?x+bend:x;SPL(cx,k,z,sc(mx(mx([52,84,32],[96,124,46],t),[150,150,60],hue>.8?t:0),.82+hh(x,z,k)*.3))}
   if(hh(x,z,29)<.5){const nx=x+(hh(x,z,30)<.5?1:-1),h2=Math.max(1,h-1-Math.floor(hh(x,z,31)*2));for(let k=0;k<h2;k++)SPL(nx,k,z,sc(mx([52,84,32],[110,130,50],k/h2),.85+hh(nx,z,k)*.25))}}
  else if(fl>.6&&r1>1-.07*(fl-.5)*3){const h=3+Math.floor(hh(x,z,23)*4),c=FLC[Math.floor(hh(Math.floor(x/9),Math.floor(z/9),24)*FLC.length)];for(let k=0;k<h;k++)SPL(x,k,z,[62,100,40]);SPL(x,h,z,c);if(hh(x,z,25)>.5){SPL(x+1,h-1,z,sc(c,.9));SPL(x-1,h-1,z,sc(c,.9))}}}
 return{MT,INS,Hw,soft,GL,doors:doors.map(d=>({...d,hx:d.hx+OX,hz:d.hz+OZ,cx:d.cx+OX,cz:d.cz+OZ})),wobjs:wobjs.map(d=>({...d,cx:d.cx+OX,cz:d.cz+OZ,parts:d.parts.map(q=>({...q,hx:q.hx+OX,hz:q.hz+OZ}))})),rooms:rooms.map(r=>({id:r.id,s:r.s,type:r.type,n:r.cells.length})),nFur,nBed,nKit,spawn:[dxw+OX+.5,G,dz1+OZ+22.5],dbg:{OCC,RM,rooms,PMc,inHole,intr,wins,strip,start1,entry:dfr.xz(du0+(DR.w>>1),T+3),ix,OX,OZ,FM,DS,mz0,mz1,mx0,mx1,st,T,DW,boxes,jun,jd0,cutsS,hz0,hz1,DR,du0,dfr},g,NX,NY,NZ,EM,lights,cx:(Math.min(...boxes.map(b=>b.x0))+Math.max(...boxes.map(b=>b.x1)))/2+OX,cz:(Math.min(...boxes.map(b=>b.z0))+Math.max(...boxes.map(b=>b.z1)))/2+OZ,
  w:Math.max(...boxes.map(b=>b.x1))-Math.min(...boxes.map(b=>b.x0)),dp:Math.max(...boxes.map(b=>b.z1))-Math.min(...boxes.map(b=>b.z0)),h:Hw+Math.ceil(SL*M.d/2)+TH}
}

/* ---- Maillage : faces visibles uniquement + occlusion ambiante par sommet ---- */
function meshify(o,bb){
 const{g,NX,NY,NZ,EM,GL=new Set(),INS,Hw:HW,MT}=o,ST=[1,NX*NZ,NX],AO=[.5,.72,.88,1],cap0=bb?1<<12:1<<17;
 const mk=()=>({n:0,cap:cap0,p:new Float32Array(3*cap0),c:new Uint8Array(3*cap0),q:new Int8Array(3*cap0),i:new Uint32Array(cap0*1.5),m:new Uint8Array(cap0),a:new Uint8Array(cap0),ni:0});
 const grow=b=>{b.cap*=2;const f=(A,k)=>{const a=new A.constructor(b.cap*k);a.set(A);return a};b.p=f(b.p,3);b.c=f(b.c,3);b.q=f(b.q,3);b.i=f(b.i,1.5);b.m=f(b.m,1);b.a=f(b.a,1)};
 const B=[mk(),mk(),mk()],hasE=EM.size>0,hasG=GL.size>0;let nv=0;
 const[X0,X1,Y0,Y1,Z0,Z1]=bb?[Math.max(2,bb[0]),Math.min(NX-2,bb[1]),Math.max(2,bb[2]),Math.min(NY-2,bb[3]),Math.max(2,bb[4]),Math.min(NZ-2,bb[5])]:[2,NX-2,2,NY-2,2,NZ-2];
 for(let y=Y0;y<Y1;y++)for(let z=Z0;z<Z1;z++){let i=(y*NZ+z)*NX+X0;for(let x=X0;x<X1;x++,i++){
  const c=g[i];if(!c)continue;nv++;
  const mtv=MT?MT[i]:2,gl=hasG&&GL.has(i),em=!gl&&hasE&&EM.has(i),b=B[gl?2:em?1:0],r0=(c>>11)*255/31,g0=(c>>5&63)*255/63,b0=(c&31)*255/31;
  for(let a=0;a<3;a++){const ta=(a+1)%3,tb=(a+2)%3,sa=ST[a],sta=ST[ta],stb=ST[tb];
   for(let sg=-1;sg<=1;sg+=2){const j=i+sg*sa;if(g[j]&&(gl||!(hasG&&GL.has(j))))continue;if(a===1&&sg<0&&y<=2)continue;
    const ao=[0,0,0,0],vb=b.n;let dim=1,insf=0;if(INS&&!em&&!gl){const nx_=x+(a===0?sg:0),ny_=y+(a===1?sg:0),nz_=z+(a===2?sg:0);if(INS[nz_*NX+nx_]&&ny_-G>=0&&ny_-G<HW-3){dim=.45;insf=16}}
    for(let k=0;k<4;k++){const su=k===1||k===2?1:0,sv=k>=2?1:0,du=su*2-1,dv=sv*2-1;
     const s1=g[j+du*sta]?1:0,s2=g[j+dv*stb]?1:0,cr=g[j+du*sta+dv*stb]?1:0,oc=s1&&s2?0:3-(s1+s2+cr);ao[k]=oc;const f=gl?1:.62+.38*AO[oc],av_=gl?1:AO[oc]*AO[oc]*dim;
     if(b.n>=b.cap)grow(b);
     const n3=b.n*3;
     b.p[n3]=x+(a===0&&sg>0?1:0)+(ta===0?su:0)+(tb===0?sv:0);b.p[n3+1]=y+(a===1&&sg>0?1:0)+(ta===1?su:0)+(tb===1?sv:0);b.p[n3+2]=z+(a===2&&sg>0?1:0)+(ta===2?su:0)+(tb===2?sv:0);
     b.m[b.n]=mtv+insf;b.a[b.n]=av_*255;b.c[n3]=r0*f;b.c[n3+1]=g0*f;b.c[n3+2]=b0*f;b.q[n3]=0;b.q[n3+1]=0;b.q[n3+2]=0;b.q[n3+a]=sg*127;b.n++}
    const L=ao[0]+ao[2]>ao[1]+ao[3]?(sg>0?[0,1,2,0,2,3]:[0,2,1,0,3,2]):(sg>0?[1,2,3,1,3,0]:[1,3,2,1,0,3]);
    for(let m=0;m<6;m++)b.i[b.ni++]=vb+L[m]}}}}
 return{B,nv}}

module.exports={derive,build,meshify,pk,VS,G,T,SH};
