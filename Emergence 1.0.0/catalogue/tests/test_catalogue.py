"""Tests of the catalogue: loading, validation, and the layer rules (python3 -m unittest discover -s catalogue/tests)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import Catalogue  # noqa: E402


class TestCatalogue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()

    def test_valid(self):
        self.assertEqual(self.cat.validate(), [])

    def test_stories_exist(self):
        self.assertGreaterEqual(len(self.cat["story"]), 100)

    def test_every_component_is_used(self):
        used = {c for e in self.cat["entity"].values() for c in e.components}
        used |= {c.id for c in self.cat["component"].values() if c.part_of in used}
        self.assertEqual(sorted(set(self.cat["component"]) - used), [])

    def test_engine_materials_are_read_not_copied(self):
        engine = [m for m in self.cat["material"].values() if m.num >= 0]
        self.assertGreaterEqual(len(engine), 34)
        self.assertTrue(all(m.file == "engine/data/materials.csv" for m in engine))

    def test_only_agents_have_a_transformer(self):
        self.assertEqual([e.id for e in self.cat["entity"].values() if e.driven_by == "transformer"], ["agent"])

    def test_unplanned_assembly_has_properties(self):
        # a knife lashed to a stick: no archetype needed for it to cut, pierce and reach
        props = self.cat.item_properties(["blade:iron", "point:iron", "shaft:oak_raw", "cord:rope_fiber"])
        self.assertTrue({"edge", "point", "handle", "reach", "binds"} <= props)

    def test_every_form_is_used_by_a_known_type(self):
        used = {p.partition(":")[0] for it in self.cat["item_type"].values() for p in it.parts}
        self.assertEqual(sorted(set(self.cat["form"]) - used), [])

    def test_many_known_types(self):
        self.assertGreaterEqual(len(self.cat["item_type"]), 400)

    def test_engine_only_component_refuses_model_writer(self):
        cat = Catalogue()
        cat._add("component", {"id": "body", "engine_only": True}, "test")
        cat._add("variable", {"id": "pain", "holder": "body", "writer": ["T_jump"]}, "test")
        self.assertTrue(any("engine-only" in p for p in cat.validate()))

    def test_ai_budget(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import budget
        s = budget.slots(self.cat)
        for typ, b in budget.BUDGET.items():
            self.assertLessEqual(len(s.get(typ, ())), b, typ)
        self.assertLessEqual(sum(budget.TOKENS.values()), budget.MAX_TOKENS)
        import language
        self.assertLessEqual(len(language.Vocabulary(self.cat).words), budget.GRAMMAR_WORDS_MAX)
        self.assertLessEqual(len(self.cat.object_vector()), budget.OBJECT_VECTOR_MAX)

    def test_hidden_properties_never_seen(self):
        seen = set(self.cat.perceptible_properties())
        for pid in ("toxicity", "magic_power", "key_for", "edible", "unlocks", "shapes_matter"):
            self.assertNotIn(pid, seen, pid)

    def test_no_truth_scale_in_tokens(self):
        for v in self.cat["variable"].values():
            if v.token:
                self.assertNotEqual(v.scale, "id", v.id)
                self.assertNotEqual(v.visibility, "engine", v.id)

    def test_violence_is_one_gesture(self):
        # Monsieur, 9 Oct: a slap, a punch, a beating and blows until death are ONE gesture with a manner
        force = {a.id for a in self.cat["action"].values() if a.family == "force"}
        for sid in ("slap_after_insult", "punch_in_brawl", "beating_near_death", "killed_by_blows"):
            st = self.cat["story"][sid]
            self.assertEqual(st.status, "expressible", sid)
            self.assertIn("strike", st.actions, sid)
            hitting = [a for a in st.actions if a in force and a not in ("grab", "push", "guard")]
            self.assertEqual(hitting, ["strike"], sid)

    def test_touch_is_intimate_only_by_manner(self):
        touch = self.cat["action"]["touch"]
        self.assertFalse(touch.intimate)
        manner = [p for p in touch.params if p.name == "manner"][0]
        self.assertEqual(sorted(manner.intimate_values), ["intimate", "romantic"])
        self.assertFalse(set(touch.minor_whitelist["manner"]) & set(manner.intimate_values))

    def test_every_contact_gesture_has_a_minor_whitelist(self):
        for a in self.cat["action"].values():
            if any(p.type == "ref" and "agent" in p.accepts for p in a.params):
                self.assertIsNotNone(a.contact, a.id)                      # D10: contact must be declared
            if a.contact and a.minor_person_ok and a.family != "force":
                self.assertTrue(a.minor_whitelist, a.id)
                zones = set(a.minor_whitelist.get("contact_zone", []))
                self.assertTrue(zones <= {"head", "shoulder", "arms", "hands", "back", "legs"}, a.id)

    def test_speech_probes_need_no_social_verb(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import language
        vocab = language.Vocabulary(self.cat)
        probes = [s for s in self.cat["story"].values() if s.utterances]
        self.assertGreaterEqual(len(probes), 11)
        for st in probes:
            for u in st.utterances:
                e = language.Expression(u, vocab)
                self.assertTrue(e.ok, (st.id, e.problems))

    def test_intimate_manner_is_caught_in_language(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import language
        e = language.Expression("(request (did you touch me (how romantic)))", language.Vocabulary(self.cat))
        self.assertIn("romantic", e.intimate_symbols())

    def test_one_gesture_many_judgements(self):
        # the same take can be judged theft by one witness and taking back by another; never an option
        self.assertIn("theft", self.cat["interpretation"])
        self.assertFalse(set(self.cat["interpretation"]) & set(self.cat["action"]))
        st = self.cat["story"]["take_back_own"]
        self.assertEqual(st.actions, ["take"])
        self.assertTrue({"theft", "taking_back"} <= set(st.interpretations))

    def test_model_interface_is_up_to_date(self):
        import model_interface
        path = model_interface.OUT
        self.assertTrue(path.exists(), "run python3 catalogue/tools/model_interface.py")
        self.assertEqual(path.read_text(encoding="utf-8"), model_interface.ModelInterface(self.cat).text(),
                         "catalogue changed: regenerate catalogue/generated/model_interface.json")

    def test_old_contract_fully_migrated(self):
        old = Path(__file__).resolve().parents[2] / "ai" / "npc_pipeline"
        if not (old / "plan_contract.py").exists():
            self.skipTest("the old contract (ai/npc_pipeline) is not in this package; migration.toml keeps its mapping")
        sys.path.insert(0, str(old))
        import plan_contract
        mig = self.cat["migration"]
        for f in plan_contract.FUNCTIONS:
            self.assertIn(f, mig, f)
        for c in plan_contract.CONDITIONS:
            self.assertIn("cond_" + c, mig, c)
        for social in ("steal", "blackmail", "deceive", "threaten", "insult", "bribe"):
            self.assertIn(mig[social].becomes, ("interpretation", "speech"), social)

    def test_interpretation_cues_are_perceptible_and_norms_parse(self):
        import re as _re
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import budget, language
        slots = budget.slots(self.cat)
        vocab = language.Vocabulary(self.cat)
        for i in self.cat["interpretation"].values():
            for cue in i.cues:
                m = _re.match(r"^([A-Z_]+)(?:\.([\w.]+))?(?:=\S+)? : ", cue)
                self.assertIsNotNone(m, (i.id, cue))
                typ, fld = m.group(1), m.group(2)
                self.assertIn(typ, slots, (i.id, cue))
                if fld:
                    self.assertIn(fld, slots[typ], (i.id, cue))
            for n in i.norms:
                e = language.Expression(f"(assert {n})", vocab)
                self.assertTrue(e.ok, (i.id, n, e.problems))

    def test_cpp_tables_and_vectors_are_up_to_date(self):
        import gen_cpp
        self.assertEqual(gen_cpp.OUT.read_text(encoding="utf-8"), gen_cpp.CppGenerator(self.cat).generate(),
                         "regenerate: python3 catalogue/tools/gen_cpp.py")
        sg = gen_cpp.StateGenerator(self.cat)
        self.assertEqual(gen_cpp.STATE_OUT.read_text(encoding="utf-8"), sg.generate_state())
        self.assertEqual(gen_cpp.VOCAB_OUT.read_text(encoding="utf-8"), sg.generate_vocab())

    def test_forbidden_action_is_caught(self):
        cat = Catalogue()
        cat._add("action", {"id": "blackmail", "family": "communicate"}, "test")
        self.assertTrue(any("social scheme" in p for p in cat.validate()))

    def test_unknown_field_is_caught(self):
        cat = Catalogue()
        cat._add("variable", {"id": "x", "writer": ["engine"], "colour": 3}, "test")
        self.assertTrue(any("unknown fields" in p for p in cat.validate()))


class TestTimeFields(unittest.TestCase):
    """T07: the optional time and matter fields of actions, processes, species, duration levels and illnesses."""

    @staticmethod
    def problems(kind, row, strict=False, extra=()):
        cat = Catalogue()
        for k, r in extra:
            cat._add(k, r, "test")
        cat._add(kind, row, "test")
        mine = f"{kind} {row['id']}:"                     # an empty catalogue has other problems: keep this entry's only
        return [x for x in cat.validate(strict=strict) if x.startswith(mine) or "unknown fields" in x]

    def test_real_catalogue_has_no_such_field_yet(self):
        cat = Catalogue.load()
        self.assertTrue(all(a.natural_end is None and a.cadence_ms == 0 and not a.productive for a in cat["action"].values()))
        self.assertEqual(cat["duration_level"], {})
        self.assertEqual(cat["illness"], {})

    def test_action_fields_accepted(self):
        row = {"id": "chop", "family": "force", "natural_end": False, "cadence_ms": 900, "productive": True}
        self.assertEqual(self.problems("action", row), [])

    def test_action_negative_cadence(self):
        self.assertTrue(any("cadence_ms" in p for p in self.problems("action", {"id": "chop", "cadence_ms": -1})))

    def test_strict_requires_gesture_time(self):
        p = self.problems("action", {"id": "chop"}, strict=True)
        self.assertTrue(any("natural_end undeclared" in x for x in p) and any("cadence_ms undeclared" in x for x in p))
        self.assertFalse(any("undeclared" in x for x in self.problems("action", {"id": "chop", "natural_end": True, "cadence_ms": 500}, strict=True)))
        self.assertFalse(any("undeclared" in x for x in self.problems("action", {"id": "chop"})))

    def test_process_fields_accepted(self):
        mats = [("material", {"id": "grain"}), ("material", {"id": "flour"})]
        row = {"id": "mill", "trigger": "tool", "clock": "game", "nominal_game_s": 600, "consumes": ["grain"], "produces": ["flour"]}
        self.assertEqual(self.problems("process", row, extra=mats), [])

    def test_process_bad_clock_duration_and_matter(self):
        p = self.problems("process", {"id": "x", "clock": "sundial", "nominal_game_s": -5, "consumes": ["nope"], "produces": ["nada"]})
        for needle in ("clock", "nominal_game_s", "consumes unknown", "produces unknown"):
            self.assertTrue(any(needle in x for x in p), needle)

    def test_species_fields_accepted(self):
        row = {"id": "wheat", "kingdom": "plant", "sow_seasons": ["autumn"], "days_to_mature": 200,
               "harvest_window_days": 20, "product_regrow_days": 0}
        self.assertEqual(self.problems("species", row), [])

    def test_species_bad_season_and_negative(self):
        p = self.problems("species", {"id": "wheat", "kingdom": "plant", "sow_seasons": ["monsoon"], "days_to_mature": -1})
        self.assertTrue(any("sow_season" in x for x in p) and any("days_to_mature" in x for x in p))

    def test_duration_level(self):
        self.assertEqual(self.problems("duration_level", {"id": "brief", "game_s": 120}), [])
        self.assertTrue(any("game_s" in x for x in self.problems("duration_level", {"id": "brief"})))

    def test_illness_accepted(self):
        row = {"id": "fever", "transmission": ["air", "contact"], "incubation_days": 2, "course_days": 6,
               "symptoms": ["pale"], "lethality": 5}
        self.assertEqual(self.problems("illness", row, extra=[("percept_word", {"id": "pale", "category": "sign"})]), [])

    def test_illness_bad_fields(self):
        p = self.problems("illness", {"id": "x", "transmission": ["telepathy"], "symptoms": ["ghost"], "lethality": 101, "course_days": -1})
        for needle in ("transmission", "symptom", "lethality", "negative"):
            self.assertTrue(any(needle in x for x in p), needle)

    def test_process_allowed_in_body_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "body.toml").write_text('[[process]]\nid = "heal"\nclock = "calendar"\nnominal_game_s = 86400\n', encoding="utf-8")
            cat = Catalogue.load(Path(d))
        self.assertEqual(cat.load_errors, [])
        self.assertEqual(cat["process"]["heal"].file, "body.toml")

    def test_unknown_field_still_strict_on_new_kinds(self):
        self.assertTrue(any("unknown fields" in x for x in self.problems("illness", {"id": "x", "cure": 1})))

    def test_render_shows_new_fields(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import render
        cat = Catalogue()
        cat._add("action", {"id": "chop", "natural_end": False, "cadence_ms": 900, "productive": True}, "test")
        cat._add("process", {"id": "mill", "clock": "game", "nominal_game_s": 600}, "test")
        cat._add("species", {"id": "wheat", "kingdom": "plant", "days_to_mature": 200}, "test")
        cat._add("duration_level", {"id": "brief", "game_s": 120}, "test")
        cat._add("illness", {"id": "fever", "lethality": 5}, "test")
        out = render.render(cat)
        for needle in ("| non | 900 | oui |", "| game | 600 |", "| 200 |", "| brief |", "| fever |"):
            self.assertIn(needle, out)


if __name__ == "__main__":
    unittest.main()
