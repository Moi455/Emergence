# État du catalogue (`catalogue/`), 13 octobre 2026

Source unique de tout ce qui existe dans la simulation (D20, D28) : TOML dans `data/`, outils Python dans `tools/`, tests dans `tests/`. Le document lisible est `CATALOGUE.md` (généré).

## Fait (étapes 0 à 18 du plan, relues onze fois ; étape 19a le 13 oct.)

| Domaine | Contenu |
|---|---|
| Monde | 16 types d'entités, 50 composants (avec leur canal de connaissance), 89 propriétés (perceptibles ou non), 84 matières, 31 processus, 63 formes de parties, 421 types d'objets connus, 79 espèces |
| PNJ | 342 variables : corps, besoins, esprit stable (33 dimensions), esprit mouvant, croyances, relations (dossiers mentaux), souvenirs, objectifs, accords, perception par observateur |
| Actions | 40 gestes paramétrés par la manière ; 23 conditions perceptives |
| Langue | 338 concepts, 704 mots de grammaire et 799 sortes ; grammaire typée (20 symboles, 2 niveaux) ; 14 sondes de parole sans verbe social. **Étape 19a** : temps, groupes, accords, quantification, lieux, rôles typés (ci-dessous) |
| Jugements | 45 interprétations (faits physiques, indices perceptibles, normes dans la langue) |
| Règles | 4 règles dures dont D10 (refus par défaut, liste blanche par geste) ; gouverneur de référence |
| Interface IA | `generated/model_interface.json` : jetons d'entrée, têtes de sortie, écritures |
| C++ | `tools/gen_cpp.py` → `engine/social/generated/…/` : `catalogue_gen.h` (gestes, conditions, variables et bornes), `npc_state_gen.h` (une structure par composant, 11 réserves d'enregistrements), `vocab_gen.h` (mots et sortes) ; vecteurs partagés du gouverneur. Mesuré : 95,5 Ko par PNJ, 45,5 Mo pour 500 (estimation de docs/06 : 32 Mo ; à compacter : les propositions des croyances et souvenirs) |
| Ancien contrat | 112 fonctions et 20 conditions migrées (`data/migration.toml`) |
| Sondes | Étape 19a : **148** sondes, **142 exprimables**, 6 trous déclarés qui sont des LOIS DU MOTEUR (odorat, contagion et maladies, conception et naissance) ; deux sondes décomposées pas à pas (champ `trace`, vérifié par `tools/probes.py`) : le complot de vengeance à trois et l'expédition du maire |
| Réglages | `village_temperament` (0 sages … 10 fous, choisi par le joueur, lu dans `WAKE.temperament`, canal `setting`) et `w_think_budget` ; jamais lus par le gouverneur (`docs/12`) |
| ELIZA | rang des mots-clés, motifs de décomposition, 18 formes de parole reconnues après coup, échange `me`/`you` : `tools/shapes.py`, `docs/11` ; passif, jamais une option du modèle |

## Commandes

```
python3 catalogue/tools/check.py            # validateur (structure, canaux, D10, couches)
python3 catalogue/tools/budget.py           # ce que l'IA lit et écrit, compté
python3 -m unittest discover -s catalogue/tests
python3 catalogue/tools/model_interface.py  # régénère l'interface du modèle
python3 catalogue/tools/gen_cpp.py          # régénère les tables C++
python3 catalogue/tools/governor_vectors.py # régénère les vecteurs partagés du gouverneur
```

## Étape 19a (13 oct.) : ce qui a été ajouté, et ce que cela coûte

Toutes des primitives GÉNÉRALES, comblées dans cet ordre ; aucune entrée n'est propre à une histoire. Budget avant → après : mots de grammaire 655 → 704 / 768 (+51 ajoutés, −2 retirés), sortes 643 → 799 / 1 024, jetons 88 → 90 / 128, vecteur d'objet 43 / 48 (inchangé), gestes 40 / 64.

| # | Primitive | Mots de grammaire | Autres coûts |
|---|---|---|---|
| 1 | **Temps** : `dawn morning noon afternoon evening night`, `spring summer autumn winter`, unités `hour day season year`, `span`, opérateurs `at_time` (rendez-vous) ≠ `before` (échéance), `after`, `until`, `for`, `yesterday`, `sometime` ; `at_festival` et `before_winter` remplacés | +22, −2 retirés | `GOAL.when`, `COMMIT.when` (heures jusqu'au rendez-vous) |
| 2 | **Groupes** : `@G` et `us` agissent (agent, destinataire), dossier GROUP (membres ≤ 4, chef, but, rôle, sorte, taille : dérivés des croyances), engagement envers un groupe, `c_sees_ref` sur un groupe (tous les membres), compagnon `with` | +6 (variables nommables) | GROUP 6 → 12 champs, jetons GROUP 2 → 4 |
| 3 | **Accords** : `(yes h:2)`, `(no q:1)`, pointeurs `h: q: c:`, `half third quarter equal`, `share`, `think_more` + `WAKE.budget`, parole prévue `PLAN.says`, étapes lisibles `PLAN.steps` / `step_targets` | +5 | PLAN 6 → 9 champs (plafond 8 → 10) ; 3 symboles réservés |
| 4 | **Référence** : `(of QTY GROUP)`, `most`, percept collectif `EVENT.count` / `among`, description relative `(described … (link the_one child @E3))`, `knows` avec trou de question, `somewhere something nothing nowhere`, cinq évidentiels alignés sur les sources | +13 | EVENT 8 → 10 champs |
| 5 | **Lieux et choses** : 56 sortes de lieux et constructions (`sites.toml`, dont `sky moon`), 100 mots de perception en listes fermées (`percept_words.toml`, `words_from`), couleur (propriété + `THING.color`), mots de blessure, `mountable`, `BELIEF.unintelligible` ; `described` permis pour un lieu | +5 (`appears`, `beyond`, `from`, `against`, `color`) | +156 sortes |
| 6 | **Rôles et typage** : les rôles d'un événement sont les paramètres du geste (`give to`, `throw at/with`, `put where`, `pull toward`, `wear on`, `channel into`…), typés ; le gouverneur résout les mêmes parties ; `(caused X (dead Y))` ; `give` un animal, `take`/`pull` une plante ; pointeurs typés par le genre de leur enregistrement | 0 | `pointer_kinds` dans `Expression` ; `arg_classes` sur 4 prédicats |
| 7 | **Sondes** : 12 trous fermés, deux nouvelles sondes | 0 | `tools/probes.py` |

À savoir : le typage des pointeurs ne devine pas. `(dead @T1)` est refusé si l'enregistrement de `@T1` est un couteau, accepté si c'est une vache ; sans enregistrement connu, la proposition passe. tok-2 donne le genre (`THING.kind`, `LOCUS.kind`). Le gouverneur, lui, traite désormais une citation (`m:1`) comme un enregistrement et non comme une personne : un jugement d'adultère se dit entre adultes (le contenu cité est déplié et vérifié).

## Pas fait

- Étape 19b : combler les 6 trous restants, tous des lois du MOTEUR : odorat et réveil par l'odeur, contagion et cours d'une maladie (3 sondes), conception et naissance (2 sondes). Fuite de vérité à corriger : `channel.requires` lit `shapes_matter`, non perceptible.
- Les rails légers (coutumes connues des PNJ), prévus après la langue. Les formes de parole (`speech_shapes.toml`) pourront les nommer.
- Brancher le tempérament dans le sampler et le professeur (`docs/12` § 3).
- Questions ouvertes pour Monsieur : O16 à O21, O28 à O30 (`docs/01_decisions.md`).
