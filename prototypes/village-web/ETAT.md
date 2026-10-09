# État du fil « Village voxelisé jouable » — 9 octobre 2026

Fil arrêté à la demande de Monsieur (8 octobre, 15 h 34) : il termine son chantier en cours et
n'en ouvre pas d'autre. Le détail technique du rendu est dans **RENDU.md**, le mode d'emploi dans
**README.md**.

## Fait
- Le MegaKit Quaternius voxelisé par le convertisseur des devs, en **voxels de 10 cm** (5 cm
  disponibles avec `?vs=0.05`). Format VXB3 (`jeu/world.bin`) et plan VXI1 (`jeu/village.vxi`).
- Une page jouable dans le navigateur : https://claude.ai/artifact/7a6jR7fZHyJAh3shh4uToq.
  Marche, vol, destruction, effondrement local et par bâtiment entier, étang, villageois animés
  du fil d'intégration, braziers, cycle jour/nuit.
- Le rendu refait de zéro (v3). Pas de texture bitmap. L'éclairage est calculé à chaque image ;
  seule la visibilité, qui ne dépend que de la géométrie, est précalculée.

## Réponse aux points de Monsieur sur le rendu
| Demande | État |
|---|---|
| Lumière selon l'heure, les nuages, la météo, calculée en temps réel | **Oui.** Aucune lumière n'est stockée. On précalcule seulement *ce que chaque point voit du ciel* ; la couleur et l'intensité du ciel et du soleil sont recalculées à chaque image. Le cycle jour/nuit tourne déjà. La météo n'est pas branchée, mais il suffira qu'elle change le ciel : l'éclairage suivra seul. |
| Pas d'upscaling | **Aucun.** Un simple curseur de résolution, au choix du joueur. |
| GPU au minimum, place pour l'IA | **iGPU visé**, le GPU dédié n'a pas été nécessaire. 150 Mo de mémoire GPU pour le village. |
| Voxels plus gros | **10 cm**, la taille de Teardown. Contrat à changer dans interfaces.md § 1 (fil moteur prévenu). |
| Textures | Pas de bitmap : grain procédural et biseau par voxel. **Voir l'écart avec les images de référence ci-dessous**, c'est là que se joue la question. |
| Eau et feu au plus léger | Ni l'un ni l'autre en voxels. Eau : surface analytique. Feu : lumières ponctuelles et cubes émissifs. |

## Mesuré
Machine de build sans GPU : les images/s n'y valent rien, le reste est juste.

| | |
|---|---|
| Téléchargement / chargement | 378 ko / 2,4 s |
| Mémoire voxels CPU | 1,2 Mo |
| Mémoire GPU | 150 Mo, dont 120 de maillages et 0,8 de grille de ciel |
| Vue de rue | 5,3 M de triangles (2,2 M de terrain, le poste dominant), 369 appels |
| Précalcul hors terrain | 4,5 s ; terrain 19,3 s de worker |
| Remaillage après destruction | 180 ms pour une maison entière, hors boucle de rendu |

## Écart avec les images de référence de Monsieur
Les quatre images (maison, village, monde, villageoise) montrent ce que « texture » veut dire
ici, et c'est une bonne nouvelle : **ce n'est pas de la texture au sens bitmap, c'est de la
couleur par voxel.** Chaque pierre, chaque tuile y est faite de plusieurs voxels de teintes
différentes, avec mousse, usure et salissure.

1. **Couleur et vieillissement par voxel — l'écart principal, et il ne coûte rien à l'exécution.**
   Le MegaKit a des textures presque unies, donc nos voxels le sont aussi. Il faut que le
   voxeliseur produise la variation : une teinte par pierre, de la mousse sur les faces du haut
   et à l'ombre, de la terre en pied de mur, des arêtes usées. Ce sont des données calculées une
   fois. **C'est ma recommandation n° 1.**
2. **La lumière** : soleil rasant et chaud, rayons volumétriques, brume en profondeur,
   lanternes. Réalisable pour peu : rayons en espace écran (environ 0,3 ms à demi-résolution),
   étalonnage chaud, brume selon l'altitude. Les lanternes sont déjà faites (braziers).
3. **La végétation dense** (herbes hautes, fleurs, lierre, buissons) : le plus gros écart en
   quantité, mais c'est du contenu, pas du rendu.
4. **La profondeur de champ** : un effet photographique, à proposer en option.
5. **Le personnage**, à environ 1 cm par voxel, est cohérent avec le choix de 1,25 cm du fil
   des skins.

Honnêtement : ces images sont générées par IA et contiennent un éclairage global parfait qu'un
iGPU ne reproduira pas en temps réel. La cible atteignable est leur palette, la direction et la
chaleur de leur lumière, et leur densité de détail.

## Pas fait
- La grille de ciel n'est pas remise à jour après une destruction : percer un mur n'éclaire pas
  encore l'intérieur. La correction est locale.
- Une seule cascade d'ombres.
- L'eau ne se prélève pas et ne s'écoule pas. Monsieur veut qu'en prendre en retire une quantité.
- Le feu ne se propage pas et ne consomme pas la matière.
- Pas de météo, pas de rayons volumétriques, pas de végétation dense.
- Les maisons sont vides à l'intérieur.
- Les images/s réelles sur l'iGPU de Monsieur ne sont pas mesurées.

## Questions ouvertes pour Monsieur
1. **Les voxels de 10 cm** vous conviennent-ils en jeu, ou préférez-vous 5 cm (`?vs=0.05`) ?
2. **Les textures** : après le rendu v3 et l'écart ci-dessus, la piste couleur et vieillissement
   par voxel (recommandée) vous va-t-elle, ou voulez-vous essayer de vraies textures bitmap ?
3. **Les images/s** sur votre machine : touche **B** dans la page.

## Pour la suite sur Claude Code
- À porter dans le cœur C++ : le PRT d'ordre 1 au sommet, la grille de ciel, la projection du
  ciel en harmoniques sphériques, VXB3 avec la taille de voxel dans l'en-tête.
- À porter dans `tools/voxelizer` : le remplissage des murs ouverts, puis la couleur et le
  vieillissement par voxel (point 1 ci-dessus).
- Tout est dans `/mnt/project-files/prototype-village/` : `jeu/` (la page), `outils/` (packers,
  vérification VXB3, captures automatiques, relevé des mesures), `captures/`, `RENDU.md`,
  `README.md`.
