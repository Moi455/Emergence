# ELIZA et la langue intérieure (13 octobre 2026)

Demande de Monsieur : étudier ELIZA, **la logique avec laquelle elle découpe les mots et en tire un sens**, pas sa conversation. Ce document dit ce que j'ai lu, ce que j'en garde, ce que je refuse, et où c'est dans le code.

## 1. Ce qu'ELIZA fait (Weizenbaum, 1966)

Sources lues : l'article de Weizenbaum ([texte](https://courses.cs.umbc.edu/331/papers/eliza.html)), la description de [Wikipédia](https://en.wikipedia.org/wiki/ELIZA), le chapitre « Doctor » de Brian Harvey ([Berkeley](https://people.eecs.berkeley.edu/~bh/v2ch9/doctor.html)). Marqué **[lu]** ce que ces pages disent, **[mémoire]** ce que je tiens du script DOCTOR original et que ces pages n'ont pas montré mot à mot (à vérifier dans l'article).

| Mécanisme d'ELIZA | Ce que c'est |
|---|---|
| **Mots-clés à rang** [lu] | un script déclare des mots-clés, chacun avec un numéro de précédence ; le texte est lu de gauche à droite, et un mot-clé déjà trouvé est abandonné pour un mot de rang plus haut |
| **Motifs de décomposition** [lu] | `(0 YOU 0 ME)` : 0 = un nombre quelconque de mots, un entier n = exactement n mots ; le premier motif de la liste du mot-clé qui convient est pris ; les motifs qui réussissent toujours (`0 YOU 0`) sont essayés en dernier |
| **Règles de réassemblage** [lu] | `(WHAT MAKES YOU THINK I 3 YOU)` : on recompose avec les morceaux numérotés ; plusieurs règles par motif, utilisées à tour de rôle |
| **Script = données** [lu] | le moteur est séparé du script (DOCTOR n'est qu'un script ; il en existe en anglais, gallois, allemand) |
| **Échange I / YOU** [lu] | « You are very helpful » devient « I are very helpful » avant la décomposition : un premier passage échange les personnes |
| **Mémoire** [lu] | sur certains mots-clés (MY), une transformation est mise en file ; sans mot-clé, ELIZA ressort la plus ancienne |
| **Sans mot-clé** [lu] | une remarque vide (« please go on ») ou la mémoire |
| **Classes de synonymes** [mémoire] | des étiquettes `(/FAMILY MOTHER FATHER SISTER…)` : un motif accepte « un mot de la famille » au lieu d'un mot |
| **NEWKEY, redirections `=`** [mémoire] | essayer le mot-clé suivant quand les motifs d'un mot-clé échouent ; renvoyer un mot-clé vers un autre |

ELIZA ne comprend rien : le « sens » est la forme de la phrase, rattachée à un mot-clé. C'est justement ce qui nous intéresse, parce que **notre langue a déjà une forme** (un mode et une proposition en arbre), et que reconnaître une forme est bon marché, lisible et testable.

## 2. Ce que je prends

| ELIZA | Chez nous | Où |
|---|---|---|
| mots-clés à rang | le **rang d'un mot** vient de sa catégorie (`keyword_ranks`) : un jugement (9) l'emporte sur une règle (8), un geste (7), un opérateur de temps (6)… ; `topic()` donne le mot qui dit de quoi l'on parle | `catalogue/data/language_grammar.toml`, `tools/shapes.py` (`Keyworder`) |
| motif de décomposition | un **motif sur l'arbre** de la parole : `_`, `?x` (même valeur partout), `<catégorie>`, `...` (le reste, comme le 0 d'ELIZA) | `tools/shapes.py` (`Pattern`) |
| classes de synonymes | **nos catégories de mots** (`<link>`, `<deontic>`, `<interpretation>`, `<mood>`…) : rien de nouveau à écrire, elles existaient | `language_core.toml`, `language_grammar.toml` |
| lire tout le texte à la recherche du mot-clé | une forme se cherche **n'importe où** dans la parole (une menace dans un `says`) ; la plus haute gagne | `ShapeMatcher.read` |
| script = données | les **formes de parole** sont des données (18 aujourd'hui), pas du code | `catalogue/data/speech_shapes.toml` |
| échange I / YOU | à l'instant où la parole est **figée pour l'auditeur** : `me` devient le dossier du parleur dans l'esprit de l'auditeur, `you` devient son propre `me` ; `us` reste `us` | `tools/shapes.py` (`Perspective`) |
| mémoire | c'est déjà la **pensée écrite** (docs/09) : chaque pas écrit un dossier que le pas suivant relit ; rien à ajouter | docs/09 § 6 |
| sans mot-clé | la parole « incompréhensible » : `BELIEF.unintelligible` ; le PNJ sait qu'on lui a parlé, pas de quoi | `catalogue/data/beliefs.toml` |

Les formes reconnues à ce jour : promesse, engagement conditionnel, menace, pression (« si tu ne fais pas…, je dirai… »), engagement à plusieurs, recrutement, rendez-vous, échéance, demande de discrétion, jugement dit, ouï-dire, accord, refus, ignorance, sondage, partage, règle énoncée, demande d'agir. Elles servent à **nommer après coup** un agencement de mots : statistiques de variété du professeur, audit, tests des sondes (le complot est bien lu comme engagement à plusieurs, rendez-vous, demande de discrétion, jugement, accord).

## 3. Ce que je ne prends pas

- **Le réassemblage qui fabrique la réponse.** Chez ELIZA, la forme *décide* de ce qu'on répond. Chez nous, rien ne décide à la place du modèle : une forme n'est ni un mot, ni un geste, ni une option offerte au Transformer, ni une règle d'action (D28 : « promettre » n'est pas une action). Un test vérifie qu'aucun identifiant de forme n'est dans le vocabulaire, les gestes ou les sorties du modèle.
- **Le dialogue par miroir** (reformuler ce que l'autre dit). Hors sujet.
- **Un analyseur à règles qui décide de la valeur sociale d'une phrase.** Le jugement (« c'était un adultère ») reste une écriture du modèle (`m_interpretation`), pas une déduction du moteur.

## 4. Risques et suite

- Les formes sont **descriptives** ; si on les utilisait un jour comme « rails légers » (coutumes que les PNJ peuvent suivre, dévier ou ignorer), ce serait une décision à part (CHANTIERS).
- Les rangs sont **proposés**, pas mesurés ; à régler sur les données du professeur (quel mot-clé prédit le mieux ce qu'un auditeur retient).
- Une forme manquée ne coûte rien (elle ne dit pas « autre chose »), une forme à tort est une erreur de statistique, jamais de simulation.
