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

## T08d (15 oct. 2026) : les naissances (P53, décision de Monsieur ; O39 close)

Fait : `body.toml` (processus `conceive`, `gestate_birth` : 44 -> **46**), `schema.py` (horloge de processus `life`), `tools/governor.py` (`Governor.conception_gate`), `stories.toml` (`marriage_and_children` et `pregnancy_birth` : `gap` -> `expressible`, plus aucun trou du moteur), tests `tests/test_t08d_births.py` ; `test_catalogue.py` et `test_language_collective.py` mis à jour (46 processus, `ENGINE_GAPS` vide). Détail : `docs/16_audit_couverture.md` § 4.4.

- **Aucun geste, aucune manière, aucune variable, aucun mot ajoutés** (D28, D10) : `conceive` exige la RÉCIPROCITÉ : deux `touch(manner=intimate)` croisés (A vers B, B vers A) à moins de 1 800 s de jeu, sans tierce personne, chacun déjà autorisé par le gouverneur ; adultes RÉELS, CRUS et APPARENTS, connus et perçus ; sexe, parenté proche et fécondité = faits du moteur à vérifier en T34 ; la porte est Python seulement (parité à faire en T34).
- **Gestation** : horloge de vie, 105 600 s de jeu = 1,22 jour de jeu = **1 h 50 réelle** (environ 0,98 an de vie ; D30 : 1 jour = 1 h 30, vie = 150 h). Naissance : nouvel agent `infant` (mineur D10 dès le premier instant), sans dossier ; croyances par observateur, formées par la perception seule.
- **Tests de refus D10** (sans aucun contenu) : mineur réel (0, 2, 9, 14, 17, 17,96 ans), mineur cru, mineur apparent, âge inconnu (cru absent, apparent absent, réel absent ou NaN, dossier non résolu, vue manquante, acteur ou partenaire absent), personne hors de vue, autre sens seul ; manières non intimes ou `romantic` : fermé ; non fécond : fermé.
- **Interface régénérée, en ajout seul : RIEN ne bouge.** Les processus, les sondes et le gouverneur n'entrent ni dans les jetons ni dans les registres : `model_interface.py` redonne un fichier identique octet pour octet, `tok2.registry --update` « déjà à jour », `output_registry --update` 0 ajout, C++ inchangé, `tok2.golden --update` sans écart. **Empreinte de l'interface : `009376fdb3dbadf2`, disposition `e84a8804b90f5bd1` (identiques à T09)** ; jetons 91 / 128, gestes 40 / 64, variables 378, mots 744 / 768. Parité du gouverneur : 9 336 cas (inchangés).
- **Données vivantes** : serie1 (9 816 lignes) et serie_planner (2 652 lignes, dont 2 635 avec `thoughts`) portent déjà l'en-tête `009376fd:e84a8804` : `teacher.dataset migrate --in-place` : 0 migrée, 0 perdue, comptes identiques avant et après ; `teacher.generator --selfcheck` : ok.
- **Tests** : `scripts/test_all.sh` **vert** (237 + 169 + 153 + 245 + 89 tests Python, 15/15 ctest ; les tests de l'élève passent, GPU libre).
- **Reste (T34, moteur)** : exécuter les deux lois, régler la probabilité de conception (la cible d'une naissance par couple et par 45 h suppose 150 couples féconds en permanence ; R ≈ 0,81 avec 70 % d'adultes en couple : retour de densité à régler), signes perçus de la grossesse (carrure `round`, teint `pale`).

## T08b (15 oct. 2026) : buts, plans, organisations, réglages

Fait dans `goals.toml`, `entities.toml`, `society.toml`, `relations.toml`, `settings.toml`, `tools/model_interface.py` (causes et déclencheurs de WAKE, `GOAL.parent`, `GROUP.my_task`) et `tools/budget.py` (PLAN : 2 jetons, plafond de champs 10 → 16). Test : `tests/test_t08b_plans_organisations.py`.

- **13 variables** ajoutées (358 → 371 avec ce seul lot) : `g_parent`, `g_has_plan`, `i_status`, `i_repeat`, `i_repeat_period`, `i_attempts`, `i_step_started`, `i_step_progress`, `w_outcome`, `s_last_believed`, `r_group_my_task`, `r_group_tasks_open`, `r_group_present`.
- **Le moteur ne juge plus** : `g_status` n'a que l'écrivain `T_jump` (test dédié) ; `a_status` = `open`, `expired`, `released`, `void` ; `i_status` : le moteur n'écrit que des faits, `abandoned` est au modèle seul.
- **Réserve d'intentions** : 1 → 4 (`entities.toml`). Saturation à mesurer en T30 et T40.
- **Écart avec la spec** : `w_outcome` est rangé dans `settings.toml` (porteur `setting`) et non sur `activity` : `activity` n'a pas de canal, et le schéma n'autorise un jeton WAKE que depuis le canal `setting`. `i_step_index` n'a plus de jeton (`PLAN.progress` vient de `i_step_progress`).
- **Mesuré après T08b** (`budget.py`, `model_interface.build()`, catalogue tel qu'il était à ce moment, avec les ajouts déjà faits par T08a) : jetons par décision **91 / 128** (PLAN 1 → 2) ; champs GOAL 12 / 16, PLAN 13 / 16, GROUP 15 / 16, WAKE 7 / 8 ; mots de grammaire 707 / 768, sortes 799 / 1 024, vecteur d'objet 43 / 48, gestes 40 / 64 ; variables écrivables par le modèle **101 / 128**. À re-mesurer après T08a et T08c.
- **À faire par T09** (régénération, non touché ici) : `generated/model_interface.json`, registres tok2 et élève (3 symboles nouveaux : `r_group_my_task`, `r_group_present`, `r_group_tasks_open`), tables C++. Tant que ce n'est pas fait, échouent : `test_model_interface_is_up_to_date`, `test_the_generated_file_is_up_to_date`, `test_cpp_tables_and_vectors_are_up_to_date`, `test_gen_cpp_stable`. `COMMIT.status` garde `fulfilled` et `broken` : c'est l'état CRU par la personne, pas celui du moteur.

## T08a (15 oct. 2026) : catalogue, matière et corps

Fait dans `data/{matter,body,actions,properties,world,entities,stories}.toml` (entities : seulement le composant `transformation` ajouté aux listes de item, structure, plant, terrain ; sans cela le test « chaque composant est utilisé » échoue).

| Ajout | Compte |
|---|---|
| Processus de la matière | 10 : `collapse`, `disassemble`, `germinate`, `separate`, `press_extract`, `wash`, `abrade`, `char`, `trap_catch`, `calcine` (31 → 41) |
| Lois du corps | 3 : `smell_spread`, `contagion`, `illness_course` (41 → 44). **Pas** `conceive` ni `gestate_birth` (O39) |
| Maladies `[[illness]]` | 8 : rhume, fièvre d'hiver, fièvre des marais, fièvre éruptive, mal des poumons, flux de ventre, fièvre des plaies, peste noire (symptômes = mots `health` existants) |
| Champs de temps des 44 processus | `trigger`, `clock`, `nominal_game_s`, `consumes`, `produces` partout (clock : 8 real, 20 game, 16 calendar) |
| Champs de temps des 40 gestes | `natural_end`, `cadence_ms` (250 à 2 000 ms) partout ; `productive` sur 6 (`operate`, `scoop`, `work`, `tie`, `shape`, `channel` ; aucun geste de dommage) |
| `[[duration_level]]` | 3 : `brief` 120 s, `a_while` 1 800 s, `long` 7 200 s de jeu |
| Variables | 5 : `made_at`, `made_by` (composant `provenance`), `process_progress`, `process_started_at` (nouveau composant `transformation`, moteur seul), `animal_product_ready` (`animal_behavior`) ; aucune n'a de jeton |
| Descriptions étendues | `cut` (carcasse espèce × partie), `extract` (plantes enracinées), `absorb_evaporate` (laisse le sel) |
| Sondes | 148 → 163 : 15 nouvelles (une par processus de matière, une pour l'odeur, une pour la maladie vue, 3 pour les descriptions étendues) ; 4 trous fermés (`smell_smoke_wake`, `epidemic_fear_exclusion`, `touchy_mayor_disaster`, `illness_and_care`) ; restent 2 trous, `marriage_and_children` et `pregnancy_birth` (O39) |

Budgets (`budget.py`) : gestes 40 / 64 ; vecteur d'objet 43 / 48 ; sortes 799 / 1 024 (inchangé : aucune matière ajoutée, `calcine` donne `plaster`) ; mots de grammaire 707 / 768 et jetons 91 / 128 : ces deux chiffres ont bougé avec le travail concurrent de T08b, T08a n'ajoute ni mot ni jeton.

Piège évité : aucune condition de processus ne porte sur une propriété non perceptible (`odor`, `traps`, `sharpens`, `wipes`, `contains`, `fuel`, `heats` sont perceptibles) ; `load_margin` et la fraîcheur déclenchent la loi dans le moteur mais n'entrent dans aucun jeton.

À régénérer par T09 : `generated/model_interface.json`, tables C++ et registre tok-2 (`cd ai && python3 -m tok2.registry --update` : symboles `r_group_*` de T08b ; T08a n'en ajoute aucun). Quatre tests échouent tant que T09 n'est pas passé : `test_model_interface_is_up_to_date` (deux fois), `test_cpp_tables_and_vectors_are_up_to_date` et `test_gen_cpp_stable`.

## T08c (15 oct. 2026) : langue, perception, espèces

Fait dans `data/{actions,language_core,perception,species,conditions,stories}.toml`, `tools/language.py` (une ligne : 5 catégories de mots typées `concept`) et `tests/test_t08c_langue_perception.py` (9 tests). `language_grammar.toml` et `percept_words.toml` : rien à changer.

- **Manières décrites par leur forme** : `speak.tone` + `rising` (voix qui monte, rythme vif), `trembling` (voix qui tremble), `low_slow` (lente et basse), `drawling` (traînante, étirée) : 5 → 9 / 9 ; `take.from` + `growing` : 4 → 5 / 8 ; `work.motion` + `twist` ; `examine.sense` + `hear` (hors liste blanche D10, comme `twist` : refusés avec une personne mineure) : 5 → 6 / 9. **10 valeurs sur 10** (`sign.kind` + `wink`, `cover_face`, `trace_sign` : 12 → 15 / 16, après levée de la limite de `schema.py`).
- **Élargissements** : `put.where` accepte `animal` ; `member` : `arg_classes = [[agent, group], [group]]` (une guilde dans une confrérie) ; sa signature `args` ne change pas, donc la forme vue par `ai/tok2/golden` non plus (à confirmer par le test de T09). Refusés : `(member @T1 @G1)` avec `@T1` un couteau.
- **Variables** : `pc_age_seen` (mot `new`, `worn`, `old` ; `THING.age`) et `pp_smell_seen` (liste de mots ; `PLACE.smell`) : 376 → **378 variables** (358 + 5 de T08a + 13 de T08b + 2). **Écart avec la spec** : `THING.age` est un champ-mot, pas une composante du vecteur d'objet (qui reste à **43 / 48**, au lieu de 44) : un mot de trois valeurs n'a rien à faire dans un vecteur de grandeurs. Les deux sont des mots de GRAMMAIRE (catégories `age`, `odor`) et non de `percept_words` : `schema.py` ferme la liste de ses catégories (`PERCEPT_CATEGORIES`).
- **Mots ajoutés : 37** (707 → **744 / 768**, 27 de marge) : 10 manières (`wink cover_face trace_sign` en plus ; `trembling` existait déjà comme sorte, donc comme symbole, mais pas comme mot de grammaire) ; 13 mots d'état de plan (`plan_state` : `running suspended blocked done abandoned failed interrupted limit_reached` ; `plan_repeat` : `once every` ; `wake_cause` : `goal_check occasion idle`) ; 8 odeurs (`smoky sweet sour acrid musty putrid aromatic rancid`) ; 3 âges (`new worn old`) ; 3 conditions (voir ci-dessous). Aucun mot propre à une histoire.
- **Conditions** : `c_have`, `c_unwatched`, `c_target_near` n'étaient PAS dans `conditions.toml` malgré l'acceptation de T08b (23 conditions) : ajoutées ici (docs/16 § 4.3) : **26 / 32**.
- **Temps des cultures** (`species.toml`) : 31 espèces renseignées (11 cultures, 6 arbres fruitiers et la vigne, 13 bêtes d'élevage et les abeilles) ; unités : jours de jeu entiers (1 jour = 1 h 30 réelle, une saison ≈ 1,2 jour, une année ≈ 4,7 jours : le blé d'automne mûrit en 4 jours, une culture de printemps en 2, un entier est grossier pour une saison). Les sauvages restent à 0.
- **Sondes** : 163 → **172** histoires, 9 nouvelles (une par ajout qui en mérite une : voix, `growing`/`twist`/`hear`, bât sur une bête, groupe dans un groupe, âge, odeurs, mots de plan, temps des cultures). `check.py --strict` OK, `probes.py` OK.

**Budgets re-mesurés après T08a + T08b + T08c** (`budget.py`, catalogue vivant) :

| Budget | Mesuré | Limite |
|---|---|---|
| Jetons par décision | **91** (SELF 1, SELF_MIND 1, SELF_STATE 1, TASTE 2, ENTITY 10, GROUP 4, BELIEF 12, HEARD 2, MEMORY 9, GOAL 4, PLAN 2, REQUEST 2, COMMIT 3, INV 8, SKILL 3, PLACE 1, THING 16, EVENT 6, LOCUS 3, WAKE 1) ; inchangé depuis T08b | 128 |
| Champs par jeton | THING 14, PLACE 9, PLAN 13, GROUP 15, GOAL 12, WAKE 7 | 16 (WAKE 8) |
| Mots de grammaire | **744** | 768 |
| Sortes | **799** (inchangé) | 1 024 |
| Vecteur d'un objet | **43** | 48 |
| Gestes | 40 | 64 |
| Conditions | 26 | 32 |
| Variables écrivables par le modèle | 101 | 128 |
| Variables du catalogue | 378 | n/a |

**À faire par T09** (non touché : `catalogue/generated/`, `engine/social/generated/`, `ai/`). Quatre tests échouent tant qu'il n'a pas régénéré : `test_model_interface_is_up_to_date` (`test_catalogue.py`), `test_the_generated_file_is_up_to_date` (`test_model_interface.py`), `test_cpp_tables_and_vectors_are_up_to_date` (`test_catalogue.py`) et `setUpClass` de `test_gen_cpp_stable.py` (`RegistryStale`). Mesuré sans rien écrire (interface construite en mémoire contre `ai/tok2/registry.json`) : **aucun conflit** ; 13 champs nouveaux (`GOAL.has_plan`, `GOAL.parent`, `GROUP.my_task`, `GROUP.present`, `GROUP.tasks_open`, `INV.age`, `PLACE.smell`, `PLAN.attempts`, `PLAN.repeat`, `PLAN.repeat_period`, `PLAN.status`, `THING.age`, `WAKE.outcome`) et **36 symboles nouveaux** : 3 de T08b (`r_group_my_task`, `r_group_present`, `r_group_tasks_open`, vérifiés), 33 de T08c (9 manières, 3 conditions, 10 mots d'état de plan, 8 odeurs, 3 âges). Les têtes de manière tiennent dans leurs capacités (`tone` 9/9, `from` 5/8, `sense` 6/9, `motion` 8/9). Test de compatibilité de `member` (`arg_classes`) : cas d'or de `ai/tok2/golden`, à lancer par T09. `language.py` ajoute 5 clés à `CATEGORY_TYPES` : elles apparaîtront dans `ai/tok2/golden/layout.json` (ajout seul).

## Corrections d'avant T09 (15 oct. 2026, relecteur adverse)

- **Noms (D28)** : `bright` -> `rising`, `grave` -> `low_slow` (speak.tone), `fragrant` -> `aromatic`, `foul` -> `putrid`, `timeout` -> `limit_reached` (w_outcome, plan_state) ; les 33 mots de T08a-c examinés, `rancid` et `sweet` gardés (noms de procédé et de saveur, sans verdict). Les symboles à graver par T09 portent donc ces noms. Test : `tests/test_t09_corrections.py`.
- **Oubli** (`forgetting.toml`, `tools/forgetting.py`, `forgetting_gen.h`, `forgetting_parity.inc` régénérés par `ForgettingGenerator`, parité C++ verte) : toutes les variables `time` lues par une récence sont des HORODATAGES (`ev_age` aussi, son jeton EVENT.age en montre l'âge) ; poids normalisés en « points » de 1000 (refusés par `check.py` sinon) ; `r_affection` et `r_obligation` dans `relation` ; capacité fixe en v1 (`capacity_from` retiré) ; `RecordPool::add(rec, now)` sans défaut ; une réserve toute protégée évince le moins bon protégé (`evicted_protected()`), elle ne refuse plus.
- **Temps** : `germinate` 43 200 s (0,5 jour), `illness_course` 518 400 s (médiane 6 jours), cours justifiés en heures réelles ; à surveiller : arbres fruitiers (14 à 47 jours de jeu avant la première récolte, jusqu'à 47 % d'une vie), cheval et chameau (14), mal des poumons (20 jours = 30 h réelles = 20 % d'une vie).
- **À faire par T09** : inchangé (`generated/model_interface.json`, registres tok2 et élève, tables C++ hors oubli) avec les nouveaux noms.

## T09 (15 oct. 2026) : régénération en ajout seul

Ordre suivi : `model_interface.py` (schéma **model-interface-3**, `tok2` lit 2 et 3) ; `tok2.registry --update` ; `student2.output_registry --update` ; `gen_cpp.py` ; `governor_vectors.py` ; `tok2.golden --update` (en-tête renouvelé, cas du sampler gelés, `--update-sampler` non nécessaire). Les deux `--check` sortent avec 0, ainsi que `gen_cpp.py --check` et `tok2.golden --check`.

| Mesure | Valeur |
|---|---|
| Empreinte de la nouvelle interface (tok-2) | **interface `009376fdb3dbadf2`**, disposition `e84a8804b90f5bd1` (avant : `2f9e945e6199d90b`, `261bb04518ef3a2e`) |
| Symboles tok-2 ajoutés | **36** (1 658 -> 1 694) : 3 `r_group_*`, 9 manières, 3 conditions, 10 mots d'état de plan, 8 odeurs, 3 âges |
| Champs tok-2 ajoutés | 13 (`GOAL.has_plan`, `GOAL.parent`, `GROUP.my_task`, `GROUP.present`, `GROUP.tasks_open`, `INV.age`, `PLACE.smell`, `PLAN.attempts`, `PLAN.repeat`, `PLAN.repeat_period`, `PLAN.status`, `THING.age`, `WAKE.outcome`) ; largeurs de bloc inchangées |
| Variables du catalogue ajoutées (`var_registry`) | **20** (358 -> 378) |
| Mots / sortes ajoutés (`vocab_registry`) | 40 mots (704 -> 744) ; 0 sorte (799) |
| Registre de sortie | 3 conditions (23 -> 26), 4 variables écrivables (94 -> 98 : `g_parent`, `i_repeat`, `i_repeat_period`, `i_status`), 9 valeurs d'énumération (86 -> 95), 10 valeurs de manière ; capacités inchangées |
| Élargissements de signature | `put.where` accepte `animal` (seule signature de geste qui bouge) ; `WAKE.trigger` accepte COMMIT, ENTITY, GROUP ; **aucun conflit** |
| Cas de parité du gouverneur (`governor_vectors.py`) | **9 336** : write 4 466, writes 1 551, gesture 3 319 (la parité C++ passe) |
| `scripts/test_all.sh` | **vert, 2 min 11 s** (224 + 169 + 123 + 211 + 69 tests Python, 11/11 ctest) |

Les anciens identifiants C++ (gestes, conditions, variables, mots, sortes) ne bougent pas : tableaux et énumérations de `catalogue_gen.h` et `vocab_gen.h` sont des préfixes de ceux de HEAD (seule la sentinelle `kCount` avance). Test : `ai/tok2/tests/test_compatible.py` (7 tests : préfixes des registres tok2, sortie, variables, mots/sortes comparés à `git show HEAD:...` ; identifiants C++ ; les 55 cas d'or gardent verdict et empreinte, donc l'élargissement de `member` est invisible à tok-2 ; `predicates.member` inchangé dans la grammaire exportée).

Corrections de tests rendues nécessaires par l'élargissement de pointeur de T08b (ENTITY accepté par `WAKE.trigger`) : le cas d'or refusé `bad_pointer_of_the_wrong_kind` et deux tests de `test_contract.py` prennent désormais un THING comme mauvais pointeur (même verdict, même nom). `student2/spec.py` : une variable de scale `qty` écrite par le modèle (`i_repeat_period`) prend la tête de quantité existante (sans elle, `Runtime.build()` levait `SpaceError`) ; aucune forme de tête ne change (T11).

**Anciens points de contrôle de `student2` : NE SE CHARGENT PAS, et c'est structurel.** Testé sur `~/.local/share/emergence/runs/a1/last.pt` : (1) `Checkpoint.check` refuse tout changement des empreintes d'entrée (interface, disposition, registre, vocabulaire sont des hachages de contenu, qui changent dès qu'on ajoute un symbole) ; seule l'empreinte de sortie `55c9948834339cdd` est identique, et `OutputRegistry.compatible` du point de contrôle est vide (le côté sortie est bien une extension) ; (2) même sans cette garde, `load_state_dict` échoue : les tables de symboles sont dimensionnées sur le NOMBRE de symboles (`embed.cat.emb.weight` 1 658 -> 1 694, `embed.prop.sym.weight` 1 658 -> 1 694, `decoder.sym.weight` 1 660 -> 1 696, avec les lignes eos/bos après les symboles). Ce que le README de student2 appelle « un ancien point de reprise se charge encore » n'est donc vrai que pour la sortie. Une migration (ajouter des lignes initialisées aux tables, avant eos/bos) est un travail de T11, non fait ici ; rien n'a été entraîné sur l'ancienne interface qui ne puisse être réentraîné.

## T06 (15 oct. 2026) : compactage de `NpcState` à 64 Kio au plus

Fait : `PropRef` (u32) + `PropositionArena` (`engine/social/include/emergence/social/proposition_arena.h`, 20 Kio = 5 120 mots, un symbole par mot : étiquette 3 bits, nombre d'enfants 5 bits, valeur 24 bits, sans perte) ; champs des structures générées triés par alignement (`gen_cpp.py`, `layout_fields`, les descripteurs de sauvegarde restent triés par identifiant) ; `PackedTime` (un `GameTime` en deux moitiés de 32 bits, alignement 4) pour supprimer le remplissage de 8 octets en fin d'enregistrement. La `Proposition` de 20 symboles reste le type d'échange (parseur, codec, langue).

| Mesure | Avant | Après |
|---|---|---|
| `sizeof(NpcState)` | 108 152 o | **36 444 o** |
| Arène des propositions (budget) | n/a | 20 480 o |
| Table annexe `SideTable` (budget de blocs) | 8 192 o | 8 192 o |
| **Total** (test `test_social_state`) | 108 152 o | **65 116 o <= 65 536** (marge 420 o) |
| 500 PNJ (partie fixe) | 51,6 Mo | 17,4 Mo |

Écart avec docs/14 7.1 (35 794 calculé) : +650 o, dû aux ajouts de T08b/T08c (3 intentions de plus, 2 champs de groupe, 20 variables) et au remplissage d'alignement de `Relation` (80 o). Sans `PackedTime` le total aurait été 65 680 o (144 o de trop). **Hors budget compté** : l'objet `SideTable` pèse en réalité 16 672 o (le tableau des générations par décalage, 8 Kio, s'ajoute aux 8 Kio de blocs) et `PropositionArena` 20 500 o ; `NpcBundle` complet : 85 960 o. À arbitrer par Monsieur si le « 64 Kio » doit compter la mémoire réelle (réduire `gens_` à u16 ou le calculer à la demande ramènerait la table à ~8,5 Kio).

**Arène pleine, jamais en silence** : `NpcBundle::store_proposition(p, now)` tente d'abord une compaction (`collect`, qui récupère les propositions des enregistrements écrasés ou oubliés), puis applique la loi d'oubli du catalogue (le moins bon croyance ou souvenir portant une proposition ; un protégé seulement si tous le sont, compté dans `evicted_protected()`), compacte et recommence. Rien n'est jamais alloué ni arrêté ; `propositions.reclaimed()` compte les enregistrements oubliés pour faire de la place et `propositions.refused()` les propositions perdues faute de tout. Une `PropRef` périmée (après compaction) se lit VIDE (époque de 14 bits). Chargement d'une vieille sauvegarde qui contiendrait plus que l'arène : les propositions en trop sont vidées et comptées (`LoadReport::arena_overflow_propositions`), jamais un refus.

**Longueur des propositions** (`python3 catalogue/tools/measure_arena.py --n 2000`, depuis `ai/`, graine 0) : **2 000 situations** (aucune en échec ; un premier passage en avait perdu 8 pendant une modification de l'échantillonneur par un autre chantier), 41 815 propositions (20,9 par situation) ; longueur **moyenne 5,07 symboles**, médiane 4, maximum 11. Tenues en même temps dans une situation : 106 symboles en moyenne (max 191), soit **2,1 % de l'arène** (max 3,7 %) ; une situation du modèle ne montre qu'un extrait de l'esprit. Pire cas réaliste, les 625 emplacements de propositions tous pleins à la longueur moyenne : 3 166 symboles = **61,8 % de l'arène** (docs/14 prévoyait 6,5 symboles par emplacement ; c'est mieux). Pleins à 20 symboles (12 500 > 5 120), c'est la loi d'oubli qui libère.

**Sauvegardes anciennes** : `engine/social/tests/data/reference_save_pre_t06.emsv` (4 PNJ) et `.fingerprints` ont été écrits par le code d'AVANT T06. Le test `a_save_written_before_the_compaction_reloads_with_the_same_fingerprint` (`test_social_codec`) les recharge : mêmes empreintes logiques, et la réécriture est identique octet pour octet (le format de fichier n'a pas bougé, version 1).

Vérifié : ctest 15/15 vert, `gen_cpp.py --check` OK, `test_gen_cpp_stable` et `test_forgetting` verts, parité du gouverneur inchangée (`governor.cpp` non touché), aucun identifiant ne bouge (le registre des variables n'a pas changé).

## T21 (15 oct. 2026) : `NpcLaws`, lois du corps et de l'esprit appliquées par le moteur

`engine/social/{include/emergence/social/npc_laws.h, src/npc_laws.cpp, tests/test_npc_laws.cpp}`. Un seul pas du moteur : 16 s de jeu (1 s réelle) ; tout autre pas est refusé (`LawReport::refused`). Le résidu fractionnaire fait partie de l'enregistrement du PNJ (`NpcBundle::laws_residue`), sauvegardé dans une section `LAWS` ajoutée (une sauvegarde sans elle se recharge avec un résidu nul ; `NPCS` n'a pas changé). Contrat d'âge : `life_clock` fait foi ; `set_age()` à la création ; `enforce_d10()` au chargement et après chaque application d'écritures T_step. 60 h de marche : 9 repas, 15 boissons, 2 nuits de 8 h, sommeil max 8,1, aucune saturation.

**Backlog des lacunes de lois (à faire, T34 ou une tâche dédiée)**
- Mort ou dégâts par soif, faim (réserves à 0), froid (< 33 °C), chaleur (> 41 °C), vieillesse : absents ; seuls des drapeaux de danger sont rendus. Seules deux morts existent : sang < 40 % et souffle à 0 pendant 180 s.
- `alive` est écrit par `step()` sur ces deux causes, mais la table de lois l'indique « pas de loi ».
- `r_obligation`, `r_rivalry`, `b_importance` ont un `rate` T_step mais aucune loi moteur (le catalogue ne décrit aucune dérive du moteur).
- `illnesses`, `immunities`, `pregnancy`, `fecundity`, `height`, `body_mass`, `wounds`, `permanent_marks` : reportés à T34 (listes dans les tables annexes ; la table `illness` n'est pas générée, donc ni cours de maladie ni fièvre).
- Les paramètres numériques des lois (taux par heure, demi-vies) sont dans un tableau de `npc_laws.cpp` : à faire générer depuis le catalogue (`gen_cpp.py`, table `law`). Même chose pour la fin de l'enfance (3 ans), absente des tables générées.
