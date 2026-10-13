# Le format du professeur

Un professeur (Gemini, ou un modèle local) reçoit la situation d'un PNJ (ce qu'il perçoit, croit, retient et veut, jamais la vérité de la scène) et rend SA décision : un geste paramétré (parler en est un, avec une parole dans la langue intérieure) et au plus 4 écritures de variables bornées. Ces décisions serviront d'étiquettes d'imitation pour le Transformer. Le gouverneur filtre tout (bornes, règle dure D10).

- **`render.py`** : situation -> texte anglais compact. Seuls les dossiers sont lus, jamais `situation.scene`. Chaque proposition est écrite en S-expression, suivie d'une glose anglaise. Les clés (`@E1`, `@T3`, `b:2`, `me`...) restent visibles pour que le professeur réponde avec elles. Seuls les traits, valeurs, émotions et besoins saillants sont listés.
- **`schema.py`** : le texte fixe (rôle, gestes, échelles, conditions d'arrêt, langue intérieure, variables écrivables, règle D10, mots) et le schéma JSON de la réponse (sous-ensemble OpenAPI de Gemini), plus une grammaire GBNF équivalente (non essayée ici). Tout est tiré de `model_interface.json` : le catalogue change, le prompt change.
- **`validate.py`** : réponse JSON + situation -> décision normalisée, ou refus avec un code stable (`invalid_json`, `bad_shape`, `unknown_gesture`, `too_many_writes`, `bad_param`, `bad_pointer`, `bad_speech`, `bad_write`, `governor:<code>`). Le gouverneur voit la vérité côté moteur : âges réels tirés de la scène, âges apparents et crus tirés des dossiers.
- **`gemini.py`** : client REST en `urllib` (generateContent en JSON structuré, countTokens, models.list), limiteur de débit, repli Flash Lite puis Flash, chargeur de clé.
- **`pilot.py`** : la ligne de commande du pilote (une situation par requête).
- **Le générateur continu** (`generator.py`, `quota.py`, `batch.py`, `caller.py`, `series.py`, `status.py`, `phrasebook.py`, `migrate.py`) : voir la section plus bas.

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


## Le générateur continu (13 oct.)

Il produit en continu, avec le quota GRATUIT de Monsieur, le `dataset.jsonl` de l'élève : une série qui peut tourner une semaine. Rien n'est payant ; aucune clé n'est affichée, journalisée ni écrite (le chargeur existant la lit).

| Fichier | Rôle |
|---|---|
| `quota.toml` | limites gratuites connues par modèle (RPM, RPD ; TPM et TPD s'il y en a), dans l'ordre de préférence ; un champ absent est appris des 429 |
| `quota.py` | `QuotaBook` (un modèle : fenêtre glissante d'une minute, compteurs du jour Pacifique, blocages, limites apprises, tout persisté), `QuotaDesk` (choisit le modèle qui peut répondre le premier), `QuotaError` (lit le corps du 429 : `quotaId` par minute ou par jour, requêtes ou jetons, `quotaValue`), `PacificDay` (minuit heure du Pacifique) |
| `caller.py` | `ModelCaller` : attend le rythme exact (intervalle 60/RPM x 1,05, jamais de rafale ; fenêtre glissante ; jetons d'entrée mesurés pour TPM/TPD), envoie, classe les erreurs ; `Pacer` : attentes interruptibles (SIGTERM) |
| `batch.py` | K situations par requête, schéma `{"decisions":[{"id":"S1", ...}]}`, validation de chaque décision par le validateur et le gouverneur du pilote, **une passe de réparation** (une requête pour toutes les décisions refusées du lot, avec leur réponse et l'erreur ; jamais pour un refus D10) |
| `phrasebook.py` | ~30 paroles valides et variées (saluer, demander, proposer, promettre, accepter, refuser, menacer, rapporter, s'excuser...) tirées des `utterances` de `catalogue/data/stories.toml`, **revalidées à chaque démarrage** par la langue du catalogue courant, dans les consignes |
| `generator.py` | la boucle, l'état, la reprise, le redémarrage sur changement de code ou de catalogue |
| `series.py`, `status.py`, `migrate.py` | fichiers de la série, bilan, migration des anciennes lignes |

### Ce que fait la boucle

K situations (6 par défaut, `--k`) de `ai/situations` (graine et indice qui avancent, **jamais deux fois la même**) -> une requête en JSON structuré -> chaque décision validée -> les refusées repartent UNE fois -> les valides sont ajoutées à `dataset.jsonl` (format de `dataset.py` : en-tête `hdr`, `id`, `teacher` = le modèle qui a répondu ; `source.repaired` si réparée ; `source.ages` = les vrais âges de la scène, **pour la migration seulement**, jamais lus par le modèle). Le journal brut (`journal.jsonl`) garde par requête : modèle, jetons mesurés, latence, réponse brute, verdict par décision.

Limites et modèles : le générateur choisit, à chaque requête, le modèle qui peut répondre **le premier** (à égalité, l'ordre de `quota.toml`). 429 « par minute » : le modèle est bloqué le temps que Google indique (3 de suite : 10 min), un autre prend la suite. 429 « par jour » (requêtes **ou** jetons) : le modèle est écarté jusqu'à minuit heure du Pacifique, la limite est apprise (`quotaValue`) et gardée dans `quota.json`. Tous les modèles épuisés : il dort jusqu'à la première remise à zéro (par tranches de 30 s, à l'écoute d'un arrêt ou d'un changement de code) puis reprend. 5xx/réseau : pauses 5, 10, 20... 300 s sans compter dans le quota. 404 : modèle écarté un jour. 400/403 : 2 de suite écartent le modèle ; sur 3 modèles de suite, arrêt avec le code 3 (clé refusée ou requête cassée : il ne faut pas brûler le quota). Cinq lots de suite sans une seule décision valide : arrêt avec le code 3.

Reprise exacte : écriture dans l'ordre `dataset` -> `journal` -> `state.json`, chaque fichier synchronisé ; une dernière ligne coupée (arrêt brutal) est retirée au démarrage ; le curseur reprend au plus grand de l'état, du journal et de la dernière ligne du dataset. SIGTERM : finit la requête en cours, sauvegarde, sort avec 0.

Redémarrage automatique (`os.execv`, même PID) quand le code de `ai/teacher`, `ai/situations`, `ai/tok2`, `catalogue/tools`, `catalogue/data/*.toml` ou `catalogue/generated/*.json` change et reste stable 30 s : le nouveau code est d'abord essayé dans un processus fils (`--selfcheck` : outils, consignes, paroles, 4 situations) ; s'il échoue (catalogue à moitié modifié), le processus en cours continue et réessaiera au changement suivant. `--no-restart` l'interdit.

### Commandes

```
cd ai
python3 -m teacher.generator --name serie1                       # essai à blanc : aucun réseau, écrit dry/ dans le dossier de la série
python3 -m teacher.generator --name serie1 --call --max-requests 3   # essai réel court
python3 -m teacher.generator --name serie1 --status              # bilan par jour de quota et par modèle
python3 -m teacher.generator --selfcheck
python3 -m teacher.dataset migrate ~/.local/share/emergence/dataset/serie1/dataset.jsonl --out /tmp/neuf.jsonl   # ou --in-place
python3 -m teacher.dataset stats FICHIER                         # lignes par interface:disposition
```
Sorties dans `~/.local/share/emergence/dataset/<série>/` (hors du dépôt, le programme refuse d'écrire dedans) : `dataset.jsonl`, `journal.jsonl`, `state.json`, `quota.json`, `generator.log`.

### Lancer une semaine

Au choix (une seule instance par série) :

```
scripts/run_generator.sh start serie1            # nohup, sans fin ; ajouter --days 7 pour s'arrêter après 7 jours
scripts/run_generator.sh status serie1           # processus + bilan
scripts/run_generator.sh logs serie1
scripts/run_generator.sh stop serie1             # arrêt propre

mkdir -p ~/.config/systemd/user && cp scripts/emergence-generator.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now emergence-generator.service
loginctl enable-linger $USER                     # pour qu'il continue session fermée
journalctl --user -u emergence-generator -f
```
Le service redémarre après un plantage (`Restart=on-failure`, 30 s) mais pas après les codes 2 (pas de clé) et 3 (erreur fatale à regarder). Le chemin du dépôt est dans `ExecStart` (à adapter si le dossier change).

Migration : arrêter le générateur avant de migrer le fichier. Une ligne dont le `hdr` n'est plus l'actuel est ré-encodée avec le tokeniseur courant et sa décision est revalidée (validateur + gouverneur) ; sinon elle est écartée et comptée par raison. Sans `source.ages` (lignes du pilote), les vrais âges sont inconnus et le gouverneur est plus strict qu'à l'origine : jamais plus laxiste.

### Mesures du 13 oct. (gemini-3.5-flash-lite, quota gratuit)

- Lot de 6 : 23 330 / 25 076 / 23 697 jetons d'entrée (consignes + schéma ~8 200, soit ~2 600 par situation), 742 / 403 / 1 005 en sortie, 2,1 à 3,3 s, **18 décisions valides sur 18**. Cache implicite de Google actif (7,8 k jetons « cached »). Coût par décision : ~4 000 jetons d'entrée, contre ~9 700 pour une requête seule.
- Réparation réelle (2 refus fabriqués : parole inventée `(ask (are you well))`, geste inconnu) : 14 317 jetons d'entrée, 1,4 s, **2 réparées sur 2**.
- `maxItems` sur le tableau `decisions` est refusé par Gemini (400 « invalid argument », mesuré) : il n'est pas dans le schéma, l'analyseur ignore les éléments en trop.
- 44 % de gestes passifs (`rest`, `look`, `wait`) sur 18 décisions : le professeur reste doux, à surveiller avec `--status`.
