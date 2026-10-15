# 16. Quantification int8 de l'élève (student2)

Code : `ai/student2/evaluate.py` (exactitude par tête), `ai/student2/quantize.py` (quantificateurs, mesures, rapport), tests `ai/student2/tests/test_evaluate.py` et `test_quantize.py`. Résultats bruts (JSON) : voir « Reproduire ». Tout chiffre ci-dessous est **[Mesuré]** sur la Quadro RTX 3000 (Turing, sm_75), PyTorch 2.14, float16 (poids stockés en half, autocast), GPU préchauffé, médiane de 3 séries de 30 appels, mêmes lots que `bench.py` (politique `forward(teacher=False)`, eager et rejouée depuis un graphe CUDA).

## Avertissement : ce n'est pas une mesure de qualité absolue

- Les deux modèles sont **mauvais** : `small` (`a1`, 4 époques) fait 38,9 % de geste exact sur la validation ; `base` (`base1`, 40 époques) **surajuste** (perte d'entraînement 0,46, perte de validation 32,8 ; geste 36,1 % sur validation). Le fichier compte 3 928 lignes, dont 3 906 utilisables ; la validation (hachage de `id`, 5 %) n'en garde que **180 décisions** : 24 phrases de parole, 8 conditions d'arrêt, etc. Les petits `n` donnent des écarts de plusieurs points qui ne sont pas du signal.
- La comparaison fp16 / int8 porte donc sur **l'accord des décisions** (même geste ET mêmes pointeurs ; décision entière), pas sur la qualité du comportement. Sur un modèle bien entraîné, la sensibilité à la quantification peut être différente : à refaire quand il existera.
- La colonne « toutes les lignes » inclut les lignes d'entraînement (3 906 décisions, sans étiquette nécessaire) : elle donne un accord plus serré mais sur des exemples que `base` a mémorisés.

## Ce qui a été fait

| Méthode | Principe | Ce qui marche réellement ici |
|---|---|---|
| `Fp16Reference` | modèle en half | référence |
| `WeightOnlyInt8` | poids int8, une échelle par canal de sortie, **déquantifiés à chaque appel** | oui |
| `DynamicInt8` (W8A8) | poids int8 par canal + activations int8 par ligne (absmax) à l'exécution, produit par `torch._int_mm` (int8 -> int32) | oui, avec contraintes (ci-dessous) |
| `torch.ao.quantization.quantize_dynamic` | | **non utilisé** : chemin CPU (fbgemm), pas de noyau CUDA |

Contraintes de `torch._int_mm` mesurées sur ce GPU : M > 16 lignes ; **M multiple de 32** (24, 40, 48, 72, 1000 échouent avec `CUBLAS_STATUS_NOT_SUPPORTED`, 32/64/96/128/1024 passent) ; **M < 65 536** (65 536 échoue : le lot 128 déclenchait 102 400 lignes dans l'encodeur de propositions) ; K et N multiples de 8. Le code complète les lignes à 32, découpe en blocs de 32 768, et retombe sur le chemin poids-seul pour les appels qui ne conviennent pas (compteurs `int_mm_calls` / `fallback_calls`). Bug trouvé et corrigé pendant le travail : la première version plantait au lot 128.

Portée (`Scope`) : `all` = toutes les couches linéaires possibles ; `body` = `all` sauf les couches dont la sortie **est** un logit ou un score de pointeur (geste, manières, condition, écritures, têtes de nombres, têtes symbole/arité/compte du décodeur, requêtes et clés de pointeurs), gardées en fp16. Jamais quantifiées, quelle que soit la portée : `embed.num.l1` et `embed.prop.count` (le modèle lit leur `.weight.dtype`), les embeddings, les normes, les masques. Les points de reprise sont lus en `torch.load(weights_only=True)` (aucun pickle) puis contrôlés comme `train.py`.

## Résultats : `small` (a1, 4 époques)

[Mesuré] Taille = paramètres + tampons persistants. « Poids GPU / pic » = mémoire GPU allouée après chargement du modèle / pic pendant une passe (poids compris). Lot 32 et 128, politique eager / graphe CUDA.

| variante | taille (Mo) | poids GPU / pic lot 32 (Mo) | poids GPU / pic lot 128 (Mo) | politique lot 32 eager / graphe (ms) | politique lot 128 eager / graphe (ms) | accord geste+pointeurs | accord décision entière | accord geste+pointeurs, toutes les lignes |
|---|---|---|---|---|---|---|---|---|
| fp16 | 20.88 | 21.0 / 99.0 | 21.0 / 334.2 | 13.05 / 11.39 | 40.06 / 40.33 | (réf.) | (réf.) | (réf.) |
| int8-weights/body | 13.64 | 13.76 / 91.8 | 13.76 / 326.9 | 13.88 / 11.98 | 40.83 / 40.94 | 100.0 % | 100.0 % | 99.9 % (3906) |
| int8-w8a8/body | 13.64 | 13.76 / 140.7 | 13.76 / 665.5 | 26.6 / 26.57 | 101.52 / 101.39 | 99.4 % | 98.9 % | 99.7 % (3906) |
| int8-weights/all | 12.1 | 12.23 / 90.3 | 12.23 / 325.4 | 15.34 / 12.47 | 41.72 / 41.7 | 100.0 % | 97.8 % | 99.8 % (3906) |
| int8-w8a8/all | 12.1 | 12.23 / 139.2 | 12.23 / 664.0 | 28.66 / 28.66 | 108.03 / 107.95 | 98.9 % | 96.7 % | 99.5 % (3906) |

Exactitude contre le professeur (points de pourcentage de variation par rapport à fp16 entre parenthèses) :

| métrique (n) | fp16 | int8-weights/body | int8-w8a8/body | int8-weights/all | int8-w8a8/all |
|---|---|---|---|---|---|
| gesture.top1 (180) | 38.9 % | 38.9 % (+0.0) | 38.9 % (+0.0) | 38.9 % (+0.0) | 38.9 % (+0.0) |
| gesture.top3 (180) | 69.4 % | 69.4 % (+0.0) | 69.4 % (+0.0) | 68.9 % (-0.6) | 68.9 % (-0.6) |
| pointers.per_pointer (166) | 41.6 % | 41.6 % (+0.0) | 41.6 % (+0.0) | 41.6 % (+0.0) | 41.6 % (+0.0) |
| pointers.all_pointers_of_decision (142) | 38.7 % | 38.7 % (+0.0) | 38.7 % (+0.0) | 38.7 % (+0.0) | 38.7 % (+0.0) |
| manner.per_value (375) | 34.7 % | 34.7 % (+0.0) | 34.7 % (+0.0) | 34.7 % (+0.0) | 34.7 % (+0.0) |
| stop_condition.condition (8) | 0.0 % | 0.0 % (+0.0) | 0.0 % (+0.0) | 0.0 % (+0.0) | 0.0 % (+0.0) |
| writes.n_writes (180) | 80.6 % | 80.6 % (+0.0) | 80.6 % (+0.0) | 80.6 % (+0.0) | 80.6 % (+0.0) |
| writes.target_and_variable (149) | 14.1 % | 14.1 % (+0.0) | 14.1 % (+0.0) | 14.1 % (+0.0) | 14.1 % (+0.0) |
| writes.write_exact (149) | 4.0 % | 4.0 % (+0.0) | 4.0 % (+0.0) | 4.0 % (+0.0) | 4.0 % (+0.0) |
| writes.write_set_exact (147) | 4.1 % | 4.1 % (+0.0) | 4.1 % (+0.0) | 4.1 % (+0.0) | 4.1 % (+0.0) |
| sequences.speech_exact (24) | 12.5 % | 12.5 % (+0.0) | 12.5 % (+0.0) | 12.5 % (+0.0) | 12.5 % (+0.0) |
| décision valide pour le validateur (gouverneur) | 95.0 % | 95.0 % | 95.0 % | 95.0 % | 95.0 % |
## Résultats : `base` (base1, 40 époques, surajusté)

[Mesuré] Taille = paramètres + tampons persistants. « Poids GPU / pic » = mémoire GPU allouée après chargement du modèle / pic pendant une passe (poids compris). Lot 32 et 128, politique eager / graphe CUDA.

| variante | taille (Mo) | poids GPU / pic lot 32 (Mo) | poids GPU / pic lot 128 (Mo) | politique lot 32 eager / graphe (ms) | politique lot 128 eager / graphe (ms) | accord geste+pointeurs | accord décision entière | accord geste+pointeurs, toutes les lignes |
|---|---|---|---|---|---|---|---|---|
| fp16 | 55.02 | 55.52 / 172.4 | 55.24 / 524.9 | 18.49 / 18.49 | 68.2 / 68.2 | (réf.) | (réf.) | (réf.) |
| int8-weights/body | 33.1 | 33.26 / 150.2 | 33.26 / 502.9 | 19.42 / 19.36 | 69.1 / 69.03 | 99.4 % | 98.3 % | 100.0 % (3906) |
| int8-w8a8/body | 33.1 | 33.26 / 220.5 | 33.26 / 1009.4 | 45.01 / 44.96 | 172.47 / 172.33 | 99.4 % | 98.3 % | 100.0 % (3906) |
| int8-weights/all | 30.04 | 30.21 / 147.1 | 30.21 / 499.9 | 19.91 / 19.88 | 70.17 / 70.14 | 98.9 % | 97.8 % | 99.9 % (3906) |
| int8-w8a8/all | 30.04 | 30.21 / 217.5 | 30.21 / 1006.3 | 48.02 / 47.98 | 181.15 / 180.9 | 99.4 % | 98.3 % | 100.0 % (3906) |

Exactitude contre le professeur (points de pourcentage de variation par rapport à fp16 entre parenthèses) :

| métrique (n) | fp16 | int8-weights/body | int8-w8a8/body | int8-weights/all | int8-w8a8/all |
|---|---|---|---|---|---|
| gesture.top1 (180) | 36.1 % | 36.7 % (+0.6) | 36.1 % (+0.0) | 37.2 % (+1.1) | 36.1 % (+0.0) |
| gesture.top3 (180) | 62.8 % | 62.8 % (+0.0) | 62.8 % (+0.0) | 62.8 % (+0.0) | 62.8 % (+0.0) |
| pointers.per_pointer (166) | 39.8 % | 40.4 % (+0.6) | 39.8 % (+0.0) | 40.4 % (+0.6) | 39.8 % (+0.0) |
| pointers.all_pointers_of_decision (142) | 35.9 % | 36.6 % (+0.7) | 35.9 % (+0.0) | 36.6 % (+0.7) | 35.9 % (+0.0) |
| manner.per_value (375) | 30.1 % | 30.7 % (+0.5) | 30.1 % (+0.0) | 30.9 % (+0.8) | 30.1 % (+0.0) |
| stop_condition.condition (8) | 25.0 % | 25.0 % (+0.0) | 25.0 % (+0.0) | 25.0 % (+0.0) | 25.0 % (+0.0) |
| writes.n_writes (180) | 71.7 % | 71.7 % (+0.0) | 71.7 % (+0.0) | 71.7 % (+0.0) | 71.7 % (+0.0) |
| writes.target_and_variable (149) | 8.1 % | 8.1 % (+0.0) | 8.1 % (+0.0) | 8.1 % (+0.0) | 8.1 % (+0.0) |
| writes.write_exact (149) | 1.3 % | 1.3 % (+0.0) | 1.3 % (+0.0) | 1.3 % (+0.0) | 1.3 % (+0.0) |
| writes.write_set_exact (147) | 1.4 % | 1.4 % (+0.0) | 1.4 % (+0.0) | 1.4 % (+0.0) | 1.4 % (+0.0) |
| sequences.speech_exact (24) | 16.7 % | 16.7 % (+0.0) | 16.7 % (+0.0) | 16.7 % (+0.0) | 16.7 % (+0.0) |
| décision valide pour le validateur (gouverneur) | 96.1 % | 96.1 % | 96.1 % | 96.1 % | 96.1 % |
## Lecture (tous les chiffres sont dans les tableaux ci-dessus)

- **Poids seuls int8** : taille -35 % (small) à -40 % (base) (`small` 20,9 -> 13,6 Mo en `body`, 12,1 en `all` ; `base` 55,0 -> 33,1 / 30,0 Mo), mémoire des poids sur GPU dans les mêmes proportions. Latence : **aucun gain** (small lot 32 graphe 11,4 -> 12,0 ms ; lot 128 40,3 -> 40,9 ms ; base lot 128 68,2 -> 69,0 ms) : on déquantifie en half puis on refait le même produit ; le gain est la mémoire, pas la vitesse. L'accord geste+pointeurs avec fp16 est de 98,9 à 100 % sur la validation et de 99,8 à 100 % sur toutes les lignes.
- **W8A8 `torch._int_mm`** : accord comparable (98,9 à 99,4 % sur la validation, 99,5 à 100 % sur toutes les lignes), mais **2 à 2,6 fois plus lent** que fp16 (small lot 128 : 40,3 -> 101,4 ms en `body`, 108 ms en `all` ; base lot 128 : 68,2 -> 172 / 181 ms) et **pic mémoire x2** au lot 128 (small 334 -> 666 Mo ; base 525 -> 1 009 Mo) : les temporaires float32 de quantification et de rééchelonnement. Mesure isolée d'une couche 384x1536 sur 2 816 lignes : le noyau `_int_mm` seul prend 0,12 ms contre 0,22 ms pour le produit fp16, mais la quantification des activations et le rééchelonnement ajoutent plus que ce gain en PyTorch eager (profil : noyaux élémentaires à diffusion non vectorisés). Un noyau fusionné (Triton, ou le moteur d'inférence livré, TensorRT-RTX) pourrait changer ce résultat ; **ce n'est pas mesuré ici**. Beaucoup d'appels retombent sur le chemin poids-seul (p. ex. `small`/`body` : 444 appels `_int_mm`, 1 518 de repli, car M <= 16 dans les têtes et le décodeur).
- **Portée** : garder les têtes en fp16 (`body`) coûte 1,5 Mo (`small`) / 3 Mo (`base`). Sur ces échantillons il n'y a pas de différence nette d'exactitude entre `body` et `all` (`small` : accord décision entière 100 % / 97,8 % en poids seuls ; `base` : 98,3 % / 97,8 %) : 180 décisions ne permettent pas de trancher ; par prudence `body` est le défaut.
- **Exactitude par tête contre le professeur** : variation toujours <= 1,1 point, dans les deux sens (`base` +0,6 à +1,1 sur geste/pointeurs/manières en int8 poids seuls : bruit sur 180 exemples, pas une amélioration). Sur `small`, seul `gesture.top3` baisse de 0,6 point en `all`.
- **Validité au sens du validateur** : identique pour toutes les variantes (`small` 95,0 % : 171 acceptées, 9 « non décodables » ; `base` 96,1 % : 173 acceptées, 7 `bad_speech`). Les étiquettes du professeur passent à 100 %. Cette validité est peu discriminante : une décision fausse mais bien formée est acceptée.
- fp16 contre poids fp32 en autocast (ce que mesure `bench.py`) : accord geste+pointeurs 100 % (`small` : décision entière 99,4 %, `base` 100 %).

## Limites

- 180 décisions de validation ; modèles faibles ; pas de modèle bien entraîné. Rien ici ne prouve l'innocuité de l'int8 sur un modèle final.
- Les chiffres de latence varient d'environ 20 % d'un lancement à l'autre (portable) ; un seul lancement par modèle.
- Non calculable proprement et donc non rapporté : un top-k autre que celui du geste ; l'égalité sémantique des phrases (la parole « exacte » est l'égalité pas à pas, une borne basse). La « validité de la parole » seule est la grammaire du langage (`Toolkit.expression`) : le gouverneur ne juge que la décision entière (codes de refus dans le JSON). Une ligne sans `source.ages` est validée avec des âges réels inconnus.
- Pas de calibration d'activations (SmoothQuant, etc.), pas de quantification de l'entrée numérique ni des embeddings, pas de int4/fp8 (pas de fp8 natif sur Turing).
- Observation hors périmètre : `teacher/validate.py` lève `KeyError: 'plan'` (`PROPOSITION_KIND` n'a pas de clé `plan`) quand une écriture de proposition vise un plan ; le générateur de test aléatoire `student2.smoke` (graine 5) le déclenche. `evaluate.py` compte ce plantage (`validator_crash:KeyError`) au lieu de le cacher. Non corrigé.

## Reproduire

```
cd ai
python3 -m student2.evaluate --ckpt ~/.local/share/emergence/runs/a1/last.pt --data ~/.local/share/emergence/runs/snap_migre.jsonl --out ev.json
python3 -m student2.quantize --wide --ckpt ~/.local/share/emergence/runs/base1/last.pt --data ~/.local/share/emergence/runs/snap_migre.jsonl --out q_base1.json   # écrit aussi q_base1.md
python3 -m unittest discover -s student2/tests -t .        # 69 tests
```


## xl vs small : l'étalon quantifié contre le petit non quantifié

Décision de Monsieur (15 oct.) : un Transformer **beaucoup trop gros** pour tenir le budget, quantifié, comparé aux petits non quantifiés. Code : `ai/student2/compare.py` (reproductible), taille `xl` dans `model.py` (`SIZES["xl"]`), tests `ai/student2/tests/test_xl.py`. Tout chiffre est **[Mesuré]** (Quadro RTX 3000 6 Go, PyTorch 2.14, float16, graine 0), sauf mention.

**La taille `xl`** : d=768, 16 couches, 12 têtes, ff 3072, décodeur 4 couches ff 2048, encodeur de propositions d=256 : **175,3 M de paramètres** (`small` : 12,1 M ; `base` : 28,5 M ; le tronc fait 113 M). Dropout résiduel 0,1 et gradient checkpointing ajoutés à `StudentConfig` (champs `dropout`, `checkpoint`, valeurs par défaut = ancien comportement ; un ancien point de contrôle se charge). Entraînement fp16 + AdamW sur 6 Go : **tient** (pic 3,8 Go au lot 32, 4,4 Go au lot 64 ; **sans** checkpointing 5,0 Go au lot 32 et le lot 64 sort de mémoire ; lot 128 sort de mémoire même avec). Débit d'entraînement : ~95 décisions/s (lot 32) contre ~220-270 pour `small`. Pas besoin de réduire : 175 M tient. Au lot 32, des alertes d'allocateur (quasi-OOM, récupérées) apparaissent dans le journal.

**Protocole** : mêmes lignes, même découpage (hachage de l'`id`), même graine, même lot 32, même dropout 0,1 et weight decay 0,1, au plus 12 époques avec arrêt sur la perte de validation (patience 3, meilleure époque restaurée) ; lr 3e-4 (`small`) et 1e-4 (`xl`). Même évaluateur et mêmes lots de validation pour les quatre variantes ; quantification `body` (têtes de sortie en fp16). Empreinte d'interface des données et du code : `009376fdb3dbadf2` (registre `2baec3a96dbc2909`). Données copiées dans `~/.local/share/emergence/runs/xl_vs_small/` (`serie1_copy.jsonl`, `planner_copy.jsonl`).

**Mise en garde, à lire d'abord** : c'est un **test de chaîne**, pas un classement des tailles. Les données sont petites, l'époque d'arrêt est choisie sur la validation même qui sert aux scores (légèrement optimiste, pareil pour les deux), et `xl` surajuste dès l'époque 5 (perte d'entraînement 6,9 contre validation 11,7 à l'époque 7). Les écarts d'exactitude de 1 à 3 points sur 505 à 626 décisions ne sont pas du signal. Les plans n'ont pas de ligne propre dans les tableaux (têtes de plan non rapportées par `evaluate.py` ici).

### Passe 1 : série réactive seule (9 816 lignes, aucune planificatrice)

Données : 9311 entraînement / 505 validation, graine 0.

| modèle | params (M) | lr | époques jouées / retenue | perte entraînement (retenue) | perte validation (retenue) | débit entraînement (déc/s) | pic mémoire entraînement (Mo) |
|---|---|---|---|---|---|---|---|
| small | 12.12 | 0.0003 | 8 / 5 | 8.3738 | 9.4646 | 220.4 | 631 |
| xl | 175.27 | 0.0001 | 7 / 4 | 9.2168 | 10.1796 | 94.1 | 3793 |

| variante | geste top-1 | geste top-3 | pointeurs (geste juste) | manières (geste juste) | condition d'arrêt (geste juste) | nombre d'écritures | écriture exacte | parole exacte (geste juste) | décision valide (validateur) |
|---|---|---|---|---|---|---|---|---|---|
| small fp16 | 39.8 % | 69.9 % | 81.1 % | 77.8 % | 100.0 % | 72.7 % | 4.3 % | 27.8 % | 95.8 % |
| xl fp16 | 39.6 % | 72.9 % | 74.7 % | 80.2 % | 100.0 % | 73.1 % | 4.0 % | 29.4 % | 99.8 % |
| xl int8-weights/body | 39.6 % | 72.9 % | 74.7 % | 80.2 % | 100.0 % | 73.1 % | 4.0 % | 29.4 % | 99.8 % |
| xl int8-w8a8/body | 39.6 % | 72.7 % | 75.3 % | 80.2 % | 100.0 % | 73.1 % | 4.0 % | 29.4 % | 99.8 % |

| variante | taille (Mo) | poids GPU (Mo) | pic inférence lot 32 / 128 (Mo) | politique lot 32 / 128 (ms, graphe) | décisions/s lot 32 / 128 | coût GPU à 200 déc/s, lot 32 / 128 | vs budget 25% | accord geste+pointeurs avec le fp16 | accord décision entière |
|---|---|---|---|---|---|---|---|---|---|
| small fp16 | 23.12 | 23.25 | 101.3 / 337.3 | 13.09 / 43.26 | 2445 / 2959 | 0.082 / 0.068 | x0.3 (tient) | (réf.) | (réf.) |
| xl fp16 | 334.29 | 348.54 | 508.1 / 982.4 | 65.85 / 245.35 | 486 / 522 | 0.412 / 0.383 | x1.6 (dépasse) | (réf.) | (réf.) |
| xl int8-weights/body | 189.16 | 192.34 | 351.9 / 826.6 | 72.79 / 250.96 | 440 / 510 | 0.455 / 0.392 | x1.8 (dépasse) | 99.8 % | 92.9 % |
| xl int8-w8a8/body | 189.16 | 192.34 | 446.7 / 1501.8 | 138.57 / 529.06 | 231 / 242 | 0.866 / 0.827 | x3.5 (dépasse) | 99.2 % | 84.4 % |

### Passe 2 : réactive + planificatrice (2 647 lignes avec pensées et plans)

Données : 11837 entraînement / 626 validation, graine 0.

| modèle | params (M) | lr | époques jouées / retenue | perte entraînement (retenue) | perte validation (retenue) | débit entraînement (déc/s) | pic mémoire entraînement (Mo) |
|---|---|---|---|---|---|---|---|
| small | 12.12 | 0.0003 | 8 / 5 | 8.3005 | 9.0926 | 269.7 | 630 |
| xl | 175.27 | 0.0001 | 7 / 4 | 8.979 | 9.8433 | 96.6 | 3789 |

| variante | geste top-1 | geste top-3 | pointeurs (geste juste) | manières (geste juste) | condition d'arrêt (geste juste) | nombre d'écritures | écriture exacte | parole exacte (geste juste) | décision valide (validateur) |
|---|---|---|---|---|---|---|---|---|---|
| small fp16 | 40.6 % | 73.8 % | 84.6 % | 80.1 % | 100.0 % | 69.2 % | 5.5 % | 29.5 % | 22.7 % |
| xl fp16 | 40.9 % | 71.9 % | 77.2 % | 81.1 % | 83.3 % | 68.2 % | 2.3 % | 30.2 % | 5.4 % |
| xl int8-weights/body | 40.9 % | 71.9 % | 77.2 % | 81.1 % | 83.3 % | 68.2 % | 2.3 % | 30.2 % | 5.8 % |
| xl int8-w8a8/body | 40.7 % | 71.9 % | 77.1 % | 81.2 % | 83.3 % | 68.2 % | 2.3 % | 30.2 % | 5.4 % |

| variante | taille (Mo) | poids GPU (Mo) | pic inférence lot 32 / 128 (Mo) | politique lot 32 / 128 (ms, graphe) | décisions/s lot 32 / 128 | coût GPU à 200 déc/s, lot 32 / 128 | vs budget 25% | accord geste+pointeurs avec le fp16 | accord décision entière |
|---|---|---|---|---|---|---|---|---|---|
| small fp16 | 23.12 | 23.25 | 101.3 / 337.3 | 13.07 / 42.95 | 2448 / 2980 | 0.082 / 0.067 | x0.3 (tient) | (réf.) | (réf.) |
| xl fp16 | 334.29 | 348.54 | 508.1 / 982.4 | 65.2 / 239.82 | 491 / 534 | 0.408 / 0.375 | x1.6 (dépasse) | (réf.) | (réf.) |
| xl int8-weights/body | 189.16 | 192.34 | 351.9 / 826.6 | 71.39 / 246.07 | 448 / 520 | 0.446 / 0.384 | x1.8 (dépasse) | 99.8 % | 93.6 % |
| xl int8-w8a8/body | 189.16 | 192.34 | 446.7 / 1501.8 | 137.71 / 525.22 | 232 / 244 | 0.861 / 0.821 | x3.4 (dépasse) | 99.0 % | 85.5 % |

La « décision valide » s'effondre en passe 2 pour les deux modèles (`small` 22,7 %, `xl` 5,4 %) : codes `bad_pointer` / `bad_param` en masse (voir `results.json`). Non expliqué ici (le modèle n'a vu que 4 époques de plans, ou le validateur hors ligne juge mal les décisions à plan) : ne pas lire ce chiffre comme une qualité. Les étiquettes du professeur ne sont pas revalidées dans ce tableau.

### Lecture

- **Coût GPU** : `xl` fp16 prend **0,41 de GPU à 200 déc/s (lot 32), 0,38 (lot 128)**, soit **1,5 à 1,6 fois le budget de 25 %** : il dépasse clairement, comme voulu. `small` : 0,07 à 0,08 (tient). Estimation = 200 x temps de politique par décision, parole non comptée (donc plus bas que le coût réel).
- **L'int8 ne rend pas `xl` plus rapide ici** : poids seuls 0,45 / 0,39 (déquantification à chaque appel : plus lent que fp16) ; W8A8 0,86 / 0,83, **plus lent encore** (2 784 appels `_int_mm` contre 8 080 retombées sur le chemin poids-seuls : trop peu de lignes par appel, plus la quantification des activations). Il ne ramène pas `xl` dans le budget. Il réduit la taille (334 -> 189 Mo) et la mémoire de poids (349 -> 192 Mo), mais le pic en W8A8 est **plus haut** au lot 128 (1 502 Mo contre 982 Mo).
- **Fidélité à fp16** : poids seuls 99,8 % d'accord geste+pointeurs, 92,9-93,6 % de décision entière ; W8A8 99,0-99,2 % et 84,4-85,5 %. Exactitudes par tête presque identiques à fp16 (écart <= 0,6 point en passe 1, <= 0,2 en passe 2).
- **xl contre small** : à ce volume de données, `xl` n'est pas meilleur que `small` (geste top-1 39,6 % contre 39,8 % ; 40,9 % contre 40,6 %), il est pire en perte de validation (10,2 contre 9,5 ; 9,8 contre 9,1). Le gros modèle ne montre aucun avantage tant que les données restent aussi peu nombreuses.

### Limites

Un seul lancement par passe (graine 0, latences ±20 %) ; pas de répétition de graine ; hyperparamètres non réglés (lr, dropout, decay) ; quantification `body` seulement dans ce tableau ; pas de mesure de la parole ni du débit de bout en bout d'`xl`. À relancer avec plus de données planificatrices (T12/T36) : `python3 -m student2.compare --data <fichiers> --out <dossier>` (`--reuse` pour re-quantifier sans réentraîner).


### Correction : l'effondrement de validité de la passe 2 était un artefact (enquête du 15 oct.)

**Cause, avec preuves.** Ce n'était pas la qualité des modèles.
1. Le contrôle témoin passe : les étiquettes du professeur sont validées à 100 % (626/626) par le même validateur.
2. Rejouer le modèle de la passe 1 (qui affichait 95,8 %) avec le code du 15 oct. 11 h donne 25,7 % ; en retirant `plan` et `stop` de ses décisions, 95,8 % (484/505). Les refus lus à la main sont tous de la forme « plan step 1: sleep cannot act on '@G3' » : le modèle émet un plan de 6 pas (et un `stop`) sur presque toutes les décisions (609/626 plans), sans rapport avec l'étiquette.
3. Pourquoi ce n'était pas visible avant : `teacher/migrate.py` (`Migration.raw_answer`) ne transmettait pas `plan`/`stop`/`thoughts` au validateur avant 07 h 05 ; la passe 1 a importé l'ancienne version. Depuis, le validateur juge aussi le plan. Or **les têtes de plan et d'arrêt n'avaient jamais reçu d'étiquette** : elles sortaient des poids aléatoires.
4. Trou de pipeline confirmé : le format planificateur (T36) range le plan dans `decision["thoughts"]` (entrées `kind: plan`, 560 lignes sur 2 647 ; 2 630 lignes portent des pensées), jamais dans `plan`. `labels.py` ne lisait que `plan`/`stop` de premier niveau et **ignorait `thoughts` sans le compter**. Aucune des deux séries ne porte de clé `stop`.

**Corrigé dans `ai/student2`** (tests : `tests/test_xl.py::ThoughtsPlanTest`, 95 tests de la suite verts) :
- `labels.py` : `LabelCodec.plan_of` lit le plan de premier niveau, sinon le premier `thoughts[kind=plan]` converti (`serves` -> `parent`, `g:new` -> pas de parent, `says` non appris) ; une trace sans plan = « pas de plan » explicite ; sans trace = pas d'étiquette. Résultat : 560 plans et 2 087 « pas de plan » étiquetés.
- `data.py` : `CACHE_VERSION` 2 -> 3. Constat : le cache de jetons (clé = empreintes du catalogue + octets de la ligne) **ne se périme pas quand `labels.py` change** ; une première relance a donc entraîné sur d'anciennes cibles sans plan (plans `n = 0`). À retenir à chaque changement de `labels.py`.
- `evaluate.py` : une étiquette sans plan/stop (`NO_LABEL`) ne fait plus juger le plan/stop prédit (comme `Trainer.exact_match`) ; nouvelle section `plans` du rapport (présence d'un plan, geste et cible de chaque pas étiqueté).
- Non corrigé, signalé : les **pensées elles-mêmes** (croyances, buts : ~1 931 buts et 1 498 croyances sur `target: new`) ne sont apprises par aucune tête ; `labels.py` n'a pas de représentation pour elles (travail de schéma de sortie, pas un correctif).

**Relance sur `planner_copy.jsonl` seul** (2 526 entraînement / 121 validation, plans étiquetés, mêmes réglages ; données et résultats dans `runs/xl_vs_small/run3b`). Validité : `small` **96,7 %**, `xl` **86,0 %** (xl : 16 `bad_speech`). Plans : présence correcte 80,2 % (la ligne « jamais de plan » donnerait ~79 %), **gestes et cibles des pas 0 % sur 31 pas étiquetés** : la tête de plan n'apprend que « pas de plan » avec 560 plans. Les chiffres de coût GPU, de taille et d'accord int8 (99,2 % d'accord de décision entière, 100 % geste+pointeurs) sont les mêmes qu'en passe 1. Les tableaux des passes 1 et 2 ci-dessus restent exacts pour les têtes réactives ; la colonne « décision valide » de la passe 2 est à ignorer.

Données : 2526 entraînement / 121 validation, graine 0.

| modèle | params (M) | lr | époques jouées / retenue | perte entraînement (retenue) | perte validation (retenue) | débit entraînement (déc/s) | pic mémoire entraînement (Mo) |
|---|---|---|---|---|---|---|---|
| small | 12.12 | 0.0003 | 10 / 7 | 9.293 | 11.76 | 253.1 | 630 |
| xl | 175.27 | 0.0001 | 7 / 4 | 12.8409 | 12.396 | 93.4 | 3788 |

| variante | geste top-1 | geste top-3 | pointeurs (geste juste) | manières (geste juste) | condition d'arrêt (geste juste) | nombre d'écritures | écriture exacte | parole exacte (geste juste) | décision valide (validateur) |
|---|---|---|---|---|---|---|---|---|---|
| small fp16 | 36.4 % | 66.1 % | 82.9 % | 86.2 % | n/a | 52.1 % | 0.0 % | 57.1 % | 96.7 % |
| xl fp16 | 38.8 % | 62.8 % | 81.0 % | 86.1 % | n/a | 51.2 % | 3.2 % | 0.0 % | 86.0 % |
| xl int8-weights/body | 38.8 % | 62.8 % | 81.0 % | 86.1 % | n/a | 51.2 % | 3.2 % | 0.0 % | 86.0 % |
| xl int8-w8a8/body | 38.8 % | 62.8 % | 81.0 % | 86.1 % | n/a | 51.2 % | 3.2 % | 0.0 % | 86.0 % |

| variante | taille (Mo) | poids GPU (Mo) | pic inférence lot 32 / 128 (Mo) | politique lot 32 / 128 (ms, graphe) | décisions/s lot 32 / 128 | coût GPU à 200 déc/s, lot 32 / 128 | vs budget 25% | accord geste+pointeurs avec le fp16 | accord décision entière |
|---|---|---|---|---|---|---|---|---|---|
| small fp16 | 23.12 | 23.25 | 101.3 / 337.3 | 12.99 / 42.73 | 2463 / 2996 | 0.081 / 0.067 | x0.3 (tient) | (réf.) | (réf.) |
| xl fp16 | 334.29 | 348.54 | 508.1 / 982.4 | 64.79 / 240.44 | 494 / 532 | 0.405 / 0.376 | x1.6 (dépasse) | (réf.) | (réf.) |
| xl int8-weights/body | 189.16 | 192.34 | 351.9 / 826.6 | 71.94 / 249.86 | 445 / 512 | 0.45 / 0.39 | x1.8 (dépasse) | 100.0 % | 99.2 % |
| xl int8-w8a8/body | 189.16 | 192.34 | 446.7 / 1501.8 | 138.07 / 533.69 | 232 / 240 | 0.863 / 0.834 | x3.5 (dépasse) | 100.0 % | 99.2 % |
