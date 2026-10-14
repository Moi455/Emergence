# em_water — physique de l'eau pour Emergence (Rust, sans dépendance)

## Principe
L'eau est un volume entier (mm³) par colonne, pas des voxels. Cellules de 5 cm (<20 m du joueur) ou 25 cm (au-delà), dans un même graphe ;
chaque paroi garde une ouverture par voxel avec son seuil propre (un trou d'un voxel dans un barrage est vu même à 25 cm).
Flux : approximation inertielle locale des équations de Saint-Venant (Bates 2010) + Manning, plafonnée par la loi de seuil (1,705·d^1,5).
Conservation exacte au mm³, déterministe (hash identique quel que soit l'ordre des arêtes), mise en sommeil des cellules au repos.

## Mesures (cargo test --release) : 15 passés, 1 ignoré volontairement
- Conservation exacte, équilibre hydrostatique (écart 0,5 mm), regrid 5 cm<->25 cm exact, creuser/poser sous l'eau exact.
- Manning pente 2 % lisse : +1,8 %. Torrent n=0,06 : +6 à +8 %. Seuil libre : écart de charge -0,1 %.
- Barrage : 0 % de fuite avant la crête, surface plate, débit sortant = débit entrant, charge sur la crête +2 % vs loi de seuil (idem en résolution mixte).
- Barrage rebouché : débit à travers le mur 0.
## Limites connues (mesurées)
- Fente d'un voxel : fuit ~35 % de plus que la loi de seuil idéale (pas de contraction latérale).
- Marches de 5 cm sur pente douce : profondeur +15 % vs Manning uniforme.
- Rupture de barrage : front 2,3x trop lent (pas de terme convectif). Test de Ritter ignoré par conception.
- Torrent lisse et raide : l'écoulement est plafonné à l'écoulement critique (trop profond) ; correct avec rugosité n≈0,06.
## COÛT (benchmark examples/bench.rs, terrain montagneux synthétique, fenêtre 128 m, 5 cm sur 40x40 m)
- 1 source (30 L/s), 40 s simulées : 52 000 arêtes actives, 19 % d'un cœur en moyenne, pointe 34 %, ~76 pas/s, ~87 ns par arête et par pas.
- 8 sources : 2,6 s de calcul par seconde simulée à 40 s, 6,4 s à 60 s -> PLUS LENT QUE LE TEMPS RÉEL. Inutilisable tel quel.
- Cause : l'eau s'étale en nappes sur des dizaines de milliers de cellules 5 cm ; le seuil de mouillage (d_min 0,5 mm -> 1 cm) ne change presque rien (-15 %).
- Non vérifié : la répartition exacte du temps (accès mémoire dispersés ? 4 itérations de racine cubique : en passer à 2 ne gagne que 4 %).
## À décider (architecture)
Les mailles 5 cm ne peuvent pas porter toute l'eau mouillée d'une fenêtre de 20 m. Pistes : budget de cellules actives, rivières/lacs
en niveau "bassin" analytique hors du voisinage immédiat, 5 cm réservé aux zones modifiées/proches, locality mémoire + SIMD, multithread.
