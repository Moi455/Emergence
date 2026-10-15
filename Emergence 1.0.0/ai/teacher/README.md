# Le format du professeur

Un professeur (Gemini, ou un modèle local) reçoit la situation d'un PNJ (ce qu'il perçoit, croit, retient et veut, jamais la vérité de la scène) et rend SA décision : un geste paramétré (parler en est un, avec une parole dans la langue intérieure) et au plus 4 écritures de variables bornées. Ces décisions serviront d'étiquettes d'imitation pour le Transformer. Le gouverneur filtre tout (bornes, règle dure D10).

- **`render.py`** : situation -> texte anglais compact. Seuls les dossiers sont lus, jamais `situation.scene`. Chaque proposition est écrite en S-expression, suivie d'une glose anglaise. Les clés (`@E1`, `@T3`, `b:2`, `me`...) restent visibles pour que le professeur réponde avec elles. Seuls les traits, valeurs, émotions et besoins saillants sont listés.
- **`schema.py`** : le texte fixe (rôle, gestes, échelles, conditions d'arrêt, langue intérieure, variables écrivables, règle D10, mots) et le schéma JSON de la réponse (sous-ensemble OpenAPI de Gemini), plus une grammaire GBNF équivalente (non essayée ici). Tout est tiré de `model_interface.json` : le catalogue change, le prompt change.
- **`validate.py`** : réponse JSON + situation -> décision normalisée, ou refus avec un code stable (`invalid_json`, `bad_shape`, `unknown_gesture`, `too_many_writes`, `bad_param`, `bad_pointer`, `bad_speech`, `bad_write`, `governor:<code>`; plans (T11) : `too_many_steps`, `bad_plan`). Un champ `plan` facultatif (au plus 6 étapes `{gesture, target}`, `repeat`, `repeat_period`, `parent`) et un champ `stop` facultatif sont acceptés ; chaque étape passe `check_gesture` (D10) ; `DecisionSchema(plans=True)` les demande au professeur (désactivé par défaut : le prompt du générateur ne change pas). Le gouverneur voit la vérité côté moteur : âges réels tirés de la scène, âges apparents et crus tirés des dossiers.
- **`gemini.py`** : client REST en `urllib` (generateContent en JSON structuré, countTokens, models.list), limiteur de débit, familles de modèles (`ModelFamilies`), stratégies de requête (`StructuredStrategy`, `PromptOnlyStrategy`), chargeur de clé.
- **`probe.py`, `bench.py`** : la sonde (au plus 2 petites requêtes par modèle : répond-il, systemInstruction, JSON structuré, réflexion, erreur) et le banc de qualité (mêmes situations pour tous). Voir « Modèles ».
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
| `quota.toml` | limites par modèle (RPM, RPD connus ; TPM 250 000 et TPD 20 M / 2 M = **plafonds locaux prudents, des estimations**), dans l'ordre de préférence |
| `quota.py` | `QuotaBook` (un modèle : fenêtre glissante d'une minute, compteurs du jour Pacifique, blocages, limites apprises, tout persisté), `QuotaDesk` (choisit le modèle qui peut répondre le premier), `QuotaError` (lit le corps du 429 : `quotaId` par minute ou par jour, requêtes ou jetons, `quotaValue`), `PacificDay` (minuit heure du Pacifique) |
| `caller.py` | `ModelCaller` : attend le rythme exact (intervalle 60/RPM x 1,05, jamais de rafale ; fenêtre glissante ; jetons d'entrée mesurés pour TPM/TPD), envoie, classe les erreurs ; `Pacer` : attentes interruptibles (SIGTERM) |
| `batch.py` | K situations par requête, schéma `{"decisions":[{"id":"S1", ...}]}`, validation de chaque décision par le validateur et le gouverneur du pilote, **une passe de réparation** (une requête pour toutes les décisions refusées du lot, avec leur réponse et l'erreur ; jamais pour un refus D10) |
| `phrasebook.py` | ~30 paroles valides et variées (saluer, demander, proposer, promettre, accepter, refuser, menacer, rapporter, s'excuser...) tirées des `utterances` de `catalogue/data/stories.toml`, **revalidées à chaque démarrage** par la langue du catalogue courant, dans les consignes |
| `generator.py` | la boucle, l'état, la reprise, le redémarrage sur changement de code ou de catalogue |
| `series.py`, `status.py`, `migrate.py` | fichiers de la série, bilan, migration des anciennes lignes |

### Ce que fait la boucle

K situations (6 par défaut, `--k`) de `ai/situations` (graine et indice qui avancent, **jamais deux fois la même**) -> une requête en JSON structuré -> chaque décision validée -> les refusées repartent UNE fois -> les valides sont ajoutées à `dataset.jsonl` (format de `dataset.py` : en-tête `hdr`, `id`, `teacher` = le modèle qui a répondu ; `source.repaired` si réparée ; `source.ages` = les vrais âges de la scène, **pour la migration seulement**, jamais lus par le modèle). Le journal brut (`journal.jsonl`) garde par requête : modèle, jetons mesurés, latence, réponse brute, verdict par décision.

Limites et modèles : le générateur choisit, à chaque requête, le modèle qui peut répondre **le premier** (à égalité, l'ordre de `quota.toml`). 429 « par minute » : le modèle est bloqué le temps que Google indique (3 de suite : 10 min), un autre prend la suite. 429 « par jour » (requêtes **ou** jetons) : le modèle est écarté jusqu'à minuit heure du Pacifique. Une limite n'est apprise que d'un `quotaValue` explicite, et seulement vers le bas : la limite effective est `min(fichier, appris)`, jamais au-dessus du fichier ; sans `quotaValue`, on bloque seulement le temps indiqué. Tous les modèles épuisés : il dort jusqu'à la première remise à zéro (par tranches de 30 s, à l'écoute d'un arrêt ou d'un changement de code) puis reprend. 5xx/réseau : pauses 5, 10, 20... 300 s ; la requête reste **comptée** (un délai dépassé a pu arriver chez Google). 404 : modèle écarté un jour. 400/403 : 2 de suite écartent le modèle ; sur 3 modèles de suite, arrêt avec le code 3 (clé refusée ou requête cassée : il ne faut pas brûler le quota). Un lot sans aucune décision valide (même réparé) met le modèle de côté une heure et les autres continuent ; arrêt avec le code 3 seulement si TOUS les modèles ont échoué ainsi (ou sont hors service) : l'invite est alors cassée. Le compteur du jour ne fait qu'avancer (une horloge qui recule ne le remet pas à zéro). Une requête est comptée et `quota.json` écrit (fsync, fichier temporaire puis renommage) **avant** l'envoi ; si `quota.json` est abîmé ou mal typé, les compteurs du jour du modèle sont reconstruits depuis `journal.jsonl` (`pday`). Une décision que le codec ne sait pas écrire est comptée refusée (événement `encode_error`), sans arrêt ni retour en arrière.

Un seul générateur par série : verrou `flock` exclusif sur `<série>/.lock` (fermé à l'`exec`, repris par la nouvelle image) ; un second lancement sort avec le code 2. Les identifiants des lignes portent le nom de la série (`serie:graine:indice`) pour que deux séries ne se masquent pas (les anciennes lignes `graine:indice` restent lues). Un redémarrage n'a jamais lieu avec une réponse en main (entre le lot et sa réparation) : il attend que la ronde soit écrite. Un disque plein ne laisse pas de demi-écriture (le fichier est tronqué à sa taille d'origine).

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
scripts/run_generator.sh start serie1            # nohup, sans fin (le PID est vérifié sur sa ligne de commande) ; ajouter --days 7 pour s'arrêter après 7 jours
scripts/run_generator.sh status serie1           # processus + bilan
scripts/run_generator.sh logs serie1
scripts/run_generator.sh stop serie1             # arrêt propre

mkdir -p ~/.config/systemd/user && cp scripts/emergence-generator.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now emergence-generator.service
loginctl enable-linger $USER                     # pour qu'il continue session fermée
journalctl --user -u emergence-generator -f
```
Le service redémarre après un plantage (`Restart=on-failure`, 30 s) mais pas après les codes 2 (pas de clé) et 3 (erreur fatale à regarder). Le chemin du dépôt est dans `ExecStart` (à adapter si le dossier change).

Migration : `--in-place` est refusé tant que le verrou de la série est tenu ou que `generator.pid` désigne un générateur vivant, et `--limit` est interdit avec `--in-place` (utiliser `--out`). Une ligne dont le `hdr` n'est plus l'actuel est ré-encodée avec le tokeniseur courant et sa décision est revalidée (validateur + gouverneur) ; sinon elle est écartée et comptée par raison. Sans `source.ages` (lignes du pilote), les vrais âges sont inconnus et le gouverneur est plus strict qu'à l'origine : jamais plus laxiste.

### Mesures du 13 oct. (gemini-3.5-flash-lite, quota gratuit)

- Lot de 6 : 23 330 / 25 076 / 23 697 jetons d'entrée (consignes + schéma ~8 200, soit ~2 600 par situation), 742 / 403 / 1 005 en sortie, 2,1 à 3,3 s, **18 décisions valides sur 18**. Cache implicite de Google actif (7,8 k jetons « cached »). Coût par décision : ~4 000 jetons d'entrée, contre ~9 700 pour une requête seule.
- Réparation réelle (2 refus fabriqués : parole inventée `(ask (are you well))`, geste inconnu) : 14 317 jetons d'entrée, 1,4 s, **2 réparées sur 2**.
- `maxItems` sur le tableau `decisions` est refusé par Gemini (400 « invalid argument », mesuré) : il n'est pas dans le schéma, l'analyseur ignore les éléments en trop.
- 44 % de gestes passifs (`rest`, `look`, `wait`) sur 18 décisions : le professeur reste doux, à surveiller avec `--status`.

## T01 : pointeurs écrits vérifiés par type (`bad_pointer`)

Une écriture `scale = mref` (`attention`, `g_origin_ref`, `i_serves`, toute future variable `mref`) est refusée si le type de l'enregistrement visé n'est pas dans les `ref_types` du champ de jeton de la variable (jeton du catalogue, par ex. `SELF_STATE.attention`, puis `input.token_types` de `model_interface.json` ; rien en dur). `WriteChecker.ref_types()` fait la résolution. `me` est de type SELF, un groupe `@G` est GROUP.

Ré-validation (copie de la série vivante, `migrate` saute les lignes déjà à l'en-tête courant : le décompte a été fait en repassant chaque décision dans le validateur) :

| fichier (copie) | lignes | refusées `bad_pointer` |
|---|---|---|
| `dataset/serie1/dataset.jsonl` (copie `runs/t01_copie.jsonl`) | 9 856 | 40 |
| `runs/snap_14oct.jsonl` | 3 928 | 22 |

Aucune autre raison de refus nouvelle. La série vivante n'a pas été modifiée.


## Modèles (14 oct.)

Les 63 modèles de `models.list` ont été triés ; les candidats texte ont été sondés (`python3 -m teacher.probe --call`, rapport dans `~/.local/share/emergence/dataset/probe_models.json`) puis comparés sur les **mêmes 6 situations** (`python3 -m teacher.bench --call --models ...`, `quality_models.json`, une requête par modèle, sans réparation : on mesure le premier coup). Les familles sont dans `gemini.py` (`ModelFamilies` : flash-lite, flash, pro, gemma) ; `ModelCatalog.chain()` reste limité à Flash Lite puis Flash par défaut, `chain(ModelFamilies.ALL)` ouvre pro et gemma. `quota.toml` porte les modèles retenus, et les autres avec `enabled = false` et la raison dans `note`.

**[Mesuré]** Qualité au premier coup (6 situations identiques, mêmes pour tous ; passifs = `wait`, `look`, `listen`, `rest`, `sleep`, `stop`, part des décisions valides) :

| Modèle | Valides 1er coup | Passifs | Sortie (+réflexion) en jetons | Latence | Décision |
|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 6/6 | 50 % | 416 | 2,1 s | chaîne |
| gemini-3.1-flash-lite | 5/6 (`bad_param`) | 40 % | 803 | 3,1 s | chaîne |
| gemini-3.1-flash-lite-preview | 5/6 (`bad_speech`) | 20 % | 411 | 2,5 s | chaîne |
| gemini-flash-lite-latest (alias) | 6/6 | 33 % | 630 | 2,3 s | chaîne (ajouté) |
| gemini-flash-latest (alias) | 6/6 | 17 % | 793 (+3 560) | 45,8 s | chaîne (ajouté, lent) |
| gemini-3.7-flash | 6/6 | 33 % | 732 (+2 664) | 31,6 s | chaîne |
| gemini-3.8 / 3.6 / 3.5-flash, 3-flash-preview | 429 par jour (quota de 20 déjà dépensé par le générateur) : voir le journal ci-dessous | | | | chaîne |
| gemma-4-31b-it | 4/6 (2 `governor:unknown_variable`) | 0 % | 502 (+6 515) | 196 s (3 requêtes) | **désactivé (<70 %)** |
| gemma-4-26b-a4b-it | 4/6 (`bad_param`, `governor:engine_owned`) | 25 % | 342 (+11 053) | 243 s (3 requêtes) | **désactivé (<70 %)** |

**[Mesuré]** Journal de production de serie1 (lots de 10 et de 6, premier coup, avant réparation) : 3.5-flash-lite 96,8 % valides (2 620 décisions, passifs 40 %), 3.1-flash-lite 78,7 % (2 742, passifs 25 %), 3.1-flash-lite-preview 80,6 % (222), 3.8-flash 100 % (28), 3.7-flash 100 % (24), 3.6-flash 96,7 % (30), 3.5-flash 100 % (12), 3-flash-preview 92,3 % (78). Les petits échantillons des flash (12 à 30 décisions) sont indicatifs seulement. 3.1-flash-lite (78,7 %) passe la barre de 70 % mais est le plus faible de la chaîne : à surveiller.

**[Mesuré]** Écartés par la sonde (aucune requête de plus) :

| Modèle | Réponse | Raison |
|---|---|---|
| gemini-2.5-pro, gemini-2.5-flash | 404 | « no longer available to new users » |
| gemini-3.1-pro-preview, gemini-pro-latest | 429 | limite gratuite **0** (requêtes et jetons) : facturation requise |
| gemini-4-argon, gemini-omni-1.1-flash, gemini-omni-flash-preview | 429 | limite gratuite **0** : facturation requise |
| antigravity-preview-05-2026 / 09-2026 / latest | 400 | « Developer instruction is not enabled », puis « This model only supports Interactions API » : ce sont des agents, pas generateContent |

Exclus d'office (non texte) : tts, image, transcribe, lyria, robotics, computer-use, deep-research, nano-banana, live, embedding, veo.

**[Mesuré]** Capacités : tous les modèles retenus acceptent `systemInstruction` et le schéma JSON structuré sur la sonde. Gemma accepte les deux avec un **petit** schéma, mais répond `400 invalid argument` au vrai schéma du lot (comme `maxItems`) : `json_schema = false` dans `quota.toml`, donc `PromptOnlyStrategy` (consignes systemInstruction gardées, schéma écrit dans le texte, JSON pur demandé puis extrait par `JsonExtractor`). Gemma réfléchit (2 000 à 4 000 jetons par requête) et met 60 à 80 s. Réflexion de `gemini-flash-latest` et `gemini-3.7-flash` : 2 600 à 3 600 jetons.

**[Mesuré]** Limites gratuites observées (la seule qui soit chiffrée par Google) : Gemma, **16 000 jetons d'entrée par minute** (`GenerateContentInputTokensPerModelPerMinute-FreeTier`, `quotaValue` 16000). Un lot de 6 fait ~23 400 jetons Gemini (~28 000 Gemma) : il ne passe pas ; 2 situations font ~15 000 jetons Gemma. D'où `max_k = 2` dans `quota.toml` : le générateur réserve alors des « tours à part » de 2 situations à ce modèle (`LaneBusy` si le modèle ne peut pas répondre : le tour retourne au chemin normal) et `QuotaBook` ne lui envoie jamais une requête plus grosse que son plafond par minute. Les RPM/RPD de Gemma et des alias `*-latest` sont **inconnus** (champs absents ; le générateur les apprend des 429).

Le champ `teacher` de chaque ligne du dataset reste le modèle qui a répondu : les professeurs se comparent après coup (`python3 -m teacher.dataset stats`).

**Fragile** : (1) les alias `*-latest` peuvent changer de modèle sans préavis, et partager le quota de leur cible (inconnu) ; (2) les échantillons du banc sont de 6 situations (une seule requête par modèle) : un taux de 83 % ou 100 % pèse peu ; (3) les chiffres de Gemma viennent d'une seule série de 3 requêtes ; (4) la sonde et le banc ont dépensé quelques requêtes que `quota.json` ne connaît pas (écart de 1 à 3 par modèle sur la journée).
