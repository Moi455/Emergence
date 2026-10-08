# Contrat d'interfaces : un seul jeu, quatre chantiers

Version 0.1, 8 octobre 2026. Propriétaire : le fil « Construction du moteur ». Ce document fixe ce qui passe d'un chantier à l'autre, pour que le village jouable, les villageois, le moteur et les données d'entraînement s'assemblent **sans conversion manuelle**.

Comment le faire évoluer : un fil qui a besoin d'un changement l'envoie au fil du moteur, qui tranche, met à jour ce fichier (numéro de version, ligne dans le journal en bas) et renvoie la version aux autres fils. On ajoute, on ne renumérote jamais un identifiant déjà publié. Le fil d'architecture relit en cas de doute.

| Chantier | Fil | Dossier dont il est propriétaire | Ce qu'il fournit aux autres |
|---|---|---|---|
| Moteur | Construction du moteur | `emergence/engine/`, `emergence/game/`, ce fichier | cœur C++, formats de voxels, table des matières, contrat d'exécution |
| Village jouable | Village voxelisé jouable | `/mnt/project-files/prototype-village/` | rendu voxel dans le navigateur, format des modules (VXB), mesures sur GPU intégré |
| Villageois | Skins des villageois | `/mnt/project-files/personnages/` | générateur à graine, squelette, vêtements, animations |
| Données d'entraînement | Données d'entraînement du Transformer | `emergence/ai/`, `/mnt/project-files/donnees-transformer/` | contrat PNJ, encodeur de jetons, jeux de données |

---

## 1. Unités et repères

| Grandeur | Règle |
|---|---|
| Longueur | mètre dans tous les fichiers échangés ; 1 voxel = 2 cm = 0,02 m |
| Repère du monde (cœur C++, plan, voxels) | x vers l'est, y vers le haut, z vers le nord ; entiers en voxels, origine au coin sud-ouest de la carte, y = 0 au niveau de la mer |
| Repère Godot et glTF | y vers le haut, droitier : `godot.x = x`, `godot.y = y`, `godot.z = -z` (le nord est −Z, l'avant par défaut de Godot) |
| Personnages (glTF) | 1 unité = 1 m, y en haut, le personnage regarde vers +Z (convention glTF), pieds à y = 0 |
| Temps | secondes de jeu ; 1 jour de jeu = 4 h réelles (P14, proposé) |
| Angles | radians dans les fichiers, degrés seulement dans les documents |

## 2. Voxels, matières, briques

- **VoxelId** sur 16 bits = classe de matière (9 bits) << 7 | teinte (7 bits). `0` = air. Rien d'autre dans le voxel (invariant 4).
- **La table des classes est unique** : `emergence/engine/data/materials.csv` (`schema_version` 1). Les numéros sont figés. Un fil qui a besoin d'une matière demande son ajout au fil du moteur ; il ne crée pas sa propre numérotation. Correspondance avec le prototype du village, qui avait sa propre liste :

| Prototype (VXB2) | Classe canonique |
|---|---|
| plaster | 17 plaster |
| wood | 21 wood_trim |
| woodwear | 22 wood_trim_worn |
| rocktrim | 23 rock_trim |
| brick | 24 brick |
| redbrick | 25 red_brick |
| masonry | 26 rubble_masonry |
| tiles | 18 roof_tile |
| iron | 27 iron |
| glass | 28 glass |
| vine | 29 vine |
| leaves | 30 leaves |
| bark | 31 bark |
| grass | 1 turf |
| dirt | 2 dirt |
| stone | 20 cut_stone |
| cobble | 32 cobblestone |
| gravel | 5 gravel |

- **Teinte** : index 0..127 dans une rampe de 128 couleurs propre à la classe. Le terrain généré écrit la teinte 0 ; seuls les modules et les éditions portent une teinte. Les rampes viendront d'un fichier par classe (`engine/data/tints/`, à créer) ; en attendant, le prototype garde ses rampes k-means.
- **Chunk** 64³ voxels (1,28 m), découpé en 8 × 8 × 8 **briques** de 8³ (16 cm). Une brique est uniforme (une seule valeur) ou une palette locale + 1, 2, 4, 8 ou 16 bits par voxel. Index dense : x le plus rapide, puis z, puis y. Référence : `engine/core/world/include/emergence/world/chunk.h`.
- **Modules** (pièces de bâtiment, arbres, objets voxelisés) : fichier de briques 8³ à palette locale, celui du prototype (VXB2) sert de base. Changements demandés pour la version commune (VXB3) : classes de `materials.csv`, champ `schema_version`, origine du module en voxels dans le repère du monde ci-dessus, et une palette locale qui peut dépasser 15 teintes au lieu d'arrondir à la plus proche. Le fil du village propose la mise en page octet par octet ; le moteur écrit le lecteur C++.
- **Écriture dans le monde** : toujours par une `Operation` (invariant 4). Une animation ou une action ne modifie jamais un voxel directement (voir § 6).

## 3. Squelette des personnages

Un seul squelette pour tous les humains, du nourrisson au vieillard : les proportions changent par la longueur des os, jamais par leurs noms ni leur hiérarchie.

- **Noms et hiérarchie** : ceux du profil humanoïde de Godot (`SkeletonProfileHumanoid`), pour que le reciblage des animations soit automatique dans Godot : `Root` > `Hips` > `Spine` > `Chest` > `UpperChest` > `Neck` > `Head` (+ `LeftEye`, `RightEye`, `Jaw`) ; `LeftShoulder` > `LeftUpperArm` > `LeftLowerArm` > `LeftHand` > doigts (`LeftThumbMetacarpal`, `LeftThumbProximal`, `LeftThumbDistal`, `LeftIndexProximal`…`LeftLittleDistal`) ; `LeftUpperLeg` > `LeftLowerLeg` > `LeftFoot` > `LeftToes` ; même chose à droite.
- **Points d'attache** (os supplémentaires, sans poids) : `RightHandProp` et `LeftHandProp` (outil tenu, paume vers l'intérieur, axe du manche sur +Y local), `BackProp` (sac, hotte), `HipProp` (bourse, couteau), `HeadProp` (chapeau rigide). Les outils sont des modules voxel attachés là.
- **Pose de repos** : T-pose, bras à l'horizontale, face à +Z, pieds à y = 0.
- **Âge** : chaque personnage porte une catégorie d'âge `child`, `teen`, `adult`, `elder` dans sa fiche (§ 5). Le moteur s'en sert pour les règles dures (aucun acte romantique ou sexuel impliquant un enfant ou un adolescent, invariant I7) ; elle n'est jamais déduite de la taille.

## 4. Vêtements

Les vêtements sont des maillages séparés, skinnés sur le même squelette, que le moteur combine à l'exécution. Un PNJ change de tenue sans changer de modèle (la fonction `dress` du contrat PNJ en dépend).

| Emplacement | Exemples | Couche |
|---|---|---|
| `underwear` | chemise de corps, braies | 0 |
| `legs` | chausses, jupe, pantalon | 1 |
| `torso` | chemise, tunique, robe | 2 |
| `over` | gilet, surcot, tablier | 3 |
| `outer` | manteau, cape | 4 |
| `feet` | souliers, bottes, sabots | 1 |
| `hands` | gants | 2 |
| `head` | capuche, coiffe, chapeau | 3 |
| `neck` | foulard, collier | 3 |
| `belt` | ceinture | 4 |
| `back` | hotte, sac (rigide, sur `BackProp`) | 5 |

- Chaque vêtement déclare les **zones du corps qu'il couvre** (masque de 16 bits : tête, cou, torse haut, torse bas, bras haut G/D, avant-bras G/D, mains G/D, bassin, cuisses G/D, mollets G/D, pieds) ; le moteur cache ces zones du corps pour éviter que la peau traverse le tissu.
- Les vêtements portent **les mêmes formes de corps** (blend shapes) que le corps de base, avec les mêmes noms, pour suivre la corpulence.
- **Couleur** : le vêtement indique jusqu'à 3 zones teignables ; la fiche du personnage donne la teinture. La matière simulée est la classe `cloth` (33) ; une matière plus fine (laine, lin, cuir) s'ajoutera à `materials.csv` sur demande.
- Une tenue nommée (travail, fête, deuil, froid, cour) est une liste de vêtements ; le vocabulaire des tenues est partagé avec le fil des données (jeton de garde-robe).

## 5. Export des personnages

- **Format** : glTF 2.0 binaire (`.glb`), un fichier par corps de base, un par vêtement, une bibliothèque d'animations sur le squelette canonique. Pas de FBX dans les échanges.
- **Fiche de personnage** (JSON, `schema_version` 1), produite par le générateur à graine et lue telle quelle par le moteur et par le fil des données :

```json
{
  "schema_version": 1,
  "id": 1234,
  "seed": 987654321,
  "age_category": "adult",
  "age_years": 34,
  "sex": "female",
  "height_m": 1.66,
  "body": {"base": "human_base_v1", "shapes": {"weight": 0.4, "muscle": 0.2}},
  "skin_tone": 0.55,
  "hair": {"style": "braid_long", "color": [0.35, 0.22, 0.12]},
  "face": {"shapes": {"jaw_wide": 0.3}},
  "outfit": [{"garment": "tunic_wool_v1", "dye": [[0.4, 0.3, 0.2]]}, {"garment": "shoes_leather_v1"}]
}
```

- **Budgets** (à mesurer avec le prototype, sur GPU intégré, jusqu'à 100 PNJ visibles) : 6 000 triangles par personnage habillé au LOD 0, 2 000 au LOD 1, 600 au LOD 2, imposteur au-delà de 60 m ; 4 os d'influence par sommet ; textures en palette ou atlas d'au plus 256 × 256 par personnage. Le style visuel (voxelisé ou lisse) est le choix du fil des villageois ; il reste dans ces budgets.

## 6. Contrat PNJ : état, décision, action

Le contrat est celui du fil des données, version 0.4 (`emergence/ai/CONTRAT_PNJ.md`), adopté tel quel comme **version 1** de cette section. Sa source de vérité exécutable reste `ai/npc_pipeline/plan_contract.py` ; le portage C++ du moteur doit reproduire ses sorties.

- Trois messages : `DecisionRequest`, `Plan` (1 à 6 étapes, chacune avec `until` et `interrupt_if`, 3 conditions au plus), `PlanResult`.
- 20 conditions et 111 fonctions. **Identifiants figés** : l'ordre de déclaration dans `plan_contract.py` au 8 octobre 2026 donne les numéros ; une nouvelle fonction s'ajoute à la fin.
- Le décideur choisit parmi les candidats proposés par le moteur ; il ne modifie rien. Le moteur d'action exécute, surveille les conditions, et transforme tout effet sur le monde en `Operation`.
- Ajouts déjà acceptés : `dress(outfit)` (catégorie body) avec un jeton de garde-robe, dès que les tenues du § 4 sont publiées par le fil des villageois.

## 7. Actions et animations

Chaque fonction du contrat se joue par une ou plusieurs animations de cette liste. Noms en `snake_case`, une animation par clip glTF, sur le squelette canonique, à 30 images/s.

- **Locomotion en place** (sans déplacement de la racine) avec la vitesse de référence dans les métadonnées du clip ; le moteur déplace le personnage et règle la vitesse de lecture. Les autres clips gardent la racine immobile sauf mention.
- **Événements** dans les clips (marqueurs nommés) : `impact` (le moteur émet l'`Operation` à cet instant : coup de pioche, de hache), `grab` et `release` (objet pris ou lâché), `footstep_l` et `footstep_r` (sons, traces).
- Chaque clip est `loop` ou `once` ; les clips `once` ont une entrée et une sortie compatibles avec `idle`.

| Famille | Clips à livrer (priorité 1 en gras) | Fonctions servies |
|---|---|---|
| Locomotion | **idle**, **walk**, **run**, sneak, turn_l, turn_r, jump, climb_ladder, swim | go_to, follow, approach, avoid, flee, wander, wait, hide, return_home, chase |
| Corps | **sit_down**, **sit_idle**, **stand_up**, lie_down, **sleep**, get_up, **eat**, **drink** | eat, drink, sleep, rest |
| Travail | **swing_pickaxe**, **swing_axe**, **dig_shovel**, hoe, trowel_place, hammer, **kneel_work**, **carry_idle**, **carry_walk**, saw, draw_water | dig, place, till, plant, harvest, cut, fetch_water, craft, build, repair, tend_crop, start_build, contribute, supply, equip, unequip |
| Objets | **pick_up**, **put_down**, **give**, store_crouch | pick_up, drop, store, take_from, give, steal, conceal, claim, destroy |
| Parole | **talk_calm**, talk_angry, talk_pleading, talk_joyful, **wave**, point, **nod**, **shake_head**, listen | greet, chat, inform, deceive, ask, propose, request, order, accept, refuse, promise, threaten, accuse, apologize, thank, compliment, insult, warn, call_for_help, comfort, forgive, teach, interrogate, bribe, answer, blackmail, negotiate, lobby |
| Vie publique | post_paper, tear_paper, read_paper, raise_hand, address_crowd, write | read, post_notice, tear_down_notice, publish, write_letter, call_vote, vote, campaign, claim_title, contest_claim, endorse, appoint, dismiss, create_title, decree, enforce, summon, delegate, found_group, join_group, leave_group, post_job, hire |
| Tendresse (jamais explicite, fondu au noir) | lean_in, hold_hands, embrace, kiss | flirt, kiss, embrace, be_intimate |
| Conflit | shove, punch, block, grab_restrain, **hit_react**, **fall_down**, die | attack, defend, chase, restrain, expel |
| Soin | kneel_tend, support_walk | heal, assist |
| Attention | look_around, search_bend, listen | observe, search, eavesdrop, investigate |
| Loisirs et rites | dance, dice, tell_story, wrestle_play, fish, pray, mourn | leisure, pray, mourn |
| Engagement | (aucun clip propre : suit l'étape en cours) | accompany, break_commitment, continue |

`be_intimate` ne se joue jamais à l'écran : `embrace`, puis fondu au noir. Le moteur refuse toute fonction de la famille Tendresse si l'un des deux personnages n'a pas `age_category` = `adult` ou `elder`.

## 8. Identifiants partagés

| Objet | Identifiant |
|---|---|
| Entité (PNJ, joueur, animal, objet) | entier 32 bits, unique dans une partie, jamais réutilisé |
| Matière | classe 9 bits de `materials.csv` |
| Fonction et condition du contrat PNJ | rang dans `plan_contract.py` (figé, ajout en fin) |
| Vêtement, coiffure, corps de base | chaîne `snake_case` suffixée de sa version (`tunic_wool_v1`) |
| Animation | nom de clip du § 7 |
| Module voxel | chaîne `snake_case` (nom de la pièce dans le kit ou du générateur) |

## 9. Questions ouvertes

| N° | Question | Défaut en attendant | À qui |
|---|---|---|---|
| I-1 | Mise en page octet par octet de VXB3 | VXB2 du prototype + les quatre changements du § 2 | fil du village |
| I-2 | Style des personnages : voxelisés à 2 cm ou maillages lisses | libre, dans les budgets du § 5 | fil des villageois |
| I-3 | Rampes de teintes par classe en fichiers de données | rampes k-means du prototype | moteur |
| I-4 | Vocabulaire des tenues (travail, fête, deuil, froid, cour…) | les cinq ci-contre | villageois + données |

## Journal

| Version | Date | Changement |
|---|---|---|
| 0.1 | 2026-10-08 | Première version : repères, voxels et matières (classes 21 à 33 ajoutées pour le kit et les vêtements), squelette humanoïde Godot, emplacements de vêtements, export glTF et fiche JSON, contrat PNJ 0.4 adopté, liste des animations |
