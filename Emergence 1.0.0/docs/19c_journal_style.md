# Annexe 19c : journal des décisions de style

Une ligne par aperçu montré à Monsieur et par décision qu'il prend (`docs/19` § 7.8). On ajoute, on n'efface jamais ; une décision remplacée est marquée « remplacée par n° X ».

- **Présentée** : la tâche qui produit l'aperçu écrit la ligne (capture dans `docs/apercus/`, réglages dans le JSON à côté de la capture source, question précise).
- **Décidée** : l'orchestrateur complète la ligne avec la réponse de Monsieur, ses mots exacts entre guillemets, et la valeur retenue dans `engine-rs/lab/style/style.toml`.
- **Référence** : quand Monsieur valide une image, `em_lab approve` la copie dans `engine-rs/lab/reference/` ; le n° de la ligne est noté dans la colonne « Référence ».

| N° | Date | Tâche | Capture (`docs/apercus/`) | Question posée | Réponse de Monsieur | Valeur retenue (`style.toml`) | Référence |
|---|---|---|---|---|---|---|---|
| S0 | 2026-10-20 | (avant le labo) | `00_arbre_reference_chene42.png` | Arbre de référence du générateur Python | validé pour le style (docs/18 § 1) | — | — |

## Questions de style ouvertes (à trancher sur captures)

Reprises de `docs/19` § 9 ; chacune est fermée par une ligne « décidée » ci-dessus.

| Question | Capture qui la pose | Tâche |
|---|---|---|
| Q2 peau du terrain en pixel art (`cell`) ou mélangée (`blend`) | `10_peau_cellule_ou_melange.png` | L17 |
| Q3 grain visible dans un voxel ou couleur unie | `16_poutre_detail_ab.png` | L22 |
| Q4 arbres voxel immobiles avec scintillement, ou balancement | `13b_vent_ab.png` | L20 |
| Q5 joint sombre entre deux pierres (jamais entre deux voxels d'une pierre) | `17_mur_poutre_1730.png` | L23 |
| Q8 arbres lointains en silhouette, canopée au-delà de 800 m | `20_panorama_foret.png`, `26_foret_silhouettes.png` | L26, L32 |
| Q9 TAA doux ou arêtes plus nettes | `06_taa_ab.png` | L12 |

Les autres questions de `docs/19` § 9 (Q1 réserve de budget, Q6 nuages, Q7 textures hors git, Q10 terrain du labo, Q11 rythme des aperçus) ne demandent pas de capture ; leurs réponses vont dans `docs/01_decisions.md`.

## Décisions de Monsieur déjà prises (20 oct. 2026)

- Budget du rendu : 50 % du GPU (« j'accepte 50 % du GPU finalement ») : plafond 8,3 ms, cible 6,5 ms (P57).
- Pixel art partout sauf l'herbe et les fleurs ; aucun chanfrein ; un bois paraît un seul bois (`docs/19` § 0.2).
