// Quads du maillage (L33) : un quad = 12 octets (3 mots), quatre sommets (bande de triangles) reconstruits ici (aucun tampon de sommets ni
// d'indices). Miroir de `em_mesh::Quad` : voir `crates/em_mesh/src/quad.rs` pour la disposition des bits.
// Groupe 3 : origine du chunk (uniforme à décalage dynamique, mètres relatifs à la caméra ; w = taille d'un voxel en
// mètres) et tampon des quads.
struct ChunkU {
  origin: vec4<f32>,
};
@group(3) @binding(0) var<uniform> CU: ChunkU;
@group(3) @binding(1) var<storage, read> QUADS: array<u32>;

// Facteur d'ambiance de l'occlusion par sommet, niveaux 0 à 3 : ceux de la référence de Monsieur.
const AO_F: vec4<f32> = vec4<f32>(0.5, 0.72, 0.88, 1.0);
// Un quad se dessine en BANDE de 4 sommets (une instance par quad, pas de tampon d'indices ni de sommets). L'ordre des
// coins de la bande fixe la diagonale (arête commune des deux triangles = les sommets 1 et 2 de la bande) et
// l'enroulement : coins 0-2 si ao0 + ao2 > ao1 + ao3, sinon 1-3 ; face positive ou négative. Quatre bandes de quatre
// coins, 2 bits par coin, rangées dans un entier (aucun tableau : pas d'accès mémoire locale) :
//   + diagonale 0-2 : (1, 2, 0, 3)   + diagonale 1-3 : (2, 3, 1, 0)
//   - diagonale 0-2 : (1, 0, 2, 3)   - diagonale 1-3 : (2, 1, 3, 0)
// Les triangles sont ceux de `Quad::triangles` (essai CPU) : (v0, v1, v2) et (v2, v1, v3).
const BANDES: u32 = 0x36E11EC9u;

struct QuadVertex {
  local: vec3<f32>,   // position du sommet dans le chunk, en voxels
  face: u32,          // 0 +x, 1 -x, 2 +y, 3 -y, 4 +z, 5 -z
  w0: u32,            // mot 0 brut (épaisseur de feuillage en bits 24..31)
  w1: u32,            // mot 1 brut (couleur sRGB8 et paramètres de matière)
  foliage: u32,       // 1 pour du feuillage
  ao: f32,            // facteur d'ambiance de CE sommet
};

fn quad_vertex(qi: u32, vi: u32) -> QuadVertex {
  let w0 = QUADS[qi * 3u];
  let w1 = QUADS[qi * 3u + 1u];
  let w2 = QUADS[qi * 3u + 2u];
  var p = vec3<f32>(f32(w0 & 127u), f32((w0 >> 7u) & 127u), f32((w0 >> 14u) & 127u));
  let face = (w0 >> 21u) & 7u;
  let axe = face >> 1u;
  let ta = (axe + 1u) % 3u;
  let tb = (axe + 2u) % 3u;
  let larg = f32((w2 & 63u) + 1u);
  let haut = f32(((w2 >> 6u) & 63u) + 1u);
  let a0 = (w2 >> 12u) & 3u;
  let a1 = (w2 >> 14u) & 3u;
  let a2 = (w2 >> 16u) & 3u;
  let a3 = (w2 >> 18u) & 3u;
  let diag02 = (a0 + a2) > (a1 + a3);
  // bande : 8 bits par (signe, diagonale), 2 bits par sommet
  let choix = (face & 1u) * 2u + select(1u, 0u, diag02);
  let k = (BANDES >> (choix * 8u + vi * 2u)) & 3u;
  let su = select(0.0, 1.0, k == 1u || k == 2u);
  let sv = select(0.0, 1.0, k >= 2u);
  p[ta] = p[ta] + su * larg;
  p[tb] = p[tb] + sv * haut;
  var o: QuadVertex;
  o.local = p;
  o.face = face;
  o.w0 = w0;
  o.w1 = w1;
  o.foliage = (w2 >> 20u) & 1u;
  o.ao = AO_F[(w2 >> (12u + 2u * k)) & 3u];
  return o;
}
