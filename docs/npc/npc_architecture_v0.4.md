# NPC architecture v0.4 - decision engine vs action engine

2 Oct 2026. Takes into account the voxel world with tools, the political layer, the English language layer and multi-step plans. Partly supersedes `npc_model_spec_v0.3.md`: its sections 2.1 to 2.4 (variables) still hold, except for the additions in section 5 below; its section 3 (single action, 76 actions) is replaced by sections 2 and 3 below.

See also `npc_memory_jobs_building_v0.5.md` (memory, questions, negotiation, jobs, construction, the 30 cases).

Files: `plan_contract.py` (the contract, with self-tests), `utterance_parser.py` (language layer prototype), `generate_states.py` (situations and scripted work programs), `teacher_prompt.md`, `teacher_tools.py`.

## 1. What changed in one paragraph

The model no longer picks one action at a time. It writes a short **plan** (1 to 6 function calls, each with stop and interrupt conditions). The **action engine** runs it alone, block after block, and wakes the model only when the plan ends, fails or is interrupted. A 15-block dig is one decision, not fifteen. Memory is owned by the engine; the model only reads the few memories it is given.

## 2. The two engines and the data layer

| | Decision engine (AI) | Action engine | Shared data layer (deterministic) |
|---|---|---|---|
| Role | decides what to do next, as a plan | carries the plan out in the world | holds the truth and the memories |
| Contains | context builder, the transformer, plan validator | scheduler, pathfinding, tool physics, block edits, animation, condition monitor, interrupt manager, result reporter | world and voxel grid, NPC variables, **memory service** (store, decay, distortion, retrieval), belief store (titles, documents), language layer (parser, frames) |
| Reads | tokens built from the data layer | the plan and the world | |
| Writes | a plan, bounded state deltas, a memory-importance score | world changes, a plan result | observations, memories, beliefs |
| Never does | move, dig, pathfind, store memories | decide goals, choose tools, judge people | decide anything |
| Runs | on demand, a few times per second for all NPCs | every tick, cheap per NPC | |

**Interface (3 messages):**

```
DecisionRequest { npc, reason: plan_done | interrupted | event | idle_timeout, tokens }
Plan            { steps: [ { f, a:{args}, until:[...], interrupt_if:[...] } ... ], on_done: report | routine }
PlanResult      { plan_id, status: done | interrupted | failed, reason, step, progress, gains, notable_events[] }
```

`PlanResult` becomes an event for the next decision and a memory (the engine decides its importance). A plan the validator rejects, or whose preconditions fail (missing tool), comes back as a `failed` result with a reason; the model learns to fetch the tool first.

**Interrupt manager (action engine).** Three sources, all cheap: (1) the plan's own `until` and `interrupt_if` conditions, (2) reflexes that always fire (attacked, hit points critical, tool broken), (3) the salience wake: objective salience filtered by the NPC's variables (affection, preferences, needs, opportunity) against a threshold that rises with `commitment`. The model never runs to find out whether something is interesting.

**Example (your pickaxe case):**

```json
{"steps":[
  {"f":"equip","a":{"tool":"pickaxe"}},
  {"f":"dig","a":{"dir":"forward","length":15,"tool":"pickaxe"},
   "until":["found(gold)"],"interrupt_if":["hp_below(30)","sees(danger)","tool_broken"]}],
 "on_done":"report"}
```

Missing `equip` steps are inserted by the action engine when the tool is in the inventory (tested in `plan_contract.py`).

## 3. Plan language

- **111 functions** (84 core, 27 extension) in 15 categories: body, move, work, inventory, speech, diplomacy, politics, intimacy, conflict, care, attention, leisure, commit. Full table in section 8.
- **20 conditions**, all cheap predicates: `found`, `sees`, `hears`, `hp_below`, `hunger_above`, `thirst_above`, `fatigue_above`, `tool_worn`, `tool_broken`, `inventory_full`, `entity_near`, `attacked`, `obstacle`, `unsafe`, `time_after`, `elapsed_over`, `reached`, `addressed`, `message_from`, `done`. At most 3 `until` and 3 `interrupt_if` per step, at most 6 steps per plan.
- Anything the validator cannot parse is rejected before it reaches the action engine.

### Tools (action engine physics)

| Tool | Digs | Places | Note |
|---|---|---|---|
| pickaxe | fast, irregular hole, blocks scatter | none | never a straight square tunnel |
| shovel | clean cubes, large | big untidy piles | |
| trowel | fine, precise, slow | fine | used for construction |
| axe | wood only | | |
| hoe | tills soil only | | |
| hands | cannot break blocks; only flowers, fruits, vegetables | finest | |

Blocks are small and unbreakable by hand. The model's tool choice is a real decision (speed against cleanliness against precision), and personality shapes it: an impulsive tired miner takes the pickaxe, a skilled careful one takes the shovel.

## 4. Language layer (engine side)

Pipeline: typed English -> token highlighting -> speech-act **frame** -> event for the model. The prototype passes 15 tests.

- Highlighting: **orange** known concepts (come, harvest, carrot), **blue** logic words (with, to, in, or, if, not), **green** entities, places, people and titles (you, me, farm, lawyer). Unknown words get red plus suggestions (prefix and close-spelling matching). A title created by the player is added to the lexicon at runtime and turns green.
- Frame: `act` (invite, request, order, propose_joint, ask_info, ask_yesno, ask_permission, promise, threaten, threaten_conditional, offer_conditional, accuse, inform), `force` 0 to 3, `politeness` -2 to +2, `modality` (want, can, must, will), `negation`, `content` (predicate plus slots: object, place, companion, purpose, if/then, demand/sanction).
- "Do you want come with me in the farm to harvest the carrots ?" gives `invite`, force 1, politeness +1, content come(companion=speaker) with purpose harvest(carrot) at farm. "Come with me" gives `order`, force 3, politeness 0. "Please come with me" gives `request`, force 2, politeness +2. The frame fields enter the event token, so refusing an order and refusing an invitation are different events (`refusal_cost`).
- The same frames carry **NPC to NPC speech**: one language for diplomacy, politics, threats and lies. `inform` points to a memory and may distort it; `deceive` is a deliberate false claim (the engine knows the truth).
- Limits: the parser is template-based; unusual grammar falls back to a JSON-constrained parse by the language model you already load for dialogue, validated against the same frame schema. Real coverage has to be measured on real player sentences.

## 5. Society layer (data, not code)

- **Title** = a name plus what NPCs attach to it. There is no global truth about who is mayor: each NPC holds beliefs (holder, confidence, perceived legitimacy, authority attached). Two people can claim the same title; authority exists only to the extent that others obey.
- **Documents**: notices on boards (flyers), newspaper issues, letters, decrees, ballots. Reading one turns its frames into beliefs and memories, weighted by trust in the author. That is how "the lawyer is Pierre" becomes knowledge: an announcement was posted and read.
- **Polls**: question, options, caller, closing time, rules as data (who votes, majority). Rules can be contested. Elections and disputes can go wrong.
- **Player-made titles**: `create_title(name, duties)` adds a word and a text embedding (computed once with the sentence encoder, the only place it is still used). The model sees it through that embedding and the attached frames.
- Functions: `claim_title`, `contest_claim`, `endorse`, `appoint`, `dismiss`, `decree`, `enforce`, `summon`, `call_vote`, `vote`, `campaign`, `post_notice`, `tear_down_notice`, `read`, `interrogate`, `bribe`, `blackmail`, `negotiate`, and others in section 8.

## 6. Model input and output (updates to v0.3)

| Token | Scalars | Max |
|---|---|---|
| self | 45 (+ 7 categories, incl. `tool_in_hand`) | 1 |
| inventory item | 3 (qty, quality, wear) | 8 |
| entity | 20 (v0.3's 18 + suspicion, indirect_threat) | 12 |
| event | 19 (the 14 of v0.3 + force, politeness, negation, conditional, apparent_intent) | 6 |
| memory | 8 (v0.3 + `secret`, `focus_knows`, `conflict`; source may be `inferred`) | 8 |
| goal or commitment | 3 | 4 |
| title | 4 (authority, confidence, legitimacy, claimants) + holder pointer | 6 |

At most 45 tokens, about 480 scalars. Output: a **program** decoded step by step. Each step = function id, arguments (pointers to entity, item, memory or document tokens; direction, tool and small numbers from closed sets), `until` and `interrupt_if` as multi-label. Plus the bounded state and relation deltas, `commitment`, `memory_importance` of v0.3.

Cost (estimates to measure): a plan lasts tens of seconds to minutes of game time, so 120 NPCs cost roughly 2 to 6 decisions per second plus wake-ups, far below the 24 per second assumed earlier; a decoder emitting about 12 program tokens per plan is affordable.

## 7. Training: three data sources

| Source | Teaches | Cost | Status |
|---|---|---|---|
| LLM teacher scores candidate **intents** (first step) in social and political situations | judgment: who to trust, vote, lie, obey, extort, court | tokens (about 4,600 per call of 8 situations, about 51,000 situations per 30 M tokens) | generator and prompt ready, 24 families |
| Scripted work expert | the **form** of work plans: tool choice by trait, length, safety conditions | zero | 13 task and tool mixes, validated by the contract |
| Parser frames | the force and politeness of speech | zero | prototype |

The teacher is not asked to write programs: it scores intents; the tail of the plan (default conditions) comes from engine templates, and work plans come from the scripted expert. This keeps the labelling task simple for a 14B model.

## 8. Function library (generated from the contract)

| Category | Action (args) | Level |
|---|---|---|
| body | `eat(item:I)`, `drink(item:I?,place:P?)`, `sleep(place:P?)`, `rest` | core |
| move | `go_to(place:P?,entity:E?)`, `follow(entity:E)`, `approach(entity:E)`, `avoid(entity:E)`, `flee(entity:E?,place:P?)`, `wander`, `wait(secs:N?)`, `return_home` | core |
| move | `hide(place:P?)` | extension |
| work | `equip(tool:T)`, `unequip`, `dig(dir:D,length:N,tool:T,width:N?,depth:N?)`, `place(block:B,pattern:X?,tool:T?)`, `till(place:P?,tool:T?)`, `plant(seed:I,place:P?)`, `harvest(kind:X,place:P?)`, `cut(target:B,tool:T?)`, `fetch_water(place:P?)`, `craft(recipe:C)` | core |
| work | `build(blueprint:C,place:P?)`, `repair(target:C)`, `tend_crop(place:P?)`, `hunt(target:C)`, `start_build(blueprint:C,place:P)`, `contribute(site:O)`, `supply(site:O,item:I)` | extension |
| inventory | `pick_up(item:I)`, `drop(item:I)`, `store(item:I,place:P)`, `take_from(place:P,item:I)`, `give(entity:E,item:I)`, `steal(entity:E?,place:P?,item:I)` | core |
| inventory | `destroy(target:C)`, `claim(item:I?,place:P?)`, `conceal(item:I,place:P)` | extension |
| speech | `greet(entity:E)`, `chat(entity:E)`, `inform(entity:E,memory:M?,fact:F?)`, `deceive(entity:E,fact:F)`, `ask(entity:E,topic:C?,fact:F?,attr:X?,subject:E?)`, `propose(entity:E,proposal:F)`, `request(entity:E,proposal:F)`, `order(entity:E,proposal:F)`, `accept(proposal:O)`, `refuse(proposal:O)`, `promise(entity:E,proposal:F)`, `threaten(entity:E,fact:F)`, `accuse(entity:E,fact:F)`, `apologize(entity:E)`, `thank(entity:E)`, `compliment(entity:E)`, `insult(entity:E)`, `warn(entity:E,fact:F)`, `call_for_help`, `comfort(entity:E)`, `forgive(entity:E)` | core |
| speech | `teach(entity:E,skill:C)` | extension |
| diplomacy | `interrogate(entity:E,topic:C)`, `bribe(entity:E,offer:F)`, `answer(entity:E,query:O,mode:X)`, `blackmail(entity:E,memory:M)`, `negotiate(entity:E,move:X,sweetener:I?)` | core |
| diplomacy | `lobby(entity:E,topic:C)` | extension |
| politics | `read(doc:O)`, `post_notice(content:F,board:P?)`, `tear_down_notice(doc:O)`, `call_vote(question:F,options:F)`, `vote(poll:O,option:X)`, `campaign(entity:E,audience:E?)`, `claim_title(title:C)`, `contest_claim(entity:E,title:C)`, `endorse(entity:E,title:C)`, `appoint(entity:E,title:C)`, `dismiss(entity:E,title:C)`, `create_title(name:C,duties:F?)`, `decree(rule:F)`, `enforce(rule:F,entity:E)`, `summon(entity:E)` | core |
| politics | `publish(content:F)`, `write_letter(entity:E,content:F)`, `delegate(task:F,entity:E)`, `found_group(name:C,purpose:F?)`, `join_group(group:C)`, `leave_group(group:C)`, `post_job(task:F,pay:F)`, `hire(entity:E,task:F,pay:F)` | extension |
| intimacy | `flirt(entity:E)`, `kiss(entity:E)`, `embrace(entity:E)`, `be_intimate(entity:E)` | core |
| conflict | `attack(entity:E,mode:X)`, `defend(entity:E?)`, `chase(entity:E)`, `expel(entity:E,place:P?)` | core |
| conflict | `restrain(entity:E)` | extension |
| care | `assist(entity:E,task:C?)` | core |
| care | `heal(entity:E)` | extension |
| attention | `observe(entity:E?,place:P?)`, `search(entity:E?,item:I?,place:P?)` | core |
| attention | `eavesdrop(entity:E)`, `investigate(place:P)` | extension |
| leisure | `leisure(activity:C,entity:E?)` | core |
| leisure | `pray`, `mourn` | extension |
| commit | `accompany(entity:E)`, `break_commitment(commitment:O)`, `continue` | core |

Argument types: E entity, I item, T tool, B block or material, P place, D direction (forward, back, left, right, up, down), N integer 1 to 64, C concept (any lexicon word, including user-made titles), F frame, M memory id, O poll, notice or document id, X closed list (for example `harvest.kind` in flower, fruit, vegetable; `attack.mode` in shove, strike, armed, lethal).

## 9. Hard rules (engine, never learned)

- Child categories are never involved in romantic or sexual actions or proposals, as actor or target. Any sexual proposal involving a child category is a reflex rule (`accept` forbidden; `refuse`, `attack`, `expel`, `call_for_help`, `flee` allowed). The teacher never generates or labels such cases.
- Romantic or sexual actions need two adults and mutual consent; `be_intimate` also a private place. Adult blood relatives: no hard rule, the model decides from the `taboo` norm and `taboo_sensitivity` (switch `--no-adult-kin-romance`). Commercial risk: Steam removed incest-themed adult games in July 2025 after payment-processor pressure.
- Feasibility mask (reach, ownership, tools, skill, place) before the model; plan validator after it.
- Titles, polls and rules are data: nothing in code says who is mayor.

## 10. Honest limits

- The parser prototype covers a handful of sentence patterns. Unseen grammar is the main risk for "absolute flexibility"; plan for the constrained fallback and for logging every parse failure in playtests.
- A program decoder is harder to train than a scorer. Start with 1 to 2 step plans; add conditions only where the scripted expert produces them.
- Political emergence will produce degenerate outcomes (a dictator, no one obeying, endless votes). That is wanted, but it needs instrumentation: a "mind viewer" that shows why an NPC obeyed or refused.
- Every function needs animation, preconditions and effects in the action engine: 84 core functions are a large production task. Build the tranche first (work, speech, notices, one vote).
- Nothing here has run against the 14B model yet. The pilot decides the prompt variant.
