"""Tests of the situation sampler (python3 -m unittest discover -s ai/situations/tests -t ai).

About 2200 situations from three seeds are drawn once and examined from every side: pointers, D10 through the
governor, absence of leaks, no constant field, coherence of links and ages, realism of events and states,
long contexts, determinism between processes. No test writes or labels romantic or sexual content about a minor:
the refusals are checked on contact gestures and on a physical quality, never on an intimate act.
"""
from __future__ import annotations

import collections
import json
import math
import os
import subprocess
import sys
import unittest
from pathlib import Path

AI = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AI))
from situations.audit import D10Audit, D10Violation  # noqa: E402
from situations.sampler import Situation, SituationSampler  # noqa: E402
from situations.scene import ADULT, LinkRules  # noqa: E402
from tok2 import Record  # noqa: E402

import language  # noqa: E402  (path set by situations.pools)
from governor import ADULT_AGE, Governor, Party  # noqa: E402

SEEDS = ((7, 1100), (11, 700), (23, 400))
SAMPLERS = {seed: SituationSampler(seed=seed) for seed, _ in SEEDS}
SITS = [SAMPLERS[seed].sample(i) for seed, n in SEEDS for i in range(n)]
N = len(SITS)
SAMPLER = SAMPLERS[7]
PARSER = language.Parser()
GOV = Governor()
ACTIONS = SAMPLER.pools.cat["action"]


def nodes(node):
    if isinstance(node, language.Node):
        yield node
        for a in node.args:
            yield from nodes(a)


def props(sit, types=("BELIEF", "HEARD", "MEMORY", "GOAL", "COMMIT")):
    for r in sit.context.records:
        if r.type in types and r.fields.get("prop"):
            yield r, PARSER.parse(r.fields["prop"])


def by_key(sit):
    return {r.key: r for r in sit.context.records}


def sort_of(sym: str) -> str:
    if sym == "me":
        return "P"
    if sym.startswith("@E"):
        return "P"
    if sym.startswith("@T"):
        return "T"
    if sym.startswith(("@L", "@PLACE")):
        return "L"
    if sym.startswith("@G"):
        return "G"
    return "?"


# the sort of pointer each slot of a predicate expects (P person or me, T thing, L place, G group)
SLOTS = {"owns": "PT", "at": "PL", "lives_at": "PL", "has": "P", "quality": "P", "state": "P", "works_as": "P",
         "knows_how": "P", "member": "PG", "holds": "P", "link": "P?P", "dead": "P", "believes": "P", "past": "",
         "long_ago": "", "worth": "", "norm": ""}


class TestPointers(unittest.TestCase):
    def test_every_pointer_is_of_the_sort_its_predicate_expects(self):
        seen = collections.Counter()
        for sit in SITS:
            for rec, root in props(sit):
                for n in nodes(root):
                    slots = SLOTS.get(n.head)
                    if not slots:
                        continue
                    for want, arg in zip(slots, n.args):
                        if isinstance(arg, str) and (arg[:1] == "@" or arg == "me"):
                            if want != "?":
                                self.assertEqual(sort_of(arg), want, f"{rec.key} {rec.fields['prop']}: {n.head} {arg}")
                            seen[n.head] += 1
        for pred in ("owns", "at", "member", "dead", "link", "lives_at", "quality", "has"):
            self.assertGreater(seen[pred], 20, pred)

    def test_dead_is_said_of_a_person_who_is_not_here(self):
        n = 0
        for sit in SITS:
            recs = by_key(sit)
            for rec, root in props(sit, ("MEMORY",)):
                for m in nodes(root):
                    if m.head == "dead":
                        n += 1
                        who = recs.get(m.args[0])
                        self.assertTrue(who is None or not who.fields["present"], rec.fields["prop"])
        self.assertGreater(n, 50)

    def test_every_pointer_points_somewhere_in_his_mind(self):
        for sit in SITS[:600]:
            keys = set(sit.context.known_keys)
            for rec, root in props(sit):
                for m in nodes(root):
                    for a in m.args:
                        if isinstance(a, str) and a[:2] in ("@E", "@T", "@L", "@G"):
                            self.assertIn(a, keys, rec.fields["prop"])

    def test_few_propositions_are_rejected(self):
        for s in SAMPLERS.values():
            made, bad, refused = s.props.made, s.props.dropped, s.props.refused
            self.assertLess(bad / (made + bad + refused), 0.01)
            self.assertLess(refused / (made + bad + refused), 0.01)

    def test_no_person_is_linked_to_himself(self):
        for sit in SITS:
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head == "link":
                        self.assertNotEqual(m.args[0], m.args[2], rec.fields["prop"])


class TestD10(unittest.TestCase):
    """The audit has already run on every situation (the sampler raises otherwise); here it is checked again from the
    outside, with the governor."""

    def party(self, sit, rec):
        f = rec.fields
        return Party(real_age=sit.people[rec.key].age, believed_age=f["look.age"], apparent_age=f["look.age"],
                     resolved=f["known_by"] == "seen")

    def test_every_event_is_allowed_by_the_governor(self):
        contact_with_minor = whitelisted = 0
        for sit in SITS:
            recs = by_key(sit)
            me = Party(real_age=sit.scene.self_.age, believed_age=recs["me"].fields["age"], apparent_age=recs["me"].fields["age"], resolved=True)
            for r in recs.values():
                if r.type != "EVENT":
                    continue
                f, a = r.fields, ACTIONS[r.fields["gesture"]]
                actor = self.party(sit, recs[f["actor"]])
                params = {p.name: v for p in a.params if p.type == "enum" for v in f["manner"] if v in p.values}
                ref = next((p.name for p in a.params if p.type == "ref"), None)
                target = {"me": me}.get(f["target"]) or (self.party(sit, recs[f["target"]]) if f["target"].startswith("@E") else
                                                         Party(resolved=True, person=False))
                v = GOV.check_gesture(a.id, params, actor, {ref: target} if ref and f["target"] else {})
                self.assertTrue(v.allowed, (a.id, params, v.code))
                if a.contact and (actor.may_be_minor() or target.may_be_minor()) and target.person:
                    contact_with_minor += 1
                    whitelisted += bool(a.minor_whitelist)
        self.assertGreater(contact_with_minor, 3)             # the rule is exercised, not vacuous

    def test_every_proposition_is_allowed_by_the_governor(self):
        refused = 0
        for sit in SITS[:500]:
            recs = by_key(sit)
            parties = {r.key: Party(real_age=sit.people[r.key].age, believed_age=r.fields.get("look.age"),
                                    apparent_age=r.fields.get("look.age"), resolved=r.fields["known_by"] == "seen")
                       for r in recs.values() if r.type == "ENTITY"}
            me = Party(real_age=sit.scene.self_.age, believed_age=sit.scene.self_.age, apparent_age=sit.scene.self_.age, resolved=True)
            for rec, _ in props(sit):
                e = language.Expression(rec.fields["prop"], GOV.vocab, bare=True)
                refused += not GOV.check_record("belief", e, me, parties).allowed
        self.assertEqual(refused, 0)

    def test_the_age_of_majority_is_the_governors(self):
        self.assertEqual(ADULT, float(ADULT_AGE))
        self.assertEqual(D10Audit(SAMPLER.pools).adult, float(ADULT_AGE))

    def test_intimate_fields_only_between_clear_adults(self):
        audit = D10Audit(SAMPLER.pools)
        partners = minors = 0
        for sit in SITS:
            me, recs = sit.scene.self_, by_key(sit)
            if me.age < ADULT:
                minors += 1
                self.assertNotIn("attracted_to", recs["me.mind"].fields)
                self.assertNotIn("drive.intimacy", recs["me.state"].fields)
            for r in recs.values():
                if r.type == "ENTITY" and (r.fields["link"] in audit.intimate_links or "rel.attraction" in r.fields):
                    partners += 1
                    self.assertGreaterEqual(me.age, ADULT)
                    self.assertGreaterEqual(sit.people[r.key].age, ADULT)
                    self.assertGreaterEqual(r.fields.get("look.age", ADULT), ADULT)
        self.assertGreater(partners, 100)                    # adults do have partners
        self.assertGreater(minors, 100)                      # and children are NPCs too

    def test_no_intimate_symbol_anywhere(self):
        audit = D10Audit(SAMPLER.pools)
        for sit in SITS[:600]:
            for r in sit.context.records:
                for name, v in r.fields.items():
                    if not (r.type == "ENTITY" and name == "link"):
                        self.assertFalse(set(audit._tokens(v)) & audit.bad, (r.key, name, v))

    def test_no_physical_quality_is_said_of_a_possible_minor(self):
        said = 0
        for sit in SITS:
            recs = by_key(sit)
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head == "quality" and m.args[1] in ("w_beautiful", "w_ugly"):
                        said += 1
                        who = m.args[0]
                        age = sit.scene.self_.age if who == "me" else sit.people[who].age if who in sit.people else None
                        self.assertTrue(age is not None and age >= ADULT)
                        if who in recs and recs[who].type == "ENTITY":
                            self.assertGreaterEqual(recs[who].fields.get("look.age", 0), ADULT)
        self.assertGreater(said, 20)                         # said of adults, so the rule is not vacuous

    def test_attention_on_a_possible_minor_keeps_the_drive_low(self):
        low = 0
        for sit in SITS:
            recs = by_key(sit)
            att, drive = recs["me.state"].fields.get("attention"), recs["me.state"].fields.get("drive.intimacy")
            if drive is not None and att in recs and recs[att].type == "ENTITY":
                seen = recs[att].fields.get("look.age", 0)
                if seen < ADULT or sit.people[att].age < ADULT:
                    low += 1
                    self.assertLessEqual(drive, 2.0)
        self.assertGreater(low, 3)

    # ---- the audit refuses what it must (contact on a possible minor, a physical quality, a symbol) ----------------
    def adult_and_minor(self):
        sit = next(s for s in SITS if s.scene.self_.age >= 30 and any(
            r.type == "ENTITY" and r.fields.get("look.age") is not None and r.fields["look.age"] < 12 for r in s.context.records))
        recs = [Record(r.type, r.key, dict(r.fields)) for r in sit.context.records]
        recs = [r for r in recs if r.type not in ("EVENT", "BELIEF", "HEARD", "MEMORY", "GOAL", "PLAN", "REQUEST", "COMMIT")]
        child = next(r for r in recs if r.type == "ENTITY" and r.fields.get("look.age") is not None and r.fields["look.age"] < 12)
        return sit, recs, child

    def test_the_audit_refuses_a_contact_gesture_outside_the_whitelist(self):
        sit, recs, child = self.adult_and_minor()
        audit = D10Audit(SAMPLER.pools)
        actor = next(r.key for r in recs if r.type == "ENTITY" and r.fields["present"] and r.key != child.key)
        ev = Record("EVENT", "@V1", {"actor": actor, "gesture": "strike", "target": child.key, "sense": "seen",
                                     "age": 0.01, "manner": ["torso"]})
        with self.assertRaises(D10Violation):
            audit.check(sit.scene.self_, recs + [ev], sit.people)
        ok = Record("EVENT", "@V1", dict(ev.fields, manner=["head", "open_hand"]))
        audit.check(sit.scene.self_, recs + [ok], sit.people)           # the whitelist is accepted

    def test_the_audit_refuses_a_physical_quality_of_a_possible_minor(self):
        sit, recs, child = self.adult_and_minor()
        bad = Record("BELIEF", "b:1", {"prop": f"(quality {child.key} w_ugly mid)", "source": "heard"})
        with self.assertRaises(D10Violation):
            D10Audit(SAMPLER.pools).check(sit.scene.self_, recs + [bad], sit.people)

    def test_the_audit_refuses_an_intimate_symbol_in_any_text_field(self):
        sit = next(s for s in SITS if s.scene.self_.age >= 30)
        audit = D10Audit(SAMPLER.pools)
        recs = [Record(r.type, r.key, dict(r.fields)) for r in sit.context.records]
        for where in ({"type": "BELIEF", "key": "b:9", "fields": {"prop": "(link me lover me)"}},
                      {"type": "PLAN", "key": "p:1", "fields": {"step": "touch", "next": "intimate", "goal": "g:1", "target": "me"}},
                      {"type": "SKILL", "key": "k:9", "fields": {"technique": "lover", "self_estimate": 1.0}}):
            with self.assertRaises(D10Violation, msg=where["type"]):
                audit.check(sit.scene.self_, recs + [Record(where["type"], where["key"], where["fields"])], sit.people)

    def test_the_audit_refuses_an_orientation_field_on_a_young_npc(self):
        s = next(x for x in SITS if x.scene.self_.age < ADULT)
        recs = [Record(r.type, r.key, dict(r.fields)) for r in s.context.records]
        next(r for r in recs if r.type == "SELF_MIND").fields["attracted_to"] = ["male"]
        with self.assertRaises(D10Violation):
            D10Audit(SAMPLER.pools).check(s.scene.self_, recs, {})


class TestOwnersDoNotLeak(unittest.TestCase):
    def owners(self):
        strangers, known = [], []
        for sit in SITS:
            recs = by_key(sit)
            things = [r for r in sit.context.records if r.type == "THING" and not sit.scene.things[int(r.key[2:]) - 1].animal]
            for r in things:
                t = sit.scene.things[int(r.key[2:]) - 1]
                if t.owner is None or t.owner == sit.scene.self_.pid:
                    continue
                key = next((k for k, p in sit.people.items() if p.pid == t.owner and k in recs), None)
                if key is None:
                    continue
                (strangers if recs[key].fields["link"] == "stranger" else known).append((r.fields.get("owner"), key, t.seen_use))
        return strangers, known

    def test_a_strangers_thing_is_rarely_correctly_owned_and_sometimes_wrongly(self):
        strangers, known = self.owners()
        self.assertGreater(len(strangers), 500)
        exact = sum(o == k for o, k, _ in strangers) / len(strangers)
        wrong = sum(o not in (None, k) for o, k, _ in strangers) / len(strangers)
        self.assertLess(exact, 0.5)
        self.assertGreater(wrong, 0.05)
        self.assertGreater(sum(o == k for o, k, _ in strangers), 0)                          # right only sometimes
        self.assertEqual(sum(o == k for o, k, seen in strangers if not seen), 0)             # never without having seen him use it

    def test_a_known_persons_thing_is_often_but_not_always_rightly_owned(self):
        _, known = self.owners()
        exact = sum(o == k for o, k, _ in known) / len(known)
        self.assertGreater(exact, 0.6)
        self.assertLess(exact, 0.97)
        self.assertGreater(sum(o not in (None, k) for o, k, _ in known), 5)

    def test_wrong_beliefs_exist_but_his_own_things_are_known(self):
        mine = [r for sit in SITS for r in sit.context.records if r.type == "INV"]
        self.assertGreater(sum(r.fields["owner"] == "me" for r in mine) / len(mine), 0.9)


class TestNoConstantField(unittest.TestCase):
    CONSTANT_BY_NATURE = {("SELF", "place"),       # always the place he is in
                          ("SELF", "wound")}       # [] = no wound; the words of wounds are not in the vocabulary yet

    def test_no_field_is_constant(self):
        values = collections.defaultdict(set)
        counts = collections.Counter()
        for sit in SITS:
            for r in sit.context.records:
                for k, v in r.fields.items():
                    values[(r.type, k)].add(json.dumps(v, sort_keys=True))
                    counts[(r.type, k)] += 1
        constant = [k for k, vs in values.items() if counts[k] >= 100 and len(vs) == 1 and k not in self.CONSTANT_BY_NATURE]
        self.assertEqual(constant, [])

    def test_flags_have_a_plausible_rate(self):
        rate = collections.defaultdict(list)
        for sit in SITS:
            for r in sit.context.records:
                if r.type in ("BELIEF", "HEARD", "MEMORY"):
                    for k in ("polarity", "secret", "contradicted", "defining"):
                        if k in r.fields:
                            rate[(r.type, k)].append(bool(r.fields[k]))
        mean = lambda k: sum(rate[k]) / len(rate[k])  # noqa: E731
        for t in ("BELIEF", "HEARD"):
            self.assertTrue(0.85 < mean((t, "polarity")) < 0.95, (t, mean((t, "polarity"))))
        self.assertTrue(0.02 < mean(("BELIEF", "secret")) < 0.10)
        self.assertTrue(0.02 < mean(("BELIEF", "contradicted")) < 0.12)
        self.assertTrue(0.03 < mean(("MEMORY", "defining")) < 0.15)


class TestLinks(unittest.TestCase):
    def test_ages_fit_the_links(self):
        for sit in SITS:
            me = sit.scene.self_.age
            for x in sit.scene.present:
                a, link = x.person.age, x.link
                if link == "sibling":
                    self.assertLessEqual(abs(a - me), 15)
                elif link == "friend":
                    self.assertLessEqual(abs(a - me), 4 if me < ADULT else 15)
                    self.assertTrue(me < ADULT or a >= ADULT)
                elif link == "apprentice":
                    self.assertGreaterEqual(a, 12)
                    self.assertGreaterEqual(me - a, 8)
                elif link == "master":
                    self.assertGreaterEqual(me, 12)
                    self.assertGreaterEqual(a, ADULT)
                elif link == "employee":
                    self.assertGreaterEqual(a, 14)
                    self.assertGreaterEqual(me, ADULT)
                elif link == "employer":
                    self.assertGreaterEqual(me, 14)
                    self.assertGreaterEqual(a, ADULT)
                elif link == "parent":
                    self.assertGreaterEqual(a - me, 15.99)
                elif link == "child":
                    self.assertGreaterEqual(me - a, 15.99)
                elif link == "colleague":
                    self.assertGreaterEqual(min(a, me), 14)

    def test_at_most_one_spouse_or_betrothed_and_few_lovers(self):
        spouses = lovers = 0
        for sit in SITS:
            links = collections.Counter(x.link for x in sit.scene.present) + collections.Counter(p_l[1] for p_l in sit.scene.absent)
            self.assertLessEqual(links["spouse"] + links["betrothed"], 1)
            self.assertLessEqual(links["lover"], 1)
            spouses += bool(links["spouse"] + links["betrothed"])
            lovers += bool(links["lover"])
        self.assertGreater(spouses, 20)
        self.assertLess(lovers, 0.04 * N)

    def test_partners_are_clear_adults_on_both_sides(self):
        audit = D10Audit(SAMPLER.pools)
        for sit in SITS:
            for x in sit.scene.present:
                if x.link in audit.intimate_links:
                    self.assertGreaterEqual(x.person.age, ADULT + 3)
                    self.assertGreaterEqual(sit.scene.self_.age, ADULT + 3)

    def test_beliefs_about_me_repeat_the_entity_link(self):
        seen = 0
        for sit in SITS:
            recs = by_key(sit)
            for rec, root in props(sit, ("BELIEF", "HEARD", "MEMORY")):
                for m in nodes(root):
                    if m.head == "link" and m.args[2] == "me" and m.args[0] in recs:
                        seen += 1
                        self.assertEqual(m.args[1], recs[m.args[0]].fields["link"], rec.fields["prop"])
        self.assertGreater(seen, 100)

    def test_links_between_others_fit_their_ages(self):
        rules, n = LinkRules(SAMPLER.pools), 0
        for sit in SITS[:800]:
            recs = by_key(sit)
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head == "link" and "me" not in (m.args[0], m.args[2]) and m.args[0] in sit.people and m.args[2] in sit.people:
                        n += 1
                        self.assertTrue(rules.fits(m.args[1], sit.people[m.args[0]].age, sit.people[m.args[2]].age), rec.fields["prop"])
        self.assertGreater(n, 10)

    def test_names_are_unique_in_a_scene(self):
        for sit in SITS:
            names = [p.name for p in sit.scene.persons()]
            self.assertEqual(len(names), len(set(names)))


class TestAges(unittest.TestCase):
    def test_a_young_child_has_no_trade_no_engagement_no_craft(self):
        young = [s for s in SITS if s.scene.self_.age < 8]
        self.assertGreater(len(young), 60)
        for sit in young:
            types = {r.type for r in sit.context.records}
            self.assertFalse(types & {"COMMIT", "SKILL"})
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head in ("works_as", "knows_how") and m.args[0] == "me":
                        self.fail(rec.fields["prop"])
            for r in sit.context.records:
                if r.type == "REQUEST" and r.fields["prop"].startswith("(request (did me "):
                    self.assertTrue(r.fields["prop"].startswith("(request (did me give "), r.fields["prop"])

    def test_nobody_under_14_has_a_trade_in_a_belief(self):
        for sit in SITS:
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head == "works_as":
                        who = sit.scene.self_ if m.args[0] == "me" else sit.people.get(m.args[0])
                        self.assertTrue(who is None or who.age >= 14, rec.fields["prop"])

    def test_no_reading_at_five(self):
        for sit in SITS:
            if sit.scene.self_.age < 9:
                self.assertFalse([r for r in sit.context.records if r.type == "BELIEF" and r.fields["source"] == "read"])

    def test_young_children_rarely_strike_or_throw_or_work(self):
        n = rare = 0
        for sit in SITS:
            recs = by_key(sit)
            for r in sit.context.records:
                if r.type == "EVENT" and sit.people[r.fields["actor"]].age < 8:
                    n += 1
                    rare += ACTIONS[r.fields["gesture"]].family in ("force", "tool", "transform") or r.fields["gesture"] == "throw"
        self.assertGreater(n, 30)
        self.assertLess(rare / n, 0.05)


class TestEvents(unittest.TestCase):
    def position(self, rec):
        f = rec.fields
        return f["dist"] * f["dir"]["cos"], f["dist"] * f["dir"]["sin"]

    def test_actors_and_targets_are_present(self):
        n = 0
        for sit in SITS:
            recs = by_key(sit)
            for r in sit.context.records:
                if r.type != "EVENT":
                    continue
                n += 1
                self.assertTrue(recs[r.fields["actor"]].fields["present"])
                t = r.fields["target"]
                if t.startswith("@E"):
                    self.assertTrue(recs[t].fields["present"])
                elif t and t != "me":
                    self.assertEqual(recs[t].type, "THING")
        self.assertGreater(n, 3000)

    def test_contact_only_within_reach(self):
        contact = 0
        for sit in SITS:
            recs = by_key(sit)
            for r in sit.context.records:
                if r.type != "EVENT" or not ACTIONS[r.fields["gesture"]].contact:
                    continue
                t = r.fields["target"]
                if not t:
                    continue
                contact += 1
                ax, ay = self.position(recs[r.fields["actor"]])
                tx, ty = (0.0, 0.0) if t == "me" else self.position(recs[t])
                self.assertLessEqual(math.hypot(ax - tx, ay - ty), 2.05, (r.fields["gesture"], t))
        self.assertGreater(contact, 100)

    def test_families_have_realistic_frequencies(self):
        fam = collections.Counter(ACTIONS[r.fields["gesture"]].family for s in SITS for r in s.context.records if r.type == "EVENT")
        total = sum(fam.values())
        share = lambda *fs: sum(fam[f] for f in fs) / total  # noqa: E731
        self.assertGreater(share("perceive", "move", "grasp"), 0.6)
        self.assertTrue(0.005 < share("force") < 0.05, share("force"))
        self.assertLess(share("care"), 0.05)

    def test_gaze_and_attention_are_on_what_is_perceived(self):
        for sit in SITS:
            recs = by_key(sit)
            ok = {"me", ""} | {k for k, r in recs.items() if (r.type == "ENTITY" and r.fields["present"]) or r.type == "THING"}
            for r in recs.values():
                if r.type == "ENTITY" and r.fields["present"]:
                    self.assertIn(r.fields["look.gaze"], ok - {r.key})
            att = recs["me.state"].fields["attention"]
            self.assertTrue(att is None or att in ok - {"", "me"}, att)

    def test_senses_and_postures_are_varied_but_running_is_rare(self):
        sense = collections.Counter(r.fields["sense"] for s in SITS for r in s.context.records if r.type == "EVENT")
        self.assertGreater(len(sense), 1)
        post = collections.Counter(r.fields["look.posture"] for s in SITS for r in s.context.records
                                   if r.type == "ENTITY" and "look.posture" in r.fields)
        self.assertLess(post["running"] / sum(post.values()), 0.05)
        motion = collections.Counter((r.fields["look.posture"], r.fields["look.motion"]) for s in SITS for r in s.context.records
                                     if r.type == "ENTITY" and "look.posture" in r.fields)
        self.assertEqual(sum(v for (p, m), v in motion.items() if p in ("sitting", "lying") and m != "still"), 0)


class TestStates(unittest.TestCase):
    def mean(self, xs):
        xs = list(xs)
        return sum(xs) / len(xs)

    def me(self, sit, name):
        return by_key(sit)["me"].fields[name]

    def test_sleep_follows_the_hour(self):
        night = self.mean(self.me(s, "need.sleep") for s in SITS if s.scene.hour < 4)
        day = self.mean(self.me(s, "need.sleep") for s in SITS if 10 < s.scene.hour < 15)
        self.assertGreater(night - day, 3.0)

    def test_hunger_follows_the_meals(self):
        before = self.mean(self.me(s, "need.hunger") for s in SITS if 11.5 < s.scene.hour < 12.5 or 18 < s.scene.hour < 19)
        after = self.mean(self.me(s, "need.hunger") for s in SITS if 7.5 < s.scene.hour < 8.5 or 13 < s.scene.hour < 14)
        self.assertGreater(before - after, 1.5)

    def test_air_follows_the_season_and_the_walls(self):
        values = SAMPLER.pools.enum("PLACE", "air_felt")
        idx = lambda s: values.index(by_key(s)["@PLACE"].fields["air_felt"])  # noqa: E731
        out = lambda season: self.mean(idx(s) for s in SITS if s.scene.season == season and not s.scene.place.indoors)
        self.assertGreater(out("summer") - out("winter"), 1.5)
        winter = lambda indoors: self.mean(idx(s) for s in SITS if s.scene.season == "winter" and s.scene.place.indoors == indoors)
        self.assertGreater(winter(True), winter(False))
        self.assertGreater(len({idx(s) for s in SITS}), 3)

    def test_fear_and_anger_are_raised_by_a_blow_aimed_at_him(self):
        def state(sit):
            return by_key(sit)["me.state"].fields
        hit = [s for s in SITS if any(r.type == "EVENT" and r.fields["target"] == "me" and
                                      ACTIONS[r.fields["gesture"]].family == "force" for r in s.context.records)]
        rest = [s for s in SITS if s not in hit]
        self.assertGreater(len(hit), 15)
        for emo in ("emo.fear", "emo.anger"):
            self.assertGreater(self.mean(state(s)[emo] for s in hit) - self.mean(state(s)[emo] for s in rest), 1.5)

    def test_some_are_hurt_some_ill_a_few_bleed_and_some_beliefs_are_contradicted(self):
        sits = [by_key(s)["me"].fields for s in SITS]
        hurt = sum(f["body.pain"] > 2 for f in sits) / N
        bleed = sum(f["body.bleeding"] > 0 for f in sits) / N
        sick = sum(f["body.sickness"] > 2 for f in sits) / N
        self.assertTrue(0.04 < hurt < 0.20, hurt)
        self.assertTrue(0.002 < bleed < 0.05, bleed)
        self.assertTrue(0.02 < sick < 0.12, sick)
        self.assertTrue(any(r.fields["contradicted"] for s in SITS for r in s.context.records if r.type == "BELIEF"))
        self.assertTrue(any(f["body.consciousness"] < 8 for f in sits))

    def test_crowd_is_what_he_perceives_not_the_truth(self):
        differ = 0
        for sit in SITS:
            crowd = by_key(sit)["@PLACE"].fields["crowd"]
            self.assertLessEqual(crowd, len(sit.scene.present))
            differ += crowd != len(sit.scene.present)
        self.assertGreater(differ, 0.1 * N)

    def test_sources_and_enumerations_are_weighted(self):
        src = collections.Counter(r.fields["source"] for s in SITS for r in s.context.records if r.type == "BELIEF")
        self.assertGreater(src["seen"], src["dreamt"] * 5)
        self.assertGreater(len(src), 5)
        post = collections.Counter(by_key(s)["me"].fields["posture"] for s in SITS)
        self.assertLess(post["running"] / N, 0.06)


class TestBasics(unittest.TestCase):
    def test_deterministic_in_process(self):
        other = SituationSampler(seed=7)
        for i in (0, 5, 123, 1000):
            self.assertEqual(other.sample(i).encoded.digest(), SITS[i].encoded.digest())
        self.assertNotEqual(SituationSampler(seed=8).sample(0).encoded.digest(), SITS[0].encoded.digest())

    def test_deterministic_between_processes(self):
        code = ("import sys; sys.path.insert(0, %r)\nfrom situations.sampler import SituationSampler\n"
                "s = SituationSampler(seed=7)\nprint(','.join(str(s.sample(i).encoded.digest()) for i in (0, 5, 123)))" % str(AI))
        outs = []
        for hashseed in ("1", "2"):
            outs.append(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                                       env=dict(os.environ, PYTHONHASHSEED=hashseed)).stdout.strip())
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], ",".join(str(SITS[i].encoded.digest()) for i in (0, 5, 123)))

    def test_every_situation_fits_the_budget(self):
        for s in SITS:
            self.assertLessEqual(s.encoded.n, SAMPLER.tokenizer.layout.max_tokens)
            self.assertGreater(s.encoded.n, 5)

    def test_a_third_of_the_situations_are_long(self):
        types = SAMPLER.pools.interface.token_types
        full = 0
        for s in SITS:
            n = collections.Counter(r.type for r in s.context.records)
            near = [t for t, spec in types.items() if spec["count"] >= 6 and n[t] >= 0.7 * spec["count"]]
            full += len(near) >= 5
        self.assertTrue(0.2 < full / N < 0.45, full / N)
        self.assertGreater(max(s.encoded.n for s in SITS), 75)

    def test_the_situation_exposes_the_people_behind_its_keys(self):
        for sit in SITS[:400]:
            self.assertIsInstance(sit, Situation)
            self.assertIs(sit.people["me"], sit.scene.self_)
            for r in sit.context.records:
                if r.type == "ENTITY":
                    p = sit.people[r.key]
                    if r.fields.get("name"):
                        self.assertEqual(r.fields["name"], p.name)
            self.assertTrue(set(sit.context.known_keys) >= {k for k in sit.people if k != "me"})

    def test_every_situation_has_a_coherent_wake_token(self):
        causes = set()
        for s in SITS:
            recs = by_key(s)
            w = recs["wake"].fields
            causes.add(w["cause"])
            types = {r.type for r in s.context.records}
            if w["cause"] == "request":
                self.assertEqual(recs[w["trigger"]].type, "REQUEST")
            if "REQUEST" in types:
                self.assertEqual(w["cause"], "request")
            if w["cause"] == "perception":
                self.assertEqual(recs[w["trigger"]].type, "EVENT")
            if w["cause"] in ("body", "routine"):
                self.assertEqual(w["trigger"], "")
            else:
                self.assertIn(recs[w["trigger"]].type, ("REQUEST", "HEARD", "EVENT", "GOAL", "PLAN"))
            self.assertIn(w["mode"], ("act", "listen", "reflect"))
        self.assertGreaterEqual(len(causes), 5)

    def test_plans_have_a_target_and_a_next_gesture(self):
        plans = [r for s in SITS for r in s.context.records if r.type == "PLAN"]
        self.assertGreater(len(plans), 100)
        for p in plans:
            self.assertIn("target", p.fields)
            self.assertNotEqual(p.fields["next"], p.fields["step"])

    def test_some_deadlines_are_overdue_and_some_pointers_are_ghosts(self):
        deadlines = [r.fields["deadline"] for s in SITS for r in s.context.records if r.fields.get("deadline") is not None]
        self.assertTrue(any(d < 0 for d in deadlines) and any(d > 0 for d in deadlines))
        self.assertGreater(sum(1 for s in SITS if s.encoded.ghosts), N // 10)

    def test_known_empty_is_not_unknown(self):
        beliefs = [r for s in SITS for r in s.context.records if r.type == "BELIEF"]
        self.assertTrue(any(r.fields["informant"] == "" for r in beliefs))        # nobody told him: he saw it
        for s in SITS:                                                               # he always knows what he holds
            self.assertIsInstance(by_key(s)["me"].fields["held"], list)
        self.assertTrue(any(by_key(s)["me"].fields["held"] == [] for s in SITS))
        self.assertTrue(any(by_key(s)["me"].fields["held"] for s in SITS))

    def test_a_told_belief_names_who_told_him(self):
        for s in SITS[:500]:
            for r in s.context.records:
                if r.type == "BELIEF" and r.fields["source"] in ("told", "heard"):
                    self.assertTrue(r.fields["informant"])


if __name__ == "__main__":
    unittest.main()
