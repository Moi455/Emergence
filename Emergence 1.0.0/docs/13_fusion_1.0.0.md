# Fusion dans Emergence 1.0.0 : carte du dépôt (14 octobre 2026)

Demande de Monsieur (14 oct.) : fusionner l'ancien dépôt (`claude/moteur-social`) dans le paquet 1.0.0, trier, documenter, puis ignorer ce qui ne sert pas à la session. **Critère de tri : la date de dernière modification.**

## 1. Règle appliquée

| Cas | Nombre | Décision |
|---|---|---|
| Fichier identique des deux côtés | 148 (503 après la copie des 357) | rien à faire |
| Fichier différent des deux côtés | 62 à la fusion (64 ensuite : `ETAT.md` et `.claude/settings.json` retouchés après) | **la version 1.0.0 gagne : elle est la plus récente dans les 62 cas** (13 oct. contre 8 à 13 oct.) |
| Fichier seulement dans 1.0.0 | 24 | gardé (générateur du professeur, `docs/10` à `12`, tempérament, formes de parole, sondes) |
| Fichier seulement dans l'ancien dépôt | 357 | **copié dans 1.0.0, date de modification conservée** (monde, rendu, personnages, prototypes, outils, archive, ancienne IA, `engine/em_water`) |

Caches (`__pycache__`, `build/`, `.git/`) ignorés. L'ancien dépôt n'a pas été modifié ; 1.0.0 d'avant fusion est sauvegardé (`Emergence 1.0.0.zip` à côté du dossier, et la branche `emergence-1.0.0`). Rien n'est commité ni poussé.

Les 62 fichiers où 1.0.0 gagne : le catalogue (données, outils, tests, interface générée), tok-2, l'élève `student2`, le professeur, les tables C++ générées de `engine/social`, `docs/01`, `08`, `09`, `CLAUDE.md`, `README.md`, `.claudeignore`, `.gitignore`.

Seule correction manuelle : `engine/CMakeLists.txt` (celui de 1.0.0 ne compilait que le moteur social) construit de nouveau le moteur du monde (`core`, `sim`, `worldgen`, `terrain`, `gdext`) **quand ses dossiers existent**. Le moteur social se construit toujours seul.

## 2. Vérification (après fusion)

| Contrôle | Résultat |
|---|---|
| `scripts/test_all.sh` | catalogue 159, tok-2 162, situations 123, professeur 173, élève 43 tests : tous verts ; ctest social 3/3 |
| CMake complet (social + monde + terrain) | ctest 9/9 : base, plan du monde, chunks, maillage, 3 du social, worldgen, terrain |
| `engine/em_water` (Rust) | **non testé** : `cargo` n'est pas installé sur la machine |

## 3. Le tri, par date de dernière modification

**Gardé lisible (travail actif, 10-13 oct.)**

| Dossier | Modifié | Rôle |
|---|---|---|
| `catalogue/` (sauf `generated/`, `CATALOGUE.md`) | 13 oct. | source unique : variables, gestes, langue, jugements, règles dures |
| `engine/social/` (sauf `generated/`, vecteurs) | 13 oct. | moteur social C++20 : gouverneur, état, horloges |
| `engine/core/testing/`, `engine/cmake/`, `engine/data/` | 13 oct. | utilisés par le moteur social |
| `ai/tok2/`, `ai/student2/`, `ai/teacher/`, `ai/situations/`, `ai/research/` | 13 oct. | format du modèle, élève, professeur, situations, mesures |
| `docs/01, 06 à 12`, `docs/interfaces.md`, `docs/00, 02, glossaire` | 13 oct. | décisions, architecture, IA, langue, tempérament |
| racine : `CHARTE_DU_JEU.md`, `CHANTIERS.md`, `ETAT.md`, `CLAUDE.md`, `README.md` | 13 oct. | charte (prime sur tout), chantiers, état |

**Ignoré pour cette session (aucun fichier supprimé)**

| Dossier | Modifié | Pourquoi | Réintégrer quand |
|---|---|---|---|
| `engine/core/{base,world,mesh}`, `engine/{gdext,sim,terrain,scripts}`, `worldgen/`, `game/` | 8 oct. | moteur voxel, génération, scène Godot : hors moteur social | mesure GPU, bus d'opérations M6, perception spatiale |
| `engine/em_water/` | 14 oct. | eau en Rust (plus récent, mais sans lien avec les PNJ) ; trop lent avec 8 sources | chantier eau/feu |
| `prototypes/`, `characters/`, `tools/voxelizer/`, `docs/style/`, `docs/reference/` | 8-9 oct. | village web, villageois 3D, voxeliseur, barre visuelle | chantier rendu et personnages |
| `ai/npc_pipeline/`, `ai/student/`, `ai/{CATALOGUE_modele,CONTRAT_PNJ,ETAT}.md` | 8-9 oct. | ancienne IA (tok-1, décideur à règles), remplacée par tok-2 et `student2` | portage d'un oracle de l'ancien pipeline |
| `sim/` | 9 oct. | ancienne simulation à règles | jamais en principe : remplacée par la boucle Transformer |
| `docs/03, 04, 05`, `docs/npc/` | 8-9 oct. | confrontation des ZIP, ancienne feuille de route, idées, anciens catalogues | doute sur l'origine d'une décision |
| `archive/`, `build/`, `assets/`, binaires, `*.jsonl`, `*.png`, sorties générées | : | lourd ou généré | jamais |

La liste vivante est `.claudeignore`. `python3 scripts/sync_claudeignore.py` la recopie dans `.claude/settings.json` (c'est là que Claude Code l'applique) ; avec `--check` il signale un écart.

## 4. À savoir

- **Assets** : `assets/` (Medieval Village MegaKit, Git LFS) était supprimé de l'arbre de travail de l'ancien dépôt ; il n'est pas dans 1.0.0. Il se récupère par `git lfs pull` sur `Moi455/Emergence`.
- **Écart entre `CHANTIERS.md` et la réalité** : sa section « 8 octobre » (mesure du rendu, bus d'opérations, rendu, eau) concerne les dossiers désormais ignorés ; la section du 11 octobre (mémoire C++, langue intérieure, perception, ordonnanceur, professeur, entraînement) est celle de cette session.
- **Dates des documents** : `docs/00, 02, glossaire, 06, 07, interfaces` portent la date de constitution du paquet (13 oct. 10:12), pas celle de leur rédaction ; je les ai gardés parce que 1.0.0 les avait retenus.
