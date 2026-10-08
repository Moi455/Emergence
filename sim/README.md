# Simulation sociale des villages (`sim/`)

Simulation sans rendu des 500 PNJ d'Emergence, au palier 2 de l'architecture (actions résolues par leur durée et leur résultat). Python ≥ 3.9, déterministe depuis une seed : c'est l'oracle du futur portage C++ (`emergence_sim` de la piste Société S5 et S6), la boucle qui accueille le Transformer des PNJ, et le générateur de trajectoires pour son entraînement.

État, mesures et ce qui manque : `ETAT.md`. Variables et actions : `docs/npc/variables_v0.3_catalogue_unique.md`.

## Lancer

```bash
cd sim
python3 -m emergence_sim.run --seed 7 --years 1 --out out          # données de la visionneuse
python3 -m emergence_sim.run --seed 7 --years 1 --traj-ppm 5000     # + 0,5 % des décisions en trajectoires
python3 viewer/build_viewer.py out/viewer_seed7.json out/chronique.html   # page autonome à ouvrir dans un navigateur
python3 -m unittest discover -s tests -v

# avec le Transformer (PyTorch et ai/ requis)
python3 -m emergence_sim.run --seed 7 --days 30 --brain transformer --model ../ai/student/runs/small/best.pt --device cuda
python3 -m emergence_sim.run --seed 7 --days 2 --brain transformer --config tiny     # poids non entraînés : plomberie et débit seulement
```

Les tests cherchent `ai/npc_pipeline/plan_contract.py` à côté de `sim/` (ou dans `EMERGENCE_AI`) pour valider chaque plan ; sans lui, ce test est sauté.

## Ce qui est simulé

- **Monde** : 5 villages de `data/content.json` (Port-Salant face à la mer, Sombrebois face à la forêt, Roc-Ferrand face aux montagnes, Sable-d'Or face au désert, Bourg-Carrefour au centre), environ 100 habitants chacun, foyers sur plusieurs générations, métiers par village.
- **Décision, la prise du cerveau** (`brain.py`) : à chaque heure de jeu, tous les PNJ qui doivent décider (fin de plan, interruption) sont réunis ; le cerveau choisit pour tous en un seul lot ; la simulation exécute ensuite dans l'ordre des identifiants. Deux cerveaux :
  - `transformer` : le modèle du fil des données (`ai/student/student_model.py`). Le moteur liste ce qui est faisable (`options.py`, au plus 16 options en fonctions du contrat, jamais filtrées sur une envie), l'état vivant devient un enregistrement du générateur 0.4 puis des jetons tok-1 (`live.py`, avec `ai/npc_pipeline/encode.py`), et le modèle note chaque option. Un gouverneur applique ses ajustements de variables dans des bornes : une émotion peut sauter, le reste avance par petits pas, le corps et les biens restent au moteur.
  - `reference` (par défaut, sans dépendance) : les anciennes utilités à règles, figées, gardées comme étalon. Elles ne sont plus étendues.
  Un HTN déroule ensuite l'option choisie en un plan de 1 à 6 étapes du contrat PNJ (`ai/CONTRAT_PNJ.md`, 112 fonctions, 20 conditions).
- **Besoins et émotions** : faim, fatigue, solitude, stress, joie, colère, peur, deuil, santé, soif (oasis).
- **Relations** : affection, confiance, respect, amour, familiarité, rancune, dette ; 48 liens au plus par PNJ, les plus faibles sont oubliés.
- **Mémoire** : 32 souvenirs au plus par PNJ, avec intensité qui s'efface ; les actes publics ont des témoins ; les ragots transportent les souvenirs d'un PNJ à l'autre, avec la confiance comme poids ; les mensonges circulent aussi et finissent parfois démasqués.
- **Paroles** : bavarder, colporter, raconter une légende, complimenter, insulter, flirter, demander en mariage, réconforter, mentir, faire campagne (actes de parole, jamais de texte libre dans l'état).
- **Vie** : naissances, prénoms hérités des aïeux, apprentissage à 12 ans, métier à 18, retraite, mort (âge, maladie, faim, soif, froid, accidents, éboulements, rixes, meurtres, exécutions, disparitions aux frontières), deuil, obsèques, héritage, orphelins recueillis par la famille ou adoptés.
- **Amour** : cour, fiançailles, mariage (résidence selon le métier), jalousie des rivaux, liaisons secrètes, témoins, découverte, séparation, fugues d'amoureux quand les familles sont en querelle. Règle dure : aucune romance si l'un des deux a moins de 18 ans (vérifiée deux fois et testée) ; tabou de parenté jusqu'aux cousins germains, désactivable dans `norms`.
- **Savoirs** : un savoir ne s'apprend qu'auprès d'un maître (ou en s'exerçant seul quand on en sait déjà un peu) ; les guildes fermées peuvent refuser des apprentis ; quand le dernier maître meurt, le savoir est perdu pour le village ou pour le monde, et peut renaître si un apprenti continue seul.
- **Économie** : production par métier et par saison, outils qui s'usent, jardins familiaux, réserves d'hiver, sel qui conserve, marchés de village avec prix par l'offre et la demande, monnaie en circuit fermé, marchands et caravaniers qui arbitrent entre villages, péage du bourg, vols, brigandage sur les routes.
- **Pouvoir** : chef élu tous les 5 ans (vote de chaque adulte selon ses liens), décrets selon la personnalité du chef (impôt, peine du vol, aide en disette, couvre-feu, péage), justice (témoins, partialité envers la famille), verdicts injustes qui créent des rancunes, détournements découverts par un scribe ou un témoin, contestation et élection anticipée, grâce des bannis, travaux publics.
- **Groupes** : guildes, cercles de croyants en l'au-delà (mal vus du prêtre), bande de hors-la-loi formée par les bannis ; querelles entre familles, et paix par mariage.
- **Frontières** : le danger double tous les 300 m (500 m en montagne). Chacun choisit sa profondeur selon le risque qu'il accepte ; l'expérience et le métier repoussent un peu la limite. Les disparus deviennent des légendes, racontées de taverne en veillée, qui augmentent la croyance en l'au-delà et donnent envie à d'autres de partir ; la peur des proches freine la spirale.
- **Tenues** : choisies à chaque plan selon l'occasion (travail, tous les jours, fête, deuil, froid, cérémonie, voyage, nuit), prêtes pour les emplacements de vêtements de `docs/interfaces.md`.

## Sorties

- `viewer_seed<S>.json` : tout ce que lit la visionneuse (`sim-viewer-0.1`).
- `trajectories_seed<S>.jsonl` (`sim-traj-0.1`), une ligne par décision échantillonnée : `request`, `state` (vocabulaire de `ai/npc_pipeline/samples/schema.json`, plus village, tenue, savoirs), `candidates` (au plus 16, avec utilités et facteurs), `scores`, `chosen`, `plan` (contrat PNJ), `result` (PlanResult : statut, raison, gains, état après). L'échantillonnage passe par un hachage de (seed, heure, PNJ), jamais par le hasard de la simulation : exporter ne change pas l'histoire.

## Repères

- 1 tick = 1 heure de jeu ; 1 an = 12 mois de 30 jours. Les marchandises sont stockées en dixièmes d'unité (entiers).
- Hasard : `splitmix64` maison (`rng.py`), jamais le module `random`.
- Contenu (villages, métiers, savoirs, tenues, prénoms, légendes, normes) : `data/content.json`.
