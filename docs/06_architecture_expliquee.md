# L'architecture expliquée (révision 2)

8 octobre 2026, soir. Cette révision applique les critiques de Monsieur du 8 octobre (messages de 14 h 45, 15 h 09, 15 h 18, 15 h 34 et 15 h 51) et ses images de référence (`docs/style/`). Elle remplace la version du matin. Elle explique **pourquoi** chaque choix est fait, ce qui le limite et ce qu'il coûte, pour que Monsieur puisse le critiquer.

**`CHARTE_DU_JEU.md` (racine) prime sur tout**, y compris sur ce document. `02_architecture_cible.md` reste le document de référence pour le code. Là où il contredit ce document-ci, **ce document-ci fait foi** jusqu'à ce que 02 soit réécrit (voir l'avertissement en tête de 02).

Statut des chiffres : **[Mesuré]** = obtenu par un test du projet (dans le conteneur, pas sur une vraie carte graphique) ; **[Source]** = écrit dans un autre document du projet ou publié ailleurs ; **[Calculé]** = arithmétique à partir d'hypothèses écrites ici ; tout le reste est une **estimation**. Rien n'a encore été mesuré sur un vrai GPU.

---

## 0. Ce qui a changé depuis la version du matin

| Sujet | Version du matin | Décision de Monsieur (8 oct.) |
|---|---|---|
| But | Société émergente, PNJ lointains simplifiés | **Simulation réelle du monde, au maximum**, pour que tout émerge. Pas un moteur de règles qui produit des anecdotes (« Jeanne a menti ») |
| Décision des PNJ | Décideur à règles (utilités + HTN) partout ; Transformer en option sur GPU dédié | **Chaque PNJ est piloté par le Transformer**, plusieurs fois par seconde, sans cache, par lots sur le GPU. Pas d'algorithme écrit à la main |
| Sortie du modèle | Un choix d'option | **Une action + l'ajustement progressif des variables du PNJ** ; seule une émotion peut sauter d'un coup ; rien d'erratique |
| PNJ loin du joueur | Exécution résolue par la durée | **Les 500 PNJ sont simulés à pleine puissance partout, tout le temps.** Seul le rendu est coupé hors de vue ; le moteur d'action tourne sans image |
| Conséquences | Opérations matérialisées à l'arrivée | Renforcé : **toute action a une répercussion** dans le monde (un pont détruit l'est quand on arrive) |
| Préparation | Variables des devs | **Avant de coder : définir toutes les variables et toutes les actions.** Les données d'entraînement viendront d'un modèle bien moins cher que Claude |
| GPU | Rendu sur GPU intégré seul, IA sur GPU dédié | **Le GPU dédié est permis pour le rendu, au strict minimum** : il sert d'abord à l'IA. Le profil « GPU intégré seul » tombe |
| Taille des voxels du monde | 2 cm | **Bien plus gros** (taille à fixer, § 6) |
| Aspect | Couleurs seules | **Textures sur les voxels**, style des images de référence |
| Lumière | Mise en cache dans le monde | **Calculée en temps réel** : heure, nuages, météo. On peut précalculer des données qu'on rééclaire, jamais la lumière elle-même |
| Upscaling | 720p agrandi en 1080p | **Pas d'upscaling** : il rendrait le voxel lisse et fade |
| Eau et feu | Champs grossiers liés aux voxels | **Au plus léger et au plus réaliste**, pas forcément en voxels. L'eau reste une quantité qu'on prélève et qui réagit (gravité, collisions) |
| Personnages | Voxels stricts | **Un style voxel** : forme générale cubique, cubes de 1,8 à 2,2 cm, avec des angles et des facettes (voir le nez de `docs/style/pnj_type.png`) |
| Frontières | Le joueur s'effondre et se réveille ramené au village | **Aucune limite visible, jamais de retour au village.** Le monde physique fait environ 20 × 20 km (charte § 2) ; le joueur n'y arrive jamais parce que la difficulté le tue avant (loups, faim, froid). Des PNJ s'y perdent et nourrissent des légendes |

---

## 1. La méthode

Elle ne change pas : partir des contraintes, chercher pour chacune ce qui ferait échouer le jeu, retenir ce qui existe et marche, mesurer ou calculer son coût, et écrire un prototype avec un critère de réussite et un repli quand rien n'existe.

**Le principe directeur** devient : *on simule tout, on ne rend que ce qui est vu*. La simulation (PNJ, actions, conséquences, économie, mémoire) tourne partout à pleine fidélité. Le rendu ne paie que ce qui est à l'écran, avec le moins de GPU possible, parce que le GPU sert d'abord au Transformer.

---

## 2. Les PNJ : le Transformer dans la boucle de chaque personnage

### 2.1 La boucle

```
 toutes les 1/f secondes, pour les 500 PNJ à la fois :

  état du monde ──► entrée de chaque PNJ ─────────────────► un seul lot GPU ──► sorties
  (moteur)          perception + identité + souvenirs        (Transformer)       │
                    + action en cours + actions faisables                         │
                                                                                  ▼
                    ◄── moteur d'action (avec ou sans rendu) ◄── action + deltas de variables bornés
```

- **Entrée** : tout ce qui fait le personnage. Ce qu'il perçoit (personnes, objets, lieux, matières, eau, feu, bruits à sa portée), son identité (traits, valeurs, métier, titres, liens, foyer, village), ses souvenirs les plus pertinents à cet instant, son état (faim, fatigue, émotions, santé), l'action en cours, et les actions faisables proposées par le moteur.
- **Sortie** (charte § 8) : le modèle peut modifier l'état interne du PNJ, modifier ou créer des souvenirs, faire évoluer perceptions, émotions et relations, poursuivre, abandonner ou réorienter un objectif, puis choisir **une action ou une séquence d'actions**. Les variables psychologiques vont de −10 à +10 (charte § 6). Les ajustements sont bornés par groupe : une émotion peut sauter d'un coup ; besoins et relations bougent par petits pas ; traits et valeurs **évoluent progressivement** (charte § 6 : un timide peut devenir assuré).
- **Profondeur variable** (charte § 24) : tous les PNJ n'ont pas besoin de la même profondeur cognitive à chaque instant. La profondeur disponible peut limiter ce qu'un individu accomplit, jamais une règle qui lui interdit un rôle. C'est un levier de coût : taille d'entrée ou fréquence modulées par PNJ, sans jamais couper la simulation.
- **Pas de cache par PNJ** (correction de Monsieur, 15 h 51) : le modèle est rappelé à chaque pas. L'économie vient du **batching** : les 500 PNJ passent dans un seul lot, ce qui remplit le GPU efficacement.
- **Rien d'erratique** : le tirage de l'action se fait avec une graine propre au PNJ, et les bornes empêchent les sauts absurdes. Les mêmes entrées donnent la même sortie.

### 2.2 Ce qui reste du décideur à règles

Il ne pilote plus aucun PNJ dans le jeu. Il garde deux rôles hors jeu : produire des étiquettes gratuites pour amorcer l'entraînement, et servir de **témoin** dans les tests (paires minimales). Le fil Transformer l'a dit : imiter la référence donne des PNJ uniformes ; l'élève doit apprendre de l'enseignant, puis de la boucle de simulation.

### 2.3 Tous les PNJ partout, sans rendu loin du joueur

| | Près du joueur (vu) | Loin du joueur (pas vu) |
|---|---|---|
| Décision | Transformer, même fréquence | Transformer, même fréquence |
| Perception | complète | complète, calculée sur l'état du monde, sans image |
| Exécution | animation, voxels, physique visible | moteur d'action sans rendu : déplacements sur la navigation, actions résolues avec leurs effets réels |
| Conséquences | opérations appliquées aux voxels chargés | opérations appliquées aux deltas des chunks non chargés, sauvegardées, visibles de loin aux niveaux de détail grossiers |

C'est le bus d'opérations (§ 4) qui rend cela possible : chaque action produit une `Operation`, appliquée au monde même si personne ne regarde.

### 2.4 Avant de coder : le catalogue unique

Monsieur l'a demandé : définir **toutes** les variables et **toutes** les actions avant de coder. Le fil Simulation tient le catalogue unique ; le fil Transformer en a écrit la moitié « modèle » (`ai/CATALOGUE_modele.md`, avec une colonne « Écriture » qui donne la borne de variation de chaque variable). Le contrat d'action actuel compte 112 fonctions et 20 conditions (`ai/CONTRAT_PNJ.md`). Ce qui manque encore à l'entrée du modèle : **les jetons de perception** (espace, matières, eau, feu, objets), fournis par le moteur.

### 2.5 D'où viennent les données

1. Amorçage : 300 000 situations étiquetées par le décideur à règles (fait, hors dépôt).
2. **Enseignant bon marché** : un modèle bien moins cher que Claude note des situations (Gemini Flash-Lite visé, ou un modèle local). Prêt, jamais lancé : il attend l'accord et le budget de Monsieur (question 3).
3. Boucle avec la simulation : l'élève joue, on garde les états qu'il visite vraiment, l'enseignant les note, on réentraîne (principe DAgger).

---

## 3. Le monde et ses frontières

- **Monde physique d'environ 20 × 20 km** (charte § 2), où vivent les 5 villages, entouré des marches. Au-delà du bord, il n'y a pas de voxel, seulement le décor lointain non jouable, jusqu'à l'horizon.
- **Aucune limite visible, aucun retour magique.** Entre le cœur et le bord, une hostilité croît de façon exponentielle (elle double tous les quelques centaines de mètres) : froid, faim, soif, tempêtes, bêtes, terrain. Le joueur meurt de ce qui arrive, pas d'une règle. Il ne voit jamais le bord parce qu'il n'y arrive jamais. L'hostilité vaut aussi sous terre et pour une forêt défrichée, pour qu'aucun contournement ne passe.
- **Les PNJ obéissent aux mêmes lois.** Ceux qui partent trop loin ne reviennent pas ; leur disparition devient une histoire que les villages se racontent.
- Orientation (acceptée) : mer à l'ouest, montagne au nord, désert à l'est, forêt au sud.

---

## 4. Une seule vérité et le bus d'opérations (inchangé, et plus important)

- **La vérité** : la seed (et le plan du monde), les chunks modifiés, le journal d'opérations, les entités (PNJ, objets, institutions). Tout le reste est un cache reconstructible.
- **L'opération** est l'unité de changement : creuser, poser, couper, brûler, bâtir, puiser de l'eau. Elle modifie les voxels (ou les deltas d'un chunk non chargé), prévient les témoins (perception → mémoire), est sauvegardée et écrite dans la chronique.
- C'est elle qui garantit « toute action a une répercussion » : un pont détruit par un PNJ loin du joueur existe comme opération ; les témoins s'en souviennent ; le joueur le trouve détruit en arrivant, et le voit de loin.
- **Ce qui manque dans le code** (`engine/ETAT.md`) : le bus (M6), l'application aux chunks non chargés, la sauvegarde des deltas, et la remontée des modifications vers les niveaux de détail grossiers. Aujourd'hui, une édition n'existe qu'au niveau 0, en mémoire.

---

## 5. Le rendu : léger, texturé, éclairé en temps réel

Monsieur a jugé le premier rendu « très moche » et demandé une vraie réflexion. **Le fil Village mène l'étude détaillée** (ce qui existe, ce qui s'applique à un monde procédural et destructible, ce que ça coûte) ; son `ETAT.md` la résume. Voici le cadre de cette étude.

**La cible visuelle** : les quatre images de `docs/style/`. On y voit des blocs lisibles mais pas minuscules, des textures de pierre, de bois et de tuile, de la mousse et du lierre, une lumière chaude de fin de journée, des rayons de soleil dans la brume, de la profondeur atmosphérique jusqu'aux montagnes, et des personnages en style voxel à facettes. Ce sont des images de concept : la cible est l'ambiance, pas l'égalité au pixel près.

1. **Voxels plus gros.** Des voxels deux fois plus gros divisent par environ 4 le nombre de faces à surface égale [Calculé] : c'est le levier le plus puissant sur le coût GPU, et il rend le bloc lisible comme dans les images.
2. **Textures dans le shader.** Chaque face lit une petite texture de sa matière (classe du voxel), avec une variante tirée de la position. Pas de mémoire par voxel en plus ; les bits libres du quad portent la variante [Source : `engine/ETAT.md`].
3. **Lumière en temps réel.** Soleil, ciel, nuages, météo et cycle jour/nuit sont dynamiques. Ce qui ne dépend que de la géométrie peut être précalculé puis **rééclairé** en temps réel : occlusion ambiante aux sommets (déjà faite), visibilité du ciel, sondes d'irradiance mises à jour par morceaux, ombres proches recalculées seulement quand le soleil ou la géométrie bouge. On ne recalcule que ce qui change. Jusqu'à 1 Go de données précalculées est accepté si cela réduit fortement le calcul (accord de Monsieur).
4. **Atmosphère.** Brume de hauteur, perspective aérienne et rayons de soleil font l'essentiel de l'ambiance des images ; ce sont des effets d'écran peu coûteux comparés à la géométrie.
5. **Pas d'upscaling.** Rendu à la résolution native. La finesse vient de la géométrie et des textures, pas d'un agrandissement.
6. **Résolution variable selon la distance.** Les anneaux de niveaux de détail sont gardés (6 anneaux emboîtés aujourd'hui) ; au loin, le paysage peut être une image en cache rafraîchie lentement.
7. **Budget GPU minimal.** Le rendu partage le GPU dédié avec le Transformer : il doit laisser l'essentiel à l'IA (§ 8).
8. **Personnages en style voxel**, pas en voxels stricts : maillages à facettes, forme cubique, cubes de 1,8 à 2,2 cm, avec des angles. Fil Villageois.

---

## 6. Voxels, matières, assets

- **VoxelId de 16 bits** (9 bits de classe de matière, 7 bits de teinte) : inchangé. La classe porte la physique ; la teinte et la texture portent l'aspect.
- **Taille du voxel** : une constante (`kVoxelMm` = 20 dans `engine/core/world/include/emergence/world/voxel_id.h`), partagée avec `worldgen`. La passer à 4 ou 5 cm est un petit chantier connu : changer la constante, la valeur codée en dur dans l'extension Godot, les empreintes de test et le contrat d'interfaces. **Défaut proposé : 5 cm**, à confirmer par Monsieur et par l'étude de rendu (question 1).
- **Chaîne d'assets** : inchangée, jugée correcte par Monsieur. Fichier 3D → convertisseur (`tools/voxelizer`) → module en briques (format VXB3) → instances (VXI) → copie à l'écriture au premier coup. À refaire à la nouvelle taille de voxel.
- **Hiérarchie de stockage** : chunks de 64³ voxels en briques de 8³ ; elle se garde à toutes les tailles de voxel.

---

## 7. Eau, feu, physique

- **Eau** : hors des voxels, au plus léger. Un champ de hauteur d'eau (colonnes) avec écoulement simple, des bassins abstraits pour les lacs et la mer. Une quantité qu'on **prélève** (un seau retire du volume au champ) et qu'on utilise. Elle réagit quand on saute ou plonge, par la gravité et les collisions : vagues et éclaboussures en particules, sans simulation fluide coûteuse.
- **Feu** : un champ de chaleur clairsemé (combustible, humidité, air) qui consomme les matières inflammables par opérations, et des particules pour l'image.
- **Physique** : Jolt (intégré à Godot) pour les corps et les débris ; stabilité des structures en deux étages (connectivité, puis graphe porteur) pour les effondrements.

---

## 8. Estimations de calcul

Machine de référence proposée : le portable de Monsieur, RTX série 3000 de 6 Go, CPU 4 cœurs / 8 threads, 16 Go de RAM. Le GPU intégré peut encore prendre le rendu quand il existe ; le jeu ne doit pas en dépendre.

### 8.1 Le Transformer en jeu (le poste dominant)

Élève `small` : 5,3 M de paramètres [Source : `ai/student/ENTRAINEMENT.md`]. Coût d'un appel ≈ 2 × paramètres × jetons [Calculé].

| Jetons d'entrée | Coût par appel | 500 PNJ à 2 appels/s | à 4 appels/s | à 10 appels/s |
|---|---|---|---|---|
| 64 (format actuel) | 0,68 GFLOP | 0,68 TFLOPS | 1,4 TFLOPS | 3,4 TFLOPS |
| 128 | 1,4 GFLOP | 1,4 TFLOPS | 2,7 TFLOPS | 6,8 TFLOPS |
| 256 | 2,7 GFLOP | 2,7 TFLOPS | 5,4 TFLOPS | 13,6 TFLOPS |

Une RTX 3060 portable donne environ 10 TFLOPS en FP32 (estimation), plusieurs fois plus en FP16 sur ses cœurs tensoriels, avec en pratique 30 à 50 % d'efficacité. **Lecture** : 64 à 128 jetons à 2 à 4 appels par seconde tiennent confortablement ; 256 jetons à 10 appels par seconde saturent la carte. La taille de l'entrée et la fréquence sont les deux réglages qui décident de tout. D'où l'idée de **choisir les souvenirs pertinents** à chaque pas plutôt que de tout envoyer.

Mémoire du GPU dédié : élève < 100 Mo ; entrées et sorties d'un lot de 500 : quelques Mo [Calculé] ; verbaliseur de dialogue (petit LLM local, seulement près du joueur) 1,5 à 2,5 Go ; rendu : le reste, en visant moins de 1,5 Go.

### 8.2 Le reste du jeu, par image (30 images/s, 33 ms)

| Poste | Budget proposé |
|---|---|
| GPU, rendu complet | le moins possible ; cible fixée par l'étude de rendu, à mesurer sur la RTX (touche H du jeu) |
| CPU, thread principal | 8 ms |
| CPU, entrées du Transformer et moteur d'action des 500 PNJ | ≤ 4 ms en moyenne, sur threads de travail |
| Un coup de pioche, toutes conséquences | ≤ 2 ms |
| Génération d'un chunk | environ 0,75 ms sur 4 cœurs [Mesuré, conteneur] |
| Plan du monde (20 km) | 4,2 s à la création [Mesuré, conteneur] |

### 8.3 Simulation accélérée (tests, entraînement, temps qui passe vite)

Avec le Transformer partout, **la simulation ne peut pas aller beaucoup plus vite que le temps réel** : c'est la carte graphique qui limite. Une année de jeu dure environ 2 h de partie (charte § 25, vie d'environ 150 h) ; accélérer au-delà demande de baisser la fréquence ou la profondeur des décisions (charte § 24). Voir la limite 2.

---

## 9. Estimations de stockage

| Contenu | Taille | Calcul ou source |
|---|---|---|
| Plan du monde 20 km | 8 Mo | 1,6 M cellules à 16 m |
| État social des 500 PNJ (souvenirs, relations, croyances, variables) | environ 32 Mo | ~64 Ko par PNJ |
| Maillages autour du bourg, voxels de 2 cm | 52 Mo pour 6,85 M quads, dont 90 % de feuillages lointains | [Mesuré, conteneur] ; nettement moins avec des voxels plus gros |
| Données précalculées pour l'éclairage | jusqu'à 1 Go | plafond accepté par Monsieur |
| Sauvegarde après 100 h | 80 à 500 Mo, cible ≤ 500 Mo | deltas de chunks, opérations, entités |
| Jeu de données d'entraînement actuel | 500 Mo (+ 120 Mo de paires et de trajectoires) | hors dépôt, régénérable |
| Installation | environ 2 à 3 Go | verbaliseur, modules, élève, moteur |

---

## 10. Points limitants

1. **Le GPU partagé entre rendu et IA.** Le Transformer pour 500 PNJ plusieurs fois par seconde et le rendu tiennent ensemble sur la RTX de Monsieur selon le calcul, mais rien n'est mesuré. **Premier test réel à faire sur sa machine** : la scène jouable avec un lot de 500 appels du Transformer à chaque pas.
2. **Le temps qui passe.** La charte (§ 25) vise une vie de PNJ d'environ **150 h de jeu**, enfance courte. Pour une vie d'environ 70 ans, une année de jeu dure donc environ 2 h de partie [Calculé], soit un jour de jeu en une vingtaine de secondes. L'échelle « 1 jour = 4 h réelles » (P14) est donc caduque. Conséquence : en temps réel, chaque PNJ vit très vite ; la fréquence du Transformer doit se compter **par jour de jeu**, pas par seconde réelle, et il faut définir quelles décisions se prennent à quel rythme (une conversation se joue à l'échelle du joueur, une vie à l'échelle des heures). À concevoir en premier dans la boucle (chantier 4).
3. **La perception à fournir au modèle.** Le modèle ne voit aujourd'hui que des situations sociales. Il faut définir ce qu'un PNJ perçoit et l'encoder en jetons, sans exploser la taille de l'entrée (§ 8.1).
4. **Les étiquettes.** Aucune étiquette d'enseignant n'existe ; l'élève actuel imite des règles. Il faut lancer l'enseignant bon marché (accord et budget de Monsieur), puis la boucle avec la simulation.
5. **Le rendu à refaire.** Textures, lumière en temps réel, voxels plus gros, pas d'upscaling : rien de cela n'est encore codé. L'étude du fil Village fixe le chemin ; aucun chiffre GPU réel n'existe.
6. **Les conséquences hors de vue.** Le bus d'opérations, les deltas sur les chunks non chargés et la sauvegarde ne sont pas codés. Sans eux, « tout a une répercussion » n'est pas tenu.
7. **Le monde de 20 km.** Conforme au plan actuel du moteur (version 1) ; rien à changer.
8. **Le volume de contenu** : générateurs, usure par graine et connecteurs restent la parade.
9. **Steam** : romance non explicite entre adultes, risque faible (vérifié le 8 oct.) ; reste à déclarer le contenu généré en direct par le verbaliseur et ses garde-fous (O7).

---

## 11. Questions pour Monsieur

Tranchées par la charte : la taille du monde (20 × 20 km), l'échelle de temps (une vie d'environ 150 h de jeu) et l'évolution des traits (progressive). Il reste :

1. **Taille des voxels du monde** : la charte dit « quelques centimètres » ; défaut proposé 5 cm.
2. **Fréquence du Transformer** : combien d'appels par PNJ, à exprimer par jour de jeu (voir limite 2) ?
3. **Enseignant bon marché** : quel modèle (Gemini Flash-Lite, un modèle local) et quel budget ?
