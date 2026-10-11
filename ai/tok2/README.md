# tok-2 : ce que le Transformer lit

Oracle Python du tokeniseur. Le portage C++ (D31) devra rendre les mêmes tableaux : même empreinte (`Encoded.digest`).

**Entrée.** Les dossiers de l'esprit d'un PNJ, ceux que le sélecteur de contexte a gardés : sa propre personne, les personnes qu'il connaît, les choses qu'il voit, ses croyances, ses souvenirs, ses objectifs, etc. Chaque dossier a une clé (`@E3`, `b:7`, `me`…). Rien ne vient de la vérité : le moteur fabrique ces dossiers à partir de ce que le PNJ perçoit et croit.

**Sortie.** Au plus 128 jetons, un par dossier. Chaque jeton est rangé dans des colonnes fixes par type :
- `num` (65 colonnes) : nombres normalisés, avec un drapeau « connu » par colonne ;
- `cat` (38) : mots et valeurs d'énumération ;
- `ptr` (5) : pointeurs vers d'autres jetons de la même décision (0 aucun, 129 hors contexte) ;
- `prop` (20 positions) : la proposition du dossier, en ordre préfixe avec l'arité.

Tout est tiré de `catalogue/generated/model_interface.json` : ajouter une variable au catalogue ajoute sa colonne.

**Choix faits (11 oct.).**
- Les noms propres forment un ensemble ouvert : dans une décision, le k-ième nom distinct devient `<name k>`. Le modèle sait seulement que deux mentions désignent le même nom.
- Un pointeur hors contexte garde sa sorte (`@E?`) mais perd son numéro.
- Une valeur hors échelle est refusée, jamais rabotée : c'est un défaut du moteur.
- Les listes de mots sont limitées à 6, les listes de pointeurs à 4 ; le moteur garde les plus saillants.

**Taille.** 75 Ko par décision une fois déplié (mesuré). Les données d'entraînement se stockent donc en dossiers, et la mise en jetons se fait à la volée.

Tests : `python3 -m unittest discover -s ai/tok2/tests -t ai`.
