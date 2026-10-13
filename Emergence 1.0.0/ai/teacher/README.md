# Le format du professeur

Un professeur (Gemini, ou un modèle local) reçoit la situation d'un PNJ (ce qu'il perçoit, croit, retient et veut, jamais la vérité de la scène) et rend SA décision : un geste paramétré (parler en est un, avec une parole dans la langue intérieure) et au plus 4 écritures de variables bornées. Ces décisions serviront d'étiquettes d'imitation pour le Transformer. Le gouverneur filtre tout (bornes, règle dure D10).

- **`render.py`** : situation -> texte anglais compact. Seuls les dossiers sont lus, jamais `situation.scene`. Chaque proposition est écrite en S-expression, suivie d'une glose anglaise. Les clés (`@E1`, `@T3`, `b:2`, `me`...) restent visibles pour que le professeur réponde avec elles. Seuls les traits, valeurs, émotions et besoins saillants sont listés.
- **`schema.py`** : le texte fixe (rôle, gestes, échelles, conditions d'arrêt, langue intérieure, variables écrivables, règle D10, mots) et le schéma JSON de la réponse (sous-ensemble OpenAPI de Gemini), plus une grammaire GBNF équivalente (non essayée ici). Tout est tiré de `model_interface.json` : le catalogue change, le prompt change.
- **`validate.py`** : réponse JSON + situation -> décision normalisée, ou refus avec un code stable (`invalid_json`, `bad_shape`, `unknown_gesture`, `too_many_writes`, `bad_param`, `bad_pointer`, `bad_speech`, `bad_write`, `governor:<code>`). Le gouverneur voit la vérité côté moteur : âges réels tirés de la scène, âges apparents et crus tirés des dossiers.
- **`gemini.py`** : client REST en `urllib` (generateContent en JSON structuré, countTokens, models.list), limiteur de débit, repli Flash Lite puis Flash, chargeur de clé.
- **`pilot.py`** : la ligne de commande.

## Utilisation

```
cd ai
python3 -m teacher.pilot --n 20 --seed 0            # essai à blanc : aucun réseau
python3 -m teacher.pilot --call --list-models       # liste les modèles utilisables (réseau)
python3 -m teacher.pilot --call --n 20              # VRAIS appels (quota gratuit ; accord de Monsieur)
python3 -m unittest discover -s ai/teacher/tests -t ai
```

L'essai à blanc écrit `system.txt`, `schema.gemini.json`, `schema.json`, `grammar.gbnf`, `prompts/NNNN.txt` et `sizes.json` dans `~/.local/share/emergence/teacher/<horodatage>/` (hors du dépôt ; le programme refuse d'écrire dans le dépôt). Les jetons y sont des estimations (caractères / 4) ; les vrais comptes viennent de `countTokens` avec `--call`.

Avec `--call` : réponses brutes, verdicts, `usageMetadata` et latences dans `responses.jsonl`, résumé dans `summary.json` (taux de réponses valides, refus par famille de gestes, part de gestes passifs : `wait`, `look`, `listen`, `rest`, `sleep`, `stop`).

## La clé

Lue dans `GEMINI_API_KEY`, sinon dans `~/.config/emergence/API_Keys` (droits 600, sinon refus ; une ligne `GEMINI_API_KEY=...` ou la clé seule). Elle ne passe que dans l'en-tête `x-goog-api-key`, jamais dans une URL, un log ou un fichier.

## Limites connues

- Le `why` du professeur est gardé dans le journal du pilote mais ne fait jamais partie de la décision.
- Les listes (`tastes`, `i_steps`) ne sont pas écrivables par le professeur ; les écritures structurées ne portent que sur une valeur ou une proposition.
- Les parts de quota (Flash Lite 15/min et 500/jour, Flash 5/min et 20/jour) sont celles données par Monsieur ; le client lit aussi les réponses 429 et s'adapte.
- La direction `{sin, cos}` des dossiers est lue « sin > 0 = à droite » (le catalogue ne le précise pas).
