# État du Transformer des PNJ (ai/), 8 oct. 2026

Fil « Données d'entraînement du Transformer ». Court bilan avant le passage sur Claude Code.

## Ce que Monsieur veut (message du 8 oct., 15:34)

Chaque PNJ a un Transformer qui tourne plusieurs fois par seconde, avec un cache possible. Il reçoit ce que le PNJ voit, toute son identité et ses souvenirs. Il ajuste progressivement ses variables (seule l'émotion peut sauter d'un coup) et choisit une action. Les 500 PNJ sont simulés en permanence, même loin du joueur, sans rendu. Les données d'entraînement viendront d'un modèle bien moins cher que Claude.

## Fait

- **Contrat d'action** (`npc_pipeline/plan_contract.py`, `CONTRAT_PNJ.md`) : 112 fonctions, 20 conditions, plans de 1 à 6 étapes.
- **Jetons tok-1** (`npc_pipeline/encode.py`, oracle du futur encodeur C++) :
  - 14 types de jetons ;
  - au plus 64 jetons, dont 16 options ;
  - pointeurs entre jetons ;
  - vocabulaire 9c6f1d8ef56c58ac, aligné sur les fiches des 600 villageois et sur `docs/interfaces.md` v0.2.
- **Élève** (`student/`) : Transformer PyTorch de 0,8 à 33 M de paramètres. Il sort un score par option et 10 moteurs explicatifs. Les scripts d'entraînement et d'évaluation sont prêts, le guide est `student/ENTRAINEMENT.md`.
- **Données** (`/mnt/project-files/donnees-transformer/`, hors dépôt) :
  - 300 000 situations générées, étiquetées par le décideur de référence ;
  - 6 978 décisions vécues dans la simulation, converties par `sim_adapter.py` ;
  - 1 500 paires minimales sur 25 sondes.
- **Enseignant** (`teacher_run.py`) : prêt, jamais lancé (Gemini Flash-Lite visé, environ 3 100 requêtes pour 50 000 situations).
- **Catalogue unique** des variables et des actions : `docs/npc/variables_v0.3_catalogue_unique.md`, tenu par le fil Simulation et validé ici ; il remplace `CATALOGUE_modele.md`.

## Mesuré (CPU du conteneur, 4 cœurs)

- `tiny`, 3 passes sur 135 000 situations : 75 % des choix identiques à la référence ; 99,5 % des choix jugés bons ; paires minimales 86 % (référence 98,6 %) ; 1 518 décisions par seconde.
- Ces mesures datent d'avant l'alignement des tenues et des métiers. Elles ne valent que comme ordre de grandeur.
- Rien n'a été mesuré sur GPU.

## Pas fait : écarts avec la vision de Monsieur

1. **Pas de sortie « ajustement des variables ».** Le modèle choisit une option ; il n'écrit aucune variable. Il faut une tête « delta d'état » bornée par groupe : saut permis pour les émotions, petits pas pour les relations, très lent pour les traits. Les bornes proposées sont dans `CATALOGUE_modele.md`, colonne « Écriture ».
2. **Pas de perception.** L'entrée décrit une situation sociale (personnes, événements, souvenirs, village), pas ce que le PNJ voit : espace, voxels, matériaux, eau, feu, objets. Il faut des jetons de perception fournis par le moteur.
3. **Pas de boucle continue.** Le modèle est appelé à chaque fin de plan, pas plusieurs fois par seconde. Pour 500 PNJ à plusieurs appels par seconde, il manque :
   - le budget de calcul ;
   - le cache ;
   - les lots GPU ;
   - l'inférence en entiers.
4. **Les options viennent d'un générateur heuristique** (`build_candidates`). Le filtre réel doit venir du moteur, qui sait ce qui est faisable.
5. **Les étiquettes actuelles imitent un décideur à règles**, la référence. C'est ce qui donne des PNJ uniformes. L'élève doit apprendre de l'enseignant puis de la boucle de simulation, pas de la référence.

## Questions ouvertes pour Monsieur

- Les traits et les valeurs morales peuvent-ils bouger, lentement, ou sont-ils figés à la naissance ?
- Quel modèle « bien moins cher » pour l'enseignant (Gemini Flash-Lite, un modèle local ?), et avec quel budget ?
- Combien d'appels du Transformer par seconde et par PNJ, en jeu ?

## Répartition convenue avec le fil Simulation

- **Ce fil** : le modèle (architecture, jetons, vocabulaire, entraînement, inférence, référence).
- **Fil Simulation** : le monde qui l'entoure (état, événements, exécution des plans, banc d'essai à 500 PNJ).
- **Interface commune** : `decide(état, ≤ 16 options)`, qui renvoie un score par option. Elle sera à étendre avec les deltas d'état.
