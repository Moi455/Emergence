"""T05: the law of forgetting is data (data/forgetting.toml), never reads the truth, and the oracle is what C++ must match."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import forgetting  # noqa: E402
import gen_cpp  # noqa: E402


class ForgettingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()

    def with_term(self, record, term):
        """A catalogue whose law of `record` has one more score term."""
        cat = Catalogue.load()
        cat["forgetting"][record].score = cat["forgetting"][record].score + [term]
        return cat

    def test_twelve_laws_one_per_record(self):
        self.assertEqual(len(self.cat["forgetting"]), 12)
        self.assertEqual(sorted(self.cat["forgetting"]), sorted(forgetting.record_components(self.cat)))
        self.assertEqual(forgetting.ForgettingChecker(self.cat).problems(), [])

    def test_truth_is_refused_in_a_score(self):
        for record, var in (("belief", "b_truth"), ("belief", "b_origin_fact"), ("episode", "m_fact_ref"),
                            ("relation", "r_true_entity")):
            cat = self.with_term(record, {"var": var, "weight": 1})
            problems = forgetting.ForgettingChecker(cat).problems()
            self.assertTrue(any(var in p and "truth" in p for p in problems), (var, problems))

    def test_truth_is_refused_in_protect(self):
        cat = Catalogue.load()
        cat["forgetting"]["belief"].protect = ["b_truth"]
        self.assertTrue(any("b_truth" in p for p in forgetting.ForgettingChecker(cat).problems()))

    def test_other_malformed_laws(self):
        cases = [("belief", {"var": "b_proposition", "weight": 1}),               # not a number
                 ("belief", {"var": "m_importance", "weight": 1}),                # another record's variable
                 ("belief", {"var": "b_acquired", "weight": 1}),                  # a time read as a value
                 ("belief", {"var": "b_weight", "weight": 1, "kind": "recency", "half_life_seasons": 2}),
                 ("belief", {"var": "b_secret", "weight": 0}),
                 ("episode", {"var": "m_when", "weight": 1, "kind": "recency"})]  # no half-life
        for record, term in cases:
            cat = self.with_term(record, term)
            self.assertTrue(forgetting.ForgettingChecker(cat).problems(), term)

    def test_missing_law_is_refused(self):
        cat = Catalogue.load()
        del cat["forgetting"]["locus"]
        self.assertTrue(any("locus" in p for p in forgetting.ForgettingChecker(cat).problems()))

    def test_recency_halves_every_half_life(self):
        h = 4 * forgetting.SEASON_SECONDS
        self.assertEqual([forgetting.recency(a, h) for a in (-5, 0, h, 2 * h, 10 * h)], [100, 100, 50, 25, 0])
        self.assertEqual(forgetting.recency(h // 2, h), 75)

    def test_score_and_victim(self):
        oracle = forgetting.ForgettingOracle(self.cat)
        now = forgetting.PARITY_NOW
        self.assertEqual(oracle.score("episode", {"m_importance": 10, "m_vividness": 5, "m_rehearsals": 50, "m_when": now}, now),
                         40 * 10 + 20 * 5 + 100 * 10 + 30 * 100)          # rehearsals capped at 10
        entries = [(1, {"m_importance": 5, "m_when": now}), (2, {"m_importance": 5, "m_when": now}),
                   (3, {"m_importance": 0, "m_when": now, "m_defining": 1}), (4, {"m_importance": 9, "m_when": now})]
        self.assertEqual(oracle.victim("episode", entries, now), 1)          # tie: the oldest; the defining one is spared
        # a store whose records are ALL protected still gives a victim: the worst of them, a tie the oldest (never a refusal)
        self.assertEqual(oracle.victim("episode", [(7, {"m_defining": 1, "m_importance": 5, "m_when": now}),
                                                   (8, {"m_defining": 1, "m_importance": 2, "m_when": now}),
                                                   (9, {"m_defining": 1, "m_importance": 2, "m_when": now})], now), 8)
        self.assertIsNone(oracle.victim("episode", [], now))

    def test_the_score_does_not_depend_on_the_truth(self):
        oracle = forgetting.ForgettingOracle(self.cat)
        a = {"b_importance": 20, "b_truth": 0, "b_origin_fact": 0}
        b = {"b_importance": 20, "b_truth": 1, "b_origin_fact": 99}
        self.assertEqual(oracle.score("belief", a, 5), oracle.score("belief", b, 5))

    def test_parity_inc_is_the_oracle(self):
        text = gen_cpp.ForgettingGenerator(self.cat).generate_parity()
        self.assertIn(f"0x{forgetting.ForgettingOracle(self.cat).parity_hash():016x}", text)
        self.assertIn(str(forgetting.PARITY_RECORDS), text)
        if gen_cpp.PARITY_OUT.exists():
            self.assertEqual(gen_cpp.PARITY_OUT.read_text(encoding="utf-8"), text)

    def test_generator_refuses_nothing_it_would_not_check(self):
        text = gen_cpp.ForgettingGenerator(self.cat).generate()
        for var in forgetting.FORBIDDEN_VARS:
            self.assertNotIn(var, text)

    # ---- T09 corrections: semantics of the times, comparable scales, relations, fixed capacity -----------------------
    def test_every_recency_reads_a_timestamp_and_says_so(self):
        """A recency term computes now - value: the variable must be an instant, declared as such (ev_age was a duration)."""
        for law in self.cat["forgetting"].values():
            for t in law.score:
                if t.get("kind") == "recency":
                    v = self.cat["variable"][t["var"]]
                    self.assertIn("horodatage", v.dynamics, t["var"])
                    self.assertNotIn("il y a combien", v.label_fr, t["var"])
        oracle = forgetting.ForgettingOracle(self.cat)
        now = forgetting.PARITY_NOW
        recent = oracle.score("event_seen", {"ev_age": now - 100}, now)
        old = oracle.score("event_seen", {"ev_age": now - 5 * forgetting.SEASON_SECONDS}, now)
        self.assertGreater(recent, old)                       # a larger duration = older = forgotten first

    def test_terms_are_comparable(self):
        """Each term weighs a whole 1..10 points of 1000, whatever the scale of its variable."""
        for law in self.cat["forgetting"].values():
            for t in law.score:
                amp = forgetting.ForgettingChecker.amplitude(t, self.cat["variable"][t["var"]])
                self.assertEqual(amp % forgetting.POINT, 0, (law.record, t))
                self.assertTrue(forgetting.POINT <= amp <= forgetting.MAX_POINTS * forgetting.POINT, (law.record, t))

    def test_an_unnormalised_or_uncapped_term_is_refused(self):
        for record, term in (("goal", {"var": "g_progress", "weight": 1}),                     # ratio x1 = 1000 is fine...
                             ("goal", {"var": "g_priority", "weight": 4}),                     # unipolar10 x4 = 400: not whole points
                             ("belief", {"var": "b_secret", "weight": 1}),                     # bool x1 = 1: nothing
                             ("episode", {"var": "m_rehearsals", "weight": 1})):              # a qty without cap
            cat = Catalogue.load()
            cat["forgetting"][record].score = [dict(term)]
            problems = forgetting.ForgettingChecker(cat).problems()
            if term == {"var": "g_progress", "weight": 1}:
                self.assertEqual(problems, [], term)
            else:
                self.assertTrue(problems, term)

    def score(self, kind, rec, now=None):
        now = forgetting.PARITY_NOW if now is None else now
        return forgetting.ForgettingOracle(self.cat).score(kind, rec, now)

    def test_a_new_priority_goal_outlives_a_stagnant_nearly_done_one(self):
        now = forgetting.PARITY_NOW
        fresh = {"g_priority": 90, "g_progress": 0, "g_since": now - 3600}
        stagnant = {"g_priority": 20, "g_progress": 950, "g_since": now - 12 * forgetting.SEASON_SECONDS}
        self.assertGreater(self.score("goal", fresh), self.score("goal", stagnant))
        # progress still counts: of two equal goals the nearly done one is kept
        a, b = dict(stagnant), dict(stagnant, g_progress=0)
        self.assertGreater(self.score("goal", a), self.score("goal", b))
        # ... but it does not crush priority: a priority 9 stagnant goal at 0 beats a priority 2 at 100 %
        self.assertGreater(self.score("goal", dict(stagnant, g_priority=90, g_progress=0)),
                           self.score("goal", dict(stagnant, g_priority=20, g_progress=1000)))

    def test_a_contradicted_belief_goes_before_a_confirmed_one(self):
        now = forgetting.PARITY_NOW
        base = {"b_importance": 50, "b_certainty": 60, "b_confirmed": now - 100, "b_acquired": now - 5000}
        self.assertLess(self.score("belief", dict(base, b_contradicted=1)), self.score("belief", base))
        # and it weighs as much as 3 points of importance, not 0.75 %: a contradicted belief of importance 10 sits below
        # an uncontradicted one of importance 7
        self.assertLess(self.score("belief", dict(base, b_importance=100, b_contradicted=1)),
                        self.score("belief", dict(base, b_importance=70)) + 1000)

    def test_rehearsals_shared_history_and_steps_count(self):
        now = forgetting.PARITY_NOW
        ep = {"m_importance": 30, "m_vividness": 30, "m_when": now - 100}
        self.assertGreater(self.score("episode", dict(ep, m_rehearsals=6)), self.score("episode", dict(ep, m_rehearsals=0)))
        # 10 rehearsals weigh as much as 2.5 points of importance (1 point = 1000 here)
        self.assertGreaterEqual(self.score("episode", dict(ep, m_rehearsals=10)) - self.score("episode", ep), 1000)
        rel = {"r_familiarity": 30, "r_last_contact": now - 100}
        self.assertGreater(self.score("relation", dict(rel, r_shared_history=15)), self.score("relation", rel))
        self.assertGreater(self.score("intention", {"i_commitment": 50, "i_step_index": 4}),
                           self.score("intention", {"i_commitment": 50, "i_step_index": 0}))
        self.assertGreaterEqual(self.score("intention", {"i_commitment": 50, "i_step_index": 6})
                                - self.score("intention", {"i_commitment": 50, "i_step_index": 0}), 1000)

    def test_the_friend_and_the_creditor_are_kept_before_the_enemy(self):
        now = forgetting.PARITY_NOW
        common = {"r_familiarity": 50, "r_last_contact": now - 3 * forgetting.SEASON_SECONDS, "r_shared_history": 8}
        friend = dict(common, r_affection=80)
        creditor = dict(common, r_obligation=80)                 # + : I owe him
        enemy = dict(common, r_affection=-80, r_resentment=80, r_fear=30)
        stranger = dict(common)
        self.assertGreater(self.score("relation", friend), self.score("relation", enemy))
        self.assertGreater(self.score("relation", creditor), self.score("relation", enemy))
        self.assertGreater(self.score("relation", friend), self.score("relation", stranger))
        self.assertGreater(self.score("relation", creditor), self.score("relation", stranger))
        relation = self.cat["forgetting"]["relation"]
        self.assertTrue({"r_affection", "r_obligation"} <= {t["var"] for t in relation.score})

    def test_the_capacity_is_fixed_in_v1(self):
        for law in self.cat["forgetting"].values():
            self.assertNotIn("capacity_from", vars(law))
        self.assertFalse(any("capacity_from" in line for line in
                             (ROOT / "data" / "forgetting.toml").read_text(encoding="utf-8").splitlines()
                             if not line.lstrip().startswith("#")))


if __name__ == "__main__":
    unittest.main()
