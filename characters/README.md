# Personnages d'Emergence : villageois en pseudo-voxels

Générateur de villageois médiévaux-fantastiques, riggés, à vêtements interchangeables. Tout part d'une graine : la même graine donne toujours le même villageois.

## Ce qu'il y a ici

| Chemin | Contenu |
|---|---|
| `gen/` | Le générateur (JavaScript sans dépendance, tourne dans Node et dans le navigateur) |
| `data/catalog.json` | Données de contenu : 52 vêtements, teintures et leur coût, 5 villages, 28 métiers et leurs tenues |
| `data/villagers.json` | Les 600 villageois (120 par village) : apparence, métier, richesse, garde-robe, tenues |
| `tools/export.mjs` | Exporte un villageois en `.glb` : `node tools/export.mjs <graine> <dossier> [village]` |
| `tools/batch.mjs` | Régénère `villagers.json` |
| `tools/thumbs.mjs` | Rend les vignettes de la galerie (Chromium sans écran) |
| `samples/` | Huit `.glb` d'exemple pour l'import dans Godot (4 animations, 5 tenues, 4 LOD) |
| `runtime/webgl2.js` | Module sans dépendance pour un moteur WebGL2 brut (le village jouable) : génère, anime et dessine un villageois |
| `runtime/demo.html` | Démo de ce module : quatre villageois en repos, marche, travail et parole |
| `index.html` | La galerie (aussi publiée en ligne) |

## Comment c'est construit

1. **Apparence** (`villager.js`) : sexe, âge (enfant, adolescent, adulte, ancien), taille, corpulence, musculature, teint (9 tons), cheveux (12 couleurs, 12 coupes), barbe, yeux, nez, bouche, sourcils, taches de rousseur, cicatrices.
2. **Squelette** (`body.js`) : 43 os aux noms du `SkeletonProfileHumanoid` de Godot (Hips, Spine, Chest, UpperChest, Neck, Head, épaules, bras, mains, pouce et quatre doigts à deux phalanges, jambes, pieds, orteils), plus un os Root. Pose de liaison bras le long du corps, paumes vers les cuisses, personnage tourné vers +Z, 1 unité = 1 m, Y vers le haut.
3. **Corps** : un champ de distance fait de primitives attachées aux os, voxelisé en voxels de **1,25 cm** (environ 135 voxels de haut pour un adulte, la densité de l'image de référence). Proportions stylisées : tête d'environ 1/5 de la taille, mains et pieds un peu grands.
4. **Visage, mains, cheveux, barbe** (`head.js`) : orbites creusées, sourcils en relief, nez de 1 à 3 voxels de saillie, bouche, oreilles, rides, plis entre les doigts ; cheveux en mèches avec reflets.
5. **Vêtements** (`garments.js`, `wardrobe.js`) : chaque vêtement est un **enregistrement de données** porté par le PNJ (type, matière, couleurs, motif, paramètres, usure, graine). Sa géométrie est recalculée pour le corps qui le porte, donc n'importe quel vêtement va à n'importe quel villageois. Les couches se superposent dans l'ordre : jambes, pieds, chemise, vêtement de dessus, gilet, gants, ceinture, tablier, sac, cape, coiffe, bijou.
6. **Maillage** (`mesh.js`) : faces visibles seulement (le corps caché sous les vêtements disparaît, mais une face entre deux membres qui bougent séparément, bras contre torse ou jambe contre jambe, est gardée pour qu'un bras levé ne montre jamais une coque creuse), occlusion ambiante cuite par face, fusion gloutonne des faces de même poids, couleurs dans un atlas de 128 à 256 px en filtrage au plus proche, poids de peau lissés aux articulations.
7. **Animations** (`anim.js`) : repos (respiration, regard), marche, travail (coup d'outil à deux mains : hache, marteau, pioche) et parole (geste de la main, hochements de tête), adaptées à l'âge. `sampleClip` et `skinMatrices` évaluent une pose sans moteur.
8. **Export** (`gltf.js`) : glTF 2.0 binaire valide (0 erreur au validateur Khronos), sans extension.

## Tenues

Chaque villageois a cinq tenues : `everyday` (quotidien), `work` (travail, selon le métier), `festival` (fête), `cold` (froid), `night` (nuit). Une tenue est une liste d'identifiants de vêtements ; un même vêtement sert dans plusieurs tenues. Changer de tenue en jeu = changer la liste portée.

## Format du .glb

- Un `Skeleton` (skin) partagé, un nœud de maillage par tenue et par niveau de détail : `Outfit_work`, `Outfit_work_LOD1` (2,5 cm), `_LOD2` (5 cm), `_LOD3` (10 cm). Les `extras` de chaque nœud donnent `outfit`, `lod`, `voxel_m` et la liste des vêtements.
- À l'import dans Godot, tous les maillages sont visibles : le jeu n'en affiche qu'un (la tenue portée, au LOD voulu) en basculant `visible`.
- Pas de normales stockées : le glTF impose alors des normales plates, c'est le rendu voxel voulu.
- Animations `idle`, `walk`, `work` et `talk` en boucle (la marche fait monter et descendre les hanches).

## Coûts mesurés (adulte, tenue de travail)

| Niveau | Voxel | Triangles | Atlas |
|---|---|---|---|
| LOD0 | 1,25 cm | 29 700 en moyenne (de 16 000 à 43 000, sur 40 villageois) | 256 px |
| LOD1 | 2,5 cm | 8 300 en moyenne | 128 px |
| LOD2 | 5 cm | 2 400 en moyenne | 64 px |
| LOD3 | 10 cm | environ 670 | 64 px |

Temps de génération dans Node (un cœur) : 0,1 à 0,2 s pour le corps, 0,2 à 0,4 s par tenue, 0,3 à 0,8 s pour le maillage LOD0. Un `.glb` complet (5 tenues, 4 LOD) pèse de 9 à 15 Mo, d'où le choix de ne livrer que des exemples : le jeu stocke la graine et la garde-robe (environ 5 Ko par PNJ) et produit le maillage au chargement.

## Dans un moteur WebGL2 brut (village jouable)

```js
import { makeVillager, changeOutfit, uploadVillager, villagerProgram } from '../personnages/runtime/webgl2.js';
const cat = await (await fetch('../personnages/data/catalog.json')).json();
const rec = (await (await fetch('../personnages/data/villagers.json')).json()).villagers[120];
const v = makeVillager(rec.seed, cat, { village: rec.village, outfit: 'work', lod: 1 });
const gv = uploadVillager(gl, v), prog = villagerProgram(gl);
// à chaque image : gv.pose('walk', t); gv.draw(prog, viewProj, model, sunDir);
// changer de tenue : changeOutfit(v, cat, 'festival', 1); puis gv.dispose() et uploadVillager à nouveau
```

Le vertex shader reçoit `uniform mat4 uBones[43]` et les attributs 0 position, 1 UV, 2 os (`uvec4`), 3 poids. Les poses sont calculées sur le CPU (environ 43 quaternions par villageois et par image) ; `VILLAGER_VS` peut être recopié dans le shader du moteur. Il faut servir le dossier en http (modules ES).

## Pistes pour la suite

- Porter `gen/` dans le cœur C++ (les modules JS servent d'oracle, comme le pipeline PNJ en Python) : la génération n'utilise que des entiers et + − × ÷ √, donc elle est reproductible bit à bit.
- Pour le LOD0, appliquer aux personnages la technique des briques à micro-tracé du document de rendu : des briques de 5 cm rastérisées avec le détail de 1,25 cm tracé dans le pixel diviseraient les triangles par 10 environ.
- Vêtements déchirés, brûlés, mouillés : ce sont des opérations sur les voxels de la couche du vêtement.
- Expressions du visage (paupières, bouche) par échange de quelques voxels peints.
