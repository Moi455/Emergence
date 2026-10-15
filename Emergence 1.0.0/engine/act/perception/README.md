# engine/act/perception : la perception par observateur (T23)

Ce que chaque PNJ voit, entend et sent des **entités** (personnes, bêtes, objets, constructions, plantes, eau, feu, traces),
des **gestes** d'autrui et de **son lieu**, écrit dans **ses** dossiers (`entity_percept`, `percept`, `place_percept`,
`event_seen` du `NpcState`) et nulle part ailleurs. Jamais la vérité : un champ n'est écrit que s'il vient d'une variable
**perceptible**, filtrée par la distance, la lumière, l'angle, les obstacles, l'attention (`SELF_STATE.attention`) et les sens
de l'observateur. Deux observateurs du même objet obtiennent deux dossiers. Le monde voxel n'est pas ici : il répond derrière
`SpaceQuery` (visibilité, son, lumière, intérieur, brume) ; `FlatSpace` (grille plate) sert aux tests.

| Classe | Rôle |
|---|---|
| `PerceptionEngine` | un pas pour tous les observateurs ; ordre par `EntityId`, fils sans effet sur le résultat ; `submit(ActEvent)`, `tick()` |
| `Observer` / `ObserverMemory` | un PNJ (entité + `NpcBundle`) et le lien dossier -> entité (côté moteur, non sauvé) |
| `SpaceQuery` / `FlatSpace` | interface du monde voxel ; implémentation de test |
| `Acuity` (`acuity.h`) | clarté 0..1000 : distance, lumière, brume, angle, couvert, attention, vue/ouïe/perspicacité/conscience |
| `PerceptRules`, `ThingCatalog` | règles de perception **générées** (`engine/act/generated/emergence/act/perception_gen.h`, par `catalogue/tools/gen_cpp.py`, classe `PerceptionGenerator`) ; propriétés d'un type de chose |
| `SpatialIndex` | grille de hachage (8 m) reconstruite à chaque pas : jamais O(n²) |
| `FileDirectory` (`KnownFiles`), `WorldLists` | dossier mental connu d'un observateur pour quelqu'un ; listes du monde (tenue, signes...) |
| `Wake`, `HeardSpeech`, `PerceptionReport` | réveils P0 (coup, cri, bête qui charge, feu proche), P1 (on lui parle), P3 (nouvelle personne, bruit fort, `occasion`, `goal_check`) ; paroles entendues pour le routeur (T24) |

## Règles (testées dans `tests/test_perception.cpp`)

- **Non-fuite** : aucune règle ne lit une variable `visibility = engine` (le générateur refuse ; `catalogue/tests/test_t23_perception_rules.py`).
  Test exhaustif : toute variable moteur de toute espèce d'entité (27 couples) est changée, le dossier reste identique bit à bit
  (vérifié par mutation : une lecture de `animal_aggression` fait échouer le test). Les 90 propriétés du catalogue : une
  propriété non perceptible (23) n'apparaît jamais, une perceptible n'apparaît que si elle est dans le vecteur d'objet.
- **D10** : `ep_age` est un âge apparent (flou selon clarté, arrondi par bandes), jamais l'âge réel.
- Un `take` discret (`sight` bas) ou derrière un couvert n'est pas vu ; un murmure (`noise` 1) ne s'entend pas au-delà de 2 m,
  ni dans la foule (bruit ambiant).
- Une `occasion` n'est émise que si un objectif **actif** du PNJ désigne (pointeur `kRef`) l'objet perçu (ou son dossier connu) ;
  `goal_check` si la personne désignée paraît morte. Une fois par vue.
- Aucune identité vraie dans un dossier : `pc_file` / `ev_actor` ne viennent que du `FileDirectory`, si la clarté suffit ; un
  sosie (classe `lookalike`) donne la classe de sosies et une certitude <= 45 sauf œil exercé (maîtrise >= 60 [Hypothèse]).

## Coût (mesuré, i9-10885H, Release, `bench_perception [obs] [entités] [fils] [côté m] [pas] [murs] [cadence]`)

500 PNJ, village dense de 3 500 entités sur 300 m (440 entités à portée de chacun), 75 murs :
1 fil ~ 35 ms par pas ; 4 fils ~ 10 ms ; 8 fils ~ 6 ms (résultat identique). Sans mur (le moteur seul, sans rayons) : ~ 22 ms à 1 fil.
Cadence 4 (un PNJ sur 4 rescanne par pas, les gestes d'autrui sont vus à chaque pas) : ~ 9-11 ms à 1 fil. La part des rayons vient de
`FlatSpace` ; la vraie `SpaceQuery` voxel aura son propre coût. **Cible de docs/15 (500 PNJ en < 10 ms par pas) : atteinte à 4 fils
ou à cadence 4, pas à 1 fil et cadence 1 dans un village aussi dense** [Mesuré, machine partagée, ± 20 %]. Débit ~ 10-15 M candidats/s/fil.

Relecture adverse (15 oct.) : 500 PNJ entassés sur 50 m avec 3 500 entités (2 M de paires, pire cas) : ~ 90-105 ms à 1 fil (320 ms avant; rayons tirés seulement pour
les meilleurs candidats : ~ 23 par PNJ au lieu de ~ 80) ; 4 fils non concluant (machine partagée, 50-100 ms) ; village de 300 m : ~ 19 ms à 1 fil.

## Conventions fixées à la relecture

- `sort` d'une entité = indice dans `kKinds`. `pc_kind_seen` est un SYMBOLE (mot : indice de `kWords` ; sorte : `kWords.size()` + indice de `kKinds`) : les
  classes de sosies n'existent que dans `kWords`. À confirmer avec le tokeniseur (T28).
- Âge : seul `look_age_seen` (âge apparent du monde) est une source ; sans lui `ep_age` = 0. Biais fixe par couple observateur/cible.
- Lumière : max(lumière de l'observateur, lumière de la cible). `lit`/`burning` sont des propriétés du TYPE, pas de l'instance : une torche allumée se
  traduit par la lumière de sa case (`SpaceQuery::light_at`), jamais par la propriété du type.
- Un dossier connu (`FileDirectory`) n'est utilisé (réveils compris) que si la clarté atteint celle de `ev_actor`.
- Un réveil de coup (P0) suit le geste ÉCRIT dans `event_seen` ; geste inconnu : le bruit seul décide.
- Les règles sont à sources multiples (virgule) ; le test `only_declared_sources_move_the_dossier` vérifie que le code ne lit que les sources déclarées.

## Écarts et points ouverts

- Sous le seuil de clarté, un champ enum garde la valeur 0 (« premier de la liste ») faute de valeur « inconnu » dans le catalogue.
- Pas de pointeur « moi » (`ep_gaze` regarde l'observateur, `ev_target` = l'observateur) : `ep_gaze` reste vide.
- `WorldLists` : les listes du monde (tenue, signes, `held_seen`) sont des poignées vers une table annexe que l'`EntityStore` n'a pas encore.
- Odeurs (T32), carte mentale (T23b), météo (`pp_weather_seen`, `pp_sun`) non faits. `sort` d'une entité = indice dans `kKinds`.
- Constantes d'acuité : première valeur [Hypothèse] à régler en jeu.
