# État du catalogue (`catalogue/`), 10 octobre 2026

Source unique de tout ce qui existe dans la simulation (D20, D28) : TOML dans `data/`, outils Python dans `tools/`, tests dans `tests/`. Le document lisible est `CATALOGUE.md` (généré).

## Fait (étapes 0 à 17 du plan, relues huit fois)

| Domaine | Contenu |
|---|---|
| Monde | 16 types d'entités, 49 composants (avec leur canal de connaissance), 89 propriétés (perceptibles ou non), 84 matières, 31 processus, 63 formes de parties, 421 types d'objets connus, 79 espèces |
| PNJ | 333 variables : corps, besoins, esprit stable (33 dimensions), esprit mouvant, croyances, relations (dossiers mentaux), souvenirs, objectifs, accords, perception par observateur |
| Actions | 40 gestes paramétrés par la manière ; 23 conditions perceptives |
| Langue | 293 concepts et 652 mots ; grammaire typée (20 symboles, 2 niveaux) ; 14 sondes de parole sans verbe social |
| Jugements | 45 interprétations (faits physiques, indices perceptibles, normes dans la langue) |
| Règles | 4 règles dures dont D10 (refus par défaut, liste blanche par geste) ; gouverneur de référence |
| Interface IA | `generated/model_interface.json` : jetons d'entrée, têtes de sortie, écritures |
| C++ | `tools/gen_cpp.py` → `engine/social/generated/…/catalogue_gen.h` ; vecteurs partagés du gouverneur |
| Ancien contrat | 112 fonctions et 20 conditions migrées (`data/migration.toml`) |

## Commandes

```
python3 catalogue/tools/check.py            # validateur (structure, canaux, D10, couches)
python3 catalogue/tools/budget.py           # ce que l'IA lit et écrit, compté
python3 -m unittest discover -s catalogue/tests
python3 catalogue/tools/model_interface.py  # régénère l'interface du modèle
python3 catalogue/tools/gen_cpp.py          # régénère les tables C++
python3 catalogue/tools/governor_vectors.py # régénère les vecteurs partagés du gouverneur
```

## Pas fait

- Étape 18 : revue de couverture des 146 sondes (une vingtaine seulement sont décomposées).
- Les rails légers (coutumes connues des PNJ), prévus après la langue.
- Questions ouvertes pour Monsieur : O16 à O21 (`docs/01_decisions.md`).
