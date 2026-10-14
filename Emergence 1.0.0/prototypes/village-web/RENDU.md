# Le rendu : ce qui est précalculé, ce qui ne l'est pas

Fil « Village voxelisé jouable », 9 octobre 2026. Réponse à la demande de réfléchir
sérieusement au rendu plutôt que d'afficher quelque chose.

## 1. Le diagnostic

La première version était moche pour trois raisons, dans cet ordre d'importance :

1. **L'éclairage était faux, pas absent.** Le terme ambiant oubliait le `1/π` de la
   loi de Lambert : toute la lumière du ciel arrivait 3,14 fois trop forte, ce qui
   écrase le contraste et donne ce gris-lilas délavé. Un rendu trop clair et sans
   contraste paraît toujours plat, quelle que soit la géométrie.
2. **Il n'y avait pas de lumière indirecte.** Une façade à l'ombre recevait la même
   quantité de ciel qu'un toit en plein air. Les intérieurs étaient donc aussi
   lumineux que la rue, et rien ne séparait visuellement un volume d'un autre.
3. **Les voxels étaient trop fins (2 cm).** À 2 cm, à dix mètres, un voxel fait moins
   d'un pixel : on ne voit plus de voxels, on voit du bruit. Le charme du voxel vient
   de la lisibilité de la maille.

**Les textures ne sont pas le problème.** C'est contre-intuitif, donc je l'ai vérifié
plutôt que de l'affirmer : Teardown, qui est la référence du voxel destructible,
**n'utilise aucune texture bitmap**. Toute sa matière vient de propriétés par
matériau (rugosité, métallicité, émission), d'une occlusion du ciel calculée à
l'exécution et d'un post-traitement soigné. Ce qu'on prend pour une texture, c'est
presque toujours de la lumière.

## 2. Les techniques étudiées, et ce qu'on en garde

Vous citiez light baking, voxel lighting, probes, irradiance, PRT. Je les ai prises
une par une, avec notre contrainte propre : **le monde est destructible et il y a un
cycle jour/nuit**. C'est ce qui élimine la moitié des candidats.

| Technique | Verdict | Pourquoi |
|---|---|---|
| **Lightmaps** (éclairage cuit en texture) | **Rejeté** | Une lightmap est valable pour une position du soleil et une géométrie. Nous changeons les deux en permanence. Recuire après chaque trou coûterait des secondes. |
| **PRT d'ordre 1** (transfert précalculé) | **Retenu, c'est la base du moteur** | On ne cuit pas la lumière, on cuit la **visibilité** : combien de ciel chaque sommet voit, et dans quelle direction (normale coudée). C'est indépendant de l'heure. Le ciel change chaque image, la surface répond par un produit scalaire. |
| **Probes / volume d'irradiance (DDGI)** | **Retenu en version dégénérée** | Une grille de probes complète demande du lancer de rayons à l'exécution. Nous gardons une grille 3D de 2 m qui ne stocke **qu'un scalaire** : la part de ciel qui atteint ce point du village. 1 octet par cellule au lieu de 9 coefficients. |
| **Voxel cone tracing (VXGI)** | **Rejeté** | Plusieurs millisecondes par image sur GPU dédié haut de gamme, et une pyramide de mips à reconstruire à chaque destruction. Hors budget iGPU. |
| **Ombres : shadow map** | **Retenu** | Une carte 2048² pour le soleil. C'est la seule partie vraiment dynamique, et elle coûte 16 Mo et un passage géométrique. |
| **Reprojection temporelle (TAA)** | **Candidat, pas encore fait** | C'est le grand levier de Teardown : il étale un effet bruité sur 4 images. ~0,3 ms. Mais il traîne sur la destruction. À évaluer une fois le reste stable. |
| **Upscaling (FSR/DLSS-like)** | **Rejeté, vous aviez raison** | Un upscaler interpole : il arrondit exactement l'arête de voxel qui fait le style. Teardown n'en utilise aucun. On garde un simple curseur de résolution, choisi par le joueur. |
| **Textures bitmap** | **Rejeté** | Coût en VRAM et en streaming, et Teardown prouve que ce n'est pas nécessaire. Remplacé par un grain procédural (~10 opérations) et un biseau sur chaque arête de voxel. |

## 3. Ce que ça donne concrètement

Le travail coûteux est sorti de la boucle de rendu de trois façons :

**(a) Au maillage, une fois par module.** Chaque sommet emporte deux choses calculées
dans un worker : son **ouverture au ciel** (occupation locale floutée trois fois, ce
qui donne une occlusion à grande échelle) et sa **normale coudée**, la direction
moyenne d'où le ciel lui arrive. Coût mémoire : **zéro octet supplémentaire**, les
deux tiennent dans les 16 octets du sommet qui existait déjà.

**(b) Une fois au chargement, pour le village.** Une grille 3D de 2 m, un octet par
cellule, remplie par propagation depuis le ciel ouvert (14 passes). C'est elle qui
rend les intérieurs sombres et les ruelles fraîches sans aucun lancer de rayon.

**(c) Chaque image, sur le CPU, pour trois fois rien.** Le ciel analytique est projeté
sur 4 coefficients d'harmoniques sphériques via 160 directions de Fibonacci. C'est
quelques microsecondes de CPU, et ça remplace l'échantillonnage du ciel par pixel.

L'irradiance reçue par une surface devient alors une seule formule dans le shader :

```
E = (0.886227·L0 + 1.023328·(L1 · b)) / π      ×  AO cuit  ×  ciel du village
```

Rien n'est échantillonné, rien n'est tracé. Le cycle jour/nuit est gratuit : seuls les
4 coefficients changent.

**La destruction ne casse rien.** C'est le point qui éliminait les lightmaps : ici,
creuser un trou ne demande que de remailler le module touché, et le PRT se recalcule
avec le maillage, dans le worker. La grille de ciel du village, elle, n'est pas mise à
jour à chaud — un trou dans un mur n'éclaire pas encore l'intérieur. C'est la
prochaine amélioration, et elle est locale : il suffit de relancer la propagation sur
la boîte touchée.

## 3 bis. Ce qui remplace la texture, et les rayons de soleil (ajouté après les images de référence)

Les images de référence de Monsieur montrent ce que « texture » veut dire dans un monde en
voxels : **chaque voxel et chaque pierre a sa propre teinte**. C'est donc décidé par voxel, dans le
shader, à partir de la position du voxel, sans rien stocker :

- une teinte par voxel, et une teinte par **pierre**, les pierres étant des blocs de 3 × 2 voxels
  posés en assises décalées ;
- de la **mousse** sur la pierre, les tuiles et le vieux bois, là où la face regarde le ciel et
  là où l'occlusion dit que l'humidité reste ;
- de la **crasse** dans les recoins, d'après la même occlusion ;
- des **fenêtres éclairées** de l'intérieur à partir de la fin d'après-midi ;
- des **prairies** alternant herbe grasse et herbe sèche à l'échelle du mètre, des touffes
  d'herbe et des fleurs dans les 20 m autour de la caméra.

Coût : une vingtaine d'opérations par pixel, zéro octet. Dans le moteur cible, ces règles iront
plutôt dans le voxeliseur, qui écrira directement la bonne teinte dans chaque voxel.

**Rayons de soleil.** Le ciel s'écrit dans l'image avec une marque qui le distingue de la matière.
Une passe au quart de la résolution part de chaque pixel vers le soleil et ramasse le ciel
rencontré : là où un toit, un tronc ou des feuilles le cachent, le rayon est coupé, ce qui dessine
les faisceaux. 32 lectures par pixel, désactivée quand le soleil est haut ou hors du champ.
Le feuillage, lui, laisse passer la lumière quand on regarde vers le soleil.

## 4. Les 1 Go que vous autorisez

Nous n'en utilisons presque rien, et c'est voulu. Le monde est déterministe : tout ce
qui est précalculé peut être **recalculé au chargement en quelques secondes** plutôt
que stocké. Le budget de données reste donc disponible pour ce qui ne se recalcule
pas : les modules voxelisés, les personnages, les deltas de sauvegarde.

## 5. Eau et feu

Vous avez raison, ni l'un ni l'autre en voxels.

- **L'eau** est déjà une surface analytique : un plan avec un shader de vagues, une
  réfraction du ciel et une atténuation en profondeur. Elle ne coûte qu'un draw call.
- **Le feu** n'est pas encore fait. Il ne sera pas voxelisé non plus : des particules
  additives pour les flammes, plus une lumière ponctuelle animée injectée dans
  l'éclairage. Le voxel ne servira qu'à dire **quelle matière brûle** et à la retirer,
  ce qui est déjà la mécanique de destruction.

## 6. Ce qui reste à faire

1. Mise à jour locale de la grille de ciel après une destruction.
2. Cascades d'ombres (une seule carte pour tout le village limite la finesse).
3. Reprojection temporelle, si la mesure sur votre machine le justifie.
4. Une lumière indirecte colorée à bas coût : faire porter à la grille de 2 m une couleur de
   rebond, mise à jour par morceaux.
5. Le feu qui se propage.
