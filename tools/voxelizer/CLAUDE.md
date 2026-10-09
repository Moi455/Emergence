# CLAUDE.md — tools/voxelizer

Convertisseur de modèles 3D texturés (.obj, .gltf, .glb) en voxels de 2 cm pleins, colorés, avec format compact VXP. Écrit par les devs, livré en octobre 2026. Lis `README.md` (méthode, benchmark, limites) avant de modifier.

- Lancer : `pip install -r requirements.txt` puis `python -m unittest discover -s tests` (50 tests, ~60 s). Interface : `python app.py` (terminal) ou `python app.py web`.
- Le format VXP utilise des briques 8³, les mêmes que les chunks du moteur : ne change pas cette taille sans mesurer (`tools/bench_compact.py`).
- Prochain travail, dans l'ordre : `docs/03_confrontation.md` § 4 à la racine du dépôt (table de matières, VoxelId 16 bits classe+teinte, alignement 24 orientations, LOD, métadonnées et connecteurs, kit entier, décodeur C++).
- Toute modification du format VXP incrémente le `MAGIC`/version et garde la lecture de l'ancien format.
- Les temps d'accès mesurés ici sont ceux de Python ; le jeu lira VXP en C++.
- Ne distribue aucun modèle du kit de test avant vérification de sa licence.
