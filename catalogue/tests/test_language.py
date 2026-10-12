"""Tests of the inner-language validator: the bare mode used for the propositions stored in records."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import language  # noqa: E402


class TestBareExpression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vocab = language.Vocabulary(Catalogue.load())

    def bare(self, text):
        return language.Expression(text, self.vocab, bare=True)

    def test_a_bare_proposition_is_valid_without_a_mood(self):
        for text in ("(owns me @T1)", "(has @E1 silver_coin:3)", "(past (did me give silver_coin (to @E1)))"):
            self.assertTrue(self.bare(text).ok, self.bare(text).problems)

    def test_the_same_text_is_not_an_utterance(self):
        self.assertFalse(language.Expression("(owns me @T1)", self.vocab).ok)
        self.assertTrue(language.Expression("(assert (owns me @T1))", self.vocab).ok)

    def test_a_mood_or_formula_is_refused_in_bare_mode(self):
        self.assertFalse(self.bare("(assert (owns me @T1))").ok)
        self.assertFalse(self.bare("(request (did me give silver_coin (to @E1)))").ok)

    def test_the_other_limits_still_apply(self):
        self.assertFalse(self.bare("(owns me no_such_word)").ok)
        self.assertFalse(self.bare("(owns me)").ok)                         # arity
        self.assertFalse(self.bare("(and " * 18 + "(owns me @T1)" + ")" * 18).ok)   # too many symbols

    def test_a_bare_citation_is_a_proposition_like_in_an_assert(self):
        self.assertTrue(language.Expression("(assert b:7)", self.vocab).ok)
        for text in ("b:7", "m:2", "g:1", " b:7 "):
            e = self.bare(text)
            self.assertTrue(e.ok, (text, e.problems))
            self.assertEqual(e.root, text.strip())
            self.assertEqual(e.intimate_symbols(), [])
        for text in ("@E1", "n:7", "b:7 b:8", "b:07x", "(b:7)", "b:7\n(owns me @T1)"):
            self.assertFalse(self.bare(text).ok, text)
        self.assertFalse(language.Expression("b:7", self.vocab).ok)      # as an utterance it is not one

    def test_digits_are_ascii(self):
        self.assertFalse(self.bare("(owns me @T٣)").ok)               # an Arabic-Indic digit
        self.assertFalse(self.bare("(has me silver_coin:²)").ok)       # a superscript two is isdigit() too


if __name__ == "__main__":
    unittest.main()
