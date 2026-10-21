# engine-rs : le laboratoire de style en Rust

Espace de travail Cargo du laboratoire de style du monde physique (`docs/19`, `docs/19a`, `docs/19b`).
Rust 1.99 (`rust-toolchain.toml`), édition 2024, `Cargo.lock` versionné, dépendances épinglées une fois dans
`Cargo.toml` (`[workspace.dependencies]`) : une tâche n'a pas à le modifier.

## Commandes

```
export PATH=$HOME/.cargo/bin:$PATH
cargo build --workspace --release
cargo test --workspace
cargo clippy --workspace -- -D warnings
scripts/gen_cpp_vectors.sh      # régénère les vecteurs de parité depuis le C++ (g++ -std=c++20)
```

## Les crates (`docs/19` § 2.2)

| Crate | Rôle | Vérité (déterministe) |
|---|---|---|
| `em_core` | Q16, hachage, empreintes, coordonnées, repères, identifiants, E/S petit-boutistes (**fait**, L01) | oui |
| `em_voxel` | briques, chunks, sources, empreintes (L05) | oui |
| `em_material` | table des matières, paquet GPU (fonctionnalité `gpu`) (L06) | non (module `table` : entiers) |
| `em_ops` | opérations v1, bus, journal, paquet `EMPK` (L18) | oui |
| `em_mesh` | maillage de chunks : faces visibles, occlusion par sommet, fusion gloutonne, épaisseur de feuillage (L33) | non |
| `em_gen` | générateurs, chargeur `.vxm`, port de `voxel_tree` | oui |
| `em_terrain` | densité, terrain de base, peau | oui (hors module `skin`) |
| `em_assembly` | recettes, entités | oui |
| `em_world` | monde, deltas, journal, rejeu | oui |
| `em_render` | `wgpu` : contexte, cibles, graphe de passes, profileur (L02), ciel et post (L03), rendu voxel (`voxel/`, L09) | non |
| `em_veg` | herbe et fleurs | non |
| `em_water_render` | rendu de l'eau | non |
| `em_lab` | binaire : scènes, captures, bancs, fenêtre | non |

Les crates sont créées vides, avec leurs dépendances déjà déclarées : une tâche écrit dans `crates/<sa crate>/src`
sans toucher au `Cargo.toml` racine. Si une dépendance manque, la demander à l'orchestrateur.

## Le rendu voxel (L09)

`em_render::voxel` : `VoxelGpuWorld` (mémoire GPU : table de chunks, tas de chunks, briques à palette, tas de mots),
`ClipmapStreamer` (décide quoi charger, du plus proche au plus lointain, par blocs modifiés), `VoxelTracePass`
(lancer de rayons primaire en compute, DDA chunk -> brique -> voxel), `VoxelMaterialPass` (couleur du voxel en
coordonnées monde avec le paquet de `em_material`), `DepthMergePass`, `LightingPass` (soleil et ciel, sans ombres).
La scène `arbre` de `em_lab` les assemble :

```
scripts/lab.sh capture --scene arbre --shot face --hour 17.5 --out face.png
scripts/lab.sh capture --scene arbre --camera 12,1.7,-8 --look-at 0,6,0 --vue masque --bloom 0
scripts/lab.sh bench --scene arbre --shot feuillage          # ms par passe sur la Quadro
scripts/serie_arbre.sh                                       # la série de captures de L09
```

Les essais GPU (`cargo test -p em_render --test voxel_gpu`) comparent le tracé à un DDA CPU et la matière à la
référence CPU de `em_material` ; sans adaptateur ils s'ignorent. Une clipmap n'a qu'un niveau (25 m autour de la
caméra) : l'arbre entier doit tenir dans la fenêtre.

## Règles du code (`docs/19` § 2.4 et § 2.7)

- **Crates de vérité** (`em_core`, `em_voxel`, `em_ops`, `em_gen`, `em_terrain`, `em_assembly`, `em_world`) :
  `#![deny(clippy::float_arithmetic)]`, aucun `HashMap` ni `HashSet` (`disallowed-types` dans le `clippy.toml` de la
  crate : Clippy n'en lit qu'un par crate), hasard par `em_core::hash` seulement, aucun `unsafe`.
- **Aucun `unsafe`** nulle part : `#![forbid(unsafe_code)]`.
- **Orienté objet** : état privé, invariants vérifiés dans les constructeurs, nouveaux types pour les identifiants,
  aucune globale ni singleton ; erreurs typées (`thiserror`), `anyhow` seulement dans `em_lab`.
- **Sens de dépendance** : le test `em_core/tests/deps_direction.rs` lit `cargo metadata` et échoue si `em_render`
  dépend de `em_world` ou `em_ops`, si une crate de vérité dépend de `wgpu`, ou si `em_ops` dépend de `em_voxel`.
- Commentaires, messages et documentation en français ; identifiants en anglais.

## Parité avec le C++

`scripts/cpp_vectors.cpp` inclut les vrais en-têtes (`engine/core/base` `hash.h` et `fixed.h`, `engine/ops` `digest`,
`engine/act` `entity_id.h`) et imprime des vecteurs que `scripts/gen_cpp_vectors.sh` range dans
`crates/em_core/tests/vecteurs/cpp_vectors.inc.rs` (versionné, ne pas éditer). `tests/parity_cpp.rs` les compare.
Le C++ de `qmul` déborde (comportement indéfini) hors de `|a·b| < 2^63` : les vecteurs restent dans ce domaine.

## Dossiers

`lab/` : scènes, style, références d'images approuvées, modèles `.vxm` (régénérables), `captures/` (ignoré).
`scripts/` : `gen_cpp_vectors.sh`, `cpp_vectors.cpp`, `lab.sh`, `serie_ciel.sh` (L03 : les 7 captures du ciel), `serie_arbre.sh` (L09 : l'arbre aux trois heures), `extract_web_ocean.py` (L03 : extrait le WGSL de `web-ocean`, `python3 -I`, dossier source en argument).

## Le rendu par maillage (L33)

Rendu de base : `scripts/lab.sh capture|bench --scene arbre|materiaux --rendu maillage` (défaut) ; `--rendu trace` pour le tracé
compute ; `--rendu ab` (capture) AVANT tracé / APRÈS maillage ; `--granulometrie-ab` (matériaux, mode voxel) ; `--granulometrie F`.
Essais : `cargo test -p em_mesh` (sans GPU), `cargo test -p em_render --test maillage_gpu` (contre le tracé),
`cargo run --release -p em_mesh --example mesures` (temps de maillage).
