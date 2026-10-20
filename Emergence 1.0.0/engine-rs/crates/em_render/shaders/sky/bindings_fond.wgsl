// Liaisons du fond de ciel (mêmes noms que web-ocean : F, transLUT, skyLUT, sampC).
@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var transLUT: texture_2d<f32>;
@group(0) @binding(2) var skyLUT: texture_2d<f32>;
@group(0) @binding(3) var sampC: sampler;
// Étage 2 seulement : ciel et nuages déjà calculés en demi-résolution (rgb = radiance, a = transmittance des nuages).
@group(0) @binding(4) var skyHalf: texture_2d<f32>;
// Étage 2 seulement : pentes des trois crêtes par azimut (LUT 1D de 4096 texels, rgb = couches 0 à 2).
@group(0) @binding(5) var ridgeLUT: texture_2d<f32>;
