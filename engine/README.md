# engine : cœur C++ (à créer)

Bibliothèque `emergence_core` (C++20, CMake), liée au jeu Godot par GDExtension et à l'exécutable sans rendu `emergence_sim`.

## Modules prévus

| Module | Contenu | Étape de la feuille de route |
|---|---|---|
| `base` | hachage entier, bruit entier, flottants stricts, maths maison, allocateurs, profileur | 0.3 |
| `world` | plan du monde, génération des chunks, VoxelId, briques, chunks, régions | M1, M2 |
| `ops` | bus d'opérations, formes d'outils, régions sales | M6 |
| `mesh` | maillage greedy binaire, LOD, micro-briques | M3, M4 |
| `light` | lumière mise en cache, sondes | M5 |
| `fields` | eau (colonnes, bassins), feu | M9 |
| `phys` | pont Jolt, corps de boîtes fusionnées | M6 |
| `stability` | connectivité, graphe porteur | M6 |
| `nav` | grille 25 cm hiérarchique (HPA*), graphe routier entre villages | S5 |
| `relevance` | paliers des PNJ, anneaux de LOD, budgets par image | M3, S5 |
| `society` | entités, variables, mémoire indexée, croyances, titres, documents, institutions, économie | S4, S6 |
| `act` | moteur d'action (plans, conditions, interruptions, exécution détaillée ou abstraite) | S4, S5 |
| `decide` | décideur de référence (utilités + HTN), élève (inférence entière, compute Vulkan) | S5, S7 |
| `lang` | cadres d'actes de parole, analyseur | S4 |
| `assets` | lecture VXP, bibliothèque de modules, blueprints, connecteurs | M8 |
| `persist` | sauvegarde par régions, journal, compaction, chronique | M10 |

## Arborescence visée

```
engine/
  CMakeLists.txt
  core/<module>/{include,src,tests,bench}
  sim/            exécutable emergence_sim (sans rendu)
  gdext/          liaison Godot
  third_party/    Jolt, zstd (sous-modules)
```
