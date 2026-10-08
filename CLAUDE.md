# CLAUDE.md — Emergence

Tu travailles sur **Emergence**, un jeu médiéval-fantastique pour Steam : monde de voxels de 2 cm entièrement destructible (physique, eau, feu, effondrements), 500 PNJ en 5 villages avec une simulation sociale profonde, rendu sur GPU intégré, IA sur GPU dédié. Le porteur du projet est **Monsieur**. Il écrit en français : réponds-lui en français, simplement, en commençant par la réponse.

## À lire avant toute tâche

1. `docs/02_architecture_cible.md` : l'architecture qui fait foi. Ses invariants (§ 1) ne se négocient pas.
2. `docs/01_decisions.md` : ce qui est décidé, proposé, ouvert. Ne contredis jamais une décision « Décidé » ; ne présente jamais une « Proposé » comme acquise.
3. `docs/04_feuille_de_route.md` : l'ordre des travaux et les critères de réussite.
4. Le `CLAUDE.md` du dossier où tu travailles (`tools/voxelizer/`, `ai/npc_pipeline/`, `engine/`).

Détail des calculs et des sources : `docs/reference/` (architecture v1, rendu sur GPU intégré, monde et horizon). Travail des développeurs sur les PNJ : `docs/npc/`. Confrontation des deux : `docs/03_confrontation.md`.

## Ce qui compte le plus

1. **La performance est la priorité numéro 1.** Machine de référence proposée (P13) : Intel Iris Xe (rendu), RTX série 3000 6 Go (IA), 16 Go de RAM. Rien ne parcourt le monde entier ; tout est déclenché par un événement et borné par un budget par image (budgets : architecture § 13). Ne calcule jamais au-delà de la précision nécessaire.
2. **Déterminisme.** La génération du monde est bit-exacte depuis la seed sur toutes les plateformes : hachages entiers, flottants stricts (pas de fusion multiplication-addition, pas de `-ffast-math`), fonctions mathématiques maison, aucune génération de vérité sur GPU, aucun `rand()` de la bibliothèque standard.
3. **Une seule vérité.** Seed + plan du monde, chunks modifiés, journal d'opérations, entités. Tout le reste est un cache reconstructible. Toute écriture dans le monde passe par une `Operation`.
4. **Le voxel ne porte que son VoxelId de 16 bits** (classe 9 bits + teinte 7 bits). Aucun état dynamique dans le voxel.
5. **Le texte libre n'entre jamais dans l'état de simulation.** Le langage passe par des cadres d'actes de parole ; le LLM local ne fait que verbaliser.
6. **Règles dures, jamais apprises** : aucun acte romantique ou sexuel impliquant un enfant ou un adolescent, comme acteur ou comme cible. Ne génère, n'étiquette et ne teste jamais de tels contenus, sauf les tests de refus déjà prévus.
7. **Mesurer avant d'affirmer.** Un chiffre sans mesure est une estimation et doit être dit comme tel. Une étape de la feuille de route n'est finie que lorsque son critère est mesuré.

## Sécurité

- Aucun secret dans le dépôt. La clé Gemini se lit dans la variable d'environnement `GEMINI_API_KEY`, jamais dans un fichier, un log ou un message de commit.
- Une clé a déjà fuité dans une conversation le 6 octobre 2026 ; si tu en vois une dans un fichier, arrête-toi et préviens Monsieur.
- Le pipeline teacher consomme un quota payant : ne lance jamais `teacher_run.py pilot` ou `run` sans que Monsieur l'ait demandé.

## Organisation du dépôt

```
docs/               vision, décisions, architecture, confrontation, feuille de route, idées, glossaire
docs/reference/     documents d'architecture d'origine (exports Markdown)
docs/npc/           conception PNJ des devs (architecture v0.4, mémoire v0.5, variables, audit)
tools/voxelizer/    convertisseur 3D → voxels (Python, 50 tests)
ai/npc_pipeline/    pipeline de données PNJ et modules de référence (Python, sans dépendance)
engine/             cœur C++ (à créer, voir engine/README.md)
game/               projet Godot 4 (à créer, voir game/README.md)
scripts/            test_all.sh
archive/            anciennes versions et sorties de travail, en lecture seule
```

## Conventions

- Code et identifiants en anglais. Documents destinés à Monsieur en français. Commentaires : la langue du fichier existant ; anglais pour le nouveau code C++.
- C++20, CMake, pas d'exceptions dans les boucles chaudes, pas d'allocation par voxel. Structures de données compactes, bit-packing assumé.
- Python ≥ 3.9. `ai/npc_pipeline` reste sans dépendance externe ; `tools/voxelizer` dépend de numpy, scipy, Pillow.
- Les modules Python de `ai/npc_pipeline` sont des **oracles** : un portage C++ doit reproduire leurs sorties sur un jeu de tests partagé. Ne les supprime pas après portage.
- Formats versionnés (`schema_version`) dès le premier commit d'un format.
- Données de contenu (matières, métiers, recettes, titres, blueprints) en fichiers de données, jamais codées en dur.

## Tests

`scripts/test_all.sh` lance tous les tests existants (pipeline PNJ, 30 cas, autotest sans clé, convertisseur). Lance-le avant de dire qu'un changement est fini, et donne le résultat réel, même rouge.

## Comment travailler avec Monsieur

- Il veut des solutions, pas des listes de blocages : quand quelque chose semble impossible, cherche ou invente une voie qui marche, avec un prototype et un critère de réussite.
- Quand une question dépend d'un choix qu'il n'a pas fait, prends un défaut raisonnable, dis lequel, et continue ; ajoute la question dans `docs/01_decisions.md` (section Ouvert).
- Les idées nouvelles vont dans `docs/05_idees.md` avec le gabarit ; elles n'entrent dans l'architecture qu'avec une mesure ou une décision.
- Toute décision prise va dans `docs/01_decisions.md` avec sa date.
