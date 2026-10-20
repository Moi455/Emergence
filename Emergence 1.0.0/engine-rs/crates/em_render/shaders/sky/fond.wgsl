// Fond de ciel du laboratoire (code Emergence). Dérivé de `SKY_BG` (web-ocean, js/wgsl/ocean.js, MIT,
// © 2026 Maksymilian Dendura) : ciel de Hillaire + nuages + disque solaire inchangés ; ajouts du labo :
// crêtes lointaines en silhouette, sol plan, étoiles de nuit, perspective aérienne (aerial.wgsl).
// Assemblé après : frame, atmo_core, bindings_fond, sky_render_funcs, sky_cloud_funcs, aerial.

struct VO { @builtin(position) pos: vec4f, @location(0) ndc: vec2f };

@vertex fn vs(@builtin(vertex_index) i: u32) -> VO {
  let p = vec2f(f32((i << 1u) & 2u), f32(i & 2u)) * 2.0 - 1.0;
  var o: VO;
  o.pos = vec4f(p, 0.0, 1.0);
  o.ndc = p;
  return o;
}

fn u01(h: u32) -> f32 { return f32(h >> 8u) * (1.0 / 16777216.0); }

fn hash3u(p: vec3i) -> u32 {
  return pcgHash(u32(p.x) ^ pcgHash(u32(p.y) ^ pcgHash(u32(p.z) + 0x9e3779b9u)));
}

// Étoiles : une chance par cellule 3D de la sphère des directions ; disque doux entièrement inclus dans la cellule.
fn stars(dir: vec3f) -> vec3f {
  let p = dir * 260.0;
  let id = vec3i(floor(p));
  let f = p - floor(p);
  let h = hash3u(id);
  if (u01(h) < 0.9915) { return vec3f(0.0); }
  let h2 = pcgHash(h);
  let h3 = pcgHash(h2);
  let c = vec3f(0.3) + 0.4 * vec3f(u01(h), u01(h2), u01(h3));
  let d = length(f - c);
  let m = u01(h2);
  let lum = (0.12 + 2.4 * m * m * m) * smoothstep(0.30, 0.0, d);
  let teinte = mix(vec3f(1.0, 0.82, 0.62), vec3f(0.68, 0.80, 1.0), u01(h3));
  return teinte * lum;
}

// Pentes (tan de l'élévation) des trois crêtes dans l'azimut `dir` : lues dans la LUT 1D calculée une fois
// (crete_lut.wgsl), au lieu de 15 bruits par pixel.
fn ridgeSlopes(dir: vec3f) -> vec3f {
  let u = fract(atan2(dir.x, -dir.z) * 0.15915494);
  return textureSampleLevel(ridgeLUT, sampC, vec2f((u * 4096.0 + 0.5) / 4096.0, 0.5), 0.0).rgb;
}

fn ridgeColor(dir: vec3f, layer: f32, dist: f32) -> vec3f {
  let sxz = normalize(F.sunDir.xz + vec2f(1e-5));
  let dxz = normalize(dir.xz + vec2f(1e-5));
  // face tournée vers la caméra : éclairée si le soleil est derrière la caméra
  let lit = smoothstep(-0.25, 0.85, dot(-dxz, sxz));
  let up = skyAtmo(vec3f(0.0, 1.0, 0.0));
  let albedo = vec3f(0.075, 0.085, 0.075);
  let direct = sunIlluminance() * max(F.sunDir.y, 0.0) * lit * 0.55 / PI;
  let surface = albedo * (direct + up * 0.9);
  return applyAerial(surface, dir, dist);
}

// Étage 1 (demi-résolution) : ciel de Hillaire et nuages. Les bords des nuages sont anticrénelés par l'estimation
// de l'empreinte du pixel (aa < 0), sans dérivées : le flot de contrôle peut diverger et le sol est ignoré.
// Sortie : rgb = radiance, a = transmittance des nuages vers le soleil (sert au disque solaire et aux étoiles).
@fragment fn fs_ciel(in: VO) -> @location(0) vec4f {
  let dir = normalize(F.camFwd.xyz + in.ndc.x * F.camRight.xyz + in.ndc.y * F.camUp.xyz);
  if (dir.y < -0.03) { return vec4f(0.0, 0.0, 0.0, 1.0); }
  // un pixel de la demi-résolution couvre deux pixels de l'écran
  let pixAng = 2.0 * length(F.camUp.xyz) * F.screen.w * 2.0;
  var d2 = dir;
  d2.y = max(d2.y, 0.0005);
  d2 = normalize(d2);
  var sunT = 1.0;
  let cl = cloudLayers(d2, pixAng, vec2f(-1.0), &sunT);
  let L = skyAtmo(d2) * (1.0 - cl.a) + cl.rgb;
  return vec4f(L, sunT);
}

// Étage 2 (pleine résolution) : ciel rééchantillonné, disque solaire, étoiles, crêtes, sol, perspective aérienne.
@fragment fn fs(in: VO) -> @location(0) vec4f {
  let dir = normalize(F.camFwd.xyz + in.ndc.x * F.camRight.xyz + in.ndc.y * F.camUp.xyz);
  var d2 = dir;
  d2.y = max(d2.y, 0.0005);
  d2 = normalize(d2);
  // bords des crêtes
  let hxz = max(length(dir.xz), 1e-4);
  let slope = dir.y / hxz;
  let cretes = ridgeSlopes(dir);
  let e0 = cretes.x - slope;
  let e1 = cretes.y - slope;
  let e2 = cretes.z - slope;
  let w0 = max(fwidth(e0), 1e-5);
  let w1 = max(fwidth(e1), 1e-5);
  let w2 = max(fwidth(e2), 1e-5);

  let demi = textureSampleLevel(skyHalf, sampC, in.pos.xy * F.screen.zw, 0.0);
  let sunT = demi.a;
  var L = demi.rgb + sunDisk(dir) * sunT;

  // nuit : lueur faible du ciel et étoiles (masquées par les nuages)
  let nuit = 1.0 - smoothstep(-0.22, -0.06, F.sunDir.y);
  if (nuit > 0.0) {
    let lueur = vec3f(0.0016, 0.0030, 0.0072) * (1.0 + 2.5 * exp(-8.0 * d2.y));
    L += (lueur + stars(dir) * smoothstep(0.0, 0.05, dir.y) * sunT) * nuit;
  }
  // crêtes lointaines, de la plus loin à la plus proche ; le pied se fond dans la brume de l'horizon
  let pied = smoothstep(0.0, 0.012, slope);
  let hz = skyAtmo(normalize(vec3f(dir.x, 0.0005, dir.z)));
  if (dir.y > 0.0) {
    if (e2 > -w2 * 1.5) {
      let a2 = smoothstep(0.0, w2 * 1.5, e2);
      L = mix(L, mix(hz, ridgeColor(dir, 2.0, 38000.0), pied), a2);
    }
    if (e1 > -w1 * 1.5) {
      let a1 = smoothstep(0.0, w1 * 1.5, e1);
      L = mix(L, mix(hz, ridgeColor(dir, 1.0, 22000.0), pied), a1);
    }
    if (e0 > -w0 * 1.5) {
      let a0 = smoothstep(0.0, w0 * 1.5, e0);
      L = mix(L, mix(hz, ridgeColor(dir, 0.0, 9000.0), pied), a0);
    }
  }

  // sol plan (herbe sombre) jusqu'à l'horizon, noyé dans la perspective aérienne
  if (dir.y < 0.0) {
    let h = max(F.camPos.y, 0.5);
    let t = min(h / -dir.y, 80000.0);
    // damier doux de prés, de champs secs et de bois, détaillé de près seulement (pas de scintillement au loin)
    let sol = F.camPos.xz + dir.xz * t;
    let n1 = gnoise(sol * 0.0007 + vec2f(5.0, 2.0));
    let n2 = gnoise(sol * 0.006);
    let n3 = gnoise(sol * 0.09) * (1.0 - smoothstep(100.0, 500.0, t));
    var albedo = mix(vec3f(0.115, 0.14, 0.060), vec3f(0.19, 0.155, 0.075), smoothstep(0.0, 0.5, n1));
    albedo = mix(albedo, vec3f(0.035, 0.055, 0.028), smoothstep(0.05, 0.45, -n1 + 0.4 * n2));
    albedo *= 1.0 + 0.25 * n2 + 0.18 * n3;
    let direct = sunIlluminance() * max(F.sunDir.y, 0.0) / PI;
    // lumière du ciel reçue par le sol : moitié zénith, moitié horizon dans l'azimut regardé
    let ambiant = mix(skyAtmo(vec3f(0.0, 1.0, 0.0)), hz, 0.5);
    let nuitSol = vec3f(0.0008, 0.0014, 0.0030) * nuit;
    L = applyAerial(albedo * (direct + ambiant) + nuitSol, dir, t);
  }
  return vec4f(L, 1.0);
}
