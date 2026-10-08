# État de la simulation sociale (sim/), 8 oct. 2026

Fil « Simulation sociale des villages ». Bilan avant le passage sur Claude Code.

## Ce que Monsieur a demandé (8 oct., 15:18 et 15:34)

Pas d'algorithme de décision : un Transformer dans la boucle de chaque PNJ, qui voit, ajuste ses variables (seules les émotions sautent) et choisit une action. Les 500 PNJ sont simulés en permanence, même loin du joueur, sans rendu. D'abord définir toutes les variables et toutes les actions. Le modèle lui-même appartient au fil « Données d'entraînement du Transformer » (`ai/`).

## Fait

- **La prise du cerveau** (`emergence_sim/brain.py`). À chaque heure de jeu, tous les PNJ qui doivent décider sont réunis, le cerveau choisit pour tous en un seul lot, puis la simulation exécute dans l'ordre des identifiants. Deux cerveaux :
  - `TransformerBrain` appelle `ai/student/student_model.Student` tel quel (point de contrôle de `train_student.py`, ou poids non entraînés pour la plomberie) ;
  - `ReferenceBrain` garde les anciennes utilités à règles, figées, comme étalon. Plus aucune règle de décision n'est ajoutée.
- **Les options du moteur** (`emergence_sim/options.py`) : ce qui est faisable, jamais ce qui est souhaitable. Au plus 16 options, chacune écrite en fonction du contrat avec ses arguments. Seules des limites physiques, légales ou dures filtrent, dont la règle de la romance.
- **L'état vivant en jetons** (`emergence_sim/live.py`) : chaque décision construit un enregistrement du générateur 0.4 depuis la simulation, puis des jetons tok-1 par `ai/npc_pipeline/encode.py`. Les champs que la simulation ne calcule pas reçoivent une valeur neutre fixe (liste `NEUTRAL`), jamais un tirage. Sur 512 PNJ, aucun jeton hors vocabulaire.
- **Le gouverneur** (`Governor` dans `brain.py`) : il applique les ajustements de variables du modèle dans des bornes. Une émotion peut sauter, une relation bouge de 5 au plus, une pulsion de 5, un trait ou une valeur de 1 par jour de jeu. Le corps, les biens et la monnaie restent au moteur, et la romance vers un mineur ou un parent est toujours refusée. Le modèle n'a pas encore de tête de sortie pour ces ajustements.
- **Le catalogue unique** des variables et des actions : `docs/npc/variables_v0.3_catalogue_unique.md`. Il fusionne v0.1, v0.2, la moitié « modèle » du fil des données et les 112 fonctions du contrat, et ajoute la moitié « monde », une proposition de jetons de perception et 10 actions du monde qui manquent. Il est envoyé au fil des données pour validation.
- **Ligne de commande** : `--brain transformer --model … --config … --device cuda --temperature …`.
- **Tests** : 12 tests verts (`python3 -m unittest discover -s tests`), dont 4 nouveaux :
  - options et règles dures ;
  - jetons de l'état vivant ;
  - cerveau Transformer déterministe, avec des plans tous valides ;
  - bornes du gouverneur.

## Mesuré (conteneur, 4 cœurs, sans GPU, poids non entraînés)

| | tiny (0,8 M) | small (5,3 M) |
|---|---|---|
| passes du modèle par seconde, lots de 500 | 1 470 | 428 |
| décisions par seconde, boucle complète | 765 | 333 |
| encodage Python par PNJ | 0,55 ms | 0,55 ms |

- 10 jours de jeu, 500 PNJ, tiny : 121 279 décisions en 159 s. Le plus gros lot rassemble 513 PNJ : tous les vivants en une seule passe.
- Le cache des situations identiques n'a servi à rien ici (0 % de réussite) : l'heure et le temps écoulé changent à chaque décision. Il ne servira que dans la boucle rapide du jeu, où la situation bouge peu d'une image à l'autre.
- Avec des poids non entraînés, les PNJ font n'importe quoi : la disette arrive en un jour. C'est attendu ; il faut un point de contrôle entraîné.
- Rien n'est mesuré sur GPU ni en inférence entière.

## Pas fait

1. **Pas de point de contrôle entraîné** dans le conteneur. Le fil des données doit en fournir un, ou il sera entraîné sur la machine de Monsieur (`ai/student/ENTRAINEMENT.md`). Ensuite : `--brain transformer --model runs/small/best.pt`.
2. **Pas de perception spatiale** : le modèle voit une situation sociale, pas l'espace, l'eau, le feu ni les structures. Les jetons proposés sont au § 6 du catalogue.
3. **Pas de réveil plusieurs fois par seconde.** La simulation décide en fin de plan ou sur interruption, par pas d'une heure de jeu (1 heure de jeu = 10 min réelles si 1 jour = 4 h). Il faudra un réveil périodique et des interruptions par événement perçu, en plus de la fin de plan.
4. **Réactions sociales encore à règles** : l'acceptation d'une demande en mariage, la réponse à une insulte et le choix de la tenue restent décidés dans `social.py` et `actions.dress`. Il faut les faire passer par le cerveau.
5. **Écarts demandés par le fil des données, pas corrigés à la source** :
   - les 24 métiers de la simulation ne sont pas encore les 26 des fiches ;
   - une table de correspondance tient lieu d'alignement ;
   - l'apprentissage commence à 12 ans, alors que la catégorie « teen » commence à 14 ;
   - quelques écarts d'âge parent-enfant font moins de 16 ans.
6. **Anciens identifiants de villages** dans la simulation (`port`, `bourg`…), traduits à la sortie. Le flux `sim-events-0.1` de `interfaces.md` § 9 n'est pas encore écrit en fichier.
7. **Le run de 5 ans** (stable, 513 → 556 habitants) date d'avant le passage en lots. Depuis, avec le cerveau de référence, seuls 60 jours (512 → 515 habitants) et le test de 90 jours ont été refaits.

## Questions ouvertes pour Monsieur

Elles sont détaillées au § 10 du catalogue :
- traits figés ou lentement mobiles ;
- nombre d'appels par seconde et par PNJ ;
- modèle « bien moins cher » pour les données ;
- mémoire longue ;
- traits reportés de v0.1.
