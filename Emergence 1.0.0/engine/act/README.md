# engine/act : le monde non voxel (T15)

`EntityStore` : objets, plantes, bêtes, structures, eau, feu, lieux. Applier du bus d'opérations (`engine/ops`), il ne change que par
`Spawn`, `Destroy`, `Move`, `EntityDelta` (builders : `entity_ops.h`). Identifiant = 22 bits de case + 10 bits de génération ; une case
qui épuiserait sa génération est retirée (jamais d'id ambigu). Composants générés par `catalogue/tools/gen_cpp.py` dans
`generated/emergence/act/world_gen.h` (`provenance`, `transformation`, ...), ids stables dans `catalogue/generated/world_registry.json`.
Position (mm) et contenant vivent dans l'enregistrement de l'entité, pas dans un composant. Itération, sérialisation et empreinte vont
par numéro de case. Tests : `test_entity_store` ; banc : `bench_entity_store [n]`.
