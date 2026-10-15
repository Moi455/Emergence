# Audit de couverture : la vie d'un village avec 40 gestes (14 oct. 2026, révisé le 15 oct.)

Question : chaque activité d'une vie de village médiéval cosy s'exprime-t-elle avec les **gestes, manières et processus existants** du catalogue, et le moteur saura-t-il l'exécuter ? Sinon, que manque-t-il précisément ? Règle de D28 : pas de geste à sens social, des primitives générales ; une valeur de manière se décrit par sa **forme** (ce qu'on voit, ce qu'on entend), et ce qu'elle veut dire appartient à qui la perçoit.

Sources vérifiées : `catalogue/data/actions.toml` (40 gestes), `matter.toml` (31 processus), `conditions.toml` (23 conditions), `items_*.toml` (421 types d'objets), `species.toml` (79 espèces), `stories.toml` (148 sondes). Architecture : `docs/14_architecture_moteur_actions.md`. Tâches : `docs/15_feuille_de_route_jouable.md` (T08a, T08b, T08c font les ajouts). À ne pas confondre avec `docs/16_quantification.md`, écrit par un autre fil.

Révision du 15 oct. :
- les valeurs de manière sont décrites par leur forme ;
- la conception et la naissance, retirées en attendant O39, sont levées le 15 oct. par P53 (§ 4.4, T08d) ;
- `c_have` porte sur ce qu'on a vu ou cru ;
- les budgets de jetons seront re-mesurés ;
- les routines ont une période ;
- le chef d'un groupe a deux champs pour suivre ses effectifs ;
- les accords ne sont plus jugés par le moteur.

Légende du statut :
- **OK** : exprimable avec l'existant ; le moteur l'exécutera avec ses lois actuelles.
- **Loi** : exprimable ; il manque une loi du moteur ou une description étendue, sans geste ni mot nouveau.
- **Manque** : il manque un processus, une manière, une condition ou une variable du catalogue (dit précisément).
- **Question** : attend une décision de Monsieur.

## 1. Les activités (64)

### Champs et récoltes

| # | Activité | Gestes et manières | Processus | Statut : ce qui manque |
|---|---|---|---|---|
| 1 | Labourer à la houe | `strike`(terrain, `with=held` houe, `swing`, `firm`, until `c_state_seen` labouré) | `till` | OK |
| 2 | Labourer à la charrue et au bœuf | `tie`(bœuf à la charrue, `lash`) puis `push`(charrue, `away`, `hard`) en suivant le bœuf (`go along`) | `till` | **Loi** : `till` le long du trajet d'un outil qui `digs` et qu'on pousse (`ContactResolver`) |
| 3 | Semer à la volée | `pour`(sac de graines, into terrain, `some`) | — | **Manque** : processus `germinate` (une graine dans un sol labouré et humide devient une pousse) |
| 4 | Arroser | `pour`(arrosoir, into terrain) | `flow`, `absorb_evaporate` | OK |
| 5 | Désherber | `pull`(plante, `firm`) | `extract` | **Loi** : `extract` s'étend aux plantes enracinées (description) |
| 6 | Moissonner | `strike`(plante, faucille ou faux, `swing`, until **`c_have`** gerbes N) | `cut` | **Manque** : condition `c_have` |
| 7 | Lier les gerbes | `tie`(gerbes, `knot`, avec paille) | `bind` | OK |
| 8 | Battre le grain | `strike`(gerbes, `with=held` fléau) | — | **Manque** : processus `separate` (séparer les parts d'un mélange par le choc, le vent ou le tamis) |
| 9 | Vanner, tamiser | `pour`(grain, into direction, au vent) ; `work`(tamis, `rub`) | — | **Manque** : `separate` |
| 10 | Moudre | `operate`(meule, `activate`) ; `work`(meule à bras, `press`) | `crush` | OK |
| 11 | Cueillir des fruits | `take`(plante, `from=` **`growing`**) | — | **Manque** : valeur `growing` de `take.from` (sur la plante qui pousse) |
| 12 | Faucher et faner le foin | `strike`(herbe, faux) ; `push`(foin, fourche) ; attendre | `cut`, `absorb_evaporate` | OK |
| 13 | Garder des semences | `put`(graines, into coffre) | — | OK |
| 14 | Récolter le miel | `operate`(ruche, `open`) ; `take`(rayon) ; `work`(rayon, `squeeze`) | — | **Manque** : processus `press_extract` (un fluide sort d'une matière ou d'une bête qu'on presse) |

### Bêtes

| # | Activité | Gestes et manières | Processus | Statut : ce qui manque |
|---|---|---|---|---|
| 15 | Nourrir les bêtes | `give`(fourrage, to bête) ; `put`(fourrage, auge) | loi animale | OK |
| 16 | Traire | `work`(vache, `squeeze`, avec seau, `a_while`) | — | **Manque** : `press_extract` ; variable `animal_product_ready` |
| 17 | Tondre | `work`(mouton, avec forces, `squeeze`) | `cut` | **Manque** : `animal_product_ready` (la laine repousse) |
| 18 | Mener le troupeau | `go`(`along` troupeau) ; `speak`(to bêtes) ; `sign`(`beckon`) | loi animale | OK |
| 19 | Abattre une bête | `strike`(bête, couteau tenu, `thrust`, `full`, until `c_target_still`) | — | OK |
| 20 | Dépecer, découper | `work`(carcasse, couteau, `saw`) | `cut` | **Loi** : `cut` sur une carcasse rend les produits espèce × partie (description) |
| 21 | Ferrer un cheval | `take`(fer) ; `put`(fer, **where = bête**) ; `strike`(clou, marteau) | `assemble` | **Manque** : élargir `put.where` à `animal` (élargissement de pointeur) |
| 22 | Monter à cheval | `mount`(cheval, `get_on`) ; `go` | — | OK |
| 23 | Atteler une charrette | `tie`(cheval à la charrette, `lash`) ; `mount`(charrette) ; `go` | `bind` | OK |

### Maison et cuisine

| # | Activité | Gestes et manières | Processus | Statut : ce qui manque |
|---|---|---|---|---|
| 24 | Faire du feu | `strike`(silex, avec fer tenu) ; `blow`(braises) | `fracture` (étincelles), `combust` | OK |
| 25 | Puiser de l'eau | `operate`(poulie du puits, `activate`) ; `scoop`(eau, seau) | `flow` | OK |
| 26 | Pétrir | `work`(pâte, `press`, `firm`, `a_while`) | `mix` | OK |
| 27 | Cuire le pain | `put`(pâte, four chaud) ; `wait`(until `c_state_seen` pain cuit) ; `take` | `heat`, `cook` | OK |
| 28 | Cuisiner un ragoût | `put`(ingrédients, marmite) ; `put`(marmite, sur le feu) ; `work`(`stir`) | `cook`, `mix` | OK |
| 29 | Brasser la bière | tremper l'orge, broyer, mélanger, chauffer, fûts fermés | `ferment` | **Manque** : `germinate` (maltage) |
| 30 | Faire beurre et fromage | `work`(lait, `stir`, baratte) ; `work`(caillé, `squeeze`) ; affiner | `ferment` | **Manque** : `separate` et `press_extract` |
| 31 | Conserver (saler, fumer, sécher) | `put`(viande, sel, fumoir, claie) | `dry_preserve` | OK |
| 32 | Laver le linge, se laver | `work`(linge, `rub`, avec eau et savon) ; `pour`(eau, sur soi) | — | **Manque** : processus `wash` (`dirtiness` et `grooming` baissent ; une plaie lavée s'infecte moins) |
| 33 | Balayer, ranger | `work`(sol, `rub`, balai) ; `put` | — | **Manque** : `wash` |
| 34 | Coudre, raccommoder | `tie`(étoffe, `sew`, fil et aiguille) | `bind` | OK |
| 35 | Filer | `operate`(rouet, `activate`) ; `work`(fuseau, **`twist`**) | `spin_weave` | **Manque** : valeur `twist` de `work.motion` (tordre en tournant) |
| 36 | Tisser jusqu'au soir | `operate`(métier, `activate`) | `spin_weave` | **Manque** : `operate` n'a pas de condition d'arrêt ; `natural_end` = faux et **tête d'arrêt de décision** (docs/14 § 4.3, T11) |
| 37 | Teindre | `put`(étoffe, cuve de teinture) ; attendre | `dye_process` | OK |
| 38 | Faire des bougies | chauffer la cire ; `pour`(cire, moule) | `melt`, `mold_cast` | OK |

### Artisanat et construction

| # | Activité | Gestes et manières | Processus | Statut : ce qui manque |
|---|---|---|---|---|
| 39 | Forger | `put`(fer, foyer) ; `operate`(soufflet) ; `take`(pinces) ; `strike`(enclume, marteau) ; `put`(fer chaud, eau) | `heat`, `forge`, `cool_freeze` | OK |
| 40 | Fondre le minerai | broyer ; `put`(minerai et charbon, bas fourneau) ; soufflet | `crush`, `smelt` | **Manque** : `char` (faire le charbon de bois) |
| 41 | Faire du charbon de bois | `put`(bûches en meule) ; `scoop`(terre, dessus) ; `work`(torche, `press`) | — | **Manque** : processus `char` (bois chauffé sans air → charbon) |
| 42 | Aiguiser un outil | `work`(lame, `rub`, pierre à aiguiser) | — | **Manque** : processus `abrade` (un abrasif enlève de la matière, refait un tranchant) |
| 43 | Menuiserie | `work`(`saw`) ; `work`(rabot, `rub`) ; `strike`(clou, marteau) | `cut`, `assemble` | **Manque** : `abrade` (raboter) |
| 44 | Poterie | `operate`(tour, `activate`) ; `shape`(argile, into forme) ; `put`(four) | `fire_clay` | OK |
| 45 | Tanner | `work`(peau, `rub`, couteau à écharner) ; `put`(peau, cuve à tan) ; attendre des jours | `cut`, `tan` | **Manque** : `process_progress`, `process_started_at` (un processus de plusieurs jours survit à la sauvegarde) |
| 46 | Souffler le verre | `blow`(canne) ; chauffer | `melt` | OK |
| 47 | Bâtir à la baguette (charte § 17) | `channel`(terrain ou structure, `assemble`, into forme) | `magic_shape` | OK |
| 48 | Maçonner | `work`(mortier, `stir`) ; `put`(pierre, dans le mur) ; `climb`(échelle) | `mix`, `assemble` | OK |
| 49 | Couvrir un toit de chaume | `put`(bottes de chaume) ; `tie` | `assemble`, `bind` | OK |
| 50 | Réparer un mur, un outil, un toit | `channel`(`mend`) ; `put` ; `tie` | `magic_shape`, `assemble`, `bind` | OK |
| 51 | Démolir à la masse (charte § 17) | `strike`(structure, masse, `hard`) | — | **Manque** : `disassemble` (une construction frappée à ses joints rend ses éléments) et `collapse` ; voir O33 |

### Matière brute, chasse, pêche

| # | Activité | Gestes et manières | Processus | Statut : ce qui manque |
|---|---|---|---|---|
| 52 | Abattre un arbre | `strike`(arbre, cognée, `swing`, `hard`, until `c_state_seen` tombé) | `cut` | **Manque** : processus `collapse` (ce qui n'est plus porté tombe) |
| 53 | Fendre du bois | `strike`(bûche, hache ou coin) | `split` | OK |
| 54 | Miner | `strike`(roche, pioche, until `c_have` minerai N) ; `take` ; étayer (`put` poutre) | `extract` | **Manque** : `collapse`, `c_have` |
| 55 | Tailler la pierre | `strike`(bloc, ciseau et maillet) | `split`, `carve` | OK |
| 56 | Faire du sel | `pour`(eau de mer, marais salant) ; attendre ; `scoop`(sel) | `absorb_evaporate` | **Loi** : `absorb_evaporate` laisse le soluté (description) |
| 57 | Pêcher à la ligne | `throw`(hameçon appâté, at eau) ; `wait`(until `c_state_seen` ligne tendue) ; `pull` | — | **Manque** : processus `trap_catch` |
| 58 | Pêcher au filet, poser un collet | `throw`(filet) ; `put`(collet) ; `wait` ; `pull` ; `take` | — | **Manque** : `trap_catch` |
| 59 | Chasser à l'arc | `go`(`along` trace, `discreet`) ; `throw`(flèche, `with` arc, at bête) | — | OK |
| 60 | Cueillir champignons et herbes | `search`(sous-bois) ; `examine`(`look`, `smell`) ; `take`(plante) | — | OK |

### Corps et soins

| # | Activité | Gestes et manières | Processus | Statut : ce qui manque |
|---|---|---|---|---|
| 61 | Soigner une plaie | `examine`(`touch`) ; `work`(onguent, `press`) ; `tie`(bandage) ; `pour`(eau, plaie) | `heal_tissue` | **Manque** : `wash` |
| 62 | Soigner un malade | `examine` ; `drink`(remède, to malade) ; `touch`(`gentle`) | — | **Manque** (O30) : lois `contagion`, `illness_course` ; table `[[illness]]` (schéma fait par T07) |
| 63 | Aider une naissance | `touch` ; `take`(nouveau-né, `in_arms`) | — | **Loi** : `gestate_birth` (P53, T08d) ; la sage-femme n'est qu'un `touch` et un `take` |
| 64 | Sentir la fumée, le pain, la mort | `examine`(`smell`) ; réveil P3 | — | **Manque** (O30) : loi `smell_spread`, variable `pp_smell_seen` |

### Vie sociale (tout passe par la parole, le signe, la manière)

Ces activités sont **OK** : elles ne demandent aucun geste nouveau, et ne doivent pas en demander (D28) :
- commercer, marchander (`speak`, `give`, `take`, `examine weigh` ; accord) ;
- enseigner un métier (parler, faire le geste devant l'apprenti qui regarde ; loi de maîtrise) ;
- apprendre à lire (`read`, `write`) ; prier (`set_posture kneel`, `speak`) ;
- jouer, chanter, danser (`perform`) ; raconter (`speak`) ; jeux (`throw`, `look`) ;
- courtiser entre adultes (`speak`, `touch`, sous D10) ; mariage et funérailles (paroles, accord `ritual`, `scoop`, `put`, `perform`) ;
- garder une maison (`wait`, `look watch`) ; arrêter quelqu'un (`grab`, `tie`, `pull`) ;
- voter, tenir conseil (`sign raise_hand`, `speak`, comptage perçu) ; écrire, afficher (`write`, `put`) ;
- garder des enfants (listes blanches D10) ; voyager et camper (`go`, `put`, `sleep`, feu).

Manques relevés dans ce groupe :
- **voix** : `speak.tone` n'a que des qualités tranchées (`warm`, `calm`, `cold`, `angry`, `pleading`), et le clip `talk_joyful` existe sans valeur qui le commande. Ajouts décrits par leur forme : `rising` (voix qui monte, rythme vif), `trembling` (voix qui tremble), `low_slow` (voix lente et basse), `drawling` (voix traînante, mots étirés) ;
- **signes** : ajouts décrits par leur forme seule : `wink` (une paupière se ferme brièvement), `cover_face` (les mains sur le visage), `trace_sign` (la main trace une figure dans l'air). Ce qu'ils veulent dire, ceux qui les voient en jugent ;
- **sens** : `examine.sense` gagne `hear` (l'oreille contre la chose) ;
- **routines** : patrouiller, faire sa tournée, se réunir demandent `i_repeat` et sa période, pas un geste ;
- **attendre le bon moment** : `c_unwatched` (personne ne paraît me regarder) et `c_target_near` (la cible paraît à portée).

## 2. Pourquoi aucun nouveau geste

| Candidat | Rejeté parce que |
|---|---|
| `dig` (creuser) | `strike` avec un outil qui `digs`, ou `scoop` : c'est la propriété de l'outil qui fait le processus |
| `harvest`, `plant`, `milk`, `fish` | des combinaisons geste + outil + processus (lignes 3, 6, 16, 57) ; un geste dédié porterait une recette, ce que refuse `matter.toml` |
| `pray`, `teach`, `trade`, `vote`, `marry` | sens social : parole, signe, accord, jugement (D28) |
| `drop` (lâcher) | `put` à ses pieds ; `stop` lâche une prise |
| `sit_on` (s'asseoir sur une chaise) | `set_posture sit` après un `go` vers le siège : le moteur pose le corps sur le support atteint ; un paramètre de plus changerait la signature de `set_posture`, donc son identifiant de sortie |
| `carry_together` (porter à deux) | deux `take` sur la même cible ; les forces jointes sont une loi du moteur |
| `slam` (poser violemment) | `throw` vers le sol ; `put` n'a pas d'intensité, et lui en ajouter une changerait sa signature |

## 3. Sondes de planification longue (pour la MESURE seulement)

Ces histoires nommées sont des **sondes** : elles disent si le catalogue et le moteur permettent un comportement. Elles ne sont ni des consignes pour le professeur, ni des familles de données (D28, charte § 28 ; les familles de données se classent par structure : docs/14 § 10.2). Pour chacune : la chaîne objectif → sous-objectifs → plans, ce qui existe, et ce qui manque.

| Sonde | Chaîne | Existe | Manque |
|---|---|---|---|
| Économiser pour une maison (`save_for_house`, `buy_house`) | `owns(me, maison)` ⟵ `amount(mes pièces, N)` ⟵ plan quotidien : travailler, être payé, ranger les pièces | prix cru (`worth`), `g_progress` (dérivé des croyances), accord d'emploi périodique | `g_parent`, `i_repeat`, plusieurs plans |
| Expédition pour l'or (`mayor_gold_expedition`) | `has(me, or)` ⟵ apprendre la route ⟵ recruter ⟵ vivres pour 10 jours ⟵ départ à l'aube dans 3 jours ⟵ marche, fouille, partage | groupes, parts, rendez-vous, échéances, `leads`, `think_more` | `GROUP.my_task`, effectifs crus du chef, P2b, `c_have`, carte mentale (la route) |
| Complot à trois (`revenge_plot_three`) | `dead(@George)` ⟵ recruter ⟵ rendez-vous en forêt ⟵ attendre que tous soient là ⟵ frapper | sonde décomposée ; `c_sees_ref` sur un groupe | `c_unwatched`, `c_target_near`, P2b, `occasion` |
| Fonder une guilde (`found_guild`) | groupe nommé ⟵ accord des membres (cotisation `each_season`) ⟵ rôle de maître ⟵ maison de guilde ⟵ coutumes | référents, accords périodiques, rôles, coutumes | groupe membre d'un groupe, `GROUP.my_task`, `s_last_believed`, registre écrit des biens communs |
| Préparer l'hiver | `maintain(not (has_need @foyer hunger))` avant l'hiver ⟵ grain ⟵ bois ⟵ viande séchée ⟵ toit réparé | `season_felt`, `before` + `winter`, `dry_preserve`, `plant_yield` | `c_have`, `process_progress`, `made_at`, temps des cultures (champs de T07), `g_parent` |
| Monter une milice | groupe ⟵ chef cru légitime ⟵ armes communes ⟵ entraînement ⟵ tours de garde toutes les 8 h ⟵ alarme | rôles, `may`, accords, loi de maîtrise | `i_repeat = every` + `i_repeat_period`, `GROUP.my_task`, sous-groupes |
| Apprendre un métier tard (`learn_trade_late`) | `knows_how(me, t_smithing)` ⟵ accord d'apprentissage ⟵ pratiquer devant le maître | accord, `k_mastery` | loi de maîtrise dans le moteur (T21) |
| Prendre le pouvoir (`election_campaign`, `coup_against_chief`) | `holds(me, chief)` ⟵ convaincre N personnes sur des jours ⟵ jour du vote | paroles, `may`, `legitimacy` (vue calculée) | sous-objectifs (`g_parent`) plutôt que des plans de plus de 6 étapes ; `occasion` |

**Ce qui revient partout** : sous-objectifs, plusieurs plans à la fois (réserve de 1 à 4), routines avec période, réveil d'échéance (P2b), occasion sociale, condition « j'ai assez » (`c_have`), carte mentale, et **une tête de plan dans le modèle** (T11).

## 4. Les ajouts au catalogue (liste exacte)

### 4.1 Gestes : 0

### 4.2 Valeurs de manière : 10, décrites par leur forme (T08c)

| Tête | Ajouts (forme seule) | Valeurs, puis capacité du registre |
|---|---|---|
| `speak.tone` | `rising` (voix qui monte, rythme vif), `trembling` (voix qui tremble), `low_slow` (voix lente et basse), `drawling` (voix traînante, mots étirés) | 5 → 9 / 9 |
| `sign.kind` | `wink` (une paupière se ferme brièvement), `cover_face` (les mains sur le visage), `trace_sign` (la main trace une figure dans l'air) | 12 → 15 / 16 |
| `take.from` | `growing` (sur la plante qui pousse) | 4 → 5 / 8 |
| `work.motion` | `twist` (tordre en tournant) | 5 → 6 / 9 |
| `examine.sense` | `hear` (l'oreille contre la chose) | 5 → 6 / 9 |

Deux **élargissements de pointeur** (T08c) : `put.where` accepte `animal` ; le prédicat `member` accepte un groupe comme membre. Sa compatibilité avec `ai/tok2/golden` est testée en T09.

### 4.3 Conditions : 3 (23 → 26 / 32 ; T08b)

| Id | Arguments | Sens (lu dans la perception ou les croyances, jamais dans la vérité) |
|---|---|---|
| `c_have` | `kind`, `quantity` | j'ai au moins N choses de cette sorte apparente, d'après ce que j'ai **vu** (mains, sur moi, contenant que je porte) ou ce que je **crois** d'un contenant (`amount`) |
| `c_unwatched` | — | personne ne paraît me regarder, parmi ceux que je vois |
| `c_target_near` | `entity` | la cible paraît à portée de main ou de voix |

### 4.4 Processus : 10 de la matière et 3 du corps (31 → 44 ; T08a)

| Id | Fichier | Déclencheur | Effet |
|---|---|---|---|
| `collapse` | `matter.toml` | `load_margin` ≤ 0 ; arbre coupé au-delà de son cœur | ce qui n'est plus porté tombe : suite d'`Operation`, blessures sous la chute, débris |
| `disassemble` | `matter.toml` | `impacts` sur une matière à cohésion `built`, aux joints | rend des éléments réutilisables au lieu de débris ; la matière naturelle ne fait que se fracturer |
| `germinate` | `matter.toml` | temps ; graine en sol labouré et humide, ou trempée | pousse (`plant_stage = sprout`) ; malt |
| `separate` | `matter.toml` | choc, vent, tamis, mouvement | battage, vannage, tamisage, écrémage, barattage |
| `press_extract` | `matter.toml` | `work` en pressant ou en serrant ce qui contient un fluide | traite, pressoir, égouttage, essorage ; le lait d'une bête suit `animal_product_ready` |
| `wash` | `matter.toml` | eau (+ savon) et frottement | `dirtiness` et `grooming` baissent ; une plaie lavée s'infecte moins |
| `abrade` | `matter.toml` | `abrasiveness`, `sharpens` | refait un tranchant (`edge`), polit, rabote, lime |
| `char` | `matter.toml` | chaleur sans air | bois → charbon de bois |
| `trap_catch` | `matter.toml` | piège armé (`traps`), filet, hameçon appâté, bête qui passe | la bête est prise selon l'espèce, l'appât, la maîtrise (D29) |
| `calcine` | `matter.toml` | chaleur > 900 °C sur du calcaire | chaux ; priorité basse |
| `smell_spread` | `body.toml` | sources d'odeur (`odor`) | champ d'odeur porté par le vent ; `PLACE.smell` ; réveil P3 (O30) |
| `contagion` | `body.toml` | proximité, eau souillée, morsure | une maladie de `[[illness]]` passe (O30) |
| `illness_course` | `body.toml` | temps | incubation, symptômes visibles, guérison ou mort ; immunités (O30) |

**Naissances levées (T08d, 15 oct., P53, décision de Monsieur ; O39 close)** : `conceive` et `gestate_birth` sont au catalogue (`body.toml`, processus 44 -> 46). Aucun geste ni valeur de manière nouveau (D28, D10) : `conceive` se branche sur `touch` de manière `intimate`, déjà marquée intime et déjà refusée à tout mineur possible, et ne s'ouvre que sur la RÉCIPROCITÉ (« si deux PNJ ont fait l'action ») : deux `touch` intimes croisés, A vers B et B vers A, à moins de 1 800 s de jeu l'un de l'autre, sans tierce personne, sans couple ni mariage exigé, chacun DÉJÀ autorisé par le gouverneur dans son sens (`Governor.conception_gate`, Python seulement, à porter avec T34 avec un test de parité ; le moteur DOIT passer par cette porte) : âge RÉEL, CRU et APPARENT de chacun adultes et connus, personnes perçues, dossiers résolus ; âge inconnu, vue absente, personne hors de vue = mineur possible = déclencheur fermé. Rien de l'acte n'est représenté (fondu au noir, hors champ, D15), aucun libellé explicite. `gestate_birth` tourne sur l'horloge de vie (nouvelle valeur `life` de `PROCESS_CLOCKS`) : 105 600 s de jeu = 1,22 jour de jeu = **1 h 50 réelle** (environ 0,98 an de vie, un peu plus que les 0,75 an de O39 ; D30 : 1 jour de jeu = 1 h 30 réelle, vie = 150 h), puis le moteur crée un agent (`infant`, `biological_parents` fixé) ; le nouveau-né n'a aucun dossier et chaque témoin forme ses croyances par la perception seule (âge apparent, parenté crue). Rien de vrai dans un jeton : `fecundity`, `pregnancy`, `biological_parents` restent `visibility = engine`, sans jeton ni écrivain du modèle ; une grossesse ne se perçoit que par des signes déjà au catalogue (carrure `round`, teint `pale`). Sondes `marriage_and_children` et `pregnancy_birth` : `gap` -> `expressible` (plus aucun trou du moteur dans les sondes). Tests : `catalogue/tests/test_t08d_births.py` (13, dont les refus d'un mineur réel, cru, apparent et d'un âge inconnu ou hors de vue ; ils ne génèrent aucun contenu). Faits MOTEUR que la porte ne voit pas, à vérifier en T34 : le sexe, la parenté proche (`biological_parents`) et la fécondité (`fecundity > 0` porte la grossesse). Démographie : la cible d'une naissance par couple et par 45 h suppose 150 couples féconds en permanence ; avec 70 % d'adultes en couple le calcul donne R ≈ 0,81 (décroissance) ; T34 règle la probabilité avec un retour de densité (`fecundity` sans profil d'âge encore défini) ; aucune valeur n'est fixée ici. Reste à T34 : le moteur d'exécution.

Descriptions étendues, sans nouvel id : `cut` (une carcasse rend les produits espèce × partie), `extract` (les plantes enracinées), `absorb_evaporate` (laisse le soluté : le sel).

### 4.5 Variables : 20 (358 → 378)

| Id | Fichier, porteur | Échelle | Écrivain | Jeton | Pour quoi | Tâche |
|---|---|---|---|---|---|---|
| `g_parent` | `goals.toml`, `goal` | mref (GOAL) | T_jump | `GOAL.parent` | sous-objectifs | T08b |
| `g_has_plan` | `goals.toml`, `goal` | bool | derived | `GOAL.has_plan` | objectifs encore sans plan | T08b |
| `i_status` | `goals.toml`, `intention` | enum `running`, `suspended`, `blocked`, `done`, `abandoned` | engine (faits : `running`, `suspended` après un autre geste choisi, `blocked` après un échec perçu, `done`), T_jump (`abandoned`) | `PLAN.status` | reprise, abandon | T08b |
| `i_repeat` | `goals.toml`, `intention` | enum `once`, `each_day`, `each_season`, `each_year`, `every` | T_jump | `PLAN.repeat` | routines | T08b |
| `i_repeat_period` | `goals.toml`, `intention` | qty (heures de jeu, 1 à 2 000) | T_jump | `PLAN.repeat_period` | tours de garde toutes les 8 h, réunion tous les 2 jours (une semaine dépasserait l'année de D30) | T08b |
| `i_attempts` | `goals.toml`, `intention` | qty | engine | `PLAN.attempts` | combien de fois l'étape a échoué | T08b |
| `w_outcome` | `goals.toml`, `activity` | enum `done`, `failed`, `blocked`, `interrupted`, `limit_reached` | engine | `WAKE.outcome` | comment l'étape a fini, tel que perçu | T08b |
| `i_step_started` | `goals.toml`, `intention` | time | engine | — | **temps** : début de l'étape (sauvegardé) | T08b |
| `i_step_progress` | `goals.toml`, `intention` | ratio | engine | `PLAN.progress` (précisé) | **temps** : où en est l'étape | T08b |
| `made_at` | `properties.toml`, `provenance` (nouveau composant) | time | engine | — (vu par `pc_age_seen`) | **temps** : âge d'un objet, d'un aliment, d'un bâtiment | T08a |
| `process_progress` | `matter.toml`, `transformation` (nouveau composant) | ratio | engine | — (vu par `pc_state_seen`) | **temps** : processus en cours | T08a |
| `process_started_at` | idem | time | engine | — | **temps** : un processus survit à la sauvegarde | T08a |
| `animal_product_ready` | `world.toml`, `animal_behavior` | list (lait, laine, œufs : ratio) | engine | — (vu : pis plein, toison longue) | **temps** : ce qui se refait entre deux traites, deux tontes | T08a |
| `s_last_believed` | `society.toml`, `social_referent` | time | engine | — | **temps** : dernier moment où un dossier de PNJ vivant désignait ce groupe ; archivage après une saison sans dossier | T08b |
| `r_group_my_task` | `relations.toml`, `relation` | mref (COMMIT) | derived | `GROUP.my_task` | ma part crue dans ce groupe | T08b |
| `r_group_tasks_open` | `relations.toml`, `relation` | qty | derived (de MES croyances) | `GROUP.tasks_open` | le chef suit ses tâches en cours | T08b |
| `r_group_present` | `relations.toml`, `relation` | qty | derived (de MES percepts et croyances) | `GROUP.present` | le chef suit qui est là | T08b |
| `made_by` | `properties.toml`, `provenance` | id | engine | — | auteur réel (moteur seul) | T08a |
| `pc_age_seen` | `perception.toml`, `percept` | word (`new`, `worn`, `old`) | derived | `THING.age` (composante du vecteur : 43 → 44 / 48) | ce qu'on voit de l'âge d'une chose | T08c |
| `pp_smell_seen` | `perception.toml`, `place_percept` | list (word) | derived | `PLACE.smell` | odeurs perçues ici (O30) | T08c |

Ce qui se répartit ainsi : 7 pour les plans, 7 pour le temps, 3 pour les organisations, 3 de provenance et de perception.

**Changements du catalogue existant (T08b)** :
- `g_status` perd l'écrivain `engine` : le moteur réveille avec `goal_check`, et le modèle écrit ;
- `a_status` ne garde, côté moteur, que `open`, `expired`, `released` et `void` ; « tenu » et « rompu » sont des croyances des parties et des témoins (docs/14 § 9 a) ;
- `WAKE.cause` gagne `goal_check`, `occasion`, `idle` (ajoutés en fin) ;
- `WAKE.trigger` accepte aussi COMMIT, ENTITY et GROUP ;
- la réserve d'intentions passe de 1 à 4 (`entities.toml`) ;
- `i_steps`, `i_step_targets`, `i_speech`, `i_repeat`, `i_repeat_period` et `g_parent` deviennent écrivables par le professeur et par la tête de plan (T11).

### 4.6 Tables et champs (schéma fait par T07 le 14 oct. ; à remplir par T08a)

| Champ ou table | Où | Contenu |
|---|---|---|
| `natural_end` (**booléen**), `cadence_ms`, `productive` | chaque `[[action]]` | le geste finit seul ou demande une condition ; cycle moteur en ms réelles ; travail compressé ou non (P37) |
| `trigger`, `clock` (`real`, `calendar`, `game`), `nominal_game_s`, `consumes`, `produces` | chaque `[[process]]` | déclencheur, horloge, durée, matières en entrée et en sortie |
| `sow_seasons`, `days_to_mature`, `harvest_window_days`, `product_regrow_days` | `species.toml` (T08c) | **temps des cultures et des bêtes** |
| `[[duration_level]]` | nouvelle table | `brief` 120 s, `a_while` 1 800 s, `long` 7 200 s de jeu |
| `[[illness]]` | `body.toml` | environ 8 maladies : transmission, incubation, cours, symptômes visibles, létalité |
| `[[forgetting]]` | T05 | loi d'oubli (docs/14 § 7.5) |
| `animation.toml` | T49 (présentation) | geste + manière + objet tenu → clip |

### 4.7 Le temps : ce qui manquait, et ce qui existait déjà

**Existait** :
- monde : `game_time`, `time_of_day`, `day_of_year`, `year`, `moon_phase` ;
- PNJ : `SELF.time`, `SELF.season`, `time_felt`, `season_felt`, `g_deadline`, `g_when`, `GOAL.age`, `q_since`, `k_last_practice`, `m_when` ;
- mots : `dawn` … `night`, saisons, `hour day season year`, `span`, `at_time`, `before`, `after`, `until`, `for`, `each_day`, `each_season`, `each_year`, `habitual` ;
- horloges `WorldClock` et `LifeClock`.

**Manquait** (ajouté ci-dessus) :
- la durée des gestes (champs de T07 et `[[duration_level]]`) ;
- le début et la progression d'une étape ;
- l'âge d'un objet ;
- la progression d'un processus long ;
- les saisons de culture ;
- les routines et leur période (en heures de jeu, jamais en semaines : une année de D30 dure environ 4,7 jours de jeu) ;
- la régénération des produits animaux ;
- l'ancienneté d'un groupe sans croyants (en saisons).

## 5. Impact sur les budgets du modèle

| Budget | Avant [Mesuré] | Après | Limite |
|---|---|---|---|
| Gestes | 40 | 40 | 64 |
| Conditions | 23 | 26 | 32 |
| Têtes de manière | 35 | 35 (10 valeurs dans les capacités) | 64 |
| Variables écrivables (registre de sortie) | 94 | 98 (`g_parent`, `i_repeat`, `i_repeat_period`, `i_status`), plus la **tête de plan** (liste `plan_steps`, capacité 8) | 128 |
| Jetons par décision | 90 | **à re-mesurer par `budget.py` après T08a, T08b et T08c** (PLAN passe à 2 jetons ; GROUP, WAKE, PLACE et THING gagnent des champs, pas des jetons) | 128 |
| Mots de grammaire | 704 | à mesurer ; environ 35 mots prévus (3 conditions, 10 manières, odeurs, âges, valeurs de `i_status`, `i_repeat`, `w_outcome` et des causes) [Estimé] | 768 |
| Vecteur d'un objet | 43 | 44 (`age`) | 48 |
| Variables du catalogue | 358 | 378 | — |
| État d'un PNJ | 108 152 o | à mesurer après T08b ; ≤ 65 536 o après T06 | 65 536 o |

Point de vigilance : il reste environ 30 mots sous le plafond de 768 [Estimé]. Le prochain grand ajout de langue devra retirer des mots, ou élargir le vocabulaire, ce qui change une forme de l'entrée du modèle (nouveau schéma du registre tok-2).
