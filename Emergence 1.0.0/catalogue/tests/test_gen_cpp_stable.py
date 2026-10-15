"""T02: the C++ identifiers are stable. A catalogue that grows (a gesture, a variable, a word) or shrinks must not
move any numeric id already generated (enums Gesture, Condition, Var; the order of kWords / kKinds)."""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import gen_cpp  # noqa: E402

NEW_ACTION = '''
[[action]]
id = "aaa_new_gesture"
family = "care"
label_fr = "geste factice de test (trie avant tous les autres)"
params = [
  { name = "target", type = "ref", accepts = ["agent", "animal"] },
  { name = "manner", type = "enum", values = ["gentle", "firm"] },
]
contact = true
party_params = ["target"]
minor_person_ok = true
effects = "test"
perceptibility = "vu"
duration = "bref"
animation = ["idle"]
'''
NEW_VARIABLE = '''
[[variable]]
id = "aaa_new_variable"
label_fr = "variable factice de test"
holder = "mind_dynamic"
scale = "unipolar10"
writer = ["engine"]
visibility = "private"
'''
NEW_WORD = '''
concept = [
  { id = "aaa_new_word", category = "predicate", args = ["entity"], label_fr = "mot factice de test" },
]
'''


def drop_block(path: Path, header: str) -> None:
    txt = path.read_text(encoding="utf-8")
    start = txt.index(header)
    end = txt.find("[[action]]", start + 1)
    path.write_text(txt[:start] + (txt[end:] if end >= 0 else ""), encoding="utf-8")


def drop_entry(data: Path, name: str) -> None:
    """Remove the one-line inline-table entry `{ id = "name", ... },` from whichever file holds it."""
    pat = re.compile(r'^[ \t]*\{ id = "%s",.*\},?[ \t]*\n' % re.escape(name), re.M)
    hits = [p for p in sorted(data.glob("*.toml")) if pat.search(p.read_text(encoding="utf-8"))]
    assert len(hits) == 1, (name, hits)
    hits[0].write_text(pat.sub("", hits[0].read_text(encoding="utf-8"), count=1), encoding="utf-8")


def enum_ids(text: str, name: str) -> dict:
    body = re.search(r"enum class %s : [\w:]+ \{(.*?)kCount" % name, text, re.S).group(1)
    ids = [m.group(1) for m in re.finditer(r"^\s+(\w+),", body, re.M)]
    return {n: i for i, n in enumerate(ids)}


def table(text: str, name: str) -> list:
    body = re.search(r"%s = \{(.*?)\n\};" % name, text, re.S).group(1)
    return re.findall(r'"([^"]*)"', body)


class TestGenCppStable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = gen_cpp.build(Catalogue.load())

    def regen(self, tmp: Path, grow: bool = True, edit=None) -> dict:
        """A full gen_cpp run on a temporary copy of the catalogue (grown with a gesture, a variable and a word,
        then `edit(data_dir)`), against the real registries (the AI-side ones read only, the news appended virtually)."""
        data = tmp / "data"
        shutil.copytree(gen_cpp.ROOT / "data", data)
        if grow:
            with open(data / "actions.toml", "a", encoding="utf-8") as f:
                f.write(NEW_ACTION)
            (data / "zz_test_variable.toml").write_text(NEW_VARIABLE, encoding="utf-8")
            (data / "zz_test_word.toml").write_text(NEW_WORD, encoding="utf-8")
        if edit:
            edit(data)
        cat = Catalogue.load(data)
        cat.validate()
        return gen_cpp.build(cat, gen_cpp.Orders(cat, strict=False, var_registry=gen_cpp.VarRegistry(),
                                                 vocab_registry=gen_cpp.VocabRegistry()))

    def grown(self, tmp: Path, drop_action: str | None = None) -> dict:
        return self.regen(tmp, edit=(lambda d: drop_block(d / "actions.toml", f'[[action]]\nid = "{drop_action}"\n'))
                          if drop_action else None)

    def assert_nothing_moved(self, new: dict, retired_enum: dict | None = None, retired_words=(), retired_kinds=()):
        """No numeric id of the shipped generation moved; the removed names are `retired_N` in their own slot."""
        retired_enum = retired_enum or {}
        for enum in ("Gesture", "Condition", "Var"):
            a, b = enum_ids(self.base[gen_cpp.OUT], enum), enum_ids(new[gen_cpp.OUT], enum)
            gone = retired_enum.get(enum, ())
            self.assertEqual({k: v for k, v in b.items() if k in a}, {k: v for k, v in a.items() if k not in gone},
                             f"{enum}: an id moved")
            for name in gone:
                self.assertEqual(b[f"retired_{a[name]}"], a[name], f"{enum}: {name} must stay in its slot")
        for tbl, gone in (("kWords", retired_words), ("kKinds", retired_kinds)):
            pat = r"std::array<std::string_view, \d+> " + tbl
            a, b = table(self.base[gen_cpp.VOCAB_OUT], pat), table(new[gen_cpp.VOCAB_OUT], pat)
            for i, w in enumerate(a):
                self.assertEqual(b[i], f"retired_{i}" if w in gone else w, f"{tbl}[{i}] moved")

    def test_removed_word_keeps_its_slot(self):
        word = "able"
        self.assertIn(word, table(self.base[gen_cpp.VOCAB_OUT], r"std::array<std::string_view, \d+> kWords"))
        with tempfile.TemporaryDirectory() as t:
            new = self.regen(Path(t), grow=False, edit=lambda d: drop_entry(d, word))
        self.assertNotIn(word, table(new[gen_cpp.VOCAB_OUT], r"std::array<std::string_view, \d+> kWords"))
        self.assert_nothing_moved(new, retired_words=(word,))

    def test_removed_variable_keeps_its_slot(self):
        with tempfile.TemporaryDirectory() as t:
            new = self.regen(Path(t), grow=False, edit=lambda d: drop_entry(d, "boredom"))
        self.assert_nothing_moved(new, {"Var": ("boredom",)}, retired_words=("boredom",))
        self.assertIn("true},   // retired: boredom", new[gen_cpp.OUT])

    def test_removed_condition_keeps_its_slot(self):
        with tempfile.TemporaryDirectory() as t:
            new = self.regen(Path(t), grow=False, edit=lambda d: drop_entry(d, "c_blocked"))
        self.assert_nothing_moved(new, {"Condition": ("c_blocked",)}, retired_words=("c_blocked",))
        self.assertIn("false", re.search(r"kConditionLive = \{(.*?)\};", new[gen_cpp.OUT], re.S).group(1))

    def test_removed_manner_value_keeps_its_index(self):
        def edit(d):
            txt = (d / "actions.toml").read_text(encoding="utf-8")
            start = txt.index('id = "touch"')
            old = '"gentle", "firm", "playful", "romantic", "intimate"'
            i = txt.index(old, start)
            (d / "actions.toml").write_text(txt[:i] + '"gentle", "firm", "romantic", "intimate"' + txt[i + len(old):], encoding="utf-8")
        with tempfile.TemporaryDirectory() as t:
            new = self.regen(Path(t), grow=False, edit=edit)
        self.assert_nothing_moved(new, retired_words=("playful",))   # the word itself leaves the language
        # the touch.manner param: same value order, same intimate mask, "playful" (index 2) no longer valid
        old_spec = re.search(r'ParamSpec\{"manner", [^\n]*"playful"[^\n]*\}', self.base[gen_cpp.OUT]).group(0)
        self.assertIn('{"gentle", "firm", "playful", "romantic", "intimate"}', old_spec)
        self.assertTrue(old_spec.endswith("0x1f}"))
        new_spec = re.search(r'ParamSpec\{"manner", [^\n]*"playful"[^\n]*\}', new[gen_cpp.OUT]).group(0)
        self.assertIn('{"gentle", "firm", "playful", "romantic", "intimate"}', new_spec)
        self.assertIn("0x18, ", new_spec)
        self.assertTrue(new_spec.endswith("0x1b}"))

    def test_growth_moves_no_identifier(self):
        with tempfile.TemporaryDirectory() as t:
            new = self.grown(Path(t))
        old_h, new_h = self.base[gen_cpp.OUT], new[gen_cpp.OUT]
        for enum, fresh in (("Gesture", "aaa_new_gesture"), ("Var", "aaa_new_variable"), ("Condition", None)):
            a, b = enum_ids(old_h, enum), enum_ids(new_h, enum)
            self.assertEqual({k: v for k, v in b.items() if k in a}, a, f"{enum}: an id moved")
            if fresh:
                self.assertEqual(b[fresh], len(a), f"{enum}: the news must be appended")
        old_v, new_v = self.base[gen_cpp.VOCAB_OUT], new[gen_cpp.VOCAB_OUT]
        for tbl in ("kWords", "kKinds"):
            a = table(old_v, r"std::array<std::string_view, \d+> " + tbl)
            b = table(new_v, r"std::array<std::string_view, \d+> " + tbl)
            self.assertEqual(b[:len(a)], a, f"{tbl}: a word moved")
        self.assertIn("aaa_new_word", table(new_v, r"std::array<std::string_view, \d+> kWords"))
        self.assertNotEqual(old_h, new_h)

    def test_removed_gesture_stays_as_retired_slot(self):
        with tempfile.TemporaryDirectory() as t:
            new = self.grown(Path(t), drop_action="touch")
        a, b = enum_ids(self.base[gen_cpp.OUT], "Gesture"), enum_ids(new[gen_cpp.OUT], "Gesture")
        self.assertEqual(b[f"retired_{a['touch']}"], a["touch"])
        self.assertNotIn("touch", b)
        self.assertEqual({k: v for k, v in b.items() if k in a}, {k: v for k, v in a.items() if k != "touch"})
        self.assertIn(", true},   // retired: touch", new[gen_cpp.OUT])

    def test_shipped_files_are_up_to_date(self):
        for path, text in self.base.items():
            self.assertTrue(path.exists() and path.read_text(encoding="utf-8") == text,
                            f"{path.name} is stale: python3 catalogue/tools/gen_cpp.py")

    def test_var_registry_is_append_only(self):
        reg = gen_cpp.VarRegistry()
        names = reg.names("vars")
        cat = Catalogue.load()
        self.assertEqual(set(names), set(cat["variable"]))
        extra = gen_cpp.VarRegistry.__new__(gen_cpp.VarRegistry)
        extra.path, extra.lists = reg.path, {"vars": reg.entries + [{"name": "gone_var"}]}
        up = extra.updated({"vars": cat["variable"]})
        self.assertEqual(up.names("vars"), names + ["gone_var"])
        self.assertTrue(up.entries[-1].get("retired"))

    # --- T15: world_registry.json (EntityKind, ComponentId) and the schema fingerprint of the EntityStore ---
    @staticmethod
    def world_ids(text: str, enum: str) -> dict:
        return enum_ids(text, enum)

    def test_world_registry_is_append_only(self):
        reg = gen_cpp.WorldRegistry()
        kinds, comps = reg.names("entity_kinds"), reg.names("components")
        cat = Catalogue.load()
        live_k, live_c = gen_cpp.world_live(cat)
        self.assertEqual(set(kinds), set(live_k))
        self.assertEqual(set(comps), set(live_c))
        # removal: stays in its slot, flagged retired; return: takes its old index back, no flag
        gone = reg.updated({"entity_kinds": live_k, "components": [c for c in live_c if c != "flow"]})
        self.assertEqual(gone.names("components"), comps)
        self.assertTrue([e for e in gone.lists["components"] if e["name"] == "flow"][0].get("retired"))
        back = gone.updated({"entity_kinds": live_k, "components": live_c})
        self.assertEqual(back.names("components"), comps)
        self.assertFalse(any(e.get("retired") for e in back.lists["components"]))
        # addition: appended at the end
        grown = reg.updated({"entity_kinds": live_k + ["zz_kind"], "components": live_c + ["zz_comp"]})
        self.assertEqual(grown.names("components"), comps + ["zz_comp"])
        self.assertEqual(grown.names("entity_kinds"), kinds + ["zz_kind"])

    def test_world_growth_moves_no_identifier(self):
        base = self.base[gen_cpp.WORLD_OUT]
        new_comp = ('\n[[component]]\nid = "aaa_zz_world"\nlabel_fr = "composant factice"\nholder = "plant"\n'
                    '\n[[variable]]\nid = "aaa_zz_world_var"\nlabel_fr = "variable factice"\nholder = "aaa_zz_world"\n'
                    'scale = "unipolar10"\nwriter = ["engine"]\nvisibility = "engine"\n')

        def edit(d):
            with open(d / "entities.toml", "a", encoding="utf-8") as f:
                f.write(new_comp)
            txt = (d / "entities.toml").read_text(encoding="utf-8")
            i = txt.index('id = "plant"')
            j = txt.index('"transformation", "lifecycle"', i)
            (d / "entities.toml").write_text(txt[:j] + '"aaa_zz_world", ' + txt[j:], encoding="utf-8")
        with tempfile.TemporaryDirectory() as t:
            new = self.regen(Path(t), grow=False, edit=edit)[gen_cpp.WORLD_OUT]
        for enum in ("EntityKind", "ComponentId"):
            a, b = enum_ids(base, enum), enum_ids(new, enum)
            self.assertEqual({k: v for k, v in b.items() if k in a}, a, f"{enum}: an id moved")
        self.assertEqual(enum_ids(new, "ComponentId")["aaa_zz_world"], len(enum_ids(base, "ComponentId")))
        fp = lambda t: re.search(r"kWorldSchemaFingerprint = (0x[0-9a-f]+)", t).group(1)
        self.assertNotEqual(fp(base), fp(new))   # an old save is refused (SchemaMismatch at load)

    def test_world_removed_component_keeps_its_slot(self):
        base = self.base[gen_cpp.WORLD_OUT]
        with tempfile.TemporaryDirectory() as t:
            def edit(d):
                for v in ("water_level", "water_flow", "ice"):
                    drop_entry(d, v)
            try:
                new = self.regen(Path(t), grow=False, edit=edit)[gen_cpp.WORLD_OUT]
            except Exception as e:   # flow variables are referenced elsewhere: the catalogue refuses, which is also stable
                self.skipTest(f"catalogue refuses the removal: {e}")
        a, b = enum_ids(base, "ComponentId"), enum_ids(new, "ComponentId")
        self.assertEqual({k: v for k, v in b.items() if k in a and k != "flow"}, {k: v for k, v in a.items() if k != "flow"})
        self.assertEqual(b[f"retired_{a['flow']}"], a["flow"])

    def test_world_schema_fingerprint_sees_components_of_a_kind(self):
        base = self.base[gen_cpp.WORLD_OUT]

        def edit(d):   # a component with variables added to a type of entity
            txt = (d / "entities.toml").read_text(encoding="utf-8")
            i = txt.index('id = "fire"')
            j = txt.index('components = ["identity", "spatial", "combustion"', i)
            (d / "entities.toml").write_text(txt[:j] + 'components = ["identity", "spatial", "combustion", "substance"' + txt[j + len('components = ["identity", "spatial", "combustion"'):], encoding="utf-8")
        with tempfile.TemporaryDirectory() as t:
            new = self.regen(Path(t), grow=False, edit=edit)[gen_cpp.WORLD_OUT]
        fp = lambda t: re.search(r"kWorldSchemaFingerprint = (0x[0-9a-f]+)", t).group(1)
        self.assertNotEqual(fp(base), fp(new))


if __name__ == "__main__":
    unittest.main()
