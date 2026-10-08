# Emergence

Jeu médiéval-fantastique pour Steam : monde de voxels de 2 cm entièrement destructible, physique, eau, feu, effondrements, et 500 PNJ en 5 villages dont la vie sociale émerge sans script. Rendu sur GPU intégré, IA sur GPU dédié.

Ce dépôt réunit, au 8 octobre 2026, tout le travail fait jusqu'ici : l'architecture pensée avec Claude, le pipeline PNJ et le convertisseur d'assets écrits par les développeurs. Il est préparé pour être repris avec Claude Code (lire `CLAUDE.md`).

## Par où commencer

| Pour… | Lire |
|---|---|
| comprendre le projet | `docs/00_vision.md` |
| savoir ce qui est décidé | `docs/01_decisions.md` |
| l'architecture qui fait foi | `docs/02_architecture_cible.md` |
| ce qu'on a repris du travail des devs | `docs/03_confrontation.md` |
| quoi faire ensuite | `docs/04_feuille_de_route.md` |
| comprendre pourquoi l'architecture est ainsi, ses limites et ses chiffres | `docs/06_architecture_expliquee.md` |
| proposer une idée | `docs/05_idees.md` |

## État au 8 octobre 2026

| Partie | État | Tests |
|---|---|---|
| Architecture | v1 consolidée ; plusieurs choix encore « proposés » | — |
| Pipeline PNJ (`ai/npc_pipeline`) | générateur, mémoire, règles sociales, dialogue, chantier, analyseur, pipeline teacher : faits ; aucun modèle entraîné, teacher jamais lancé en vrai | 30 cas (22 OK, 7 LEARN, 1 SPEC), autotests sans clé verts |
| Convertisseur (`tools/voxelizer`) | voxelisation, remplissage, palette, format VXP : faits ; table de matières, LOD, connecteurs : à faire | 50 tests verts |
| Moteur C++ (`engine`) | à créer | — |
| Jeu Godot (`game`) | à créer | — |

## Lancer les tests

```
pip install -r tools/voxelizer/requirements.txt
scripts/test_all.sh            # ou --quick pour sauter les autotests longs du pipeline
```

## Arborescence

```
CLAUDE.md                instructions pour Claude Code
docs/                    vision, décisions, architecture, confrontation, feuille de route, idées, glossaire
  reference/             documents d'architecture d'origine
  npc/                   conception PNJ des devs et audit
tools/voxelizer/         convertisseur 3D → voxels (Python)
ai/npc_pipeline/         pipeline de données PNJ et modules de référence (Python)
engine/                  cœur C++ (plan)
game/                    projet Godot (plan)
scripts/                 test_all.sh
archive/                 anciennes versions et sorties de travail (lecture seule)
```

## Avant de commencer

- La clé Gemini du 6 octobre est révoquée ; la nouvelle se garde dans la variable d'environnement `GEMINI_API_KEY`, jamais dans un fichier.
- Créer un dépôt GitHub privé à partir de ce dossier pour travailler avec Claude Code.
