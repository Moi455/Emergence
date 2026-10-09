> Remplacé par `docs/npc/variables_v0.3_catalogue_unique.md` (validé le 8 oct. 2026 par le fil Données du Transformer). Ce fichier reste comme trace de la moitié « modèle ».

# Catalogue PNJ, moitié « modèle »

Fil Données du Transformer, 8 oct. 2026. Généré depuis le code : `representation.py`, `plan_contract.py`, `generate_states.py` 0.4, `encode.py` tok-1, vocabulaire 9c6f1d8ef56c58ac. À fusionner dans le catalogue unique tenu par le fil Simulation, qui apporte la moitié « monde » (espace, voxels, matériaux, eau, feu, économie, frontières).

La colonne « Écriture » est une **proposition** pour la sortie demandée par Monsieur (le Transformer ajuste progressivement les variables, seule l'émotion peut sauter). Cette sortie n'existe pas encore dans le modèle. « moteur » veut dire que la variable est calculée par la simulation, pas par le Transformer.

## 1. Variables numériques (129)

| Groupe | Variables | Échelle | Écriture proposée |
|---|---|---|---|
| entity.perception | chemistry | −1..1 | moteur (perception) ; rep_* progressif (rumeurs) |
| entity.perception | perceived | 0..1 | moteur (perception) ; rep_* progressif (rumeurs) |
| entity.perception | distance, days_since_contact | quantité | moteur (perception) ; rep_* progressif (rumeurs) |
| entity.perception | beauty | 0..100 | moteur (perception) ; rep_* progressif (rumeurs) |
| entity.perception | rep_trust, rep_danger | −100..100 | moteur (perception) ; rep_* progressif (rumeurs) |
| entity.perception | understanding | ordinal | moteur (perception) ; rep_* progressif (rumeurs) |
| entity.rel | affection, trust, respect, romance, debt | −100..100 | progressif, Δ ≤ 5 par décision ; fear peut sauter ; debt = moteur |
| entity.rel | fear, familiarity, grudge | 0..100 | progressif, Δ ≤ 5 par décision ; fear peut sauter ; debt = moteur |
| entity.social | mood_toward, urge_to_interact | −100..100 | progressif, Δ ≤ 10 |
| entity.social | suspicion, indirect_threat | 0..100 | progressif, Δ ≤ 10 |
| event | intensity, salience | 0..100 | moteur (perception) |
| event | understanding | ordinal | moteur (perception) |
| event | reliability, intent | 0..1 | moteur (perception) |
| event | delay, holders | quantité | moteur (perception) |
| event | out_of_world | booléen | moteur (perception) |
| event.norm | kin, property, honor, life, fidelity, truth, fairness, taboo | 0..100 | moteur (règles) |
| goal | priority | 0..100 | priorité, Δ ≤ 10 ; création et abandon = actions |
| goal | progress | 0..1 | priorité, Δ ≤ 10 ; création et abandon = actions |
| goal | deadline_h | quantité | priorité, Δ ≤ 10 ; création et abandon = actions |
| group | identification, cohesion, rank | 0..100 | progressif, Δ ≤ 3 |
| household | cohesion | 0..100 | moteur |
| household | wealth, honor | −100..100 | moteur |
| household | size | quantité | moteur |
| household | head | booléen | moteur |
| inventory | quality, wear | 0..100 | moteur |
| inventory | qty | quantité | moteur |
| memory | importance, severity | 0..100 | réévaluation importance/valence, Δ ≤ 10 ; création = moteur |
| memory | certainty | 0..1 | réévaluation importance/valence, Δ ≤ 10 ; création = moteur |
| memory | valence | −100..100 | réévaluation importance/valence, Δ ≤ 10 ; création = moteur |
| memory | age_days | quantité | réévaluation importance/valence, Δ ≤ 10 ; création = moteur |
| memory | defining, secret | booléen | réévaluation importance/valence, Δ ≤ 10 ; création = moteur |
| self.activity | progress | 0..1 | moteur |
| self.activity | commitment | 0..100 | moteur |
| self.activity | secs_since_decision | quantité | moteur |
| self.body | hp, strength, job_skill | 0..100 | moteur (corps ; compétence par l'usage) |
| self.body | load_ratio | 0..1 | moteur (corps ; compétence par l'usage) |
| self.drive | libido, social_need, achievement, hoarding | 0..100 | progressif, Δ ≤ 5 par décision |
| self.state | fear, shock, confusion | 0..100 | émotion : **saut permis** |
| self.state | hunger, thirst, pain | 0..100 | moteur (corps) |
| self.state | anger, stress, joy | −100..100 | émotion : **saut permis** |
| self.state | fatigue | −100..100 | moteur (corps) |
| self.stock | food, fuel, tools | −100..100 | moteur (inventaire) |
| self.temperament | reactivity, resilience | 0..100 | figé à la naissance |
| self.trait | aggression, courage, empathy, sociability, honesty, impulsivity, curiosity, tolerance, justice, ambition, grudge | −100..100 | lent, Δ ≤ 1 par jour de jeu (ou figé ?) |
| self.value | kin_protection, property_respect, honor, life_value, romantic_fidelity, taboo_sensitivity | 0..100 | lent, Δ ≤ 1 par jour de jeu |
| self.wardrobe | wear | 0..100 | moteur (usure) |
| title | authority | 0..100 | moteur (institutions) |
| title | conf | 0..1 | moteur (institutions) |
| title | legit | −100..100 | moteur (institutions) |
| village.collective | rep, economy, food, security | −100..100 | moteur (agrégat des PNJ) |
| village.collective | tension, cohesion | 0..100 | moteur (agrégat des PNJ) |
| village.norm | kin, property, honor, life, fidelity, truth, fairness, taboo | 0..100 | moteur (agrégat, très lent) |
| village.other | relation | −100..100 | moteur ; my_ties progressif |
| village.other | trade_dep, threat, my_ties | 0..100 | moteur ; my_ties progressif |
| village.personal | belonging | 0..100 | progressif, Δ ≤ 3 |
| village.personal | loyalty, leader_trust, leader_legit, institution_trust | −100..100 | progressif, Δ ≤ 3 |
| village.problem | urgency, progress | 0..100 | moteur |

## 2. Variables catégorielles

| Porteur | Variables |
|---|---|
| self | age_cat, love_status, job, current_action, weather, place_type, tool_in_hand |
| entity | link, age_cat, love_status, visible_action, village |
| event | type, role, source, speech_act, style |
| memory | type, source, what, broke, outcome, focus_knows |
| goal | type |
| title | title, my_role |
| village | id, frontier, problem.kind, problem.need, other.id |
| group | kind |

Valeurs figées : villages sea_village, mountain_village, desert_village, forest_village, market_town ; tenues everyday, work, travel, festive, mourning, cold, court, night ; âges child, teen, adult, elder ; 26 métiers des fiches + apprentice et none.

## 3. Actions du contrat (112 fonctions, 85 de noyau)

Un plan compte 1 à 6 étapes, avec au plus 3 conditions `until` et 3 `interrupt_if`. Le détail et l'animation proposée par fonction sont dans `ai/CONTRAT_PNJ.md`.

| Catégorie | Fonctions |
|---|---|
| body | eat, drink, sleep, rest, dress |
| move | go_to, follow, approach, avoid, flee, wander, wait, hide*, return_home |
| work | equip, unequip, dig, place, till, plant, harvest, cut, fetch_water, craft, build*, repair*, tend_crop*, hunt*, start_build*, contribute*, supply* |
| inventory | pick_up, drop, store, take_from, give, steal, destroy*, claim*, conceal* |
| speech | greet, chat, inform, deceive, ask, propose, request, order, accept, refuse, promise, threaten, accuse, apologize, thank, compliment, insult, warn, call_for_help, comfort, forgive, teach* |
| diplomacy | interrogate, bribe, answer, blackmail, negotiate, lobby* |
| politics | read, post_notice, tear_down_notice, publish*, write_letter*, call_vote, vote, campaign, claim_title, contest_claim, endorse, appoint, dismiss, create_title, decree, enforce, summon, delegate*, found_group*, join_group*, leave_group*, post_job*, hire* |
| intimacy | flirt, kiss, embrace, be_intimate |
| conflict | attack, defend, chase, restrain*, expel |
| care | heal*, assist |
| attention | observe, search, eavesdrop*, investigate* |
| leisure | leisure, pray*, mourn* |
| commit | accompany, break_commitment, continue |

`*` = extension. Conditions (20) : found, sees, hears, hp_below, hunger_above, thirst_above, fatigue_above, tool_worn, tool_broken, inventory_full, entity_near, attacked, obstacle, unsafe, time_after, elapsed_over, reached, addressed, message_from, done.

## 4. Ce que cette moitié ne couvre pas

- La perception spatiale : ce que le PNJ voit (voxels, objets, matériaux, eau, feu, distances, lignes de vue). Il faut des jetons de perception fournis par le moteur.
- L'espace des options complet : `build_candidates` est un générateur heuristique de situations d'entraînement, pas le filtre du moteur.
- La mémoire longue : 9 souvenirs choisis par situation au plus.
- Les variables du monde, de l'économie et des institutions au-delà du village : moitié « monde ».
