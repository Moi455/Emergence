"""T22: the timing table of the gestures is generated from actions.toml and follows the gesture registry."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import gen_act_timing  # noqa: E402


class TestGenActTiming(unittest.TestCase):
    def test_header_is_up_to_date(self):
        self.assertEqual(gen_act_timing.OUT.read_text(encoding="utf-8"), gen_act_timing.build(),
                         "regenerate: python3 catalogue/tools/gen_act_timing.py")

    def test_rows_follow_the_gesture_registry_order(self):
        text = (ROOT.parent / "engine" / "social" / "generated" / "emergence" / "social" / "catalogue_gen.h").read_text(encoding="utf-8")
        names = re.search(r"kGestureNames = \{\s*(.*?)\s*\};", text, re.S).group(1)
        registry = re.findall(r'"([a-z_]+)"', names)
        rows = re.findall(r'^  \{"([a-z_]+)", (?:true|false), (?:true|false), \d+\},$', gen_act_timing.build(), re.M)
        self.assertEqual(rows, registry)

    def test_every_gesture_has_a_cadence_and_the_productive_ones_are_the_six_known(self):
        actions = gen_act_timing.load("actions.toml")["action"]
        self.assertTrue(all(int(a["cadence_ms"]) > 0 for a in actions))
        self.assertEqual(sorted(a["id"] for a in actions if a.get("productive")),
                         ["channel", "operate", "scoop", "shape", "tie", "work"])


if __name__ == "__main__":
    unittest.main()
