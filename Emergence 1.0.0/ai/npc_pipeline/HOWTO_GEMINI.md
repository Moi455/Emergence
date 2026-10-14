# Générer le jeu de données avec Gemini 3.5 Flash-Lite - mode d'emploi

Tout tourne seul : vous lancez une commande, elle génère les situations, vérifie l'API, choisit la meilleure variante de prompt, étiquette en respectant vos quotas (y compris en dormant jusqu'à la remise à zéro quotidienne) et exporte le jeu de données. Vous pouvez l'arrêter et la relancer quand vous voulez : rien n'est perdu.

## 0. Ce qu'il faut savoir avant

- **Aucune installation** : Python 3.9+ suffit (bibliothèque standard uniquement, pas de SDK Google, donc pas de casse si le SDK change).
- **Vos quotas** : j'ai lu « 15 RPM, 250K TPM, 500 RPM ». Deux « RPM » ne peuvent pas coexister : j'ai considéré que **500 est un nombre de requêtes par jour (RPD)**. Vérifiez la valeur réelle dans AI Studio (page Rate limits) et corrigez `rpd` dans `config.json`. Les quotas sont par projet Google Cloud, pas par clé, et la limite quotidienne se remet à zéro à minuit heure du Pacifique (vers 9 h, heure de France : le script calcule lui-même).
- **Le goulot, c'est le nombre de requêtes par jour**, pas les tokens. D'où `per_call` : combien de situations par requête.

| per_call | tokens d'entrée / requête (estimation) | situations étiquetées / jour (RPD 500) | 20 000 situations | 50 000 situations |
|---|---|---|---|---|
| 8 | ~4 300 | ~3 600 | ~6 jours | ~14 jours |
| 16 (défaut) | ~7 100 | ~7 100 | ~3 jours | ~7 jours |
| 24 | ~10 000 | ~10 700 | ~2 jours | ~5 jours |

À 15 requêtes par minute et 16 situations par requête, vous consommez environ 105 000 tokens d'entrée par minute sur les 250 000 autorisés : le TPM n'est pas la limite. Ces tokens sont estimés avec un autre tokenizer (Mistral) : comptez ±20 %. Passer à 24 situations par requête divise le nombre de jours mais peut dégrader la qualité : testez-le avec le pilote avant.

## 1. Mise en place (une fois)

**Installation : utilisez l'archive complète.** Les scripts s'appellent les uns les autres (le générateur a besoin de `social_rules.py`, `dialogue_protocols.py`, `memory_service.py` et `plan_contract.py`) : si un seul fichier manque, rien ne démarre. L'archive `npc_pipeline.zip` contient tout :

```fish
python3 -m zipfile -e ~/Téléchargements/npc_pipeline.zip ~/
cd ~/npc_pipeline
```

Les scripts vérifient eux-mêmes que le dossier est complet et listent les fichiers manquants.

Dans fish, depuis le dossier des scripts :

```fish
cd ~/npc_pipeline
set -gx GEMINI_API_KEY 'COLLEZ_VOTRE_CLE_ICI'
```

La clé ne doit **jamais** être écrite dans un fichier ni collée dans une conversation. Elle n'existe que dans cette session de terminal (refaites le `set` à chaque nouveau terminal ; pour la rendre permanente : `set -Ux GEMINI_API_KEY '...'` (stockée dans votre profil fish, jamais dans le dossier du projet)).

Premier contrôle, **sans clé réelle** (1 à 2 minutes) : il prouve que toute la mécanique fonctionne (limites, reprise après arrêt, erreurs 429/503, filtres de sécurité, JSON cassé) contre un faux serveur :

```fish
python3 selftest_pipeline.py
python3 selftest_quota_stress.py
```

Les deux doivent finir par `ALL CHECKS PASSED`. Ils ne prouvent pas que l'API réelle accepte exactement nos requêtes : c'est le rôle de l'étape 3.

## 2. Régler les paramètres

```fish
python3 run_pipeline.py --stage states      # crée config.json, génère et valide les situations
gedit config.json
```

À vérifier : `rpm` 15, `tpm` 250000, `pilot_levels` (niveaux de réflexion comparés par le pilote : `minimal` et `low` par défaut ; ajoutez `medium` pour le tester, il consomme environ 200 tokens de réflexion de plus par réponse), **`rpd`** (votre vrai quota quotidien), `per_call` 16, `workers` 4, `target` (nombre de situations voulues, 50000 par défaut). Laissez `variant` et `thinking` sur `"auto"` : le pilote choisira.

## 3. Vérifier l'API réelle (environ 1 minute)

```fish
python3 teacher_run.py probe
```

Il envoie quelques requêtes minuscules, teste les niveaux de réflexion (`minimal`, `low`, `medium`, `high`) et une vraie situation avec chaque variante. Lisez la sortie :

- `API key refused` : clé fausse, ou API pas activée pour le projet.
- `thinking=... REJECTED` : ce niveau n'existe pas pour ce modèle, c'est normal, il sera ignoré.
- `[client] API rejected 'xxx': continuing without it` : l'API a refusé un champ facultatif ; le script continue sans et le note dans `data/capabilities.json`.
- Lors de votre premier essai réel (5 oct.), les quatre niveaux ont été acceptés et la requête a été comprise : l'API réelle accepte donc notre format. Les champs d'usage réels sont `total_tokens`, `total_input_tokens`, `total_output_tokens`, `total_thought_tokens`.
- Une erreur `bad_request` qui se répète : copiez-moi les dernières lignes de `logs/run.log` et je corrige l'appel.

## 4. Pilote puis petit essai

```fish
python3 run_pipeline.py --target 300
```

Il enchaîne : pilote (environ 80 requêtes, 5 à 10 minutes) qui compare 3 formats de sortie × niveaux de réflexion en étiquetant deux fois les mêmes situations avec les options mélangées, puis étiquette 300 situations et les exporte. Le tableau du pilote donne la validité du JSON, le taux de réponses plates, l'accord avec soi-même (self-rho), le biais de position et les tokens par requête. **Cet accord mesure la constance, pas la justesse.** Mesurez la justesse vous-même :

```fish
python3 gold_tool.py make --n 100
gedit data/gold_todo.txt
python3 gold_tool.py score
```

Vous étiquetez 100 situations à l'aveugle (sans voir les notes du professeur), le script donne le pourcentage où le choix principal de Gemini contient le vôtre, par famille. Moins de 60 % sur une famille : réécrivez le prompt pour cette famille, ou écrivez des règles plutôt que de lui faire confiance.

## 5. Lancement complet, sans surveillance

```fish
nohup python3 run_pipeline.py --target 50000 > pipeline.out 2>&1 &
```

Suivi :

```fish
tail -f logs/run.log                 # journal en direct
python3 teacher_run.py status        # avancement, quota du jour, jours restants
```

Arrêt propre (les requêtes en cours se terminent, rien n'est perdu), puis relance identique :

```fish
kill -INT (pgrep -f run_pipeline.py)
```

Quand le quota du jour est épuisé, le journal affiche `WAITING for quota reset` et le script dort jusqu'à minuit Pacifique, puis reprend tout seul. **Empêchez la mise en veille de l'ordinateur** pendant les jours de calcul (une veille interrompt le processus ; relancer la même commande reprend sans perte).

## 6. Résultats

```fish
python3 teacher_run.py export
```

- `data/intent_dataset.jsonl` : une ligne par situation étiquetée : `state` (les variables), `cands` (les options), `scores` (0 à 4), `soft` (scores en probabilités), `drivers` (si la variante les fournit), `alt` (action manquante proposée), `split` (train 90 %, val 5 %, test 5 %, stable d'une exécution à l'autre).
- `data/rejected.jsonl` : situations écartées et pourquoi (`blocked` = filtre de sécurité, `flat` = réponse sans information, `invalid_output`).
- L'export affiche les rejets par famille : si une famille violente ou sexuelle est rejetée bien plus que les autres, le professeur est biaisé sur ces cas ; traitez-les par des règles.
- L'export liste les actions `alt` les plus proposées : ce sont des options à ajouter au générateur.

## 7. Si quelque chose ne va pas

| Symptôme | Cause probable | Que faire |
|---|---|---|
| `FATAL: the API keeps rejecting the request` | modèle, clé ou format refusés 3 fois d'affilée | `python3 teacher_run.py probe`, puis envoyez-moi `logs/run.log` |
| `daily quota reached` dès le début | `rpd` trop haut dans la config, ou autre usage du même projet | baissez `rpd` |
| beaucoup de `invalid_output` | trop de situations par requête | `per_call` 8 |
| beaucoup de `blocked` | filtres de sécurité sur des scénarios violents | normal en partie ; voir l'export par famille |
| 429 incessants à la minute | `rpm` ou `tpm` trop optimistes | baissez-les de 20 % |
| le script ne bouge plus | attente de la remise à zéro du quota | `python3 teacher_run.py status` |

## 8. Ce qui est vérifié et ce qui ne l'est pas

Vérifié (tests automatiques contre un faux serveur, voir `selftest_*.py`) : limiteur RPM/TPM/RPD, sommeil jusqu'au changement de jour, reprise après arrêt sans doublon, erreurs 429 et 503, JSON tronqué, tableaux de mauvaise longueur, réponses plates, isolement des situations bloquées par dichotomie, adaptation quand l'API refuse un champ facultatif, export et découpage.

Non vérifié : l'acceptation par l'API **réelle** de la requête (format Interactions API relevé dans la documentation de Google, revision `2026-05-20`), le nom exact des champs d'usage, le comportement réel des filtres de sécurité, la qualité des étiquettes de Gemini 3.5 Flash-Lite sur votre jeu. Les étapes 3 et 4 existent pour ça.

## 9. Où sont les choses

| Fichier | Rôle |
|---|---|
| `run_pipeline.py` | la commande unique (états, sonde, pilote, étiquetage, export) |
| `teacher_run.py` | les étapes une par une : `probe`, `pilot`, `run`, `status`, `export` |
| `gemini_client.py` | appel REST de l'API et limiteur de débit |
| `teacher_prompt.md`, `teacher_tools.py` | le prompt du professeur et la validation de ses réponses |
| `generate_states.py` | générateur des situations (24 familles), `plan_contract.py` le contrat de plans |
| `gold_tool.py` | vos 100 étiquettes à l'aveugle et la mesure d'accord |
| `selftest_pipeline.py`, `selftest_quota_stress.py`, `mock_gemini_server.py` | tests sans clé |
| `config.json` | tous les réglages |
| `npc_architecture_v0.4.md`, `npc_memory_jobs_building_v0.5.md` | architecture, mémoire, métiers, construction, les 30 cas |
