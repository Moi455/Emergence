# worldgen/ : état au 8 octobre 2026

Propriétaire jusqu'ici : fil « Génération du monde par graine ». Ce dossier est l'unique générateur de chunks du jeu. Le plan à 16 m (relief, érosion, rivières, biomes, villages, routes, marches) reste dans `engine/core/world`, figé en version 1. Toute demande de changement du plan passe par le propriétaire du moteur. API et mesures détaillées : `README.md`.

## Fait

- **Chunks 64³ générés depuis la graine.**
  - Relief fin jusqu'à 37 cm.
  - Sol en couches, strates inclinées et socle.
  - Fer, sel et argile.
  - Grottes : systèmes de 400 m, galeries, salles et entrées.
  - Rochers.
  - Arbres : chêne, bouleau, pin et saule. Les géants grossissent jusqu'à ×10 au fond de la marche de la forêt.
  - Routes nivelées, plateformes des 5 villages.
  - Tout est en entiers ; la graine fixe le résultat.
- **Génération directe à n'importe quel niveau de détail** via `ChunkKey{x,y,z,lod}`, avec des voxels de 2 cm << lod, sans réduire les chunks fins. `classify()` répond Air, Solid, Mixed ou OutOfWorld sans rien générer.
- **Fusion avec le générateur du moteur.** `generate(ChunkCoord, Chunk&)` remplace son `ChunkGenerator`. Le moteur l'a branché (`engine/terrain`, `WorldGenSource`).
- **Teinte d'essence** sur l'écorce (31) et le feuillage (30) : 0 chêne, 1 saule, 2 pin, 3 bouleau. Il n'y a pas de hêtre ; il faut corriger le libellé de la teinte 1 dans `interfaces.md` § 2 bis.
- **Couronnes pleines en blocs au-delà de lod 2** (16 cm et plus). C'est une demande du fil moteur, livrée et testée avant la consigne de ne plus ouvrir de chantier.
  - `kChunkGenVersion` = 2.
  - Pour revenir en arrière, il suffit de mettre `kPorousCrownMaxLod` très haut dans `src/trees.cpp`.
- **Atlas** (carte, relief 3D, lieux en voxels, coupes) : https://claude.ai/artifact/KdMpKXenPSSk1ZyasD6zdX. Ses données se régénèrent avec `worldgen_tool export --seed 42 --out DIR`.
- **CMake** : le correctif du fil Intégration (`worldgen_cmake_standalone.patch`) est appliqué. Quand worldgen est le projet principal, le moteur l'inclut lui-même et le second passage s'arrête par `return()`. `scripts/check_determinism.sh` cherche donc l'exécutable dans `engine/worldgen/` si besoin.

## Mesuré (conteneur, 4 cœurs)

| Mesure | Résultat |
|---|---|
| Chunk de surface, lod 0 et lod 2 | 0,44 ms en moyenne, sur 1 fil |
| Chunk de canopée dense, lod 2 | jusqu'à ~10 ms |
| `bench_terrain market_town`, 6 anneaux sur 1,4 km | 7,1 à 7,6 s ici ; 12,9 s mesuré par le fil moteur. Avant : 69 s pour le seul anneau 1, par réduction 2×2×2 |
| Quads au chargement complet autour du bourg | 1,95 M, contre 6,85 M avant les couronnes pleines |
| Dont terrain seul, lod 3 à 5 | 1,11 M |
| `test_worldgen` | 11/11 |
| ctest du moteur avec worldgen | 6/6 |
| CI : `ctest -R "test_worldgen\|test_terrain"` depuis `worldgen/` | 2/2 |
| `check_determinism.sh` (g++ et clang++, Release et Debug) | 4 empreintes identiques |

Empreintes de référence (`tests/golden_seed7_4km.txt`) : plan `e37d2bfbd6de7983`, chunks `0c9abe435638d4f3`.

## Pas fait

- **Eau en voxels.** `water_mm()` donne le niveau du plan. Monsieur accepte que l'eau et le feu ne soient pas des voxels : c'est au moteur de les représenter.
- **Lits de rivière creusés au voxel.** Aujourd'hui, seul le niveau d'eau du plan existe.
- **Ponts, bâtiments, mobilier.** Les plateformes des villages sont plates et vides ; le contenu des villages appartient au fil Village et aux assets voxelisés.
- **Couronnes pleines, suite.** L'Atlas montre des plaques à fort contraste sur les géants à lod 4. Le volume lui-même est plein (vérifié en coupe), donc c'est l'affichage du visualiseur qui est en cause, à revoir sur Claude Code.
- **Canopée dense à lod 2** : jusqu'à ~10 ms par chunk. Le cache de colonnes n'est pas fait.
- **Deltas sauvegardés.** Les identifiants d'arbres sont stables pour cela (`TreeInstance::id`), mais la sauvegarde elle-même revient au moteur.

## Questions ouvertes

1. **Frontières.** worldgen ne contient ni mur ni retour au village ; c'est conforme à la demande de Monsieur (le joueur n'atteint jamais la limite, la difficulté le tue avant). Les marches portent une profondeur et un danger croissants (`march_depth_m` du plan) ; la simulation doit s'en servir pour les loups, la faim, etc. Hors de la carte, `classify()` répond OutOfWorld, sans aucun voxel.
2. **Taille du monde.** Monsieur parle de 50 km au total. Aujourd'hui, la carte en voxels fait 20 km, et le décor lointain du plan (sans voxels) va jusqu'à 205 km. Si la limite physique doit être à 50 km, il faut agrandir la carte du plan (moteur, version 2 du plan). worldgen suit `plan.n × cell_mm` sans changement de code ; seules la mémoire et le temps du plan grandissent (~5 s pour 20 km).
3. **Voxels plus gros**, demandés par Monsieur. Ce que ça change ici :
   - La taille vient de `kVoxelMm` (20 mm) du moteur, et worldgen calcule tout en `kVoxelMm << lod`. Passer à 4, 5 ou 8 cm est surtout un changement de constante. Tout est en millimètres entiers, donc 5 cm marche aussi.
   - Plusieurs seuils réglés en millimètres seraient à revoir : octaves fines (1,5 m à 37 cm), trous du feuillage sur 4 voxels, seuil des couronnes pleines (`kPorousCrownMaxLod`), épaisseur d'écorce (40 mm minimum), rayon minimal d'arbre visible.
   - Les empreintes de référence sont à régénérer (`WORLDGEN_WRITE_GOLDEN=1`).
   - Gain : avec des voxels 2 fois plus gros, il y a 8 fois moins de voxels par mètre cube, et chaque niveau de détail couvre 2 fois plus loin.
4. **Textures dans les voxels.** C'est une demande de Monsieur. Le générateur ne fournit aujourd'hui que la classe de matière (et la teinte d'essence) ; les textures se feraient au rendu, à partir de la classe, de la position et de la teinte. Aucun changement n'est nécessaire dans worldgen, sauf si l'on veut réserver des bits de teinte à une variante de texture.
