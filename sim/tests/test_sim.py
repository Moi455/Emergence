"""Tests of the village social simulation.  python3 -m unittest discover -s sim/tests"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path.insert(0, SIM)

from emergence_sim.core import Sim                      # noqa: E402
from emergence_sim.run import fingerprint                # noqa: E402
from emergence_sim import actions, social, decide       # noqa: E402
from emergence_sim.rules import romance_ok               # noqa: E402


def find_plan_contract():
    cands = [os.environ.get("EMERGENCE_AI", ""), os.path.join(SIM, "..", "ai", "npc_pipeline"),
             "/mnt/project-files/projet-unifie/emergence/ai/npc_pipeline"]
    for c in cands:
        if c and os.path.exists(os.path.join(c, "plan_contract.py")):
            sys.path.insert(0, c)
            import plan_contract
            return plan_contract
    return None


class Determinism(unittest.TestCase):
    def test_same_seed_same_world(self):
        a, b = Sim(seed=11), Sim(seed=11)
        a.run(12)
        b.run(12)
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertEqual([e["x"] for e in a.events], [e["x"] for e in b.events])

    def test_other_seed_other_world(self):
        a, b = Sim(seed=11), Sim(seed=12)
        a.run(3)
        b.run(3)
        self.assertNotEqual(fingerprint(a), fingerprint(b))

    def test_export_does_not_change_the_sim(self):
        with tempfile.TemporaryDirectory() as d:
            a = Sim(seed=5)
            b = Sim(seed=5, traj_ppm=200000, traj_path=os.path.join(d, "t.jsonl"))
            a.run(8)
            b.run(8)
            b.traj_f.close()
            self.assertEqual(fingerprint(a), fingerprint(b))
            with open(os.path.join(d, "t.jsonl"), encoding="utf-8") as f:
                rows = [json.loads(x) for x in f]
            self.assertGreater(len(rows), 100)
            for r in rows[:200]:
                for k in ("schema_version", "seed", "tick", "npc", "request", "state", "candidates", "scores", "chosen", "plan", "result"):
                    self.assertIn(k, r)
                self.assertIn(r["chosen"], [c["id"] for c in r["candidates"]])
                self.assertLessEqual(len(r["candidates"]), 16)
                self.assertIn(r["result"]["status"], ("done", "failed", "interrupted"))


class Contract(unittest.TestCase):
    def test_every_plan_validates(self):
        pc = find_plan_contract()
        if pc is None:
            self.skipTest("ai/npc_pipeline/plan_contract.py not found (set EMERGENCE_AI)")
        sim = Sim(seed=3)
        seen = {}
        orig = actions.execute

        def spy(s, n, c):
            plan, hours, out = orig(s, n, c)
            errs = pc.validate_plan(plan)
            if errs:
                seen.setdefault(c.key, (errs, plan))
            return plan, hours, out
        decide.actions.execute = spy
        try:
            sim.run(20)
        finally:
            decide.actions.execute = orig
        self.assertEqual(seen, {}, f"invalid plans: {seen}")


class HardRules(unittest.TestCase):
    def test_no_romance_with_minors_or_kin(self):
        sim = Sim(seed=21)
        bad = []
        o_flirt, o_prop = social.ACTS["flirt"], social.ACTS["propose"]

        def guard(fn):
            def w(s, a, b, *rest):
                if s.age(a) < s.ADULT or s.age(b) < s.ADULT or s.is_kin(a, b):
                    bad.append((a.id, b.id, s.age(a), s.age(b)))
                return fn(s, a, b, *rest)
            return w
        social.ACTS["flirt"], social.ACTS["propose"] = guard(o_flirt), guard(o_prop)
        try:
            sim.run(40)
        finally:
            social.ACTS["flirt"], social.ACTS["propose"] = o_flirt, o_prop
        # interact() may pick flirt only when romance_ok holds; _flirt re-checks. Any attempt reaching here is a bug.
        self.assertEqual(bad, [])
        for n in sim.npcs:
            for o in [n.engaged, n.affair] + ([n.partners[-1]] if sim.day > 0 and n.partners and n.partners[-1] != n.partner else []):
                if o is None:
                    continue
                m = sim.npcs[o]
                self.assertFalse(sim.is_kin(n, m), (n.name, m.name))

    def test_romance_ok_refuses_teens(self):
        sim = Sim(seed=2)
        teens = [n for n in sim.npcs if 14 <= sim.age(n) < 18]
        adults = [n for n in sim.npcs if sim.age(n) >= 18]
        self.assertTrue(teens and adults)
        for t in teens[:20]:
            for a in adults[:50]:
                self.assertFalse(romance_ok(sim, t, a))
                self.assertFalse(romance_ok(sim, a, t))


class Society(unittest.TestCase):
    def test_craft_loss_is_detected(self):
        sim = Sim(seed=4)
        sim.run(7)
        holders = [n for n in sim.npcs if n.alive and n.skills.get("writing", 0) >= 20]
        self.assertTrue(holders)
        for n in holders:
            sim.die(n, "illness")
        sim.t = (sim.day // 7 + 1) * 7 * 24
        sim.crafts_daily()
        self.assertIn("writing", sim.lost_world)
        self.assertTrue(any(e["k"] == "craft_lost" and e["d"]["craft"] == "writing" for e in sim.events))

    def test_a_season_of_village_life(self):
        sim = Sim(seed=9)
        sim.run(90)
        alive = sum(1 for n in sim.npcs if n.alive)
        self.assertGreater(alive, 380, "population collapsed")
        kinds = {e["k"] for e in sim.events}
        for k in ("apprenticeship", "wedding", "birth", "death"):
            self.assertIn(k, kinds)
        self.assertGreater(sim.interactions, 10000)
        changed = sum(1 for n in sim.npcs if n.outfit_changes > 0)
        self.assertGreater(changed, 300)


def have_torch():
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


class BrainSocket(unittest.TestCase):
    """The loop that hosts the Transformer: engine options, live tokens, batched brain, bounded deltas."""

    def test_options_respect_hard_rules(self):
        from emergence_sim import options
        sim = Sim(seed=3)
        sim.run(5)
        for n in sim.npcs:
            if not n.alive:
                continue
            o = options.feasible(sim, n)
            self.assertLessEqual(len(o), 16)
            self.assertTrue(any(c.key == "sleep" for c in o))
            for c in o:
                if c.key == "court":
                    self.assertTrue(romance_ok(sim, n, sim.npcs[c.target]))
                    self.assertGreaterEqual(sim.age(n), 18)

    def test_live_tokens(self):
        if find_plan_contract() is None:
            self.skipTest("ai/npc_pipeline not found (set EMERGENCE_AI)")
        from emergence_sim import options, live
        sim = Sim(seed=3)
        sim.run(5)
        enc, gs, sa, V = live.ai()
        for n in sim.npcs:
            if not n.alive:
                continue
            o = options.feasible(sim, n)
            tk = live.tokens(sim, n, o)
            self.assertEqual(tk["n_cands"], len(o))
            self.assertLessEqual(len(tk["cat"]), enc.MAX_TOKENS)
            for row in tk["cat"]:
                self.assertNotIn(1, row[1:6], "a value outside the model vocabulary")
            rec = live.record(sim, n, o)
            for e in rec["state"]["entities"]:
                if e["age_cat"] in ("child", "teen") or sim.age(n) < 18:
                    self.assertEqual(e["rel"]["romance"], 0)

    def test_transformer_brain_is_deterministic_and_valid(self):
        if not have_torch() or find_plan_contract() is None:
            self.skipTest("torch or ai/ not available")
        from emergence_sim.brain import TransformerBrain
        pc = find_plan_contract()
        a = Sim(seed=3, brain=TransformerBrain(seed=1))
        b = Sim(seed=3, brain=TransformerBrain(seed=1))
        a.run(1)
        b.run(1)
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertGreater(a.decisions, 400)
        self.assertGreater(a.brain.stats()["max_batch"], 400)            # the whole village in one forward pass
        for n in a.npcs:
            if n.alive and n.plan and n.plan.get("steps"):
                self.assertFalse(pc.validate_plan(n.plan), n.plan)

    def test_governor_bounds(self):
        from emergence_sim.brain import Governor
        sim = Sim(seed=3)
        g = Governor()
        adult = next(n for n in sim.npcs if n.alive and sim.age(n) >= 30 and n.rel)
        o = sorted(adult.rel)[0]
        a0, h0, c0 = adult.rel[o][0], adult.hunger, adult.tr["courage"]
        g.apply(sim, adult, {"state.anger": 60, f"rel.E{o}.affection": 40, "state.hunger": -50, "trait.courage": 9})
        self.assertEqual(adult.anger, min(100, 60))                      # an emotion may jump
        self.assertEqual(adult.rel[o][0], max(-100, min(100, a0 + 5)))   # a relation moves by 5 at most
        self.assertEqual(adult.hunger, h0)                               # the body is the engine's
        self.assertEqual(adult.tr["courage"], min(100, c0 + 1))          # a trait moves by 1 per day at most
        g.apply(sim, adult, {"trait.courage": 1})
        self.assertEqual(adult.tr["courage"], min(100, c0 + 1))
        child = next(n for n in sim.npcs if n.alive and sim.age(n) < 12 and n.rel)
        k = sorted(child.rel)[0]
        r0 = child.rel[k][3]
        g.apply(sim, child, {f"rel.E{k}.romance": 5})
        self.assertEqual(child.rel[k][3], r0)                             # hard rule, whatever the model says


if __name__ == "__main__":
    unittest.main()
