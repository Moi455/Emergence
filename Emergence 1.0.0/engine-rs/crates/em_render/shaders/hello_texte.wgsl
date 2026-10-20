// Surimpression de texte : une texture R8 (255 = lettre, 128 = ombre portée), échantillonnage au plus proche.

struct Rect {
    // x0, y0, x1, y1 en coordonnées normalisées de l'écran (y vers le haut)
    r: vec4<f32>,
};

@group(0) @binding(0) var<uniform> rect: Rect;
@group(0) @binding(1) var texte: texture_2d<f32>;
@group(0) @binding(2) var echant: sampler;

struct Sortie {
    @builtin(position) pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs(@builtin(vertex_index) i: u32) -> Sortie {
    let c = vec2<f32>(f32(i & 1u), f32((i >> 1u) & 1u));
    var o: Sortie;
    o.pos = vec4<f32>(mix(rect.r.x, rect.r.z, c.x), mix(rect.r.y, rect.r.w, c.y), 0.0, 1.0);
    o.uv = vec2<f32>(c.x, 1.0 - c.y);
    return o;
}

@fragment
fn fs(e: Sortie) -> @location(0) vec4<f32> {
    let v = textureSample(texte, echant, e.uv).r;
    if (v > 0.75) {
        return vec4<f32>(1.0, 0.97, 0.85, 1.0);
    }
    if (v > 0.25) {
        return vec4<f32>(0.0, 0.0, 0.0, 0.75);
    }
    discard;
}
