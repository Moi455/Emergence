# NPC memory, questions, negotiation, jobs, construction - v0.5

2 Oct 2026. Companion to `npc_architecture_v0.4.md`. Everything marked "tested" is run by `scenario_tests.py`, `memory_service.py`, `build_site.py` or `generate_states.py --check`.

## 0. Were these cases tested?

Not before this version: the contract of v0.4 covered actions, not questions or negotiations. Writing the tests exposed these gaps, now fixed:

- The parser did not understand "where does Paul live" or "how much money does Paul have". It now extracts an attribute and a subject (also after "do you know ...").
- No protocol existed for answering. Added the function `answer(entity, query, mode)`; the engine builds the content from the NPC's real belief.
- `negotiate` could not express a move. It is now `negotiate(entity, move, sweetener)` with moves chosen from a closed list; the engine computes the figures.
- The memory had no notion of what others know, of competing versions of an event, of deductions, of reputation, of places or of ties among third parties. All added (section 1).
- One of my own tests (case 26) was too permissive because of an operator-precedence slip; it is now strict.
- Case 16 failed as "specified"; I built it (shared goals with a disliked partner) so it counts as data the model receives.

Honest limits: a passing test shows that the facts the decision needs exist and that the engine updates them correctly. It does not show that the trained model will behave well. The negotiation test uses a hand-written stub in place of the model, and its 200 out of 200 deals mostly reflect a hungry buyer; it validates the protocol, not realism.

## 1. Memory: how it is managed (engine side, `memory_service.py`)

The model never stores or retrieves anything. It receives the few memories recalled for the current situation, as tokens.

| Mechanism | How it works |
|---|---|
| Record | kind, agent, target, object, place, time, **source** (seen, heard, told, read, inferred), who told, certainty, importance, valence, secret, defining, witnesses, who it was told to, `event_ref` (to link several versions of one event) |
| Consolidation | the same event (same kind, agent, target, place, source) within 30 minutes merges into one record with a count: 30 chats are one record |
| Forgetting | strength = importance x exp(-age / tau); tau grows with importance and with each recall; `defining` memories never fade; below a floor the record disappears |
| Capacity | about 300 records for light NPCs, about 1,000 for advanced ones; the weakest non-defining record is evicted first |
| Recall | top K by strength, relevance (entities, place, kinds) and emotion; recalling reinforces |
| Transmission | a retold memory is weaker (certainty x trust in the teller); honest drift grows with doubt; a lie falsifies the content; the teller remembers whom it told |
| Beliefs | `lookup(attr, subject)`: where_is (distribution over places, recent sightings dominate), home_of (repeated night sightings or told), wealth_of (estimate with a precision, or a flagged guess), job_of, title_holder (from read notices, with alternatives) |
| Contradiction | versions of one event are kept side by side with support; new evidence reweights them, names the wrong tellers (suspicion) and lowers their claims |
| Reputation | computed from memories about a person (trust, danger), weighted by source, recency and count |
| Places | danger, fondness and taboo from what happened there; fear fades, a taboo stays |
| Third-party ties | beliefs about who likes whom; indirect threat from ties to my enemies or against my loved ones |

What the model sees per recalled memory: kind, source, agent, target, age, certainty, importance, valence, defining, secret, **focus_knows** (does the person I am dealing with know this? yes, no, unknown) and **conflict** (number of competing versions).

Not measured yet: recall cost at 1,000 records per NPC across 120 NPCs. It is a linear scan per decision; with a few decisions per second it should be small, but this needs a benchmark in the real engine.

## 2. Questions: "where does Paul live", "how much money does Paul have"

Pipeline (tested end to end):

1. The parser turns the sentence into a query: `ask_info`, attribute `home_of`, subject `paul`.
2. The engine looks it up in the **answerer's** memory and builds a question event: `know` (sure, likely, vague, none) and `sens` (how private it is: home 40, wealth 70, secret 90, shifted by closeness to the subject, trust in the asker, familiarity).
3. The model chooses a mode: `truth`, `vague`, `lie`, `refuse`, `unknown`, `redirect`.
4. The engine builds the content from the real belief. With `know = none`, `truth` degrades to `unknown`: the engine never invents. `unknown` while the NPC does know is recorded as **feigned ignorance**.
5. The asker keeps a "told" memory with certainty set by trust in the answerer; a refusal is remembered as a refusal.
6. A believed lie becomes a wrong belief; when an observation refutes it, the claim drops and suspicion of the liar rises.

Wealth ("sous" are coins, an item): an NPC knows its own purse exactly; about others it only holds an estimate with a precision, from what it saw or was told, or a flagged guess from the person's job. Asking "how many coins" therefore returns "about 30", never the exact figure.

Interrogation and extortion use the same mechanism with a `pressure` field (polite, threat, bribe).

## 3. Negotiation

The engine computes, for each side, what an offer is worth (market price shaped by that NPC's need and stock gap) and exposes `gain`, `fair` and `round`. The model chooses a move: `accept`, `concede_small`, `concede_big`, `hold`, `raise`, `sweeten`, `bluff_walk`, `walk`; the engine moves the price accordingly. Settlement is atomic (all or nothing), both sides write a memory of the deal (fair or hard), and an unforeseen event (goods sold elsewhere) voids the offer cleanly so that a substitute can be negotiated. Tested: termination, conservation of coins and goods, no overlap leads to a walk-away, failed payment moves nothing.

Not covered: non-monetary offers (favours, votes, alliances) use the same moves but need valuations of intangible things.

## 4. Jobs

A job is **data**, like a title, not a class in code:

- name, tools, skills it trains, recipes, workplace affordances (forge, field, mine), the work intents it offers (what an NPC with this job can usefully do now), an income arrangement (barter, coins, wage);
- the NPC carries `job` (category), `job_skill` (grows when plans complete) and, if employed, an `employer` link; a job can be learned from a master (`teach`, `hire` an apprentice);
- the model decides **whether and what** to work on, from needs, stock gaps, the achievement drive, posted jobs and demand on the notice boards; the engine supplies the candidate work intents and runs the plans;
- a job created by the player (`create_title("brewer")`) is just a name plus whatever NPCs attach to it.

Status: the scripted work expert (13 task and tool combinations) and the job categories exist; the Job registry and the apprenticeship and wage flows are specified (`post_job`, `hire`) but not built.

## 5. Construction

The three options, judged:

| Option | Strength | Weakness |
|---|---|---|
| NPCs place blocks themselves, planned by the model | rich, uses the tool physics | brittle: every unforeseen event breaks a long plan |
| Gather resources, a witch pours them into her cauldron, the house pops | robust, simple, fits a fantasy village | removes tool-based building from NPCs; risks feeling too easy |
| **Diff-based build site, two modes on the same data (recommended)** | cannot get stuck; supports both | needs a site and blueprint registry |

How the recommended one works (`build_site.py`, 13 tests):

- A building is a **blueprint** (position to block; parametric houses, barns, walls) placed at an origin on a **site** that holds the materials delivered so far.
- Work is always recomputed as the **difference between blueprint and world**. A block someone destroyed returns as a task; a boulder in the doorway becomes a `clear` task; missing material becomes a `needs` list. Nothing stores "step 14 of 80", so nothing can be corrupted.
- **Hands-on mode**: NPCs place blocks with their tools (trowel fine and neat, shovel fast and rough, a pickaxe cannot place, hands cannot break blocks).
- **Ritual or time-lapse mode**: once the stock is in, the witch or a mason finishes the diff over time; it stops and reports what is missing if the cauldron runs dry. This is your witch idea, built on the same data, so one can start with it and add hands-on building later.
- Tested: a build with vandalism, a boulder in the doorway and a 12-block wood shortage finishes exactly equal to the blueprint with no stray block; it is idempotent once done; damage after completion heals itself.

What the decision model does (and only this): decide that a house is needed, choose blueprint and site within bounds, recruit and pay workers (negotiation), organise materials (gathering plans, notices), react to a failure (missing material, site claimed by someone else, a worker absent). The geometry is the engine's job.

To make the witch interesting rather than a shortcut: she costs a price (negotiation), needs materials and time, can be unavailable, can be bribed or refuse. She becomes a political and economic actor.

## 6. The 30 cases

Verdicts: **OK** the engine mechanism exists and is tested; **LEARN** the facts reach the model, the behaviour has to be learned from data; **SPEC** specified, not built. Counts: 22 OK, 7 LEARN, 1 SPEC.

| # | Case | Verdict | Mechanism |
|---|---|---|---|
| 1 | Understands that an object belongs to someone | OK | 'owns' memories from seen use, claims, deeds; belief with confidence |
| 2 | Tells taking a free object from stealing an owned one | OK | engine truth vs the actor's belief; honest mistakes possible |
| 3 | Understands an object was hidden on purpose | OK | covered or closed items give 'deliberate evidence'; a witnessed hiding names the hider |
| 4 | Senses that someone lies without knowing why | OK | refuted claims accumulate as 'suspicion' independent of any motive |
| 5 | Holds two contradictory pieces of information about one event | OK | versions are kept side by side with support |
| 6 | Revises a belief after discovering it was false | OK | evidence reweights versions and names the wrong teller |
| 7 | Distinguishes seen, told and deduced | OK | source is stored per memory and weights belief: seen 1.0, read .8, told .6, inferred .5 |
| 8 | Keeps information about someone and passes it on later | OK | retell with lower certainty; the listener's reputation of the person moves |
| 9 | Knows that someone does not know what it knows | OK | first-order knowledge: witnesses, who was told, who was seen elsewhere |
| 10 | Acts differently depending on what the other is believed to know | LEARN | token field 'focus_knows' is supplied for every recalled memory |
| 11 | Same act, different consequences depending on context | OK | witnesses decide who remembers; reputation exists only where it was seen |
| 12 | Has contradictory goals at the same time | LEARN | up to 4 goal tokens with priorities; the model arbitrates |
| 13 | Gives up an immediate goal for a longer-term one | LEARN | plans can ignore a need up to a stated threshold (interrupt_if hunger_above) |
| 14 | Behaves toward someone according to their history | OK | two NPCs with different histories receive opposite reputation tokens |
| 15 | Fears and loves the same person | OK | affection and fear are independent scalars; the generator produces such pairs |
| 16 | Cooperates with someone it hates for a common goal | LEARN | goal token carries a 'partner' pointer; the generator produces shared goals with disliked partners |
| 17 | Pretends to cooperate for a later advantage | LEARN | visible action and hidden goal are separate; observers only see the action |
| 18 | Sees an indirect threat without having been attacked | OK | threat from ties: ally of my enemy, enemy of someone I love |
| 19 | Tells an accident from a deliberate act | OK | engine keeps the true flag; witnesses get 'apparent intent' from cues |
| 20 | Reads the same act differently according to relation and knowledge | OK | interpretation shifts with trust and grudge before any model call |
| 21 | Knows a physical change alters what it can do | OK | reachability and plan results ('obstacle') change with the voxel world |
| 22 | Uses an environment object that was never scripted for this | LEARN | candidates come from affordance tags, not from scenarios; choosing is learned |
| 23 | Understands an object as a means to a goal | OK | goal -> object by tag (bridge, signal, climbable, carry) |
| 24 | Builds or moves things to change the environment strategically | LEARN | wall candidates from blockers; whole buildings via the diff-based build site |
| 25 | Exploits a change made earlier by another NPC | OK | a built bridge is perceived, remembered with its builder, and reachability changes |
| 26 | A past event in a place keeps having consequences | OK | places carry danger, fondness and taboo from memories, fading over time |
| 27 | Reasons about several people at once: who knows what, who likes whom | OK | belief links among third parties + first-order knowledge for each pair |
| 28 | A journalist's article changes people who were not there | OK | documents become 'read' memories, weighted by trust in the author |
| 29 | Several groups with different interests | SPEC | group token and found/join/leave functions are in the contract; no engine yet |
| 30 | A long causal chain: event -> perception -> memory -> rumour -> reputation -> relation -> behaviour | OK | every link produces data; the last link is the model's choice |

Cases 22 to 25 (objects used as means, strategic construction) are the least certain: the engine proposes candidates from object tags and goals, but creative use will only be as good as the data teaches. Case 29 (groups with diverging interests) is the one real gap: no group engine yet.

Questions and negotiation, as tested:

- home of Paul: know=sure sens=80 (friend asked by a stranger)
- feigned ignorance is flagged (the engine knows he knew)
- a believed lie becomes a wrong belief in the asker
- the lie is found out: suspicion of Pierre rises
- wealth of Paul: vague=comfortable truth~30 (an estimate, never the exact figure)
- no knowledge: 'truth' degrades to 'unknown', the engine never invents
- negotiation: 200/200 deals, always terminating, coins and goods conserved
- an unforeseen event voids the offer cleanly and a substitute good is negotiated
- a deal that cannot be paid is rejected and nothing moves

## 7. Model inputs added in this version

| Token or field | Status |
|---|---|
| entity: `suspicion`, `indirect_threat` | produced by the generator, with a coherence rule (no unexplained suspicion; a threat needs a tie memory) |
| event: `apparent_intent` (accident, unclear, deliberate) | produced by the generator for harmful events |
| memory: `focus_knows`, `conflict`, source `inferred` | `focus_knows` produced by the generator; `conflict` by the memory service |
| goal: `partner` pointer (shared goal with a disliked person) | produced |
| families `info_request` and `negotiation` | produced, with candidates `answer` and `negotiate` |
| token `link` (who likes whom), `place`, `object` (believed owner), `group` | specified in `schema.json`, computed by the engine modules, not yet emitted by the generator |

## 8. What remains, in order

1. Pilot with the 14B model: JSON validity, self-agreement, agreement with your hand labels.
2. Emit the `link`, `place` and `object` tokens from the generator.
3. Group engine (case 29) and Job registry.
4. A behavioural test suite for the trained model: the 30 cases as minimal pairs, run against the student, not against the engine.
5. Benchmark memory recall and the interrupt manager in the real engine.
6. Measure how much real player language the template parser covers.
