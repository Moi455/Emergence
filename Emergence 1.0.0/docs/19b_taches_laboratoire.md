# Annexe 19b : tâches du laboratoire de style (L01 à L32)

Plan exécutable par des agents Sonnet, d'après `docs/19_laboratoire_architecture.md` (architecture) et `docs/19a_formats_et_interfaces.md` (formats). Ordonné pour montrer des **aperçus à Monsieur le plus tôt possible**.

## Règles communes à toutes les tâches

1. **Lire d'abord** : `docs/19` (les § cités par la tâche), `docs/19a`, ce fichier, `engine-rs/README.md`. Les signatures écrites ici sont **le contrat** : un changement passe par l'orchestrateur, qui met à jour ce fichier.
2. **Rust** : `cargo build --workspace --release`, `cargo test --workspace`, `cargo clippy --workspace -- -D warnings` verts à la fin de chaque tâche. Règles de `docs/19` § 2.4 (crates de vérité sans flottants, sans `HashMap`, sans `unsafe`). Commentaires et messages en français.
3. **Mesures** : tout chiffre rendu porte son statut ([Mesuré], [Calculé], [Estimé]) ; les temps GPU viennent de `em_lab bench` sur la Quadro (lancé par `engine-rs/scripts/lab.sh`), jamais d'une estimation. Un critère rouge se rapporte tel quel, avec la mesure.
4. **Capture pour Monsieur** : chaque tâche visuelle dépose ses PNG dans `engine-rs/lab/captures/AAAA-MM-JJ/`, copie les retenues dans `docs/apercus/NN_<nom>.png` et ajoute une ligne « présentée » dans `docs/19c_journal_style.md`, avec les questions précises à lui poser.
5. **Relecteur adverse** après chaque tâche (CLAUDE.md), puis corrections avant de rendre.
6. **Commits** : décidés par la session qui orchestre (consigne de Monsieur pour chaque session).
7. **Statut** : l'agent met à jour la table ci-dessous (statut, date, résultat mesuré en une ligne).
8. **Orienté objet, rigoureusement** (« Codez bien orienté objet », Monsieur, 20 oct.) : règles de `docs/19` § 2.7. Dans les signatures ci-dessous, un champ `pub` n'est permis que pour une configuration validée (`…Config`, `…Params`), un rapport de mesure en lecture seule (`ProfileReport`, `ImageDiff`, `BusStats`) ou une disposition GPU `#[repr(C)]` rangée dans un module `gpu` ; partout ailleurs, champs privés, constructeur qui vérifie l'invariant, accesseurs. Le relecteur refuse une globale, un `static mut`, un singleton, un `match` sur un nom à la place d'un trait.
9. **Lecture des sources** : avant L01, l'orchestrateur retire de `.claudeignore` les lignes `engine/core/base/`, `engine/core/world/`, `engine/core/mesh/`, `engine/em_water/`, `générateurs de voxels/` et `docs/style/` (la condition « [RÉINTÉGRER QUAND] on attaque le rendu, l'eau » est remplie), puis lance `python3 scripts/sync_claudeignore.py` : L01, L03, L05 et L21 lisent ces fichiers.
10. **Budget** : rendu ≤ 50 % du GPU (décision de Monsieur) : plafond dur 8,3 ms, cible 6,5 ms, préréglages `haut`/`moyen`/`bas` de `docs/19` § 1.4 ; les seuils de coût des tâches ci-dessous sont ceux du préréglage `haut`.

Tailles : **S** ≤ 400 lignes, une demi-journée d'agent ; **M** 400 à 1 200 lignes ; **L** 1 200 à 2 500 lignes (le découper en sous-étapes testées).

## Table de suivi

| Tâche | Titre | Taille | Dépend de | Parallèle avec | Statut | Date | Résultat mesuré |
|---|---|---|---|---|---|---|---|
| L01 | Workspace + `em_core` | M | — | L02, L04 | fait | 2026-10-20 | [Mesuré] 13 crates ; build release, test (26 tests), clippy -D warnings verts ; 7 familles de vecteurs C++ égales (≈ 650 vecteurs) ; erreur max sin/cos 7,6e-6, atan2 6,3e-6, qlog2 7,6e-6 (limite 2⁻¹⁴ = 6,1e-5) |
| L02 | Hôte de rendu : adaptateur, hors écran, fenêtre, PNG, profileur | M | — | L01, L04 | fait | 2026-10-20 | [Mesuré] adaptateur « Quadro RTX 3000 » (Vulkan, NVIDIA 615.71.09) ; limites accordées 8+ textures / 16+ tampons de stockage, 32 Kio partagés, 1 Gio par liaison ; 2 captures 1920×1080 identiques octet pour octet (sha256 égaux), 0,3 à 0,5 s de rendu ; `bench --frames 600` : ciel 0,141 ms, texte 0,010 ms, total 0,151 ms (médiane, p95 0,152, n = 600, SM ≈ 1000 MHz) ; fenêtre Wayland OK sans PRIME (Échap, F12) ; sans pilote désigné : refus clair, code 2 ; build release, test, clippy verts. Écarts de signature : `RenderGraph::add` et `render` renvoient `Result`, `FrameTarget::acquire` renvoie `Result`, `read_texture_png` renvoie `CaptureError` ; `em_lab` a reçu `winit`, `serde_json`, `glam` ; `bench.sh` non créé (`lab.sh bench`) |
| L03 | Ciel de Hillaire, bloom, AgX (port `web-ocean`) | M | L02 | L05, L06 | fait (budget : voir résultat) | 2026-10-20 | [Mesuré, Quadro RTX 3000, 1080p, SM ≈ 1110 MHz, 600 images] ciel steady : `ciel_lut` absente (LUT recalculées seulement au changement), 0,084 ms si le soleil bouge à chaque image ; `ciel_fond` (ciel + nuages demi-rés. + sol + crêtes + étoiles) 0,83 ms ; `bloom` 8 niveaux 0,19 ms ; `tonemap` AgX 0,13 ms ; total 1,15 ms (sans nuages 0,75). Budget docs/19 § 1.4 : ligne 2 (0,10) TENUE (0,084 au pire) ; lignes 16 et 17 (0,15 et 0,04) DÉPASSÉES de 0,04 et 0,09 ; le fond de ciel (0,83) dépasse sa part dans la ligne 12 (0,65 pour tout l'éclairage). Sans cube d'environnement ni visibilité du soleil (non branchés, extraits et validés pour L21). 7 captures reproductibles (sha256 égaux), 3 essais GPU (aucun NaN/inf sur 7 heures × 2 sens, reproductibilité, recalcul paresseux), `shaders_validate` (10 modules naga) ; build release, test, clippy -D warnings verts. Écarts de signature : `SkyParams` à champs privés (élévation, azimut, turbidité, brume ; `SunModel::position(heure)`), pas de `sun_visibility`/`env_cube`, `SkyBackgroundPass` en deux étages, `PassContext::render_pass_to` ajouté, le profileur additionne les portées d'une même passe ; `scripts/serie_ciel.sh`, `lab.sh capture --scene ciel --sun-elevation … --sun-azimuth …` |
| L04 | Exporteur `.vxm` (Python) | S | — | L01, L02 | fait (sauf `export_vegetation.sh`) | 2026-10-20 | [Mesuré] chêne 42 de 14 m : 607 784 voxels au LOD0 (+248 doublons écorce/rameau écartés), 6 LOD en 3,4 s, 935 393 o (zlib), exportations identiques octet pour octet, empreintes de génération avant/après identiques (9 cas), 31 tests verts ; écart des boîtes de LOD jusqu'à 1,5 voxel grossier (spec : ±1) ; arbustes : LOD dont le voxel dépasse la hauteur omis ; pas de saule dans `voxel_tree.py` ; `engine-rs/scripts/export_vegetation.sh` remplacé par `tools/vegetation/export_reference_assets.py` (consigne : ne pas toucher à `engine-rs/`) |
| L05 | `em_voxel` : briques, chunks, sources, empreintes | M | L01 | L03, L06 | fait (crate seul vert ; workspace non vérifiable : `em_render` et `em_material` en cours chez d'autres agents) | 2026-10-20 | [Mesuré, release, 1 fil] 22 tests de propriété verts, clippy -D warnings vert (toutes cibles) ; chunk 64³ : air et plein 32 o, sol plat 15 136 o, relief 3 matières 47 776 o, bruit 552 992 o (dense 524 288 o) ; lecture 127 Mvoxels/s, écriture ChunkWriter 25 Mvoxels/s, depuis dense 508 Mvoxels/s ; `CompositeSource` 3 couches : 0,046 ms/chunk (seuil 0,3 ms tenu) ; `cargo run --release -p em_voxel --example mesures` |
| L06 | `em_material` : table, teintes, paquet GPU | M | L01 | L03, L05 | fait (crate vert ; clippy du workspace rouge à cause d'`em_render`, L02, pas d'`em_material`) | 2026-10-20 | [Mesuré] 36 classes, `MaterialGpu` = 64 o, paquet 81 Ko (32 768 + 24 576 + 24 576 + 128) ; 38 tests (build/test/clippy `-D warnings` verts pour la crate, avec et sans `gpu`, debug et release) ; empreintes épinglées : paquet `0xd4460f47e8c9ae23`, évaluation CPU `0x4b2051d3d4d4da37` ; erreurs `MaterialError` (thiserror) au lieu d'`anyhow::Result`, `register` renvoie `Result<u8, _>` |
| L07 | Comparateur d'images, références | S | L02 | L03-L06 | à faire | | |
| L08 | Chargeur `.vxm` + scène statique | S | L04, L05, L06 | L07 | fait | 2026-10-20 | [Mesuré, release] chêne 42 (935 393 o) chargé en 23,6 ms min / 27,8 ms médiane / 34,4 ms max (n = 15 ; seuil 300 ms) ; 607 784 voxels au LOD 0 retrouvés après rastérisation en chunks aux 4 quarts de tour ; 5,62 Mo de voxels pour les 6 LOD ; rastérisé : 48 chunks, 4 450 briques non vides (toutes à palette), 0,99 Mo au LOD 0 (14 chunks / 789 briques / 0,23 Mo au LOD 1) ; échantillon de 10 000 voxels et boîtes des 6 LOD égaux à `read_vxm.py` ; empreintes épinglées : contenu `0x75d986c2b4b5ddee`, chunks LOD 0 `0xaea741cffc7a91c7` (rotation 1 : `0x9bc5c3a5d1fcfab3`) ; orientation (rouge +x, bleu +z, vue de dessus rouge à droite) et quarts de tour verts ; build release, test, clippy -D warnings verts ; `cargo run --release -p em_gen --example mesures`. Écarts : `em_gen` reçoit `Generator`/`GenPlan`/`GenParams`/`GenError` (sans `lights()`, créé par L25) ; un LOD absent ou vide est DÉRIVÉ du plus fin par réduction (pas servi tel quel, sinon l'échelle serait fausse), avec `VxmWarning` ; la lecture des scènes TOML est dans `em_lab/src/scene_statique.rs` (seul module à manier des flottants), `#[allow(dead_code)]` jusqu'à L09 ; aucune dépendance ajoutée ; `lab/scenes/arbre.toml` créé |
| L09 | Premier rendu voxel (tracé, G-buffer, éclairage direct) | L | L03, L05, L06, L08 | L16 | fait (budget : voir résultat) | 2026-10-20 | [Mesuré, Quadro RTX 3000, 1080p, 600 images, SM 1 515 à 1 650 MHz, `bench --scene arbre --shot …`, ms médiane] **tracé + matière** (budget ligne 6 : 1,0 ms ; tracé seul visé 0,6) : prise `feuillage` (arbre = 38 % de l'écran) tracé 2,09 + matière 1,15 = **3,24 ms** (×3,2) ; `trois_quarts` 1,45 + 0,73 = 2,18 ; `face` (arbre 10 %, sol 13 %, ciel 77 %) 1,21 + 0,67 = 1,88 (×1,9) ; `tronc` 1,62 + 1,14 = 2,76 ; **le critère « tracé seul ≤ 0,6 ms » est ROUGE (2,1 ms sur `feuillage`, 1,2 ms sur `face`)**. Autres passes (feuillage) : `voxel_profondeur` 0,05, `voxel_lumiere` 0,13, bloom 0,14, tonemap 0,09, fond de ciel 0,71 ; total image 4,36 ms (face 3,00 ; cible 6,5, plafond 8,3). Coût d'un rayon : ciel seul (aucun impact) 0,59 ms (plancher sans tracé 0,15), sol seul 0,65 ; matière de terrain 1,15 ms pour 2 M de pixels. Optimisations déjà passées : DDA incrémental imbriqué (chunks puis briques puis voxels) : ciel seul 1,25 -> 0,59 ms, `face` 1,77 -> 1,17 ; table de bits de chunks en uniforme : aucun gain (retirée). **Exactitude** : tracé GPU contre un DDA CPU de référence (f64, voxel par voxel) sur les 129 600 pixels d'une vue en perspective : 3 pixels différents (0,0023 %), voxel ET face égaux sur tous les autres ; silhouette orthographique IoU 0,996 (critère 0,99) sur la Quadro ET sur l'Intel ; albédo GPU contre `em_material` CPU : 10 125 pixels du chêne (sol, feuilles, écorce) ΔE max 0,73, mosaïque des 5 modes de teinte (rampe, terrain, bois, pierre, végétation à 4 rôles) 64 valeurs ΔE max 0,65 (critère 1) ; aucun NaN ni infini dans le HDR (3 vues dont une à la verticale) ; caméra à l'intérieur d'un voxel plein : face d'entrée vue, pas de plantage ; vue d'en haut : rouge à droite, bleu en haut ; 2 captures de 1080p identiques octet pour octet (sha256 égaux, aussi entre deux lancements). **Mémoire** : chêne 42 = 48 chunks mixtes, 4 450 briques, 108 244 mots de tas (0,43 Mo), 1 536 chunks de sol uniformes (rien d'alloué) ; chargement initial 0,86 Mo en 1 584 chunks ; un bloc modifié ne réécrit que son chunk (même mémoire) ; une fenêtre qui glisse de 2 chunks ne traite que la tranche neuve. **Manque (assumé)** : ombres (L11), occlusion (L14), indirect (L15), translucidité des feuilles, TAA (L12) ; une seule clipmap (25 m autour de la caméra : l'arbre entier doit y tenir, d'où des prises à moins de 20 m ; L26 ajoute 5 niveaux) ; le sol est tracé en voxels et fondu vers le sol du ciel entre 14 et 25 m ; GB3 (mouvement) non créé (L12). **Écarts de signature** : `VoxelCamera` (position en mm entiers, repère gauche) à côté de la `Camera` libre de L02 (repère droitier, gardée pour le ciel) ; `FrameContext::new_voxel` et `view()` ; `Scene::camera_mut` remplacé par `deplacer` et `tourner` ; `ClipmapConfig` gagne `chunk_capacity` ; `VoxelGpuWorld::new` et `upload_chunk` renvoient des `Result` (`WorldError`) ; `ClipmapStreamer::update` renvoie un `StreamReport` (`update_until_complete` pour le préchargement) ; matière en passe séparée `VoxelMaterialPass` ; `em_gen::vegetation_ramps`, `em_voxel::Brick::packed_indices`, `em_material::{gpu_class_extra, gpu_counts}` ajoutés ; `em_render` reçoit `em_gen` en dépendance de développement ; `Cargo.toml` racine inchangé. `scripts/serie_arbre.sh`, `lab.sh capture --scene arbre --shot face --hour 17.5 [--camera x,y,z --look-at x,y,z --vue image|albedo|normales|distance|masque --ortho-hauteur m]`, `lab.sh bench --scene arbre --shot feuillage` |
| L10 | Matière v1 : végétation de `voxel_tree` | M | L09 | L11, L12, L13 | partiel : volet « feuillage vivant et lumière chaude » fait (matière v1 déjà en L09) ; voir résultat | 2026-10-21 | [Mesuré, Quadro RTX 3000, 1080p, 300 à 600 images, SM 1 500 à 1 530 MHz, `bench --scene arbre --hour 18.5`, ms médiane, AVANT -> APRÈS] **prise `feuillage` (caméra dans le houppier, pire cas : écran plein de feuilles à contre-jour)** : `voxel_lumiere` 0,180 -> 0,252 ; nouvelle passe `voxel_epaisseur` 0 -> 0,87 ; **prise `face` (arbre sur 25 % de l'écran)** : 0,164 -> 0,207 et 0 -> 0,36. Soit +0,94 ms (pire cas) et +0,40 ms (cas courant) pour le soleil seul, contre 0,65 ms visés pour l'éclairage de 8 lumières : **budget dépassé dans le pire cas, tenu dans le cas courant** (l'ambiance de l'hémisphère est précalculée par sommet : +0,04 ; le comptage d'épaisseur est le coût). **Fait** : (1) soleil = transmittance de Hillaire (déjà le cas depuis L09, désormais PROUVÉ : `feuillage_gpu::la_couleur_du_soleil_suit_la_transmittance_de_l_atmosphere`, GPU contre `AtmosphereReference` CPU, écart < 1 % à 60°, 30°, 14°, 9° ; LUT contre CPU : écart max 0,0005) ; ambiance = intégrale cosinus du ciel sur l'hémisphère de la face (8 directions, précalculée pour les 6 faces par sommet) au lieu d'une prise unique ; (2) translucidité : `FoliageThicknessPass` compte le feuillage traversé le long du soleil depuis le centre du voxel touché (DDA exact sur 8 cellules puis un échantillon tous les 1,5 voxel, borné à 48 voxels, soleil barré si un solide non feuillage s'y trouve), l'éclairage ajoute une transmission vert-jaune modulée par l'ombre de L11 lue au-delà de la zone (une prise) ; tests : plaque de feuilles à contre-jour = calcul CPU (`FoliageLightParams::translucent_radiance`, 6 %), nulle si un solide barre le soleil, nulle à l'ombre d'une autre feuille (au-delà de la zone), nulle face au soleil, moindre derrière deux plaques ; (3) liseré doré sur le feuillage mince (< 20 cm le long du soleil), sans flou ; (4) étalonnage : `FoliageLightParams` (champs privés, `with_*` validés, ligne de commande `--feuillage-*` et `--regard-*`, `--sans-feuillage` pour l'A/B) ; défauts exposition x0,8, saturation 1,1, contraste 1,2, chaleur 0,10 modulée par la hauteur du soleil ; (5) aplats de voxel intacts (épaisseur par voxel, aucun flou). `scripts/serie_feuillage.sh`, captures reproductibles octet pour octet. **Manque** : occlusion ambiante (L14) et indirect (L15) : le côté éclairé reste uniformément lime, sans creux sombres ; éclairage du dessous des feuilles par le sol (L15) non fait ; pas de classe « brindille » dans la table de matières ; le comptage d'épaisseur traite les amas de voxels comme des solides (longueur d'absorption 1 m pour compenser), un houppier réel est poreux ; ombre au-delà de la zone en une prise (dure). |
| L11 | Ombres du soleil en cascades stables | L | L09 | L10, L12, L13 | fait (budget tenu au repos et en régime soutenu ; voir résultat) | 2026-10-21 | [Mesuré, Quadro RTX 3000, 1080p, 600 images, SM 1 455 à 1 515 MHz, `bench --scene arbre --shot feuillage`, ms médiane] **passe `voxel_ombres`** : 0,0000 au repos (aucune tuile à refaire), **0,089 (p95 0,19) en régénération continue** (9 tuiles de 128² par image, une génération de 4 cascades 1024² en 29 images), **génération entière en une image 2,20 ms** (256 tuiles) ; **application dans `voxel_lumiere`** : 0,145 -> 0,261 ms (+0,116, pénombre 16 prises) ; total ombres soutenu ≈ 0,20 ms contre 0,35 visé (tenu), 0,12 au repos. Tracé et matière inchangés (2,37 + 1,28). **Choix** : 4 cascades 1024² par DOUBLEMENT du texel (1,25 / 2,5 / 5 / 10 cm ; portées pleines 5,6 / 11,2 / 22,4 / 44,8 m), calage sur le réseau de texels ancré dans le MONDE (le texel absolu (K, M) a toujours la même valeur), cran de `taille/32` ; remplissage par la MÊME `trace()` en mode SHADOW_MAP ; génération arrière dans une autre couche, échange à la dernière tuile ; plus de fondu temporel entre générations (pas de soleil 0,033° : saut < 1/4 de voxel). **Stabilité prouvée** (`cargo test -p em_render --test ombres_gpu`) : décalage de caméra < 1 texel : 0 texel sur 4 × 1 048 576 diffère de plus de 5 mm ; franchissement d'un cran : 0 sur 1 015 808 (fenêtre décalée d'un nombre entier de texels) ; rotation de 360° : cascades identiques octet pour octet ; 600 images de rotation à l'écran : 0,09 % des pixels changent d'état d'ombre (pire image 0,48 %, critère 0,5 %). **Acné** : sol plat + cube, 5 soleils de 12° à 85°, de près et de loin, ombre dure et pénombre : 0 pixel de sol sur-assombri, 0 pixel de face éclairée du cube assombri, décollement au pied du cube 0,0 à 0,1 % ; **pente de 30° en escalier : 0 % à 50°, 0,5 % à 60°, 2,7 % à 35° (arêtes de marches, rouge toléré à 4 %)**. **Écarts** : pas de fondu temporel entre générations (inutile aux pas retenus), pas de tuiles sales par boîte d'édition (invalidation de toute la cascade par `ShadowControl`), pas de cinquième cascade, pas d'ombres de contact, ombres limitées à la clipmap (25 m : l'ombre de 18 h 30 est coupée à 25 m) ; `ShadowParams` à champs privés (`with_*` validés), `ShadowPlanner` testé sans GPU ; `lab.sh capture … --vue ombre|cascades`, `--sans-ombres`, `--ombres-continu`, `--ombres-tuiles N`, `--ombres-penombre-cm`, etc. |
| L12 | TAA | M | L09 | L10, L11, L13 | à faire | | |
| L13 | Panneau de style et mode fenêtre complet | M | L09 | L10, L11, L12 | à faire | | |
| L14 | Occlusion proche tracée | M | L12 | L15, L16 | partiel : passe, éclairage, captures et essais faits ; budget 0,40 ms NON tenu (voir résultat) ; L12 (TAA) non fait, remplacé par un échantillonnage déterministe | 2026-10-21 | [Mesuré, Quadro RTX 3000, 1080p, 600 images, SM 1 515 à 1 560 MHz, `bench --hour 18.5`, ms médiane, passe `voxel_ao` = tracé des rayons + filtre] **prise `face` (arbre 25 % de l'écran) : 0,67 ms** (4 rayons de 1 m, demi-résolution ; 0,46 avec 2 rayons ; 0,27 avec 1 rayon de 0,1 m = coût fixe du filtre 0,22 + 0,08) ; **prise `feuillage` (caméra dans le houppier, pire cas) : 1,41 ms** ; scène `materiaux` `ensemble_moyen` (le sol remplit l'écran) : 0,72 ms. Total image `face` 3,52 -> 4,14 ms. **Budget 0,40 : dépassé de 0,27 ms (cas courant) à 1,0 ms (pire cas)**. Avant demi-résolution : 6 rayons pleine résolution = 5,3 ms sur `feuillage`. Un rayon court coûte 0,15 à 0,27 ms par jeu en demi-résolution ; le filtre pleine résolution (hit 16 o + 9 lectures) 0,22 ms ; une version à un fil par bloc (tableau privé) est PLUS lente (0,81), écartée. **Ce qu'on baisse** : `--ao-rayons 2` (-0,2), `--ao-portee 0,5` (-0,2 sur `feuillage`), la montée en résolution en quart de résolution (non faite). **Fait** : `AmbientOcclusionPass` (compute : N rayons cosinus par bloc de 2 x 2 pixels depuis le point touché, décalé de 0,02 voxel hors de la face, par la MÊME `trace()` en mode `OCCLUSION` ; filtre bilatéral en pleine résolution : poids gaussien, poids ÷ 50 si la face ou le plan du voxel diffère, donc les arêtes de voxel ne sont jamais traversées) ; échantillonnage DÉTERMINISTE (spirale de Fibonacci tournée par un hachage de la position monde au quart de voxel, aucun bruit temporel : octets identiques d'une image à l'autre) ; `AmbientOcclusionParams` (champs privés, `with_*` validés) et `--ao-rayons`, `--ao-portee`, `--ao-force`, `--ao-filtre`, `--ao-diviseur`, `--sans-ao`, `--ao-ab` (capture AVANT/APRÈS), `--vue ao` ; éclairage : l'occlusion n'assombrit que l'ambiance du ciel et le soulèvement bleu-violet, jamais le soleil, avec rebonds de couleur (Jimenez 2016) : le creux garde la teinte de l'albédo. **Essais** (`em_render/tests/ao_gpu.rs`, 6) : coin de trois plans visibilité 0,11 (critère < 0,5), sol dégagé 1,000 (> 0,95) ; GPU contre référence CPU (`occlusion_cpu`, DDA f64) sur 10 357 pixels d'un nuage de voxels : écart moyen 0,0005, pire 0,068, aucun pixel à plus de 0,1 ; deux images donnent les mêmes octets ; le dessus d'un cube reste à 1,00 jusqu'au bord pendant que son pied tombe à 0,00 (le filtre ne traverse pas l'arête) ; lumière : sol dégagé identique avec et sans AO (écart relatif 0), coin plus sombre, rapports vert/rouge et vert/bleu conservés à 90 % ; 51 PNG de la série identiques octet pour octet sur deux lancements. **Manque** : budget ; critère (2) bruit : le bruit est nul sur sol plat (déterministe) mais l'AO d'une surface voxel est granuleuse à très courte distance (blocs de 2 pixels) ; critère (4) pente de 30° : écart type 0,167 au lieu de 0,03 (les marches de l'escalier occultent réellement leurs pieds ; il faut la peau lisse de L17 et une normale de peau) ; pas d'accumulation temporelle (L12), pas de niveau 1 de la clipmap, pas de double comptage à gérer tant que L15 n'existe pas (la portée de 1 m devra rester sous la maille des sondes) ; l'AO n'agit pas sur le soleil direct : la face éclairée du feuillage reste lime (question 3 du journal S6). **Écarts** : `LightUniform.feuillage_c.z` porte « AO disponible » ; liaison 7 du groupe G-buffer de `voxel_lumiere` ; `DebugView::Occlusion` ; `lab.sh capture --ao-ab`, `scripts/serie_ao.sh`. |
| L15 | Sondes DDGI voxel | L | L11, L12 | L14 | à faire | | |
| L16 | Terrain : densité du labo, source de base, peau (CPU) | M | L05, L06 | phase B et C | à faire | | |
| L17 | Rendu de la peau | M | L09, L16 | L14, L15 | à faire | | |
| L18 | `em_ops` : opérations v1, bus local, journal | M | L01 | toute la phase C | à faire | | |
| L19 | `em_world` : deltas, appliqueur, creusement, rejeu | M | L05, L16, L17, L18 | L20, L21 | à faire | | |
| L20 | Herbe et fleurs (`em_veg`) | L | L17 | L19, L21 | à faire | | |
| L21 | Eau v1 : surface, écoulement, réfraction | L | L03, L17 | L19, L20 | à faire | | |
| L22 | Matière v2 : détail CC0, relief, joints | M | L10 | phase C, D | à faire | | |
| L23 | Recettes mur de pierre, poutre, poteau | M | L05, L06, L22 | L24, L25 | à faire | | |
| L23p | Test de style : recettes bâti (mur de pierre, poutre, poteau, toit) + mode de matière `VoxelPixel` + scène `materiaux` A/B | M | L06, L08, L09 | L11 | fait | 2026-10-21 | [Mesuré, Quadro RTX 3000, 1080p, 300 images, `bench --scene materiaux --shot ensemble_moyen`, ms médiane] passe `voxel_matiere` : **continu 1,066 ms, voxel 0,815 ms** (-24 %, 5 hachages entiers au lieu de 5 bruits de valeur) ; tracé 0,93 à 0,95, profondeur 0,06, lumière 0,17. Albédo GPU contre référence CPU (`em_render/tests/materiaux_gpu.rs`, 47 valeurs : pierre, mortier, 3 axes du bois et bois de bout, tuiles, mousse) : ΔE max 0,675 en VoxelPixel, 0,709 en continu (critère 1). Tests : 16 sur les recettes (`em_gen/tests/bati.rs` : empreintes épinglées mur `0x6b970dc6291158fe`, poutre `0x37af849eda9f4365`, poteau `0x2ef56146f973ffd9`, toit `0xe55bea8ba1c5744a` ; joints d'un voxel, pierres = boîtes pleines donc aucun chanfrein, deux pierres jamais en contact, mousse, niveaux grossiers contre `reduce_2x`, mur à cheval sur un bord de chunk) et 9 sur le mode (`em_material/tests/voxel_pixel.rs` : à gigue nulle deux voxels d'une même pierre sont identiques où qu'ils soient, écart borné par la gigue sinon, corrélation du bois le long du fil 0,886 contre -0,075 en travers, empreinte `0xbc8e1aa477b723db`). 13 captures A/B reproductibles octet pour octet (`scripts/serie_materiaux.sh`, `lab.sh capture --scene materiaux --mode continu\|voxel\|ab`). **Écarts** : classe 36 `moss` ajoutée et rampe de `cut_stone` à joints bruns dans `material_render.toml` : empreintes épinglées d'`em_material` mises à jour (évaluation `0x44cb47594b400546`, paquet `0xc4f499134de3133d`) ; `class_extra.w` porte le mode, nouveau tampon `pixel_params` (binding 6) ; `--mode` et `--etiquette` ajoutés à `ArgsArbre` ; la végétation est refusée en VoxelPixel (déjà voxel par voxel). |
| L24 | Brume volumétrique, rayons, perspective aérienne | M | L11 | L23, L25 | à faire | | |
| L25 | Lumières ponctuelles ombrées, nuit | M | L11, L15, L23 | L24 | à faire | | |
| L26 | Clipmap 6 niveaux, LOD, **porte budgétaire forêt dense** | L | L09, L17 | L27, L28 | à faire | | |
| L27 | Eau v2 : reflets tracés, cascade, embruns | M | L21, L24 | L26, L28 | à faire | | |
| L28 | Entités, opérations de recette, paquet `EMPK`, instantanés | L | L19, L23 | L26, L27 | à faire | | |
| L29 | Scène de synthèse, préréglages, rapport budgétaire | M | L26 et toutes les passes | L30 | à faire | | |
| L30 | Port Rust de `voxel_tree` : squelette en Q16 | L | L01, L05 | dès la phase C | à faire | | |
| L31 | Port Rust : épaisseurs, rastérisation, feuillage, couleurs | L | L30, L10 | L29 | à faire | | |
| L32 | Port Rust : arbustes, topiaire, silhouettes lointaines | M | L31 | — | à faire | | |

Chemin critique : L01 → L05 → L08 → L09 → L11 → L15 → L25 → L29 (L29 attend toutes les passes ; la porte budgétaire L26 attend L09 et L17).

---

## Phase A : le socle

### L01 — Workspace et `em_core` (M)

- **Crates** : `engine-rs/` (workspace), `em_core` complet ; les 12 autres crates créées vides (`lib.rs` ou `main.rs`) avec leurs dépendances déclarées selon `docs/19` § 2.2, pour que les tâches suivantes travaillent en parallèle.
- **Livrables** : `Cargo.toml` (workspace, `resolver = "2"`, versions des dépendances communes en `[workspace.dependencies]`), `rust-toolchain.toml` (1.99), `clippy.toml`, un `clippy.toml` par crate de vérité (`disallowed-types = HashMap, HashSet`), `README.md` en français, `engine-rs/scripts/cpp_vectors.cpp` (petit programme qui inclut `engine/core/base/include/emergence/base/{hash,fixed}.h` et `engine/ops` `digest`, et imprime les vecteurs de test).
- **Interface** (module par module) :
  ```rust
  // q16
  #[derive(Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
  pub struct Q16(pub i64);                         // 1.0 = 65 536
  impl Q16 { pub const ONE: Q16; pub const fn from_int(v: i64) -> Q16; pub const fn from_ratio(n: i64, d: i64) -> Q16;
             pub fn mul(self, o: Q16) -> Q16; pub fn div(self, o: Q16) -> Q16; pub fn floor(self) -> i64; }
  // + Add, Sub, Neg ; fonctions libres :
  pub fn qmul(a: i64, b: i64) -> i64; pub fn qdiv(a: i64, b: i64) -> i64; pub fn qlerp(a: i64, b: i64, t: i64) -> i64;
  pub fn qsmoothstep(e0: i64, e1: i64, x: i64) -> i64; pub fn qramp(e0: i64, e1: i64, x: i64) -> i64;
  pub fn isqrt64(v: u64) -> u64; pub fn qexp2(x: i64) -> i64;                       // identiques au C++ (fixed.h)
  pub fn qsqrt(x: Q16) -> Q16; pub fn qlog2(x: Q16) -> Q16; pub fn qpow(x: Q16, e: Q16) -> Q16;
  pub fn sin_turns(t: Q16) -> Q16; pub fn cos_turns(t: Q16) -> Q16; pub fn atan2_turns(y: Q16, x: Q16) -> Q16; // angles en tours
  // hash
  pub const fn mix64(x: u64) -> u64; pub const fn hash_combine(h: u64, v: u64) -> u64;
  pub const fn hash2(seed: u64, x: i64, y: i64) -> u64; pub const fn hash3(seed: u64, x: i64, y: i64, z: i64) -> u64;
  pub const fn layer_seed(world_seed: u64, layer: u64) -> u64;
  pub struct SplitMix64 { /* privé */ } impl SplitMix64 { pub fn new(seed: u64) -> Self; pub fn next_u64(&mut self) -> u64;
      pub fn below(&mut self, n: u64) -> u64 /* sans biais */; pub fn unit_q16(&mut self) -> Q16 /* [0, 1) */ }
  // digest
  pub fn crc32(bytes: &[u8]) -> u32; pub struct Fnv64 { /* privé */ }
  impl Fnv64 { pub fn new() -> Self; pub fn add(&mut self, b: &[u8]); pub fn add_u64(&mut self, v: u64); pub fn value(&self) -> u64; }
  // coords (constantes de docs/19 § 3.1)
  pub const VOXEL_MM: i64 = 50; pub const CHUNK_EDGE: i32 = 64; pub const BRICK_EDGE: i32 = 8;
  pub const REGION_CHUNKS_XZ: i32 = 32; pub const REGION_CHUNKS_Y: i32 = 16; pub const WORLD_SIZE_VOXELS: i32 = 400_000;
  pub const WORLD_BOTTOM_VOXEL: i32 = -10_000; pub const WORLD_TOP_VOXEL: i32 = 70_000; pub type Lod = u8;
  pub struct VoxelCoord { pub x: i32, pub y: i32, pub z: i32 }   // x est, y haut, z nord ; voxels du niveau
  pub struct ChunkKey { pub x: i32, pub y: i32, pub z: i32 }     // voxel >> 6 au même niveau
  pub struct RegionKey { pub x: i32, pub y: i32, pub z: i32 }
  pub struct VoxelBox { pub min: VoxelCoord, pub max: VoxelCoord } // [min, max)
  pub fn floor_div(a: i64, b: i64) -> i64; pub fn chunk_of(v: VoxelCoord) -> ChunkKey; pub fn region_of(c: ChunkKey) -> RegionKey;
  pub fn voxel_index(x: u32, y: u32, z: u32) -> u16 /* x + 8z + 64y dans une brique */; pub fn brick_index(bx: u32, by: u32, bz: u32) -> u16;
  // frame : la SEULE conversion entre repères
  pub fn act_mm_to_world_mm(p: [i32; 3]) -> [i32; 3]; pub fn world_mm_to_act_mm(p: [i32; 3]) -> [i32; 3];
  // ids
  pub struct EntityId(pub u32);  // génération << 22 | case (case ≥ 1), comme engine/act/entity_id.h
  impl EntityId { pub const NONE: EntityId; pub fn new(slot: u32, generation: u32) -> Self; pub fn slot(self) -> u32; pub fn generation(self) -> u32; }
  pub struct MaterialId(pub u16); pub struct VoxelValue(pub u16);   // classe 9 bits << 7 | teinte 7 bits
  impl VoxelValue { pub const AIR: VoxelValue; pub const fn new(m: MaterialId, tint: u8) -> Self; pub const fn material(self) -> MaterialId; pub const fn tint(self) -> u8; }
  // io
  pub struct LeWriter { /* Vec<u8> */ } pub struct LeReader<'a> { /* &[u8] + position */ } // u8..u64, i32, i64, bytes ; erreur « tronqué »
  ```
- **Acceptation** : (1) les trois commandes de la règle 2 vertes ; (2) vecteurs C++ épinglés et égaux : `mix64` (10 valeurs), `hash3` (dont graine `u64::MAX` et coordonnées négatives), `layer_seed`, `qmul`/`qdiv`/`qsmoothstep`/`qexp2`/`isqrt64` (100 entrées), `crc32(b"123456789") == 0xCBF43926`, FNV-1a ; (3) `sin_turns`, `cos_turns`, `atan2_turns`, `qlog2` : erreur max ≤ 2⁻¹⁴ sur 10 000 points (comparaison en `f64` dans les tests seulement) ; (4) test `deps_direction` (lit `cargo metadata`) qui échoue si `em_render` dépend de `em_world` ou `em_ops`, si une crate de vérité dépend de `wgpu`, ou si `em_ops` dépend de `em_voxel`.
- **Capture** : aucune.
- **Piège** : `qmul` du C++ fait `(a*b) >> 16` en `int64`, ce qui déborde (comportement indéfini) hors du domaine `|a·b| < 2⁶³` : les vecteurs de parité restent dans ce domaine, le Rust calcule avec un intermédiaire `i128` et vérifie le domaine par `debug_assert!` ; `as u64` sur `i64` négatif (complément à deux, comme le C++) ; `>>` arithmétique sur négatif ; `floor_div` des négatifs (le sous-sol est en y < 0).

### L02 — Hôte de rendu : adaptateur, hors écran, fenêtre, PNG, profileur (M)

- **Crates** : `em_render` (cœur), `em_lab` (binaire) ; `engine-rs/scripts/lab.sh`, `bench.sh`.
- **Interface** :
  ```rust
  pub struct GpuRequest { pub adapter_hint: String /* env EM_ADAPTER, défaut "Quadro" */, pub allow_any_adapter: bool, pub validation: bool }
  pub struct GpuContext { /* privé : instance, adaptateur, device, queue, rapport */ }
  impl GpuContext { pub fn new(req: &GpuRequest) -> Result<Self, GpuError>; pub fn device(&self) -> &wgpu::Device; pub fn queue(&self) -> &wgpu::Queue; pub fn info(&self) -> &AdapterReport; }
  // champs privés ; demande TIMESTAMP_QUERY (+ INSIDE_ENCODERS si dispo) et les limites de docs/19 § 7.1 :
  // ≥ 8 textures et ≥ 16 tampons de stockage par étage, ≥ 32 Kio de mémoire partagée, 1 Gio par liaison ; refus clair sinon
  pub trait FrameTarget { fn size(&self) -> (u32, u32); fn acquire(&mut self) -> TargetFrame; fn present(&mut self, frame: TargetFrame); }
  pub struct OffscreenTarget; pub struct WindowTarget;          // même code d'image derrière
  pub struct GpuProfiler;
  impl GpuProfiler { pub fn new(gpu: &GpuContext, max_scopes: u32) -> Self;
      pub fn render_scope(&mut self, name: &'static str) -> Option<wgpu::RenderPassTimestampWrites<'_>>;
      pub fn compute_scope(&mut self, name: &'static str) -> Option<wgpu::ComputePassTimestampWrites<'_>>;
      pub fn resolve(&mut self, enc: &mut wgpu::CommandEncoder); pub fn end_frame(&mut self, gpu: &GpuContext);
      pub fn report(&self) -> ProfileReport; }                   // médiane, p95, n par passe ; JSON de 19a § 6.6
  pub fn read_texture_png(gpu: &GpuContext, tex: &wgpu::Texture, path: &Path) -> anyhow::Result<()>;
  pub struct RenderGraph { /* Vec<Box<dyn RenderPass>> + Resources nommées */ }
  impl RenderGraph { pub fn add(&mut self, pass: Box<dyn RenderPass>); pub fn set_enabled(&mut self, name: &str, on: bool);
      pub fn render(&mut self, gpu: &GpuContext, frame: &FrameContext, target: &mut dyn FrameTarget, prof: &mut GpuProfiler); }
  ```
  Ligne de commande d'`em_lab` (complétée par les tâches suivantes) : `capture`, `bench`, `window`, `compare`, `check-images`, `approve`, `assets pack` (`clap` en mode dérivé). Scène `hello` : dégradé plein écran + surimpression texte (police 8 × 8 intégrée, domaine public).
- **Acceptation** : (1) `scripts/lab.sh capture --scene hello` écrit un PNG 1920 × 1080 en moins de 5 s et le journal nomme « Quadro RTX 3000 » et le pilote ; (2) deux captures successives identiques octet pour octet ; (3) `bench --frames 600` rend un JSON avec deux passes, `n = 600`, médiane et p95, et les horloges relevées par `nvidia-smi` ; (4) `window` s'ouvre (avec `__NV_PRIME_RENDER_OFFLOAD=1` si nécessaire : le noter dans `lab.sh`), Échap quitte, F12 capture ; (5) sans `VK_DRIVER_FILES` (seul l'Intel visible), message d'erreur clair et code de sortie ≠ 0, sauf `--allow-any-adapter` ; (6) les limites demandées sont journalisées, et un test force une limite impossible pour vérifier le refus clair.
- **Capture** : `00_hote_mire.png` (mire et ms par passe) ; pour l'équipe, pas pour Monsieur.
- **Piège** : `wgpu` 30 : `Instance::enumerate_adapters` est **asynchrone**, `Device::poll(PollType::Wait { .. })` ; lignes de lecture alignées sur 256 o (`COPY_BYTES_PER_ROW_ALIGNMENT`) ; PNG en sRGB (pas les valeurs linéaires) ; période d'horodatage par `Queue::get_timestamp_period()` ; les requêtes sont lues 2 images plus tard (anneau).

### L03 — Ciel de Hillaire, bloom, AgX : port de `web-ocean` (M)

- **Crate** : `em_render` ; shaders dans `crates/em_render/shaders/third_party/web_ocean/` avec `LICENSE` (MIT, © 2026 Maksymilian Dendura) et `MANIFEST.toml` (fichier source, export, empreinte SHA-256) ; outil `engine-rs/scripts/extract_web_ocean.py` (lit les modules JS **comme du texte**, remplace les constantes de gabarit `${N}`, `${CASCADES}`, `${ENV_MIPS}`…, écrit les `.wgsl` ; lancé avec `python3 -I`, le dossier source en argument : c'est un téléchargement).
- **Sources** : `/home/samuelpyrat/Téléchargements/web-ocean-main/js/wgsl/{common,sky,post}.js` (copie identique dans `engine/em_water/ici, un exemple…/js/wgsl/`).
- **Interface** :
  ```rust
  pub struct SunModel { pub latitude_deg: f32, pub day_of_year: u16 }
  impl SunModel { pub fn sun_direction(&self, hour: f32) -> glam::Vec3; } // vers le soleil, monde y haut ; 1 jour de jeu = 1 h 30 réelle (D30) géré par l'appelant
  pub struct CloudParams { pub altitude_km: f32, pub coverage: f32, pub density: f32, pub wind_time: f32 }
  pub struct SkyParams { pub sun_dir: glam::Vec3, pub sun_illuminance: f32, pub haze: f32, pub clouds: CloudParams }
  pub struct SkyPass;      // RenderPass : LUT (transmittance et diffusion multiple au changement, vue chaque image), cube (une face par image), visibilité du soleil
  impl SkyPass { pub fn set_params(&mut self, p: &SkyParams); pub fn env_cube(&self) -> &wgpu::TextureView;
                 pub fn skyview_lut(&self) -> &wgpu::TextureView; pub fn transmittance_lut(&self) -> &wgpu::TextureView;
                 pub fn sun_visibility(&self) -> &wgpu::Buffer; }
  pub struct SkyBackgroundPass; pub struct BloomPass; pub struct CompositePass; // AgX + regard + vignette + tramage
  ```
  La struct `Frame` est celle de 19a § 5.4 (réécrite, pas celle de `web-ocean`).
- **Acceptation** : (1) chaque shader extrait passe la validation `naga` (test `shaders_validate`) ; (2) 12 captures : heures 6, 8, 12, 17,5, 19, 21 (latitude 46° N, jour 172), vers le soleil et à l'opposé ; (3) aucun NaN ni infini dans la lecture HDR ; (4) passes du ciel ≤ 0,10 ms en médiane (banc, cube amorti) ; (5) la capture de 19 h vers le soleil, comparée à `web-ocean-main/docs/front.jpg` par Monsieur.
- **Capture pour Monsieur** : planche `01_ciel_6h-21h.png` (les 6 heures). Question : couleurs du couchant, densité des nuages, brume.
- **Piège** : l'atmosphère est en **km** et la caméra en m ; Z inversé ; mises en page `auto` du JS à rendre explicites ; écarts Tint/naga (expressions constantes, `select`) ; alignement des `vec3` dans les uniformes (tout en `vec4` comme `web-ocean`).

### L04 — Exporteur `.vxm` dans `voxel_tree.py` et `voxel_bush.py` (S)

- **Où** : copier `/home/samuelpyrat/Documents/Codex (Copie)/emergence/Map/voxel_tree.py` et `voxel_bush.py` dans `tools/vegetation/` (une ligne de provenance en tête, contenu inchangé sinon) ; ajouter `save_vxm(tree_by_lod, path, export_sky, export_pal)`, le format `vxm` dans `--formats`, `--lods 0,1,2,3,4,5` (régénère l'arbre avec `voxel = 0,05 × 2^lod`, même graine, `bake_light=False`), `--export-pal` (canal `pal`, toujours mis par `export_vegetation.sh`), `--export-sky`, et une **scène d'orientation** (`--orientation-test` : un voxel rouge à l'est et un bleu au nord du pivot) ; `tools/vegetation/read_vxm.py` (lecteur + vérifications) ; `tools/vegetation/tests/test_vxm.py` ; `engine-rs/scripts/export_vegetation.sh` (la bibliothèque du labo : chêne 42 à 14 m, hêtre, bouleau, épicéa, pin, peuplier, érable avec 2 graines chacun, rosier, buis topiaire sphère, lavande → `engine-rs/lab/models/`).
- **Interface** : format de 19a § 1, octet par octet.
- **Acceptation** : (1) `python3 tools/vegetation/voxel_tree.py --seed 42 --species chene --height 14 --formats vxm --lods 0,1,2,3,4,5 --export-pal --out engine-rs/lab/models/chene_42` ; le lecteur trouve **607 784** voxels au LOD0 (cellules distinctes [Mesuré le 20 oct.]) et, par sorte après dédoublonnage, des comptes cohérents avec `generate_tree` ; (2) aller-retour exact (ensembles de (x, y, z, sorte, rampe) égaux) ; CRC valide ; (3) deux exportations identiques octet pour octet ; (4) boîtes des LOD : `bbox(LODk) × 2^k` à ±1 voxel grossier de `bbox(LOD0)`, pour k = 1 à 5 ; (5) moins de 20 s pour les 6 LOD ; (6) la scène d'orientation lue par `read_vxm.py` a son voxel rouge en +x et son bleu en +z.
- **Capture** : l'aperçu Python `--preview` sans ombrage cuit, `chene_42_python.png`, référence de L09 et L10.
- **Piège** : axes (Python z haut) ; doublons écorce/rameau ; `steps` variable (`min(30, 255 // nb_rampes)`) ; `ramp = (pal − 1) // steps` ; oublier `bake_light=False`.

### L05 — `em_voxel` : briques, chunks, sources, empreintes (M)

- **Interface** :
  ```rust
  pub struct Brick { /* privé : enum Repr { Uniform(VoxelValue), Palette { bits, palette, indices } } */ }
  impl Brick { pub fn uniform(v: VoxelValue) -> Self; pub fn is_uniform(&self) -> Option<VoxelValue>; pub fn bits(&self) -> u8; pub fn palette(&self) -> &[VoxelValue]; }
  impl Brick { pub fn get(&self, i: u16) -> VoxelValue; pub fn from_dense(d: &[VoxelValue; 512]) -> Self; pub fn to_dense(&self, out: &mut [VoxelValue; 512]);
               pub fn occupancy(&self) -> [u64; 8]; pub fn encode(&self, w: &mut LeWriter); pub fn decode(r: &mut LeReader) -> Result<Self, DecodeError>; } // EMBK, 19a § 2.5
  pub struct Chunk { /* 512 briques */ }
  impl Chunk { pub fn new_air() -> Self; pub fn get(&self, x: u32, y: u32, z: u32) -> VoxelValue; pub fn brick(&self, b: u16) -> &Brick;
               pub fn set_brick(&mut self, b: u16, brick: Brick); pub fn classify(&self) -> ChunkClass; pub fn fingerprint(&self, h: &mut Fnv64); }
  pub enum ChunkClass { Air, Uniform(VoxelValue), Mixed } pub enum ChunkHint { Air, Solid(VoxelValue), Unknown }
  pub enum PutMode { Solid, CarveAir }
  pub trait VoxelSource /* docs/19 § 2.5 */ ; pub trait VoxelSink /* idem */ ;
  pub struct ChunkWriter<'a> { /* fenêtre d'un chunk ; implémente VoxelSink */ }
  pub struct CompositeSource { /* couches dans l'ordre fixe de docs/19 § 3.2 */ } impl VoxelSource for CompositeSource
  pub enum ReduceRule { Majority4of8 { priority: Vec<MaterialId> } }
  pub fn reduce_2x(children: [&Chunk; 8], rule: &ReduceRule, out: &mut Chunk);   // enfant i = cx + 2cz + 4cy
  pub struct OccupancyColumns { /* 64 × 64 colonnes de u64, pour la peau et le GPU */ }
  ```
- **Acceptation** : (1) aller-retour dense ↔ palette pour 1, 2, 4, 8, 16 bits et 1 000 briques aléatoires ; (2) EMBK : encodage puis décodage identiques, refus d'une brique tronquée ; (3) réduction : cas écrits à la main (mur mince, 3/8, 4/8, priorités) ; (4) empreinte épinglée d'un chunk synthétique ; (5) `CompositeSource` de 3 couches : ≤ 0,3 ms par chunk mixte, 1 fil, release [Mesuré, à rendre].
- **Capture** : aucune.
- **Piège** : ordre **x, z, y** (pas x, y, z) ; palette ≤ 255 valeurs + air ; jamais d'itération de `HashMap` dans une empreinte.

### L06 — `em_material` : table, teintes, paquet GPU (M)

- **Données** : `engine/data/materials.csv` (ajouter **34 `petal`** et **35 `fruit`**, catégorie `plant`, rien d'autre ne change) ; nouveau `engine/data/material_render.toml` (19a § 6.2) avec une entrée pour chaque classe.
- **Interface** :
  ```rust
  pub struct MaterialDef { /* privé : id, nom, catégorie, densité, dureté, inflammabilité, couleur de base, propriétés de rendu */ }
  impl MaterialDef { pub fn id(&self) -> MaterialId; pub fn name(&self) -> &str; pub fn category(&self) -> &str; pub fn density_kg_m3(&self) -> u32;
                     pub fn hardness(&self) -> u8; pub fn flammability(&self) -> u8; pub fn base_srgb(&self) -> [u8; 3]; pub fn render(&self) -> &RenderProps; }
  pub struct MaterialTable;
  impl MaterialTable { pub fn load(csv: &Path, render_toml: &Path) -> anyhow::Result<Self>; pub fn by_name(&self, n: &str) -> Option<MaterialId>;
      pub fn get(&self, id: MaterialId) -> &MaterialDef; pub fn gpu_entries(&self) -> Vec<MaterialGpu>; pub fn class_ramps(&self) -> Vec<[f32; 4]>;
      pub fn version(&self) -> u32; }                                                   // FNV des deux fichiers
  pub enum TintMode { Ramp128, WoodAxis, StonePiece, Vegetation, Terrain }
  pub fn tint_wood(axis: u8, variant: u8) -> u8; pub fn tint_stone(piece: u8) -> u8; pub fn tint_vegetation(species: u8, ramp: u8) -> u8;
  pub struct VegetationRamps;
  impl VegetationRamps { pub fn register(&mut self, species_key: &str, role: RampRole, ramps: &[[[u8; 3]; 3]]) -> u8 /* case d'essence */;
                         pub fn gpu_data(&self) -> Vec<[f32; 4]>; }                   // 19a § 5.3
  pub const MATERIAL_WGSL: &str;          // material.wgsl (complété par L10 et L22)
  ```
- **Acceptation** : (1) les 36 lignes chargées, aucun numéro changé (test qui compare les identifiants 0..33 à la version du 20 oct.) ; (2) chaque classe a une entrée de rendu ou hérite de `[default]` (test) ; (3) `size_of::<MaterialGpu>() == 64` ; (4) conversion sRGB → linéaire faite une fois ; (5) 32 cases d'essence au plus, erreur claire au-delà.
- **Capture** : aucune.
- **Piège** : ne jamais renuméroter `materials.csv` (les numéros sont dans les sauvegardes) ; la teinte de végétation n'a que 2 bits de rampe (19a § 5.3).

### L07 — Comparateur d'images et références (S)

- **Crate** : `em_lab` (module `imgcmp`).
- **Interface** : `pub struct ImageDiff { pub delta_e_mean: f32, pub delta_e_p99: f32, pub delta_e_max: f32, pub ssim_luma: f32 }` ; `pub fn compare(a: &RgbaImage, b: &RgbaImage) -> ImageDiff` (ΔE dans Oklab, SSIM de luminance par blocs 8 × 8) ; commandes `em_lab compare a.png b.png [--json]`, `check-images` (seuils de `docs/19` § 7.4 : moyenne ≤ 0,5, p99 ≤ 3, SSIM ≥ 0,98), `approve` (copie dans `lab/reference/` et rappelle d'écrire la ligne « décidée » dans `docs/19c`).
- **Acceptation** : images identiques → 0 et 1 ; décalage de luminance connu → ΔE attendu à 5 % près ; flou gaussien σ = 1 px détecté (SSIM < 0,98) ; décalage d'un pixel détecté.
- **Capture** : aucune.
- **Piège** : comparer en sRGB décodé (linéaire) puis Oklab, pas en octets bruts.

---

## Phase B : le premier arbre

### L08 — Chargeur `.vxm` et scène statique (S)

- **Crates** : `em_gen` (module `vxm`), `em_lab` (scènes lues dans `lab/scenes/*.toml`, 19a § 6.4).
- **Interface** :
  ```rust
  pub trait Generator /* docs/19 § 2.5, créé ici */ ; pub trait GenPlan /* idem */ ;
  pub struct VxmModel { /* privé : méta JSON, LOD */ } // implémente Generator (son plan = le modèle chargé, sans calcul)
  impl VxmModel { pub fn load(path: &Path) -> Result<Self, GenError>; pub fn meta(&self) -> &VxmMeta; pub fn lods(&self) -> &[Lod]; pub fn bounds(&self, lod: Lod) -> VoxelBox; }
  pub struct PlacedModel { /* privé : modèle, pivot LOD0 monde, quarts de tour, case d'essence */ }
  impl PlacedModel { pub fn new(model: Arc<VxmModel>, pivot: VoxelCoord, quarter_turns: u8, species_slot: u8) -> Result<Self, GenError>; }
  impl VoxelSource for PlacedModel { .. }   // classes et teintes de 19a § 1.4 ; au LOD k : pivot = floor_div(pivot, 2^k)
  pub struct StaticScene { /* sol plat de turf + modèles placés */ } impl VoxelSource for StaticScene
  ```
- **Acceptation** : (0) la scène d'orientation de L04, vue d'en haut le nord en haut, montre le rouge à droite et le bleu en haut (repère gaucher, `docs/19` § 2.6) ; (1) `chene_42.vxm` chargé → 607 784 voxels pleins au LOD0 après rastérisation dans les chunks ; (2) quarts de tour 0..3 : même compte, boîtes tournées correctes (test) ; (3) chargement ≤ 300 ms [Mesuré, à rendre] ; (4) un LOD absent du fichier se replie sur le plus proche plus fin, avec un avertissement.
- **Capture** : aucune.
- **Piège** : rotation autour du **centre** de la cellule pivot (erreur d'un voxel sinon) ; `floor_div` du pivot aux niveaux grossiers.

### L09 — Premier rendu voxel : tracé, G-buffer, éclairage direct (L)

- **Crates** : `em_render` (`VoxelGpuWorld`, `ClipmapStreamer` à un niveau, `VoxelTracePass`, `DepthMergePass`, `LightingPass` v0, ressources du G-buffer, projections), `em_lab` (scène `arbre`).
- **Interface** :
  ```rust
  pub struct ClipmapConfig { pub levels: u8 /* 1 ici, 6 en L26 */, pub chunks_per_axis: u32 /* 16 */, pub brick_capacity: u32, pub payload_words: u32 }
  pub struct VoxelGpuWorld;
  impl VoxelGpuWorld { pub fn new(gpu: &GpuContext, cfg: ClipmapConfig) -> Self;
      pub fn upload_chunk(&mut self, gpu: &GpuContext, level: u8, key: ChunkKey, chunk: &Chunk, flags: ChunkFlags);
      pub fn evict_chunk(&mut self, level: u8, key: ChunkKey); pub fn set_level_origin(&mut self, level: u8, origin: ChunkKey);
      pub fn bind_group_layout(&self) -> &wgpu::BindGroupLayout; pub fn bind_group(&self) -> &wgpu::BindGroup; pub fn stats(&self) -> GpuWorldStats; }
  pub struct ClipmapStreamer; impl ClipmapStreamer { pub fn update(&mut self, cam: &Camera, src: &dyn VoxelSource, world: &mut VoxelGpuWorld, gpu: &GpuContext); }
  pub enum Projection { Perspective { fov_y_deg: f32 }, Orthographic { height_m: f32 } } // perspective : Z inversé infini
  pub struct Camera { /* privé : position (voxel entier + fraction), lacet, tangage, projection */ }
  impl Camera { pub fn new(pos_mm: [i64; 3], yaw_deg: f32, pitch_deg: f32, projection: Projection) -> Self; // lacet 0° = nord, horaire vu d'en haut
                pub fn view_proj_lh(&self, aspect: f32) -> glam::Mat4; pub fn set_pose(&mut self, pos_mm: [i64; 3], yaw_deg: f32, pitch_deg: f32); }
  ```
  Shaders : `voxel_common.wgsl` (disposition de 19a § 5.1, décodage), `voxel_trace.wgsl` (`fn trace(ray: Ray, t_min: f32, t_max: f32, mode: u32) -> Hit` : la fonction partagée de `docs/19` § 4.5), `gbuffer.wgsl` (écriture des formats de 19a § 5.2), `lighting.wgsl` v0 (soleil lambertien + ciel par le cube d'environnement en faible niveau, sans ombres).
- **Acceptation** : (1) scène `arbre` (chêne 42 sur un sol plat de turf), capture 1080p ; (2) **silhouette** : capture orthographique de côté en mode « masque » comparée au masque calculé sur le CPU depuis les voxels du `.vxm` : IoU ≥ 0,99 ; (3) `voxel_trace` en médiane sur 600 images, l'arbre couvrant ≈ 40 % de l'écran, **sans la matière v1** : **visé ≤ 0,6 ms** [à mesurer, rapporté même rouge] ; (4) zéro NaN ; (5) caméra placée dans un voxel plein : pas de plantage, la face d'entrée est vue ; (6) deux captures sur la même carte et le même pilote : identiques octet pour octet (sinon ΔE max ≤ 1, avec l'explication) ; (7) scène d'orientation rendue vue d'en haut : rouge à droite, bleu en haut.
- **Capture pour Monsieur** : `02_arbre_1730.png` (de face) et `03_arbre_contrejour_1900.png`, à côté de `chene_42_python.png`. Question : silhouette et lisibilité du pixel art à 10, 20, 40 m.
- **Piège** : DDA en cellules entières et distances `f32` relatives à la caméra ; rayon qui part dans le plein ; signe de la normale ; index torique ; briques uniformes ; pas d'entiers 64 bits en WGSL (deux `u32`) ; limite de liaison de stockage par défaut à 128 Mio.

### L10 — Matière v1 : la végétation de `voxel_tree`, continue en coordonnées monde (M)

- **Crates** : `em_material` (`material.wgsl`, référence CPU), `em_render` (branchement dans `voxel_trace` et vue de débogage « albédo »).
- **Interface** : `fn eval_voxel_material(hit: VoxelHit) -> SurfaceSample` (WGSL : albédo, normale, rugosité, translucidité, émission, occlusion de matière) ; `pub fn eval_voxel_albedo_cpu(table: &MaterialTable, veg: &VegetationRamps, value: VoxelValue, center_mm: [i64; 3], lod: Lod) -> [f32; 3]` (miroir exact). Même **fonction** de bruit de valeur que `voxel_tree.value_noise` (multiplicateurs 73856093, 19349663, 83492791 ; mélange 2654435761, 2246822519, 3266489917 ; lissage `f²(3 − 2f)`), évaluée au **centre du voxel** en coordonnées monde (mètres), amorcée par la **graine de matière de l'essence** (19a § 5.3 ; la graine de chaque arbre n'est pas connue du shader) ; feuilles : **rampe tirée au shader** comme `colorize` (bruit à 0,55 et 1,3 m⁻¹ + gigue, saison globale), puis `tval = 0,10 + 0,80 × 0,6 + (bruit(5 m⁻¹) − 0,5) × 0,22 + gigue × 0,14` (gigue = hachage du voxel) ; écorce : variante portée par la teinte (écorce, écorce secondaire), fissures étirées verticalement à 4 et 9 m⁻¹ ; rameaux.
- **Acceptation** : (1) GPU contre CPU : sur 10 000 pixels d'une vue orthographique d'albédo, ΔE max ≤ 1 ; (2) contre Python, en **distributions** (pas voxel par voxel) : sur les voxels de feuille, la moyenne Oklab de notre albédo est à ΔE ≤ 3 de la moyenne des couleurs `pal` du `.vxm` (palette Python sans ombrage), l'écart type de la luminance à ±20 % près, et la part de chaque rampe de feuillage à ±5 points ; (3) coût ajouté au tracé ≤ 0,1 ms.
- **Capture pour Monsieur** : `04_arbre_matiere_v1.png` à côté de l'aperçu Python. Question : les verts et l'écorce sont-ils ceux du générateur validé ?
- **Piège** : Python travaille en `float32` relatif au pied de l'arbre ; nous en coordonnées monde : comparer des distributions, pas des voxels un à un ; la gigue Python vient de `numpy` (non reproductible) : la nôtre vient du hachage.

---

## Phase C : la lumière

### L11 — Ombres du soleil en cascades stables (L)

- **Crate** : `em_render` (`ShadowCascades`, `shadow_fill.wgsl` : triangle plein écran qui trace un rayon par texel en mode `SHADOW_MAP` (briques `skin` ignorées, la peau étant rastérisée d'abord dans la tuile) et écrit `frag_depth`, `shadow_sample.wgsl`).
- **Interface** :
  ```rust
  pub struct CascadeCfg { pub far_m: f32, pub size: u32 }
  pub struct ShadowConfig { pub cascades: [CascadeCfg; 4] /* haut : 12 m en 4096², 40 et 120 m en 2048², 400 m en 1024² */, pub generation_period_s: f32 /* 0,5 en haut, 1,0 en moyen */, pub tiles_per_frame: u32 }
  pub struct ShadowCascades; // RenderPass ; 3 générations Depth16Unorm ; tuiles sales (glissement, édition, nouvelle génération)
  impl ShadowCascades { pub fn mark_dirty_box(&mut self, b: VoxelBox); pub fn bind_group(&self) -> &wgpu::BindGroup; }
  ```
  Cinquième cascade (terrain seul, plan macro) : interface posée, remplie en phase 1.
- **Acceptation** : (1) stabilité : caméra qui tourne de 360° en 10 s sur scène fixe : ≤ 0,5 % des pixels déjà visibles changent d'état d'ombre d'une image à l'autre ; (2) soleil accéléré ×10 : pas de saut visible, l'écart d'une image à l'autre dans les zones d'ombre reste ≤ ΔE 1 en moyenne grâce au fondu entre générations (×60 sert seulement à regarder) ; (3) acné : sol plat + cube, puis pente de 30° en peau, aucun pixel éclairé assombri par lui-même ; (4) coût médian ≤ 0,40 ms dans `arbre` en `haut` (cascade 0 en 4096², génération de 0,5 s), ≤ 0,20 ms en `moyen` ; une génération complète en ≤ 30 images.
- **Capture pour Monsieur** : `05_ombre_feuillage_10h_15h_19h.png`. Question : netteté et taches de lumière au sol.
- **Piège** : alignement des centres sur les texels dans le repère du soleil ; biais en 16 bits ; acné des feuilles (décalage selon la normale ≈ 1 voxel) ; fondu entre deux générations.

### L12 — TAA (M)

- **Crate** : `em_render` (`TaaPass`, gigue de Halton (2, 3) sur 8 phases dans `Frame.jitter`).
- **Acceptation** : (1) caméra fixe convergée : image N contre N + 1, ΔE moyen ≤ 0,3 ; (2) caméra qui glisse de 2 px par image puis s'arrête : énergie de traînée sous le seuil en ≤ 4 images ; (3) coût ≤ 0,18 ms ; (4) réglage de netteté (0 ; 0,5 ; 1) dans `style.toml`.
- **Capture pour Monsieur** : `06_taa_ab.png` (sans, doux, net) sur les arêtes des feuilles. Question Q9.
- **Piège** : reprojection du monde statique par la profondeur (le compute n'écrit pas de vecteurs) ; rejet des désocclusions après une édition.

### L13 — Panneau de style et mode fenêtre complet (M)

- **Crates** : `em_lab`, `em_render` (surimpression, vues de débogage, `QualityKnob`).
- **Livrables** : `lab/style/style.toml` (19a § 6.5) rechargé à chaud ; bascule des passes F1-F12 ; heure `[` `]` (Ctrl : ×60) ; vues de débogage (albédo, normales, AO, sondes, cascades, niveau de LOD, coût par pixel en fausses couleurs à partir d'un compteur de pas) ; surimpression (ms par passe, heure, style) ; F12 = capture avec JSON de style ; `em_lab journal --capture <png> --question "<texte>"` qui imprime la ligne prête pour `docs/19c`.
- **Acceptation** : (1) un réglage modifié et sauvegardé s'applique en ≤ 0,5 s ; (2) chaque passe désactivée puis réactivée sans erreur de validation `wgpu` ; (3) test unitaire de lecture et de rechargement du TOML ; (4) les ms affichées égalent celles du banc à ±5 %.
- **Capture** : aucune nouvelle (outil).
- **Piège** : recréer les pipelines au rechargement des shaders sans fuir de mémoire GPU.

### L14 — Occlusion proche tracée dans la grille voxel (M)

- **Crate** : `em_render` (`AoPass` : demi-résolution, 4 rayons cosinus ≤ 2 m en `haut` (2 en `moyen`) dans les niveaux 0-1, mode `OCCLUSION` (départ décalé d'au moins un voxel selon la normale), accumulation temporelle, débruitage bilatéral, montée en résolution guidée par la profondeur).
- **Acceptation** : (1) coin formé de 3 murs voxel : AO < 0,5 au coin ; sol dégagé : AO > 0,95 ; (2) bruit résiduel après convergence : écart type ≤ 0,02 sur une zone plane ouverte ; (3) coût ≤ 0,40 ms en `haut`, ≤ 0,25 ms en `moyen` ; (4) pente de peau à 30° : AO uniforme (écart type ≤ 0,03), pas de stries dues aux marches de l'occupation.
- **Capture pour Monsieur** : `07_ao_pied_arbre.png`. Question : profondeur des recoins, sombre ou doux ?
- **Piège** : double comptage avec les sondes (l'AO ne vaut que pour les distances plus courtes que la maille des sondes).

### L15 — Sondes d'irradiance DDGI tracées dans la grille voxel (L)

- **Crate** : `em_render` (`ProbeVolume` : 3 niveaux 1, 4, 16 m, 32 × 16 × 32 sondes, plus un niveau de 0,5 m (16 × 8 × 16) posé sur les bâtiments proches ; irradiance 6 × 6 + bordure, visibilité 14 × 14 + bordure, en `r32uint` empaqueté (19a § 5.5) ; 8 192 sondes par image en `haut` (4 096 en `moyen`), 64 rayons chacune ; classement des sondes dans le plein, puis déplacement).
- **Acceptation** : (1) coût ≤ 0,50 ms en `haut`, ≤ 0,25 ms en `moyen` ; (2) fuite : pièce close de 3 m (murs de 30 cm, plus minces que la maille d'1 m), soleil dehors : irradiance intérieure ≤ 2 % de l'extérieure avec le niveau de 0,5 m, valeur sans ce niveau rapportée aussi ; (3) rebond coloré : mur rouge au soleil sur sol blanc : décalage de chroma mesurable au pied du mur ; (4) une ouverture percée dans la pièce éclaire l'intérieur en ≤ 60 images.
- **Capture pour Monsieur** : `08_rebond_sous_couronne.png`. Question : chaleur du rebond, obscurité sous les arbres.
- **Piège** : sondes enterrées (le terrain en est plein) ; hystérésis trop forte (traînées) ou trop faible (bruit).

---

## Phase D : le sol

### L16 — Terrain : densité du labo, source de base, peau (CPU) (M)

- **Crates** : `em_terrain`, `em_mesh`.
- **Interface** :
  ```rust
  pub trait DensityField /* docs/19 § 2.5 */ ;
  pub struct LabLandscape { /* privé : graine, paramètres des collines, de la falaise, de l'étang, du ruisseau */ } impl LabLandscape { pub fn new(seed: u64) -> Self; }          // 128 × 128 m : collines, falaise à strates, cuvette d'étang, lit de ruisseau, marche de cascade ; Q16
  pub struct FlatField { /* privé */ } impl FlatField { pub fn new(height_mm: i64, material: VoxelValue) -> Self; }
  pub struct TerrainBaseSource<F: DensityField> { /* privé : le champ */ } impl<F: DensityField> TerrainBaseSource<F> { pub fn new(field: Arc<F>) -> Self; }
  impl<F: DensityField> VoxelSource for TerrainBaseSource<F>
  pub struct SurfaceNets { /* privé : taille de cellule en voxels du niveau */ } impl SurfaceNets { pub fn new(cell_voxels: u32 /* 2 à 8, défaut 4 */) -> Result<Self, ConfigError>; }
  impl SurfaceNets { pub fn mesh_chunk(&self, sampler: &dyn Fn([i64; 3]) -> i32 /* densité en Q16 mètres */, key: ChunkKey, lod: Lod,
                                      edited: &BrickMask, skirts: SkirtMask, out: &mut SkinMesh); }
  pub struct SkinMesh { /* privé : positions [i16; 3] en 1/256 de voxel du niveau, relatives au coin du chunk (jupes comprises) ; normales octaédriques [i16; 2] ; indices u16 */ }
  impl SkinMesh { pub fn vertices(&self) -> &[SkinVertex]; pub fn indices(&self) -> &[u16]; pub fn is_empty(&self) -> bool; }
  impl<F: DensityField> SkinSource for TerrainBaseSource<F>
  ```
  Le module `em_terrain::skin` peut utiliser des flottants (visuel) ; le reste non.
- **Acceptation** : (1) empreintes de chunks identiques avec 1 et 8 fils et en ordre mélangé ; (2) voxel plein ⇔ densité au centre < 0, vérifié exhaustivement sur 10 chunks ; (3) sommets de peau à moins d'une demi-cellule de l'isosurface ; (4) **pas de terrasses** : sur la parcelle de 2 % de pente, la hauteur de la peau reste à ≤ 0,5 cm de l'isosurface analytique, et sur un profil de 20 m elle est strictement monotone avec une pente qui ne varie pas de plus de 20 % (une peau en marches de 5 cm échoue) ; `fill_chunk` remplit par colonnes grâce à `DensityField::surface_column` ; (5) `fill_chunk` ≤ 1 ms et maillage ≤ 0,3 ms par chunk, 1 fil, release [Mesuré, à rendre].
- **Capture** : aucune (vue CPU en fil de fer facultative).
- **Piège** : mailler l'occupation au lieu de la densité ; coutures entre chunks (échantillonner la bordure partagée) ; dénivelés de 500 m sous la mer (y négatif).

### L17 — Rendu de la peau (M)

- **Crates** : `em_render` (`SkinDepthPass`, `SkinGBufferPass`, `DepthMergePass` définitive, `GroundTiles`), `em_lab` (scène `terrain`).
- **Règles** (docs/19 § 4.5 et § 6.1) : les briques de terrain montent dans la clipmap avec le drapeau `skin` ; le tracé les ignore si le pixel a une peau, les rend opaques sinon ; la fusion des profondeurs **recopie exactement** la profondeur de la pré-passe là où la peau gagne ; la passe G-buffer de la peau teste `Equal` avec `@invariant` sur la position ; la matière d'un point de peau = voxel juste sous la surface (recherche ≤ 2 voxels vers le bas, sinon `DensityField::material`) ; modes `cell` et `blend` (`style.toml`) ; jupes de 2 cellules aux bords dont le voisin est d'un autre niveau ; `GroundTiles` (texture torique 1024² à 10 cm : hauteur R16, matière et drapeaux) pour l'herbe.
- **Acceptation** : (1) vue de terrain seul : 0 pixel de ciel sous l'horizon (jupes) ; (2) couverture de la passe G-buffer = couverture de la pré-passe, au pixel près ; (3) coût pré-passe + G-buffer ≤ 0,35 ms sur le paysage du labo ; (4) captures A/B `cell` et `blend` ; (5) **acné sur pente** : pente de 30° au soleil rasant, les cascades (mode `SHADOW_MAP`), les ombres de contact et les sondes ne strient pas la peau (écart type de luminance ≤ 2 % sur la pente nue) ; (6) scène `terrain` (paysage du labo, prises de vue nommées) livrée.
- **Capture pour Monsieur** : `09_colline_falaise_1730.png` et `10_peau_cellule_ou_melange.png`. Question Q2.
- **Piège** : égalité de profondeur cassée par un shader de sommets différent ; voxels qui percent la peau (règle des briques `skin`).

### L18 — `em_ops` : opérations v1, bus local, journal (M)

- **Crate** : `em_ops` ; `engine-rs/scripts/cpp_ops_vectors.cpp` et `cpp_journal_check.cpp` (petits programmes compilés sur `engine/ops/src`).
- **Interface** :
  ```rust
  pub struct Operation { /* privé : op_id, tick, seq, author, cause, kind, process, gesture, flags, version, noise, sight, trace, reserved, payload */ }
  impl Operation { pub fn new(tick: u64, author: u32, cause: u64, kind: u16, payload: Payload) -> Self; // op_id et seq = 0 jusqu'au flush
      pub fn op_id(&self) -> u64; pub fn kind(&self) -> u16; pub fn payload(&self) -> &[u8]; /* … un accesseur par champ, dont reserved */
      pub(crate) fn assign(&mut self, op_id: u64, seq: u32); }               // seul le bus attribue op_id et seq
  pub fn encode(op: &Operation, out: &mut Vec<u8>); pub fn decode(bytes: &[u8]) -> Result<(Operation, usize), DecodeStatus>;
  pub enum Payload { VoxelEdit(VoxelEdit), EntityDelta(..), Spawn(..), Destroy(..), Move(..), EntityRecipe(EntityRecipe), EntityParts(EntityParts) }
  impl Payload { pub fn decode(kind: u16, bytes: &[u8]) -> Result<Self, DecodeStatus>; pub fn encode(&self, out: &mut Vec<u8>); }
  pub struct VoxelEdit { /* privé : forme, p[7], new_voxel, only_class, liste */ }
  impl VoxelEdit { pub fn boxed(min: VoxelCoord, max: VoxelCoord, new_voxel: VoxelValue) -> Self; pub fn sphere(center_16: [i32; 3], radius_16: i32, new_voxel: VoxelValue) -> Self;
      pub fn capsule(..) -> Self; pub fn list(cells: Vec<VoxelCoord>, new_voxel: VoxelValue) -> Self; pub fn blob(center_16: [i32; 3], radius_16: i32, roughness_permille: u16, wavelength_16: i32, new_voxel: VoxelValue) -> Self;
      pub fn only_class(self, class: MaterialId) -> Self; pub fn shape(&self) -> Shape; pub fn contains(&self, v: VoxelCoord, world_seed: u64, op_id: u64) -> bool; }
  pub trait Applier /* docs/19 § 2.5 */ ; pub trait OperationSink /* idem */ ;
  pub struct LocalBus; impl LocalBus { pub fn add_applier(&mut self, a: Box<dyn Applier>); pub fn flush(&mut self, up_to_tick: u64) -> usize; pub fn stats(&self) -> BusStats; }
  impl OperationSink for LocalBus
  pub struct Journal; impl Journal { pub fn open(path: &Path) -> Result<Self, JournalStatus>; pub fn scan(path: &Path) -> JournalScan;
                                     pub fn replay(path: &Path, a: &mut dyn Applier) -> JournalScan; } impl Applier for Journal
  ```
  Charges de 19a § 3 (sortes 8 et 9 nouvelles ; `VoxelEdit.changed` toujours 0).
- **Acceptation** : (1) 20 opérations des sortes 1 à 7 encodées par le C++ (dont une avec `reserved` ≠ 0) : décodage Rust égal, et réencodage Rust identique octet pour octet ; (2) un journal écrit par Rust **avec les sortes 1 à 7 seulement** est lu par `OpJournal::scan` du C++ avec le statut `Ok` et la même empreinte (le C++ refuse encore les sortes 8 et 9 : `kMaxKnownKind` = 7 ; elles sont testées côté Rust, avec les drapeaux de 19a § 3) ; un journal écrit par le C++ est rejoué par Rust ; (3) même ordre total que le C++ sur 10 000 soumissions mélangées (comparé au C++) ; (4) débit flush + journal ≥ 1 M op/s (le C++ fait ≈ 2 M op/s [Source : engine/ops/README.md]).
- **Capture** : aucune.
- **Piège** : l'ordre de tri inclut les octets de la charge en dernier ; queue tronquée (plantage) acceptée, CRC faux refusé ; `fsync`.

### L19 — `em_world` : deltas, appliqueur voxel, creusement, rejeu (M)

- **Crates** : `em_voxel` (`RegionDeltaStore`), `em_world`, `em_lab` (outil de creusement).
- **Interface** :
  ```rust
  pub struct RegionDeltaStore; impl RegionDeltaStore { pub fn brick(&self, region: RegionKey, chunk: u16, brick: u16) -> Option<&Brick>;
      pub fn write_brick(&mut self, region: RegionKey, chunk: u16, brick: u16, b: Brick); pub fn regions(&self) -> impl Iterator<Item = RegionKey> /* triées */;
      pub fn fingerprint(&self) -> u64; }
  pub struct World;
  impl World { pub fn new(manifest: WorldManifest, terrain: Arc<dyn VoxelSource>) -> Self; pub fn sink(&self) -> &dyn OperationSink;
      pub fn step(&mut self, up_to_tick: u64) -> FlushReport; pub fn source(&self) -> Arc<dyn VoxelSource> /* composite */;
      pub fn take_dirty(&mut self) -> DirtySet /* chunks par niveau + boîtes */; pub fn fingerprint(&self) -> u64;
      pub fn record_journal(&mut self, path: &Path) -> Result<(), WorldError>;
      pub fn replay(journal: &Path, manifest: WorldManifest, terrain: Arc<dyn VoxelSource>) -> Result<World, WorldError>; }
  // + codec EMWM v1 de WorldManifest (19a § 2.2) ; World garde ses appliqueurs, son bus et ses deltas en champs privés
  pub struct VoxelApplier;   // Applier : formes box, sphere, capsule, list, blob ; only_class ; terrain → deltas (entités en L28)
  ```
  Outil (fenêtre) : clic = `VoxelEdit blob` (rayon et rugosité réglables) soumis au bus ; la brique éditée perd sa peau ; les cascades et les sondes sont prévenues.
- **Acceptation** : (1) 1 000 creusements aléatoires : empreinte du monde vivant = empreinte après rejeu complet du journal ; (2) idem avec 1 et 8 fils ; (3) latence d'un coup (soumission → briques prêtes au téléversement) ≤ 2 ms CPU [Mesuré, à rendre] ; (4) aucun trou visible dans la transition peau / voxels (0 pixel de ciel sous l'horizon autour du trou) ; (5) forme `blob` : 10 vecteurs de test épinglés (centre, rayon, rugosité, longueur d'onde, `op_id` → ensemble de voxels) et indépendance de l'ordre de parcours.
- **Capture pour Monsieur** : `11_trou_dans_la_colline.png`. Question : la transition lisse → voxels est-elle acceptable ?
- **Piège** : appliquer dans l'ordre du bus, jamais dans l'ordre d'arrivée ; une brique éditée dans plusieurs niveaux (réduction).

### L20 — Herbe et fleurs (`em_veg`) (L)

- **Crate** : `em_veg` (implémente `RenderPass` d'`em_render`).
- **Interface** :
  ```rust
  pub struct GrassConfig { pub tile_m: f32 /* 4 */, pub range_m: f32 /* 80 en haut, 48 en moyen */, pub density_near_per_m2: f32 /* 400 */, pub lod_m: [f32; 4] /* 8, 24, 48, 80 */ }
  impl GrassConfig { pub fn validate(&self) -> Result<(), ConfigError>; }
  pub struct FlowerSpecies { pub key: &'static str, pub mesh: FlowerMesh, pub density_scale: f32, pub clump_scale_m: f32 }
  pub fn place_blades_cpu(tile: (i32, i32), cfg: &GrassConfig, ground: &dyn GroundSampler, out: &mut Vec<BladeInstance>); // référence
  pub struct GrassPass; impl GrassPass { pub fn new(gpu: &GpuContext, cfg: GrassConfig, flowers: Vec<FlowerSpecies>) -> Self; } // élimination compute, dessin indirect
  ```
  Masques : classe `turf`, pente < 40°, pas d'eau, pas de brique éditée, chemins (densité ×0,2). Vent : direction, force, texture de rafales ; vecteurs de mouvement.
- **Acceptation** : (1) positions GPU = positions CPU pour 3 tuiles (à 0,1 mm près) ; (2) coût ≤ 0,75 ms au banc `prairie` en `haut` (portée 80 m ; `GroundTiles` à deux niveaux : 10 cm jusqu'à 51 m, 40 cm au-delà), ≤ 0,40 ms en `moyen` [à rendre] ; (3) 0 brin sur la roche, dans l'eau ou dans un trou ; (4) aucune tuile qui « saute » quand la caméra avance (transitions de LOD fondues).
- **Scène** : `prairie` (paysage du labo, prairie fleurie, un chêne `.vxm` en lisière), livrée par cette tâche ; avec le **scintillement du feuillage voxel** (variation de translucidité hachée dans le temps, réglable) pour la question Q4.
- **Capture pour Monsieur** : `12_prairie_1730.png`, `13_prairie_contrejour_1900.png`, et `13b_vent_ab.png` (herbe au vent à côté d'un arbre immobile, avec et sans scintillement du feuillage). Questions : réalisme de l'herbe à côté du pixel art ; Q4.
- **Piège** : génération dépendante de l'ordre des fils (utiliser l'indice du brin, jamais un compteur atomique, pour la graine) ; scintillement des brins lointains (fondu vers la normale du sol).

### L21 — Eau v1 : surface, écoulement, réfraction (L)

- **Crate** : `em_water_render` ; shaders portés de `web-ocean` `sim.js` (initialisation, évolution, FFT lignes et colonnes, mips LEAN, texture de mousse) et `ocean.js` (Fresnel, éclats, masquage de Smith, diffusion, mousse), avec 2 ou 3 petites cascades.
- **Interface** :
  ```rust
  pub trait WaterSurfaceSource /* docs/19 § 2.5 */ ;
  pub struct WaterTile { /* privé : origine (mm), 16 × 16 cellules de 25 cm : niveau, vitesse, mousse, profondeur */ }
  impl WaterTile { pub fn new(origin_mm: [i64; 2]) -> Self; pub fn set_cell(&mut self, i: u8, j: u8, cell: WaterCell); pub fn cell(&self, i: u8, j: u8) -> WaterCell; pub fn origin_mm(&self) -> [i64; 2]; }
  pub struct AnalyticWater { /* étang, ruisseau le long d'une courbe, marche de cascade du LabLandscape */ } impl WaterSurfaceSource for AnalyticWater
  pub struct WaterPass; // surface, carte d'écoulement à deux phases, réfraction (copie HDR), absorption, ciel par le cube, réflexion d'écran
  ```
- **Acceptation** : (1) validation `naga` des shaders portés ; (2) coût ≤ 0,25 ms avec l'eau sur 30 % de l'écran (sans les reflets tracés, qui viennent en L27) ; (3) la mousse avance vers l'aval (centroïde de la mousse déplacé dans le sens de la vitesse, test) ; (4) aucune couture entre tuiles ; (5) scène `eau` (étang, ruisseau, marche de cascade du paysage du labo) livrée.
- **Capture pour Monsieur** : `14_etang_1000_1730_1900.png`, `15_ruisseau.png`. Question : couleur, transparence, reflets.
- **Piège** : unités (le `web-ocean` vise des vagues d'océan : réduire vent et cascades) ; réfraction qui montre ce qui est devant l'eau (tester la profondeur).

---

## Phase F : la matière et le bâti

### L22 — Matière v2 : détail CC0, relief, joints (M)

- **Crates** : `em_material`, `em_render`, `em_lab` (`assets pack`) ; `engine-rs/scripts/fetch_textures.py` ; manifeste `engine-rs/lab/textures.toml` (19a § 6.3), images dans `assets/textures/` (hors git).
- **Contenu** : 12 couches CC0 au plus (bois fin, bois de poutre, écorce, pierre taillée, moellon, roche, terre, gravier, mousse) choisies sur ambientCG ou Poly Haven, licence et empreinte dans le manifeste ; détail projeté sur le plan de la face en coordonnées monde ; relief par différences finies ; fil du bois selon l'axe de la teinte ; joints seulement entre pièces différentes ; mousse et salissure.
- **Acceptation** : (1) **pas de biseau** : sur une poutre de 3 m (60 voxels en ligne), écart moyen de luminance entre les pixels de bord de voxel et ceux du centre ≤ 2 % ; (2) **un seul bois** : corrélation des couleurs de voxels voisins le long du fil ≥ 0,8 (contre ≤ 0,3 pour une mosaïque aléatoire, témoin du test) ; (3) joint présent entre deux pièces, absent entre deux voxels d'une même pièce (test synthétique) ; (4) atlas ≤ 20 Mo (12 couches 512² rgba8 + mips) ; (5) coût ajouté ≤ 0,1 ms.
- **Capture pour Monsieur** : `16_poutre_detail_ab.png` (sans détail, faible, fort). Question Q3.
- **Piège** : niveau de mip à choisir à la main dans le compute (pas de dérivées) : `log2(distance × angle_pixel / taille_texel)`.

### L23 — Recettes mur de pierre, poutre, poteau (M)

- **Crates** : `em_assembly` (minimal : `Recipe`, registre, placement statique depuis la scène), `em_gen` (générateurs `wall`, `beam`, `post`).
- **Interface** : `pub struct StoneWallRecipe; pub struct BeamRecipe; pub struct PostRecipe;` (implémentent `Recipe` ; paramètres de 19a § 4.1 ; pièces de pierre numérotées dans la teinte, mortier en retrait d'un voxel en option, pierres irrégulières tirées de la graine ; axe du fil dans la teinte) ; rastérisation à tout niveau.
- **Acceptation** : (1) empreintes déterministes ; (2) niveaux grossiers : accord d'occupation ≥ 90 % avec la réduction des voxels fins ; (3) aucune matière « chaux » ; (4) scène `mur_poutre` (mur de 3 × 2 m, linteau, poteau).
- **Capture pour Monsieur** : `17_mur_poutre_1730.png` à côté de `bon pierre.png` et `pas bon chaux.png`. Questions Q3 et Q5.
- **Piège** : pièces coupées par les bords de chunk (le numéro de pièce doit venir de la recette, pas du chunk).

---

## Phase G : l'atmosphère

### L24 — Brume volumétrique, rayons, perspective aérienne (M)

- **Crate** : `em_render` (`FogPass` : froxels 160 × 90 × 128 en `haut` (64 tranches en `moyen`), injection, lumière par les cascades, intégration, application ; perspective aérienne de Hillaire au-delà).
- **Scène** : `foret` (6 à 8 arbres `.vxm` sur le paysage du labo, prises de vue à contre-jour), livrée par cette tâche.
- **Acceptation** : (1) coût ≤ 0,45 ms en `haut` (160 × 90 × 128, lanternes dans la brume), ≤ 0,22 ms en `moyen` ; (2) rayons : soleil bas dans `foret`, variance de luminance le long d'une ligne de brume au-dessus du seuil fixé dans le test ; (3) pas de scintillement : écart image à image ≤ ΔE 0,5 caméra fixe.
- **Capture pour Monsieur** : `18_rayons_foret_1900.png`. Question : densité de la brume du soir.
- **Piège** : fuite de lumière à travers les murs (échantillonner les cascades, jamais une lumière non ombrée).

### L25 — Lumières ponctuelles ombrées, nuit (M)

- **Crates** : `em_render` (tuiles de lumières, rayons d'ombre en ligne, émission, scintillement), `em_gen`/`em_assembly` (recette `lantern` qui déclare sa lumière).
- **Acceptation** : (1) fuite : lumière dans une pièce close à murs de 30 cm : éclairement sur la face extérieure ≤ 1 % de l'intérieure ; (2) coût ajouté ≤ 0,25 ms avec 8 lumières ombrées par tuile en `haut`, ≤ 0,15 ms avec 4 en `moyen` ; (3) les sondes voient la lanterne (rebond).
- **Capture pour Monsieur** : `19_lanterne_nuit.png`. Question : couleur et portée de la flamme.
- **Piège** : plus de 4 lumières fortes dans une tuile (garder les plus fortes, sans papillotement).

---

## Phase H : l'échelle

### L26 — Clipmap 6 niveaux, LOD, porte budgétaire forêt dense (L)

- **Crate** : `em_render` (`ClipmapStreamer` complet : 6 niveaux toriques, glissement, priorités, budget de 8 Mo par image ; `ChunkBoxPass` → `t_enter` ; transitions tramées entre niveaux), `em_lab` (scène `foret_dense` : paysage du labo étendu, arbres de la bibliothèque `.vxm` placés à 1 / 40 m² jusqu'à 800 m, chemin de caméra `orbit.toml`).
- **Acceptation** : (1) **porte budgétaire** : `voxel_trace` ≤ 1,0 ms en médiane en 1080p sur le chemin du banc ; au-delà de 1,2 ms, appliquer les replis de `docs/19` § 4.3 dans l'ordre et rapporter chaque mesure ; (2) vol à 20 m/s : 0 chunk manquant dans le champ après 0,5 s ; (5) les arbres utilisent les 6 LOD exportés par L04 (pas de repli d'un niveau sur un autre) ; (3) mémoire GPU mesurée comparée au § 1.5 ; (4) rapport JSON complet de toutes les passes.
- **Capture pour Monsieur** : `20_panorama_foret.png` + le tableau des ms. Question Q8.
- **Piège** : glissement torique (un chunk évincé encore lu par le GPU dans l'image en vol) ; rayon qui change de niveau au bord du cube.

### L27 — Eau v2 : reflets tracés, cascade, embruns (M)

- **Crate** : `em_water_render` (rayons de réflexion voxel en demi-résolution, nappe de cascade, injection des embruns dans la brume).
- **Acceptation** : (1) les arbres et le mur se reflètent dans l'étang, y compris hors écran ; (2) coût de l'eau ≤ 0,45 ms quand l'étang remplit l'écran (pire cas, reflets en pleine résolution), ≤ 0,35 ms dans le banc de synthèse en `haut` ; (3) la cascade ne scintille pas (ΔE ≤ 0,5 caméra fixe hors écoulement).
- **Capture pour Monsieur** : `21_cascade_et_reflets.png`.
- **Piège** : rayons de réflexion qui partent sous la surface.

### L28 — Entités, opérations de recette, paquet `EMPK`, instantanés (L)

- **Crates** : `em_assembly` (table d'entités, rustines locales, `EntityApplier` pour `EntityRecipe`, `EntityParts`, `Destroy` ; recettes `log`, `table`, `vxm_model` ; matérialisation de `base_ref`), `em_ops` (`PackStore` : écriture, ouverture, validation, compactage, 19a § 2), `em_world` (instantanés, ouverture d'une partie), `em_lab` (touche « transmuter » : deux bûches → une table par le bus).
- **Interface** :
  ```rust
  pub struct EntityTable; impl EntityTable { pub fn get(&self, id: EntityId) -> Option<&EntityRecord>; pub fn fingerprint(&self) -> u64; }
  pub struct EntityApplier; impl Applier for EntityApplier
  pub struct PackStore; impl PackStore { pub fn create(path: &Path) -> io::Result<Self>; pub fn open(path: &Path) -> Result<Self, PackError>;
      pub fn commit(&mut self, op_id: u64, records: &[PackRecord]) -> io::Result<()>; pub fn get(&self, kind: u16, key: u64) -> Option<Vec<u8>>;
      pub fn compact(&mut self) -> io::Result<()>; pub fn dead_ratio(&self) -> f32; }
  impl World { pub fn snapshot(&mut self) -> anyhow::Result<u64 /* op_id */>; pub fn open_save(dir: &Path) -> anyhow::Result<World>; }
  ```
- **Acceptation** (preuves de `docs/19` § 3.6) : (1) monde vivant = base + rejeu complet = instantané au milieu + rejeu de la queue (empreintes égales) sur 10 000 opérations mêlées (creuser, matérialiser, transmuter, retirer des parties) ; (2) pied de paquet corrompu : ouverture sur la validation précédente ; (3) compactage : taille réduite, contenu égal ; (4) coûts de la table de `docs/19` § 3.7 mesurés et rapportés.
- **Capture pour Monsieur** : `22_buches_puis_table.png` (avant, après).
- **Piège** : un objet de base matérialisé deux fois (pierre tombale à poser dans la même opération) ; révision attendue non vérifiée.

### L29 — Scène de synthèse, préréglages, rapport budgétaire (M)

- **Crate** : `em_lab` (scène `village_mini` : colline, falaise, étang, ruisseau, cascade, chêne et forêt, mur et poutre, lanterne, prairie), `em_render` (préréglages `bas`, `moyen`, `haut` étalonnés).
- **Acceptation** : (1) banc complet aux heures 10, 17,5, 19 et de nuit ; (2) en `haut`, passes du labo ≤ 5,5 ms en médiane (donc ≤ 6,5 ms avec la réserve d'1 ms) et jamais plus de 8,3 ms en médiane sur aucun banc ; sinon, liste des réglages baissés dans l'ordre de `docs/19` § 1.4 jusqu'à tenir, avec la mesure à chaque pas ; `moyen` et `bas` étalonnés et mesurés ; (3) `docs/19` § 1.4 et § 1.5 mis à jour avec les valeurs [Mesuré] ; (4) toutes les références d'images vertes.
- **Capture pour Monsieur** : `23_village_mini_planche.png` (4 heures). Question : le style est-il validé ?
- **Piège** : mesurer avec la carte chaude (chauffe de 10 s) et noter les horloges.

---

## Phase I : les générateurs en Rust

### L30 — Port Rust de `voxel_tree` : squelette en Q16 (L)

- **Crates** : `em_gen` (module `tree`), données `engine/data/species.toml` (exportées depuis les `Species` Python par un script, 16 essences, rampes comprises).
- **Interface** : `pub struct TreeGenerator;` (implémente `Generator`) ; `pub struct TreeParams { pub species: String, pub height_mm: u32, pub season: Season, pub leaf_density_permille: u16 }` ; plan = squelette (croissance ordre par ordre, phyllotaxie à l'angle d'or, tropismes, enveloppe de couronne, auto-élagage par cellules d'encombrement, rayons par le modèle des tuyaux, exposant 2,4).
- **Acceptation** : (1) déterminisme (empreinte du plan épinglée ; identique avec 1 et 8 fils) ; (2) sur 20 graines par essence, contre Python : nombre de nœuds ±10 %, boîte de la couronne ±5 %, rayon à la base ±5 % ; (3) plan ≤ 30 ms par arbre [Mesuré, à rendre].
- **Capture** : aucune (vue du squelette facultative).
- **Piège** : le Python utilise `numpy` (flottants, générateur non portable) : on porte la **sémantique**, pas les bits ; trigonométrie en tours Q16.

### L31 — Port Rust : épaisseurs, rastérisation, feuillage, couleurs (L)

- **Crate** : `em_gen` (module `tree`, suite).
- **Contenu** : capsules effilées pour le bois épais, tracé 3D des brindilles, amas de feuilles (ellipsoïdes bruités, trouées, aiguilles), plafond de hauteur, priorité des sortes, teintes `vegetation(essence, rampe)`, rastérisation paresseuse par fenêtre à tout niveau.
- **Acceptation** : (1) sur 20 graines par essence, contre Python : voxels ±10 %, part de feuilles ±3 points, briques occupées ±10 % ; (2) rastérisation LOD0 ≤ 20 ms (un arbre de 600 000 voxels) ; (3) déterminisme ; (4) même rendu de matière qu'avec le `.vxm` (L10).
- **Capture pour Monsieur** : `24_chene_rust_et_python.png` (même essence, même hauteur). Question : reconnaît-on le générateur validé ?
- **Piège** : la fenêtre de rastérisation coupe un amas de feuilles : le bruit doit venir des coordonnées monde, pas de l'ordre de parcours.

### L32 — Port Rust : arbustes, topiaire, silhouettes lointaines (M)

- **Crate** : `em_gen`.
- **Contenu** : arbustes multi-tiges, fleurs et fruits par saison, topiaire (sphère, dôme, cube, cône) ; recette `tree_silhouette` (fût + amas du houppier tirés de la même graine, sans croissance) pour les niveaux ≥ 3.
- **Acceptation** : (1) parité statistique avec `voxel_bush.py` comme en L31 ; (2) silhouette contre arbre complet au niveau 3 : IoU d'occupation ≥ 0,7, coût ≤ 0,1 ms par arbre ; (3) la forêt du banc L26 se compose avec les silhouettes au-delà de 100 m sans saut visible au passage de niveau (capture).
- **Capture pour Monsieur** : `25_haie_et_topiaires.png`, `26_foret_silhouettes.png`.
- **Piège** : une silhouette qui ne tombe pas sous le vrai houppier (même graine, mêmes tirages de départ que le squelette).
