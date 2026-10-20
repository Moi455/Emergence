# Le monde physique voxel en Rust : compréhension et plan (20 oct. 2026)

Document de travail pour DISCUTER avec Monsieur avant de coder. Rien ici n'est décidé tant qu'il n'a pas répondu (voir § 6).

## 1. Ce que Monsieur veut (ses mots, regroupés)

- **Style** : « pixel art de précision » avec une gestion des lumières particulièrement soignée ; médiéval fantaisie ultra réaliste, cosy, surtout pas Minecraft. Références : `Map/Image_Style_Jeu.jpg`, `style_type_du_monde.png`, `maison_type.png`, `PNJ_type.png`, `bon pierre.png` (bon), `pas bon chaux.png` (mauvais).
- **Voxels** de 5 cm, MAIS « les voxels n'ont qu'un intérêt pratique » : physique, construction paramétrique, esthétique pixel art. Chaque voxel a une **texture** : en plus de sa couleur, des propriétés qui changent sa réaction à la lumière (comme dans le générateur d'arbres). **Aucun chanfrein** entre voxels (le défaut de la maison de référence : effet mosaïque) : un bois doit paraître UN seul bois.
- **Sous-entités paramétriques** : le monde est fait d'entités générées par graine ou modèle paramétrique (une table, une maison, un arbre), elles-mêmes faites de voxels (physique + style). Avec la baguette et le sort qui convient, des bûches deviennent une table : l'opération agit sur l'ENTITÉ paramétrique, pas voxel par voxel.
- **Terre** : se creuse par voxels, trous plus ou moins irréguliers, grâce aux baguettes (faire disparaître, transformer…). Le sol, bien que voxel, est **maillé en surface** pour être lisse, surtout sur les pentes ; si on creuse, on tombe sur les voxels.
- **Herbe et fleurs** : ultra réalistes, PAS en voxels.
- **Arbres** : le générateur est validé pour le style. **Maisons** : « pas trop mal », mais fleurs et arbres autour sont nuls.
- **Eau** : simulée physiquement (répartition par gravité, obstacles, pas les turbulences), rendu photographique ultra réaliste. Un travail existe déjà (`engine/em_water`, rendu de référence `web-ocean`).
- **Relief** : très vallonné, montagneux, recoins, cascades, très riche.
- **Technique** : tout en **Rust**, orienté objet ; **moins de 25 % de la carte graphique** ; soin particulier à la lumière, aux ombres, aux textures.
- **Méthode** : phase de définition du style avec des aperçus réguliers, beaucoup de discussion.

## 2. Ce qui existe (inventaire vérifié)

| Élément | Où | État / limite |
|---|---|---|
| Générateur d'arbres | `Map/voxel_tree.py` (Python, 65 Ko) | Validé pour le style. 608 032 voxels pour un chêne de 14 m, 2,8 s ; squelette (croissance, pipe model), feuillage en amas, palette ≤ 255 couleurs, ombrage « cuit ». À porter en Rust, paramétrique, sans stocker 600 000 voxels par arbre. |
| Arbustes | `Map/voxel_bush.py` | Même moteur (fleurs, topiaire). |
| Générateur de maison | `générateurs de voxels/` (JS + démo Three.js) | Grille dense de ~1 M voxels par maison, maillage naïf 1 à 1,5 M triangles (inutilisable) ; chanfreins ; décor autour à jeter. À refaire en plan paramétrique + rastérisation paresseuse. |
| Architecture d'un « nouveau monde » | `Map/ARCHITECTURE.md` + 2 en-têtes C++ | Bonne base de pensée : 20 × 20 km, chunk 64³ (3,2 m), vérité = graine + deltas par région + journal d'opérations, eau en champ creux (25 cm), assemblages. Recoupe ce qu'on a déjà fait côté PNJ (bus d'opérations T16, EntityStore T15). |
| Eau physique | `engine/em_water` (Rust, 15 tests) | Saint-Venant inertiel + Manning, conservation exacte, barrages OK. **Trop lent avec 8 sources** (plus lent que le temps réel : nappes de dizaines de milliers de cellules). |
| Rendu d'océan | `web-ocean-main` (WebGPU, MIT) | Shaders WGSL excellents : FFT, atmosphère de Hillaire, éclats solaires, mousse, bloom, tonemapping AgX. Océan ouvert seulement, 6 à 8 ms sur une RTX 5070 Ti. **Les WGSL se réutilisent tels quels dans une appli Rust `wgpu`.** |
| Ancien moteur de monde | `engine/core/{world,mesh}`, `worldgen/`, `game/` (C++/Godot) | Chunks 64³ en briques 8³, quads de 8 octets, 6 anneaux de LOD : à remplacer ou à porter. |
| Machine | Quadro RTX 3000, 6 Go (Turing, 5 TFLOPS environ) | Vulkan OK (il faut désigner son pilote, sinon le chargeur ne liste que l'Intel). Budget < 25 % = environ **4 ms par image à 60 i/s** : très serré pour cette ambition. |
| Rust | installé (rustup, 1.99) | OK. |

## 3. Les idées d'architecture que je propose (à discuter)

**Quatre couches de matière, pas une.**
1. **Terrain** : champ de voxels 5 cm (matière + densité), stocké creux (palette par brique 8³), généré à la demande depuis la graine, avec des deltas persistants. Sa SURFACE est maillée en « peau » lisse (surface nets sur la densité) avec mélange de matières par triplanaire ; les zones creusées montrent des faces voxel. LOD générés depuis la recette, pas par réduction.
2. **Entités paramétriques** (maisons, meubles, arbres, rochers, props) : une **recette + graine** (« Assembly » à parties distinctes : fondations, murs, charpente, toit, ouvertures, mobilier). Elles sont rastérisées en voxels À LA DEMANDE par chunk et par LOD, jamais stockées entières. Les sorts agissent sur la recette (bûches → table).
3. **Végétation fine non voxel** : herbe, fleurs, mousse, lierre en instances GPU (vent, LOD, masques de densité issus de l'écologie), enlevées là où on creuse.
4. **Eau** : champ physique séparé (cellules creuses), couplé aux voxels (obstacles, barrages, creusement) ; rendu photographique à part.

**Pas de chanfrein, une seule matière.** Le matériau est évalué dans le shader en coordonnées MONDE (bruit 3D continu, fibres, veines, usure, humidité, mousse), donc le motif traverse les limites de voxels : un bois reste un bois. Chaque matière fournit des propriétés (albédo et sa variation, rugosité, relief, translucidité des feuilles, émission). Les arêtes de voxels restent nettes (pixel art de précision) mais sans biseau.

**Lumière (là où se joue le style)** : soleil et ciel de Hillaire (réutiliser `sky.js`), ombres en cascades stables, occlusion ambiante et lumière indirecte tirées directement de la grille voxel (lancer de rayons dans une grille d'occupation autour du joueur : peu coûteux), brume volumétrique et rayons de soleil, lumières ponctuelles (feux, torches) ombrées par traversée voxel, bloom + AgX. Tout avec un étalonnage par niveaux de qualité pour tenir 25 %.

**Hôte** : une application Rust autonome (`wgpu` + `winit`) pour le monde, avec un banc de captures d'écran (PNG) pour vous montrer des aperçus sans dépendre d'une fenêtre. Le moteur des PNJ (C++) se branche par des interfaces déjà prévues (`Applier` du bus d'opérations, `SpaceQuery`, `NavigationQuery`) via une interface C.

## 4. Plan en phases (chaque phase se termine par des aperçus et vos retours)

- **Phase 0, laboratoire de style (d'abord, avant tout moteur)** : un visualiseur Rust minimal qui rend (a) UN arbre de votre générateur avec matières par voxel et lumière, (b) un morceau de terrain lisse + herbe + fleurs, (c) un plan d'eau avec le rendu de `web-ocean`, (d) UN mur de pierre et UNE poutre sans chanfrein. Itérations rapides avec vous jusqu'à ce que le style soit validé. Mesure du coût GPU dès cette phase (le budget de 25 % décide de la suite).
- **Phase 1, noyau voxel** : stockage creux, génération déterministe du relief (montagnes, vallées, rivières, cascades), maillage de peau, LOD, flux de chargement, deltas et journal.
- **Phase 2, pipeline de lumière complet** (ombres, atmosphère, indirect, brume, post-traitement, TAA), sous budget.
- **Phase 3, générateurs paramétriques** : arbres et arbustes (port Rust), maisons et décors par recettes, assemblages et stabilité.
- **Phase 4, eau** : solveur repensé (GPU ou hiérarchique) + rendu.
- **Phase 5, destruction et construction** : opérations de baguettes, effondrements, débris, entités mobiles.
- **Phase 6, vie du monde** : écologie (herbe, fleurs, forêts), villages, chemins.
- **Phase 7, branchement au moteur des PNJ** (perception, navigation, opérations) et animations.

## 5. Risques que je vois (honnêtes)

1. **Budget GPU** : 25 % d'une Quadro RTX 3000, soit environ 4 ms/image à 60 i/s, pour relief + forêt + eau photographique + lumière soignée. Plausible seulement avec un étalonnage agressif (résolution interne, effets à demi-résolution, amortis dans le temps). À MESURER en phase 0.
2. **Eau physique** : le solveur actuel est trop lent ; il faut une autre architecture (zones actives bornées, bassins analytiques au loin, éventuellement GPU).
3. **Qualité du style** : c'est subjectif ; d'où la phase 0 avec vos retours.
4. **Deux langages** : monde en Rust, PNJ en C++. Frontière à bien dessiner (interfaces C).
5. **Beaucoup de choses à fusionner** avec ce qui existe côté PNJ (opérations, entités).

## 6. Questions pour Monsieur

Voir le message de présentation (hôte du rendu, définition du budget 25 %, peau de terrain et creusement, sens exact du « pixel art » sur les surfaces, textures procédurales ou bitmap, sorte de baguettes, taille du monde chargé, animations/UI).
