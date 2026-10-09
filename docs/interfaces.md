# Contrat d'interfaces : un seul jeu, six chantiers

Version 0.4, 8 octobre 2026. Propriétaire : le fil « Construction du moteur ». Ce document fixe ce qui passe d'un chantier à l'autre, pour que le village jouable, les villageois, le moteur et les données d'entraînement s'assemblent **sans conversion manuelle**.

Comment le faire évoluer : un fil qui a besoin d'un changement l'envoie au fil du moteur, qui tranche, met à jour ce fichier (numéro de version, ligne dans le journal en bas) et renvoie la version aux autres fils. On ajoute, on ne renumérote jamais un identifiant déjà publié. Le fil d'architecture relit en cas de doute.

| Chantier | Fil | Dossier dont il est propriétaire | Ce qu'il fournit aux autres |
|---|---|---|---|
| Moteur | Construction du moteur | `emergence/engine/`, `emergence/game/`, ce fichier | cœur C++, formats de voxels, table des matières, contrat d'exécution |
| Village jouable | Village voxelisé jouable | `/mnt/project-files/prototype-village/` | rendu voxel dans le navigateur, format des modules (VXB), mesures sur GPU intégré |
| Villageois | Skins des villageois | `/mnt/project-files/personnages/` | générateur à graine, squelette, vêtements, animations |
| Données d'entraînement | Données d'entraînement du Transformer | `emergence/ai/`, `/mnt/project-files/donnees-transformer/` | contrat PNJ, encodeur de jetons, jeux de données |
| Génération du monde | Génération du monde par graine | `emergence/worldgen/` | chunks générés depuis le plan (strates, grottes, minerais, arbres, routes, plateformes des villages), niveaux de détail |
| Société | Simulation sociale des villages | `emergence/sim/` | simulation sans rendu des 500 PNJ, flux d'événements sociaux |

---

## 1. Unités et repères

| Grandeur | Règle |
|---|---|
| Longueur | mètre dans tous les fichiers échangés ; 1 voxel = 2 cm = 0,02 m |
| Repère du monde (cœur C++, plan, voxels) | x vers l'est, y vers le haut, z vers le nord ; entiers en voxels, origine au coin sud-ouest de la carte, y = 0 au niveau de la mer. Le chunk (cx, cy, cz) couvre les voxels [64·c, 64·c + 64) sur chaque axe ; au niveau de détail `lod`, un voxel mesure 2 cm << lod sur la même grille 64³ |
| Repère Godot et glTF | y vers le haut, droitier : `godot.x = x`, `godot.y = y`, `godot.z = -z` (le nord est −Z, l'avant par défaut de Godot) |
| Personnages (glTF) | 1 unité = 1 m, y en haut, le personnage regarde vers +Z (convention glTF), pieds à y = 0 entre les deux pieds |
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

- **Teinte** : index 0..127 dans une rampe de 128 couleurs propre à la classe. Le terrain généré écrit la teinte 0, sauf la végétation générée (`vine` 29, `leaves` 30, `bark` 31) qui porte l'essence en teinte 0..3 (0 chêne, 1 saule, 2 pin, 3 bouleau ; ordre de `worldgen`) ; les modules et les éditions portent une teinte libre. Les rampes viendront d'un fichier par classe (`engine/data/tints/`, à créer) ; en attendant, le prototype garde ses rampes k-means.
- **Chunk** 64³ voxels (1,28 m), découpé en 8 × 8 × 8 **briques** de 8³ (16 cm). Une brique est uniforme (une seule valeur) ou une palette locale + 1, 2, 4, 8 ou 16 bits par voxel. Index dense : x le plus rapide, puis z, puis y. Référence : `engine/core/world/include/emergence/world/chunk.h`.
- **Modules** (pièces de bâtiment, arbres, objets voxelisés) : format **VXB3**, adopté tel que proposé par le fil du village (`/mnt/project-files/prototype-village/VXB3_proposition.md`, qui fait foi octet par octet). Résumé : fichier gzip, petit-boutiste ; en-tête `"VXB3"`, `schema_version` 1, version de `materials.csv`, drapeaux (bit 0 : section de rampes provisoire), nombre de modules ; par module : nom, origine i32×3 en voxels par rapport au pivot (repère du monde), dimensions u16×3, nombre de briques, puis les briques 8³ dans l'ordre bx, bz, by ; tag 0 vide, 1 uniforme (u16), 2 palette de k ≤ 255 valeurs non vides avec index de 1, 2, 4 ou 8 bits (index 0 = air), 3 brut u16 ×512 ; voxels **x, puis z, puis y** comme `chunk.h` ; crc32 du contenu non compressé à la fin. Le lecteur C++ copie une brique telle quelle dans un chunk.
- **Placement des modules** : fichier d'instances **VXI**, séparé de VXB3. Gzip, petit-boutiste : `"VXI1"`, u16 `schema_version` = 1, u32 nombre d'instances, puis par instance : u8 longueur du nom, nom du module (§ 8), i32×3 position du pivot en voxels du monde, u8 rotation r en quarts de tour autour de +y (sens trigonométrique vu de dessus, de l'est vers le nord, comme Godot), u8 réservé = 0 ; crc32 à la fin. Voxel du monde = pivot + Rot(r) × local, en coordonnées continues. Passage glTF → monde : miroir par le plan du pivot (la cellule z devient −z−1), profondeur complétée à un multiple de 8 avant le miroir, donc `dims.z` est un multiple de 8. Une instance éditée reçoit sa propre copie de briques (copie à l'écriture) ; l'édition est un delta du monde, pas une modification du module.
- **Écriture dans le monde** : toujours par une `Operation` (invariant 4). Une animation ou une action ne modifie jamais un voxel directement (voir § 6).

## 2 bis. Génération du monde

- **Plan du monde** : `engine/core/world/` (fil du moteur). `kWorldGeneratorVersion` = 1 est **figé** depuis le 8 octobre, empreinte de la graine 1 = `6a24a0d52057c0df`. Tout changement de sortie du plan passe à la version 2 et est annoncé au fil de génération, qui refait alors ses empreintes.
- **Chunks du jeu** : `em::wg::WorldGen` (`emergence/worldgen/`, fil de génération), qui lit `WorldPlan` sans le modifier et écrit dans `em::Chunk` par `Chunk::set_brick`. API : `generate(ChunkCoord, Chunk&)`, classement Air / Solid / Mixed / OutOfWorld, niveau de détail, `ground_mm()` et `trees_in()` pour le placement. `ChunkGenerator` du moteur reste comme repli minimal et référence de test.
- Le fil de génération propose ses changements au plan (relief, érosion, sites) au fil du moteur, qui les applique.
- **Exports pour les autres fils** (commande `emergence_sim`, sortie dans `/mnt/project-files/moteur/exports/`) :
  - `geo` → `geography_seed<N>.json` (`schema_version` `"geo-1"`) : graine, version et empreinte du plan, villages (`id` du § 8, `frontier`, `pos_m` = [x est, z nord] en mètres, `height_m`, `resources` indicatives 0..10 dans un rayon de 3 km), `road_km` = [[a, b, km]…].
  - `zone --at <village>` → `zones/zone_<village>.json` (`"zone-1"`) + `_height.u16`, `_top.u8`, `_water.u16` : champ de hauteur de 128 m de côté au pas de 8 cm autour d'un village, hauteurs en voxels au-dessus de `base_voxel_y`, classe de matière du voxel du dessus, niveau d'eau. Le format est décrit dans le JSON. Quand `WorldGen` sera branché, les zones seront refaites avec les plateformes des villages.

## 3. Squelette des personnages

Un seul squelette pour tous les humains, du nourrisson au vieillard : les proportions changent par la longueur des os, jamais par leurs noms ni leur hiérarchie.

- **Noms et hiérarchie** : ceux du profil humanoïde de Godot (`SkeletonProfileHumanoid`), pour que le reciblage des animations soit automatique dans Godot : `Root` > `Hips` > `Spine` > `Chest` > `UpperChest` > `Neck` > `Head` (+ `LeftEye`, `RightEye`, `Jaw`) ; `LeftShoulder` > `LeftUpperArm` > `LeftLowerArm` > `LeftHand` > doigts (`LeftThumbMetacarpal`, `LeftThumbProximal`, `LeftThumbDistal`, `LeftIndexProximal`…`LeftLittleDistal`) ; `LeftUpperLeg` > `LeftLowerLeg` > `LeftFoot` > `LeftToes` ; même chose à droite.
- **Points d'attache** (os supplémentaires, sans poids) : `RightHandProp` et `LeftHandProp` (outil tenu, paume vers l'intérieur, axe du manche sur +Y local), `BackProp` (sac, hotte), `HipProp` (bourse, couteau), `HeadProp` (chapeau rigide). Les outils sont des modules voxel attachés là.
- **Pose de liaison** : bras le long du corps (proposée par le fil des villageois : c'est la pose la plus vue et les voxels y restent alignés aux membres), face à +Z, pieds à y = 0. Le reciblage de Godot passe par les poses de repos, donc une animation faite sur une autre pose se recible sans retouche.
- **Âge** : chaque personnage porte une catégorie d'âge `child`, `teen`, `adult`, `elder` dans sa fiche (§ 5). Le moteur s'en sert pour les règles dures (aucun acte romantique ou sexuel impliquant un enfant ou un adolescent, invariant I7) ; elle n'est jamais déduite de la taille.

## 4. Vêtements

Style tranché (I-2), précisé par Monsieur : **style voxel**, pas voxel strict. La forme est faite de blocs de 2 cm (angles et triangles permis), peints en voxels de 1 cm ; chaque voxel porte un index de palette et un os. Les extras des nœuds `.glb` donnent `voxel_m` (bloc) et `texel_m` ; les LOD 0 et 1 portent une `normalTexture` (biseau par voxel). La source de vérité est une pile de couches de voxels : le corps, puis chaque vêtement ajusté à ce corps. Un vêtement est une **recette de données** (emplacement, type, matière, couleurs, motif, usure, graine) portée par le PNJ ; sa géométrie est recalculée pour le corps qui le porte. Le cœur C++ compose les couches et remaille à la volée (quelques ms), ce qui permet les vêtements déchirés ou brûlés et des niveaux de détail par sous-échantillonnage. Un PNJ change de tenue sans changer de modèle (la fonction `dress` du contrat PNJ en dépend).

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

- Plusieurs vêtements peuvent partager un emplacement (chemise et tunique en `torso`, gilet et tablier en `over`) : chaque recette porte un entier `layer` qui fixe l'ordre de superposition, en plus de `slot`. `underwear` reste libre.
- Chaque vêtement déclare les **zones du corps qu'il couvre** (masque de 16 bits, bit 0 = tête jusqu'à bit 15 = pieds dans l'ordre suivant : tête, cou, torse haut, torse bas, bras haut G/D, avant-bras G/D, mains G/D, bassin, cuisses G/D, mollets G/D, pieds) ; la composition supprime les voxels de corps cachés sous ces zones.
- **Couleur** : le vêtement indique jusqu'à 3 zones teignables ; la fiche du personnage donne la teinture. La matière simulée est la classe `cloth` (33). Les matières de recette (`linen`, `wool`, `velvet`, `oilskin`, `leather`, `knit`, `straw`, `felt`, `metal`) sont des noms de recette ; elles deviendront des classes de `materials.csv` quand la simulation en aura besoin (feu, usure).
- **Tenues** (I-4, tranchée) : une tenue nommée est une liste de recettes de vêtements. Vocabulaire figé, ajout en fin seulement : `everyday`, `work`, `travel`, `festive`, `mourning`, `cold`, `court`, `night`. La simulation choisit la tenue selon l'occasion ; c'est l'argument de `dress(outfit)` et le jeton de garde-robe du fil des données.

## 5. Export des personnages

- **Format** : glTF 2.0 binaire (`.glb`) **par PNJ** : squelette, un maillage par tenue déjà composée (faces cachées supprimées, fusion gloutonne, atlas de couleurs de 128 à 256 px en filtrage au plus proche, un appel de dessin), animations au moins `idle` et `walk`. Dans Godot, changer de tenue = basculer la visibilité d'un `MeshInstance3D` sous le même `Skeleton3D`. Une bibliothèque d'animations commune sur le squelette canonique complète les clips du § 7. Pas de FBX dans les échanges.
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
  "village": "forest_village",
  "outfits": {
    "everyday": [{"slot": "torso", "type": "tunic", "material": "wool", "colors": [[0.4, 0.3, 0.2]], "pattern": "plain", "wear": 0.2, "seed": 77},
                 {"slot": "feet", "type": "shoes", "material": "leather", "seed": 78}],
    "work": [{"slot": "over", "type": "apron", "material": "leather", "seed": 79}]
  }
}
```

- **Budgets** (mesurés par le fil des villageois sur 40 villageois habillés ; à vérifier sur GPU intégré avec 100 PNJ visibles, environ 500 000 triangles au pire) : LOD 0 en blocs de 2 cm jusqu'à 4 m (environ 22 300 triangles), LOD 1 en 4 cm jusqu'à 12 m (5 200), LOD 2 en 8 cm jusqu'à 30 m (1 250), LOD 3 en 16 cm jusqu'à 60 m (260), imposteur au-delà (mesures sur 29 adultes) ; 4 os d'influence par sommet ; textures en palette ou atlas d'au plus 256 × 256 par personnage. Une tenue absente de `outfits` se replie sur `everyday`.

## 6. Contrat PNJ : état, décision, action

> **Remplacé par `catalogue/` (D28, 9 oct. 2026).** Les 112 fonctions de `plan_contract.py` (dont steal, blackmail, deceive) mêlaient gestes, actes sociaux et interprétations ; elles cèdent la place aux 40 gestes paramétrés de `catalogue/data/actions.toml`, à la langue intérieure et aux conditions perceptives de `catalogue/data/conditions.toml`. Une version 2 de ce paragraphe et du § 7 sera **générée** depuis le catalogue (avec les en-têtes C++, D31). `plan_contract.py` reste comme référence historique.

Le contrat est celui du fil des données, version 0.4 (`emergence/ai/CONTRAT_PNJ.md`), adopté tel quel comme **version 1** de cette section. Sa source de vérité exécutable reste `ai/npc_pipeline/plan_contract.py` ; le portage C++ du moteur doit reproduire ses sorties.

- Trois messages : `DecisionRequest`, `Plan` (1 à 6 étapes, chacune avec `until` et `interrupt_if`, 3 conditions au plus), `PlanResult`.
- 20 conditions et 111 fonctions. **Identifiants figés** : l'ordre de déclaration dans `plan_contract.py` au 8 octobre 2026 donne les numéros ; une nouvelle fonction s'ajoute à la fin.
- Le décideur choisit parmi les candidats proposés par le moteur ; il ne modifie rien. Le moteur d'action exécute, surveille les conditions, et transforme tout effet sur le monde en `Operation`.
- `dress(outfit)` est la fonction 112, ajoutée en fin. Encodage des jetons : format `tok-1`, oracle `ai/npc_pipeline/encode.py` (`token_layout.json`, `model_vocab.json`) ; tout changement de `tok-1` passe par ce contrat.

## 7. Actions et animations

Chaque fonction du contrat se joue par une ou plusieurs animations de cette liste. Noms en `snake_case`, une animation par clip glTF, sur le squelette canonique, à 30 images/s.

- **Locomotion en place** (sans déplacement de la racine) avec la vitesse de référence dans les métadonnées du clip ; le moteur déplace le personnage et règle la vitesse de lecture. Les autres clips gardent la racine immobile sauf mention.
- **Événements** dans les clips (marqueurs nommés) : `impact` (le moteur émet l'`Operation` à cet instant : coup de pioche, de hache), `grab` et `release` (objet pris ou lâché), `footstep_l` et `footstep_r` (sons, traces).
- Chaque clip est `loop` ou `once` ; les clips `once` ont une entrée et une sortie compatibles avec `idle`.
- **Métadonnées dans le glTF** (glTF n'a pas d'événements) : `animations[i].extras` = `{"loop": true, "speed_mps": 1.3, "events": [{"name": "impact", "t": 0.62}]}`, temps en secondes depuis le début du clip.
- Les noms de ce tableau font foi. `work` et `talk`, livrés en premier par le générateur, sont des alias provisoires de `kneel_work` et `talk_calm`.

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

`be_intimate` ne se joue jamais à l'écran : `embrace`, puis fondu au noir. Règle D10 (version catalogue) : avec un mineur (âge réel, cru ou apparent), seules les valeurs de `minor_whitelist` du geste `touch` passent (tenir la main, serrer dans ses bras, toucher l'épaule ou la tête, doucement ou en jouant) ; `kiss` et `lean_in` ne se jouent jamais avec un mineur ; les manières romantic et intimate sont refusées.

## 8. Identifiants partagés

| Objet | Identifiant |
|---|---|
| Entité (PNJ, joueur, animal, objet) | entier 32 bits, unique dans une partie, jamais réutilisé |
| Matière | classe 9 bits de `materials.csv` |
| Fonction et condition du contrat PNJ | rang dans `plan_contract.py` (figé, ajout en fin) |
| Vêtement, coiffure, corps de base | chaîne `snake_case` suffixée de sa version (`tunic_wool_v1`) |
| Animation | nom de clip du § 7 |
| Module voxel | chaîne `snake_case` (nom de la pièce dans le kit ou du générateur) |
| Village | `market_town` (centre), `sea_village` (ouest), `mountain_village` (nord), `desert_village` (est), `forest_village` (sud). Anciens noms : `bourg`, `port`, `mine`, `oasis`, `bois` (simulation) ; `town`, `port`, `miners`, `oasis`, `foresters` (`emergence_sim`, accepté en entrée) |
| Lieu abstrait (palier 2) | `village:site`, site ∈ `home:<foyer>`, `tavern`, `square`, `temple`, `market`, `sea`, `saltpans`, `shipyard`, `forest`, `mine`, `smithy`, `quarry`, `workshop`, `well`, `fields`, `bakery`, `march`, `wilds` (ajout en fin). Le moteur rattache chaque site à un bâtiment ou une zone du village |
| Tenue | une des huit clés du § 4 |

## 9. Événements sociaux : simulation → jeu

Flux JSONL, une ligne par événement, `schema_version` `"sim-events-0.1"` (proposé par le fil de la simulation, adopté) :

```json
{"schema_version": "sim-events-0.1", "t_s": 86400, "kind": "wedding", "actors": [1234, 1301], "village": "forest_village", "place": "forest_village:temple", "text_fr": "…", "data": {}}
```

- `t_s` en secondes de jeu ; `actors` = identifiants d'entité (§ 8) ; `village` et `place` = identifiants du § 8.
- `kind` parmi : birth, death, wedding, engagement, elopement, separation, apprenticeship, craft_lost, craft_lost_village, craft_rediscovered, theft_caught, brawl, murder, verdict, exile, election, decree, challenge, embezzlement_exposed, expedition, vanished, record_depth, legend_born, epidemic, epidemic_end, accident, collapse, adoption, orphaned, guild_founded, cult_founded, feud, feud_peace, affair_exposed, festival, robbery, outlaw_band, pardon, famine, famine_relief, migration, blackmail, lie_exposed, rescue. Ajout en fin seulement.
- `text_fr` sert au débogage et n'entre jamais dans l'état. Le texte montré au joueur est produit par le jeu à partir de `kind` et `data`, dans sa langue (anglais pour l'instant).
- Les règles dures valent aussi ici : aucun événement de la famille Tendresse (engagement, wedding, elopement, affair_exposed) avec un acteur `child` ou `teen`.

## 10. Questions ouvertes

| N° | Question | Défaut en attendant | À qui |
|---|---|---|---|
| I-1 | ~~Mise en page de VXB3~~ | tranchée en 0.2 (§ 2) | — |
| I-2 | ~~Style des personnages~~ | tranchée en 0.2 : pseudo-voxels de 1,25 à 1,5 cm (§ 4) | — |
| I-3 | Rampes de teintes par classe en fichiers de données | section de rampes de VXB3 en attendant | moteur |
| I-4 | ~~Vocabulaire des tenues~~ | tranchée en 0.2 : huit clés (§ 4) | — |
| I-5 | Lien entre sites abstraits et bâtiments réels du village | le moteur rattache par type de module | moteur + village + simulation |

## Journal

| Version | Date | Changement |
|---|---|---|
| 0.1 | 2026-10-08 | Première version : repères, voxels et matières (classes 21 à 33 ajoutées pour le kit et les vêtements), squelette humanoïde Godot, emplacements de vêtements, export glTF et fiche JSON, contrat PNJ 0.4 adopté, liste des animations |
| 0.2 | 2026-10-08 | VXB3 adopté (ordre x, z, y ; palette ≤ 255) et fichier d'instances VXI ; génération des chunks confiée à `worldgen`, plan figé en version 1 ; teinte d'essence pour la végétation générée ; pose de liaison bras le long du corps ; personnages en pseudo-voxels composés par couches, un `.glb` par PNJ ; huit tenues ; identifiants de village et lieux abstraits ; flux d'événements sociaux ; exports géographie et zones |
| 0.3 | 2026-10-08 | Teinte 1 = saule ; sens de rotation et miroir de VXI ; budgets des personnages en 4 niveaux mesurés ; plusieurs vêtements par emplacement (`layer`) ; ordre du masque de zones ; matières de recette ; métadonnées des clips dans `extras` ; alias `work` et `talk` ; `dress` = fonction 112, `tok-1` figé |
| 0.4 | 2026-10-08 | Villageois en style voxel : blocs de 2 cm peints en voxels de 1 cm, `voxel_m` et `texel_m` dans les extras, budgets remesurés |
