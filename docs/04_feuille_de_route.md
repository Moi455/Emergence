# Feuille de route

Principe : on avance dans l'ordre des risques, et chaque étape a un critère mesuré sur la machine de référence (Iris Xe + RTX série 3000 6 Go). Une étape n'est finie que lorsque son critère est mesuré, pas quand le code compile. Deux pistes avancent en parallèle : le **monde** (voxels, rendu) et la **société** (PNJ), parce qu'elles ne se touchent qu'au contrat décision / action et au bus d'opérations.

## Phase 0 : mise en place (avant tout prototype)

| Tâche | Fini quand |
|---|---|
| 0.1 Créer le dépôt Git à partir de ce ZIP, pousser sur GitHub privé | `scripts/test_all.sh` passe sur la machine de Monsieur |
| 0.2 CI minimale : tests Python des deux outils, scan des secrets | la CI est verte |
| 0.3 Squelette CMake du cœur C++ (`engine/core`) avec un test unitaire vide et un exécutable `emergence_sim` vide | compile sous Linux et Windows |
| 0.4 Squelette Godot 4 (`game/`) qui charge une GDExtension vide | la scène s'ouvre |
| 0.5 Mesurer la machine de référence : bande passante mémoire, temps d'un triangle plein écran, capacités Vulkan des deux GPU | fichier `docs/mesures/machine_reference.md` |

## Piste Monde

| N° | Prototype | Critère de réussite | Repli si échec |
|---|---|---|---|
| M1 | Plan du monde 20 × 20 km depuis une seed (relief, érosion, rivières, biomes, frontières, sites des villages) | moins de 30 s à la création, décor compris ; empreinte identique au bit sur deux machines | 2 min ; plan à 32 m, érosion simplifiée |
| M2 | Chunks 64³ en briques 8³, génération locale déterministe, VoxelId 16 bits | génération d'un chunk de surface < 1 ms ; empreintes stables | — |
| M3 | Maillage greedy binaire et anneaux de LOD jusqu'à 640 m | géométrie de tous les anneaux < 6 ms GPU ; < 1 Go VRAM | changer de niveau à 1,5 pixel |
| M4 | Micro-briques de 8 cm tracées dans le pixel shader (anneau 0) | ≥ 2 fois moins cher que des faces de 2 cm à image égale | anneau 0 réduit à 6 m |
| M5 | Lumière en cache dans le monde | mise à jour après un coup de pioche < 1 ms CPU ; passe couleur < 3 ms GPU | lumière par sommet seule |
| M6 | Bus d'opérations + coup de pioche de bout en bout (voxels, maillage, collisions, navigation, lumière, stabilité) | ≤ 2 ms | étaler sur plusieurs images |
| M7 | Lointain en cubemap + relief du plan au-delà de 5 km, décor de seed jusqu'à l'horizon, courbure, atmosphère, ombre des montagnes, origine flottante | depuis un sommet, carte entière et décor jusqu'à l'horizon visibles avec courbure, atmosphère et ombre des montagnes, < 2 ms GPU en moyenne, pas de trou à 10 m/s ; carte d'ombre à 32 m recalculée par tranches < 10 ms CPU ; aucun tremblement ni dérive physique au coin de la carte (14 km du centre) ; une tour de 30 m bâtie sur un sommet visible à 20 km dans la minute | cubemap moins fréquent, décor à 512 m dès le bord, ombre à 64 m, double précision Godot/Jolt, imposteurs sans tuiles de surcharge |
| M8 | Modules du convertisseur instanciés en copie à l'écriture | village de 30 maisons : mémoire et temps de dessin mesurés contre des chunks ordinaires | modules recopiés au chargement |
| M9 | Eau (colonnes + bassins) et feu (champ clairsemé) | vider 100 seaux et brûler un village sans passer sous 30 images/s | fréquence réduite |
| M10 | Persistance par régions, journal d'opérations, compaction | 100 h simulées : sauvegarde < 500 Mo, chargement < 10 s | compaction plus agressive |
| M11 | Frontière : une marche et son retour (sauvetage narratif) | des testeurs qui cherchent à passer ne repèrent ni mur ni règle, et chaque doublement d'équipement les mène environ 300 m plus loin | marche plus large, vue plus bornée, retour plus tôt |
| M12 | Deux GPU (prototype 7 du document de rendu) | rendu sur l'intégré pendant l'inférence sur la RTX, < 1 ms d'impact par image ; inférence entière identique au bit près sur CPU et GPU | inférence flottante, décisions exclues de ce qui doit être reproductible |

## Piste Société

| N° | Étape | Critère de réussite |
|---|---|---|
| S1 | Pipeline des devs, points 1 à 3 de leur liste : `representation.py` branché dans le texte du teacher, ambition et tolérance, couche village dans le générateur | `generate_states.py --check` sans violation ; rapport `corpus_report.py` sur 1 000 situations |
| S2 | Contenu des souvenirs, familles nouvelles (commerce entre villages, voyage, frontière, parcelles, apprentissage) | 30 cas toujours verts ; nouvelles familles couvertes par le rapport |
| S3 | Paires de sensibilité + pilote Gemini réel + 100 étiquettes à l'aveugle (`gold_tool.py`) | accord teacher/humain mesuré ; décision prise sur la variante de prompt |
| S4 | Portage C++ du noyau social : contrat de plan, mémoire (avec index), règles sociales, protocoles de dialogue, chantier, analyseur | chaque module reproduit les sorties de sa version Python sur un jeu de tests partagé |
| S5 | Décideur de référence (utilités + HTN) et moteur d'action abstrait (palier 2) | `emergence_sim` fait vivre 500 PNJ en 5 villages avec le décideur de référence ; 1 an de jeu en moins de 10 minutes, 50 ans en une nuit ; métiers transmis et perdus observables |
| S6 | Institutions (famille, atelier, village, culte, seigneurie), titres, avis, un vote | cas 29 passe de SPEC à OK |
| S7 | Gros jeu de données teacher, entraînement de l'élève, inférence entière | l'élève bat la référence sur les 30 cas en paires minimales ; mêmes décisions au bit près sur CPU et GPU |
| S8 | Boucle simulateur → teacher → élève (DAgger) : déroulés courts de l'élève (quelques jours à quelques semaines de jeu) lancés depuis des états de la référence | l'écart élève/référence diminue sur les états réellement visités |
| S9 | Visualiseur d'esprit (pourquoi ce PNJ a obéi, refusé, menti) | utilisable dès les premiers PNJ jouables |

## Jonction : tranche verticale

Un village de 100 PNJ près du joueur, dans un monde réel de quelques km² : travail (creuser, cultiver, bâtir par chantier), parole (questions, négociation, rumeur), un avis affiché, un vote, un vol et ses suites. Critères : 30 images/s sur Iris Xe ; ≤ 3 ms CPU de société par image ; revenir après 10 ans de jeu simulé et retrouver un village cohérent.

## Premières tâches conseillées pour Claude Code

1. Phase 0 complète (0.1 à 0.4).
2. M1 et S1 en parallèle : ce sont les deux socles, et ils ne dépendent de rien.
3. Le convertisseur : table de matières et VoxelId 16 bits (`docs/03_confrontation.md` § 4, points 1 et 2), pour que les premiers modules soient au bon format dès M8.
