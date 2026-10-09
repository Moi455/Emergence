# CLAUDE.md — Emergence

Tu travailles sur **Emergence**, un jeu médiéval-fantastique pour Steam : un monde de voxels destructible et 500 PNJ en 5 villages, chacun piloté par un Transformer, dans une **simulation réelle du monde** où tout doit émerger. Le porteur du projet est **Monsieur**. Il écrit en français : réponds-lui en français, simplement, en commençant par la réponse.

Tu tournes maintenant **sur sa machine** (portable, RTX série 3000 de 6 Go, 16 Go de RAM), avec un vrai GPU. Les sessions précédentes tournaient dans le cloud, sans GPU : aucun chiffre de performance réel n'existe encore. Ton travail est de mesurer, d'entraîner et de brancher pour de vrai.

## À lire avant toute tâche (dans cet ordre, et rien d'autre tant que ce n'est pas utile)

1. **`CHARTE_DU_JEU.md` (racine) : la charte fonctionnelle et de design de Monsieur. Elle prime sur TOUT** : documents, décisions, code, ce fichier. En cas de contradiction, la charte gagne ; signale la contradiction à Monsieur.
2. `CHANTIERS.md` : ce qu'il faut faire, dans quel ordre, et les questions ouvertes.
3. `docs/06_architecture_expliquee.md` (révision 2) : l'architecture voulue par Monsieur au 8 octobre au soir. **Il fait foi** là où `docs/02_architecture_cible.md` le contredit.
4. `docs/01_decisions.md` : D1 à D27 sont décidés ; ne les contredis jamais. Les « Proposé » ne sont pas acquis.
5. Le `ETAT.md` du dossier où tu travailles (`ETAT.md` à la racine, `engine/`, `ai/`, et les autres quand ils existent), puis son `README.md` ou `CLAUDE.md`.
6. `docs/interfaces.md` : le contrat entre les parties (unités, voxels, matières, personnages, actions, identifiants).

## La barre visuelle

Les images de `docs/style/` (`monde_type.png`, `maison_type.png`, `pnj_type.png`, `style_jeu.jpg`) sont **le niveau attendu, pas moins** (Monsieur, 8 oct.). Blocs lisibles et texturés, mousse et lierre, lumière chaude en temps réel, brume et rayons de soleil, profondeur jusqu'aux montagnes, personnages en style voxel à facettes. Tout travail de rendu, d'asset ou de personnage se juge contre ces images, capture à l'appui.

## Ce que Monsieur veut (résumé de D17 à D27 ; la charte fait foi)

1. **Chaque PNJ est piloté par le Transformer**, plusieurs fois par seconde, sans cache, par lots sur le GPU. Il reçoit perception, identité, souvenirs, état ; il rend une action et des ajustements progressifs de ses variables (seule une émotion peut sauter d'un coup). Pas de moteur de règles écrit à la main pour décider à la place du modèle.
2. **Les 500 PNJ sont simulés à pleine puissance partout**, même loin du joueur ; seul le rendu est coupé hors de vue. **Toute action a une répercussion persistante** (une `Operation` appliquée au monde, chargé ou non, et sauvegardée).
3. **Avant de coder une action ou une variable**, elle doit être dans le catalogue unique (`ai/CATALOGUE_modele.md` et le catalogue de `sim/`).
4. **GPU** : le rendu utilise le moins possible du GPU dédié ; l'essentiel reste au Transformer.
5. **Rendu** : voxels du monde plus gros que 2 cm (taille ouverte : 5 cm proposé, 10 cm essayé par le prototype village), textures (demandées ; le prototype s'en passe, question O14), lumière en temps réel (heure, nuages, météo), pas d'upscaling.
6. **Eau et feu** au plus léger, pas forcément en voxels ; l'eau est une quantité prélevable qui réagit.
7. **Frontières** : monde physique d'environ 20 × 20 km ; aucune limite visible, jamais de retour au village ; la difficulté tue avant le bord.
8. **Temps** : un PNJ vit environ 150 h de jeu (charte § 25) ; variables psychologiques de −10 à +10 ; traits qui évoluent progressivement ; profondeur de simulation variable selon les PNJ (§ 24).

## Règles qui ne se négocient pas

- **Mesurer avant d'affirmer.** Un chiffre sans mesure est une estimation et se dit comme tel. Donne les résultats réels, même rouges.
- **Déterminisme de la génération du monde** : bit-exacte depuis la seed (entiers et virgule fixe, pas de `-ffast-math`, pas de `rand()`). Les empreintes épinglées dans les tests font foi.
- **Une seule vérité** : seed + plan, chunks modifiés, journal d'opérations, entités. Tout le reste est un cache.
- **Le texte libre n'entre jamais dans l'état de simulation.**
- **Règles dures, jamais apprises** : aucun acte romantique ou sexuel impliquant un enfant ou un adolescent, comme acteur ou comme cible. Ne génère, n'étiquette et ne teste jamais de tels contenus, sauf les tests de refus déjà prévus.

## Sécurité et coûts

- Aucun secret dans le dépôt. La clé Gemini se lit dans `GEMINI_API_KEY`, jamais dans un fichier, un log ou un commit.
- **Aucun appel payant** (Gemini, autre API, Meshy ou autre service) sans l'accord explicite de Monsieur pour cet appel. `teacher_run.py pilot|run` est concerné.

## Économie de tokens

Monsieur trouve la consommation trop élevée. `.claudeignore` et `.claude/settings.json` (règles `permissions.deny`) écartent les données, binaires, modèles 3D, captures et builds. Ne contourne pas ces règles ; lis un fichier par morceaux quand il est long, et ne relis pas ce que tu viens d'écrire.

## Commandes

```
scripts/test_all.sh                       # pipeline PNJ, convertisseur (Python)
cmake -S engine -B build && cmake --build build -j && ctest --test-dir build   # cœur C++
godot --path game                         # scène jouable (touche H : temps GPU, images/s)
python ai/student/train_student.py ...    # voir ai/student/ENTRAINEMENT.md
```

## Organisation du dépôt

```
CHANTIERS.md      travaux ouverts, ordre, questions pour Monsieur
ETAT.md           état du dépôt ; chaque dossier a le sien
docs/             décisions, architecture (06 fait foi), interfaces, style/ (barre visuelle), reference/
engine/           cœur C++20 (plan, chunks, maillage, terrain) + extension Godot
worldgen/         génération déterministe du monde
game/             projet Godot 4.6, scène play.tscn
ai/               Transformer des PNJ : contrat, catalogue, jetons, données, entraînement (student/)
sim/              simulation sociale provisoire (moteur à règles, à remplacer par la boucle Transformer)
characters/       générateur des villageois (à refaire en style voxel)
prototypes/       village jouable dans le navigateur
tools/voxelizer/  convertisseur 3D → voxels
archive/          anciennes versions, en lecture seule
```

## Conventions

- Code et identifiants en anglais ; documents pour Monsieur en français.
- C++20, CMake ; pas d'allocation par voxel ; formats versionnés (`schema_version`).
- Les modules Python de `ai/npc_pipeline` sont des **oracles** : un portage C++ doit reproduire leurs sorties.
- Toute décision va dans `docs/01_decisions.md` avec sa date ; quand un choix manque, prends un défaut raisonnable, dis lequel, et ajoute la question dans la section « Ouvert ».
- Monsieur veut des solutions, pas des listes de blocages.
