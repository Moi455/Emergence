"""Content refusals counted by family of structure (T12b): finishReason SAFETY or an empty reply."""
import unittest

from teacher.status import content_refused, structure_family


class ContentRefusalTests(unittest.TestCase):
    def test_safety_and_empty_replies_count(self):
        self.assertTrue(content_refused({"finish": "SAFETY", "raw": "{}"}))
        self.assertTrue(content_refused({"finish": "NO_CANDIDATE:{'blockReason': 'SAFETY'}", "raw": ""}))
        self.assertTrue(content_refused({"finish": "STOP", "raw": "  "}))
        self.assertFalse(content_refused({"finish": "STOP", "raw": '{"items": []}'}))
        self.assertFalse(content_refused({"raw": "x"}))

    def test_the_family_is_that_of_the_sampler(self):
        from situations.sampler import STRUCTURES
        for i in range(20):
            self.assertIn(structure_family(0, i), STRUCTURES)
        self.assertEqual(structure_family("x", "y"), "?")


if __name__ == "__main__":
    unittest.main()
