"""Round 3 of the sampler: ghosts only on overflow, the dead, who is carried, who can act and speak, a body only for
bodies, and the plausibility of scenes, inventories, norms and feelings. Measured on the 2200 situations of
test_situations."""
from __future__ import annotations

import collections

import language
import re
import statistics
import unittest

from .test_plausibility import HOLDING, POOLS, events, position
from .test_situations import (ACTIONS, ADULT, N, PARSER, SAMPLER, SITS, D10Audit, D10Violation, Record, by_key, nodes,
                              props)

KEY = re.compile(r"@[ETLG]\d+")
CAP = SAMPLER.pools.interface.token_types["ENTITY"]["count"]
FIT = ("active", "hurt")
ZONE_VALUES = {"head", "torso", "arms", "legs", "shoulder", "back", "hands", "hand", "arm", "collar", "hair"}
MOBILE = {"go", "climb", "jump", "swim", "mount"}
NEEDS = ("need.hunger", "need.thirst", "need.sleep", "need.exhaustion", "body.pain")


def _dead_nodes(node):
    """`(dead X)` said as a fact; not one that somebody only means to bring about (intends, wants)."""
    if isinstance(node, language.Node):
        if node.head in ("intends", "wants"):
            return
        if node.head == "dead":
            yield node
        for a in node.args:
            yield from _dead_nodes(a)


def dead_of(sit):
    return {m.args[0] for _, root in props(sit, ("BELIEF", "HEARD", "MEMORY")) for m in _dead_nodes(root)}


def zone_params(g):
    return {p.name for p in ACTIONS[g].params if SAMPLER.grammar.chooser.is_zone(p)}


class TestGhostsAndTheDead(unittest.TestCase):
    def test_ghosts_exist_only_when_the_entity_budget_overflows(self):
        with_ghosts = 0
        for sit in SITS:
            ghosts = [k for k in sit.people if k.startswith("@E") and k not in by_key(sit)]
            if ghosts:
                with_ghosts += 1
                self.assertEqual(sum(r.type == "ENTITY" for r in sit.context.records), CAP, "ghosts without an overflow")
        self.assertTrue(0.05 < with_ghosts / N < 0.45, with_ghosts / N)

    def test_the_people_he_talks_about_have_files(self):
        cited = ghosts = 0
        for sit in SITS:
            recs = by_key(sit)
            for rec, _ in props(sit):
                for k in KEY.findall(rec.fields["prop"]):
                    if k.startswith("@E"):
                        cited += 1
                        ghosts += k not in recs
            for r in sit.context.records:
                if r.type == "PLAN":
                    self.assertTrue(r.fields["target"] in recs or not r.fields["target"].startswith("@E"))
        self.assertLess(ghosts / cited, 0.1)

    def test_death_is_rare_except_in_a_situation_about_a_loss(self):
        plain = [s for s in SITS if s.structure != "loss"]
        n = sum(1 for s in plain if dead_of(s))
        self.assertTrue(0.01 < n / len(plain) <= 0.035, n / len(plain))
        loss = [s for s in SITS if s.structure == "loss"]
        self.assertGreater(sum(1 for s in loss if dead_of(s)) / len(loss), 0.5)

    def test_the_dead_inform_nobody_owe_nothing_own_nothing_and_are_not_planned_for(self):
        for sit in SITS:
            dead = dead_of(sit)
            if not dead:
                continue
            recs = by_key(sit)
            for k in dead:
                self.assertFalse(recs[k].fields["present"])
                self.assertNotIn(recs[k].fields["link"], POOLS.intimate_links)            # not a spouse
            for r in sit.context.records:
                f = r.fields
                if r.type in ("BELIEF", "HEARD"):
                    self.assertNotIn(f["informant"], dead)
                    self.assertFalse(dead & set(f.get("shared") or []))
                    if "(dead" not in f["prop"]:
                        self.assertFalse(dead & set(KEY.findall(f["prop"])), f["prop"])    # nothing is told of him as alive
                if r.type == "COMMIT":
                    self.assertNotIn(f["counterparty"], dead)
                    self.assertFalse(dead & set(f["witnesses"]))
                if r.type in ("THING", "INV", "LOCUS"):
                    self.assertNotIn(f.get("owner"), dead)
                if r.type == "PLAN":
                    self.assertNotIn(f["target"], dead)
                if r.type in ("GOAL", "REQUEST"):
                    self.assertFalse(dead & set(KEY.findall(f["prop"])))


class TestWhoCanActAndWhatTheyDo(unittest.TestCase):
    def test_take_and_put_are_never_done_to_a_person_unless_he_is_carried(self):
        n = 0
        for sit in SITS:
            recs = by_key(sit)
            for r, _, _ in events(sit):
                f = r.fields
                if f["gesture"] in ("take", "put") and (f["target"] == "me" or f["target"].startswith("@E")):
                    n += 1
                    if f["target"] == "me":
                        ok = sit.scene.self_.age < 3 or recs["me"].fields["body.pain"] > 6
                    else:
                        ok = sit.people[f["target"]].age < 3 or recs[f["target"]].fields["look.condition"] in ("hurt", "down")
                    self.assertTrue(ok, (f["gesture"], f["target"]))
        self.assertLess(n, 0.04 * N)
        for sit in SITS:                                               # nor in what he remembers or has heard
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head == "did" and len(m.args) > 2 and m.args[1] in ("take", "put") and isinstance(m.args[2], str):
                        who = sit.people.get(m.args[2])
                        self.assertTrue(m.args[2].startswith("@T") or (who is not None and who.age < 3) or m.args[2] == "me", rec.fields["prop"])

    def test_deeds_of_memories_bear_on_objects_too(self):
        on_things = deeds = 0
        for sit in SITS:
            for rec, root in props(sit, ("MEMORY",)):
                for m in nodes(root):
                    if m.head == "did" and len(m.args) > 2 and m.args[1] != "give" and isinstance(m.args[2], str):
                        deeds += 1
                        on_things += m.args[2].startswith("@T")
        self.assertGreater(on_things / deeds, 0.5)

    def test_giving_is_not_everything_and_people_eat_and_drink(self):
        g = collections.Counter(r.fields["gesture"] for s in SITS for r in s.context.records if r.type == "EVENT")
        total = sum(g.values())
        self.assertLessEqual(g["give"] / total, 0.15)
        self.assertGreater(g["eat"] / total, 0.01)
        self.assertGreater(g["drink"] / total, 0.01)
        mem = collections.Counter(m.args[1] for s in SITS for _, root in props(s, ("MEMORY",)) for m in nodes(root)
                                  if m.head == "did" and len(m.args) > 2)
        self.assertLessEqual(mem["give"] / sum(mem.values()), 0.15)

    def test_only_fit_actors_in_a_posture_that_allows_the_gesture(self):
        for sit in SITS:
            recs = by_key(sit)
            for r, _, _ in events(sit):
                a, g = recs[r.fields["actor"]].fields, r.fields["gesture"]
                self.assertIn(a["look.condition"], FIT)
                if a["look.posture"] in ("lying", "prone"):
                    self.assertIn(g, ("look", "listen", "rest", "sleep", "set_posture", "eat", "drink", "wait", "stop", "speak"))
                if a["look.posture"] in ("sitting", "kneeling"):
                    self.assertNotIn(g, MOBILE)

    def test_who_speaks_or_asks_is_fit_and_within_earshot(self):
        n = 0
        for sit in SITS:
            recs = by_key(sit)
            for r in sit.context.records:
                who = r.fields.get("informant") if r.type == "HEARD" else r.fields.get("from") if r.type == "REQUEST" else \
                    r.fields["actor"] if r.type == "EVENT" and r.fields["gesture"] == "speak" else None
                if who:
                    n += 1
                    self.assertIn(recs[who].fields["look.condition"], FIT)
                    self.assertLessEqual(recs[who].fields["dist"], 10.0)
                    self.assertNotIn(recs[who].fields["look.posture"], ("lying", "prone"))
        self.assertGreater(n, 400)

    def test_somebody_speaks_within_sight_now_and_then(self):
        g = collections.Counter(r.fields["gesture"] for s in SITS for r in s.context.records if r.type == "EVENT")
        self.assertTrue(0.01 < g["speak"] / sum(g.values()) < 0.08)

    def test_a_gift_names_the_receiver_and_work_and_tying_name_the_tool(self):
        gifts = tools = 0
        for sit in SITS:
            for r in sit.context.records:
                if r.type == "EVENT" and r.fields["gesture"] == "give":
                    gifts += 1
                    self.assertTrue(r.fields.get("from_to"))
                    self.assertNotEqual(r.fields["from_to"], r.fields["actor"])
                if r.type == "EVENT" and r.fields["gesture"] in ("work", "tie"):
                    tools += 1
                    self.assertTrue(r.fields.get("with"))
        self.assertGreater(gifts, 30)
        self.assertGreater(tools, 30)

    def test_a_part_of_the_body_is_named_only_for_a_body(self):
        n = 0
        for sit in SITS:
            recs = by_key(sit)
            for r, _, _ in events(sit):
                f = r.fields
                if f["target"].startswith("@T") and recs[f["target"]].fields["kind"] in POOLS.cat["species"]:
                    continue
                if f["target"].startswith("@T"):
                    zones = zone_params(f["gesture"])
                    for m in f["manner"]:
                        owners = [p.name for p in ACTIONS[f["gesture"]].params if p.type == "enum" and m in p.values]
                        n += 1
                        self.assertFalse(owners and all(o in zones for o in owners), (f["gesture"], m))
        self.assertGreater(n, 100)
        for sit in SITS[:1000]:                                     # nor in what he is told
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head == "did" and len(m.args) > 3 and isinstance(m.args[2], str) and m.args[2].startswith("@T") \
                            and m.args[1] in ACTIONS:
                        for h in m.args[3:]:
                            if hasattr(h, "head") and h.head == "how":
                                owners = [p.name for p in ACTIONS[m.args[1]].params if p.type == "enum" and h.args[0] in p.values]
                                kind = next((r.fields["kind"] for r in sit.context.records if r.key == m.args[2]), None)
                                if kind in POOLS.category_of:
                                    self.assertFalse(owners and all(o in zone_params(m.args[1]) for o in owners), rec.fields["prop"])


class TestBeliefsAndWake(unittest.TestCase):
    def test_nobody_present_is_believed_at_the_place(self):
        for sit in SITS:
            recs = by_key(sit)
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head == "at" and m.args[1] == "@PLACE":
                        self.assertFalse(recs.get(m.args[0]) is not None and recs[m.args[0]].fields.get("present"), rec.fields["prop"])

    def test_who_owns_what_comes_from_the_owner_he_believes_or_is_contradicted(self):
        n = contradicted = 0
        for sit in SITS:
            recs = by_key(sit)
            for rec, root in props(sit, ("BELIEF",)):
                for m in nodes(root):
                    if m.head == "owns" and m.args[1] in recs and recs[m.args[1]].type in ("THING", "INV"):
                        n += 1
                        believed = recs[m.args[1]].fields.get("owner")
                        if believed != m.args[0]:
                            contradicted += 1
                            self.assertTrue(rec.fields["contradicted"], rec.fields["prop"])
        self.assertGreater(n, 200)
        self.assertGreater(contradicted, 5)

    def test_triggers_that_do_not_wake_him_are_there_too(self):
        pending = sum(1 for s in SITS if any(r.type == "REQUEST" for r in s.context.records) and by_key(s)["wake"].fields["cause"] != "request")
        self.assertTrue(0.03 < pending / N < 0.2, pending / N)
        body = [by_key(s)["me"].fields for s in SITS if by_key(s)["wake"].fields["cause"] == "body"]
        two = sum(sum(f[k] >= 7.4 for k in NEEDS) >= 2 for f in body)
        self.assertGreater(two / len(body), 0.1)
        other = [by_key(s)["me"].fields for s in SITS if by_key(s)["wake"].fields["cause"] != "body"]
        busy = sum(max(f[k] for k in NEEDS) >= 7.4 for f in other)
        self.assertTrue(0.03 < busy / len(other) < 0.2, busy / len(other))

    def test_urgency_follows_the_content(self):
        by = collections.defaultdict(list)
        body = []
        for sit in SITS:
            recs = by_key(sit)
            w = recs["wake"].fields
            if w["cause"] == "perception":
                t = recs[w["trigger"]].fields
                blow = ACTIONS[t["gesture"]].family == "force" and t["target"] == "me"
                by["blow" if blow else "glance" if t["gesture"] in ("look", "go", "listen") else "other"].append(w["urgency"])
            if w["cause"] == "body":
                body.append((max(recs["me"].fields[k] for k in NEEDS), w["urgency"]))
        self.assertGreater(len(by["blow"]), 5)
        self.assertGreater(statistics.mean(by["blow"]), statistics.mean(by["glance"]) + 3)
        self.assertGreater(statistics.correlation([a for a, _ in body], [b for _, b in body]), 0.5)

    def test_need_goals_follow_the_level_of_the_need(self):
        levels, all_levels = [], []
        for sit in SITS:
            b = by_key(sit)["me"].fields
            lv = {"hunger": b["need.hunger"], "thirst": b["need.thirst"], "exhaustion": max(b["need.exhaustion"], b["need.sleep"] - 2),
                  "pain": b["body.pain"]}
            all_levels += list(lv.values())
            for rec, root in props(sit, ("GOAL",)):
                if root.head == "state" and root.args[0] == "me" and root.args[1] in lv:
                    levels.append(lv[root.args[1]])
        self.assertGreater(len(levels), 100)
        self.assertGreater(statistics.mean(levels), statistics.mean(all_levels) + 1.5)

    def test_the_origin_of_a_goal_is_a_record_that_shares_a_pointer_with_it(self):
        n = 0
        for sit in SITS:
            recs = by_key(sit)
            for r in sit.context.records:
                ref = r.fields.get("origin_ref") if r.type == "GOAL" else None
                if ref and recs[ref].type in ("BELIEF", "MEMORY"):
                    n += 1
                    self.assertTrue(set(KEY.findall(r.fields["prop"])) & set(KEY.findall(recs[ref].fields["prop"])))
        self.assertGreater(n, 100)

    def test_a_plan_is_for_an_active_goal_and_a_target_that_is_here_or_known(self):
        n = 0
        for sit in SITS:
            recs = by_key(sit)
            for r in sit.context.records:
                if r.type != "PLAN":
                    continue
                n += 1
                goal = recs[r.fields["goal"]].fields["status"]
                self.assertIn(goal, ("active", "paused"))
                if goal == "paused":                                     # a paused goal: a suspended plan
                    self.assertEqual(r.fields["status"], "suspended")
                t = r.fields["target"]
                if t.startswith("@E"):
                    self.assertTrue(t in recs and recs[t].fields["present"], t)
                if t.startswith("@L"):
                    self.assertIn(t, recs)
        self.assertGreater(n, 150)

    def test_a_norm_makes_sense_a_price_follows_the_object_and_what_is_heard_is_plausible(self):
        norms = {"forbidden": ("strike", "push", "grab", "take", "throw"), "shameful": ("strike", "push", "take", "throw"),
                 "obligatory": ("give", "work", "pour", "scoop"), "admirable": ("give", "work", "scoop", "tie"),
                 "permitted": ("eat", "drink", "sleep", "rest", "wear", "go", "take")}
        n = 0
        worth = collections.defaultdict(list)
        for sit in SITS:
            for rec, root in props(sit):
                for m in nodes(root):
                    if m.head == "norm":
                        n += 1
                        self.assertIn(m.args[1].args[1], norms[m.args[0]], rec.fields["prop"])
                    if m.head == "worth":
                        worth[m.args[0]].append(int(m.args[1]))
        self.assertGreater(n, 100)
        self.assertGreater(statistics.median(worth["silver_coin"]), 3 * statistics.median(worth["copper_coin"]))
        heads = collections.Counter(PARSER.parse(r.fields["prop"]).head for s in SITS for r in s.context.records if r.type == "HEARD")
        self.assertTrue(set(heads) <= {"has", "lives_at", "works_as", "worth", "at", "quality", "past", "dead", "owns"}, heads)
        self.assertGreater(sum(heads.values()), 100)

    def test_he_is_never_told_what_he_carries(self):
        n = 0
        for sit in SITS:
            for rec in sit.context.records:
                if rec.type == "BELIEF":
                    m = re.match(r"\(has me ([^\s:)]+)", rec.fields["prop"])
                    if m and m.group(1) in sit.scene.carried:
                        n += 1
                        self.assertEqual(rec.fields["source"], "seen")
        self.assertGreater(n, 5)


class TestAgesAndScenes(unittest.TestCase):
    def test_a_baby_is_neither_asked_nor_told_nor_given_adult_tools(self):
        babies = [s for s in SITS if s.scene.self_.age < 3]
        self.assertGreater(len(babies), 40)
        for sit in babies:
            types = {r.type for r in sit.context.records}
            self.assertFalse(types & {"REQUEST", "HEARD", "COMMIT", "SKILL"})
            for r in sit.context.records:
                if r.type == "INV":
                    self.assertEqual(POOLS.category_of[r.fields["kind"]], "toy")
                if r.type == "GOAL":
                    self.assertNotIn("works_as", r.fields["prop"])
            for rec, root in props(sit):
                self.assertNotIn(root.head, ("norm", "worth"))

    def test_a_child_under_8_is_never_without_a_grown_up_nearby(self):
        kids = [s for s in SITS if s.scene.self_.age < 8]
        self.assertGreater(len(kids), 100)
        for sit in kids:
            self.assertTrue(any(x.person.age >= ADULT and x.known and x.dist < 15 for x in sit.scene.present))
            self.assertTrue(any(r.type == "ENTITY" and r.fields["present"] and sit.people[r.key].age >= ADULT for r in sit.context.records))

    def test_no_child_alone_at_the_tavern_at_night(self):
        for sit in SITS:
            sc = sit.scene
            if sc.place.name == "tavern" and (sc.hour >= 20 or sc.hour < 6):
                self.assertGreaterEqual(sc.self_.age, 14)

    def test_no_arms_under_twelve(self):
        n = 0
        for sit in SITS:
            if sit.scene.self_.age < 12:
                n += 1
                kinds = {r.fields["kind"] for r in sit.context.records if r.type in ("INV", "THING")} | set(sit.scene.carried)
                self.assertFalse({k for k in kinds if POOLS.category_of.get(k) in POOLS.weapon_categories}, kinds)
                for rec, root in props(sit):
                    for m in nodes(root):
                        for a in m.args:
                            if isinstance(a, str):
                                self.assertNotIn(POOLS.category_of.get(a.partition(":")[0]), POOLS.weapon_categories)
        self.assertGreater(n, 250)

    def test_the_share_of_strangers_depends_on_the_place(self):
        share = collections.defaultdict(lambda: [0, 0])
        aff = []
        for sit in SITS:
            for x in sit.scene.present:
                share[sit.scene.place.name][0] += x.link == "stranger"
                share[sit.scene.place.name][1] += 1
            for r in sit.context.records:
                if r.type == "ENTITY" and r.fields["present"] and r.fields["link"] == "stranger" and r.fields["id_certainty"] < 4:
                    aff.append(r.fields["rel.affection"])
        rate = {k: a / b for k, (a, b) in share.items()}
        self.assertLess(rate["home"], 0.12)
        self.assertGreater(rate["market"], 0.55)
        self.assertGreater(rate["market"], 4 * rate["home"])
        self.assertLess(statistics.pstdev(aff), 2.2)                 # a stranger inspires nothing much

    def test_the_family_is_drawn_consistently(self):
        pairs = collections.Counter()
        for sit in SITS:
            ages = collections.defaultdict(list)
            for x in sit.scene.present:
                ages[x.link].append(x.person.age)
            for p, l in sit.scene.absent:
                ages[l].append(p.age)
            for gp in ages["grandparent"]:
                for pa in ages["parent"]:
                    pairs["gp"] += 1
                    self.assertTrue(15.9 <= gp - pa <= 45.1, (gp, pa))
            for au in ages["aunt_uncle"]:
                for pa in ages["parent"]:
                    pairs["au"] += 1
                    self.assertLessEqual(abs(au - pa), 15.1)
            for sib in ages["sibling"]:
                for pa in ages["parent"]:
                    pairs["sib"] += 1
                    self.assertGreaterEqual(pa - sib, 15.9)
            for gc in ages["grandchild"]:
                for ch in ages["child"]:
                    pairs["gc"] += 1
                    self.assertTrue(15.9 <= ch - gc <= 45.1)
        self.assertGreater(pairs["gp"], 30)
        self.assertGreater(pairs["sib"], 30)

    def test_objects_are_drawn_per_item_not_per_category(self):
        kinds = collections.Counter(r.fields["kind"] for s in SITS for r in s.context.records if r.type == "THING" and "display" not in r.fields)
        total = sum(kinds.values())
        self.assertLess(kinds.most_common(1)[0][1] / total, 0.03)          # one item per category used to be 8 %
        self.assertGreater(len(kinds), 220)

    def test_an_inventory_has_each_kind_once_and_no_boats_on_land(self):
        for sit in SITS:
            kinds = [r.fields["kind"] for r in sit.context.records if r.type == "INV"]
            self.assertEqual(len(kinds), len(set(kinds)))
            for r in sit.context.records:
                if r.type in ("THING", "INV"):
                    self.assertNotIn(r.fields["kind"], POOLS.water_kinds)

    def test_what_he_carries_follows_his_trade_and_his_place(self):
        from situations.scene import OCC_CARRY, PLACE_CARRY
        own = other = n_own = n_other = 0
        for sit in SITS:
            me = sit.scene.self_
            if me.age < 18 or not me.occupation or me.occupation not in OCC_CARRY:
                continue
            special = set(OCC_CARRY[me.occupation]) - {"currency", "carry", "bread"}
            for r in sit.context.records:
                if r.type == "INV":
                    cat = POOLS.category_of[r.fields["kind"]]
                    allowed = set(OCC_CARRY[me.occupation]) | set(PLACE_CARRY.get(sit.scene.place.name, ())) | {"currency", "carry", "bread", "blade"}
                    self.assertIn(cat, allowed, (me.occupation, sit.scene.place.name, cat))
                    own += cat in special
                    n_own += 1
        self.assertGreater(n_own, 100)
        self.assertGreater(own / n_own, 0.2)

    def test_a_quantity_fits_the_kind(self):
        stacks = ("currency", "bread", "produce", "meat", "grain", "seed", "ammo", "raw_wood", "raw_stone", "raw_mineral", "building",
                  "fiber", "metal_stock", "preserve", "animal_product", "raw_animal", "fire", "dish", "drink")
        seen = collections.Counter()
        for sit in SITS:
            for r in sit.context.records:
                if r.type in ("THING", "INV") and "amount" in r.fields:
                    stack = POOLS.category_of[r.fields["kind"]] in stacks
                    seen[stack, r.fields["amount"]] += 1
                    if not stack:
                        self.assertIn(r.fields["amount"], ("few", "some", "unknown"))
        self.assertGreater(seen[True, "many"], 100)

    def test_the_tavern_is_quieter_at_night_and_baby_faces_are_not_floored(self):
        night = day = 0
        for sit in SITS:
            if sit.scene.place.name == "tavern":
                if sit.scene.hour >= 21.5 or sit.scene.hour < 5.5:
                    night += 1
                else:
                    day += 1
        self.assertLess(night / (night + day), 0.3)                         # the night is a third of the day
        seen = [r.fields["look.age"] for s in SITS for r in s.context.records
                if r.type == "ENTITY" and r.fields["present"] and s.people[r.key].age < 0.5]
        self.assertTrue(seen and min(seen) < 0.5)

    def test_faces_follow_the_events(self):
        angry = n = 0
        for sit in SITS:
            recs = by_key(sit)
            for r, _, _ in events(sit):
                if ACTIONS[r.fields["gesture"]].family == "force":
                    n += 1
                    angry += recs[r.fields["actor"]].fields["look.expression"] in ("anger", "contempt")
        self.assertGreater(n, 40)
        self.assertGreater(angry / n, 0.5)

    def test_no_drive_for_intimacy_when_no_adult_is_present(self):
        n = 0
        for sit in SITS:
            st = by_key(sit)["me.state"].fields
            if "drive.intimacy" in st and not any(x.person.age >= ADULT for x in sit.scene.present):
                n += 1
                self.assertLessEqual(st["drive.intimacy"], 2.0)
        self.assertGreater(n, 5)

    def test_some_absent_relatives_come_with_a_believed_age(self):
        seen = believed = 0
        for sit in SITS:
            recs = by_key(sit)
            ages = {m.args[0] for _, root in props(sit, ("BELIEF",)) for m in nodes(root) if m.head == "state" and m.args[1] == "age_years"}
            for r in recs.values():
                if r.type == "ENTITY" and not r.fields["present"] and r.fields["known_by"] == "seen":
                    seen += 1
                    believed += r.key in ages
        self.assertGreater(believed / seen, 0.2)


class TestAudit(unittest.TestCase):
    def test_the_audit_refuses_a_file_whose_name_is_not_the_persons(self):
        sit = next(s for s in SITS if any(r.type == "ENTITY" and r.fields.get("name") for r in s.context.records))
        recs = [Record(r.type, r.key, dict(r.fields)) for r in sit.context.records]
        D10Audit(SAMPLER.pools).check(sit.scene.self_, recs, sit.people)
        next(r for r in recs if r.type == "ENTITY" and r.fields.get("name")).fields["name"] = "n:99999"
        with self.assertRaises(D10Violation):
            D10Audit(SAMPLER.pools).check(sit.scene.self_, recs, sit.people)


if __name__ == "__main__":
    unittest.main()
