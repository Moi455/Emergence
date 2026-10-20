// Struct `Frame` du ciel, RÉÉCRITE pour le moteur (docs/19b L03) : seuls les champs lus par les shaders de
// web-ocean y figurent, tous en vec4 (pas de piège d'alignement des vec3 dans les uniformes).
// Disposition miroir de `sky::gpu::SkyFrame` (Rust) : 11 vec4, 176 octets.
struct Frame {
  camPos:   vec4f,     // xyz mètres, w = temps (s)
  camRight: vec4f,     // xyz * tan(fovX/2)
  camUp:    vec4f,     // xyz * tan(fovY/2)
  camFwd:   vec4f,     // xyz
  sunDir:   vec4f,     // xyz vers le soleil (y haut), w = échelle d'éclairement solaire
  screen:   vec4f,     // largeur, hauteur, 1/largeur, 1/hauteur
  post:     vec4f,     // x = exposition, y = bloom, z = numéro d'image, w = inutilisé
  atmo:     vec4f,     // x = multiplicateur de Mie (turbidité), y = altitude caméra (km), z = voile haut, w = densité du voile
  waterCol: vec4f,     // rgb = couleur du corps d'eau (réservé à l'eau, L21), w inutilisé
  fogExt:   vec4f,     // rgb = extinction par mètre au niveau du sol (Rayleigh + Mie), w = plancher de brume
  cloudP:   vec4f,     // altitude (km), couverture, densité optique, temps de vent
};
