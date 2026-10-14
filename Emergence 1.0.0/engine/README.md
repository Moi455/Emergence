# engine : cœur C++

Bibliothèque `emergence_core` (C++20, CMake, sans dépendance), liée plus tard au jeu Godot par GDExtension et dès maintenant à l'exécutable sans rendu `emergence_sim`.

## État au 8 octobre 2026

| Étape | Fait | Mesuré (machine de build : 4 cœurs x86 du conteneur, pas la machine de référence) |
|---|---|---|
| 0.3 Squelette CMake, tests, `emergence_sim` | oui, Linux (gcc 13, clang) ; Windows pas encore essayé | 3 exécutables de test, 20 tests, tous verts |
| M1 Plan du monde 20 × 20 km | relief, frontières, érosion, rivières, lacs, mer, biomes, géologie, sols, 5 sites, 8 routes, décor jusqu'à 205 km | 4,2 s (critère < 30 s) ; 36 Mo ; empreinte identique sur 12 compilations (gcc et clang, -O0, -O3, -march=native, 1 et 4 threads). Deux machines différentes : pas encore vérifié |
| 0.4 Godot 4.6.1 charge la GDExtension | `engine/gdext/` (classe `EmergenceWorld`), projet `game/` ; godot-cpp au commit `272e7f4a5fde342ea20983371fffafdccea07f20`, API 4.6 | la scène s'ouvre sans écran et retrouve la même empreinte (`6a24a0d52057c0df`) que l'exécutable C++ ; rendu testé en OpenGL logiciel (xvfb) |
| M2 Chunks 64³ en briques 8³, VoxelId 16 bits | génération locale, briques uniformes ou à palette 1/2/4/8/16 bits, chunks d'air et de roche implicites | chunk de surface : 0,42 ms en moyenne, 0,62 ms au 95ᵉ centile (critère < 1 ms) ; 9,5 Ko par chunk de surface ; 17 chunks à générer par colonne de 121, le reste implicite |

| M3 Maillage glouton binaire + LOD (en cours) | `core/mesh/` : faces par masques 64 bits, quad de 8 octets avec occlusion ambiante aux coins ; `terrain_streamer` : 6 anneaux emboîtés (2 cm à 64 cm, carré de 1,4 km), murs de couture, régions de 8³ chunks ; `terrain/` branche le générateur `worldgen/` ; shader Godot à extraction de sommets (`game/shaders/terrain_quads.gdshader`) | chargement complet autour du bourg 12,9 s sur 4 cœurs, 6,85 M quads (52 Mo), 164 régions dessinées ; marche : 0,8 s de calcul par pas de 2,56 m, en tâche de fond ; creuser un trou de 30 cm : 43 ms. Mesure GPU sur l'Iris Xe : à faire par Monsieur (touche H dans le jeu) |

Ce qui manque à M1 : grottes (réseau dans le plan), gisements, mesure sur la machine de référence et sur une deuxième machine (Windows/MSVC, ARM). Ce qui manque à M2 : lit des rivières creusé au voxel, routes et villages dans les voxels, strates rocheuses fines.

Ce qui manque à M3 : mesure du temps GPU sur la machine de référence ; feuillages pleins aux niveaux grossiers (demandé au fil de génération, ils font 90 % des quads lointains en forêt) ; les éditions ne se voient qu'au niveau 0 (44 m autour du joueur) ; micro-tracé du champ proche (choix 5 de l'architecture).

## Construire et tester

```
cmake -S engine -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
cd build && ctest                       # EMERGENCE_SKIP_SLOW=1 saute la carte complète
./core/bench_world                      # mesures M1 et M2
./sim/emergence_sim plan --seed 1 --out cartes/      # plan, temps, empreinte, cartes PNG
./sim/emergence_sim chunks --at town --out cartes/   # 20 × 20 m de voxels de 2 cm, vue de dessus et coupe
engine/scripts/check_determinism.sh 1   # même empreinte avec gcc/clang, -O0/-O3, 1/4 threads
./core/bench_mesh                       # mesures M3 (maillage)
./terrain/bench_terrain market_town     # mesures M3 (anneaux, marche, creusage) sur le générateur worldgen
./sim/emergence_sim geo --out geography_seed1.json        # villages, ressources, routes (docs/interfaces.md § 2 bis)
./sim/emergence_sim zone --at sea_village --out zones/   # champ de hauteur 128 m au pas de 8 cm autour d'un village

# Godot : GDExtension puis scène
git clone https://github.com/godotengine/godot-cpp && git -C godot-cpp checkout 272e7f4a5fde342ea20983371fffafdccea07f20
cmake -S engine -B build-gd -G Ninja -DGODOT_CPP_DIR=$PWD/godot-cpp && cmake --build build-gd --target emergence_gdext
godot --path game                                     # jeu : marcher, voler (F), creuser (clic gauche), poser (clic droit)
godot --path game res://scenes/terrain_view.tscn -- --site miners --shot capture.png   # terrain 2 cm maillé
```

## Choix d'implémentation

- **Génération 100 % entière.** Bruit de gradient en virgule fixe Q16, hachage splitmix64, `2^x` et racine carrée entières. Aucun flottant dans la vérité : c'est plus sûr que des flottants stricts pour l'identité au bit près entre compilateurs. Options `-ffp-contract=off -fno-fast-math` gardées par sécurité (`cmake/StrictFloat.cmake`).
- **Plan du monde** (`core/world/src/`) : `relief.cpp` (cœur habité, marches mer/montagne/désert/forêt dont le terrain dépend de la profondeur, limite intérieure qui serpente), `erosion.cpp` (Priority-Flood + ε, aire drainée, incision implicite de Braun et Willett, effondrement des pentes > 55°, dépôt dans les cuvettes), `settlements.cpp` (bourg près du centre, un village par frontière, routes A* avec coût de pente et de gué), `backdrop.cpp` (décor à 128 m jusqu'à 51 km, 512 m jusqu'à 205 km, jamais voxélisé), `world_plan.cpp` (biomes, roche, sols, empreinte).
- **Chunks** (`chunk.h`, `brick.cpp`, `chunk_gen.cpp`) : le profil d'une colonne est échantillonné toutes les 8 cm et interpolé (le bruit le plus fin a une longueur d'onde de 1,6 m ; le shader ajoutera le micro-détail). Couches : dessus selon le biome, sous-sol, roche du plan, granit à 40 m de profondeur. L'eau n'est pas dans les voxels (champ à part, architecture § 3.3). Le terrain écrit la teinte 0.
- **Table des matières** : `data/materials.csv` (classe 9 bits ; numéros figés, on ajoute sans renuméroter). Les noms sont ceux que le convertisseur devra viser.
- **Empreintes épinglées** dans les tests : si elles changent, tous les mondes changent. Il faut alors incrémenter `kWorldGeneratorVersion` exprès.

## Arborescence

```
engine/
  CMakeLists.txt, cmake/StrictFloat.cmake
  data/materials.csv
  core/base/      hachage, virgule fixe, bruit, empreinte, PNG, parallel_for
  core/world/     plan du monde (M1), chunks et briques (M2), tests, bench
  core/testing/   mini-harnais de tests sans dépendance
  sim/            emergence_sim
  scripts/        check_determinism.sh
```

## Modules prévus ensuite

| Module | Contenu | Étape |
|---|---|---|
| `mesh` | maillage greedy binaire sur la classe seule, LOD | M3, M4 |
| `light` | lumière mise en cache, sondes | M5 |
| `ops` | bus d'opérations, formes d'outils, régions sales (seul à écrire les voxels) | M6 |
| `fields` | eau (colonnes, bassins), feu | M9 |
| `phys`, `stability` | pont Jolt, connectivité | M6 |
| `nav`, `relevance` | grille 25 cm, HPA*, routes ; paliers et budgets | S5, M3 |
| `society`, `act`, `decide`, `lang` | portage C++ du noyau social (oracles Python) | S4 à S7 |
| `assets`, `persist` | VXP, modules ; sauvegarde par régions | M8, M10 |
| `gdext/` | liaison Godot 4 | 0.4 |
