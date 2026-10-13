# Glossaire

| Terme | Sens dans ce projet |
|---|---|
| Voxel | cube de 2 cm ; ne porte qu'un `VoxelId` de 16 bits |
| VoxelId | classe de matière (9 bits) + teinte (7 bits) |
| Brique de stockage | 8³ voxels (16 cm), uniforme ou à palette locale |
| Micro-brique | 4³ voxels (8 cm), masque de 64 bits tracé dans le pixel shader |
| Chunk | 64³ voxels (1,28 m), unité de génération, de maillage et de sale |
| Région | 32³ chunks, unité de fichier de sauvegarde |
| Plan du monde | carte grossière (16 m) calculée une fois depuis la seed : relief, rivières, biomes, villages, routes, hostilité |
| Opération | enregistrement compact et rejouable d'une modification du monde (forme, outil, matière, graine, perceptibilité) |
| Région sale | zone qu'une opération a touchée ; chaque cache s'y reconstruit |
| Matérialisation paresseuse | transformer en voxels une opération faite hors de la vue, quand le joueur approche |
| Module | asset voxel issu du convertisseur, stocké une fois et instancié |
| Blueprint | liste d'instances de modules qui décrit un bâtiment |
| Chantier par différence | le travail restant est toujours blueprint moins monde |
| Palier | niveau de fidélité de simulation d'un PNJ (0 proche, 1 village du joueur, 2 ailleurs) |
| Référence | décideur à utilités + HTN, sur CPU |
| Élève | Transformer distillé depuis le teacher, sur GPU dédié |
| Teacher | LLM hors jeu (Gemini) qui note des intentions candidates pour produire les données |
| Plan | 1 à 6 appels de fonction avec conditions d'arrêt et d'interruption |
| Cadre (d'acte de parole) | représentation structurée d'une phrase : acte, force, politesse, modalité, contenu |
| Verbaliseur | petit LLM local qui transforme un cadre en phrase ; n'écrit jamais dans l'état |
| Hostilité | champ H(d) = 2^(d / 300 m) dans les marches (3 km autour du cœur habité, 5 km côté montagne), qui alimente les systèmes de survie |
| Cœur habité | zone d'environ 14 × 12 km où vivent les 5 villages |
| Marche | bande de 3 km (5 km côté montagne) entre le cœur habité et le bord de la carte, où H croît |
| Retour | à la limite, le joueur s'effondre et se réveille ramené par les gens du village le plus proche ; jamais de mur invisible |
| Décor de seed | relief non jouable au-delà du bord de la carte, à 128 m puis 512 m, jusqu'à l'horizon |
| Oracle | version Python d'un module, dont la version C++ doit reproduire les sorties |
