# worldgen : génération fine du monde (étage 2)

Le plan du monde à 16 m (`engine/core/world/world_plan.*` : relief, érosion, rivières, biomes, marches, villages, routes, décor) est l'étage 1. Ce dossier en tire les **chunks de voxels** de 2 cm, à la demande, dans n'importe quel ordre et sur n'importe quel fil.

Ce qu'il ajoute sous 16 m : relief fin (octaves de 24 m à 37 cm, crêtes dans la roche), couches de surface et de sol par biome, strates sédimentaires inclinées, socle granitique vers -250 m, minerai de fer, lentilles de sel (désert, côte) et d'argile, réseau de grottes indexé (galeries, salles, entrées), rochers, arbres placés par hachage (chêne, bouleau, pin, saule ; écorce dehors, bois dedans ; géants au fond de la marche forestière), routes taillées dans la pente, plateformes nivelées des cinq villages.

## API (`include/emergence/worldgen/worldgen.h`)

```cpp
em::wg::WorldGen gen(plan);                       // ~20 ms à 20 km (grottes, routes)
gen.classify({x, y, z, lod});                     // Air / Solid / Mixed / OutOfWorld, ~0,15 µs
gen.generate({x, y, z, lod}, voxels);             // 64³ VoxelId, voxel = 2 cm << lod
gen.generate(em::ChunkCoord{x, y, z}, chunk);     // lod 0, encodé en briques (em::Chunk)
gen.ground_mm(x_mm, z_mm, lod);                   // hauteur du sol utilisée par generate
gen.trees_in(x0, z0, x1, z1, &trees);             // arbres avec id stable (deltas)
gen.settlement_pads(); gen.cave_segments();
```

Repère de `docs/interfaces.md` : x est, y haut, z nord, origine au coin sud-ouest, y = 0 au niveau de la mer. Chunk (x, y, z) au niveau `lod` : origine (x, y, z) × 1,28 m << lod. **Un chunk grossier se génère directement**, sans réduire les chunks fins : les octaves plus fines que 4 voxels et les arbres plus petits qu'un voxel sont sautés. Au-delà de lod 2 (voxels de 16 cm et plus), les couronnes deviennent des volumes pleins faits de blocs (un tiers du rayon à lod 3, la moitié à lod 4, le rayon entier ensuite, 8 voxels au plus), que la fusion gloutonne du moteur réunit : 6,85 M → 1,95 M quads au chargement complet autour du bourg (`bench_terrain market_town`). `kChunkGenVersion` = 2. Teinte 0 partout, sauf écorce et feuillage qui portent l’essence (interfaces.md § 2 bis : 0 chêne, 1 saule, 2 pin, 3 bouleau). L'eau n'est pas en voxels (`water_mm()` donne le niveau du plan).

## Mesures (graine 42, 20 km, 1 fil, machine du conteneur)

- chunk de surface : 0,44 ms en moyenne à lod 0 et lod 2 (critère M2 : < 1 ms) ; chunks de canopée dense à lod 2 jusqu'à ~10 ms
- export complet de la visionneuse (12 lieux, 3 coupes) : 23 s

## Déterminisme

Entiers et virgule fixe Q16 uniquement, tirages par hachage. `tests/test_worldgen.cpp` (11 tests) vérifie : même graine = mêmes chunks quel que soit l'ordre et le nombre de fils, classify == contenu réel, sol == voxels, aller-retour en briques, teinte d’essence, empreintes de référence (`tests/golden_seed7_4km.txt`, à régénérer avec `WORLDGEN_WRITE_GOLDEN=1` quand le plan change). `scripts/check_determinism.sh` compile avec gcc et clang en Release et Debug : les quatre donnent les mêmes empreintes.

## Construire

```
cmake -S worldgen -B build && cmake --build build && build/test_worldgen
build/worldgen_tool bench  --seed 42
build/worldgen_tool export --seed 42 --out DIR   # données de la visionneuse
```
