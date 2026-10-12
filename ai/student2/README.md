# student2 : le Transformer des PNJ (élève) pour tok-2

Lit les dossiers tok-2 d'un PNJ, rend un geste, ses pointeurs, ses manières, sa condition d'arrêt, jusqu'à 4 écritures et une phrase du langage intérieur. Entraînement en Python/PyTorch (float16 : la Quadro est Turing, pas de bfloat16).

**Ce n'est pas encore entraîné sur de vrais exemples.** Tout ce qui est mesuré ici l'est sur des réponses **aléatoires** que le validateur accepte (`smoke.py`) : elles servent à tester la chaîne et la vitesse, jamais à apprendre un comportement. Aucun appel réseau.

## Chaîne

```
dataset.jsonl (teacher/dataset.py) ─► data.py : jetons tok-2 à la volée + cibles (labels.py) ─► model.py ─► losses.py ─► train.py
```

| Fichier | Rôle |
|---|---|
| `teacher/dataset.py` | Format des étiquettes. Une ligne = `context` (JSON canonique de `DecisionContext`, en-tête avec empreintes), `decision` (geste, paramètres, parole, écritures ; **pointeurs par clé de dossier**, jamais par emplacement), `verdict`, `source` (modèle, date, graine, indice). `teacher.pilot` l'écrit maintenant en plus de `responses.jsonl`, pour chaque réponse valide. |
| `spec.py` | Toutes les tailles de têtes, tirées du catalogue (40 gestes, 151 logits de manière, 91 variables écrivables, 23 conditions, 203 candidats de pointeur). |
| `labels.py` | Décision ↔ cibles (`encode` / `decode`). Les fantômes sont refusés comme cibles. |
| `sequences.py` | Texte S-expression ↔ pas (symbole, arité, emplacement, compte), comme les colonnes de proposition tok-2. |
| `data.py` | `LabelDataset` (refuse un fichier d'une autre disposition), collate à tailles multiples de 8. |
| `model.py` | Modèle (`tiny` pour les tests, `small`, `base`). Crochet de mémoire par PNJ : `NpcMemory` + `NoMemory` (rien d'autre n'est implémenté). |
| `losses.py`, `train.py` | Entropie croisée par tête, AdamW, cosinus, autocast float16 + GradScaler, points de reprise qui portent les empreintes. |
| `smoke.py` | Réponses aléatoires validées par `AnswerValidator`. **Pas des données d'entraînement.** |
| `bench.py` | Mesures de vitesse et de mémoire. |

## Choix

- **Embedding d'un dossier** : type + mots (liés à leur colonne *et* à leur type) + nombres (FiLM par type, drapeaux « connu » en entrée) + proposition (petit Transformer sur les 20 symboles : arité, profondeur, emplacement, compte).
- **Tronc** : Transformer d'ensembles, biais d'attention appris par (type, colonne, sens, tête) ; les fantômes sont 33 jetons appris, attendables.
- **Têtes factorisées**, chacune conditionnée par la précédente (forçage par l'enseignant en entraînement, argmax en inférence, mêmes modules) : geste (masque de faisabilité en entrée, tout à 1 par défaut) → pointeurs → manières partagées → condition + arguments → nombre d'écritures → par écriture : cible, variable, valeur. Les écritures ne sont permises que sur des variables du genre de la cible (masque exact).
- **Valeurs** : nombre borné en 21 niveaux (variable à saut : valeur absolue ; variable à pas : variation en dixièmes du pas, puisque le gouverneur borne de toute façon). La quantification perd au plus un demi-niveau : `decode(encode(d))` est exact sur la grille, `encode(decode(encode(d))) = encode(d)` toujours.
- **Parole et propositions** : décodeur causal à attention croisée, pas à pas, masques structurels (fin seulement quand l'arbre est fermé). L'automate de grammaire du catalogue n'est **pas** appliqué.
- **Points de reprise** : refusés si l'une des empreintes diffère (interface, disposition, registre, vocabulaire, têtes de sortie).

## Mesures [Mesuré]

Quadro RTX 3000, PyTorch 2.14, float16, GPU préchauffé, médiane de 3 séries, contextes réels de l'échantillonneur (88 jetons remplis au plus, 8 jetons fantômes), mode « eager » (ni graphe CUDA ni `torch.compile`). La dispersion d'un lancement à l'autre atteint ±30 % (surtout `base`, lot de 32).

| | paramètres | entraînement, lot 32 | entraînement, lot 128 | politique seule, lot 32 | politique seule, lot 128 | mémoire GPU (entraînement lot 128 / inférence lot 32) |
|---|---|---|---|---|---|---|
| `small` | 10,2 M | 60 ms = **530 décisions/s** | 122 ms = **1 047 /s** | 12,9 ms = **2 470 /s** | 31 ms = 4 120 /s | 1,35 Go / 242 Mo |
| `base` | 27,6 M | 142 ms = **226 /s** (80 ms dans un autre lancement) | 227 ms = **564 /s** | 15 ms = **2 125 /s** | 54 ms = 2 380 /s | 2,56 Go / 548 Mo |

- Parole : 21 pas, sans cache KV (boucle de référence lente) : **102 ms** (`small`) et **121 ms** (`base`) pour 8 comme pour 32 phrases. Bien au-dessus des 4,5 ms de docs/09 (qui comptent un décodeur à cache KV dans un graphe CUDA) : c'est la boucle Python, pas le calcul.
- Les nombres de paramètres dépassent ceux de docs/09 (6,5 M et 17 M) parce que ces têtes contiennent aussi les plongements de 1 452 symboles, les pointeurs, le décodeur de parole (2,7 M en `small`, 8,2 M en `base`).
- 200 décisions/s : la politique tient (10 lots de 32 par seconde = 129 ms de GPU par seconde en `small`, soit environ 13 % du GPU **en mode eager** ; docs/09 comptait 7 % en graphe CUDA). Ce chiffre ne compte ni le sélecteur ni la parole.
- Entraînement : une passe sur 1 M de décisions prendrait environ 16 min en `small` (lot 128) et 30 min en `base` [Estimé : 1 M / décisions par seconde mesurées].

## Limites

- Pas d'automate de grammaire dans le décodeur ; une phrase prédite peut être invalide (le gouverneur la refuserait).
- `nonzero` dans l'embedder (mots, propositions) force une synchronisation GPU et des formes dynamiques : pas de graphe CUDA tel quel. À plier en tables fusionnées (docs/09 § 4.2) pour la version livrée.
- Une condition d'arrêt dont un argument est un nom (`n:12`), un mot avec compte ou un degré (`all`) n'est pas représentable : l'exemple est écarté et compté (`LabelDataset.audit`). Les listes (`i_steps`, `tastes`) ne sont pas écrites.
- Les nombres sont quantifiés : 21 niveaux (écriture absolue) ou dixièmes du pas.
- La mémoire par PNJ n'est qu'un crochet (`NoMemory`) ; la poignée stable par dossier que docs/09 demande à tok-2 n'existe pas encore.
- La masque de faisabilité n'est pas fourni par le moteur : tout est permis.

## Commandes

```
cd ai
python3 -m unittest discover -s student2/tests -t .          # 22 tests, ~20 s
python3 -m student2.smoke --n 256 --seed 0 --out /tmp/smoke.jsonl   # réponses ALÉATOIRES valides (test seulement)
python3 -m student2.train --data /tmp/smoke.jsonl --size tiny --epochs 2 --batch 32 --out /tmp/run   # essai de chaîne
python3 -m student2.bench --data /tmp/smoke.jsonl --sizes small base --batch 32 128
```
