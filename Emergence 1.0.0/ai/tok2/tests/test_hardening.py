"""Round 3 of the review: rehead, exported key rules, pinned pooling, collision repair, [] only for held objects,
giant integers, registry file typing, CLI flags (python3 -m unittest discover -s ai/tok2/tests -t ai)."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tok2 import codecs, DecisionContext, InputVocabulary, Layout, ModelInterface, Record, TokenError, Tokenizer  # noqa: E402
from tok2 import golden, registry  # noqa: E402
from tok2.errors import listing, short  # noqa: E402
from tok2.keys import FIXED_KEYS, KEY  # noqa: E402
from tok2.registry import Registry  # noqa: E402
from tok2.tests.test_registry import VECTOR_FIELDS, changed  # noqa: E402
from tok2.tests.test_tok2 import base  # noqa: E402

TOK = Tokenizer()
LAYOUT = json.loads(golden.LAYOUT_PATH.read_text(encoding="utf-8"))


class Base(unittest.TestCase):
    def refuses(self, *records, known=None):
        with self.assertRaises(TokenError):
            TOK.encode(base(*records, known=known))


class TestRehead(unittest.TestCase):
    def frozen(self):
        return golden.GoldenCases(TOK).frozen_sampler_lines()

    def test_rehead_renews_the_header_and_the_digest_and_keeps_the_records(self):
        gc = golden.GoldenCases(TOK)
        line = self.frozen()[0]
        case = json.loads(line)
        old = copy.deepcopy(case)
        case["context"]["header"] = {"schema": "tok2-context-1", "interface": "0" * 16, "layout": "1" * 16}
        case["expect"]["digest"] = "deadbeef"
        new = json.loads(gc.rehead_line(json.dumps(case)))
        self.assertEqual(new["context"]["header"], TOK.header())
        self.assertEqual(new["context"]["records"], old["context"]["records"])
        self.assertEqual(new["context"]["known_keys"], old["context"]["known_keys"])
        self.assertEqual(new, old)                                    # and the digest is the true one again

    def test_a_stale_header_is_renewed_but_a_wrong_digest_under_a_good_header_is_an_error(self):
        lines = self.frozen()
        stale = json.loads(lines[0])
        stale["context"]["header"]["layout"] = "0" * 16
        liar = json.loads(lines[1])
        liar["expect"]["digest"] = "00000000"                         # a tokenizer regression would look like this
        for field, value in (("digest", "00000000"), ("n", 999), ("ghosts", ["@E1"])):
            bad = json.loads(lines[1])
            bad["expect"][field] = value
            with mock.patch.object(golden.GoldenCases, "frozen_sampler_lines", staticmethod(lambda b=bad: [json.dumps(b)])):
                with self.assertRaises(TokenError, msg=field) as cm:
                    golden.GoldenCases(TOK).frozen()
                self.assertIn("blessed", str(cm.exception))
        patched = [json.dumps(stale), json.dumps(liar)] + lines[2:]
        with mock.patch.object(golden.GoldenCases, "frozen_sampler_lines", staticmethod(lambda: patched)):
            with self.assertRaises(TokenError):
                golden.GoldenCases(TOK).frozen()                      # the liar is caught, the stale header is not the issue
            forced = golden.GoldenCases(TOK).frozen(rehead=True)     # --rehead blesses on purpose
        self.assertEqual(forced[1], lines[1])
        self.assertEqual(forced[0], lines[0])
        stale_only = [json.dumps(stale)] + lines[1:]
        with mock.patch.object(golden.GoldenCases, "frozen_sampler_lines", staticmethod(lambda: stale_only)):
            self.assertEqual(golden.GoldenCases(TOK).frozen(), lines)  # only the header was old: renewed without fuss

    def test_check_fails_on_a_wrong_digest_under_a_correct_header(self):
        lines = self.frozen()
        liar = json.loads(lines[1])
        liar["expect"]["digest"] = "00000000"
        hand = [l for l in golden.CASES_PATH.read_text(encoding="utf-8").splitlines() if not l.startswith('{"name": "sampler')]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cases.jsonl"
            p.write_text("\n".join([lines[0], json.dumps(liar)] + lines[2:] + hand) + "\n", encoding="utf-8")
            with mock.patch.object(golden, "CASES_PATH", p):
                self.assertEqual(golden.main(["--check"]), 1)
                self.assertEqual(golden.main(["--update"]), 1)       # nor does --update bless it silently
                self.assertEqual(golden.main(["--rehead"]), 0)       # only the explicit --rehead does
                self.assertEqual(golden.main(["--check"]), 0)

    def test_a_digest_that_changes_with_unchanged_columns_is_warned_about(self):
        old = golden.CASES_PATH.read_text(encoding="utf-8")
        new_lines = []
        for l in old.splitlines():
            c = json.loads(l)
            if c["name"] == "ok_counts":
                c["expect"]["digest"] = "12345678"
            new_lines.append(json.dumps(c))
        new = "\n".join(new_lines) + "\n"
        lay = copy.deepcopy(LAYOUT)
        self.assertEqual(golden.suspicious_changes(old, new, LAYOUT, lay), [f"ok_counts: {json.loads([l for l in old.splitlines() if 'ok_counts' in l][0])['expect']['digest']} -> 12345678"])
        lay["types"]["BELIEF"]["columns"][0]["col"] += 100            # the columns of BELIEF did change: explained
        self.assertEqual(golden.suspicious_changes(old, new, LAYOUT, lay), [])
        self.assertEqual(golden.suspicious_changes("", new, LAYOUT, LAYOUT), [])
        self.assertEqual(golden.suspicious_changes(old, new, None, LAYOUT), [])

    def test_a_frozen_case_that_no_longer_encodes_is_reported(self):
        case = json.loads(self.frozen()[0])
        case["context"]["records"][0]["fields"]["no_such_field"] = 1
        with self.assertRaises(TokenError) as cm:
            golden.GoldenCases(TOK).rehead_line(json.dumps(case))
        self.assertIn(case["name"], str(cm.exception))

    def test_the_committed_frozen_cases_are_the_ones_of_their_first_draw(self):
        self.assertEqual(len(self.frozen()), 12)
        self.assertEqual(golden.GoldenCases(TOK).frozen(), self.frozen())


class TestCliFlags(unittest.TestCase):
    def test_unknown_flags_are_refused(self):
        self.assertEqual(golden.main(["--chek"]), 2)
        self.assertEqual(registry.main(["--chek"]), 2)
        self.assertEqual(registry.main(["--check", "--updaet"]), 2)
        self.assertEqual(golden.main(["--check"]), 0)
        self.assertEqual(registry.main(["--check"]), 0)


class TestLayoutJsonKeysAndSymbols(unittest.TestCase):
    def test_the_key_rules_are_exported(self):
        k = LAYOUT["keys"]
        self.assertEqual(k["num"], "0|[1-9][0-9]{0,11}")
        self.assertEqual(k["fixed_keys"], list(FIXED_KEYS))
        self.assertEqual(k["fixed_keys"], ["me", "me.mind", "me.state", "wake", "@PLACE"])
        self.assertEqual(k["name_digits_max"], 12)
        self.assertIn("fullmatch", k["rule"])
        self.assertEqual(k["prefixes_in_propositions"], list(InputVocabulary.POINTER_KINDS))
        # a port can rebuild the regex from the export alone
        import re
        key_re = re.compile(rf"(?:{'|'.join(re.escape(x) for x in k['fixed_keys'])}|" + "|".join(
            re.escape(t["key"]) + f"(?:{k['num']})" for t in LAYOUT["types"].values() if t["key"] not in k["fixed_keys"]) + ")")
        for key in ("@E1", "b:0", "t:12", "me", "me.mind", "@PLACE", "wake", "@E999999999999"):
            self.assertTrue(key_re.fullmatch(key), key)
            self.assertTrue(KEY.fullmatch(key), key)
        for key in ("@E01", "@E1\n", "b:", "me1", "@PLACE1", "@E9999999999999", "wake1", "m:-1"):
            self.assertIsNone(key_re.fullmatch(key), key)
            self.assertIsNone(KEY.fullmatch(key), key)

    def test_fixed_keys_are_compared_by_equality_not_by_prefix(self):
        for key in ("me1", "me.mind2", "wake1", "@PLACE1", "mee"):
            self.assertFalse(TOK.layout.types["SELF"].key_ok(key))
        self.assertTrue(TOK.layout.types["SELF_MIND"].key_ok("me.mind"))
        self.assertFalse(TOK.layout.types["SELF"].key_ok("me.mind"))
        self.assertFalse(TOK.layout.types["SELF_MIND"].key_ok("me"))

    def test_reserved_symbols_are_exported_with_their_ids(self):
        res = LAYOUT["reserved_symbols"]
        self.assertEqual([r["symbol"] for r in res], InputVocabulary.reserved())
        for r in res:
            self.assertEqual(LAYOUT["vocabulary"][r["id"]], r["symbol"])
        self.assertEqual(res[0], {"symbol": "<pad>", "id": 0})
        self.assertIn({"symbol": "<name_other>", "id": TOK.vocab.ids["<name_other>"]}, res)

    def test_the_scope_of_the_promise_is_written(self):
        self.assertIn("EXCEPT", LAYOUT["scope"].upper().replace("EXCEPT", "EXCEPT"))
        self.assertIn("language.py", LAYOUT["scope"])
        self.assertIn("bad_prop_", LAYOUT["scope"])
        self.assertNotIn("scope", golden.GoldenLayout.fingerprint_of.__doc__ or "")
        h = copy.deepcopy(LAYOUT)
        h["scope"] = "other"
        self.assertEqual(golden.GoldenLayout.fingerprint_of(h), LAYOUT["fingerprints"]["layout"])
        # keys and reserved symbols ARE in the fingerprint
        h = copy.deepcopy(LAYOUT)
        h["keys"]["name_digits_max"] = 13
        self.assertNotEqual(golden.GoldenLayout.fingerprint_of(h), LAYOUT["fingerprints"]["layout"])

    def test_the_refused_propositions_are_golden_cases(self):
        names = {json.loads(l)["name"]: json.loads(l)["expect"] for l in golden.CASES_PATH.read_text().splitlines()}
        for n in ("bad_prop_wrong_argument_type", "bad_prop_depth_3", "bad_prop_four_pointers", "bad_prop_too_many_symbols",
                  "bad_time_until_beyond"):
            self.assertEqual(names[n], {"error": "TokenError"}, n)
        for n in ("ok_epsilon_unit_components", "ok_time_until_bounds"):
            self.assertIn("digest", names[n])


class TestPinnedPooling(unittest.TestCase):
    def setUp(self):
        self.reg = Registry.load()

    def rename_mass(self, d):
        for t, f in VECTOR_FIELDS:
            spec = d["input"]["token_types"][t]["fields"][f]
            spec["components"][spec["components"].index("mass")] = "weight"
        d["input"]["object_vector"][d["input"]["object_vector"].index("mass")] = "weight"

    def test_pooling_is_recorded_per_component(self):
        e = self.reg.types["SELF"].fields["held"]
        self.assertEqual([c.pool for c in e.components[:2]], ["sum", "max"])
        self.assertTrue(all(c.pool in ("sum", "max") for t in self.reg.types.values() for f in t.fields.values()
                            for c in (f.components or [])))

    def test_renaming_the_mass_is_a_conflict_and_the_message_says_what_to_do(self):
        new = ModelInterface.from_dict(changed(self.rename_mass))
        add, conflicts = self.reg.diff(new)
        text = " ".join(conflicts)
        self.assertIn("sum-pooled component mass", text)
        self.assertIn("SUM_COMPONENTS", text)
        with self.assertRaises(TokenError):
            Tokenizer(new, self.reg)

    def test_a_rename_is_allowed_once_the_new_name_takes_over_the_sum(self):
        new = ModelInterface.from_dict(changed(self.rename_mass))
        with mock.patch.object(codecs, "SUM_COMPONENTS", {"mass", "weight"}):
            add, conflicts = self.reg.diff(new)
            self.assertEqual(conflicts, [])
            up = self.reg.updated(new)
        e = up.types["SELF"].fields["held"]
        self.assertTrue(e.components[0].retired and e.components[0].name == "mass")
        self.assertEqual((e.components[-1].name, e.components[-1].pool), ("weight", "sum"))
        lay = Layout(new, InputVocabulary(new, up.symbols), up)
        codec = lay.types["SELF"].columns["held"].codec
        self.assertEqual(codec.pools[codec.components.index("weight")], "sum")

    def test_the_registry_wins_over_a_change_of_the_code_rule(self):
        # the rule in the code only seeds NEW components; what is registered stays what it was
        with mock.patch.object(codecs, "SUM_COMPONENTS", {"size"}):
            self.assertEqual(self.reg.diff(ModelInterface()), ([], []))
        with mock.patch.object(codecs, "SUM_COMPONENTS", set()):
            e = Tokenizer().encode(base().__class__([Record("SELF", "me", {"held": [{"mass": 2.0}, {"mass": 3.0}]}),
                                                     Record("PLACE", "@PLACE", {})]))
        col = TOK.layout.types["SELF"].columns["held"].codec.cols[0]
        self.assertAlmostEqual(float(e.num[e.keys.index("me"), col]), np.log1p(5.0), places=2)

    def test_the_pooling_is_in_the_layout_fingerprint(self):
        held = next(c for c in LAYOUT["types"]["SELF"]["columns"] if c["name"] == "held")
        self.assertEqual(held["components"][0]["pool"], "sum")
        self.assertEqual(LAYOUT["constants"]["pooled_by_sum"], ["mass"])


class TestInsertionInTheMiddle(unittest.TestCase):
    def test_a_property_declared_in_the_middle_of_the_catalogue_is_appended_in_the_registry(self):
        """The catalogue may declare a new property anywhere; the registry appends it, and the declared order is
        re-recorded, so the next --check is clean (no permanent 'reordered' conflict)."""
        def insert(d):
            d["input"]["object_vector"].insert(3, "zzmid")
            for t, f in VECTOR_FIELDS:
                spec = d["input"]["token_types"][t]["fields"][f]
                spec["components"].insert(3, "zzmid")
                spec["component_scales"].insert(3, "qty")
                spec["component_units"].insert(3, "kg")
        reg = Registry.load()
        new = ModelInterface.from_dict(changed(insert))
        add, conflicts = reg.diff(new)
        self.assertEqual(conflicts, [])
        up = reg.updated(new)
        e = up.types["SELF"].fields["held"]
        self.assertEqual(e.components[-1].name, "zzmid")                       # appended
        self.assertEqual(e.components[-1].rank, 3)                             # declared fourth
        self.assertEqual(up.diff(new), ([], []))
        Layout(new, InputVocabulary(new, up.symbols), up)
        # and swapping two registered components afterwards is still a conflict
        def swap(d):
            insert(d)
            for t, f in VECTOR_FIELDS:
                spec = d["input"]["token_types"][t]["fields"][f]
                for k in ("components", "component_scales", "component_units"):
                    spec[k][0], spec[k][1] = spec[k][1], spec[k][0]
        self.assertTrue(up.diff(ModelInterface.from_dict(changed(swap)))[1])


class TestComingBack(unittest.TestCase):
    def test_a_retired_component_that_returns_takes_its_old_column_without_a_conflict(self):
        reg = Registry.load()

        def drop(d):
            for t, f in VECTOR_FIELDS:
                spec = d["input"]["token_types"][t]["fields"][f]
                i = spec["components"].index("size")
                for k in ("components", "component_scales", "component_units"):
                    del spec[k][i]
        gone = ModelInterface.from_dict(changed(drop))
        mid = reg.updated(gone)
        col = reg.types["SELF"].fields["held"].components[1].col
        self.assertTrue(mid.types["SELF"].fields["held"].components[1].retired)
        self.assertIsNone(mid.types["SELF"].fields["held"].components[1].rank)
        self.assertEqual(mid.diff(gone), ([], []))
        # add something else meanwhile (it is ranked), then bring `size` back where it was declared
        def other(d):
            drop(d)
            for t, f in VECTOR_FIELDS:
                spec = d["input"]["token_types"][t]["fields"][f]
                for k, v in (("components", "zzlate"), ("component_scales", "qty"), ("component_units", "kg")):
                    spec[k].append(v)
        mid2 = mid.updated(ModelInterface.from_dict(changed(other)))
        back = ModelInterface()
        add, conflicts = mid2.diff(back)
        self.assertEqual(conflicts, [])
        self.assertTrue(any("components back" in a for a in add))
        up = mid2.updated(back)
        self.assertEqual(up.types["SELF"].fields["held"].components[1].col, col)
        self.assertFalse(up.types["SELF"].fields["held"].components[1].retired)

    def test_the_reorder_message_agrees_with_the_readme(self):
        def edit(d):
            for t, f in VECTOR_FIELDS:
                spec = d["input"]["token_types"][t]["fields"][f]
                for k in ("components", "component_scales", "component_units"):
                    spec[k][0], spec[k][1] = spec[k][1], spec[k][0]
        _, conflicts = Registry.load().diff(ModelInterface.from_dict(changed(edit)))
        text = " ".join(conflicts)
        self.assertIn("reordered or swapped", text)
        self.assertNotIn("only grows at the end", text)
        self.assertIn("anywhere", text)


class TestNoPositionalVectors(Base):
    def test_a_named_vector_is_a_dict(self):
        n = len(TOK.interface.object_vector)
        for rec in (Record("ENTITY", "@E1", {"dir": [0.0, 1.0]}), Record("ENTITY", "@E1", {"rep": [0.1] * 5}),
                    Record("THING", "@T1", {"props": [1.0] * n}), Record("THING", "@T1", {"dir": (0.0, 1.0)}),
                    Record("SELF", "me", {"time": [0.0, 1.0, 0.5]}), Record("SELF", "me", {"held": [1.0] * n}),
                    Record("ENTITY", "@E1", {"look.held": [0.0] * n})):
            recs = [r for r in base().records if r.type != rec.type] + [rec]
            with self.assertRaises(TokenError, msg=short(rec, 60)) as cm:
                TOK.encode(DecisionContext(recs))
            self.assertIn("positional", str(cm.exception))
        TOK.encode(base(Record("ENTITY", "@E1", {"dir": {"sin": 0.0, "cos": 1.0}})))

    def test_a_list_of_dicts_stays_for_held_objects(self):
        TOK.encode(DecisionContext([Record("SELF", "me", {"held": [{"mass": 1.0}, {"mass": 2.0}]}), Record("PLACE", "@PLACE", {})]))
        self.refuses(Record("THING", "@T1", {"props": [{"mass": 1.0}]}))


class TestRegistryRepairAdvice(unittest.TestCase):
    def test_a_component_conflict_advises_renaming_the_component(self):
        def edit(d):
            d["input"]["token_types"]["SELF"]["fields"]["held"]["component_scales"][1] = "unipolar10"
        _, conflicts = Registry.load().diff(ModelInterface.from_dict(changed(edit)))
        self.assertIn("rename the COMPONENT", " ".join(conflicts))
        self.assertNotIn("rename the field", " ".join(c for c in conflicts if "component size" in c))

    def test_a_reordered_vector_advises_the_component_too(self):
        def edit(d):
            for t, f in VECTOR_FIELDS:
                spec = d["input"]["token_types"][t]["fields"][f]
                for k in ("components", "component_scales", "component_units"):
                    spec[k][0], spec[k][1] = spec[k][1], spec[k][0]
        _, conflicts = Registry.load().diff(ModelInterface.from_dict(changed(edit)))
        self.assertIn("COMPONENT", " ".join(conflicts))

    def test_a_column_collision_explains_how_to_repair_it(self):
        d = Registry.load().to_dict()
        f = d["types"]["BELIEF"]["fields"]
        f["certainty"]["col"] = f["age"]["col"]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.json"
            p.write_text(json.dumps(d))
            with self.assertRaises(TokenError) as cm:
                Registry.load(p)
        msg = str(cm.exception)
        for word in ("merge", "renumber", "MOST RECENT", "no model has been trained", "widths"):
            self.assertIn(word, msg)


class TestRegistryFileTyping(unittest.TestCase):
    def broken(self, edit):
        d = Registry.load().to_dict()
        edit(d)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.json"
            p.write_text(json.dumps(d))
            with self.assertRaises(TokenError):
                Registry.load(p)

    def test_widths_are_mandatory_in_v2(self):
        self.broken(lambda d: d.pop("widths"))

    def test_columns_and_widths_must_be_integers(self):
        a = lambda d: d["types"]["BELIEF"]["fields"]["age"]  # noqa: E731
        self.broken(lambda d: a(d).update(col="3"))
        self.broken(lambda d: a(d).update(col=1.5))
        self.broken(lambda d: a(d).update(col=True))
        self.broken(lambda d: a(d).update(width="1"))
        self.broken(lambda d: a(d).update(width=0))
        self.broken(lambda d: a(d).update(col=-1))
        self.broken(lambda d: d["types"]["SELF"]["fields"]["held"]["components"][0].update(col="x"))
        self.broken(lambda d: d["types"]["SELF"]["fields"]["held"].update(width=3))
        self.broken(lambda d: d["types"]["SELF"]["fields"]["held"]["components"][0].update(pool="avg"))
        self.broken(lambda d: d["widths"].update(num="65"))
        self.broken(lambda d: d["types"]["BELIEF"].update(id="7"))
        self.broken(lambda d: d["symbols"].__setitem__(5, 5))
        self.broken(lambda d: a(d).update(scale=None))

    def test_a_validation_error_is_a_token_error_whatever_its_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.json"
            for text in ("[]", "{}", '{"schema": "tok2-registry-2"}', "nonsense", '{"schema": 5}'):
                p.write_text(text)
                with self.assertRaises(TokenError):
                    Registry.load(p)


class TestRetirementIsAnUpdate(unittest.TestCase):
    def test_dropping_a_field_or_a_type_is_reported_and_written(self):
        reg = Registry.load()
        new = ModelInterface.from_dict(changed(lambda d: d["input"]["token_types"]["ENTITY"]["fields"].pop("rel.rivalry")))
        add, conflicts = reg.diff(new)
        self.assertEqual(conflicts, [])
        self.assertTrue(any("rel.rivalry retired" in a for a in add), add)
        up = reg.updated(new)
        self.assertTrue(up.types["ENTITY"].fields["rel.rivalry"].retired)
        self.assertEqual(up.diff(new), ([], []))

        def drop_type(d):
            del d["input"]["token_types"]["SKILL"]
        new2 = ModelInterface.from_dict(changed(drop_type))
        add2, _ = reg.diff(new2)
        self.assertTrue(any("type SKILL retired" in a for a in add2), add2)
        self.assertTrue(reg.updated(new2).types["SKILL"].retired)


class TestPropositionColumn(unittest.TestCase):
    def test_a_renamed_proposition_field_is_read_at_column_zero(self):
        def rename(d):
            f = d["input"]["token_types"]["BELIEF"]["fields"]
            f["content"] = f.pop("prop")
        new = ModelInterface.from_dict(changed(rename))
        reg = Registry.load()
        up = reg.updated(new)
        e = up.types["BELIEF"].fields
        self.assertTrue(e["prop"].retired)
        self.assertEqual((e["content"].col, e["content"].width), (0, 1))
        tok = Tokenizer(new, up)
        enc = tok.encode(base(Record("BELIEF", "b:1", {"content": "(owns me silver_coin)"})))
        self.assertGreater(int((enc.prop_sym[enc.keys.index("b:1")] != 0).sum()), 2)
        Registry.validate(up)                                       # the retired field at 0 does not collide with the new one
        self.assertEqual(up.widths()["prop"], 1)


class TestHeldObjectsOnly(Base):
    def test_empty_list_is_known_zeros_only_for_held_objects(self):
        for t, f in (("SELF", "held"), ("ENTITY", "look.held")):
            self.assertTrue(TOK.layout.types[t].columns[f].codec.multi, (t, f))
        e = TOK.encode(DecisionContext([Record("SELF", "me", {"held": []}), Record("PLACE", "@PLACE", {})]))
        self.assertEqual(int(e.known[e.keys.index("me")].sum()), len(TOK.interface.object_vector))
        e = TOK.encode(base(Record("ENTITY", "@E1", {"present": True, "look.held": []})))
        self.assertGreater(int(e.known.sum()), 40)

    def test_empty_list_is_refused_for_the_other_vectors(self):
        self.refuses(Record("ENTITY", "@E1", {"rep": []}))
        self.refuses(Record("THING", "@T1", {"props": []}))
        self.refuses(Record("INV", "@T2", {"props": []}))
        self.refuses(Record("ENTITY", "@E1", {"dir": []}))
        self.refuses(Record("THING", "@T1", {"props": [{"mass": 1.0}]}))             # a list of vectors is for held objects
        self.refuses(Record("ENTITY", "@E1", {"rep": [{"honesty": 0.5}]}))
        # unknown stays None or absent
        TOK.encode(base(Record("ENTITY", "@E1", {"rep": None}), Record("THING", "@T1", {"props": None})))
        TOK.encode(base(Record("ENTITY", "@E1", {"rep": {}}), Record("THING", "@T1", {"props": {"mass": 2}})))

    def test_the_interface_flags_the_multi_vectors(self):
        ft = TOK.interface.token_types
        self.assertTrue(ft["SELF"]["fields"]["held"]["multi"] and ft["ENTITY"]["fields"]["look.held"]["multi"])
        self.assertFalse(ft["THING"]["fields"]["props"].get("multi"))


class TestRefTypesRound3(Base):
    def test_gaze_may_rest_on_a_place_and_attention_on_a_noise(self):
        TOK.encode(base(Record("ENTITY", "@E1", {"present": True, "look.gaze": "@PLACE"}),
                        Record("LOCUS", "@L1", {}), Record("ENTITY", "@E2", {"present": True, "look.gaze": "@L1"})))
        known = ["me", "@PLACE", "me.state", "@V3", "h:2"]
        TOK.encode(base(Record("SELF_STATE", "me.state", {"attention": "@V3"}), known=known))
        TOK.encode(base(Record("SELF_STATE", "me.state", {"attention": "h:2"}), known=known))
        self.refuses(Record("SELF_STATE", "me.state", {"attention": "b:2"}), known=known + ["b:2"])
        self.refuses(Record("ENTITY", "@E1", {"present": True, "look.gaze": "b:2"}), known=known + ["@E1", "b:2"])


class TestGiantIntegers(Base):
    BIG = 10 ** 5000

    def test_no_value_error_whatever_the_size(self):
        big, digits = self.BIG, "9" * 5000
        cases = [
            Record("ENTITY", "@E1", {"dist": big}), Record("ENTITY", "@E1", {"rel.trust": big}),
            Record("ENTITY", "@E1", {"rel.trust": -big}), Record("ENTITY", "@E1", {"dist": float(10 ** 300)}),
            Record("ENTITY", "@E1", {"link": big}), Record("ENTITY", "@E1", {"name": big}),
            Record("ENTITY", "@E1", {"name": "n:" + digits}), Record("ENTITY", "@E1", {"link": digits}),
            Record("ENTITY", "@E1", {"look.attire": [digits]}), Record("ENTITY", "@E1", {"rep": {big: 1}}),
            Record("ENTITY", "@E1", {"rep": {digits: 1}}), Record("ENTITY", "@E1", {"dir": {"sin": big}}),
            Record("ENTITY", "@E1" + digits, {}), Record("ENTITY", big, {}), Record(digits, "@E1", {}),
            Record("GOAL", "g:1", {"deadline": big}), Record("GOAL", "g:1", {"deadline": -big}),
            Record("GOAL", "g:1", {"prop": "(has me silver_coin:" + digits + ")"}),
            Record("GOAL", "g:1", {"prop": "(worth silver_coin " + digits + ")"}),
            Record("GOAL", "g:1", {"prop": "(owns me @T" + digits + ")"}),
            Record("GOAL", "g:1", {"prop": "n:" + digits}), Record("BELIEF", "b:1", {"informant": "@E" + digits}),
            Record("BELIEF", "b:1", {"shared": [big]}), Record("SELF", "me", {"held": [{"mass": big}]}),
            Record("SELF", "me", {"held": [{"mass": 4 * 10 ** 6}, {"mass": 7 * 10 ** 6}]}),
        ]
        for rec in cases:
            recs = [r for r in base().records if r.type != rec.type] + [rec]
            with self.assertRaises(TokenError, msg=short(rec, 80)) as cm:
                TOK.encode(DecisionContext(recs, ["me", "@PLACE", "b:1", "g:1", "@E1"]))
            self.assertLess(len(str(cm.exception)), 600)

    def test_giant_integers_are_also_safe_in_serialization_and_known_keys(self):
        with self.assertRaises(TokenError):
            DecisionContext(base().records, [self.BIG]).mind_keys()
        with self.assertRaises(TokenError):
            base(Record("ENTITY", "@E1", {"dist": self.BIG})).dumps(TOK)
        with self.assertRaises(TokenError):
            DecisionContext.loads('{"header": %s, "records": [], "known_keys": [%s]}' % (json.dumps(TOK.header()), "9" * 5000), TOK)

    def test_short_and_listing_never_raise_and_are_bounded(self):
        for x in (self.BIG, -self.BIG, "x" * 10000, [self.BIG] * 100, {1: 2}, object(), np.float32(1), b"\xff" * 500, "‮"):
            self.assertLessEqual(len(short(x)), 60)
        self.assertLessEqual(len(listing([f"item{i}" for i in range(500)])), 260)
        self.assertIn("more", listing([f"item{i}" for i in range(500)]))

    def test_error_messages_are_bounded(self):
        with self.assertRaises(TokenError) as cm:
            TOK.encode(base(Record("ENTITY", "@E1", {"look.attire": ["tattered"] * 7, **{f"zz{i}": 1 for i in range(300)}})))
        self.assertLess(len(str(cm.exception)), 400)
        with self.assertRaises(TokenError) as cm:
            TOK.encode(base(Record("ENTITY", "@E1", {"link": "x" * 5000})))
        self.assertLess(len(str(cm.exception)), 400)
        with self.assertRaises(TokenError) as cm:
            TOK.encode(base(Record("BELIEF", "b:1", {"prop": "(owns " + "zzz " * 200 + ")"})))
        self.assertLess(len(str(cm.exception)), 400)


class TestKnownKeysAssignment(unittest.TestCase):
    def test_known_keys_assigned_later_is_checked_and_materialised(self):
        c = base()
        c.known_keys = ["me", "@PLACE", "@E5"]
        self.assertIsInstance(c.known_keys, frozenset)
        c.known_keys = (k for k in ("me", "@PLACE"))
        self.assertEqual(c.known_keys, frozenset({"me", "@PLACE"}))
        c.known_keys = None
        self.assertIsNone(c.known_keys)
        for bad in ("abc", 5, [["x"]], b"abc"):
            with self.assertRaises(TokenError):
                c.known_keys = bad
        self.assertIsNone(c.known_keys)


if __name__ == "__main__":
    unittest.main()
