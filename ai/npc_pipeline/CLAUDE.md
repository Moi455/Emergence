# CLAUDE.md — ai/npc_pipeline

Pipeline de données des PNJ et modules de référence du moteur social, écrits par les devs (septembre-octobre 2026). Python ≥ 3.9, **aucune dépendance**. Tous les scripts restent dans ce dossier (ils s'importent entre eux). État détaillé : `docs/npc/README_devs_npc_2026-10-06.md` ; conception : `docs/npc/npc_architecture_v0.4.md` et `npc_memory_jobs_building_v0.5.md`.

## Tests (sans clé)
```
python3 plan_contract.py; python3 memory_service.py; python3 build_site.py
python3 scenario_tests.py                       # 30 cas : 22 OK, 7 LEARN, 1 SPEC attendus
python3 generate_states.py --n 1000 --check     # 18 invariants, 0 violation attendue
python3 selftest_pipeline.py; python3 selftest_quota_stress.py
python3 reference_decider.py; python3 encode.py; python3 minimal_pairs.py
```

## Données du Transformer (générateur 0.4, octobre 2026)
- `reference_decider.py` : décideur à utilités (10 moteurs), étiquettes gratuites `ref-0.4`. L'élève doit le battre plus tard.
- `encode.py` : format de jetons `tok-1`, **oracle du portage C++** ; `--build-vocab` réécrit `model_vocab.json` (le hash change, les jeux de données doivent être refaits).
- `build_dataset.py` : génère, étiquette (référence, professeur `--teacher-labels`, simulation `--sim-trajectories`), écrit des fichiers binaires. Gros jeux dans `/mnt/project-files/donnees-transformer/`.
- `minimal_pairs.py` : 25 sondes à sens attendu écrit à la main.
- Entraînement : `../student/ENTRAINEMENT.md`.

## Règles
- `GEMINI_API_KEY` vient de l'environnement, jamais d'un fichier. Ne lance pas `teacher_run.py pilot|run` sans demande explicite de Monsieur (quota payant).
- Le générateur construit des situations et des candidats, **jamais la décision** (point 10 de la révision du 6 oct.).
- Règles dures : aucun cas romantique ou sexuel impliquant un enfant ou un adolescent n'est généré ni étiqueté ; `--check` le vérifie, garde-le vert.
- Ces modules sont les **oracles** du portage C++ : si tu changes un comportement, change le test et note-le dans `docs/01_decisions.md`.
- `samples/` contient des échantillons (schéma, situations, programmes de travail) ; `data/` et `logs/` sont créés par le pipeline et ne sont pas versionnés.

## Prochain travail (ordre)
Fait en 0.4 : vue en entiers, ambition et tolérance, couche village et foyer, contenu des souvenirs, familles village/apprentissage/frontière/commerce entre villages/fête, garde-robe et `dress(outfit)`, rapport (`docs/npc/audit/report_v04.md`), paires minimales.
1. Brancher les trajectoires du fil Simulation (`--sim-trajectories`, champs id/family/state/cands).
2. Pilote réel du professeur (sur demande de Monsieur seulement).
3. Quantification entière de l'élève (M12, S7) et encodeur C++ fidèle à `encode.py`.
