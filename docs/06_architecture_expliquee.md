# L'architecture expliquée

8 octobre 2026. Ce document explique **comment** l'architecture a été construite et **pourquoi** chaque choix a été fait, pour qu'on puisse la critiquer. Il ne remplace pas `02_architecture_cible.md`, qui fait foi pour le code ; il en donne le raisonnement, les limites et les chiffres.

Statut des chiffres : **[Mesuré]** = obtenu par un test du projet ; **[Source]** = publié ailleurs (références dans `docs/reference/`) ; **[Calculé]** = arithmétique à partir d'hypothèses écrites ici ; tout le reste est une **estimation** à vérifier par prototype. Aucun moteur n'existe encore : la plupart des chiffres sont des calculs, pas des mesures.

---

## 1. La méthode

L'architecture n'est pas partie d'un moteur existant. Elle est partie des contraintes et a cherché, pour chacune, ce qui ferait échouer le jeu.

**Les contraintes de départ** (vos décisions) :

| Contrainte | Ce qu'elle impose |
|---|---|
| Voxels de 2 cm, tout destructible | 15 625 voxels par m² de surface, soit 10¹³ voxels de surface sur 400 km² [Calculé] : impossible à stocker ni même à générer en entier |
| Rendu sur GPU intégré | Bande passante mémoire de 68 Go/s au mieux sur Iris Xe, partagée avec le CPU [Calculé] ; aucun jeu à voxels fins ne tourne dessus aujourd'hui |
| GPU dédié réservé à l'IA | Le rendu ne peut pas « emprunter » le GPU dédié ; l'IA, elle, a une vraie puissance de calcul |
| Monde déterministe, seuls les deltas sauvegardés | La génération doit donner le même résultat au bit près, sur toute machine, toujours |
| 500 PNJ avec mémoire, société émergente | Pas de script : les événements doivent remonter du monde physique jusqu'à la mémoire des PNJ |
| Performance d'abord | Ne jamais calculer au-delà de la précision nécessaire |

**Le principe qui en sort** : *on ne paie que ce qui est perçu*. Le détail à 2 cm n'existe que là où quelqu'un regarde ou agit. Ailleurs, le monde est une formule (la seed), un journal d'événements et des résumés. C'est ce principe, appliqué système par système, qui donne toute l'architecture.

**Comment chaque choix a été fait** : pour chaque système, on a cherché ce qui existe déjà et marche (Minecraft et ses mods, Teardown, Vintage Story, 7 Days to Die, Dwarf Fortress, publications de rendu et d'IA), on a mesuré ou calculé son coût sur la machine de référence, et on a gardé ce qui tient dans le budget. Quand rien n'existait (le 2 cm sur GPU intégré), on a combiné des techniques prouvées séparément et on a écrit un prototype avec un critère de réussite et un repli.

**Puis la confrontation avec le travail des développeurs.** Leur code a été lu, testé (tous les tests passent [Mesuré]) et comparé point par point (`03_confrontation.md`). Plusieurs de leurs idées ont remplacé les nôtres ; c'est indiqué plus bas.

---

## 2. Les dix choix, un par un

Chaque choix est présenté de la même façon : le problème, la solution, pourquoi celle-là, ce qu'on a écarté, et **ce qui la ferait tomber** (le point à critiquer).

### Choix 1 — Une seule vérité, tout le reste est un cache

- **Problème** : un monde de 400 km² modifiable ne tient ni en mémoire ni dans une sauvegarde si on le stocke en voxels.
- **Solution** : la vérité tient en quatre choses : la seed (et le plan du monde qu'elle produit), les chunks modifiés à la main, le journal d'opérations, les entités (PNJ, objets, institutions). Maillages, collisions, navigation, lumière, eau, feu sont des caches jetables, reconstruits là où une opération a touché.
- **Pourquoi** : c'est la seule façon d'avoir à la fois un monde immense, une sauvegarde petite et aucune incohérence entre systèmes (un cache ne peut pas contredire la vérité, il est reconstruit depuis elle).
- **Écarté** : stocker le monde en octree compressé (SVO/DAG) comme vérité. Excellent pour un monde statique, mais chaque modification coûte cher [Source : HashDAG, 1,5 à 2 fois plus lent au rendu].
- **Ce qui le ferait tomber** : un système qui garde sa propre copie « pour aller plus vite ». C'est l'invariant I3, à surveiller en revue de code.

### Choix 2 — L'opération comme unité de changement (idée nouvelle, née de la confrontation)

- **Problème** : trois besoins semblaient séparés. La sauvegarde veut des deltas compacts. Les chantiers des PNJ loin du joueur doivent avancer sans voxels. La mémoire des PNJ veut des événements perçus par des témoins.
- **Solution** : un seul enregistrement, l'`Operation` (qui, quoi, forme, outil, matière, graine, bruit, visibilité). Il est appliqué aux voxels, ou mis en attente si la zone n'est pas chargée. Il prévient les témoins, qui en font un souvenir. Il est sauvegardé et écrit dans la chronique.
- **Pourquoi** : c'est le pont entre la physique et la société. Un pont détruit hors de la vue du joueur existe comme opération ; les témoins s'en souviennent ; quand le joueur arrive, les voxels apparaissent depuis la même opération. Le cas 30 des devs (« événement → perception → mémoire → rumeur → réputation ») devient une propriété du moteur, pas un scénario.
- **Écarté** : un système d'événements séparé pour l'IA. Il aurait créé deux vérités.
- **Ce qui le ferait tomber** : une opération non déterministe (un effondrement physique calculé en flottants). **Règle** : tout ce qui n'est pas rejouable au bit près (débris physiques) est enregistré comme résultat, jamais rejoué.

### Choix 3 — Le voxel : 16 bits, classe de matière + teinte (idée nouvelle, née de la confrontation)

- **Problème** : le convertisseur des devs garde une couleur par voxel ; leur propre benchmark montre que **la couleur coûte 10 fois plus que la forme** (4,5 à 5,6 bits par voxel contre 0,2 à 1,3) [Mesuré, `tools/voxelizer/docs/benchmark_encodages.md`]. Notre architecture prévoyait « matière seule », plus pauvre visuellement.
- **Solution** : `VoxelId` = 9 bits de classe (512 matières : résistance, densité, inflammabilité, son) + 7 bits de teinte (128 nuances par matière). La physique, le feu et l'IA ne lisent que la classe. Le terrain généré écrit la teinte 0 et laisse la variation au shader. Le maillage fusionne sur la classe seule.
- **Pourquoi** : on garde la richesse des textures converties sans payer 24 bits par voxel, et les briques de terrain restent uniformes (2 octets pour 512 voxels).
- **Écarté** : couleur 24 bits par voxel (mémoire ×3 et briques jamais uniformes) ; matière seule (modules convertis trop pauvres).
- **Ce qui le ferait tomber** : si 128 teintes par matière ne suffisent pas pour les modules convertis. À vérifier en reconvertissant le kit de 176 pièces.

### Choix 4 — La hiérarchie de stockage : chunk 64³, brique 8³, micro-brique 4³

- **Problème** : trouver la granularité qui compresse bien, se modifie vite et se dessine vite.
- **Solution** : chunk de 64³ voxels (1,28 m) pour la génération, le maillage et la sauvegarde ; brique de stockage 8³ (16 cm) uniforme ou à palette locale ; micro-brique de rendu 4³ (8 cm) dont l'occupation tient exactement dans un entier de 64 bits.
- **Pourquoi** : 64³ est la taille où le maillage greedy binaire est le plus rapide (masques de 64 bits, 74 µs par chunk en moyenne [Source]). Les briques 8³ sont celles qui donnent le meilleur compromis dans le benchmark des devs : 6,1 à 6,4 bits par voxel couleur comprise [Mesuré], contre 8,6 à 11,3 en 4³. Les deux choix tombent juste sans l'avoir cherché.
- **Écarté** : chunks 32³ (plus de surcoût par chunk), 16³ en stockage (moins de briques uniformes).
- **Ce qui le ferait tomber** : peu de chose ; c'est le choix le mieux étayé.

### Choix 5 — Le rendu sur GPU intégré : la taille des voxels double avec la distance

C'est **le point le plus risqué** du projet, et celui sur lequel vous aviez demandé une solution plutôt qu'un constat d'échec.

- **Problème** : Teardown, la référence du voxel destructible, exige une GTX 1060 et ne supporte pas les GPU intégrés Intel [Source]. Son coût vient du lancer de rayons long et de l'éclairage recalculé à chaque image, pas de la taille des voxels.
- **Solution, en cinq idées combinées** :
  1. **Le 2 cm seulement là où il se voit.** En 720p, un voxel de 2 cm fait moins d'un pixel au-delà d'environ 10 m [Calculé]. Au-delà, on dessine des voxels plus gros.
  2. **Des anneaux à coût constant.** Chaque fois que la distance double, la taille des voxels double. Chaque anneau contient alors environ 600 000 cellules de surface, quelle que soit sa distance [Calculé]. Le coût total croît comme le logarithme de la distance de vue, pas comme son carré.
  3. **La géométrie par rastérisation, le détail par le pixel.** Près du joueur, le GPU dessine les faces des briques de 8 cm ; le détail à 2 cm à l'intérieur est tracé dans le pixel shader, sur une dizaine de pas au plus, en lisant 8 octets. Cela divise par 16 le nombre de faces de l'anneau le plus dense [Calculé].
  4. **La lumière calculée une fois, dans le monde.** Elle est stockée sur les surfaces et recalculée seulement là où un coup de pioche a changé quelque chose : l'inverse exact de Teardown.
  5. **Ce qui ne bouge pas n'est pas redessiné.** Au-delà de 640 m, le paysage est une image en cache (un cubemap avec profondeur), rafraîchie une face par image.
- **Plus loin** : relief du plan du monde en geometry clipmap jusqu'au bord, puis décor de seed (128 m, puis 512 m) jusqu'à l'horizon, à 196 km depuis un sommet de 3 km [Calculé], avec courbure de la Terre dans le shader et atmosphère précalculée.
- **Budget proposé à 30 images/s** : 22 ms de GPU sur 33, dont 6 ms de géométrie, 3 ms de micro-tracé, 3 ms de lumière, 3 ms de PNJ, 3 ms d'eau et transparences, 1 ms de lointain, 3 ms d'upscaling 720p → 1080p.
- **Écarté** : lancer de rayons dans tout le volume (Teardown) ; octree compressé comme rendu principal (Aokana : statique, sans édition).
- **Ce qui le ferait tomber** : les surfaces rugueuses laissées par la pioche. Le greedy meshing fusionne mal l'organique ; l'hypothèse d'une réduction par 4 des triangles n'est pas mesurée. **Repli** : réduire l'anneau 2 cm à 6 m et passer de niveau à 1,5 pixel ; on perd un peu de détail à mi-distance, le jeu reste jouable. Les prototypes M3, M4 et M5 de la feuille de route tranchent.

### Choix 6 — La voxelisation des assets : du fichier 3D au module (votre question)

**Oui, on a une solution, et elle est en grande partie déjà écrite par vos développeurs.**

- **Ce qui existe et marche** [Mesuré, 50 tests verts] : voxelisation conservative depuis .obj/.gltf, remplissage de l'intérieur (un mur de pierre est plein de pierre, sinon la destruction révèle du vide), bouchage des murs ouverts, palette de couleurs en OKLab par k-means, format VXP en briques 8³ à accès aléatoire (17 µs par lecture en Python [Mesuré]), environ 7 fois plus compact que l'export JSON compressé.
- **Ce qu'on y ajoute** :
  1. **Projection sur les matières** : chaque couleur est rattachée à une classe de matière (chêne équarri, granit taillé, chaume), avec une proposition automatique que l'artiste corrige. C'est le choix 3.
  2. **Modules partagés en copie à l'écriture** : chaque module (mur, fenêtre, maison entière) est stocké une fois. Le monde ne contient que des références (module, position, une des 24 orientations, graine), 16 à 32 octets chacune. Au premier coup de pioche, le chunk recopie les voxels et devient ordinaire.
  3. **Usure par graine** : la graine de chaque copie pilote une usure procédurale (arêtes ébréchées, mousse). Trente maisons du même modèle ne se ressemblent pas, sans stocker trente copies.
  4. **Connecteurs** : chaque module porte des points d'attache (mur-mur, mur-toit, porte-cadre) pour que les générateurs assemblent sans trous.
  5. **Le même module sert au chantier des PNJ** : un blueprint est une liste d'instances de modules ; le travail restant est toujours « blueprint moins monde » (idée des devs, gardée telle quelle : elle ne peut pas se corrompre et guérit après vandalisme).
- **Ce qui manque encore** : la table des matières, les niveaux de détail précalculés par module, les connecteurs, l'épaississement automatique des détails de moins de 2 cm (qui disparaissent à la voxelisation).
- **Ce qui le ferait tomber** : le volume de production. À 2 cm, chaque objet compte des dizaines de milliers de voxels (un mur avec fenêtre : 31 914 [Mesuré]). D'où la priorité aux générateurs et à l'usure par graine plutôt qu'à la retouche manuelle.

### Choix 7 — Physique, eau, feu, effondrements : des champs grossiers, pas des voxels

- **Problème** : simuler l'eau et le feu au voxel de 2 cm coûterait des millions de cellules.
- **Solution** : rien de dynamique dans le voxel. L'eau est une hauteur par colonne de 25 cm, plus des bassins abstraits. Le feu est un champ clairsemé de 25 à 50 cm (température, combustible, humidité, ouverture à l'air). Les effondrements passent par une stabilité en deux étages : connectivité bornée, puis graphe porteur grossier (approche 7 Days to Die). Les débris deviennent des corps rigides Jolt (boîtes de 4 à 8 cm, environ 200 corps actifs au plus).
- **Pourquoi** : ces systèmes n'ont besoin que de la précision à laquelle l'œil juge le phénomène. Une flamme n'a pas besoin d'une cellule de 2 cm.
- **Ce qui le ferait tomber** : les arches et les voûtes, mal gérées par le modèle 7 Days to Die ; l'eau sur plusieurs étages souterrains. Les deux sont notés dans `05_idees.md`.

### Choix 8 — Les PNJ : une décision identique partout, seule l'exécution change

- **Problème** : 500 PNJ avec mémoire, sans que le village « saute » quand le joueur arrive.
- **Solution** : les 500 PNJ prennent tous de vraies décisions individuelles, avec les mêmes entrées, où qu'ils soient. Ce qui baisse avec la distance, c'est la fidélité de l'exécution. Au palier 0 (64 PNJ au plus, près du joueur), le plan s'exécute voxel par voxel. Au palier 1 (le reste du village du joueur), les actions sont résolues par leur durée. Au palier 2 (les quatre autres villages), la résolution est horaire et les opérations sont enregistrées, puis matérialisées à l'arrivée du joueur.
- **Le contrat des devs** (gardé tel quel) : `DecisionRequest` → `Plan` de 1 à 6 étapes avec conditions d'arrêt et d'interruption → `PlanResult`. Un plan de 15 coups de pioche est une décision, pas quinze : le décideur n'est réveillé que quand un plan finit, échoue ou est interrompu.
- **Deux décideurs, un contrat** : une référence lisible (utilités + HTN, quelques µs sur CPU) et un élève (Transformer de 5 à 30 M de paramètres, distillé depuis Gemini, sur le GPU dédié). Règle des devs : l'élève doit battre la référence sur les 30 cas de capacités, sinon il n'entre pas.
- **Écarté** : des agrégats de population pour les villages lointains (prévus quand on parlait de milliers d'habitants ; inutiles à 500).
- **Ce qui le ferait tomber** : la qualité des données d'entraînement. Aucune étiquette réelle n'existe encore. Voir la limite 5 plus bas.

### Choix 9 — Le langage naturel n'entre jamais dans l'état

- **Solution** : le texte du joueur devient un cadre structuré (acte, force, politesse, modalité, contenu), par l'analyseur des devs (anglais, 15 tests). La réponse d'un PNJ est produite par un petit LLM local à partir d'un cadre ; ce LLM n'a aucun accès en écriture à la simulation.
- **Pourquoi** : c'est ce qui garde le jeu déterministe, sauvegardable et sûr. Un LLM qui écrirait dans l'état rendrait toute sauvegarde non rejouable.
- **Vous avez tranché** : anglais seulement pour l'instant ; le cadre est indépendant de la langue.

### Choix 10 — Le monde de 20 km et ses frontières

- **Solution** : un cœur habité d'environ 14 × 12 km. Autour, des marches de 3 km (5 km côté montagne) où une hostilité H double tous les 300 m (500 m en montagne). H n'est pas une règle à part : il multiplie la soif, le froid, la houle, la densité des bêtes. Doubler son équipement fait gagner environ 300 m : on avance à chaque essai sans jamais passer. Il n'y a pas de mur : à la limite, le joueur s'effondre et se réveille ramené par les gens du village le plus proche. H s'applique aussi sous terre et à la repousse d'une forêt défrichée, pour qu'aucun contournement ne passe.
- **Pourquoi 20 km** : avec 500 habitants, 50 km laissaient 2 500 km² presque vides ; 20 km gardent les villages à une demi-journée de marche du bourg (×6 : un jour de jeu = 4 h réelles).
- **Ce qui le ferait tomber** : un joueur qui repère la règle. Le prototype M11 le teste avec des testeurs qui cherchent à passer.

---

## 3. Estimations de puissance de calcul

Machine de référence proposée : portable Intel Iris Xe (rendu), RTX série 3000 6 Go (IA), CPU 4 cœurs / 8 threads, 16 Go de RAM.

### 3.1 Par image (30 images/s = 33 ms)

| Poste | Budget | D'où vient le chiffre |
|---|---|---|
| GPU intégré, rendu complet | 22 ms (11 ms de marge) | répartition du choix 5 ; à mesurer par M3 à M5 |
| Bande passante GPU intégré | 68 Go/s théoriques, soit 2,3 Go par image au maximum, partagés avec le CPU [Calculé] | LPDDR4x-4266 sur 128 bits : 4 266 millions de transferts × 16 octets |
| CPU, thread principal | 8 ms | logique et envoi des commandes de rendu |
| CPU, société (500 PNJ) | ≤ 3 ms en moyenne, sur threads de travail | estimation, prototype S5 |
| Un coup de pioche, toutes conséquences | ≤ 2 ms (maillage, collisions, navigation, lumière, stabilité, témoins) | remaillage 74 µs par chunk [Source] : environ 25 chunks par coup |
| Génération d'un chunk de surface | < 1 ms | cible M2 |
| Envoi vers le GPU | 4 Mo par image | file de priorité par distance et regard |

### 3.2 IA sur le GPU dédié (en jeu)

| Poste | Estimation |
|---|---|
| Décisions par seconde réelle, 500 PNJ | 10 à 30 (un plan dure de quelques dizaines de secondes à quelques minutes de jeu) |
| Coût d'une décision, élève de 10 M de paramètres et ~45 jetons | environ 1 milliard d'opérations [Calculé : 2 × paramètres × jetons] |
| Total | moins de 30 milliards d'opérations par seconde, une petite fraction d'une RTX 3060 portable (environ 10 TFLOPS en FP32, estimés pour une fréquence voisine de 1,4 GHz) |
| Verbaliseur (LLM ~2 milliards de paramètres, 4 bits) | ne parle que près du joueur ; débit à mesurer |

### 3.3 Hors jeu

| Poste | Estimation |
|---|---|
| Plan du monde (1,6 million de cellules à 16 m, relief, érosion, rivières) | < 30 s à la création de la partie, sur CPU, déterministe |
| Simulateur sans rendu, avec le décideur de référence | 1 an de jeu = environ 158 millions de décisions [Calculé : 30 par s × 4 h × 365]. En 10 minutes, cela fait 263 000 décisions par seconde ; à 5 µs chacune, environ 1,3 cœur CPU [Calculé]. Tenable. |
| Données du teacher (Gemini) | coût par appel et quota à mesurer au pilote de 100 étiquettes |

---

## 4. Estimations de stockage

### 4.1 En mémoire pendant le jeu

| Contenu | Taille | Calcul |
|---|---|---|
| Voxels à 2 cm chargés autour du joueur (rayon 64 m) | environ 350 Mo pour du terrain, plus les bâtiments du village | 7 850 colonnes × 1,5 chunk de surface × ~29 Ko par chunk (une centaine de briques à palette de 2 à 4 bits + index) [Calculé] |
| Caches dérivés (maillages, collisions, navigation, lumière) | ≤ 1 Go de RAM | budget |
| Maillages et champs côté GPU intégré | ≤ 1 Go (maillages 300 Mo, lumière et eau 64 Mo, matières 100 Mo, images 80 Mo, ombres 32 Mo) | budget du document d'architecture |
| Plan du monde | environ 8 Mo | 1,6 million de cellules à 16 m |
| Résumé de région lu par la société | environ 3 Mo | 100 000 cellules de 64 m × ~32 octets [Calculé] |
| Souvenirs des 500 PNJ | environ 11 Mo | 475 × 300 + 25 × 1 000 = 167 500 souvenirs × 64 octets [Calculé] |
| État social complet (souvenirs, relations, croyances, institutions) | environ 32 Mo | ~64 Ko par PNJ |
| GPU dédié : élève + verbaliseur | ≤ 4 Go sur 6 (élève < 100 Mo, verbaliseur 1,5 à 2,5 Go avec son cache) | estimation |
| **RAM totale du jeu** | **≤ 4 Go** | budget |

### 4.2 La sauvegarde après 100 heures

| Contenu | Taille unitaire | Volume supposé | Total |
|---|---|---|---|
| Plan du monde (recalculable, gardé pour éviter 30 s au chargement) | — | 1 | ~8 Mo |
| Chunks modifiés à la main | 2 à 8 Ko compressés | 5 000 à 50 000 | 20 à 400 Mo |
| Opérations rejouables (fouilles, champs, routes, chantiers) | 32 à 64 octets | 500 000 | 16 à 32 Mo |
| Instances de modules | 16 à 32 octets | 500 000 | 8 à 16 Mo |
| PNJ, mémoire, relations | ~64 Ko | 500 | ~32 Mo |
| Chronique, tuiles de surcharge du lointain | — | — | < 15 Mo |
| **Total** | | | **80 à 500 Mo** ; cible ≤ 500 Mo |

### 4.3 L'installation

Estimation : environ 2 à 3 Go, dont le verbaliseur (~1,2 à 1,5 Go), la bibliothèque de modules voxel (quelques centaines de Mo au plus au rythme de 6 bits par voxel), l'élève (< 100 Mo) et le moteur.

---

## 5. Les points limitants

Classés du plus grave au moins grave. Pour chacun, ce qu'on sait, ce qu'on ne sait pas, et ce qu'on fait si ça casse.

1. **Le 2 cm éditable sur GPU intégré n'a aucun précédent.** Chaque morceau est prouvé séparément, pas leur combinaison. Le plus incertain : le nombre réel de triangles sur des surfaces creusées. Repli connu (anneau 2 cm à 6 m). **Premier prototype à faire.**
2. **La bande passante partagée.** Sur un GPU intégré, le rendu et la simulation CPU se disputent la même mémoire. Le budget de 3 ms de société et de 22 ms de rendu ont été estimés séparément ; ensemble, ils peuvent se gêner. À mesurer en charge réelle (tranche verticale).
3. **La transition abstrait → détaillé.** Quand le joueur arrive, les chantiers et les fouilles résolus « par leur durée » doivent apparaître en voxels sans incohérence. La parade est la décision identique à tous les paliers et les opérations déterministes ; le test est « revenir après 10 ans de jeu et trouver un village cohérent ».
4. **L'élève ne peut pas tenir le rythme du simulateur accéléré, et n'en a pas besoin** (point vérifié avec le fil d'architecture). Le critère « 1 an en moins de 10 minutes » demande environ 263 000 décisions par seconde [Calculé]. C'est tenable avec le décideur de référence (environ 1,3 cœur), et c'est lui que le simulateur utilise pour tester la société sur des années. Avec l'élève, cela ferait environ 263 000 milliards d'opérations par seconde, hors de portée d'une RTX 3060 portable. Mais l'élève n'en a pas besoin : en jeu, il ne prend que 10 à 30 décisions par seconde. Pour son entraînement (boucle DAgger, S8), il tourne sur des déroulés courts, de quelques jours à quelques semaines de jeu, lancés depuis des états de la référence. Un élève plus petit reste une option si le prototype M12 montre que le temps réel coûte trop cher.
5. **Les données d'entraînement n'existent pas.** Aucune étiquette réelle, aucun modèle entraîné. Le défaut le plus grave signalé par les devs : le teacher voit des valeurs trop grossières. L'ordre de travail est fixé (`02` § 9.2) ; le décideur de référence garantit que le jeu marche même si l'élève échoue.
6. **Le volume de contenu.** À 2 cm, modéliser coûte cher, et 111 fonctions de plan demandent des animations. Parade : générateurs, usure par graine, et une tranche verticale limitée (travail, parole, avis, un vote) avant d'élargir.
7. **La croissance de la sauvegarde.** 100 000 chunks modifiés à la main font déjà environ 500 Mo. Si les PNJ creusent beaucoup « à la main » au lieu d'opérations rejouables, la sauvegarde gonfle. Parade : compaction ; règle que les travaux des PNJ restent des opérations.
8. **Les joueurs sans deux GPU.** Votre portable a deux GPU ; la plupart des PC de bureau Steam n'ont que le dédié. Le rendu, dimensionné pour un GPU intégré, n'en prend qu'une petite partie, et l'IA y tourne en calcul asynchrone basse priorité. Sur GPU intégré seul, le décideur de référence prend le relais. À tester (prototype M12).
9. **Les règles Steam.** Vérifié le 8 octobre : la règle de juillet 2025 vise le contenu sexuel explicite ; une romance non explicite entre adultes (D15), même apparentés (D11), présente un risque faible si rien n'est sexuel ni montré, avec la norme de tabou forte par défaut et l'interrupteur `--no-adult-kin-romance` prêt. Reste à rédiger la déclaration du contenu IA généré en direct (le verbaliseur) et de ses garde-fous (O7).

---

## 6. Où critiquer en priorité

Si vous voulez concentrer vos critiques là où elles changent le plus le projet :

1. **Le budget de rendu (choix 5)** : est-ce que vos prototypes ou idées de rendu passent par d'autres chemins que les anneaux et le micro-tracé ? Les sept prototypes du document de rendu servent de grille pour les comparer.
2. **La règle « même décision à tous les paliers » (choix 8)** : c'est elle qui coûte le plus de CPU, et c'est elle qui garantit la cohérence.
3. **L'opération comme unité universelle (choix 2)** : si un système du jeu ne s'exprime pas bien en opérations, c'est là que l'architecture plie.

Les documents de référence (`docs/reference/`) gardent le détail des calculs et toutes les sources citées.
