# CLAUDE.md — Emergence 1.0.0

Tu travailles sur **Emergence**, un jeu médiéval-fantastique pour Steam : 500 PNJ pilotés par un Transformer, dans une simulation où tout doit émerger. Le porteur du projet est **Monsieur**. Il écrit en français : réponds-lui en français, simplement, en commençant par la réponse.

Ce dossier est le paquet **1.0.0** (branche `emergence-1.0.0`), **fusionné le 14 oct.** avec l'ancienne branche `claude/moteur-social` (carte et tri par date : `docs/13_fusion_1.0.0.md`). Il contient tout : moteur social et IA des PNJ (travail actif), mais aussi le monde en voxels, le rendu, les personnages 3D, l'eau et l'ancienne IA, **mis en `.claudeignore`** pour cette session (moteur social des PNJ). Pour les lire, retirer la ligne de `.claudeignore` puis lancer `python3 scripts/sync_claudeignore.py`.

Machine de Monsieur : Quadro RTX 3000 6 Go (Turing, float16 seulement), i9-10885H 8 cœurs, 62 Go de RAM. C'est la cible de mesure : ce qui tourne dessus tournera sur la RTX 3060 mobile des joueurs.

## À lire avant toute tâche (dans cet ordre)

1. `CHARTE_DU_JEU.md` : la charte de Monsieur. **Elle prime sur tout** ; signale toute contradiction.
2. `CHANTIERS.md` et `ETAT.md` : ce qui reste à faire, et dans quel ordre.
3. `docs/06_architecture_expliquee.md` : l'architecture voulue par Monsieur (fait foi sur `docs/02`).
4. `docs/01_decisions.md` : D1 à D32 sont décidés ; les « Proposé » ne sont pas acquis.
5. `docs/09_architecture_ia_rd.md` (le cerveau des PNJ, mesuré) et `docs/08_comment_ca_marche.md` (le catalogue).
6. Le `README.md` du dossier où tu travailles.

## Ce que Monsieur veut

- **Au moins 200 décisions de PNJ par seconde**, un seul modèle partagé, par lots sur le GPU, réveils sur événement. Rien d'autre n'est imposé au budget (13 oct.).
- **GPU : 25 % au maximum pour l'IA**, si cela augmente nettement l'intelligence et l'émergence de situations, de relations et d'organisations complexes. Réduire sans perdre de qualité est bienvenu (13 oct.).
- **Des comportements complexes et collectifs** : « Pierre, Jacques et Jean sont partis dans la forêt pour tuer ensemble George, car il a trompé leurs femmes » ; « le maire a organisé une expédition pour aller trouver de l'or ». L'architecture retenue est la **pensée écrite** (docs/09, P31).
- **Simulation maximale, au plus proche de la vraie vie.** Pendant l'entraînement seulement, un évaluateur peut lire la vérité du monde ; jamais en jeu.
- **Des réactions souvent disproportionnées ou absurdes** font l'amusement. Une variable de partie laissera le joueur choisir le tempérament du village (fous, modérés, sages…) : à concevoir.
- Pas de moteur de règles écrit à la main qui décide à la place du modèle. Toute action a une répercussion persistante.
- Avant de coder une action ou une variable, elle doit être dans le catalogue (`catalogue/`, D28 ; `python3 catalogue/tools/check.py`).
- Moteur d'inférence livré : **TensorRT-RTX** (13 oct.).
- Langue intérieure : s'inspirer de la logique d'**ELIZA** (découpage en mots-clés, motifs de décomposition, extraction de sens), pas de sa conversation (13 oct.).

## Règles qui ne se négocient pas

- **Mesurer avant d'affirmer.** Un chiffre sans mesure est une estimation et se dit comme tel. Donne les résultats réels, même rouges.
- **Déterminisme** : entiers et virgule fixe pour le monde, pas de `-ffast-math`, pas de `rand()`. Les empreintes épinglées dans les tests font foi.
- **Une seule vérité** : catalogue, état des PNJ, journal d'opérations. Tout le reste est un cache.
- **Le texte libre n'entre jamais dans l'état de simulation.** Rien de vrai dans ce que lit le modèle (règle `no_truth_in_tokens`).
- **Règle dure D10** : aucun acte romantique ou sexuel impliquant un enfant ou un adolescent, comme acteur ou comme cible. Refus par défaut. Ne génère, n'étiquette et ne teste jamais de tels contenus, sauf les tests de refus.

## Sécurité et coûts

- Aucun secret dans le dépôt. La clé Gemini est dans `GEMINI_API_KEY` ou `~/.config/emergence/API_Keys` (droits 600) ; jamais affichée, journalisée ni commitée.
- Monsieur a autorisé son **quota gratuit Gemini** pour produire les données d'entraînement, en sortie JSON, avec changement automatique de modèle quand une limite (RPM, RPD, TPM, TPD) est atteinte, et un générateur qui tourne **en continu** (13 oct.). Tout autre appel payant demande son accord.

## Méthode de travail

- **Séquencer** au maximum, **orienté objet**, décomposer en profondeur avant de coder ; chercher l'open source existant (licence commerciale) avant de recoder.
- **C++ (ou Rust) seulement pour le moteur du jeu**, qui doit rester léger ; entraînement, données, outils et tests en **Python**.
- **Relecteur systématique** : après chaque travail, un sous-agent relecteur adverse, puis corriger ce qu'il trouve avant de présenter.
- **Sous-agents : Sonnet 5.5 par défaut** ; Opus seulement si Monsieur le demande.
- **Pousser souvent** sur GitHub (branche `emergence-1.0.0`, jamais `main`, jamais de force push), sauf consigne contraire de Monsieur pour une session.
- **Économie de tokens** : respecter `.claudeignore` (synchronisé par `scripts/sync_claudeignore.py`) ; lire par morceaux ; ne pas relire ce qu'on vient d'écrire.

## Commandes

```
scripts/test_all.sh                                   # tout : catalogue, tok-2, situations, professeur, élève, moteur C++
python3 catalogue/tools/check.py                      # le catalogue
cmake -S engine -B build && cmake --build build -j && ctest --test-dir build   # moteur social C++
cd ai && python3 -m situations.sampler --n 300        # situations d'amorçage
cd ai && python3 -m teacher.pilot --n 20              # rendu pour le professeur (sans réseau)
cd ai && python3 -m student2.train --help             # entraînement de l'élève
```

## Organisation

```
CHARTE_DU_JEU.md   la charte de Monsieur (prime sur tout)
CHANTIERS.md       travaux ouverts ; ETAT.md : état
docs/              décisions (01), architecture (02, 06), IA (07, 09), catalogue expliqué (08), interfaces, glossaire, vision
catalogue/         source unique : variables, gestes, langue, jugements, règles dures ; outils, interface générée, tests
engine/social/     moteur social C++20 : gouverneur, état des PNJ, horloges (tables générées depuis catalogue/)
ai/tok2/           format d'entrée du modèle (oracle Python du futur portage C++)
ai/situations/     situations d'amorçage plausibles (avec audit D10)
ai/teacher/        professeur LLM : rendu, schéma de réponse, validation, pilote et générateur de données
ai/student2/       l'élève : modèle, étiquettes, entraînement en float16
ai/research/       bancs d'essai et sondes mesurés (docs/07, docs/09)
engine-rs/         monde physique en Rust (wgpu, winit) : laboratoire de style, début du moteur du monde (docs/19, 19a, 19b)

Ignorés pour cette session (présents, lisibles sur demande, voir `.claudeignore`) :
engine/core/{base,world,mesh}, gdext, terrain, em_water   moteur voxel, extension Godot, eau (Rust)
worldgen/ game/ prototypes/ characters/ tools/voxelizer/   monde, scène Godot, village web, villageois 3D, voxeliseur
ai/npc_pipeline/ ai/student/ sim/                          ancienne IA et ancienne simulation à règles
archive/ docs/style/ docs/reference/ docs/npc/             historique et barre visuelle
```
