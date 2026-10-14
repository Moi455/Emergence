# NPC decision model - condensed spec v0.3 (English)

> **Partly superseded by `npc_architecture_v0.4.md`** (2 Oct 2026): the model now outputs a multi-step plan instead of one action (section 3 below is replaced by the 101-function library), and tokens for inventory, titles and speech-act frames were added. Variable tables in sections 2.1 to 2.4 remain valid.


30 Sep - 2 Oct 2026 (rev. 2). Supersedes v0.2 for everything the model sees. Companion files: `generate_states.py`, `teacher_prompt.md`, `teacher_tools.py`, `schema.json`.

## 1. Design decisions

- **The model consumes numeric tokens, never text.** Runtime cost depends on the number of tokens (max 31), not on scalars per token (a linear projection is almost free). Condensing variables therefore saves mainly teacher/training tokens and design/test surface, not game speed. Game speed comes from: token caps, a small d_model, int8, event-driven calls, batching bursts.
- **The teacher (LLM) sees a sparse, binned text**: neutral values omitted, 5 levels (`--`, `-`, neutral, `+`, `++`; `some/high/max` for intensities). Measured with the Mistral v3 tokenizer: **286 tokens per situation** (JSON would be 522). The student keeps the exact numbers; fine resolution comes from the reference scorer, qualitative corrections from the teacher.
- Names are English everywhere; the model never sees personal names or French text.

## 2. Model input (max 31 tokens, about 400 scalars, plus reserved spare slots)

| Token | Scalars | Categories | Max |
|---|---|---|---|
| self | 45 | 6 | 1 |
| perceived entity | 18 | 4 | 12 |
| recent event | 14 | 3 | 6 |
| memory | 5 | 3 | 8 |
| goal / commitment | 3 | 2 | 4 |

### 2.1 self (45 scalars)

| Group | Variables | Range |
|---|---|---|
| traits (9) | aggression, courage, empathy, sociability, honesty, impulsivity, curiosity, justice, grudge | -100..100 |
| temperament (2) | reactivity, resilience | 0..100 |
| values (6) | kin_protection, property_respect, honor, life_value, romantic_fidelity, taboo_sensitivity | 0..100 |
| drives (4) | libido, social_need, achievement, hoarding | 0..100 |
| states (10) | hunger, thirst, pain, fear, shock, confusion (0..100); fatigue, anger, stress, joy (-100..100) | |
| body (4) | hp, strength, load_ratio (0..1), job_skill | 0..100 |
| activity (3) | progress (0..1), commitment (how absorbed, 0..100), secs_since_decision | |
| stock gap (3) | food, fuel, tools | -100..100 |
| time (4) | hour_sin, hour_cos, season_sin, season_cos | |

Categories (6): age_cat {child, adolescent, adult, elder}, love_status {single, courting, partnered, married, separated, widowed}, job, current_action (one of the 76 actions or idle), weather, place_type.

### 2.2 perceived entity (18 scalars)

| Group | Variables | Range |
|---|---|---|
| relation (8) | affection, trust, respect, romance, debt (-100..100); fear, familiarity, grudge (0..100) | |
| mood (2) | mood_toward, urge_to_interact | -100..100 |
| perception (8) | chemistry (-1..1, hash of (seed, A, B)), perceived (0..1), distance, beauty, days_since_contact, rep_trust, rep_danger (-100..100), understanding (0..4) | |

Categories (4): kin_links (multi-hot: spouse, partner, child, parent, sibling, friend, neighbor, colleague, employer, employee, rival, enemy), age_cat, love_status, visible_action.

### 2.3 event (14 scalars)

intensity, salience, understanding (0..4), reliability, delay, out_of_world, plus **8 norm-violation values** (0..100): kin, property, honor, life, fidelity, truth, fairness, taboo. They come from an offline appraisal table (action x context x link x flags) and are weighted by the NPC's values: kin_protection, property_respect, honor, life_value, romantic_fidelity, honesty (trait), justice (trait), taboo_sensitivity. The `taboo` value is high for a romantic advance between blood relatives: the table only signals it, the NPC's own taboo_sensitivity and the rest of its state decide. Categories: type, role {target, witness, agent, reporter}, source {seen, heard, told}. Agent and target are pointers to entity tokens.

### 2.4 memory (5 scalars) and goal (3 scalars)

memory: age_days, certainty, importance, valence, defining; categories type, role, source (agent/target pointers).
goal or commitment: priority, progress, deadline_h; categories type, target.

## 3. Model output

| Head | Content |
|---|---|
| action | one of the 76 actions below, masked by feasibility (distribution, sampled with a per-NPC seed) |
| target | pointer over the entity tokens (when the action needs E) |
| argument | item / location / activity / mode / proposal id / fact, chosen among engine-provided options |
| d_state | 10 bounded deltas for the states in 2.1 |
| d_relation | 8 bounded deltas toward the addressed entity |
| new_goal | optional: type, target, priority |
| commitment | 0..100, sets the interrupt threshold |
| memory_importance | 0..100 for the event just lived |

The engine applies the bounds, the decay toward baseline, and the feasibility mask. Argument codes: E entity, I item, R resource node, L location, A activity, F fact or claim, P proposal id, K skill, M mode, C commitment id. The verb of `gather` is chosen by the resource's affordance (chop, mine, pick, fish).

### 3.1 The 76 actions (59 core, 17 extension)

| Category | Action (args) | Level |
|---|---|---|
| body | `eat(I)`, `drink(I/R)`, `sleep(L)`, `rest` | core |
| move | `go_to(L)`, `follow(E)`, `approach(E)`, `avoid(E)`, `flee(E/L)`, `wander`, `wait`, `return_home` | core |
| move | `hide(L)` | extension |
| work | `gather(R)`, `till(L)`, `plant(I,L)`, `harvest(L)`, `draw_water(R)`, `craft(recipe)` | core |
| work | `clear_land(L)`, `dig(L)`, `tend_crop(L)`, `build(L)`, `repair(target)`, `hunt(R)` | extension |
| inventory | `pick_up(I)`, `drop(I)`, `store(I,L)`, `take_from(L,I)`, `give(E,I)`, `steal(E/L,I)` | core |
| inventory | `destroy(target)`, `claim(I/L)` | extension |
| speech | `greet(E)`, `chat(E)`, `inform(E,F)`, `deceive(E,F)`, `ask(E,F)`, `propose(E,P)`, `request(E,P)`, `accept(P)`, `refuse(P)`, `promise(E,P)`, `threaten(E,F)`, `accuse(E,F)`, `apologize(E)`, `thank(E)`, `compliment(E)`, `insult(E)`, `warn(E,F)`, `call_for_help`, `comfort(E)`, `forgive(E)` | core |
| speech | `order(E,P)`, `teach(E,K)` | extension |
| intimacy | `flirt(E)`, `kiss(E)`, `embrace(E)`, `be_intimate(E)` | core |
| conflict | `attack(E,M)`, `defend(E)`, `chase(E)`, `expel(E,L)` | core |
| conflict | `restrain(E)` | extension |
| care | `assist(E,task)` | core |
| care | `heal(E)` | extension |
| attention | `observe(E/L)`, `search(E/I/L)` | core |
| attention | `eavesdrop(E)`, `investigate(L)` | extension |
| leisure | `leisure(A,E?)` | core |
| leisure | `pray`, `mourn` | extension |
| commit | `accompany(E)`, `break_commitment(C)`, `continue` | core |

`attack` modes: shove, strike, armed, lethal. Speech acts carry a structured content (proposal kind: leisure, trade, task, accompany, romance, harm; or a fact pointing to a memory or event). `deceive` is a deliberate false claim; the engine knows the truth and distinguishes a lie from a mistake.

## 4. Engine only (the model never sees these)

| Group | Variables |
|---|---|
| identity and body | id, name (player and verbalizer only), is_player, ai_level {light, advanced}, age, alive, position, heading, path, posture, endurance, senses |
| temperament baseline | baseline_mood, decay constants per state, bounds, max delta per decision |
| drives (parameters) | accumulation rate and last satisfaction time per drive |
| preferences | tree category -> object -> value (-100..100); the engine passes only the resolved value for each object, place or activity present in a token |
| skills | per domain: farming, woodcutting, mining, stonework, smithing, carpentry, building, cooking, hunting, fishing, healing, trade, melee, persuasion, stealth |
| possessions | inventory (type, quantity, quality, wear, freshness, rightful_owner), equipment, home, owned land, stock targets, debts and credits (source of the `debt` scalar) |
| knowledge | known individuals, places, mental map, known resources, known owners, recipes, rumours, where_is(target) distribution |
| goals and commitments | full lists with success and abandon conditions; the model receives the 4 most important |
| perception | radii, field of view, noise, objective and perceived salience, opportunity interest, wake-up threshold |
| world | grid cell (terrain, fertility, humidity, cover, soil state, crop, minerals, water, owner, danger), resources defined by data (affordances: action, tool, skill, effort, duration, yield, depletion, side effects), buildings, item types, recipes, plants, trees, time, weather |
| player and verbalizer | structured command, free text, converted event (speech act + content + out_of_world), verbalizer queue (one request at a time), schema version, random seed |

## 5. Hard rules enforced by the engine (never learned)

- **Child categories (child, adolescent) are never involved in romantic or sexual actions or proposals**, as actor or target. Non-negotiable; also a legal and platform requirement.
- Romantic or sexual actions (`flirt`, `kiss`, `be_intimate`) require two adults (adult or elder) and mutual consent; `be_intimate` also requires a private place. `embrace` is a plain hug, allowed at any age.
- **Adult blood relatives: no hard rule.** The model decides, driven by the `taboo` norm signal and the NPC's taboo_sensitivity (design decision of 2 Oct 2026). The switch `--no-adult-kin-romance` turns it off in data and in the validator. Commercial risk to weigh: in July 2025 Steam removed numerous incest-themed adult games after payment-processor pressure, and its rules now say that content violating payment processors' standards may be refused, "in particular certain kinds of adult only content".
- Any proposal of a sexual nature involving a child category is handled by a reflex rule, not by data: `accept` forbidden; `refuse`, `attack`, `expel`, `call_for_help`, `flee` allowed. The teacher never generates or labels such cases.
- `attack` mode `lethal` is not available to a child category.
- Feasibility mask: the model only chooses among actions the engine finds possible now (reach, ownership, tools, skill, place).
- Absolute taboos and the platform content rules are checked here, before the model and before the verbalizer.

## 6. How the generator keeps states coherent

- Traits come from 5 latent factors (warmth, extraversion, conscientiousness, openness, hotheadedness), so they correlate. 5 percent of traits are flipped on purpose (out of character).
- Needs derive from the clock and the time since the last meal or drink; fatigue from hours awake; pain from hit points.
- Relations derive from the link type (spouse, child, rival...) and ages respect the link (a parent is at least 16 years older).
- About 12 percent of entities get a contradiction (loved but distrusted...). Each one is explained by a memory (a lie, an insult, a gift) so that no label needs an impossible story. Low pain with low hit points is allowed only when shock is high.
- `python3 generate_states.py --n 4000 --check` validates 18 invariants (ages, ranges, kinship, romance with minors, romantic events with minors, explained relations, forbidden candidates, no leak of hidden fields to the teacher). On 9 seeds x 4,000 situations: no violation except 1 rare unexplained relation (memory cap, since raised to 9).
- Fixed on 2 Oct: the spouse was wrongly treated as a blood relative, so romantic actions toward a spouse never appeared; elders were excluded from romance. Both corrected.

## 7. Teaching new variables after the first training

Plan for it now; it is cheap if the following holds.

- **Spare slots.** Reserve unused inputs that are always zero and masked: +6 scalars in self, +4 per entity, +2 per event, and 2 spare categories per token. The first layer's weights for these slots start at zero, so activating one changes nothing until training moves it.
- **Neutral default = no effect.** A new variable defaults to its neutral value in all old data. Because the teacher text omits neutral values, old labels stay valid; only situations where the new variable is non-neutral need new labels (order of magnitude: a few thousand situations, 1 to 2 M tokens; to be measured).
- **Retrain with a replay mix.** Fine-tune on new targeted data mixed with old data (no catastrophic forgetting), small learning rate. The model is small, so a full retraining from scratch stays a cheap fallback; the real cost is labels, not compute.
- **Versioned schema.** `schema_version` in every record and checkpoint; the generator and the tensor encoder read the same schema file.
- **Harder cases:** changing the meaning of an existing variable (relabel everything it touches), adding a new action (new output class: needs targeted data and a masked reserved slot), removing a variable (set it to neutral and retrain).
