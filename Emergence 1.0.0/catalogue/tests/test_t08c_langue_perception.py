"""T08c : manières décrites par leur forme, mots de la langue, perception de l'âge et des odeurs, temps des cultures."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue, SEASONS  # noqa: E402
import budget  # noqa: E402
import language  # noqa: E402
import model_interface  # noqa: E402

# Terms that give a MEANING (an emotion, a social intention, a verdict) to a manner; a manner is a form only (D28).
EVALUATIVE = set("""complicity complicit shame ashamed guilt guilty contempt mockery flirt threat conspiracy insolent humble sly
sincere false honest happy sad joyful angry afraid proud gentle rude polite kind mean nasty nice good bad beautiful ugly
pleasant unpleasant hostile friendly cold_hearted cruel
honte honteux fier fière sincère hypocrite moqueur moqueuse menaçant menaçante menace joyeux joyeuse triste méprisant
méprisante mépris poli polie impoli grossier grossière gentil gentille méchant méchante humble insolent insolente
complice sournois sournoise honnête faux fausse mensonge peur peureux colère joie bon bonne mauvais mauvaise beau belle
laid laide agréable désagréable hostile amical amicale cruel cruelle exprime exprimant signifie traduit manifeste
trahit révèle séduisant séduisante ironique sarcastique""".split())


class TestT08c(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()
        cls.vocab = language.Vocabulary(cls.cat)
        cls.act = cls.cat["action"]

    def param(self, action, name):
        return next(p for p in self.act[action].params if p.name == name)

    def test_new_manner_values_are_forms_not_social_meanings(self):
        """A manner says HOW the body moves (a form), never what it means (D28). Each new value must be described in the
        parameter's note by a form (`valeur = description` or `valeur : description`, at least three words), and that
        description, like the value itself, must hold no evaluative, emotional or social term."""
        added = {("speak", "tone"): {"rising", "trembling", "low_slow", "drawling"}, ("take", "from"): {"growing"},
                 ("work", "motion"): {"twist"}, ("examine", "sense"): {"hear"},
                 ("sign", "kind"): {"wink", "cover_face", "trace_sign"}}
        for (a, n), vals in added.items():
            p = self.param(a, n)
            self.assertTrue(vals <= set(p.values), (a, n))
            for v in vals:
                self.assertFalse(set(v.split("_")) & EVALUATIVE, f"{a}.{n}={v}: the value itself judges")
                m = re.search(r"(?:^|[;,]\s*|\s)" + re.escape(v) + r"\s*[=:]\s*([^;]+)", p.note)
                self.assertIsNotNone(m, f"{a}.{n}={v}: no form note in {p.note!r}")
                words = re.findall(r"[a-zà-ÿœ']+", m.group(1).lower())
                self.assertGreaterEqual(len(words), 3, f"{a}.{n}={v}: description too short {m.group(1)!r}")
                judging = set(words) & EVALUATIVE
                self.assertFalse(judging, f"{a}.{n}={v}: evaluative terms {judging}")
        self.assertIn("forme de la voix", self.param("speak", "tone").note)
        # the checker is not vacuous: a social description is caught
        self.assertTrue(set(re.findall(r"[a-zà-ÿœ']+", "la voix exprime la honte, menaçante")) & EVALUATIVE)

    def test_hear_and_twist_stay_outside_the_minor_whitelists(self):
        self.assertNotIn("hear", self.act["examine"].minor_whitelist["sense"])
        self.assertNotIn("twist", self.act["work"].minor_whitelist["motion"])

    def test_put_where_takes_an_animal_and_a_pointer_to_a_beast_is_accepted(self):
        self.assertIn("animal", self.param("put", "where").accepts)
        self.assertTrue(language.Expression("(request (did you put @T4 (where donkey)))", self.vocab).ok)
        self.assertFalse(language.Expression("(request (did you put @T4 (where @E5)))", self.vocab).ok)   # une personne, non

    def test_member_takes_a_person_or_a_group_but_never_an_object(self):
        c = self.cat["concept"]["member"]
        self.assertEqual(c.arg_classes, [["agent", "group"], ["group"]])
        self.assertEqual(c.args, ["agent", "group"])                # la signature de tok-2 (ai/tok2/golden) ne bouge pas
        ok = lambda t, k=None: language.Expression(t, self.vocab, pointer_kinds=k or {}).ok   # noqa: E731
        self.assertTrue(ok("(assert (member @G2 @G1))"))
        self.assertTrue(ok("(assert (member @E2 @G1))"))
        self.assertTrue(ok("(assert (member us @G1))"))
        self.assertFalse(ok("(assert (member @T1 @G1))", {"@T1": "knife"}))
        self.assertFalse(ok("(assert (member @E2 @T1))", {"@T1": "knife"}))

    def test_status_repeat_outcome_and_cause_values_have_a_word(self):
        v = self.cat["variable"]
        for var in ("i_status", "i_repeat", "w_outcome"):
            for val in v[var].values:
                self.assertIn(val, self.vocab.cats, f"{var}={val} sans mot")
        for cause in ("goal_check", "occasion", "idle"):
            self.assertIn(cause, self.vocab.cats)

    def test_age_and_smell_are_perceived_as_words(self):
        v = self.cat["variable"]
        self.assertEqual((v["pc_age_seen"].scale, v["pc_age_seen"].token), ("word", "THING.age"))
        self.assertEqual((v["pp_smell_seen"].scale, v["pp_smell_seen"].list_of, v["pp_smell_seen"].token), ("list", "word", "PLACE.smell"))
        self.assertNotIn("made_at", v["pc_age_seen"].token)       # l'instant de fabrication reste au moteur
        for w in ("new", "worn", "old", "smoky", "putrid", "aromatic"):
            self.assertTrue(self.vocab.is_(w, "age") or self.vocab.is_(w, "odor"), w)
        self.assertTrue(language.Expression("(assert (appears @T2 old))", self.vocab).ok)

    def used_words(self):
        """Words that something really uses: a value of a variable, of a gesture parameter or of a token field of the
        model interface, a word category a variable declares it draws from, or a word of a probe's utterance or trace
        (the story notes do not count: they only list the words)."""
        used = set()
        for v in self.cat["variable"].values():
            used |= set(v.values or [])
            for c in {c for w, cs in self.vocab.cats.items() for c in cs}:
                if f"`{c}`" in v.note and v.scale in ("word", "list"):
                    used |= {w for w, cs in self.vocab.cats.items() if c in cs}
        for a in self.act.values():
            for p in a.params:
                used |= set(p.values or [])
        for fields in model_interface.ModelInterface.EXPLICIT.values():
            for f in fields.values():
                used |= set(f.get("values") or [])
        for st in self.cat["story"].values():
            for line in list(st.utterances) + list(st.trace):
                used |= set(re.findall(r"[a-z_]+", line))
        return used

    def test_every_new_word_is_used_by_a_variable_a_gesture_or_a_probe(self):
        new = {"plan_state": "running suspended blocked done abandoned failed interrupted limit_reached",
               "plan_repeat": "once every", "wake_cause": "goal_check occasion idle",
               "odor": "smoky sweet sour acrid musty putrid aromatic rancid", "age": "new worn old",
               "manner": "wink cover_face trace_sign"}
        used = self.used_words()
        for category, words in new.items():
            for w in words.split():
                self.assertTrue(self.vocab.is_(w, category), f"{w} is not a {category} word")
                self.assertIn(w, used, f"{w} ({category}) is in the grammar but nothing uses it")
        self.assertNotIn("zzz_unused_word", used)                          # the check can fail
        self.assertIn("watch_rota_interrupted", self.cat["story"])

    def test_crops_and_herds_carry_their_times(self):
        sp = self.cat["species"]
        for s in sp.values():
            for x in s.sow_seasons:
                self.assertIn(x, SEASONS)
        crops = ["wheat", "barley", "oats", "rye", "beans", "cabbage", "turnip", "onion", "carrot", "flax", "hemp"]
        for c in crops:
            self.assertTrue(sp[c].sow_seasons and sp[c].days_to_mature > 0 and sp[c].harvest_window_days > 0, c)
        for a in ("sheep", "goat", "cow", "chicken", "goose", "bee"):
            self.assertGreater(sp[a].product_regrow_days, 0, a)
        self.assertEqual(sp["wheat"].sow_seasons, ["autumn"])

    def test_budgets_after_t08c(self):
        s = budget.counted_slots(self.cat)
        self.assertLessEqual(len(self.vocab.words), budget.GRAMMAR_WORDS_MAX)
        self.assertLessEqual(len(self.vocab.kinds), budget.KINDS_MAX)
        self.assertLessEqual(len(self.cat.object_vector()), budget.OBJECT_VECTOR_MAX)
        self.assertLessEqual(len(self.cat["action"]), budget.MAX_GESTURES)
        self.assertLessEqual(len(s["THING"]), budget.BUDGET["THING"])
        self.assertLessEqual(len(s["PLACE"]), budget.BUDGET["PLACE"])
        conds = [c for c in self.cat["concept"].values() if c.category == "condition"]
        self.assertEqual(len(conds), 26)
        self.assertLessEqual(len(conds), 32)
        for p in self.act.values():
            for prm in p.params:
                if prm.type == "enum" and not prm.ordinal:
                    self.assertLessEqual(len(prm.values), 16, (p.id, prm.name))


if __name__ == "__main__":
    unittest.main()
