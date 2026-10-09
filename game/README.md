# game : projet Godot 4.6

Hôte du jeu : éditeur, interface, audio, entrées, export Steam. Le cœur C++ (`engine/`) y est chargé comme GDExtension (`emergence.gdextension`, bibliothèque dans `bin/`, construite par `engine/gdext`).

- `scenes/play.tscn` (scène principale) : le jeu. Terrain du monde complet en 6 anneaux de détail autour du joueur (2 cm près de soi, 64 cm à 700 m), chargé en tâche de fond. Souris pour regarder (clic pour capturer, Échap pour libérer), ZQSD/WASD, Maj pour courir, Espace pour sauter, F pour voler (Espace et C pour monter et descendre), clic gauche pour creuser, clic droit pour poser de la terre, 1 à 4 pour la taille de l'outil, H pour le panneau (images par seconde, quads), L pour les ombres. Arguments après `--` : `--site market_town|sea_village|mountain_village|desert_village|forest_village`, `--seed N`, `--shot fichier.png`, `--view high`, `--autotest`.
- `scenes/main.tscn` : génère le plan du monde depuis la graine et affiche l'empreinte, les temps et les villages (test de bout en bout de l'étape 0.4).
- `scenes/terrain_view.tscn` : terrain de voxels de 2 cm maillé (greedy) autour d'un village. Arguments après `--` : `--site town|port|miners|oasis|foresters`, `--seed N`, `--shot fichier.png`.

Physique : Jolt (réglage du projet) ; le sol du joueur est un maillage de collision refait autour de lui à chaque chunk franchi ou à chaque modification. Rendu du terrain : `shaders/terrain_quads.gdshader` lit les quads de 8 octets d'une texture par région (extraction de sommets, un maillage d'index partagé). `terrain_view.tscn` déplie encore les quads en triangles, pour le débogage.
