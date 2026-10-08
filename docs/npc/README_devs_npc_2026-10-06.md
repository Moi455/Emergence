# Simulation sociale à PNJ émergents : README du prochain développeur

Dernière mise à jour du projet : 6 octobre 2026. Ce README décrit ce qui existe réellement, pas ce qui était prévu.

## 1. Le projet en cinq lignes

Un jeu Steam de type voxel (blocs très petits), village d'époque ancienne, ~120 PNJ (3 villages de 40), 5 PNJ « avancés » par village. Le joueur parle en anglais naturel. Un **petit réseau de neurones** (transformer, cible 5 à 30 M de paramètres) décide pour chaque PNJ ce qu'il fait, sous forme de **plans** de 1 à 6 fonctions avec conditions d'arrêt. Un **moteur d'action** exécute les plans seul. Le réseau est entraîné par distillation : un LLM « teacher » (Gemini 3.5 Flash-Lite, hors jeu, jamais d'API dans le jeu livré) note des actions candidates sur des situations générées.

Cible matérielle du joueur : CPU ~20 000 passmark, RTX 4070 (8 Go ou 12 Go : à confirmer), 16 Go de RAM. Un seul petit LLM local (type Gemma 4 E2B) sert uniquement à verbaliser les réponses des PNJ et, éventuellement, à analyser les phrases hors gabarit.

## 2. État réel

| Statut | Éléments |
|---|---|
| **Fait et testé automatiquement** | contrat de plans (`plan_contract.py`), mémoire (`memory_service.py`), règles sociales (`social_rules.py`), questions/réponses et négociation (`dialogue_protocols.py`), constructeur par différence (`build_site.py`), analyseur d'énoncés (`utterance_parser.py`), générateur de situations (`generate_states.py`), pipeline Gemini (`run_pipeline.py`, `teacher_run.py`, `gemini_client.py`), 30 cas de capacités (`scenario_tests.py`), autotests sans clé (`selftest_*.py`) |
| **Vérifié sur l'API réelle** | seulement la sonde `teacher_run.py probe` (l'utilisateur l'a lancée le 5 oct. : requête acceptée, niveaux de réflexion minimal/low/medium/high acceptés). **Le pilote et l'étiquetage n'ont jamais tourné sur l'API réelle.** |
| **Écrit mais pas encore branché** | `representation.py` (classification des variables, conversion vers -10..+10) et `corpus_report.py` (rapport statistique). Testés sur l'ancien générateur ; le texte envoyé au teacher utilise toujours les symboles `--  -  +  ++`. |
| **Spécifié, non construit** | moteur de groupes (cas 29), registre des métiers, jetons `link`/`place`/`object`/`group` émis par le générateur, moteur d'action complet dans le jeu, le réseau lui-même (aucun modèle n'a été entraîné), vérification des 30 cas sur un modèle entraîné |
| **Non fait de la dernière révision demandée** | voir section 7 |

Ce que prouvent les tests : que les faits dont une décision a besoin existent et que le moteur les met à jour correctement. Ils ne prouvent pas qu'un réseau entraîné se comportera bien.

## 3. Architecture

```
Générateur de situations ──► Teacher (Gemini) ──► Dataset ──► Petit réseau (à faire)
 (état + candidats)         note 0..4 chaque option          état → plan
        ▲                                                         │
        │                                                         ▼
 Données partagées du moteur ◄──── Moteur d'action ◄──── Plan (fonctions + conditions)
 (monde, mémoire, croyances, titres, langage)
```

- **Moteur de décision (IA)** : construit le contexte, appelle le réseau, valide le plan. Ne bouge rien, ne stocke aucun souvenir.
- **Moteur d'action** : exécute les plans (déplacement, outils, blocs), surveille les conditions d'arrêt, gère les interruptions, renvoie un résultat de plan. Le réseau n'est rappelé que quand un plan finit, échoue ou est interrompu.
- **Couche de données déterministe** : monde voxel, variables des PNJ, **mémoire** (stockage, oubli, rappel, déformation, croyances), titres, documents, analyseur de langage.
- Interface : 3 messages (`DecisionRequest`, `Plan`, `PlanResult`), détaillés dans `docs/npc_architecture_v0.4.md`.

### Entraînement (le principe)
Le teacher ne rédige pas de programmes : il **note chaque option candidate** (entiers 0 à 4) pour une situation. Les notes deviennent des cibles souples (softmax). Les plans de travail (creuser, cultiver, bâtir) viennent d'un expert scripté gratuit (`--work-programs`). Le texte en langage naturel n'entre jamais dans le réseau : il lui parvient sous forme de cadre d'acte de parole (acte, force 0..3, politesse, contenu).

## 4. Fichiers importants (`pipeline/`)

| Fichier | Rôle |
|---|---|
| `generate_states.py` | générateur de situations (24 familles), validation de 18+ invariants (`--check`), expert de plans de travail |
| `plan_contract.py` | 111 fonctions (84 de base), 20 conditions, validation et résolution des préconditions d'un plan |
| `memory_service.py` | mémoire d'un PNJ : consolidation, oubli, rappel, versions contradictoires, réputation, lieux, liens entre tiers |
| `social_rules.py` | propriété et vol, dissimulation, intention apparente, moyens-fins par affordances, accessibilité, contexte de décision |
| `dialogue_protocols.py` | résolution des questions (modes truth/vague/lie/refuse/unknown/redirect) et négociation |
| `build_site.py` | chantiers par différence plan/monde, modes à la main et rituel |
| `utterance_parser.py` | surlignage orange/bleu/vert, actes de parole, requêtes « où habite X » |
| `teacher_prompt.md`, `teacher_tools.py` | prompt du teacher (3 variantes de sortie : none/text/codes), validation des réponses |
| `gemini_client.py` | client REST de l'Interactions API (bibliothèque standard), limiteur RPM/TPM/RPD |
| `teacher_run.py` | commandes `probe`, `pilot`, `run`, `status`, `export` ; reprise sans perte, sommeil jusqu'au reset quotidien |
| `run_pipeline.py` | commande unique de bout en bout |
| `gold_tool.py` | étiquetage manuel à l'aveugle et mesure d'accord avec le teacher |
| `representation.py` | **nouveau, non branché** : registre et classification de chaque variable, `to10()` |
| `corpus_report.py` | **nouveau** : rapport statistique d'un corpus (distributions, couverture, doublons, alt_rate si étiquettes) |
| `scenario_tests.py` | les 30 cas de capacités + questions + négociation |
| `selftest_pipeline.py`, `selftest_quota_stress.py`, `mock_gemini_server.py` | tests complets sans clé contre un faux serveur |
| `config.json`, `HOWTO_GEMINI.md` | réglages et mode d'emploi (en français) |

`docs/` : architecture v0.4, mémoire/métiers/construction/30 cas v0.5, spécification v0.3 (partiellement remplacée), catalogues de variables v0.1 et v0.2 (anciens). `samples/` : `schema.json`, un échantillon de situations, un échantillon de plans de travail. `audit/` : rapport statistique de référence de l'ancien générateur.

## 5. Lancer

Prérequis : Python 3.9+ (testé en 3.12 ici, utilisé en 3.14 sous Fedora par l'utilisateur), aucune dépendance. Tous les scripts doivent rester **dans le même dossier** (ils s'importent entre eux).

```fish
cd pipeline
python3 plan_contract.py; python3 memory_service.py; python3 build_site.py
python3 scenario_tests.py
python3 selftest_pipeline.py; python3 selftest_quota_stress.py     # sans clé, 1 à 2 min chacun
set -gx GEMINI_API_KEY 'votre-clé'                                  # jamais dans un fichier
python3 teacher_run.py probe
python3 run_pipeline.py --target 300
```

## 6. Choix techniques et pourquoi

- **Distillation par notation de candidats** plutôt que génération de programmes par le LLM : plus simple pour un petit teacher, soft labels, plus économe en requêtes.
- **Plans courts avec conditions** : un creusement de 15 blocs est une décision, pas quinze.
- **Mémoire, perception, langage dans le moteur**, jamais dans le réseau : le réseau ne reçoit que quelques souvenirs rappelés, avec source, certitude, `focus_knows` et nombre de versions concurrentes.
- **Titres = nom + croyances des PNJ**, pas de vérité globale sur le maire.
- **Ordre des options mélangé** par le générateur, pour limiter le biais de position.
- **Gemini 3.x : ne pas fixer temperature/top_p/top_k** (déconseillé par Google). La constance vient des règles du prompt et se mesure avec le pilote (deux passes, options mélangées).
- **Limiteur de débit propre** : le goulot est le nombre de requêtes par jour, pas les tokens. `per_call` = nombre de situations par requête (16 par défaut).
- **Règles dures dans le moteur, jamais apprises** : aucun acte romantique ou sexuel impliquant une catégorie d'âge enfant ; refus de ces cas par réflexe ; les adultes apparentés ne sont pas bloqués (décision du porteur du projet, interrupteur `--no-adult-kin-romance`).
- **Trois représentations** à distinguer (décision de la révision du 6 oct., pas encore implémentée dans le texte du teacher) : canonique (stockée, pleine résolution), teacher (entiers -10..+10 ou 0..10 + contexte), modèle (mêmes entiers, divisés par 10, catégories en embeddings, quantités en log). Les variables unipolaires (faim, peur, rancune, intensités) vont de 0 à 10, pas de -10 à +10.

## 7. Ce qui reste à faire, dans l'ordre

La révision demandée le 6 oct. (10 points). État de chacun :

| # | Point | État |
|---|---|---|
| 1 | échelle -10..+10 pour le modèle final, classification explicite | `representation.py` écrit ; **le texte du teacher et le dataset ne l'utilisent pas encore** |
| 2 | séparer teacher / dataset / modèle, aucune compression destructive | principe acté ; le dataset stocke déjà l'état canonique, mais le teacher voit encore 5 niveaux symboliques (c'est là le vrai défaut : les étiquettes dépendent d'une information plus grossière que l'entrée du réseau) |
| 3 | couche village/société | **non fait** (aucune variable village dans le générateur) |
| 4 | mémoire avec contenu (« E2 a volé mon blé ») | **non fait** (un souvenir n'a que type, agent, valence, importance) |
| 5 | traits ambition et tolérance | **non fait** (le générateur a 9 traits, sans ambition ni tolérance) |
| 6 | audit de l'espace des actions candidates, alt_rate | `corpus_report.py` mesure la couverture des classes de réponse ; alt_rate nécessite un run teacher |
| 7 | situations multi-niveaux et dilemmes | **non fait** (39 % des situations touchent 2 niveaux, tous parmi individu/famille/institution) |
| 8 | corpus de test de ~1 000 exemples et rapport | rapport de référence sur l'ancien générateur fait (`audit/`) ; corpus corrigé **à produire** |
| 9 | paires de sensibilité (une variable change) | **non fait** |
| 10 | ne pas surcoder le comportement | garde-fou à respecter : le générateur construit des situations et des candidats, jamais la décision |

Plan proposé : (a) brancher `representation.py` dans `view_of`/`view_text` (entiers -10..+10, zéros omis, dit dans le prompt) ; (b) ajouter ambition et tolérance ; (c) couche village (jeton village, foyer, groupes, autres villages, événements collectifs, familles de dilemmes) ; (d) contenu des souvenirs (objet, gravité, norme violée, tiers, suite) ; (e) corriger `build_candidates` là où `corpus_report.py` montre des classes absentes ; (f) corpus de 1 000 + rapport ; (g) paires de sensibilité avec témoin de bruit (même situation étiquetée deux fois) ; (h) **pilote Gemini réel** et 100 étiquettes à l'aveugle (`gold_tool.py`) ; (i) seulement ensuite le dataset massif.

## 8. Problèmes connus et pièges

- **Clé API exposée** : une clé Gemini a été collée dans la conversation le 6 oct. Elle doit être révoquée. Ne jamais l'écrire dans un fichier.
- **Quotas** : « 500 » a été interprété comme requêtes **par jour** (RPD) ; à confirmer dans AI Studio. Les quotas sont par projet.
- **Environnement de développement sans accès à l'API Gemini** (`host_not_allowed`) : aucun test réel n'a pu y être fait.
- **Le teacher n'est pas une vérité** : la constance du pilote n'est pas la justesse ; il faut les 100 étiquettes à l'aveugle. Risque de rejets déséquilibrés sur les scénarios violents ou sexuels (filtres de sécurité) : l'export affiche les rejets par famille.
- **Teacher actuel trop grossier** (symboles à 5 niveaux) : ne pas lancer de gros dataset avant la correction.
- Les familles du générateur construisent encore des candidats par type d'événement ; les classes « deceive » et « negotiate » sont rares dans plusieurs familles (voir `audit/baseline_report.md`).
- La mémoire est un balayage linéaire par décision : coût à mesurer à 1 000 souvenirs par PNJ.
- Couverture réelle de l'analyseur d'énoncés sur des phrases de joueurs : inconnue.

## 9. Recommandations

1. Ne pas lancer 50 000 exemples avant : le texte en entiers, le village, les souvenirs structurés, ambition/tolérance et un corpus de 1 000 validé.
2. Mesurer la **sensibilité du teacher** (paires où une variable change, avec témoin de bruit) avant d'investir : si le teacher ne réagit pas aux écarts de valeurs, l'échelle fine n'apporte rien et le réseau n'apprendra pas ces écarts.
3. Garder la référence « règles + utilités » comme point de comparaison : le réseau doit la battre sur les tests pour mériter sa place.
4. Construire la tranche verticale (1 village, 20 à 40 PNJ, 30 actions, 3 scénarios de bout en bout) avant d'étendre.
5. Tester le réseau entraîné sur les 30 cas en paires minimales, pas seulement le moteur.
6. Ajouter des outils de debug (« visualiseur d'esprit ») dès les premiers PNJ jouables.

## 10. Chiffres de référence (ancien générateur, 1 000 situations, graine 4242)

- 59 actions distinctes offertes parmi les candidats ; 2,73 entités et ~12 candidats par situation.
- 11,4 % des situations offrent moins de 3 classes de réponse ; 39,4 % touchent au moins 2 niveaux ; 0 variable village.
- Contradictions explicables entre variables : ~1 % des entités (aimé mais peu fiable, détesté mais respecté).
- Coût teacher mesuré avec le tokenizer Mistral v3 (à ±20 % pour Gemini) : ~330 tokens par situation, ~1 250 tokens de prompt, ~4 700 tokens par appel de 8 situations.
- Tests : contrat 9, mémoire 16, chantier 13, analyseur 15, 30 cas (22 OK, 7 LEARN, 1 SPEC).
