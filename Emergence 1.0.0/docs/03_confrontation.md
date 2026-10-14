# Confrontation : travail des développeurs et architecture

8 octobre 2026. Ce que contenaient les quatre ZIP, ce qu'on garde, ce qu'on adapte, ce qu'on écarte, et le travail qui reste. Tous les tests mentionnés ont été relancés le 8 octobre dans un environnement propre.

## 1. Inventaire des ZIP

| ZIP | Contenu réel | Devenu |
|---|---|---|
| `projet_brut.zip` | Pipeline PNJ (25 fichiers en double : `outputs/npc_pipeline/` et `work_home_claude/`, identiques ; la seconde copie a en plus `representation.py`, `corpus_report.py`, `states_400.jsonl`), catalogues de variables v0.1 et v0.2 (plus leurs brouillons en morceaux), rapport d'audit, anciennes versions `.bak`, et des résidus d'environnement (`.npm/`, `.npm-global/`, binaire `uvx`, journaux npm) | Code dans `ai/npc_pipeline/`, docs dans `docs/npc/`, anciennes versions dans `archive/npc_old_versions/`. Résidus et brouillons écartés |
| `npc_project.zip` | Le README de passation des devs (6 octobre) | `docs/npc/README_devs_npc_2026-10-06.md` |
| `livraison_brute.zip` et `livraison_brute1.zip` | Identiques octet pour octet : le convertisseur `voxelizer` et ses sorties de travail (images, benchmarks, relevés) | `tools/voxelizer/`, sorties dans `archive/voxelizer_work/` |

Aucune clé d'API n'est présente dans les fichiers (vérifié par recherche du motif des clés Google). Le README des devs signale toutefois qu'une clé Gemini a été collée dans une conversation le 6 octobre : **elle doit être révoquée**.

## 2. État vérifié

| Composant | Tests relancés le 8 oct. | Résultat |
|---|---|---|
| Contrat de plans (`plan_contract.py`) | 9 | OK, 111 fonctions (84 de base), 20 conditions |
| Mémoire (`memory_service.py`) | 16 | OK |
| Chantier par différence (`build_site.py`) | 13 | OK |
| Analyseur d'énoncés (`utterance_parser.py`) | démonstration | OK |
| 30 cas de capacités (`scenario_tests.py`) | 30 | 22 OK, 7 LEARN, 1 SPEC (groupes) |
| Représentation (`representation.py`) | aller-retour | OK, 127 variables |
| Générateur (`generate_states.py --n 500 --check`) | 18 invariants | aucune violation |
| Pipeline complet sans clé (`selftest_pipeline.py`) | contre faux serveur | ALL CHECKS PASSED |
| Convertisseur (`tools/voxelizer`) | 50 | OK (60 s) |

## 3. Composant par composant

| Sujet | Devs | Architecture | Verdict | Action |
|---|---|---|---|---|
| Séparation décision / action / données | 3 couches, 3 messages | Utility → HTN → exécution | **Garder celle des devs** : plus précise, elle devient le contrat du moteur | Porter en C++ dans `act` et `decide` |
| Décideur | Transformer distillé qui note des intentions candidates | Utility AI + HTN ; Transformer possible sur GPU dédié | **Les deux, même contrat** (voir architecture § 8.2) | Écrire la référence à utilités d'abord ; l'élève doit la battre |
| Nombre de PNJ | ~120 (3 villages de 40), cible RTX 4070 | 300, puis 50 000 envisagés | **500 en 5 villages** [Décidé] | Mettre à jour le générateur (couche village) |
| Matériel cible | RTX 4070 chez le joueur | Iris Xe pour le rendu, RTX série 3000 6 Go pour l'IA | **Architecture** [Décidé] | Budgets VRAM en § 9.3 |
| Plans de 1 à 6 étapes avec conditions | fait et testé | non prévu sous cette forme | **Garder** : un plan = une décision, coût divisé | — |
| 111 fonctions | toutes spécifiées | catalogue d'interactions | **Garder la liste, construire une tranche** | Tranche : travail, parole, avis, un vote |
| Mémoire | riche, testée, balayage linéaire, 300 à 1 000 souvenirs | 48 octets, 256 souvenirs, index | **Celle des devs**, avec index et faits partagés | Index ; contenu des souvenirs |
| Couche village et groupes | absente (cas 29 en SPEC) | institutions comme entités | **Priorité** | Moteur d'institutions, jetons village et groupe |
| Monde des variables (`variables_v0.2` § 9) | grille 2D de cellules | voxels 3D + résumés de région | **Architecture** : la grille 2D devient le résumé de région lu par la société | Définir le résumé de région (terrain, ressources, propriétaires, danger) |
| Construction | chantier par différence, mode main et mode rituel | opérations matérialisées à l'arrivée du joueur | **Fusion** : blueprint = instances de modules ; mode rituel = matérialisation lointaine | Adapter `build_site.py` aux modules |
| Outils (pioche, pelle, truelle, mains) | physique d'outils dans le moteur d'action | outils = formes d'opérations | **Identiques** | Formes paramétriques dans `ops` |
| Langage | analyseur anglais + cadres, LLM local pour verbaliser | non traité | **Garder** ; le texte n'entre jamais dans l'état | Question de la langue du jeu ouverte |
| Déterminisme de l'IA | tirage par graine de PNJ | inférence entière | **Les deux** | Prototype 7 du rendu (deux GPU) |
| Teacher Gemini | pipeline prêt, jamais lancé en vrai | — | **Garder l'ordre des devs** | Points 1 à 9 de leur README avant tout gros run |
| Données d'entraînement | générateur synthétique | simulateur sans rendu comme source | **Les deux** : amorçage synthétique, puis états du simulateur | Boucle DAgger (architecture § 9.2) |
| Règles dures (mineurs) | moteur, réflexes, tests | — | **Garder sans exception** | Invariant I7 |
| Romance entre adultes apparentés | autorisée, décision du porteur, interrupteur prévu | — | **Garder la décision**, risque Steam signalé | À reconsidérer avant la sortie |
| Convertisseur : format | VXP, briques 8³, palettes locales, dédup, blocs compressés, coque seule | chunks 64³ en briques 8³, voxel = matière 16 bits | **Compatibles** : même brique 8³ | Voir § 4 |
| Convertisseur : couleur | couleur par voxel, palette k-means | matière seule + bruit dans le shader | **Synthèse** : VoxelId = classe 9 bits + teinte 7 bits | Projeter les palettes sur les rampes des classes |
| Convertisseur : matières | indice dans les noms de matériaux d'origine | matière physique (résistance, combustible) | **Architecture** | Table de correspondance matériau d'origine → classe |
| Convertisseur : langage | Python, accès `get()` en 20 à 55 µs | cœur C++ | **Outil reste en Python** ; décodeur VXP porté en C++ | — |

## 4. Convertisseur : ce qui reste à faire pour qu'il serve le jeu

Dans l'ordre :

1. **Table de matières** : chaque matériau ou texture d'origine est rattaché à une classe de la palette globale (chêne, granit taillé, plâtre, tuile, chaume…), proposée automatiquement et corrigée à la main.
2. **Identifiants 16 bits** : projeter la palette OKLab de chaque pièce sur les rampes de teintes de sa classe ; mesurer l'écart visuel.
3. **Alignement sur la grille du monde** : modules orientés dans l'une des 24 orientations, briques alignées sur les briques 8³ des chunks.
4. **Niveaux de détail précalculés** par module (réduction 2×, 4×, 8× qui préserve les murs fins), maillage greedy de chaque niveau.
5. **Métadonnées de module** : connecteurs, graphe porteur (poutres, murs, piliers), sources de lumière, boîtes de collision.
6. **Murs ouverts du kit** : vérifier le volume obtenu par `--seal 11` (≈ 55 % d'une dalle pleine, non vérifié) ou corriger à la source.
7. **Traitement du kit entier** (176 pièces, 8 trop grandes ignorées) et des grands toits (> 30 M cellules) par découpe en sous-modules.
8. **Décodeur VXP en C++** dans le cœur, testé contre la version Python.
9. Piste des devs non réalisée : texture procédurale triplanaire par matière plus résidu, pour réduire encore la couleur.
10. Licence des modèles du kit de test à vérifier avant toute distribution.

## 5. Pipeline PNJ : ce qui reste à faire

La liste des devs (section 7 de leur README) reste valable et ordonnée. S'y ajoutent, du fait des décisions du 7 et du 8 octobre :

- couche village pour 5 villages et ~100 habitants chacun, avec économies complémentaires (architecture § 2.3) ;
- jetons village, groupe, lieu, objet et lien émis par le générateur ;
- familles de situations nouvelles : commerce entre villages, voyage, frontière et légendes de l'au-delà, conflit de parcelles, apprentissage et perte d'une technique ;
- décideur de référence à utilités, écrit avant l'entraînement ;
- portage en C++ des modules du moteur, avec les versions Python comme oracles.

## 6. Ce qui a été écarté et pourquoi

- `.npm/`, `.npm-global/`, `.local/bin/uvx`, `.config/`, `.wget-hsts`, `.npmrc` : résidus de l'environnement de travail des devs, sans rapport avec le projet.
- `variables_part1-3.md`, `v02_part1-2.md` : brouillons découpés des catalogues finaux, identiques à un détail près (la ligne `idéal_partenaire`, version finale gardée).
- `outputs/npc_pipeline.zip` et sa copie dépliée : doublons de `work_home_claude/`.
- `livraison_brute1.zip` : doublon exact de `livraison_brute.zip`.
