# Générateur de maisons voxel — README technique (intégration moteur Rust / Godot)

Cible : le moteur d'Emergence (Rust, hôte Godot, iGPU ou ≤ 25 % d'une Quadro RTX 3000, voxels de 5 cm texturés).
**Ce paquet ne contient pas de moteur Rust.** Il contient le *générateur* (JS, déterministe), un *exporteur binaire*
et la spécification de ce qu'un rendu Rust doit en faire. Le rendu WebGL de `maison-voxel.html` n'est qu'une démo de référence visuelle.

## 1. Contenu
| Fichier | Rôle |
|---|---|
| `gen_core.js` | Générateur (`derive`, `build`, `meshify`). Extrait tel quel de la page, aucune dépendance. Node ≥ 16. |
| `export_house.js` | `node export_house.js <graine> [sortie]` → `.vxh` (grille) + `.json` (métadonnées). |
| `sample_gravit.*`, `sample_a.*` | Deux maisons exportées (graines `gravit` et `a`). |

Le générateur est en JS ; il faut soit l'exécuter hors-ligne (cuisson → `.vxh`), soit le porter en Rust.
Le portage est ~600 lignes denses, déterministe à la graine (PRNG `mul`/`hs`/`hh` : entiers 32 bits, à reproduire à l'identique avec `wrapping_mul`).
Recommandation : cuire hors-ligne une bibliothèque de graines, puis charger les `.vxh`. Temps de génération mesuré : 0,4–0,7 s par maison (Node, une maison).

## 2. Grille
- Voxel = 0,05 m (`voxel_m`). Axes : x, z horizontaux, **y vertical**. Index : `i = (y*nz + z)*nx + x` (x varie le plus vite).
- Taille type : 260–295 × 165–240 × 245–305 (marge de 64 voxels autour de la maison). 0,75–1,2 M voxels pleins.
- `ground_layers = 6` : le sol de l'herbe est à y = 5, le niveau 0 des murs commence à y = 6. Le vide hors grille = air.
- Dimensions utiles de la maison : `size_vox` (w, d, h). Centre : `center_xz`. Apparition du joueur : `spawn` (x, y, z en voxels).
- Hauteur d'étage : 54 voxels (2,70 m). Épaisseur de mur : 6 (30 cm). Porte intérieure : 14×36 (70×180 cm). Escalier : 14 marches.

## 3. Format `.vxh`
```
0   4  "VXH1"
4   4  u32 nx   8 u32 ny   12 u32 nz   (little endian)
16  4  f32 voxel_m (=0.05)   20 u32 ground_layers (=6)
24  8  réservé
32  …  zlib (deflate) de :  [u16 × N couleurs RGB565] [u8 × N matériau] [u8 × N drapeaux]    N = nx*ny*nz
```
- Couleur : RGB565 (`r5<<11 | g6<<5 | b5`), **0 = vide**. Invariant testé : `couleur≠0 ⇔ matériau≠0`.
- Matériau (`MT`) : 1 pierre/métal · 2 bois · 3 plâtre · 4 végétal/sol · 5 toit. Sert à choisir texture/rugosité, pas la couleur.
- Drapeaux : bit0 émissif (braises, lampes, lanterne) · bit1 verre (peut être vide, voir §6) · bit2 face intérieure (voxel adjacent à un volume habité : éclairage ambiant plus faible, et seulement les lumières intérieures) · bit3 « mou » (herbe/fleurs : pas de collision).
- Taille mesurée après deflate : 0,9–1,6 Mo par maison. Pour un jeu, découper en chunks 32³–48³ et ne stocker que les non-vides.

## 4. Métadonnées `.json`
- `doors[]` : `kind` ('ext'|'int'), `storey`, `hinge` [x,z] (coin de la charnière, en coordonnées de grille, flottants), `y`, `u` [x,z] (vecteur unitaire le long du vantail fermé, charnière → bord libre), `n` [x,z] (sens d'ouverture : la porte pivote vers `n`), `w`, `h`, `arch`, `color`, `cells[]` (indices de grille **vides** occupés par la baie : à rendre non-collisionnants quand la porte est ouverte, bloquants quand elle est fermée).
- `windows[]` : même principe, avec deux `leaves[]` (battants) chacun avec sa charnière et son sens.
- `lights[]` : position en voxels, couleur sRGB, intensité, rayon (m), `exterior` (true = n'éclaire que l'extérieur).
- `rooms[]` : `{id, s, type, n}` ; types : hall, living, kitchen, bedroom, study, store. `counts` : meubles, lits, cuisines (invariants : ≥ 1 lit et ≥ 1 cuisine par maison).
- Garanties vérifiées par tests sur le code d'origine : toutes les pièces connectées par des portes, aucun mur d'épaisseur 0 dans les angles, pas de poches inaccessibles, conduit de cheminée creux.

## 5. Ce que le moteur Rust doit faire (ce que la démo fait, en moins coûteux)
**Maillage — point critique de performance.** Mon `meshify` fait un maillage *naïf par face visible* : 0,9–1,5 M triangles par maison (1,8–2,9 M sommets), AO par sommet. C'est **inacceptable** pour votre cible iGPU. Il faut :
1. *Greedy meshing* par chunk et par (matériau, couleur quantifiée) ou, mieux, **grille de couleurs en texture 3D / atlas** avec quads fusionnés : ordre de grandeur attendu ×10 à ×30 de réduction sur les murs plats ; la pierre irrégulière réduit moins (les couleurs varient par voxel) → soit on garde un quad par face avec AO, soit on stocke la couleur par texel dans un atlas de chunk. À mesurer, je n'ai pas de chiffre.
2. Remaillage incrémental par chunk à la destruction (déjà le schéma de la démo : chunks de 48, lots 2×2 sur la face visée).
3. LOD : au-delà de ~200 m, remplacer la maison par un proxy (voir §7). Une maison voxel 5 cm n'a aucun intérêt à 200 m.
4. Instancier les décors répétés (tuiles de meubles, fleurs) si le coût de draw dépasse le budget.

**Ombrage/texture (spécification de ce que fait la démo, à porter en WGSL/GLSL)** :
- Couleur de sommet sRGB→linéaire. Bruit de valeur 3D à 3 octaves (fréquences ≈ 2,3 / 7 / 19 par voxel) multiplie la couleur (amplitude par matériau : pierre .55, bois .42, plâtre .34, végétal .5, toit .4) → casse la régularité « Minecraft ».
- Mousse : teinte verte mélangée là où un bruit basse fréquence (~0,55/voxel) dépasse un seuil, sur pierre et toit. Salissure plus sombre vers le bas des murs.
- Relief : normale perturbée par dérivées d'une hauteur (luminosité + bruit + biseau d'arête), pente limitée, fondu avec la distance (nul au-delà de ~1 m). Biseau d'arête de voxel léger.
- AO par sommet (4 niveaux 0,5/0,72/0,88/1) appliqué à l'éclairage indirect ; faces intérieures atténuées ×0,45.
- Éclairage : soleil directionnel bas et chaud + hémisphère froide ; lumières ponctuelles *séparées* intérieur/extérieur (une lumière intérieure ne touche jamais un sommet extérieur et inversement : c'est ce qui supprime les fuites de lumière à travers les murs).
- Ombres : shadow map du soleil, `shadowSide = Front` (évite les fuites). Brume exponentielle teintée par la direction du soleil, appliquée avant tonemapping. Tonemapping ACES.
- Émissif : multiplié ×3,2 (HDR) pour le bloom.
- Je n'ai **pas** mesuré ces shaders sur GPU réel (test uniquement sous SwiftShader/CPU). Le coût réel sur iGPU est inconnu ; la couche bruit+relief+brume est faite pour être désactivable par niveau de qualité (3 niveaux dans la démo).

**Physique** : collision = boîte joueur (demi-largeur 3,4 voxels ≈ 17 cm, hauteur 33 voxels ≈ 1,65 m, œil à 31 voxels, marche franchissable ≤ 4 voxels = 20 cm) contre la grille ; ignorer les voxels `mou` et les `cells` d'une porte ouverte. Visée par DDA voxel (portée 38 voxels pour F/ouvrir, ~110 pour casser).

## 6. À réimplémenter côté moteur (non fourni par le générateur)
- **Vantaux de portes et de fenêtres** : le générateur ne produit que les baies vides (`cells`) et la géométrie de charnière. Les planches de la porte, ses ferrures, le cadre et les vitres des fenêtres sont fabriqués par le *rendu* de la démo (fonction `leafMesh`, dans `maison-voxel.html`). Il faut les reproduire (mini-grille de voxels par vantail pivotée autour de `hinge`, angle ±90° vers `n`, durée d'animation libre). Verre : sombre et réfléchissant, ou clair et émissif si `lit`.
- Arbres, forêt, ciel, terrain : **hors générateur** ; les arbres viennent de votre `voxel_tree.py` (déjà dans votre archive).
- Le plan `GL` (verre dans la grille) peut être vide ; ne pas en dépendre.

## 7. Intégration Godot + Rust (proposition, non codée)
1. Cuisson hors-ligne : `node export_house.js <graine>` pour N graines → `.vxh`/`.json` dans le dépôt de ressources.
2. Crate Rust `house_vox` : parse `.vxh`, découpe en chunks, greedy meshing, expose via GDExtension un `Node3D` par maison (mesh par chunk + `ArrayMesh`), plus API `break_voxels(x,y,z,face)` (lot 2×2) qui remaille le chunk.
3. Placement dans la map : la maison est posée à `y_sol`, la grille couvre ~15 m × 15 m ; aplanir le terrain sous l'emprise (`size_vox` × 5 cm) pour éviter qu'elle flotte ou s'enfonce. Le sol herbeux de la grille (6 couches) doit se raccorder au terrain du monde — cette jonction n'est pas résolue ici.
4. LOD : proxy = boîte + toit en 2 pentes (déductible de `params.roof`, `size_vox`) au-delà de ~50–100 m.

## 8. Limites connues (franchement)
- Rendu de la démo : proche du style voulu en ambiance, mais **de près ce sont encore des cubes de 5 cm** ; toits peu lisibles ; ne l'ai jamais vu sur GPU réel. Ne pas le prendre pour le niveau de qualité final.
- Maillage naïf = 1–1,5 M triangles par maison : le portage Rust doit commencer par là, sinon la cible iGPU est hors de portée.
- Le texturage « voxel texturé » exigé par Emergence n'est ici que du bruit procédural + couleur par voxel ; pas d'atlas de textures. Si vous voulez de vraies textures, il faut décider de l'UV (triplanar par `MT` est l'option la plus simple).
- Générateur testé en Node uniquement ; aucun test d'intégration Rust/Godot n'existe.
