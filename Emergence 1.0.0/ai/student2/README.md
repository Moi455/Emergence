# student2 : le Transformer des PNJ (élève) pour tok-2

Lit les dossiers tok-2 d'un PNJ, rend un geste, ses pointeurs, ses manières, sa condition d'arrêt, jusqu'à 4 écritures, des phrases du langage intérieur, **un plan (au plus 6 étapes) et une condition d'arrêt de décision** (T11). Entraînement en Python/PyTorch (float16 : la Quadro est Turing, pas de bfloat16).

**Pas encore entraîné sur de vrais exemples.** Tout ce qui est mesuré ici l'est sur des réponses **aléatoires** que le validateur accepte (`smoke.py`) : elles servent à tester la chaîne et la vitesse, jamais à apprendre un comportement. Le jeu d'entraînement refuse ces lignes (`synthetic: true`) sauf `--smoke-test`. Aucun appel réseau.

## Chaîne

```
dataset.jsonl (teacher/dataset.py) ─► data.py : contrôle des lignes, cache de jetons tok-2, cibles (labels.py)
        ─► Collator (formes fixes) ─► model.py ─► losses.py ─► train.py
```

| Fichier | Rôle |
|---|---|
| `teacher/dataset.py` | Format des étiquettes. Une ligne commence par un en-tête court (`hdr` = interface:disposition, `id` = graine:indice, `teacher`, `synthetic`), puis `verdict`, `source`, `decision` (pointeurs par **clé de dossier**, jamais par emplacement) et `context` (JSON canonique de `DecisionContext`, avec ses empreintes). `teacher.pilot` l'écrit pour chaque réponse valide. |
| `output_registry.py` + `.json` | Registre **ajout seul** des indices de sortie (gestes, variables, conditions, valeurs de manière, formes, valeurs d'énumération), avec une capacité fixe et une réserve masquée : un catalogue qui grandit ne change pas les formes. **Schéma 2 (T11)** : capacité `plan_steps` = 8 et liste `lists.plan_steps` (`i_steps`, `i_step_targets`), 6 étapes utilisables. Un registre de schéma 1 se lit et se met à niveau en mémoire. |
| `spec.py` | Tailles de têtes, grilles de nombres (exact jusqu'à 256), masques de types acceptés par paramètre, tables d'arité des symboles (tirées des tables du langage). |
| `labels.py`, `sequences.py` | Décision ↔ cibles ; texte S-expression ↔ pas (symbole, arité, emplacement, compte). Un exemple que les masques interdiraient est refusé. |
| `data.py` | `LabelDataset` (contrôle à l'ouverture, cache), `Collator` (indices compacts de capacité fixe). |
| `model.py` | Modèle `tiny` (tests), `small`, `base`. Crochet de mémoire par PNJ : `NpcMemory` + `NoMemory` (rien d'autre n'est implémenté). |
| `losses.py`, `train.py` | Entropie croisée par tête, AdamW, cosinus, float16 + GradScaler, reprise, points de reprise à empreintes. |
| `smoke.py`, `bench.py` | Réponses aléatoires validées ; mesures. |

## À l'ouverture d'un fichier

- Chaque ligne est contrôlée **sur son en-tête court**, sans la décoder : une ligne écrite pour une autre interface ou disposition est exclue et comptée ; **au-delà de 5 % le chargement échoue**.
- Une situation demandée deux fois (même `id`) est gardée une fois. Le découpage entraînement / validation est un hachage de (graine, `id`) : il ne dépend ni de l'ordre des lignes ni du reste du fichier.
- Les lignes aléatoires de test sont refusées sans `--smoke-test` (train, bench).
- Chaque ligne retenue est mise en jetons **une fois** dans un cache (fichiers `.npy` en mémoire partagée, par blocs de 1024 lignes, clé = empreintes du catalogue + condensat du bloc ; `~/.cache/emergence/student2`, ou `--cache`). Choix : `.npy` et non `.npz`, pour lire une ligne au hasard sans décompresser un bloc. Une ligne que le codec ne sait pas coder est exclue et comptée avec sa raison (`audit()`), jamais remplacée ; au-delà de 25 % le chargement échoue. `audit()` compte aussi les exemples dont une quantité ou un compte est arrondi de plus de 5 %.

## Ce dont chaque tête dépend

`ctx` = la sortie du tronc sur le dossier SELF.
- **Geste** : `ctx` et le masque de faisabilité (tout à 1 tant que le moteur n'en fournit pas).
- **Pointeurs** (≤ 3) : `ctx` + le geste. Masques exacts : « personne » seulement si le paramètre est facultatif ; seulement des dossiers des types qu'il accepte ; directions et formes seulement s'il les accepte. Les pointeurs ne dépendent **pas** les uns des autres.
- **Manières partagées** : `ctx` + le geste ; le niveau « aucun » seulement pour un paramètre facultatif.
- **Condition d'arrêt** : `ctx` + le geste ; ses arguments dépendent en plus de la condition (types d'argument masqués).
- **Écritures** : une chaîne de 4 pas. L'écriture *i* dépend de `ctx` + le geste + le plongement de l'écriture *i−1* (sa cible et sa variable). Cible, puis variable (masquée par le genre de la cible), puis valeur. Ordre imposé : cibles non décroissantes, variables croissantes sur une même cible ; une écriture sans variable légale restante n'est pas faite. Les écritures au-delà de leur nombre sont inertes.
- **Phrases** (parole, propositions d'écriture) : décodeur causal, parti du geste (parole) ou de la (cible, variable) de l'écriture. Masques : fin seulement arbre fermé ; arités permises par symbole ; un symbole pointeur ne vise qu'un dossier de son genre ; en génération, l'arbre doit pouvoir se fermer dans les 20 symboles. **L'automate de grammaire (types des arguments) n'est pas appliqué.**
- **Plan** (`PlanHead`, T11) : une chaîne de 8 positions (6 utilisables). L'étape *k* lit `ctx` + le geste de la décision + sa position + le plongement de l'étape *k−1* ; elle choisit un geste du registre **ou FIN** (après FIN, tout est FIN), puis **un** pointeur parmi les dossiers des types de `PLAN.step_targets` (le premier pointeur du geste ; « personne » seulement si le geste n'a pas de pointeur obligatoire). Puis `i_repeat` (valeurs d'énumération du registre), `i_repeat_period` (grille de quantités, lu seulement si `every`) et `g_parent` (un GOAL ou personne). Étiquettes présentes seulement si la décision porte la clé `plan` (`null` = « pas de plan », explicite) ; sinon `NO_LABEL`.
- **Arrêt de décision** (`StopHead`, T11) : la table de conditions existante, pour un geste **sans** `until` ; une classe de plus, « aucune » (= la capacité des conditions). Étiquette seulement si la décision porte la clé `stop`.
- En entraînement, chaque tête est conditionnée par la vraie valeur précédente ; en inférence par l'argmax. Mêmes modules, mêmes masques.

## Formes fixes, déterminisme

Le `Collator` prépare, à capacité fixe, les colonnes de mots compactées (K ∈ {12, 20, 38}), les lignes à proposition (≤ 32), les arêtes du graphe (≤ 16 par dossier, 0 perdue mesurée) et les phrases à écrire. Le `forward` n'a plus de `nonzero`, de branche dépendante des données ni d'addition atomique ; la perte et la génération se capturent dans un graphe CUDA (testé). `--fixed` / `pad_to` donnent les mêmes formes pour une décision seule et pour un lot.
Mesuré : le même lot deux fois donne des logits **identiques bit à bit** (CPU et GPU float16) ; une décision seule ou dans un lot de 16 (mêmes formes) diffère de 5e-4 au plus en float16 (noyaux différents selon la taille du lot) : pas identique bit à bit, mêmes décisions.

## Mesures [Mesuré]

Quadro RTX 3000, PyTorch 2.14, float16, GPU préchauffé, médiane de 3 séries, 88 dossiers remplis + 8 jetons fantômes, ±20 % d'un lancement à l'autre (portable). « Graphe » = rejoué depuis un graphe CUDA.

| | params | entraînement lot 32 | lot 128 | politique lot 32 (eager / graphe) | lot 128 | parole, 8 phrases (eager / graphe) | mémoire GPU entraîn. lot 128 / infér. lot 32 | bout en bout, lot 128 |
|---|---|---|---|---|---|---|---|---|
| `small` | 10,8 M | 79 ms = **403/s** | 136 ms = **939/s** | 20,2 / **11,2 ms** (2 860/s) | 38,7 ms | 115 / **14,1 ms** | 1,58 Go / 280 Mo | **938/s** |
| `base` | 28,5 M | 87 ms = **368/s** | 226 ms = **567/s** | 21,9 / 18,1 ms (1 760/s) | 64 ms | 129 / **17,7 ms** | 2,91 Go / 635 Mo | **505/s** |

Avant / après ce tour (`small`, même machine) : parole 8 phrases 102 ms → 115 ms en eager (le cache KV ne change rien tant que le lancement des noyaux domine) mais **14,1 ms en graphe** (objectif < 15 ms atteint en `small`, manqué en `base` : 17,7 ms) ; politique lot 32 : 12,9 ms eager → 20,2 ms eager (chaîne d'écritures, masques) mais 11,2 ms en graphe ; entraînement lot 32 : 530/s → 403/s, lot 128 : 1 047/s → 939/s (plus de noyaux, plus de mémoire : 1,35 → 1,58 Go) ; le chargement n'est plus le goulot (bout en bout = entraînement seul, 3 processus de chargement, mémoire épinglée).
Une passe de 1 M de décisions : environ 18 min en `small` (lot 128), 33 min en `base` [Estimé : 1 M / débit mesuré].

## Point de contrôle versionné et chargeur partiel (T11)

Version 3 : le point de contrôle porte `registry_schema` et la forme de chaque tenseur (`shapes`). **Un point de contrôle d'avant T11 (version 2) ne se charge PAS tel quel** : les formes ont changé (tables de symboles 1658 → 1694 depuis T09, décodeur 1660 → 1696, têtes de plan et d'arrêt nouvelles). Seul `Checkpoint.load(chemin, rt, partial=True)` (CLI : `train --init-from`) le lit, via `partial.py` : mêmes nom et forme → copié ; `embed.cat.emb`, `embed.prop.sym`, `decoder.sym` → les anciennes lignes gardent leur place (registre tok-2 en ajout seul), les lignes des nouveaux symboles gardent leurs poids initiaux, et les deux lignes de fin du décodeur (fin de séquence, début) **sont déplacées** à la fin de la table agrandie ; tenseur nouveau → poids initiaux ; autre forme sans règle → réinitialisé ; tenseur disparu → ignoré. `payload["load_report"]` liste tout (`new`, `reset`, `remapped`, `dropped`) et `payload["fingerprint_diff"]` les empreintes qui diffèrent. L'ordre des index de sortie du registre doit rester un préfixe du courant. Hypothèse non vérifiable sans l'ancien registre tok-2 : que ses symboles sont un préfixe du nouveau (la promesse « en ajout seul »). L'optimiseur repart à zéro.

## L'esprit écrit : apprendre les pas de réflexion (T11b)

`teacher/mind_replay.py` transforme une ligne planner (pensées écrites avant l'acte) en lignes `reflect` puis `act` (voir `teacher/README.md`). **Aucune tête, aucun registre, aucun catalogue, aucune interface tok-2 ne change** : un pas de réflexion est une décision ordinaire que les têtes existantes savent dire.

| Ce qu'une ligne `reflect` demande | Tête qui l'apprend |
|---|---|
| le geste est l'espace réservé `stop` (le moteur l'ignore en mode `reflect`) | tête de geste (le mode se lit dans `WAKE.mode`) |
| continuer ou agir | écriture `think_more` sur `me` (vrai sauf au dernier pas) : chaîne d'écritures, tête d'énumération |
| écrire UN dossier | croyance / but : écriture de `b_proposition` / `g_desired` sur la cible `new` (ou sur la clé du dossier révisé), phrase par le décodeur de phrases |
| plan | tête de plan (étapes, répétition, période, **parent = le but servi**, `g:new` devient la clé qu'il a reçue) ; une pensée qui n'est pas un plan porte `plan: null` (« pas de plan », explicite) |

Reconnaître une ligne `reflect` : son étiquette écrit `think_more` **et** porte une étiquette de plan (une ligne d'acte n'en a jamais). Les lignes d'un même esprit (`<id>#r0`, `#r1`, `#a`) restent du même côté du découpage entraînement / validation (le hachage porte sur l'`id` d'avant le `#`).
**Pertes** : deux termes en plus, sans paramètre neuf. `plan_first` (y a-t-il un plan : la position 0 de la tête de plan ; les 7 autres positions sont FIN presque toujours et noyaient la moyenne de `plan_gesture`) et `think_more` (les entrées de la tête d'énumération dont la variable est `think_more`). Sans étiquette (toutes les données plus anciennes) ils valent zéro.
**Évaluation** (`reflection.py`, branchée dans `evaluate.py` : section `reflection` du rapport, les lignes `reflect` sont retirées du jugement du validateur d'actes) : exactitude du **type** de pensée (belief, belief_about, goal, plan), de la **variable** écrite, de la **cible** (`new` ou le dossier révisé), de la **proposition** (exacte = même phrase canonique ; **valide** = le vrai `ThoughtChecker` accepte la pensée prédite sur l'esprit de l'état), du **plan** (exact, valide) et du `think_more` ; le tout aussi par type de pensée.

### Mesures [Mesuré] (copie de `serie_planner`, 2 652 lignes, `small`, 12 M, GPU, lot 64, 30 époques, lr 3e-4, validation = 5 % des situations)

- Rejeu : 2 635 lignes avec pensées, **4 094 exemples `reflect`** (croyance 1 497, but 2 035, plan 561, croyance sur autrui 1) + **2 651 `act`** ; **taux de rejeu valide 2 651 / 2 652 = 99,96 %** : une ligne refusée, dont une proposition de croyance (`(did @E1 speak @T7)`) que le `ThoughtChecker` accepte mais que tok-2 refuse (`speak` ne vise pas une chose) : un trou de validation du professeur, relevé. 6 744 des 6 745 lignes sont lisibles par l'élève.
- **Sur l'ensemble d'entraînement** (sous-échantillon, 1 001 pas, dans la même condition de décision libre) : type 97,6 %, variable 97,5 %, proposition exacte 90,7 % et valide 97,5 %, plan exact 94,8 %, `think_more` 99,2 % : **la chaîne apprend bien** (têtes, masques, phrases).
- **Sur la validation** (194 pas `reflect`) : type 58,2 % (majorité « but » : 51,0 %) ; variable 59,3 % ; cible 87,6 % ; proposition exacte 22,4 %, **valide 82,4 %** ; plan exact 8,3 % (n = 24), valide 12,5 % ; `think_more` 64,9 % (majorité 61,9 % ; avec le budget seul 67,0 %). Par type du but étiqueté : croyance 60 %, but 69 %, plan 17 %.
- **Lecture honnête** : sur ~2 600 lignes c'est un test de chaîne. L'écart entre l'entraînement (97 %) et la validation (58 %) est du sur-apprentissage, pas un défaut de câblage ; les chiffres de validation sont à peine au-dessus de la majorité. Ils ne diront quelque chose qu'avec des dizaines de milliers de lignes. Le test `tests/test_reflect.py` (modèle `tiny`, pensées synthétiques déterministes) vérifie que la chaîne apprend quand le signal existe (type, variable et `think_more` > 85 %, plan exact > 70 %).

Limites propres à ce rejeu : le mode, l'échéance, le parent et le début (`mode`, `deadline_h`, `parent`, `when_h`) d'un nouveau but sont écrits dans l'état suivant mais **pas appris** (une écriture sur `new` n'existe que pour les propositions, et la chaîne tient 4 écritures) ; la parole prévue d'un plan (`says`) non plus ; les champs que le moteur remplit à la création d'un dossier (source `inferred`, certitude 5, importance 5, ...) sont des **conventions du rejeu**, à remplacer par ce que le moteur écrira ; la décision de l'élève est apprise sur l'état « vrai » du professeur (guidage), pas encore sur ses propres sorties enchaînées ; `situations.audit` (qui demande la scène) n'est pas rejoué, seules les phrases ajoutées passent par le gouverneur.

## Limites

- Pas d'automate de grammaire dans le décodeur ; une phrase prédite peut être invalide (le gouverneur la refuserait). Les arbres plus profonds que 10 sont refusés à l'étiquetage.
- L'entraînement reste plus lent qu'avant en eager (formes fixes et masques coûtent des noyaux) ; seul le graphe CUDA donne les chiffres d'inférence ci-dessus.
- Condition d'arrêt avec un argument nom (`n:12`), mot avec compte ou degré (`all`) : non représentable, exemple écarté et compté. `i_steps` et `i_step_targets` s'écrivent par la tête de plan, pas par la chaîne d'écritures ; `tastes` n'est pas écrit.
- Quantification : 21 niveaux pour un nombre borné (échelle absolue ou dixièmes du pas) ; quantités et comptes exacts jusqu'à 256 (305 classes), puis échelle ×1,25 (≤ 11 % d'erreur, comptée par `audit()`).
- Mémoire par PNJ : un crochet seulement. La poignée stable par dossier que docs/09 demande à tok-2 n'existe pas.
- Une capacité dépassée (64 gestes, 128 variables, 128 formes...) est un changement de schéma, pas un ajout.

## Commandes

```
cd ai
python3 -m unittest discover -s student2/tests -t .          # 100 tests, ~3,5 min
python3 -m student2.output_registry --check                  # le registre de sortie couvre le catalogue ?
python3 -m student2.smoke --n 256 --seed 0 --out /tmp/smoke.jsonl          # réponses ALÉATOIRES valides (test seulement) ; --plans : avec plans et arrêts aléatoires
python3 -m student2.train --data /tmp/smoke.jsonl --smoke-test --size tiny --epochs 2 --batch 32 --out /tmp/run
python3 -m student2.train --data run/dataset.jsonl --size small --epochs 6 --out runs/a   # puis --resume runs/a/last.pt
python3 -m student2.bench --data /tmp/smoke.jsonl --smoke-test --sizes small base --batch 32 128 --end-to-end
```
