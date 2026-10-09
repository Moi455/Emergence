# Journal des décisions

Chaque ligne a un statut : **Décidé** (par Monsieur), **Proposé** (par Claude, en attente de validation), **Ouvert** (question à trancher). Ajouter une ligne, ne jamais effacer : une décision remplacée est marquée « remplacée par n° X ».

## Décidé

| N° | Date | Décision | Source |
|---|---|---|---|
| D1 | 2026-10-07 | La performance est la priorité numéro 1 | Monsieur |
| D2 | 2026-10-07 | Rendu sur le GPU intégré ; GPU dédié réservé à l'IA | Monsieur |
| D3 | 2026-10-07 | Voxels de 2 cm, monde entièrement destructible, eau, feu, effondrements | Monsieur |
| D4 | 2026-10-07 | Monde déterministe depuis une seed ; seuls les deltas sont sauvegardés | Monsieur |
| D5 | 2026-10-07 | Procédural en voie principale, convertisseur 3D → voxels pour les modèles faits main | Monsieur |
| D6 | 2026-10-07 | Savoir-faire transmis par apprentissage avec baguettes limitées, perdables | Monsieur |
| D7 | 2026-10-07 | 500 m de profondeur, montagnes jusqu'à 3 km, horizon lointain | Monsieur |
| D8 | 2026-10-08 | 500 PNJ en environ 5 villages | Monsieur |
| D9 | 2026-10-08 | Frontières mer, forêt, montagne, désert, à difficulté exponentielle, illusion d'un au-delà | Monsieur |
| D10 | 2026-10-02 | Règles dures : aucun acte romantique ou sexuel impliquant un enfant ou un adolescent | Projet PNJ des devs, confirmé |
| D11 | 2026-10-02 | Romance entre adultes apparentés : pas de règle dure, le modèle décide via la norme de tabou (interrupteur `--no-adult-kin-romance`) | Porteur du projet, selon le README des devs |
| D12 | 2026-10-06 | Teacher hors jeu : Gemini (3.5 Flash-Lite) ; aucune API dans le jeu livré | Projet PNJ des devs |
| D13 | 2026-10-08 | Carte de 20 × 20 km, frontières mer à l'ouest, montagne au nord, désert à l'est, forêt au sud (P1 et P16 acceptés) | Monsieur |
| D14 | 2026-10-08 | Langue du joueur : anglais seulement pour l'instant ; architecture prête pour d'autres langues | Monsieur |
| D15 | 2026-10-08 | Romance : composante naturelle de la vie sociale, jamais d'acte sexuel explicite ; le jeu ne porte pas dessus. D11 conservée, conformité Steam à vérifier avant la sortie | Monsieur |
| D16 | 2026-10-08 | Clé Gemini du 6 octobre révoquée | Monsieur |
| D17 | 2026-10-08 | But : simulation réelle du monde, au maximum ; tout doit émerger, aucun moteur de règles écrit à la main pour les PNJ | Monsieur |
| D18 | 2026-10-08 | Chaque PNJ est piloté par le Transformer, plusieurs fois par seconde, sans cache, par lots sur le GPU. Entrée : perception, identité, souvenirs, état. Sortie : une action + des ajustements progressifs des variables (seule une émotion peut sauter d'un coup). Remplace P6, P7, P21 et la règle de décision par paliers | Monsieur |
| D19 | 2026-10-08 | Les 500 PNJ sont simulés à pleine puissance partout et tout le temps ; seul le rendu est coupé hors de vue ; toute action a une répercussion persistante dans le monde | Monsieur |
| D20 | 2026-10-08 | Avant de coder : catalogue complet des variables et des actions. Données d'entraînement produites par un modèle bien moins cher que Claude | Monsieur |
| D21 | 2026-10-08 | GPU dédié permis pour le rendu, au strict minimum ; il sert d'abord à l'IA. Le profil « GPU intégré seul » tombe. Remplace D2 | Monsieur |
| D22 | 2026-10-08 | Voxels du monde bien plus gros que 2 cm (taille à fixer, défaut proposé 5 cm) ; textures sur les voxels ; niveau visuel attendu = images de `docs/style/`, pas moins. Amende D3 | Monsieur |
| D23 | 2026-10-08 | Lumière calculée en temps réel (heure, nuages, météo) ; seules des données rééclairables peuvent être précalculées, jusqu'à 1 Go ; pas d'upscaling | Monsieur |
| D24 | 2026-10-08 | Eau et feu au plus léger et au plus réaliste, pas forcément en voxels ; l'eau est une quantité prélevable qui réagit (gravité, collisions) | Monsieur |
| D25 | 2026-10-08 | Personnages en style voxel (maillage à facettes, cubes de 1,8 à 2,2 cm, avec des angles), pas en voxels stricts | Monsieur |
| D26 | 2026-10-08 | Frontières : aucune limite visible, jamais d'évanouissement ni de retour au village ; la difficulté tue avant le bord. Monde physique de 50 km au total : **remplacé par D27** (20 × 20 km). Remplace le « sauvetage narratif » de P9 | Monsieur |
| D27 | 2026-10-08 | **`CHARTE_DU_JEU.md` (racine) est la charte fonctionnelle et de design ; elle prime sur tout ce qui précède.** Elle fixe notamment : monde physique d'environ 20 × 20 km (§ 2) ; variables psychologiques de −10 à +10 (§ 6) ; traits qui évoluent progressivement (§ 6) ; le Transformer modifie état, souvenirs, perceptions, émotions, relations et objectifs puis choisit une action ou une séquence d'actions (§ 8) ; profondeur de simulation variable selon les PNJ, sans règle qui interdise un rôle (§ 24) ; vie d'un PNJ d'environ 150 h de jeu (§ 25) | Monsieur |
| D28 | 2026-10-09 | **Trois couches jamais mélangées** : gestes physiques paramétrés par la manière (une claque, un coup de poing, un passage à tabac, des coups mortels = un seul geste) ; parole = un geste dont le contenu est une expression de la langue intérieure composée par le Transformer (faire chanter, menacer, promettre ne sont pas des actions) ; interprétations (vol, trahison, meurtre) = jugements des témoins sur des faits objectifs, jamais des options. Le catalogue vient des premiers principes ; les histoires ne sont que des sondes ou des rails légers. Tout doit rester gérable par l'IA (vue compacte et factorisée). Source unique : `catalogue/` | Monsieur |
| D29 | 2026-10-09 | Faune et phénomènes magiques : catalogués, pilotés par des lois simples du moteur, pas par un Transformer | Monsieur |
| D30 | 2026-10-09 | Calendrier : 1 jour = 1 h 30 réelle (jour 1 h, nuit 30 min) ; 1 an = 7 h réelles (≈ 4 jours ⅔, saison 1 h 45 ; Monsieur a d'abord dit 20 h puis corrigé : « sinon cela va être dur »). Avec une vie d'environ 150 h (charte § 25), une vie ≈ 21 années de calendrier ; le vieillissement suit une horloge de vie séparée (enfance ≈ 15 h, adolescence ≈ 6 h, adulte ≈ 105 h, vieillesse ≈ 24 h). Remplace P25 | Monsieur |
| D31 | 2026-10-09 | Le moteur social est écrit en C++20 dans `engine/`, à côté du monde ; ses énumérations, structures et bornes du gouverneur sont générées depuis `catalogue/` (une seule source de vérité). Python reste pour les outils, les références (`sim/`, `ai/npc_pipeline`) et l'entraînement (PyTorch) | Monsieur |

## Proposé (à valider par Monsieur)

| N° | Proposition | Où c'est détaillé |
|---|---|---|
| P1 | Carte de 20 × 20 km par défaut (acceptée, D13) | architecture § 2.1 |
| P2 | Godot 4 comme hôte, cœur C++20 indépendant du moteur, Jolt | architecture § 12 |
| P3 | Chunks 64³ en briques 8³, micro-briques de rendu 4³ | architecture § 3.1 |
| P4 | VoxelId 16 bits = classe de matière 9 bits + teinte 7 bits | architecture § 3.2 |
| P5 | Bus d'opérations unique pour monde, perception, mémoire, sauvegarde, chronique | architecture § 4 |
| P6 | Contrat décision / action des devs ; deux décideurs (référence Utility+HTN, élève Transformer) | architecture § 8.2 |
| P7 | Décision identique à tous les paliers ; seule l'exécution change | architecture § 8.3 |
| P8 | Un village par frontière + un bourg central, économies complémentaires | architecture § 2.3 |
| P9 | Marches de 3 km (5 km côté montagne) dans la carte, hostilité H = 2^(d/300 m), valable aussi sous terre ; sauvetage narratif ; au-delà comme croyance sociale | architecture § 2.2 |
| P10 | Inférence entière sur GPU dédié via compute Vulkan | architecture § 9.3 |
| P11 | Boucle d'entraînement avec le simulateur sans rendu (DAgger) | architecture § 9.2 |
| P12 | Code Python des devs conservé comme oracle des tests du portage C++ | architecture § 12 |
| P13 | Machine de référence : Iris Xe, 16 Go de RAM, 30 images/s en 720p interne vers 1080p | architecture § 13 |
| P14 | (caduque, D27) Échelle de temps : 1 jour de jeu = 4 h réelles (×6) | architecture § 2.4 |
| P15 | Résumé de région en cellules de 64 m lu par la société | architecture § 2.5 |
| P16 | (acceptée, D13) Orientation des frontières : mer à l'ouest, montagne au nord, désert à l'est, forêt au sud, tirée de la seed ; cohérente avec un vent dominant venu de la mer | architecture § 2.2 |
| P17 | Génération du monde en entiers et virgule fixe Q16 seulement (bruit, érosion, plan, chunks), plutôt qu'en flottants stricts ; empreintes de référence épinglées dans les tests | `engine/README.md` ; empreinte identique sur 12 compilations gcc/clang le 8 oct. [Mesuré] |
| P18 | Profil des colonnes de terrain échantillonné toutes les 8 cm et interpolé ; granit à 40 m sous la surface ; l'eau hors des voxels | `engine/README.md` ; chunk de surface 0,42 ms en moyenne [Mesuré, conteneur] |
| P19 | Table des matières en données (`engine/data/materials.csv`), numéros de classe figés, cible du convertisseur | `engine/data/materials.csv` |
| P20 | Le professeur lit une vue en entiers (−10..+10 ou 0..10, zéros omis) ; l'élève lit les mêmes entiers divisés par 10 | `ai/npc_pipeline/representation.py`, `generate_states.py` 0.4 |
| P21 | Un décideur à utilités lisibles (`reference_decider.py`, ref-0.4) donne les étiquettes gratuites de départ et sert de repli ; l'élève doit le battre grâce au professeur et à la simulation | paires minimales : référence 98,6 % sur 1 000 paires [Mesuré] |
| P22 | Format de jetons `tok-1` (64 jetons, 16 options, pointeurs entre jetons) ; `encode.py` est l'oracle du futur encodeur C++ | `ai/npc_pipeline/encode.py`, `token_layout.json` |
| P23 | Générateur 0.4 : couche village (5 villages, problème commun, frontières, commerce), foyer, contenu des souvenirs, garde-robe et `dress(outfit)` en fin de contrat | `ai/CONTRAT_PNJ.md` ; `docs/npc/audit/report_v04.md` |
| P24 | Élève `small` (5,3 M paramètres) par défaut pour la RTX de Monsieur ; `tiny` (0,8 M) en repli | `ai/student/ENTRAINEMENT.md` |

| P25 | (remplacée par D30) Calendrier compressé : 1 jour ≈ 18 min réelles, 1 an = 8 jours (2 par saison), âge apparent compressé (enfance ×2, adolescence ×1,33, vieillesse ×1,5) : une vie ≈ 150 h (charte § 25) | `catalogue/data/world.toml` |
| P26 | Bornes d'écriture du Transformer : par décision (`step`), par jour de jeu (`rate`), par année vécue pour les traits (1), valeurs (0,5), tempérament (0,3) ; l'ancienne borne « 0,1 par jour » est caduque ; au plus 4 écritures par décision | `catalogue/README.md`, revue du 9 oct. |
| P27 | Esprit stable en 33 dimensions (32 vues par l'IA) : 18 traits HEXACO, 5 aptitudes, 2 de tempérament, 8 valeurs, attirance, goûts singuliers (attitudes envers un concept) ; les normes précises sont des croyances | `catalogue/data/mind_static.toml` |
| P28 | Les objets sont des assemblages de parties (forme × matière) ; les 421 types sont un savoir commun, jamais une limite | `catalogue/data/forms.toml`, `items_*.toml` |
| P29 | Les jetons ne contiennent aucune vérité : dossiers mentaux, événements remémorés, lieux reconnus, accords tels que crus | règle `no_truth_in_tokens`, `catalogue/data/hard_rules.toml` |

## Ouvert

| N° | Question | Défaut en attendant |
|---|---|---|
| O1 | ~~Confirmer 20 × 20 km ?~~ tranché par D13 | — |
| O2 | ~~Langue du joueur~~ tranché par D14 | — |
| O3 | ~~Romance entre adultes apparentés et Steam~~ fermée le 8 oct. : D11 conservée, risque faible (la règle Steam de juillet 2025 vise le contenu sexuel explicite ; rien de sexuel ni montré, rien sur la page du magasin), norme de tabou forte par défaut, interrupteur prêt. Détail : fil « Règles Steam sur la romance » | — |
| O4 | Hébergement du code (dépôt GitHub privé) pour travailler avec Claude Code | Monsieur le crée (annoncé le 8 oct.) |
| O5 | Licence des modèles du kit médiéval utilisé pour tester le convertisseur | ne rien distribuer avant vérification |
| O6 | ~~Clé Gemini exposée~~ révoquée, voir D16 | — |
| O7 | Déclaration Steam du contenu IA « live-generated » (verbaliseur LLM local) et description des garde-fous contre le contenu illégal ; aucun contenu sexuel adulte généré en direct | à rédiger avant la sortie ; les règles dures I6 et I7 en sont la base |
| O8 | ~~Monde de 50 km~~ tranché par D27 : 20 × 20 km | — |
| O9 | Taille des voxels du monde. Essai du prototype village (9 oct., `prototypes/village-web/RENDU.md`) : à 2 cm la maille devient du bruit au-delà de dix mètres ; il est passé à 10 cm. Résultat d'essai, pas décision : la charte dit « quelques cm » | 5 cm proposé, 10 cm essayé ; à trancher par Monsieur |
| O10 | Fréquence du Transformer par PNJ | 2 à 4 appels par seconde |
| O11 | ~~Échelle de temps~~ tranché par D27 : vie d'environ 150 h de jeu, soit environ 2 h par année ; P14 (1 jour = 4 h) caduque | — |
| O12 | ~~Traits figés ou non~~ tranché par D27 : ils évoluent progressivement | — |
| O13 | Enseignant bon marché : quel modèle, quel budget | Gemini Flash-Lite, rien lancé sans accord |
| O15 | ~~Durée du jour et calendrier~~ tranché par D30 | — |
| O14 | Textures bitmap sur les voxels. Monsieur les a demandées (D20) ; l'essai du prototype village (9 oct., `prototypes/village-web/RENDU.md`) s'en passe : grain procédural, biseau des arêtes, éclairage PRT et grille de ciel, sur le modèle de Teardown (affirmation du fil, non vérifiée ici) | textures maintenues tant que Monsieur n'a pas tranché ; comparer les deux sur captures |
