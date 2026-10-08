# CLAUDE.md — ai/npc_pipeline

Pipeline de données des PNJ et modules de référence du moteur social, écrits par les devs (septembre-octobre 2026). Python ≥ 3.9, **aucune dépendance**. Tous les scripts restent dans ce dossier (ils s'importent entre eux). État détaillé : `docs/npc/README_devs_npc_2026-10-06.md` ; conception : `docs/npc/npc_architecture_v0.4.md` et `npc_memory_jobs_building_v0.5.md`.

## Tests (sans clé)
```
python3 plan_contract.py; python3 memory_service.py; python3 build_site.py
python3 scenario_tests.py                       # 30 cas : 22 OK, 7 LEARN, 1 SPEC attendus
python3 generate_states.py --n 1000 --check     # 18 invariants, 0 violation attendue
python3 selftest_pipeline.py; python3 selftest_quota_stress.py
```

## Règles
- `GEMINI_API_KEY` vient de l'environnement, jamais d'un fichier. Ne lance pas `teacher_run.py pilot|run` sans demande explicite de Monsieur (quota payant).
- Le générateur construit des situations et des candidats, **jamais la décision** (point 10 de la révision du 6 oct.).
- Règles dures : aucun cas romantique ou sexuel impliquant un enfant ou un adolescent n'est généré ni étiqueté ; `--check` le vérifie, garde-le vert.
- Ces modules sont les **oracles** du portage C++ : si tu changes un comportement, change le test et note-le dans `docs/01_decisions.md`.
- `samples/` contient des échantillons (schéma, situations, programmes de travail) ; `data/` et `logs/` sont créés par le pipeline et ne sont pas versionnés.

## Prochain travail (ordre)
1. Brancher `representation.py` dans `view_of`/`view_text` (entiers -10..+10 / 0..10, zéros omis).
2. Ambition et tolérance ; couche village pour 5 villages (~100 PNJ chacun) ; contenu des souvenirs.
3. Familles nouvelles : commerce entre villages, voyage, frontière et légendes, parcelles, apprentissage.
4. Corpus de 1 000 + rapport, paires de sensibilité, puis pilote réel (sur demande).
