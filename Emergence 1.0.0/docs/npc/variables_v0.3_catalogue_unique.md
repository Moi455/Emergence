# Catalogue unique : variables et actions du monde simulé (v0.3)

8 octobre 2026. Tenu par le fil « Simulation sociale des villages ». Parties « modèle » **validées par le fil « Données d'entraînement du Transformer »** (8 oct., 20:48), qui fait foi pour le modèle (jetons, vocabulaire, sorties). L'alignement sur la charte (échelle, souvenirs et objectifs écrits par le Transformer) est validé aussi (9 oct., 01:43).

**La charte du jeu de Monsieur (`CHARTE_DU_JEU.md`, 8 octobre, 20:48) prime sur tout ce qui précède, ce document compris.** Les points de la charte qui touchent ce catalogue sont repris au § 0.

Ce document **remplace** comme référence de travail :
- `variables_v0.1_catalogue.md` (catalogue exhaustif, écrit pour une grille 2D) ;
- `variables_v0.2_noyau.md` (noyau de la tranche verticale) ;
- `ai/CATALOGUE_modele.md` (moitié « modèle », générée depuis le code).

Ces trois fichiers restent comme historique. Le contrat d'action détaillé (arguments, conditions, animations) reste dans `ai/CONTRAT_PNJ.md` et `docs/interfaces.md` § 6 et 7. Ce catalogue en reprend la liste pour qu'il n'y ait qu'un endroit où voir tout ce qui existe.

---

## 0. Ce que Monsieur a fixé

### 0.1 Charte du jeu (8 octobre, 20:48)

- **§ 6, échelle** : les variables psychologiques sont quantitatives et nuancées, sur une échelle de **−10 à +10**, jamais en catégories. Ce catalogue les note ainsi (§ 1). Le moteur les stocke en dixièmes (entier × 10), pour que les petits pas restent possibles : un trait de +3,5 est stocké 35.
- **§ 6, changement** : un timide peut devenir assuré, une personne devenir rancunière, ambitieuse ou radicale. Les traits et les valeurs bougent donc, lentement (ancienne question Q1, tranchée).
- **§ 8, boucle cognitive** : le Transformer reçoit la perception, l'état, la personnalité, les besoins, les relations, les souvenirs pertinents, les désirs et objectifs persistants, et le contexte. Il peut ensuite :
  - modifier l'état interne ;
  - modifier ou créer des souvenirs ;
  - faire évoluer perceptions, émotions et relations ;
  - poursuivre, abandonner ou réorienter un objectif ;
  - choisir une action ou une séquence d'actions.
  Le moteur exécute. Une action finie, échouée ou **interrompue parce que la perception a changé** ramène le PNJ dans la boucle.
- **§ 9, objectifs persistants** : désirs, intentions et projets gardés en mémoire sur une longue durée, mis en pause quand les circonstances l'exigent.
- **§ 5, pas d'omniscience** : un PNJ ne voit pas les variables internes d'un autre ; il les infère. Les jetons ne montrent des autres que ce qui se perçoit, et ce que le PNJ en croit.
- **§ 24, mobilité sociale** : aucune règle n'enferme un PNJ dans son rôle ; les options du moteur ne doivent pas l'interdire (§ 7.2 : changer de métier manque).
- **§ 25, durée de vie** : environ 150 heures de jeu, enfance courte, âge adulte majoritaire, vieillesse accélérée (§ 5.1).
- **§ 29, séparation** : le moteur a la vérité objective, la simulation l'état vivant, le Transformer la décision cognitive.

### 0.2 Messages du 8 octobre, 15:18 et 15:34

- **Tout est simulé, tout le temps.** Les 500 PNJ tournent à pleine précision de décision même loin du joueur ; seul le rendu (voxels, animation, physique fine) s'arrête hors de vue. Un pont détruit hors de vue est détruit quand le joueur arrive.
- **Chaque PNJ a un Transformer dans sa boucle** : il reçoit ce que le PNJ voit, toute son identité, ses souvenirs ; il ajuste ses variables et choisit une action. Pas d'algorithme de décision à règles.
- **Ajustement progressif** : seules les émotions peuvent sauter d'un coup ; le reste bouge par petits pas, sans aléa gratuit.
- **Définir d'abord toutes les variables et toutes les actions** : c'est l'objet de ce document.
- Eau et feu au plus léger, pas forcément en voxels ; l'eau prélevée doit diminuer réellement et rester utilisable.
- Lumière calculée en temps réel (heure, nuages, météo), jamais précalculée.
- Frontières : aucune limite visible ; la difficulté croît jusqu'à la mort (loups, faim, froid) ; des PNJ s'y perdent et deviennent des histoires.

## 1. Comment lire les tableaux

| Colonne | Valeurs |
|---|---|
| **Écrit par** | `moteur` : calculé par la simulation (corps, physique, économie, perception). `T saut` : le Transformer peut le changer d'un coup. `T pas N` : le Transformer le change d'au plus N par décision, sur l'échelle de la charte. `T lent` : au plus 0,1 par jour de jeu. `naissance` : tiré à la naissance, puis fixe. `action` : créé ou détruit par une action choisie. |
| **Vu par le modèle** | nom du champ dans le jeton tok-1 (`ai/npc_pipeline/encode.py`), ou `—` si le modèle ne le voit pas encore. |
| **sim/** | `oui` : la simulation sans rendu (`emergence/sim/`) le simule aujourd'hui ; `neutre` : le jeton reçoit une valeur fixe tant que la simulation ne le modélise pas ; `—` : absent. |
| **Statut** | `N` noyau, `E` extension, `R` reporté (repris de v0.1 et v0.2). |

Échelles : les variables psychologiques et sociales sont sur l'échelle de la charte, `−10..10` (bipolaire) ou `0..10` (quand le négatif n'a pas de sens : faim, peur, familiarité), avec une décimale ; le moteur les stocke en dixièmes. Les grandeurs physiques gardent leur unité : `0..100` pour les points de vie ou l'usure, `0..1`, `qté` = quantité réelle (le jeton la passe en échelle log 0..10). Le jeton tok-1 arrondit à l'entier (`representation.to10`), ce qui suffit pour tester la boucle. **Décision du fil des données pour tok-2** : le modèle lira les dixièmes stockés par le moteur (int8 −100..+100, divisé par 100 au lieu de 10 dans le lecteur), sinon les pas fins du § 1.1 restent invisibles au modèle tant qu'ils ne franchissent pas un entier. Seuls `to10` et `num` de `encode.py` changent ; le stockage du moteur ne change pas.

### 1.1 Règles d'écriture par le Transformer

Appliquées par le gouverneur du moteur (`sim/emergence_sim/brain.py`, classe `Governor`), quelle que soit la sortie du modèle. Les pas sont donnés sur l'échelle de la charte. La dernière colonne dit si le gouverneur l'applique déjà ; les autres groupes ne sont pas encore stockés par la simulation et sont refusés en attendant.

| Groupe | Règle | Appliquée |
|---|---|---|
| Émotions (peur, colère, joie, stress ; choc, confusion) | saut permis, borné à l'échelle | oui (choc et confusion : pas encore stockés) |
| Deuil | pas de 1 | oui |
| Relations (affection, confiance, respect, romance, familiarité, rancune) | pas de 0,5 par décision | oui |
| Pulsions | pas de 0,5 | oui |
| Traits et valeurs | 0,1 par jour de jeu au plus (charte § 6 : ils changent) | oui |
| Humeur envers, envie d'interagir, soupçon | pas de 1 | prévue |
| Appartenance, loyauté, confiance envers le chef | pas de 0,3 | prévue |
| Souvenirs : réinterpréter l'importance ou la valence | pas de 1 | oui |
| Souvenirs : en créer un (types connus de la simulation, valence et importance bornées) | création | oui |
| Objectifs : créer, abandonner, réorienter (nouvelle cible), changer la priorité | priorité par pas de 1 ; au plus 4 objectifs | oui |
| Corps, besoins, biens, monnaie, compétences, dette | refusé : c'est le moteur | oui |
| Romance vers un mineur ou un parent proche | refusé toujours (règle dure) | oui |

## 2. Le PNJ

### 2.1 Identité et corps

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| id, prénom, famille | id, texte | naissance | id → pointeur ; le nom jamais | oui | N |
| âge, catégorie d'âge (child < 14, teen < 18, adult < 60, elder) | années, énum | moteur | `SELF.age`, `age_cat` | oui (seuil apprenti 12) | N |
| sexe, orientation | énum | naissance | — | oui | N |
| vivant, date et cause de décès | | moteur | — | oui | N |
| village d'origine, village actuel, foyer | id | moteur, action (migrer) | `VILLAGE.village_id` | oui | N |
| position, orientation, posture, destination | m, rad, énum | moteur | `place_type` seulement | lieu abstrait `village:site` | N |
| points de vie | 0..100 | moteur | `body.hp` | oui | N |
| force, endurance, agilité, robustesse | 0..100 | naissance + âge | `body.strength` | neutre (55 adulte) | N |
| charge portée / capacité | 0..1 | moteur | `body.load_ratio` | neutre (0) | N |
| acuité visuelle, auditive | 0..100 | naissance | — | — | E |
| maladie (sévérité), immunité | 0..100, jours | moteur | — (douleur seulement) | oui | N |
| blessures (lieu, gravité, saignement, infection) | liste | moteur | — | — | E |
| grossesse, fertilité | énum, 0..100 | moteur | — | oui (naissances) | N |
| beauté, propreté, signes visibles | 0..100 | naissance, moteur | `ENTITY.beauty` (des autres) | neutre (50) | E |

### 2.2 Personnalité

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| agressivité, courage, empathie, sociabilité, honnêteté, impulsivité, curiosité, tolérance, justice, rancune | −10..10 | naissance, puis T lent (charte § 6) | `SELF.trait.*` | oui | N |
| ambition | −10..10 | naissance, T lent | `SELF.trait.ambition` | oui (rangée en pulsion) | N |
| prudence, loyauté, possessivité, fierté, générosité, diligence, conformisme, sensualité, spiritualité, intelligence | −10..10 | naissance | — | — | R |
| réactivité émotionnelle, résilience | 0..10 | naissance | `SELF.temperament.*` | neutre (50, 55) | N |
| humeur de base, stress de base | −10..10 | naissance | — | — | E |

### 2.3 Valeurs

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| protection des proches, respect de la propriété, honneur, valeur de la vie, fidélité amoureuse, sensibilité aux tabous | 0..10 | naissance, T lent | `SELF.value.*` | oui | N |
| piété | 0..10 | naissance, T lent | — | oui | N (à ajouter au jeton) |
| loyauté au groupe, respect de l'autorité, liberté, tradition, hospitalité | 0..10 | naissance | — | — | R |
| croyance en l'au-delà des frontières | 0..10 | moteur (récits, légendes) | — | oui | N (à ajouter au jeton) |

### 2.4 Pulsions et besoins

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| libido, besoin social, accomplissement, accumulation | 0..10 | T pas 0,5 + dérive du moteur | `SELF.drive.*` | oui | N |
| solitude | 0..10 | moteur (présence d'autrui) | — | oui | N (à ajouter au jeton) |
| faim, soif | 0..10 | moteur | `state.hunger`, `state.thirst` | oui | N |
| fatigue | −10..10 (−10 reposé) | moteur | `state.fatigue` | oui (0..100, convertie) | N |
| douleur | 0..10 | moteur | `state.pain` | oui (100 − pv) | N |
| heures depuis le repas | qté | moteur | `hours_since_meal` | estimée depuis la faim | N |
| confort thermique | −10..10 | moteur (météo, tenue, abri) | — | — | E |
| reconnaissance, nouveauté, calme | 0..10 | T pas 0,5 | — | — | R |

### 2.5 Émotions

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| peur, choc, confusion | 0..10 | **T saut** + moteur (danger) | `state.fear/shock/confusion` | peur oui ; choc, confusion neutres | N |
| colère, stress | −10..10 | **T saut** + moteur | `state.anger/stress` | oui (0..100) | N |
| joie | −10..10 | **T saut** + moteur | `state.joy` | oui | N |
| deuil | 0..10 | T pas 1 + moteur (décès) | — | oui | N (à ajouter au jeton) |
| honte, culpabilité, fierté ressentie, ennui, surprise | 0..10 | T saut | — | — | E |
| dégoût, jalousie, ébriété | 0..10 | T saut, moteur | — | — | R |

### 2.6 Activité

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| action en cours | énum (fonction du contrat) | action | `SELF_STATE.current_action` | oui | N |
| plan (1 à 6 étapes), étape, progression | contrat, 0..1 | moteur | `activity.progress` | oui | N |
| degré d'engagement | 0..100 | T (avec l'action) | `activity.commitment` | neutre (0) | N |
| secondes depuis la décision | qté | moteur | `activity.secs_since_decision` | oui | N |
| en conversation avec | liste d'id | moteur | — | — | E |
| outil en main | énum | action (`equip`) | `tool_in_hand` | neutre (mains) | N |

### 2.7 Tenue

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| tenue portée (everyday, work, travel, festive, mourning, cold, court, night) | énum | action `dress` | `SELF.outfit_worn`, `ENTITY.wears.*` | oui (choisie par une règle provisoire, à confier au modèle) | N |
| tenues possédées, usure | booléens, 0..100 | moteur | `SELF.owns.*`, `outfit.wear` | toutes possédées, usure neutre | N |
| pièces sur 11 emplacements, teintes | voir `interfaces.md` § 4 | fil Skins | — | — | N (rendu) |

### 2.8 Métier et compétences

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| métier (26 métiers des fiches + apprenti + aucun) | énum | action (apprentissage), moteur | `SELF.job` | oui (24 métiers propres, table de correspondance dans `sim_adapter.JOB`) | N |
| compétence par savoir-faire (24 savoirs) | 0..100 | moteur (pratique, enseignement) | `body.job_skill` (le métier seulement) | oui | N |
| maître, apprentis, savoir appris | id | action, moteur | — | oui | N |
| ancienneté, employeur, salaire convenu | | moteur, action | — | — | E |

### 2.9 Possessions

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| monnaie personnelle | qté | moteur | — | oui | N |
| inventaire porté (type, quantité, qualité, usure, fraîcheur, propriétaire légitime, caché) | liste ≤ 8 | moteur | `INV.*` | neutre (vide) | N |
| manque de nourriture, combustible, outils | −10..10 | moteur | `stock.food/fuel/tools` | oui (depuis le foyer) | N |
| logement, terres, atelier, bétail | id | moteur, action | — | foyer seulement | E |
| créances et dettes | liste | moteur | `rel.debt` (agrégé par personne) | `rel.debt` | N |

### 2.10 Mémoire

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| souvenir : type, agent, cible, tiers, lieu, jour | énum, id | moteur et T (création, charte § 8) | `MEMORY.type`, pointeurs | oui (≤ 32 par PNJ, 21 types) | N |
| source (vu, entendu, rapporté, déduit), certitude | énum, 0..1 | moteur | `MEMORY.source`, `certainty` | oui (ouï-dire, mensonges) | N |
| importance, valence | 0..10, −10..10 | moteur à la création, puis T pas 1 (réinterprétation) | `importance`, `valence` | oui | N |
| gravité, norme enfreinte, issue (vengé, pardonné, puni, remboursé, non résolu) | | moteur, action | `severity`, `broke`, `outcome` | partiel | N |
| marquant, secret | booléens | moteur | `defining`, `secret` | oui (secrets d'adultère, de détournement) | N |
| nombre de rappels, distorsion | | moteur | — | — | E |
| capacité, taux d'oubli | | naissance | — | 32 fixe, oubli par saillance | N |

Le modèle voit 9 souvenirs choisis par saillance (question ouverte Q4 sur la mémoire longue).

### 2.11 Connaissances

| Variable | Contenu | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| personnes connues | id, familiarité, dernière position connue | moteur | via `ENTITY` | oui (relations) | N |
| lieux connus, carte mentale | lieux, chemins | moteur | — | — | E |
| ressources connues, prix connus | lieu, type, quantité, fraîcheur | moteur | — | prix du village seulement | E |
| recettes connues | liste | moteur | — | savoirs | N |
| rumeurs, légendes entendues | contenu, source, crédibilité | moteur | — | oui (légendes, ouï-dire) | N |

### 2.12 Buts et engagements

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| objectif persistant (charte § 9) : type (besoin, projet, vengeance, demande d'aide, tâche partagée, accompagner), cible, partenaire, depuis | énum, id | **T** (créer, abandonner, réorienter) | `GOAL.type`, pointeurs | oui, stocké et montré au modèle (au plus 4) ; l'agenda (noces, funérailles, fêtes, recherches) reste à part | N |
| types d'objectifs voulus par la charte : économiser pour une maison, séduire, se venger, quitter le village, apprendre un métier, s'enrichir, obtenir une fonction, retrouver quelqu'un | énum | T | — (hors vocabulaire tok-1, sauf vengeance) | — | N. **Vocabulaire tok-2** (fil des données, 9 oct.) : `save_for_house`, `seduce`, `leave_village`, `learn_trade`, `get_rich`, `obtain_office`, `find_person`, en plus de `revenge` |
| priorité | 0..10 | T pas 1 | `GOAL.priority` | oui | N |
| progrès, échéance | 0..1, h | moteur | `progress`, `deadline_h` | neutre (0) : le moteur ne mesure pas encore le progrès | N |
| engagement : envers, type (promesse, serment, contrat, accompagnement, mariage, emploi), degré, statut | | action, moteur | — | fiançailles, mariage | N |
| demande reçue : de qui, quoi, statut | | moteur | `EVENT` | — | N |

## 3. Les autres, vus par le PNJ

Relation de A vers B, asymétrique, au plus 48 par PNJ (les plus faibles sont oubliées).

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| affection, confiance, respect, romance | −10..10 | T pas 0,5 + moteur (événements) | `ENTITY.rel.*` | oui | N |
| familiarité, rancune | 0..10 | T pas 0,5 + moteur | `rel.familiarity/grudge` | oui | N |
| crainte | 0..10 | **T saut** | `rel.fear` | neutre (0) | N |
| dette | −10..10 | moteur | `rel.debt` | oui | N |
| lien (parent, enfant, fratrie, conjoint, partenaire, ami, voisin, collègue, employeur, employé, rival, ennemi, inconnu) | énum | moteur | `ENTITY.link` | oui | N |
| humeur envers, envie d'interagir | −10..10 | T pas 1 | `mood_toward`, `urge_to_interact` | neutre | N |
| soupçon, menace indirecte | 0..10 | T pas 1 | `suspicion`, `indirect_threat` | neutre | N |
| réputation connue (fiabilité, danger) | −10..10 | moteur (rumeurs), T pas 1 | `rep_trust`, `rep_danger` | neutre | N |
| perçu, distance, jours sans contact, compréhension | 0..1, qté, ordinal | moteur (perception) | `perceived`, `distance`, `days_since_contact`, `understanding` | oui (présence, distance entre villages) | N |
| action visible, tenue, statut amoureux, village | énum | moteur | `visible_action`, `wears.*`, `love_status`, `village` | oui | N |
| traits et valeurs supposés, secrets connus sur B, relation supposée entre B et C | | T, moteur | — | secrets seulement | E |
| gratitude, attachement, autorité reconnue, rivalité, jalousie, dépendance | | T pas 0,5 | — | — | E |

## 4. La société

### 4.1 Foyer

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| membres, chef de foyer | id | moteur | `HOUSEHOLD.size`, `head` | oui | N |
| biens (14 biens en dixièmes), monnaie, outils | qté | moteur | `HOUSEHOLD.wealth` | oui | N |
| cohésion, honneur | 0..10, −10..10 | moteur | `cohesion`, `honor` | neutres | N |
| querelles avec d'autres foyers | id, depuis | moteur | — | oui (vendettas, paix par mariage) | N |

### 4.2 Groupes et titres

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| groupe : type (guilde, culte, bande hors-la-loi, famille, village), membres, fondateur, savoir, fermé | | action `found_group`, moteur | — | oui (guildes, cultes, bandes) | N |
| identification, cohésion, rang | 0..10 | T pas 0,3, moteur | — | — | E |
| titre : nom (chef, adjoint, juge, trésorier, scribe, percepteur…), titulaire, prétendants, autorité, légitimité | | action (élection, revendication), moteur | `TITLE.*` | chef élu seulement | N |

### 4.3 Village

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| id (sea_village, mountain_village, desert_village, forest_village, market_town), frontière | énum | monde | `VILLAGE.village_id`, `frontier` | oui (anciens noms, table de correspondance) | N |
| chef, prochaine élection, historique des chefs | id, jour | moteur (élection) | — | oui | N |
| décrets : impôt, peine du vol, secours contre la famine, taxe de marché, tabou de parenté, couvre-feu | | action `decree` du chef | — | oui | N |
| marché : stock par bien, prix, bourse du marché, trésor | qté | moteur | `VILLAGE.economy`, `food` | oui (économie fermée) | N |
| agitation | 0..100 | moteur (agrégat) | `tension` | oui | N |
| accusations en attente, verdicts | liste | moteur, action | — | oui (justice du chef) | N |
| savoirs connus, savoirs perdus | listes | moteur | — | oui | N |
| problème (disette, épidémie, raid, inondation, puits sec, pont cassé, loups…), urgence | énum, 0..100 | moteur | `problem_kind`, `urgency` | disette et épidémie | N |
| coutumes (8 normes : parenté, propriété, honneur, vie, fidélité, vérité, équité, tabou) | 0..10 | moteur (agrégat très lent) | `VILLAGE.custom.*` | neutres (50 + biais du village) | N |
| appartenance, loyauté, confiance envers le chef, légitimité du chef, confiance dans les institutions | −10..10 | T pas 0,3 | `belonging`, `loyalty`, `leader_*`, `institution_trust` | confiance envers le chef oui, le reste neutre | N |
| sécurité, réputation, cohésion | −10..10 | moteur | `security`, `rep`, `cohesion` | neutres | N |
| fête du village, jours de repos | jour | moteur | — | oui | N |

### 4.4 Entre villages

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| relation, dépendance commerciale, menace | −10..10, 0..10 | moteur | `OTHER_VILLAGE.*` | neutres | E |
| mes attaches dans l'autre village | 0..100 | moteur | `my_ties` | oui (nombre de relations) | N |
| routes : distance, sécurité, fréquentation | km, 0..100 | monde, moteur | — | distance, temps de trajet, brigandage | N |
| flux : migrations, caravanes, messagers | | moteur | — | migrations, voyages de commerce | N |

## 5. Le monde

Le monde a 20 × 20 km de terre jouable dans 50 km de voxels ; voxels de 2 cm en chunks de 64³ (`interfaces.md` § 1 et 2). Hors de vue, le moteur garde les **conséquences** (un pont existe ou non, un puits a de l'eau ou non), pas les voxels détaillés.

### 5.1 Temps, lumière, météo

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| seconde, heure, jour, jour de la semaine, mois, saison, année | | moteur (1 jour de jeu = 4 h réelles, proposé) | `time.hour_*`, `season` | heure de jeu par pas | N |
| horloge du vieillissement (charte § 25 : une vie ≈ 150 heures de jeu, enfance courte, vieillesse accélérée) | | moteur | `SELF.age` | — : la simulation vieillit au rythme du calendrier (1 an = 360 jours) | N (à décider, voir Q6) |
| météo : type, température, précipitations, vent, nuages, humidité | énum, °C, qté | moteur (graine) | `weather` | type seulement | N |
| luminosité (soleil, lune, nuages, feu) | 0..1 | moteur, **temps réel** | — | — | N (perception) |
| effet sur la vue et le déplacement | 0..1 | moteur | — | tempête sur les métiers dehors | E |

### 5.2 Matière et espace

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| voxel : classe de matière (9 bits) + teinte (7 bits) | `materials.csv` | moteur (`Operation` seulement) | — (perception agrégée) | — | N |
| matière : densité, dureté, inflammabilité, couleur | par classe | données | — | — | N |
| matière : cohésion (naturelle ou bâtie), conduction de chaleur, perméabilité | par classe | données | — | — | N (à ajouter à `materials.csv`) |
| lieu abstrait `village:site` et sa zone dans le monde | id | monde | `place_type` | oui (sites) | N |
| propriétaire d'un lieu, usage (public, privé, commun, sacré) | | moteur, action | — | — | N |

### 5.3 Structures et stabilité

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| structure (bâtiment, pont, galerie, étai) : id, type, propriétaire, usages, contenu | | monde, action `build` | — | — | N |
| état : intact, abîmé, effondré ; usure | énum, 0..100 | moteur (physique agrégée) | — | — | N |
| marge de stabilité (charge / résistance, étaiement) | 0..100 | moteur | — | effondrements de mine tirés au sort | N |
| chantier en cours : progrès, matériaux manquants, participants | | action `start_build`, `contribute`, `supply` | — | — | N |

### 5.4 Eau (pas forcément en voxels)

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| masse d'eau (mer, rivière, étang, puits, flaque) : volume, niveau, débit, potabilité | m³, m, m³/s | moteur | — | eau du puits comme bien du marché | N |
| eau portée (seau, cruche) | litres | action `fetch_water`, moteur | `INV` | — | N |
| humidité du sol, absorption, évaporation | 0..100 | moteur | — | — | N |

### 5.5 Feu (pas forcément en voxels)

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| foyer de feu : position, étendue, température, combustible restant, oxygène | °C, qté | moteur | — | — | N |
| humidité et inflammabilité de ce qui brûle | 0..100 | données, moteur | — | — | N |

### 5.6 Ressources vivantes

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| sol : fertilité, état (nu, labouré, semé, cultivé, jachère), culture et stade | | moteur, action | — | jardins et champs agrégés par saison | N |
| arbres : essence, âge, bois disponible, repousse | | monde, moteur | — | bois comme bien | N |
| gisements : minerai, quantité, profondeur | | monde | — | minerai et pierre comme biens | N |
| faune : espèce, population, agressivité, peur des humains | | moteur | — | — | E (loups des frontières : N) |

### 5.7 Objets et recettes

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| type d'objet : catégorie, poids, valeur, durabilité, périssabilité, effets, propriétés (tranchant, inflammable…) | | données | `ITEM.item`, `INV.item` | 14 biens : food, salt, wood, ore, tools, cloth, ale, glass, medicine, water, dye, stone, jewel, boat | N |
| instance : quantité, qualité, usure, fraîcheur, propriétaire, lieu | | moteur | `INV.*`, `ITEM.*` | stocks du foyer et du marché | N |
| recette : entrées, outils, savoir, lieu, durée, sorties | | données | — | métiers « fait / a besoin » | N |
| objet au sol à proximité | | moteur | `ITEM.*` | — | N |

### 5.8 Frontières

| Variable | Échelle | Écrit par | Vu par le modèle | sim/ | Statut |
|---|---|---|---|---|---|
| profondeur depuis la lisière | m | moteur | — | oui | N |
| survie à la profondeur d : 2^(−d / demi-distance) (mer, forêt, désert 300 m, montagne 500 m) | 0..1 | données | — | oui | N |
| cause de mort ou de disparition (loups, faim, froid, noyade, chute) | énum | moteur | — | « disparu » | N |
| légendes : titre, frontière, héros, conteurs | | moteur (récits) | `content=legend:*` | oui | N |
| record de profondeur par village | m | moteur | — | oui | N |

## 6. Perception : ce que le PNJ voit

Déjà en place : ce qu'un PNJ subit ou voit faire (insulte, coup, bousculade, demande en mariage, flirt, compliment, récit, réconfort) est noté par le moteur (`Sim.perceive`) et montré au modèle en jetons `EVENT` (les 3 plus forts des dernières 24 heures). Une insulte, un coup ou une demande en mariage **interrompt** l'action en cours de la cible, qui repasse dans la boucle à l'heure suivante (charte § 8).

À créer : le jeton tok-1 décrit une situation **sociale**. Pour la boucle « vision → action » voulue par Monsieur, le moteur doit produire des jetons de perception. Proposition à trancher avec le fil Transformer (format `tok-2`) :

| Jeton proposé | Champs | Source |
|---|---|---|
| `PERCEPT_PLACE` (1) | type de lieu, intérieur ou dehors, luminosité, bruit ambiant, température ressentie, couvert, danger | moteur |
| `PERCEPT_THING` (≤ 8) | catégorie (objet, structure, eau, feu, animal, plante, ressource), matière dominante, état (intact, abîmé, effondré, en feu, inondé), distance, direction, propriétaire (moi, quelqu'un, personne), utilité pour mes besoins | moteur, agrégé depuis les voxels **dans le champ de vision** |
| `PERCEPT_DANGER` (≤ 2) | type (chute, éboulement, feu, eau profonde, bête), intensité, distance, se rapproche ou non | moteur |

Tête de sortie prévue pour tok-2 (fil des données, 9 oct.), en cinq parties : deltas d'état ; deltas de relations, par jeton `ENTITY` ; réinterprétation de souvenirs, par jeton `MEMORY` ; opération sur un objectif (garder, abandonner, réorienter, créer avec un type) ; score des options. Le gouverneur du § 1.1 borne toutes ces sorties.

Règle : le moteur résume les voxels en quelques choses saillantes ; le modèle ne voit jamais de voxels. Précisions du fil des données : 17 types de jetons au lieu de 14, contexte porté d'environ 64 à 80 jetons, direction en sinus et cosinus relatifs au PNJ, propriétaire d'une chose en pointeur vers son jeton `ENTITY`.

## 7. Les actions

### 7.1 Les 112 fonctions du contrat

Arguments, conditions et animations : `ai/CONTRAT_PNJ.md`. `*` = extension.

| Catégorie | Fonctions |
|---|---|
| corps | eat, drink, sleep, rest, dress |
| déplacement | go_to, follow, approach, avoid, flee, wander, wait, hide*, return_home |
| travail | equip, unequip, dig, place, till, plant, harvest, cut, fetch_water, craft, build*, repair*, tend_crop*, hunt*, start_build*, contribute*, supply* |
| objets | pick_up, drop, store, take_from, give, steal, destroy*, claim*, conceal* |
| parole | greet, chat, inform, deceive, ask, propose, request, order, accept, refuse, promise, threaten, accuse, apologize, thank, compliment, insult, warn, call_for_help, comfort, forgive, teach* |
| tractation | interrogate, bribe, answer, blackmail, negotiate, lobby* |
| vie publique | read, post_notice, tear_down_notice, publish*, write_letter*, call_vote, vote, campaign, claim_title, contest_claim, endorse, appoint, dismiss, create_title, decree, enforce, summon, delegate*, found_group*, join_group*, leave_group*, post_job*, hire* |
| tendresse (jamais explicite, adultes seulement) | flirt, kiss, embrace, be_intimate |
| conflit | attack, defend, chase, restrain*, expel |
| soin | heal*, assist |
| attention | observe, search, eavesdrop*, investigate* |
| loisirs et rites | leisure, pray*, mourn* |
| engagement | accompany, break_commitment, continue |

Conditions (20) : found, sees, hears, hp_below, hunger_above, thirst_above, fatigue_above, tool_worn, tool_broken, inventory_full, entity_near, attacked, obstacle, unsafe, time_after, elapsed_over, reached, addressed, message_from, done.

### 7.2 Actions du monde qui manquent (proposées, à ajouter en fin de contrat)

Ce que Monsieur veut voir arriver (eau, feu, effondrements, frontières) demande des verbes que le contrat n'a pas. Proposition, à valider par le fil du moteur (`interfaces.md` § 6) puis le fil Transformer (vocabulaire) :

| Fonction proposée | Arguments | Pourquoi |
|---|---|---|
| `pour` | item (eau), place | vider un seau : l'eau se répand |
| `light_fire`, `extinguish` | place | le feu comme phénomène, pas comme décor |
| `shore_up` | target (structure) | étayer une galerie, un pont |
| `demolish` | target | détruire volontairement une structure |
| `carry` | item, place | le transport réel des matériaux |
| `swim`, `climb` | place | eau profonde, falaises (animations déjà listées) |
| `travel` | place (autre village) | voyage de plusieurs heures, distinct de `go_to` |
| `explore` | frontière, profondeur visée | partir au-delà ; la simulation l'exécute déjà avec `go_to` + `search` |
| `trade` | item, entity | acheter ou vendre au marché ; aujourd'hui `negotiate` |
| `teach` passe du statut d'extension au noyau | entity, skill | la transmission des savoirs est au cœur du jeu |
| `change_job` | job | mobilité sociale (charte § 24) : aujourd'hui seul l'apprentissage ou l'exode change un métier |
| `smash` | target, tool (masse) | la masse désassemble les constructions en éléments (charte § 17) |
| `buy_service` | entity, task | payer un artisan pour construire (charte § 17) |

### 7.3 Ce que le moteur propose au modèle

À chaque décision, le moteur liste **ce qui est faisable**, jamais ce qui est souhaitable (`sim/emergence_sim/options.py`) : au plus 16 options, chacune sous forme de fonction du contrat avec ses arguments. Seules des limites physiques, légales ou dures filtrent : âge, cible vivante, nourriture à la maison, monnaie pour payer, chef à défier, règle de la romance. Les personnes ciblées sont choisies par saillance (présence, force du lien), pas par préférence.

## 8. Événements émis par la simulation

Flux `sim-events-0.1` (`interfaces.md` § 9). Types : birth, death, wedding, engagement, elopement, separation, apprenticeship, craft_lost, craft_lost_village, craft_rediscovered, theft_caught, brawl, murder, verdict, exile, election, decree, challenge, embezzlement_exposed, expedition, vanished, record_depth, legend_born, epidemic, epidemic_end, accident, collapse, adoption, orphaned, guild_founded, cult_founded, feud, feud_peace, affair_exposed, festival, robbery, outlaw_band, pardon, famine, famine_relief, migration, blackmail, lie_exposed, rescue.

Types de souvenirs de la simulation aujourd'hui (21) : helped, kindness, betrayed, liar, insulted, theft_victim, saw_theft, brawl, murder, rejected, heartbreak, affair_seen, affair_secret, embezzle, embezzle_secret, verdict_unjust, death_kin, death_friend, birth, wedding, recovered. 12 ont un équivalent dans le vocabulaire du modèle (`sim_adapter.MEMORY`) ; les 9 autres (deuils, naissances, noces, chagrin, guérison, secrets) n'atteignent pas encore le modèle et sont à ajouter au vocabulaire.

## 9. Bilan

- **Vu par le modèle et simulé** : le cœur du PNJ (traits, valeurs, pulsions, besoins, émotions principales, corps), ses relations, ses souvenirs, son métier, son foyer et l'essentiel de son village.
- **Vu par le modèle mais neutre dans la simulation** : tempérament, force, crainte envers les autres, humeur et soupçon envers eux, réputations, coutumes fines du village, inventaire porté. Ces champs reçoivent une valeur fixe (`sim/emergence_sim/live.py`, `NEUTRAL`) tant que la simulation ne les calcule pas.
- **Simulé mais pas encore vu par le modèle** : piété, croyance en l'au-delà, solitude, deuil, maladie, décrets, savoirs perdus, querelles de foyers, groupes, frontières, légendes.
- **Ni l'un ni l'autre** : la perception de l'espace (§ 6), le progrès des objectifs et les types d'objectifs de la charte (§ 2.12), l'horloge du vieillissement (§ 5.1), le monde physique fin (§ 5.2 à 5.5) et les actions du monde qui manquent (§ 7.2).
- **Sortie du modèle** : il choisit une option ; le moteur déroule ensuite l'option en une séquence de 1 à 6 étapes. L'écriture de l'état, des relations, des souvenirs et des objectifs (§ 1.1) est prête côté moteur, mais la tête de sortie du modèle qui la produit n'existe pas encore.

## 10. Questions ouvertes pour Monsieur

| N° | Question | Défaut en attendant |
|---|---|---|
| Q1 | ~~Les traits bougent-ils ?~~ Tranchée par la charte § 6 : oui, lentement. | 0,1 par jour de jeu au plus |
| Q2 | Combien d'appels du Transformer par seconde et par PNJ en jeu ? | à chaque fin de plan, interruption ou événement, plus un réveil périodique |
| Q3 | Quel modèle « bien moins cher » produit les données d'entraînement, et avec quel budget ? | rien n'est lancé |
| Q4 | Le modèle voit 9 souvenirs par décision : faut-il une mémoire longue (résumé, recherche) ? | 9 par saillance |
| Q5 | Faut-il garder les 10 traits reportés de v0.1 (prudence, loyauté, fierté, générosité…) ? | reportés |
| Q6 | Charte § 25 : une vie d'environ 150 heures de jeu. Avec 1 jour de jeu = 4 h réelles (P14), une vie de 70 ans durerait plus de 100 000 h. Faut-il une horloge de vieillissement séparée du calendrier, ou un calendrier compressé ? | rien n'est changé ; décision avec le fil du moteur |
