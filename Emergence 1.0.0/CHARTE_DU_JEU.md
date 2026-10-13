# CHARTE DU JEU

## 1. Vision

Le jeu doit donner au joueur la sensation d’entrer dans **un monde qui existe réellement**, et non dans un ensemble de niveaux, de quêtes et de contenus préparés pour lui.

C’est un monde médiéval-fantastique vivant, persistant, vaste, physique et social, dans lequel le joueur peut construire une existence complète : travailler, voyager, se faire des amis, tomber amoureux, fonder une famille, posséder une maison, apprendre un métier, devenir artisan, marchand, militaire, propriétaire, criminel ou dirigeant, partir à l’aventure, vivre simplement ou chercher à transformer la société qui l’entoure.

L’objectif fondamental n’est pas de raconter une histoire écrite par les développeurs. **L’objectif est de construire un système capable de produire des histoires.**

Le développeur ne doit donc pas chercher à prévoir ce que le joueur vivra. Il définit les règles, les possibilités fondamentales, les contraintes et le cadre esthétique du monde. Ensuite, le monde fonctionne.

Les situations, les relations, les conflits, les alliances, les trajectoires individuelles, les familles, les sociétés et les événements résultent de cette simulation.

> **Le développeur écrit les règles et les possibilités fondamentales ; la simulation produit les situations, les histoires, les relations et les sociétés.**

Le jeu doit pouvoir produire des situations dont le développeur lui-même ne connaît pas la forme à l’avance.

---

# 2. Un monde, pas un décor

Le monde est un espace physique d’environ **20 × 20 km**, soit 400 km². Il est composé de voxels extrêmement fins, de l’ordre de quelques centimètres, afin de permettre une destruction et une transformation réellement physiques du terrain et des constructions.

Le monde est généré à partir d’une **graine**. Chaque partie possède donc sa propre organisation géographique et sociale.

La génération détermine notamment la topographie, les paysages, les cours d’eau, les forêts, les villages, les constructions, les ressources, la répartition des populations ainsi que de nombreux éléments de l’histoire initiale du monde.

La génération procédurale n’est toutefois pas l’émergence elle-même. Elle constitue la manière dont le développeur distribue aléatoirement les éléments qu’il a conçus.

Le développeur définit le vocabulaire du monde : types de reliefs, végétation, architectures, matériaux, phénomènes, structures sociales possibles, personnalités, comportements, capacités, etc.

La graine décide ensuite **quelle combinaison particulière de ces éléments existe dans cette partie**.

Un monde peut ainsi posséder une cascade à un endroit, une vallée à un autre, un village isolé dans une forêt, une famille vivant dans une ferme éloignée, une zone marécageuse dangereuse ou une personne singulière vivant seule dans les montagnes.

Le monde ne doit jamais donner l’impression d’être une succession de biomes copiés-collés. L’exploration doit produire de véritables découvertes.

---

# 3. Le monde existe indépendamment du joueur

Le joueur n’est pas le centre ontologique du monde.

Les 500 PNJ environ doivent continuer à vivre, réfléchir, travailler, se déplacer, se rencontrer, se disputer, aimer, vieillir, mourir, fonder des familles et prendre des décisions même lorsque le joueur est ailleurs.

Si le joueur quitte un village et revient cinq années plus tard, il ne doit pas retrouver le village dans l’état où il l’a laissé.

Des gens peuvent être morts. Des enfants peuvent être devenus adultes. Des couples peuvent s’être formés ou séparés. Des entreprises peuvent avoir prospéré ou disparu. Une personne peut avoir changé de métier. Un conflit peut avoir éclaté. Un nouveau dirigeant peut être arrivé au pouvoir. Une maison peut avoir changé de propriétaire.

Le monde continue donc **sans attendre le joueur**.

La simulation logique doit rester active même lorsque la représentation graphique détaillée d’une zone ne l’est pas. Le rendu est une matérialisation locale du monde ; il ne constitue pas son existence.

---

# 4. Le monde est créé avant l’arrivée du joueur

Le monde doit avoir une existence antérieure au joueur.

Les habitants possèdent une histoire, des relations, des souvenirs, des habitudes, des connaissances et des opinions avant même que le joueur les rencontre.

Cette histoire n’a pas besoin d’être écrite sous forme de scénario.

Elle peut être produite par la génération et la simulation initiale du monde. Le joueur arrive donc dans une société qui a déjà vécu.

Lorsqu’un joueur incarne un personnage existant, il peut recevoir une synthèse de ce que ce personnage sait déjà : son histoire connue, ses relations, ses connaissances, ses habitudes et les éléments pertinents de son environnement.

Il ne reçoit pas pour autant la vérité absolue du monde.

---

# 5. Le joueur n’est pas omniscient

Le joueur possède une connaissance du monde comparable, dans son principe, à celle d’un être vivant dans ce monde.

Il voit ce qui est observable. Il se souvient de ce qu’il a vécu. Il apprend ce qu’on lui raconte. Il peut déduire, se tromper, être trompé et croire à des informations fausses.

Les PNJ fonctionnent selon le même principe.

Un PNJ ne connaît pas directement les variables internes d’un autre PNJ. Il ne sait pas automatiquement qu’une personne est jalouse, qu’elle ment, qu’elle a peur ou qu’elle a commis quelque chose hors de sa présence.

Il peut seulement l’inférer à partir de ce qu’il perçoit, de ce qu’on lui dit, de ses souvenirs et de son modèle du monde.

Les rumeurs, mensonges, erreurs de perception, omissions, secrets et fausses croyances doivent donc pouvoir exister.

Le joueur peut mentir.

Les PNJ peuvent mentir au joueur.

La vérité du monde ne doit pas être systématiquement révélée au joueur par l’interface.

---

# 6. Les PNJ sont le cœur de l’émergence

Les PNJ ne sont pas des donneurs de quêtes, des marchands ambulants ou des figurants.

Ils sont les agents à partir desquels le monde produit son histoire.

Chaque PNJ possède un état interne évolutif comprenant notamment sa personnalité, ses besoins, ses émotions, ses relations, ses perceptions, ses connaissances, ses souvenirs, son contexte et ses objectifs ou désirs.

Les variables psychologiques sont quantitatives et nuancées, notamment sur une échelle de **-10 à +10**, plutôt que sous la forme grossière de catégories comme « faible/moyen/fort » ou « ++/-- ».

Un PNJ peut être extrêmement méfiant, légèrement susceptible, profondément attaché à quelqu’un, temporairement terrifié, de plus en plus ambitieux, etc.

Ces variables ne sont pas simplement des statistiques décoratives : elles doivent influencer effectivement le comportement.

Un PNJ timide peut progressivement devenir assuré. Un individu respecté peut perdre son statut. Une personne peut devenir rancunière après plusieurs événements. Une relation peut se dégrader, se réparer ou se transformer. Une personne peut tomber amoureuse, perdre quelqu’un, changer de métier, devenir ambitieuse, se radicaliser, s’isoler ou chercher à prendre le pouvoir.

Le changement doit être une propriété normale de la simulation.

---

# 7. Des personnalités réellement distinctes

Les PNJ ne doivent pas être uniformes.

La génération initiale doit produire des personnalités variées, parfois excentriques, maladroites, étranges, contradictoires ou particulièrement marquées.

Le monde doit contenir des individus qui sont de véritables personnages.

Certains doivent être attachants, d’autres agaçants, certains très intelligents, d’autres complètement perdus, certains raisonnables, d’autres impulsifs ou extravagants.

Cette diversité est essentielle à l’émergence.

Le but n’est pas de créer 500 variantes d’un même comportement rationnel, mais 500 individus susceptibles de réagir différemment à un même monde.

---

# 8. La boucle cognitive des PNJ

Le comportement d’un PNJ repose sur une boucle continue.

Le système fournit au Transformer :

- ce que le PNJ perçoit à l’instant considéré ;
    
- son état interne actuel ;
    
- sa personnalité ;
    
- ses besoins ;
    
- ses relations ;
    
- ses souvenirs pertinents ;
    
- ses désirs et objectifs persistants ;
    
- le contexte dans lequel il se trouve.
    

Le Transformer traite ces informations et peut alors :

1. modifier l’état interne du PNJ ;
    
2. modifier certains souvenirs ou en créer de nouveaux ;
    
3. faire évoluer ses perceptions, émotions ou relations ;
    
4. poursuivre, abandonner ou réorienter un objectif ;
    
5. choisir une action ou une séquence d’actions.
    

Le moteur exécute ensuite ces décisions.

Il est responsable de la physique, des déplacements, des collisions, des interactions, de la simulation matérielle et de toutes les conséquences objectives des actions.

Le Transformer ne remplace donc pas le moteur du jeu.

**Il décide dans le monde ; le moteur fait exister ses décisions.**

Lorsqu’une action est terminée, échoue ou est interrompue, le PNJ repasse dans la boucle avec son nouvel état.

Un PNJ qui décide de rester tranquillement boire pendant trente minutes peut être interrompu après deux minutes parce qu’un individu entre dans la pièce avec un couteau.

Il ne doit pas simplement poursuivre son ancienne animation : sa perception a changé, son état a changé, le contexte a changé. Le Transformer réévalue alors la situation.

---

# 9. La planification à long terme

L’intelligence des PNJ ne doit pas se limiter à la réaction immédiate.

Un PNJ peut conserver des **désirs, intentions et projets persistants** dans sa mémoire.

Il peut vouloir économiser suffisamment d’argent pour acheter une maison, séduire quelqu’un, se venger, quitter son village, apprendre un métier, devenir riche, obtenir une fonction politique ou retrouver une personne.

Il peut poursuivre ces objectifs sur une longue durée, en les interrompant temporairement lorsque les circonstances l’exigent.

La planification à long terme est une difficulté technique importante, mais elle constitue une propriété fondamentale du comportement recherché.

Le PNJ ne doit donc pas être une succession de réactions sans continuité.

Il doit avoir une trajectoire.

---

# 10. L’émergence est le jeu lui-même

L’émergence ne constitue pas une couche de contenu ajoutée au-dessus du jeu.

**L’émergence est ce qui se produit lorsque le jeu fonctionne.**

Le développeur définit :

- les variables ;
    
- les règles ;
    
- les actions possibles ;
    
- les contraintes ;
    
- les interactions ;
    
- les systèmes physiques ;
    
- les systèmes sociaux ;
    
- les capacités cognitives ;
    
- les possibilités de génération ;
    
- les outils permettant aux agents d’agir.
    

Puis les agents utilisent ces possibilités.

Un PNJ peut décider de faire quelque chose que personne n’a explicitement écrit comme « événement ».

Un ensemble de décisions individuelles peut produire une nouvelle situation sociale.

Plusieurs situations peuvent produire un conflit.

Un conflit peut produire une migration.

Une migration peut modifier l’économie d’un village.

Une évolution économique peut modifier les relations politiques.

Une relation politique peut produire une guerre.

Une guerre peut provoquer des morts, des déplacements, des changements de propriété, des rancunes familiales et de nouvelles relations.

Aucun de ces événements n’a besoin d’être pré-écrit.

Le développeur construit **l’espace des possibles** ; la simulation parcourt cet espace.

---

# 11. Les sociétés émergent des individus

Les institutions ne doivent pas être considérées comme des créatures autonomes du monde.

Une mairie, une famille, une entreprise, une armée, une organisation criminelle ou une communauté sont avant tout des ensembles d’individus reliés entre eux.

Le jeu doit donc privilégier la profondeur des individus et de leurs relations plutôt que de remplacer leur comportement par des variables abstraites représentant directement « la société ».

Un PNJ peut aimer son village tout en détestant son maire.

Il peut respecter son employeur mais mépriser sa politique.

Il peut être loyal envers une personne et hostile à l'organisation à laquelle celle-ci appartient.

La société doit apparaître comme le résultat de ces relations complexes.

---

# 12. Les relations sont persistantes et significatives

Les relations entre personnages constituent une infrastructure majeure du jeu.

Un PNJ peut devenir ami, ennemi, conjoint, rival, allié, collègue, employeur, employé, voisin, informateur, membre de la famille ou simple connaissance.

Ces relations doivent être persistantes et évoluer avec les événements.

Le joueur doit pouvoir réellement construire des relations avec les personnages.

Il peut demander à un ami de l’accompagner dans une mine, demander à quelqu’un de surveiller sa maison pendant son absence, travailler avec une personne, l’aider, la trahir ou lui confier quelque chose.

Les PNJ ne doivent pas redevenir neutres après une interaction.

Les relations constituent une partie de leur mémoire et de leur identité.

---

# 13. Le joueur peut vivre une vie complète

Le jeu ne doit pas considérer la vie ordinaire comme un contenu secondaire.

Il doit être possible de jouer pendant des dizaines d’heures sans poursuivre un objectif spectaculaire et simplement construire une existence.

Le joueur peut travailler, posséder une maison, avoir des voisins, se marier, avoir des enfants, transmettre des biens ou des connaissances, changer de profession, devenir artisan, marchand, agriculteur, militaire, propriétaire, criminel ou responsable politique.

Une vie banale doit pouvoir être intéressante parce qu’elle existe dans un monde vivant.

Le jeu ne doit pas constamment chercher à rappeler au joueur qu’il doit accomplir quelque chose.

---

# 14. Liberté sans promesse d’omnipotence

Le joueur peut tenter énormément de choses, mais il reste soumis aux règles du monde.

Les possibilités physiques et logiques sont définies par le moteur.

La liberté vient de la combinaison de ces primitives, pas d’une magie permettant de faire n’importe quoi sans cohérence.

Le joueur peut formuler des intentions en langage naturel, mais le système ne doit jamais inventer une capacité qui n’existe pas.

Le langage naturel est une **interface de traduction**, pas un moyen de contourner les règles du jeu.

Le joueur peut dire quelque chose d’impossible ; le système doit alors interpréter cette intention dans la mesure du possible ou la rejeter.

---

# 15. Le langage naturel comme interface

Le joueur doit pouvoir s’exprimer naturellement.

Par exemple :

> « Salut Georgette, comment tu vas ? Ça te dirait de venir te promener avec moi dans la forêt ? »

Le Transformer d’interface ne crée pas une nouvelle mécanique de jeu. Il traduit cette phrase vers les concepts existants : salutation amicale, demande de promenade, destination, relation avec Georgette, etc.

Georgette produit ensuite une réponse logique selon son propre état.

Cette réponse peut être traduite à son tour en langage naturel.

Si elle ne comprend pas une référence, si elle est méfiante, si elle n’aime pas le joueur ou si elle est simplement occupée, sa réponse doit refléter son état plutôt que satisfaire automatiquement la demande.

Le langage sert donc à **exprimer une intention dans un monde qui possède ses propres règles**.

---

# 16. Le monde matériel

Le monde doit être profondément physique.

Le terrain et les constructions sont constitués de voxels extrêmement fins et doivent pouvoir être transformés ou détruits.

La destruction n’est pas une simple suppression de bloc façon Minecraft.

La matière doit pouvoir se séparer selon sa structure. Une construction mal soutenue peut s’effondrer. Une excavation peut modifier les contraintes physiques d’une structure.

Une cavité ne doit pas pouvoir rester artificiellement suspendue sans raison.

La physique doit cependant rester suffisamment contrôlée pour être calculable et jouable.

Le monde est donc réaliste dans ses principes, mais conçu pour servir une simulation de jeu.

---

# 17. Construction et magie

La construction s’inscrit dans une esthétique médiévale-fantastique.

Les artisans utilisent des baguettes ou outils magiques permettant de transformer les matériaux disponibles en constructions ou objets appropriés.

La magie ne doit pas être un pouvoir arbitraire permettant de créer gratuitement n’importe quoi.

Elle constitue une technologie particulière du monde, intégrée à son économie et à ses métiers.

Le joueur peut payer un artisan pour réaliser une construction.

Il peut également apprendre auprès d’un artisan. Celui-ci peut lui prêter un outil de faible puissance pendant son apprentissage, lui permettre de pratiquer, puis progressivement lui transmettre son savoir-faire et l’accès à un outil plus performant.

La compétence est donc transmissible socialement.

La destruction repose notamment sur un outil principal, la masse, qui permet de désassembler les constructions en éléments constitutifs.

Le monde doit ainsi permettre de transformer réellement la matière plutôt que de simplement placer et supprimer des objets abstraits.

---

# 18. Une fantasy mystérieuse

Le monde est fondamentalement médiéval dans son organisation, avec une esthétique de fantasy assumée, mais la magie doit rester **pondérée et mystérieuse**.

Une partie de la magie est maîtrisée et intégrée à la civilisation.

Une autre partie demeure inconnue, dangereuse ou incomprise.

Le monde doit comporter des phénomènes que les habitants eux-mêmes ne comprennent pas nécessairement : zones étranges, manifestations dangereuses, lieux mystérieux, phénomènes magiques inhabituels.

L’inconnu est une composante essentielle de l’exploration.

Le joueur ne doit pas avoir l’impression que le monde entier lui est expliqué dès le départ.

---

# 19. L’exploration comme découverte

Le monde doit être suffisamment vaste et diversifié pour donner envie de partir.

Les villages ne doivent pas être placés partout.

Entre les zones habitées doivent exister de grands espaces naturels : montagnes, vallées, forêts, marais, ravins, grottes, cascades, paysages ouverts et lieux difficiles d’accès.

Il doit être possible de rencontrer un village auquel on ne s’attendait pas, une famille isolée, une ferme, un personnage vivant seul dans les bois, une zone dangereuse ou un phénomène que personne n’avait raconté au joueur.

Le jeu ne doit pas garantir que le joueur découvrira tout.

Il n’existe pas nécessairement de « contenu important » que le système doit absolument montrer au joueur.

**La découverte doit être une conséquence de l’exploration et de la vie du monde.**

---

# 20. Pas de quête obligatoire pour donner du sens au monde

Le jeu ne doit pas transformer artificiellement chaque événement en quête.

Un personnage peut avoir un problème sans produire un marqueur au-dessus de sa tête.

Une famille peut traverser une crise sans que le jeu annonce au joueur qu’il s’agit d’une mission.

Un village peut être en conflit sans demander explicitement au joueur de résoudre le problème.

Le joueur peut intervenir, observer, aider, exploiter la situation ou partir.

Le monde continue dans tous les cas.

Même l’inaction peut avoir une signification sociale.

Si tout le village assiste aux funérailles d’une personne importante et que le joueur ne vient pas, les habitants peuvent remarquer son absence et modifier leur opinion de lui.

**Ne rien faire est également un comportement observable.**

---

# 21. Le joueur peut être impliqué sans être forcé

Le joueur peut être spectateur.

Il peut refuser de participer à un événement.

Mais il ne peut pas être socialement invisible.

Les habitants observent ses comportements et construisent leurs propres interprétations.

Le joueur devient donc naturellement un acteur du monde simplement parce qu’il y vit.

Le jeu ne doit pas avoir besoin de lui dire « intervenez ici ».

Les opportunités émergent de sa présence.

---

# 22. Plusieurs façons de commencer

Le monde peut proposer plusieurs cadres de départ sans changer les règles fondamentales de simulation.

Le joueur peut notamment :

- incarner un habitant possédant déjà une histoire, un métier et des relations ;
    
- arriver comme étranger complet et devoir s’intégrer ;
    
- commencer dans un monde paisible ou dans une situation déjà troublée ;
    
- commencer dans une société traversant une guerre ou une crise ;
    
- recevoir un cadre de départ orienté vers une ambition particulière : devenir criminel, voleur, assassin, dirigeant, etc. ;
    
- commencer sans objectif particulier et simplement vivre.
    

Le rôle du joueur et l’état initial du monde sont deux dimensions distinctes et peuvent être combinés.

Un scénario de départ ne doit pas devenir une histoire linéaire.

Il constitue simplement **la situation initiale à partir de laquelle la simulation commence**.

---

# 23. Aucun destin imposé

Le jeu peut proposer des idées ou des ambitions, mais ne doit jamais imposer au joueur une trajectoire.

Le joueur peut décider de devenir maire.

Il peut aussi passer toute sa vie à cultiver son champ.

Il peut partir à l’autre bout du monde.

Il peut rester dans son village.

Il peut chercher l’aventure ou la fuir.

Il peut vouloir devenir riche ou ne jamais chercher l’argent.

Il peut devenir un personnage majeur du monde ou rester totalement insignifiant.

La réussite n’est pas définie par la réalisation d’un objectif global imposé.

---

# 24. La mobilité sociale doit être réelle

Les individus ne doivent pas être enfermés définitivement dans leur rôle initial.

Un paysan peut devenir marchand.

Un artisan peut devenir riche.

Un inconnu peut devenir une personnalité politique.

Un individu peut prendre la tête d'une organisation criminelle.

Un personnage sans importance peut devenir central dans la vie d’un village.

Inversement, une personne importante peut perdre sa position.

Tout le monde n’a pas besoin d’avoir une simulation cognitive suffisamment profonde pour accomplir n’importe quelle trajectoire complexe à tout instant. La profondeur de simulation peut limiter ce que certains individus peuvent réellement accomplir.

Mais cette limitation doit venir de **la profondeur de simulation disponible**, pas d’une règle artificielle disant qu’un certain type de PNJ ne peut jamais changer de rôle.

---

# 25. Temps, vieillissement et mort

Les PNJ vivent, vieillissent et meurent définitivement.

La durée de vie moyenne visée est d’environ **150 heures de jeu**, avec un cycle de vie volontairement compressé : l’enfance reste relativement courte, l’âge adulte constitue la majeure partie de la vie, puis le vieillissement s’accélère.

La mort d’un PNJ n’est pas une simple disparition d’entité.

Ses relations, ses proches, ses biens, son emploi, ses responsabilités, ses informations et son influence peuvent disparaître ou être redistribués.

L’importance de sa mort doit être proportionnelle à son importance réelle.

La mort d’un individu isolé peut avoir peu de conséquences.

La mort d’un dirigeant, d’un parent central, d’un chef militaire ou d’une personne occupant une position sociale essentielle peut provoquer des conséquences considérables.

Le jeu ne doit pas artificiellement dramatiser chaque mort.

---

# 26. Le joueur et la mort

Le joueur reste soumis au monde autant que possible.

Il ne possède pas de pouvoirs surnaturels permettant de contourner les règles fondamentales.

Deux exceptions principales existent pour des raisons de jouabilité : la mort permanente du joueur ne doit pas supprimer arbitrairement des dizaines d’heures de progression, et le joueur n’est pas contraint de dormir.

En dehors de ces exceptions, le joueur doit vivre dans le même monde que les autres.

---

# 27. Un monde parfois sérieux, parfois absurde

Le monde doit être crédible dans ses règles et ses conséquences, mais les comportements émergents peuvent produire de l’humour.

L’humour ne doit pas être ajouté artificiellement par des blagues écrites.

Il doit provenir des personnages, de leurs contradictions et des situations qu’ils créent.

Un maire peut prendre une décision catastrophique parce qu’il est extrêmement susceptible.

Un personnage peut provoquer une situation absurde à cause de sa personnalité.

Un événement qui fait rire le joueur peut simultanément avoir de véritables conséquences pour les personnages concernés.

Le monde doit donc pouvoir être drôle sans devenir une parodie.

---

# 28. Le développeur ne doit pas connaître l'histoire

C’est l’un des principes fondamentaux de la conception.

Dans un jeu traditionnel, les développeurs cherchent généralement à prévoir les situations que le joueur rencontrera.

Ici, le principe est inversé.

Le développeur doit chercher à définir **un système suffisamment riche pour que les situations puissent être imprévisibles**.

Il doit savoir ce que le moteur permet.

Il ne doit pas savoir exactement ce que les PNJ vont en faire.

Il doit savoir quelles règles existent.

Il ne doit pas savoir quelle société émergera de leur combinaison.

Il doit savoir comment fonctionne la relation entre deux individus.

Il ne doit pas savoir quelles histoires naîtront de centaines de relations successives.

La réussite du jeu se mesure donc en partie à sa capacité à produire des situations que même ses créateurs n’avaient pas imaginées.

---

# 29. Principe architectural fondamental

La séparation des responsabilités doit rester claire.

**Le moteur possède la vérité objective du monde.**

Il gère la physique, les règles, les objets, les actions autorisées, les conséquences matérielles et les contraintes.

**La simulation possède l’état vivant du monde.**

Elle maintient les individus, leurs relations, leurs mémoires, leurs évolutions et leurs conséquences persistantes.

**Le Transformer possède la décision cognitive des PNJ.**

Il interprète la situation à partir de ce que le PNJ perçoit et de ce qu’il est, puis choisit comment celui-ci doit évoluer et agir.

**Le système de génération construit le monde initial à partir de la graine.**

**Le rendu matérialise graphiquement la portion du monde nécessaire au joueur.**

Aucun de ces composants ne doit être confondu avec les autres.

---

# 30. Une architecture au service de la densité

L’intelligence doit être obtenue avec des modèles suffisamment légers pour permettre une simulation massive.

L’objectif n’est pas de donner à quelques PNJ un modèle gigantesque.

L’objectif est de pouvoir faire fonctionner **beaucoup d’individus simultanément**, chacun possédant une identité, une mémoire, des relations, des objectifs et une capacité réelle de décision.

Le Transformer doit donc être conçu comme un composant de simulation extrêmement léger et fréquent, plutôt que comme un agent conversationnel spectaculaire mais impossible à multiplier.

La qualité recherchée n’est pas celle d’une conversation isolée.

C’est celle de **milliers de décisions cohérentes produisant collectivement un monde vivant**.

---

# 31. Philosophie générale

Ce jeu ne doit pas être conçu comme un récit que le joueur traverse.

Il doit être conçu comme **un monde dans lequel le joueur vit**.

Le contenu ne doit pas être entièrement fabriqué avant la partie.

La partie doit fabriquer une partie de son propre contenu.

Les développeurs créent les lois de la nature, les capacités des êtres, les matériaux, les comportements possibles, les règles sociales, les outils, les environnements et les possibilités de génération.

La graine détermine un monde particulier.

Les PNJ donnent vie à ce monde.

Le temps le transforme.

Les interactions produisent des conséquences.

Le joueur s’insère dans cette dynamique.

Et de l’ensemble émergent des histoires.

---

# 32. Principe directeur

Le jeu doit toujours privilégier :

**la simulation plutôt que le scénario,  
les individus plutôt que les archétypes,  
les conséquences plutôt que les récompenses artificielles,  
la découverte plutôt que la révélation,  
la liberté plutôt que l’objectif imposé,  
la cohérence plutôt que le script,  
la profondeur plutôt que la quantité de contenu prédéfini.**

Le développeur ne doit pas chercher à écrire toutes les histoires possibles.

Il doit construire un monde dans lequel **des histoires peuvent arriver**.

Le résultat recherché est un monde où, après plusieurs dizaines d’heures, le joueur puisse raconter quelque chose que les développeurs n’avaient jamais écrit :

> « Il s’est passé ça, parce que cette personne a fait ça, puis cette autre personne a réagi comme ça, et tout a dégénéré. »

C’est précisément là que le jeu aura atteint son objectif.

**Le jeu n’est pas l’histoire écrite par le développeur.  
Le jeu est ce qui arrive lorsque le monde fonctionne.**