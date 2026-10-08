# CLAUDE.md : sim/

Propriétaire : le fil « Simulation sociale des villages ». Lis d'abord `README.md`.

- Python ≥ 3.9, **sans dépendance** pour le cerveau de référence. Le cerveau `transformer` demande PyTorch et le dossier `ai/` voisin (ou `EMERGENCE_AI`). C'est un oracle : le portage C++ devra reproduire ses sorties (`run.fingerprint`).
- **Plus de logique de décision à règles** (décision de Monsieur, 8 oct.). Le Transformer décide. `decide.candidates` reste figé comme étalon ; ne l'étends pas. `options.py` liste ce qui est **faisable**, jamais ce qui est souhaitable : une condition sur une envie (faim, ambition, rancune…) n'a rien à y faire.
- **Modèle** (architecture, jetons, vocabulaire, entraînement) : fil des données, dans `ai/`. Ne le modifie pas d'ici ; `live.py` et `brain.py` l'appellent tel quel. Les variables et actions : `docs/npc/variables_v0.3_catalogue_unique.md`.
- **Déterminisme** : tout tirage passe par `rng.Rng` (splitmix64). Jamais `random`, jamais de dépendance à l'ordre d'un `set` ou d'un `dict` non trié dans une décision. Toute boucle sur des PNJ se fait par identifiant croissant.
- **Règle dure** : `rules.romance_ok` refuse toute romance si l'un des deux a moins de 18 ans. Ne la contourne jamais ; `_flirt` et `_propose` la revérifient ; le test `HardRules` doit rester vert.
- **Contrat PNJ** : chaque plan émis doit passer `ai/npc_pipeline/plan_contract.validate_plan`. Une nouvelle fonction passe d'abord par le fil du moteur (`docs/interfaces.md`).
- **Texte libre** : les textes français des événements servent à l'affichage ; ils n'entrent jamais dans l'état d'un PNJ.
- **Contenu** (villages, métiers, savoirs, tenues, normes) dans `data/content.json`, jamais en dur.
- Tests : `python3 -m unittest discover -s tests` avant de dire qu'un changement est fini.
