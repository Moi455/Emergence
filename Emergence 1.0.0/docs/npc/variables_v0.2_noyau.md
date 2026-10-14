# Variables de la simulation sociale — version resserrée (v0.2)

30/09/2026. Remplace v0.1 comme référence de travail (v0.1 reste le catalogue exhaustif).

## 0. Critère et légende

Une variable entre dans le **noyau** seulement si :
- elle change le comportement dans au moins un des trois scénarios de test (**accompagner le joueur**, **tomber amoureux**, **détester après un mensonge**), ou
- elle est nécessaire à la boucle de vie quotidienne qui les héberge (manger, boire, dormir, travailler, échanger).

Toute autre variable est reportée. Chaque variable du noyau doit avoir un écrivain (un événement ou une règle qui la modifie) et un lecteur (une décision ou une interprétation qui la lit).

| Niveau | Sens |
|---|---|
| **M** | entre dans le modèle de décision (jetons d'entrée) |
| **E** | stockée et utilisée par le moteur seulement ; le modèle n'en voit qu'un résumé éventuel |
| **R** | reporté après la tranche verticale |

| Statut | Sens |
|---|---|
| S | stockée |
| D | dérivée (calculée, non stockée) |

Plages : [-100;100] ou [0;100], sauf indication contraire.

---

## 1. Bilan chiffré du modèle

| Jeton | Scalaires | Catégories | Nombre max |
|---|---|---|---|
| soi | 48 | 6 | 1 |
| entité perçue | 20 | 4 | 16 |
| événement récent | 13 | 3 | 8 |
| souvenir | 5 | 3 | 12 |
| but ou engagement | 3 | 2 | 4 |

- Entrée maximale : **41 jetons**, environ 540 scalaires. En pratique, 10 à 16 entités, donc autour de 30 jetons.
- v0.1 comptait environ 400 lignes marquées « noyau ». Le modèle n'en voit plus qu'une cinquantaine de scalaires par PNJ, plus les jetons ci-dessus.
- Les préférences (arbre hiérarchique) ne sont pas fournies en bloc : le moteur calcule `préférence_résolue` pour chaque objet, lieu ou activité présent dans un jeton.

---

## 2. Modèle — jeton « soi » (48 scalaires + 6 catégories)

### 2.1 Personnalité (10, S)

| Variable | -100 | +100 |
|---|---|---|
| agressivité | douceur, évitement | confrontation |
| courage | peureux | courageux |
| empathie | indifférence | empathie |
| sociabilité | solitaire | sociable |
| honnêteté | trompeur | honnête |
| impulsivité | réfléchi, prudent | impulsif, téméraire |
| curiosité | conservateur | curieux |
| tolérance | intolérant | tolérant |
| justice | indifférent à l'injustice | très sensible à l'injustice |
| rancune | indulgent | rancunier |

### 2.2 Tempérament (3, S)

| Variable | Plage | Rôle |
|---|---|---|
| réactivité_émotionnelle | [0;100] | amplitude des variations d'états |
| résilience | [0;100] | vitesse de retour vers la base |
| humeur_de_base | [-100;100] | niveau de repos de la joie |

### 2.3 Valeurs (5, S, [0;100])

| Variable | Note |
|---|---|
| protection_des_proches | |
| respect_de_la_propriété | |
| honneur_réputation | |
| valeur_de_la_vie | aversion à tuer ou blesser |
| fidélité_amoureuse | attente d'exclusivité |

### 2.4 Pulsions (5, niveau seulement)

Les taux d'accumulation et les dates de dernier assouvissement restent dans le moteur (E).

| Variable | Plage | Statut |
|---|---|---|
| libido | [0;100] | S |
| contact_social | [0;100] | S |
| accomplissement | [0;100] | S |
| accumulation | [0;100] | S |
| sécurité | [0;100] | D |

### 2.5 États instantanés (10, S)

| Variable | Plage |
|---|---|
| faim, soif, douleur, peur, choc, confusion | [0;100] |
| fatigue, colère, stress, joie | [-100;100] |

### 2.6 Activité et corps (11)

| Variable | Plage | Statut |
|---|---|---|
| progression de l'action en cours | [0;1] | S |
| degré_d_engagement | [0;100] | S |
| temps_depuis_dernière_décision | secondes | D |
| points_de_vie | [0;100] | S |
| force | [0;100] | S |
| charge_portée / capacité | [0;1] | D |
| manque_de_stock[nourriture, eau, combustible, outils] | [-100;100] ×4 | D |
| compétence_dans_le_métier | [0;100] | S |

### 2.7 Temps (4, D)

heure_sin, heure_cos, saison_sin, saison_cos.

### 2.8 Catégories (6)

| Variable | Valeurs |
|---|---|
| catégorie_âge | enfant, adolescent, adulte, ancien |
| statut_amoureux | célibataire, courtise, en_couple, marié, séparé, veuf |
| métier_actuel | énum |
| action_en_cours | type d'action (vocabulaire) |
| météo | clair, nuageux, pluie, orage, neige, brouillard, vent |
| type_de_lieu | énum |

---

## 3. Modèle — jeton « entité perçue » (20 scalaires + 4 catégories, jusqu'à 16)

### 3.1 Relation de soi vers l'entité (9, S)

| Variable | Plage |
|---|---|
| affection | [-100;100] |
| confiance | [-100;100] |
| crainte | [0;100] |
| respect | [-100;100] |
| attirance_romantique | [-100;100] |
| attachement | [0;100] |
| familiarité | [0;100] |
| dette | [-100;100] (D, calculée depuis les créances et dettes du moteur) |
| grief_accumulé | [0;100] |

### 3.2 États envers l'entité (2, S)

humeur_envers [-100;100], envie_d_interaction [-100;100].

### 3.3 Perception et apparence (9)

| Variable | Plage | Statut |
|---|---|---|
| chimie(soi, entité) | [-1;1] | D, pseudo-aléatoire : hachage de (graine, A, B), stable, asymétrique |
| degré_de_perception | [0;1] | D |
| distance | mètres | D |
| beauté_perçue | [0;100] | D |
| temps_depuis_dernier_contact | durée | D |
| réputation_connue : fiabilité | [-100;100] | S |
| réputation_connue : dangerosité | [-100;100] | S |
| réputation_connue : moralité | [-100;100] | S |
| niveau_de_compréhension | 0 à 4 (aucun, présence, interaction vue, action identifiée, compréhension complète) | D |

### 3.4 Catégories (4)

| Variable | Valeurs |
|---|---|
| liens_typés (multi-hot) | parent, enfant, frère_sœur, conjoint, fiancé, ex_partenaire, ami, voisin, collègue, employeur, employé, maître, apprenti, rival, ennemi_déclaré, protecteur, protégé, créancier, débiteur |
| catégorie_âge | enfant, adolescent, adulte, ancien |
| statut_amoureux | voir 2.8 |
| action_visible | type d'action ou aucune |

---

## 4. Modèle — jeton « événement récent » (13 scalaires + 3 catégories, jusqu'à 8)

| Variable | Plage / type | Note |
|---|---|---|
| type_événement | catégorie | vocabulaire d'actions et d'événements subis |
| rôle_de_l_observateur | catégorie | agent, cible, témoin, rapporteur |
| source_de_l_information | catégorie | vu, entendu, rapporté |
| agent, cible | pointeurs vers les jetons entité | |
| objet | embedding de concept | précalculé hors ligne |
| intensité | [0;100] | |
| saillance_perçue | [0;100] | D |
| niveau_de_compréhension | 0 à 4 | |
| fiabilité | [0;1] | |
| délai | secondes | |
| hors_monde | booléen | concept inexistant dans le monde |
| violation_de_norme (7 dimensions) | [0;100] ×7 | issu de la table d'évaluation, voir 7 |

---

## 5. Modèle — jeton « souvenir » (5 scalaires + 3 catégories, jusqu'à 12)

| Variable | Plage / type |
|---|---|
| type_événement, source, rôle | catégories |
| agent, cible, objet, lieu | pointeurs ou embeddings |
| âge_du_souvenir | durée (D) |
| certitude | [0;1] |
| importance | [0;100] |
| valence_ressentie | [-100;100] |
| marquant | booléen |

---

## 6. Modèle — jeton « but ou engagement » (3 scalaires + 2 catégories, jusqu'à 4)

| Variable | Plage / type |
|---|---|
| type (but ou engagement) | catégorie : besoin, relation, possession, statut, vengeance, protection, découverte, projet, demande_d_autrui, promesse, accompagnement, service, mariage, emploi |
| cible | pointeur |
| priorité ou degré | [0;100] |
| progrès | [0;1] |
| échéance_restante | durée |

---

## 7. Modèle — sorties et table des normes

### 7.1 Sorties

| Variable | Plage / type |
|---|---|
| action : type | distribution sur le vocabulaire, masquée par la faisabilité |
| action : cible | pointeur (attention sur les jetons entité) |
| action : objet, contenu, intensité, durée | selon l'action |
| Δ_états | 10 valeurs bornées |
| Δ_relations | 9 valeurs bornées, pour l'entité visée |
| nouveau_but | type, cible, priorité |
| degré_d_engagement | [0;100] |
| importance_mémorielle | [0;100] |
| acte_de_parole | type, contenu |

### 7.2 Table d'évaluation des normes (engine, construite une fois hors ligne)

Vecteur de violation de normes à 7 dimensions, chacune pondérée par une variable du PNJ :

| Dimension | Pondérée par |
|---|---|
| protection des proches | valeur protection_des_proches |
| propriété | valeur respect_de_la_propriété |
| honneur | valeur honneur_réputation |
| vie | valeur valeur_de_la_vie |
| fidélité amoureuse | valeur fidélité_amoureuse |
| vérité | trait honnêteté |
| équité | trait justice |

Autres colonnes : menace_intrinsèque [0;100], désirabilité_intrinsèque [-100;100] ; indexée par (action × contexte × lien typé × drapeaux : consentement, catégorie d'âge, statut amoureux).

---

## 8. Moteur (E) — stocké pour chaque individu, non fourni tel quel au modèle

| Groupe | Variables | Statut |
|---|---|---|
| Identité | id, nom (réservé au joueur et au verbalisateur), est_joueur, niveau_IA {léger, avancé}, âge, vivant, village_d_origine | S |
| Corps et déplacement | position (x, y), orientation, destination, chemin_en_cours, posture, endurance, acuité_visuelle, acuité_auditive, vitesse_de_déplacement (D), capacité_de_charge (D) | S / D |
| Préférences | arbre : catégorie → objet → valeur [-100;100], parent_id ; catégories du noyau : consommation, activités, métiers, lieux, moments, matériaux et objets | S |
| Sortie des préférences | préférence_résolue(objet) : valeur la plus spécifique non neutre | D |
| Pulsions (paramètres) | taux_d_accumulation, dernier_assouvissement, pour chaque pulsion | S |
| Dynamique des états | constante_de_retour[état], bornes[variable], Δ_max_par_décision | S |
| Idéal de partenaire | aucun stockage : remplacé par chimie (voir 3.3) | — |
| Compétences | compétence[domaine] : agriculture, bûcheronnage, minage, taille_de_pierre, forge, menuiserie, construction, cuisine, chasse, pêche, soin, commerce, combat_mêlée, persuasion, discrétion | S |
| Possessions | inventaire[] : type, quantité, qualité, usure, fraîcheur, propriétaire_légitime ; équipement_porté ; logement ; terres_possédées ; stocks_cibles[catégorie] | S |
| Dettes et créances | liste : autre, objet ou valeur, date, échéance | S |
| Relations | toutes celles de 3.1 pour chaque individu connu, plus liens_typés, dernier_contact, nb_interactions_positives, nb_interactions_négatives, souvenirs_clés[] | S |
| Réputation | réputation_connue[entité] : fiabilité, dangerosité, moralité + source {vu, ouï-dire} | S |
| Mémoire | capacité_mémoire, taux_d_oubli, observations brutes (target_id, location_id, timestamp), souvenirs d'événements (voir 5 + cause_id, version_altérée) | S |
| Connaissances | individus_connus, lieux_connus, carte_mentale, ressources_connues, propriétaires_connus, recettes_connues, rumeurs_en_circulation, où_est(cible) (D) | S / D |
| Buts | liste complète ; le modèle reçoit les 4 plus prioritaires. Champs : type, cible, priorité, origine, échéance, conditions_de_réussite, conditions_d_abandon, progrès | S |
| Engagements | envers, type, contenu, début, fin_prévue, conditions_de_rupture, degré, statut | S |
| Demandes reçues | de, contenu (proposition structurée), date, statut {en_attente, acceptée, refusée} | S |
| Perception (calculs) | rayon_intime (fixe), rayons de discussion, collaboration, présence (D), champ_de_vision, bruit_émis, bruit_ambiant, saillance_objective (D), saillance_perçue (D), intérêt_opportunité (D), seuil_de_réveil (D) | S / D |
| Réveil | période_de_réveil_périodique par niveau_IA, graine_aléatoire_par_PNJ, température_d_échantillonnage | S |

### Action et conséquences (moteur)

| Variable | Note |
|---|---|
| action : id, agent, type, cible, objet, contenu, intensité, durée_prévue, lieu, contexte (public ou privé, témoins), horodatage_début, statut {planifiée, en_cours, achevée, interrompue, échouée}, cause_id | S |
| conséquences : changements_monde[] (dégâts, transfert_de_propriété, déplacement, production, consommation, destruction, construction, information_transmise, modification_du_terrain), visibilité, bruit, témoins_potentiels (D) | S |
| événement_perçu : observateur, rôle, source, niveau_de_compréhension, fiabilité, délai | S |
| acte_de_parole : type_d_acte, émetteur, destinataires, audience, contenu_propositionnel, ton, hors_monde ; véracité_objective et croyance_de_l_émetteur connues du moteur seulement (distinguent mensonge et erreur) | S |

---

## 9. Moteur (E) — monde

### 9.1 Cellule de la grille 2D

| Variable | Plage / type |
|---|---|
| x, y | entiers |
| type_terrain | plaine, forêt, roche, eau, marécage, montagne, chemin, bâtiment |
| opacité_vue, opacité_son | [0;1] |
| coût_de_déplacement | nombre |
| franchissable | booléen |
| fertilité_du_sol, humidité | [0;100] |
| couvert_végétal | aucun, herbe, buissons, forêt_jeune, forêt_dense, cultures |
| densité_d_arbres | [0;100] |
| état_du_sol | nu, labouré, semé, cultivé, jachère, bâti |
| culture | espèce, stade, santé, jours_avant_récolte |
| ressource_minérale | type, quantité_restante, richesse, profondeur |
| eau | type {source, rivière, puits, étang}, débit, niveau, potabilité |
| propriétaire, zone_d_usage | id, {public, privé, commun} |
| danger | [0;100] |
| construction_id | id |

### 9.2 Ressource du monde (définie par des données)

| Variable | Plage / type |
|---|---|
| id, nom, catégorie | végétal, minéral, eau, animal, sol |
| quantité_max, régénération, accessibilité | nombres |
| affordance.action | couper, miner, labourer, planter, récolter, puiser, pêcher, chasser |
| affordance.outil_requis | types d'objet |
| affordance.compétence_requise | domaine + niveau |
| affordance.effort, durée, rendement (objet, quantité, variance), épuisement_par_usage, risque_dégâts | nombres |
| effets_secondaires | changement d'état du sol ou du couvert (par exemple défrichement) |
| saisonnalité | saisons disponibles |

### 9.3 Bâtiment

id, type, cellules, propriétaire, résidents[], usages (dormir, cuisiner, forger, stocker, vendre, réunir), capacité_de_stockage, contenu, état_usure, verrouillage {ouvert, fermé, verrouillé}, caractère {public, privé, sacré}, construction_en_cours (progrès, matériaux restants).

### 9.4 Objets, recettes, plantes

| Groupe | Variables |
|---|---|
| Type d'objet | id, nom, catégorie (nourriture, boisson, matériau, combustible, outil, arme, vêtement, meuble, semence, conteneur, médicament, troc, ornement), poids, volume, valeur_d_échange_de_base, valeur_d_usage, durabilité, périssabilité, empilable, propriétés_physiques, effets_à_l_usage, compétence_requise, dégâts (armes), rareté |
| Instance d'objet | id, type, quantité, qualité, usure, fraîcheur, propriétaire, localisation |
| Recette | id, entrées[], outils_requis[], compétence, lieu_requis, durée, sorties[] (quantité et qualité dépendent de la compétence) |
| Plante | espèce, durées de croissance par stade, saisons de semis et de récolte, besoin_en_eau, fertilité_requise, rendement |
| Arbre | espèce, âge, bois_disponible, croissance, repousse |

### 9.5 Temps et météo

minute, heure, jour, jour_de_semaine, saison, année, échelle_de_temps ; luminosité ; météo (type, température, précipitations, vent, humidité) ; effet_sur_la_perception (D), effet_sur_le_déplacement (D).

### 9.6 Joueur et verbalisateur

commande_structurée (cible, verbe, objet, contenu), énoncé_texte, cible_de_l_adresse, événement_converti (acte de parole + contenu + hors_monde), réplique_verbalisée, état_exposé_au_verbalisateur, file_du_verbalisateur (une requête à la fois), version_du_schéma, graine_aléatoire (sauvegarde et rejouabilité).

### 9.7 Groupes minimaux

Seuls les foyers (famille, couple) restent dans le noyau : id, type {foyer, couple}, membres[], rôles[membre], ressources_communes. Les autres groupes, normes locales, économie, villages et institutions sont reportés.

---

## 10. Reporté (R)

| Domaine | Variables reportées |
|---|---|
| Personnalité | prudence (fusionnée dans impulsivité), ambition, diligence, générosité, fierté, possessivité, loyauté (trait), conformisme, sensualité, spiritualité, intelligence, stress_de_base |
| Valeurs | loyauté_au_groupe, respect_de_l_autorité, pureté_sacré, liberté_autonomie, tradition, hospitalité, normes_intériorisées[] |
| Pulsions | reconnaissance, nouveauté, calme_intimité, spiritualité, confort |
| États | confort_thermique, surprise, honte, culpabilité, fierté_ressentie, ennui, deuil, dégoût, jalousie_générale, hygiène, ébriété, solitude_ressentie, attirance_du_moment |
| Relations | gratitude_accumulée, autorité_reconnue, rivalité, jalousie_envers, dépendance, loyauté_envers |
| Croyances sociales | traits_perçus, valeurs_perçues, intention_supposée, statut_perçu, secrets_connus_sur, croyance_relation(B, C), réputation (générosité, compétence) |
| Corps | sexe, blessures[] détaillées, maladies[], handicaps[], grossesse, fertilité, apparence (propreté, signes visibles) |
| Buts | aspirations, plan[], horizon_de_planification (PNJ avancés) |
| Compétences | expérience, apprentissage en cours, employeur, rémunération |
| Possessions | monnaie, atelier, bétail |
| Préférences | catégories biomes, itinéraires, saisons, météo, couleurs, animaux, taille de groupe, traits valorisés chez autrui |
| Société | groupes (clan, corporation, bande, village), normes locales, prix du marché, offre et demande, institutions, rites, héritage |
| Villages | toute la couche 3 : relations entre villages, flux, caravanes, messagers, événements collectifs |
| Monde | mines détaillées (galeries, stabilité, air), routes, faune (animaux, populations), maladies des plantes, événements naturels, calendrier |
| Mémoire | émotions_associées, nb_rappels, dernier_rappel, secrets_détenus, événements_marquants_de_vie |
| Interprétation | valence_pour_autrui, variables de justification et de diagnostic |

---

## 11. Changements par rapport à v0.1 (à valider)

| Changement | Raison |
|---|---|
| traits de personnalité : 21 ramenés à 10 | voir ci-dessous et section 10 |
| prudence fusionnée dans impulsivité | axes quasi opposés, une seule variable suffit |
| ambition, diligence reportées | aucun des trois scénarios n'en dépend ; le travail est porté par la pulsion accomplissement |
| fierté, loyauté (trait), sensualité, possessivité supprimées du noyau | couvertes par les valeurs (honneur, fidélité amoureuse) et la pulsion libido |
| idéal_partenaire remplacé par chimie(A, B) | les préférences déclarées prédisent mal l'attirance réelle ; une valeur dérivée suffit |
| 7 valeurs ramenées à 5 | les groupes et l'autorité sont hors de la tranche |
| pulsions : 10 ramenées à 5 | les autres sont reportées |
| états : 22 ramenés à 10 | les autres sont reportés |
| relations : 15 ramenées à 9 | les autres sont reportées |
| préférences fournies résolues, pas en bloc | évite d'alourdir l'entrée |
| taux et dates des pulsions, dynamique des états | restent dans le moteur |
| dette : dérivée des créances et dettes du moteur | évite de stocker deux fois la même information |
| grand moteur monde (sections 9) conservé | aucun impact sur la taille du modèle |
