# engine/act : le monde non voxel (T15)

`EntityStore` : objets, plantes, bêtes, structures, eau, feu, lieux. Applier du bus d'opérations (`engine/ops`), il ne change que par
`Spawn`, `Destroy`, `Move`, `EntityDelta` (builders : `entity_ops.h`). Identifiant = 22 bits de case + 10 bits de génération ; une case
qui épuiserait sa génération est retirée (jamais d'id ambigu). Composants générés par `catalogue/tools/gen_cpp.py` dans
`generated/emergence/act/world_gen.h` (`provenance`, `transformation`, ...), ids stables dans `catalogue/generated/world_registry.json`.
Position (mm) et contenant vivent dans l'enregistrement de l'entité, pas dans un composant. Itération, sérialisation et empreinte vont
par numéro de case. Tests : `test_entity_store` ; banc : `bench_entity_store [n]`.

## Lois de la matière 1 (T18)

`contact_resolver.*` : quelles entités se touchent (qui repose sur qui, charge portée, marge) et avec quelles propriétés
(`cuts`, `impacts`, `digs`, `binds`, `sharpens`, `graspable`, lues dans les parties, jamais dans un nom d'outil).
`process_engine.*` + `laws/` : `cut`, `split`, `fracture`, `crush`, `carve`, `disassemble`, `extract`, `till`, `assemble`, `bind`,
`abrade` (sur contact) et `collapse` (horloge réelle : marge de charge, effondrement, chute). Le moteur ne modifie rien : il rend des
`Emission` (Operation + clés d'ordre) que l'appelant remet au bus. Terrain voxel : `extract` / `till` rendent une `VoxelRequest`.
Tables : `catalogue/tools/gen_matter.py` (`--check`) → `generated/emergence/act/matter_gen.h`, ids dans `catalogue/generated/matter_registry.json`.
Tests : `test_matter_laws` ; banc : `bench_matter_laws [n]` (processus/s). Limites : positions et tailles en cube dérivé de la masse
si la fiche n'en donne pas ; l'usure de l'outil et l'intégrité d'un objet n'ont pas encore de variable (T20 `wear`).

### Limites et dette de T18 (à lire avant de s'appuyer dessus)

- `sort` d'une entité = indice de son id dans `kKinds` (`vocab_registry.json`), produit par `gen_matter.py` ; le registre `matter_registry.json` ne sert qu'aux index internes.
- Les chutes sont INSTANTANÉES : l'entité est téléportée à la hauteur d'atterrissage (un seul `Move`), sans énergie transmise à ce qu'elle heurte et sans cascade dans le pas ; la suite se joue aux pas suivants.
- `tick_time` scanne tout le monde à chaque tick (mesuré : 4 ms pour 20 000 corps ici, environ 25 ms pour 100 000) : prévoir des régions sales avant la charge cible.
- Un corps de plus de 64 cellules (64 m) sur un axe n'est indexé que sur ses 64 premières cellules (c'est du terrain, pas une entité). Les valeurs hostiles sont saturées (100 t, 100 m, 100 m/s, 10 km de chute) ; fiche invalide : matière inconnue = aucune matière.
- Conflit sur une même cible : l'ordre est un hachage de (tick, auteur, decision_seq), donc sans favori ; le perdant rend `Conflict`.
- Dette « T18b : table loi/processus au catalogue » (constantes de comportement en dur, NON externalisées) : tolérance d'appui 20 mm ; masses 300 g (frappe), 500 g (creuse), 25 000 g et 1 500 mm (saisie) ; dureté « tendre » 35 ; 8 mJ par (ténacité x cm2) pour casser ; 50 g par (ténacité x cm2) de portance ; diviseurs d'énergie 32 (fendre), 8 (joints), 4 (écraser) ; pièces max 4 (couper) et 6 (fendre, éclats) et 8 (gravats) ; travail 25 pour mille (tailler) et 8 pour mille (aiguiser) par coup ; profondeurs 500 mm (extraire) et 250 mm (labourer) ; bruit et vue de chaque processus ; catégories labourables (`TILLABLE_CATEGORIES` de `gen_matter.py`).
