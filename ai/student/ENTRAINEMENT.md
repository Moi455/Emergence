# Entraîner l'élève (le Transformer des PNJ)

Ce dossier contient tout ce qu'il faut pour entraîner et évaluer le décideur des PNJ sur votre machine (RTX série 3000, 6 Go). Les données sont déjà prêtes dans `/mnt/project-files/donnees-transformer/` ; vous pouvez aussi les refaire en une commande.

## Ce que fait le modèle

À chaque fin de plan, le moteur propose de 2 à 16 options (accepter, refuser, frapper, fuir, enseigner son métier, donner au village…). L'élève lit la situation sous forme de jetons (le PNJ, son village, son foyer, les personnes proches, les événements, ses souvenirs, ses buts, ses titres, son inventaire, puis une ligne par option) et donne un score à chaque option. Le moteur tire l'option selon ces scores avec une graine propre au PNJ, puis le HTN la déroule en plan.

Format des jetons : `tok-1`, décrit dans `ai/npc_pipeline/encode.py` et exporté dans `token_layout.json`. Ce fichier Python est l'oracle du portage C++ : le moteur doit produire exactement les mêmes entiers.

## Les trois sources d'étiquettes

| Source | Coût | Rôle | État |
|---|---|---|---|
| Décideur de référence (`reference_decider.py`, utilités lisibles) | gratuit, ~1 000 situations/s par cœur | pré-entraînement, base de comparaison, repli sans GPU dédié | fait : 300 000 situations étiquetées |
| Professeur Gemini (`teacher_run.py`) | votre clé et votre quota | étiquettes plus fines, à poids 3 | prêt, **jamais lancé** : attend votre accord |
| Simulation sans rendu (fil « Simulation sociale ») | gratuit | états réellement visités, boucle DAgger | en cours dans l'autre fil |

Tant que seules les étiquettes de la référence existent, l'élève apprend à imiter la référence. C'est voulu pour démarrer, mais la règle des devs reste : l'élève doit **battre** la référence, ce qui n'est possible qu'avec les étiquettes du professeur et la boucle de simulation.

## Installation (une fois)

```
cd emergence/ai/student
python -m venv .venv && source .venv/bin/activate        # fish : source .venv/bin/activate.fish
pip install torch numpy                                    # la version CUDA de torch s'installe d'office sous Linux
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## Entraîner

```
python train_student.py --data /chemin/vers/donnees-transformer/ref_v04_300k --config small --epochs 8 --batch 256 --out runs/small
```

- `--config` : `tiny` (0,8 M de paramètres), `small` (5,3 M, défaut conseillé), `base` (~15 M), `large` (~33 M).
- Le meilleur modèle est écrit dans `runs/small/best.pt`, la courbe dans `runs/small/log.jsonl`.
- Mémoire : `small` avec 256 situations par lot tient largement dans 6 Go (estimation : moins de 1,5 Go). Si la carte manque de mémoire, baissez `--batch` à 128.

Durée : mesurée sur le processeur de ce conteneur (4 cœurs) : `small` traite environ 175 situations par seconde ; `tiny` environ 550. Sur une RTX 3060 portable, mon **estimation non mesurée** est de 3 000 à 8 000 situations par seconde pour `small`, donc 8 passes sur 270 000 situations d'entraînement en 5 à 15 minutes. Le chargement des lots en Python peut devenir le goulot ; c'est la première chose à regarder si la carte n'est pas occupée à fond.

## Évaluer

```
python eval_student.py --ckpt runs/small/best.pt --data /chemin/vers/donnees-transformer/ref_v04_300k \
                       --pairs /chemin/vers/donnees-transformer/paires_minimales.jsonl
```

Trois mesures :

1. **top1** : l'élève choisit la même meilleure option que l'étiquette. Comme plusieurs options sont souvent à égalité, **good** (l'option choisie a un score ≥ 3 sur 4) est plus parlant.
2. **Paires minimales** (`minimal_pairs.py`, 25 sondes) : on change une seule variable (agressivité, confiance envers celui qui propose, faim, fidélité, tabou, loyauté au village, nombre d'autres détenteurs d'un métier, fête, froid…) et on vérifie que la probabilité des bonnes options bouge dans le bon sens. Les sens attendus sont écrits à la main, pas lus dans la référence. La sonde « noise_witness » présente deux fois la même situation : elle doit donner deux fois la même réponse.
3. **Vitesse** : décisions par seconde par lots de 512. Le jeu a besoin d'environ 30 décisions par seconde pour 500 PNJ.

## Résultat mesuré ici (point de départ, 8 oct., avant le passage à 8 tenues)

`tiny`, 3 passes sur 135 000 situations, processeur 4 cœurs, 16 minutes : test top1 0,752, good 0,995, 1 518 décisions/s. Paires minimales : élève 86 %, référence 98,6 %. Sondes encore faibles : peur de l'interrogateur (0 %), tenue de fête (35 %), accaparement (45 %), honnêteté (60 %). `small` sur 300 000 situations et 8 passes devrait les rattraper ; c'est la première chose à regarder dans `eval.json` après votre entraînement.

## Refaire ou agrandir les données

```
cd emergence/ai/npc_pipeline
python3 build_dataset.py --n 300000 --name ref_v04_300k --workers 8      # ~1 min sur 8 cœurs, ~520 Mo
python3 minimal_pairs.py --per-probe 60 --out paires_minimales.jsonl
```

Tout est déterministe : même graine, mêmes fichiers. Aucune dépendance externe pour ces deux scripts.

## Données de la simulation

`sim_seed7/` contient 6 978 décisions vécues dans la simulation sans rendu (5 ans de jeu, 500 PNJ), converties par `sim_adapter.py` et étiquetées par la référence. Elles servent d'abord de **test hors distribution** :

```
python eval_student.py --ckpt runs/small/best.pt --data /chemin/vers/donnees-transformer/sim_seed7
```

Pour les mélanger à l'entraînement :

```
python3 build_dataset.py --n 300000 --name ref_sim_v04 --sim-trajectories ../../../donnees-transformer/sim/seed7_adapte_v04.jsonl
```

## Lancer le professeur (seulement avec votre accord)

Le professeur consomme votre clé Gemini et votre quota. Rien n'a été lancé. Quand vous le décidez :

```
cd emergence/ai/npc_pipeline
export GEMINI_API_KEY='…'                  # fish : set -gx GEMINI_API_KEY '…'   (jamais dans un fichier)
python3 teacher_run.py probe               # vérifie la clé et les niveaux de réflexion (1 à 3 requêtes)
python3 teacher_run.py pilot               # compare 3 variantes de sortie sur 96 situations (quelques dizaines de requêtes)
python3 run_pipeline.py --target 50000     # étiquetage complet, reprend tout seul après interruption
python3 teacher_run.py export              # écrit data/dataset.jsonl
python3 build_dataset.py --n 300000 --name mix_v04 --teacher-labels data/dataset.jsonl
```

Ordre de grandeur (estimation) : une situation fait environ 2 000 caractères, soit 600 à 700 jetons d'entrée ; à 16 situations par requête et 500 requêtes par jour, 50 000 situations demandent environ 3 100 requêtes, soit 6 à 7 jours au quota gratuit. Vérifiez le prix et les quotas réels de Gemini Flash-Lite dans AI Studio avant le gros passage.

## Fichiers

| Fichier | Rôle |
|---|---|
| `student_model.py` | le Transformer : sans encodage de position (les options n'ont pas d'ordre), projection des nombres propre à chaque type de jeton, pointeurs injectés dans l'entrée et dans l'attention |
| `train_student.py` | entraînement (AdamW, cosinus, bfloat16 sur GPU), écrit `best.pt` |
| `eval_student.py` | test, paires minimales, vitesse |
| `dataset_reader.py` | lecture des fichiers binaires (numpy, sans tout charger en mémoire) |
| `../npc_pipeline/encode.py` | jetons `tok-1`, oracle du portage C++ |
| `../npc_pipeline/reference_decider.py` | décideur à utilités, étiquettes gratuites |
| `../npc_pipeline/build_dataset.py` | génération, étiquetage, encodage, fichiers binaires |
| `../npc_pipeline/minimal_pairs.py` | paires minimales avec sens attendu |

## Étapes suivantes

1. Inférence en entiers (style I-BERT) pour avoir les mêmes décisions sur toutes les machines (feuille de route M12 et S7) : entraînement avec quantification simulée, puis export.
2. Étiquettes du professeur, puis boucle avec la simulation sans rendu.
