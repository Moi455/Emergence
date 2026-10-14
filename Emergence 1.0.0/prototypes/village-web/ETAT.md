# État du fil « Village voxelisé jouable » — 9 octobre 2026

Fil arrêté à la demande de Monsieur : il termine son chantier et n'en ouvre pas d'autre. Le
détail technique du rendu est dans **RENDU.md**, le mode d'emploi dans **README.md**.

## Fait
- Le MegaKit Quaternius voxelisé par le convertisseur des devs, en **voxels de 10 cm** (5 cm
  disponibles avec `?vs=0.05`). Format VXB3 (`jeu/world.bin`) et plan VXI1 (`jeu/village.vxi`).
- Une page jouable dans le navigateur : https://claude.ai/artifact/7a6jR7fZHyJAh3shh4uToq.
  Marche, vol, destruction, effondrement local et par bâtiment entier, étang, villageois animés
  du fil d'intégration, braziers, cycle jour/nuit. Elle s'ouvre à l'heure dorée.
- Le rendu refait de zéro, puis repris pour viser les quatre images de référence :
  - **couleur par voxel et par pierre** : chaque pierre a sa teinte, posée en assises décalées ;
    mousse sur la pierre, les tuiles et le vieux bois là où le ciel tombe et où l'humidité reste ;
    crasse dans les recoins ; fenêtres éclairées de l'intérieur dès la fin d'après-midi ;
  - **lumière** : soleil rasant chaud, rayons de soleil qui passent entre les toits et les arbres,
    feuillage traversé par la lumière à contre-jour, étalonnage ombres froides et lumières
    chaudes, ciel bleu au-dessus d'un horizon doré ;
  - **prairie** : touffes d'herbe et fleurs (boutons d'or, pâquerettes) jusqu'à 20 m, prairies
    alternant herbe grasse et herbe sèche à l'échelle du mètre.
  Rien de tout cela n'est une texture bitmap, ni n'est stocké : tout est décidé par voxel, à
  partir de la graine.
- Un bug de terrain trouvé en route : le sol proche était maillé à 0,625 voxel par cellule, soit
  2,5 fois trop de surfaces. Corrigé.

## Réponse aux points de Monsieur sur le rendu
| Demande | État |
|---|---|
| Lumière selon l'heure, les nuages, la météo, en temps réel | **Oui.** Aucune lumière stockée. Seul ce que chaque point voit du ciel est précalculé (géométrie). Ciel et soleil recalculés à chaque image. La météo n'est pas branchée ; quand elle changera le ciel, l'éclairage suivra seul. |
| Pas d'upscaling | **Aucun.** |
| GPU au minimum | **iGPU visé**, GPU dédié pas nécessaire. |
| Voxels plus gros | **10 cm**, la taille de Teardown. |
| Textures | Couleur par voxel plutôt que bitmap, voir l'écart ci-dessous. |
| Eau et feu au plus léger | Pas de voxels. Eau : surface analytique. Feu : lumières et cubes émissifs. |

## Mesuré
Machine de build sans GPU : les images/s n'y valent rien, le reste est juste.

| | |
|---|---|
| Téléchargement / chargement | 378 ko / 2,4 s |
| Mémoire voxels CPU | 1,2 Mo |
| Mémoire GPU | 190 Mo, dont 160 de maillages (l'herbe en compte une quarantaine) et 0,8 de grille de ciel |
| Triangles | 5,5 à 6,1 M selon la vue, dont l'herbe +0,6 M ; ~300 appels de dessin |
| Rayons de soleil | une passe au quart de la résolution, 32 lectures par pixel, désactivée quand le soleil est haut ou hors champ |
| Couleur par voxel, mousse, crasse | une vingtaine d'opérations par pixel, zéro octet |
| Précalcul hors terrain | 4,5 s |
| Remaillage après destruction | 180 à 200 ms pour une maison entière, hors boucle de rendu |

## Écart restant avec les images de référence — honnêtement
Les captures du dossier `captures/` (`v3_contrejour.png`, `v3_village_haut.png`,
`v3_prairie.png`) sont à comparer avec les images de Monsieur. **La lumière et la palette sont
maintenant dans la même famille. Le niveau, lui, n'y est pas encore**, et l'écart tient surtout au
contenu, pas au moteur :

1. **La densité de contenu — le plus gros écart.** Les images ont des buissons, du lierre sur les
   murs, des conifères et des bouleaux, des tas de bois, des tonneaux, du linge, des lanternes,
   des clôtures partout, des rochers, une rivière, une cascade, des falaises et un château. Le
   village n'a que les 47 pièces du MegaKit et 4 arbres procéduraux.
2. **Les modèles sources.** Les murs des images montrent des pierres de formes différentes, des
   poutres sculptées, des toits de bardeaux irréguliers. Les pièces du MegaKit sont lisses et
   presque unies : la couleur par voxel que j'ajoute dans le shader ne peut pas inventer la
   forme d'une pierre.
3. **La lumière indirecte colorée.** Dans les images, le mur à l'ombre reçoit le reflet doré du
   sol éclairé. Nous n'avons que la lumière du ciel. Une version à bas coût existe (faire porter
   à la grille de 2 m une couleur de rebond, mise à jour par morceaux), mais je ne l'ai pas
   faite.
4. **Les personnages.** La villageoise de référence a un visage presque photographique, avec des
   voxels de 5 mm environ. Nos villageois sont à 1,25 cm avec des visages simples.
5. **L'effet photographique** (profondeur de champ, éclairage global parfait) : ces images sont
   générées par IA. Une partie est atteignable en option (flou de profondeur), une partie ne
   l'est pas en temps réel sur un iGPU.

## Outils externes qu'il faudrait pour atteindre ce niveau
- **Gratuits, sans accord nécessaire** : les packs CC0 de Quaternius (Stylized Nature MegaKit,
  Ultimate Nature, Medieval Weapons, Fantasy Props) et de Kenney, voxelisés tels quels par notre
  convertisseur. Ils couvrent la végétation, les rochers et une bonne partie des accessoires. Les
  textures CC0 de Poly Haven et ambientCG peuvent être projetées au moment de la voxelisation
  pour donner aux pierres et au bois une vraie variation.
- **Payants au-delà d'un quota gratuit, il faut votre accord** : **Meshy AI** (ou Tripo, Rodin)
  pour générer depuis un texte ou une image les pièces que les packs n'ont pas, avec leurs
  textures : puits, pont de pierre, château, lanternes, enseignes, maisons à colombages sur
  mesure. Leur sortie (glTF texturé) passe directement dans notre convertisseur. Je n'ai rien
  appelé.
- **Pour les visages des villageois** : des têtes texturées haute résolution (Meshy, ou
  MakeHuman et MB-Lab, gratuits) voxelisées autour de 5 mm, seulement pour la tête. C'est le
  domaine du fil des skins.
- **Pas d'outil à acheter pour le relief** (falaises, rivière, montagnes) : c'est le générateur
  de monde.

## Pas fait
- Grille de ciel non remise à jour après une destruction (percer un mur n'éclaire pas encore
  l'intérieur ; la correction est locale).
- Une seule cascade d'ombres ; pas de lumière indirecte colorée.
- Eau ni prélevable ni coulante (Monsieur veut qu'en prendre en retire une quantité).
- Feu sans propagation ; pas de météo ; maisons vides à l'intérieur.
- L'herbe s'arrête net à 20 m (limite visible en prairie, à adoucir).
- Images/s réelles sur l'iGPU de Monsieur non mesurées.

## Questions ouvertes pour Monsieur
1. **Voxels de 10 cm ou 5 cm** (`?vs=0.05`) ? Je recommande 10 cm.
2. **Accord pour Meshy AI** (ou équivalent payant) pour les pièces sur mesure, une fois les packs
   CC0 gratuits épuisés ?
3. **Images/s** sur votre machine : touche **B** dans la page.

## Pour la suite sur Claude Code
- À porter dans le cœur C++ : le PRT d'ordre 1 au sommet, la grille de ciel, la projection du ciel
  en harmoniques sphériques, la couleur par voxel (mêmes règles, calculées au voxeliseur plutôt
  que dans le shader), les rayons de soleil, VXB3 avec la taille de voxel dans l'en-tête.
- À porter dans `tools/voxelizer` : le remplissage des murs ouverts, la projection de textures
  CC0, le vieillissement par voxel.
- Tout est dans `/mnt/project-files/prototype-village/` : `jeu/`, `outils/`, `captures/`,
  `RENDU.md`, `README.md`, ce fichier.
