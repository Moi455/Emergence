# Architecture cible unifiée

> **Avertissement (8 octobre, soir).** Plusieurs parties de ce document sont dépassées par les décisions D17 à D26 de Monsieur (`01_decisions.md`). Là où ils divergent, **`06_architecture_expliquee.md` (révision 2) fait foi**. Principaux points dépassés : principe 5 et § 9.4 (rendu sur GPU intégré seul) ; principe 6, §§ 8.2 et 8.3 (décideur à règles, paliers) : chaque PNJ est piloté par le Transformer, partout, à pleine puissance ; § 2.2 (retour au village en bordure) : aucune limite visible, la difficulté tue avant ; § 3 et § 5 (voxels de 2 cm, couleurs seules, lumière en cache, upscaling) : voxels plus gros, textures, lumière en temps réel, pas d'upscaling ; § 3.3 et § 6 (eau et feu liés aux voxels) : au plus léger. La réécriture complète de ce document est un chantier ouvert (`CHANTIERS.md`).

Version 1.0, 8 octobre 2026. Synthèse entre trois sources : les documents d'architecture du projet (`docs/reference/`), le travail des développeurs sur les PNJ (`ai/npc_pipeline/`, `docs/npc/`) et le convertisseur d'assets (`tools/voxelizer/`). Ce document fait foi pour le code ; les documents de référence gardent le détail des calculs et des sources.

Statut des affirmations : **[Décidé]** = choix de Monsieur ; **[Proposé]** = recommandation de Claude, à valider ; **[Mesuré]** = chiffre obtenu par un test ; tout autre chiffre est une estimation à vérifier par prototype.

---

## 0. En une page

1. **Une seule vérité, tout le reste est un cache.** La vérité tient en quatre choses : la seed (et le plan du monde qu'elle produit), les chunks modifiés, le journal d'opérations, les entités (PNJ, objets, institutions). Maillages, collisions, navigation, lumière, champs d'eau et de feu sont des caches jetables, reconstruits par régions sales.
2. **L'opération est l'unité de changement du monde.** Coup de pioche du joueur, fouille d'un PNJ, feu qui ronge une poutre, chantier qui avance : tout est une `Operation`. Le même enregistrement sert à modifier les voxels, à prévenir les témoins (mémoire des PNJ), à sauvegarder et à écrire la chronique. C'est le pont entre la physique et la société.
3. **Le voxel de 2 cm n'existe que là où quelqu'un regarde ou agit.** Ailleurs, le monde est une formule (génération déterministe), un journal d'opérations et des résumés de région.
4. **Un identifiant de 16 bits par voxel, rien d'autre.** 9 bits de classe de matière (physique, feu, son) et 7 bits de teinte. Tout état dynamique (eau, chaleur, dégâts) vit dans des champs clairsemés de 25 à 50 cm.
5. **Rendu sur le GPU intégré, IA sur le GPU dédié** [Décidé]. Le rendu est dimensionné pour une Iris Xe ; l'IA apprise tourne sur le GPU dédié, avec un repli sans GPU dédié.
6. **La décision d'un PNJ ne dépend jamais de sa distance au joueur ; seule l'exécution change.** Les 500 PNJ prennent tous de vraies décisions individuelles. Près du joueur, le moteur d'action exécute le plan voxel par voxel ; loin, il le résout par sa durée et son résultat. C'est ce qui garde la cohérence quand le joueur arrive dans un village.
7. **Un contrat unique entre décision et action** (repris des développeurs) : `DecisionRequest`, `Plan`, `PlanResult`. Deux décideurs interchangeables le respectent : une référence à base d'utilités et de HTN, et un petit Transformer distillé depuis un LLM.
8. **Le langage naturel n'entre jamais dans l'état.** Le texte du joueur devient un cadre d'acte de parole ; la réponse d'un PNJ est verbalisée par un petit LLM local à partir d'un cadre. Aucun texte libre ne modifie la simulation : c'est ce qui la garde déterministe et sauvegardable.
9. **Le monde fait 20 × 20 km** [Proposé par défaut, Monsieur a dit « peut-être »], entouré de quatre frontières hostiles (mer, forêt, montagne, désert) [Décidé] dont la difficulté croît de façon exponentielle, puis d'un décor non jouable généré par la seed.
10. **500 PNJ en 5 villages** [Décidé]. Proposition : un village par frontière, plus une ville centrale de marché, avec des économies complémentaires qui obligent à circuler, échanger et se disputer l'espace.

---

## 1. Invariants (règles que le code ne doit jamais violer)

| # | Invariant | Pourquoi | Comment le vérifier |
|---|---|---|---|
| I1 | Performance d'abord : rien ne parcourt le monde entier ; tout est déclenché par un événement et borné par un budget par image | GPU intégré, CPU partagé | Profileur intégré, budgets en section 13, tests de non-régression de temps |
| I2 | Génération bit-exacte depuis (seed, paramètres, version du générateur, position) | Seuls les deltas sont sauvegardés | Empreintes de chunks sur un jeu de seeds de référence, comparées entre plateformes et compilateurs |
| I3 | Une seule source de vérité ; aucun système ne garde sa propre copie | Cohérence, sauvegarde légère | Revue de code : un cache doit pouvoir être effacé et reconstruit |
| I4 | Toute modification du monde passe par une `Operation` | Rejeu, témoins, sauvegarde | Les fonctions d'écriture de voxels sont privées au module `ops` |
| I5 | La matière est conservée : ce qui est creusé devient une quantité quelque part | Économie et crédibilité | Tests de conservation (comme ceux de la négociation des devs) |
| I6 | Le texte libre n'entre jamais dans l'état de simulation | Déterminisme, sécurité | Le verbaliseur n'a aucun accès en écriture |
| I7 | Règles dures du moteur, jamais apprises : aucun acte romantique ou sexuel impliquant une catégorie d'âge enfant ou adolescent, comme acteur ou cible | Légal, plateforme, éthique | Validateur de plan + réflexe ; tests dédiés (déjà présents dans `generate_states.py --check`) |
| I8 | Formats versionnés dès le premier jour (sauvegarde, schéma des jetons, modules voxel) | Évolution sans casser les parties | `schema_version` dans chaque enregistrement |
| I9 | Aucun secret dans le dépôt (clé Gemini, jetons) | Une clé a déjà fuité dans une conversation | Variables d'environnement seulement ; scan des secrets en CI |

---

## 2. Le monde

### 2.1 Échelle

| Grandeur | Valeur | Conséquence |
|---|---|---|
| Carte jouable | 20 × 20 km [Proposé par défaut] | 400 km², plan du monde à 16 m = 1 250 × 1 250 cellules (1,6 million), quelques Mo |
| Profondeur | 500 m sous le niveau de référence [Décidé le 7 oct. pour 50 km, conservé] | Grottes décrites comme un réseau dans le plan |
| Altitude | jusqu'à 3 km, sur la frontière montagne | Visible de partout : le lointain doit être dessiné (voir `docs/reference/monde_horizon.md`) |
| Chunk | 64³ voxels = 1,28 m | 15 625 chunks par côté ; air et roche pleine implicites, jamais alloués |
| Coordonnées | indice de chunk entier + décalage flottant ; rendu relatif à la caméra ; origine déplacée tous les 1 à 2 km | Pas besoin de double précision |

Passer de 50 à 20 km divise par six la surface : plan du monde, tuiles lointaines et sauvegarde rétrécissent d'autant. Les solutions du document « Monde de 20 km et horizon lointain » (`docs/reference/monde_horizon.md`) restent valables.

### 2.2 Les quatre frontières : « on pourrait aller plus loin »

Objectif de Monsieur : le joueur doit toujours croire qu'il existe un monde magique derrière, sans jamais pouvoir vraiment y aller. Proposition : **un champ d'hostilité** plutôt qu'un mur.

- **Les marches font partie de la carte de 20 km** : une bande de 3 km de large (5 km côté montagne) autour d'un cœur habité d'environ 14 × 12 km. La limite intérieure de la marche suit le terrain.
- Chaque point de la marche a une hostilité `H(d) = 2^(d / 300 m)` (`2^(d / 500 m)` côté montagne), où `d` est la distance à la limite intérieure. H double tous les 300 m : doubler son équipement fait gagner une distance fixe, donc on progresse à chaque essai sans jamais passer. Au bord de la carte (3 km), H vaut environ 1 000. Le décor de seed commence au bord de la carte.
- H n'est pas une règle à part : il **alimente les systèmes existants**. Il multiplie la soif, le froid, la fatigue, le coût de déplacement, la fréquence des tempêtes, la densité des créatures, la probabilité de se perdre. Rien de nouveau à coder, seulement des entrées supplémentaires aux mêmes formules.
- **Orientation par défaut** [Proposé, P16] : mer à l'ouest, montagne au nord, désert à l'est, forêt au sud, tirée de la seed. Elle suit le climat : le vent dominant vient de la mer et laisse sa pluie sur la forêt et les montagnes, le désert est le côté le plus éloigné de la mer. Les coins sont des transitions (fjords, plateau aride, steppe arborée, marais côtiers).
- Chaque frontière a sa physionomie :

| Frontière | Ce qui monte avec H | Ce que l'on voit au loin |
|---|---|---|
| Mer | Houle, courants qui ramènent au rivage, tempêtes, brouillard | Îles et côtes lointaines générées par la seed, lumières la nuit |
| Forêt | Densité, obscurité sous la canopée, arbres de plus en plus gigantesques, orientation qui dérive, bêtes | Un mur d'arbres immenses qui dépasse les collines |
| Montagne | Froid, altitude, avalanches, parois verticales ; sommets à 3 km | Chaînes et cols enneigés, une silhouette de citadelle sur un col |
| Désert | Chaleur, soif, tempêtes de sable, mirages | Mirage d'une ville à l'horizon, qui recule quand on avance |

- **Pas de contournement.** H s'applique aussi sous terre (roche plus dure, galeries inondées, air qui manque, jusqu'au fond du monde à −500 m) et à la repousse d'une forêt défrichée : ni un tunnel ni un défrichement collectif ne passent sous la règle.
- **Pas de mur invisible.** À la limite absolue, un événement narratif ramène le joueur (« des bergers vous ont trouvé inconscient à la lisière »). Il devient une histoire que les PNJ racontent.
- **Le monde derrière est aussi une construction sociale** [idée nouvelle]. Les PNJ portent des croyances sur l'au-delà (légendes, documents, récits de voyageurs), propagées par le même système de rumeurs que le reste. De rares voyageurs « venus de derrière » arrivent naufragés ou mourants, avec un récit fragmentaire et invérifiable ; ils ne peuvent jamais servir de guide, sinon le joueur leur demanderait le chemin et l'illusion tomberait. Le rêve du joueur est nourri par la société, pas par un texte figé.
- Le décor au-delà du bord de la carte est généré par la seed à très basse résolution (relief à 128 m, puis 512 m au-delà de 50 km, jusqu'à l'horizon), jamais voxelisé.

### 2.3 Cinq villages, cinq économies [Proposé]

| Village | Lieu | Ressources et métiers | Ce qu'il doit acheter |
|---|---|---|---|
| Port | côte, côté mer | pêche, sel marin, charpenterie navale | bois, grain, outils |
| Forestiers | lisière de la forêt | bois, chasse, résine, herbes | sel, métal, grain |
| Mineurs | contreforts de la montagne | pierre, minerai, forge | nourriture, bois de mine |
| Oasis | bord du désert | verre, teintures, caravanes, épices | eau, bois, nourriture |
| Bourg central | carrefour des routes | marché, grain, institutions (seigneurie, culte, tribunal) | tout, en échange de protection et de débouchés |

Environ 100 habitants chacun, dont 5 PNJ « avancés » (mémoire plus grande, plus de décisions) comme dans le projet des devs. Le bourg est au centre du cœur habité et chaque village près de sa frontière : 4 à 6 km entre un village et le bourg, 7 à 11 km entre villages voisins. À ×6, 5 km font environ 6 h de jeu à pied : aller au bourg prend une demi-journée et on y dort souvent avant de revenir, ce qui crée des rencontres. Les déplacements sont réels et coûtent. Aucun village n'est autosuffisant, donc le commerce, les mariages entre villages, les vols et les conflits pour les terres naissent sans script.

Gestion de l'espace : les parcelles, pâturages, coupes de bois et carrières ont un propriétaire (individu, famille ou institution) ; la carte est finie, donc la croissance crée des tensions. La population suit les naissances et les décès autour de 500, avec une capacité de charge par village fixée par la nourriture.

### 2.4 Échelle de temps [Proposé]

Un jour de jeu dure 4 heures réelles (temps accéléré ×6). Toutes les durées de ce document sont en temps de jeu sauf mention contraire.

### 2.5 Résumé de région

La société ne lit jamais les voxels. Elle lit un résumé indexé sur des cellules de 64 m (4 × 4 cellules du plan à 16 m, environ 100 000 sur la carte) : terrain, ressources, propriétaires, danger, hostilité H. Il remplace la « grille 2D » du catalogue de variables des devs et se met à jour par les opérations.

### 2.6 Génération

Inchangé par rapport à `docs/reference/architecture_v1.md` § 1 bis : plan du monde calculé une fois à la création de la partie (relief, érosion, rivières, géologie, biomes, sites des villages, routes, hostilité des frontières), puis génération locale de chaque chunk en interrogeant ce plan. Flottants stricts ou entiers, hachages entiers, aucune génération de vérité sur GPU. Le détail visuel sous la brique peut être recalculé par le GPU avec le même bruit entier (solution 5 du document de rendu).

---

## 3. Représentation des voxels

### 3.1 Hiérarchie

| Niveau | Taille | Contenu | Rôle |
|---|---|---|---|
| Région (fichier) | 32³ chunks ≈ 41 m | index Morton des chunks modifiés | sauvegarde, streaming disque |
| Chunk | 64³ voxels = 1,28 m | 8³ briques de stockage | unité de génération, de maillage, de sale |
| Brique de stockage | 8³ voxels = 16 cm | uniforme (2 octets) ou palette locale + 1 à 4 bits par voxel | compacité en RAM ; même granularité que le format VXP du convertisseur |
| Micro-brique de rendu | 4³ voxels = 8 cm | masque d'occupation de 64 bits + indices de palette | micro-tracé dans le pixel shader (anneau 0) |

Les mesures du convertisseur confirment le choix des briques 8³ : c'est la taille qui donne le meilleur compromis sur les six pièces testées [Mesuré, `tools/voxelizer/docs/benchmark_encodages.md`].

### 3.2 L'identifiant de voxel : classe de matière + teinte [Proposé, idée nouvelle]

Le benchmark des devs montre que **la couleur coûte 10 fois plus que la géométrie** (4,5 à 5,6 bits par voxel contre 0,2 à 1,3) [Mesuré]. L'architecture prévoyait un voxel « matière seule » avec des variations calculées dans le shader ; le convertisseur, lui, garde une couleur par voxel issue des textures. Synthèse :

```
VoxelId (u16) = classe (9 bits, 512 matières physiques) << 7 | teinte (7 bits, 128 nuances)
```

- La **classe** porte tout ce qui compte pour la simulation : résistance, densité, inflammabilité, son, outil requis. La physique, le feu et l'IA lisent `id >> 7`.
- La **teinte** indexe une rampe de 128 couleurs propre à la classe (en OKLab, comme le convertisseur). Elle ne sert qu'au rendu.
- Le shader ajoute la micro-variation procédurale par position (gratuite).
- Le convertisseur projette sa palette k-means locale sur les rampes des classes : une brique « mur en plâtre » devient la classe *plâtre* avec 3 à 8 teintes. On garde la richesse des textures sans payer une couleur 24 bits par voxel.
- Les palettes locales des briques de stockage s'appliquent sur ces 16 bits : une brique à 6 identifiants distincts coûte 3 bits par voxel.
- **Règle de maillage** : le maillage greedy fusionne sur la classe seule ; la teinte est lue dans la brique par le shader (vertex pulling). Fusionner sur l'identifiant complet multiplierait les quads de tout ce qui sort du convertisseur.
- **Règle de génération** : le terrain généré écrit la teinte 0 et laisse la variation au bruit du shader ; seuls les modules convertis et les éditions portent une teinte explicite. Sinon les briques de terrain perdent leur uniformité (2 octets) et la RAM explose.

### 3.3 État dynamique

Rien dans le voxel. Champs clairsemés : eau en hauteurs par colonnes de 25 cm et bassins abstraits ; feu à 25 ou 50 cm (température, combustible, humidité, ouverture à l'air) ; dégâts et usure par brique quand c'est utile. Voir `docs/reference/architecture_v1.md` §§ 9 et 10.

---

## 4. Le bus d'opérations [Proposé, idée centrale]

Le document d'architecture faisait de l'opération l'unité de sauvegarde et de matérialisation paresseuse. Le projet des devs fait du chantier « par différence » le moteur de construction, et de la perception d'événements la source de la mémoire des PNJ. Ces trois idées sont la même : **un événement compact, rejouable, perceptible**.

```
Operation {
  id, tick, author (entité ou système), cause_id (opération ou décision qui l'a déclenchée)
  kind: dig | place | fill | burn | collapse | build_step | till | cut_tree | ...
  shape: (forme paramétrique : boîte, sphère irrégulière de pioche, module + transformation)
  tool, material_in, material_out, seed
  effects_summary: quantités déplacées, propriétaire touché, dégâts
  perceptibility: bruit (dB), visibilité (rayon, lumière), trace laissée
}
```

Abonnés, chacun avec son propre budget et sa propre résolution :

| Abonné | Ce qu'il fait de l'opération |
|---|---|
| Voxels | applique la forme sur les chunks chargés, ou la met en attente si la zone n'est pas chargée (matérialisation paresseuse) |
| Caches dérivés | marquent leur région sale : maillage, collisions, navigation, lumière, stabilité, champs |
| Perception | calcule les témoins possibles (rayon de bruit, lignes de vue sur l'occupation grossière) et leur envoie un événement perçu, avec rôle, source, degré de compréhension |
| Mémoire des PNJ | chaque témoin enregistre un souvenir (consolidé, avec oubli), comme dans `memory_service.py` |
| Propriété et normes | si l'opération touche un bien d'autrui, le moteur social calcule la violation de norme (vol, vandalisme) pour les témoins |
| Persistance | ajoute l'opération au journal de la région ; la compaction fusionne les opérations matérialisées dans les deltas |
| Chronique | garde les opérations marquantes (un pont détruit, une mine ouverte) comme histoire du monde |

Conséquence : le cas 30 des devs (« événement, perception, mémoire, rumeur, réputation, relation, comportement ») devient une propriété du moteur et non un scénario. Un pont qu'un PNJ a détruit hors de la vue du joueur existe comme opération ; les témoins s'en souviennent ; quand le joueur arrive, les voxels sont matérialisés depuis la même opération.

---

## 5. Rendu

Résumé de `docs/reference/rendu_voxels_igpu.md`, qui garde le détail et les sources.

- Anneaux de LOD : la taille des voxels double quand la distance double (2 cm jusqu'à ~10 m en 720p interne), donc un coût à peu près constant par anneau.
- Anneau 0 : micro-briques de 8 cm dessinées comme des faces, détail 2 cm tracé dans le pixel shader (masque de 64 bits, une dizaine de pas au plus).
- Lumière mise en cache dans le monde et recalculée seulement après une modification ; ombres en cascades mises en cache.
- Une passe légère (forward + pré-passe de profondeur ou visibility buffer), rendu 720p, upscaling temporel vers 1080p.
- Au-delà de ~640 m : cubemap avec profondeur, mis à jour une face par image ; au-delà de ~5 km, relief du plan du monde en geometry clipmap ; puis le décor de seed jusqu'à l'horizon (196 km depuis un sommet de 3 km). La carte n'occupe que les 28 premiers km de la vue depuis un sommet : le décor porte presque tout le lointain.
- Modules issus du convertisseur partagés et instanciés, copiés dans les chunks seulement au premier coup (copie à l'écriture), avec une usure tirée de la graine de chaque instance.
- Budget : 22 ms sur 33 ms à 30 images/s sur Iris Xe, à vérifier par les 7 prototypes du document de rendu.

---

## 6. Physique, eau, feu, effondrements

Inchangé : `docs/reference/architecture_v1.md` §§ 7 à 11. Jolt pour les corps rigides (boîtes fusionnées de 4 à 8 cm, plafond d'environ 200 corps actifs) ; stabilité en deux étages (connectivité bornée, puis graphe porteur grossier) ; eau en tuyaux virtuels par colonnes et bassins ; feu sur champ clairsemé couplé à l'ouverture à l'air. Les outils des devs (pioche irrégulière, pelle nette, truelle précise, mains qui ne cassent pas les blocs) deviennent les formes des opérations de creusement.

---

## 7. Assets et construction

Une seule chaîne relie le fichier 3D, le rendu, la simulation et les chantiers des PNJ.

```
fichier 3D (.obj/.gltf) ──► voxelizer ──► module VXP (classe+teinte, intérieur plein, LOD)
                                              │
                         bibliothèque de modules (stockés une fois)
                                              │
        générateurs (villages, maisons, mobilier) ──► blueprint = liste d'instances de modules
                                              │
                   chantier par différence (build_site) ──► opérations build_step
                                              │
                         voxels du monde (copie à l'écriture au premier coup)
```

- **Le convertisseur** (`tools/voxelizer`) fait déjà l'essentiel : voxelisation conservative, remplissage, bouchage des murs ouverts, palette OKLab, format VXP compact à accès aléatoire, 50 tests qui passent [Mesuré]. Ce qui manque est listé dans `docs/03_confrontation.md`.
- **Le blueprint** des devs (`build_site.py`) devient une liste d'instances de modules plutôt qu'une liste de blocs. Le principe « le travail est toujours la différence entre le plan et le monde » est gardé tel quel : il ne peut pas se corrompre et il guérit après vandalisme.
- **Le mode rituel des devs** (la sorcière qui finit le chantier une fois les matériaux réunis) est exactement le mécanisme de matérialisation des chantiers lointains : hors de la vue, un chantier avance par sa durée ; quand le joueur arrive, la différence restante est appliquée en voxels. On garde les deux modes, et le mode rituel devient aussi un mécanisme de jeu (sorcière payante, corruptible, parfois indisponible).
- **Les connecteurs** [idée nouvelle] : chaque module porte des points d'attache (mur-mur, mur-toit, porte-cadre) pour que les générateurs assemblent sans trous. Le kit voxelisé par les devs (176 pièces) en a besoin.
- Les baguettes de métier [Décidé] sont des outils d'opération : une baguette prêtée limite la précision et les formes permises ; la technique est un savoir-faire transmis de maître à apprenti et peut se perdre (compteur de détenteurs par technique).

---

## 8. Société : architecture des PNJ

### 8.1 Trois couches (reprises des devs, validées)

| Couche | Rôle | Ne fait jamais |
|---|---|---|
| Données (déterministe) | monde, variables des PNJ, mémoire, croyances, titres, documents, institutions, langage | décider |
| Décision | construit le contexte, choisit une intention, produit un `Plan`, ajuste quelques états bornés | bouger, creuser, stocker un souvenir |
| Action | exécute le plan, surveille les conditions d'arrêt et d'interruption, renvoie un `PlanResult` | choisir un but, juger quelqu'un |

Interface (inchangée, `docs/npc/npc_architecture_v0.4.md`) :

```
DecisionRequest { npc, reason: plan_done | interrupted | event | idle_timeout, tokens }
Plan            { steps: [ { f, a:{args}, until:[...], interrupt_if:[...] } ... ], on_done }
PlanResult      { plan_id, status: done | interrupted | failed, reason, step, progress, gains, notable_events[] }
```

Un plan de 15 blocs de fouille est une décision, pas quinze. Le réseau n'est réveillé que quand un plan finit, échoue ou est interrompu. Interruptions : conditions du plan, réflexes (attaqué, blessé, outil cassé), saillance filtrée par les variables du PNJ.

### 8.2 Deux décideurs, un seul contrat [Proposé]

Le document d'architecture recommandait l'Utility AI et le HTN ; les devs ont construit un Transformer distillé qui **note des intentions candidates** proposées par le moteur, avec des plans de travail venant d'un expert scripté. Ce sont en réalité la même architecture : le moteur propose les actions possibles, une fonction note chaque intention, un planificateur déroule l'intention en étapes. Seule la fonction de notation change.

| Décideur | Notation des intentions | Déroulement en plan | Où il tourne | Rôle |
|---|---|---|---|---|
| Référence | utilités lisibles (courbes sur besoins, traits, relations, normes) | HTN des métiers et modèles de plans | CPU, quelques µs | repli sans GPU dédié, base de comparaison, amorçage des données |
| Élève | Transformer distillé (5 à 30 M de paramètres), entrée en jetons numériques | même HTN et mêmes modèles | GPU dédié, par lots, inférence entière | décideur principal quand un GPU dédié existe |

Règle reprise des devs : **l'élève doit battre la référence** sur les 30 cas de capacités en paires minimales pour mériter sa place.

### 8.3 Paliers de simulation pour 500 PNJ [Proposé]

Avec 500 habitants, tous peuvent être simulés individuellement ; aucun agrégat de population n'est nécessaire.

| Palier | Qui | Décision | Exécution | Perception |
|---|---|---|---|---|
| 0 | ≤ 64 PNJ à moins de ~50 m du joueur ou en interaction | complète, à chaque fin de plan | voxel par voxel, chemin fin sur grille de 25 cm | complète |
| 1 | le reste du village du joueur (~100) | complète | actions résolues par leur durée, trajets sur graphe sans collisions | événements du village, bruit et vue simplifiés |
| 2 | les 4 autres villages (~400) et les voyageurs | complète, mêmes entrées | résolution horaire : résultats et opérations enregistrées, matérialisées à l'arrivée du joueur | événements du village et des routes |

La décision est la même à tous les paliers (principe 6 de la page 1) ; c'est la fidélité de l'action et de la perception qui baisse. Quand le joueur arrive, rien ne « saute » : les PNJ sont là où leur plan les a menés, et les voxels de leurs opérations apparaissent.

### 8.4 Mémoire

`memory_service.py` est gardé comme référence (consolidation, oubli exponentiel, rappel, versions concurrentes, transmission avec dérive, croyances, réputation, lieux, liens entre tiers ; 16 tests). Changements pour l'échelle :

- Budgets : ~300 souvenirs pour un PNJ léger, ~1 000 pour un avancé (chiffres des devs). Pour 500 PNJ dont 25 avancés : environ 167 000 souvenirs, une dizaine de Mo à ~64 octets chacun.
- **Index** par participant, lieu et type à la place du balayage linéaire actuel (point signalé par les devs).
- **Faits partagés stockés une fois** : un événement du monde (une opération) est un fait unique ; chaque souvenir pointe dessus avec sa source, sa certitude et sa version. C'est déjà l'idée de `event_ref` chez les devs.
- **Contenu des souvenirs** (point 4 de leur liste) : objet, gravité, norme violée, tiers, suite. Indispensable pour « E2 a volé mon blé ».

### 8.5 Couche village et institutions (le manque principal)

Le cas 29 des devs (groupes aux intérêts divergents) n'a pas de moteur, et leur générateur n'a aucune variable de village. Avec 5 villages décidés, c'est la priorité de la société.

- **Institution = entité de données** : famille, foyer, atelier, guilde, village, culte, seigneurie, bande. Elle a des membres et des rôles, des ressources, des normes (comme données), des règles d'appartenance et de décision.
- **Titres et autorité** (déjà conçus par les devs) : un titre est un nom plus les croyances des PNJ ; aucune vérité globale sur qui est maire.
- **Économie** : offre et demande par village ; les prix locaux viennent des stocks et des besoins ; caravanes et colporteurs sont des PNJ qui marchent vraiment sur les routes.
- **Relations entre villages** : agrégées depuis les relations individuelles (mariages, dettes, vols, rancunes) plus des événements collectifs (fête, foire, raid, épidémie).
- **Jetons nouveaux pour le décideur** : village (prospérité, tension, autorité perçue), groupe, lieu, objet, lien (déjà spécifiés dans `schema.json` mais pas émis).

### 8.6 Transmission des métiers

Un métier est une donnée (devs : `job` = outils, compétences, recettes, lieux, intentions offertes, revenu). Une technique a une liste de détenteurs ; l'apprentissage est une relation maître-apprenti dans la durée, avec une baguette prêtée ; une technique disparaît avec son dernier détenteur [Décidé].

---

## 9. IA apprise : données, entraînement, exécution

### 9.1 Ce qui existe (devs)

Un générateur de 24 familles de situations avec 18 invariants vérifiés, un prompt de teacher, un client Gemini avec limiteur de débit, un pipeline de bout en bout testé contre un faux serveur, un outil d'étiquetage à l'aveugle. **Aucune étiquette réelle, aucun modèle entraîné** [README des devs]. La sonde de l'API a fonctionné le 5 octobre.

### 9.2 Ordre proposé (celui des devs, complété)

1. Brancher `representation.py` : le teacher voit des entiers -10..+10 (ou 0..10 pour les variables unipolaires), plus les 5 symboles grossiers. C'est le défaut le plus grave : les étiquettes ne peuvent pas être plus fines que ce que voit le teacher.
2. Ajouter ambition et tolérance, la couche village, le contenu des souvenirs.
3. Corpus de 1 000 situations, rapport, paires de sensibilité avec témoin de bruit.
4. Pilote Gemini réel, 100 étiquettes à l'aveugle, mesure d'accord.
5. Seulement ensuite, le gros jeu de données.
6. **[Idée nouvelle] Boucle avec le simulateur sans rendu.** Le générateur synthétique ne couvre pas la distribution des états que le jeu produit vraiment. Une fois le simulateur social en place, on fait tourner l'élève (ou la référence) pendant des années simulées, on échantillonne les états réellement visités, surtout ceux où l'élève et la référence divergent, on les fait noter par le teacher, puis on réentraîne (principe DAgger). Le générateur synthétique reste pour l'amorçage et les cas rares.

### 9.3 Exécution

- Inférence **entièrement en entiers** (INT8 avec accumulation INT32, approximations entières de softmax et de normalisation, style I-BERT) pour obtenir les mêmes décisions sur tout matériel, avec un tirage par graine propre à chaque PNJ.
- Sur le GPU dédié par lots, via compute Vulkan (même API que le rendu de Godot, indépendante du fabricant) ; ONNX Runtime peut servir pour prototyper.
- Coût estimé : un modèle de 10 M de paramètres avec ~45 jetons coûte ~1 milliard d'opérations par décision ; 500 PNJ font environ 10 à 30 décisions par seconde (un plan dure de quelques dizaines de secondes à quelques minutes de jeu), soit moins de 30 milliards d'opérations par seconde : une petite fraction d'une RTX 3060 portable.
- VRAM du GPU dédié (6 Go chez Monsieur) : élève < 100 Mo ; verbaliseur LLM de type 2 milliards de paramètres quantifié en 4 bits, environ 1,5 à 2,5 Go avec son cache ; le reste en marge. À mesurer.

### 9.4 Profils matériels des joueurs

| Matériel | Rendu | Décision des PNJ | Verbaliseur |
|---|---|---|---|
| GPU intégré + GPU dédié (portables, cas de Monsieur) | intégré | élève sur dédié | dédié |
| Un seul GPU dédié (PC de bureau) | dédié | élève en compute asynchrone basse priorité, budget fixe par image | dédié, ou répliques préécrites |
| GPU intégré seul | intégré | référence sur CPU | répliques préécrites à partir des cadres |

---

## 10. Langage du joueur

Repris des devs (`utterance_parser.py`, 15 tests) : surlignage orange (concepts connus), bleu (mots logiques), vert (entités, lieux, titres), rouge (inconnus avec suggestions) ; cadre d'acte de parole (acte, force 0..3, politesse -2..+2, modalité, négation, contenu). Le même cadre sert aux échanges entre PNJ. Repli : analyse contrainte en JSON par le LLM local, validée contre le même schéma.

Question ouverte : l'analyseur est en anglais. Le jeu sera-t-il jouable en français ? Voir `docs/01_decisions.md`.

---

## 11. Persistance

Une sauvegarde = seed, paramètres et version du générateur, plan du monde, régions de chunks modifiés (stockés entiers, compressés zstd), journal d'opérations non matérialisées, entités (PNJ, objets, institutions), chronique. Écriture incrémentale des régions sales, journal anti-plantage, compaction régulière. Pour 500 PNJ : environ 32 Mo d'état social (souvenirs, relations, croyances), à mesurer. Cible : moins de 500 Mo après 100 heures.

---

## 12. Moteur, langages et organisation du code [Proposé]

| Partie | Technologie | Raison |
|---|---|---|
| Hôte du jeu | Godot 4 (≥ 4.6, Jolt intégré) | léger, sans redevance, accès Vulkan bas niveau |
| Cœur | bibliothèque C++20 indépendante du moteur, liée par GDExtension | performances, déterminisme, hôte remplaçable |
| Simulateur sans rendu | exécutable C++ qui lie le même cœur | avec le décideur de référence : 1 an de jeu en moins de 10 minutes, 50 ans en une nuit ; source de données d'entraînement |
| Outils hors ligne | Python 3 (voxelizer, pipeline de données, entraînement PyTorch) | déjà écrits, itération rapide |
| Inférence | compute Vulkan en entiers | indépendante du fabricant, déterministe |

Modules du cœur (voir `engine/README.md`) : `world` (plan, génération, chunks), `ops` (bus d'opérations), `mesh`, `light`, `fields` (eau, feu), `phys` (pont Jolt), `stability`, `nav`, `relevance` (paliers et LOD), `society` (données, mémoire, croyances, institutions), `act` (moteur d'action), `decide` (référence et élève), `lang` (cadres), `persist`.

**Le code Python des devs devient l'oracle des tests.** Chaque module porté en C++ (mémoire, règles sociales, protocoles de dialogue, chantier, contrat de plan, analyseur) doit reproduire les sorties de sa version Python sur les mêmes entrées. On garde la version Python comme spécification exécutable.

---

## 13. Budgets chiffrés (machine de référence : Iris Xe + RTX série 3000 6 Go, 16 Go de RAM)

| Ressource | Budget |
|---|---|
| Image | 33 ms (30 images/s), dont 22 ms de GPU intégré prévus |
| CPU, thread principal | 8 ms par image |
| CPU, simulation sociale (500 PNJ, paliers 0 à 2) | ≤ 3 ms par image en moyenne, sur threads de travail |
| Coup de pioche de bout en bout | ≤ 2 ms (maillage, collisions, navigation, lumière, stabilité, témoins) |
| VRAM du GPU intégré | ≤ 1 Go |
| VRAM du GPU dédié | ≤ 4 Go (élève + verbaliseur) |
| RAM du jeu | ≤ 4 Go |
| Sauvegarde | ≤ 500 Mo après 100 h |

---

## 14. Risques principaux

| Risque | Gravité | Parade |
|---|---|---|
| Rendu 2 cm éditable sur GPU intégré : aucun précédent | élevée | prototypes de rendu 1, 2 et 4 en premier ; repli : anneau 0 réduit à 6 m |
| Transition abstrait → détaillé (chantier, PNJ) incohérente | élevée | décision identique à tous les paliers ; opérations déterministes ; tests « revenir après 10 ans » |
| L'élève n'apprend pas mieux que la référence | moyenne | référence d'abord ; paires minimales ; boucle avec le simulateur |
| Teacher peu sensible aux écarts fins ou filtré sur les scènes violentes | moyenne | paires de sensibilité avant tout gros run ; rejets suivis par famille |
| 111 fonctions de plan = énorme production d'animations et d'effets | élevée | tranche verticale d'abord (travail, parole, avis, un vote) |
| Contenu à 2 cm : volume de modélisation | élevée | convertisseur + générateurs + connecteurs ; usure par graine |
| Analyseur de langage : couverture réelle inconnue | moyenne | journaliser chaque échec en playtest ; repli LLM contraint |
| Romance entre adultes apparentés autorisée par défaut | faible | vérifié le 8 oct. : la règle Steam vise le contenu sexuel explicite ; rien de sexuel ni montré, norme de tabou forte par défaut, interrupteur `--no-adult-kin-romance` prêt |
| Contenu généré en direct par le verbaliseur | moyenne | déclaration Steam « live-generated » avec garde-fous (O7) ; le verbaliseur ne parle qu'à partir de cadres validés |

---

## 15. Comment faire évoluer ce document

- Une idée nouvelle va d'abord dans `docs/05_idees.md` avec le gabarit prévu.
- Elle entre ici quand elle a un prototype et un critère de réussite mesuré, ou quand Monsieur la décide.
- Toute décision prise va dans `docs/01_decisions.md` avec sa date et son auteur.
