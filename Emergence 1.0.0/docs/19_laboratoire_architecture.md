# Laboratoire de style du monde physique : architecture (20 oct. 2026)

Suite de `docs/18_monde_physique_plan.md` (validé par Monsieur), après ses décisions fermes du 20 octobre 2026 (rappelées en § 0.2). Ce document est le plan d'architecture du **laboratoire de style**, qui est le **vrai début du moteur du monde** en Rust : les solutions retenues ici (stockage, opérations, rendu, lumière) sont celles du jeu, pas un essai jetable.

Annexes :
- `docs/19a_formats_et_interfaces.md` : formats binaires (`.vxm`, paquet `EMPK`, charges utiles des opérations), dispositions GPU, fichiers de données, interface C vers le moteur des PNJ ;
- `docs/19b_taches_laboratoire.md` : les tâches L01 à L32, chacune avec son interface, son critère d'acceptation mesurable, sa capture attendue et son piège ; c'est le plan que suivent les agents Sonnet ;
- `docs/19c_journal_style.md` : le journal des décisions de style prises avec Monsieur sur captures.

> **Budget, décision de Monsieur (20 oct. 2026 : « j'accepte 50 % du GPU finalement »)** : le rendu SEUL dispose de **50 % du temps GPU** de la Quadro RTX 3000 6 Go, soit un **plafond dur de 8,3 ms par image** à **60 images/s** en **1080p natif** (pas d'upscaling ; TAA permis) ; l'IA des PNJ prend sa part à côté (7 à 17 %). **Cible de conception : 6,5 ms**, dont ≈ 5,4 ms de passes du laboratoire et 1,0 ms réservée aux personnages, particules, feu et interface des phases suivantes (§ 1.1).

Statut des chiffres : **[Mesuré]** = obtenu sur la machine de Monsieur pendant la rédaction (20 oct.) ; **[Source]** = écrit dans un document ou un code du projet, ou publié ; **[Calculé]** = arithmétique à partir d'hypothèses écrites ici ; **[Estimé]** = jugement d'ordre de grandeur, à mesurer ; **[Hypothèse]** = posé pour avancer, à confirmer par Monsieur. **Aucun temps GPU de ce document n'est encore mesuré** : les premières mesures viennent des tâches L02, L09 et L26.

---

## 0. En bref

### 0.1 Les choix clés

1. **Un workspace Cargo `engine-rs/`** de 13 crates sans cycle : vérité déterministe (`em_core`, `em_voxel`, `em_ops`, `em_gen`, `em_terrain`, `em_assembly`, `em_world`, entiers et Q16, flottants interdits par lint) d'un côté, présentation (`em_material`, `em_mesh`, `em_render`, `em_veg`, `em_water_render`) de l'autre, et le binaire `em_lab`.
2. **Le monde statique en voxels est rendu par lancer de rayons en compute** (traversée hiérarchique chunk → brique → voxel) dans une **clipmap de briques** de 6 niveaux centrée sur la caméra (5 cm jusqu'à 25,6 m, puis 10, 20, 40, 80, 160 cm), et **non par maillage** : mesuré sur le chêne de référence, le maillage glouton donne 792 356 quads pour UN arbre (§ 1.7), ce qui rend une forêt impossible en rastérisation. Le coût du tracé suit le nombre de pixels, pas le nombre de voxels.
3. **La rastérisation reste pour ce qui n'est pas voxel ou bouge** : peau lisse du terrain, herbe et fleurs (instances GPU), eau, petits corps voxel mobiles et, plus tard, personnages. Tout écrit le même G-buffer.
4. **Pas de chanfrein** : la couleur d'un voxel est un champ continu en coordonnées MONDE échantillonné au centre du voxel (pixel art, mais un bois reste un bois), plus un détail bitmap sous-voxel et un relief par différences finies, continus d'un voxel à l'autre. Les 7 bits de teinte portent un sens par classe (axe du fil du bois, pièce de pierre, essence et rampe de végétation).
5. **Lumière** : ciel de Hillaire repris de `web-ocean` (MIT), ombres du soleil en **cascades stables** remplies par la même traversée voxel (générations rafraîchies par morceaux, sans scintillement), occlusion proche tracée dans la grille voxel, lumière indirecte par **sondes DDGI tracées dans la grille voxel**, lumières ponctuelles ombrées par rayons voxel, brume volumétrique en froxels (rayons de soleil), TAA, bloom, AgX.
6. **Stockage « comme un PDF »** : vérité = graine + **paquet incrémental `EMPK`** (révisions des chunks édités, des entités et des pierres tombales, avec des tables incrémentales chaînées comme les références croisées d'un PDF) + **journal d'opérations au format v1 du bus C++ (T16)** ; instantané toutes les 10 minutes, compactage, rejeu bit exact.
7. **Entités paramétriques** : recette + graine + paramètres + état des parties + rustines locales ; une opération change une recette (des bûches deviennent une table) en quelques dizaines d'octets ; la végétation du monde de base n'est pas stockée tant que personne n'y touche.
8. **Budget** : rendu ≤ **50 % du GPU** (décision de Monsieur) : plafond dur 8,3 ms, **cible 6,5 ms** ; préréglage `haut` estimé à 5,4 ms de passes + 1,0 ms de réserve ; `moyen` 3,7 ms et `bas` 2,6 ms pour l'étalonnage (§ 1.4) ; VRAM visée ≈ 0,83 Go [Calculé].
9. **Harnais** : rendu hors écran reproductible en PNG, profileur par horodatages GPU (ms par passe), tests d'images de référence à tolérance perceptuelle, tests de déterminisme multi-fils, bancs, mode fenêtre interactif, journal de style.
10. **Ordre** : premières captures du ciel dès L03, premier arbre en L09, puis lumière, sol, herbe, eau, matières et bâti, atmosphère, et enfin la porte budgétaire de la forêt dense (L26) avant le port Rust des générateurs (L30 à L32).
11. **Orienté objet rigoureux** (« Codez bien orienté objet », Monsieur, 20 oct.) : état privé derrière des méthodes, invariants garantis par les constructeurs, traits courts là où il y a plusieurs implémentations, dépendances injectées, aucune globale (§ 2.7).

### 0.2 Les décisions de Monsieur que ce plan applique (20 oct. 2026)

| N° | Décision | Où c'est appliqué |
|---|---|---|
| 1 | Tout en Rust, sans Godot ; hôte = application `wgpu` + `winit` ; « Codez bien orienté objet » | § 2, § 2.7 |
| 2 | Le laboratoire est un vrai début du moteur, réutilisable | § 2, § 3 |
| 3 | Voxels de 5 cm ; pixel art PARTOUT sauf herbe et fleurs ; feuilles = voxels | § 4, § 6.1 |
| 4 | Aucun chanfrein ; matière continue en coordonnées monde ; propriétés de matière au shader ; textures = procédural + détail bitmap libre de droits | § 4.6 |
| 5 | Terrain : surface en peau lisse (surface nets) avec mélange de matières ; les zones creusées montrent des faces voxel | § 6.1 |
| 6 | Herbe et fleurs ultra réalistes, instances GPU, pas voxel | § 6.2 |
| 7 | Eau simulée (plus tard) et rendue de façon photographique ; le labo fait d'abord le rendu | § 6.3 |
| 8 | Monde 20 × 20 km d'entités paramétriques ; seules les modifications sont stockées (état ou journal « comme un PDF ») | § 3 |
| 9 | Budget du rendu : **50 % du GPU** de la Quadro RTX 3000 (« j'accepte 50 % du GPU finalement », qui remplace les 25 % du matin) ; pilote par `VK_DRIVER_FILES` | § 1, § 7.1 |
| 10 | Soin particulier : lumière, ombres, textures | § 5 |
| 11 | Captures PNG régulières, rendu hors écran reproductible + mode fenêtre | § 7 |
| 12 | Opérations d'entité et de terrain prévues pour les sorts | § 3.3, § 3.4 |
| 13 | Contenu généré déterministe (entiers, Q16, indépendant des fils) | § 2.4, § 7.5 |
| 14 | Moteur des PNJ branché plus tard par les interfaces existantes, via une interface C | § 2.6, 19a § 7 |

---

## 1. Hypothèses et budget

### 1.1 Le budget : 50 % du GPU pour le rendu (décision de Monsieur, 20 oct. ; P57)

> **[Décidé]** Le rendu SEUL a au plus **8,3 ms de temps GPU par image** (50 % de 16,67 ms), à **60 images/s**, en **1080p natif** (D23), sur la **Quadro RTX 3000 6 Go** ; le **TAA est permis**. L'IA des PNJ tourne à côté (7 à 17 % du GPU selon le modèle, `docs/16_quantification.md`, O25).

Trois seuils :

- **plafond dur 8,3 ms** : jamais dépassé en médiane sur un banc ; au-delà, on baisse dans l'ordre du § 1.4 ;
- **cible 6,5 ms** : ce que le préréglage `haut` tient sur la scène de synthèse (L29) ; les 1,8 ms restantes absorbent les pointes (édition, glissement de la clipmap), la chaleur d'un portable et la contention avec l'IA ;
- **réserve de 1,0 ms dans la cible** pour ce que le laboratoire n'a pas encore : personnages (quelques dizaines de PNJ visibles), particules, feu, interface. Les passes du laboratoire visent donc ≈ 5,4 ms (question Q1).

Le temps GPU d'une passe n'est pas un pourcentage d'occupation quand l'image est cadencée : l'interférence réelle (deux charges sur la carte) se mesurera en phase 7, quand le Transformer tournera à côté.

### 1.2 La machine

| Fait | Valeur | Statut |
|---|---|---|
| Carte | Quadro RTX 3000 (Turing TU106, 1920 cœurs, 6 Go GDDR6) | [Mesuré] `nvidia-smi` : 6144 Mio, horloge SM max 2100 MHz ; cœurs [Source : fiche NVIDIA] |
| Pilote, Vulkan | 615.71.09, Vulkan 1.4.351 | [Mesuré] `vulkaninfo` avec `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json` |
| Horodatage GPU | `timestampPeriod` = 1 ns, `timestampComputeAndGraphics` = vrai | [Mesuré] |
| Calcul | sous-groupes de 32, mémoire partagée 48 Kio, `drawIndirectCount` oui, `shaderFloat16` oui, `shaderInt64` oui, `VK_KHR_ray_query` et `VK_EXT_mesh_shader` présents | [Mesuré] |
| Puissance FP32 | ≈ 5,3 TFLOPS à 1,38 GHz soutenus | [Calculé] 1920 × 2 × 1,38 GHz ; l'horloge soutenue d'un portable varie (chaleur, alimentation) |
| Bande passante | ≈ 336 Go/s | [Source : fiche NVIDIA, non vérifiée ici] |
| Processeur | i9-10885H, 8 cœurs / 16 fils, 62 Go de RAM | [Source : CLAUDE.md] |
| Rust, crates | rustc 1.99 ; en cache : `wgpu` 30.0.1, `naga` 30.0.1, `winit` 0.30.13, `image` 0.25, `png` 0.18, `bytemuck` 1.25, `rayon` 1.12, `half` 2.7, `flate2` 1.1, `zstd` 0.13, `crc32fast` 1.5, `serde`, `toml` 1.1 ; crates.io joignable | [Mesuré] |

### 1.3 Ordres de grandeur

| Grandeur | Valeur | Statut |
|---|---|---|
| Pixels en 1080p | 2,07 M | [Calculé] |
| Angle d'un pixel au centre, champ vertical 60° | 1,069 mrad | [Calculé] 2·tan(30°)/1080 |
| Un voxel de 5 cm couvre 1 pixel à | 46,8 m (2 pixels à 23,4 m) | [Calculé] |
| Calcul disponible dans la cible de 6,5 ms | ≈ 34 GFLOP, soit ≈ 16 600 FLOP par pixel | [Calculé], rendement réel 30 à 50 % [Estimé] |
| Trafic mémoire disponible dans 6,5 ms | ≈ 2,2 Go | [Calculé] |
| Une passe plein écran qui lit et écrit 16 o/pixel | ≈ 0,1 ms | [Calculé] 33 Mo à 336 Go/s |
| Triangles rastérisés par ms (petits triangles) | ≈ 1 M | [Estimé] |

### 1.4 Budget par passe (1080p, 60 i/s) et préréglages

Ordre d'exécution du § 5.1 (mêmes numéros). Tous les temps sont **[Estimé]**, à remplacer par la mesure (profileur L02, porte budgétaire L26, étalonnage L29). Trois préréglages de qualité : `haut` (le jeu sur la Quadro, dans la cible de 6,5 ms), `moyen` et `bas` (cartes plus faibles, ou repli si la mesure est rouge).

| # | Passe | `haut` (ms) | Réglage en `haut` | `moyen` | `bas` |
|---|---|---|---|---|---|
| 1 | Téléversements GPU (briques, maillages, instances) | 0,05 | ≤ 8 Mo par image | 0,05 | 0,05 |
| 2 | Ciel : LUT de vue (chaque image), transmittance et diffusion multiple (au changement), cube d'environnement (une face par image), visibilité du soleil | 0,10 | 2 couches de nuages | 0,08 | 0,06 |
| 3 | Cascades d'ombre : rafraîchissement par tuiles (peau rastérisée + voxels tracés) | 0,35 | cascade 0 en 4096² (texel ≈ 0,6 cm), génération toutes les 0,5 s | 0,20 (2048², 1 s) | 0,12 (3 cascades, 2 s) |
| 4 | Pré-passe de profondeur : peau du terrain (+ corps mobiles) | 0,15 | maille de 4 voxels | 0,15 | 0,12 (maille de 8) |
| 5 | Boîtes des chunks visibles → distance d'entrée des rayons | 0,04 | — | 0,04 | 0,04 |
| 6 | **Tracé primaire des voxels + matière v2** → G-buffer | **1,00** | seuil de LOD 1,8 px, détail et relief jusqu'à 15 m | 0,85 | 0,70 (seuil 3 px) |
| 7 | Fusion des profondeurs + pyramide HiZ | 0,06 | — | 0,06 | 0,06 |
| 8 | G-buffer de la peau | 0,20 | mode `blend` | 0,18 | 0,15 |
| 9 | Herbe et fleurs : élimination en compute + dessin indirect | 0,75 | portée 80 m, ≈ 400 brins/m² de près | 0,40 (48 m) | 0,25 (32 m, densité ×0,7) |
| 10 | Occlusion proche tracée + débruitage | 0,40 | demi-résolution, 4 rayons ≤ 2 m | 0,25 (2 rayons) | 0,12 (quart de rés., 1 rayon) |
| 11 | Sondes d'irradiance (DDGI voxel) | 0,50 | 8 192 sondes × 64 rayons par image (chaque sonde toutes les 6 images) + niveau de 0,5 m dans les bâtiments | 0,25 (4 096) | 0,12 (1 024) |
| 12 | Éclairage différé : soleil, ciel, sondes, AO, lumières ponctuelles et leurs rayons d'ombre, émission, fond de ciel | 0,65 | ombre douce du soleil (PCSS), 8 lumières ombrées par tuile, ombres de contact en pleine résolution | 0,40 (4 lumières, contact en demi-rés.) | 0,30 (2 lumières) |
| 13 | Eau : rayons de réflexion + surface + réfraction | 0,35 | reflets voxel en pleine résolution | 0,22 (demi-rés.) | 0,12 (écran + ciel) |
| 14 | Brume volumétrique + application | 0,45 | froxels 160 × 90 × 128, lumières ponctuelles dans la brume | 0,22 (× 64 tranches) | 0,12 (120 × 68 × 48) |
| 15 | TAA | 0,18 | avec réglage de netteté | 0,15 | 0,15 |
| 16 | Bloom | 0,15 | 8 niveaux | 0,12 (6) | 0,08 (4) |
| 17 | Composition AgX + tramage | 0,04 | — | 0,04 | 0,04 |
| | **Passes du laboratoire** | **5,42** | | **3,66** | **2,60** |
| | Réserve : personnages, particules, feu, interface (phases 5-7) | 1,00 | | 1,00 | 1,00 |
| | **Total** | **6,42** | cible 6,5 ; plafond 8,3 | **4,66** | **3,60** |

**Ce que la marge des 50 % achète** par rapport au premier plan à 25 % (qui est devenu le préréglage `moyen`) : une **indirecte** plus juste (deux fois plus de sondes rafraîchies, un niveau de 0,5 m dans les maisons, AO à 4 rayons), une **brume volumétrique** deux fois plus fine en profondeur avec les lanternes dedans (les rayons du soir), **l'herbe jusqu'à 80 m** au lieu de 48, des **ombres plus fines** (cascade 0 en 4096², une génération toutes les 0,5 s, pénombre douce, ombres de contact en pleine résolution), des **reflets d'eau** en pleine résolution, 8 lumières ombrées par tuile, et une **réserve d'1 ms** pour les personnages.

**Ce qu'on baisse en premier si la mesure dépasse la cible** (dans cet ordre, chaque ligne est un réglage du § 7.7, en partant de `haut`) : (1) sondes par image 8 192 → 4 096 (−0,25) ; (2) brume 128 → 64 tranches, sans lumières ponctuelles (−0,23) ; (3) AO 4 → 2 rayons (−0,15) ; (4) herbe 80 → 48 m (−0,35) ; (5) reflets d'eau en demi-résolution (−0,13) ; (6) lumières ombrées 8 → 4 par tuile, contact en demi-résolution (−0,25) ; (7) cascade 0 4096² → 2048², génération 1 s (−0,15) ; (8) bloom 8 → 6 niveaux (−0,03) ; (9) seuil de LOD des voxels 1,8 → 3 px (−0,15 à −0,30) ; puis le préréglage `bas`. **Jamais baissés** sans l'accord de Monsieur : la résolution native, la taille des voxels, la matière de près (c'est le style).

### 1.5 Mémoire vidéo (préréglage `haut`)

| Ressource | Taille | Statut |
|---|---|---|
| G-buffer (4 cibles de 4 o + profondeur 32 bits + distance R32F) | 50 Mo | [Calculé] 24 o × 2,07 M |
| Scène HDR rgba16f + copie pour la réfraction | 33 Mo | [Calculé] |
| Historique TAA (×2) | 33 Mo | [Calculé] |
| AO demi-résolution, bloom | 12 Mo | [Calculé] |
| Cascades d'ombre : 3 générations × (4096² + 2 × 2048² + 1024²) × 2 o (Depth16), + la cinquième (terrain, 1024²) | 163 Mo | [Calculé] |
| Clipmap : tables de chunks + chunks (6 niveaux) | 26 Mo | [Calculé] ≈ 2 000 chunks occupés par niveau × 2 176 o |
| Clipmap : briques, forêt dense partout (≈ 1,2 M briques × ≈ 250 o : 2 bits par voxel dans le houppier, 4 bits dans les briques mêlées tronc-feuillage, § 4.4) | 300 Mo | [Calculé] à partir du § 1.7, 1 arbre / 40 m² [Hypothèse] ; tout en 4 bits : ≈ 430 Mo |
| Sondes DDGI : 3 niveaux × 16 384 sondes × 1,28 Ko + niveau de 0,5 m dans les bâtiments | 66 Mo | [Calculé] (formats en 19a § 5.5) |
| Froxels (3 volumes 160 × 90 × 128 rgba16f) | 44 Mo | [Calculé] |
| Ciel (LUT + cube 256² × 6 × 9 niveaux) | 5 Mo | [Calculé] |
| Peau du terrain (6 niveaux) | 20 Mo | [Calculé] ≈ 512 chunks de surface × 6,7 Ko par niveau |
| Herbe (sol à deux niveaux + instances), eau, atlas de matières (12 couches 512² rgba8 + mips), anneaux de téléversement | 73 Mo | [Calculé] |
| **Total** | **≈ 0,83 Go** (≈ 0,95 Go si toutes les briques sont en 4 bits) | cible ≤ 1,0 Go ; docs/06 § 8.1 visait < 1,5 Go |

### 1.6 Processeur

| Travail | Budget | Fil |
|---|---|---|
| Préparer et soumettre une image | ≤ 1,5 ms | principal |
| Composer un chunk 64³ à un niveau quelconque (sol + entités + deltas) | ≤ 1 ms | ouvriers (`rayon`, 6 fils sur 16) |
| Mailler la peau d'un chunk | ≤ 0,3 ms | ouvriers |
| Plan d'un arbre (squelette, port Rust) / rastérisation LOD0 | ≤ 30 ms / ≤ 20 ms | ouvriers |
| Un coup de pioche, toutes conséquences jusqu'au GPU | ≤ 2 ms | [Source : docs/06 § 8.2] |
| Téléversement GPU | ≤ 8 Mo par image | principal |

Tous ces chiffres sont des **cibles** [Hypothèse] ; les bancs de L05, L16, L19 et L30-L31 les mesurent.

### 1.7 Mesures faites pour ce document [Mesuré, 20 oct.]

Scripts jetables du rédacteur (hors dépôt) : génération par `voxel_tree.py` (sans ombrage cuit), puis comptage des faces exposées (6 voisins), fusion gloutonne 2D par tranche et par sorte, briques 8³ occupées, et réductions 2×, 4×, 8× (cellule pleine si au moins un quart des voxels fins sont pleins). Ces réductions ne servent qu'à estimer l'ordre de grandeur des LOD : dans le moteur, les LOD d'un arbre viennent de sa recette (L04 exporte les vrais et les mesure), et la règle 4/8 du § 3.2 ne s'applique qu'aux briques éditées.

**Chêne graine 42, 14 m** (l'arbre de `docs/apercus/00_arbre_reference_chene42.png`) : 608 032 voxels rendus par le générateur, **607 784 cellules distinctes** (248 cellules sont à la fois écorce et rameau : piège de l'exporteur, L04) ; 94,5 % de feuilles (574 554), 13 607 écorce, 19 871 rameaux ; génération 1,2 s.

| Niveau | Voxels | Faces exposées | Quads gloutons (par sorte) | Briques 8³ | Remplissage |
|---|---|---|---|---|---|
| LOD0, 5 cm | 607 784 | 1 174 258 | **792 356** | 4 406 | 27 % |
| LOD1, 10 cm | 118 526 | 125 216 | 78 630 | 800 | 29 % |
| LOD2, 20 cm | 14 281 | 20 034 | 10 970 | 146 | 19 % |
| LOD3, 40 cm | 1 825 | 3 878 | 2 283 | 31 | 12 % |

Même chêne à sa hauteur tirée par l'essence (19,1 m) : 1 468 746 voxels, 1 858 200 quads en LOD0, 9 648 briques, 3,0 s.

**Maison `sample_gravit.vxh`** (générateur JS) : 442 640 voxels de bâti (hors sol et herbe) ; 301 726 faces exposées ; **45 270 quads** en fusionnant par matériau (la couleur lue au shader), 199 756 en fusionnant par couleur ; 2 831 briques occupées (31 %).

Lecture : le feuillage ne se fusionne presque pas (×1,5), le bâti très bien (×6,7). C'est ce qui décide du § 4. Au passage, la question « le maillage glouton est-il compatible avec une matière continue en coordonnées monde ? » a sa réponse : **oui**, si l'on fusionne par classe de matière et que le shader relit la valeur de chaque voxel (45 270 quads au lieu de 199 756 pour la maison) ; c'est le feuillage, pas la matière, qui le condamne.

---

## 2. Organisation du dépôt

### 2.1 Arborescence

```
engine-rs/                      workspace Cargo (lisible par Claude, voir .claudeignore)
  Cargo.toml                    [workspace], versions des dépendances fixées une fois
  rust-toolchain.toml           channel = "1.99"
  README.md                     en français : commandes, crates, règles
  clippy.toml                   règles communes
  crates/
    em_core/  em_voxel/  em_material/  em_ops/  em_mesh/  em_gen/  em_terrain/
    em_assembly/  em_world/  em_render/  em_veg/  em_water_render/  em_lab/
  lab/
    scenes/<scène>.toml         prises de vue nommées (caméra, heure, météo)
    style/style.toml            paramètres de style, rechargés à chaud
    reference/<scène>_<prise>.png   images de référence approuvées par Monsieur
    models/*.vxm                modèles exportés par tools/vegetation (régénérables)
    captures/                   sorties datées (ignorées)
  scripts/
    lab.sh  bench.sh  fetch_textures.py  export_vegetation.sh
tools/vegetation/               voxel_tree.py, voxel_bush.py (copiés de Map/) + exporteur .vxm (L04)
assets/textures/                textures CC0 téléchargées (hors git) ; leur manifeste lisible est engine-rs/lab/textures.toml
```

`engine/em_water` (solveur physique) reste où il est pendant le laboratoire ; il rejoint `engine-rs/crates/em_water` en phase 4.

### 2.2 Les crates (P58)

| Crate | Rôle (une responsabilité) | Dépend de | Ne dépend jamais de |
|---|---|---|---|
| `em_core` | Q16 et ses fonctions (racine, exp2, log2, sinus en tours), hachage identique au C++ (`mix64`, `hash2/3`, graines de couche), CRC32 et FNV-1a identiques à `engine/ops`, coordonnées et clés (voxel, brique, chunk, région, LOD), repères (monde y-haut, act z-haut), identifiants (`EntityId` 22 + 10 bits, `MaterialId`, `VoxelValue`), lecteur et écrivain petit-boutistes | rien | tout le reste |
| `em_voxel` | Brique 8³ à palette (uniforme, 1/2/4/8/16 bits), chunk 64³, `VoxelSource`, `VoxelSink`, source composite, réduction 2×, colonnes d'occupation, magasin de deltas par région, éditeur de formes, empreintes | `em_core` | rendu, opérations |
| `em_material` | Table des matières (`engine/data/materials.csv` + `material_render.toml`), sens des teintes par classe, rampes, rampes de végétation, manifeste des textures, fonction WGSL de matière et sa référence CPU. Deux modules : `table` (entiers : identifiants, noms, propriétés physiques, sens des teintes ; **seul module lu par les crates de vérité**) et `gpu` (flottants : paquet GPU, rampes linéaires, référence CPU), derrière la fonctionnalité Cargo `gpu` qu'active `em_render` | `em_core` | `wgpu` |
| `em_ops` | `Operation` v1 compatible octet par octet avec `engine/ops` (T16), charges utiles typées, `Applier`, `OperationSink`, `LocalBus` (même ordre total que le C++), `Journal` (EMOPLG v1), paquet `EMPK` | `em_core` | voxels, rendu |
| `em_mesh` | Surface nets générique (sur un échantillonneur de densité), jupes de couture, `SkinSource`, `SkinMesh` ; maillage glouton binaire (quads de 8 o) pour les corps mobiles et le repli | `em_core`, `em_voxel` | `wgpu` |
| `em_gen` | Générateurs paramétriques : `Generator` et `GenPlan` ; chargeur `.vxm` (pont avec Python) ; port Rust de `voxel_tree`/`voxel_bush` ; rochers ; plus tard maisons | `em_core`, `em_voxel`, `em_material` | opérations, rendu |
| `em_terrain` | `DensityField` (densité analytique en Q16), paysage du labo, source voxel du terrain de base, règles de matière du sol, peau (implémente `SkinSource`), requêtes de hauteur | `em_core`, `em_voxel`, `em_material`, `em_mesh` | opérations, rendu |
| `em_assembly` | Entités paramétriques : `Recipe`, registre des recettes, assemblages en parties, table des entités, rustines locales, opérations d'entité, matérialisation de la végétation de base | `em_core`, `em_voxel`, `em_material`, `em_gen`, `em_ops` | rendu |
| `em_world` | Le monde : manifeste, composition (sol + deltas + entités), appliqueurs (voxels, entités), bus local ou puits externe, journal, paquet, instantanés, compactage, rejeu, suivi des chunks sales | `em_core`, `em_voxel`, `em_ops`, `em_terrain`, `em_assembly` | rendu |
| `em_render` | `wgpu` : contexte GPU, cibles (fenêtre, hors écran), graphe de passes, bibliothèque de shaders, profileur, captures, clipmap GPU et diffuseur, toutes les passes de lumière | `em_core`, `em_voxel`, `em_material`, `em_mesh` + `wgpu`, `bytemuck`, `glam`, `png`, `rayon` | `em_world`, `em_ops` |
| `em_veg` | Herbe et fleurs : règles de placement déterministes, maillages procéduraux, passe GPU (élimination, LOD, vent) | `em_core`, `em_render` | vérité |
| `em_water_render` | Rendu de l'eau : surface, écoulement, shaders `web-ocean`, réfraction, réflexions ; trait `WaterSurfaceSource` | `em_core`, `em_render` | `em_water` (phase 4 : un adaptateur) |
| `em_lab` | Binaire : scènes, captures, bancs, fenêtre, panneau de style ; relie `em_world` et `em_render` | tous | — |

`em_capi` (interface C pour le moteur des PNJ) est **prévue, pas créée** pendant le laboratoire (§ 2.6).

### 2.3 Graphe des dépendances (aucun cycle)

```
em_core ─┬─► em_voxel ─┬─► em_mesh ──────────────┐
         │             │                          │
         ├─► em_material ─────────┐               │
         │                        ▼               ▼
         ├─► em_ops         em_gen ◄─(voxel,mat)  em_terrain ◄─(voxel,mat,mesh)
         │     │               │                  │
         │     └──► em_assembly ◄┘                │
         │              │                         │
         │              └──────► em_world ◄───────┘        (vérité, déterministe)
         │
         └─► em_render ◄─(voxel, material, mesh)            (présentation)
                ├─► em_veg
                └─► em_water_render
                                    em_lab ◄── tous         (binaire)
```

Sens interdits, vérifiés par un test qui lit `cargo metadata` (L01) : `em_render` → `em_world`/`em_ops` ; une crate de vérité → `wgpu` ; `em_ops` → `em_voxel` (comme `core → ops` interdit côté C++, docs/14 § 8.1).

### 2.4 Règles du code

- **Déterminisme des crates de vérité** (`em_core`, `em_voxel`, `em_ops`, `em_gen`, `em_terrain` hors module `skin`, `em_assembly`, `em_world`) : `#![deny(clippy::float_arithmetic)]` ; entiers et `Q16` seulement ; hasard par `em_core::hash` (jamais `rand`) ; `HashMap`/`HashSet` interdits (`disallowed-types` dans leur `clippy.toml`) au profit de `BTreeMap` ou de vecteurs triés ; tout calcul parallèle (`rayon`) est une fonction pure par clé, résultats triés par clé avant application. Un rendu visuel seul (couleur des feuilles au shader, maillage de peau) peut utiliser `f32` : il n'est jamais relu par la simulation.
- **Aucun `unsafe`** : `#![forbid(unsafe_code)]` partout (seule `em_capi`, plus tard, l'autorisera).
- **Orienté objet** : règles du § 2.7 (consigne de Monsieur).
- **Formats versionnés** : tout fichier ou tampon persistant porte une signature, une version et un CRC ; refus fermé d'une version future (comme `OpJournal`).
- **Dépendances** : `wgpu` 30.0.1, `winit` 0.30.13, `naga` 30.0.1 (validation hors ligne des shaders), `bytemuck`, `glam` (rendu seulement), `png`, `image` (textures), `rayon`, `serde` + `toml`, `flate2` (pour `.vxm`), `zstd` (paquet `EMPK`), `log` + `env_logger`. Pas d'`egui` au début : le panneau de style est un fichier TOML rechargé à chaud + touches + surimpression texte (évite le couplage de versions `egui-wgpu`/`wgpu`).
- **Langue** : identifiants en anglais, commentaires et messages en français, comme le reste du dépôt.

### 2.5 Les traits principaux

Signatures de référence ; les tâches de `19b` les reprennent mot pour mot. `Lod` = `u8` (voxel = 5 cm × 2^lod).

```rust
// em_voxel : toute source de voxels (sol, deltas, entités, modèle .vxm, composite)
pub trait VoxelSource: Send + Sync {
    /// Remplit `out` avec le chunk `key` au niveau `lod`. Fonction pure : mêmes entrées, mêmes octets,
    /// quel que soit le fil ou l'ordre des appels.
    fn fill_chunk(&self, key: ChunkKey, lod: Lod, out: &mut Chunk);
    /// Classement rapide sans remplir (Air, Plein(valeur), Inconnu) pour sauter les chunks vides.
    fn classify(&self, key: ChunkKey, lod: Lod) -> ChunkHint { ChunkHint::Unknown }
    /// Étiquette de version (générateurs, deltas) pour invalider les caches.
    fn version_tag(&self) -> u64;
}
pub trait VoxelSink { fn put(&mut self, at: VoxelCoord, value: VoxelValue, mode: PutMode); } // Solid | CarveAir

// em_gen : générateur paramétrique en deux temps (plan coûteux une fois, rastérisation paresseuse)
pub trait Generator: Send + Sync {
    fn id(&self) -> GeneratorId;            // registre en ajout seul
    fn version(&self) -> u32;               // change si la sortie change
    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError>;
}
pub trait GenPlan: Send + Sync {
    fn bounds(&self, lod: Lod) -> VoxelBox; // repère local, pivot au pied, niveau lod
    fn rasterize(&self, lod: Lod, window: VoxelBox, sink: &mut dyn VoxelSink); // seulement ce qui tombe dans window
    fn lights(&self) -> &[LocalLight] { &[] }  // une lanterne déclare sa lumière
}

// em_assembly : une sorte d'entité physique (bûche, table, mur, poutre, arbre, maison)
pub trait Recipe: Send + Sync {
    fn kind(&self) -> RecipeKind;           // registre en ajout seul (19a § 4)
    fn version(&self) -> u16;
    fn decode_params(&self, bytes: &[u8]) -> Result<RecipeParams, ParamError>;
    fn parts(&self, params: &RecipeParams, seed: u64) -> PartList;       // parties nommées et leurs boîtes
    fn plan(&self, params: &RecipeParams, seed: u64, parts: &PartState) -> Arc<dyn GenPlan>;
}

// em_ops : abonné du bus, même contrat que engine/ops/applier.h
pub trait Applier: Send {
    fn name(&self) -> &'static str;
    fn apply(&mut self, op: &Operation) -> ApplyStatus;   // Applied | Deferred | Ignored | Rejected
    fn fingerprint(&self) -> u64 { 0 }
    fn last_op_id(&self) -> u64 { 0 }
    fn end_of_flush(&mut self) {}
}
pub trait OperationSink: Send + Sync {    // LocalBus dans le labo ; l'hôte C++ en phase 7
    fn submit(&self, op: Operation, decision_seq: u32, k: u32) -> SubmitResult;
}

// em_terrain : densité analytique du terrain de base
pub trait DensityField: Send + Sync {
    fn density(&self, p_mm: [i64; 3]) -> Q16;            // < 0 : plein ; repère monde y-haut
    fn material(&self, v: VoxelCoord, depth_mm: i64) -> VoxelValue;
    fn surface_column(&self, x_mm: i64, z_mm: i64) -> Option<i64>; // hauteur si la colonne est un simple relief (remplissage par colonne)
    fn height_bounds(&self, x0_mm: i64, z0_mm: i64, x1_mm: i64, z1_mm: i64) -> (i64, i64);
    fn version(&self) -> u32;
}
// em_mesh
pub trait SkinSource: Send + Sync {
    fn skin_chunk(&self, key: ChunkKey, lod: Lod, edited: &BrickMask, out: &mut SkinMesh);
}

// em_render : une passe du graphe
pub trait RenderPass: Send {
    fn name(&self) -> &'static str;
    fn resize(&mut self, gpu: &GpuContext, res: &mut Resources, size: (u32, u32)) {}
    fn prepare(&mut self, gpu: &GpuContext, res: &Resources, frame: &FrameContext) {}
    fn record(&mut self, gpu: &GpuContext, res: &Resources, frame: &FrameContext,
              enc: &mut wgpu::CommandEncoder, prof: &mut GpuProfiler);
    fn enabled(&self) -> bool { true }
    fn knobs(&mut self) -> Vec<&mut QualityKnob> { Vec::new() }
}
pub trait FrameTarget {                     // WindowTarget, OffscreenTarget
    fn size(&self) -> (u32, u32);
    fn acquire(&mut self) -> TargetFrame;
    fn present(&mut self, frame: TargetFrame);
}
// em_water_render
pub trait WaterSurfaceSource: Send + Sync {  // AnalyticWater (labo) ; adaptateur em_water (phase 4)
    fn tiles_in(&self, area_mm: [i64; 4], out: &mut Vec<WaterTile>); // niveau, vitesse, mousse, à 25 cm
    fn revision(&self) -> u64;
}
// em_lab
pub trait Scene {
    fn name(&self) -> &'static str;
    fn build(&mut self, ctx: &mut SceneContext) -> anyhow::Result<()>;
    fn world(&self) -> &dyn LabWorld;        // VoxelSource + SkinSource + lumières + eau + sol pour l'herbe
    fn shots(&self) -> &[Shot];              // lues dans lab/scenes/<nom>.toml
    fn tick(&mut self, _dt: f32) {}
}
```

Pourquoi **pas de trait `Material`** : une matière est une ligne de données (table du § 4.6 et de 19a § 5), évaluée par une seule fonction WGSL et sa référence CPU ; un trait par matière dupliquerait la logique entre CPU et GPU. `MaterialDef` est une struct, `MaterialTable` la possède.

### 2.6 Points d'accroche du moteur des PNJ (prévus, non implémentés)

Le moteur des PNJ (C++) parle au monde par des interfaces déjà écrites ; le monde Rust les servira par une crate `em_capi` (phase 7). Détail des fonctions C en 19a § 7.

| Interface C++ existante | Ce que le monde Rust fournit | Où |
|---|---|---|
| `em::ops::Applier` (abonnés 2 « voxels » et 3 « champs ») | `em_world_apply(op)` → `ApplyStatus`, `fingerprint`, `last_op_id`, `end_of_flush` | `engine/ops/include/emergence/ops/applier.h` |
| `OperationBus::submit` | le monde soumet ses propres opérations (effondrement, eau) par un rappel fourni par l'hôte | `operation_bus.h` |
| `SpaceQuery` (T23) | transmission de la vue et du son, lumière, bruit ambiant, intérieur, brume ; const, pure, multi-fils | `engine/act/perception/.../space_query.h` |
| `ViewProbe` (T23b) | `blocked(from, to)` dans le champ de vue ; c'est ce qu'utilise le `Navigator` C++, qui implémente lui-même `NavigationQuery` | `engine/act/navigation/.../view_probe.h`, `navigation_query.h` |
| `VoxelRequest` (T18 : `extract`, `till`) | conversion en `VoxelEdit` côté monde (les lois n'émettent pas d'opération voxel aujourd'hui) | `engine/act/laws/law_kit.h` |

**Repères** : le monde suit le contrat voxel (x est, y haut, z nord, `docs/interfaces.md` § 1 et `Map/world_contract.h`) ; le moteur d'actions C++ est en z haut (x est, y nord ; `engine/act/README.md`). La conversion se fait à **un seul endroit**, `em_core::frame`, appelée seulement par `em_capi` et par le décodage des charges `Spawn`/`Move` (19a § 3). Les rotations sont définies physiquement (quart de tour de l'est vers le nord), donc sans ambiguïté de main. Le repère monde (x est, y haut, z nord) est **gaucher** : `em_render` n'utilise que des matrices gauches (`glam` `*_lh`, dont `Mat4::perspective_infinite_reverse_lh` et `Mat4::look_to_lh`) ; lacet 0° = regard vers le nord (+z), positif dans le sens horaire vu d'en haut (vers l'est) ; tangage positif vers le haut. Une **scène d'orientation** (L08, L09) le vérifie : un voxel rouge à l'est et un bleu au nord du pivot, vus d'en haut le nord en haut, donnent le rouge à droite et le bleu en haut ; la même scène exportée par Python (L04) doit donner la même image.

**Identifiants** : l'`EntityStore` C++ attribue les `EntityId` (22 bits de case + 10 de génération) ; le labo les attribue avec le même schéma par un `LocalEntityIds` ; en phase 7, un `HostEntityIds` les demande à l'hôte.

### 2.7 Orienté objet, rigoureusement (« Codez bien orienté objet », Monsieur, 20 oct. ; P70)

Règles que chaque tâche applique et que le relecteur vérifie :

1. **Encapsulation** : les champs d'une struct qui porte un invariant sont **privés** ; on la construit par un constructeur qui le vérifie (`Brick::from_dense`, `Operation::new`, `VxmModel::load`, `Camera::new`) et on la lit par des méthodes. Exemples d'invariants : une palette de brique sans doublon et ≤ 256 entrées ; un `op_id` attribué **seulement** par le bus (`pub(crate)`) ; un `EntityId` à case ≥ 1.
2. **Types valeur** (`Q16`, `VoxelCoord`, `ChunkKey`, `VoxelValue`, `EntityId`, `MaterialId`) : nouveaux types (`struct EntityId(u32)`) plutôt que des entiers nus, avec leurs opérations en méthodes ; un `u16` n'est jamais pris pour une matière.
3. **Exceptions permises aux champs publics** : les structs de configuration (`ClipmapConfig`, `GrassConfig`, `ShadowConfig`) validées par `fn validate(&self) -> Result<(), ConfigError>` à la construction de l'objet qui les reçoit ; les rapports de mesure en lecture seule, sans invariant (`ProfileReport`, `ImageDiff`, `BusStats`) ; et les dispositions GPU `#[repr(C)]` (`MaterialGpu`, uniformes), rangées dans des modules `gpu` et jamais utilisées comme état de la simulation.
4. **Traits** : courts, une seule responsabilité, seulement là où il y a au moins deux implémentations (docs/14 § 8.2) ; le polymorphisme passe par `dyn Trait` ou des génériques, jamais par un `match` sur un nom.
5. **Composition et injection** : un objet reçoit ses collaborateurs par son constructeur (`World::new(manifest, terrain)`, `RenderGraph::add(pass)`) ; **aucune globale**, aucun `static mut`, aucun singleton paresseux ; l'état partagé entre fils passe par `Arc` et un verrou ou un double tampon possédé par un objet.
6. **Une responsabilité par objet** : le `ClipmapStreamer` décide quoi charger, `VoxelGpuWorld` possède la mémoire GPU, `VoxelTracePass` dessine ; aucun ne fait le travail d'un autre.
7. **Erreurs typées** (`thiserror`) dans les bibliothèques ; `anyhow` seulement dans `em_lab`.

---

## 3. Stockage et opérations

### 3.1 La vérité

Le monde n'est jamais stocké en entier. La vérité est :

1. `world.manifest` : graine, versions de chaque générateur et de la table des matières, empreinte du plan (reprend `WorldManifest` de `Map/world_contract.h`) ;
2. **le monde de base**, recalculé depuis la graine : relief (densité analytique), écologie (arbres, rochers placés par cellule), établissements (maisons par recettes) ;
3. **le paquet `EMPK`** : les chunks modifiés (leurs briques réécrites), les entités matérialisées ou créées, les pierres tombales des objets de base retirés, chacun avec l'`op_id` de l'état qu'il représente ;
4. **le journal d'opérations** depuis le dernier instantané (format `EMOPLG` v1 du C++, blocs de 4 096 opérations avec CRC).

Tout le reste est un **cache** : chunks composés, LOD, maillages de peau, clipmap GPU, sondes, cascades d'ombre.

Constantes reprises du contrat `Map/` : voxel 50 mm ; chunk 64³ = 3,2 m ; brique 8³ = 40 cm ; région 32 × 16 × 32 chunks = 102,4 × 51,2 × 102,4 m ; monde 400 000 voxels de côté, de y = −10 000 (−500 m) à y = 70 000 (3,5 km). Ordre dense dans une brique et un chunk : **x le plus rapide, puis z, puis y** (`docs/interfaces.md` § 2). Attention : `docs/interfaces.md` (8 oct.) parle encore de voxels de 2 cm, de chunks de 1,28 m et de briques de 16 cm ; seuls ses repères et ses ordres sont repris ici, la taille est **5 cm** (P52), le chunk 3,2 m, la brique 40 cm.

### 3.2 Composer un chunk

`em_world::CompositeSource::fill_chunk(key, lod)` applique, **dans cet ordre fixe** :

1. **terrain de base** : densité analytique échantillonnée au centre des cellules du niveau, matière par `DensityField::material` ;
2. **deltas de région** (éditions du terrain et voxels libres posés) : au niveau 0, les briques réécrites remplacent celles du terrain ; aux niveaux grossiers, les briques éditées sont **réduites** depuis le niveau 0 (règle 4/8 et classe majoritaire, comme `downsample` en C++) ;
3. **entités** : la végétation de base (moins ses pierres tombales) et les entités matérialisées ou créées, rastérisées depuis leur recette AU niveau demandé (`GenPlan::rasterize(lod, fenêtre)`), puis leurs rustines locales ; un voxel d'entité remplace le terrain, et `PutMode::CarveAir` creuse (une cave) ;
4. **drapeaux de brique** pour le rendu : `skin` (terrain non édité, rendu par la peau), `edited`.

Chaque couche est une `VoxelSource` ; la composition est pure et parallèle par chunk.

### 3.3 Les opérations

Une seule structure, l'`Operation` v1 de `engine/ops` (48 octets d'en-tête, petit-boutiste, sortes en ajout seul), reprise **octet par octet** en Rust (`em_ops`) et prouvée par des vecteurs croisés C++ ↔ Rust (L18). Le labo a son `LocalBus` (même ordre total : tick, auteur, `decision_seq`, `k`, sorte, octets) ; en phase 7, le bus C++ devient le seul bus et le monde Rust en est l'abonné n° 2 (voxels) et n° 3 (champs).

Sortes utilisées par le monde (charges détaillées en 19a § 3) :

| Sorte | Effet sur le monde | Exemple |
|---|---|---|
| `VoxelEdit` (2) | formes `box`, `sphere`, `capsule`, `list`, `module` (docs/14 § 4.6) + **`blob`** (sphère au rayon bruité par `hash(op_id)`, pour les trous irréguliers, ajout en fin) ; `new_voxel` (0 = air) ; `only_class` (transformer une matière en une autre) | creuser, faire disparaître, changer la pierre en sable |
| `Spawn` (4), `Destroy` (5), `Move` (6) | l'entité au sens du catalogue (sa sorte, sa position en mm, son contenant) | une table apparaît, une bûche est portée |
| **`EntityRecipe` (8, nouvelle)** | donne ou change la FORME physique d'une entité : recette, version, graine, ancre en voxels, quart de tour, paramètres ; peut matérialiser un objet de base (`base_ref`) | des bûches deviennent une table |
| **`EntityParts` (9, nouvelle)** | retire, remet ou abîme des parties nommées d'un assemblage, avec la révision attendue | la masse démonte un mur en pierres (O33) |
| `Field` (7) | l'eau (phase 4) | puiser un seau |

Les sortes 8 et 9 sont à **ajouter au registre C++** (ajout seul) au branchement : aujourd'hui `engine/ops` refuse toute sorte au-delà de 7 (`kMaxKnownKind`), donc les tests croisés Rust ↔ C++ portent sur les sortes 1 à 7, et une tâche C++ (hors laboratoire) montera `kMaxKnownKind` à 9 avec leurs drapeaux d'en-tête (19a § 3). D'ici là elles n'existent que dans `em_ops` (P63). Une entité physique naît toujours par un `Spawn` (qui lui donne son `EntityId` et sa sorte du catalogue) suivi, dans le même pas, d'un `EntityRecipe` (sa forme) ; un `Move` déplace aussi son ancre voxel (position convertie en voxels du monde, arrondi vers le bas).

### 3.4 Opération sur une recette ou sur des voxels

- **Sur une recette** (le cas des sorts d'artisan, de la masse, de la construction) : l'état de l'entité change (recette, paramètres, parties) ; ses voxels ne sont **jamais** stockés : ils sont rastérisés à la demande, à tous les LOD, depuis la recette. Une transmutation « deux bûches → une table » = `Destroy` ×2 + `Spawn` + `EntityRecipe(table, graine = hash(op_id), paramètres tirés des bûches : essence, volume)` : environ 250 octets de journal, environ 100 octets d'état.
- **Sur des voxels** (pioche, baguette « faire disparaître ») : `VoxelEdit` sur une boîte du monde. L'appliqueur découpe : la part qui touche le terrain va dans les deltas de région ; la part qui touche une entité va dans les **rustines locales** de cette entité (briques en copie à l'écriture, dans le repère local de l'entité), ce qui garde l'entité déplaçable et transformable (une table entaillée reste une table). Ordre de traitement des entités : par identifiant croissant.
- **Végétation de base** (des millions d'arbres sur 400 km²) : elle n'a pas d'`EntityId` tant que personne n'y touche (l'`EntityStore` C++ n'a que 4 M cases). Son identité est `base_ref = hash(couche, cellule, rang)`. La première opération qui la touche la **matérialise** (`EntityRecipe` avec `base_ref`) : pierre tombale dans le paquet, entité normale ensuite. Un arbre abattu coûte une pierre tombale de 8 octets et un enregistrement d'entité.

### 3.5 Le paquet incrémental `EMPK` (« comme un PDF », P62)

Comme un PDF à mises à jour incrémentales : on **ajoute** en fin de fichier les enregistrements qui ont changé, puis une **table** qui ne liste que les clés changées par cette validation et pointe vers la table précédente (comme la table de références croisées d'un PDF) ; une table complète est réécrite au compactage et toutes les 64 validations, pour borner la remontée. L'enregistrement de voxels a le grain du **chunk** (ses briques éditées), pas de la région, pour qu'une petite édition ne réécrive pas une région entière. Ouvrir = lire le pied de fichier, puis remonter les tables jusqu'à la dernière table complète.

```
save/<partie>/
  world.manifest          graine, versions, empreintes (EMWM v1)
  world.empk              paquet : régions, pages d'entités, pages de pierres tombales, tables (EMPK v1, 19a § 2)
  journal/oplog-NNNNNN.emj    journal EMOPLG v1 depuis le dernier instantané
```

- **Instantané** = une validation du paquet (tous les enregistrements sales + une table finale, `fsync`), toutes les **10 minutes de jeu réel** ou toutes les 100 000 opérations, et à la sauvegarde. La table porte l'`op_id` de l'état.
- **Journal** : après un instantané durable, les segments antérieurs sont supprimés, ou archivés si la Chronique (T31b) en a besoin. Pourquoi : à 100 opérations/s et 64 o par opération [Source : banc T16, 64 o/op], le journal ferait 23 Mo par heure, 2,3 Go en 100 h [Calculé] ; avec un instantané toutes les 10 min (≈ 60 000 opérations d'environ 100 o en moyenne, § 3.7), la queue reste sous 10 Mo.
- **Compactage** : quand plus de 40 % du paquet est mort (versions remplacées), réécriture des seuls enregistrements vivants dans un nouveau fichier, puis renommage atomique.
- **Ouverture d'une partie** : manifeste → paquet (dernière table) → rejeu de la queue du journal → monde prêt.

### 3.6 Le rejeu déterministe

Ce qui le garantit : les opérations portent tout ce qui sert à les appliquer (aucune lecture d'horloge ni de hasard non haché) ; ordre total par `op_id` ; formes voxel en entiers (centres de voxel en 1/16 de voxel, rayons au carré en entiers) ; recettes en Q16 ; composition pure. **Preuves exigées** (L19, L28) : (a) état vivant après N opérations = état après « base + rejeu complet » = état après « instantané au milieu + rejeu de la queue », comparés par empreinte FNV-1a des briques en ordre canonique ; (b) mêmes empreintes avec 1 et 8 fils et dans un ordre de chunks mélangé ; (c) un journal tronqué (plantage) se relit jusqu'au dernier bloc valide, comme en C++.

### 3.7 Coût d'une modification locale

Une brique réécrite à 2 bits par voxel (air, terre, pierre) pèse 128 o d'indices + 8 o de palette + 4 o d'en-tête ≈ 140 o [Calculé].

| Modification | Journal | Mémoire (état chargé) | Disque après instantané (zstd) |
|---|---|---|---|
| Coup de pioche (sphère de 15 cm, ≈ 113 voxels) | ≈ 85 o (48 + 37) | 1 à 8 briques ≈ 1 Ko | ≈ 0,5 Ko [Estimé] |
| Trou de 1 m³ (sphère de 62 cm, ≈ 8 000 voxels) | ≈ 85 o | ≈ 40 briques ≈ 6 Ko | ≈ 2 à 3 Ko [Estimé] |
| Arbre de base abattu | ≈ 100 o | pierre tombale 8 o + entité ≈ 100 o | ≈ 60 o |
| Deux bûches → une table | ≈ 250 o | entité ≈ 100 o | ≈ 80 o |
| Mur d'une maison percé à la pioche | ≈ 85 o | rustine de l'entité, quelques briques | ≈ 1 Ko |
| Une pierre retirée d'un mur à la masse | ≈ 70 o (`EntityParts`) | 1 bit de partie | ≈ 0 (page d'entité) |

### 3.8 Des LOD générés depuis la recette

- **Terrain** : la densité est analytique ; le niveau L l'échantillonne directement à 5 cm × 2^L. Aucune réduction.
- **Entités** : chaque recette rastérise au niveau demandé (le générateur Python le fait déjà avec `voxel=0.10`, `0.20`, `0.40` : même squelette, mêmes graines, feuillage re-rastérisé ; c'est ce qu'exporte le `.vxm`).
- **Éditions** : seules les briques éditées sont réduites depuis le niveau 0 (un trou se voit de loin ; P46 « un pont détruit salit ses niveaux grossiers »).
- **Arbres lointains** (niveau ≥ 3, au-delà de 100 m) : le plan complet d'un arbre (squelette) coûte trop cher pour des milliers d'arbres ; une **recette de silhouette** de la même essence (fût + amas du houppier tirés de la même graine, sans croissance) les remplace (L32, question Q8).

---

## 4. Le rendu des voxels en pixel art

### 4.1 Contraintes

Voxels de 5 cm nets (pixel art), sans biseau ni couture ; arbres de 600 000 à 1,5 million de voxels (§ 1.7) ; murs et poutres « d'un seul bois » ; destruction et transformation à tout moment ; 0,85 ms pour le tracé primaire (§ 1.4) ; une lumière soignée qui a besoin, elle aussi, d'interroger la géométrie (ombres, occlusion, indirect, reflets).

### 4.2 Trois options comparées

| | A. Maillage glouton rastérisé | B. **Lancer de rayons en compute dans une clipmap de briques** | C. Boîtes de briques rastérisées + tracé dans le fragment |
|---|---|---|---|
| Principe | quads de 8 o (format de `engine/core/mesh/greedy.h`), fusion par matière, couleur lue au shader | un rayon par pixel ; traversée chunk (3,2 m) → brique (40 cm) → voxel avec masques de bits | on dessine les boîtes des briques occupées ; le fragment avance dans la brique (≤ 24 pas) |
| Coût d'un chêne en LOD0 | **792 356 quads** [Mesuré] ; ≈ 400 000 face à la caméra | ≈ 4 406 briques en mémoire (≈ 0,9 Mo) ; coût à l'écran ∝ pixels | 4 406 boîtes ; surdessin |
| Forêt dense (1 arbre / 40 m², cône de 90°, LOD à 2 px) | ≈ 13 arbres dans le cône jusqu'à 25,6 m (π × 25,6² / 4 / 40) × 400 k = **5,2 M quads ≈ 10,4 M triangles ≈ 5 à 10 ms** [Calculé/Estimé] : hors budget même avec l'élimination par occlusion | ≈ 1,24 M rayons × ≈ 25 pas × ≈ 20 instructions ≈ 0,6 G instructions ≈ 0,25 ms au pic, **≈ 0,75 à 0,9 ms** avec divergence et latence [Estimé] | dans un houppier rempli à 27 %, un pixel traverse 5 à 15 boîtes ; écrire la profondeur dans le fragment coupe le test précoce : ×3 à ×5 de B [Estimé] |
| Maison (45 270 quads) | bon : ≈ 0,1 ms | ≈ même coût que tout pixel | moyen |
| Édition (creuser) | remaillage CPU du chunk | réécriture de briques, rien à mailler | réécriture de briques |
| Sert aussi aux ombres, à l'AO, à l'indirect, aux reflets | non (il faut une autre structure) | **oui, la même** | en partie |
| Anticrénelage | matériel possible | TAA | TAA |

Le lancer de rayons matériel de Turing (`VK_KHR_ray_query`, exposé par `wgpu` en expérimental) ne vaut pas mieux ici : il veut des triangles, c'est-à-dire le nombre de quads de A. À revoir plus tard.

### 4.3 Le choix (P59)

**B pour tout le monde statique en voxels** (bâti, arbres, arbustes, rochers, props, terrain creusé), **rastérisation pour le reste** : peau lisse du terrain (§ 6.1), herbe et fleurs (§ 6.2), eau (§ 6.3), petits corps voxel mobiles (portes qui pivotent, débris : maillés par le maillage glouton binaire d'`em_mesh`, qui sert aussi de repli) et personnages (plus tard). Tout le monde écrit le même G-buffer.

**Porte budgétaire** (L26) : banc « forêt dense » en 1080p, tracé primaire ≤ 1,0 ms en médiane. Au-delà de 1,2 ms : (1) passe grossière au huitième de résolution qui donne une distance de départ par tuile 8 × 8 ; (2) seuil de LOD 3 px ; (3) tracé des niveaux ≥ 3 en demi-résolution ; (4) **repli** : le bâti passe en option A (45 k quads par maison) et le tracé ne garde que la végétation.

### 4.4 La structure GPU : une clipmap de briques

Six cubes emboîtés centrés sur la caméra ; le niveau L a des voxels de 5 cm × 2^L et 16 chunks de côté (adressage torique, la grille glisse quand la caméra franchit un chunk) :

| Niveau | Voxel | Demi-côté couvert | Voxel au bord du niveau |
|---|---|---|---|
| 0 | 5 cm | 25,6 m | 1,83 px |
| 1 | 10 cm | 51,2 m | 1,83 px |
| 2 | 20 cm | 102,4 m | 1,83 px |
| 3 | 40 cm | 204,8 m | 1,83 px |
| 4 | 80 cm | 409,6 m | 1,83 px |
| 5 | 1,6 m | 819,2 m | 1,83 px |

[Calculé] avec 1,069 mrad par pixel, sur l'axe au bord du cube : 1,83 px, et de 1,6 à 2,1 px selon la place de la caméra dans son chunk (le cube glisse par chunks entiers) ; dans les coins du cube (diagonale), ≈ 1,05 px. Un voxel couvre donc au moins un pixel partout et environ deux sur les axes ; le pixel art reste lisible jusqu'au loin, et le coût par niveau est à peu près constant.

Trois étages de données (disposition exacte en 19a § 5) : **table de chunks** par niveau (16³ entrées de 4 o : vide, plein uniforme, ou case d'un chunk) ; **chunk** (512 entrées de brique de 4 o + **deux** masques de 512 bits : toutes les briques occupées, et les seules briques **visibles**, c'est-à-dire non `skin`) ; **brique** (masque d'occupation de 512 bits + palette et indices de 1, 2, 4 ou 8 bits dans un tas de mots). Drapeaux de brique : `uniform` (valeur dans l'entrée), `skin` (terrain non édité). Taille d'une brique d'arbre : la teinte de végétation ne porte que l'essence et une **variante** (écorce, écorce secondaire, rameau ; la rampe des feuilles est tirée au shader, § 4.6), donc une brique de houppier n'a que 3 ou 4 valeurs (air, feuille, rameau, écorce) : **2 bits** par voxel, 136 o d'indices et de palette + 64 o de masque + 8 o de méta ≈ 210 o ; une brique mêlée (tronc, écorce secondaire, feuilles, fleurs) passe à 4 bits ≈ 360 o.

**Diffusion** (`em_render::ClipmapStreamer`) : quand un niveau glisse, il demande les nouveaux chunks à la `VoxelSource` sur les fils ouvriers (les chunks d'air ou pleins sont classés sans être remplis), les empaquette au format GPU et les téléverse dans la limite de 8 Mo par image, du plus proche au plus lointain. Les chunks sales (éditions) passent devant.

### 4.5 Le tracé

1. **Bornes du rayon** : la pré-passe rastérise la peau (profondeur `t_skin`) ; une passe rastérise les **boîtes des chunks qui contiennent au moins une brique visible** (non `skin` : arbres, bâti, terrain creusé ; quelques milliers) et garde la distance d'entrée la plus proche `t_enter` (profondeur `Depth32Float` en Z inversé, effacée à 0 = « aucune boîte », convertie en distance dans le tracé). Un pixel qu'aucune boîte ne couvre ne lance aucun rayon (ciel, terrain nu sous sa peau). **Caméra dans une boîte** (cas fréquent : on marche dans la forêt) : les faces avant ne couvrent pas tout ; si le chunk de la caméra ou l'un de ses 26 voisins contient une brique visible, la cible est effacée à « tout près » et tous les rayons partent de la caméra (la traversée saute vite les chunks vides).
2. **Traversée** de `t_enter` à `t_skin` : DDA de Amanatides et Woo par niveau (chunks, puis briques avec le masque de 512 bits du chunk, puis voxels avec le masque de la brique), en cellules entières et distances `f32` relatives à la caméra (aucune perte de précision à 20 km : la caméra est un voxel entier plus une fraction). Quand le rayon sort du cube du niveau L, il continue au niveau L + 1 ; c'est ce qui fait le LOD. Sur les 10 % externes d'un niveau, le passage au niveau suivant est tiré au hasard (bruit bleu) pour fondre la transition sous le TAA.
3. **Briques de peau** : si le pixel a une peau (`t_skin` fini), la traversée lit le masque des briques **visibles** : les briques `skin` sont vides pour elle, sans test brique par brique (la peau, lisse, les recouvre) ; si le pixel n'a pas de peau (bord d'un trou), elles sont opaques et montrent leurs faces voxel, ce qui ferme les trous de la transition.
4. **Sortie** : distance, niveau, coordonnée du voxel, face touchée, point d'impact, valeur (classe + teinte). Le même shader écrit le G-buffer après l'évaluation de la matière (§ 4.6). Une caméra à l'intérieur d'un voxel plein voit la face d'entrée.
5. La même fonction `trace()` (fichier `voxel_trace.wgsl`) sert, avec d'autres bornes et un autre **mode**, aux cascades d'ombre, à l'AO, aux sondes, aux ombres des lumières et aux reflets de l'eau. Modes : `PRIMARY` (règle du point 3), `SHADOW_MAP` (briques `skin` ignorées : la peau est rastérisée dans la cascade, ce qui évite l'acné d'une peau lisse sur une occupation en marches), `OCCLUSION` (AO, sondes, lumières ponctuelles, ombres de contact, reflets : briques `skin` opaques, départ décalé d'au moins un voxel du niveau selon la normale).

### 4.6 Le shader de matière : sans chanfrein, continu en coordonnées monde (P60)

Ce que Monsieur a refusé (`pas bon chaux.png`, maison JS) : un biseau sur chaque voxel et une couleur au hasard par voxel, qui font une **mosaïque** ; et les murs blanchis à la chaux. Ce qu'il veut (`bon pierre.png`, images de style) : des pièces (pierres, planches, poutres) lisibles, chacune d'une seule matière, en pixels de 5 cm.

Évaluation, pour un voxel touché (ou un point de la peau) :

1. **Couleur du voxel (le « pixel »)** : un champ **continu en coordonnées monde**, évalué **au centre du voxel** du niveau affiché. Deux voxels voisins d'une même pièce ont des couleurs corrélées (le fil d'un bois court sur toute la poutre) ; la couleur est constante sur la face (pixel art). Le champ dépend de la classe et de la teinte :
   - **bois** : la teinte porte l'**axe du fil** (x, y, z) et une variante ; veines = bruit étiré le long de l'axe (≈ 0,3 cycle/m le long, ≈ 8 cycles/m en travers) ;
   - **pierre** : la teinte porte un **numéro de pièce** (haché) ; chaque pierre a sa nuance et son grain ; le joint n'existe qu'entre deux pièces différentes (assombrissement près du bord quand le voxel voisin dans le plan est d'une autre pièce : jamais entre deux voxels d'une même pièce) ;
   - **végétation** : la teinte porte l'**essence et une variante** (écorce, écorce secondaire, rameau ; rampe de fleur ou de fruit) ; la **rampe des feuilles** est tirée au shader comme dans `voxel_tree.py` (bruit lent à 0,55 et 1,3 m⁻¹ + gigue), et la nuance reprend la logique validée sans ombrage cuit (`tval = 0,10 + 0,80 × 0,6 + (bruit 5 m⁻¹ − 0,5) × 0,22 + gigue × 0,14`), avec les fissures d'écorce (bruit étiré verticalement à 4 et 9 m⁻¹). Même fonction de bruit de valeur que Python (mêmes multiplicateurs de hachage), mais en coordonnées **monde** et avec une **graine par essence** (le shader ne connaît pas la graine de chaque arbre) : deux chênes voisins ont des champs différents parce qu'ils sont à des endroits différents. On compare donc des **distributions** de couleurs avec Python, pas des voxels un à un ;
   - **terrain** : rampe de 128 nuances, variante par bruit lent.
   Une **gigue par voxel** faible (hachage du voxel, amplitude par matière, réglable dans `style.toml`) garde le grain pixel sans mosaïque.
2. **Détail bitmap sous-voxel** : une couche de détail par matière (luminance, hauteur, rugosité ; textures CC0 d'ambientCG ou Poly Haven, choisies en L22), projetée sur le plan de la face (les faces sont alignées sur les axes : pas de mélange triplanaire) avec des coordonnées **monde**, donc continue d'un voxel à l'autre. Amplitude faible (≤ 15 % en luminance par défaut), fondue avec la distance (question Q3).
3. **Relief** : hauteur = détail bitmap + bruit procédural, en coordonnées monde ; normale par **différences finies** dans le plan de la face (3 évaluations, pas de dérivées d'écran : le tracé est en compute). Rien ne dépend des coordonnées locales du voxel : **aucun biseau, aucune couture**.
4. **Rugosité** (base + variation), **translucidité** (feuilles : lumière transmise en contre-jour, épaisseur estimée par l'occupation voisine), **émission** (braises, verre de lanterne, en HDR, avec scintillement haché).
5. **Usure** : mousse sur les faces tournées vers le ciel et peu exposées (occupation des 26 voisins au niveau 0, lue dans les masques déjà en cache), salissure dans les recoins.

La matière vient d'une table GPU (512 entrées de 64 o, 19a § 5) construite depuis `engine/data/materials.csv` (physique, inchangée, ajout seul) et un nouveau `engine/data/material_render.toml` (aspect). Une **référence CPU** (`em_material::eval_albedo_cpu`) permet de tester le shader pixel par pixel.

### 4.7 Le lointain

Au-delà du niveau 5 (≈ 820 m) : la peau du terrain continue en hauteurs (CDLOD sur le plan macro, phase 1) jusqu'à l'horizon, et les forêts deviennent une **canopée** (couleur et hauteur ajoutées à la peau). Les maisons y font moins d'un pixel par voxel de 1,6 m. Les imposteurs classiques (cartes octaédriques d'arbres) ne sont pas nécessaires en deçà de 820 m, puisque la clipmap porte déjà les LOD ; ils restent en réserve si la canopée ne suffit pas. Question Q8.

### 4.8 Ce qui reste rastérisé en voxels

Les **corps mobiles** (porte qui pivote, table en train d'apparaître, débris qui tombent) ne sont pas dans la clipmap : maillage glouton binaire (`em_mesh`, quads de 8 o), même fonction de matière au fragment, tracés aussi dans la cascade d'ombre la plus proche. Hors laboratoire (phase 5), mais l'interface est posée.

---

## 5. La lumière

### 5.1 L'image, passe par passe

```
 1 téléversements ─► 2 ciel (LUT, nuages, cube, soleil) ─► 3 cascades d'ombre (tuiles sales)
 4 pré-passe peau (profondeur) ─► 5 boîtes des chunks visibles (t_enter) ─► 6 TRACÉ PRIMAIRE (compute → G-buffer)
 7 fusion des profondeurs + HiZ ─► 8 G-buffer peau (profondeur égale) ─► 9 herbe et fleurs (élimination HiZ, dessin indirect)
10 AO proche ─► 11 sondes DDGI ─► 12 ÉCLAIRAGE (tuiles de lumières, puis compute → HDR, fond de ciel)
13 eau (reflets tracés, surface, réfraction) ─► 14 brume volumétrique ─► 15 TAA ─► 16 bloom ─► 17 AgX ─► surimpression (débogage, hors budget)
```

G-buffer (formats acceptés en écriture de stockage ET en cible de rendu, pour que compute et raster écrivent les mêmes textures) : `GB0 rgba8unorm` albédo encodé sRGB à la main + occlusion de matière ; `GB1 r32uint` normale octaédrique 2 × 16 bits ; `GB2 rgba8unorm` rugosité, translucidité, émission, drapeaux ; `GB3 r32uint` mouvement (deux demi-flottants) ; profondeur `Depth32Float` en **Z inversé** infini (comme `web-ocean`) ; `R32Float` distance du tracé. Détail en 19a § 5.

### 5.2 Ciel et atmosphère (reprise de `web-ocean`, MIT, © Maksymilian Dendura)

Repris presque tels quels (`/home/samuelpyrat/Téléchargements/web-ocean-main/js/wgsl/`) : `ATMO_CORE_WGSL` (milieu, sphères, phases), `TRANS_LUT` (256 × 64), `MS_LUT` (32²), `SKYVIEW_LUT` (256 × 144), `SKY_RENDER_FUNCS` (radiance, disque solaire), `SKY_CLOUD_FUNCS` (deux couches de nuages plates, ombrées, bords anticrénelés), `ENV_CUBE` + `CUBE_MIPS` (256² × 6, 9 niveaux), `SUN_VIS` (transmittance des nuages vers le soleil), `BLOOM_DOWN`/`BLOOM_UP`, `COMPOSITE` (AgX, regard, vignette, tramage). Adaptations : les gabarits JS (`${N}`, `${CASCADES}`) deviennent des constantes WGSL ; les mises en page « auto » deviennent explicites ; la struct `Frame` est réécrite pour notre moteur ; l'atmosphère reste en km et la caméra en m ; le cube d'environnement est rafraîchi d'une face par image (le ciel change lentement). Licence copiée à côté des shaders. Position du soleil : jour de l'année, heure, latitude du monde (D30 : 1 jour = 1 h 30 réelle).

### 5.3 Ombres du soleil en cascades stables (P61)

- **Quatre cascades** (préréglage `haut` : 4096² jusqu'à ≈ 12 m, soit un texel d'≈ 0,6 cm et 8 texels par voxel ; 2048² jusqu'à ≈ 40 et 120 m ; 1024² jusqu'à ≈ 400 m) + une **cinquième, terrain seul** (1024², plan macro, jusqu'à ≈ 3 km) pour les ombres des montagnes au couchant.
- **Stables** : centre de chaque cascade aligné sur ses texels dans le repère du soleil, rayon fixe (sphère englobante de la tranche), donc aucun scintillement quand la caméra tourne ou avance.
- **Remplies par la même géométrie que l'image** : pour chaque tuile sale, (1) la peau est rastérisée en profondeur, (2) un triangle plein écran trace dans la clipmap, depuis le soleil, un rayon par texel en mode `SHADOW_MAP` (briques `skin` ignorées) et écrit `frag_depth` (test de profondeur : on garde le plus proche). Format `Depth16Unorm` (filtrage PCF matériel par comparaison).
- **Générations** : la direction du soleil est figée par génération (période 0,5 s en `haut`, 1 s en `moyen`) ; une génération se remplit par tuiles en arrière-plan ; l'éclairage échantillonne les deux dernières générations complètes et les fond dans le temps ; trois tampons. Le soleil tourne de 0,067 °/s (D30) : en 0,5 s, l'ombre d'une cime à 20 m bouge d'≈ 1,2 cm, moins qu'un quart de voxel [Calculé]. Quand le temps est accéléré (débogage), la période se compte en angle de soleil (≤ 0,033° par génération) dans la limite d'une génération par image, et le fondu entre générations masque le reste.
- **Tuiles sales** aussi quand la caméra fait glisser une cascade (seule la bande neuve) et quand une édition touche une boîte (projetée dans chaque cascade).
- **Échantillonnage** : pénombre douce à la taille du disque solaire (PCSS) en `haut`, PCF 3 × 3 tourné en `moyen` ; décalage selon la normale d'environ un voxel (feuilles : pas d'acné) ; plus des **ombres de contact** (rayons voxel de ≤ 60 cm, mode `SHADOW_MAP`, pleine résolution en `haut`) pour les arêtes nettes de près.
- Les mêmes cascades servent à la brume (§ 5.6), à l'eau et aux sondes.

### 5.4 Occlusion et lumière indirecte tirées de la grille voxel

| | Cascades de radiance 3D | **Sondes DDGI tracées dans la grille voxel** | Cônes voxel (VXGI) | AO seule + grille de ciel (prototype village) |
|---|---|---|---|---|
| Coût sur cette carte | ≈ 1 à 2 ms ; mémoire lourde en 3D monde ; recherche récente, la version écran perd le hors-champ | **≈ 0,25 ms par tranche de 4 096 sondes × 64 rayons par image** ; 0,50 ms en `haut` (8 192) [Estimé] | voxélisation de la radiance + mips + 5 à 9 cônes par pixel : ≈ 2 à 3 ms [Estimé] | ≈ 0,15 ms |
| Mémoire | élevée | ≈ 63 Mo (3 niveaux) | 3D mipmappé | 1 o par cellule |
| Rebond coloré, plusieurs rebonds | oui | oui (accumulés dans le temps) | oui | non |
| Fuites à travers les murs | faibles | possibles, car un mur de 30 cm est plus mince que la maille d'1 m : contrôlées par la visibilité (moments de profondeur), le classement des sondes et un niveau de 0,5 m dans les bâtiments | moyennes | — |
| Destruction | à recalculer | s'adapte seule en ≈ 0,5 s | revoxéliser | propagation locale |
| Difficulté pour un agent | élevée | moyenne (algorithme publié, bien décrit) | élevée | faible |

**Choix** : **sondes DDGI** (trois niveaux centrés sur la caméra : 1 m, 4 m, 16 m d'espacement, 32 × 16 × 32 sondes par niveau, soit 49 152, plus un niveau de 0,5 m (16 × 8 × 16) posé sur les bâtiments proches ; irradiance en octaèdre 6 × 6 + bordure, visibilité 14 × 14 + bordure, toutes deux en `r32uint` empaqueté (19a § 5.5) ; 8 192 sondes par image en `haut`, 64 rayons chacune, donc chaque sonde rafraîchie toutes les 6 images (0,1 s) ; sondes à l'intérieur du plein désactivées, puis déplacées) **plus une occlusion proche tracée** (rayons de ≤ 2 m dans les niveaux 0-1, 4 rayons par pixel en demi-résolution en `haut`, accumulation temporelle et un débruitage bilatéral) pour les recoins entre voxels, que les sondes ne voient pas. L'AO proche ne multiplie que ce qui est plus court que la maille des sondes (pas de double comptage). Les rayons des sondes voient le soleil (cascades), le ciel, l'émission des voxels et les lumières ponctuelles : une lanterne éclaire aussi par rebond.

### 5.5 Lumières ponctuelles ombrées

Lumières déclarées par les recettes (lanterne, feu, forge) via `GenPlan::lights()`. Découpage en tuiles 16 × 16 (compute) ; dans l'éclairage, les **8 lumières les plus fortes d'une tuile** (4 en `moyen`, 2 en `bas`) tracent un rayon d'ombre dans la grille voxel (niveaux 0-1, borné par le rayon de la lumière) ; les autres ne sont pas ombrées. C'est l'occupation voxel qui empêche la lumière intérieure de sortir par les murs (le générateur JS séparait intérieur et extérieur à la main). Feux : intensité scintillante hachée.

### 5.6 Brume volumétrique, rayons de soleil, perspective aérienne

Froxels 160 × 90 × 128 en `haut` (64 tranches en `moyen` ; profondeur exponentielle jusqu'à ≈ 300 m) : densité (brume de hauteur + bruit lent + densités locales injectées : embruns de cascade, fumée de cheminée), lumière du soleil × cascade d'ombre (c'est ce qui dessine les **rayons**), phase de Henyey-Greenstein, ciel par les sondes ou les harmoniques du ciel, lumières ponctuelles (en `haut` : les lanternes dessinent leur halo dans la brume) ; gigue temporelle et reprojection ; intégration avant-arrière ; au-delà, la perspective aérienne de Hillaire. Appliquée à la scène et à l'eau.

### 5.7 TAA, bloom, AgX

TAA : gigue de Halton (2, 3) sur 8 phases, reprojection par la profondeur pour le monde statique, vecteurs de mouvement pour l'herbe, l'eau et les corps mobiles ; écrêtage de variance en YCoCg ; historique en Catmull-Rom ; rejet des désocclusions (édition). Le pixel art supporte mal le flou : la netteté est un réglage de style (question Q9). Bloom et AgX de `web-ocean` (Karis, 6 niveaux, regard et tramage).

### 5.8 Ce qu'on baisse d'abord

Voir § 1.4 : ordre de baisse et colonnes des trois préréglages. Chaque passe expose ses réglages (`QualityKnob`) ; les préréglages `haut` (≈ 5,4 ms de passes + 1,0 ms de réserve, dans la cible de 6,5 ms), `moyen` (≈ 3,7 ms) et `bas` (≈ 2,6 ms) sont étalonnés en L29 sur la scène de synthèse, et le plafond dur de 8,3 ms n'est jamais dépassé en médiane.

---

## 6. Terrain, herbe et fleurs, eau

### 6.1 La peau du terrain (P66)

- **Densité analytique, pas l'occupation** : surface nets sur l'occupation binaire donnerait des terrasses de 5 cm sur les pentes douces (une marche tous les 2,5 m sur 2 % de pente) [Calculé]. La peau est donc maillée sur la **densité continue du générateur** (`DensityField`, Q16), là où le terrain n'est pas édité. L'occupation voxel (pour la physique et l'ombre) est la même densité échantillonnée au centre des voxels.
- **Maille** : 4 voxels du niveau (20 cm au niveau 0, réglable de 2 à 8) ; normale par le gradient analytique ; ≈ 512 triangles par chunk de surface [Calculé]. La finesse de 5 cm vient de la matière, pas de la géométrie.
- **Pixel art sur une peau lisse** : la matière d'un point de peau est celle du **voxel juste sous la surface**, lu dans la clipmap (même valeur que si l'on creusait), évaluée par la même fonction que les faces voxel, projetée sur l'axe dominant avec une transition tramée. Deux modes, à trancher sur captures (question Q2) : `cellule` (une matière par cellule de 5 cm, pixel art strict) et `mélange` (poids des 4 cellules voisines avec mélange par hauteur du détail : le « mélange de matières » de la décision 5).
- **Zones creusées** : une brique éditée n'a plus de peau ; ses voxels sont tracés comme le reste (§ 4.5, point 3). Transition par brique de 40 cm, acceptée par Monsieur ; amélioration possible plus tard : exclusion par cellule.
- **Coutures entre niveaux** : jupes verticales de 2 cellules sur les bords de chunk dont le voisin est d'un autre niveau. Les surfaces de deux niveaux étant échantillonnées sur la même densité, l'écart est faible.
- **Collision** (hors labo) : la boîte du joueur contre l'occupation voxel ; la hauteur du sol par la densité analytique là où le terrain n'est pas édité (marche lisse sur la peau).
- **Paysage du labo** (`LabLandscape`) : 128 × 128 m faits main (collines, falaise rocheuse avec strates, cuvette d'étang, lit de ruisseau, marche de cascade), pas le générateur du monde de 20 km (question Q10).

### 6.2 Herbe et fleurs (P67)

- **Aucune donnée par brin côté CPU.** Le sol est découpé en tuiles de 4 × 4 m jusqu'à 80 m (`haut` ; 48 m en `moyen`). Chaque image, une passe compute élimine les tuiles (cône de vue, HiZ), choisit un LOD par distance et **génère les brins** de la tuile par hachage déterministe (grille stratifiée et gigue), lit la hauteur et la matière du sol dans une texture torique à deux niveaux (`GroundTiles` : 10 cm jusqu'à 51 m, 40 cm jusqu'à 205 m ; hauteur R16 + matière + drapeaux), applique les masques (classe `turf`, pente < 40°, pas d'eau, pas de brique éditée, chemins piétinés), écrit les instances et les arguments de dessin indirect.
- **LOD** : 0-8 m, brins de 15 sommets (courbes, deux faces) ; 8-24 m, 7 sommets et touffes ; 24-48 m, 3 sommets ; 48-80 m, touffes clairsemées de 3 sommets fondues dans la couleur de la peau ; au-delà, la peau suffit. Densité près de la caméra ≈ 400 brins/m² [Hypothèse], ≈ 100 000 instances dessinées en `haut` [Estimé].
- **Vent** : direction et force globales + texture de rafales qui défile ; flexion en Bézier dans le shader de sommets ; vecteurs de mouvement pour le TAA.
- **Fleurs** : maillages procéduraux par espèce (marguerite, coquelicot, bleuet, bouton d'or, lavande), générés au démarrage en Rust, en touffes (bruit lent), densité bien plus faible.
- **Ombrage** : dégradé de la base à la pointe, translucidité en contre-jour, occlusion à la base, normale fondue vers celle du sol au loin. **Pas de pixel art** (décision 3).

### 6.3 L'eau (P67)

- **Labo** : une `AnalyticWater` (niveau d'un étang, ruisseau le long d'une courbe, chute à une marche de la falaise) fournit des tuiles de 25 cm : niveau, vitesse, mousse, profondeur. En **phase 4**, un adaptateur sur le solveur `em_water` (volumes entiers par colonne, cellules 5/25 cm) fournit les mêmes tuiles : le rendu ne change pas.
- **Surface** : grille rastérisée sur les tuiles mouillées ; petites vagues de vent par **les cascades FFT de `web-ocean`** réduites à 2 ou 3 petites cascades (pas d'océan ici) ; **carte d'écoulement** à deux phases qui fait courir les rides et la mousse vers l'aval ; normales et rugosité anisotrope par les moments LEAN de `web-ocean` ; Fresnel (`fresnelWater`), éclats du soleil (pente gaussienne anisotrope + masquage de Smith), diffusion sous la surface aux crêtes en contre-jour.
- **Réfraction et absorption** : couleur de la scène derrière (copie HDR), décalée par la normale, atténuée par l'épaisseur d'eau (Beer-Lambert, turbidité réglable comme `waterCol` de `web-ocean`) ; mousse de rive selon la profondeur ; caustiques plus tard.
- **Reflets** : ciel par le cube d'environnement ; puis **rayons voxel en demi-résolution** pour les arbres et les maisons qui se reflètent dans l'étang (l'image de style le montre) ; réflexion d'écran en repli.
- **Cascade** : nappe rastérisée qui suit le profil de la chute, textures de mousse qui défilent, embruns injectés dans la brume (§ 5.6) et quelques particules.

---

## 7. Le harnais

### 7.1 Lancement

`engine-rs/scripts/lab.sh` (bash) : `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json`, `WGPU_BACKEND=vulkan`, et, pour la fenêtre sur ce portable hybride, `__NV_PRIME_RENDER_OFFLOAD=1` si la présentation échoue [Hypothèse, vérifiée en L02] ; puis `cargo run --release -p em_lab -- "$@"`. Le code choisit l'adaptateur **discret** dont le nom contient `EM_ADAPTER` (défaut « Quadro ») et **refuse** l'Intel ou `llvmpipe` avec un message qui dit quoi faire (pas de repli silencieux), sauf `--allow-any-adapter`. Le journal écrit le nom de la carte et la version du pilote. Attention : dans `wgpu` 30, `Instance::enumerate_adapters` est asynchrone. **Limites** : les valeurs par défaut de `wgpu` sont trop basses pour ce plan (4 textures de stockage et 8 tampons de stockage par étage de shader, 16 Kio de mémoire partagée, 128 Mio par liaison) ; l'hôte demande explicitement au moins 8 textures de stockage, 16 tampons de stockage, 32 Kio de mémoire partagée, 1 Gio par liaison et par tampon, et s'arrête avec un message clair si l'adaptateur refuse. La Quadro les accepte largement [Mesuré : `maxPerStageDescriptorStorageImages` et `…StorageBuffers` = 1 048 576, 48 Kio partagés, `maxStorageBufferRange` = 4 Gio].

### 7.2 Hors écran et captures

`em_lab capture --scene arbre --shot face --hour 17.5 [--frames 64] [--out …]` : même code que la fenêtre, cible hors écran 1920 × 1080 ; un nombre fixe d'images de chauffe (TAA, sondes, AO convergés) avec la même gigue, puis lecture (lignes alignées sur 256 o) et PNG sRGB, avec à côté un JSON (scène, prise, heure, style, empreinte du monde, carte, pilote, ms par passe). Sorties : `engine-rs/lab/captures/AAAA-MM-JJ/<scène>_<prise>_<heure>.png`. Les captures retenues pour Monsieur sont copiées dans `docs/apercus/NN_<nom>.png`.

### 7.3 Profilage GPU

`GpuProfiler` : horodatages au début et à la fin de chaque passe (`timestamp_writes` des passes de rendu et de calcul), résolution dans un tampon, lecture différée sur un anneau de 3 images, conversion par `Queue::get_timestamp_period()`. Rapport : médiane, p95, nombre d'échantillons par passe, total, plus les horloges SM et mémoire, la température et la puissance relevées par `nvidia-smi` pendant le banc (une carte de portable varie avec la chaleur). Affiché en surimpression dans la fenêtre.

### 7.4 Tests d'images de référence

`em_lab check-images` : rend chaque prise de `lab/reference/` et la compare à l'image approuvée par Monsieur. Métrique maison (pas de dépendance) : ΔE dans l'espace Oklab, moyenne ≤ 0,5 et 99e centile ≤ 3 ; plus un SSIM de luminance par blocs de 8 × 8 ≥ 0,98. `em_lab approve --scene … --shot …` remplace la référence, seulement après un « oui » de Monsieur noté dans `docs/19c_journal_style.md`.

### 7.5 Tests de déterminisme

- **Parité avec le C++** : vecteurs de `mix64`, `hash3`, `layer_seed`, CRC32, FNV-1a, et octets d'`Operation` v1, produits une fois par un petit programme C++ compilé sur les en-têtes du dépôt et épinglés dans les tests Rust.
- **Génération bit exacte** : empreintes de chunks épinglées pour des clés fixes (terrain, `.vxm` placés, recettes), égales avec `RAYON_NUM_THREADS=1` et `=8`, et dans un ordre de chunks mélangé.
- **Rejeu** : § 3.6.
- **Rendu** : deux captures successives sur la même carte et le même pilote : identiques octet pour octet tant qu'aucune passe n'utilise d'opération atomique dans un ordre variable ; sinon, ΔE Oklab maximum ≤ 1.

### 7.6 Bancs

`em_lab bench --scene foret_dense --frames 600 --warmup 120 --path orbit.toml --json …` : chemin de caméra fixe, réglages figés, rapport JSON comparable d'un jour à l'autre (`scripts/bench.sh` lance la suite : `arbre`, `mur_poutre`, `prairie`, `eau`, `foret_dense`, `village_mini`). Les bancs CPU (`cargo bench` ou tests chronométrés) couvrent la composition d'un chunk, le maillage de peau, l'application d'une opération et le plan d'un arbre.

### 7.7 Mode fenêtre interactif

Caméra libre (ZQSD/WASD, souris capturée, Maj ×5, molette = vitesse) ; heure (`[` `]`, `Ctrl` pour l'accélérer) ; **bascule des passes** (F1 à F12, sans recompiler) ; vues de débogage (albédo, normales, AO, sondes, cascades, LOD, coût par pixel) ; capture (F12 → même chemin que § 7.2) ; creuser (clic : `VoxelEdit blob` par le vrai bus, à partir de L19) ; **`lab/style/style.toml` rechargé à chaud** (exposition, regard AgX, bloom, brume, amplitudes de variation par matière, détail, relief, netteté du TAA, densité de l'herbe…) ; surimpression texte (ms par passe, réglages, heure). Pas d'`egui` au départ (§ 2.4).

### 7.8 Journal de style

`docs/19c_journal_style.md` : une ligne par décision prise avec Monsieur (date, capture, paramètre ou variante A/B, verdict, valeur retenue dans `style.toml`). Chaque tâche qui produit une capture pour Monsieur y ajoute la ligne « présentée », et la ligne « décidée » quand il a répondu.

---

## 8. Plan de tâches

Le détail (interface exacte, critère mesurable, taille, piège, capture attendue) est en **`docs/19b_taches_laboratoire.md`**. Résumé, dans l'ordre qui donne des aperçus le plus tôt :

| Phase | Tâches | Première capture pour Monsieur |
|---|---|---|
| A. Socle | L01 workspace + `em_core` ; L02 hôte (adaptateur, hors écran, fenêtre, PNG, profileur) ; L03 ciel de Hillaire + bloom + AgX ; L04 exporteur `.vxm` (Python) ; L05 `em_voxel` ; L06 `em_material` ; L07 comparateur d'images | **le ciel à 6 heures du jour (L03)** |
| B. Premier arbre | L08 chargeur `.vxm` + scène statique ; L09 premier rendu voxel (clipmap à un niveau, tracé, éclairage direct) ; L10 matière v1 (végétation de `voxel_tree`) | **le chêne 42 au soleil couchant (L09), à côté de l'aperçu Python (L10)** |
| C. Lumière | L11 cascades stables ; L12 TAA ; L13 panneau de style ; L14 AO proche ; L15 sondes DDGI | ombre tachetée, AO, rebond coloré |
| D. Sol | L16 densité + peau (CPU) ; L17 rendu de la peau ; L18 `em_ops` (opérations v1, bus local, journal) ; L19 `em_world` (deltas, creusement, rejeu) ; L20 herbe et fleurs | colline, trou creusé, prairie |
| E. Eau | L21 eau v1 (surface, écoulement, réfraction) | étang et ruisseau |
| F. Matière et bâti | L22 matière v2 (détail CC0, relief, joints) ; L23 recettes mur de pierre, poutre, poteau | **mur et poutre sans chanfrein, à côté de « pas bon chaux »** |
| G. Atmosphère | L24 brume et rayons ; L25 lumières ponctuelles, nuit | rayons dans la forêt, lanterne la nuit |
| H. Échelle | L26 clipmap 6 niveaux + LOD + **porte budgétaire forêt dense** ; L27 eau v2 (reflets tracés, cascade) ; L28 entités et opérations de recette, paquet `EMPK`, instantanés ; L29 scène de synthèse + préréglages + rapport budgétaire | panorama de forêt + tableau des ms ; bûches → table |
| I. Générateurs en Rust | L30 squelette Q16 ; L31 rastérisation, feuillage, couleurs, parité statistique avec Python ; L32 arbustes, topiaire, silhouettes lointaines | le même chêne, généré en Rust |

**Parallélisme** : L01, L02, L04 dès le départ ; L03 et L07 après L02 ; L05 et L06 après L01 ; L16 (sol, CPU) dès L05 et L06, et L18 (`em_ops`) dès L01, en parallèle des phases B et C ; après L09 : L10, L11, L12, L13 en parallèle (fichiers différents) ; après L17 : L19, L20, L21 en parallèle ; L22-L23 en parallèle de la phase C ; L30 dès L05 (CPU seul). Chemin critique : L01 → L05 → L08 → L09 → L11 → L15 → L25 → L29 (L29 attend toutes les passes ; la porte budgétaire L26 attend L09 et L17).

**Après le laboratoire** (hors de ce plan) : générateur du monde 20 km et écologie (phase 1), recette de maison portée de `gen_core.js` (phase 3), solveur d'eau repensé et rapatrié (phase 4), corps mobiles et effondrements (phase 5), `em_capi` et branchement des PNJ (phase 7).

---

## 9. Questions ouvertes pour Monsieur

| N° | Question | Recommandation |
|---|---|---|
| Q1 | **La réserve des personnages** : vous avez accordé 50 % du GPU au rendu (8,3 ms). Le plan vise 6,5 ms, dont 1 ms réservée aux personnages, au feu, aux particules et à l'interface qui viendront plus tard. Gardez-vous cette marge de 1,8 ms sous le plafond (pointes, chaleur du portable, IA qui tourne à côté), ou préférez-vous la dépenser tout de suite en qualité (herbe plus loin, brume plus fine) ? | Garder la marge : un portable chauffe, et l'IA partage la carte ; on la dépensera quand les personnages seront mesurés. |
| Q2 | **Le sol lisse en pixel art ?** La peau du terrain a-t-elle une matière par carré de 5 cm (pixel art strict, comme les murs) ou un mélange continu comme une photo (comme l'herbe) ? | Pixel art (vous avez dit « tout sauf l'herbe et les fleurs ») avec un léger mélange aux frontières ; captures A/B en L17. |
| Q3 | **Le détail dans un voxel** : voit-on un grain (fibres du bois, pores de la pierre) à l'intérieur d'un voxel de 5 cm, ou chaque voxel est-il d'une couleur unie ? | Grain visible mais faible (≤ 15 %), qui s'efface au-delà de 10 m ; captures A/B en L22. |
| Q4 | **Le vent sur les arbres voxel** : arbres immobiles (seul le feuillage scintille dans la lumière), ou balancement (qui déforme la grille des voxels) ? | Immobiles avec scintillement ; l'herbe et les fleurs ondulent. |
| Q5 | **Les joints des murs** : un léger joint sombre entre deux PIERRES (jamais entre deux voxels d'une même pierre), comme sur « bon pierre », vous convient-il ? | Oui, réglable en force ; jamais de biseau par voxel. |
| Q6 | **Les nuages** : deux couches plates de `web-ocean` (≈ 0,05 ms, très belles au couchant) ou nuages volumétriques (≈ 1 ms, hors budget) ? | Couches plates + ombres de nuages au sol. |
| Q7 | **Les textures CC0** (ambientCG, Poly Haven) : téléchargées par un script avec empreintes, sans les mettre dans git (dépôt léger), ou versionnées (≈ 100 Mo) ? | Script : le dépôt reste léger et les licences sont listées dans un manifeste. |
| Q8 | **Les arbres lointains** (au-delà de 100 à 200 m) : une silhouette simplifiée de la même essence, ou le vrai arbre complet (environ 10 fois plus de calcul processeur au chargement) ? Et au-delà de 800 m, une canopée sans voxels ? | Silhouette puis canopée ; vous jugerez sur le panorama de L26. |
| Q9 | **Netteté contre stabilité** : le TAA adoucit un peu les arêtes de voxel ; préférez-vous des arêtes plus nettes avec un léger scintillement ? | TAA doux avec un réglage de netteté ; captures A/B en L12. |
| Q10 | **Le terrain du labo** : un paysage fait main de 128 m (collines, falaise, étang, ruisseau, cascade) jusqu'à la validation du style, le générateur du monde de 20 km venant après ? | Oui : le style d'abord, la géographie ensuite. |
| Q11 | **Le rythme des aperçus** : une planche PNG par tâche visuelle (heures fixes : 10 h, 17 h 30, 19 h, nuit), avec 2 ou 3 questions précises, vous convient-il ? | Oui ; vos réponses vont dans `docs/19c_journal_style.md`. |
