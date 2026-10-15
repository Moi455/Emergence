# Architecture du moteur d'actions (14 oct. 2026, révisé le 15 oct.)

Statut : **proposition, défauts pris** (P35 à P51 de `docs/01_decisions.md`). `CHARTE_DU_JEU.md` prime sur ce document. Il complète `docs/06` (architecture voulue), `docs/09` (cerveau des PNJ), `docs/10` (moteur et IA) et remplace, pour le moteur d'actions, `docs/02` § 4 et `docs/interfaces.md` § 6-7 (version 0.5 à écrire, tâche T42 de `docs/15`).

Révision du 15 oct., après une relecture adverse :
- le moteur ne constate plus jamais qu'un objectif est atteint (§ 4.2) ;
- un geste n'échoue que sur place, et l'on se déplace avec ce qu'on sait (§ 4.3, 4.8) ;
- un accord se juge par les témoins, pas par le moteur (§ 9) ;
- les scénarios du professeur se classent par structure (§ 10.2) ;
- la conception et la naissance attendent Monsieur (O39).

Étiquettes : **[Mesuré]** = commande lancée sur la machine de Monsieur (sortie citée) ; **[Calculé]** = arithmétique sur des hypothèses écrites ; **[Estimé]** = à mesurer ; **[Hypothèse]** = idée non testée.

Documents liés : l'audit de couverture des actions est dans `docs/16_audit_couverture.md` (à ne pas confondre avec `docs/16_quantification.md`, écrit par un autre fil) ; le plan de travail en tâches est dans `docs/15_feuille_de_route_jouable.md`.

---

## 0. En bref

1. **Un PNJ planifie, le moteur exécute.** Cinq étages : objectif (GOAL), puis plan (PLAN, mémo écrit par le modèle), puis étape (un geste choisi par le modèle), puis exécution continue (le moteur), puis processus de la matière, et enfin `Operation` sur le monde. Le moteur n'annule, n'abandonne ni ne juge jamais un plan ou un objectif : il réveille le modèle, qui décide.
2. **Aucun nouveau geste.** Les 40 gestes couvrent 64 activités de la vie d'un village (`docs/16`). Il manque 10 processus de la matière, 3 lois du corps (odorat, maladies), 3 conditions d'arrêt, 10 valeurs de manière décrites par leur forme, et 20 variables (7 pour les plans, 7 pour le temps, 3 pour les organisations, 3 de perception et de provenance). **La naissance attend Monsieur** (O39).
3. **Ordonnanceur C++** : six priorités (P0 à P4, plus P2b pour les échéances), trois causes de réveil nouvelles (`goal_check`, `occasion`, `idle`), un seau de 200 décisions/s, un budget de réflexion par PNJ, et un plancher d'une suite de réflexion par jour de jeu pour qui poursuit un objectif.
4. **Perception par observateur** : c'est le seul code qui écrit les perceptions. **On ne se déplace qu'avec ce qu'on sait** (carte mentale) et **on n'échoue que sur place**. Un tokeniseur C++ unique sert au jeu et à l'entraînement, et Python l'appelle par une API C.
5. **L'état d'un PNJ mesure 108 152 octets**, et non 95,5 Ko [Mesuré]. Cible : ≤ 64 Kio (64 466 octets au calcul, § 7). Sauvegarde versionnée relue par noms ; loi d'oubli déclarée dans le catalogue.
6. **Identifiants stables** (T02, fait) : le C++ suit désormais l'ordre des registres en ajout seul.
7. **Le modèle ne sait pas encore écrire un plan** : `i_steps` et `i_step_targets` sont absents du registre de sortie de l'élève [Mesuré]. Il faut une tête de plan (T11).
8. **Données** : le professeur répond comme un vrai humain, par une suite de pensée écrite puis l'acte ; un second flux de scénarios inventés par Gemini et Gemma, classés par structure ; plusieurs professeurs, pondérés par la mesure.

---

## 1. Ce qui existe, vérifié le 14 et le 15 oct.

| Élément | État vérifié | Source |
|---|---|---|
| Catalogue | 358 variables, 40 gestes, 23 conditions, 31 processus, 84 matières, 421 types d'objets, 79 espèces, 148 sondes ; `check.py` : OK ; 177 tests verts | `check.py`, `unittest discover -s catalogue/tests` [Mesuré, 15 oct.] |
| Budget de l'IA | jetons 90/128, mots 704/768, sortes 799/1 024, vecteur d'objet 43/48, gestes 40/64 | `budget.py` [Mesuré, 14 oct.] |
| Registres en ajout seul | tok-2 : 1 658 symboles ; sortie de l'élève : 40 gestes / 64, 23 conditions / 32, 94 écrivables / 128, 35 têtes de manière / 64 ; **`var_registry.json`** (358 variables, T02) | [Mesuré] |
| Identifiants C++ (T02, **fait**) | ordre des registres, plus de tri par nom ; `test_gen_cpp_stable.py` : 4 tests verts | [Mesuré, 15 oct.] |
| Table annexe (T03, **fait**) | `SideTable` : 1 000 000 d'opérations contre un oracle, 0 écart, 75 767 troncatures, 18 801 compactages, empreinte `fbefd8be95762830` ; 5 tests verts | `test_social_side_table` [Mesuré, 15 oct.] |
| Schéma du temps (T07, **fait**) | `natural_end` (**booléen** : le geste finit seul, ou il lui faut une condition), `cadence_ms`, `productive` ; processus : `trigger`, `clock` (`real`, `calendar`, `game`), `nominal_game_s`, `consumes`, `produces` ; espèces : `sow_seasons`, `days_to_mature`, `harvest_window_days`, `product_regrow_days` ; tables `[[duration_level]]`, `[[illness]]` | `catalogue/schema.py` |
| Validateur du professeur (T01, **fait**) | une écriture `mref` est vérifiée selon les `ref_types` de son champ de jeton ; à la ré-validation, 40 lignes refusées sur 9 856 et 22 sur 3 928 ; 211 tests du professeur verts | `ai/teacher/README.md` § T01 [Mesuré] |
| État d'un PNJ | **108 152 octets** ; 500 PNJ = 51,6 Mo ; croyances 64 512 o (60 %), souvenirs 18 432 o, relations 17 664 o ; une `Proposition` = 104 o, copiée dans chaque croyance, souvenir, objectif, demande et relation | `test_social_state` et sonde `sizeof` [Mesuré] |
| Gouverneur C++ | `check_write`, `check_gesture`, `check_writes` ; 29 tests ; **8 006 cas de parité** avec l'oracle (4 383 écritures, 300 lots d'écritures, 3 323 gestes) ; `check_utterance` et `check_record` **pas portés** | tableaux `kWrites`, `kWritesCases`, `kGestureCases` de `engine/social/tests/governor_vectors.inc` (comptes imprimés par `python3 catalogue/tools/governor_vectors.py`) [Mesuré, 15 oct.] |
| Horloges | `WorldClock` (1 s réelle = 16 s de jeu), `LifeClock` (vie de 150 h) | `clock.h` |
| Intention | **une seule** par PNJ ; ses étapes sont des mots, sans manière ni condition | `npc_state_gen.h`, `goals.toml` |
| Plans côté IA | `i_steps` et `i_step_targets` sont dans `model_interface.json`, **pas** dans le registre de sortie | [Mesuré] |
| Professeur | **44 % de gestes passifs** (`rest`, `look`, `wait`) | [Mesuré, n = 18, 13 oct.] : trop peu pour conclure |
| Monde | plan de 20 km figé (v1) ; `worldgen` produit les chunks 64³ à la demande ; `ChunkCache::edit_sphere` agit au niveau 0 seulement, en mémoire | `engine/ETAT.md` |
| Distances entre villages (graine 1) | routes de 2,9 km à 17,6 km | `emergence_sim geo --seed 1` [Mesuré] |
| Animations | **24 clips** : 20 `clip()`, 3 `gait()` (`walk`, `run`, `carry_walk`), 1 `strike()` (`swing_pickaxe`) ; `interfaces.md` § 7 en demande 60 distincts, et les « + » de `actions.toml` une vingtaine de plus | lecture de `characters/gen/anim.js` [Mesuré] |
| Absent | exécution des gestes, processus, `Operation`, bus, ordonnanceur C++, perception C++, navigation, tokeniseur C++, sauvegarde, langue C++ | — |

---

## 2. Exigence de premier rang : des PNJ qui planifient (Monsieur, 14 oct.)

> « Les PNJ doivent être aussi intelligents que de vrais humains, réagir avec des organisations, des choses complexes ; tout doit être rendu possible par des variables. Ils doivent pouvoir PLANIFIER pour servir un but, pas réagir direct. »

| Exigence | Traduction | § |
|---|---|---|
| Planifier pour un but | GOAL → PLAN → étapes → gestes ; jusqu'à 4 plans (un par objectif actif), sous-objectifs (`g_parent`), routines (`i_repeat` et sa période), rendez-vous (`g_when`) qui réveillent | 4.1-4.2 |
| Reprendre, replanifier, abandonner | l'échec d'une étape réveille avec `WAKE.outcome` ; **seul le modèle** abandonne (`g_status`, `i_status`) ; un objectif qui *paraît* atteint réveille avec `goal_check`, et le modèle juge | 4.2 |
| Engagements envers autrui | accords envers une personne ou un groupe ; échéances crues qui réveillent ; tenu ou rompu, **ce sont les témoins et les parties qui le jugent** | 4.2, 9 |
| Ne pas réduire le PNJ à des réflexes | un réveil P0 appelle le modèle sans rien annuler ; le moteur ne suspend un plan **que** parce que le modèle a choisi un autre geste ; budget de réflexion par PNJ, plancher quotidien, réflexion ouverte par une occasion sociale | 5 |
| Organisations en variables | groupes, rôles, chef, accords, coutumes, biens communs : dossiers et croyances ; aucune classe d'institution | 9 |
| Évaluer | huit mesures de planification et des mesures d'émergence sans cible imposée | 9, 10.4 |
| Données | le professeur écrit des suites de pensée (but → plan → étapes) ; au moins 30 % des exemples en réflexion | 10 |

**Principe** : le moteur décide *quand* un PNJ pense et *combien au plus* ; le modèle décide *quoi* (D17). Le moteur exécute un geste et en applique les conséquences physiques. Il ne choisit jamais le geste suivant, même quand le plan le nomme, et il ne tire jamais de conclusion à la place d'une personne (un objectif atteint, un accord tenu, un vol).

---

## 3. Vue d'ensemble

```
 catalogue/ (TOML) ──gen_cpp, model_interface──► tables C++ générées + registres en ajout seul (tok-2, sortie, variables)
        │                                                    │
        ▼                                                    ▼
┌──────────────────────────── SimulationHost (fil de simulation, pas fixe de 100 ms réels) ────────────────────────────┐
│                                                                                                                      │
│  Scheduler ──qui pense ?──► Tokenizer (tok-2 C++) ──paquets 64/128──► InferenceBackend ──sorties──► DecisionDecoder  │
│     ▲   ▲                        ▲  (lit NpcState, jamais la vérité)   (PyTorch via API C,                  │           │
│     │   │                        │                                      TensorRT-RTX livré)                 ▼           │
│     │   │                  PerceptionSystem ◄────────────┐                                       Governor (D10, bornes) │
│     │   │                  (écrit les percepts,          │                                                  │           │
│     │   │                   la carte mentale)            │                                                  ▼           │
│     │   └── réveils ─────────────┤                       │                                        DecisionApplier       │
│     │                            │                       │                         écritures ◄────────┤                 │
│     │                            │                       │              (MindWriter, SpeechRouter,     │ geste          │
│     │                            │                       │               AgreementBook)                ▼                │
│     │                     OperationBus ◄── Operation ── ProcessEngine ◄── GestureExecutor ◄── PlanExecutor              │
│     │                            │   (lois de matter.toml, body.toml)  (RoutePlanner sur la    (GOAL→PLAN→étape)        │
│     │                            │                                      carte mentale)                                  │
│     └──── ExecutionReport ───────┼─────────────────────────────────────────────┘                                        │
│                                  ├──► EntityStore (objets, plantes, bêtes, structures, eau, feu : toujours simulés)    │
│                                  ├──► VoxelOpApplier ──► ChunkCache (chargé) | RegionDeltaStore (non chargé) ──► LOD   │
│                                  ├──► OpJournal (sauvegarde) ──► Chronicle (T31b)                                       │
│                                  └──► PerceptionSystem (témoins)                                                       │
└──────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────┘
                                               │ instantanés (double tampon) : transformations, AnimationCue, maillages
                                               ▼
                        Présentation Godot (gdext) : NpcPresenter (AnimationTree), maillages voxel, joueur
```

**Le pas de simulation** (100 ms réels = 1,6 s de jeu), dans cet ordre fixe :

1. `WorldClock::advance_real(0.1)`, puis les lois sur le temps (`ProcessEngine::tick_time`, `NpcLaws::tick`).
2. `GestureExecutor::tick` : chaque exécution en cours avance d'un pas, émet ses `Operation` et ses `ExecutionReport`.
3. `OperationBus::flush` : les abonnés appliquent les opérations du pas, dans l'ordre (§ 4.6).
4. `PerceptionSystem::update` : les observateurs perçoivent, écrivent leurs percepts et leur carte mentale ; les réveils sont émis.
5. `Scheduler::plan_tick` : choisit les PNJ qui pensent ; `Tokenizer` prépare les paquets.
6. `InferenceBackend::run` : en mode synchrone pour les tests ; en jeu, le lot du pas *t* est servi au pas *t + 1* (latence ≤ 100 ms) [Estimé].
7. `Governor` puis `DecisionApplier` : les écritures sont appliquées, et les gestes démarrent au pas suivant.

---

## 4. Du but à l'opération

### 4.1 Les cinq étages

| Étage | Ce que c'est | Stocké où | Écrit par | Décide quoi |
|---|---|---|---|---|
| **Objectif** (GOAL) | une proposition à rendre vraie, garder vraie ou empêcher ; échéance `g_deadline`, rendez-vous `g_when`, parent `g_parent` (nouveau) | `goal_records` (8) | **le modèle seul**, `g_status` compris (T08b retire l'écrivain `engine` de `g_status`) | le modèle |
| **Plan** (PLAN) | un mémo de 1 à 6 étapes (geste + cible), parole prévue `i_speech`, `i_repeat` et sa période, `i_status` (nouveaux) ; un plan par objectif actif | `intention_records` : **1 → 4** (mesure de saturation prévue en T30 et T40) | le modèle (tête de plan) ; le moteur ne note que des faits (`running`, `suspended` quand le modèle a choisi un autre geste, `blocked` après un échec perçu, `done` quand les étapes sont épuisées) | le modèle |
| **Étape** | le geste choisi au moment d'agir, avec sa manière, ses cibles et sa condition d'arrêt ; le modèle relit `PLAN.next` | `GestureCall` en cours | modèle (mode `act`, paquet de 64 jetons) | le modèle |
| **Exécution** | le geste qui dure : approche, cycles, fin, échec constaté **sur place** | `GestureExecution` (sauvegardé : `i_step_started`, `i_step_progress`, `i_attempts`) | moteur | rien : il applique |
| **Processus → Operation** | la loi physique déclenchée par le contact, la chaleur ou le temps, puis le changement du monde | `OperationBus`, `EntityStore`, voxels | moteur | rien : c'est la physique |

**Le plan est un mémo, décidé étape par étape (P36).** La charte (§ 8) permet au modèle de choisir « une action ou une séquence d'actions ». Deux façons de faire :

- **v1, retenue** : chaque étape commence par une décision `act` sur un paquet de 64 jetons, où le modèle relit `PLAN.next` et choisit la manière. Coût d'une décision `act`, lot de 32, paquet de 64 jetons, sur la Quadro : **3,6 ms en `small`, 6,5 ms en `base`**, le modèle recommandé (docs/09 § 6.2, colonnes `small` 6,5 M et `base` 17 M) [Mesuré].
- **v2, si la mesure l'exige** : des étapes « scellées » que le moteur enchaîne sans rappeler le modèle. En simulation, les fins de geste prenaient 446 000 décisions sur 490 000 [Mesuré, synthétique, docs/10]. On mesure d'abord la charge réelle avec des conditions d'arrêt longues et des routines (T30 : file P2) ; v2 n'est faite que si le seau déborde (O34).

### 4.2 La vie d'un plan et d'un objectif

```
                 écriture du plan (reflect)
                          │
                          ▼
   ┌──────────────► RUNNING ──étape finie──► réveil P2 : le modèle choisit le geste de l'étape suivante
   │                  │  │                         │ dernière étape finie
   │   le modèle      │  │ le modèle choisit       ▼
   │   rejoue         │  │ un autre geste       DONE ──i_repeat── RUNNING à la période suivante (P2b)
   │   PLAN.next      │  ▼
   │              SUSPENDED   (un réveil P0, P1 ou P3 ne change RIEN tant que le modèle n'a pas choisi un autre geste)
   │                  │
   └──────────────────┘    échec PERÇU sur place ──► BLOCKED : réveil P2, WAKE.outcome = failed ou blocked
                                                     │ le modèle réécrit les étapes, ou écrit
                                                     ▼ g_status = abandoned, ou i_status = abandoned
                                                  ABANDONED (gardé pour la mémoire, puis oublié par la loi d'oubli)
```

Règles du moteur ; aucune ne choisit un geste ni ne tire de conclusion :

- **Reprise** : si le geste décidé et ses cibles sont ceux de `PLAN.next`, le plan passe en `RUNNING` ; si le modèle choisit un autre geste, le plan en cours passe en `SUSPENDED`. C'est la **seule** cause de suspension. Quand le geste choisi à la place se termine, le réveil P2 remontre le plan suspendu (2ᵉ jeton PLAN).
- **Abandon** : seulement par une écriture du modèle (`g_status`, `i_status`).
- **Objectif qui paraît atteint ou perdu** : le moteur ne le constate pas. Quand une valeur dérivée des **croyances du PNJ** change d'état (`g_progress` atteint 1, ou une croyance contredit l'objectif : la cible crue morte, l'objet cru détruit), il émet un réveil `goal_check` ; le modèle relit et écrit lui-même `g_status`. Le catalogue (`goals.toml`) disait que le moteur « constate atteint ou échoué » : c'est corrigé par T08b.
- **Rendez-vous et échéances** : `g_when`, `g_deadline` et les échéances crues des accords (`commitments_seen`) inscrivent un réveil P2b.
- **Routines** : `i_repeat` vaut `once`, `each_day`, `each_season`, `each_year` ou `every`, avec **`i_repeat_period`** (heures de jeu) pour `every` : un tour de garde toutes les 8 h, une réunion tous les 2 jours. Avec D30, une année de calendrier dure environ 4,7 jours de jeu : une « semaine » de 7 jours dépasserait l'année. On compte donc en heures et en jours de jeu, jamais en semaines.
- **Fermeté** : `i_commitment`, écrit par le modèle, filtre les réveils P3 ; il ne filtre jamais P0, P1, P2 ni P2b.

### 4.3 L'exécution continue d'un geste

```
 GestureExecution : PENDING ─► APPROACH (aller vers ce qu'on CROIT : carte mentale, § 4.8) ─► PERFORM (cycles) ─► FINISHED
                                    │                                                        │   ├ le geste finit seul (natural_end)
                                    │ sur place, l'acteur VOIT : rien là, passage fermé       │   ├ condition d'arrêt vraie
                                    ▼                                                        │   └ quantité atteinte (amount)
                                 FAILED (cause perçue) ◄─────────────────────────────────────┘ outil cassé, prise perdue,
                                                                                               matière trop dure, chute
 Toute fin produit un ExecutionReport {npc, gesture, outcome, tick, cause perçue} → réveil P2.
```

- **On n'échoue que sur place.** Un geste ne peut pas échouer à distance sur ce que l'acteur ne perçoit pas. Si la cible a bougé ou disparu hors de sa vue, il va là où il la croit (dernier lieu vu, `LOCUS`) et l'échec (« ce n'est pas là ») n'existe que quand il perçoit l'absence. Une route coupée hors de vue se découvre quand l'obstacle entre dans son champ de vision. L'exécuteur ne lit que ce que `PerceptionSystem` donne à l'acteur ; il ne consulte jamais la vérité pour décider d'un échec (tests en T22 et T23b).
- **Condition d'arrêt**, dans cet ordre : (1) le paramètre `until` du geste, quand il en a un (`strike`, `grab`, `sleep`, `wait`) ; (2) sinon, **la condition d'arrêt de la décision**, une tête du modèle valable pour tout geste qui dure (T11 ; elle ne change la signature d'aucun geste) ; (3) sinon, si `natural_end` est vrai, le geste finit seul (une arrivée, un coup, une gorgée) ; (4) sinon, l'exécuteur s'arrête au bout de la durée `a_while` et rend `limit_reached`. C'est une butée mécanique : elle réveille le modèle, elle ne décide rien.
- **Les conditions se lisent dans la perception de l'acteur**, jamais dans la vérité : « l'arbre paraît tombé ». Ajouts : `c_have` (j'ai au moins N choses de telle sorte, d'après ce que j'ai **vu** dans mes mains, sur moi, dans ce que je porte, ou ce que je **crois** d'un contenant), `c_unwatched` (personne ne paraît me regarder, parmi ceux que je vois), `c_target_near` (la cible paraît à portée).
- **Interruption** : seul le corps interrompt physiquement un geste (un coup reçu déclenche `hit_react`, une chute, l'inconscience, une prise par autrui). Un réveil P0 n'arrête rien : il appelle le modèle (≤ 0,1 s au p95 en simulation), dont la décision remplace ou non le geste.
- **Échec perçu** : `WAKE.outcome` (nouveau) vaut `done`, `failed`, `blocked`, `interrupted` ou `limit_reached`, avec une cause perçue (« la porte ne s'ouvre pas »), jamais une cause invisible (« il faut la clé n° 42 »).
- **Masque de faisabilité** : calculé sur les percepts et les croyances ; ce que le monde refuse échoue physiquement, sur place.
  Règles du masque (T28, `engine/social/tokenizer/mask.h`, lit seulement les tableaux du tokeniseur) : (1) un pointeur n'accepte que les types de dossier que ses `accepts` désignent, et « personne » seulement s'il est optionnel ; (2) un objet que le dossier dit **sans** la propriété demandée par `requires` (drapeau connu, valeur 0) est écarté, une propriété inconnue n'écarte rien ; (3) la partie touchée d'un geste de contact (`party_params`) n'est pas une personne **connue absente** ; (4) elle n'est pas **soi-même** pour `take`, `grab`, `strike`, `push`, `pull` seulement : se toucher, s'examiner, se fouiller, s'attacher (se bander avec un tissu) et se vêtir restent possibles ; soigner un blessé ou un enfant présent n'est jamais masqué ; (5) un geste est faisable si chacun de ses pointeurs obligatoires a un candidat (ou une direction/forme).

### 4.4 Le temps des gestes (P37)

Le jour de jeu dure 1 h 30 réelle (D30), soit 16 s de jeu par seconde réelle ; l'espace n'est pas compressé.

| Quoi | Horloge (`clock` de T07) | Règle | Exemple [Calculé] |
|---|---|---|---|
| Cycle moteur (un coup, un pas, une gorgée) | `real` | `cadence_ms` par geste, compatible avec l'animation | un coup de hache : 900 ms réels |
| Travail sur la matière (couper, labourer, pétrir, forger) | `game` | quantité de travail par cycle × `kTaskCompression` = 16 (le rapport de D30), pour qu'un travail dure en temps de jeu sa durée de la vraie vie | abattre un chêne ≈ 30 min de jeu ≈ 1 min 52 s réelle ≈ 125 coups de 900 ms |
| Dommages au corps | `real`, jamais compressés | un coup de poing reste un coup de poing (`body.toml`) | un combat dure des secondes |
| Processus lents (fermentation, tannage, pousse, cicatrisation) | `calendar` | `nominal_game_s` par processus | bière ≈ 1,5 jour de jeu ≈ 2 h 15 réelles |
| Déplacement | `real` | vitesse réelle (1,3 m/s au pas, clip `walk`) | 1 km ≈ 12 min 50 s réelles ≈ 3,4 h de jeu |
| Durées choisies (`brief`, `a_while`, `long`) | `game` | `[[duration_level]]` : 120 s, 1 800 s, 7 200 s de jeu | 7,5 s, 1 min 52 s, 7 min 30 s réelles |

**Voyages [Calculé, graine 1]** : à pied, le bourg et le village de la montagne (2,9 km) sont à environ 10 h de jeu (37 min réelles) ; la forêt et la mer (17,6 km) à environ 60 h de jeu (2,5 jours). C'est la question O31. Un voyage de 60 h de jeu met les lois des besoins à l'épreuve (faim, sommeil, épuisement) : T21 le teste.

### 4.5 Les processus (lois, jamais choisis)

```
 GestureExecutor ──contact (outil tenu × cible × manière)──► ContactResolver ──► ProcessLaw (cut, split, extract, till…)
 ProcessClock    ──temps écoulé, chaleur, humidité──────────────────────────────► ProcessLaw (cook, ferment, rot, grow…)
                                                        ProcessLaw ─► effets entiers ─► Operation(s)
```

- `ContactResolver` lit **les propriétés** (`cuts`, `impacts`, `digs`, `heats`, `binds`, `abrasiveness`…) de ce qui touche et de ce qui est touché, jamais le nom du geste ni de l'outil. Un objet jamais vu agit par ses propriétés (P28).
- Une `ProcessLaw` par processus de `matter.toml` et `body.toml` (table générée : id, déclencheur, horloge, durée nominale, entrées, sorties) ; le code de chaque loi est écrit à la main, en entiers, et testé contre une table d'exemples tirée du catalogue.
- `kTaskCompression` ne s'applique qu'aux processus `productive`, jamais aux dommages corporels.
- Hasard : `hash3(seed_monde, op_id, k)` (`engine/core/base/hash.h`), jamais `rand()`.

### 4.6 L'opération (format v1)

Toute modification du monde **et** tout acte perceptible passent par une `Operation` (invariant I4 de docs/02, P45). Un geste sans effet matériel (un signe, un regard, une parole) est une `Operation` de sorte `act`, que les témoins perçoivent.

```
 OpHeader v1 (48 octets, petit-boutiste)
   u64 op_id        séquence du monde, jamais réutilisée
   u64 tick         pas de simulation (100 ms réels)
   u32 seq          rang dans le pas : tri par (author, decision_seq, k), donc déterministe quel que soit le fil
   u32 author       EntityId (0 = loi du monde)
   u64 cause        op_id ou decision_id (bit 63 = décision)
   u16 kind         OpKind (registre en ajout seul)
   u16 process      id de processus (registre), 0xFFFF = aucun
   u16 gesture      id de geste (registre), 0xFFFF = aucun
   u8  flags        bit0 voxels, bit1 entités, bit2 champs (eau, feu, chaleur, odeur), bit3 parole
   u8  version      = 1
   u32 payload_bytes
   u8  noise, sight, trace, reserved      perceptibilité (0..10) et sorte de trace laissée
 Charge utile : une suite d'éléments typés
   VoxelEdit   { u8 shape (box | sphere | capsule | list | module), i32 p[7] en voxels, u16 new_voxel (0 = air),
                 u16 only_class (0xFFFF = toutes), u32 changed (rempli par l'applicateur) }
   EntityDelta { u32 entity, u16 var (registre des variables), i32 old, i32 new }
   Spawn       { u32 entity, u16 kind (sorte : objet, espèce), i32 pos_mm[3], u32 holder (0 = au sol) }
   Destroy     { u32 entity }
   Move        { u32 entity, i32 to_mm[3], u32 holder }
   Field       { u8 field, i32 pos_mm[3], i32 amount }
   Act         { u16 gesture, u8 manner[8], u32 target[3] (vérité : pour le moteur et la perception seulement),
                 u32 content (PropRef de la parole ou de l'écrit) }
```

Abonnés du bus, **dans cet ordre fixe** : (1) `EntityStore`, (2) `VoxelOpApplier`, (3) champs (eau, feu, chaleur, odeur), (4) `PerceptionSystem` (témoins), (5) `AgreementBook` (journal des faits qui touchent les parties d'un accord, § 9), (6) `OpJournal`, (7) `Chronicle` (T31b). **Le moteur ne calcule jamais une violation de norme** : la ligne « Propriété et normes » de docs/02 § 4 est remplacée. Le témoin reçoit un EVENT et son modèle juge (D28).

### 4.7 Monde chargé ou non (P46)

| | Chargé (près du joueur) | Non chargé (ailleurs) |
|---|---|---|
| Objets, plantes, bêtes, structures, eau, feu | `EntityStore`, toujours simulé | `EntityStore`, toujours simulé (D19) |
| Voxels | `ChunkCache` : l'opération s'applique tout de suite | `RegionDeltaStore` : l'opération est gardée par région et appliquée au chargement (matérialisation paresseuse) |
| Lire un voxel pour une loi (quel minerai, quelle dureté) | chunk chargé | `SimChunkCache` : `worldgen.generate` à la demande (0,44 ms par chunk, mesuré en conteneur, README de worldgen) plus les deltas ; plafond de 256 Mo [Estimé] |
| Déplacement | carte mentale + évitement dans le champ de vision (§ 4.8) | idem : même règle, sans image |
| Vu de loin | — | `LodPropagator` : une région modifiée salit ses chunks grossiers (un pont détruit se voit de loin) |

### 4.8 Se déplacer avec ce qu'on sait (P51)

On choisit son chemin sur sa **connaissance**, jamais sur la grille vraie.

- **Carte mentale** (`MentalMap`, par PNJ, hors `NpcState`) : les tronçons de route du plan que le PNJ connaît (un bit par tronçon), les tuiles de 256 m qu'il a parcourues (6 104 bits ≈ 763 octets pour 20 km), et ses lieux connus (`LOCUS`, `place_recognized`). Total ≈ 1 Kio par PNJ, 0,5 Mo pour 500 [Calculé]. Elle s'enrichit par la perception (ce qu'il traverse et voit) et par les paroles (« la route du col passe par… » : une croyance, peut-être fausse). La connaissance initiale (le village natal, les routes qu'on prend) est tirée à la création du monde (T47).
- **`RoutePlanner`** : A* sur les routes connues et les tuiles parcourues, vers l'endroit où le PNJ **croit** que se trouve la cible. Au-delà de ce qu'il connaît, il marche dans la direction crue : il explore, et peut se perdre (charte § 3, marches).
- **Évitement local** : la grille d'occupation (32 cm) n'est consultée que **dans le champ de vision de l'acteur**, ce qui revient à voir l'obstacle. Une route coupée plus loin est découverte en arrivant (§ 4.3).
- Même règle hors de vue (D19) : sans image, mais avec la même connaissance.

### 4.9 Persistance des opérations

`OpJournal` ajoute chaque opération à des blocs de 4 096 opérations, avec CRC32. En v1, le journal non compacté est sauvegardé tel quel (section OPLG). La compaction (fusion des `VoxelEdit` matérialisés dans les deltas de chunks, résumé des opérations d'entités) et la `Chronicle` (les opérations marquantes : morts, constructions, destructions, accords publics) arrivent avec T31b. Cible de docs/06 : ≤ 500 Mo après 100 h, à mesurer (T57).

---

## 5. L'ordonnanceur (P43)

### 5.1 Les causes de réveil

`WAKE.cause` garde ses valeurs actuelles (`perception`, `speech`, `request`, `body`, `plan`, `timer`, `routine`) et en gagne trois, ajoutées en fin de liste : `goal_check`, `occasion`, `idle`. `WAKE.trigger` accepte en plus COMMIT, ENTITY et GROUP (élargissement de pointeur, T08b).

| Priorité | Cause | `WAKE.cause`, `WAKE.trigger` | Effet sur le plan |
|---|---|---|---|
| **P0** danger | indice de menace **perçu** : arme sortie près de soi, coup, feu, cri | `perception`, urgence haute ; l'EVENT | aucun : le geste continue jusqu'à la décision (≤ 0,1 s au p95 [Mesuré, synthétique]) |
| **P1** interpellé | on lui parle, une demande arrive | `speech` ou `request` ; HEARD ou REQUEST | aucun |
| **P2** fin d'étape | `ExecutionReport` | `plan` + `WAKE.outcome` ; le PLAN | le plan avance, ou passe `BLOCKED` |
| **P2b** échéance | `g_when`, `g_deadline`, échéance crue d'un accord, période de `i_repeat` | `timer` ou `routine` ; GOAL, PLAN ou COMMIT | le plan suspendu ou terminé est remontré |
| **P3** notable | nouvelle personne, bruit fort, odeur forte (T32) ; **occasion sociale** (ci-dessous) ; **objectif qui paraît atteint ou perdu** d'après ses croyances | `perception`, `occasion` ou `goal_check` ; EVENT, ENTITY, GROUP ou GOAL | aucun ; filtré par `i_commitment`, sauf `goal_check` |
| **P4** battement | rien depuis 8 s (éveillé) ou 60 s (endormi), en temps réel | `idle` | aucun |

**Occasion sociale** : un percept dont l'objet est désigné par l'un des dossiers actifs du PNJ (une personne, un groupe ou un lieu nommé par un GOAL, un PLAN ou un COMMIT) : celui à qui l'on voulait parler entre dans la taverne ; les membres du groupe se rassemblent ; le lieu du rendez-vous est en vue. Le test se fait sur les dossiers du PNJ, jamais sur la vérité. C'est elle qui transforme un plan en action au bon moment.

### 5.2 Le budget

- **Seau** : 200 décisions/s en moyenne (D32), 18 par pas, rafale à 64 quand P0 attend ; oracle : `ai/research/sim_scheduler.py`.
- **Paquets** : 64 jetons pour `act` et `listen`, 128 pour `reflect` ; lots de 32 (action) et 8 (réflexion) (docs/09).
- **Budget de réflexion par PNJ** (option C de docs/10) : il s'ouvre sur une offre reçue, un plan bloqué deux fois, un saut d'émotion de 5 ou plus, un objectif créé, un `goal_check`, une **occasion sociale**, ou le premier sommeil de la nuit (consolidation). Il se dépense pas à pas (`WAKE.budget`, `think_more`).
- **Plancher** (P43) : un PNJ qui a un objectif actif reçoit au moins une suite de réflexion par jour de jeu ; sa longueur suit la profondeur de simulation (charte § 24), jamais le rang (O35).
- **Part visée** : 150 actions et 50 réflexions par seconde (O23).

### 5.3 Déterminisme et classes

- Ordre total : (priorité, tick du réveil, `npc_id`) ; aucun parcours de `unordered_map` dans la simulation.
- Tirage du geste avec une graine propre au PNJ et au compteur de décisions (docs/06 § 2.1).
- Classes : `WakeEvent`, `WakeQueue` (une file par priorité), `TokenBucket`, `ReflectBudget`, `BatchPlanner`, `Scheduler` (`plan_tick() → DecisionBatch`).
- Mesures exposées (T30) : latence p95 entre l'émission d'un réveil et la décision, par priorité ; taux de réveils jamais servis (expirés ou remplacés) ; taille de la file P2.

---

## 6. La perception et le tokeniseur unique

### 6.1 La perception par observateur (P44)

```
 Operation (bus) ─► PerceptionSystem
                      ├ SpatialIndex   grille de hachage 4 m ; candidats à portée (vue ≤ 60 m de jour, ouïe selon le volume)
                      ├ LineOfSight    sur l'occupation grossière (32 cm), lumière, brume, cachettes (conceals)
                      ├ Hearing        volume, bruit ambiant, distance ; un murmure ne passe pas la foule
                      ├ Attention      ce qui est au centre (SELF_STATE.attention) est perçu plus finement
                      ├ PerceptWriter  écrit EntityPercept, Percept, PlacePercept, EventSeen, HEARD dans le NpcState
                      │                de CHAQUE observateur, selon SA finesse et SA maîtrise
                      └ MapWriter      enrichit la carte mentale (§ 4.8) de ce que l'observateur traverse et voit
```

**Pare-feu de la vérité** : `PerceptionSystem` est le seul code qui lit les variables `visibility = engine` d'autrui pour en tirer des percepts, et le seul qui consulte l'occupation vraie (dans le champ de vision, pour l'évitement). Le `Tokenizer` ne lit le `NpcState` qu'au travers d'accesseurs **générés** depuis la table des jetons de `model_interface.json`. Un test statique le vérifie (T28). Les identifiants objectifs (`r_true_entity`, `m_fact_ref`, `b_origin_fact`, `b_truth`) restent au moteur.

### 6.2 Le tokeniseur C++

- Port de `ai/tok2` (oracle Python), avec parité exacte sur les cas d'or et sur 10 000 situations du sampler (T28).
- `FeasibilityMask` : calculé sur les percepts et les croyances, d'après les `requires` des gestes.
- `CandidateSelector` : candidats bornés (64 croyances, 32 souvenirs, 24 personnes, docs/10) ; saillance simple d'amorce, en attendant la tête « sélecteur ».
- **API C** (`engine/capi/emergence_capi.h`) et liaison Python par `ctypes` : `em_world_create`, `em_world_step`, `em_world_apply`, `em_world_save`, `em_world_load`, `em_tokenize`. Un seul tokeniseur, en jeu et pendant DAgger.
- **DecisionRecord v1** : une ligne au format de `ai/teacher/dataset.py`, avec `source = "engine"`, le tick, la cause du réveil, les sorties et les verdicts du gouverneur.

### 6.3 La parole entre les esprits (`SpeechRouter`, T24)

- **Traduction d'une personne** : un pointeur du locuteur est traduit par le **nom que le locuteur donne à son dossier**, jamais par `r_true_entity`. L'auditeur reçoit son propre dossier du même nom (le plus ancien), sinon un nouveau référent « celui qu'il appelle Aldric » (`r_known_by = name_only`, `r_true_entity = 0`). Un locuteur qui se trompe de personne transmet donc sa croyance, pas la personne. C'est la lettre voulue de docs/15 T24 : le nom sert à retrouver le dossier de l'auditeur, la vérité n'entre jamais.
- **Référents sans nom** : le routeur garde, par auditeur, le dernier dossier créé par locuteur et par pointeur (32 au plus, cache non sauvé) et le réutilise ; un inconnu qui parle à chaque pas ne recrée pas de dossier.
- **Refus D10** : `d10_hearer` et `d10_intimate` trahissent qu'un auditeur peut être mineur. Ils restent dans le **journal du moteur** (`SpeechRefusal`) ; ils ne sont **jamais** renvoyés au modèle ni écrits dans une mémoire. Un test vérifie qu'une parole refusée ne modifie aucun esprit.

---

## 7. L'état des PNJ : sauvegarde, oubli, tables annexes, compactage

### 7.1 Mesure et cible

[Mesuré] 108 152 octets par PNJ. [Calculé] après compactage (sonde sur `npc_state_gen.h` : `Proposition` remplacée par une référence de 4 octets, champs triés par alignement, 4 octets de numéro par enregistrement) :

| Partie | Aujourd'hui | Après |
|---|---|---|
| Croyances (384) | 64 512 | 19 968 |
| Relations (96) | 17 664 | 7 296 |
| Souvenirs (128) | 18 432 | 5 632 |
| Le reste | 7 544 | 2 898 |
| **Partie fixe** | **108 152** | **35 794** |
| Arène des propositions (budget fixe) | — | 20 480 |
| Table annexe ListRef (budget fixe) | — | 8 192 |
| **Total** | 108 152 | **64 466 ≤ 65 536** |

Les ajouts de T08b (3 intentions de plus, 2 champs de groupe) restent à mesurer. La carte mentale (≈ 1 Kio) se compte à part. L'arène de 20 Kio tient environ 4 096 symboles, soit 6,5 symboles en moyenne si les 625 emplacements de propositions sont pleins [Calculé] ; la longueur réelle se mesure en T06. Arène pleine : c'est la loi d'oubli qui libère.

### 7.2 Des identifiants qui ne bougent pas (P39, T02 fait)

Gestes et conditions dans l'ordre de `ai/student2/output_registry.json`, mots et sortes dans l'ordre de `ai/tok2/registry.json`, variables dans `catalogue/generated/var_registry.json` (358 entrées) ; une entrée retirée garde son numéro.

### 7.3 La table annexe (ListRef, T03 fait)

`SideTable` par PNJ : un tableau de `u32` avec préfixe de longueur ; `ListRef` = décalage + 1 (0 = vide), avec des bits de génération qui détectent une référence périmée ; budget fixe de 8 Kio ; troncature déclarée par variable.

### 7.4 L'arène des propositions

`PropRef` (u32) vers une `PropositionArena` par PNJ ; la `Proposition` de 20 symboles reste le type d'échange (décodeur, gouverneur, langue).

### 7.5 La loi d'oubli, déclarée dans le catalogue (P42)

```toml
[[forgetting]]
record = "episode"                         # une sorte d'enregistrement (entities.toml, max_count)
protect = ["m_defining"]                   # épargné tant que vrai (voir ci-dessous)
score = [                                  # score entier ; le plus bas est oublié ; égalité : le plus ancien
  { var = "m_importance", weight = 40 },   # 4 points de 1000 (unipolar10 : x10)
  { var = "m_vividness",  weight = 20 },
  { var = "m_rehearsals", weight = 100, cap = 10 },   # une qty est toujours plafonnée : 1 point = 1000 / cap
  { var = "m_when", weight = 30, kind = "recency", half_life_seasons = 4 },   # m_when est un HORODATAGE
]
```

Trois règles (corrections du 15 oct. 2026) :

- **Capacité fixe en v1** : c'est le `max_count` du composant. L'ancien champ `capacity_from` est retiré (la variable `memory_store_capacity` est dérivée, en milli-unités, et rien ne la calcule : la rendre effective demande une loi de la mémoire par PNJ, hors v1).
- **Échelles comparables** : chaque terme pèse 1 à 10 « points » de 1000 au maximum ; le poids écrit est le nombre de points x 1000 / l'étendue de la variable (unipolar10 x10, ratio x1, bool x1000, récence x10, qty : 1000 / cap). Un terme qui n'est pas un nombre entier de points est refusé par `check.py`. Les variables lues par une récence sont des horodatages (`dynamics` le dit) : plus la valeur est petite, plus c'est ancien.
- **Une réserve dont tous les enregistrements sont protégés ne refuse plus l'ajout** (décision de Monsieur, 15 oct.) : `RecordPool::add` évince le moins bon des enregistrements protégés (même score, égalité = le plus ancien) et le compte (`evicted_protected()`), pour que le PNJ ne cesse jamais de former des souvenirs. `add(rec, now)` n'a pas de valeur par défaut pour `now`.

`check.py` refuse un score qui lit `b_truth`, `b_origin_fact`, `m_fact_ref` ou `r_true_entity`. `gen_cpp` génère `score(kind, record)` en entiers ; un oracle Python (`catalogue/tools/forgetting.py`) sert à la parité.

### 7.6 La sauvegarde versionnée (P40)

```
 Fichier EMSV v1 (petit-boutiste)
   "EMSV" | u16 version = 1 | u16 flags | u64 world_seed | u32 plan_version | u32 chunkgen_version
   | u64 catalogue_fp | u64 tok2_registry_fp | u64 output_registry_fp | u64 var_registry_fp | u64 sim_tick | u32 n_sections
 Section : u32 tag | u16 version | u16 flags | u64 length | u32 crc32 | octets
   NAME  tables de noms (gestes, conditions, variables, mots, sortes, processus, matières)   T04
   NPCS  état des PNJ : composants, réserves, SideTable, arène, WriteLedger, carte mentale       T04, T23b
   ENTS  EntityStore (T15)       OPLG  journal non compacté (T16)      REGN  deltas de chunks (T17)
   CLCK  horloges (T31)          AGRM  accords et leur journal de faits (T25)                  REFS  référents (T35)
   CHRN  chronique : section ajoutée par T31b ; un lecteur v1 ignore une section inconnue et la compte
```

Relecture **par noms** : une colonne inconnue est ignorée et comptée ; une colonne absente prend sa valeur initiale ; un changement de sens est refusé, sauf un élargissement (`i16` → `i32`) ; CRC faux = section refusée. Le `WriteLedger` est restauré avec l'horloge du moteur. Aucune copie brute de structure.

---

## 8. Les interfaces entre couches

### 8.1 Modules et sens des dépendances

```
 catalogue/ (données) ──génère──► engine/social/generated, var_registry.json ; lus par tous les modules C++
 engine/core   (base, world, mesh)      monde voxel, plan, chunks, ChunkCache           ◄── existant
 worldgen/                              chunks depuis la graine ; villages (T44-T46)     ◄── existant
 engine/ops    (nouveau)                Operation, OperationBus, OpJournal, VoxelOpApplier, RegionDeltaStore, LodPropagator, Chronicle
 engine/act    (nouveau)                EntityStore, ProcessEngine, ContactResolver, GestureExecutor, PerceptionSystem,
                                        MentalMap, RoutePlanner
 engine/social (existant, étendu)       NpcState, SideTable, PropositionArena, Language, Governor, Tokenizer, Scheduler, NpcLaws,
                                        PlanExecutor, DecisionApplier, MindWriter, SpeechRouter, AgreementBook, Referents, NpcStateCodec
 engine/save   (nouveau)                SaveContainer (EMSV), sections
 engine/capi   (nouveau)                API C pour Python (développement, DAgger) ; InferenceBackend
 engine/infer  (nouveau, fusion)        TrtRtxBackend
 engine/gdext  (existant, étendu)       EmergenceSim, NpcPresenter, AnimationMap (présentation : lit, n'écrit jamais)

 Sens permis : social → act → ops → core ; act → core (lecture) ; gdext → tous (lecture d'instantanés) ;
 interdit : core → ops, ops → social, gdext → écriture directe du monde (toute écriture passe par une Operation).
```

### 8.2 Classes et responsabilités

| Module | Classe | Responsabilité (une seule) |
|---|---|---|
| social | `SimulationHost` | possède les modules, avance le pas fixe, publie les instantanés |
| social | `NpcStore`, `NpcState` (généré) | état des PNJ ; adresses stables |
| social | `SideTable`, `PropositionArena` | données de taille variable d'un PNJ |
| social | `ForgettingLaw` (générée) | score d'oubli par sorte d'enregistrement |
| social | `NpcLaws` | dynamiques `writer = engine` : besoins, retours lents, familiarité, maîtrise, netteté |
| social | `Language` | analyser et typer la langue intérieure (port de `language.py`) |
| social | `Governor`, `WriteLedger` | borner, refuser, D10 ; plus `check_utterance`, `check_record` (T14) |
| social | `Tokenizer`, `FeasibilityMask`, `CandidateSelector` | dossier de 64 ou 128 jetons, masque, candidats |
| social | `Scheduler` et ses parties | qui pense, quand, combien ; mesures de latence |
| social | `DecisionDecoder`, `DecisionApplier` | sorties brutes → appel de geste, écritures, parole, plan ; application après le gouverneur |
| social | `MindWriter` | crée et modifie les enregistrements ; appelle la loi d'oubli |
| social | `SpeechRouter` | une parole → HEARD chez chaque auditeur, pointeurs traduits vers SES dossiers |
| social | `AgreementBook` | enregistre l'accord (parties, proposition, échéance, témoins, forme), journalise les faits qui touchent ses parties, réveille à l'échéance ; **ne juge jamais** s'il est tenu (§ 9) |
| social | `Referents` | référents de groupe et de rôle : création en parlant, `s_last_believed`, archivage |
| social | `PlanExecutor` | réserve d'intentions, états du plan, réveils P2, P2b et `goal_check` |
| social | `NpcStateCodec` | section NPCS de la sauvegarde |
| act | `EntityStore` | entités non voxel ; composants générés depuis les variables du monde |
| act | `GestureExecutor`, `GestureExecution`, `GestureTiming` | machine à états d'un geste ; `ExecutionReport` ; échec seulement sur place |
| act | `ContactResolver`, `ProcessEngine`, `ProcessLaw`, `ProcessClock` | lois de la matière et du corps |
| act | `PerceptionSystem` et ses parties | percepts par observateur ; réveils P0, P1, P3 |
| act | `MentalMap`, `RoutePlanner` | ce que le PNJ sait des chemins ; itinéraire sur cette connaissance |
| ops | `Operation`, `OperationBus`, `OpSubscriber` | format v1, publication, ordre des abonnés |
| ops | `VoxelOpApplier`, `RegionDeltaStore`, `LodPropagator`, `SimChunkCache` | voxels chargés ou non, niveaux grossiers |
| ops | `OpJournal`, `Chronicle` | journal ; compaction et histoire du monde (T31b) |
| save | `SaveContainer`, `SectionWriter`, `SectionReader` | fichier EMSV |
| capi | `InferenceBackend` (interface), `PythonBridgeBackend`, `RandomBackend` | le modèle vu du moteur |
| gdext | `EmergenceSim`, `NpcPresenter`, `AnimationMap` (générée), `PropAttacher` | présentation |

**Règles orientées objet** : une interface abstraite seulement là où il y a au moins deux implémentations (`InferenceBackend`, `OpSubscriber`, `ProcessLaw`) ; pas de variable globale ; un module ne touche l'état d'un autre que par son API publique ou une `Operation` ; les tables viennent du catalogue, jamais d'un `switch` écrit à la main sur des noms.

**Règles de déterminisme** : entiers et Q16, `-fno-fast-math` (`emergence_strict_target`), hasard par hachage, ordre total des opérations et des décisions. L'inférence GPU en float16 est la seule source non entière : le même PNJ donne les mêmes bits dans deux lots différents [Mesuré, docs/09 § 6.2, un couple de lots]. Les tests d'empreinte utilisent `RandomBackend`.

### 8.3 Les formats versionnés

| Format | Version | Où |
|---|---|---|
| Interface du modèle | `model-interface-2` → 3 (tête de plan, arrêt de décision, `WAKE.outcome`, causes ajoutées) | `catalogue/generated/model_interface.json` |
| Registre des entrées | `tok2-registry-2` (ajout seul) | `ai/tok2/registry.json` |
| Registre des sorties | `student2-output-registry-1` → 2 (liste `plan_steps`, tête d'arrêt de décision) ; changement de forme, donc **point de contrôle versionné et chargeur partiel** (T11) | `ai/student2/output_registry.json` |
| Registre des variables | `var-registry-1` | `catalogue/generated/var_registry.json` |
| Operation | v1 (§ 4.6) | `engine/ops` |
| Sauvegarde | EMSV v1 (§ 7.6) | `engine/save` |
| AnimationCue | v1 (§ 8.4) | `engine/act` → `engine/gdext` |
| AnimationMap | `animation-map-1` | `catalogue/data/animation.toml` (nouveau) |
| DecisionRecord | v1 = lignes de `dataset.py`, `source = "engine"` | `ai/teacher/dataset.py` |
| ScenarioSpec | `scenario-1` (§ 10.2) | `ai/scenarios/schema.json` (nouveau) |
| Réponse du professeur | `teacher-answer-2` (§ 10.1) | `ai/teacher/schema.py` |

### 8.4 Vers les animations (P38)

- **La simulation commande, l'animation suit** : le lecteur étire le clip pour que son `impact` tombe au tick de l'`Operation`. Cela amende `interfaces.md` § 7 (là, l'`impact` du clip déclenchait l'opération) : un PNJ hors de vue n'a pas d'animation et doit agir au même rythme (D19).

```
 AnimationCue v1 (48 octets, petit-boutiste) : u32 npc | u64 tick | u16 clip (registre des clips)
   | u8 phase (enter, loop, once, exit, stop) | u8 layer (corps, haut du corps, visage) | i32 speed_q16 | u32 duration_real_ms
   | u32 impact_real_ms (0xFFFFFFFF = aucun) | u32 target_entity | u16 prop_right, prop_left (sorte d'objet tenu) | i32 target_pos_mm[3]
```

- `AnimationMap` (générée depuis `catalogue/data/animation.toml`) : pour chaque geste, des règles sur la manière et les propriétés de l'objet tenu → un clip et sa vitesse. Par exemple `strike` + `open_hand` → `slap` ; `strike` + `held` + objet qui `digs` → `swing_pickaxe` ; `go` + `run` → `run` ; `discreet` → `sneak`. C'est de la présentation : elle n'entre pas dans l'état de simulation.
- **D10, défense en profondeur** : `NpcPresenter` refuse `kiss`, `lean_in` ou un `embrace` de manière romantique si une des deux parties n'est pas un adulte connu (test en T53).

---

## 9. Les organisations : tout en variables

Rien d'institutionnel n'est une classe C++ : une mairie, une guilde, une milice, une église ou un marché sont des personnes reliées par des croyances (`member`, `leads`, `holds`, `may`, `custom`, `owns`), des accords et des attitudes envers le groupe. Les vues calculées (`legitimacy`, `group_cohesion`, `role_holder_support`, `recognized_members`, `unrest`) servent à la chronique et aux mesures, jamais aux jetons.

| Une organisation doit pouvoir… | Ce qui existe | Ce qui est ajouté ou décidé |
|---|---|---|
| **se former** | référent créé en le nommant ; `us` figé à la parole ; accord avec un groupe pour contrepartie | rien |
| **se structurer** | `holds` + `s_scope`, `may`, `leads` | un groupe peut être **membre d'un groupe** (élargissement de `member`) |
| **décider** | paroles, vote = `sign raise_hand`, comptage perçu (`EVENT.count`), coutume de décision, croyance `(intends @G …)` | rien |
| **répartir les tâches** | demande puis acceptation = accord ; `GOAL.origin = role / asked / agreement` | **`GROUP.my_task`** (`r_group_my_task`) : l'accord que je crois avoir envers ce groupe |
| **tenir ses effectifs** (le chef) | 4 membres dans un jeton GROUP, 3 accords en COMMIT | **(b)** deux champs dérivés de SES croyances : `r_group_tasks_open` (combien de tâches je crois en cours) et `r_group_present` (combien je crois présents) ; le chef résume ses effectifs par des écritures (`(count (of member @G) 12)`), que le sélecteur retrouve ; si la sonde d'expédition (T40, 10 à 20 membres) échoue, on montera à 8 le nombre de membres montrés au chef d'un groupe |
| **tenir des biens communs** | `owns @G T`, `custody_log`, `may`, lieu possédé par un groupe | **(e)** registre réconciliable : un registre est un objet écrit (`tally_stick`, `book`, `wax_tablet`) que l'on lit et réécrit (`write`, `read`) ; on le confronte à ce qu'on voit en inspectant (`examine`, `search`, `c_have`) ; aucun compte n'est tenu par le moteur pour le groupe |
| **se réunir à date fixe** | `at_time`, `each_day`, `each_season`, `each_year` ; accords périodiques | `i_repeat = every` + `i_repeat_period` |
| **durer après la mort d'un chef** | le rôle est un référent ; succession par croyances et coutumes | rien |
| **se dissoudre** | croyances qui changent ; accords déliés ou caducs | cycle de vie du référent : `s_last_believed` ; **archivé après une saison de calendrier entière** (1 h 45 réelle, D30) sans qu'aucun dossier de PNJ vivant ne le désigne |
| **saisir l'occasion** | — | **(d)** le réveil `occasion` (§ 5.1) ouvre un budget de réflexion |

**(a) Comment un accord est vérifié (P50, décidé avant T25).** Un accord est une proposition de la langue intérieure, et rien n'est écrit à la main pour la vérifier.
- `AgreementBook` garde les parties, la proposition acceptée, l'échéance, les témoins et la forme. Il **journalise les faits objectifs** qui touchent les parties et les choses nommées dans la proposition : chaque `Operation` dont l'auteur, la cible ou l'objet est l'un d'eux.
- Le moteur ne tient que des états de fait : `open`, `expired` (l'échéance est passée : un fait du temps), `released` (le bénéficiaire l'a dit : un fait de parole), `void` (une partie est morte : un fait).
- **Tenu ou rompu** est un jugement : chaque partie et chaque témoin l'écrit dans ses croyances (`(kept c:2)`, ou l'interprétation `broken_promise`), à la lumière de ce qu'il a perçu. À l'échéance, les parties sont réveillées (P2b, déclencheur COMMIT).
- `commitments_seen` se tire de ces croyances. Les valeurs `fulfilled` et `broken` de `a_status` sont retirées du moteur (T08b).
- La mesure M5 (engagements tenus) est faite par un évaluateur **d'entraînement seulement**, qui lit le journal de faits (CLAUDE.md : un évaluateur peut lire la vérité pendant l'entraînement, jamais en jeu).

**(c) La réserve de 4 intentions** est mesurée : distribution du nombre de plans actifs par PNJ, et part du temps passé à 4 (T30, T40). On l'élargit si cette part dépasse 10 % [Hypothèse].

**(f) Mesures d'émergence, sans cible imposée** (T30 en une journée, T57 sur une année) : groupes nommés par un PNJ ; leur durée de vie (en saisons) ; le nombre de membres crus par au moins deux PNJ ; les groupes qui ont un titulaire de rôle ; les accords de groupe, et la part que l'évaluateur d'entraînement juge tenue ; les objectifs à sous-objectifs ; les plans de plus de 3 étapes menés au bout. Ces chiffres se rapportent ; ils ne se règlent pas (charte § 28).

---

## 10. Les données du professeur : transférer la psychologie humaine

Précision de Monsieur (14 oct.) : le but de Gemini, et de tous les modèles Gemini et Gemma disponibles, est de **transférer sa connaissance de la psychologie humaine** au Transformer, au moyen d'un format de sortie strict. On lui demande de **se comporter en humain** face à des cas venus du jeu (sampler, puis le moteur en DAgger) ou inventés par Gemini.

### 10.1 La consigne « humain planificateur » et la trace de pensée (T36)

**Consigne** : « Tu es cette personne. Avec ce passé, ces liens, ces buts et ce que tu perçois, que ferait un vrai être humain ? Pense d'abord comme lui : ce qu'il croit, ce qu'il veut, comment il compte s'y prendre. Puis agis. » Le tempérament du village module la consigne (docs/12) ; D10 et les bornes restent dans la consigne et dans le gouverneur.

**Réponse `teacher-answer-2`** (JSON structuré ; `why` reste jeté) :

```json
{"decisions": [{"id": "S1",
  "why": "≤ 25 mots, jeté",
  "thoughts": [
    {"kind": "belief",       "target": "new", "prop": "(…)"},
    {"kind": "belief_about", "target": "new", "prop": "(believes @E3 (…))"},
    {"kind": "goal",         "target": "new", "prop": "(achieve …)", "parent": "g:2", "deadline_h": 24, "when_h": 6},
    {"kind": "plan", "serves": "g:new", "steps": [{"gesture": "go", "target": "@L2"}, {"gesture": "speak", "target": "@E3"}],
     "says": "(offer …)", "repeat": "once"}
  ],
  "gesture": "go", "params": [{"name": "target", "value": "@L2"}], "until": "(c_reached @L2)",
  "speech": null, "writes": []}]}
```

- **0 à 5 pensées**, chacune écrit **un** dossier. Le convertisseur rejoue les écritures sur le dossier mental, ré-encode en tok-2 après chaque pas, et produit k exemples `reflect` (avec `think_more` = 1 sauf au dernier), plus 1 exemple `act`.
- **Filtre `incoherent_trace`, contradictions formelles seulement** : la réponse écrit un plan, son acte n'est pas la première étape de ce plan, **et** ni le geste ni sa cible n'apparaissent dans aucune pensée de la même réponse, **et** le réveil n'est pas P0 ni P1. Tout le reste passe. La cohérence au sens large (l'acte sert-il le but ?) **se mesure sans rejeter** (M2, T40).
- **Listes écrivables** : `i_steps`, `i_step_targets`, `i_speech`, `i_repeat`, `i_repeat_period`, `g_parent` ; chaque étape passe par `check_gesture` (D10) et chaque proposition par `check_record`.
- **Passivité** : la part de gestes passifs (éveillé, de jour, sans urgence) est suivie par professeur. Seuil d'alerte provisoire : **≤ 30 %** [Hypothèse]. Le chiffre mesuré de 44 % porte sur 18 décisions, trop peu pour conclure. Un villageois éveillé, de jour et sans urgence travaille, parle ou va quelque part la plupart du temps ; une pause ou une attente (`rest`, `wait`, `look`) reste légitime, et l'inaction est observable (charte § 20). 30 % laisse une large place aux pauses. On le mesure sur au moins 300 décisions avant de juger un professeur ; ce n'est jamais une règle du jeu.

### 10.2 Le second flux : des scénarios inventés (T37, T38)

```
 Gemini/Gemma « auteur » ─► ScenarioSpec v1 (JSON structuré, vocabulaire fermé du catalogue)
        │ (voit et écrit la VÉRITÉ du scénario)
        ▼
 Contrôles : schéma → vocabulaire → langue → plausibilité (âges, liens, métiers, objets)
           → D10 (audit + gouverneur ; tout le scénario est rejeté, jamais réparé) → dé-duplication → quotas par famille
        ▼
 Convertisseur ─► une Situation par personne « focus » : son dossier mental contient SEULEMENT ce qu'elle a perçu
        │          (witnessed_by) ou appris (chaîne told), avec des croyances parfois fausses ; encodage tok-2
        ▼
 Professeur « étiqueteur » ─► voit le rendu du DOSSIER (teacher.render), jamais le texte du scénario
        ▼
 dataset.jsonl (source = "scenario", famille, auteur, étiqueteur)
```

**Familles de STRUCTURE, pas d'intrigues nommées** (D28, charte § 28). L'auteur reçoit une structure et invente le reste :

| Famille | Structure demandée | Part |
|---|---|---|
| but lointain | un objectif qui demande plusieurs jours et des sous-objectifs | 15 % |
| coopération | un objectif qu'on ne peut atteindre qu'avec d'autres, rôles à répartir | 15 % |
| conflit | deux personnes ou groupes dont les buts s'excluent | 10 % |
| dette et échange | une obligation en cours, une dette, un échange inégal | 10 % |
| information inégale | un secret, une rumeur, une croyance fausse chez l'un | 10 % |
| autorité et appartenance | un rôle contesté, une règle d'un groupe, une loyauté partagée | 10 % |
| deuil et perte | une perte récente qui change les buts | 10 % |
| rareté et saison | une ressource qui manque, une échéance de saison | 10 % |
| vie ordinaire | rien d'urgent : travail, voisins, famille | 10 % |

Les histoires nommées de `stories.toml` (maison, guilde, complot, expédition…) **restent des sondes de mesure** ; elles ne servent ni de consigne à l'auteur ni de quota.

**ScenarioSpec v1** (abrégé) :

```json
{"schema": "scenario-1", "family": "cooperation",
 "setting": {"village": "forest_village", "site": "tavern", "time": "evening", "season": "winter", "temperament": 7},
 "people":  [{"key": "P1", "age": 34, "sex": "female", "occupation": "t_smithing",
              "traits": {"patience": -6}, "values": {"honor": 7}, "needs": {"hunger": 3}, "emotions": {"anger": 2}}],
 "groups":  [{"key": "G1", "kind": "g_guild", "members": ["P1", "P3"], "leader": "P3", "goal": "(…)"}],
 "links":   [{"a": "P1", "b": "P2", "link": "spouse", "a_to_b": {"trust": 3, "affection": 5}}],
 "things":  [{"key": "T1", "kind": "silver_coin", "holder": "P2", "owner": "P2", "place": "here"}],
 "facts":   [{"key": "F1", "prop": "(did P2 take T1)", "when_h": -30, "witnessed_by": ["P4"],
              "told": [{"from": "P4", "to": "P1", "when_h": -5}]}],
 "agreements": [{"parties": ["P1", "G1"], "prop": "(…)", "deadline_h": 48, "witnesses": ["P3"]}],
 "goals":   [{"who": "P1", "prop": "(…)", "priority": 7, "deadline_h": 72, "parent": null}],
 "focus":   ["P1", "P3"]}
```

- **Pas de fuite de vérité** : seul le convertisseur fait passer un fait dans un esprit, par `witnessed_by` ou une chaîne `told`. Les clés `P/T/G/L` sont réécrites en `@E/@T/@G/@L` propres à chaque observateur.
- **Plausibilité** : règles de `situations/scene.py` ; appel « critique » facultatif, de 0 à 10, seuil 6.
- **Diversité** : quotas du tableau ci-dessus, tempérament uniforme de 0 à 10, lieux selon `sites.toml`, de 2 à 10 personnes, toutes les tranches d'âge.
- **Dé-duplication** : empreinte canonique (fnv1a64, sans noms) et MinHash ; rejet à une similarité de Jaccard ≥ 0,8.
- **Mélange** : au départ 60 % sampler, 40 % scénarios ; avec DAgger, 50 % moteur, 30 % scénarios, 20 % sampler ; au moins 30 % d'exemples en réflexion.

### 10.3 Plusieurs professeurs (T39)

- **Jeu d'étalonnage** : 300 situations, étiquetées par chaque modèle disponible.
- **Accord** : kappa de Fleiss sur la famille du geste ; accord sur la cible ; signe des écritures ; structure de la trace.
- **Biais par professeur** : passivité, violence, parole ; longueur des traces ; amplitude des écritures ; **pente du tempérament** ; refus D10 ; réparations ; invalides.
- **Juge** : le modèle le plus fort compare 200 paires à l'aveugle.
- **Règle de mélange** : poids = validité × victoires chez le juge × accord avec le consensus. Exclusion si validité < 90 % ou victoires < 35 % [Hypothèse]. **Aucun professeur au-delà de 50 %** des données. Quand ils divergent, les deux étiquettes sont gardées (cible douce).

### 10.4 Évaluer la planification (T40)

| N° | Mesure | Comment |
|---|---|---|
| M1 | plans menés à terme | objectifs dotés d'un plan qui finissent `achieved`, **écrit par le modèle**, à 1 et 3 jours de jeu, par famille de structure |
| M2 | cohérence but-étapes | une table « prédicat de l'objectif → gestes compatibles », **pour la mesure seulement** : elle vit dans `ai/research/plan/`, et un test interdit de l'importer ailleurs ; plus un juge LLM sur un échantillon |
| M3 | coalition | `probe_coalition.py` refait avec le vrai tok-2, puis en boucle fermée sur le moteur |
| M4 | replanification | échecs injectés sur place (chemin bloqué, outil cassé) : part des plans révisés, abandonnés, ou bloqués en boucle (même étape ratée plus de 3 fois) |
| M5 | engagements tenus | évaluateur d'entraînement seulement, sur le journal de faits des accords (§ 9 a) |
| M6 | persistance | un plan actif revient-il dans PLAN après k décisions intercalées ? |
| M7 | profondeur | part de `reflect`, longueur des suites, part des actes égaux à `PLAN.next`, saturation de la réserve de 4 plans |
| M8 | passivité | part de gestes passifs, éveillé, de jour, sans urgence |

Cibles provisoires pour T41, **[Hypothèse]** : M3 ≥ 90 %, M1 ≥ 60 % pour les objectifs faisables, M4 (boucles bloquées) ≤ 5 %.

### 10.5 Ce qui change dans le sampler (T12)

Le sampler gagne :
- les causes `plan` (fin d'étape), `timer` (échéance), `goal_check` et `occasion` ;
- au moins 30 % de situations en `reflect` ;
- plusieurs PLAN, des objectifs avec parent, des routines (dont `every`) ;
- des dossiers GROUP avec `my_task` et les effectifs crus ;
- des accords envers des groupes ;
- les **familles de structure** du § 10.2.

Il construit des situations ; il ne décide jamais.

---

## 11. Écarts relevés dans les documents existants

| Document | Écart | Correction |
|---|---|---|
| `catalogue/ETAT.md` | 95,5 Ko par PNJ | 108 152 octets mesurés (après 19a) |
| `catalogue/data/goals.toml` (`g_status`) | « le moteur constate atteint ou échoué » | le moteur réveille (`goal_check`) ; le modèle écrit (T08b, P35) |
| `catalogue/data/goals.toml` (`a_status`) | le moteur tient « tenu » et « rompu » | le moteur ne tient que `open`, `expired`, `released`, `void` ; tenu ou rompu se juge (T08b, P50) |
| `docs/interfaces.md` § 1 | « 1 jour de jeu = 4 h réelles (P14) » | D30 : 1 h 30 ; version 0.5 (T42) |
| `docs/interfaces.md` § 6-7 | contrat de 112 fonctions ; l'`impact` du clip pilote l'`Operation` | gestes du catalogue ; la simulation pilote l'animation (P38) |
| `docs/02` § 4 | le moteur calcule la violation de norme pour les témoins | le témoin juge (D28, P45) |
| `docs/06` § 2.3 | « déplacements sur la navigation », sans dire sur quelle connaissance | navigation sur la connaissance du PNJ (P51) |
| `stories.toml`, `farm_cycle` | « take/pull n'acceptent pas plant » | ils l'acceptent depuis 19a ; il manque `take.from = growing` |
| `docs/10` § 6.3, `interfaces.md` § 6 | `interrupt_if` (3 conditions) dans le plan | réveils filtrés par `i_commitment` ; le modèle décide |
| `ai/teacher/README.md` | les listes ne sont pas écrivables par le professeur | elles le deviennent (T11, T36) |
| `docs/10`, `docs/09` | 4 650 cas de parité du gouverneur | 8 006 (comptés le 15 oct.) |

## 12. Décisions et questions

Décisions P35 à P51, questions O31 à O39 : `docs/01_decisions.md`.
