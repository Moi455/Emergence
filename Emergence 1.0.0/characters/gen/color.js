// sRGB colors as integers 0xRRGGBB. All math is plain arithmetic (deterministic).

export function hex(s) { return parseInt(s.replace('#', ''), 16); }
export function rgb(r, g, b) {
  r = r < 0 ? 0 : r > 255 ? 255 : Math.round(r);
  g = g < 0 ? 0 : g > 255 ? 255 : Math.round(g);
  b = b < 0 ? 0 : b > 255 ? 255 : Math.round(b);
  return (r << 16) | (g << 8) | b;
}
export const R = c => (c >> 16) & 255, G = c => (c >> 8) & 255, B = c => c & 255;
export function mix(a, b, t) {
  return rgb(R(a) + (R(b) - R(a)) * t, G(a) + (G(b) - G(a)) * t, B(a) + (B(b) - B(a)) * t);
}
export function mul(c, k) { return rgb(R(c) * k, G(c) * k, B(c) * k); }
// shade with a slight hue shift: darker -> cooler/more saturated, lighter -> warmer (pixel-art ramp)
export function ramp(c, k) {
  if (k < 1) {
    const d = 1 - k;
    return rgb(R(c) * (k - d * 0.08), G(c) * k, B(c) * (k + d * 0.18));
  }
  const d = k - 1;
  return rgb(R(c) * k + 255 * d * 0.12, G(c) * k + 255 * d * 0.08, B(c) * (k - d * 0.15));
}
export function lum(c) { return (R(c) * 0.299 + G(c) * 0.587 + B(c) * 0.114) / 255; }
export function desat(c, t) { const l = lum(c) * 255; return mix(c, rgb(l, l, l), t); }
export function tint(c, t, k) { return mix(c, t, k); }
