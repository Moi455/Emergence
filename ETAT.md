# État du dépôt (10 octobre 2026)

**Depuis le 9 oct. (Claude Code sur la machine de Monsieur)** : branche `claude/moteur-social` poussée sur GitHub. Focus : moteur social et Transformer (le reste est mis de côté, `.claudeignore`).

| Nouveau | État |
|---|---|
| `catalogue/` | source unique des variables et des gestes, étapes 0 à 17 faites, 45 tests verts ; voir `catalogue/ETAT.md` |
| `engine/social/` | moteur social C++20 (D31) : tables générées depuis le catalogue, gouverneur porté, d'accord avec son oracle Python sur 4 650 cas ; ctest 7/7 vert sur la machine de Monsieur |
| `docs/07_conception_ia.md` | conception du cerveau des PNJ, mesures réelles sur la Quadro RTX 3000 : 200 décisions/s ≈ 4 à 6 % du GPU en `small` |
| `ai/research/` | bancs d'essai GPU et simulation de l'ordonnanceur |

L'ancien état ci-dessous date du 8 oct.

## Ancien état (8 octobre 2026)

Branche `claude/integration-5q5447`, PR #1 (brouillon, à fusionner par Monsieur). La CI (`.github/workflows/ci.yml`) lance cinq tâches : pipeline PNJ et convertisseur (`scripts/test_all.sh`), moteur C++ (ctest), génération du monde (`test_worldgen`), simulation sociale (unittest). Elle est verte sur 7b970f6 ; chaque commit suivant passe tous les tests en local avant d'être poussé. Vérifiez le résultat du dernier commit sur GitHub.

## Ce qui est là

| Dossier | Contenu | État |
|---|---|---|
| `docs/` | décisions, architecture cible, feuille de route, `interfaces.md` v0.3 (contrat entre les fils) | `06_architecture_expliquee.md` doit être révisé selon les critiques de Monsieur du 8 oct. (texture des voxels, lumière en temps réel, pas d'upscaling, frontières sans téléportation, PNJ tous simulés par le Transformer) |
| `engine/` | cœur C++20 : plan du monde, chunks, maillage, terrain branché sur `worldgen/` ; extension Godot | 6 tests verts |
| `game/` | projet Godot 4.6 : scène principale `scenes/play.tscn` (monde en 6 anneaux de détail, de 2 cm à 64 cm, sur 1,4 km ; marcher, sauter, voler, creuser, poser) | jouable ; le fil moteur fait son bilan dans `engine/ETAT.md` ; la GDExtension (`game/bin/*.so`) n'est pas dans le dépôt et se reconstruit |
| `worldgen/` | générateur du monde déterministe depuis la graine | tests verts |
| `characters/` | générateur des villageois (graine → personnage rigué, 8 tenues, 24 animations) | les .glb se régénèrent avec `characters/tools/export.mjs` et ne sont pas dans le dépôt |
| `prototypes/village-web/` (bilan : `ETAT.md`, rendu : `RENDU.md`) | village jouable dans le navigateur : voxels de 10 cm, lumière du ciel en temps réel (cycle jour/nuit, exposition automatique), vrais villageois animés et éclairés par la même lumière | `python3 -m http.server` à la racine, puis `/prototypes/village-web/jeu/index.html` |
| `ai/` (bilan : `ai/ETAT.md`, catalogue : `ai/CATALOGUE_modele.md`) | données du Transformer (générateur 0.4, décideur de référence, jetons tok-1, `sim_adapter.py`), scripts d'entraînement (`ENTRAINEMENT.md`) | jeu de 300 000 exemples hors dépôt (`/mnt/project-files/donnees-transformer/`) ; le professeur Gemini n'a jamais été lancé |
| `sim/` (bilan : `sim/ETAT.md`) | simulation sociale sans affichage, 500 PNJ ; boucle `brain.py` / `live.py` prête à recevoir le Transformer de `ai/student` (un lot par heure de jeu) et gouverneur des ajustements de variables | le cerveau par défaut est encore le décideur à règles ; le cerveau Transformer demande PyTorch ; pas encore branchée sur les villageois ; catalogue unique : `docs/npc/variables_v0.3_catalogue_unique.md` (à valider par le fil Données) |
| `tools/voxelizer/` | convertisseur 3D → voxels | 50 tests |
| `assets/` | Medieval Village MegaKit (Git LFS) | |

## À savoir pour la suite (Claude Code sur la machine de Monsieur)

- Git LFS ne pouvait pas recevoir de nouveaux objets depuis les sessions dans le cloud : seul `assets/**` est en LFS. Sur une vraie machine, LFS fonctionne normalement.
- Jamais de clé dans le dépôt : `GEMINI_API_KEY` vient de l'environnement. Ne lancez pas `teacher_run.py pilot|run` sans l'accord de Monsieur.
- Aucun chiffre d'images par seconde n'a encore été mesuré sur un GPU réel (Iris Xe). Les mesures faites dans le cloud utilisaient un rendu logiciel.
