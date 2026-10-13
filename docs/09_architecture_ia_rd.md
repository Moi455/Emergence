# R&D : un cerveau de PNJ capable de complots et d'expéditions (13 oct. 2026)

Statut : **proposition**, rien n'est décidé. Ce document prolonge `docs/07_conception_ia.md` (§ 8 dit où il le confirme et où il le corrige).
**[Mesuré]** = sur la machine de Monsieur (Quadro RTX 3000 6 Go, Turing, 30 SM, 80 W ; PyTorch 2.14, CUDA 13). Scripts et résultats bruts : `ai/research/arch/` ; `python3 ai/research/arch/summarize.py` réimprime les tableaux depuis `results/*.json`. **[Estimé]** sinon, avec sa source. **[Hypothèse]** = idée non mesurée.
Les bancs de coût utilisent des poids aléatoires, à la taille exacte de l'interface tok-2 (révision 12). Les deux sondes (§ 5) entraînent de vrais petits modèles. Un glossaire est à la fin.

## 1. La réponse

1. **Oui, 200 décisions/s tiennent.** Le cerveau recommandé, en `base` (17 M paramètres), prend 17,5 ms par pas de 100 ms, soit **≈ 17 % de la Quadro** [Mesuré, médiane de 3 passages ; 13 à 29 ms selon les passages]. En `small` (6,5 M), 13,5 ms. Sur une RTX 3060 mobile, c'est le même ordre de grandeur (§ 2) ; un moteur d'inférence fusionné devrait descendre vers 10 % [Estimé].
2. **Le levier de l'intelligence : superviser les étapes intermédiaires du raisonnement, puis les faire écrire.** La sonde de coalition (§ 5.2) le mesure : trois villageois lésés doivent deviner qui sait, se proposer un lieu et une heure, et s'y retrouver.
   - 0,9 M paramètres, une passe, sans supervision intermédiaire : **71 %** de réussite.
   - Deux fois plus de couches : 73 % (80 % en entraînant deux fois plus longtemps). Couches bouclées (style TRM) : 70 %.
   - La même passe avec une tête de théorie de l'esprit (ToM) supervisée sur « qui sait, depuis quand » : **97 %**.
   - Ces étapes écrites dans les dossiers, la **« pensée écrite »** : **99,9 %**, pour 19 % de décisions en plus.
   - Mais avec une trace de professeur fausse une fois sur cinq : **76 %**.
3. **La pensée écrite.** Penser, c'est une suite de décisions courtes en mode `reflect` (le jeton WAKE le prévoit déjà).
   - Chaque décision écrit **un** dossier : une croyance, un jugement, un objectif, une étape de plan, une offre à faire, une croyance sur autrui (« Jacques viendra »).
   - Le pas suivant relit ce dossier.
   - Le modèle choisit de continuer ou de s'arrêter ; l'ordonnanceur fixe le budget.
   - Elle est visible, gouvernée, sauvegardée, et elle tient sur des heures de jeu.
   - Elle exige que le professeur écrive des traces cohérentes avec ses actions.
4. **Le reste du cerveau est celui de docs/07** : un seul Transformer d'ensembles partagé, qui lit les dossiers reliés par pointeurs. Trois ajouts : une **tête ToM** sur chaque personne (que sait-il ? que fera-t-il ?) ; un **critique de plans** (8 plans candidats notés en 0,3 ms) ; un **sélecteur de contexte appris**, c'est-à-dire un rappel des bons souvenirs. La qualité de ce sélecteur n'est pas encore mesurée [Hypothèse].
5. **Pas de mémoire latente récurrente.** Avec la recette essayée (BPTT sur 8 décisions, 2 500 pas), 8 jetons de mémoire n'apportent rien (73,0 % avec, 72,8 % sans), et font moins bien que 8 événements de plus (85 %). Un rappel parfait des bons dossiers donne 99,9 %. **Apprendre en jeu, c'est donc écrire et retrouver des dossiers** : sûr, lisible, sauvegardé, gouverné. Aucun poids ne bouge pendant la partie. [Mesuré, § 5.1]
6. **Deux vitesses, un seul jeu de poids.** Le réflexe tient en une passe sur un paquet de 64 jetons ; la délibération enchaîne N passes `reflect` sur 128 jetons. Sur la sonde, un modèle deux fois plus profond apporte peu (73 à 80 %) : O18 se tranche par « mêmes poids, plus de pas ».
7. **Écartés, mesures à l'appui** :
   - un petit LLM dans la boucle : au moins 36 à 176 % du GPU ;
   - le mélange d'experts, sous la forme permise par nos contraintes : 2 à 5 fois plus lent par couche ;
   - la récurrence latente en profondeur : aucun gain ;
   - l'apprentissage des poids en jeu ;
   - ONNX Runtime sur le graphe exporté tel quel : 1,7 à 1,9 fois plus lent que PyTorch.
8. **Ce qui manque pour le complot et l'expédition, ce n'est pas le calcul.** Ce sont les données (le professeur doit écrire des traces de réflexion) et une quinzaine de primitives du catalogue (§ 7) : heure du jour, rendez-vous, accords à plusieurs, groupe « nous trois » avec ses membres et son chef, parts et durées, « continuer à réfléchir ».

## 2. De la Quadro à la RTX 3060 mobile

| | Quadro RTX 3000 (mesures) | RTX 3060 Laptop (cible) |
|---|---|---|
| Puce | TU106, 30 SM, 3 Mo de L2 [Mesuré] | GA106 complet, 30 SM, 3 Mo de L2 [Estimé, fiches] |
| Mémoire | 6 Go, 192 bits, 336 Go/s | 6 Go, 192 bits, 336 Go/s |
| Puissance, fréquence | 80 W ; ≈ 1,0 GHz sous GEMM lourde (855 à 1 080 MHz) [Mesuré] | 60 à 115 W ; 1,3 à 1,7 GHz annoncés [Estimé, fiches] |
| GEMM FP16, accumulation FP32 | 23 à 25 TFLOP/s ; l'accumulation FP16 ne donne que +3 à +16 % : plein débit, carte pro [Mesuré] | demi-débit sur GeForce : ≈ 22 TFLOP/s crête [Estimé, livre blanc Ampere] |

**Extrapolation.** Nos lots tournent loin de la crête : `small` ≈ 6 TFLOP/s [Estimé : FLOPs analytiques de docs/07 / temps mesuré]. SM, bande passante et L2 sont identiques. Mais la fréquence et les cœurs tensoriels diffèrent, dans les deux sens, et nous n'avons pas de profil qui prouve où est le goulot. **Même ordre de grandeur, à confirmer sur une vraie 3060** (question 8). Le « 17 % » ne compte que le GPU : la mise en jetons, le gouverneur et les copies sont sur le processeur.

## 3. Comment naissent les deux comportements

**« Pierre, Jacques et Jean partent dans la forêt pour tuer George, car il a trompé leurs femmes. »**
Les paroles sont écrites dans la langue intérieure du catalogue (`offer` = proposer ; `did us strike @George` = « nous frappons George »). ✗ = primitive manquante (§ 7).

| # | Qui, quand | Mode | Ce qu'il lit | Ce qu'il écrit ou fait |
|---|---|---|---|---|
| 1 | Pierre entend Marthe (deux adultes) | `listen` | HEARD : George a eu un geste intime avec Marie ; Marie est son épouse | croyance `qualifies … adultery` ; colère (saut) ; rancune envers George (pas borné) |
| 2 | aussitôt (urgence) | `reflect` | ses traits (vindicatif, audacieux), sa rancune | objectif `achieve (dead @George)` |
| 3 | | `reflect` | rumeur : Jacques et Jean aussi ; qui a parlé à qui | croyance sur autrui `believes @Jacques (that b:adultère)` |
| 4 | | `reflect` + tête ToM | Jacques : rancune crue, confiance | croyance « Jacques viendra » (certitude 7) ; « Paul non » (ami de George) |
| 5 | | `reflect` + critique | 4 plans : seul et tout de suite / dénoncer au chef / à trois, en forêt, à l'aube / attendre | plan : recruter Jacques et Jean, forêt, ✗ aube de demain |
| 6 | | `act` | plan, étape suivante | `go` vers Jacques |
| 7 | devant Jacques, seul | `act` | Jacques présent | `speak` à voix basse : `(offer (future (and (did ✗us3 strike @George) (at ✗us3 @forêt ✗aube))))` |
| 8 | Jacques ; puis Jean | `listen` puis `act` | l'offre, sa propre rancune, sa confiance en Pierre | accepte : `COMMIT` ✗ à trois |
| 9 | à l'aube | réveil sur échéance | COMMIT, plan | prendre la hache ; `go` en forêt, discrètement |
| 10 | dans la forêt | `act` | les deux autres là ; George arrive | `strike` jusqu'à ce que la cible soit à terre |

**Règle dure.** À l'étape 1, l'acte intime est dit entre adultes. Si un auditeur peut être mineur, le gouverneur refuse cette parole (D10, P30). Un test de refus de ce cas est à ajouter.

**Volume.** Pierre prend environ 12 décisions, dont 5 de réflexion ; Jacques et Jean environ 8 chacun, sur une journée de jeu (1 h 30 réelle) [Estimé]. À 0,4 décision/s, chaque PNJ en a plus de 2 000 par jour : **le débit n'est pas le problème**. Ce qui compte : une réflexion qui enchaîne croyance → jugement → objectif → plan ; une ToM qui choisit les bons complices ; un accord tenu dans des dossiers (COMMIT, PLAN) que l'échéance réveille ; un gouverneur qui borne chaque écriture.

**« Le maire organise une expédition pour trouver de l'or. »** Même mécanique, plus longue :
1. Il entend parler d'une légende (`exists gold @L26`).
2. Réflexion : un objectif lié à son rôle (`holds chief`), avant l'hiver ; un sous-objectif, apprendre la route.
3. ToM : qui viendra ? qui le croit en droit de commander (`may`) ?
4. Critique : choisir entre trois plans.
5. Annonce sur la place : une demande et une offre de ✗ part du butin.
6. Chacun accepte ou refuse selon ses croyances ; le groupe ✗ « l'expédition » naît, et le maire le mène (`leads`).
7. Provisions ✗ pour 10 jours ; départ ✗ dans 3 jours, à l'aube ; marche derrière lui (`go … along`) ; fouille, retour, partage.

Le maire prend 30 à 60 décisions sur plusieurs jours [Estimé]. Son plan survit à des centaines d'autres décisions parce qu'il est **écrit** (GOAL, PLAN, COMMIT), retrouvé par le sélecteur, et réveillé par l'échéance.

## 4. Panorama critique (court)

| Famille | Coût et effet mesurés | Verdict |
|---|---|---|
| Transformer d'ensembles à pointeurs (un réseau de graphe sur le graphe cru) | § 6.2 ; 100 % de fausses croyances en contexte | **cœur retenu** |
| **Pensée écrite** (chaîne de pensée écrite dans les dossiers, calcul adaptatif) | un pas = une décision ; 99,9 % | **retenue** ; exige des traces cohérentes |
| Tête de théorie de l'esprit (ToMnet), supervisée | une tête ; 71 → 88 %, 97 % avec « depuis quand » | **retenue** |
| Critique de plans (« imagination légère ») | 0,3 ms pour 8 PNJ × 8 plans ; effet non mesuré | **retenu** en mode `reflect` |
| Modèle du monde latent (Dreamer, MuZero) | 3 ms pour 64 déroulés de 5 pas | **plus tard** : la ToM et la politique prédisent déjà le monde social |
| Récurrence en profondeur (Universal Transformer, TRM, HRM, Coconut) | même temps que 8 couches ; 70 % | **non sous cette forme** (TRM et HRM supervisent chaque boucle : à réessayer) |
| Mémoire latente par PNJ (RMT, poids rapides, Titans) | +20 % ; inutilisée (73 % avec ou sans) | **non pour l'instant** |
| RNN, GRU ; modèles d'état (Mamba-2, RWKV-7, Gated DeltaNet, xLSTM) | GRU : 33 % | **non** : nos entrées sont un ensemble de dossiers, pas une suite |
| Mélange d'experts (MoE) | formes permises par le déterminisme : ×2,1 à ×5,3 par couche | **pas maintenant** : on manque de données, pas de paramètres. Un MoE sans abandon à formes fixes demanderait des noyaux maison (non testé) |
| Sortie précoce, profondeur adaptative | un lot de taille fixe paie toutes les couches | **oui, mais par décision** : c'est le budget de réflexion |
| FiLM ou hyper-réseau de personnalité, précalculé chaque jour | +5 à +7 % ; effet sur l'individualité non mesuré | **à essayer**, sous réserve d'O21 |
| LoRA par PNJ, appris en jeu | +17 % ; un pas d'apprentissage coûte 2 à 4 décisions | **non en version 1** : dérive, aucun test possible |
| Petit LLM dans la boucle (85 à 106 M) | au moins 36 à 176 % du GPU | **hors boucle** : professeur, juge, traducteur de la parole du joueur (charte § 15) |
| GNN sur le vrai graphe social | — | **interdit** : il lirait la vérité |
| Règles, GOAP, HTN | — | **interdits comme décideurs** (D17) ; permis pour exécuter un geste, amorcer, tester |
| PPO, multi-agents (CTDE), imitation, DAgger, auto-supervisé | entraînement | **retenus pour l'entraînement** (§ 6.3) |
| SNN, réservoirs, réseaux liquides, GAN, diffusion, évolutionnaire, logique floue | — | **non** : immatures sur GPU, itératifs, ou faits de règles écrites |
| Architectures cognitives (ACT-R, SOAR) | — | **cadre** : 128 jetons = mémoire de travail ; souvenirs = épisodique ; croyances = sémantique ; pensée écrite = délibération |

## 5. Les sondes d'intelligence [Mesuré]

Deux graines par modèle (une pour les contrôles marqués 1 g.) : les fourchettes sont l'écart entre graines, pas des intervalles de confiance.

### 5.1 Fausse croyance et mémoire longue (`probe_belief.py`)

**La tâche.** Un observateur regarde 5 personnes déplacer 4 objets entre 5 lieux, aller et venir, sur 64 événements. Tous les 8 événements, une question : « où X croit-il que se trouve tel objet ? ». La moitié sont de fausses croyances. Les identités sont des poignées stables ; les emplacements sont remélangés à chaque décision.
Le modèle : d = 128, 4 couches, 0,9 M paramètres, 32 jetons par décision. Entraînement : 2 500 pas de 512 épisodes. Évaluation : 131 072 questions tenues à part. Hasard : 20 % ; « répondre où est l'objet » : 51 %.

| Modèle (jetons d'événements par décision) | Tout | Fausses croyances | dont décisif ≥ 16 événements avant |
|---|---|---|---|
| 8 derniers événements, sans mémoire (1 g.) | 72,8 % | 50,3 % | 26,3 % |
| 8 derniers + 8 jetons de mémoire récurrente | 73,0 % | 51,1 % | 27,4 % |
| idem + mémoire à poids rapides 64 × 64 | 73,0 % | 51,0 % | 27,4 % |
| 16 derniers événements (docs/07) | 84,6 % | 73,2 % | 56,6 % |
| **16 événements choisis par un rappel parfait** (oracle) | **99,9 %** | **99,9 %** | **99,9 %** |
| GRU sur le flux (2,6 M) | 33,2 % | 31,2 % | 24,4 % |
| les 64 événements (2,7 fois le calcul, 1 g.) | 96,4 % | 94,3 % | 89,7 % |

**Ce qu'on en tire.**
- Le Transformer à pointeurs apprend parfaitement la fausse croyance quand l'information est dans son contexte : 100 % à moins de 16 événements.
- **La mémoire récurrente est restée inutilisée** : avec ou sans elle, 73 %. À jetons égaux, elle perd contre une fenêtre plus large (73 % contre 85 %). Avec cette recette (BPTT sur 8 décisions, 2 500 pas), elle n'apprend pas à s'en servir ; une autre (curriculum, plus de pas) pourrait faire mieux.
- **Tout se joue sur ce qu'on lui montre.** L'oracle de rappel fixe le plafond ; un sélecteur appris ne l'atteindra pas tout à fait.

### 5.2 Coalition : se concerter et se retrouver (`probe_coalition.py`)

**La tâche.** 5 villageois et George. George a trompé 3 d'entre eux. Un témoin l'a vu, et l'information passe par 10 conversations : on sait qui a parlé à qui et quand, pas ce qui s'est dit. Il y a 0 à 4 relais.
- La coalition, ce sont les lésés qui savent. Son plus audacieux propose à chacun « au lieu et à l'heure de George », un par heure. Chacun accepte, puis tous s'y rendent.
- Il ne faut inviter personne d'autre, et ne rien faire s'il n'y a pas de coalition (20 % des épisodes).
- **Simplification** : chaque villageois a vu toutes les conversations, le témoin et l'audace de chacun. Rien d'inobservable n'entre dans ses jetons, mais dans le jeu un PNJ ne connaîtrait que les conversations qu'il a vues ou dont on lui a parlé.
- Le professeur exact réussit à 100 % dans la même boucle fermée (`teacher_closed_loop`).

L'élève est entraîné par imitation, 3 000 pas. Puis il **joue seul les 5 villageois en boucle fermée**, sur 4 096 épisodes tenus à part, avec ses propres réflexions, propositions et acceptations. 31 jetons, d = 128.

| Modèle | Paramètres | Calcul par décision | Décisions par villageois | Succès | Invitations exactes | Secret trahi |
|---|---|---|---|---|---|---|
| une passe, 4 couches | 0,91 M | 51 MFLOP | 24 | 71,3 % | 73,1 % | 26,4 % |
| une passe, 8 couches | 1,70 M | 101 MFLOP | 24 | 73,2 % | 75,6 % | 24,9 % |
| une passe, 8 couches, entraînée 2 fois plus (1 g.) | 1,70 M | 101 MFLOP | 24 | 79,6 % | 82,5 % | 18,7 % |
| 2 couches bouclées 4 fois (TRM, Universal Transformer) | 0,51 M | 101 MFLOP | 24 | 70,4 % | 71,2 % | 26,8 % |
| 4 couches + tête ToM (qui sait ? qui en est ?) | 0,91 M | 51 MFLOP | 24 | 88,1 % | 88,9 % | 10,8 % |
| 4 couches + tête ToM avec la même supervision que la pensée écrite (qui sait, depuis quand), une passe | 0,91 M | 51 MFLOP | 24 | 97,4 % (96,7-98,1) | 98,1 % | 2,5 % |
| **4 couches + pensée écrite** (≤ 5 pas, arrêt choisi par le modèle) | 0,91 M | 51 MFLOP | **28,5** | **99,9 %** | **100 %** | **0,1 %** |
| pensée écrite, trace du professeur fausse 1 fois sur 5 | 0,91 M | 51 MFLOP | 28,5 | 75,9 % (71,8-80,1) | 67,3 % | 23,8 % |

**Ce que la sonde prouve.**
- Un petit Transformer à pointeurs apprend une coordination à trois, propositions et rendez-vous compris, et la rejoue seul.
- **Ce qui compte d'abord, c'est de superviser les états intermédiaires** (qui sait, depuis quand). En une passe, une tête ToM ainsi supervisée atteint déjà 97 %.
- **Les écrire dans les dossiers** ajoute 2,5 points et fait tomber les invitations indiscrètes de 2,5 % à 0,1 %, pour 19 % de décisions en plus.
- Doubler la profondeur, entraîner deux fois plus longtemps ou boucler les couches ne compense pas : 73 %, 80 %, 70 %.
- **La cohérence de la trace est décisive.** Avec 20 % de pensées fausses mais des actions justes, l'élève tombe à 76 %, alors même que ses propres réflexions en boucle fermée sont exactes. Mon interprétation [Hypothèse] : il a appris à ne pas se fier à ce qu'il pense.

**Ce qu'elle ne prouve pas.**
- Le monde est synthétique et petit, et tout le monde y voit toutes les conversations.
- La trace de réflexion suit un format fixé par un professeur exact. Celle d'un LLM sera plus bruitée (voir la ligne à 76 %), et le PNJ devra apprendre **quoi** penser, pas seulement **comment**.
- L'avantage d'écrire plutôt que de superviser une tête est faible ici (2,5 points), avec des chaînes de 4 relais au plus. Qu'il grandisse avec des chaînes plus longues que la profondeur du modèle reste une [Hypothèse].
- La récurrence latente est testée sans supervision par boucle, contrairement à TRM et HRM.
- Rien ne mesure la plausibilité sociale, ni les 128 jetons hétérogènes du vrai tok-2.

## 6. Recommandation

### 6.1 L'architecture : « pensée écrite à deux vitesses »

```
 esprit du PNJ (dossiers) ─► sélecteur appris (rappel ; passe A sur 48 jetons) ─► jetons tok-2 (paquet 64 ou 128)
                                         │
                Transformer d'ensembles à pointeurs : un seul encodeur partagé, `base` 17 M
           ┌─────────────────────────────┼──────────────────────────────┐
     mode act/listen (réflexe)      mode reflect (délibération)       têtes du même modèle :
     1 passe, 64 jetons :           N passes, 128 jetons ; chaque      ToM sur chaque personne,
     geste, pointeurs, manière,     pas écrit UN dossier ; le modèle   valeur, critique de 8 plans,
     ≤ 4 écritures                  choisit « encore » ou « stop »     décodeur de parole (20 pas)
           └──────────► gouverneur (bornes, D10, P30) ─► Operation
```

**Un seul modèle (D32).** Le sélecteur, la tête ToM, le critique et le décodeur de parole sont des **têtes du même modèle**, entraînées ensemble sur le même encodeur ; le banc les mesure comme petits réseaux séparés de même taille. Si Monsieur entend « un seul modèle » plus strictement, c'est la question 1.

**Qui décide quoi (D17).** L'ordonnanceur décide **quand** et **combien au plus** : il donne un budget de réflexion sur événement (fort changement émotionnel, offre reçue, plan bloqué, nuit), comme les réveils de docs/07 § 3.2. Le modèle décide **quoi** : ce qu'il écrit, et s'il continue. Les « scénarios semés » de § 6.3 sont des données d'entraînement, jamais des rails en jeu.
La **profondeur de simulation** de la charte (§ 24, O20) devient naturellement **le budget de réflexion d'un PNJ**, pas la taille de son modèle.

### 6.2 Coûts mesurés

| Pièce (lot, FP16, graphe CUDA) | `small` 6,5 M | `base` 17 M |
|---|---|---|
| Action, lot de 32, paquet 128 / **64** jetons | 7,2 / **3,6** ms | 13,8 / **6,5** ms |
| Réflexion, lot de 8, 128 jetons | 2,3 ms | 4,0 ms |
| Sélecteur (passe A, 48 jetons, lot de 32) | 1,7 ms | 1,7 ms |
| Parole (20 pas, automate, d 256, lot de 8) | 4,5 à 4,9 ms | 4,6 à 4,8 ms |
| Critique de plans (8 PNJ × 8 plans) | 0,2 ms | 0,3 ms |
| **Pas complet de 100 ms** (médiane de 3 passages ; plage) | **13,5 ms** (12,8 à 27,5) | **17,5 ms** (17,4 à 28,6) |

**Demande et capacité.** Ce pas offre 320 actions, 80 pas de réflexion et 80 paroles par seconde. Je propose que **les pas de réflexion comptent dans les 200 décisions/s de D32** : par exemple 150 actions et 50 réflexions, et la parole fait partie de la décision de parler. Le coût affiché est celui de la capacité : les lots sont de taille fixe, complétés à vide.

**Autres mesures.**
- Coût fixe de l'interface (plongements, graphe, têtes) : 41 % du temps en `small`, 30 % en `base`. C'est la première cible d'un noyau fusionné.
- 8 couches : 13,1 ms ; 2 couches bouclées 4 fois : 13,2 ms, pour 3,6 M paramètres d'encodeur au lieu de 14,2.
- FiLM de personnalité : +5 à +7 %.
- MoE, par couche (32 × 128 jetons) : FFN dense 0,43 ms ; un expert sur 4 calculé partout puis choisi, 2,27 ms ; un expert par PNJ, 0,89 ms.
- LLM de 85 à 106 M, une passe sans génération : 36 à 44 % du GPU à 128 jetons, 143 à 176 % à 512.
- ONNX Runtime : 1,7 à 1,9 fois plus lent que PyTorch sur le même graphe exporté, non fusionné ; gestes identiques à 100 %.
- Mémoire des processus : 318, 402 et 526 Mio (`small`, `base`, `large`, contexte CUDA compris).
- Déterminisme : un même PNJ donne les mêmes bits dans deux lots différents, en mode direct et en graphe CUDA. Un seul couple de lots a été testé (`state.json`).
- Variabilité : un passage sur trois a donné presque le double (pire cas en `base` : 28,6 ms, au premier passage). Un entraînement d'un autre agent occupait le GPU aux passages 2 et 3. Cause non élucidée : à refaire sur un GPU réservé.

### 6.3 La boucle d'apprentissage

1. **Le professeur écrit des traces de réflexion**, pas seulement des actions : la suite de dossiers croyance → jugement → objectif → plan → offre → croyance sur autrui, au format du catalogue. La sonde montre que cette supervision rend les comportements à étapes apprenables.
   **Ses actions doivent découler de ses propres pensées écrites**, même fausses. On lui demande donc la trace puis l'action dans la même réponse, et on rejette les réponses incohérentes. Une trace fausse une fois sur cinq, suivie d'actions justes, fait tomber la sonde à 76 %.
2. **Imitation** sur les situations de `ai/situations`, avec des **scénarios semés** (grief, rumeur, légende de l'or, rôle de chef) : ces comportements sont trop rares dans une simulation libre.
3. **Tâches auxiliaires gratuites** :
   - prédire le prochain geste perçu d'autrui (la tête ToM) et sa réponse à une offre ;
   - prédire sa propre perception suivante et l'issue de son geste ;
   - entraîner les clés du sélecteur par une perte contrastive.
4. **DAgger** par trajectoires sur le moteur C++. Un professeur « vue large », qui voit tout l'historique, apprend au sélecteur quoi rappeler.
5. **Préférences, puis renforcement léger** : PPO avec pénalité KL, et éventuellement un critique centralisé (question 6). Récompense : accords tenus, plausibilité jugée par le professeur.
6. **Programme** : jugement seul → offre à deux → coalition à trois → groupe avec chef → expédition de plusieurs jours.

Entraînement sur la Quadro en float16 avec mise à l'échelle des gradients : une passe de `base` sur 1 M de décisions prend environ 20 min [Estimé].

**Apprendre en jeu** : oui, par ce que le PNJ **écrit** (souvenirs, croyances, jugements, plans, accords) et **retrouve** (sélecteur), et par la consolidation de nuit en mode `reflect`. En version 1, aucun poids ne bouge en jeu : ni mémoire latente, ni LoRA, ni renforcement en ligne.

### 6.4 Le moteur d'inférence livré

1. Pour le développement et DAgger : PyTorch avec graphes CUDA.
2. **À mesurer d'abord : TensorRT-RTX.** C'est le moteur de NVIDIA pour le grand public : il prend en charge Turing et les cartes suivantes, compile sur la machine du joueur, et tient en une petite bibliothèque. Licence de redistribution à vérifier.
3. Sinon, **un petit moteur CUDA maison** : cuBLASLt plus environ 6 noyaux fusionnés (sac d'embeddings et FiLM, biais de graphe, attention à biais sur une séquence entière en mémoire partagée, normalisation, têtes, décodeur de parole). Parité avec l'oracle PyTorch sur 99,9 % des décisions. Vulkan ensuite, pour AMD (O19).
4. **Non** : libtorch (1 à 2 Go à livrer) ; ONNX Runtime sans opérateurs fusionnés.

### 6.5 Risques, et ce qu'il faut mesurer ensuite

1. **Traces du professeur** : un LLM écrit-il des réflexions cohérentes, avec des actions qui en découlent ? Pilote de 200 situations « grief » et « expédition » avant toute dépense de quota.
2. **Rumination** : bornée par le budget de l'ordonnanceur et une pénalité d'arrêt ; à mesurer en partie longue.
3. **Rareté** : sans scénarios semés, ces comportements manqueront aux données.
4. **Sélecteur appris** : mesurer sa qualité contre l'oracle de § 5.1.
5. **Part du GPU** : fusionner, puis mesurer sous un vrai rendu Vulkan, GPU réservé, 30 min ; mesurer aussi le coût processeur.
6. **Une vraie 3060 mobile**, à 60 W et à 115 W.
7. **Refaire les sondes** avec le vrai tok-2, des traces de LLM, une perception partielle et 500 PNJ.

## 7. Ce qui manque au catalogue et à la langue (pour l'étape 19)

Vérifié dans `catalogue/data/*.toml` et `catalogue/generated/model_interface.json`.

| Manque | Pour quoi | Ce qui existe déjà | Proposition |
|---|---|---|---|
| **Heure du jour** : aube, matin, midi, soir, nuit | « à l'aube » | `today`, `tomorrow`, `soon`, `future` ; `c_time` attend une heure ressentie, sans mot pour la dire | mots de temps `dawn`, `morning`, `noon`, `evening`, `night` |
| **Durées et décalages** : jour, heure, « dans 3 jours », « pendant 10 jours » | provisions, départ | quantités, `long_ago` | une unité de temps (`day`, `hour`) qui se combine avec une quantité |
| **Rendez-vous** : être à L **à** T, et non **avant** T | se retrouver | `COMMIT.deadline` et `GOAL.deadline` veulent dire « avant » | champ « quand » (à T), distinct de l'échéance |
| **Accord à plusieurs** | « nous trois », l'expédition | `a_parties` côté moteur ; dans le jeton, `COMMIT.counterparty` = une seule personne | contrepartie = groupe ou liste (≤ 4) dans le jeton COMMIT |
| **Former un groupe sur le moment** : qui est « nous » ? | « nous trois », « l'expédition » | `us` ; le moteur crée un référent quand quelqu'un nomme ou décrit un groupe (`s_introduced_by`) | règle de figement de `us` (le parleur, les destinataires, les personnes nommées) ; `(count us 3)` |
| **Ce que je crois d'un groupe** : membres, chef, but, mon rôle | conjurés, expédition | GROUP : relations seulement, 2 jetons au plus | GROUP : membres crus (≤ 4 pointeurs), chef cru, but (proposition), mon rôle ; 3 à 4 jetons |
| **Parts et fractions** : moitié, tiers, à parts égales | partage du butin | `all`, `few`, `one`, nombres | `half`, `third`, `share`, `equal` |
| **Accepter une offre précise** | plusieurs offres en cours | formule `yes` | `(accept that h:2)`, ou un pointeur de réponse |
| **Condition « tous là »** | attendre les complices | `c_sees_ref` vise une seule entité | `c_sees_ref` sur un groupe |
| **Continuer à réfléchir** | pensée écrite, calcul adaptatif | `WAKE.mode = reflect` | sortie « encore / stop » (condition `c_think_more`), et le budget dans WAKE |
| **Intention de dire** : l'offre préparée | préparer le recrutement | `GOAL (achieve (did me speak (to X) (says P)))`, au bord des 20 symboles et des 2 niveaux | un emplacement « parole prévue » dans PLAN |
| **Plan relisible** | réviser un plan long | PLAN ne montre que l'étape en cours et la suivante (`i_steps` reste au moteur) | étapes visibles (≤ 6 mots) |
| **Chef d'un groupe de circonstance** | légitimité, ordres | `leads`, `holds`, `may` ; rôles fixes (`chief`…) | `leads @G` suffit ; vérifier que `may` s'applique à un groupe de circonstance |
| **« Ensemble »** (avec qui, et non avec quoi) | tuer à trois | `with` = l'instrument ; `did us …` | rôle « avec » (`along REF`), ou s'en tenir à `us` |

Déjà là, rien à ajouter :
- les jugements `adultery`, `revenge`, `murder`, `betrayal`, `broken_promise` (un complice qui fait défaut) ;
- la demande de discrétion à un complice : `(request (not (future (did you speak (to anyone) …))))` ;
- les règles D10 et P30, tenues par le gouverneur.

## 8. Ce que ce document confirme ou corrige dans docs/07

1. **Budget.** docs/07 § 1 annonçait 4 à 7,5 % pour la politique seule. Mais docs/07 § 2.2 estimait déjà 15 à 20 % en `base` avec sélecteur, parole et réflexion : **la mesure (≈ 17 %) le confirme**.
2. **Boucle lente.** docs/07 § 3.1 lui donnait environ 10 % du budget. Ici, la réflexion devient le levier principal (jusqu'à un quart des décisions), sans second modèle : O18 se tranche par « mêmes poids, plus de pas ».
3. **État récurrent.** docs/07 § 4 le refusait parce qu'il est hors catalogue et invisible au professeur. La sonde ajoute un argument de performance, pour la recette essayée : la mémoire est restée inutilisée (73,0 % avec, 72,8 % sans). Mon brouillon du 12 oct. le recommandait : c'était une erreur.
4. **ONNX Runtime en phase 1** (docs/07 § 6) : 1,7 à 1,9 fois plus lent sur notre graphe exporté. Il ne vaut qu'avec des opérateurs fusionnés.
5. **Le format du professeur** (`ai/teacher`) demande des actions ; il faudra aussi des traces de réflexion. Je n'y ai pas touché.
6. **tok-2.**
   - Il faut lier chaque mot à sa colonne, sinon deux champs portant le même mot se confondent.
   - Les paquets de 64 et 128 jetons ne changent rien : la limite reste 128.
   - Les tables repliées sont un précalcul sur les poids, sans rapport avec O21.

## 9. Questions pour Monsieur

1. **Pensée écrite et « un seul modèle ».** Penser = une suite de décisions courtes qui écrivent des dossiers visibles, gouvernés et sauvegardés. Le modèle choisit de continuer, l'ordonnanceur fixe le budget. Sélecteur, ToM, critique et parole sont des têtes du même modèle. D'accord avec cette lecture de D32 ?
2. **Les réflexions comptent-elles dans les 200 décisions/s ?** Je propose oui, par exemple 150 actions et 50 réflexions.
3. **Profondeur de simulation** (charte § 24, O20) : la régler par le budget de réflexion d'un PNJ plutôt que par la taille de son modèle ?
4. **Professeur** : dépenser le quota Gemini sur des traces de réflexion, plus longues que de simples actions, après un pilote de 200 situations ? Et semer des scénarios (grief, or, chef) dans les données d'entraînement ?
5. **Part du GPU** : environ 17 % de la Quadro en PyTorch, objectif d'environ 10 % après fusion. Acceptable face au rendu ?
6. **Critique centralisé** : pendant l'entraînement seulement, un critique peut lire la vérité du monde ; jamais le PNJ en jeu. D'accord ?
7. **Étape 19** : ajouter au catalogue les primitives du § 7 ? Et le moteur livré : TensorRT-RTX (licence NVIDIA) ou moteur CUDA maison, Vulkan ensuite (O19) ?
8. **Une vraie RTX 3060 mobile** : une heure de mesure sur un portable de votre entourage ?

## Glossaire

| Mot | Sens |
|---|---|
| lot | plusieurs PNJ calculés ensemble sur le GPU (taille fixe : 32, ou 8) |
| paquet | nombre de jetons lus par décision (64 ou 128) ; on prend le plus petit qui suffit |
| graphe CUDA | un calcul enregistré une fois et rejoué, sans frais de lancement |
| tête | petite sortie spécialisée posée sur le même réseau (geste, ToM, critique…) |
| ToM | théorie de l'esprit : ce qu'un PNJ croit que les autres savent et feront |
| FiLM | réglage d'un réseau par deux vecteurs (échelle, décalage) propres à chaque PNJ |
| MoE | mélange d'experts : plusieurs sous-réseaux, un seul utilisé par jeton |
| TRM, HRM | petits réseaux qui bouclent sur eux-mêmes pour raisonner (2025) |
| DAgger | l'élève joue, le professeur corrige là où l'élève est allé |
| PPO, KL | renforcement prudent, qui reste près du modèle imité |
| BPTT | apprendre une mémoire en remontant le temps sur plusieurs décisions |
| automate de grammaire | masque qui n'autorise, à chaque pas de parole, que les mots grammaticaux |

## Reproduire

Dans `ai/research/arch/` :
- `bench_gemm_rate.py`, `bench_arch.py` (`--only tick3` pour le pas recommandé), `bench_fusion.py`, `bench_deliberation.py`, `check_state.py` ;
- `bench_ort.py`, dans le venv `~/.venvs/emergence-ort`, hors dépôt ;
- `probe_belief.py` (≈ 2 h 30) et `probe_coalition.py` (≈ 45 min ; contrôles : `--models tomsince4,reflect4noisy,direct8long`) ;
- `summarize.py` réimprime tous les tableaux.

## Sources

Graphormer (Ying 2021) · Set Transformer (Lee 2019) · Pointer Networks (Vinyals 2015) · AlphaStar (Vinyals 2019) · Chain of thought et problèmes séquentiels (Li 2024, arXiv:2402.12875) · Universal Transformers (Dehghani 2018) · ACT (Graves 2016) · PonderNet (Banino 2021) · Coconut (Hao 2024) · Recurrent depth (Geiping 2025) · HRM (Wang 2025, arXiv:2506.21734) · TRM (Jolicoeur-Martineau 2025, arXiv:2510.04871) · RMT (Bulatov 2022) · TTT (Sun 2024) · Titans (Behrouz 2025) · Gated DeltaNet (Yang 2025) · Mamba-2 (2024) · RWKV-7 (2025) · ToMnet (Rabinowitz 2018) · ToMi (Le 2019) · Generative Agents (Park 2023, 2024) · MuZero (2020) · DreamerV3 (2023) · Switch Transformer (2021) · FiLM (Perez 2018) · Punica, S-LoRA (2023) · MAPPO (2021) · DAgger (Ross 2011) · DPO (2023) · NVIDIA Ampere GA102 whitepaper · TensorRT-RTX 1.0 release notes.
