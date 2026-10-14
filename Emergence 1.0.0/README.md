# Emergence 1.0.0

Le moteur social et l'IA des PNJ d'Emergence : 500 villageois pilotés par un seul Transformer partagé, dans une simulation où les comportements émergent (complots, expéditions, alliances, rumeurs) au lieu d'être écrits.

## Ce qu'il y a dedans

| Dossier | Contenu | État |
|---|---|---|
| `catalogue/` | Tout ce qui existe dans la simulation : 40 gestes paramétrés par la manière, une langue intérieure typée, 46 jugements (vol, trahison, affront…), 342 variables, la règle dure des mineurs ; validateur et tests | fait, relu |
| `engine/social/` | Moteur social C++20 : gouverneur (bornes, règle des mineurs), état des PNJ, horloges | partiel : le reste est dans `CHANTIERS.md` |
| `ai/tok2/` | Ce que lit le modèle : l'esprit d'un PNJ en 128 jetons, identifiants figés | fait, relu |
| `ai/situations/` | Situations plausibles pour amorcer l'entraînement, contrôlées par le gouverneur | fait, relu |
| `ai/teacher/` | Le professeur (Gemini) : rendu des situations, schéma JSON, validation des réponses | fait ; générateur continu du quota gratuit écrit (`ai/teacher/README.md`) |
| `ai/student2/` | L'élève : le Transformer, ses têtes de sortie, l'entraînement en float16 | fait, pas encore entraîné |
| `ai/research/` | Mesures sur la Quadro : coût, sondes de raisonnement (coalition, fausse croyance) | fait |
| `docs/` | Décisions, architecture, conception de l'IA, catalogue expliqué, tempérament, `13_fusion_1.0.0.md` (carte du dépôt) | à jour au 14 oct. 2026 |
| `engine/core`, `worldgen/`, `game/`, `prototypes/`, `characters/`, `tools/`, `engine/em_water/`, `sim/`, `archive/` | Monde voxel, rendu, villageois 3D, eau (Rust), ancienne simulation : repris de l'ancien dépôt à la fusion du 14 oct. | présents, hors du chantier en cours (`.claudeignore`) |

## Les grands choix

- **Trois couches jamais mélangées** : les gestes du corps, la parole (composée dans la langue intérieure), les jugements des témoins.
- **Pensée écrite** (docs/09) : un PNJ réfléchit par petites décisions qui écrivent ses propres dossiers (croyance, jugement, objectif, plan, offre). Mesuré : 99,9 % de réussite sur la sonde de coalition, contre 71 % en une passe.
- **Rien de vrai dans ce que lit le modèle** : seulement ce que le PNJ perçoit, croit et retient.
- **Coût mesuré** : environ 17 % du GPU de la Quadro pour 200 décisions par seconde (objectif ≤ 25 %).

## Tester

```
scripts/test_all.sh
```

Prérequis : Python 3.12+, numpy, PyTorch avec CUDA (pour `ai/student2`), CMake et un compilateur C++20.
