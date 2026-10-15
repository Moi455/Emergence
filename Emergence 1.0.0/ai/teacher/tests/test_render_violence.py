"""The teacher sees situations with an aim of force without any leak of the truth (T12b): no plot summary, motive, form
or true age; the aim is rendered like any other goal."""
import unittest

from situations.sampler import SituationSampler
from teacher.render import SituationRenderer
from teacher.toolkit import Toolkit

SAMPLER = SituationSampler(5)
RENDERER = SituationRenderer(Toolkit())
LEAKS = ("PlotSummary", "kin_revenge", "inheritance", "warning", "aggressor", "hunted", "witness plot", "kind=", "motive")


class RenderViolenceTests(unittest.TestCase):
    def test_violent_situations_render_without_leak(self):
        shown = 0
        for i in range(700):
            sit = SAMPLER.sample(i)
            if sit.plot is None:
                continue
            text = RENDERER.render(sit)
            shown += 1
            for w in LEAKS:
                self.assertNotIn(w, text, (i, w))
            self.assertNotIn("None", text.replace("None of", ""), i)
            # the true ages of the people are never printed as a fact about them
            truth = {f"{p.age:.1f} years" for k, p in sit.people.items() if k != "me"}
            self.assertFalse([t for t in truth if t in text], i)
        self.assertGreater(shown, 20)

    def test_the_render_only_reads_the_records(self):
        sit = SAMPLER.sample(11)
        a = RENDERER.render(sit)
        sit.scene = None
        sit.plot = None
        sit.people = {}
        self.assertEqual(a, RENDERER.render(sit))


if __name__ == "__main__":
    unittest.main()
