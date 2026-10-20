# Annexe 19c : journal des décisions de style

Une ligne par aperçu montré à Monsieur et par décision qu'il prend (`docs/19` § 7.8). On ajoute, on n'efface jamais ; une décision remplacée est marquée « remplacée par n° X ».

- **Présentée** : la tâche qui produit l'aperçu écrit la ligne (capture dans `docs/apercus/`, réglages dans le JSON à côté de la capture source, question précise).
- **Décidée** : l'orchestrateur complète la ligne avec la réponse de Monsieur, ses mots exacts entre guillemets, et la valeur retenue dans `engine-rs/lab/style/style.toml`.
- **Référence** : quand Monsieur valide une image, `em_lab approve` la copie dans `engine-rs/lab/reference/` ; le n° de la ligne est noté dans la colonne « Référence ».

| N° | Date | Tâche | Capture (`docs/apercus/`) | Question posée | Réponse de Monsieur | Valeur retenue (`style.toml`) | Référence |
|---|---|---|---|---|---|---|---|
| S0 | 2026-10-20 | (avant le labo) | `00_arbre_reference_chene42.png` | Arbre de référence du générateur Python | validé pour le style (docs/18 § 1) | — | — |
| S1 | 2026-10-20 | L02 | `engine-rs/lab/captures/00_hote_mire.png` (équipe, pas pour Monsieur) | Aucune question de style : mire de l'hôte (ciel de test, pas Hillaire). Question technique : valider la police 8 × 8 en majuscules sans accents pour les surimpressions du labo ? | — | — | — |
| S2 | 2026-10-20 | L03 | `01_ciel_coucher.png`, `01_ciel_aube.png`, `01_ciel_crepuscule.png`, `01_ciel_nuit.png` | Quel ciel et quelle heure se rapprochent le plus de vos images de référence `Image_Style_Jeu.jpg` (coucher de soleil doré avec rayons) ? Les couleurs du couchant (or, rose, violet) vous conviennent-elles ? Nuages : trop étirés, plus de petits cumulus bombés comme sur vos images ? Brume : plus épaisse dans les vallées ? Étoiles de nuit : assez visibles ? (Les rayons de soleil et la brume volumétrique viendront avec la brume 3D ; ici, ciel seul avec crêtes et sol de test.) Réglages dans les JSON des captures (`engine-rs/scripts/serie_ciel.sh`). | — | — | — |
| S3 | 2026-10-20 | L09 | `02_arbre_face_1000.png`, `02_arbre_contrejour_1900.png`, `02_arbre_feuillage_1000.png`, `02_arbre_tronc_1000.png`, à comparer à `00_arbre_reference_chene42.png` (autres prises et heures dans `engine-rs/lab/captures/AAAA-MM-JJ/`, `scripts/serie_arbre.sh`) | Premier rendu voxel : le chêne 42 tracé en lancer de rayons, soleil et ciel sans ombres, sans occlusion, sans indirect. (1) Pixel art : le voxel de 5 cm est-il assez lisible à 19 m (face), 9 m (feuillage) et 3 m (tronc) ? Faut-il plus de grain ou de contraste entre voxels voisins du feuillage ? (2) Tronc : est-ce « un seul bois », continu, sans biseau, comme vous le voulez ? La bande verte (écorce secondaire) vient du générateur Python : la garder ? (3) Feuillage : les verts sont ceux du générateur, mais l'aperçu Python a des creux sombres et des sommets clairs (lumière cuite) que nous n'avons pas encore : acceptez-vous d'attendre les ombres (L11) et l'occlusion (L14), ou voulez-vous un ombrage provisoire ? (4) Contre-jour de 19 h : voulez-vous que les feuilles laissent passer la lumière dorée (translucidité) ? (5) Le sol est en voxels de 5 cm, fondu vers le sol du ciel au-delà de 14 m (une seule clipmap) : le préférez-vous en voxels visibles ou lisse (peau, L17) ? Réglages dans les JSON des captures. | — | — | — |

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

## Décision de style du 21 oct. 2026 (Monsieur)

- **Feuilles** : variation voxel par voxel CONFIRMÉE (gigue de nuance ±14 % de `voxel_tree.py`), exemptée du test de continuité d'em_material (point I4 de la relecture L01-L08).
- **Bois et pierre** : Monsieur veut TESTER un rendu « pixel art vrai » où la texture est créée par la variation de couleur entre voxels, et non par une matière continue en coordonnées monde. Toujours sans chanfrein ni biseau. Action : tâche L23p (recettes mur de pierre / poutre / poteau + mode de matière « variation par voxel » + scène de comparaison A/B continu contre voxel), à lancer après L09. Les captures A/B seront présentées à Monsieur pour trancher par matière.
