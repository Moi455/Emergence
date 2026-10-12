# Situations d'amorçage

Fabrique des moments plausibles de la vie d'un PNJ : ce qu'il voit, croit, se rappelle et veut. Ils servent au pilote du professeur et au premier entraînement, en attendant que le moteur C++ produise de vraies situations (DAgger).

`SituationSampler(seed).sample(i) -> Situation(seed, index, scene, context, encoded, people)`. `people` donne, pour chaque clé de son esprit (`me`, `@E1`…, fantômes compris), la vraie personne derrière (âge réel, nom) : c'est la vérité du moteur, jamais lue par le professeur.

- **`scene.py`** : la vérité de la scène (lieu, heure, personnes, objets, bêtes). Les âges suivent le lien (`LinkRules` : fratrie ±15 ans, ami d'âge proche, apprenti ≥ 12 ans, partenaire intime adulte net des deux côtés, au plus un conjoint ou fiancé, amants rares), les noms sont uniques dans une scène, 30 % des scènes sont chargées (foule, objets, absents) pour produire de longs contextes.
- **`parties.py`** : les `Party` du gouverneur (âge réel, apparent, cru, dossier résolu) côté générateur ; refus par défaut pour un absent, un fantôme ou un nom seul.
- **`gestures.py`** : quel geste, avec quelle manière, pour un événement ou un acte raconté. Familles pondérées (percevoir, se déplacer, saisir fréquents ; la force ~2 %), contact seulement à portée (≤ 2 m), jeune enfant qui frappe, lance ou travaille rarement, et **le gouverneur tranche** (`check_gesture`) : un geste refusé n'est jamais proposé ; avec une personne possiblement mineure, un geste de contact porte exactement les valeurs de sa `minor_whitelist`.
- **`propositions.py`** : croyances, objectifs, souvenirs et demandes, faits de prédicats généraux du catalogue, validés par la langue **puis par le gouverneur** (`check_record`). Pas de métier ni de savoir-faire avant 14 ans, pas de qualité physique d'un mineur possible, liens cohérents avec `ENTITY.link` et avec les âges.
- **`body.py`** : corps et météo (sommeil et faim selon l'heure, air ressenti selon la saison et les murs, force selon l'âge, quelques blessés, malades, ivres).
- **`builders.py`** : un constructeur par type de dossier (`SelfBuilder`, `PersonBuilder`, `ThingBuilder`, `PlaceBuilder`, `EventBuilder`, `BeliefBuilder`, `MemoryBuilder`, `SocialBuilder`, `GoalBuilder`, `SkillBuilder`, `StateBuilder`, `WakeBuilder`) autour d'un `BuildContext` partagé.
- **`mind.py`** : `MindBuilder.build(scene, rng) -> Mind(records, people, extra_known)` ; l'ordre des constructeurs y est écrit.
- **`audit.py`** : contrôle D10 **indépendant** de chaque situation (il ne partage aucune constante avec le générateur : âge adulte tiré du gouverneur, liens intimes des drapeaux `intimate`). Il reconstruit les `Party` depuis la vérité de la scène et les dossiers, fait passer chaque proposition par `check_record` (citations `b:`/`m:`/`g:`/`@V` dépliées), chaque événement et chaque étape de plan par `check_gesture`, parcourt tous les champs texte et liste, et refuse qualité physique d'un mineur possible, champs ou liens intimes hors adultes nets, `drive.intimacy` > 2 quand l'attention porte sur un mineur possible.

Rien n'est écrit à la main hors des archétypes de lieux, des tables de pondération et de la table des âges par lien : tous les mots viennent du catalogue. L'échantillonneur ne décide jamais à la place du PNJ et ne met aucune vérité dans les dossiers (le propriétaire d'un objet est *cru* : exact surtout pour ses propres biens et les personnes connues, exact pour un inconnu seulement si le PNJ l'a vu tenir l'objet, parfois faux).

Mesuré (12 oct., graine 5, 2 000 situations) : 8,1 ms par situation (dont ~2 ms de mise en jetons et ~2 ms d'audit), 53 jetons en moyenne (21 à 88 ; 31 % des situations à 70 jetons ou plus), 0,00 % de propositions invalides, 0 refus du gouverneur (il est consulté avant d'écrire).

Chaque situation porte un jeton `WAKE` cohérent, un `PLAN` avec `target` et `next`, des échéances parfois dépassées, des personnes connues mais hors du lot (fantômes pour le tokeniseur) et les conventions inconnu / vide (`informant: ""` quand personne ne l'a dit, `held: []` mains vides, `wound: []` aucune blessure).

Limites : pas encore de mots pour les tenues, les marques, la météo vue, les blessures ni les sortes de lieux ; les affordances des objets ne sont données que quand elles sont sûres ; `care` (toucher) est rare parce que le catalogue le limite fortement avec un mineur possible ; les fréquences, âges par lien et tables de pondération sont des valeurs de départ, pas des mesures du monde.

Si `python3 -m tok2.golden --update` est relancé, les 12 cas « sampler » d'or changent (nouveau sampler) : ne pas le faire sans décision.

```
cd ai && python3 -m situations.sampler --n 300     # statistiques
cd ai && python3 -m situations.sampler --show 3    # une situation
python3 -m unittest discover -s ai/situations/tests -t ai
```
