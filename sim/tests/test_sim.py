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


if __name__ == "__main__":
    unittest.main()
