# voxelizer — modèle 3D texturé → voxels pleins, 1 voxel = 1 entité, **ultra-léger**

Entrée : `.obj` / `.gltf` / `.glb` (+ textures). Sortie : un modèle de voxels de 2 cm (réglable), remplis, colorés d'après les
textures, avec **couleur + ID matériau par voxel**, où chaque voxel est une entité (`Voxel`) ; exports JSON, GLB (1 nœud/voxel)
et **VXP**, un format hybride compact avec accès aléatoire `get(x,y,z)`.

```
pip install -r requirements.txt                       # numpy, scipy, Pillow
python app.py                                         # menu interactif dans le terminal
python app.py web --folder ~/Emergence/OBJ            # interface web locale (navigateur)
python -m voxelizer Prop_Crate.obj -o out --vxp       # ligne de commande (+ --glb, --scale 10, --palette 32 ...)
python -m unittest discover -s tests                  # 50 tests
```
Les textures : placez les PNG dans `Textures/` à côté du dossier OBJ (ou `--texture-dir`). **Dans le zip fourni, seule
`T_MetalOrnaments_BaseColor.png` manquait** : une texture de substitution la remplace (9 pièces d'ornements métalliques).

## Architecture
| Module | Rôle |
|---|---|
| `loaders.py`, `scene.py` | OBJ/MTL, glTF/GLB, textures linéaires + mipmaps ; détection des pointeurs Git LFS |
| `scaling.py` | échelle (unité, facteur, taille imposée) + prévision de taille avant calcul |
| `surface.py`, `refine.py` | surface conservative exacte (SAT), couleur moyenne ou **matériau dominant**, retrait du débord (parité de rayons) |
| `solid.py` | remplissage, bouchage de trous (dilatation + fermeture morphologique), budgets mémoire |
| `style.py`, `ao.py` | direction artistique en OKLab : palette k-means, netteté, saturation, contraste, AO cuite |
| `render.py` | rendu soigné : AO interpolée, ombres portées, sol, contour, tone mapping |
| `model.py`, `exporters.py` | entités `Voxel` (couleur, matériau, faces exposées, voisins, destruction) ; JSON, GLB |
| **`compact.py`** | **format VXP** (bricks adaptatifs + palettes + RLE + dédup + blocs compressés + coque seule) |
| `app.py` | application terminal + web |

## Stockage ultra-léger : méthode, benchmark, résultats
**Recherche (état de l'art)** : découpler géométrie et attributs (Dado et al. 2016, DAG d'attributs ; Dolonius, compression des
couleurs de surfaces voxélisées) ; conteneurs hybrides adaptatifs tableau/bitmap/runs (Roaring) ; conteneurs à palette bit-packée
avec cas « valeur unique » (sections de chunk des jeux voxel) ; surface seule en colonnes de « slabs » (Voxlap KVX/KV6).

**Candidats mesurés** (`tools/bench_compact.py`, détails dans `docs/benchmark_encodages.md`) : grille dense, liste x,y,z,couleur,
Morton + écarts (varint, Elias-Fano, borne d'entropie), colonnes RLE, KV6-like, SVO, SVDAG, plaques 2D dédupliquées,
**chaîne relative** (votre idée), bricks 4³/8³/16³ (VXP). Chaque ligne est marquée *mesurée* (encodeur + décodeur, aller-retour vérifié)
ou *calculée* (taille exacte déduite de la structure).

**Enseignement 1 — la géométrie est presque gratuite, les attributs la dominent.**
| pièce | VXP géométrie | SVDAG géométrie | chaîne 26-voisins DFS (surface) | écarts Morton varint | VXP couleur+matériau | tuiles 8×8 uniques |
|---|---:|---:|---:|---:|---:|---:|
| Mur_fenetre | 1,716 o (0.43 b/vox) | 2,426 o (0.61 b/vox) | 2,201 o (0.55 b/vox) | 38,364 o (9.62 b/vox) | 22,313 o (5.59 b/vox) | 846 / 850 |
| Porte | 3,627 o (1.30 b/vox) | 8,546 o (3.05 b/vox) | 3,028 o (1.08 b/vox) | 26,658 o (9.52 b/vox) | 13,231 o (4.73 b/vox) | 495 / 495 |
| Caisse | 8,213 o (0.49 b/vox) | 14,258 o (0.84 b/vox) | 5,224 o (0.31 b/vox) | 160,713 o (9.51 b/vox) | 85,244 o (5.04 b/vox) | 2,308 / 2,566 |
| Toit | 74,441 o (2.69 b/vox) | 105,815 o (3.83 b/vox) | — | 264,074 o (9.56 b/vox) | 135,656 o (4.91 b/vox) | 7,016 / 9,883 |
| Mur_ferme_seal11 | 6,537 o (0.30 b/vox) | 12,214 o (0.56 b/vox) | 4,808 o (0.22 b/vox) | 208,626 o (9.52 b/vox) | 99,799 o (4.55 b/vox) | 2,436 / 3,370 |
| Brique_x5 | 6,999 o (0.23 b/vox) | 14,764 o (0.48 b/vox) | 3,648 o (0.12 b/vox) | 291,678 o (9.51 b/vox) | 84,792 o (2.76 b/vox) | 2,886 / 4,407 |

**Enseignement 2 — votre idée de positions relatives.** Version littérale (x,y,z ∈ {−1,+1} par rapport au voxel précédent) :
impossible à généraliser, car chaque pas change la parité des trois coordonnées, donc la chaîne n'atteint qu'une sous-grille :
**au plus 25 % des voxels** de chaque pièce (mesuré). Version généralisée (26 voisins, parcours en profondeur
avec retour arrière) : **excellente en stockage pur** (colonne ci-dessus : souvent moins d'un bit/voxel), mais sans accès aléatoire direct :
il faut des ancres (≈1,5 bit/voxel pour une ancre/64 voxels) et un index spatial, ce qui annule le gain face à VXP, et le parcours est
séquentiel. Le principe « relatif » est conservé là où il paie : le répertoire de bricks est codé en **écarts de Morton**.
Comme la géométrie pèse peu (≈ 5-10 % du total), je ne l'ai pas rendue plus complexe.

**Enseignement 3 — les « planches » de texture par déduplication EXACTE ne marchent pas ici.** Les textures réelles, quantifiées en
palette, se répètent peu à l'identique (colonne « tuiles 8×8 uniques » : 65 % à 100 % de tuiles uniques selon la pièce ; la brique ×5 en répète le plus, avec 35 % de doublons, trop peu pour battre les palettes locales). Ce qui marche :
**palettes locales par brick** + **valeurs uniques** + **compression par blocs**. La piste suivante, non réalisée : tuiles
quantifiées avec perte, ou prédiction « matériau + position » (texture procédurale triplanaire) avec résidu.

**Enseignement 4 — compression par blocs : on garde l'accès aléatoire.** Chaque bloc de 64 bricks est compressé indépendamment (zlib ou
lzma) ; `get()` ne décompresse que le bloc visé. Gain ×1,6 à ×2,4 par rapport au brut.

### Résultats du format VXP (tailles sur disque)
| pièce | voxels | JSON .gz (avant) | VXP brut | VXP zlib/blocs | VXP lzma/blocs | **VXP coque+lzma** | bits/voxel (coque) | gain vs JSON |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Mur_fenetre | 31,914 | 174.8 Ko | 20.7 Ko | 14.4 Ko | 13.8 Ko | **13.5 Ko** | 3.47 | ×13 |
| Porte | 22,392 | 122.6 Ko | 16.7 Ko | 11.6 Ko | 11.0 Ko | **9.0 Ko** | 3.29 | ×14 |
| Caisse | 135,251 | 700.9 Ko | 91.9 Ko | 54.9 Ko | 49.1 Ko | **19.2 Ko** | 1.16 | ×37 |
| Toit | 221,015 | 1.2 Mo | 221.4 Ko | 135.8 Ko | 126.7 Ko | **85.1 Ko** | 3.15 | ×14 |
| Mur_ferme_seal11 | 175,351 | 964.3 Ko | 112.7 Ko | 51.2 Ko | 44.3 Ko | **23.8 Ko** | 1.11 | ×41 |
| Brique_x5 | 245,424 | 1.2 Mo | 90.8 Ko | 35.1 Ko | 29.7 Ko | **10.6 Ko** | 0.35 | ×112 |
| Brique_x10 (2 mm) | 1,969,532 | 10.1 Mo | 451.0 Ko | 161.4 Ko | 120.7 Ko | **41.0 Ko** | 0.17 | ×241 |

Brique_x10 : valeurs mesurées lors du développement (même format). « coque » = voxels visibles seuls + liste des poches de vide closes ;
l'intérieur est reconstruit au chargement par remplissage.

### Utilisation en code
```python
from voxelizer import *
res = VoxelizationPipeline(VoxelizeConfig()).run("Prop_Crate.obj")
data = pack_model(res.model, shell_only=True, compress="lzma")    # octets VXP
open("crate.vxp", "wb").write(data)
p = VoxelPack(data)
p.get(10, 4, 7)             # (indice couleur, indice matériau) ou None ; ne décode que le bloc concerné
p.palette, p.materials      # palette RGBA, noms de matériaux
model = p.to_model()        # entités Voxel (intérieur reconstruit)
```
Attention : sur un fichier « coque », `get()` ne voit que les voxels stockés (les visibles) ; `arrays(fill=True)`/`to_model()` reconstruisent l'intérieur.

### Compromis du mode « coque seule »
Géométrie : **exacte** (tous les voxels, noyau compris). Couleur + matériau : **exacts pour tout voxel visible** ; pour les voxels
enfouis, reconstruits par « voisin visible le plus proche », donc **approchés** (couleur intérieure identique à 41 %, 81 %, 62 % sur
caisse, brique ×5, mur scellé ; matériau identique à 100 %, 100 %, 87 %). Le mode « plein » est exact partout.

## Limites connues
- **Non traité** : le village entier (inventaire à 2 cm : 176 pièces, 168 voxélisées, 8 ignorées car trop grandes, 0 en erreur ; elles n'ont pas été rendues ni compressées une à une) ;
  les très grands toits (> 30 M cellules) ; le budget d'entités Python est de 3 M (le VXP, lui, n'a pas cette limite côté stockage).
- La **loi cubique** : ×10 d'échelle = ×1000 de voxels ; seules les petites pièces montent à ×10.
- **Murs ouverts du kit** : deux feuilles sans volume fermé ; `--seal 11` les remplit à ~55 % d'une dalle pleine (non vérifié que ce
  soit le bon volume) ; la fermeture aplanit les creux < 2×rayon.
- Les temps d'accès `get()` mesurés (20-55 µs) sont ceux de **Python** : le format est prévu pour une lecture native (C/C++/Rust).
- La vigne n'a **aucune information de couleur** dans le kit (texture = alpha seul) : elle reste d'une couleur uniforme.
- Le rendu soigné est de l'aperçu ; les voxels exportés gardent leur couleur plate (l'éclairage reste à faire côté moteur de jeu).
