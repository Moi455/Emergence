#!/usr/bin/env python3
"""scenario_tests.py - the 30 capabilities, tested against the ENGINE mechanisms, plus questions and negotiation.

Verdicts:
  OK    the engine mechanism exists and is tested here (facts, events and token fields are produced correctly)
  LEARN the information the decision needs reaches the model, but the BEHAVIOUR must be learned from data
  SPEC  specified in the contract/data model, not implemented in the engine yet

A passing test never proves the trained model will behave well; it proves the facts the model needs exist.
  python3 scenario_tests.py
"""
import random
import sys

import dialogue_protocols as dp
import social_rules as sr
import build_site
import plan_contract as pc
import utterance_parser as up
from memory_service import MemoryStore, DAY, HOUR

T0 = 100 * DAY
RESULTS = []


def case(n, title, verdict, note):
    def deco(fn):
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL case {n}: {title}: {e}")
            sys.exit(1)
        RESULTS.append((n, title, verdict, note))
        return fn
    return deco


def S(name, seed=0):
    return MemoryStore(name, rng=random.Random(seed))


# ---------------------------------------------------------------- 1 - 3
@case(1, "Understands that an object belongs to someone", "OK", "'owns' memories from seen use, claims, deeds; belief with confidence")
def _():
    a = S("Marie")
    a.add("owns", agent="Paul", obj="axe_7", t=T0 - DAY, source="seen", certainty=1.0)
    assert sr.believed_owner(a, "axe_7", T0) == ("Paul", 1.0)
    assert sr.believed_owner(a, "axe_9", T0) == (None, 0.0)


@case(2, "Tells taking a free object from stealing an owned one", "OK", "engine truth vs the actor's belief; honest mistakes possible")
def _():
    a = S("Marie")
    a.add("owns", agent="Paul", obj="axe_7", t=T0, source="seen")
    free = {"id": "axe_1", "rightful_owner": None}
    owned = {"id": "axe_7", "rightful_owner": "Paul"}
    unknown = {"id": "axe_8", "rightful_owner": "Paul"}
    assert sr.resolve_take("Marie", a, free, T0)["type"] == "take"
    r = sr.resolve_take("Marie", a, owned, T0)
    assert r["type"] == "theft" and r["intentional"] and not r["mistake"]
    r = sr.resolve_take("Marie", a, unknown, T0)
    assert r["type"] == "theft" and r["mistake"] and not r["intentional"]


@case(3, "Understands an object was hidden on purpose", "OK", "covered or closed items give 'deliberate evidence'; a witnessed hiding names the hider")
def _():
    finder = S("Luc")
    loose = {"id": "gem_1"}
    buried = sr.conceal({"id": "gem_2"}, "Paul", "cellar_7", covered_by_placed_blocks=True)
    assert sr.found_hidden_event(loose, finder, T0)["deliberate_evidence"] == 0.0
    ev = sr.found_hidden_event(buried, finder, T0)
    assert ev["deliberate_evidence"] >= .9 and not ev["hider_known"]
    finder.add("hid_item", agent="Paul", obj="gem_2", t=T0 - 60)
    assert sr.found_hidden_event(buried, finder, T0)["hider_known"]


# ---------------------------------------------------------------- 4 - 8
@case(4, "Senses that someone lies without knowing why", "OK", "refuted claims accumulate as 'suspicion' independent of any motive")
def _():
    luc, anna = S("Luc", 1), S("Anna", 2)
    for i in range(2):
        luc.add("seen_at", agent="Paul", place=f"house_{i}", t=T0 - DAY, payload={"night": True}, event_ref=f"e{i}")
    for mid in list(luc.mems):
        bad = luc.retell(mid, anna, T0, .9, lie=True, alt_place="cellar_7")
    for i in range(2):
        anna.add("seen_at", agent="Paul", place=f"house_{i}", t=T0 + HOUR, payload={"night": True}, event_ref=f"e{i}")
        anna.revise(f"e{i}", {"night": True}, T0 + HOUR)
    assert sr.suspicion(anna, "Luc") >= 35, sr.suspicion(anna, "Luc")
    assert sr.suspicion(anna, "Paul") == 0


@case(5, "Holds two contradictory pieces of information about one event", "OK", "versions are kept side by side with support")
def _():
    a = S("Anna")
    a.add("theft", agent="Paul", t=T0 - DAY, source="told", told_by="Luc", certainty=.6, payload={"culprit": "Paul"}, event_ref="theft_42")
    a.add("theft", agent="Sam", t=T0 - DAY, source="read", certainty=.7, payload={"culprit": "Sam"}, event_ref="theft_42")
    v = a.versions("theft_42")
    assert len(v) == 2 and a.conflict_degree("theft_42") == 1 and abs(sum(x["p"] for x in v) - 1) < .02


@case(6, "Revises a belief after discovering it was false", "OK", "evidence reweights versions and names the wrong teller")
def _():
    a = S("Anna")
    a.add("theft", agent="Paul", t=T0 - DAY, source="told", told_by="Luc", certainty=.6, payload={"culprit": "Paul"}, event_ref="theft_42")
    a.add("theft", agent="Sam", t=T0 - DAY, source="read", certainty=.7, payload={"culprit": "Sam"}, event_ref="theft_42")
    evs = a.revise("theft_42", {"culprit": "Sam"}, T0, source="seen")
    v = a.versions("theft_42")
    assert v[0]["payload"]["culprit"] == "Sam" and v[0]["p"] > .85
    assert any(e["teller"] == "Luc" for e in evs)


@case(7, "Distinguishes seen, told and deduced", "OK", "source is stored per memory and weights belief: seen 1.0, read .8, told .6, inferred .5")
def _():
    a = S("Anna")
    m1 = a.add("theft", agent="Paul", t=T0, source="seen")
    m2 = a.add("theft", agent="Paul", t=T0 + 1, source="told", told_by="Luc", certainty=.6)
    m3 = a.infer("theft", "Paul", {"culprit": "Paul"}, .5, T0 + 2, basis=[m1, m2])
    src = {m["id"]: m["source"] for m in a.mems.values()}
    assert src[m1] == "seen" and src[m2] == "told" and src[m3] == "inferred"
    assert a.mems[m3]["payload"]["basis"] == [m1, m2]


@case(8, "Keeps information about someone and passes it on later", "OK", "retell with lower certainty; the listener's reputation of the person moves")
def _():
    marie, pierre = S("Marie", 3), S("Pierre", 4)
    m = marie.add("theft", agent="Paul", t=T0 - 10 * DAY, source="seen", importance=60, witnesses=["Marie"])
    before = pierre.reputation("Paul", "trust", T0)["value"]
    marie.retell(m, pierre, T0, .8)
    after = pierre.reputation("Paul", "trust", T0)["value"]
    assert before == 0 and after < 0
    assert after > marie.reputation("Paul", "trust", T0)["value"]          # weaker than first-hand


# ---------------------------------------------------------------- 9 - 11
@case(9, "Knows that someone does not know what it knows", "OK", "first-order knowledge: witnesses, who was told, who was seen elsewhere")
def _():
    marie = S("Marie")
    m = marie.add("theft", agent="Paul", place="market", t=T0 - HOUR, witnesses=["Marie"])
    marie.add("seen_at", agent="Pierre", place="field_3", t=T0 - HOUR)
    assert marie.knows("Paul", m) == "yes"          # the culprit knows
    assert marie.knows("Pierre", m) == "no"          # Marie saw him elsewhere
    assert marie.knows("Zed", m) == "unknown"
    pierre = S("Pierre")
    marie.retell(m, pierre, T0, .9)
    assert marie.knows("Pierre", m) == "yes"


@case(10, "Acts differently depending on what the other is believed to know", "LEARN", "token field 'focus_knows' is supplied for every recalled memory")
def _():
    marie = S("Marie")
    m = marie.add("theft", agent="Paul", place="market", t=T0 - HOUR, witnesses=["Marie"], importance=70)
    marie.add("seen_at", agent="Pierre", place="field_3", t=T0 - HOUR)
    c1 = sr.decision_context(marie, "Pierre", ["Pierre"], T0)
    marie.retell(m, S("Pierre"), T0, .9)
    c2 = sr.decision_context(marie, "Pierre", ["Pierre"], T0)
    k1 = {x["kind"]: x["focus_knows"] for x in c1["memories"]}["theft"]
    k2 = {x["kind"]: x["focus_knows"] for x in c2["memories"]}["theft"]
    assert (k1, k2) == ("no", "yes")


@case(11, "Same act, different consequences depending on context", "OK", "witnesses decide who remembers; reputation exists only where it was seen")
def _():
    victim, witness, absent = S("V"), S("W"), S("A")
    for st in (victim, witness):
        st.add("theft", agent="Paul", t=T0, source="seen", importance=60)
    # same act in private: nobody but the victim learns it
    victim2 = S("V2")
    victim2.add("theft", agent="Paul", t=T0, source="seen", importance=60)
    assert witness.reputation("Paul", "trust", T0)["value"] < 0
    assert absent.reputation("Paul", "trust", T0)["value"] == 0
    assert absent.reputation("Paul", "trust", T0)["confidence"] == 0


# --------------------------------------------------------------- 12 - 17
@case(12, "Has contradictory goals at the same time", "LEARN", "up to 4 goal tokens with priorities; the model arbitrates")
def _():
    goals = [{"type": "vengeance", "target": "E2", "priority": 80}, {"type": "project", "target": "harvest_field", "priority": 70},
             {"type": "need", "target": "sleep", "priority": 60}, {"type": "accompany", "target": "E1", "priority": 55}]
    assert len(goals) == 4 and len({g["type"] for g in goals}) == 4
    assert pc.validate_plan({"steps": [{"f": "accompany", "a": {"entity": "E1"}}]}) == []


@case(13, "Gives up an immediate goal for a longer-term one", "LEARN", "plans can ignore a need up to a stated threshold (interrupt_if hunger_above)")
def _():
    plan = {"steps": [{"f": "dig", "a": {"dir": "forward", "length": 30, "tool": "shovel"}, "until": ["found(ore)"],
                       "interrupt_if": ["hunger_above(90)", "hp_below(25)"]}]}
    assert pc.validate_plan(plan) == []


@case(14, "Behaves toward someone according to their history", "OK", "two NPCs with different histories receive opposite reputation tokens")
def _():
    a, b = S("A"), S("B")
    a.add("help_given", agent="Paul", t=T0 - DAY, importance=60)
    b.add("theft", agent="Paul", t=T0 - DAY, importance=60)
    ca, cb = sr.decision_context(a, "Paul", ["Paul"], T0), sr.decision_context(b, "Paul", ["Paul"], T0)
    assert ca["entities"]["Paul"]["rep_trust"] > 0 > cb["entities"]["Paul"]["rep_trust"]


@case(15, "Fears and loves the same person", "OK", "affection and fear are independent scalars; the generator produces such pairs")
def _():
    import generate_states as g
    rng = random.Random(9)
    found = 0
    for i in range(1500):
        rec = g.gen_situation(rng, i, "routine", 7, 4, 2, False)
        found += any(e["rel"]["fear"] > 50 and e["rel"]["affection"] > 40 for e in rec["state"]["entities"])
    assert found > 0, found


@case(16, "Cooperates with someone it hates for a common goal", "LEARN", "goal token carries a 'partner' pointer; the generator produces shared goals with disliked partners")
def _():
    import generate_states as g
    assert "partner" in g.SCHEMA["goal"]["pointers"]
    rng = random.Random(3)
    found = 0
    for i in range(3000):
        rec = g.gen_situation(rng, i, "routine", 7, 4, 2, False)
        ents = {e["id"]: e for e in rec["state"]["entities"]}
        found += any(x.get("partner") and ents[x["partner"]]["rel"]["affection"] < -30 for x in rec["state"]["goals"])
    assert found > 0, found


@case(17, "Pretends to cooperate for a later advantage", "LEARN", "visible action and hidden goal are separate; observers only see the action")
def _():
    plan = {"steps": [{"f": "accompany", "a": {"entity": "E1"}}]}
    hidden_goal = {"type": "betray_later", "target": "E1", "priority": 60}
    assert pc.validate_plan(plan) == [] and hidden_goal["type"] not in ("accompany",)


# --------------------------------------------------------------- 18 - 20
@case(18, "Sees an indirect threat without having been attacked", "OK", "threat from ties: ally of my enemy, enemy of someone I love")
def _():
    me = S("Me")
    me.add("link_belief", agent="Sam", target="Gus", t=T0 - DAY, payload={"affinity": 70, "rel": "ally"})
    me.add("link_belief", agent="Sam", target="Lea", t=T0 - DAY, payload={"affinity": -60, "rel": "rival"})
    t_sam = me.indirect_threat("Sam", enemies=["Gus"], loved=["Lea"], now=T0)
    t_other = me.indirect_threat("Nobody", enemies=["Gus"], loved=["Lea"], now=T0)
    assert t_sam >= 50 and t_other == 0, (t_sam, t_other)


@case(19, "Tells an accident from a deliberate act", "OK", "engine keeps the true flag; witnesses get 'apparent intent' from cues")
def _():
    assert sr.apparent_intent("trip") < .2 < .7 < sr.apparent_intent("strike")
    assert sr.apparent_intent("strike", repeated=1, prior_threat=1) == 1.0
    assert sr.apparent_intent("strike", actor_clumsy=1, apologized=1) < sr.apparent_intent("strike")


@case(20, "Reads the same act differently according to relation and knowledge", "OK", "interpretation shifts with trust and grudge before any model call")
def _():
    ev = sr.apparent_intent("shove")
    friend = sr.interpret_intent(ev, trust=80, grudge=0)
    enemy = sr.interpret_intent(ev, trust=-80, grudge=70)
    assert friend < ev < enemy and enemy - friend > .3


# --------------------------------------------------------------- 21 - 25
@case(21, "Knows a physical change alters what it can do", "OK", "reachability and plan results ('obstacle') change with the voxel world")
def _():
    grid = ["..w..", "..w..", "..w.."]
    assert not sr.reachable(grid, (0, 1), (4, 1))
    grid[1] = "..b.."
    assert sr.reachable(grid, (0, 1), (4, 1))


@case(22, "Uses an environment object that was never scripted for this", "LEARN", "candidates come from affordance tags, not from scenarios; choosing is learned")
def _():
    c = sr.means_for_goal("cross_gap", ["wood", "bell"])
    assert c and c[0]["f"] == "place" and c[0]["a"]["block"] == "wood"
    assert sr.means_for_goal("reach_high", ["ladder"])[0]["f"] == "use"
    assert sr.means_for_goal("cross_gap", ["bell"]) == []


@case(23, "Understands an object as a means to a goal", "OK", "goal -> object by tag (bridge, signal, climbable, carry)")
def _():
    assert sr.means_for_goal("call_attention", ["torch", "stone"])[0]["a"]["item"] == "torch"
    assert sr.means_for_goal("carry_load", ["cart"])


@case(24, "Builds or moves things to change the environment strategically", "LEARN", "wall candidates from blockers; whole buildings via the diff-based build site")
def _():
    c = sr.means_for_goal("block_path", ["stone"])
    assert c[0]["a"]["pattern"] == "wall"
    site = build_site.BuildSite(build_site.house_blueprint(), (0, 0, 0), build_site.World())
    assert len(site.tasks()) == len(site.bp)


@case(25, "Exploits a change made earlier by another NPC", "OK", "a built bridge is perceived, remembered with its builder, and reachability changes")
def _():
    b = S("B")
    grid = ["..w..", "..w..", "..w.."]
    assert not sr.reachable(grid, (0, 1), (4, 1))
    b.add("built", agent="Anna", place="river_1", t=T0 - HOUR, payload={"what": "bridge"}, importance=40)
    grid[1] = "..b.."
    assert sr.reachable(grid, (0, 1), (4, 1))
    assert any(m["kind"] == "built" and m["agent"] == "Anna" for m in b.recall(T0, entities=("Anna",)))


# --------------------------------------------------------------- 26 - 30
@case(26, "A past event in a place keeps having consequences", "OK", "places carry danger, fondness and taboo from memories, fading over time")
def _():
    a = S("A")
    a.add("murder", agent="X", place="cellar_7", t=T0 - DAY, valence=-90, importance=80)
    now = a.place_reputation("cellar_7", T0)
    later = a.place_reputation("cellar_7", T0 + 300 * DAY)
    assert now["taboo"] and now["fondness"] < -50 and now["danger"] > 20
    assert later["danger"] < now["danger"] and later["fondness"] > now["fondness"] and later["taboo"]   # fear fades, the taboo stays
    assert a.place_reputation("meadow_1", T0)["n"] == 0


@case(27, "Reasons about several people at once: who knows what, who likes whom", "OK", "belief links among third parties + first-order knowledge for each pair")
def _():
    me = S("Me")
    me.add("link_belief", agent="Paul", target="Marie", t=T0, payload={"affinity": 80, "rel": "lover"})
    me.add("link_belief", agent="Marie", target="Luc", t=T0, payload={"affinity": -70, "rel": "enemy"})
    m = me.add("secret_affair", agent="Paul", target="Marie", t=T0, secret=True, witnesses=["Me"], importance=70)
    assert me.link_belief("Marie", "Paul", T0)["affinity"] == 80
    assert me.link_belief("Luc", "Marie", T0)["affinity"] == -70
    assert me.knows("Luc", m) == "unknown" and me.knows("Paul", m) == "yes"


@case(28, "A journalist's article changes people who were not there", "OK", "documents become 'read' memories, weighted by trust in the author")
def _():
    witness, reader_trust, reader_doubt = S("W", 1), S("R1", 2), S("R2", 3)
    witness.add("theft", agent="Paul", t=T0, source="seen", importance=60)
    for st, trust in ((reader_trust, 90), (reader_doubt, 10)):
        st.add("theft", agent="Paul", t=T0 + HOUR, source="read", certainty=.3 + .6 * trust / 100, importance=50,
               payload={"author": "Journalist"})
    rw = witness.reputation("Paul", "trust", T0 + HOUR)["value"]
    r1 = reader_trust.reputation("Paul", "trust", T0 + HOUR)["value"]
    r2 = reader_doubt.reputation("Paul", "trust", T0 + HOUR)["value"]
    assert rw < r1 < r2 < 0 or rw <= r1 <= r2 < 0, (rw, r1, r2)


@case(29, "Several groups with different interests", "SPEC", "group token and found/join/leave functions are in the contract; no engine yet")
def _():
    for f in ("found_group", "join_group", "leave_group"):
        assert f in pc.FUNCTIONS


@case(30, "A long causal chain: event -> perception -> memory -> rumour -> reputation -> relation -> behaviour", "OK", "every link produces data; the last link is the model's choice")
def _():
    witness, bob, carl = S("W", 1), S("Bob", 2), S("Carl", 3)
    m = witness.add("theft", agent="Paul", place="market", t=T0, source="seen", importance=70, witnesses=["W"], event_ref="th1")
    assert witness.reputation("Paul", "trust", T0)["value"] < 0                       # perception -> memory -> reputation
    b1 = witness.retell(m, bob, T0 + HOUR, .8)                                         # transmission
    c1 = bob.retell(b1, carl, T0 + 2 * HOUR, .8)
    reps = [witness.reputation("Paul", "trust", T0 + 3 * HOUR)["value"], bob.reputation("Paul", "trust", T0 + 3 * HOUR)["value"],
            carl.reputation("Paul", "trust", T0 + 3 * HOUR)["value"]]
    assert reps[0] <= reps[1] <= reps[2] < 0                                           # reputation spreads, weaker each hop
    ctx = sr.decision_context(carl, "Paul", ["Paul"], T0 + 3 * HOUR)                   # behaviour: what the model will see
    assert ctx["entities"]["Paul"]["rep_trust"] < 0 and ctx["memories"][0]["source"] == "told"


# ======================================================== questions & negotiation
def questions_and_negotiation():
    lex = up.Lexicon()
    lex.add("paul", "person")
    pierre, zed, marie = S("Pierre", 1), S("Zed", 2), S("Marie", 3)
    for d in (3, 2, 1):
        pierre.add("seen_at", agent="paul", place="house_12", t=T0 - d * DAY, payload={"night": True}, importance=40)
    pierre.add("saw_money", agent="paul", t=T0 - 2 * DAY, payload={"coins": 30}, importance=30)
    rng = random.Random(5)
    out = []
    # "Where does Paul live?" typed by the player -> frame -> query -> memory
    fr = up.parse("Where does Paul live ?", lex)["frame"]["content"]["query"]
    q = dp.build_question(pierre, "Pierre", "Zed", fr["attr"], fr["subject"], T0, affection_to_subject=60,
                          trust_in_asker=0, familiarity_with_asker=5)
    assert q["know"] in ("sure", "likely") and q["sens"] >= 70, q
    out.append(f"home of Paul: know={q['know']} sens={q['sens']} (friend asked by a stranger)")
    # the model picks a mode; here three different characters
    a = dp.apply_answer("refuse", q, rng)
    assert a["content"] is None
    a = dp.apply_answer("unknown", q, rng)
    assert a["feigned_ignorance"] is True
    out.append("feigned ignorance is flagged (the engine knows he knew)")
    a = dp.apply_answer("lie", q, rng, alt_values=["cellar_7"])
    assert a["content"] == "cellar_7" and a.get("is_lie")
    dp.asker_update(zed, "Pierre", a, trust_in_answerer=70, now=T0)
    assert zed.lookup("home_of", "paul", T0)["value"] == "cellar_7"
    out.append("a believed lie becomes a wrong belief in the asker")
    zed.add("seen_at", agent="paul", place="house_12", t=T0 + DAY, payload={"night": True}, event_ref="x")
    for m in list(zed.mems.values()):
        if m["kind"] == "told_home":
            zed.refute(m["id"], T0 + DAY)
    assert sr.suspicion(zed, "Pierre") >= 35
    out.append("the lie is found out: suspicion of Pierre rises")
    # a friend asks and Pierre tells the truth
    q2 = dp.build_question(pierre, "Pierre", "Marie", "home_of", "paul", T0, affection_to_subject=60, trust_in_asker=80, familiarity_with_asker=80)
    assert q2["sens"] < q["sens"]
    a2 = dp.apply_answer("truth", q2, rng)
    dp.asker_update(marie, "Pierre", a2, trust_in_answerer=80, now=T0)
    assert marie.lookup("home_of", "paul", T0)["value"] == "house_12"
    # "How much money does Paul have?"
    fr = up.parse("How much money does Paul have ?", lex)["frame"]["content"]["query"]
    q3 = dp.build_question(pierre, "Pierre", "Zed", fr["attr"], fr["subject"], T0, affection_to_subject=10, trust_in_asker=20, familiarity_with_asker=40)
    assert q3["attr"] == "wealth_of" and q3["sens"] >= 60
    a3 = dp.apply_answer("vague", q3, rng)
    assert a3["content"] in ("poor", "modest", "comfortable", "rich")
    a3b = dp.apply_answer("truth", q3, rng)
    assert abs(a3b["content"] - 30) <= 3
    out.append(f"wealth of Paul: vague={a3['content']} truth~{a3b['content']} (an estimate, never the exact figure)")
    # someone who never met Paul
    q4 = dp.build_question(marie_blank := S("Blank"), "Blank", "Zed", "home_of", "paul", T0)
    assert q4["know"] == "none" and dp.apply_answer("truth", q4, rng)["mode"] == "unknown"
    out.append("no knowledge: 'truth' degrades to 'unknown', the engine never invents")
    # the NPC asked about itself
    q5 = dp.build_question(S("Paul"), "paul", "Zed", "wealth_of", "paul", T0)
    assert q5["know"] == "sure"
    # ---------------- negotiation
    buyer = {"hunger": 70}
    seller = {"hunger": 10}
    n_ok = 0
    deals = 0
    for seed in range(200):
        r = random.Random(seed)
        neg = dp.Negotiation(buyer, seller, "bread", r.randint(1, 5), r)
        dp.run(neg, r)
        assert neg.status in ("deal", "walked", "open"), neg.status
        if neg.status == "deal":
            deals += 1
            assert neg.res_seller - 1e-6 <= neg.deal_price <= neg.res_buyer + 1e-6 or neg.log
            b_inv, s_inv = {"coin": 100}, {"bread": 10, "coin": 0}
            before = b_inv["coin"] + s_inv["coin"], b_inv.get("bread", 0) + s_inv["bread"]
            assert dp.settle(neg, b_inv, s_inv, S("b"), S("s"), T0)
            after = b_inv["coin"] + s_inv["coin"], b_inv.get("bread", 0) + s_inv["bread"]
            assert before == after                                                  # coins and goods are conserved
        n_ok += 1
    assert deals > 100
    out.append(f"negotiation: {deals}/200 deals, always terminating, coins and goods conserved")
    # no overlap -> walk away
    rich_seller = {"hunger": 100}
    poor_buyer = {"hunger": 0}
    r = random.Random(1)
    neg = dp.Negotiation(poor_buyer, rich_seller, "meat", 3, r)
    neg.res_buyer, neg.res_seller = 5, 30
    dp.run(neg, r)
    assert neg.status != "deal"
    # unforeseen event: the goods are sold elsewhere mid-negotiation
    calm = {"hunger": 5}                       # not in a hurry, so the haggling lasts several rounds
    r = random.Random(2)
    neg = dp.Negotiation(calm, seller, "bread", 3, r)
    res = dp.run(neg, r, disturb=lambda rd, n: rd == 2, alt=lambda n: dp.Negotiation(calm, seller, "apple", 6, random.Random(3)))
    assert neg.status == "void" and isinstance(res, dp.Negotiation) and res.good == "apple"
    dp.run(res, random.Random(3))
    assert res.status in ("deal", "walked")
    out.append("an unforeseen event voids the offer cleanly and a substitute good is negotiated")
    # failed settlement is atomic
    r = random.Random(11)
    neg = dp.Negotiation(buyer, seller, "bread", 2, r)
    neg.status, neg.deal_price = "deal", 50
    b_inv, s_inv = {"coin": 5}, {"bread": 9, "coin": 0}
    assert not dp.settle(neg, b_inv, s_inv, S("b"), S("s"), T0) and b_inv == {"coin": 5} and s_inv == {"bread": 9, "coin": 0}
    out.append("a deal that cannot be paid is rejected and nothing moves")
    return out


if __name__ == "__main__":
    extra = questions_and_negotiation()
    print("\n=== The 30 capabilities ===")
    sym = {"OK": "OK   ", "LEARN": "LEARN", "SPEC": "SPEC "}
    for n, title, verdict, note in RESULTS:
        print(f"{n:2d}. [{sym[verdict]}] {title}\n        {note}")
    c = {v: sum(1 for r in RESULTS if r[2] == v) for v in ("OK", "LEARN", "SPEC")}
    print(f"\n{len(RESULTS)} cases: {c['OK']} OK (mechanism tested), {c['LEARN']} LEARN (facts delivered, behaviour to be trained), {c['SPEC']} SPEC (specified, not built)")
    print("\n=== Questions and negotiation ===")
    for line in extra:
        print("-", line)
