# VXB3 : proposition de mise en page (question I-1 de interfaces.md)

Proposé par le fil « Village voxelisé jouable », le 8 octobre 2026. C'est le fil moteur qui tranche. Base : VXB2, le format du prototype, décrit dans `outils/pack_world.py`.

## Ce qui change par rapport à VXB2
1. Les classes sont celles de `engine/data/materials.csv`, avec la table de correspondance du § 2. Le packer convertit les classes à l'écriture.
2. Un champ `schema_version` et la version de `materials.csv` utilisée.
3. Les axes sont ceux du monde (x est, y haut, z nord). Le packer passe du glTF au monde avec `z_monde = -z_gltf`. Les deux repères sont de sens opposé, donc la géométrie reste la même et n'est pas réfléchie. Chaque module porte son origine en voxels par rapport à son pivot.
4. La palette locale d'une brique n'est plus limitée à 15 couleurs. VXB2 en arrondissait l'excédent à la teinte la plus proche.
5. L'ordre des voxels dans une brique et des briques dans un module suit `chunk.h` : x le plus rapide, puis z, puis y. VXB2 utilisait x, puis y, puis z. Le lecteur C++ peut ainsi copier une brique telle quelle dans un chunk.

## Mise en page (petit-boutiste, fichier entier compressé en gzip)

```
En-tête
  char[4]  magic = "VXB3"
  u16      schema_version = 1
  u16      materials_schema_version      (version de materials.csv : 1)
  u16      flags                          (bit 0 : section de rampes présente)
  u16      n_modules

Section de rampes (seulement si flags bit 0, provisoire tant que I-3 n'est pas tranchée)
  u16      n_ramps
  n_ramps × { u16 class ; u8 rgb[128][3] }    (sRGB, teinte 0..127)

Modules, n_modules fois
  u8       name_len ; char name[name_len]   (snake_case, § 8)
  i32      origin[3]   (voxels, coin min de la grille par rapport au pivot du module, axes du monde)
  u16      dims[3]     (voxels)
  u32      n_bricks    (= ceil(dx/8)·ceil(dy/8)·ceil(dz/8), sert de contrôle)
  briques dans l'ordre bx le plus rapide, puis bz, puis by :
    u8 tag
    tag 0 : brique vide
    tag 1 : uniforme   → u16 voxel_id
    tag 2 : palette    → u8 k (1..255, entrées non vides) ; u16 ids[k] triés croissants ;
                         512 index de b bits, b = plus petit de {1,2,4,8} tel que k+1 ≤ 2^b ;
                         index 0 = air, index i = ids[i-1] ; voxels dans l'ordre x, puis z, puis y ;
                         bits remplis depuis le bit de poids faible de chaque octet
    tag 3 : brut       → u16 voxel_id[512]  (si plus de 255 valeurs distinctes)

Pied de fichier
  u32      crc32 de tout ce qui précède (non compressé)
```

## Remarques
- Avec b = 4 et un ordre x, z, y, la palette à 15 couleurs de VXB2 devient un cas particulier du tag 2. La conversion VXB2 → VXB3 est donc sans perte.
- Le placement des modules dans le monde n'appartient pas à VXB3. Je propose un fichier d'instances séparé, VXI, avec : nom du module, position i32 × 3 en voxels, rotation en quarts de tour autour de y (u8). Le générateur de village du prototype le produit déjà en mémoire (environ 2 000 instances).
- Taille attendue : la même que VXB2 (6,3 Mo en gzip pour les 47 pièces), plus quelques briques où l'arrondi à 15 couleurs disparaît.
- Côté prototype : dès que le fil moteur valide, le packer écrit VXB3 et la page de jeu le lit. Le moteur WebGL garde en interne son atlas en index de 4 bits et réduit à la volée les rares briques à plus de 15 couleurs. Ce compromis reste propre au rendu du navigateur.
