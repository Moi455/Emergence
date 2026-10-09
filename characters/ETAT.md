# État des villageois (fil « Skins des villageois »), 8 octobre 2026

## Fait

- 600 villageois tirés d'une graine (120 par village), riggés sur 61 os aux noms Godot, 52 vêtements en données refaits pour chaque corps, 8 tenues par villageois (quotidien, travail, voyage, fête, deuil, froid, apparat, nuit), 24 animations de base.
- **Passage au style voxel demandé par Monsieur** (version 2 du générateur) :
  - forme générale en cubes de 2 cm ;
  - les marches deviennent des pentes et des facettes selon la matière : la peau s'adoucit (nez en coin, pommettes), les cheveux gardent leurs marches de cubes, le tissu est entre les deux ;
  - le nez et les oreilles sont sculptés en blocs entiers ;
  - peinture en pixels de 1 cm, et chaque pixel a le relief d'un petit cube (carte de normales répétée), ce qui donne l'aspect tricoté des vêtements de l'image « PNJ type » sans un triangle de plus ;
  - proportions rapprochées du réel : tête de 1/7 de la taille au lieu de 1/5, cou plus long, épaules moins larges.
- Exports `.glb` valides au validateur Khronos (0 erreur), échantillons dans `samples/`, module WebGL2 pour le village jouable (`runtime/webgl2.js`, relief des petits cubes calculé dans le shader), fiches au format du contrat (`data/fiches.json`), galerie en ligne.

## Mesuré

Mesures sur 29 adultes en tenue de travail :

| Niveau | Blocs | Triangles (moyenne) | Budget du contrat |
|---|---|---|---|
| LOD0 | 2 cm, pixels de 1 cm | 22 300 (18 400 à 29 900) | aucun, sert de près |
| LOD1 | 4 cm, pixels de 2 cm | 5 200 | 6 000 : tenu |
| LOD2 | 8 cm | 1 250 | 2 000 : tenu |
| LOD3 | 16 cm | 260 | 600 : tenu |

- Génération dans Node, sur un cœur : 0,25 s pour le corps, 0,6 s par tenue, 0,25 s pour le maillage LOD0.
- Un `.glb` complet (8 tenues, 4 niveaux de détail, 24 animations) pèse de 12 à 22 Mo. Le jeu ne garde que la graine et la garde-robe, environ 5 Ko par PNJ.
- Les 8 échantillons passent le validateur Khronos avec 0 erreur et 16 avertissements. Ces avertissements disent que l'espace tangent de la carte de normales est à calculer à l'import, ce que Godot fait.
- Pas mesuré : le rendu sur un vrai Iris Xe.

## Pas fait, et écart honnête avec les images de Monsieur

Comparé à l'image « PNJ type », on n'y est pas :

- **Visage.** La référence a un visage réaliste (anatomie, yeux, lèvres, peau, taches de rousseur) couvert d'une mosaïque fine d'environ 3 à 4 mm. Le nôtre reste un visage stylisé en blocs de 2 cm, avec yeux et bouche peints. C'est le plus gros écart. Un générateur procédural à base de formes simples ne fera pas un visage réaliste.
- **Cheveux.** La référence a des mèches bouclées qui tombent. Les nôtres sont un casque de cubes avec des mèches peintes.
- **Vêtements.** L'aspect tricoté en petits cubes s'en rapproche. Mais les formes sont raides : pas de drapé, pas de plis vrais, épaules gonflées, des colliers de fête qui flottent en plaques. Une jupe longue assise reste une cloche.
- **Lumière.** Soleil bas, rayons, profondeur de champ : c'est le travail du moteur. La galerie n'a qu'un éclairage simple (soleil chaud, contre-jour).
- Le shader « petit cube » n'est pas encore porté dans Godot. Le `.glb` porte une carte de normales cuite, donc Godot l'affiche déjà sans shader. Le shader de `runtime/webgl2.js` (quinze lignes) est le modèle à recopier.

## Ce qu'il faudrait pour atteindre le niveau des images

L'image « PNJ type » n'est pas faite de vrais voxels de 3 mm. C'est un **maillage réaliste**, avec une **texture en mosaïque** sur la peau et des **cubes de 1 à 2 cm sur les vêtements**. Ce rendu est tenable sur un iGPU : peu de triangles, et la mosaïque n'est qu'un shader. La voie :

1. **Corps et visages réalistes.**
   - **MPFB2** (MakeHuman pour Blender) est gratuit, hors ligne, avec des ressources CC0. Il se pilote par script : âge, sexe, corpulence, origine et traits du visage donnent des centaines de personnes distinctes déjà riggées. C'est la meilleure option pour 500 PNJ tirés d'une graine. Il faut Blender sur la machine de Monsieur, donc ça se fait dans Claude Code et pas dans la sandbox.
   - **Meshy AI** (ou Tripo, Rodin) est payant, du texte ou de l'image vers la 3D. C'est bien pour les vêtements, accessoires, coiffures et objets. C'est moins contrôlable pour 500 visages distincts, et la licence de chaque modèle est à vérifier. Rien n'a été appelé : il faut le feu vert de Monsieur pour tout service payant.
2. **Vêtements** passés au voxeliseur de Monsieur (`tools/voxelizer`), en cubes de 1,5 à 2 cm, et portés par-dessus le corps réaliste.
3. **Peau** en mosaïque fine par shader (même principe que le relief des petits cubes, à la taille de 3 à 4 mm).
4. **Rendu Godot** : lumière du jour en temps réel, occlusion ambiante, soleil bas, budget iGPU (travail du fil moteur).

Ce qui reste utile de ce fil dans cette voie : les graines, les garde-robes en données, les 8 tenues, le squelette aux noms Godot, les 24 animations, les fiches du contrat, l'export glTF et les niveaux de détail.

## Questions ouvertes

- Le contrat d'interfaces (v0.2) dit « voxels de villageois de 1,25 à 1,5 cm ». C'est désormais 1 cm pour la peinture et des blocs de 2 cm pour la forme : le fil moteur doit l'acter.
- Monsieur donne-t-il son feu vert pour la voie MPFB2 (gratuite) et, ou, pour Meshy AI (payante) ?
- Les autres propositions envoyées au fil moteur n'ont pas encore de décision : LOD choisi par la distance, plusieurs vêtements par emplacement, `extras` des animations, matières.
