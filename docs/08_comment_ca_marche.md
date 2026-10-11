# Comment ça marche : le catalogue d'Emergence

## En bref

1. Le **catalogue** (`catalogue/`) est la liste unique de tout ce qui existe dans la simulation : gestes, mots, variables, objets, jugements.
2. Trois couches ne sont jamais mélangées : le **corps** (gestes), la **parole** (ce qu'on dit, composé par le Transformer), les **jugements** (ce que les témoins concluent).
3. Le Transformer, l'IA qui décide pour chaque PNJ, ne reçoit qu'une **vue compacte et bornée** ; la richesse reste dans le moteur.
4. Un **gouverneur** (contrôleur) borne ce que l'IA écrit : il coupe ou refuse, il ne décide jamais.
5. Chaque pièce est **vérifiée** par des outils, et la partie C++ est testée contre les mêmes cas que la version Python de référence.

## 1. Le principe : trois couches

| Couche | Ce que c'est | Exemple |
|---|---|---|
| Gestes (`actions.toml`) | Ce que le corps fait, décrit par sa manière : force, zone, objet utilisé, durée, condition d'arrêt | Une claque et des coups jusqu'à l'immobilité sont **un seul geste**, `strike`, avec une autre force et une autre condition d'arrêt |
| Parole (`language_*.toml`) | Parler est un geste ; ce qui est dit est un **contenu** composé par le Transformer | Le chantage n'existe pas comme action. C'est une phrase : « si tu ne me donnes pas 3 pièces, je dis… » |
| Jugements (`interpretations.toml`) | Ce qu'un témoin **conclut** de faits physiques. Jamais une option offerte à l'IA | Le vol n'est pas une action. Un témoin voit `take` (prendre), en cachette, une chose qu'un autre croit à lui : il peut en conclure « vol » |

Deux témoins peuvent conclure différemment d'un même geste : pour le fils, reprendre la hache est un vol ; pour le père, ce n'est rien.

Le validateur refuse un geste dont l'identifiant serait `steal`, `slap`, `threaten` ou `promise` (voler, gifler, menacer, promettre) : ces mots appartiennent à la parole ou aux jugements.

## 2. Les histoires : des sondes

Les histoires (`data/stories.toml`) ne sont **que des questions** : « le catalogue permet-il d'exprimer cela ? ». Si la réponse est non, on ajoute une **primitive générale**, jamais une entrée propre à l'histoire. Une histoire ne justifie aucune entrée et ne contraint aucun PNJ.

Aujourd'hui, 146 sondes existent ; une quinzaine sont décomposées en gestes et en paroles. L'étape 18, en cours, décompose les autres et ajoute les primitives générales qui manquent.

Plus tard, des **rails légers** (coutumes connues, comme faire la cour ou marchander) pourront aider l'entraînement. Un PNJ pourra les suivre, les dévier ou les ignorer. Ils ne sont pas faits.

## 3. Les objets : des assemblages

Un objet est un assemblage de **parties**. Une partie = une **forme** × une **matière** : « lame:fer », « manche:chêne ». Les propriétés se déduisent des parties : une lame de fer coupe mieux qu'une lame de silex et casse moins.

Toute combinaison est permise, même non prévue : un couteau attaché au bout d'un bâton devient une lance. Les 421 **types connus** (une faucille, une hache) sont des modèles de référence, jamais une limite. Le catalogue compte 63 formes et 84 matières.

## 4. Les drapeaux du catalogue

Chaque variable, propriété, composant ou geste porte des drapeaux. Ils protègent la simulation contre les écritures abusives.

| Drapeau | Ce qu'il protège |
|---|---|
| `writer` | Qui peut écrire la variable : `engine` (le moteur seul), `T_jump` (le Transformer peut sauter d'un coup, réservé aux émotions), `T_step` (pas borné), `T_slow` (borné par année de vie), `derived` (vue calculée, jamais écrite), `birth` (valeur fixée à la naissance), `action` (effet d'un geste) |
| `step` | Variation maximale **par décision** |
| `rate` | Variation maximale **par jour de jeu** (1 h 30 réelle). Sans lui, des petits pas répétés deviendraient un saut |
| `slow_rate` | Variation maximale **par année de vie** (2 h 30 réelles à l'âge adulte : 42 ans en 105 h) |
| `clock` | Horloge suivie : `real` (secondes réelles), `day` (calendrier), `life` (horloge de vie), `none` |
| `engine_only` | Composant que le Transformer ne peut jamais écrire (corps, besoins, biens) |
| `channel` | Par quel canal le PNJ connaît la donnée : `own_mind` (ses émotions), `interoception` (ce que son corps sent), `perception` (ce qu'il voit maintenant), `belief` (ce qu'il croit, retient, veut). Sans canal, aucun jeton |
| `token` | Où l'IA voit la variable (`SELF.body.pain`). Vide = moteur seul |
| `perceptible` | Obligatoire sur chaque propriété. `false` : la propriété ne se voit pas (toxicité), seule une croyance la fait connaître |
| `list_of` | Type des éléments d'une liste qui atteint l'IA (mot, quantité, pointeur) |
| `reads` | Pour une variable dérivée de croyance : les variables qu'elle lit |
| `intimate` | Règle dure D10 : jamais portée vers ou depuis un mineur. Déclarée sur relations et besoins |
| `contact` | Geste pouvant toucher une personne : déclaration obligatoire |
| `party_params` | Paramètres pouvant désigner une personne concernée par le geste |
| `minor_person_ok` | Le geste est-il permis avec un mineur, oui ou non (D10) |
| `minor_whitelist` | Si oui, seules les valeurs listées sont permises, et chaque paramètre listé devient obligatoire |
| `lookalike` | Classe perçue commune à des sosies : un champignon mortel ressemble à un comestible |
| `values_from` | Une énumération reprend les concepts d'une catégorie : une seule source |

## 5. Ce que l'IA lit et écrit

Le Transformer a un budget. Chiffres donnés par `python3 catalogue/tools/budget.py` (mesurés, pas estimés) :

| Quoi | Mesuré | Limite |
|---|---|---|
| Jetons par décision | 87 | 128 (cible ≈ 96) |
| Variables | 342 au total : 202 vues par l'IA, 140 moteur seul | |
| Propriétés d'un objet (vecteur fixe) | 43 | 48 |
| Mots de grammaire | 654 | 768 |
| Sortes (types d'objets, matières, espèces, formes) | 643 | 1 024 |
| Gestes | 40 | 64 |
| Écritures par décision | au plus 4, plus le geste | 4 |

**Rien de vrai dans ce que l'IA lit** (règle dure `no_truth_in_tokens`). L'IA ne voit que les **dossiers mentaux** du PNJ : ce qu'il perçoit, croit et retient.

- Un sosie posé à la place d'un marteau passe pour l'original : le moteur rattache par l'apparence et le lieu cru, jamais par l'identité vraie.
- `THING.owner` est le propriétaire **cru**, pas le vrai.
- Une bête montre ce qu'elle fait (`grazing`, `charging`), sans dire pourquoi. Le jugement de danger revient au PNJ.

## 6. La langue intérieure

Une parole est un **mode** (affirmer `assert`, demander `ask`, proposer `offer`…) suivi d'une **proposition** : un prédicat, ses arguments, une polarité (vrai ou faux) et un temps. Quelques **formules** se disent seules : pardon `sorry`, attention `watch_out`, à l'aide `help`.

Les **pointeurs** renvoient aux dossiers du parleur : `@E3` une personne, `@T5` une chose, `@L2` un lieu qu'il connaît, `b:7` une de ses croyances, `m:2` un souvenir, `g:1` un objectif. Au moment de parler, le moteur **fige** la phrase : l'auditeur reçoit une entrée dans ses propres termes, et l'apparie à ses dossiers. Rien ne passe par la vérité.

Exemple (histoire « Interrogé sur sa nuit ») :

`(assert (past (did me sleep @L1)))`

Un homme affirme qu'il dormait chez lui alors qu'il était à la mine. Le mensonge n'a pas de mot : c'est affirmer ce qu'on croit faux.

## 7. Le gouverneur

Le gouverneur (`catalogue/tools/governor.py`) se place entre le Transformer et le monde. Il **coupe ou refuse**, il ne décide jamais. Il :

- refuse toute écriture sur une variable réservée au moteur ;
- borne chaque nombre : un saut seulement pour `T_jump`, sinon par `step`, `rate` et `slow_rate` ;
- limite à 4 écritures par décision ;
- applique la règle dure D10 **par défaut refusée** : en cas de doute sur l'âge ou sur l'identité d'une personne, celle-ci est traitée comme mineure.

La version C++ (`engine/social/`) doit reproduire les décisions du gouverneur Python, raisons comprises. Les deux lisent les mêmes **vecteurs de test** (`engine/social/tests/governor_vectors.inc`), générés par `catalogue/tools/governor_vectors.py`.

## 8. Comment on vérifie

| Contrôle | Commande ou fichier | Ce qu'il garantit |
|---|---|---|
| Validateur | `python3 catalogue/tools/check.py` (option `--strict`) | Structure, références, séparation des couches, règles D10 |
| Budget | `python3 catalogue/tools/budget.py` | Ce que l'IA lit et écrit, compté |
| Tests du catalogue | `python3 -m unittest discover -s catalogue/tests` | 24 tests de catalogue, 18 tests du gouverneur |
| Interface du modèle | `catalogue/generated/model_interface.json` (`model_interface.py`) | Entrées, sorties, écritures de l'IA |
| Tables C++ | `engine/social/generated/` (`gen_cpp.py`) | Gestes, variables, mots, générés depuis le catalogue |
| Tests C++ | `engine/social/tests/` (`test_governor.cpp`, `test_state.cpp`, `test_clock.cpp`) | Le moteur C++ suit le catalogue |

Après chaque travail, un **relecteur adverse** (un second agent chargé de chercher les erreurs) est lancé, et ses trouvailles sont corrigées avant présentation (demande de Monsieur, 9 octobre).

**État réel** : la mesure du stockage donne 95,5 Ko par PNJ, soit 45,5 Mo pour 500 PNJ (estimation de l'architecture : 32 Mo). Il reste à compacter les propositions des croyances et des souvenirs. Les questions ouvertes sont O16 à O21 (`docs/01_decisions.md`).

## Pour aller plus loin

1. `catalogue/README.md` : le principe et les règles, en une page.
2. `catalogue/data/actions.toml` : les 40 gestes, avec leurs manières.
3. `catalogue/data/language_grammar.toml` : comment une parole est composée et figée.
4. `catalogue/tools/governor.py` : ce que le gouverneur refuse, et pourquoi.
5. `catalogue/ETAT.md` : ce qui est fait, ce qui reste, les chiffres.
