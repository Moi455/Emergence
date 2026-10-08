# Prototype « Village voxel jouable »

Page jouable : https://claude.ai/artifact/7a6jR7fZHyJAh3shh4uToq (WebGL2, s'ouvre dans le navigateur). Le moteur cible reste Godot 4 + cœur C++ ; ce prototype sert à mesurer, sur le GPU de Monsieur, l'esthétique, le poids et la tenue du rendu à 2 cm.

## Ce qui tourne
- Le kit Quaternius Medieval Village MegaKit (CC0) : 47 pièces voxélisées à 2 cm par le convertisseur des devs (`tools/voxelizer`, utilisé tel quel depuis une copie). Les murs du kit, qui ne sont que deux feuilles, sont remplis par le packer : la destruction révèle donc de la matière.
- Un générateur de plans déterministe (graine 1337) qui assemble ces pièces : 26 maisons de 2 ou 3 étages (4×4 à 6×8 m), une tour, une place pavée, des rues, des clôtures, des caisses et une charrette, soit environ 2 000 instances.
- 4 arbres procéduraux, générés depuis la graine et placés en environ 70 exemplaires.
- Un terrain procédural 327 × 327 m. Sa couleur vient du bruit, sans aucun stockage, et seuls les voxels creusés sont stockés.
- Le déplacement à pied : collisions au voxel près, marches franchies jusqu'à 40 cm, saut, course. Un mode vol existe aussi.
- La destruction : sphère de 8 à 48 cm, modulée par la dureté (pierre et métal résistent, terre et torchis cèdent), avec des débris. Copie à l'écriture au niveau de la brique 8³ : seule l'instance touchée reçoit ses propres briques.

## Architecture appliquée (06_architecture_expliquee.md)
- VoxelId sur 16 bits = classe (9) | teinte (7). Briques 8³ uniformes ou à palette locale de 15 couleurs (index 4 bits). Voxels enfouis ramenés à une teinte par classe.
- Micro-tracé, anneau proche (jusqu'à 25 m) : le GPU rastérise les faces des micro-briques de 8 cm et le pixel shader trace les voxels de 2 cm (DDA, 40 pas au plus), en écrivant la profondeur.
- Anneaux suivants : raster 8 cm jusqu'à 40 m, 16 cm jusqu'à 75 m, 32 cm au-delà. Le terrain est découpé en quadtree, de 2 cm à 64 cm par colonne.
- Modules stockés une fois et dessinés par instanciation. Ombres solaires 2048², occlusion ambiante calculée au voxel dans le shader, ciel procédural.

## Mesures (machine de build, GPU logiciel SwiftShader : les images/s ne sont pas significatives ici)
| Mesure | Valeur |
|---|---|
| Téléchargement | 6,3 Mo de données (8,4 Mo en base64 sur la page) + 100 Ko de code |
| Données décompressées | 23 Mo |
| Voxels uniques stockés | 9,5 M pour le kit, 12 M avec les arbres |
| Voxels du village (instances) | 230 M |
| Briques mixtes | 84 k pour le kit, 124 k avec les arbres |
| Mémoire GPU | ~170 Mo (atlas 43 Mo, maillages ~100 Mo, ombre 16 Mo) |
| Mémoire voxels CPU | ~41 Mo |
| Toit 6×8 en maillage glouton 2 cm | 1 133 557 quads |
| Le même toit en micro-tracé (faces de 8 cm) | 63 850 quads (×17,7 de moins) |
| Kit entier, faces au plus près | 4,4 M quads en glouton contre 251 k en micro-tracé |
| Chargement | 4 à 8 s en GPU logiciel, plus avec les arbres |

Les vraies images/s se mesurent avec la touche **B** (tour du village de 20 s : moyenne, 95e et 99e centiles, temps GPU si le navigateur le permet, nom du GPU utilisé). La page demande le GPU basse consommation (`powerPreference: 'low-power'`), donc normalement l'iGPU.

## Fichiers
- `jeu/` : la page (`index.html`, `engine.js`, `shared.js`) et les données (`world.bin` en binaire gzip, `world.b64.txt` pour l'hébergement). En local : `python3 -m http.server` dans `jeu/`, puis ouvrir `index.html`.
- `outils/vox_one.py` : voxélise une pièce avec le convertisseur des devs. `outils/pack_world.py` : packer VXB2 (remplissage des murs, palettes, briques). `outils/world_stats.json` : statistiques par pièce. `shots.js` : captures automatiques.
- `captures/` : vues aérienne, de rue, mur au micro-tracé et destruction.

## À faire remonter dans le projet unifié
- Le format VXB2 (briques 8³ et palette locale 4 bits) et le remplissage des murs ouverts, à porter dans `tools/voxelizer` et dans le décodeur C++.
- La mesure du micro-tracé, qui confirme le choix 5.

## Limites connues
- Pas encore d'effondrement : un morceau détaché reste en l'air. Pas d'eau ni de feu.
- Les ombres sont calculées sur les faces de 8 cm : contour un peu épais.
- Les intérieurs des maisons sont vides, sans escaliers ni meubles.
- Hors de l'anneau proche, les parties creusées des instances lointaines restent dessinées au micro-tracé (correct, mais plus coûteux).
