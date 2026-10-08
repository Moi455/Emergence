# Variables de la simulation sociale — catalogue

Version 0.1 — 30/09/2026. Catalogue des variables uniquement (ni règles ni fonctionnement).

## 0. Légende et conventions

| Symbole | Sens |
|---|---|
| ● | noyau : nécessaire à la tranche verticale (1 village, 20 à 40 PNJ) |
| ○ | extension : à ajouter après la tranche verticale |
| S | variable stockée |
| D | variable dérivée : calculée à partir d'autres variables, non stockée |
| [a;b] | plage numérique |
| id | identifiant unique |
| énum | valeur parmi une liste fermée |

Conventions :
- Une variable n'apparaît qu'une seule fois dans le catalogue.
- Les valeurs relationnelles sont stockées de façon parcimonieuse : seulement pour les individus connus.
- Aucune habitude et aucune conclusion psychologique ne sont stockées : elles émergent des observations mémorisées.
- Le joueur possède exactement les mêmes variables qu'un PNJ (section 21 pour son interface).

---

## 1. Identité et corps

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| id | id | ● S | identifiant unique |
| nom | texte | ● S | réservé au joueur et au verbalisateur, jamais au modèle de décision |
| est_joueur | booléen | ● S | |
| niveau_IA | énum {léger, avancé} | ● S | |
| âge | années | ● S | |
| catégorie_âge | énum {enfant, adolescent, adulte, ancien} | ● D | sert au filtre de faisabilité : aucune action sexuelle ou romantique impliquant « enfant » |
| sexe | énum | ○ S | |
| vivant | booléen | ● S | |
| date_naissance, date_décès | horodatage | ○ S | |
| cause_décès | énum | ○ S | |
| village_d_origine | id | ● S | |
| position (x, y) | flottants | ● S | |
| orientation | angle | ● S | |
| destination, chemin_en_cours | position, liste de cellules | ● S | |
| posture | énum {debout, assis, allongé, caché, endormi} | ● S | |
| points_de_vie | [0;100] | ● S | |
| force, endurance, agilité, robustesse | [0;100] | ● S | |
| capacité_de_charge | kg | ● D | dérivée de force et endurance |
| vitesse_de_déplacement | m/s | ● D | dérivée du corps, de la charge, de la fatigue, du terrain |
| acuité_visuelle, acuité_auditive | [0;100] | ● S | |
| blessures[] | liste (localisation, gravité, saignement, infection) | ○ S | |
| maladies[] | liste (type, stade, contagiosité, durée) | ○ S | |
| handicaps[] | liste | ○ S | |
| grossesse | énum {non, enceinte} + stade | ○ S | |
| fertilité | [0;100] | ○ S | |
| apparence : beauté | [0;100] | ○ S | stimulus perçu par les autres, pas une préférence |
| apparence : propreté | [0;100] | ○ S | |
| apparence : signes_visibles | liste (âge apparent, blessures visibles, tenue) | ○ D | |

---

## 2. Personnalité (traits stables)

Tous les traits sont des axes [-100;100].

| Variable | -100 | +100 | Statut |
|---|---|---|---|
| agressivité | douceur, évitement | confrontation | ● S |
| courage | peureux | courageux | ● S |
| prudence | témérité | prudence | ● S |
| empathie | indifférence | empathie | ● S |
| sociabilité | solitaire | sociable | ● S |
| ambition | peu ambitieux | très ambitieux | ● S |
| honnêteté | trompeur | honnête | ● S |
| impulsivité | réfléchi | impulsif | ● S |
| curiosité | conservateur | curieux | ● S |
| tolérance | intolérant | tolérant | ● S |
| justice | indifférent à l'injustice | très sensible à l'injustice | ● S |
| loyauté | infidèle | très loyal | ● S |
| rancune | indulgent | rancunier | ● S |
| possessivité | détaché | possessif, jaloux | ● S |
| fierté | humble | très sensible à l'humiliation | ● S |
| générosité | avare | généreux | ● S |
| diligence | paresseux | travailleur | ● S |
| conformisme | rebelle | conformiste | ● S |
| sensualité | réservé | très sensuel | ● S |
| spiritualité | indifférent | très spirituel | ○ S |
| intelligence | lent | vif | ○ S |

Tempérament émotionnel :

| Variable | Plage | Statut | Note |
|---|---|---|---|
| réactivité_émotionnelle | [0;100] | ● S | amplitude des variations d'états |
| résilience | [0;100] | ● S | vitesse de retour vers le niveau de base |
| humeur_de_base | [-100;100] | ● S | niveau de repos de la joie |
| stress_de_base | [-100;100] | ○ S | niveau de repos du stress |

---

## 3. Valeurs et normes personnelles

Importance accordée, [0;100].

| Variable | Statut | Note |
|---|---|---|
| protection_des_proches | ● S | |
| loyauté_au_groupe | ● S | |
| respect_de_l_autorité | ● S | |
| respect_de_la_propriété | ● S | |
| honneur_réputation | ● S | |
| valeur_de_la_vie | ● S | aversion à tuer ou blesser |
| fidélité_amoureuse | ● S | attente d'exclusivité |
| pureté_sacré | ○ S | tabous, dégoût moral |
| liberté_autonomie | ○ S | |
| tradition | ○ S | |
| hospitalité | ○ S | |
| normes_intériorisées[] | ○ S | liste (type d'action, contexte, valence [-100;100], force [0;100]) acquise par l'éducation et l'observation |

---

## 4. Préférences

Structure : catégorie → objet → valeur [-100;100], hiérarchie du général au spécifique (la préférence la plus spécifique non neutre est prioritaire).

| Variable | Plage | Statut | Note |
|---|---|---|---|
| préférence.objet_id | id | ● S | |
| préférence.parent_id | id | ● S | niveau supérieur dans la hiérarchie |
| préférence.valeur | [-100;100] | ● S | |
| catégorie : consommation (aliments, boissons) | | ● S | |
| catégorie : activités (travail, loisirs, jeux, activités sociales) | | ● S | |
| catégorie : métiers | | ● S | |
| catégorie : lieux | | ● S | |
| catégorie : biomes | | ● S | |
| catégorie : itinéraires | | ● S | |
| catégorie : saisons | | ● S | |
| catégorie : météo | | ● S | |
| catégorie : moments (matin, après-midi, soir, nuit) | | ● S | |
| catégorie : couleurs | | ● S | |
| catégorie : matériaux et objets | | ● S | |
| catégorie : animaux | | ○ S | |
| catégorie : taille_de_groupe_préférée | | ○ S | solitude ↔ foule |
| idéal_partenaire (un vecteur par axe de personnalité + âge + apparence) | [-100;100] par axe | ● S | tiré au hasard à la création du PNJ, jamais configuré à la main |
| traits_valorisés_chez_autrui[axe] | [-100;100] par axe | ○ S | amitié, collaboration |

---

## 5. Pulsions et besoins non physiologiques

Chaque pulsion possède les trois sous-variables : niveau, taux d'accumulation, dernier assouvissement.

| Pulsion | niveau | taux_accumulation | dernier_assouvissement | Statut |
|---|---|---|---|---|
| libido | [0;100] | [0;100] | horodatage | ● S |
| contact_social | [0;100] | [0;100] | horodatage | ● S |
| sécurité | [0;100] | dérivé | dérivé | ● D |
| reconnaissance | [0;100] | [0;100] | horodatage | ● S |
| accomplissement | [0;100] | [0;100] | horodatage | ● S |
| nouveauté | [0;100] | [0;100] | horodatage | ● S |
| calme_intimité | [0;100] | [0;100] | horodatage | ○ S |
| accumulation | [0;100] | [0;100] | horodatage | ● S |
| confort (chaleur, abri) | [0;100] | dérivé | dérivé | ● D |
| spiritualité | [0;100] | [0;100] | horodatage | ○ S |

---

## 6. États instantanés

### 6.1 États généraux

| Variable | Plage | Statut | Note |
|---|---|---|---|
| faim | [0;100] | ● S | |
| soif | [0;100] | ● S | |
| fatigue | [-100;100] | ● S | -100 reposé, +100 épuisé |
| douleur | [0;100] | ● S | |
| peur | [0;100] | ● S | |
| colère | [-100;100] | ● S | -100 très calme |
| stress | [-100;100] | ● S | |
| joie | [-100;100] | ● S | -100 très triste |
| choc | [0;100] | ● S | |
| confort_thermique | [-100;100] | ● S | -100 froid, +100 chaud |
| surprise | [0;100] | ● S | |
| confusion | [0;100] | ● S | événement incompréhensible ou hors du monde |
| honte | [0;100] | ● S | |
| culpabilité | [0;100] | ● S | |
| fierté_ressentie | [0;100] | ● S | |
| ennui | [0;100] | ● S | |
| deuil | [0;100] | ● S | décroissance très lente |
| dégoût | [0;100] | ○ S | |
| jalousie_générale | [0;100] | ○ S | |
| hygiène | [0;100] | ○ S | |
| ébriété | [0;100] | ○ S | |
| solitude_ressentie | [0;100] | ● D | dérivée de contact_social et de la présence d'autrui |

### 6.2 États envers un individu

| Variable | Plage | Statut |
|---|---|---|
| humeur_envers | [-100;100] | ● S |
| envie_d_interaction | [-100;100] | ● S |
| attirance_du_moment | [-100;100] | ○ S |

### 6.3 État d'activité

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| action_en_cours | id | ● S | |
| phase_de_l_action | énum {préparation, exécution, fin} | ● S | |
| progression | [0;1] | ● S | |
| degré_d_engagement | [0;100] | ● S | fixe le seuil d'interruption |
| dernière_décision | horodatage | ● S | |
| temps_depuis_dernière_décision | secondes | ● D | |
| en_conversation_avec | liste d'id | ● S | |

---

## 7. Relations (de A vers B, asymétriques)

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| affection | [-100;100] | ● S | haine ↔ amour |
| confiance | [-100;100] | ● S | |
| crainte | [0;100] | ● S | |
| respect | [-100;100] | ● S | mépris ↔ admiration |
| attirance_romantique | [-100;100] | ● S | répulsion ↔ désir, distincte de l'affection |
| attachement | [0;100] | ● S | intimité, proximité émotionnelle |
| familiarité | [0;100] | ● S | niveau de connaissance mutuelle |
| dette | [-100;100] | ● S | -100 je lui dois beaucoup, +100 il me doit beaucoup |
| gratitude_accumulée | [0;100] | ● S | |
| grief_accumulé | [0;100] | ● S | rancune non résolue, dynamique lente |
| autorité_reconnue | [-100;100] | ● S | légitimité que j'accorde à B de me commander |
| rivalité | [0;100] | ○ S | |
| jalousie_envers | [0;100] | ○ S | |
| dépendance | [0;100] | ○ S | |
| loyauté_envers | [0;100] | ○ S | |
| dernier_contact | horodatage | ● S | |
| nb_interactions_positives, nb_interactions_négatives | entiers | ● S | |
| souvenirs_clés[] | liste d'id de souvenirs | ● S | justifient l'état actuel de la relation |
| liens_typés[] | liste d'énum + depuis | ● S | parent, enfant, frère_sœur, grand-parent, oncle_tante, cousin, conjoint, fiancé, ex_partenaire, ami, voisin, collègue, employeur, employé, maître, apprenti, rival, ennemi_déclaré, protecteur, protégé, créancier, débiteur |
| statut_amoureux (de soi) | énum {célibataire, courtise, en_couple, marié, séparé, veuf} | ● S | |
| partenaire_actuel | id | ● S | |

---

## 8. Image des autres et réputation (croyances sociales)

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| traits_perçus[B][axe] | [-100;100] | ○ S | personnalité que je crois à B |
| confiance_dans_l_estimation | [0;1] | ○ S | |
| valeurs_perçues[B][valeur] | [0;100] | ○ S | |
| intention_supposée[B] | énum | ○ S | |
| réputation_connue[B][dimension] | [-100;100] | ● S | dimensions : fiabilité, dangerosité, générosité, moralité, compétence |
| source_de_la_réputation | énum {vu, ouï-dire} | ● S | |
| statut_perçu[B] | [0;100] | ● S | rang social que je lui attribue |
| secrets_connus_sur[B] | liste d'id de souvenirs | ○ S | |
| croyance_relation(B, C) | énum / [-100;100] | ○ S | ce que je crois de la relation entre B et C |

---

## 9. Mémoire et connaissances

### 9.1 Paramètres

| Variable | Plage / type | Statut |
|---|---|---|
| capacité_mémoire | entier | ● S |
| taux_d_oubli | [0;100] | ● S |
| attention(A, B) | [0;100] | ● D |

### 9.2 Observation brute

| Variable | Type | Statut |
|---|---|---|
| target_id | id | ● S |
| location_id | id | ● S |
| timestamp | horodatage | ● S |

### 9.3 Souvenir d'événement

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| souvenir.id | id | ● S | |
| type_événement | énum (vocabulaire des actions et des événements subis) | ● S | |
| agent, cible, objet | id | ● S | |
| lieu | id | ● S | |
| horodatage | horodatage | ● S | |
| source | énum {vu, entendu, rapporté (id), déduit} | ● S | |
| certitude | [0;1] | ● S | |
| importance | [0;100] | ● S | |
| valence_ressentie | [-100;100] | ● S | |
| émotions_associées | instantané des états | ○ S | |
| nb_rappels, dernier_rappel | entier, horodatage | ○ S | |
| version_altérée | booléen / degré de distorsion | ○ S | |
| cause_id | id | ● S | chaîne causale, sert à justifier une relation |
| marquant | booléen | ● S | jamais oublié |

### 9.4 Connaissances

| Variable | Contenu | Statut |
|---|---|---|
| individus_connus | id → nom, familiarité, dernière position connue | ● S |
| lieux_connus | id → position, type, dernière visite | ● S |
| carte_mentale | cellules et chemins connus | ● S |
| ressources_connues | lieu, type, quantité estimée, fraîcheur | ● S |
| prix_connus | bien → valeur d'échange estimée, fraîcheur | ● S |
| propriétaires_connus | objet ou lieu → id | ● S |
| recettes_connues | liste d'id de recettes | ● S |
| rumeurs_en_circulation[] | contenu, source, crédibilité, date | ● S |
| secrets_détenus[] | liste d'id de souvenirs | ○ S |
| événements_marquants_de_vie[] | naissance, mariage, deuil, départ, exil, etc. | ○ S |
| où_est(target) | distribution de probabilité par lieu | ● D |

---

## 10. Buts, intentions, engagements

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| but.id | id | ● S | |
| but.type | énum {besoin, relation, possession, statut, vengeance, protection, découverte, projet, demande_d_autrui} | ● S | |
| but.cible | id | ● S | |
| but.priorité | [0;100] | ● S | |
| but.origine | id (souvenir, besoin ou demande) | ● S | |
| but.échéance | horodatage | ● S | |
| but.conditions_de_réussite | structure | ● S | |
| but.conditions_d_abandon | structure | ● S | |
| but.progrès | [0;1] | ● S | |
| but.créé_le | horodatage | ● S | |
| intention_courante | id de but + action suivante | ● S | |
| plan[] | liste d'étapes | ○ S | utilisé par les PNJ avancés |
| horizon_de_planification | heures de jeu | ○ S | PNJ avancés |
| engagement.id | id | ● S | |
| engagement.envers | id | ● S | |
| engagement.type | énum {promesse, serment, contrat, accompagnement, service, mariage, emploi} | ● S | |
| engagement.contenu | structure | ● S | |
| engagement.début, fin_prévue | horodatage | ● S | |
| engagement.conditions_de_rupture | structure | ● S | |
| engagement.degré | [0;100] | ● S | |
| engagement.statut | énum {actif, rempli, rompu} | ● S | |
| demande_reçue.de | id | ● S | |
| demande_reçue.contenu | proposition structurée | ● S | |
| demande_reçue.date | horodatage | ● S | |
| demande_reçue.statut | énum {en_attente, acceptée, refusée} | ● S | |
| aspiration.type | énum {métier, mariage, propriété, pouvoir, vengeance, savoir, famille} | ○ S | |
| aspiration.cible | id | ○ S | |
| aspiration.intensité | [0;100] | ○ S | |

---

## 11. Compétences et travail

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| compétence[domaine] | [0;100] | ● S | domaines : agriculture, élevage, bûcheronnage, minage, taille_de_pierre, forge, menuiserie, construction, tissage_couture, cuisine, chasse, pêche, soin_herboristerie, commerce, combat_mêlée, persuasion, discrétion, enseignement, orientation |
| compétence.expérience | nombre | ○ S | alimente la progression |
| métier_actuel | énum | ● S | |
| rôle_social | énum | ● S | par exemple fermier, forgeron, chef, marchand |
| ancienneté_dans_le_métier | durée | ○ S | |
| employeur | id | ○ S | |
| rémunération_convenue | structure | ○ S | |
| apprentissage_en_cours | compétence, maître, progrès | ○ S | |

---

## 12. Possessions et économie individuelle

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| inventaire[] | type, quantité, qualité [0;100], usure [0;100], fraîcheur | ● S | |
| inventaire.propriétaire_légitime | id | ● S | différent du détenteur si l'objet est volé ou prêté |
| inventaire.caché | booléen | ○ S | |
| équipement_porté[] | emplacement, objet | ● S | |
| stocks_cibles[catégorie] | niveau visé | ● S | fixe le manque de stock |
| logement | id de bâtiment | ● S | |
| terres_possédées[] | liste de cellules ou de champs | ● S | |
| atelier | id de bâtiment | ○ S | |
| bétail[] | liste d'id d'animaux | ○ S | |
| monnaie | nombre | ○ S | unité d'échange si le monde en a une |
| créances[] | autre, objet ou valeur, date, échéance | ● S | |
| dettes[] | autre, objet ou valeur, date, échéance | ● S | |
| richesse_estimée | nombre | ● D | |

---

## 13. Perception

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| rayon_intime | mètres | ● S | fixe |
| rayon_discussion, rayon_collaboration, rayon_présence | mètres | ● D | dépendent de l'environnement |
| champ_de_vision | angle | ● S | |
| degré_de_perception(entité) | [0;1] | ● D | distance, cellules traversées, terrain, obstacles, luminosité, bruit |
| niveau_de_compréhension | énum {aucun, présence, interaction_vue, action_identifiée, compréhension_complète} | ● D | |
| bruit_émis(événement) | [0;1] | ● D | |
| bruit_ambiant(lieu) | [0;1] | ● D | |
| attention_actuelle | id d'entité | ○ S | |
| liste_perçue[] | id, degré, distance, action_visible | ● D | |
| saillance_objective(événement) | [0;100] | ● D | intensité, danger, gravité, durée, visibilité, bruit, proximité |
| saillance_perçue(événement) | [0;100] | ● D | saillance objective filtrée par la personnalité, les préférences et les relations |
| intérêt_opportunité(objet ou lieu) | [0;100] | ● D | valeur × manque de stock − coût du détour − risque |
| seuil_de_réveil | [0;100] | ● D | fonction du degré d'engagement |

---

## 14. Actions, événements et interprétation

### 14.1 Action

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| action.id | id | ● S | |
| agent | id | ● S | |
| type | énum (vocabulaire d'actions, plus de 200) | ● S | |
| cible | id | ● S | |
| objet | id | ● S | |
| contenu | structure (acte de parole, proposition, consigne) | ● S | |
| intensité | [0;100] | ● S | |
| durée_prévue | secondes de jeu | ● S | |
| lieu | id | ● S | |
| contexte | public ou privé, témoins présents | ● S | |
| horodatage_début | horodatage | ● S | |
| statut | énum {planifiée, en_cours, achevée, interrompue, échouée} | ● S | |
| cause_id | id | ● S | |

### 14.2 Conséquences objectives

| Variable | Plage / type | Statut |
|---|---|---|
| changements_monde[] | dégâts, transfert_de_propriété, déplacement, production, consommation, destruction, construction, information_transmise, modification_du_terrain | ● S |
| dégâts | [0;100] | ● S |
| objets_transférés | liste | ● S |
| états_modifiés | liste | ● S |
| visibilité | [0;1] | ● S |
| bruit | [0;1] | ● S |
| témoins_potentiels[] | liste d'id | ● D |

### 14.3 Événement perçu

| Variable | Plage / type | Statut |
|---|---|---|
| événement_perçu.id | id | ● S |
| observateur | id | ● S |
| rôle_de_l_observateur | énum {agent, cible, témoin, rapporteur} | ● S |
| source_de_l_information | énum {vu, entendu, rapporté} | ● S |
| niveau_de_compréhension | énum (voir section 13) | ● S |
| fiabilité | [0;1] | ● S |
| délai | secondes de jeu | ● S |

### 14.4 Acte de parole

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| type_d_acte | énum {informer, demander, proposer, ordonner, promettre, menacer, accuser, mentir, etc.} | ● S | |
| émetteur | id | ● S | |
| destinataires, audience | listes d'id | ● S | |
| contenu_propositionnel | fait ou demande structuré | ● S | |
| ton | énum {chuchoté, normal, crié} | ● S | |
| véracité_objective | booléen | ● S | connue du moteur seulement |
| croyance_de_l_émetteur | contenu | ● S | connue du moteur seulement, distingue le mensonge de l'erreur |
| vecteur_sémantique | 384 flottants | ○ S | énoncé du joueur en langage naturel |
| hors_monde | booléen | ● S | concept inexistant dans le monde du jeu |

### 14.5 Table d'évaluation des normes

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| violation_norme[action × contexte × relation] | vecteur [0;100] sur les valeurs (section 3) | ● S | table construite une fois, hors ligne |
| menace_intrinsèque[action × contexte] | [0;100] | ● S | |
| désirabilité_intrinsèque[action × contexte] | [-100;100] | ● S | |

### 14.6 Interprétation (sortie du modèle)

| Variable | Plage / type | Statut |
|---|---|---|
| intentionnalité_perçue | [0;1] | ● S |
| gravité_perçue | [0;100] | ● S |
| légitimité_perçue | [-100;100] | ● S |
| menace_perçue | [0;100] | ● S |
| responsabilité_attribuée | id + degré [0;1] | ● S |
| valence_pour_moi | [-100;100] | ● S |
| valence_pour_autrui[id] | [-100;100] | ○ S |
| congruence_avec_mes_buts | [-100;100] | ● S |
| normes_violées | vecteur [0;100] | ● S |
| importance_mémorielle | [0;100] | ● S |

---

## 15. Société : groupes, statut, normes (couche 2)

### 15.1 Groupe

| Variable | Plage / type | Statut |
|---|---|---|
| groupe.id | id | ● S |
| type | énum {foyer, famille, clan, corporation, bande, village, couple, autre} | ● S |
| membres[] | liste d'id | ● S |
| rôles[membre] | énum | ● S |
| chefs[] | liste d'id | ● S |
| rang[membre] | [0;100] | ● S |
| normes_du_groupe | vecteur sur les valeurs | ● D |
| ressources_communes | inventaire | ● S |
| territoire | liste de cellules | ● S |
| cohésion | [0;100] | ● D |
| réputation_du_groupe | [-100;100] | ● D |
| date_de_création | horodatage | ● S |
| histoire[] | liste d'id de souvenirs | ○ S |

### 15.2 Lien de l'individu au groupe

| Variable | Plage / type | Statut |
|---|---|---|
| appartenances[] | liste d'id de groupes | ● S |
| rang_dans_le_groupe | [0;100] | ● S |
| statut_d_appartenance | énum {membre, invité, banni, exclu} | ● S |
| identification_au_groupe | [0;100] | ○ S |

### 15.3 Statut social

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| prestige | [0;100] | ● D | agrégat du respect reçu |
| influence | [0;100] | ● D | |
| autorité_formelle | énum (rôle) | ● S | |
| richesse_perçue_par_autrui | [0;100] | ● D | |
| réputation_communautaire[dimension] | [-100;100] | ● D | agrégat des réputations connues |

### 15.4 Normes sociales locales

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| norme.type_d_action | énum | ● S | |
| norme.contexte | structure | ● S | |
| norme.relation | énum | ● S | |
| norme.valence | [-100;100] | ● S | |
| norme.sévérité | [0;100] | ● S | |
| norme.sanction_attendue | énum {aucune, rejet, amende, coups, bannissement, mort} | ● S | |
| norme.consensus | [0;1] | ● D | part des membres qui y adhèrent |
| norme.origine | énum {émergente, instituée} | ○ S | |

### 15.5 Économie locale

| Variable | Plage / type | Statut |
|---|---|---|
| prix_du_marché[bien] | nombre | ● D |
| offre[bien], demande[bien] | nombres | ● D |
| stock_communautaire[bien] | nombre | ● S |

### 15.6 Institutions

| Variable | Contenu | Statut |
|---|---|---|
| marché | lieu, périodicité, prix par bien | ○ S |
| affaire_en_justice | accusé, plaignant, témoins, verdict, peine | ○ S |
| titres_de_propriété | objet ou terrain → propriétaire | ○ S |
| règle_d_héritage | structure | ○ S |
| rites_du_mariage | conditions, cérémonie | ○ S |
| corvées | tâche, répartition | ○ S |

---

## 16. Sociétés : villages (couche 3)

### 16.1 Village

| Variable | Plage / type | Statut |
|---|---|---|
| village.id, nom, position | id, texte, position | ● S |
| population | entier | ● D |
| pyramide_des_âges | histogramme | ● D |
| stocks_totaux[bien] | nombres | ● D |
| production[bien] | nombres | ● D |
| consommation[bien] | nombres | ● D |
| solde_des_ressources[bien] | nombres | ● D |
| bâtiments[] | liste d'id | ● S |
| ressources_naturelles_accessibles[] | liste | ● D |
| dirigeants[] | liste d'id | ● S |
| culture (valeurs moyennes) | vecteur sur les valeurs | ● D |
| normes_dominantes | liste | ● D |
| cohésion, prospérité, sécurité, santé_publique | [0;100] | ● D |

### 16.2 Relations entre villages

| Variable | Plage / type | Statut |
|---|---|---|
| amitié_hostilité | [-100;100] | ○ S |
| confiance_inter_villages | [-100;100] | ○ S |
| flux_commerciaux[bien] | nombres | ○ D |
| dépendance | [0;100] | ○ D |
| traités_alliances[] | liste | ○ S |
| conflit_en_cours | énum {aucun, tension, raids, guerre} | ○ S |
| routes | distance, sécurité, fréquentation | ○ S |
| réputation_de_A_chez_B | [-100;100] | ○ D |

### 16.3 Flux et événements collectifs

| Variable | Contenu | Statut |
|---|---|---|
| migrations | individu, origine, destination | ○ S |
| caravanes | contenu, itinéraire | ○ S |
| messagers | contenu, destinataire | ○ S |
| événement_collectif | type {fête, marché, assemblée, épidémie, famine}, village, durée | ○ S |

---

## 17. Monde : terrain, ressources, bâtiments

### 17.1 Cellule de la grille 2D

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| x, y | entiers | ● S | |
| type_terrain | énum {plaine, forêt, roche, eau, marécage, montagne, chemin, bâtiment} | ● S | |
| opacité_vue | [0;1] | ● S | |
| opacité_son | [0;1] | ● S | |
| coût_de_déplacement | nombre | ● S | |
| franchissable | booléen | ● S | |
| altitude, pente | nombres | ○ S | |
| fertilité_du_sol | [0;100] | ● S | |
| humidité | [0;100] | ● S | |
| température | °C | ○ S | |
| couvert_végétal | énum {aucun, herbe, buissons, forêt_jeune, forêt_dense, cultures} | ● S | |
| densité_d_arbres | [0;100] | ● S | |
| état_du_sol | énum {nu, labouré, semé, cultivé, jachère, bâti} | ● S | |
| culture | espèce, stade, santé, jours_avant_récolte | ● S | |
| ressource_minérale | type, quantité_restante, richesse, profondeur | ● S | |
| eau | type {source, rivière, puits, étang}, débit, niveau, potabilité | ● S | |
| propriétaire | id ou groupe | ● S | |
| zone_d_usage | énum {public, privé, commun} | ● S | |
| danger | [0;100] | ● S | |
| traces_de_passage | fréquentation récente | ○ S | |
| feu | état et intensité | ○ S | |
| construction_id | id | ● S | |

### 17.2 Ressource du monde (définition pilotée par les données)

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| ressource.id, nom | id, texte | ● S | |
| catégorie | énum {végétal, minéral, eau, animal, sol} | ● S | |
| quantité_max | nombre | ● S | |
| régénération | taux et conditions | ● S | |
| accessibilité | [0;1] | ● S | |
| affordance.action | énum (couper, miner, labourer, planter, récolter, puiser, pêcher, chasser, etc.) | ● S | |
| affordance.outil_requis | liste de types d'objet | ● S | |
| affordance.compétence_requise | domaine + niveau | ● S | |
| affordance.effort | [0;100] | ● S | |
| affordance.durée | secondes de jeu | ● S | |
| affordance.rendement | objet, quantité, variance | ● S | |
| affordance.épuisement_par_usage | nombre | ● S | |
| affordance.risque_dégâts | [0;100] | ● S | |
| effets_secondaires | changement d'état du sol ou du couvert (par exemple défrichement) | ● S | |
| saisonnalité | saisons disponibles | ● S | |

### 17.3 Bâtiment

| Variable | Plage / type | Statut |
|---|---|---|
| bâtiment.id, type | id, énum | ● S |
| cellules | liste | ● S |
| propriétaire | id ou groupe | ● S |
| résidents[] | liste d'id | ● S |
| usages (affordances) | dormir, cuisiner, forger, stocker, vendre, réunir | ● S |
| capacité_de_stockage | nombre | ● S |
| contenu | inventaire | ● S |
| état_usure | [0;100] | ● S |
| verrouillage | énum {ouvert, fermé, verrouillé} | ● S |
| caractère | énum {public, privé, sacré} | ● S |
| construction_en_cours | progrès, matériaux restants | ● S |
| température_intérieure | °C | ○ S |

### 17.4 Mine et routes

| Variable | Plage / type | Statut |
|---|---|---|
| mine.profondeur | mètres | ○ S |
| mine.galeries | liste | ○ S |
| mine.stabilité | [0;100] | ○ S |
| mine.qualité_d_air | [0;100] | ○ S |
| mine.veines[] | minerai, quantité | ○ S |
| route.cellules, usure | listes, [0;100] | ○ S |
| route.fréquentation | nombre | ○ D |

---

## 18. Objets et recettes (catalogue)

### 18.1 Type d'objet

| Variable | Plage / type | Statut |
|---|---|---|
| type.id, nom | id, texte | ● S |
| catégorie | énum {nourriture, boisson, matériau, combustible, outil, arme, vêtement, meuble, semence, conteneur, médicament, troc, ornement, objet_rituel} | ● S |
| poids, volume | nombres | ● S |
| valeur_d_échange_de_base | nombre | ● S |
| valeur_d_usage | nombre | ● S |
| durabilité | [0;100] | ● S |
| durée_de_vie (périssabilité) | durée | ● S |
| empilable | booléen | ● S |
| propriétés_physiques | tranchant, contondant, inflammable, isolant | ● S |
| effets_à_l_usage | variations d'états (faim, soif, santé, joie, etc.) | ● S |
| compétence_requise_pour_l_usage | domaine + niveau | ● S |
| dégâts (armes) | [0;100] | ● S |
| rareté | [0;100] | ● S |

### 18.2 Instance d'objet

| Variable | Plage / type | Statut |
|---|---|---|
| instance.id, type | id | ● S |
| quantité | entier | ● S |
| qualité | [0;100] | ● S |
| usure | [0;100] | ● S |
| fraîcheur | durée restante | ● S |
| propriétaire | id | ● S |
| localisation | inventaire, cellule ou bâtiment | ● S |
| marque_du_producteur | id | ○ S |

### 18.3 Recette

| Variable | Plage / type | Statut |
|---|---|---|
| recette.id | id | ● S |
| entrées[] | type, quantité | ● S |
| outils_requis[] | types d'objet | ● S |
| compétence | domaine + niveau | ● S |
| lieu_requis | affordance de bâtiment | ● S |
| durée | secondes de jeu | ● S |
| sorties[] | type, quantité, qualité = f(compétence) | ● S |
| déchets | types | ○ S |

---

## 19. Faune et flore

| Variable | Plage / type | Statut |
|---|---|---|
| plante.espèce | énum | ● S |
| plante.durées_de_croissance (par stade) | durées | ● S |
| plante.saisons_de_semis, saisons_de_récolte | listes | ● S |
| plante.besoin_en_eau | [0;100] | ● S |
| plante.fertilité_requise | [0;100] | ● S |
| plante.rendement | objet, quantité | ● S |
| plante.résistances (gel, sécheresse) | [0;100] | ○ S |
| plante.maladies | liste | ○ S |
| arbre.espèce, âge | énum, années | ● S |
| arbre.bois_disponible | nombre | ● S |
| arbre.croissance, repousse | taux | ● S |
| animal.espèce, âge, santé, faim | énum, années, [0;100] | ○ S |
| animal.statut | énum {domestique, sauvage} | ○ S |
| animal.agressivité, peur_des_humains | [0;100] | ○ S |
| animal.produits | lait, laine, viande, œufs | ○ S |
| animal.propriétaire | id | ○ S |
| animal.reproduction | état et cycle | ○ S |
| population_locale[espèce] | nombre | ○ D |
| pression_de_chasse_pêche | [0;100] | ○ D |

---

## 20. Temps et environnement

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| minute, heure | entiers | ● S | |
| jour, jour_de_semaine | entiers | ● S | |
| saison, année | énum, entier | ● S | |
| échelle_de_temps | facteur simulation / temps réel | ● S | |
| luminosité | [0;1] | ● S | |
| moment_de_la_journée | énum {matin, après-midi, soir, nuit} | ● D | |
| météo.type | énum {clair, nuageux, pluie, orage, neige, brouillard, vent} | ● S | |
| météo.température | °C | ● S | |
| météo.précipitations, vent, humidité | nombres | ● S | |
| effet_sur_la_perception | [0;1] | ● D | |
| effet_sur_le_déplacement | [0;1] | ● D | |
| événement_naturel | type {incendie, inondation, sécheresse, gel, épidémie, tempête}, intensité, zone, durée | ○ S | |
| calendrier | fêtes, saisons agricoles | ○ S | |

---

## 21. Joueur et interface

| Variable | Plage / type | Statut | Note |
|---|---|---|---|
| commande_structurée | cible, verbe, objet, contenu | ● S | même canal que les événements des PNJ |
| énoncé_texte | chaîne | ● S | langage naturel |
| cible_de_l_adresse | id | ● S | |
| ton_choisi | énum {chuchoté, normal, crié} | ○ S | |
| geste | énum | ○ S | |
| événement_converti | acte de parole + contenu + hors_monde | ● S | résultat de l'analyse de l'énoncé |
| réplique_verbalisée | texte | ● S | sortie du mini LLM |
| état_exposé_au_verbalisateur | sous-ensemble de variables du PNJ | ● S | |
| file_du_verbalisateur | une requête à la fois | ● S | |
| version_du_schéma | entier | ● S | sauvegarde |
| graine_aléatoire | entier | ● S | sauvegarde et rejouabilité |

---

## 22. Interface du modèle et dynamique

### 22.1 Entrées (jetons)

| Variable | Contenu | Statut |
|---|---|---|
| jeton_soi | personnalité, valeurs, états, pulsions, buts, engagement, heure | ● D |
| jetons_entités[K_e] | relations, perception, distance, action visible | ● D |
| jetons_souvenirs[K_m] | souvenirs les plus pertinents | ● D |
| jetons_événements[K_ev] | événements récents + vecteur de normes violées | ● D |
| jetons_buts[K_g] | buts et engagements actifs | ● D |
| contexte | lieu, météo, heure | ● D |
| masque_de_faisabilité | actions possibles à cet instant | ● D |
| embeddings_de_concepts | objets, activités, lieux (précalculés hors ligne) | ● S |

### 22.2 Sorties

| Variable | Plage / type | Statut |
|---|---|---|
| action | type, cible, objet, contenu, intensité, durée | ● |
| distribution_sur_les_actions | probabilités (pour l'échantillonnage) | ● |
| Δ_états[] | bornés | ● |
| Δ_relations[] | bornés | ● |
| nouveau_but | type, cible, priorité | ● |
| degré_d_engagement | [0;100] | ● |
| importance_mémorielle | [0;100] | ● |
| acte_de_parole | type, contenu | ● |

### 22.3 Paramètres de dynamique

| Variable | Plage / type | Statut |
|---|---|---|
| constante_de_retour[état] | temps | ● S |
| bornes[variable] | min, max | ● S |
| Δ_max_par_décision | [0;100] | ● S |
| température_d_échantillonnage | nombre | ● S |
| période_de_réveil_périodique | secondes de jeu, par niveau_IA | ● S |
| graine_aléatoire_par_PNJ | entier | ● S |

### 22.4 Diagnostic

| Variable | Plage / type | Statut |
|---|---|---|
| justification | ids des souvenirs et règles ayant pesé | ○ S |
| entropie_de_la_décision | nombre | ○ D |
| version_du_modèle | texte | ○ S |
