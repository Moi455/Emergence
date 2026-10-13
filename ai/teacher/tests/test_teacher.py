"""Tests of the teacher format (no network): rendering, schema, validator, key loader, model chain, pilot loop.

    python3 -m unittest discover -s ai/teacher/tests -t ai
"""
from __future__ import annotations

import json
import os
import statistics
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from situations.sampler import SituationSampler
from tok2 import DecisionContext, Record

from teacher.gemini import (ApiKeyError, ApiKeyLoader, ApiResult, GeminiClient, ModelCatalog, QuotaBook, RateLimiter,
                            Redactor)
from teacher.pilot import DryRun, ModelPool, PilotRun, RunDirectory, RunSummary
from teacher.render import SituationRenderer
from teacher.schema import EXAMPLES, DecisionSchema
from teacher.toolkit import ROOT, Toolkit
from teacher.validate import AnswerValidator, SceneTruth, TruthSource

TK = Toolkit()
SAMPLER = SituationSampler(7)
RENDERER = SituationRenderer(TK)


def answer(gesture, params=(), speech="", writes=(), why="test"):
    return json.dumps({"why": why, "gesture": gesture, "params": [{"name": n, "value": v} for n, v in params],
                       "speech": speech, "writes": [{"target": t, "variable": v, "value": x} for t, v, x in writes]})


TAKE = (("target", "@T1"), ("from", "ground"), ("hold", "in_hand"), ("stealth", "open"), ("contact_zone", "hands"))
SPEAK = (("to", "@E1"), ("volume", "normal"), ("tone", "calm"))
SEARCH = (("target", "@E2"), ("thoroughness", "brief"))


class FakeTruth(TruthSource):
    def __init__(self, ages):
        self.ages = ages

    def real_age(self, key):
        return self.ages.get(key)


def mini_situation():
    """A hand-made mind: an adult acquaintance @E1, a child @E2 who looks like an adult (real age 11), a person
    known by name only @E3, a bowl, a wolf and a stone."""
    far = {"sin": 0.0, "cos": 1.0}
    recs = [
        Record("SELF", "me", {"age": 30.0, "age_stage": "adult", "sex": "female", "season": "spring", "place": "@PLACE",
                              "posture": "standing", "time": {"sin": 0.0, "cos": 1.0, "certainty": 0.9}}),
        Record("SELF_MIND", "me.mind", {"trait.patience": 6.0}),
        Record("SELF_STATE", "me.state", {"emo.anger": 1.0, "emo.joy": 3.0, "drive.company": 4.0}),
        Record("ENTITY", "@E1", {"link": "neighbor", "present": True, "known_by": "seen", "name": "n:11", "dist": 3.0,
                                 "dir": far, "look.age": 35.0, "rel.trust": 2.0, "rel.affection": 1.0}),
        Record("ENTITY", "@E2", {"link": "stranger", "present": True, "known_by": "seen", "dist": 4.0, "dir": far,
                                 "look.age": 25.0}),
        Record("ENTITY", "@E3", {"link": "sibling", "present": False, "known_by": "name_only", "name": "n:33"}),
        Record("THING", "@T1", {"kind": "wooden_bowl", "dist": 1.0, "dir": far, "owner": "@E1",
                                "props": {"mass": 0.3, "graspable": True}}),
        Record("THING", "@T2", {"kind": "sheep", "dist": 8.0, "dir": far, "display": "grazing", "motion": "still"}),
        Record("THING", "@T3", {"kind": "stone_loose", "dist": 2.0, "dir": far, "props": {"mass": 2.0, "graspable": True}}),
        Record("PLACE", "@PLACE", {"indoors": False, "crowd": 2, "light": 8.0}),
        Record("LOCUS", "@L1", {"dist": 300.0, "dir": far}),
        Record("BELIEF", "b:1", {"prop": "(owns @E1 @T1)", "source": "seen", "age": 2.0, "certainty": 7.0, "polarity": True}),
        Record("GOAL", "g:1", {"prop": "(has me bread_loaf)", "mode": "achieve", "status": "active", "priority": 3.0}),
        Record("MEMORY", "m:1", {"prop": "(past (did @E1 give bread_loaf (to me)))", "age": 40.0, "emotion": "e_gratitude"}),
    ]
    return SimpleNamespace(context=DecisionContext(recs), scene=None)


MINI = mini_situation()
MINI_VALIDATOR = AnswerValidator(TK, truth_factory=lambda s: FakeTruth({"me": 30.0, "@E1": 35.0, "@E2": 11.0, "@E3": 40.0}))


class TruthlessSituation:
    """A situation whose scene explodes when touched: the renderer must work from the records only."""
    def __init__(self, sit):
        self.context = sit.context

    @property
    def scene(self):
        raise AssertionError("the renderer touched the true scene")


# ------------------------------------------------------------------------------------------------ rendering
class RenderTests(unittest.TestCase):
    def test_reads_only_the_records(self):
        for i in range(5):
            self.assertTrue(RENDERER.render(TruthlessSituation(SAMPLER.sample(i))))

    def test_no_truth_in_text(self):
        for i in range(40):
            sit = SAMPLER.sample(i)
            text = RENDERER.render(sit)
            truth = SceneTruth(sit.scene, sit.context.records, TK.interface.token_types["ENTITY"]["count"])
            for key, person in truth.people.items():
                self.assertNotIn(f"{person.age:.2f}", text, f"situation {i}: the true age of {key} is printed")
            # the owner shown is the BELIEVED one (the record's), never the true one
            owner_key = {p.pid: k for k, p in truth.people.items()}
            things = [r for r in sit.context.records if r.type == "THING" and "props" in r.fields]
            for rec, thing in zip(things, [t for t in sit.scene.things if not t.animal]):
                line = next(ln for ln in text.splitlines() if ln.startswith(rec.key + " "))
                real = owner_key.get(thing.owner)
                if real and real != rec.fields.get("owner"):
                    self.assertNotIn(f"owner you believe: {real}", line)

    def test_text_is_independent_of_the_scene(self):
        """Change every true age and owner of the scene: the text must not move by a character."""
        for i in range(10):
            sit = SAMPLER.sample(i)
            before = RENDERER.render(sit)
            for p in sit.scene.persons():
                p.age += 7.0
            for t in sit.scene.things:
                t.owner = None if t.owner else sit.scene.self_.pid
            self.assertEqual(before, RENDERER.render(sit))

    def test_every_key_is_visible(self):
        for i in range(30):
            sit = SAMPLER.sample(i)
            text = RENDERER.render(sit)
            for r in sit.context.records:
                if r.type in ("SELF_MIND", "SELF_STATE", "SKILL", "TASTE"):
                    continue
                self.assertIn(r.key, text, f"situation {i}: key {r.key} ({r.type}) is not rendered")

    def test_propositions_have_sexpr_and_gloss(self):
        sit = SAMPLER.sample(1)
        text = RENDERER.render(sit)
        for r in sit.context.records:
            if r.type in ("BELIEF", "GOAL", "MEMORY", "HEARD", "COMMIT"):
                self.assertIn(" ".join(r.fields["prop"].split()) + ' "', text)

    def test_concise(self):
        sizes = [len(RENDERER.render(SAMPLER.sample(i))) for i in range(30)]
        self.assertLess(statistics.mean(sizes), 9000)
        self.assertLess(max(sizes), 14000)

    def test_salience_only(self):
        text = RENDERER.render_records(MINI.context.records)
        self.assertIn("joy 3", text)
        self.assertNotIn("anger 1", text)            # a low emotion is not listed
        self.assertIn("looks about 35", text)
        self.assertIn("known by name only", text)


# ------------------------------------------------------------------------------------------------ schema
class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = DecisionSchema(TK)
        cls.raw = json.loads(Path(ROOT / "catalogue/generated/model_interface.json").read_text())["output"]

    def test_json_and_enums(self):
        for style in (self.schema.response_schema(), self.schema.json_schema()):
            style = json.loads(json.dumps(style))                    # valid JSON
            props = style["properties"]
            self.assertEqual(sorted(props["gesture"]["enum"]), sorted(self.raw["gestures"]))
            self.assertEqual(len(props["gesture"]["enum"]), 40)
            variables = set(props["writes"]["items"]["properties"]["variable"]["enum"])
            writable = {k for k, v in self.raw["writes"]["writable"].items() if v["scale"] != "list"}
            self.assertEqual(variables, writable)
            self.assertEqual(props["writes"]["maxItems"], self.raw["writes"]["max_per_decision"])
            self.assertEqual(set(style["required"]), {"why", "gesture", "params", "speech", "writes"})
            names = {p["name"] for g in self.raw["gestures"].values() for p in g["params"] if p.get("type") != "expression"}
            self.assertEqual(set(props["params"]["items"]["properties"]["name"]["enum"]), names)

    def test_gemini_subset(self):
        text = json.dumps(self.schema.response_schema())
        for banned in ("oneOf", "anyOf", "$ref", "additionalProperties"):
            self.assertNotIn(banned, text)
        self.assertEqual(self.schema.response_schema()["type"], "OBJECT")
        self.assertEqual(self.schema.json_schema()["type"], "object")
        self.assertEqual(self.schema.response_schema()["propertyOrdering"][0], "why")

    def test_instructions_cover_the_contract(self):
        text = self.schema.instructions()
        for g in self.raw["gestures"]:
            self.assertIn(f"\n  {g}", text)
        for head in self.raw["manner_heads"]:
            self.assertIn(f"  {head}:", text)
        for cond in self.raw["condition_head"]:
            self.assertIn(cond, text)
        for var in self.raw["writes"]["writable"]:
            if self.raw["writes"]["writable"][var]["scale"] != "list":
                self.assertIn(var, text)
        for must in ("under 18", "at most 20 symbols", "at most 4 changes"):
            self.assertIn(must, text)

    def test_examples_are_valid_language(self):
        for e in EXAMPLES:
            if e["speech"]:
                ex = TK.expression(e["speech"])
                self.assertTrue(ex.ok, ex.problems)
            spec = TK.spec.gestures[e["gesture"]]
            self.assertEqual({p.name for p in spec.params if p.kind != "expression" and not p.optional}
                             - {n for n, _ in e["params"]}, set())

    def test_grammar(self):
        g = self.schema.gbnf()
        self.assertTrue(g.startswith("root ::="))
        for gesture in self.raw["gestures"]:
            self.assertIn(f'\\"{gesture}\\"', g)
        self.assertIn("{0,3}", g)

    def test_vocab_option_changes_size_only(self):
        full, none = DecisionSchema(TK, "full").instructions(), DecisionSchema(TK, "none").instructions()
        self.assertGreater(len(full), len(none))
        self.assertEqual(DecisionSchema(TK, "full").response_schema(), DecisionSchema(TK, "none").response_schema())

    def test_spec_matches_catalogue(self):
        for gid, g in TK.spec.gestures.items():
            a = TK.cat["action"][gid]
            self.assertEqual([(p.name, p.optional) for p in g.params], [(p.name, p.optional) for p in a.params], gid)
            for p, q in zip(g.params, a.params):
                if p.kind == "enum":
                    self.assertEqual(list(p.values), q.values, f"{gid}.{p.name}")


# ------------------------------------------------------------------------------------------------ validator
class ValidatorTests(unittest.TestCase):
    def check(self, text, sit=MINI, v=MINI_VALIDATOR):
        return v.validate(text, sit)

    def assertRefused(self, out, code):
        self.assertFalse(out.ok, out.decision)
        self.assertEqual(out.code, code, out.detail)

    # ---- accepted
    def test_good_speak(self):
        out = self.check(answer("speak", SPEAK, "(assert (owns @E1 @T1))", [("self", "anger", "4")]))
        self.assertTrue(out.ok, (out.code, out.detail))
        d = out.decision
        self.assertEqual((d.gesture, d.family), ("speak", "communicate"))
        self.assertEqual(d.speech, "(assert (owns @E1 @T1))")
        self.assertEqual(d.writes[0].variable, "anger")
        self.assertEqual(d.writes[0].value, 4.0)
        json.dumps(d.to_dict())

    def test_good_take_with_relation_write(self):
        out = self.check(answer("take", TAKE, "", [("@E1", "r_trust", "2.4")]))
        self.assertTrue(out.ok, (out.code, out.detail))
        self.assertAlmostEqual(out.decision.writes[0].value, 2.4)        # old 2.0, step 0.5 per decision

    def test_good_wait_and_conditions(self):
        for cond in ("c_done", "(c_elapsed 30)", "(c_target_down @E1)", "(c_reached @L1)", "(c_sees wolf)", "(c_hunger_above 6)"):
            out = self.check(answer("wait", [("until", cond)]))
            self.assertTrue(out.ok, (cond, out.code, out.detail))

    def test_good_new_record_and_citation(self):
        out = self.check(answer("wait", [("until", "c_done")], "", [("new", "g_desired", "(has me bread_loaf:2)")]))
        self.assertTrue(out.ok, (out.code, out.detail))
        out = self.check(answer("speak", SPEAK, "(assert (that b:1))"))
        self.assertTrue(out.ok, (out.code, out.detail))

    def test_write_is_clipped_not_refused(self):
        out = self.check(answer("wait", [("until", "c_done")], "", [("@E1", "r_trust", "9")]))
        self.assertTrue(out.ok)
        self.assertAlmostEqual(out.decision.writes[0].value, 2.5)
        self.assertEqual(out.decision.writes[0].verdict, "clipped")

    def test_fenced_json_tolerated(self):
        self.assertTrue(self.check("```json\n" + answer("stop") + "\n```").ok)

    # ---- refused by the validator
    def test_invalid_json(self):
        self.assertRefused(self.check("this is not json"), "invalid_json")
        self.assertRefused(self.check(""), "invalid_json")

    def test_bad_shape(self):
        self.assertRefused(self.check("[1, 2]"), "bad_shape")
        self.assertRefused(self.check(json.dumps({"gesture": "stop", "params": "x"})), "bad_shape")
        self.assertRefused(self.check(json.dumps({"gesture": "stop", "params": [{"name": "a", "value": 3}]})), "bad_shape")

    def test_unknown_gesture(self):
        self.assertRefused(self.check(answer("fly")), "unknown_gesture")
        self.assertRefused(self.check(answer("steal")), "unknown_gesture")

    def test_bad_pointer(self):
        t = (("target", "@T9"),) + TAKE[1:]
        self.assertRefused(self.check(answer("take", t)), "bad_pointer")
        self.assertRefused(self.check(answer("speak", SPEAK, "(assert (has @E7 bread_loaf))")), "bad_pointer")
        self.assertRefused(self.check(answer("wait", [("until", "(c_target_down @E9)")])), "bad_pointer")
        self.assertRefused(self.check(answer("wait", [("until", "c_done")], "", [("@E8", "r_trust", "1")])), "bad_pointer")

    def test_bad_param(self):
        self.assertRefused(self.check(answer("take", TAKE[:3])), "bad_param")                                   # missing
        self.assertRefused(self.check(answer("take", (("target", "@T1"), ("from", "sky")) + TAKE[2:])), "bad_param")
        self.assertRefused(self.check(answer("take", TAKE + (("target", "@T3"),))), "bad_param")                # twice
        self.assertRefused(self.check(answer("take", TAKE + (("colour", "red"),))), "bad_param")                # unknown
        self.assertRefused(self.check(answer("eat", (("item", "@T2"), ("amount", "some")))), "bad_param")        # a sheep is no food item
        self.assertRefused(self.check(answer("speak", SPEAK + (("content", "(hello)"),), "(hello)")), "bad_param")
        self.assertRefused(self.check(answer("wait", [("until", "c_never")])), "bad_param")
        self.assertRefused(self.check(answer("wait", [("until", "(c_elapsed)")])), "bad_param")
        self.assertRefused(self.check(answer("wait", [("until", "(c_elapsed wolf)")])), "bad_param")

    def test_bad_speech(self):
        self.assertRefused(self.check(answer("speak", SPEAK, "(assert (frobnicate me))")), "bad_speech")
        self.assertRefused(self.check(answer("speak", SPEAK, "hello there")), "bad_speech")
        self.assertRefused(self.check(answer("speak", SPEAK, "(assert (has me bread_loaf)")), "bad_speech")      # parenthesis
        self.assertRefused(self.check(answer("speak", SPEAK, "")), "bad_speech")
        self.assertRefused(self.check(answer("wait", [("until", "c_done")], "(hello)")), "bad_speech")
        long = "(assert " + "(and " * 6 + "(dead @E1)" + " (dead @E1))" * 6 + ")"
        self.assertRefused(self.check(answer("speak", SPEAK, long)), "bad_speech")

    def test_too_many_writes(self):
        w = [("self", v, "3") for v in ("anger", "fear", "joy", "pride", "shame")]
        self.assertRefused(self.check(answer("stop", writes=w)), "too_many_writes")
        self.assertTrue(self.check(answer("stop", writes=w[:4])).ok)

    def test_bad_write(self):
        self.assertRefused(self.check(answer("stop", writes=[("@E1", "anger", "3")])), "bad_write")      # wrong target kind
        self.assertRefused(self.check(answer("stop", writes=[("self", "anger", "lots")])), "bad_write")
        self.assertRefused(self.check(answer("stop", writes=[("new", "anger", "3")])), "bad_write")
        self.assertRefused(self.check(answer("stop", writes=[("b:1", "b_secret", "maybe")])), "bad_write")
        self.assertRefused(self.check(answer("stop", writes=[("self", "anger", "1_0")])), "bad_write")
        self.assertRefused(self.check(answer("stop", writes=[("self", "anger", "\uff11\uff12")])), "bad_write")
        self.assertRefused(self.check(answer("stop", writes=[("g:1", "g_deadline", "-5")])), "bad_write")
        self.assertRefused(self.check(answer("stop", writes=[("g:1", "g_deadline", "1e300")])), "bad_write")
        self.assertTrue(self.check(answer("stop", writes=[("b:1", "b_secret", "true")])).ok)
        self.assertRefused(self.check(answer("stop", writes=[("self", "tastes", "x")])), "bad_write")       # a list: not supported

    def test_unknown_old_value(self):
        # @E2 has no rel.trust in the record: a bounded write cannot be judged; an emotion (a jump) can
        self.assertRefused(self.check(answer("stop", writes=[("@E2", "r_trust", "3")])), "unknown_old")
        self.assertTrue(self.check(answer("stop", writes=[("self", "fear", "3")])).ok)

    def test_self_and_me_are_one_target(self):
        out = self.check(answer("stop", writes=[("self", "fear", "3"), ("me", "fear", "5")]))
        self.assertTrue(out.ok)
        self.assertEqual(len(out.decision.writes), 1)

    def test_condition_names_are_checked(self):
        self.assertRefused(self.check(answer("wait", [("until", "(c_target_down n:99999)")])), "bad_pointer")
        self.assertTrue(self.check(answer("wait", [("until", "(c_target_down n:11)")])).ok)

    # ---- refused by the governor
    def test_judgement_needs_every_person_resolved(self):
        """m_interpretation adultery is an intimate judgement: refused when any person it names, or the one who
        judges, may be a minor. Neutral judgements pass."""
        add = lambda t: answer("stop", writes=[("m:1", "m_interpretation", t)])        # noqa: E731
        base = MINI.context.records
        self.assertTrue(self.check(add("generosity")).ok)
        self.assertTrue(self.check(add("adultery")).ok)                                 # positive control: adults, resolved
        child_me = [Record(r.type, r.key, dict(r.fields)) for r in base]
        child_me[0].fields["age"] = 12.0
        sit = SimpleNamespace(context=DecisionContext(child_me), scene=None)
        v = AnswerValidator(TK, truth_factory=lambda s: FakeTruth({"me": 12.0, "@E1": 35.0, "@E2": 11.0}))
        self.assertRefused(v.validate(add("adultery"), sit), "governor:d10_intimate")
        named = [Record(r.type, r.key, dict(r.fields)) for r in base]
        named[-1].fields["prop"] = "(past (did n:33 give bread_loaf (to @E1)))"          # n:33 = @E3, known by name only
        sit = SimpleNamespace(context=DecisionContext(named), scene=None)
        self.assertRefused(self.check(add("adultery"), sit), "governor:d10_intimate")

    def test_engine_variable(self):
        self.assertRefused(self.check(answer("stop", writes=[("self", "hunger", "0")])), "governor:engine_owned")
        self.assertRefused(self.check(answer("stop", writes=[("self", "pain", "0")])), "governor:engine_owned")
        self.assertRefused(self.check(answer("stop", writes=[("self", "luck", "9")])), "governor:unknown_variable")

    def test_governor_uses_the_real_age(self):
        # @E2 LOOKS 25 in the NPC's record but is 11 in the scene: the engine's governor knows the truth
        self.assertRefused(self.check(answer("search", SEARCH)), "governor:d10_person")
        ok = AnswerValidator(TK, truth_factory=lambda s: FakeTruth({"me": 30.0, "@E1": 35.0, "@E2": 25.0}))
        self.assertTrue(ok.validate(answer("search", SEARCH), MINI).ok)

    def test_unresolved_person_is_denied_by_default(self):
        out = self.check(answer("search", (("target", "@E3"), ("thoroughness", "brief"))))
        self.assertRefused(out, "governor:d10_person")                       # known by name only

    def test_unknown_real_age_is_denied(self):
        v = AnswerValidator(TK, truth_factory=lambda s: FakeTruth({"me": 30.0}))
        self.assertRefused(v.validate(answer("search", (("target", "@E1"), ("thoroughness", "brief"))), MINI),
                           "governor:d10_person")

    # ---- against the sampler
    def test_scene_truth_matches_the_records(self):
        v = AnswerValidator(TK)
        for i in range(40):
            sit = SAMPLER.sample(i)
            out = v.validate(answer("wait", [("until", "c_done")]), sit)       # builds the truth map and cross-checks names
            self.assertTrue(out.ok, (i, out.code, out.detail))
            truth = SceneTruth(sit.scene, sit.context.records, TK.interface.token_types["ENTITY"]["count"])
            for r in sit.context.records:
                if r.type == "ENTITY" and "look.age" in r.fields:
                    self.assertLessEqual(abs(r.fields["look.age"] - truth.real_age(r.key)), 4.5)

    def test_truth_mismatch_is_detected(self):
        sit = SAMPLER.sample(2)
        sit.scene.present[0].person.name = "n:99999"
        sit.scene.present[0].known = True
        out = AnswerValidator(TK).validate(answer("stop"), sit)
        self.assertRefused(out, "truth_error")

    def test_swapped_strangers_are_detected(self):
        """Strangers carry no name: the apparent age is what reveals a drifted key map."""
        for i in range(60):
            sit = SAMPLER.sample(i)
            strangers = [x for x in sit.scene.present if x.link == "stranger" and x.known or x.dist < 15]
            ages = {round(x.person.age) for x in strangers}
            if len(strangers) >= 2 and len(ages) > 1 and max(ages) - min(ages) > 12:
                a, b = strangers[0].person, strangers[-1].person
                a.age, b.age = b.age, a.age
                out = AnswerValidator(TK).validate(answer("stop"), sit)
                self.assertRefused(out, "truth_error")
                return
        self.skipTest("no situation with two strangers of very different ages in the first 60")


# ------------------------------------------------------------------------------------------------ key and client
class KeyLoaderTests(unittest.TestCase):
    SECRET = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKE1234567"

    def file(self, text, mode=0o600):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "API_Keys"
        p.write_text(text)
        os.chmod(p, mode)
        return p

    def test_env_first(self):
        self.assertEqual(ApiKeyLoader(env={"GEMINI_API_KEY": " abc "}, path=Path("/nonexistent")).load(), "abc")

    def test_file_formats(self):
        for text in (f"GEMINI_API_KEY={self.SECRET}\n", f"export GEMINI_API_KEY='{self.SECRET}'\n", f"{self.SECRET}\n",
                     f"# comment\nOTHER=1\nGEMINI_API_KEY=\"{self.SECRET}\"\n"):
            self.assertEqual(ApiKeyLoader(env={}, path=self.file(text)).load(), self.SECRET)

    def test_loose_permissions_refused_without_leaking(self):
        with self.assertRaises(ApiKeyError) as cm:
            ApiKeyLoader(env={}, path=self.file(self.SECRET, 0o644)).load()
        self.assertNotIn(self.SECRET, str(cm.exception))

    def test_missing_and_empty(self):
        with self.assertRaises(ApiKeyError):
            ApiKeyLoader(env={}, path=Path("/nonexistent/keys")).load()
        with self.assertRaises(ApiKeyError):
            ApiKeyLoader(env={}, path=self.file("# nothing\n")).load()

    def test_redactor(self):
        r = Redactor(self.SECRET)
        self.assertNotIn(self.SECRET, r.clean(f"error for key {self.SECRET} here"))
        self.assertNotIn("AIza", r.clean("AIzaSyOTHEROTHEROTHEROTHEROTHER12345"))


class ClientTests(unittest.TestCase):
    class Resp:
        def __init__(self, status, body):
            self.status, self._b = status, json.dumps(body).encode()

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def client(self, status, body):
        seen = {}

        def opener(req, timeout):
            seen["url"], seen["headers"], seen["body"] = req.full_url, dict(req.header_items()), json.loads(req.data or b"{}")
            return self.Resp(status, body)
        return GeminiClient("AIzaSyFAKEFAKEFAKEFAKEFAKEFAKE1234567", opener=opener), seen

    def test_generate_success_and_key_in_header_only(self):
        c, seen = self.client(200, {"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}],
                                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3}})
        r = c.generate("gemini-2.5-flash-lite", "sys", "usr", {"type": "OBJECT"})
        self.assertTrue(r.ok)
        self.assertEqual(r.usage["promptTokenCount"], 10)
        self.assertNotIn("AIza", seen["url"])
        self.assertEqual(seen["headers"]["X-goog-api-key"], c.key)
        cfg = seen["body"]["generationConfig"]
        self.assertEqual(cfg["responseMimeType"], "application/json")
        self.assertEqual(cfg["responseSchema"], {"type": "OBJECT"})
        self.assertEqual(seen["body"]["systemInstruction"]["parts"][0]["text"], "sys")

    def test_quota_classification(self):
        day = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota",
                         "details": [{"@type": "QuotaFailure", "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}
        minute = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "slow down",
                            "details": [{"@type": "RetryInfo", "retryDelay": "37s"}]}}
        c, _ = self.client(429, day)
        self.assertEqual(c.generate("m", "s", "u", {}).quota_scope, "day")
        c, _ = self.client(429, minute)
        r = c.generate("m", "s", "u", {})
        self.assertEqual((r.quota_scope, r.retry_after), ("minute", 37.0))

    def test_odd_error_payloads_do_not_crash(self):
        c, _ = self.client(429, [{"error": {"status": "X", "details": ["junk", {"retryDelay": "3s"}]}}])
        r = c.generate("m", "s", "u", {})
        self.assertEqual((r.status, r.retry_after), (429, 3.0))
        c, _ = self.client(500, {"error": "plain string"})
        self.assertEqual(c.generate("m", "s", "u", {}).status, 500)

    def test_count_tokens(self):
        c, seen = self.client(200, {"totalTokens": 1234})
        self.assertEqual(c.count_tokens("gemini-2.5-flash-lite", "s", "u"), 1234)
        self.assertTrue(seen["url"].endswith("models/gemini-2.5-flash-lite:countTokens"))


class ModelChainTests(unittest.TestCase):
    def test_order_lite_first_then_flash(self):
        names = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite", "gemini-2.5-pro",
                 "gemini-2.5-flash-image", "gemini-2.5-flash-preview-tts", "gemini-3-flash-preview",
                 "gemini-2.5-flash-lite-preview-09-2025", "gemini-2.0-flash", "embedding-001", "gemma-3-27b-it"]
        models = [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]} for n in names]
        models.append({"name": "models/gemini-2.5-flash-8b", "supportedGenerationMethods": ["countTokens"]})
        chain = ModelCatalog(models).chain()
        lite = [m for m in chain if "lite" in m]
        self.assertEqual(chain[:len(lite)], lite)                       # every Lite before any Flash
        self.assertEqual(lite[0], "gemini-2.5-flash-lite")              # newest stable first
        self.assertEqual(chain.index("gemini-2.5-flash"), len(lite))
        for banned in ("pro", "image", "tts", "embedding", "gemma", "8b"):
            self.assertFalse(any(banned in m for m in chain), banned)

    def test_rate_limiter_spacing(self):
        t = [0.0]
        slept = []
        lim = RateLimiter(15, clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
        lim.wait(); lim.wait(); lim.wait()
        self.assertEqual(slept, [4.0, 4.0])                             # 15 requests a minute: 4 s apart

    def test_quota_book(self):
        b = QuotaBook()
        b.spend("a")
        self.assertEqual(b.available(["a", "gemini-2.5-flash-lite"]), ["gemini-2.5-flash-lite"])
        for _ in range(20):
            b.count("gemini-2.5-flash")
        self.assertEqual(b.available(["gemini-2.5-flash"]), [])         # 20 a day on Flash


# ------------------------------------------------------------------------------------------------ pilot
class FakeClient:
    """Stands in for GeminiClient: no network."""
    def __init__(self, script):
        self.script, self.calls, self.redactor = list(script), [], Redactor("")

    def generate(self, model, system, user, schema, temperature=0.9, max_output_tokens=1024, thinking_budget=None):
        self.calls.append(model)
        return self.script.pop(0)(model)


def good(model):
    return ApiResult(True, 200, answer("wait", [("until", "c_done")]), "STOP",
                     {"promptTokenCount": 100, "candidatesTokenCount": 20}, 0.5)


def day_quota(model):
    return ApiResult(False, 429, error="RESOURCE_EXHAUSTED", quota_scope="day")


def garbage(model):
    return ApiResult(True, 200, "no", "STOP", {}, 0.1)


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = RunDirectory(Path(self.tmp.name), "t")

    def pilot(self, script, chain=("gemini-2.5-flash-lite", "gemini-2.5-flash")):
        pool = ModelPool(list(chain), clock=lambda: 1e9, sleep=lambda s: None)
        for lim in pool.limiters.values():                 # no waiting in tests
            lim.sleep = lambda s: None
        return PilotRun(FakeClient(script), TK, DecisionSchema(TK, "none"), RENDERER, SituationSampler(1),
                        AnswerValidator(TK), pool, self.out, log=lambda s: None), pool

    def test_fallback_on_daily_quota(self):
        run, pool = self.pilot([day_quota, good, good, garbage])
        recs = run.run(3)
        self.assertEqual([r["model"] for r in recs], ["gemini-2.5-flash", "gemini-2.5-flash", "gemini-2.5-flash"])
        self.assertEqual([r["code"] for r in recs], ["ok", "ok", "invalid_json"])
        self.assertIn("gemini-2.5-flash-lite", pool.book.spent)

    def test_minute_limit_loop_is_capped(self):
        minute = lambda m: ApiResult(False, 429, error="RESOURCE_EXHAUSTED", quota_scope="minute", retry_after=0)   # noqa: E731
        run, pool = self.pilot([minute] * 4 + [good])
        import teacher.pilot as P
        real = P.time.sleep
        P.time.sleep = lambda s: None
        try:
            recs = run.run(1)
        finally:
            P.time.sleep = real
        self.assertIn("gemini-2.5-flash-lite", pool.book.spent)           # 4th 429 in a row: model treated as spent
        self.assertEqual(recs[0]["model"], "gemini-2.5-flash")

    def test_bad_request_stops_after_two(self):
        bad = lambda m: ApiResult(False, 400, error="INVALID_ARGUMENT")   # noqa: E731
        run, _ = self.pilot([bad, bad, good])
        with self.assertRaises(RuntimeError):
            run.run(1)

    def test_missing_model_is_skipped_and_empty_answers_are_counted(self):
        gone = lambda m: ApiResult(False, 404, error="NOT_FOUND")         # noqa: E731
        blocked = lambda m: ApiResult(False, 200, "", "SAFETY", {}, 0.2)  # noqa: E731
        run, pool = self.pilot([gone, blocked, good])
        recs = run.run(2)
        self.assertEqual([r["code"] for r in recs], ["no_text", "ok"])
        self.assertIn("gemini-2.5-flash-lite", pool.book.spent)

    def test_truncated_answer_is_its_own_code_and_stops_a_streak(self):
        cut = lambda m: ApiResult(True, 200, '{"why": "x', "MAX_TOKENS", {}, 0.2)   # noqa: E731
        run, _ = self.pilot([cut, cut, cut])
        with self.assertRaises(RuntimeError):
            run.run(5)
        self.assertEqual([r["code"] for r in run.records], ["truncated"] * 3)

    def test_thinking_off_for_flash_25_only(self):
        run, _ = self.pilot([good])
        self.assertEqual(run.thinking_for("gemini-2.5-flash-lite"), 0)
        self.assertIsNone(run.thinking_for("gemini-3-flash-preview"))

    def test_all_models_spent_stops(self):
        run, _ = self.pilot([day_quota, day_quota])
        self.assertEqual(run.run(3), [])

    def test_summary(self):
        run, _ = self.pilot([good, garbage, good])
        recs = run.run(3)
        s = RunSummary(recs, TK).compute()
        self.assertEqual((s["answers"], s["valid"]), (3, 2))
        self.assertEqual(s["codes"], {"ok": 2, "invalid_json": 1})
        self.assertEqual(s["passive_share_of_valid"], 1.0)                 # both valid answers are 'wait'
        self.assertTrue((self.out.path / "responses.jsonl").exists())
        self.assertIn("by_family", s)

    def test_dataset_file_has_only_valid_answers_with_keys_and_header(self):
        run, _ = self.pilot([good, garbage, good])
        run.run(3)
        from teacher.dataset import FILE_NAME, DatasetFile, LabelRecord
        recs = list(DatasetFile(self.out.path / FILE_NAME))
        self.assertEqual(len(recs), 2)                                       # the garbage answer is not a label
        r = recs[0]
        self.assertEqual(r.decision["gesture"], "wait")
        self.assertEqual(r.verdict, "ok")
        self.assertEqual(r.source["index"], 0)
        self.assertEqual(r.source["seed"], 1)
        self.assertIn("teacher", r.source)
        tok = run.sampler.tokenizer
        self.assertEqual(r.context["header"], tok.header())                 # fingerprints travel with the line
        ctx = DecisionContext.loads(json.dumps(r.context), tok)              # and the context loads back
        self.assertEqual(tok.encode(ctx).digest(), run.sampler.sample(0).encoded.digest())
        self.assertNotIn("why", r.to_line())                                 # the teacher's prose is not state
        from teacher.dataset import LineMeta
        line = r.to_line()
        self.assertTrue(line.startswith('{"format":"emergence-labels-1","hdr":"'))      # the short header comes first
        meta = LineMeta.of(line)
        self.assertEqual((meta.hdr, meta.id, meta.synthetic, meta.smoke), (r.hdr, "1:0", False, False))
        self.assertEqual(len(meta.hdr), 17)
        self.assertEqual(LabelRecord.from_line(r.to_line()), r)

    def test_dry_run_writes_files_and_sizes(self):
        info = DryRun(TK, DecisionSchema(TK, "full"), RENDERER, SituationSampler(0)).run(3, self.out)
        for name in ("system.txt", "schema.gemini.json", "schema.json", "grammar.gbnf", "sizes.json", "prompts/0002.txt"):
            self.assertTrue((self.out.path / name).exists(), name)
        self.assertEqual(info["bad_examples"], [])
        self.assertGreater(info["system_chars"], 10000)

    def test_refuses_to_write_in_the_repository(self):
        with self.assertRaises(SystemExit):
            RunDirectory(ROOT / "ai" / "teacher", "x")


if __name__ == "__main__":
    unittest.main()


class IntimateFieldsHiddenNearMinors(unittest.TestCase):
    """D10 by construction: with a possible minor present, the teacher never reads the NPC's orientation or drive
    for intimacy (even unrelated to that person)."""

    def test_hidden_when_a_possible_minor_is_present(self):
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from situations.sampler import SituationSampler
        from teacher.render import SituationRenderer
        sampler, renderer = SituationSampler(seed=4), SituationRenderer()
        seen_minor = seen_adult_only = 0
        for i in range(400):
            sit = sampler.sample(i)
            text = renderer.render(sit)
            minor_here = any(r.type == "ENTITY" and r.fields.get("present")
                             and not (isinstance(r.fields.get("look.age"), (int, float)) and r.fields["look.age"] >= 18)
                             for r in sit.context.records)
            if minor_here:
                seen_minor += 1
                self.assertNotIn("Attracted to", text)
                self.assertNotIn("need_intimacy", text)
                self.assertNotIn("drive.intimacy", text)
            elif "Attracted to" in text:
                seen_adult_only += 1
        self.assertGreater(seen_minor, 20)
        self.assertGreater(seen_adult_only, 5)

