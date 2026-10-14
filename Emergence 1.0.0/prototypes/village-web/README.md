# Prototype « Village voxel jouable »

Page jouable : https://claude.ai/artifact/7a6jR7fZHyJAh3shh4uToq (WebGL2, s'ouvre dans le
navigateur). Le moteur cible reste **Godot 4 + cœur C++** ; ce prototype sert à juger, sur la
machine de Monsieur, l'esthétique, le poids et la tenue du rendu.

**Voxels de 10 cm** depuis le 9 octobre 2026 (2 cm auparavant). Le changement vient d'une
remarque de Monsieur sur le rendu « ultra fin » ; c'est aussi la taille de voxel de Teardown.
Les données à 5 cm existent toujours : ouvrir la page avec `?vs=0.05`.

## Le rendu, en une phrase
Aucune texture bitmap. L'aspect vient de propriétés par matériau, d'un grain procédural, et
surtout d'un éclairage dont la partie coûteuse est précalculée en **visibilité** et jamais en
lumière, ce qui laisse le cycle jour/nuit et la destruction entièrement libres.
Le détail est dans **RENDU.md**, qui répond point par point à la question « que peut-on sortir
de la boucle de rendu ».

- **PRT d'ordre 1 au sommet** : chaque sommet porte son ouverture au ciel et sa normale coudée,
  calculées au maillage dans un worker. Coût mémoire : zéro octet, elles tiennent dans les
  16 octets du sommet.
- **Grille de ciel du village**, 2 m, un octet par cellule, remplie par propagation au
  chargement. C'est elle qui assombrit les intérieurs et les ruelles.
- **Ciel analytique projeté sur 4 coefficients d'harmoniques sphériques**, recalculé par image
  sur le CPU (160 directions de Fibonacci, quelques microsecondes). Le cycle jour/nuit est donc
  gratuit.
- **Une shadow map solaire** de 2048², le seul élément vraiment dynamique.
- **Couleur par voxel et par pierre**, mousse, crasse dans les recoins, fenêtres éclairées le
  soir, prairies et touffes d'herbe fleuries jusqu'à 20 m : tout est décidé par voxel depuis la
  graine, rien n'est stocké.
- **Rayons de soleil** à contre-jour (passe au quart de la résolution) et feuillage traversé
  par la lumière. Étalonnage : ombres froides, lumières chaudes. La page s'ouvre à l'heure dorée.
- **Grain procédural et biseau par voxel**, atténués avec la distance pour ne pas scintiller.
- **Braziers** : le feu n'est pas voxelisé. Six lumières ponctuelles chaudes et des cubes
  émissifs, allumés quand le soleil passe sous l'horizon.
- Rendu en HDR, bloom à quart de résolution, ACES, vignette. Pas d'upscaling : il arrondit
  l'arête de voxel, qui est précisément le style.

## Ce qui tourne
- Le kit Quaternius Medieval Village MegaKit (CC0) : 47 pièces voxelisées à 10 cm par le
  convertisseur des devs (`tools/voxelizer`, utilisé tel quel). Les murs du kit, qui ne sont que
  deux feuilles, sont remplis par le packer : la destruction révèle de la matière.
- Un générateur de plan déterministe (graine 1337) : 26 maisons de 2 ou 3 étages, une tour, une
  place pavée, des rues, des clôtures, des caisses et une charrette, soit environ 2 000
  instances, plus 4 arbres procéduraux placés en 70 exemplaires.
- Un terrain procédural de 1 024 m de côté : collines, crêtes, un ruisseau, des champs en
  lanières autour du village. La couleur vient du bruit, rien n'est stocké sauf les voxels
  creusés.
- Déplacement à pied (collisions au voxel, marches, saut, course) et mode vol.
- Destruction : sphère de 9 à 55 cm modulée par la dureté, avec débris et copie à l'écriture au
  niveau de la brique 8³.
- Effondrement : local autour du coup, et par îlots sur le bâtiment entier (remplissage 4³
  depuis le sol, déclenché 350 ms après le dernier coup). Les arbres en sont exclus.
- Un étang : niveau calculé sur le point le plus bas de la berge, surface animée, pas de voxels
  d'eau.
- Des villageois animés, apportés par le fil d'intégration (`jeu/villagers.js`, branché sur
  `window.__game.addDrawHook` et `addUpdate`). Sans ce fichier la page tourne comme avant.

## Format commun VXB3 (interfaces.md § 2)
- `jeu/world.bin` (copie base64 `world.b64.txt`) est en VXB3 : classes de `materials.csv`, axes
  du monde (z nord, `z_monde = −z_glTF`, miroir pur par le plan du pivot), voxels rangés x puis
  z puis y, palette locale jusqu'à 255 couleurs, taille de voxel dans l'en-tête, crc32.
- `jeu/village.vxi` : le plan en VXI1, 2 032 instances. Les arbres ne sont pas dans VXB3 : ils
  sont générés depuis la graine.
- `outils/pack_world_vxb3.py` écrit VXB3, `outils/write_vxi.py` et `outils/dump_instances.js`
  écrivent VXI, `outils/vxb3test.js` vérifie : 9 459 268 voxels, aucune différence d'occupation.

## Mesures
Les images par seconde affichées ici n'ont **aucune valeur** : la machine de build n'a pas de
GPU et rend en logiciel (SwiftShader). Les mesures de taille, de mémoire et de précalcul, elles,
sont justes.

| Mesure | Valeur à 10 cm | Pour mémoire, à 2 cm |
|---|---|---|
| Données du village téléchargées | **378 ko** (989 ko décompressés) | 7,5 Mo (23 Mo décompressés) |
| Chargement complet | 2,4 s | 4 à 8 s |
| Modules uniques / instances | 40 / 2 032 | 47 / 2 032 |
| Voxels du village | 4 M, dont 0,2 M stockés une seule fois | 230 M, dont 9,5 M |
| Mémoire voxels CPU | **1,2 Mo** | 41 Mo |
| Mémoire GPU totale | 190 Mo (avec l'herbe) | ~170 Mo |
| dont maillages | 160 Mo | ~100 Mo |
| dont shadow map 2048² | 16 Mo | 16 Mo |
| dont **grille de ciel du village** | **781 ko** | — |
| dont cible HDR + bloom | 11,4 Mo | — |
| Villageois (fil intégration) | 48 villageois, 132 k triangles, 28,8 Mo | — |
| Triangles, vue de rue | 5,5 à 6,1 M selon la vue, dont 2,7 à 3,3 M de terrain et d'herbe | — |
| Appels de dessin | ~300 | — |
| Précalcul, maillage + PRT des modules | 3,9 s | — |
| Précalcul, terrain (1 024 m) | 19,3 s de temps worker, réparti sur 3 workers | — |
| Précalcul, grille de ciel du village | **0,65 s** | — |
| Remaillage après une destruction | 180 à 200 ms pour une maison entière, dans un worker | — |
| Rayon de l'outil de destruction | 20 à 110 cm | 4 à 22 cm |

Les temps de précalcul sont mesurés sur la machine de build, **sans GPU et avec un CPU partagé** :
sur une machine normale ils seront nettement plus courts. Ce qui compte, c'est leur rapport. Le
précalcul total du village, hors terrain, tient en **4,5 secondes**, et il remplace un éclairage
qu'il faudrait sinon recalculer soixante fois par seconde.

Le panneau en haut à gauche donne en direct : images/s, CPU, GPU, triangles, appels, mémoire
GPU détaillée, mémoire voxels CPU, **temps de précalcul** (modules, terrain, ciel du village) et
**temps de remaillage après une destruction**.

**Touche B** : tour du village de 20 s, qui rend la moyenne, le 95e et le 99e centile, le temps
GPU si le navigateur le donne, et le nom du GPU. C'est le seul chiffre de performance qui
compte, et il faut le lire sur la machine de Monsieur. La page demande le GPU basse
consommation (`powerPreference: 'low-power'`), donc normalement l'iGPU.

## Commandes
- `,` et `;` : reculer et avancer l'heure. `N` : arrêter ou relancer le cycle jour/nuit.
- `1` à `4` ou la molette : taille de l'outil. Clic gauche maintenu : creuser.
- `F` : vol. `B` : mesure. `H` : masquer le panneau.
- `?vs=0.05` : recharger le monde en voxels de 5 cm. `?scale=0.75` : rendre à 75 %.

## Fichiers
- `jeu/` : la page (`index.html`, `engine.js`, `shared.js`) et les données (`world.bin`, et
  `world.b64.txt` pour l'hébergement). En local : `python3 -m http.server` dans `jeu/`.
- `outils/` : `vox_one.py` (voxélisation d'une pièce), `pack_world_vxb3.py`, `write_vxi.py`,
  `vxb3test.js`, `shots.js` (captures automatiques).
- `captures/` : les vues de rue, de village, aériennes, de nuit et d'intérieur.
- `RENDU.md` : l'étude sur l'éclairage précalculé, ce qui est retenu et ce qui est écarté.
- `VXB3_proposition.md` : la proposition de format envoyée au fil moteur.

## À faire remonter dans le projet unifié
- Le PRT d'ordre 1 au sommet et la grille de ciel : ce sont les deux briques de rendu qui se
  portent telles quelles dans le cœur C++, et elles ne coûtent presque rien.
- Le format VXB3 avec la taille de voxel dans l'en-tête.
- Le remplissage des murs ouverts, à porter dans `tools/voxelizer`.

## Limites connues
- La grille de ciel du village n'est pas remise à jour après une destruction : percer un mur
  n'éclaire pas encore l'intérieur. La correction est locale, il suffit de relancer la
  propagation sur la boîte touchée.
- Une seule cascade d'ombres pour tout le village : le contour s'épaissit au loin.
- L'eau est une surface posée, sans écoulement : creuser la berge ne vide pas l'étang.
- Le feu éclaire et brûle visuellement, mais ne se propage pas et ne consomme pas la matière.
- Les intérieurs des maisons sont vides, sans escaliers ni meubles.
