# Chantiers ouverts (8 octobre 2026, passage sur Claude Code)

`CHARTE_DU_JEU.md` prime sur tout ; en cas de contradiction avec ce fichier, elle gagne.

Ordre conseillé. Chaque chantier se termine par une mesure sur la machine de Monsieur, pas par « ça compile ». Détail : `docs/06_architecture_expliquee.md` et les `ETAT.md` de chaque dossier.

## 1. Mesurer ce qui existe, sur le vrai GPU (premier jour)

- Reconstruire la GDExtension (`engine/`), lancer `godot --path game`, noter images/s et temps GPU (touche H) autour du bourg. Aucun chiffre réel n'existe.
- Lancer un lot factice de 500 appels de l'élève `small` à 2, 4 et 10 Hz pendant que la scène tourne : mesurer l'impact sur le rendu et le temps par lot (limite 1 de `06`).

## 2. Entraîner le Transformer sur la RTX

- Suivre `ai/student/ENTRAINEMENT.md`. Le jeu de données (500 Mo) n'est pas dans le ZIP : le régénérer avec `python ai/npc_pipeline/build_dataset.py --n 300000 --name ref_v04_300k` (déterministe).
- Ce ne sont que des étiquettes du décideur à règles : point de départ, pas l'objectif. L'enseignant bon marché attend l'accord et le budget de Monsieur (O13).

## 3. Le catalogue complet des variables et des actions (avant tout nouveau code PNJ)

- Fusionner `ai/CATALOGUE_modele.md` et le catalogue de `sim/` en un seul fichier, avec pour chaque variable sa borne d'écriture par pas.
- Ajouter la **perception** (ce qu'un PNJ voit : espace, matières, eau, feu, objets) et son encodage en jetons, en restant à 64 à 128 jetons.

## 4. Brancher le Transformer dans la boucle

- Remplacer le moteur à règles de `sim/` par la boucle de `06` § 2.1 : 500 PNJ en un lot, plusieurs fois par seconde ; sortie = action + deltas bornés.
- Ajouter au modèle la tête « ajustement des variables » (`ai/ETAT.md`, écart 1).
- Moteur d'action sans rendu pour les PNJ hors de vue, avec effets réels.

## 5. Le bus d'opérations et les conséquences persistantes

- M6 : toute écriture passe par une `Operation` ; application aux chunks non chargés (deltas), sauvegarde, remontée vers les niveaux de détail grossiers (un pont détruit se voit de loin).

## 6. Rendu au niveau des images de `docs/style/`

**Écart actuel (constaté le 8 oct.)** : voxels de 2 cm à couleurs unies, sans texture ; lumière simple, sans brume ni rayons ; feuillage lointain lourd ; personnages en voxels stricts. Monsieur a jugé le rendu « très moche ». Les images de `docs/style/` sont la barre, pas moins.

À faire :
- Taille des voxels (O9) : 5 cm proposé ; le prototype village a essayé 10 cm (son `RENDU.md`). À trancher par Monsieur sur captures, puis constante `kVoxelMm`, extension Godot, empreintes, contrat d'interfaces.
- Textures par matière (O14) : demandées par Monsieur ; le prototype village s'en passe (grain procédural, biseau, PRT, grille de ciel). Montrer les deux sur captures avant de choisir.
- Lumière en temps réel (soleil, ciel, nuages, météo) avec données rééclairables précalculées (occlusion, visibilité du ciel, sondes d'irradiance), brume de hauteur, rayons de soleil ; pas d'upscaling.
- Personnages en style voxel à facettes (`characters/`), cubes de 1,8 à 2,2 cm.
- Chaque étape : une capture comparée aux images de référence.

**Outils externes nécessaires pour ce niveau** (Monsieur a demandé qu'on le lui dise) :

| Besoin | Outil proposé | Coût | Pourquoi |
|---|---|---|---|
| Modèles 3D de maisons, objets, végétation, à voxeliser | **Meshy AI** (ou Tripo, Rodin) : image ou texte → modèle 3D texturé | abonnement payant au-delà de l'essai | le kit actuel ne suffit pas pour la variété et la richesse des images ; le convertisseur `tools/voxelizer` transforme leurs sorties en modules |
| Textures de matières (pierre, bois, tuile, mousse) | **Poly Haven** et **ambientCG** | gratuit (CC0) | textures sources pour le shader, réduites au style voxel |
| Retouche des modèles avant voxelisation | **Blender** | gratuit | épaissir les détails trop fins, nettoyer, poser les pivots |
| Personnages de base | Meshy AI ou modèles existants, puis stylisation à facettes | idem Meshy | le style du PNJ de référence demande des visages sculptés, pas seulement des cubes |

Aucun de ces services payants ne doit être utilisé sans l'accord de Monsieur. La licence du Medieval Village MegaKit (O5) reste à vérifier avant toute distribution.

## 7. Eau, feu, frontières

- Eau en champ de hauteur prélevable, feu en champ de chaleur + particules (D24).
- Hostilité des marches jusqu'à la mort, sans limite visible (D26), dans le monde de 20 × 20 km (D27).

## Ce qui n'est pas dans le ZIP

- Jeu de données d'entraînement (500 Mo) et trajectoires : se régénèrent (chantier 2).
- `assets/` (Medieval Village MegaKit, Git LFS) : se récupère par `git lfs pull` dans le dépôt GitHub `Moi455/Emergence`.
- `.glb` des villageois : se régénèrent avec `characters/tools/export.mjs`.
- Binaires de la GDExtension : se reconstruisent.

## États des parties

Reçus : `ETAT.md` (racine), `engine/ETAT.md`, `ai/ETAT.md`. Les bilans de la génération du monde, de la simulation, du village et des villageois n'étaient pas déposés au moment du ZIP ; leurs `README.md` décrivent ce qui est fait.

## Questions pour Monsieur

Il en reste quatre (`docs/01_decisions.md`, O9, O10, O13, O14) : taille des voxels (5 cm proposé, 10 cm essayé), textures bitmap ou non, nombre d'appels du Transformer par PNJ, enseignant bon marché et son budget. Plus l'accord pour un outil comme Meshy AI. La charte a tranché le reste.
