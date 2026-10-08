# CLAUDE.md — engine

Cœur C++20 du jeu, indépendant du moteur hôte (Godot 4 via GDExtension). État, mesures et commandes : `engine/README.md`.

- Budgets et invariants : `docs/02_architecture_cible.md` §§ 1 et 13. Chaque module a un micro-benchmark dès sa création (`core/<module>/bench`).
- Déterminisme : la génération est en entiers et virgule fixe Q16 (`core/base/include/emergence/base/fixed.h`, `noise.h`), jamais de flottant, de `rand()` ni d'état aléatoire partagé. Chaque couche tire sa graine de `layer_seed(seed, Layer::X)` ; ajoute une nouvelle valeur à l'enum `Layer` plutôt que de réutiliser une graine.
- Les empreintes de référence sont épinglées dans `core/world/tests/`. Si un changement les modifie, c'est voulu ou c'est un bug : incrémente `kWorldGeneratorVersion` et mets à jour les valeurs exprès, puis lance `scripts/check_determinism.sh`.
- Les écritures de voxels seront privées au module `ops` (invariant I4) ; pour l'instant seuls le générateur et les tests appellent `Chunk::set_brick*`.
- Un module porté depuis `ai/npc_pipeline` doit passer les mêmes cas que son oracle Python (tests partagés en JSON).
- Tests sans dépendance : `core/testing/include/emergence/testing/check.h` (`TEST`, `CHECK`, `CHECK_EQ`).
