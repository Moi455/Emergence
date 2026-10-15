"""Round 2 of the sampler: identity and D10 toward people who are not here, realistic events, a reason to wake that is
justified, memories that feel like what happened, beliefs that make sense, objects that belong to the place, a
demography with babies and the very old, plans that serve their goal, feelings that go together, and the code
that carries it (one grammar, one bootstrap). All measured on the 2200 situations of test_situations."""
from __future__ import annotations

import collections
import math
import re
import statistics
import unittest
from pathlib import Path

from ..builders import WAKE_CAUSES
from .test_situations import (ACTIONS, ADULT, GOV, N, SAMPLER, SAMPLERS, SITS, D10Audit, D10Violation, Party, Record,
                              by_key, nodes, props)

POOLS = SAMPLER.pools
INTIMATE_LINKS = {c.id for c in POOLS.cat["concept"].values() if c.category == "link" and c.intimate}
HOLDING = {"take", "put", "give", "throw", "pour", "wear", "operate", "strike", "push", "pull", "grab", "scoop", "work",
           "tie", "blow", "shape", "channel", "eat", "drink", "sleep", "touch", "search", "examine", "read", "mount", "write"}
FOOD_DRINK = {"eat": "edible", "drink": "drinkable"}
WEARABLE = ("clothing", "headwear", "footwear", "armor", "jewel")


def position(rec):
    f = rec.fields
    return f["dist"] * f["dir"]["cos"], f["dist"] * f["dir"]["sin"]


def events(sit):
    recs = by_key(sit)
    pos = {k: position(r) for k, r in recs.items() if r.type in ("ENTITY", "THING") and "dist" in r.fields} | {"me": (0.0, 0.0)}
    for r in recs.values():
        if r.type == "EVENT":
            f = r.fields
            gap = math.hypot(*(a - b for a, b in zip(pos[f["actor"]], pos[f["target"]]))) if f["target"] else None
            yield r, recs, gap


class TestIdentityAndD10(unittest.TestCase):
    def test_an_intimate_file_is_a_clear_adult_he_knows_by_sight(self):
        n = absent = 0
        for sit in SITS:
            recs = by_key(sit)
            believed = {m.args[0]: int(m.args[2]) for _, root in props(sit, ("BELIEF",)) for m in nodes(root)
                        if m.head == "state" and m.args[1] == "age_years"}
            for r in recs.values():
                if r.type != "ENTITY":
                    continue
                f = r.fields
                if f["link"] in INTIMATE_LINKS or "rel.attraction" in f:
                    n += 1
                    self.assertEqual(f["known_by"], "seen", "never toward a name-only or described person")
                    self.assertGreaterEqual(sit.people[r.key].age, ADULT)
                    if f["present"]:
                        self.assertGreaterEqual(f["look.age"], ADULT)
                    else:
                        absent += 1
                        self.assertGreaterEqual(believed.get(r.key, 0), 21, "an absent partner: his adult age is a belief")
                        self.assertLessEqual(abs(believed[r.key] - sit.people[r.key].age), 1.5)
        self.assertGreater(n, 200)
        self.assertGreater(absent, 5)

    def test_a_described_person_has_no_name_and_the_half_known_are_uncertain(self):
        seen = collections.defaultdict(list)
        for sit in SITS:
            for r in sit.context.records:
                if r.type == "ENTITY":
                    seen[r.fields["known_by"]].append(r.fields)
        self.assertGreater(len(seen["described"]), 30)
        self.assertTrue(all("name" not in f for f in seen["described"]))
        mean = lambda kb, k: statistics.mean(f[k] for f in seen[kb])  # noqa: E731
        for kb in ("name_only", "described"):
            self.assertLess(mean(kb, "id_certainty"), 4.0)
            self.assertLess(mean(kb, "rel.familiarity"), 4.0)
        self.assertGreater(mean("seen", "id_certainty"), 4.5)

    def test_the_link_of_a_half_known_person_is_often_wrong_and_identity_is_sometimes_mistaken(self):
        wrong = collections.Counter()
        total = collections.Counter()
        for sit in SITS:
            truth = {x.person.pid: x.link for x in sit.scene.present} | {p.pid: l for p, l in sit.scene.absent}
            for r in sit.context.records:
                if r.type == "ENTITY":
                    kb, f = r.fields["known_by"], r.fields
                    group = kb if kb != "seen" else ("stranger" if truth[sit.people[r.key].pid] == "stranger" else "known")
                    total[group] += 1
                    wrong[group] += truth[sit.people[r.key].pid] != f["link"]
        self.assertGreater(wrong["name_only"] / total["name_only"], 0.2)
        self.assertGreater(wrong["described"] / total["described"], 0.5)
        self.assertTrue(0.01 < wrong["known"] / total["known"] < 0.15)           # not recognised
        self.assertTrue(0.01 < wrong["stranger"] / total["stranger"] < 0.15)     # taken for somebody
        # certainty is not a function of the true link: some strangers look familiar, some friends are doubtful
        ids = [(r.fields["link"] == "stranger", r.fields["id_certainty"]) for s in SITS for r in s.context.records
               if r.type == "ENTITY" and r.fields["present"]]
        self.assertTrue(any(st and c > 4 for st, c in ids) and any(not st and c < 6 for st, c in ids))

    def test_the_audit_derives_its_own_intimate_fields_from_the_interface(self):
        audit = D10Audit(POOLS)
        self.assertEqual(audit.intimate_fields, {t: frozenset(f) for t, f in POOLS.intimate_fields.items()})
        self.assertIn("rel.attraction", audit.intimate_fields["ENTITY"])
        self.assertGreaterEqual(len(audit.intimate_fields), 3)

    def adults(self):
        sit = next(s for s in SITS if s.scene.self_.age >= 30 and any(
            r.type == "ENTITY" and r.fields["present"] and r.fields["known_by"] == "seen" and r.fields["look.age"] >= 25
            and r.fields["link"] != "stranger" for r in s.context.records))
        recs = [Record(r.type, r.key, dict(r.fields)) for r in sit.context.records
                if r.type not in ("EVENT", "BELIEF", "HEARD", "MEMORY", "GOAL", "PLAN", "REQUEST", "COMMIT")]
        return sit, recs, next(r for r in recs if r.type == "ENTITY" and r.fields["present"] and r.fields["look.age"] >= 25
                               and r.fields["known_by"] == "seen")

    def test_the_audit_refuses_an_intimate_file_toward_somebody_known_by_name_only(self):
        sit, recs, person = self.adults()
        person.fields.update(link=next(iter(INTIMATE_LINKS)), known_by="name_only")     # two adults: the policy alone refuses
        for k in [k for k in person.fields if k.startswith("look.")] + ["dist", "dir"]:
            person.fields.pop(k)
        person.fields["present"] = False
        with self.assertRaises(D10Violation):
            D10Audit(POOLS).check(sit.scene.self_, recs, sit.people)

    def test_the_audit_refuses_an_absent_partner_without_a_believed_adult_age(self):
        sit, recs, person = self.adults()
        for k in [k for k in person.fields if k.startswith("look.")] + ["dist", "dir"]:
            person.fields.pop(k)
        person.fields.update(present=False, link=next(iter(INTIMATE_LINKS)), known_by="seen")
        with self.assertRaises(D10Violation):                                    # no belief (state X age_years N)
            D10Audit(POOLS).check(sit.scene.self_, recs, sit.people)
        belief = Record("BELIEF", "b:1", {"prop": f"(state {person.key} age_years {int(sit.people[person.key].age)})",
                                          "source": "seen", "polarity": True})
        D10Audit(POOLS).check(sit.scene.self_, recs + [belief], sit.people)      # with the belief, two adults: accepted

    def test_the_audit_detects_a_drifted_key_table(self):
        sit, recs, person = self.adults()
        people = dict(sit.people)
        other = next(p for k, p in people.items() if k not in ("me", person.key) and abs(p.age - people[person.key].age) > 12)
        people[person.key] = other
        with self.assertRaises(D10Violation):
            D10Audit(POOLS).check(sit.scene.self_, recs, people)

    def test_the_audit_covers_the_tastes(self):
        sit = next(s for s in SITS if s.scene.self_.age < 12)
        recs = [Record(r.type, r.key, dict(r.fields)) for r in sit.context.records] + [
            Record("TASTE", "t:9", {"concept": "w_ugly", "attitude": 3.0})]
        with self.assertRaises(D10Violation):
            D10Audit(POOLS).check(sit.scene.self_, recs, sit.people)


class TestEvents(unittest.TestCase):
    def test_everything_that_holds_or_uses_its_target_is_within_reach(self):
        n = 0
        for sit in SITS:
            for r, recs, gap in events(sit):
                if r.fields["gesture"] in HOLDING and r.fields["target"]:
                    n += 1
                    self.assertLessEqual(gap, 2.05, (r.fields["gesture"], r.fields["target"]))
        self.assertGreater(n, 2500)

    def test_the_target_fits_the_gesture(self):
        seen = collections.Counter()
        for sit in SITS:
            for r, recs, gap in events(sit):
                g, t = r.fields["gesture"], r.fields["target"]
                if not t.startswith("@T"):
                    continue
                kind = recs[t].fields["kind"]
                cat = POOLS.category_of.get(kind)
                if g in FOOD_DRINK:
                    seen[g] += 1
                    self.assertTrue(POOLS.item_has(kind, FOOD_DRINK[g]), (g, kind))
                if g in ("read", "write"):
                    seen[g] += 1
                    self.assertEqual(cat, "writing")
                if g == "throw":
                    seen[g] += 1
                    self.assertTrue(POOLS.item_has(kind, "throwable"))
                if g == "wear":
                    self.assertIn(cat, WEARABLE)
                if g == "mount":
                    self.assertIn(kind, ("horse", "donkey", "camel", "ox"))
                if g == "take":
                    self.assertTrue(POOLS.item_has(kind, "graspable"))
        for g in ("eat", "drink", "throw"):
            self.assertGreater(seen[g], 10, g)

    def test_what_is_perceived_follows_the_gesture(self):
        senses = collections.Counter()
        for sit in SITS:
            for r in sit.context.records:
                if r.type == "EVENT":
                    text, sense = ACTIONS[r.fields["gesture"]].perceptibility, r.fields["sense"]
                    senses[sense] += 1
                    if sense == "seen":
                        self.assertIn("vu", text)
                    if sense == "heard":
                        self.assertIn("entendu", text)
                    if sense == "felt":
                        self.assertTrue(r.fields["target"] == "me" and ACTIONS[r.fields["gesture"]].contact)
        self.assertGreater(senses["heard"], 50)
        self.assertGreater(senses["seen"], 10 * senses["heard"] / 3)

    def test_going_looking_and_listening_are_at_most_a_third(self):
        g = collections.Counter(r.fields["gesture"] for s in SITS for r in s.context.records if r.type == "EVENT")
        total = sum(g.values())
        self.assertLessEqual((g["go"] + g["look"] + g["listen"]) / total, 0.35)
        self.assertGreater(len(g), 20)

    def test_a_baby_does_what_a_baby_does(self):
        n = 0
        for sit in SITS:
            for r in sit.context.records:
                if r.type == "EVENT" and sit.people[r.fields["actor"]].age < 3:
                    n += 1
                    self.assertIn(r.fields["gesture"], ("look", "listen", "sleep", "rest", "set_posture", "eat", "drink"))
        self.assertGreater(n, 0)

    def test_adults_touch_children_by_hands_arms_and_shoulders(self):
        zone = collections.Counter()
        for sit in SITS:
            for r in sit.context.records:
                f = r.fields
                if r.type == "EVENT" and f["target"] == "me" and sit.scene.self_.age < ADULT and sit.people[f["actor"]].age >= ADULT:
                    zone.update(v for v in f["manner"] if v in ("hands", "hand", "arms", "arm", "shoulder", "back", "head", "legs"))
        self.assertGreater(sum(zone.values()), 60)
        self.assertGreater(sum(zone[k] for k in ("hands", "hand", "arms", "arm", "shoulder")) / sum(zone.values()), 0.6)


class TestWake(unittest.TestCase):
    TARGET = WAKE_CAUSES

    def test_the_causes_follow_the_target_distribution(self):
        c = collections.Counter(by_key(s)["wake"].fields["cause"] for s in SITS)
        for cause, share in self.TARGET.items():
            self.assertAlmostEqual(c[cause] / N, share, delta=0.04, msg=cause)

    def test_the_situation_justifies_the_cause(self):
        for sit in SITS:
            recs = by_key(sit)
            w, types = recs["wake"].fields, collections.Counter(r.type for r in sit.context.records)
            if w["cause"] == "request":
                self.assertEqual(recs[w["trigger"]].type, "REQUEST")
            else:                                               # a request left pending is older than a request that wakes
                self.assertTrue(all(r.fields["age"] >= 2 for r in sit.context.records if r.type == "REQUEST"))
            self.assertEqual(types["HEARD"] > 0, w["cause"] == "speech")
            if w["cause"] == "body":
                me = recs["me"].fields
                self.assertGreaterEqual(max(me[k] for k in ("need.hunger", "need.thirst", "need.sleep", "need.exhaustion", "body.pain")), 7.4)
            else:
                me = recs["me"].fields
                self.assertLessEqual(max(me[k] for k in ("need.hunger", "need.thirst", "need.sleep", "need.exhaustion", "body.pain")), 9.01)
            if w["cause"] == "timer":                      # a deadline passed, or a repeating plan comes round again
                trig = recs[w["trigger"]]
                if trig.type == "PLAN":
                    self.assertNotEqual(trig.fields["repeat"], "once")
                    self.assertIn(trig.fields["status"], ("done", "suspended"))
                else:
                    self.assertLess(trig.fields["deadline"], 0)
            if w["cause"] == "goal_check":
                self.assertEqual(recs[w["trigger"]].type, "GOAL")
                self.assertGreaterEqual(recs[w["trigger"]].fields["progress"], 0.97)
            if w["cause"] == "occasion":
                self.assertIn(recs[w["trigger"]].type, ("GOAL", "ENTITY", "GROUP"))
            if w["cause"] in ("idle", "routine", "body"):
                self.assertEqual(w["trigger"], "")
            if w["cause"] == "plan":
                self.assertEqual(recs[w["trigger"]].type, "PLAN")
            if w["cause"] == "perception":
                self.assertEqual(recs[w["trigger"]].type, "EVENT")
                self.assertLess(recs[w["trigger"]].fields["age"], 0.05)             # a fresh event
            if w["cause"] in ("request", "speech", "perception"):
                self.assertTrue(any(r.type == "ENTITY" and r.fields["present"] for r in sit.context.records))


class TestMemories(unittest.TestCase):
    def test_past_is_recent_and_long_ago_is_old(self):
        n = collections.Counter()
        for sit in SITS:
            for r in sit.context.records:
                if r.type == "MEMORY":
                    word = r.fields["prop"].split()[0].lstrip("(")
                    n[word] += 1
                    self.assertEqual(word == "past", r.fields["age"] < 200.0, (word, r.fields["age"]))
        self.assertGreater(n["past"], 500)
        self.assertGreater(n["long_ago"], 500)

    def memories(self, pattern):
        for sit in SITS:
            for r in sit.context.records:
                if r.type == "MEMORY" and re.search(pattern, r.fields["prop"]):
                    yield r.fields

    def test_force_done_to_him_is_remembered_badly(self):
        force = tuple(g for g, a in ACTIONS.items() if a.family == "force")
        rows = [f for f in self.memories(r"\(did @E\d+ (%s) me" % "|".join(force)) if f["role"] == "target"]
        self.assertGreater(len(rows), 50)
        self.assertLess(statistics.mean(f["valence"] for f in rows), -3)
        self.assertGreater(sum(f["emotion"] in ("e_fear", "e_anger", "e_shame", "e_anxiety", "e_sadness", "e_surprise") for f in rows) / len(rows), 0.9)
        self.assertGreater(sum(f.get("interp") in ("assault", "affront", "threat_felt", "injustice") for f in rows) / len(rows), 0.4)

    def test_a_gift_to_him_is_remembered_with_gratitude(self):
        rows = [f for f in self.memories(r"give \S+ \(to me\)") if f["role"] == "target"]
        self.assertGreater(len(rows), 30)
        self.assertGreater(statistics.mean(f["valence"] for f in rows), 3)
        self.assertGreater(sum(f["emotion"] in ("e_gratitude", "e_joy", "e_tenderness") for f in rows) / len(rows), 0.8)
        self.assertTrue(all(f.get("interp") in (None, "generosity", "kindness") for f in rows))

    def test_a_death_is_grieved(self):
        rows = list(self.memories(r"\(dead "))
        self.assertGreater(len(rows), 25)
        self.assertGreater(sum(f["emotion"] in ("e_grief", "e_sadness") for f in rows) / len(rows), 0.5)
        self.assertLess(statistics.mean(f["valence"] for f in rows), -3)


class TestBeliefsAndObjects(unittest.TestCase):
    def test_no_one_present_is_believed_at_a_faraway_place(self):
        n = 0
        for sit in SITS:
            recs = by_key(sit)
            for rec, root in props(sit, ("BELIEF", "HEARD", "MEMORY")):
                for m in nodes(root):
                    if m.head == "at" and m.args[1].startswith("@L"):
                        n += 1
                        who = recs.get(m.args[0])
                        self.assertTrue(m.args[0] != "me" and (who is None or not who.fields.get("present")), rec.fields["prop"])
        self.assertGreater(n, 100)

    def test_traits_are_stable_not_relations(self):
        n = 0
        traits = SAMPLER.grammar.traits
        for sit in SITS:
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head == "state" and m.args[1] not in ("age_years",) + tuple(SAMPLER.grammar.conditions):
                        n += 1
                        self.assertFalse(m.args[1].startswith("r_"), rec.fields["prop"])
                        self.assertIn(m.args[1], traits)
        self.assertGreater(n, 100)

    def test_the_crowd_is_at_least_the_people_he_sees(self):
        for sit in SITS:
            here = sum(1 for r in sit.context.records if r.type == "ENTITY" and r.fields["present"])
            self.assertGreaterEqual(by_key(sit)["@PLACE"].fields["crowd"], here)

    def kinds_of(self, sit):
        for rec, root in props(sit, ("BELIEF", "GOAL", "COMMIT")):
            for m in nodes(root):
                if m.head == "has" or (m.head == "did" and len(m.args) > 1 and m.args[1] == "give" and len(m.args) > 2):
                    arg = m.args[1] if m.head == "has" else m.args[2]
                    if isinstance(arg, str) and arg.partition(":")[0] in POOLS.category_of:
                        yield arg.partition(":")[0]

    def test_kinds_belong_to_the_place(self):
        fit = total = 0
        for sit in SITS:
            sc = sit.scene
            local = {k for cat in sc.place.items for k in POOLS.items_by_category.get(cat, ())}
            local |= {t.kind for t in sc.things} | set(sc.carried) | set(POOLS.items_by_category["currency"])
            for kind in self.kinds_of(sit):
                total += 1
                fit += kind in local
        self.assertGreater(total, 2000)
        self.assertGreater(fit / total, 0.995)

    def test_only_what_can_be_handed_over_is_given(self):
        n = 0
        for sit in SITS:
            for rec, root in props(sit, ("BELIEF", "HEARD", "MEMORY", "COMMIT")):
                for m in nodes(root):
                    if m.head == "did" and len(m.args) > 2 and m.args[1] == "give" and isinstance(m.args[2], str):
                        kind = m.args[2].partition(":")[0]
                        if kind in POOLS.category_of:
                            n += 1
                            self.assertTrue(POOLS.item_has(kind, "carryable") and POOLS.item_vector(kind)["mass"] <= 10.0, kind)
        self.assertGreater(n, 300)

    def test_a_weapon_for_a_child_is_rare(self):
        kids = [s for s in SITS if s.scene.self_.age < 12]
        weapons = sum(1 for s in kids for r in s.context.records if r.type == "INV" and POOLS.category_of[r.fields["kind"]] in POOLS.weapon_categories)
        inv = sum(1 for s in kids for r in s.context.records if r.type == "INV")
        self.assertGreater(len(kids), 200)
        self.assertLess(weapons / max(1, inv), 0.01)
        adults = [s for s in SITS if s.scene.self_.age >= 18]
        self.assertGreater(sum(1 for s in adults for r in s.context.records if r.type == "INV"
                               and POOLS.category_of[r.fields["kind"]] in POOLS.weapon_categories), weapons)

    def test_a_trade_comes_from_the_occupation_with_some_errors(self):
        ok = n = 0
        for sit in SITS:
            for rec, root in props(sit, ("BELIEF",)):
                for m in nodes(root):
                    if m.head == "works_as":
                        who = sit.scene.self_ if m.args[0] == "me" else sit.people.get(m.args[0])
                        if who is not None and who.occupation:
                            n += 1
                            ok += who.occupation == m.args[1]
        self.assertGreater(n, 100)
        self.assertTrue(0.6 < ok / n < 0.97, ok / n)


class TestDemography(unittest.TestCase):
    def test_babies_and_the_very_old_exist(self):
        ages = [p.age for s in SITS for p in s.scene.persons()]
        self.assertTrue(0.01 < sum(a < 3 for a in ages) / len(ages) < 0.06)
        self.assertGreater(sum(a >= 85 for a in ages) / len(ages), 0.005)
        self.assertGreater(sum(1 for s in SITS if s.scene.self_.age < 3), 15)         # a few baby NPCs

    def test_long_scenes_are_not_biased_by_age(self):
        long = [s.scene.self_.age < 12 for s in SITS if s.scene.long]
        short = [s.scene.self_.age < 12 for s in SITS if not s.scene.long]
        self.assertGreater(len(long), 300)
        self.assertGreater(sum(long) / len(long), 0.6 * sum(short) / len(short))


class TestPlans(unittest.TestCase):
    SERVES = {"has": {"go", "take", "examine", "search", "wait", "look"}, "at": {"go", "wait", "rest", "set_posture", "look", "search", "speak"},
              "owns": {"go", "take", "examine", "look"}, "works_as": {"go", "work", "examine", "rest", "look"},
              "knows_how": {"examine", "work", "go"}, "link": {"go", "look", "wait", "speak"},
              "did": {"go", "give", "speak", "look"}}
    NEED = {"thirst": {"drink", "go", "rest", "look"}, "hunger": {"eat", "go", "rest", "look"}, "exhaustion": {"set_posture", "rest", "go", "sleep"},
            "pain": {"rest", "set_posture"}}

    def test_a_plan_serves_its_goal(self):
        n = collections.Counter()
        for sit in SITS:
            recs = by_key(sit)
            for r in sit.context.records:
                if r.type != "PLAN":
                    continue
                goal = next(iter(props_of(recs[r.fields["goal"]])))
                while goal.head in ("at_time", "before", "after"):             # a time mark does not change what serves the goal
                    goal = goal.args[-1]
                n[goal.head] += 1
                allowed = self.NEED[goal.args[1]] if goal.head == "state" else self.SERVES[goal.head]
                self.assertTrue(set(r.fields["steps"]) <= allowed,
                                (goal.head, r.fields["steps"]))
                self.assertTrue({r.fields["step"], r.fields["next"]} <= set(r.fields["steps"]))
                if r.fields["target"].startswith("@T") and r.fields["step"] in ("drink", "eat"):
                    kind = recs[r.fields["target"]].fields["kind"]
                    self.assertTrue(POOLS.item_has(kind, FOOD_DRINK[r.fields["step"]]))
        self.assertGreater(sum(n.values()), 150)
        self.assertGreater(len(n), 4)


def props_of(rec):
    from .test_situations import PARSER
    return nodes(PARSER.parse(rec.fields["prop"]))


class TestFeelings(unittest.TestCase):
    def test_affection_trust_and_fear_go_together_but_not_perfectly(self):
        rows = [r.fields for s in SITS for r in s.context.records if r.type == "ENTITY" and r.fields["present"]]
        corr = lambda a, b: statistics.correlation([f[a] for f in rows], [f[b] for f in rows])  # noqa: E731
        self.assertTrue(0.4 < corr("rel.affection", "rel.trust") < 0.93)
        self.assertLess(corr("rel.affection", "rel.fear"), -0.2)
        self.assertLess(corr("rel.affection", "rel.resentment"), -0.4)
        self.assertGreater(corr("rel.affection", "rel.perceived_regard"), 0.3)


class TestCode(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_one_bootstrap_touches_sys_path(self):
        users = [p.name for p in self.ROOT.glob("*.py") if "sys.path" in p.read_text() and p.name != "bootstrap.py"]
        self.assertEqual(users, [])

    def test_the_grammar_is_built_once_and_sessions_are_made_per_situation(self):
        from situations.propositions import PropositionGrammar, PropositionSession
        self.assertIsInstance(SAMPLER.grammar, PropositionGrammar)
        self.assertFalse(hasattr(SAMPLER.grammar, "arm"))
        self.assertTrue(hasattr(PropositionSession, "belief") and not hasattr(PropositionSession, "arm"))
        a, b = SAMPLERS[7].sample(3), SAMPLERS[7].sample(3)
        self.assertEqual(a.encoded.digest(), b.encoded.digest())              # no state leaks from one situation to the next

    def test_validation_is_public(self):
        self.assertTrue(callable(SAMPLER.grammar.validate))


if __name__ == "__main__":
    unittest.main()
