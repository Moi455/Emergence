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
| P14 | Échelle de temps : 1 jour de jeu = 4 h réelles (×6) | architecture § 2.4 |
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
