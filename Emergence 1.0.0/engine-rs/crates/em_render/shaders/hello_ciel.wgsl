// Ciel de test (PAS Hillaire : L03) : dégradé vertical, soleil, graticule d'azimut et d'élévation.
// Sortie en linéaire : la cible est sRGB, le matériel encode à l'écriture.

struct Uniformes {
    droite: vec4<f32>,
    haut: vec4<f32>,
    avant: vec4<f32>,
    // x = tan(champ/2), y = rapport d'aspect, z = temps (s), w = inutilisé
    params: vec4<f32>,
    soleil: vec4<f32>,
};

@group(0) @binding(0) var<uniform> u: Uniformes;

struct Sortie {
    @builtin(position) pos: vec4<f32>,
    @location(0) ndc: vec2<f32>,
};

@vertex
fn vs(@builtin(vertex_index) i: u32) -> Sortie {
    // Triangle plein écran.
    let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u));
    var o: Sortie;
    o.pos = vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
    o.ndc = p * 2.0 - 1.0;
    return o;
}

// Bruit de gigue entrelacé (Jimenez), déterministe : casse le banding du dégradé 8 bits.
fn gigue(p: vec2<f32>) -> f32 {
    return fract(52.9829189 * fract(dot(p, vec2<f32>(0.06711056, 0.00583715))));
}

@fragment
fn fs(e: Sortie) -> @location(0) vec4<f32> {
    let t = u.params.x;
    let d = normalize(u.avant.xyz + e.ndc.x * u.params.y * t * u.droite.xyz + e.ndc.y * t * u.haut.xyz);

    let zenith = vec3<f32>(0.035, 0.13, 0.42);
    let horizon = vec3<f32>(0.62, 0.72, 0.84);
    let sol = vec3<f32>(0.10, 0.095, 0.085);

    var c: vec3<f32>;
    if (d.y >= 0.0) {
        c = mix(horizon, zenith, pow(clamp(d.y, 0.0, 1.0), 0.45));
    } else {
        c = mix(horizon * 0.35, sol, clamp(-d.y * 6.0, 0.0, 1.0));
    }

    // Soleil : disque net + halo chaud.
    let cs = dot(d, normalize(u.soleil.xyz));
    c += vec3<f32>(1.0, 0.85, 0.6) * (smoothstep(0.9995, 0.9999, cs) * 6.0 + pow(max(cs, 0.0), 64.0) * 0.5);

    // Graticule : méridiens tous les 15 degrés d'azimut, parallèles tous les 15 degrés d'élévation.
    let az = atan2(d.x, -d.z) * 57.29578 / 15.0;
    let el = asin(clamp(d.y, -1.0, 1.0)) * 57.29578 / 15.0;
    let l_az = abs(fract(az + 0.5) - 0.5) / max(fwidth(az), 1e-4);
    let l_el = abs(fract(el + 0.5) - 0.5) / max(fwidth(el), 1e-4);
    let ligne = 1.0 - clamp(min(l_az, l_el) - 0.5, 0.0, 1.0);
    let cap = select(0.0, 1.0, abs(el) < 5.9);
    c = mix(c, vec3<f32>(1.0, 1.0, 1.0), ligne * 0.22 * cap);

    c += (gigue(e.pos.xy) - 0.5) / 255.0;
    return vec4<f32>(max(c, vec3<f32>(0.0)), 1.0);
}
