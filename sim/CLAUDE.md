# CLAUDE.md : sim/

Propriétaire : le fil « Simulation sociale des villages ». Lis d'abord `README.md`.

- Python ≥ 3.9, **sans dépendance**. C'est un oracle : le portage C++ devra reproduire ses sorties (`run.fingerprint`).
- **Déterminisme** : tout tirage passe par `rng.Rng` (splitmix64). Jamais `random`, jamais de dépendance à l'ordre d'un `set` ou d'un `dict` non trié dans une décision. Toute boucle sur des PNJ se fait par identifiant croissant.
- **Règle dure** : `rules.romance_ok` refuse toute romance si l'un des deux a moins de 18 ans. Ne la contourne jamais ; `_flirt` et `_propose` la revérifient ; le test `HardRules` doit rester vert.
- **Contrat PNJ** : chaque plan émis doit passer `ai/npc_pipeline/plan_contract.validate_plan`. Une nouvelle fonction passe d'abord par le fil du moteur (`docs/interfaces.md`).
- **Texte libre** : les textes français des événements servent à l'affichage ; ils n'entrent jamais dans l'état d'un PNJ.
- **Contenu** (villages, métiers, savoirs, tenues, normes) dans `data/content.json`, jamais en dur.
- Tests : `python3 -m unittest discover -s tests` avant de dire qu'un changement est fini.
