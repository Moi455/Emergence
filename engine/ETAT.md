# État du moteur (`engine/`, `game/`) au 8 octobre 2026, fin de session

Fil « Construction du moteur ». Arrêté à la demande de Monsieur (15 h 35) pour le passage sur Claude Code.

## Fait et mesuré

Les mesures viennent du conteneur (4 cœurs x86, rendu logiciel), pas de la machine de référence.

| Étape | Résultat |
|---|---|
| 0.3 CMake, tests, `emergence_sim` | 6 suites ctest vertes (`base`, `world_plan`, `chunks`, `mesh`, `worldgen`, `terrain`) |
| M1 Plan du monde 20 km | 4,2 s ; empreinte graine 1 = `6a24a0d52057c0df`, identique sur 12 compilations gcc/clang ; plan figé en version 1 |
| 0.4 Godot 4.6.1 + GDExtension | godot-cpp `272e7f4a`, classe `EmergenceWorld` |
| M2 Chunks 64³ en briques 8³ | 0,42 ms par chunk (générateur du moteur) ; le jeu utilise désormais `worldgen/` (fil Génération), environ 0,75 ms par chunk sur 4 cœurs |
| M3 Maillage et niveaux de détail | quads de 8 octets avec occlusion aux coins (niveaux 0 à 2) ; 6 anneaux emboîtés (carré de 1,4 km), murs de couture ; chargement complet 12,9 s ; 6,85 M quads autour du bourg (52 Mo), dont 90 % de feuillages lointains ; en marchant, 0,8 s de calcul par pas de 2,56 m, en tâche de fond ; un trou de 30 cm : 43 ms |
| Scène jouable `game/scenes/play.tscn` | marcher, courir, sauter, voler, creuser, poser ; collision Jolt autour du joueur ; shader à extraction de sommets ; `--autotest` creuse 2,6 m (OK) ; captures dans `/mnt/project-files/moteur/captures/jeu_*.png` |
| Contrat `docs/interfaces.md` v0.2 | VXB3 et VXI, pose de liaison, tenues, identifiants de village, événements de la simulation |
| Exports | `emergence_sim geo` et `zone` ; sorties dans `/mnt/project-files/moteur/exports/` |

## Pas fait

- Temps GPU et images par seconde sur l'Iris Xe : la touche H du jeu les affiche.
- Feuillages pleins aux niveaux grossiers : noté par le fil Génération pour la suite sur Claude Code, pas implémenté.
- Éditions visibles seulement au niveau 0 (44 m autour du joueur) ; elles restent en mémoire, sans sauvegarde.
- Bus d'opérations (M6), physique d'effondrement, eau et feu, sauvegarde par deltas.
- Micro-tracé du champ proche.

## Ce que les demandes de Monsieur (15 h 35) changent pour le cœur

1. **Voxels plus gros.** La taille tient dans une constante, `kVoxelMm` = 20 dans `core/world/include/emergence/world/voxel_id.h`. `worldgen` s'en sert aussi (`voxel_mm(lod)`). Pour passer à 4 ou 5 cm, il faut :
   - changer cette constante ;
   - remplacer `kVoxelM` = 0.02, codé en dur dans `gdext/src/emergence_world.cpp`, par une valeur dérivée de la constante ;
   - repasser les empreintes épinglées des chunks ;
   - mettre à jour le § 1 du contrat.

   Le plan du monde, en millimètres, ne bouge pas. Des voxels deux fois plus gros divisent par environ 4 le nombre de quads à surface égale, ce qui aide aussi la contrainte GPU.
2. **Textures sur les voxels.** Elles se font dans le shader, à partir de la classe et de la position du voxel, sans mémoire en plus. Les bits 59 à 63 du quad sont libres pour une variante. La teinte 7 bits des briques n'est pas encore lue par le shader.
3. **Lumière en temps réel (heure, nuages, météo).** La scène actuelle n'a rien de précalculé : soleil et ciel dynamiques, ombres. Le « cache de lumière » prévu en M5 dans l'architecture est à revoir dans ce sens. Le moteur n'a pas de suréchantillonnage.
4. **GPU au minimum.** Le budget à tenir est un nombre de quads et de régions dessinées, à mesurer sur l'Iris Xe. Les réglages sont exposés : nombre d'anneaux, taille des anneaux, occlusion.
5. **Tous les PNJ simulés partout, toute action a une conséquence.** Le cœur doit appliquer les modifications du monde aussi là où personne ne regarde, et les garder.
   - Toute écriture doit passer par le bus d'opérations (M6). Ses deltas doivent s'appliquer à des chunks non chargés et être sauvegardés.
   - Les niveaux grossiers doivent montrer les modifications : un pont détruit doit se voir de loin.
   - Aujourd'hui, `ChunkCache::edit_sphere` ne couvre que le niveau 0, en mémoire.
6. **Pas de mur ni de retour au village en bordure.** Le cœur n'en a pas. Le plan s'arrête au bord de la carte de 20 km, et le décor non voxelisé s'étend au-delà. La difficulté croissante relève de la simulation.
7. **Eau et feu hors voxels, au plus léger.** C'est déjà le choix P18 : l'eau est un champ à part. Puiser devra retirer du volume de ce champ.

## Questions ouvertes pour Monsieur

- Quelle taille de voxel : 4 cm, 5 cm, ou autre ? Elle décide de la constante ci-dessus et du travail des fils Village et Villageois.
- Quelles images par seconde sur l'Iris Xe dans `play.tscn` ? Lancer avec `godot --path game`, puis appuyer sur H.
