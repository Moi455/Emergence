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
