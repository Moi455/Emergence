# tok-2 : ce que le Transformer lit

Oracle Python du tokeniseur. Le portage C++ (D31) devra rendre les mêmes tableaux : même empreinte (`Encoded.digest`), vérifiée sur les jeux d'or (`golden/`).

**Entrée.** Les dossiers de l'esprit d'un PNJ, ceux que le sélecteur de contexte a gardés : sa propre personne, les personnes qu'il connaît, les choses qu'il voit, ses croyances, ses souvenirs, ses objectifs, la raison de son réveil (`WAKE`), etc. Chaque dossier a une clé (`@E3`, `b:7`, `me`, `wake`…). Rien ne vient de la vérité : le moteur fabrique ces dossiers à partir de ce que le PNJ perçoit et croit.

**Sortie.** Au plus 128 jetons, un par dossier. Chaque jeton est rangé dans des colonnes fixes par type (`num` 65 colonnes en float16, `cat` 38 en int16, `ptr` 5 en uint8, `prop` 20 positions), chacune avec son drapeau « connu » (`known`, `cat_known`, `ptr_known`). Tout est tiré de `catalogue/generated/model_interface.json` : ajouter une variable au catalogue ajoute sa colonne.

## Conventions des Records (ce que le moteur doit respecter)

- **Unités de la charte.** Les échelles psychologiques vont de −10 à +10 (de 0 à 10 pour les échelles non signées) ; le tokeniseur divise par 10. Un pourcentage (0..100) ou une valeur déjà normalisée (0..1) est une erreur du moteur : refusé, jamais raboté. Âges et échéances en heures de jeu, distances en mètres, masses en kg, volumes en litres. Les quantités sont ≥ 0 (sauf les °C) et au plus 1e7. Les composantes nommées (sin/cos, axes de réputation) sont données en [−1, 1].
- **Inconnu n'est pas vide.** Champ absent ou `None` : inconnu (drapeau 0). Pointeur `""` : connu, « personne ». Liste `[]` : connue vide. Vecteur de liste (`held`, mains vides) `[]` : connu, toutes composantes à 0. Une composante absente d'un dictionnaire reste inconnue.
- **L'ordre des listes compte.** Dans un type (les trois dossiers `BELIEF`, les `ENTITY`…) et dans chaque liste de mots ou de pointeurs, l'ordre donné est la saillance choisie par le moteur : le plus saillant d'abord. Le tokeniseur ne trie jamais. Les types, eux, sont rangés dans l'ordre du registre.
- **Plafonds.** Au plus `count` dossiers par type (budget), 6 mots par liste de mots, 4 pointeurs par liste de pointeurs, 20 symboles par proposition. `SELF` et `PLACE` sont obligatoires. Une personne `present=False` ne porte ni `dist`, ni `dir`, ni `look.*`.
- **Objets tenus.** Plusieurs objets dans les mains ou dans celles d'autrui : la masse (`mass`) s'additionne, toute autre composante prend le maximum. Chaque objet est contrôlé séparément avant la mise en commun.
- **Échéances signées.** `deadline` (GOAL, COMMIT) est un nombre d'heures *jusqu'à* l'échéance ; négatif si elle est dépassée ; le modèle lit un log signé. Un `age` reste un âge (heures écoulées).
- **Propositions.** Validées par la grammaire du catalogue (`language.Expression`) : proposition nue pour croyances, objectifs, souvenirs, engagements ; énoncé complet (avec humeur) pour `REQUEST.prop`. Nombres et comptes en chiffres ASCII, sans zéro de tête, au plus 1e7 ; clés canoniques (`@E7`, jamais `@E07`). Les symboles réservés (`<pad>`, `<num>`, `@E`…) sont refusés dans les champs de mots.
- **Toute erreur d'entrée est une `TokenError`**, jamais une `ValueError`, une `TypeError` ou une `OverflowError`. Les scalaires numpy sont acceptés.

## Pointeurs, esprit du PNJ et fantômes

`DecisionContext(records, known_keys)` : `known_keys` contient les clés de **tout** l'esprit du PNJ (défaut : les clés des records). Un pointeur vers une clé inconnue de l'esprit est refusé. Un pointeur vers une clé connue mais absente du lot devient un **fantôme** : emplacement `129 + k`, k de 0 à 31, numéroté par première apparition dans l'ordre d'encodage (lignes, puis colonnes `ptr`, puis positions de proposition) ; au-delà de 32 fantômes, `161`. Deux pointeurs vers le même fantôme donnent le même emplacement ; deux fantômes différents, deux emplacements : `(owns @E7 …)(at @E7 …)` ≠ `(owns @E7 …)(at @E9 …)`. Le modèle ne voit jamais le numéro du dossier, seulement l'identité. Le décodeur écrit `@E~k` (`@E?` au-delà de 32).

## Identifiants stables (`registry.json`)

Les poids d'un modèle sont liés aux identifiants de types, de symboles et de colonnes : ils ne bougent jamais quand le catalogue grandit.

```
cd ai && python3 -m tok2.registry            # ce qui manque au registre
cd ai && python3 -m tok2.registry --update   # ajoute les nouveautés À LA FIN
cd ai && python3 -m tok2.registry --check    # code de sortie 1 si périmé
```

Ajout seul : un nouveau type prend le numéro suivant, un nouveau champ les colonnes libres suivantes de son bloc, un nouveau symbole l'identifiant suivant. Ce que l'interface retire reste réservé (marqué `retired`, jamais réutilisé). Un champ dont le bloc, la largeur ou le codec change est un conflit : lui donner un autre nom. Les largeurs de bloc sont le maximum utilisé. Le `Tokenizer` refuse une interface qui contient un élément absent du registre et dit la commande à lancer.

## Parité C++ et jeux d'or

- Les nombres sont normalisés en double précision, puis arrondis **une seule fois** en float16 (IEEE binary16, arrondi au pair) ; `-0.0` devient `0.0`. `num` et `prop_num` sont en float16. Les formules sont dans `golden/layout.json`.
- Nombres d'une proposition : `log1p(n + 1)` ; 0 signifie « pas de compte », donc `silver_coin:0` ≠ `silver_coin`. Exact jusqu'à environ 250 au décodage (binary16).
- `Encoded.digest()` : `zlib.crc32` enchaîné sur les octets petit-boutiens de `n` (uint32) puis de chaque tableau de `Encoded.ARRAYS`, dans l'ordre, en ordre C, avec son dtype.
- L'empreinte de l'interface porte sur le JSON canonique du seul sous-arbre `input` et de ce que tok-2 lit de `speech` ; la version de schéma est vérifiée.
- `python3 -m tok2.golden --update` écrit `golden/layout.json` (types, colonnes, formules, largeurs, constantes 0/129/161, vocabulaire id→symbole, table mot de parole → id d'entrée pour lier les plongements) et `golden/cases.jsonl` (36 décisions : 12 du sampler à graine fixe, les autres faites à la main pour les bords, dont des refus). Un test vérifie qu'ils sont à jour et épingle les empreintes ; seuls les cas faits à la main sont régénérés par le test, les 12 du sampler sont vérifiés par leur empreinte.
- Sérialisation : `Record.to_dict/from_dict`, `DecisionContext.dumps/loads(tokenizer)` en JSON canonique (clés triées, sans espaces) avec un en-tête `{schema, interface, layout}` ; un contexte écrit pour une autre interface est refusé.

## Choix faits

- Les noms propres forment un ensemble ouvert : dans une décision, le k-ième nom distinct devient `<name k>` ; à partir du 65e, `<name_other>`. Le modèle sait seulement que deux mentions désignent le même nom.
- Une valeur hors échelle est refusée, jamais rabotée : c'est un défaut du moteur.
- Les listes de mots sont limitées à 6, les listes de pointeurs à 4 ; le moteur garde les plus saillants.

## Limites connues

- **Même chaîne, même identifiant** : deux mots écrits pareil sont le même symbole dans tous les champs (le plongement du champ les distingue).
- **Alias de noms** : seuls 64 noms distincts par décision gardent leur identité ; les suivants partagent `<name_other>` (et ne sont plus distinguables entre eux). Le décodeur rend `n:?`.
- **`@T` partagé** : `INV` (objets portés) et `THING` (objets vus) numérotent tous deux en `@T` dans la même décision ; le moteur doit donner des numéros distincts.
- **Quantités exactes absentes de la parole** : une proposition garde `log1p(n + 1)` en binary16, pas l'entier ; au-delà de 250 environ le compte n'est plus exact (le modèle n'a besoin que de l'ordre de grandeur).
- `log1p` n'est pas garanti identique au dernier bit entre bibliothèques : après l'arrondi en float16 l'écart n'apparaît que sur un cas limite très rare ; un portage qui diverge sur un cas d'or doit être examiné valeur par valeur.

## Taille et vitesse

Mesures dans `ai/situations/README.md` (ms par encodage, octets par décision). Les données d'entraînement se stockent en dossiers (`dumps`), et la mise en jetons se fait à la volée.

Tests : `python3 -m unittest discover -s ai/tok2/tests -t ai`.
