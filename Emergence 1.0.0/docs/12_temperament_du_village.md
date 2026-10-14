# Tempérament du village : un réglage de partie (13 octobre 2026)

Demande de Monsieur (13 oct.) : « le jeu sera aussi et surtout amusant parce que les PNJ auront souvent des réactions disproportionnées, absurdes. Dans le code, ajouter une variable pour que le joueur choisisse s'il joue dans un village de fous, de modérés, de sages, etc. »

## 1. La variable

`village_temperament` (`catalogue/data/settings.toml`) : échelle bornée **0 à 10**, écrite **par le moteur seul** (le joueur la choisit à la création de la partie, **village par village**), lue par le Transformer dans le jeton **`WAKE.temperament`**.

| Valeur | Repère nommé (l'interface du joueur) | Ce que le professeur cherche à faire jouer |
|---|---|---|
| 0 à 1 | **sages** | réactions mesurées, longue délibération, pardon, médiation |
| 2 à 3 | **posés** | réactions proportionnées, un peu lentes à s'emporter |
| 4 à 6 (défaut 5) | **modérés** | le comportement de base, tel qu'entraîné jusqu'ici |
| 7 à 8 | **caractériels** | colère qui saute pour une broutille, rumeurs qui enflent, rancunes disproportionnées |
| 9 à 10 | **fous** | réactions absurdes : panique collective pour un chat, procès pour un pain, expédition pour un rêve ; toujours des gestes et des paroles **valides** |

Pourquoi un nombre et pas une liste de modes : le même modèle apprend une graduation, sans règle écrite à la main ; on peut mélanger (un village de modérés avec un fou), et le joueur peut régler finement.

Canal : nouveau canal **`setting`** (un paramètre du jeu, ni croyance ni perception), composant `setting` de l'entité `world`. Il tient aussi `w_think_budget` (budget de réflexion, WAKE.budget). Le modèle ne peut pas les écrire (testé).

## 2. Ce qu'il ne change JAMAIS

- **Règles dures** (D10…) : le gouverneur **ne lit pas** ce réglage. Aucun paramètre, aucune branche ; `hard_rules.toml` et les vecteurs du gouverneur (Python et C++) ne le mentionnent pas. Un village de fous ne peut pas franchir D10.
- **Bornes** (`step`, `rate`, `slow_rate`, 4 écritures par décision) : identiques. Une réaction « disproportionnée » reste une suite de gestes et de paroles valides, dans les bornes, ou une émotion qui saute (seules les émotions sautent, D18).
- **Lois du monde** : inchangées (blessures, feu, économie).

Tests : `catalogue/tests/test_language_collective.py::TestVillageTemperament` (variable écrite par le moteur seul, aucun réglage écrivable par le modèle, le gouverneur et les règles dures ne mentionnent pas le réglage, verdict D10 unique).

## 3. Comment le sampler et le professeur s'en serviront (à faire, rien n'est branché)

**Le sampler** (`ai/situations`) : tirer `village_temperament` **par village simulé**, pas par situation seule : toutes les situations d'un même village partagent la valeur (cohérence des suites de pensée écrite). Tirage proposé : la moitié des villages autour de 5 (modérés), le reste réparti sur les extrêmes (0-2 et 7-10) pour que les comportements rares aient des exemples. La valeur entre dans l'enregistrement `WAKE` (champ `temperament`, nombre sur l'échelle de la charte, divisé par 10 par tok-2). Brancher cela change l'ordre des tirages donc les empreintes d'or du sampler : à faire en une fois, avec `python3 -m tok2.golden --update-sampler`.

**Le professeur** (`ai/teacher`) : la consigne dépend de la bande. Le rendu ajoute une ligne « Village temperament: 8/10 (hot-headed) » et un paragraphe de consigne :
- *sages* : « Reactions are measured. You weigh before you act; anger fades fast; you prefer talking. »
- *modérés* : consigne actuelle.
- *caractériels / fous* : « In this village people often overreact: a small insult can bring a shout, a blow, a feud. Proportion is not a virtue here. Stay inside the game: only valid gestures and valid sentences, never anything the hard rules forbid. »

La validation du professeur (gouverneur, grammaire, D10) est **inchangée** : on compte seulement, par bande, les réponses refusées. Si une bande refuse beaucoup plus, la consigne est à corriger, jamais le gouverneur.

**L'évaluation** (à mesurer, rien n'est mesuré) : par bande, la part d'émotions qui sautent pour un déclencheur anodin ; la longueur des délibérations (`think_more`) ; la part de gestes violents après une insulte. Hypothèse : la valeur du réglage doit être lisible dans ces trois nombres.

## 4. Jeu

Au choix du joueur : curseur ou repères (sages, posés, modérés, caractériels, fous) à la création ; modifiable dans les options ; **par village** (5 villages) avec un réglage global qui les fixe tous. Enregistré dans l'état de la partie (une seule vérité : c'est un réglage, pas un cache).

## 5. Question pour Monsieur

O28 (`docs/01_decisions.md`) : réglage **par village** (proposé) ou global ? Modifiable en cours de partie (proposé : oui, dans les options) ? Le défaut doit-il être « modérés » (5) ou plus haut, puisque l'amusement vient des excès ?
