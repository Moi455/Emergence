# CLAUDE.md — engine

Cœur C++20 du jeu, indépendant du moteur hôte (Godot 4 via GDExtension). Rien n'est encore écrit : suis `engine/README.md` et la phase 0 de `docs/04_feuille_de_route.md`.

- Budgets et invariants : `docs/02_architecture_cible.md` §§ 1 et 13. Chaque module a un micro-benchmark dès sa création.
- Déterminisme : options de compilation strictes (`-ffp-contract=off`, pas de `-ffast-math`, `/fp:strict` sous MSVC) pour le code de génération ; tests d'empreinte sur des seeds de référence.
- Les écritures de voxels sont privées au module `ops`.
- Un module porté depuis `ai/npc_pipeline` doit passer les mêmes cas que son oracle Python (tests partagés en JSON).
