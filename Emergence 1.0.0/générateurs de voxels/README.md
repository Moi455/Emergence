# Maisons voxel — générateur médiéval fantaisie à graine

Page unique `maison-voxel.html` (Three.js r128 via CDN, aucun build). Ouvrir dans un navigateur récent avec accès internet (CDN jsdelivr) et WebGL.

## Utilisation
- Saisir une graine puis « Générer » (ou « Au hasard »). La même graine donne toujours la même maison.
- « Paramètres » : JSON éditable (étages, plan rect/L/T, murs, toit, fenêtres, porte, cheminée, appentis…) puis « Appliquer ».
- « Visiter » : ZQSD/WASD, Maj courir, Espace sauter, souris pour regarder.
  - F : ouvrir/fermer la porte ou fenêtre visée (distance ≈ 38 voxels).
  - Clic gauche ou E : détruire un lot de 2×2 voxels.
  - Échap : quitter.
- Bouton qualité : 3 niveaux (post-traitement + bloom / rendu direct / léger). Descente automatique si trop lent.

## Contenu
- Voxels de 5 cm ; murs (pierre irrégulière, colombage), toit, fenêtres/porte ouvrantes, cheminée creuse, perron, appentis, clôture, lanterne.
- Intérieur : pièces toutes reliées par des portes, escalier si étage, mobilier varié (au moins un lit et une cuisine avec poêle/plan de travail, sans évier).
- Rendu : lumière de fin de journée, ombres, brume, relief sous-voxel, ciel, terrain et montagnes, forêt lointaine.
- Arbres : issus de votre `voxel_tree.py` (8 essences, voxels de 10 cm, embarqués compressés, ~1 Mo).

## Limites connues
- Testé seulement sans GPU réel (SwiftShader) : performances et pointer lock non vérifiés.
- De très près, les cubes de 5 cm restent visibles ; toits peu lisibles ; forêt lointaine en boîtes.
- Arbres nécessitent `DecompressionStream` (sinon seule la forêt lointaine s'affiche).
- Pas de lierre (exclu), cascade, animaux, linge.

## Publication
https://claude.ai/artifact/7RQWGKaynnzErnMe81AQVv
