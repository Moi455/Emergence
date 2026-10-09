# catalogue/ — la source unique des variables et des actions

Tout ce qui existe dans le monde simulé est déclaré ici **avant** d'être codé (D20). Remplace `ai/CATALOGUE_modele.md` et `docs/npc/variables_v0.3_catalogue_unique.md`. Plan de travail : étapes 0 à 18 (`~/.claude/plans/allez-y-planifiez-le-structured-engelbart.md`).

## Trois couches, jamais mélangées (Monsieur, 9 oct. 2026)

1. **Gestes physiques** (`[[action]]`) : ce que le corps fait, paramétré par la manière. Une claque, un coup de poing, un passage à tabac et des coups mortels sont **un seul geste** avec une force, une zone, une répétition et une condition d'arrêt.
2. **Parole** (`[[concept]]`, `[[grammar]]`) : parler est un geste ; ce qui est dit est une expression de la **langue intérieure** composée par le Transformer. « Faire chanter », « menacer », « promettre » ne sont pas des actions.
3. **Interprétations** (`[[interpretation]]`) : vol, trahison, meurtre, injustice… sont ce que les témoins concluent de **faits objectifs**. Jamais une option. Le validateur refuse un geste qui porte un de ces noms.

## D'où viennent les entrées

**Des premiers principes, pas des exemples.** Le gros du catalogue est fait de gestes et de mots très simples, obtenus en parcourant des axes complets (tout ce qu'un corps peut faire, tout ce que la matière peut subir, tout ce que la langue peut dire). Leurs combinaisons ne sont prévues par personne : c'est le Transformer qui les fait émerger (Monsieur, 9 oct.).

Les **histoires** (`data/stories.toml`) ne sont que des **sondes** : « le catalogue permet-il d'exprimer ceci ? ». Une sonde qui échoue révèle un manque, comblé par une primitive générale, jamais par une entrée propre à l'histoire. Une histoire ne justifie aucune entrée et ne contraint aucun comportement. Plus tard, des **rails légers** (coutumes connues des PNJ : faire la cour, marchander, funérailles) pourront aider l'entraînement ; un PNJ peut les suivre, les dévier ou les ignorer, le moteur ne les impose jamais.

## Ce que l'IA peut gérer (contrainte permanente, Monsieur, 9 oct.)

La richesse vit dans le moteur et les données ; le Transformer (≈ 5 M de paramètres, 500 PNJ en un lot) n'en reçoit qu'une **vue compacte et factorisée**. Chaque étape vérifie ces budgets :

| Quoi | Budget | Comment |
|---|---|---|
| Entrée d'une décision | ≤ 128 jetons (cible ≈ 96) | un **sélecteur appris** (entraîné par la perte de la politique) choisit les personnes, choses, souvenirs et croyances, parmi ce que le PNJ perçoit et croit ; une saillance simple ne sert que d'amorce provisoire, à remplacer |
| Un objet | vecteur fixe d'usages et d'états perceptibles + 6 grandeurs (≤ 48) + sorte apparente (table des sortes, ≤ 1 024) | un assemblage jamais vu est compris par ses propriétés : il généralise |
| Le corps | un résumé (douleur, saignement, conscience, mobilité, pire blessure) | les 16 zones et le volume de sang restent au moteur |
| Les autres | seulement ce qui se voit (apparence) | jamais leurs variables internes (charte § 5) |
| Un geste en sortie | ≤ 64 gestes × cible par pointeur × manière en ≤ 5 niveaux par paramètre | têtes de sortie séparées, masques de faisabilité du moteur |
| Une parole | ≤ 768 mots de grammaire (le vrai vocabulaire : concepts, gestes, manières, interprétations, variables et propriétés nommables, directions) + une table de **sortes** à part (types d'objets, matières, espèces, formes : ≤ 1 024 en tout, factorisée par catégorie), ≤ 20 symboles | décodeur autorégressif contraint par la grammaire (un automate), 20 pas au plus |
| Une proposition imbriquée | un jeton de plus par niveau, ≤ 2 niveaux | comptée dans les 12 jetons BELIEF |
| Les absents | un absent saillant (un proche, quelqu'un attendu) garde son jeton ENTITY avec present = faux | on remarque l'absence (charte § 20) |
| Ce qu'une décision écrit | geste choisi + **≤ 4 écritures** (pointeur, variable, valeur ; créer une croyance, un objectif, un souvenir ou un plan = une écriture dont la proposition sort du décodeur de la parole) | chacune bornée par le pas par décision et le taux par jour ; le reste suit les lois de retour du moteur (revue du 9 oct.) |
| Rythme | gestes rapides, objectifs lents | tout ne se décide pas à chaque pas |

**Unités de temps** (D30) : minute de jeu = 3,75 s réelles ; heure de jeu = 3 min 45 s ; jour = 1 h 30 (1 h de jour, 30 min de nuit) ; saison = 1 h 45 ; an = 7 h ; année de vie ≈ 2 h 30 à l'âge adulte (horloge de vie). Chaque dynamique déclare son horloge (`clock` : `real`, `day` = calendrier, `life` = horloge de vie).

**Durées des processus** (D30, D32 ; un PNJ décide en moyenne toutes les 2,5 s réelles = 40 s de jeu) :

| Processus | Horloge | Durée | En temps réel |
|---|---|---|---|
| surprise, sursaut | réel | ≈ 10 s | quelques décisions |
| peur sans menace, souffle, épuisement | réel | dizaines de secondes à minutes | |
| colère, douleur aiguë | réel | minutes | |
| faim (repas), soif | calendrier | ≈ 3 repas par jour | ≈ toutes les 30 min |
| sommeil | calendrier | ≈ 8 h de jeu | ≈ 30 min (la nuit) |
| ivresse | calendrier | quelques heures de jeu | ≈ 10 à 20 min |
| plaie, maladie | calendrier | de quelques heures à quelques jours | ≈ 10 min à quelques heures |
| deuil, humeur, attitudes, normes | calendrier | jours | heures |
| culture (semis → récolte) | calendrier | ≈ 1 saison | ≈ 1 h 45 |
| fermentation, tannage | calendrier | ≈ 1 à 2 jours | ≈ 1 h 30 à 3 h |
| grossesse, croissance, vieillissement | vie | grossesse ≈ 0,75 an de vie ; enfance 15 h ; vie 150 h | grossesse ≈ 1 h 50 |
| traits, valeurs | vie | ≤ 1 (traits) par année de vie | ≈ 2 h 30 par année de vie |

**Écritures** : créer un enregistrement (une croyance, un objectif, un souvenir) compte pour UNE écriture, quel que soit son nombre de champs. **Cadres d'événement** (règle unique) : un jeton BELIEF, MEMORY ou EVENT porte le prédicat, ≤ 3 pointeurs (les mots et quantités ne sont pas des pointeurs : attitude(agent, variable, entité, degré) a 2 pointeurs) et ≤ 2 rôles en ligne (with, to, into, how) ; une parole rapportée (says) ou une proposition imbriquée coûte un jeton de plus, pris dans les 12 jetons BELIEF ou les 9 MEMORY.

**Pas de temps.** `step` = au plus par décision ; `rate` = au plus par **jour de jeu** (1 h 30 réelle, D30) ; `slow_rate` = au plus par **année de vie** (≈ 2 h 30 réelles à l'âge adulte : l'horloge de vie est séparée du calendrier, dont l'année dure 7 h). Les 500 PNJ se partagent 200 décisions par seconde (D32), plus vite pour ceux qu'un événement réveille : sans `rate`, des pas répétés deviendraient un saut.

**Rien de vrai dans ce que l'IA lit** (règle dure `no_truth_in_tokens`) — ni dans les jetons, ni dans le **masque de faisabilité** (calculé sur ce que le PNJ perçoit et croit ; l'échec réel est physique et perçu), ni dans les **réveils** (on se réveille parce qu'on perçoit, pas parce qu'un danger est près en vrai), ni dans le **dépliage de la parole** (voir `data/language_grammar.toml`) : les jetons pointent vers les dossiers mentaux du PNJ, les événements qu'il se rappelle ou qu'on lui décrit, les lieux tels qu'il les connaît ; jamais vers un identifiant objectif, l'état réel d'un accord ou la vérité d'une croyance.

Champ `token` d'une variable : où l'IA la voit (`SELF.body.pain`, `ENTITY.look.wounds`…), ou vide si elle ne la voit pas (moteur seul). Une variable non vue peut quand même agir sur le monde : c'est le moteur qui l'applique.

## Commandes

```
python3 catalogue/tools/check.py            # structure, références, séparation des couches
python3 catalogue/tools/check.py --strict   # + toutes les sondes exprimables
python3 catalogue/tools/render.py           # écrit catalogue/CATALOGUE.md (pour Monsieur)
python3 catalogue/tools/budget.py           # ce que l'IA voit, compté (budget)
python3 -m unittest discover -s catalogue/tests
```

## Ajouter une entrée

Une table TOML dans le fichier de son domaine (`data/body.toml`, `data/beliefs.toml`…). Les champs permis sont ceux des classes de `schema.py` ; un champ inconnu est une erreur. Échelles de la charte : `bipolar10` (−10..+10) et `unipolar10` (0..10), stockées en dixièmes par le moteur. Écrivains : `engine`, `T_jump` (le Transformer peut sauter), `T_step` (pas borné par `step`), `T_slow` (au plus `slow_rate` par année vécue : l'ancienne borne de 0,1 par jour de jeu est caduque : avec une vie de 150 h, un jour de jeu dure 1 h 30 réelle (D30)), `birth`, `action`, `derived` (vue calculée, jamais écrite).
