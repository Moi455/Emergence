# Le moteur et l'IA d'Emergence : comment ça marche

13 oct. 2026. Pour Monsieur. Rien de nouveau n'est décidé ici : le document dit ce qui existe, ce qui reste à construire, et répond à la question du temps de réflexion.

Étiquettes : **[Mesuré]** = test sur la Quadro RTX 3000 ou banc du projet ; **[Calculé]** = arithmétique sur des hypothèses écrites ; **[Estimé]** = à confirmer ; **[Hypothèse]** = idée non testée.

---

## 1. En bref

**Réponse à votre question : pas encore.** Aucun budget de réflexion par PNJ n'existe dans le code. Le document de recherche le propose (docs/09, § 6.1) ; la décision O24 répond « oui, en attendant ». Voir § 4.

1. Le moteur social décide quels PNJ pensent, selon ce qu'ils perçoivent. Le total vise 200 décisions par seconde (D32).
2. Un seul modèle partagé lit, pour chaque PNJ, un dossier mental de 128 jetons.
3. Le PNJ agit en un pas, ou il réfléchit : une suite de petits pas qui écrivent croyances, objectifs et plans.
4. Le gouverneur borne ce que le modèle écrit. Le moteur exécutera le geste et en gardera une trace durable (à construire).
5. Aucun poids du modèle ne change pendant la partie.
6. Mesuré : environ 17 % du GPU de la Quadro pour 200 décisions par seconde.

---

## 2. Le moteur, pendant une seconde de jeu

Une seconde réelle fait 16 secondes de jeu. Un jour de jeu dure 1 h 30 réelle. L'ordonnanceur travaille par pas de 100 ms, soit dix pas par seconde.

| # | Ce qui se passe | Existe | À construire |
|---|---|---|---|
| 1 | Un événement a lieu : un couteau sort, quelqu'un parle, un geste finit | monde (niveau 0) | bus d'opérations (M6) |
| 2 | Chaque PNJ perçoit ce qui est à sa portée et l'écrit dans ses dossiers. Il ne voit jamais la vérité | non | perception par observateur (chantier 3) |
| 3 | L'ordonnanceur choisit les PNJ qui pensent | prototype Python mesuré | version C++ (chantier 4) |
| 4 | Le moteur prépare le dossier de 128 jetons | tok-2 en Python | portage C++ ; sélecteur appris |
| 5 | Le modèle choisit geste, cibles, manière, condition d'arrêt, au plus 4 écritures, et une phrase au besoin | modèle en Python, testé sur des réponses aléatoires | entraînement, puis DAgger |
| 6 | Le gouverneur borne, refuse, journalise | oui, en C++ : accord avec l'oracle Python sur 4 650 cas | rien |
| 7 | Le moteur exécute le geste et en garde une trace | non | exécution des gestes, opérations (chantiers 4-5) |
| 8 | Les témoins perçoivent le geste et concluent | 46 jugements au catalogue | calcul des jugements côté témoin |

**Qui se réveille, et pourquoi (étape 3).** Cinq causes, par priorité :

- **P0 danger** : arme tirée près de soi, coup, feu, cri (servi en 0,1 s au p95 en simulation) ;
- **P1 interpellé** : on lui parle, une demande arrive ;
- **P2 fin de geste** : condition d'arrêt atteinte, échec ou blocage ;
- **P3 perception notable** : une nouvelle personne, un bruit fort ; le PNJ règle lui-même ce qu'il juge notable ;
- **P4 battement** : rien depuis 8 s éveillé, 60 s endormi.

Chaque pas sert 18 PNJ, plus un par danger en attente (64 au plus). Une réserve de jetons tient la moyenne sous 200 par seconde. Simulation **[Mesuré, synthétique]** : 181 décisions par seconde en moyenne, 500 PNJ, 45 min. Limite franche : les fins de geste prennent presque tout le budget (446 000 décisions sur 490 000). La parade prévue : des intentions plus longues, de 1 à 6 étapes.

**Le dossier du PNJ (étape 4).** Le PNJ ne voit que son dossier : lui-même et son réveil (WAKE), les personnes et objets qu'il connaît, ses croyances (BELIEF), souvenirs, objectifs, plans, engagements. Le moteur propose des candidats (64 croyances, 32 souvenirs, 24 personnes au plus) ; un sélecteur appris en garde 12 croyances et 9 souvenirs. Un propriétaire y est celui qu'il *croit*, jamais le vrai.

**Le gouverneur (étape 6).** Il ne décide jamais. Il coupe ou refuse :

- une variable réservée au moteur est refusée ;
- chaque variation est bornée : petit pas par décision, plafond par jour, plafond par année de vie. Seule une émotion peut sauter d'un coup ;
- 4 écritures au plus par décision ;
- règle dure D10 : un inconnu, un nom seul ou un âge inconnu compte comme mineur possible ; l'acte intime est alors refusé ;
- chaque refus sert d'exemple négatif à l'entraînement.

**Le geste et les témoins (étapes 7 et 8).** Le modèle choisit par exemple `strike` (frapper), avec une manière (force, zone, arme) et une condition d'arrêt. Le corps exécute. Le moteur écrira une `Operation` qui change le monde, même hors de vue (à construire). Les témoins perçoivent le geste selon sa visibilité : un vol en cachette n'est pas vu. Puis ils concluent. Le catalogue sépare le fait (prendre) du jugement (vol). Deux témoins peuvent conclure différemment. Le jugement n'est jamais une option offerte au modèle.

---

## 3. L'IA

### 3.1 Un seul modèle

- **Transformer d'ensembles** : il lit une liste de dossiers reliés par pointeurs (`@E3` = une personne, `b:7` = une croyance). Il lit le graphe que le PNJ *croit*. Un réseau de graphe sur le vrai graphe lirait la vérité : c'est interdit.
- **Taille** : 6,5 M de paramètres (`small`) à 17 M (`base`) selon docs/09. La Quadro n'a pas de bfloat16 : calcul en float16.
- **Trois modes**, marqués par un jeton : `act` (agir), `listen` (juger ce qu'on entend), `reflect` (réfléchir).
- **Têtes du même modèle** : sélecteur, théorie de l'esprit (ToM), critique de plans, décodeur de parole.

### 3.2 Ce qu'il produit

| Sortie | Forme | Contrôle |
|---|---|---|
| Geste | un parmi 40 | masqué par la faisabilité venue du moteur |
| Cibles | au plus 3 pointeurs, selon le geste | pointeurs typés (une personne, pas une croyance) |
| Manière, arrêt | paramètres en 5 niveaux ; une condition d'arrêt | catalogue |
| Écritures | au plus 4 : cible, variable (93 écrivables), valeur (21 niveaux) | gouverneur |
| Parole | une phrase dans la langue intérieure, 20 symboles au plus, environ 650 mots | grammaire du catalogue (pas encore appliquée au décodeur) |

La langue intérieure s'inspire de la logique d'ELIZA (mots-clés, motifs de décomposition), pas de sa conversation.

### 3.3 La pensée écrite (mode `reflect`)

Penser, c'est une suite de décisions courtes. Chaque pas écrit **un** dossier : une croyance, un jugement, un objectif, une étape de plan, une offre, une croyance sur autrui. Le pas suivant relit ce dossier. Le modèle dit « encore » ou « stop » (condition `c_think_more`, à ajouter). L'ordonnanceur fixe le plafond. Ce qui est écrit est visible, gouverné et sauvegardé.

**Sonde de coalition [Mesuré]** : cinq villageois, un coupable, trois lésés, dix conversations ; le modèle joue seul les cinq villageois, sur 4 096 épisodes tenus à part. Monde synthétique, petit modèle.

| Modèle | Réussite |
|---|---|
| une passe, sans supervision intermédiaire | 71,3 % |
| une passe, tête ToM supervisée (« qui sait, depuis quand ») | 97,4 % |
| **pensée écrite** (au plus 5 pas, arrêt choisi par le modèle) | **99,9 %** |
| pensée écrite, avec une trace de professeur fausse une fois sur cinq | 75,9 % |

Deux leçons : superviser les étapes intermédiaires compte plus que la taille du modèle ; une trace de réflexion incohérente fait chuter le résultat.

**Mémoire** [Mesuré] : une mémoire récurrente cachée n'apporte rien (73,0 % avec, 72,8 % sans). Quand on lui fournit les bons événements, le modèle atteint 99,9 %. Apprendre en jeu veut donc dire **écrire et retrouver des dossiers**.

### 3.4 Coût [Mesuré]

Un pas complet de 100 ms prend **17,5 ms en `base`, soit environ 17 % de la Quadro** (médiane de trois passages ; de 13 à 29 ms selon le passage). En `small`, 13,5 ms. Sans vrai rendu Vulkan et sans fusion des noyaux, ces chiffres restent provisoires. Un moteur fusionné viserait environ 10 % [Estimé]. Votre plafond est 25 % (CLAUDE.md).

Écartés par mesure : un petit LLM dans la boucle (36 à 176 % du GPU), l'apprentissage des poids en jeu, la récurrence latente.

---

## 4. Le temps de réflexion par PNJ

### 4.1 Où en est-on

- **Aujourd'hui** : l'ordonnanceur Python a un seul seau de jetons partagé. Il n'y a pas de budget par PNJ. Un PNJ pense dès qu'un réveil le désigne.
- **docs/09, § 6.1** : chaque PNJ reçoit un budget de pas de réflexion, ouvert sur événement (fort changement émotionnel, offre reçue, plan bloqué, nuit). Le modèle dépense ce budget en écrivant, puis dit « encore » ou « stop ».
- **O24** (docs/01) : « oui, en attendant ». **O20** : « fixe en attendant », tirée à la naissance, réglant la taille du contexte lu et non la fréquence. **docs/06, § 2.1** : la profondeur règle la taille d'entrée ou la fréquence. Ces trois textes ne disent pas la même chose (§ 7).

### 4.2 Ordres de grandeur

- Un pas de réflexion coûte 4,0 ms en `base` pour un lot de 8 **[Mesuré]**.
- La proposition O23 : 150 actions et 50 réflexions par seconde. Cela fait en moyenne **0,1 réflexion par PNJ et par seconde** **[Calculé]**.
- Pierre fait environ 5 réflexions dans une journée de jeu ; le maire, 30 à 60 décisions sur plusieurs jours **[Estimé, docs/09]**.
- Les réflexes (`act`, `listen`) ne seraient pas soumis à ce budget **[Hypothèse]** : docs/09 ne le dit pas.

**Contrainte de la charte (§ 24)** : la limite doit venir de la profondeur de simulation disponible, pas d'une règle qui dit « ce PNJ ne réfléchit pas ». Un budget fixé seulement par le rang social serait donc une règle artificielle.

### 4.3 Ce que cela change pour le joueur [Hypothèse]

Face à un danger, la réaction serait la même : elle reste un réflexe. Un budget bas donne des PNJ qui agissent sur le moment, sans plan à trois étapes, et plus de maladresses. Un budget haut donne des complots préparés, qui prennent des heures de jeu. Les réactions disproportionnées que vous aimez viendraient surtout des budgets bas.

### 4.4 Les options (je ne tranche pas)

| Option | Principe | Avantage | Risque |
|---|---|---|---|
| A. Fixe à la naissance | un budget tiré pour toute la vie | simple, proche de O20 | ne suit pas la mobilité sociale (§ 24) |
| B. Selon l'importance | plus pour chef, marchand, ancien | le complot vient de ceux qui comptent | règle de rang si elle remplace la profondeur |
| C. Selon la situation | ouvert sur événement (docs/09) | colle aux réveils ; coût lissé | un plafond global est nécessaire |
| D. Selon le tempérament du village | variable de partie : fous, modérés, sages | répond à votre demande de choix | à concevoir |
| E. Combinée | base à la naissance, qui grandit avec la vie, plus les événements | le plus proche de la charte | le plus complexe à régler |

**Défaut retenu pour la suite (question ouverte)** : option C, plafonnée par seconde, sans lien au rang. La base grandira avec la vie (O20).

---

## 5. Comment l'IA apprend

1. **Professeur Gemini.** Il rend la décision et sa trace de réflexion dans une même réponse. Quota gratuit : Flash Lite 15 par minute et 500 par jour ; Flash 5 par minute et 20 par jour. Le pilote n'a jamais été lancé : chaque appel réel demande votre accord. Il faut d'abord mesurer les jetons réels (estimation : 4 000 par situation).
2. **Situations d'amorçage** (`ai/situations`). 2 000 situations en 10 ms chacune, zéro proposition invalide. Le gouverneur les contrôle avant écriture. Des scénarios semés (rancune, rumeur, or, chef) compensent leur rareté : proposé, pas encore construit.
3. **Imitation.** Le modèle reproduit les décisions du professeur. L'ancien jeu de 300 000 exemples (format tok-1, hors dépôt) ne suit plus le format : il faut le régénérer. Entraînement en float16 : environ 18 min pour 1 M de décisions en `small` **[Estimé]**.
4. **DAgger** sur le moteur C++. Le modèle joue dans le moteur ; un professeur qui voit tout note les situations qu'il visite réellement ; on réentraîne. Pas encore possible : il faut le moteur complet (chantiers 3 à 5).
5. **Plus tard** : préférences et renforcement léger, avec un critique qui lit la vérité seulement pendant l'entraînement (O26).

**Rien ne change en jeu.** Le PNJ apprend en écrivant et en retrouvant ses dossiers : souvenirs, croyances, plans, engagements.

---

## 6. Deux exemples, de bout en bout

Tirés de docs/09, § 3 : pensées, paroles, engagements, gestes. Les jugements des témoins sont une illustration du mécanisme.

### 6.1 « Pierre, Jacques et Jean partent tuer George, qui a trompé leurs femmes »

| Moment | Pensée écrite | Parole | Engagement ou geste | Témoins |
|---|---|---|---|---|
| Pierre entend Marthe | croyance : George a eu un geste intime avec Marie (adultère) ; colère ; rancune | — | — | — |
| Il réfléchit | objectif : George mort | — | — | — |
| Il croit que Jacques et Jean savent | « Jacques viendra » ; « Paul non » (ami de George) | — | — | — |
| Il compare quatre plans (critique) | recruter deux hommes ; forêt ; à l'aube | — | — | — |
| Il rejoint Jacques, seul | — | à voix basse : offre d'agir à trois, à l'aube, en forêt | — | — |
| Jacques, puis Jean | — | — | acceptation : engagement à trois ✗ | — |
| À l'aube | réveil sur l'échéance | — | prend la hache ; marche en forêt | — |
| En forêt | — | — | frappe jusqu'à ce que George soit à terre | un témoin peut conclure au meurtre (`murder`) ; un complice qui se dérobe, à la trahison (`betrayal`) |

Pierre fait environ 12 décisions, dont 5 de réflexion ; Jacques et Jean environ 8 chacun **[Estimé]**. Règle dure : l'acte intime est dit entre adultes ; si un auditeur peut être mineur, le gouverneur refuse la parole (D10). Ce test de refus reste à ajouter.

### 6.2 « Le maire organise une expédition pour trouver de l'or »

| Moment | Pensée écrite | Parole | Engagement ou geste | Témoins |
|---|---|---|---|---|
| Il entend une légende d'or | croyance : l'or existe à tel endroit | — | — | — |
| Avant l'hiver | objectif lié à son rôle de chef ; sous-objectif : apprendre la route | — | — | — |
| Il évalue | qui viendra ; qui le croit en droit de commander | — | — | — |
| Il compare trois plans | plan retenu | — | — | — |
| Sur la place | — | demande et offre : une part du butin ✗ | — | le village entend |
| Chacun répond selon ses croyances | — | — | groupe « l'expédition » ✗ ; le maire le mène | — |
| Trois jours plus tard, à l'aube | réveil sur échéance | — | provisions pour dix jours ✗ ; la troupe marche derrière lui | un membre qui garde l'or : trahison |

L'expédition dure plusieurs jours : 30 à 60 décisions **[Estimé]**. Son plan survit à des centaines d'autres décisions parce qu'il est écrit (objectif, plan, engagement), retrouvé par le sélecteur et réveillé par l'échéance.

### 6.3 Ce qui manque au catalogue (docs/09, § 7)

Pour ces deux scènes, il manque : l'heure du jour (« à l'aube »), les durées (« dans trois jours »), le rendez-vous à une heure, le groupe « nous » figé et ses croyances (membres, chef, but), les parts (moitié, tiers), l'acceptation d'une offre précise, la condition « tous là », « continuer à réfléchir » et l'intention de dire dans le plan. Les jugements `adultery`, `revenge`, `murder`, `betrayal` et `broken_promise` existent déjà, ainsi que les règles D10 et P30.

---

## 7. Écarts à corriger dans les documents

- **Profondeur de simulation** : O20, O24 et docs/06 § 2.1 disent trois choses (§ 4.1). À trancher par vous.
- **Tailles de modèles** : docs/07 et 09 donnent `base` à 16-17 M ; le README de `ai/student2` mesure 28,5 M. À réconcilier.
- **Part du GPU** : docs/07 annonce 7,5 % ; docs/09 corrige à environ 17 %. Ce document retient 17 %.
- **Conditions d'arrêt** : 23 dans docs/07, 16 dans docs/09. À vérifier dans `catalogue/generated/model_interface.json`.
