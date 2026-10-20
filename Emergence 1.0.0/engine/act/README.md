# engine/act : le monde non voxel (T15)

`EntityStore` : objets, plantes, bêtes, structures, eau, feu, lieux. Applier du bus d'opérations (`engine/ops`), il ne change que par
`Spawn`, `Destroy`, `Move`, `EntityDelta` (builders : `entity_ops.h`). Identifiant = 22 bits de case + 10 bits de génération ; une case
qui épuiserait sa génération est retirée (jamais d'id ambigu). Composants générés par `catalogue/tools/gen_cpp.py` dans
`generated/emergence/act/world_gen.h` (`provenance`, `transformation`, ...), ids stables dans `catalogue/generated/world_registry.json`.
Position (mm) et contenant vivent dans l'enregistrement de l'entité, pas dans un composant. Itération, sérialisation et empreinte vont
par numéro de case. Tests : `test_entity_store` ; banc : `bench_entity_store [n]`.

## Lois de la matière 1 (T18)

`contact_resolver.*` : quelles entités se touchent (qui repose sur qui, charge portée, marge) et avec quelles propriétés
(`cuts`, `impacts`, `digs`, `binds`, `sharpens`, `graspable`, lues dans les parties, jamais dans un nom d'outil).
`process_engine.*` + `laws/` : `cut`, `split`, `fracture`, `crush`, `carve`, `disassemble`, `extract`, `till`, `assemble`, `bind`,
`abrade` (sur contact) et `collapse` (horloge réelle : marge de charge, effondrement, chute). Le moteur ne modifie rien : il rend des
`Emission` (Operation + clés d'ordre) que l'appelant remet au bus. Terrain voxel : `extract` / `till` rendent une `VoxelRequest`.
Tables : `catalogue/tools/gen_matter.py` (`--check`) → `generated/emergence/act/matter_gen.h`, ids dans `catalogue/generated/matter_registry.json`.
Tests : `test_matter_laws` ; banc : `bench_matter_laws [n]` (processus/s). Limites : positions et tailles en cube dérivé de la masse
si la fiche n'en donne pas ; l'usure de l'outil et l'intégrité d'un objet n'ont pas encore de variable (T20 `wear`).

### Limites et dette de T18 (à lire avant de s'appuyer dessus)

- `sort` d'une entité = indice de son id dans `kKinds` (`vocab_registry.json`), produit par `gen_matter.py` ; le registre `matter_registry.json` ne sert qu'aux index internes.
- Les chutes sont INSTANTANÉES : l'entité est téléportée à la hauteur d'atterrissage (un seul `Move`), sans énergie transmise à ce qu'elle heurte et sans cascade dans le pas ; la suite se joue aux pas suivants.
- `tick_time` scanne tout le monde à chaque tick (mesuré : 4 ms pour 20 000 corps ici, environ 25 ms pour 100 000) : prévoir des régions sales avant la charge cible.
- Un corps de plus de 64 cellules (64 m) sur un axe n'est indexé que sur ses 64 premières cellules (c'est du terrain, pas une entité). Les valeurs hostiles sont saturées (100 t, 100 m, 100 m/s, 10 km de chute) ; fiche invalide : matière inconnue = aucune matière.
- Conflit sur une même cible : l'ordre est un hachage de (tick, auteur, decision_seq), donc sans favori ; le perdant rend `Conflict`.
- Dette « T18b : table loi/processus au catalogue » (constantes de comportement en dur, NON externalisées) : tolérance d'appui 20 mm ; masses 300 g (frappe), 500 g (creuse), 25 000 g et 1 500 mm (saisie) ; dureté « tendre » 35 ; 8 mJ par (ténacité x cm2) pour casser ; 50 g par (ténacité x cm2) de portance ; diviseurs d'énergie 32 (fendre), 8 (joints), 4 (écraser) ; pièces max 4 (couper) et 6 (fendre, éclats) et 8 (gravats) ; travail 25 pour mille (tailler) et 8 pour mille (aiguiser) par coup ; profondeurs 500 mm (extraire) et 250 mm (labourer) ; bruit et vue de chaque processus ; catégories labourables (`TILLABLE_CATEGORIES` de `gen_matter.py`).

## Exécuteur de gestes (T22)

`gesture_executor.*`, `gesture_execution.h`, `gesture_timing.*` (+ `navigation_query.*`, `gesture_senses.*`). La décision du modèle (geste,
paramètres, condition d'arrêt, plan) est exécutée dans le temps : approche de ce que l'acteur CROIT (`NavigationQuery`, route sur sa
connaissance, P51), puis cycles à la cadence du catalogue (tick = 16 s de jeu = 1000 ms réelles ; `cadence_ms` par geste). Il produit des
`Contact` pour `ProcessEngine::on_contacts` et des `Emission` pour le bus (déplacer, prendre, poser, donner, manger, boire, parler : jamais
d'effet caché), et un `ExecutionReport` par geste fini (`w_outcome` : done, failed, blocked, interrupted, limit_reached ; jamais « but atteint »).
Ordre d'arrêt : `until` du geste, puis tête d'arrêt de la décision, puis `natural_end`, puis butée `a_while` (`limit_reached`) ; une durée choisie
(brief, a_while, long) est la butée voulue par le modèle (= done). `kTaskCompression` (x16) s'applique aux seuls gestes `productive`.
Un geste n'échoue que SUR PLACE : si la cible a bougé hors de vue, l'acteur va où il la croit et ne constate l'absence qu'en arrivant ;
une route coupée se découvre quand l'obstacle entre dans son champ (`NavStatus::Blocked`). Les 26 conditions sont lues dans la perception de
l'acteur (`ActorSenses` ; `ObserverSenses` lit les dossiers écrits par la perception) ou dans son propre corps, jamais dans la vérité.
Faits écrits dans le plan (`intention`) : `i_status`, `i_step_started`, `i_step_progress`, `i_step_index`, `i_attempts`. Chaque geste passe d'abord par
le gouverneur (`check_gesture`, D10) ; un refus ne lance rien, la raison reste dans le rapport (journal moteur) et n'est jamais écrite dans un dossier.
Un coup reçu, une chute, l'inconscience ou une prise interrompent (`notify`, `BodyEvent`) ; un réveil P0/P1 n'arrête rien (`on_wake`).
`NpcNeedsApplier` (Applier du bus, après l'EntityStore) recopie les `EntityDelta` des besoins (faim, soif...) dans le dossier du PNJ, d'où `NpcLaws::step` repart.
Tables : `catalogue/tools/gen_act_timing.py` (`--check`) → `generated/emergence/act/gesture_timing_gen.h` (cadence, natural_end, productive, durées, nutrition/hydratation).
Tests : `test_gesture_executor` (40 gestes, familles, conditions, interruption, P51, kTaskCompression, chêne, 1/4/8 fils, 500 PNJ x 1 jour) ; banc : `bench_gesture_executor`.

### Limites et dette de T22

- Étalonnages nommés dans `gesture_timing.h` (estimés, hors catalogue) : vitesses d'allure (1,3 m/s au pas), portée de la main 1,5 m, vitesses de coup, volumes de la voix, sauts, 3 dixièmes de besoin par point de nutrition, seuil « reposé », 3 contacts sans effet = échec.
- `eat` / `drink` : un tiers de l'objet par cycle (`amount` = 1, 2 ou 3 cycles) ; l'objet n'est détruit qu'avec `all` (pas de variable de reste d'une portion dans le catalogue) ; la toxicité n'agit pas (loi d'un autre lot).
- `NpcNeedsApplier` ne recopie que dans le sens opération → dossier ; le retour dossier → EntityStore (NpcLaws écrit les besoins) reste à faire avec l'ordonnanceur (T26).
- `ObserverSenses` : `c_have` ne lit que `own_held_seen` (pas le contenu cru d'un contenant) ; `c_unwatched` suppose qu'un `ep_gaze` renseigné regarde l'acteur (la perception ne l'écrit pas encore) ; `c_attacked` et `c_stopped` arrivent par `notify` (le corps), pas par la perception.
- Un coup sur un corps vivant : l'exécuteur émet le `Contact` ; le modèle de dommage (`body.toml`) n'est pas dans `ProcessEngine` (T34), donc aucun effet tant qu'il n'existe pas ; `contact_results` ignore volontairement les cibles vivantes.
- Pas de plafond sur un geste qui a une condition d'arrêt jamais vraie (ordre voulu par docs/14 4.3) : seul un réveil du modèle ou le corps l'arrête.

### Revue de T22 : corrections et conventions

- **Un seul repère** hors T18 : z vers le haut, x et y horizontaux (store, perception, navigation, exécuteur). `resolver_frame.*` est l'UNIQUE adaptateur vers les lois de T18 (y vers le haut) : un `EntityStore` miroir (Applier du bus, à enregistrer après le store, dès la création du monde) rejoue chaque `Spawn`/`Move` avec y et z échangés ; `to_resolver(Contact)`, `to_world(Emission)`, `ZUpGround` (sol vu de l'exécuteur). Coût : mémoire des entités doublée (à revoir en T18b si le résolveur apprend un repère).
- **D10 sur le contenu** de `speak`/`write` : `GestureDecision::content_verdict` (verdict de `check_utterance`, SpeechRouter) est exigé ; sans verdict qui autorise, `begin()` refuse et rien n'est émis.
- **`i_step_targets`** : en-tête bit 31 (cible du plan) sauté via `social/plan_target_header.h` (convention provisoire jusqu'à la variable `i_target`, T28c) ; test avec un vrai `ContextBuilder` (`test_gesture_plan_context`).
- **Vérité** : `ObserverSenses` reconstruit la position vue depuis le relèvement et la distance gardés dans le percept ; `eat`/`drink`/`give`/`throw`/`put`/`pour`/`read` jugent portée et présence sur la perception ; `sees_kind` ne lit que le dernier balayage ; `c_hears` compare le mot de l'événement entendu ; `c_attacked`/`c_stopped` viennent du corps (`notify`) et un coup attendu vaut `done`.
- **Navigation** : mon interface s'appelle `ExecutorNavigation` (`executor_navigation.*`) ; `NavigatorAdapter` câble le `Navigator` de T23b (`Moving`/`Exploring` = avancer vers le waypoint). Test de bout en bout avec la vraie carte mentale (pont coupé hors de vue : arrive en contournant, ou échoue `blocked` sur place).
- **Remplacement** : `begin()` met fin à l'exécution en cours avec un rapport `interrupted`/`Replaced` (aussi quand le nouveau geste est refusé) ; la navigation est annulée.
- `kTaskCompression` : tous les gestes `productive` (operate, scoop, work, tie, shape, channel) posent `Contact::productive` (testé) ; `work_units`, code mort, retiré.
- `i_step_index` reste en milli-unités (échelle `qty` du catalogue, lue ainsi par le ContextBuilder) ; la loi d'oubli (`forgetting.toml`, `500 * min(i_step_index, 6)`) le lit comme un entier brut : à corriger de son côté (elle sature toujours).

### Dette « T22b : table loi/geste au catalogue » (constantes de comportement en dur, NON externalisées)

`kPaceSpeedMmS`, `kClimbSpeedPermille`, `kSwimSpeedMmS`, `kReachMm`, `kStopAtMm`, `kArrivedMm`, `kNearMm`, `kBlowSpeedMmS`, `kVolumeNoise`, `kJumpMm`, `kTenthsPerFoodPoint`, `kRestedSleepinessMaxTenths`, `kRestedExhaustionMaxTenths`, `kNoEffectCycles` (gesture_timing.h) ; `kTurnMinMrad`, `kUnconsciousBelow` et les postures (gesture_executor.cpp) ; les parts 333/666/1000 de `pour` ; bruit et vue de chaque geste (`act(...)`) ; le rapport un tiers d'objet par cycle de `eat`/`drink`.
