"""T18: the tables of the laws of matter (engine/act/generated/.../matter_gen.h) follow the catalogue and never renumber."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import gen_matter  # noqa: E402


class GenMatterTest(unittest.TestCase):
    def test_gen_matter_stable(self):
        files = gen_matter.build()
        for path, text in files.items():
            self.assertEqual(path.read_text(encoding="utf-8"), text, "regenerate: python3 catalogue/tools/gen_matter.py")

    def test_registry_is_append_only_and_has_the_laws(self):
        reg = json.loads(gen_matter.REGISTRY.read_text(encoding="utf-8"))
        names = [e["name"] for e in reg["processes"]]
        for p in ("cut", "split", "fracture", "crush", "extract", "till", "assemble", "bind", "carve", "collapse", "disassemble", "abrade"):
            self.assertIn(p, names)
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
