# Conception du cerveau des PNJ (R&D, 9 oct. 2026)

Statut : **proposition**, rien n'est décidé. **[Mesuré]** = sur la machine de Monsieur (Quadro RTX 3000 6 Go, Turing, PyTorch 2.14, CUDA 13) ; scripts et résultats bruts dans `ai/research/` (`results/*.json`). **[Estimé]** sinon. Les modèles mesurés ont des poids aléatoires : on mesure le coût, pas l'intelligence.

## 1. Verdict

1. **Un seul jeu de poids pour les 500 PNJ** : un Transformer d'ensembles de 6 à 16 M de paramètres, 128 jetons, pointeurs en biais d'attention, appelé par lots fixes de 20 à 64, en FP16.
2. 200 décisions/s ne coûtent presque rien : **4 % du GPU** en `small` (5,5 M), **7,5 %** en `base` (16 M), **13 %** en `large` (34 M) [Mesuré].
3. Les vrais goulots sont ailleurs : le coût de lancement (sans graphe CUDA, au moins 4 à 6 ms par appel), le partage avec le rendu (+5 ms au p95 sur l'image qui croise une décision) et surtout **les données**.
4. Autour du modèle, plusieurs boucles : un **ordonnanceur à événements** (qui pense quand, jamais quoi), un **sélecteur de contexte** appris, la **politique rapide**, un **décodeur de parole par cadres**, une **boucle lente de réflexion** et le **gouverneur**.
5. Pas de GNN sur le vrai graphe social, qui ferait lire la vérité. Le Transformer à biais de pointeurs est déjà un GNN sur le graphe que le PNJ *croit*.
6. La marge de calcul va à la **profondeur du modèle**, pas à la fréquence : on commence en `small` et on passe en `base` quand les données suffisent.

## 2. Budget de calcul

### 2.1 Politique rapide, FP16, 128 jetons, graphe CUDA [Mesuré]

| Modèle | Paramètres (calcul) | GFLOP/décision | B=1 | B=16 | B=64 | B=200 | B=500 | Débit max | GPU à 200/s |
|---|---|---|---|---|---|---|---|---|---|
| `xs` d128×4 | 1,1 M | 0,25 | 0,50 ms | 1,5 ms | 4,6 ms | 13 ms | 33 ms | 15 200/s | ≈ 2 % |
| `small` d256×6 | 5,5 M | 1,38 | 0,76 ms | 3,4 ms | 11 ms | 34 ms | 85 ms | 5 860/s | ≈ 4 % |
| `base` d384×8 | 16 M | 3,98 | 1,1 ms | 6,2 ms | 23 ms | 69 ms | 171 ms | 2 930/s | ≈ 7,5 % |
| `large` d512×10 | 34 M | 8,67 | 1,6 ms | 11 ms | 40 ms | 122 ms | 301 ms | 1 660/s | ≈ 13 % |
| `xl` d768×12 | 90 M | 23,0 | 2,6 ms | 23 ms | 89 ms | 270 ms | 683 ms | 740/s | ≈ 29 % |

Dernière colonne : 10 lots de 20 par seconde, interpolés entre les mesures à B=16 et B=64.

Autres mesures [Mesuré] :
- **Sans graphe CUDA**, `small` B=1 prend 4,9 ms au lieu de 0,76 ms. Il faut des formes statiques (emplacements fixes par type, lots de taille fixe).
- **FP32** est 3,2 fois plus lent (110 contre 34 ms, `small` B=200). **INT8** (`torch._int_mm`) est *plus lent* que FP16 sur nos formes : 11-12 TOP/s contre 19-22 TFLOP/s. On reste en FP16.
- **Mémoire du processus**, contexte CUDA compris : `small` 206 Mo (lots de 32) / 276 Mo (lots de 64) ; `base` 314 / 394 ; `large` 376 / 492. Les copies hôte ↔ GPU ajoutent 0,03 à 0,3 ms.
- **Avec un rendu simulé** (autre processus, 30 images/s, 12 ou 24 ms de GPU par image) : un pas de 20 décisions passe de 5,8 à 10-14 ms (p50). L'image qui croise une décision gagne 5 ms au p95 (17,9 contre 12,7 ms). Seul, le GPU baisse sa fréquence entre deux pas : d'où 5,8 ms au lieu de 3,4.
- **Décodeur autorégressif** de parole (2 couches, 16 symboles, masque de grammaire, boucle entière dans un graphe CUDA) : 4,7 ms pour 8 phrases, 9,8 ms pour 32.
- **GNN global** (500 nœuds, 20 à 150 liens, 2-3 couches) : 0,7 à 9 ms avec `index_add_`, mais **non reproductible bit à bit** ; notre version déterministe naïve prend 6 à 70 ms.
- **CPU** (i9-10885H, 4 threads, lots de 20) : `xs` fait 565 décisions/s ; `small` 151/s (183 en INT8 dynamique). Sans GPU, le repli est `xs`.

### 2.2 Conséquences [Estimé]

- Fusionner les noyaux (TensorRT ou moteur maison) gagnerait environ 1,5 à 2 fois : `small` plafonne à 8 TFLOP/s, la multiplication FP16 seule atteint 19-22.
- Le budget laisse la place à une passe de sélection (+12 %), à la parole (≈ 30 phrases/s) et à la réflexion (≈ 20/s) : sous 10 % du GPU en `small`, 15 à 20 % en `base`.

## 3. Architecture

### 3.1 Modules et boucles

```
 moteur (vérité) ─► [ordonnanceur] ─► [sélecteur] ─► [politique rapide] ─► [gouverneur] ─► Operation
                     qui pense          128 jetons     geste, pointeurs,       bornes,
                     maintenant         choisis        manière, ≤ 4 écritures   règles dures
                                                       si « parler » ─► [décodeur par cadres]
 sommeil, objectif fini, plan bloqué ─► [même modèle, mode « réfléchir »] ─► objectifs, plan, souvenirs
```

| Module | Appris ? | Quand | Coût |
|---|---|---|---|
| Ordonnanceur | non (moteur) | pas de 100 ms | négligeable |
| Sélecteur de contexte | score appris, candidats du moteur | chaque décision | ≈ 12 % d'une décision [Estimé] |
| Politique rapide | oui | 200/s en moyenne | § 2.1 |
| Décodeur par cadres | oui | geste « parler » (≈ 15 %) | ≈ 1 ms par lot [Estimé] |
| Boucle lente | oui, mêmes poids | ≈ 10 % du budget, davantage la nuit | une décision |
| Gouverneur | non (catalogue) | chaque sortie | négligeable |

**Un seul modèle** : mêmes poids pour tous les PNJ et pour trois modes marqués par un jeton : `agir`, `écouter` (juger ce qu'on vient d'entendre), `réfléchir`. En réserve : un second modèle partagé, plus profond, pour la réflexion seule (`large` à 20/s ≈ 1,5 % du GPU).

### 3.2 Qui pense quand

L'ordonnanceur choisit **quand** un PNJ pense, jamais **ce qu'il fait** : ce n'est pas un moteur de règles (D17). Cinq réveils, par priorité :

- **P0 danger** : arme tirée près de soi, coup, feu, cri.
- **P1 interpellé** : on lui parle, une demande arrive.
- **P2 fin de geste** : condition d'arrêt atteinte, échec, blocage (charte § 8).
- **P3 perception notable**, filtrée par `PLAN.commitment`, que le modèle écrit lui-même : le PNJ règle sa propre distraction.
- **P4 battement** : rien depuis 8 s éveillé, 60 s endormi.

À chaque pas de 100 ms, on sert 20 PNJ, du plus prioritaire au plus ancien. Un danger permet un pic à 64, pris sur une réserve (seau à jetons) : la moyenne reste à 200/s. Chaque geste porte sa **condition de réveil**, choisie par le modèle (cadre des « options » : Sutton, Precup, Singh, 1999). Un PNJ pense ainsi en moyenne toutes les 2,5 s, et aussitôt quand quelque chose le concerne.

Simulation (`sim_scheduler.py`, 45 min, charge inventée qui sature le budget, couteau dans une taverne : 40 PNJ, incendie : 100 PNJ) [Mesuré] :
- les 140 dangers et toutes les interpellations sont servis dans le pas même : moins de 100 ms d'attente, plus 5 à 15 ms d'inférence ;
- les fins de geste attendent 0,5 s au p95 (0,7 s au pire) ;
- ce sont les perceptions notables qui attendent : 2,7 s au p95, 26 s au pire ;
- chaque PNJ reçoit entre 0,32 et 0,48 décision/s.

### 3.3 Ce qui entre dans les 128 jetons

En deux étages, comme les *generative agents* (Park et al., 2023), mais appris :

1. **Le moteur rassemble les candidats**, sans juger : ce qui pointe vers les présents, l'objectif et le plan en cours, le sujet de la conversation, les événements récents. Au plus 64 croyances, 32 souvenirs et 24 personnes, tous à soi.
2. **Le modèle choisit.** Une passe A (2 couches, 48 jetons : soi, plan, objectifs, perception) produit une requête. Chaque candidat a une clé, recalculée quand l'enregistrement change. Le score combine requête × clé, l'âge, l'importance et la certitude. On garde les 12 croyances et les 9 souvenirs les mieux classés.

Pour l'entraîner, un modèle « large vue » hors jeu lit tous les candidats (≈ 300 jetons) ; le sélecteur apprend à reproduire sa décision avec 128 jetons.

**Précalcul permis, cache interdit.** Réutiliser une décision passée est interdit. Mémoriser une fonction pure de données inchangées (clé d'une croyance, plongement de la personnalité) ne l'est pas : le recalcul donnerait le même résultat, et chaque décision repasse par le modèle complet. On ne garde que les clés du sélecteur ; le reste ne ferait gagner qu'environ 5 % [Estimé].

### 3.4 Sorties

- **Geste** : 64 logits, masqués par la faisabilité venue du moteur.
- **Pointeurs** (cible, instrument) sur les jetons (Vinyals et al., 2015), **conditionnés au geste choisi** comme les têtes d'AlphaStar (Vinyals et al., 2019).
- **Manière** : 5 paramètres × 5 niveaux ; **réveil** : 16 conditions.
- **Écritures** : 4 emplacements (pointeur, variable, valeur en 21 niveaux) ; une tête de valeur pour le renforcement.
- **Tirage déterministe** : bruit de Gumbel tiré de Philox(graine du monde, PNJ, numéro de décision).
- **Parole par cadres.** Une expression est un prédicat à 3 arguments au plus, sur 2 niveaux au plus : on la décode en 3 tours au lieu de 16 pas (mode et prédicat ; arguments en parallèle selon leur type : pointeur, sorte, quantité ; proposition imbriquée). La profondeur étant bornée, la grammaire se compile en **automate fini** et le masque est une lecture de table sur le GPU (principe d'Outlines : Willard & Louf, 2023). Le décodeur à 16 pas mesuré sert de borne haute.

### 3.5 Le graphe social : GNN ou pas ?

Un GNN sur le graphe réel lirait les relations des autres entre eux, donc leurs variables internes. Il violerait `no_truth_in_tokens` et la charte § 5, et il n'est pas reproductible avec les noyaux usuels [Mesuré].

Le graphe utile est celui que le PNJ croit : ses dossiers de personnes et ses croyances `link(a, sorte, b)`, reliés par pointeurs. Un Transformer avec un biais d'attention sur ces arêtes *est* un GNN sur ce graphe (Graphormer : Ying et al., 2021). Hors décision, un GNN sert à analyser les sociétés qui émergent.

### 3.6 Gouverneur

En C++, généré depuis `catalogue/` (D31). Il applique :
- les bornes `step`, `rate` et `slow_rate`, et au plus 4 écritures par décision ;
- les règles dures (D10), masquées avant la décision et vérifiées après ;
- le refus de tout pointeur vers la vérité.

Chaque refus est journalisé et sert d'exemple négatif à l'entraînement.

## 4. Alternatives

| Approche | Pour | Contre | Verdict |
|---|---|---|---|
| Transformer d'ensembles + pointeurs | ordre libre, pointeurs natifs, 4-13 % du GPU | sélection du contexte nécessaire | **retenu** |
| GNN global | structure de groupe | lit la vérité, non déterministe | analyse seulement |
| État récurrent par PNJ (GRU ; Mamba : Gu & Dao, 2023) | continuité, coût minime | état caché hors catalogue, invisible au professeur | non : la continuité passe par PLAN, GOAL, MEMORY |
| Mélange d'experts (Fedus et al., 2021) | capacité sans calcul | on n'est pas limité en calcul ; déterminisme | non |
| Options hiérarchiques | moins de décisions | — | **retenu** (réveil, plans de 1 à 6 étapes) |
| Modèle du monde (DreamerV3 : Hafner et al., 2023) | imagination, renforcement | trop lourd ici | tâche auxiliaire : prédire la perception suivante |
| LLM local dans la boucle (≈ 7 B, 4 bits) | raisonnement riche | ≈ 4,5 Go, des secondes par décision | professeur et juge hors jeu |
| Profondeur variable (LayerDrop : Fan et al., 2019) | charte § 24 | lots à regrouper par profondeur | plus tard, boucle lente |
| Multi-modules à LLM (PIANO de Project Sid, 2024 ; CICERO, 2022) | cohérence sur 1 000 agents | un LLM par agent | on garde le découpage, distillé |

## 5. Entraînement et données

### 5.1 Étiquettes par jour, quotas gratuits [Estimé]

Une situation rendue en JSON (vue entière de la P20, zéros omis) fait environ 2 500 jetons en entrée et 250 en sortie. Avec 6 situations et une légende commune de 4 000 jetons, une requête fait environ 20 000 jetons : 12 requêtes/min restent sous 250 000 jetons/min.

| Source | Requêtes/jour | Situations/jour | Par semaine | Usage |
|---|---|---|---|---|
| 3.1 + 3.5 Flash Lite | 1 000 | ≈ 6 000 | ≈ 40 000 | décisions courantes, classements |
| Flash « forts » + 2.5 Lite | ≈ 140 | ≈ 700 | ≈ 5 000 | cas durs, réflexion, audit des Lite |
| LLM local 4 bits la nuit (p. ex. Qwen3, Apache 2.0) | — | ≈ 3 000-6 000 | ≈ 30 000 | émotions, croire ou non, réparer la grammaire, juge |
| Décideur de référence | illimité | — | — | amorçage seulement |
| Simulation | illimité | états sans étiquette | — | DAgger, tâches auxiliaires |

Total : environ 300 000 étiquettes de professeur en 6 semaines, l'ordre de grandeur qui convient à `small` ou `base`.

### 5.2 Méthode

1. **Amorçage** : une passe sur les 300 000 étiquettes de la référence pour roder jetons et têtes, puis abandon (elle donne des PNJ uniformes).
2. **Distillation contrefactuelle** : une requête porte une situation et 4 à 5 variantes ne changeant qu'un facteur (trait, relation, perception) : contexte payé une fois, sensibilité apprise directement. Beaucoup de personnalités extrêmes (charte § 7).
3. **DAgger** (Ross et al., 2011) : l'élève joue dans la simulation sans rendu, environ 25 fois plus vite que le temps réel ; le professeur étiquette environ 1 état sur 1 000, là où l'élève hésite le plus (entropie, désaccord entre versions, nouveauté). Un cycle par semaine.
4. **Préférences** : le professeur classe 4 tirages de l'élève (peu de jetons en sortie). Apprentissage de type DPO (Rafailov et al., 2023), retour par IA (Lee et al., 2023).
5. **Tâches auxiliaires gratuites** (UNREAL : Jaderberg et al., 2016) : prédire la perception suivante et l'issue de son geste.
6. **Renforcement léger, en dernier** : récompense = pulsions du catalogue + plausibilité jugée par le professeur, avec une pénalité KL qui garde l'élève près du modèle distillé.

Progression : survie → face-à-face → parole et croyances → groupes, normes, accords → objectifs longs.

**Le professeur voit** exactement les jetons de l'élève, en texte, avec des identifiants locaux (`E3 : homme adulte, tient un couteau, s'approche, confiance −2`). **Il rend** geste, pointeurs, manière, écritures, l'expression de langue intérieure en JSON (vérifiée par le validateur du catalogue ; invalide = rejetée et comptée) et un classement de 3 alternatives. Une justification en clair reste dans le jeu de données pour l'audit, jamais dans l'état de simulation.

### 5.3 Mesurer la cohérence et l'émergence

- **Sensibilité** : paires minimales (`minimal_pairs.py`, à étendre au catalogue) ; il faut battre la référence (98,6 %).
- **Individualité** : retrouver le PNJ, ou ses traits (R²), à partir de 50 de ses décisions ; entropie des gestes de PNJ différents dans une même situation.
- **Cohérence** : plans menés à terme ou abandonnés sans cause, écart entre dit et cru (mesuré, pas interdit : le mensonge existe), volatilité des relations, persistance des objectifs.
- **Émergence**, sur de longues parties : variété des accords, propagation et déformation des rumeurs, modularité du réseau, Gini des richesses, changements de rôle (charte § 24), événements de la chronique absents des sondes (§ 28), juge LLM en aveugle élève contre référence (Zheng et al., 2023).
- **Règles dures** : zéro violation, garanti par le gouverneur.

## 6. Inférence en C++

- **Phase 1 (premier jouable)** : ONNX Runtime (MIT), API C++, fournisseur CUDA (ONNX Runtime ≥ 1.27 cible CUDA 13) avec graphes CUDA, FP16, lots fixes de 32 (64 en cas de danger). Repli CPU avec `xs`. Parité avec l'oracle PyTorch : ≥ 99,9 % de décisions identiques.
- **Phase 2 (avant Steam)** : un moteur Vulkan, multi-constructeur. AMD représente environ 18,5 % des joueurs Steam (mars 2026), et CUDA 13 ne prend plus en charge les cartes antérieures à Turing. On évalue d'abord ncnn (BSD-3, Vulkan, INT8, conversion depuis PyTorch). Sinon, 6 noyaux maison (linéaire, normalisation, GELU, attention avec biais, collecte, argmax), environ 3 000 lignes (P10). TensorRT reste le plus rapide sur NVIDIA ; il a retiré Volta en 10.5 et le support de Turing est à surveiller.
- **Déterminisme** [Mesuré] :
  - à taille de lot égale, la sortie d'un PNJ est **identique bit à bit**, quels que soient ses voisins, sa place dans le lot, et en graphe CUDA comme en mode direct ;
  - d'une taille à l'autre, non : 18 % seulement des lignes sont identiques entre 1 lot de 500 et 25 lots de 20 (écart ≤ 1 × 10⁻³ en FP16). Aucun geste n'a changé, mais un quasi-ex æquo basculera un jour (le phénomène décrit par Thinking Machines, 2025) ;
  - d'où les **lots de taille fixe**, complétés par des lignes masquées, et le tirage Philox côté C++. La rejouabilité d'une partie repose sur le journal d'opérations, pas sur le modèle.
- **Mémoire** : 0,2 à 0,5 Go en tout ; il reste plus de 5 Go au rendu.
- **Partage du GPU** : lancer le pas juste après la soumission d'une image, en lots de 20 (≈ 4 ms), pour ne pas retarder l'image suivante.

## 7. Risques et questions pour Monsieur

1. **Contradiction à trancher** : D18 et `CLAUDE.md` disent « chaque PNJ plusieurs fois par seconde » ; votre consigne du 9 oct. fixe 200 décisions/s pour tous (0,4 par PNJ). Je propose d'inscrire la seconde : la réactivité vient des réveils sur événement.
2. **Marge** : 200/s n'occupe que 4 % du GPU en `small`. La dépenser en intelligence (`base`, `large`) plutôt qu'en fréquence ?
3. **Un second modèle partagé**, plus profond, pour la seule réflexion : est-ce compatible avec « un seul modèle » ?
4. **Professeur** : accord pour les quotas gratuits Gemini (≈ 1 100 requêtes/jour) et un modèle local la nuit ? Rien n'est lancé.
5. **Steam** : NVIDIA seule en version 1, ou Vulkan dès le départ ?
6. **Dépendance** : DAgger a besoin de la simulation sociale C++ (D31) ; en attendant, la boucle tourne sur `sim/` en Python.
7. **Machine** : mesurée à 8 cœurs / 16 threads (i9-10885H) et 62 Go de RAM, et non 4 / 8 et 16 Go comme l'écrivent `CLAUDE.md` et `docs/06`.

## Sources

Park et al. 2023, *Generative Agents*, arXiv:2304.03442 · Altera 2024, *Project Sid*, arXiv:2411.00114 · Bakhtin et al. 2022, *CICERO*, Science 378 · Ross, Gordon, Bagnell 2011, *DAgger*, arXiv:1011.0686 · Ying et al. 2021, *Graphormer*, arXiv:2106.05234 · Vinyals et al. 2015, *Pointer Networks*, arXiv:1506.03134 · Vinyals et al. 2019, *AlphaStar*, Nature 575 · Lee et al. 2019, *Set Transformer*, arXiv:1810.00825 · Sutton, Precup, Singh 1999, *Options*, Artificial Intelligence 112 · Gu & Dao 2023, *Mamba*, arXiv:2312.00752 · Fedus et al. 2021, *Switch Transformer*, arXiv:2101.03961 · Hafner et al. 2023, *DreamerV3*, arXiv:2301.04104 · Fan et al. 2019, *LayerDrop*, arXiv:1909.11556 · Willard & Louf 2023, *Outlines*, arXiv:2307.09702 · Rafailov et al. 2023, *DPO*, arXiv:2305.18290 · Lee et al. 2023, *RLAIF*, arXiv:2309.00267 · Zheng et al. 2023, *LLM-as-a-judge*, arXiv:2306.05685 · Jaderberg et al. 2016, *UNREAL*, arXiv:1611.05397 · He / Thinking Machines 2025, *Defeating Nondeterminism in LLM Inference* · TensorRT 10.x release notes (docs.nvidia.com) · ONNX Runtime releases 1.26-1.28 (github.com/microsoft/onnxruntime) · ncnn (github.com/Tencent/ncnn) · Steam Hardware Survey (mars 2026, via TweakTown).
