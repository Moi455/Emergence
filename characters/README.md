# Personnages d'Emergence : villageois en style voxel

Générateur de villageois médiévaux-fantastiques, riggés, à vêtements interchangeables. Tout part d'une graine : la même graine donne toujours le même villageois.

Depuis la version 2 du générateur, ce n'est plus du voxel strict mais un **style voxel** : une forme générale en cubes de 2 cm, dont les marches deviennent des pentes et des facettes là où la matière le demande (nez en biseau, pommettes, mains), peinte avec des pixels de 1 cm, et chaque pixel a le relief d'un petit cube. L'état du travail et l'écart restant avec les images de référence sont dans `ETAT.md`.

## Ce qu'il y a ici

| Chemin | Contenu |
|---|---|
| `gen/` | Le générateur (JavaScript sans dépendance, tourne dans Node et dans le navigateur) |
| `data/catalog.json` | Données de contenu : 52 vêtements, teintures et leur coût, 5 villages, 28 métiers et leurs tenues |
| `data/villagers.json` | Les 600 villageois (120 par village) : apparence, métier, richesse, garde-robe, tenues (format interne du générateur) |
| `data/fiches.json` | Les mêmes 600 villageois au format de fiche du contrat d'interfaces (§ 5) : emplacements du contrat, couche, zones couvertes, identifiants de village |
| `tools/fiches.mjs` | Régénère `fiches.json` à partir de `villagers.json` (4 min sur 4 cœurs en 4 tranches) |
| `tools/export.mjs` | Exporte un villageois en `.glb` : `node tools/export.mjs <graine> <dossier> [village]` |
| `tools/batch.mjs` | Régénère `villagers.json` |
| `tools/thumbs.mjs` | Rend les vignettes de la galerie (Chromium sans écran) |
| `samples/` | Huit `.glb` d'exemple pour l'import dans Godot (24 animations, 8 tenues, 4 LOD) |
| `runtime/webgl2.js` | Module sans dépendance pour un moteur WebGL2 brut (le village jouable) : génère, anime et dessine un villageois |
| `runtime/demo.html` | Démo de ce module (`?clip=walk,eat&ids=5,120&outfit=court`) |
| `index.html` | La galerie (aussi publiée en ligne) |

## Comment c'est construit

1. **Apparence** (`villager.js`) : sexe, âge (enfant, adolescent, adulte, ancien), taille, corpulence, musculature, teint (9 tons), cheveux (12 couleurs, 12 coupes), barbe, yeux, nez, bouche, sourcils, taches de rousseur, cicatrices.
2. **Squelette** (`body.js`) : 61 os aux noms du `SkeletonProfileHumanoid` de Godot, conformes au § 3 du contrat d'interfaces : Root, Hips, Spine, Chest, UpperChest, Neck, Head, LeftEye, RightEye, Jaw, épaules, bras, mains, pouce et quatre doigts à trois phalanges, jambes, pieds, orteils, et les points d'attache sans poids `RightHandProp`, `LeftHandProp` (outil tenu, manche sur +Y local), `BackProp`, `HipProp`, `HeadProp`. Les 53 premiers os portent des poids ; yeux, mâchoire et points d'attache viennent après. Pose de liaison bras le long du corps, paumes vers les cuisses, personnage tourné vers +Z, 1 unité = 1 m, Y vers le haut.
3. **Corps** : un champ de distance fait de primitives attachées aux os, voxelisé en voxels fins de **1 cm** (environ 170 voxels de haut pour un adulte). Proportions proches du réel : tête d'environ 1/7 de la taille.
4. **Visage, mains, cheveux, barbe** (`head.js`) : yeux, sourcils, bouche, rides et taches peints au voxel fin ; le nez et les oreilles sont sculptés en blocs entiers de 2 cm (le nez sort d'un bloc puis de deux, le biseau en fait un coin) ; plis entre les doigts ; cheveux en mèches avec reflets.
5. **Vêtements** (`garments.js`, `wardrobe.js`) : chaque vêtement est un **enregistrement de données** porté par le PNJ (type, matière, couleurs, motif, paramètres, usure, graine). Sa géométrie est recalculée pour le corps qui le porte, donc n'importe quel vêtement va à n'importe quel villageois. Les couches se superposent dans l'ordre : jambes, pieds, chemise, vêtement de dessus, gilet, gants, ceinture, tablier, sac, cape, coiffe, bijou.
6. **Maillage en style voxel** (`stylemesh.js`) : les voxels fins sont regroupés en blocs de 2 cm, posés sur le personnage (le milieu du visage est le milieu d'un bloc, le sol, la ligne des sourcils et le plan du visage sont des limites de blocs). Une face par face de bloc visible ; chaque coin est tiré vers la surface comme un *surface net*, d'autant plus que la matière est souple (peau 0,9, fourrure 0,6, tissu 0,45, cuir 0,4, bois 0,3, cheveux 0,2, métal 0,15) : les marches de la peau deviennent des pentes et des triangles, les cheveux gardent leurs marches de cubes. Chaque face de bloc est peinte avec 2 × 2 pixels pris sur les voxels fins (le premier voxel du même membre rencontré, avec son occlusion ambiante). Une face entre deux membres qui bougent séparément est gardée, pour qu'un bras levé ne montre jamais une coque creuse. Le maillage voxel strict d'avant reste disponible (`meshOutfit(base, grille, lod, { strict: true })`).
7. **Relief de petit cube** (`bevel.js`) : chaque pixel de l'atlas est une face de voxel ; une carte de normales répétée une fois par pixel lui donne un biseau, ce qui fait lire chaque voxel comme un petit cube (l'aspect tricoté des vêtements de l'image de référence), sans un triangle de plus. Dans la galerie c'est une tuile 16 × 16 répétée, dans `runtime/webgl2.js` c'est calculé dans le shader (et effacé au loin), dans le `.glb` c'est une carte cuite à 4 pixels par voxel, la même pour tous les atlas d'une taille donnée.
8. **Animations** (`anim.js`) : les 24 clips de priorité 1 du § 7 du contrat, à 30 images/s, adaptés à l'âge (voir plus bas). `sampleClip` et `skinMatrices` évaluent une pose sans moteur.
9. **Export** (`gltf.js`) : glTF 2.0 binaire valide (0 erreur au validateur Khronos), sans extension. 16 avertissements : la carte de normales demande un espace tangent que le fichier ne fournit pas (le moteur le calcule à l'import).

## Tenues

Chaque villageois a les huit tenues du contrat : `everyday` (quotidien), `work` (travail, selon le métier), `travel` (voyage : cape, bottes, besace), `festive` (fête), `mourning` (deuil : la tenue de tous les jours refaite en teintes sombres, tête couverte), `cold` (froid), `court` (apparat : les plus beaux habits que le foyer peut s'offrir), `night` (nuit). Une tenue est une liste d'identifiants de vêtements ; un même vêtement sert dans plusieurs tenues. Changer de tenue en jeu = changer la liste portée.

## Format du .glb

- Un `Skeleton` (skin) partagé, un nœud de maillage par tenue et par niveau de détail : `Outfit_work` (blocs de 2 cm), `Outfit_work_LOD1` (4 cm), `_LOD2` (8 cm), `_LOD3` (16 cm). Les `extras` de chaque nœud donnent `outfit`, `lod`, `voxel_m` (taille des blocs), `texel_m` (taille d'un pixel peint) et la liste des vêtements.
- À l'import dans Godot, tous les maillages sont visibles : le jeu n'en affiche qu'un (la tenue portée, au LOD voulu) en basculant `visible`.
- Pas de normales stockées : le glTF impose alors des normales plates, ce qui garde les facettes et les triangles du style. LOD0 et LOD1 ont une `normalTexture` (le biseau de chaque voxel).
- 24 animations nommées comme au § 7 du contrat. Les `extras` de chaque animation donnent `loop` (boucle ou une fois), `fps` (30), `speed_mps` (vitesse de référence des déplacements, faits sur place) et `events` (`impact`, `grab`, `release`, `footstep_l`, `footstep_r`, en secondes depuis le début du clip). Les déplacements de la racine passent par la translation de `Hips`.

## Animations

| Famille | Clips |
|---|---|
| Déplacement | `idle`, `walk`, `run`, `carry_idle`, `carry_walk` |
| Corps | `sit_down`, `sit_idle`, `stand_up`, `sleep`, `eat`, `drink` |
| Travail | `swing_pickaxe`, `swing_axe`, `dig_shovel`, `kneel_work` |
| Objets | `pick_up`, `put_down`, `give` |
| Parole | `talk_calm`, `wave`, `nod`, `shake_head` |
| Conflit | `hit_react`, `fall_down` |

Les clips joués une fois (`sit_down`, `stand_up`, `pick_up`, `put_down`, `give`, `nod`, `shake_head`, `hit_react`, `fall_down`) commencent et finissent sur une pose compatible avec `idle`, sauf `sit_down` (finit assis), `stand_up` (part d'assis) et `fall_down` (finit couché comme `sleep`). Limite connue : une jupe longue reste une cloche raide en position assise, car le skinning linéaire ne sait pas draper ; il faudra un peu de tissu simulé dans le moteur.

## Coûts mesurés (adulte, tenue de travail, 29 villageois)

| Niveau | Blocs | Triangles | Atlas |
|---|---|---|---|
| LOD0 | 2 cm, pixels de 1 cm | 22 300 en moyenne (de 18 400 à 29 900) | 256 × 256 à 512 × 256 |
| LOD1 | 4 cm, pixels de 2 cm | 5 200 en moyenne (de 4 300 à 6 700) | 128 à 256 px |
| LOD2 | 8 cm | 1 250 en moyenne | 64 px |
| LOD3 | 16 cm | 260 en moyenne | 64 px |

Le contrat v0.2 fixe 6 000 / 2 000 / 600 triangles : LOD1, LOD2 et LOD3 y tiennent. LOD0 sert de près (moins de 4 m environ) ; la proposition faite au fil du moteur est de choisir le niveau par la distance.

Temps de génération dans Node (un cœur) : 0,25 s pour le corps, 0,6 s par tenue, 0,25 s pour le maillage LOD0. Un `.glb` complet (8 tenues, 4 LOD, 24 animations) pèse environ 20 Mo, d'où le choix de ne livrer que des exemples : le jeu stocke la graine et la garde-robe (environ 5 Ko par PNJ) et produit le maillage au chargement.

## Dans un moteur WebGL2 brut (village jouable)

```js
import { makeVillager, changeOutfit, uploadVillager, villagerProgram } from '../personnages/runtime/webgl2.js';
const cat = await (await fetch('../personnages/data/catalog.json')).json();
const rec = (await (await fetch('../personnages/data/villagers.json')).json()).villagers[120];
const v = makeVillager(rec.seed, cat, { village: rec.village, outfit: 'work', lod: 1 });
const gv = uploadVillager(gl, v), prog = villagerProgram(gl);
// à chaque image : gv.pose('walk', t); gv.draw(prog, viewProj, model, sunDir);
// changer de tenue : changeOutfit(v, cat, 'festive', 1); puis gv.dispose() et uploadVillager à nouveau
```

Le vertex shader reçoit `uniform mat4 uBones[53]` (les os qui portent des poids) et les attributs 0 position, 1 UV, 2 os (`uvec4`), 3 poids. Les poses sont calculées sur le CPU (une soixantaine de quaternions par villageois et par image) ; `VILLAGER_VS` peut être recopié dans le shader du moteur. Il faut servir le dossier en http (modules ES).

## Pistes pour la suite

- Porter `gen/` dans le cœur C++ (les modules JS servent d'oracle, comme le pipeline PNJ en Python) : la génération n'utilise que des entiers et + − × ÷ √, donc elle est reproductible bit à bit.
- Vêtements déchirés, brûlés, mouillés : ce sont des opérations sur les voxels de la couche du vêtement.
- Expressions du visage (paupières, bouche) par échange de quelques voxels peints.
