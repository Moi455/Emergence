# Annexe 19a : formats et interfaces du laboratoire (20 oct. 2026)

Annexe de `docs/19_laboratoire_architecture.md`. Tout est **petit-boutiste**. Tout format persistant porte une signature, une version et un CRC32 (IEEE, polynôme réfléchi 0xEDB88320, même valeur que `zlib.crc32` et que `engine/ops/digest.h`) ; une version future est **refusée**, jamais devinée. Les registres sont **en ajout seul** : on ne renumérote jamais.

---

## 1. Format d'échange `.vxm` v1 (Python → Rust)

Pont provisoire entre les générateurs Python validés (`voxel_tree.py`, `voxel_bush.py`) et le moteur Rust, en attendant leur port (L30-L32). Un fichier = un arbre ou un arbuste, **plusieurs LOD générés depuis la recette** (même graine, même squelette, feuillage re-rastérisé à `voxel = 0,05 × 2^lod`, **lod de 0 à 5** pour couvrir les 6 niveaux de la clipmap), **sans ombrage cuit**.

### 1.1 Disposition

| Décalage | Taille | Champ |
|---|---|---|
| 0 | 4 | signature `"VXM1"` |
| 4 | 2 | `u16 version` = 1 |
| 6 | 2 | `u16 flags` : bit 0 corps compressés zlib ; bit 1 canal `sky` présent ; bit 2 canal `pal` présent |
| 8 | 4 | `u32 json_len` |
| 12 | `json_len` | en-tête JSON UTF-8 (§ 1.2) |
| … | | `lod_count` sections, `lod` croissant (§ 1.3) |
| fin − 4 | 4 | `u32 crc32` de tous les octets qui précèdent |

### 1.2 En-tête JSON

```json
{
  "format": "vxm-1",
  "generator": "voxel_tree.py",
  "generator_sha256": "<empreinte du fichier .py qui a produit le modèle>",
  "seed": "42", "seed_int": 42,
  "species": "chene", "nom": "Chêne",
  "height_m": 14.0, "season": "summer", "leaf_density": 1.0, "topiary": null,
  "voxel_m": 0.05,
  "axes": "x_est,y_haut,z_nord",
  "source_axes": "python x -> est, python y -> nord, python z -> haut",
  "lods": [0, 1, 2, 3, 4, 5],
  "steps": 30,
  "ramps": [[[38,30,24],[84,70,58],[128,112,94]], "... une rampe = sombre, moyen, clair (sRGB)"],
  "ramp_roles": ["bark", "bark_alt", "twig", "leaf", "leaf", "leaf"],
  "palette": "[[r,g,b] x 256], seulement si flags bit 2 (palette Python sans ombrage cuit)",
  "base_radius_m": 0.28
}
```

`ramps` et `ramp_roles` suivent l'ordre de `colorize()` : écorce, écorce secondaire, rameau, feuillages, fleurs, fruits. `steps` = nombre de nuances par rampe utilisé par Python (`min(30, 255 // nb_rampes)`).

### 1.3 Une section de LOD

| Taille | Champ |
|---|---|
| 1 | `u8 lod` (voxel = `voxel_m × 2^lod`) |
| 3 | réservés = 0 |
| 12 | `i32 min[3]` : coin de la boîte, en voxels du niveau, repère monde (x est, y haut, z nord) ; **pivot = cellule du pied du tronc = (0, 0, 0)** de ce niveau |
| 12 | `u32 dims[3]` |
| 4 | `u32 count` : voxels pleins, **chacun une seule fois** |
| 4 | `u32 body_len` : octets du corps tel qu'écrit |
| `body_len` | corps (zlib si bit 0) : tableaux à la suite, voxels triés par (y, z, x) : `u16 x[count]`, `u16 y[count]`, `u16 z[count]` (relatifs à `min`), `u8 kind[count]` (1 écorce, 2 feuille, 3 rameau, 4 fleur, 5 fruit), `u8 ramp[count]` (indice dans `ramps`), puis `u8 pal[count]` si bit 2, puis `u8 sky[count]` si bit 1 |

### 1.4 Règles

- **Axes** : Python a z vers le haut ; on décide que `x_py` = est et `y_py` = nord ; l'exporteur écrit `(x, y, z)_monde = (x_py, z_py, y_py)`. Comme triplet, c'est une permutation de déterminant −1 ; physiquement, ce n'est **pas** un miroir : le repère de Python (est, nord, haut) est droitier, le repère monde (est, haut, nord) est gaucher, et ce sont les mêmes directions physiques. Le moteur rend en repère gaucher (`docs/19` § 2.6) ; la scène d'orientation de L04, L08 et L09 le prouve.
- **Doublons** : une cellule peut sortir à la fois écorce et rameau de `generate_tree` (248 cellules pour le chêne 42 de 14 m [Mesuré]) ; on garde la **première sorte par priorité écorce > rameau > fleur > fruit > feuille**. Compte attendu au LOD0 pour ce chêne : **607 784** voxels.
- **Rampe** : `ramp = (pal_idx − 1) // steps` avec `bake_light=False`. Le moteur n'en garde qu'une **variante** de 2 bits (§ 5.3) : pour l'écorce, 0 écorce, 1 écorce secondaire (mousse, marques), 2 rameau ; pour les fleurs et les fruits, la rampe dans leur rôle ; pour les **feuilles, rien** : leur rampe est tirée au shader en coordonnées monde (`docs/19` § 4.6). La rampe Python des feuilles reste dans le fichier pour les comparaisons de distribution.
- **Palette** : la bibliothèque du labo est exportée avec le canal `pal` (bit 2) ; c'est la référence de couleur de L10.
- **Ciel** (option `--export-sky`) : le terme `sky` de `compute_light()` (part de ciel vue, donnée géométrique, rééclairable : permise par D23), pour comparer en A/B avec l'occlusion calculée par le moteur. Jamais la lumière du soleil.
- **Déterminisme** : deux exportations identiques donnent des fichiers identiques octet pour octet.
- **Chargement Rust** (`em_gen::vxm::VxmModel`) : position monde d'un voxel du LOD k = `floor_div(pivot_monde_LOD0, 2^k) + rot(local)`, rotation d'un quart de tour (est → nord) autour du **centre** de la cellule pivot ; écorce et rameau → classe `bark` (31), feuille → `leaves` (30), fleur → `petal` (34, ajoutée par L06), fruit → `fruit` (35, ajoutée par L06) ; teinte = `vegetation(essence, variante)` (§ 5.3).

---

## 2. Stockage d'une partie

### 2.1 Arborescence

```
save/<partie>/
  world.manifest                manifeste EMWM v1 (§ 2.2)
  world.empk                    paquet incrémental EMPK v1 (§ 2.3)
  journal/oplog-NNNNNN.emj      journal EMOPLG v1, identique au C++ (engine/ops/op_journal.h)
```

### 2.2 Manifeste `EMWM` v1

`"EMWM"`, `u32 version` = 1, `u64 world_id`, `u64 seed`, `u32 generator_versions[8]` (géographie, écologie, établissements, maisons, arbres, matières du sol, paysage du labo, réservé), `u32 material_catalog_version` (empreinte de `materials.csv` + `material_render.toml`), `u64 macro_plan_fingerprint`, `u64 created_unix_ms` (métadonnée seulement, jamais lue par la simulation), `u32 crc32`.

### 2.3 Paquet `EMPK` v1 (« comme un PDF »)

En-tête de fichier (16 o) : `"EMPK\0\0\0\0"`, `u32 format_version` = 1, `u32` réservé.

**Enregistrement** (en-tête de 32 o puis charge) :

| Taille | Champ |
|---|---|
| 4 | `u32 magic` = `"RCRD"` |
| 2 | `u16 type` : 1 chunk de voxels édités, 2 page d'entités, 3 page de pierres tombales, 4 eau (phase 4), `0xFFFF` table |
| 2 | `u16 flags` : bit 0 charge compressée zstd |
| 8 | `u64 key` (§ 2.4) |
| 8 | `u64 op_id` : l'état représenté est celui après cette opération |
| 4 | `u32 stored_len` |
| 4 | `u32 crc32` de la charge stockée |
| `stored_len` | charge |

**Table** (type `0xFFFF`) : `u64 op_id`, `u64 prev_table_offset` (0 = première), `u8 full` (1 = table complète, 0 = seulement les clés changées par cette validation), trois octets réservés, `u32 count`, puis `count` × { `u16 type`, `u16 flags` (bit 0 = clé supprimée), `u64 key`, `u64 offset`, `u32 len` }, triés par (type, key). Comme la table de références croisées d'un PDF : la vue courante = cette table, puis les précédentes jusqu'à la dernière table complète, la plus récente l'emportant. Une table complète est écrite au compactage et toutes les 64 validations.

**Pied** (24 o, ajouté après chaque table) : `"EMPKTAIL"`, `u64 offset` de la table, `u32 crc32` des 16 octets précédents, `u32` réservé.

- **Valider** (instantané) : ajouter les enregistrements sales, puis la table, puis le pied ; `fsync` du fichier.
- **Ouvrir** : lire les 24 derniers octets ; si le pied est invalide (plantage pendant l'écriture), remonter jusqu'au dernier pied valide ; puis remonter les tables jusqu'à une table complète. Rien n'est jamais réécrit en place.
- **Compacter** : quand plus de 40 % des octets sont morts, écrire un nouveau fichier avec les seuls enregistrements vivants et une table, puis renommer de façon atomique.

### 2.4 Clés et charges

| Type | Clé | Charge (avant zstd) |
|---|---|---|
| 1 chunk de voxels édités | `(cx + 32768) \| (cz + 32768) << 16 \| (cy + 32768) << 32` (chunk du niveau 0, coordonnées signées décalées) | `u32 n`, puis n × { `u16 brick` (bx + 8 bz + 64 by), brique EMBK (§ 2.5) }, triés par brique. Un enregistrement par chunk édité (pas par région : une petite édition ne réécrit pas une région entière) ; la région (32 × 16 × 32 chunks) reste l'unité de regroupement en mémoire |
| 2 page d'entités | `(entity_id & 0x3FFFFF) >> 12` : la **case** (22 bits bas) divisée par 4 096, jamais la génération (10 bits hauts) | `u32 n`, puis n enregistrements d'entité (§ 2.6) triés par identifiant |
| 3 pierres tombales | cellule macro de 256 m : `cx \| cz << 16` (toujours ≥ 0 : le monde commence au coin sud-ouest) | `u32 n`, `u64 base_ref[n]` triés |

### 2.5 Brique `EMBK`

- `u8 tag` : 0 uniforme, 1 palette.
- Uniforme : `u16 value`.
- Palette : `u8 bits` ∈ {1, 2, 4, 8, 16} ; `u16 palette_len` (≤ 256, 0 si 16 bits) ; `u16 palette[palette_len]` ; indices : 512 × `bits` bits, voxel i aux bits `[i·bits, i·bits + bits)` du flux d'octets, bit de poids faible d'abord. Ordre des voxels : **x, puis z, puis y** (`docs/interfaces.md` § 2).
- Une brique d'éditions redevenue égale à la brique de base est retirée au compactage.

### 2.6 Enregistrement d'entité

`u32 id`, `u32 revision`, `u16 recipe_kind`, `u16 recipe_version`, `u64 seed`, `u64 base_ref` (0 si créée), `i32 anchor[3]` (voxels, repère monde), `u8 quarter_turns`, `u8 flags` (bit 0 détruite, bit 1 mobile), `u16 params_len`, `params`, `u16 parts_len`, état des parties (bits « retirée » puis `u8` de dommage par partie abîmée), `u32 patch_bricks`, puis n × { `i16 bx, by, bz` (briques dans le repère local de l'entité), brique EMBK }.

---

## 3. Charges utiles des opérations

En-tête : `Operation` v1 de `engine/ops/include/emergence/ops/operation.h`, 48 octets dans cet ordre (vérifié dans `operation.cpp`) : `u64 op_id`, `u64 tick`, `u32 seq`, `u32 author`, `u64 cause`, `u16 kind`, `u16 process`, `u16 gesture`, `u8 flags`, `u8 version` = 1, `u32 payload_bytes`, `u8 noise`, `u8 sight`, `u8 trace`, `u8 reserved`. Une opération porte **un seul élément** de sa sorte, champs bruts à la suite (comme `engine/act/src/entity_ops.cpp`).

| Sorte | Charge | Repère |
|---|---|---|
| 2 `VoxelEdit` (drapeau `kFlagVoxels`) | `u8 shape`, `i32 p[7]`, `u16 new_voxel` (0 = air), `u16 only_class` (`0xFFFF` = toutes), `u32 changed` (**toujours 0** : `Applier::apply` reçoit l'opération en lecture seule ; le nombre de voxels changés va dans les statistiques), puis la suite propre à `list` | voxels, **monde** (y haut) |
| 3 `EntityDelta` | `u32 entity`, `u16 var`, `i32 old`, `i32 new` (C++ existant) | — |
| 4 `Spawn` | `u32 expected`, `u16 kind`, `i32 pos_mm[3]`, `u32 holder`, `u16 sort` (C++ existant ; il ajoute `sort` à docs/14) | mm, **act** (z haut) |
| 5 `Destroy` | `u32 entity` | — |
| 6 `Move` | `u32 entity`, `i32 to_mm[3]`, `u32 holder` ; côté monde, l'ancre voxel de la forme suit (mm convertis en voxels du monde, arrondi vers le bas) | mm, **act** |
| 8 `EntityRecipe` (nouvelle ; drapeaux `kFlagEntities \| kFlagVoxels`) | `u32 entity`, `u32 expected_revision`, `u16 recipe_kind`, `u16 recipe_version`, `u64 seed`, `u64 base_ref`, `i32 anchor[3]`, `u8 quarter_turns`, `u8 mode` (0 donner ou remplacer la forme, 1 matérialiser `base_ref`, 2 retirer la forme), `u16 params_len`, `params` | voxels, **monde** |
| 9 `EntityParts` (nouvelle ; drapeaux `kFlagEntities \| kFlagVoxels`) | `u32 entity`, `u32 expected_revision`, `u16 n`, n × { `u16 part`, `u8 action` (0 retirer, 1 remettre, 2 abîmer), `u8 amount` } | — |

**Compatibilité avec le C++** : `engine/ops` refuse aujourd'hui toute sorte au-delà de 7 (`kMaxKnownKind`, `operation.cpp`) ; les tests croisés portent donc sur les sortes 1 à 7, et une tâche C++ hors laboratoire montera `kMaxKnownKind` à 9. **Naissance d'une entité physique** : `Spawn` (le C++ attribue l'`EntityId` et la sorte du catalogue) puis, dans le même pas, `EntityRecipe` (la forme) ; la matérialisation d'un objet de base suit le même ordre, avec `mode` = 1 et le `base_ref`.

**Formes de `VoxelEdit`** (calculs en entiers 64 bits ; un voxel v a pour centre `16·v + 8` en seizièmes de voxel) :

| `shape` | `p[0..7]` | Règle |
|---|---|---|
| 0 `box` | min (voxels), max exclusif (voxels), — | `min ≤ v < max` |
| 1 `sphere` | centre (1/16 voxel), rayon (1/16 voxel), — | `Σ(16v + 8 − c)² ≤ r²` |
| 2 `capsule` | a (1/16), b (1/16), rayon (1/16) | distance au segment ≤ r (projection en Q16 bornée à [0, 1]) |
| 3 `list` | `p[0]` = n | suivi de n × `i32[3]` (voxels) |
| 4 `module` | identifiant VXB3, pivot (voxels), quarts de tour | réservé (docs/14) |
| 5 `blob` (nouvelle) | centre c (1/16), rayon r (1/16), rugosité ρ ‰, longueur d'onde λ (1/16, ≥ 16), — | voxel inclus si `‖q‖² ≤ r_v²`, avec `q = 16v + 8 − c` et `r_v = r × (1000 + ρ × (n − 500) / 500) / 1000` ; `n` ∈ [0, 1000] est un bruit de valeur 3D entier : cellule `g = floor_div(q, λ)`, poids `w = (q − g·λ) × 1000 / λ` par axe, valeurs aux 8 coins `hash3(graine, gx, gy, gz) % 1001` avec `graine = hash_combine(seed_monde, op_id)` (règle de docs/14 § 4.5 : le hasard vient de la graine du monde et de l'opération), interpolation trilinéaire en entiers (‰). Vecteurs de test épinglés en L19 |

`only_class` + `new_voxel` font les **transformations** (pierre → sable ; `new_voxel` = 0 avec `only_class` = « faire disparaître cette matière seulement »).

**Conversion de repère** (une seule fonction, `em_core::frame`) : `(x, y, z)_monde = (x, z, y)_act` pour les positions en mm ; jamais ailleurs.

---

## 4. Registres

### 4.1 Recettes (`RecipeKind`, `u16`, ajout seul ; `em_assembly::registry`)

| Id | Nom | Paramètres (v1) | Tâche |
|---|---|---|---|
| 0 | invalide | — | — |
| 1 | `vxm_model` | `u64` empreinte du nom de modèle (pont provisoire) | L28 |
| 2 | `tree` | essence, hauteur (mm), saison, densité de feuillage (‰) | L31 |
| 3 | `bush` | essence, hauteur, saison, topiaire | L32 |
| 4 | `log` (bûche) | essence du bois, longueur (mm), diamètre (mm) | L28 |
| 5 | `table` | essence, longueur, largeur, hauteur (mm), style | L28 |
| 6 | `stone_wall` | longueur, hauteur, épaisseur (voxels), appareil (assises réglées / moellons), pierre, mortier | L23 |
| 7 | `beam` (poutre) | axe, section (voxels), longueur, essence, usure | L23 |
| 8 | `post` (poteau) | section, hauteur, essence | L23 |
| 9 | `rock` | taille, matière, forme | après le labo |
| 10 | `lantern` | matière, couleur et intensité de la flamme (déclare une lumière) | L25 |
| 11 | `tree_silhouette` | essence, hauteur (proxy lointain) | L32 |

Les parties d'un assemblage (`PartList`) portent un identifiant de **forme du catalogue** (`catalogue/data/forms.toml`, P28) et un nom de matière, pour que le C++ (`ContactResolver`, qui lit les propriétés des parties) et la forme physique Rust parlent des mêmes parties.

### 4.2 Générateurs (`GeneratorId`, `u16`)

1 `vxm`, 2 `tree`, 3 `bush`, 4 `wall`, 5 `beam`, 6 `table`, 7 `log`, 8 `lantern`, 9 `tree_silhouette`, 10 `lab_landscape` (terrain), 11 `post`, 12 `rock`. Chaque générateur a une `version` ; changer sa sortie oblige à l'incrémenter et à refaire ses empreintes.

---

## 5. Dispositions GPU

### 5.1 Clipmap de briques

```wgsl
struct ClipLevel {                 // 6 entrées, tampon uniforme
  origin_chunk: vec3<i32>,         // coin du cube en chunks DU NIVEAU (voxel monde >> (6 + lod))
  lod: u32,
  table_offset: u32,               // lod × 4096
  _pad0: u32, _pad1: u32, _pad2: u32,
};
@group(1) @binding(0) var<uniform> levels: array<ClipLevel, 6>;
@group(1) @binding(1) var<storage, read> chunk_table: array<u32>;  // 6 × 16³
@group(1) @binding(2) var<storage, read> chunk_pool: array<ChunkGpu>;
@group(1) @binding(3) var<storage, read> brick_occ: array<vec4<u32>>; // 4 par brique = 512 bits
@group(1) @binding(4) var<storage, read> brick_meta: array<vec2<u32>>;  // 2 mots par brique
@group(1) @binding(5) var<storage, read> payload: array<u32>;
struct ChunkGpu { mask_all: array<u32, 16>, mask_visible: array<u32, 16>, bricks: array<u32, 512> };   // 2 176 o
```

- **Index de table** : `table_offset + (cx & 15) + 16 × (cz & 15) + 256 × (cy & 15)`, valable seulement si le chunk est dans `[origin, origin + 16)` sur chaque axe.
- **Entrée de chunk** : `0xFFFFFFFF` vide ; bit 31 = plein uniforme (bits 0-15 = valeur, bits 16-30 = 0, donc jamais égal à `0xFFFFFFFF`) ; sinon bits 0-23 = case dans `chunk_pool`, bit 24 = contient des briques de peau, bit 25 = contient des briques visibles (non `skin`) : seuls ces chunks ont une boîte dans la passe `t_enter`. `mask_all` sert aux modes `OCCLUSION` et au mode `PRIMARY` sans peau ; `mask_visible` au mode `PRIMARY` avec peau et au mode `SHADOW_MAP`.
- **Entrée de brique** : `0xFFFFFFFF` vide ; bit 31 = uniforme (bits 0-15 = valeur, bit 30 = `skin`, bit 29 = `edited`, bits 16-28 = 0, donc jamais égal à `0xFFFFFFFF`) ; sinon bit 31 = 0, bits 0-23 = case de brique (la case `0xFFFFFF` est réservée), bit 30 = `skin`, bit 29 = `edited`.
- **Bits** : voxel i = `x + 8z + 64y` (même ordre que le CPU) ; brique b = `bx + 8bz + 64by`.
- **`brick_meta`** (deux mots par brique) : mot 0 = décalage en **mots** dans `payload` (32 bits : jusqu'à 16 Gio, aucune limite pratique) ; mot 1 = bits 0-3 `log2(bits)` (0 → 1 bit, 1 → 2, 2 → 4, 3 → 8, 4 → 16 bits), bits 8-15 `palette_len − 1` (1 à 256 entrées ; ignoré à 16 bits), le reste à 0. Dans `payload` : la palette (deux `u16` par mot), puis les indices (bit de poids faible d'abord).
- **Allocation** : une classe de taille par nombre de bits, exactement à la mesure : 1 bit → 18 mots (1 de palette + 16 d'indices, arrondi pair), 2 bits → 34 mots, 4 bits → 72 mots, 8 bits → 256 mots, 16 bits → 256 mots ; listes libres par classe ; défragmentation jamais pendant une image.
- **Limites** : demander à l'adaptateur `max_storage_buffer_binding_size` et `max_buffer_size` jusqu'à 1 Gio (défaut de `wgpu` : 128 Mio), `max_storage_buffers_per_shader_stage` ≥ 16 (défaut 8), `max_storage_textures_per_shader_stage` ≥ 8 (défaut 4 ; le tracé écrit 5 textures), `max_compute_workgroup_storage_size` ≥ 32 Kio (défaut 16 Kio) ; voir `docs/19` § 7.1.

### 5.2 G-buffer (formats écrits par le compute ET par le raster)

| Cible | Format | Contenu |
|---|---|---|
| GB0 | `rgba8unorm` | albédo encodé sRGB à la main (rgb), occlusion de matière (a) |
| GB1 | `r32uint` | normale octaédrique 2 × 16 bits |
| GB2 | `rgba8unorm` | rugosité, translucidité, émission (échelle logarithmique), drapeaux (feuillage, eau, herbe, voxel) |
| GB3 | `r32uint` | mouvement en pixels (`pack2x16float`), 0 = reprojection par la profondeur |
| Profondeur | `Depth32Float`, Z inversé infini, test `Greater`, effacée à 0 | — |
| Distance du tracé | `R32Float` | distance le long du rayon |

`rgba8unorm-srgb` n'est pas accepté en écriture de stockage : d'où l'encodage sRGB à la main dans les deux chemins. Les pipelines de profondeur et de G-buffer de la peau déclarent `@invariant` sur la position (test `Equal` exact, voir L17 en 19b).

### 5.3 Matières

```rust
#[repr(C)] #[derive(Copy, Clone, bytemuck::Pod, bytemuck::Zeroable)]
pub struct MaterialGpu {                  // 64 octets, 512 entrées (indice = classe)
    pub albedo_linear: [f32; 3], pub albedo_var: f32,
    pub hue_var: f32, pub voxel_jitter: f32, pub roughness: f32, pub roughness_var: f32,
    pub relief: f32, pub detail_strength: f32, pub detail_scale_m: f32, pub translucency: f32,
    pub emission: f32, pub detail_layer: u32, pub tint_mode: u32, pub flags: u32,
}
```

Tampons annexes : `class_ramps: array<vec4<f32>>` (3 couleurs par classe : sombre, moyen, clair) ; `veg_ramps: array<vec4<f32>>` indexé par ((essence × 4 + rôle) × 4 + rampe) × 3 couleurs (rôles : 0 écorce, 1 feuilles, 2 fleurs, 3 fruits), plus une **graine de matière par essence** (`u32`, hachage du nom de l'essence) qui amorce le bruit de valeur des feuilles et de l'écorce, pour la **saison courante** (la saison est globale ; changer de saison réécrit le tampon).

**Sens des 7 bits de teinte** (`tint_mode`) :

| Mode | Bits | Sens |
|---|---|---|
| `ramp128` | 7 | nuance 0..127 dans la rampe de la classe |
| `wood_axis` | axe 2 + variante 5 | axe du fil : 0 x (est), 1 y (haut), 2 z (nord), 3 bois de bout ; variante = planche ou pièce |
| `stone_piece` | pièce 7 | numéro haché de la pierre ; 0 = mortier ; le joint n'existe qu'entre deux pièces différentes |
| `vegetation` | essence 5 + variante 2 | case d'essence (≤ 32 : aujourd'hui 7 arbres + 9 arbustes [Mesuré]) ; variante : écorce 0, écorce secondaire 1, rameau 2 (classe `bark`) ; rampe de fleur (≤ 4) ou de fruit (≤ 2) ; **feuilles : 0**, leur rampe est tirée au shader |
| `terrain` | variante 7 | variante lente (strates, humidité) |

### 5.5 Sondes d'irradiance

Formats inscriptibles en stockage dans le cœur de `wgpu` 30, sans fonctionnalité propre à l'adaptateur : irradiance et visibilité en **`r32uint` empaqueté**. Irradiance : un texel = couleur en R11G11B10 flottant empaquetée à la main (même codage que `rg11b10ufloat`), atlas de 8 × 8 texels par sonde (6 × 6 + bordure). Visibilité : un texel = moyenne et moyenne des carrés de la distance en `pack2x16float`, atlas de 16 × 16 par sonde (14 × 14 + bordure). Lecture : filtrage bilinéaire fait à la main (4 lectures par atlas), d'où 1,28 Ko par sonde et 63 Mo pour 3 niveaux de 16 384 sondes, + ≈ 3 Mo pour le niveau de 0,5 m.

### 5.4 Uniformes d'image

```wgsl
struct Frame {
  view_proj: mat4x4<f32>,       // relatif à la caméra, Z inversé infini (comme web-ocean)
  inv_view_proj: mat4x4<f32>,
  prev_view_proj: mat4x4<f32>,
  cam_voxel: vec4<i32>,         // voxel entier de la caméra (niveau 0) ; w = n° d'image
  cam_frac: vec4<f32>,          // position dans ce voxel en m ; w = temps (s)
  cam_right: vec4<f32>, cam_up: vec4<f32>, cam_fwd: vec4<f32>,
  sun_dir: vec4<f32>,           // vers le soleil ; w = éclairement
  screen: vec4<f32>,            // largeur, hauteur, 1/largeur, 1/hauteur
  jitter: vec4<f32>,            // gigue courante (xy), précédente (zw), en pixels
  atmo: vec4<f32>,              // brume (mie), altitude caméra en km
  post: vec4<f32>,              // exposition, bloom, n° d'image, vignette
  fog: vec4<f32>, wind: vec4<f32>, style0: vec4<f32>, style1: vec4<f32>,
};
```

---

## 6. Fichiers de données et de configuration

### 6.1 `engine/data/materials.csv` (physique, existant)

Inchangé, ajout seul : L06 ajoute `34,petal,plant,…` et `35,fruit,plant,…` ; L23 ajoute `36,mortar,building,…` si l'appareil de pierre en a besoin. **Aucune matière « chaux blanche »** pour les murs (consigne de `Map/ARCHITECTURE.md` et image « pas bon chaux »).

### 6.2 `engine/data/material_render.toml` (aspect, nouveau)

```toml
schema_version = 1
[default]
albedo_var = 0.08      # amplitude du champ continu (fraction de la luminance)
hue_var = 0.02
voxel_jitter = 0.03    # gigue par voxel : le grain pixel, sans mosaïque
roughness = 0.8
roughness_var = 0.1
relief = 0.3
detail = ""            # couche de l'atlas (manifeste des textures), vide = aucune
detail_strength = 0.12
detail_scale_m = 0.5
translucency = 0.0
emission = 0.0
tint_mode = "ramp128"
flags = []             # "foliage", "moss", "skin", "flicker"

[material.leaves]
tint_mode = "vegetation"
translucency = 0.45
flags = ["foliage"]

[material.wood_trim]
tint_mode = "wood_axis"
detail = "wood_fine"
```

### 6.3 Manifeste des textures (`engine-rs/lab/textures.toml`)

Le manifeste est dans `engine-rs/` (lisible et versionné) ; les images téléchargées vont dans `assets/textures/` (hors git, et ignoré par `.claudeignore`).

Une entrée par couche : `layer` (nom utilisé par `material_render.toml`), `source` (ambientCG ou Poly Haven), `asset_id`, `url`, `licence` = `"CC0-1.0"`, `sha256` de l'archive, fichiers retenus (couleur, hauteur, rugosité), résolution. `engine-rs/scripts/fetch_textures.py` télécharge dans un dossier vide, vérifie l'empreinte, n'extrait que les images listées, puis `em_lab assets pack` construit l'atlas (512² par couche, rgba8 : luminance du détail, hauteur, rugosité, occlusion).

### 6.4 Scène (`engine-rs/lab/scenes/<nom>.toml`)

```toml
name = "arbre"
origin_m = [10000.0, 0.0, 10000.0] # coin de la scène dans le monde (le monde commence à (0, *, 0) au sud-ouest) ;
                                   # toutes les positions de la scène sont relatives à ce point
landscape = "flat_turf"           # flat_turf | lab_landscape
[[model]]
path = "lab/models/chene_42.vxm"
at_m = [0.0, 0.0, 0.0]
quarter_turns = 0
[[shot]]
name = "face"
pos_m = [12.0, 1.7, -8.0]
yaw_deg = 140.0
pitch_deg = 8.0
fov_deg = 60.0
hours = [10.0, 17.5, 19.0]
```

### 6.5 Style (`engine-rs/lab/style/style.toml`)

Clés regroupées par section (`[exposure]`, `[agx]` : saturation, contraste, chaleur ; `[bloom]` ; `[fog]` : densité, hauteur, couleur ; `[materials.<nom>]` : surcharges de 6.2 ; `[taa]` : netteté ; `[grass]` : densité, portée ; `[skin]` : mode `cell` ou `blend`). Rechargé à chaud dans la fenêtre ; copié dans le JSON de chaque capture.

### 6.6 Rapport de banc (JSON)

```json
{ "scene": "foret_dense", "frames": 600, "warmup": 120, "resolution": [1920, 1080],
  "adapter": "Quadro RTX 3000", "driver": "615.71.09",
  "passes": [ { "name": "voxel_trace", "median_ms": 0.0, "p95_ms": 0.0, "n": 600 } ],
  "total_median_ms": 0.0, "total_p95_ms": 0.0,
  "gpu_clocks": { "sm_mhz_median": 0, "mem_mhz_median": 0, "temp_c_max": 0, "power_w_median": 0.0 },
  "style_sha256": "", "world_fingerprint": "" }
```

---

## 8. Types communs (contrat des tâches)

Types utilisés par plusieurs tâches, avec leurs champs. Règles orientées objet de `docs/19` § 2.7 : champs privés et constructeurs pour tout ce qui porte un invariant ; champs publics seulement pour les configurations validées et les dispositions GPU.

| Type (crate) | Contenu | Créé par |
|---|---|---|
| `WorldManifest` (`em_world`) | graine, `world_id`, versions des générateurs (`[u32; 8]`), version de la table des matières, empreinte du plan ; codec EMWM v1 (§ 2.2) | L19 |
| `GenParams` (`em_gen`) | paramètres décodés d'un générateur : `generator: GeneratorId`, `version: u32`, octets bruts privés + accesseurs typés par générateur | L08 |
| `GenError` (`em_gen`) | `BadParams`, `UnknownSpecies`, `Io` (`thiserror`) | L08 |
| `LocalLight` (`em_gen`) | position locale en mm, couleur sRGB, intensité (lm), rayon (mm), scintillement (‰) | L25 |
| `RecipeParams` (`em_assembly`) | paramètres décodés d'une recette (énumération par sorte de recette) | L23 |
| `Part`, `PartList` (`em_assembly`) | partie : `id: u16`, `form` (identifiant de `catalogue/data/forms.toml`), matière, boîte locale ; liste ordonnée par `id` | L23 |
| `PartState` (`em_assembly`) | bits « retirée » + dommage (`u8`) par partie ; méthodes `is_removed`, `damage` | L23 |
| `BrickMask` (`em_voxel`) | 512 bits (`[u64; 8]`) : une brique par bit, ordre `bx + 8bz + 64by` | L05 |
| `SkirtMask` (`em_mesh`) | 6 bits : faces du chunk dont le voisin est d'un autre niveau | L16 |
| `ChunkFlags` (`em_render`) | `has_skin`, `has_visible`, `edited` | L09 |
| `Ray`, `Hit`, `VoxelHit` (WGSL, `em_render`) | rayon : origine relative à la caméra, direction, `t_min`, `t_max`, mode ; impact : distance, niveau, voxel, face, point, valeur | L09 |
| `SurfaceSample` (WGSL, `em_material`) | albédo linéaire, normale, rugosité, translucidité, émission, occlusion de matière | L10 |
| `FrameContext` (`em_render`) | n° d'image, temps, caméra, soleil, uniformes `Frame`, préréglage, style courant | L02 |
| `Resources` (`em_render`) | textures et tampons nommés du graphe (G-buffer, profondeurs, HDR, HiZ) ; accès par nom typé, jamais par chaîne libre | L02 |
| `QualityKnob` (`em_render`) | nom, valeur courante, valeurs permises, coût estimé ; modifiable par le panneau de style | L13 |
| `TargetFrame` (`em_render`) | vue de la texture de sortie de l'image (fenêtre ou hors écran) | L02 |
| `Shot` (`em_lab`) | nom, position relative à `origin_m`, lacet, tangage, champ, heures | L08 |
| `SceneContext` (`em_lab`) | accès au GPU, à la table des matières, aux modèles chargés ; aucune globale | L08 |
| `LabWorld` (trait, `em_lab`) | `voxel_source() -> Arc<dyn VoxelSource>`, `skin_source() -> Option<Arc<dyn SkinSource>>`, `lights() -> &[LocalLight]`, `water() -> Option<&dyn WaterSurfaceSource>` ; implémenté par `StaticScene` (L08) puis par l'adaptateur d'`em_world` (L19) | L08 |

## 7. Interface C vers le moteur des PNJ (prévue, crate `em_capi`, phase 7)

Rien de ceci n'est codé pendant le laboratoire. Les signatures fixent ce que le monde devra fournir ; elles reprennent les interfaces C++ existantes (`Applier`, `SpaceQuery`, `ViewProbe`). Positions en **mm, repère act (z haut)** ; conversion par `em_core::frame` seulement.

```c
typedef struct EmWorld EmWorld;

/* Abonné du bus C++ (Applier n° 2 voxels et n° 3 champs) : l'hôte appelle, dans l'ordre du bus. */
uint8_t  em_world_apply(EmWorld*, const uint8_t* op_bytes, size_t len);  /* ApplyStatus : 0 Applied, 1 Deferred, 2 Ignored, 3 Rejected */
void     em_world_end_of_flush(EmWorld*);
uint64_t em_world_fingerprint(const EmWorld*);
uint64_t em_world_last_op_id(const EmWorld*);

/* Le monde soumet ses propres opérations (effondrement, eau, conversion d'une VoxelRequest de T18). */
typedef uint8_t (*em_submit_fn)(void* user, const uint8_t* op_bytes, size_t len, uint32_t decision_seq, uint32_t k);
void     em_world_set_sink(EmWorld*, em_submit_fn submit, void* user);
uint8_t  em_world_voxel_request(EmWorld*, uint64_t tick, uint32_t author, uint16_t process,
                                const int32_t at_mm[3], uint16_t material, int32_t depth_mm);

/* SpaceQuery (T23) : const, pur, appelable depuis plusieurs fils à la fois. */
uint16_t em_space_sight_transmission(const EmWorld*, const int32_t eye_mm[3], const int32_t target_mm[3]);
uint16_t em_space_sound_transmission(const EmWorld*, const int32_t src_mm[3], const int32_t dst_mm[3]);
int16_t  em_space_light_at(const EmWorld*, const int32_t p_mm[3], int64_t game_time);
int16_t  em_space_ambient_noise_at(const EmWorld*, const int32_t p_mm[3]);
uint8_t  em_space_indoors(const EmWorld*, const int32_t p_mm[3]);
uint16_t em_space_fog_permille(const EmWorld*, const int32_t p_mm[3]);

/* ViewProbe (T23b) : utilisé par le Navigator C++, qui implémente lui-même NavigationQuery. */
uint8_t  em_view_blocked(const EmWorld*, const int32_t from_mm[3], const int32_t to_mm[3]);
```

Règles : les requêtes lisent un **instantané en lecture seule** de l'occupation (double tampon publié à la fin de chaque `flush`) ; aucune ne lit la vérité au-delà de ce qu'elles déclarent (P51 : le `Navigator` ne demande jamais un point hors du champ de vue de l'acteur) ; `em_space_light_at` combine la lumière du ciel (heure, nuages) et l'occlusion des sondes, sur l'échelle 0..100 de la charte.
