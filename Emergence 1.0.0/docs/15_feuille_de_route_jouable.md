# Feuille de route jusqu'au jeu jouable (14 oct. 2026, révisée le 15 oct.)

But de Monsieur : « ajouter les actions manquantes, les variables, etc. À la fin, cela doit marcher, et on doit pouvoir passer à la création du monde, puis aux animations des actions des PNJ, puis à la fusion de tout cela. » Exigence de premier rang (14 oct.) : des PNJ qui **planifient** au service d'un but et s'**organisent**.

Architecture : `docs/14_architecture_moteur_actions.md`. Ajouts au catalogue : `docs/16_audit_couverture.md`. Décisions P35 à P51 et questions O31 à O39 : `docs/01_decisions.md`.

## État réel au 15 oct.

| Tâche | État | Chiffres |
|---|---|---|
| **T01** Professeur : types des pointeurs écrits | **fait** | `WriteChecker.ref_types()` lit les `ref_types` du champ de jeton ; ré-validation : 40 lignes refusées `bad_pointer` sur 9 856, et 22 sur 3 928 ; 211 tests du professeur verts (`ai/teacher/README.md` § T01) |
| **T02** Identifiants C++ stables | **fait** | `catalogue/generated/var_registry.json` (`var-registry-1`, 358 variables) ; `test_gen_cpp_stable.py` : 4 tests verts ; gouverneur C++ : 29 tests, 8 006 cas de parité (4 383 écritures, 300 lots, 3 323 gestes : tableaux de `engine/social/tests/governor_vectors.inc`, comptes imprimés par `python3 catalogue/tools/governor_vectors.py`) |
| **T03** Table annexe `SideTable` | **fait** | 1 000 000 d'opérations contre un oracle : 0 écart, 75 767 troncatures, 18 801 compactages, empreinte `fbefd8be95762830` ; 5 tests verts (`test_social_side_table`) |
| **T07** Schéma du temps | **fait** | `natural_end` (booléen), `cadence_ms`, `productive` ; processus : `trigger`, `clock` (`real`, `calendar`, `game`), `nominal_game_s`, `consumes`, `produces` ; espèces ; `[[duration_level]]` ; `[[illness]]` ; 177 tests du catalogue verts |

Tests relancés le 15 oct. sur la machine de Monsieur : `unittest` du catalogue (177) et du professeur (211), `test_social_governor`, `test_social_side_table` et `test_social_state` (le dernier affiche 108 152 octets par PNJ).

## Règles pour chaque tâche

- **Une tâche = un agent Sonnet en une session.** Taille **S** : une à deux heures ; **M** : une demi-session ; **L** : une session entière (à scinder si elle déborde).
- Chaque tâche finit par son **critère d'acceptation mesuré**, recopié avec le chiffre obtenu (même rouge) dans le `ETAT.md` du dossier, puis passe par un relecteur adverse (CLAUDE.md).
- Avant de coder une variable ou une action : elle est au catalogue (D20, D28). `scripts/test_all.sh` et `ctest` restent verts.
- Déterminisme : entiers et Q16, `emergence_strict_target`, hasard par hachage.
- D10 : seuls des **tests de refus** touchent aux contenus intimes.
- Machine de référence pour toute mesure : celle de Monsieur (Quadro RTX 3000 6 Go, i9-10885H, 62 Go).
- Aucun `git commit` ni `push` sans consigne de Monsieur pour la session.

## Les jalons

| Jalon | Ce qui le prouve | Tâches |
|---|---|---|
| **J0 Fondations** | sauvegarde de l'état des PNJ, identifiants stables, professeur durci, oubli, compactage | T01 à T06 |
| **J1 Catalogue complet** | ajouts de l'audit, régénération en ajout seul, données migrées, tête de plan | T07 à T12 |
| **J2 « Ça marche »** | 500 PNJ sans rendu, une journée de jeu, ≥ 200 décisions/s, plans exécutés, sauvegarde et reprise identiques | T13 à T35, T23b, T31b (T30 = la preuve) |
| **J3 Données humaines** | professeur « humain planificateur », scénarios par structure, plusieurs professeurs, sondes de planification | T36 à T41 |
| **J4 Monde créé** | 5 villages bâtis, nature, 500 habitants avec leur passé | T42 à T48 |
| **J5 Animations** | chaque geste et chaque manière jouent un clip, calé sur la simulation | T49 à T53 |
| **J6 Fusion** | Godot + simulation + inférence livrée, ≤ 25 % du GPU pour l'IA | T54 à T57 |

## Le parallélisme (calculé depuis les dépendances des tâches)

Une tâche entre dans la vague qui suit celle de sa dépendance la plus tardive ; les tâches d'une même vague se font en parallèle. Les tâches faites (T01, T02, T03, T07) comptent comme satisfaites.

| Vague | Tâches parallélisables |
|---|---|
| 0 | T04, T05, T08a, T08b, T13, T15, T16, T44 (T43 bloquée : O9) |
| 1 | T06, T08c, T14, T17, T18, T21, T23, T45 |
| 2 | T09, T19, T20, T22, T23b, T24, T28, T33, T46, T49 |
| 3 | T10, T25, T26, T32, T47, T50, T51, T52 (T34 bloquée : O39) |
| 4 | T11, T27, T35, T42, T53 |
| 5 | T12, T29, T31, T36 |
| 6 | T30, T31b, T37, T39 |
| 7 | T38, T40, T41, T48, T54 |
| 8 | T55, T57 |
| 9 | T56 |

Chemins critiques : jusqu'à J2, **T08a → T08c → T09 → T26 → T27 → T29 → T30**, et à égalité T08a → T18 → T22 → T26. Jusqu'à J6, la suite est T30 → T54 → T56 (après T55) et T57.

---

## J0 : Fondations

**T01 : Professeur, types des pointeurs écrits** : **fait** (voir l'état réel ci-dessus).

**T02 : Identifiants C++ stables** : **fait**.

**T03 : Table annexe `SideTable`** : **fait**.

**T04 : Sauvegarde et chargement de `NpcState` (sections NAME et NPCS v1)**
- Dossiers : `engine/social/include/emergence/social/npc_state_codec.h`, `src/npc_state_codec.cpp`, `catalogue/tools/gen_cpp.py` (descripteurs de champs : sorte, nom de variable, `offsetof`, type de stockage), `engine/social/tests/test_codec.cpp`.
- Dépendances : T03 (T02 fait).
- Interface : docs/14 § 7.6. Relecture par noms ; refus fermé. La section NPCS contient aussi le `WriteLedger` de chaque PNJ (par son `restore()` existant) et une place pour la carte mentale (remplie par T23b).
- Acceptation :
  - aller-retour de 500 PNJ remplis par un remplisseur déterministe, avec la même empreinte logique ;
  - une colonne inconnue est ignorée et comptée ; une colonne absente prend sa valeur initiale ;
  - un changement de type est refusé ; un CRC faux est refusé ;
  - durée de sauvegarde plus chargement de 500 PNJ mesurée et écrite (cible ≤ 200 ms [Estimé]) ;
  - `ctest` vert.
- Taille : L.
- Piège : copier les structures telles quelles (`memcpy`) ; oublier de renvoyer les symboles des propositions vers la table NAME.

**T05 : Loi d'oubli pilotée par le catalogue**
- Dossiers : `catalogue/schema.py` (classe `Forgetting`), `catalogue/data/entities.toml`, `catalogue/tools/check.py`, `catalogue/tools/forgetting.py` (oracle), `catalogue/tools/gen_cpp.py`, `engine/social/include/emergence/social/npc_store.h`.
- Dépendances : T02, T07.
- Interface : docs/14 § 7.5 ; `gen::forgetting_score(Kind, const Record&) → int32` ; ce qui est sous `protect` n'est jamais oublié ; une récence se compte en saisons (D30).
- Acceptation :
  - 12 entrées `[[forgetting]]` ;
  - `check.py` refuse un score qui lit `b_truth`, `b_origin_fact`, `m_fact_ref` ou `r_true_entity` (test) ;
  - parité C++ / Python sur 10 000 enregistrements ;
  - réserve pleine : un souvenir marquant n'est jamais oublié, et un ajout dans une réserve toute protégée est refusé et compté.
- Taille : M.
- Piège : faire dépendre l'oubli de la vérité.

**T06 : Compactage de `NpcState` à 64 Kio au plus**
- Dossiers : `catalogue/tools/gen_cpp.py` (`PropRef`, champs triés), `engine/social/include/emergence/social/proposition_arena.h`, `state_types.h`, `tests/test_state.cpp`.
- Dépendances : T04, T05.
- Interface : docs/14 § 7.1 et 7.4 ; arène de 20 Kio ; arène pleine → loi d'oubli.
- Acceptation :
  - `test_social_state` vérifie `sizeof(NpcState)` + arène + table annexe ≤ 65 536 octets, réserve de 4 intentions comprise ;
  - longueur moyenne d'une proposition mesurée sur 2 000 situations et écrite ;
  - une sauvegarde écrite avant T06 se recharge après, avec la même empreinte logique ;
  - parité du gouverneur inchangée.
- Taille : L.
- Piège : une arène qui se remplit en silence.

## J1 : Catalogue complet

**T07 : Schéma du catalogue, champs du temps** : **fait**.

**T08a : Catalogue, matière et corps**
- Dossiers : `catalogue/data/{matter,body,actions,properties,world,stories}.toml`.
- Dépendances : T07.
- Interface : docs/16 § 4.4 et § 4.6 :
  - 10 processus de la matière, et 3 lois du corps (`smell_spread`, `contagion`, `illness_course`) ; **ni `conceive` ni `gestate_birth`** (O39) ;
  - environ 8 maladies `[[illness]]` ;
  - `natural_end`, `cadence_ms`, `productive` sur les 40 gestes ; `trigger`, `clock`, `nominal_game_s`, `consumes`, `produces` sur les 44 processus ;
  - `[[duration_level]]` ;
  - variables `made_at`, `made_by`, `process_progress`, `process_started_at`, `animal_product_ready` ;
  - descriptions étendues de `cut`, `extract`, `absorb_evaporate` ;
  - au moins une sonde par processus ajouté.
- Acceptation :
  - `check.py --strict` OK (champs de temps présents sur les 40 gestes) ;
  - `budget.py` : gestes 40/64, jetons inchangés par rapport à la mesure d'avant (aucun champ de jeton ajouté), vecteur d'objet ≤ 48 ;
  - sondes nouvelles `expressible`.
- Taille : M.
- Piège : une condition de processus sur une propriété non perceptible, recopiée ensuite dans un jeton.

**T08b : Catalogue, buts, plans, organisations, réglages**
- Dossiers : `catalogue/data/{goals,conditions,entities,society,relations,settings}.toml`, `catalogue/tools/model_interface.py` (valeurs de `WAKE.cause`, types de `WAKE.trigger`).
- Dépendances : T07 (en parallèle de T08a : fichiers distincts).
- Interface : docs/16 § 4.3 et § 4.5 (champs marqués T08b), et les **changements** :
  - `g_status` sans l'écrivain `engine` ;
  - `a_status` réduit, côté moteur, à `open`, `expired`, `released` et `void` ;
  - `WAKE.cause` gagne `goal_check`, `occasion` et `idle` ; `WAKE.trigger` accepte COMMIT, ENTITY et GROUP ;
  - réserve d'intentions de 4 ;
  - `i_repeat` avec `every` et `i_repeat_period` ;
  - `r_group_my_task`, `r_group_tasks_open`, `r_group_present` ;
  - `s_last_believed`.
- Acceptation :
  - `check.py --strict` OK ;
  - `budget.py` : conditions 26/32, écrivables ≤ 128 ; **jetons re-mesurés et écrits** (≤ 128 ; aucune valeur annoncée d'avance) ;
  - un test vérifie qu'aucun écrivain `engine` ne reste sur `g_status`.
- Taille : M.
- Piège : laisser au moteur une variable qui conclut à la place d'une personne (statut d'un objectif, accord « tenu »).

**T08c : Catalogue, langue, perception, espèces**
- Dossiers : `catalogue/data/{actions,language_core,language_grammar,percept_words,perception,species}.toml`.
- Dépendances : T08a (même fichier `actions.toml`).
- Interface : docs/16 § 4.2 (10 valeurs de manière **décrites par leur forme**, élargissements de `put.where` et de `member`), `pc_age_seen`, `pp_smell_seen`, mots d'odeur et d'âge, mots des valeurs de `i_status`, `i_repeat`, `w_outcome` et des causes, temps des cultures dans `species.toml`.
- Acceptation :
  - `check.py --strict` OK ;
  - `budget.py` : mots ≤ 768, sortes ≤ 1 024, vecteur d'objet ≤ 48, **jetons re-mesurés** après T08a, T08b et T08c, et écrits dans `catalogue/ETAT.md` ;
  - `probes.py` OK ; `CATALOGUE.md` régénéré.
- Taille : M.
- Piège : décrire une manière par son sens social (« complicité », « honte ») au lieu de sa forme (D28).

**T09 : Régénération en ajout seul, et budgets**
- Dossiers : `catalogue/generated/`, `ai/tok2/registry.json`, `ai/student2/output_registry.json`, `engine/social/generated/`, `engine/social/tests/governor_vectors.inc`.
- Dépendances : T02, T08a, T08b, T08c.
- Interface : `model_interface.py` → `model-interface-3` ; `tok2.registry --update` ; `student2.output_registry --update` ; `gen_cpp.py` ; `governor_vectors.py`.
- Acceptation :
  - les deux `--check` sortent avec 0 ; les anciens registres sont un préfixe strict des nouveaux ;
  - **test de compatibilité de l'élargissement de `member`** (`arg_classes`) : les cas d'or de `ai/tok2/golden` restent valides et identiques ;
  - le nombre de cas de parité du gouverneur, relu dans la sortie de `governor_vectors.py`, est écrit ;
  - `scripts/test_all.sh` et `ctest` verts.
- Taille : M.
- Piège : **aucun conflit de signature n'est attendu** (seulement des valeurs ajoutées et des élargissements). S'il en apparaît un, s'arrêter et le signaler, sans renommer à la hâte. Les changements de forme des têtes de sortie relèvent de T11, pas de T09.

**T10 : Migration du jeu de données du professeur**
- Dossiers : `ai/teacher/{dataset,migrate,phrasebook,schema}.py`.
- Dépendances : T09.
- Interface : `python3 -m teacher.dataset migrate FICHIER --out NOUVEAU`.
- Acceptation : lignes gardées et écartées, **par raison**, écrites dans `ai/teacher/README.md` ; aucune ligne perdue sans être comptée ; `teacher.generator --selfcheck` OK.
- Taille : S.
- Piège : « corriger » des lignes devenues plus strictes ; on les compte, on ne les corrige pas.

**T11 : Tête de plan, tête d'arrêt de décision, listes écrivables, point de contrôle versionné**
- Dossiers : `ai/student2/{spec,labels,model,losses,output_registry,train}.py`, `ai/teacher/validate.py`, `ai/teacher/schema.py`.
- Dépendances : T01, T09, T10.
- Interface :
  - tête de plan : au plus 6 étapes × (un geste du registre ou FIN, et 1 pointeur parmi les `ref_types` de `PLAN.step_targets`), plus `i_repeat`, `i_repeat_period` et `g_parent` ;
  - tête d'arrêt de décision : la table de conditions existante, utilisée quand le geste n'a pas de `until` ;
  - registre de sortie en schéma 2 (liste `plan_steps`, capacité 8) ;
  - **point de contrôle versionné** (schéma du registre et formes des têtes inscrits dedans) et **chargeur partiel** : les tenseurs de même forme se chargent, les têtes nouvelles partent de leurs poids initiaux, et chaque tenseur ignoré est listé ;
  - le professeur peut écrire les listes.
- Acceptation :
  - un point de contrôle d'avant T11 se charge par le chargeur partiel (test), et la liste des tenseurs réinitialisés est exacte ;
  - 200 pas d'entraînement sur des plans synthétiques font baisser la perte ;
  - le validateur accepte un plan valide ; il refuse un geste inconnu, un pointeur du mauvais type, plus de 6 étapes, et une étape refusée par `check_gesture` (D10).
- Taille : L.
- Piège : promettre qu'un ancien point de contrôle se charge « tel quel » : les formes changent, seul le chargeur partiel le permet.

**T12 : Sampler, plans, sous-objectifs, routines, nouveaux réveils**
- Dossiers : `ai/situations/{builders,plans,mind,propositions}.py`, `ai/situations/tests/`.
- Dépendances : T09, T11.
- Interface : docs/14 § 10.5.
- Acceptation, sur 2 000 situations :
  - causes `plan`, `timer`, `routine`, `goal_check` et `occasion` ensemble ≥ 25 % ;
  - situations à 2 PLAN ou plus ≥ 20 % ; objectifs à parent ≥ 15 % ; mode `reflect` ≥ 30 % ;
  - 0 proposition invalide ; audit D10 : 0 refus ;
  - temps par situation mesuré **sur la machine de Monsieur** (i9-10885H ; le sampler ne touche pas la Quadro), dans ±50 % des 10 ms d'aujourd'hui.
- Taille : M.
- Piège : faire décider le sampler à la place du PNJ ; le sampler construit le contexte, il ne produit pas l'étiquette.

## J2 : « Ça marche » (moteur C++ sans rendu)

**T13 : Langue intérieure en C++**
- Dossiers : `engine/social/include/emergence/social/language.h`, `src/language.cpp`, `tests/test_language.cpp`, `catalogue/tools/language_vectors.py`.
- Dépendances : T02.
- Interface : port de `catalogue/tools/language.py` ; `Parser::parse → TypedExpression`, `problems()` avec les mêmes codes.
- Acceptation : parité sur 50 000 expressions (valides, et mutées invalides) : même verdict, mêmes codes ; temps par expression mesuré.
- Taille : L.
- Piège : le typage (`arg_classes`, `pointer_kinds`), les deux niveaux d'imbrication, les citations.

**T14 : Gouverneur C++, paroles et dossiers**
- Dossiers : `engine/social/{include/emergence/social/governor.h, src/governor.cpp}`, `catalogue/tools/governor_vectors.py`.
- Dépendances : T13.
- Interface : `check_utterance`, `check_record`, P30 (`d10_hearer`), dépliage des dossiers cités.
- Acceptation : au moins 5 000 vecteurs de paroles et de dossiers, parité à 100 %, comptés par la sortie de `governor_vectors.py` ; tests de refus D10, dont le cas de docs/09 § 3 ; `ctest` vert.
- Taille : M.
- Piège : ne pas déplier une citation, et laisser passer ce qu'elle contient.

**T15 : `EntityStore` (le monde non voxel)**
- Dossiers : `engine/act/` (nouveau module), `catalogue/tools/gen_cpp.py` (composants du monde, dont `provenance` et `transformation`).
- Dépendances : T02.
- Interface : `create`, `destroy`, `move`, accesseurs générés ; aucune écriture hors d'un abonné du bus.
- Acceptation : 100 000 entités créées, déplacées et détruites, empreinte identique sur deux exécutions ; mémoire par entité mesurée.
- Taille : M.
- Piège : copier les voxels d'une structure dans l'entité.

**T16 : Bus d'opérations (M6)**
- Dossiers : `engine/ops/` : `operation.h`, `operation_bus.h/.cpp`, `op_journal.h/.cpp`.
- Dépendances : aucune.
- Interface : docs/14 § 4.6.
- Acceptation : encodage aller-retour ; débit mesuré ; 8 fils → même empreinte du journal qu'un seul fil.
- Taille : M.
- Piège : laisser une autre voie d'écriture des voxels (I4).

**T17 : Opérations sur le monde voxel, chargé ou non**
- Dossiers : `engine/ops/{voxel_op_applier,region_delta_store,lod_propagator,sim_chunk_cache}.*`, `engine/core/mesh/include/emergence/mesh/chunk_cache.h`.
- Dépendances : T16.
- Interface : docs/14 § 4.7.
- Acceptation : même empreinte de chunk, que l'opération soit appliquée sur un chunk chargé ou en delta puis au chargement ; un tronçon de pont de 4 m détruit change son chunk grossier ; empreintes de `worldgen` inchangées.
- Taille : L.
- Piège : un ordre des deltas ou une réduction de niveau de détail non déterministes.

**T18 : Lois de la matière, 1 (séparer, assembler, s'effondrer)**
- Dossiers : `engine/act/{contact_resolver,process_engine}.*`, `engine/act/laws/`.
- Dépendances : T08a, T15, T16.
- Interface : `cut`, `split`, `fracture`, `crush`, `extract`, `till`, `assemble`, `bind`, `carve`, `collapse`, `disassemble`, `abrade` ; `kTaskCompression = 16` pour les processus `productive`.
- Acceptation : un test par processus, avec des résultats entiers tirés d'une table générée depuis le catalogue ; `grep` des noms d'outils dans `engine/act/laws/` = 0 ; pas de flottant.
- Taille : L.
- Piège : écrire des recettes au lieu de lire les propriétés.

**T19 : Lois de la matière, 2 (chaleur et chimie)**
- Dossiers : `engine/act/laws/`.
- Dépendances : T18.
- Interface : `heat`, `combust`, `char`, `calcine`, `melt`, `smelt`, `forge`, `fire_clay`, `cook`, `cool_freeze`, `ferment`, `rot`, `dry_preserve`, `tan`, `dye_process`, `mix`, `mold_cast`, `spin_weave`, `separate`, `press_extract` ; `ProcessClock`.
- Acceptation : un test par processus ; une fermentation commencée, sauvegardée puis rechargée, finit au même tick ; `rot` lit `made_at`.
- Taille : L.
- Piège : faire avancer un processus lent au rythme des pas plutôt qu'au temps de jeu écoulé.

**T20 : Lois de la matière, 3 (vivant, fluides, pièges, magie)**
- Dossiers : `engine/act/laws/`, `engine/act/fields/`.
- Dépendances : T18.
- Interface : `grow`, `germinate`, `heal_tissue`, `wear`, `wash`, `flow`, `absorb_evaporate`, `trap_catch`, `magic_shape` ; temps des cultures ; `animal_product_ready`.
- Acceptation : un champ semé au printemps mûrit dans la fenêtre de `days_to_mature` ; puiser baisse vraiment `water_volume` ; une baguette poussée au-delà de la maîtrise baisse `magic_stability`.
- Taille : L.
- Piège : `magic_shape` qui crée de la matière (charte § 17).

**T21 : Lois de l'esprit et du corps des PNJ (`NpcLaws`)**
- Dossiers : `engine/social/{include/emergence/social/npc_laws.h, src/npc_laws.cpp}`.
- Dépendances : T02, T05.
- Interface : les dynamiques `writer = engine` du catalogue : besoins, retour des émotions, familiarité, effacement des attitudes, netteté des souvenirs, maîtrise.
- Acceptation :
  - table « variable → loi » générée, chaque variable `engine` ayant sa loi ou la mention « pas de loi » ;
  - **voyage de 60 h de jeu à pied** (3 h 45 réelles, la route forêt ↔ mer de la graine 1) : faim, soif, sommeil et épuisement suivent les rythmes de D30 (environ 3 repas et un sommeil d'environ 8 h par jour de jeu), sans saturation ni valeur hors borne ;
  - la maîtrise monte plus vite devant un maître qui regarde ;
  - aucune loi ne dépasse le `rate` d'une variable `T_step`.
- Taille : M.
- Piège : une loi qui « réagit » à un événement à la place du modèle ; le moteur ne fait que les retours lents et la physiologie.

**T22 : Exécuteur de gestes**
- Dossiers : `engine/act/{gesture_executor,gesture_execution,gesture_timing}.*`.
- Dépendances : T15, T16, T18, T21 (navigation par une interface ; T23b fournit la vraie).
- Interface : docs/14 § 4.3 et 4.4 ; ordre des conditions d'arrêt : `until`, puis tête d'arrêt de décision, puis `natural_end`, puis butée `a_while` (`timeout`).
- Acceptation :
  - machine à états testée sur les 40 gestes ;
  - abattre un chêne : nombre de coups et durée réelle à ±20 % du calcul de docs/14 § 4.4 ;
  - un coup reçu interrompt ; un réveil P0 n'interrompt rien ;
  - **pas d'échec à distance** : une cible déplacée hors de vue ne fait échouer le geste qu'une fois l'acteur sur place, quand il perçoit l'absence ;
  - `c_have` (vu ou cru), `c_unwatched` et `c_target_near` testées.
- Taille : L.
- Piège : lire la vérité pour une condition d'arrêt ou pour un échec.

**T23 : Perception par observateur**
- Dossiers : `engine/act/perception/`.
- Dépendances : T03, T15, T16.
- Interface : docs/14 § 6.1 ; réveils P0, P1, P3, `occasion` et `goal_check` (calculés sur les dossiers du PNJ).
- Acceptation :
  - un `take` discret derrière un couvert n'est pas vu ; un murmure ne s'entend qu'à 2 m au plus ;
  - un test statique : aucun champ `visibility = engine` copié dans un percept ;
  - une occasion n'est émise que si l'objet perçu est désigné par un dossier actif du PNJ ;
  - temps par pas pour 500 PNJ mesuré sur l'i9 (cible ≤ 2 ms [Estimé]).
- Taille : L.
- Piège : un coût en O(n²) ; la vraie identité qui passe dans un percept.

**T23b : Carte mentale et itinéraires (`MentalMap`, `RoutePlanner`)**
- Dossiers : `engine/act/navigation/`.
- Dépendances : T15, T23.
- Interface : docs/14 § 4.8 : tronçons de route connus, tuiles parcourues de 256 m, lieux connus ; A* sur cette connaissance ; exploration au-delà ; occupation vraie consultée **seulement** dans le champ de vision.
- Acceptation :
  - **route coupée hors de vue** : le PNJ marche jusqu'à voir l'obstacle, puis échoue (`blocked`) sur place ; jamais avant ;
  - un PNJ qui ne connaît pas un lieu ne s'y rend pas en ligne droite parfaite à travers l'inconnu (test sur un relief) ;
  - une route apprise par la parole entre dans la carte mentale ;
  - mémoire par PNJ mesurée (≈ 1 Kio [Calculé]) ;
  - sauvegarde dans NPCS.
- Taille : L.
- Piège : appeler un A* sur la grille vraie « pour aller plus vite ».

**T24 : La parole entre les esprits (`SpeechRouter`)**
- Dossiers : `engine/social/{speech_router,mind_writer}.*`.
- Dépendances : T13, T14, T23.
- Interface : parole → HEARD chez chaque auditeur ; pointeurs traduits ; `us` figé ; référent créé ; `b_hops` augmente.
- Acceptation :
  - parité avec l'oracle Python du dépliage ;
  - une rumeur à 3 relais garde `b_hops` = 3 ;
  - un locuteur qui se trompe de personne transmet « celui qu'il appelle Aldric », jamais la vraie personne ;
  - une parole refusée par D10 n'atteint personne.
- Taille : L.
- Piège : résoudre par la vérité une référence que le locuteur a faite par erreur.

**T25 : Les accords (`AgreementBook`)**
- Dossiers : `engine/social/agreement_book.*`.
- Dépendances : T24, T08b.
- Interface (P50, docs/14 § 9 a) :
  - `open(offre, acceptation) → AgreementId` ;
  - `log(AgreementId, op_id)` pour chaque `Operation` qui touche une partie ou une chose nommée dans la proposition ;
  - réveil P2b des parties à l'échéance (déclencheur COMMIT) ;
  - états moteur `open`, `expired`, `released`, `void` seulement ;
  - `commitments_seen` tiré des croyances.
- Acceptation :
  - promesse : à l'échéance, les parties et les témoins sont réveillés et le moteur n'écrit **ni** « tenu » **ni** « rompu » (test) ;
  - obligation `each_season` relancée trois saisons de suite ;
  - test statique : `a_status` n'atteint aucun jeton ;
  - le journal de faits d'un accord est lisible par l'évaluateur d'entraînement (M5).
- Taille : M.
- Piège : évaluer la proposition de l'accord contre la vérité pour décider s'il est tenu.

**T26 : Exécuteur de plans**
- Dossiers : `engine/social/plan_executor.*`.
- Dépendances : T09, T22.
- Interface : docs/14 § 4.2 : 4 intentions ; suspension **seulement** quand le modèle choisit un autre geste ; `i_repeat`, `i_repeat_period` ; réveils P2, P2b et `goal_check` ; `w_outcome`.
- Acceptation :
  - scénarios scriptés (décisions écrites dans le test, sans modèle) : plan de 4 étapes ; P0 puis un autre geste, puis reprise ; échec perçu → `blocked` ; tour de garde toutes les 8 h, 3 jours de suite ;
  - abandon par écriture seulement ;
  - un objectif dont la croyance dit « atteint » donne un réveil `goal_check` **et aucune écriture du moteur** dans `g_status` ;
  - l'exécuteur ne démarre jamais un geste de lui-même.
- Taille : M.
- Piège : enchaîner les étapes sans décision (c'est la v2 : O34).

**T27 : Ordonnanceur C++**
- Dossiers : `engine/social/scheduler/`.
- Dépendances : T26.
- Interface : docs/14 § 5 ; oracle `ai/research/sim_scheduler.py`.
- Acceptation :
  - sur la trace synthétique, décisions/s à ±1 % et P0 au p95 ≤ 0,1 s ;
  - 6 h synthétiques : chaque PNJ qui a un objectif actif réfléchit au moins une fois par jour de jeu ;
  - une occasion ouvre un budget de réflexion ;
  - déterministe ; le filtre P3 ne lit que `i_commitment` ;
  - mesures exposées : latence p95 par priorité, réveils jamais servis, taille de la file P2.
- Taille : M.
- Piège : un seuil P3 inventé par le moteur.

**T28 : Tokeniseur tok-2 en C++, masque de faisabilité, candidats**
- Dossiers : `engine/social/tokenizer/`.
- Dépendances : T06, T13, T23.
- Interface : port exact de `ai/tok2` ; `TokenView` généré (pare-feu).
- Acceptation :
  - parité bit à bit avec les cas d'or et sur 10 000 situations ;
  - temps par PNJ mesuré (cible ≤ 20 µs [Estimé]) ;
  - le masque suit une croyance fausse, pas la vérité ;
  - aucun accesseur vers une variable sans jeton.
- Taille : L.
- Piège : les arrondis des codecs numériques.

**T29 : API C et liaison Python**
- Dossiers : `engine/capi/`, `ai/enginepy/`.
- Dépendances : T27, T28.
- Interface : docs/14 § 6.2 ; `RandomBackend`, `PythonBridgeBackend`.
- Acceptation : 100 pas de 50 PNJ par `ctypes` ; les jetons de `em_tokenize` égalent ceux de `ai/tok2` ; le moteur se compile sans Python.
- Taille : M.
- Piège : la propriété de la mémoire entre les deux côtés (règle : le moteur possède, Python copie).

**T35 : Organisations, cycle de vie des référents** (avant T31 et T30)
- Dossiers : `engine/social/referents.*`.
- Dépendances : T24, T25.
- Interface : docs/14 § 9 : création en parlant, groupe membre d'un groupe, `s_last_believed`, archivage après **une saison de calendrier** sans dossier qui le désigne, `r_group_my_task`, `r_group_tasks_open`, `r_group_present` dérivés des croyances du PNJ.
- Acceptation : un groupe formé par la parole ; une section dans une guilde ; un groupe que plus personne ne désigne, archivé après une saison ; un groupe dont un vieux membre se souvient, jamais archivé ; sondes `found_guild` et `criminal_band_forms` en boucle fermée (gestes scriptés).
- Taille : M.
- Piège : coder une institution (une classe `Guild`).

**T31 : Sauvegarde du monde (EMSV)** (avant T30)
- Dossiers : `engine/save/`.
- Dépendances : T04, T15, T17, T25, T35.
- Interface : docs/14 § 7.6 : NAME, NPCS, ENTS, OPLG, REGN, **CLCK** (horloges : tick, `WorldClock`, graines des tirages), AGRM, REFS ; une section inconnue est ignorée et comptée.
- Acceptation : aller-retour d'un monde de test (50 PNJ, une heure de jeu scriptée) avec des empreintes identiques ; taille mesurée ; une section corrompue est refusée ; versions dans l'en-tête.
- Taille : M.
- Piège : sauvegarder un cache (maillages, navigation, index spatial).

**T30 : La boucle « ça marche » (preuve du jalon J2)**
- Dossiers : `engine/social/simulation_host.*`, `ai/enginepy/run.py`, `engine/ETAT.md`.
- Dépendances : T29, T17, T19, T20, T23b, T25, T31, T35.
- Interface : `SimulationHost` (docs/14 § 3) ; point de contrôle de `student2`, ou des poids au hasard au début.
- Acceptation, sur la Quadro, 500 PNJ, une journée de jeu (1 h 30 réelle), sans rendu :
  - ≥ 200 décisions/s en moyenne ; P0 au p95 ≤ 0,1 s ;
  - **attente d'un réveil P2 au p95**, **taux de réveils jamais servis**, **taille de la file P2** (moyenne et maximum) mesurés et écrits (ils servent à O34) ;
  - GPU de l'IA ≤ 25 % (`nvidia-smi`, moyenne) ; simulation CPU ≤ 4 ms par pas en moyenne ; 0 plantage ;
  - avec `RandomBackend` et la même graine, deux exécutions donnent la même empreinte du journal ;
  - sauvegarde à mi-parcours (T31) puis reprise : suite identique ;
  - distribution du nombre de plans actifs par PNJ et part du temps passé à 4 ;
  - **mesures d'émergence, rapportées sans cible** (docs/14 § 9 f).
- Taille : L.
- Piège : le non-déterminisme du GPU (les tests d'empreinte se font avec `RandomBackend`).

**T31b : Chronique et compaction du journal**
- Dossiers : `engine/ops/{chronicle,op_compactor}.*`, `engine/save/`.
- Dépendances : T31.
- Interface : section CHRN (ajoutée sans changer la version d'EMSV) ; les `VoxelEdit` matérialisés fusionnés dans les deltas ; les opérations d'entités résumées dans l'état.
- Acceptation : après compaction, l'état rechargé est identique ; taille du journal avant et après, mesurée ; la chronique garde les morts, les constructions, les destructions et les accords publics.
- Taille : M.
- Piège : effacer une opération dont un souvenir (`m_fact_ref`) a encore besoin.

**T32 : Loi du corps O30, l'odorat**
- Dossiers : `engine/act/fields/smell.*`, `engine/act/perception/`.
- Dépendances : T20, T23.
- Interface : `smell_spread`, `pp_smell_seen`, réveil P3.
- Acceptation : la sonde `smell_smoke_wake` en boucle fermée ; la portée suit le vent.
- Taille : M.
- Piège : un réveil causé par la vérité du feu, et non par l'odeur perçue.

**T33 : Loi du corps O30, les maladies**
- Dossiers : `catalogue/data/body.toml` (déjà rempli par T08a), `engine/act/laws/illness.*`.
- Dépendances : T08a, T21, T23.
- Interface : `contagion`, `illness_course` ; symptômes visibles ; immunités.
- Acceptation : les sondes `illness_and_care` et `epidemic_fear_exclusion` en boucle fermée ; taux d'attaque d'une épidémie synthétique mesuré.
- Taille : M.
- Piège : montrer la maladie (la vérité) au lieu des symptômes perçus.

**T34 : Naissances (BLOQUÉE : question O39 à Monsieur)**
- Dossiers : selon la réponse de Monsieur.
- Dépendances : réponse à O39 ; puis T04, T14, T21, T24.
- Interface : aucune avant la décision. Rien n'est écrit, ni loi ni test, au-delà des tests de refus D10 existants.
- Acceptation : écrite après la décision.
- Taille : M.
- Piège : D10 et D15.

## J3 : Données humaines (en parallèle de J2)

**T36 : Consigne « humain planificateur » et trace de pensée écrite**
- Dossiers : `ai/teacher/{schema,batch,render,validate,dataset}.py`, `ai/teacher/mind_replay.py`.
- Dépendances : T10, T11.
- Interface : docs/14 § 10.1 (`teacher-answer-2`) ; une réponse donne k exemples `reflect` et 1 exemple `act` ; refus `incoherent_trace` pour les **seules contradictions formelles**.
- Acceptation :
  - `--selfcheck` à blanc ;
  - pilote réel de 300 décisions sur le quota gratuit : ≥ 90 % de réponses valides ; une trace dans ≥ 50 % des situations non urgentes ;
  - **part de gestes passifs** (éveillé, de jour, sans urgence) **≤ 30 %** [Hypothèse], contre 44 % mesurés sur 18 décisions. La justification est dans docs/14 § 10.1 : seuil d'alerte, jamais une règle du jeu ;
  - part des réponses rejetées pour `incoherent_trace` écrite (si elle dépasse 5 %, revoir la consigne, pas le filtre) ;
  - rejeu : chaque état intermédiaire se ré-encode en tok-2 valide.
- Taille : L.
- Piège : élargir le filtre de cohérence au-delà du formel (la cohérence au sens large se mesure, M2).

**T37 : Format de scénario (ScenarioSpec v1) et convertisseur**
- Dossiers : `ai/scenarios/` (nouveau) : `schema.json`, `convert.py`, `checks.py`, `tests/`.
- Dépendances : T01, T12.
- Interface : docs/14 § 10.2 ; familles **de structure** ; réutilise `situations.scene`, `layout`, `MindBuilder`, `audit`.
- Acceptation :
  - 200 scénarios écrits à la main et 200 synthétiques convertis ;
  - tok-2 valide, `check_record` sur chaque dossier, audit D10 à 0 problème ;
  - **test de non-fuite** : un secret que la personne focus n'a ni vu ni appris n'apparaît dans aucun de ses dossiers ;
  - codes de refus stables ;
  - aucune famille ne porte le nom d'une histoire de `stories.toml` (test).
- Taille : L.
- Piège : recopier la vérité du scénario dans les croyances de l'observateur.

**T38 : Auteur de scénarios (Gemini, Gemma), diversité, dé-duplication, mélange**
- Dossiers : `ai/scenarios/{author,dedup,quotas,mix}.py`.
- Dépendances : T36, T37.
- Interface : quotas par famille de structure, MinHash, fichier de mélange.
- Acceptation : à blanc ; sur 50 scénarios réels : ≥ 80 % convertis, quasi-doublons mesurés (cible ≤ 5 %), quotas tenus à ±10 % ; l'invite de l'étiqueteur ne contient aucun texte du scénario (test).
- Taille : M.
- Piège : laisser l'étiqueteur voir le scénario.

**T39 : Qualité par professeur**
- Dossiers : `ai/teacher/eval/`.
- Dépendances : T36.
- Interface : docs/14 § 10.3.
- Acceptation :
  - jeu d'étalonnage de 300 situations étiqueté par **au moins 2 professeurs** ;
  - rapport : kappa de Fleiss (famille du geste), accord sur la cible, signe des écritures, pente du tempérament, passivité, refus D10, invalides ;
  - poids en JSON, avec exclusion si validité < 90 % ou victoires chez le juge < 35 % [Hypothèse], et plafond de 50 % par professeur ;
  - le chargeur de `student2` lit les poids (test).
- Taille : M.
- Piège : un vote majoritaire qui écrase la diversité humaine.

**T40 : Sondes d'évaluation de la planification**
- Dossiers : `ai/research/plan/`.
- Dépendances : T36 (hors ligne), T30 (boucle fermée).
- Interface : mesures M1 à M8 (docs/14 § 10.4).
- Acceptation :
  - les huit mesures se calculent et se reproduisent (même graine, mêmes chiffres) ;
  - **test d'isolement** : la table « but → gestes compatibles » n'est importée par aucun module hors de `ai/research/plan/` (recherche dans `ai/`, `catalogue/`, `engine/`) ;
  - mesures de départ écrites ;
  - sonde « expédition » à 10 et 20 membres : M1 et M5 du chef, pour trancher l'élargissement de GROUP.members.
  - Cibles pour T41, **[Hypothèse]** : M3 ≥ 90 %, M1 ≥ 60 % pour les objectifs faisables, M4 ≤ 5 %.
- Taille : M.
- Piège : laisser la table d'évaluation devenir une règle du jeu.

**T41 : Entraînement sur données mixtes, puis DAgger branché**
- Dossiers : `ai/student2/`, `ai/enginepy/`.
- Dépendances : T39, T30.
- Interface : poids par professeur, tête de plan, mélange de sources ; DAgger par `em_world_step`.
- Acceptation : perte de validation par source ; M1 à M8 meilleurs que des poids au hasard, et comparés aux cibles de T40 ; 10 000 situations du moteur collectées.
- Taille : L.
- Piège : valider sur la distribution d'entraînement.

## J4 : Création du monde

**T42 : Contrat d'interfaces, version 0.5**
- Dossiers : `docs/interfaces.md`.
- Dépendances : T16, T50.
- Acceptation : chaque format de docs/14 § 8.3 décrit octet par octet ; plus aucune mention de « 4 h réelles ».
- Taille : S.
- Piège : décrire autre chose que ce que fait le code.

**T43 : Taille du voxel (BLOQUÉE : O9, Monsieur)**
- Dossiers : `voxel_id.h`, `emergence_world.cpp`, `worldgen/`, empreintes.
- Acceptation : `ctest` vert ; `check_determinism.sh` : 4 empreintes identiques.
- Taille : M.
- Piège : les seuils en voxels cachés dans `worldgen`.

**T44 : Plan des villages (parcelles et bâtiments)**
- Dossiers : `worldgen/` (module `settlement`).
- Dépendances : aucune.
- Acceptation : empreintes des 5 villages ; chaque village a les sortes de lieux dont son économie a besoin ; identiques avec gcc et clang.
- Taille : L.
- Piège : écrire une histoire dans la disposition.

**T45 : Bâtiments posés (VXI) et objets d'intérieur**
- Dossiers : `worldgen/`, `tools/voxelizer/`, `engine/terrain/`, `engine/act/`.
- Dépendances : T44, T15.
- Acceptation : empreintes avec bâtiments ; chaque entité structure renvoie à son instance ; un chemin de chaque maison au puits.
- Taille : L.
- Piège : la licence du kit (O5).

**T46 : Nature initiale**
- Dossiers : `worldgen/`, `engine/act/`.
- Dépendances : T44, T15, T08c.
- Acceptation : comptes par village écrits ; reproductibles depuis la graine.
- Taille : M.
- Piège : peupler hors des habitats (D13).

**T47 : Population initiale, dossiers mentaux, cartes mentales**
- Dossiers : `engine/social/population/`.
- Dépendances : T45, T04, T24.
- Interface : 500 PNJ, foyers, métiers, parenté, maîtrises ; croyances initiales **par observateur** ; carte mentale initiale (le village natal, les routes qu'on prend).
- Acceptation : 500 PNJ, audit D10 à 0 problème ; chaque PNJ a une maison, un métier ou un rôle d'enfant, au moins 5 relations, et connaît le chemin de chez lui au centre de son village ; reproductible.
- Taille : L.
- Piège : des croyances ou des cartes omniscientes.

**T48 : Histoire initiale (charte § 4)**
- Dossiers : `engine/social/population/history.*`.
- Dépendances : T47, T30.
- Acceptation : durée de création du monde mesurée (O38) ; diversité des relations et des souvenirs mesurée.
- Taille : L.
- Piège : écrire une histoire au lieu de tirer des faits.

## J5 : Animations des actions des PNJ

**T49 : Table geste + manière → clip (`AnimationMap`)**
- Dossiers : `catalogue/data/animation.toml`, `catalogue/schema.py`, `catalogue/tools/gen_cpp.py`.
- Dépendances : T08c.
- Acceptation : chaque combinaison (geste, valeurs de manière) que le modèle peut produire, listes blanches D10 comprises, mène à au moins un clip ; la liste des clips manquants est écrite.
- Taille : M.
- Piège : faire entrer la présentation dans l'état de simulation.

**T50 : `AnimationCue` v1 et calage sur la simulation**
- Dossiers : `engine/act/animation_cue.*`.
- Dépendances : T22.
- Interface : docs/14 § 8.4 (48 octets).
- Acceptation : sur 1 000 exécutions, le tick d'impact du signal égale celui de l'opération ; flux déterministe.
- Taille : S.
- Piège : faire dépendre la simulation de l'animation (P38).

**T51 : Clips manquants, lot 1 (déplacement, travail, objets)**
- Dossiers : `characters/gen/anim.js`, `characters/tools/export.mjs`.
- Dépendances : T49.
- Interface : les 24 clips existants restent (`idle`, `walk`, `run`, `carry_walk`, `carry_idle`, `sit_down`, `sit_idle`, `stand_up`, `sleep`, `eat`, `drink`, `swing_pickaxe`, `swing_axe`, `dig_shovel`, `kneel_work`, `pick_up`, `put_down`, `give`, `talk_calm`, `wave`, `nod`, `shake_head`, `hit_react`, `fall_down`). À ajouter : `climb_wall`, `climb_ladder`, `mount`, `ride`, `row`, `throw`, `shoot_bow`, `pour`, `pull`, `stir`, `hoe`, `hammer`, `trowel_place`, `draw_water`, `saw`, `use_mechanism`, `channel_wand`, `blow`, `play_instrument`, `sneak`, `turn_l`, `turn_r`, `jump`, `swim`, avec leurs événements.
- Acceptation : `.glb` exportés, validateur Khronos à 0 erreur ; `extras` présents ; nombre de clips livrés écrit.
- Taille : M.
- Piège : déplacer la racine dans un clip de locomotion.

**T52 : Clips manquants, lot 2 (parole, signes, conflit, soin, tendresse)**
- Dossiers : `characters/gen/anim.js`.
- Dépendances : T49.
- Interface :
  - conflit et soin : `slap`, `kick`, `shove`, `block`, `grab_restrain`, `die`, `kneel_tend`, `support_walk`, `change_clothes` ;
  - signes : `point`, `beckon`, `shrug`, `bow`, `applaud`, `spit`, `fist`, `wink`, `cover_face`, `trace_sign`, `raise_hand` ;
  - parole : `talk_angry`, `talk_pleading`, `talk_joyful` (piloté par `bright`), `talk_trembling`, `talk_grave`, `talk_drawling` ;
  - attention, écriture, rites : `listen`, `look_around`, `search_bend`, `read_paper`, `write`, `dance`, `pray`, `mourn` ;
  - tendresse : `embrace`, `hold_hands`, `lean_in`, `kiss`.
- Acceptation : validateur Khronos à 0 erreur ; clips de tendresse pudiques (jamais au-delà du fondu au noir).
- Taille : M.
- Piège : D10 et D15. Le garde de présentation est testé en T53, qui crée le lecteur.

**T53 : Lecteur d'animation dans Godot (`NpcPresenter`)**
- Dossiers : `engine/gdext/src/`, `game/scenes/`.
- Dépendances : T50, T51, T52.
- Interface : `AnimationTree` piloté par les signaux ; étirement pour caler `impact` ; objets aux points d'attache ; niveaux de détail ; **garde D10**.
- Acceptation :
  - test sans fenêtre : 50 PNJ jouent leurs signaux ; écart d'impact ≤ 1 image (33 ms) ; temps par image mesuré ;
  - **test de refus D10** : `NpcPresenter` ne joue jamais `kiss`, `lean_in` ni un `embrace` romantique si une partie n'est pas un adulte connu.
- Taille : L.
- Piège : écrire dans le monde depuis la présentation.

## J6 : Fusion

**T54 : La simulation dans Godot, et le joueur**
- Dossiers : `engine/gdext/`, `game/`.
- Dépendances : T30, T17, T53.
- Interface : `SimulationHost` sur son fil, instantanés en double tampon ; le joueur passe par les **mêmes gestes** (charte § 14).
- Acceptation : le joueur creuse → une `Operation` → un PNJ témoin s'en souvient ; 500 PNJ simulés ; sauvegarde et chargement en jeu.
- Taille : L.
- Piège : une voie d'écriture du joueur qui contourne le bus.

**T55 : Inférence livrée, TensorRT-RTX**
- Dossiers : `engine/infer/`.
- Dépendances : T41.
- Acceptation : parité de geste ≥ 99,9 % avec PyTorch sur 10 000 décisions ; latence par pas mesurée ; licence vérifiée et écrite (O27).
- Taille : L.
- Piège : la précision float16 des têtes (comparer les logits).

**T56 : Mesure de bout en bout sur la Quadro**
- Dépendances : T54, T55.
- Acceptation : IA ≤ 25 % du GPU sous un rendu Vulkan réel pendant 30 min ; images par seconde et temps GPU du rendu écrits ; 200 décisions/s tenues.
- Taille : M.
- Piège : un autre travail sur le GPU pendant la mesure.

**T57 : Endurance « cinq ans plus tard » (charte § 3)**
- Dépendances : T54 (ou T30, sans rendu), T31b.
- Interface : une année de calendrier sans rendu (7 h réelles), sur 3 graines.
- Acceptation :
  - RSS stable à ±5 % ;
  - taille de la sauvegarde mesurée et rapportée aux 500 Mo pour 100 h ;
  - morts, couples, changements de métier comptés (naissances selon O39) ;
  - **mesures d'émergence sans cible** (docs/14 § 9 f) : groupes nommés par un PNJ, leur durée de vie en saisons, leurs membres, les accords de groupe jugés tenus par l'évaluateur d'entraînement.
- Taille : M.
- Piège : conclure à partir d'une seule graine.
