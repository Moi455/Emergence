
### Mur_fenetre : 31,914 voxels (dont 297 intérieur), boîte (101, 157, 21)

| encodage | octets | bits/voxel | vs JSON .gz | statut |
|---|---:|---:|---:|---|
| JSON .gz (export actuel) | 179,061 | 44.89 | ×1.0 | mesuré |
| liste x,y,z,couleur brute | 127,656 | 32.00 | ×1.4 | calculé |
|   + lzma | 13,200 | 3.31 | ×13.6 | mesuré |
| grille dense (octet/cellule) | 332,997 | 83.47 | ×0.5 | calculé; boîte (101, 157, 21) |
|   + lzma | 16,936 | 4.25 | ×10.6 | mesuré |
| Morton: écarts varint + ancres/64 (géométrie) | 38,364 | 9.62 | ×4.7 | calculé |
|   Elias-Fano (géométrie, borne sans ancres) | 36,331 | 9.11 | ×4.9 | calculé |
|   entropie ordre 0 des écarts (borne) | 11,933 | 2.99 | ×15.0 | calculé |
| colonnes RLE (axe x) géom+couleur | 49,704 | 12.46 | ×3.6 | calculé |
| KV6-like surface seule (axe y) | 65,355 | 16.38 | ×2.7 | calculé; intérieur à reconstruire |
| SVO pointeurs+couleur feuilles (collapse uniforme) | 97,230 | 24.37 | ×1.8 | calculé; 10,886 nœuds, 31,914 feuilles |
| SVDAG géométrie seule | 2,426 | 0.61 | ×73.8 | calculé; 154 nœuds uniques |
|   + couleurs (flux Morton) + index | 32,530 | 8.15 | ×5.5 | calculé; total attributs; ajouter la ligne au-dessus |
| plaques 2D 4x4 dédup (axe z) exact | 44,219 | 11.08 | ×4.0 | calculé; 2,342 tuiles uniques / 2,678 |
| plaques 2D 8x8 dédup (axe z) exact | 55,890 | 14.01 | ×3.2 | calculé; 846 tuiles uniques / 850 |
| VXP bricks 4³ couleur+matériau | 45,214 | 11.33 | ×4.0 | mesuré; 2,086 bricks, 1,968 charges uniques, encodage 0.8s |
| VXP bricks 8³ couleur+matériau | 25,637 | 6.43 | ×7.0 | mesuré; 474 bricks, 472 charges uniques, encodage 0.2s |
|   + lzma sur le fichier | 14,780 | 3.70 | ×12.1 | mesuré |
|   dont géométrie seule (VXP 8³) | 1,716 | 0.43 | ×104.3 | mesuré |
|   dont couleur seule | 22,313 | 5.59 | ×8.0 | mesuré |
|   dont matériau | 1,608 | 0.40 | ×111.4 | mesuré |
| VXP 8³ coque seule (intérieur reconstruit) | 25,001 | 6.27 | ×7.2 | mesuré |
|   + lzma | 14,460 | 3.62 | ×12.4 | mesuré |
| VXP bricks 16³ couleur+matériau | 21,212 | 5.32 | ×8.4 | mesuré; 122 bricks, 122 charges uniques, encodage 0.1s |
| chaîne 26-voisins DFS (surface, géométrie) | 2,201 | 0.55 | ×81.4 | mesuré; 63,234 symboles, 2 sauts, H1=0.28 b/sym; sans index d'accès |

Flux couleur (ordre Morton), octets : brut 31,914 · RLE 38,026 · entropie H0 17,033 · H1 10,120 · lzma 11,228.  Accès aléatoire VXP 8³ (Python, µs/requête) : à froid 18, à chaud 17.
- chaîne littérale ±1 : couverture max 25 % des voxels (parité)

### Porte : 22,392 voxels (dont 7,113 intérieur), boîte (56, 116, 7)

| encodage | octets | bits/voxel | vs JSON .gz | statut |
|---|---:|---:|---:|---|
| JSON .gz (export actuel) | 123,921 | 44.27 | ×1.0 | mesuré |
| liste x,y,z,couleur brute | 89,568 | 32.00 | ×1.4 | calculé |
|   + lzma | 9,628 | 3.44 | ×12.9 | mesuré |
| grille dense (octet/cellule) | 45,472 | 16.25 | ×2.7 | calculé; boîte (56, 116, 7) |
|   + lzma | 9,428 | 3.37 | ×13.1 | mesuré |
| Morton: écarts varint + ancres/64 (géométrie) | 26,658 | 9.52 | ×4.6 | calculé |
|   Elias-Fano (géométrie, borne sans ancres) | 18,937 | 6.77 | ×6.5 | calculé |
|   entropie ordre 0 des écarts (borne) | 7,098 | 2.54 | ×17.5 | calculé |
| colonnes RLE (axe y) géom+couleur | 41,130 | 14.69 | ×3.0 | calculé |
| KV6-like surface seule (axe y) | 30,950 | 11.06 | ×4.0 | calculé; intérieur à reconstruire |
| SVO pointeurs+couleur feuilles (collapse uniforme) | 49,637 | 17.73 | ×2.5 | calculé; 4,661 nœuds, 21,671 feuilles |
| SVDAG géométrie seule | 8,546 | 3.05 | ×14.5 | calculé; 470 nœuds uniques |
|   + couleurs (flux Morton) + index | 24,272 | 8.67 | ×5.1 | calculé; total attributs; ajouter la ligne au-dessus |
| plaques 2D 4x4 dédup (axe z) exact | 30,130 | 10.76 | ×4.1 | calculé; 1,711 tuiles uniques / 1,744 |
| plaques 2D 8x8 dédup (axe z) exact | 32,329 | 11.55 | ×3.8 | calculé; 495 tuiles uniques / 495 |
| VXP bricks 4³ couleur+matériau | 24,008 | 8.58 | ×5.2 | mesuré; 712 bricks, 710 charges uniques, encodage 0.3s |
| VXP bricks 8³ couleur+matériau | 17,064 | 6.10 | ×7.3 | mesuré; 102 bricks, 102 charges uniques, encodage 0.0s |
|   + lzma sur le fichier | 11,172 | 3.99 | ×11.1 | mesuré |
|   dont géométrie seule (VXP 8³) | 3,627 | 1.30 | ×34.2 | mesuré |
|   dont couleur seule | 13,231 | 4.73 | ×9.4 | mesuré |
|   dont matériau | 206 | 0.07 | ×601.6 | mesuré |
| VXP 8³ coque seule (intérieur reconstruit) | 13,951 | 4.98 | ×8.9 | mesuré |
|   + lzma | 8,780 | 3.14 | ×14.1 | mesuré |
| VXP bricks 16³ couleur+matériau | 17,535 | 6.26 | ×7.1 | mesuré; 31 bricks, 31 charges uniques, encodage 0.0s |
| chaîne 26-voisins DFS (surface, géométrie) | 3,028 | 1.08 | ×40.9 | mesuré; 30,558 symboles, 2 sauts, H1=0.79 b/sym; sans index d'accès |

Flux couleur (ordre Morton), octets : brut 22,392 · RLE 32,564 · entropie H0 8,744 · H1 8,080 · lzma 8,748.  Accès aléatoire VXP 8³ (Python, µs/requête) : à froid 8, à chaud 7.
- chaîne littérale ±1 : couverture max 25 % des voxels (parité)

### Caisse : 135,251 voxels (dont 109,919 intérieur), boîte (56, 54, 56)

| encodage | octets | bits/voxel | vs JSON .gz | statut |
|---|---:|---:|---:|---|
| JSON .gz (export actuel) | 725,871 | 42.93 | ×1.0 | mesuré |
| liste x,y,z,couleur brute | 541,004 | 32.00 | ×1.3 | calculé |
|   + lzma | 35,692 | 2.11 | ×20.3 | mesuré |
| grille dense (octet/cellule) | 169,344 | 10.02 | ×4.3 | calculé; boîte (56, 54, 56) |
|   + lzma | 32,436 | 1.92 | ×22.4 | mesuré |
| Morton: écarts varint + ancres/64 (géométrie) | 160,713 | 9.51 | ×4.5 | calculé |
|   Elias-Fano (géométrie, borne sans ancres) | 49,231 | 2.91 | ×14.7 | calculé |
|   entropie ordre 0 des écarts (borne) | 34,259 | 2.03 | ×21.2 | calculé |
| colonnes RLE (axe y) géom+couleur | 225,750 | 13.35 | ×3.2 | calculé |
| KV6-like surface seule (axe x) | 53,688 | 3.18 | ×13.5 | calculé; intérieur à reconstruire |
| SVO pointeurs+couleur feuilles (collapse uniforme) | 252,314 | 14.92 | ×2.9 | calculé; 20,802 nœuds, 127,502 feuilles |
| SVDAG géométrie seule | 14,258 | 0.84 | ×50.9 | calculé; 626 nœuds uniques |
|   + couleurs (flux Morton) + index | 137,755 | 8.15 | ×5.3 | calculé; total attributs; ajouter la ligne au-dessus |
| plaques 2D 4x4 dédup (axe z) exact | 133,092 | 7.87 | ×5.5 | calculé; 7,221 tuiles uniques / 9,959 |
| plaques 2D 8x8 dédup (axe y) exact | 151,892 | 8.98 | ×4.8 | calculé; 2,308 tuiles uniques / 2,566 |
| VXP bricks 4³ couleur+matériau | 106,266 | 6.29 | ×6.8 | mesuré; 2,652 bricks, 2,397 charges uniques, encodage 0.7s |
| VXP bricks 8³ couleur+matériau | 94,133 | 5.57 | ×7.7 | mesuré; 343 bricks, 338 charges uniques, encodage 0.1s |
|   + lzma sur le fichier | 49,248 | 2.91 | ×14.7 | mesuré |
|   dont géométrie seule (VXP 8³) | 8,213 | 0.49 | ×88.4 | mesuré |
|   dont couleur seule | 85,244 | 5.04 | ×8.5 | mesuré |
|   dont matériau | 676 | 0.04 | ×1073.8 | mesuré |
| VXP 8³ coque seule (intérieur reconstruit) | 34,725 | 2.05 | ×20.9 | mesuré |
|   + lzma | 20,340 | 1.20 | ×35.7 | mesuré |
| VXP bricks 16³ couleur+matériau | 100,636 | 5.95 | ×7.2 | mesuré; 64 bricks, 64 charges uniques, encodage 0.1s |
| chaîne 26-voisins DFS (surface, géométrie) | 5,224 | 0.31 | ×138.9 | mesuré; 50,664 symboles, 1 sauts, H1=0.82 b/sym; sans index d'accès |

Flux couleur (ordre Morton), octets : brut 135,251 · RLE 183,850 · entropie H0 77,953 · H1 63,294 · lzma 41,672.  Accès aléatoire VXP 8³ (Python, µs/requête) : à froid 18, à chaud 17.
- chaîne littérale ±1 : couverture max 25 % des voxels (parité)

### Toit : 221,015 voxels (dont 96,208 intérieur), boîte (218, 167, 99)

| encodage | octets | bits/voxel | vs JSON .gz | statut |
|---|---:|---:|---:|---|
| JSON .gz (export actuel) | 1,238,137 | 44.82 | ×1.0 | extrapolé |
| liste x,y,z,couleur brute | 884,060 | 32.00 | ×1.4 | calculé |
|   + lzma | 54,440 | 1.97 | ×22.7 | mesuré |
| grille dense (octet/cellule) | 3,604,194 | 130.46 | ×0.3 | calculé; boîte (218, 167, 99) |
|   + lzma | 62,652 | 2.27 | ×19.8 | mesuré |
| Morton: écarts varint + ancres/64 (géométrie) | 264,074 | 9.56 | ×4.7 | calculé |
|   Elias-Fano (géométrie, borne sans ancres) | 194,506 | 7.04 | ×6.4 | calculé |
|   entropie ordre 0 des écarts (borne) | 91,589 | 3.32 | ×13.5 | calculé |
| colonnes RLE (axe z) géom+couleur | 347,703 | 12.59 | ×3.6 | calculé |
| KV6-like surface seule (axe x) | 266,147 | 9.63 | ×4.7 | calculé; intérieur à reconstruire |
| SVO pointeurs+couleur feuilles (collapse uniforme) | 531,598 | 19.24 | ×2.3 | calculé; 53,599 nœuds, 210,004 feuilles |
| SVDAG géométrie seule | 105,815 | 3.83 | ×11.7 | calculé; 4,803 nœuds uniques |
|   + couleurs (flux Morton) + index | 240,227 | 8.70 | ×5.2 | calculé; total attributs; ajouter la ligne au-dessus |
| plaques 2D 4x4 dédup (axe x) exact | 297,096 | 10.75 | ×4.2 | calculé; 13,816 tuiles uniques / 27,101 |
| plaques 2D 8x8 dédup (axe x) exact | 472,524 | 17.10 | ×2.6 | calculé; 7,016 tuiles uniques / 9,883 |
| VXP bricks 4³ couleur+matériau | 251,812 | 9.11 | ×4.9 | mesuré; 9,014 bricks, 8,177 charges uniques, encodage 3.4s |
| VXP bricks 8³ couleur+matériau | 226,726 | 8.21 | ×5.5 | mesuré; 1,847 bricks, 1,820 charges uniques, encodage 0.9s |
|   + lzma sur le fichier | 113,700 | 4.12 | ×10.9 | mesuré |
|   dont géométrie seule (VXP 8³) | 74,441 | 2.69 | ×16.6 | mesuré |
|   dont couleur seule | 135,656 | 4.91 | ×9.1 | mesuré |
|   dont matériau | 16,629 | 0.60 | ×74.5 | mesuré |
| VXP 8³ coque seule (intérieur reconstruit) | 168,273 | 6.09 | ×7.4 | mesuré |
|   + lzma | 80,840 | 2.93 | ×15.3 | mesuré |
| VXP bricks 16³ couleur+matériau | 259,712 | 9.40 | ×4.8 | mesuré; 374 bricks, 372 charges uniques, encodage 0.3s |

Flux couleur (ordre Morton), octets : brut 221,015 · RLE 244,370 · entropie H0 126,462 · H1 75,906 · lzma 71,808.  Accès aléatoire VXP 8³ (Python, µs/requête) : à froid 29, à chaud 28.
- chaîne littérale ±1 : couverture max 25 % des voxels (parité)
- chaîne DFS non évaluée (> 120 000 voxels de surface)

### Mur_ferme_seal11 : 175,351 voxels (dont 132,670 intérieur), boîte (101, 157, 21)

| encodage | octets | bits/voxel | vs JSON .gz | statut |
|---|---:|---:|---:|---|
| JSON .gz (export actuel) | 990,339 | 45.18 | ×1.0 | extrapolé |
| liste x,y,z,couleur brute | 701,404 | 32.00 | ×1.4 | calculé |
|   + lzma | 42,396 | 1.93 | ×23.4 | mesuré |
| grille dense (octet/cellule) | 332,997 | 15.19 | ×3.0 | calculé; boîte (101, 157, 21) |
|   + lzma | 40,352 | 1.84 | ×24.5 | mesuré |
| Morton: écarts varint + ancres/64 (géométrie) | 208,626 | 9.52 | ×4.7 | calculé |
|   Elias-Fano (géométrie, borne sans ancres) | 144,877 | 6.61 | ×6.8 | calculé |
|   entropie ordre 0 des écarts (borne) | 41,709 | 1.90 | ×23.7 | calculé |
| colonnes RLE (axe z) géom+couleur | 209,766 | 9.57 | ×4.7 | calculé |
| KV6-like surface seule (axe y) | 87,483 | 3.99 | ×11.3 | calculé; intérieur à reconstruire |
| SVO pointeurs+couleur feuilles (collapse uniforme) | 300,510 | 13.71 | ×3.3 | calculé; 25,173 nœuds, 149,472 feuilles |
| SVDAG géométrie seule | 12,214 | 0.56 | ×81.1 | calculé; 618 nœuds uniques |
|   + couleurs (flux Morton) + index | 177,823 | 8.11 | ×5.6 | calculé; total attributs; ajouter la ligne au-dessus |
| plaques 2D 4x4 dédup (axe z) exact | 132,134 | 6.03 | ×7.5 | calculé; 6,852 tuiles uniques / 12,167 |
| plaques 2D 8x8 dédup (axe z) exact | 161,642 | 7.37 | ×6.1 | calculé; 2,436 tuiles uniques / 3,370 |
| VXP bricks 4³ couleur+matériau | 134,347 | 6.13 | ×7.4 | mesuré; 3,905 bricks, 3,834 charges uniques, encodage 1.4s |
| VXP bricks 8³ couleur+matériau | 115,404 | 5.27 | ×8.6 | mesuré; 690 bricks, 689 charges uniques, encodage 0.3s |
|   + lzma sur le fichier | 49,444 | 2.26 | ×20.0 | mesuré |
|   dont géométrie seule (VXP 8³) | 6,537 | 0.30 | ×151.5 | mesuré |
|   dont couleur seule | 99,799 | 4.55 | ×9.9 | mesuré |
|   dont matériau | 9,068 | 0.41 | ×109.2 | mesuré |
| VXP 8³ coque seule (intérieur reconstruit) | 45,203 | 2.06 | ×21.9 | mesuré |
|   + lzma | 25,512 | 1.16 | ×38.8 | mesuré |
| VXP bricks 16³ couleur+matériau | 124,729 | 5.69 | ×7.9 | mesuré; 127 bricks, 127 charges uniques, encodage 0.1s |
| chaîne 26-voisins DFS (surface, géométrie) | 4,808 | 0.22 | ×206.0 | mesuré; 85,362 symboles, 1 sauts, H1=0.45 b/sym; sans index d'accès |

Flux couleur (ordre Morton), octets : brut 175,351 · RLE 204,556 · entropie H0 86,004 · H1 57,621 · lzma 40,052.  Accès aléatoire VXP 8³ (Python, µs/requête) : à froid 30, à chaud 29.
- chaîne littérale ±1 : couverture max 25 % des voxels (parité)

### Brique_x5 : 245,424 voxels (dont 223,296 intérieur), boîte (86, 53, 64)

| encodage | octets | bits/voxel | vs JSON .gz | statut |
|---|---:|---:|---:|---|
| JSON .gz (export actuel) | 1,238,021 | 40.36 | ×1.0 | extrapolé |
| liste x,y,z,couleur brute | 981,696 | 32.00 | ×1.3 | calculé |
|   + lzma | 25,884 | 0.84 | ×47.8 | mesuré |
| grille dense (octet/cellule) | 291,712 | 9.51 | ×4.2 | calculé; boîte (86, 53, 64) |
|   + lzma | 20,788 | 0.68 | ×59.6 | mesuré |
| Morton: écarts varint + ancres/64 (géométrie) | 291,678 | 9.51 | ×4.2 | calculé |
|   Elias-Fano (géométrie, borne sans ancres) | 91,658 | 2.99 | ×13.5 | calculé |
|   entropie ordre 0 des écarts (borne) | 55,466 | 1.81 | ×22.3 | calculé |
| colonnes RLE (axe y) géom+couleur | 147,891 | 4.82 | ×8.4 | calculé |
| KV6-like surface seule (axe x) | 47,648 | 1.55 | ×26.0 | calculé; intérieur à reconstruire |
| SVO pointeurs+couleur feuilles (collapse uniforme) | 251,518 | 8.20 | ×4.9 | calculé; 20,772 nœuds, 126,886 feuilles |
| SVDAG géométrie seule | 14,764 | 0.48 | ×83.9 | calculé; 684 nœuds uniques |
|   + couleurs (flux Morton) + index | 248,160 | 8.09 | ×5.0 | calculé; total attributs; ajouter la ligne au-dessus |
| plaques 2D 4x4 dédup (axe y) exact | 119,158 | 3.88 | ×10.4 | calculé; 5,584 tuiles uniques / 16,912 |
| plaques 2D 8x8 dédup (axe y) exact | 191,898 | 6.26 | ×6.5 | calculé; 2,886 tuiles uniques / 4,407 |
| VXP bricks 4³ couleur+matériau | 90,507 | 2.95 | ×13.7 | mesuré; 4,390 bricks, 2,904 charges uniques, encodage 0.9s |
| VXP bricks 8³ couleur+matériau | 92,954 | 3.03 | ×13.3 | mesuré; 611 bricks, 581 charges uniques, encodage 0.3s |
|   + lzma sur le fichier | 31,408 | 1.02 | ×39.4 | mesuré |
|   dont géométrie seule (VXP 8³) | 6,999 | 0.23 | ×176.9 | mesuré |
|   dont couleur seule | 84,792 | 2.76 | ×14.6 | mesuré |
|   dont matériau | 1,163 | 0.04 | ×1064.5 | mesuré |
| VXP 8³ coque seule (intérieur reconstruit) | 24,080 | 0.78 | ×51.4 | mesuré |
|   + lzma | 11,388 | 0.37 | ×108.7 | mesuré |
| VXP bricks 16³ couleur+matériau | 118,587 | 3.87 | ×10.4 | mesuré; 96 bricks, 96 charges uniques, encodage 0.1s |
| chaîne 26-voisins DFS (surface, géométrie) | 3,648 | 0.12 | ×339.4 | mesuré; 44,256 symboles, 1 sauts, H1=0.66 b/sym; sans index d'accès |

Flux couleur (ordre Morton), octets : brut 245,424 · RLE 139,034 · entropie H0 117,164 · H1 49,839 · lzma 29,868.  Accès aléatoire VXP 8³ (Python, µs/requête) : à froid 27, à chaud 26.
- chaîne littérale ±1 : couverture max 25 % des voxels (parité)