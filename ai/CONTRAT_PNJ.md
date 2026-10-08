# Contrat PNJ : état, décision, action (proposition du fil « Données d'entraînement du Transformer »)

Version : 0.4 (8 octobre 2026). Source de vérité : `ai/npc_pipeline/plan_contract.py` (fonctions, conditions, validation) et `generate_states.py` (état). Ce fichier en est l'export lisible ; le fil du moteur tranche la version finale dans `docs/interfaces.md` et ce fil la suit.

## 1. Trois messages

```
DecisionRequest { npc, reason: plan_done | interrupted | event | idle_timeout, tokens }
Plan            { steps: [ { f, a:{args}, until:[<=3 conditions], interrupt_if:[<=3 conditions] } x1..6 ], on_done: report | routine }
PlanResult      { plan_id, status: done | interrupted | failed, reason, step, progress, gains, notable_events[] }
```

- Le décideur (référence à utilités ou Transformer) ne bouge rien : il choisit une option parmi les **candidats** proposés par le moteur, puis le HTN la déroule en plan.
- Le moteur d'action exécute, surveille les conditions, et ne rappelle le décideur qu'en fin, échec ou interruption de plan.
- `PlanResult` devient un événement et un souvenir.

## 2. Entrée du décideur (jetons)

Chaque situation est une suite de jetons de largeur fixe (spécifiée et produite par `ai/npc_pipeline/encode.py`, oracle du portage C++) :
SELF (personnalité), SELF_STATE (besoins, corps, activité, heure), VILLAGE, OTHER_VILLAGE ×4, HOUSEHOLD, ENTITY ×≤6, EVENT ×≤3, MEMORY ×≤9, GOAL ×≤4, TITLE ×≤6, ITEM ×≤8, puis CAND ×≤16 (une par option).
Valeurs : entiers −10..+10 (bipolaires) ou 0..10 (unipolaires), catégories en identifiants de vocabulaire, pointeurs vers d'autres jetons. Sortie : un score par CAND.

## 3. Conditions (20)

`found`(1 arg), `sees`(1 arg), `hears`(1 arg), `hp_below`(1 arg), `hunger_above`(1 arg), `thirst_above`(1 arg), `fatigue_above`(1 arg), `tool_worn`(1 arg), `tool_broken`, `inventory_full`, `entity_near`(2 arg), `attacked`, `obstacle`, `unsafe`, `time_after`(1 arg), `elapsed_over`(1 arg), `reached`(1 arg), `addressed`, `message_from`(1 arg), `done`

## 4. Fonctions (112) et famille d'animation proposée

Chaque fonction doit correspondre à une animation existante. Colonne « Animation » : famille proposée, à valider avec le fil Skins.

| Fonction | Catégorie | Noyau | Arguments | Animation proposée |
|---|---|---|---|---|
| `eat` | body | oui | item:I | eat_drink / sleep_lie / sit_rest |
| `drink` | body | oui | item:I?, place:P? | eat_drink / sleep_lie / sit_rest |
| `sleep` | body | oui | place:P? | eat_drink / sleep_lie / sit_rest |
| `rest` | body | oui |  | eat_drink / sleep_lie / sit_rest |
| `dress` | body | oui | outfit:X | change_clothes (se changer, ~2 s) |
| `go_to` | move | oui | place:P?, entity:E? | walk / run / sneak (locomotion) |
| `follow` | move | oui | entity:E | walk / run / sneak (locomotion) |
| `approach` | move | oui | entity:E | walk / run / sneak (locomotion) |
| `avoid` | move | oui | entity:E | walk / run / sneak (locomotion) |
| `flee` | move | oui | entity:E?, place:P? | walk / run / sneak (locomotion) |
| `wander` | move | oui |  | walk / run / sneak (locomotion) |
| `wait` | move | oui | secs:N? | walk / run / sneak (locomotion) |
| `hide` | move | ext. | place:P? | walk / run / sneak (locomotion) |
| `return_home` | move | oui |  | walk / run / sneak (locomotion) |
| `equip` | work | oui | tool:T | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `unequip` | work | oui |  | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `dig` | work | oui | dir:D, length:N, tool:T, width:N?, depth:N? | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `place` | work | oui | block:B, pattern:X?, tool:T? | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `till` | work | oui | place:P?, tool:T? | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `plant` | work | oui | seed:I, place:P? | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `harvest` | work | oui | kind:X, place:P? | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `cut` | work | oui | target:B, tool:T? | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `fetch_water` | work | oui | place:P? | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `craft` | work | oui | recipe:C | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `build` | work | ext. | blueprint:C, place:P? | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `repair` | work | ext. | target:C | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `tend_crop` | work | ext. | place:P? | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `hunt` | work | ext. | target:C | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `pick_up` | inventory | oui | item:I | pick_up / give_hand / store_crouch |
| `drop` | inventory | oui | item:I | pick_up / give_hand / store_crouch |
| `store` | inventory | oui | item:I, place:P | pick_up / give_hand / store_crouch |
| `take_from` | inventory | oui | place:P, item:I | pick_up / give_hand / store_crouch |
| `give` | inventory | oui | entity:E, item:I | pick_up / give_hand / store_crouch |
| `steal` | inventory | oui | entity:E?, place:P?, item:I | pick_up / give_hand / store_crouch |
| `destroy` | inventory | ext. | target:C | pick_up / give_hand / store_crouch |
| `claim` | inventory | ext. | item:I?, place:P? | pick_up / give_hand / store_crouch |
| `greet` | speech | oui | entity:E | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `chat` | speech | oui | entity:E | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `inform` | speech | oui | entity:E, memory:M?, fact:F? | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `deceive` | speech | oui | entity:E, fact:F | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `ask` | speech | oui | entity:E, topic:C?, fact:F?, attr:X?, subject:E? | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `propose` | speech | oui | entity:E, proposal:F | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `request` | speech | oui | entity:E, proposal:F | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `order` | speech | oui | entity:E, proposal:F | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `accept` | speech | oui | proposal:O | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `refuse` | speech | oui | proposal:O | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `promise` | speech | oui | entity:E, proposal:F | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `threaten` | speech | oui | entity:E, fact:F | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `accuse` | speech | oui | entity:E, fact:F | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `apologize` | speech | oui | entity:E | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `thank` | speech | oui | entity:E | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `compliment` | speech | oui | entity:E | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `insult` | speech | oui | entity:E | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `warn` | speech | oui | entity:E, fact:F | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `call_for_help` | speech | oui |  | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `comfort` | speech | oui | entity:E | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `forgive` | speech | oui | entity:E | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `teach` | speech | ext. | entity:E, skill:C | talk_gesture (tone: calm, angry, pleading, joyful) / point / nod_shake |
| `interrogate` | diplomacy | oui | entity:E, topic:C | talk_gesture + hand_over_item |
| `bribe` | diplomacy | oui | entity:E, offer:F | talk_gesture + hand_over_item |
| `answer` | diplomacy | oui | entity:E, query:O, mode:X | talk_gesture + hand_over_item |
| `blackmail` | diplomacy | oui | entity:E, memory:M | talk_gesture + hand_over_item |
| `negotiate` | diplomacy | oui | entity:E, move:X, sweetener:I? | talk_gesture + hand_over_item |
| `lobby` | diplomacy | ext. | entity:E, topic:C | talk_gesture + hand_over_item |
| `read` | politics | oui | doc:O | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `post_notice` | politics | oui | content:F, board:P? | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `tear_down_notice` | politics | oui | doc:O | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `publish` | politics | ext. | content:F | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `write_letter` | politics | ext. | entity:E, content:F | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `call_vote` | politics | oui | question:F, options:F | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `vote` | politics | oui | poll:O, option:X | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `campaign` | politics | oui | entity:E, audience:E? | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `claim_title` | politics | oui | title:C | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `contest_claim` | politics | oui | entity:E, title:C | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `endorse` | politics | oui | entity:E, title:C | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `appoint` | politics | oui | entity:E, title:C | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `dismiss` | politics | oui | entity:E, title:C | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `create_title` | politics | oui | name:C, duties:F? | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `decree` | politics | oui | rule:F | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `enforce` | politics | oui | rule:F, entity:E | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `summon` | politics | oui | entity:E | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `delegate` | politics | ext. | task:F, entity:E | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `flirt` | intimacy | oui | entity:E | lean_in / hold_hands / embrace / kiss (fade, never explicit) |
| `kiss` | intimacy | oui | entity:E | lean_in / hold_hands / embrace / kiss (fade, never explicit) |
| `embrace` | intimacy | oui | entity:E | lean_in / hold_hands / embrace / kiss (fade, never explicit) |
| `be_intimate` | intimacy | oui | entity:E | lean_in / hold_hands / embrace / kiss (fade, never explicit) |
| `conceal` | inventory | ext. | item:I, place:P | pick_up / give_hand / store_crouch |
| `found_group` | politics | ext. | name:C, purpose:F? | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `join_group` | politics | ext. | group:C | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `leave_group` | politics | ext. | group:C | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `post_job` | politics | ext. | task:F, pay:F | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `hire` | politics | ext. | entity:E, task:F, pay:F | post_paper / tear_paper / raise_hand_vote / address_crowd |
| `start_build` | work | ext. | blueprint:C, place:P | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `contribute` | work | ext. | site:O | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `supply` | work | ext. | site:O, item:I | tool swing per tool (pickaxe, shovel, trowel, axe, hoe) / kneel_work / carry |
| `attack` | conflict | oui | entity:E, mode:X | shove / punch / block / grab / chase_run |
| `defend` | conflict | oui | entity:E? | shove / punch / block / grab / chase_run |
| `chase` | conflict | oui | entity:E | shove / punch / block / grab / chase_run |
| `restrain` | conflict | ext. | entity:E | shove / punch / block / grab / chase_run |
| `expel` | conflict | oui | entity:E, place:P? | shove / punch / block / grab / chase_run |
| `heal` | care | ext. | entity:E | kneel_tend / support_walk |
| `assist` | care | oui | entity:E, task:C? | kneel_tend / support_walk |
| `observe` | attention | oui | entity:E?, place:P? | look_at / search_bend / listen |
| `search` | attention | oui | entity:E?, item:I?, place:P? | look_at / search_bend / listen |
| `eavesdrop` | attention | ext. | entity:E | look_at / search_bend / listen |
| `investigate` | attention | ext. | place:P | look_at / search_bend / listen |
| `leisure` | leisure | oui | activity:C, entity:E? | per activity (dance, dice, story, wrestle_play, fish) |
| `pray` | leisure | ext. |  | per activity (dance, dice, story, wrestle_play, fish) |
| `mourn` | leisure | ext. |  | per activity (dance, dice, story, wrestle_play, fish) |
| `accompany` | commit | oui | entity:E | (no own animation: follows the current step) |
| `break_commitment` | commit | oui | commitment:O | (no own animation: follows the current step) |
| `continue` | commit | oui |  | (no own animation: follows the current step) |

Types d'arguments : E entité, I objet, P lieu, T outil, D direction, N nombre, B bloc, C concept/recette, F fait ou proposition, O référence à un événement, X mode, M souvenir.

## 5. Ajouts prévus

- **Tenue selon l'occasion (fait, 8 oct.)** : `dress(outfit:X)` est ajoutée en dernière position (les numéros des autres fonctions ne bougent pas), 8 tenues figées par `docs/interfaces.md` v0.2 : `everyday`, `work`, `travel`, `festive`, `mourning`, `cold`, `court`, `night`. Chaque PNJ les possède toutes (une tenue absente se replie sur `everyday`), et son usure entre dans le jeton SELF ; les personnes proches montrent leur tenue. Le choix est appris comme les autres décisions (paires minimales « fête » et « froid » ; `court` devant une élection ou une revendication de titre, `travel` pour un voyage proposé). Le fil Skins traduit chaque tenue en pièces sur les 11 emplacements de `docs/interfaces.md`.
- Fonctions du village déjà utilisées par le générateur 0.4 bien que « extension » : `teach`, `contribute`, `supply`.
- **Alignement avec les fiches des villageois (8 oct.)** : le générateur utilise les 26 métiers de `personnages/data/fiches.json` (pondérés par leur nombre) et la catégorie d'âge `teen` de `docs/interfaces.md`. Dans les fiches, le métier `child` ou `elder` se traduit par `none` côté décideur ; `apprentice` reste un état propre au décideur.
