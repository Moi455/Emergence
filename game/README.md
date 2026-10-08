# game : projet Godot 4.6

Hôte du jeu : éditeur, interface, audio, entrées, export Steam. Le cœur C++ (`engine/`) y est chargé comme GDExtension (`emergence.gdextension`, bibliothèque dans `bin/`, construite par `engine/gdext`).

- `scenes/main.tscn` : génère le plan du monde depuis la graine et affiche l'empreinte, les temps et les villages (test de bout en bout de l'étape 0.4).
- `scenes/terrain_view.tscn` : terrain de voxels de 2 cm maillé (greedy) autour d'un village. Arguments après `--` : `--site town|port|miners|oasis|foresters`, `--seed N`, `--shot fichier.png`.

Physique : Jolt (réglage du projet). Le rendu définitif des voxels passera par le RenderingDevice (extraction de sommets, quads de 8 octets) ; la capture actuelle déplie les quads en triangles.
