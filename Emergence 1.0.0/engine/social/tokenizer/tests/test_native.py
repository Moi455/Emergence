"""Python <-> C++ parity of the tok-2 tokenizer through the C interface (ai/tok2/native.py), plus the static checks of
the tokenizer module (generated header up to date, firewall of the objective fields).

    python3 -m unittest discover -s engine/social/tokenizer/tests -t engine/social/tokenizer/tests    (from the repo root)

The C++ library comes from EM_TOK2_LIB or a build folder (emergence_tok2_capi); without it the parity tests are skipped.
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "ai")); sys.path.insert(0, str(ROOT / "catalogue"))

from tok2 import DecisionContext, Tokenizer  # noqa: E402
from tok2.native import NativeRefusal, NativeTokenizer, NativeUnavailable  # noqa: E402

TOK = ROOT / "engine" / "social" / "tokenizer"
try:
    NATIVE = NativeTokenizer()
except NativeUnavailable:
    NATIVE = None


def same_arrays(py, nat) -> list:
    return [a for a in ("type_id", "num", "known", "cat", "cat_known", "ptr", "ptr_known", "prop_sym", "prop_arity",
                        "prop_depth", "prop_slot", "prop_num")
            if getattr(py, a).tobytes() != nat.arrays[a].tobytes()]


class GeneratedHeader(unittest.TestCase):
    def test_tok2_gen_is_up_to_date(self):
        r = subprocess.run([sys.executable, str(TOK / "gen_tok2.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class Firewall(unittest.TestCase):
    """The tokenizer module reads the NPC's mind through token views only: no objective field, no variable without token."""

    def setUp(self):
        from schema import Catalogue
        self.vars = Catalogue.load().entries["variable"]
        self.sources = [p for p in list((TOK / "include").rglob("*")) + list((TOK / "src").rglob("*"))
                        if p.suffix in (".h", ".cpp")]

    def test_no_engine_variable_is_named(self):
        engine = {v.id for v in self.vars.values() if v.visibility == "engine"}
        for p in self.sources:
            words = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", re.sub(r"//.*", "", p.read_text())))
            self.assertEqual(sorted(words & engine), [], f"{p.name} reads an objective variable")

    def test_every_state_field_has_a_token(self):
        ok = {v.id for v in self.vars.values() if v.token and v.visibility != "engine"}
        known = set(self.vars)
        for p in self.sources:
            text = re.sub(r"//.*", "", p.read_text())
            for w in set(re.findall(r"\.(?:b|m|r|ep|pc|g|i|k|q|lc|pp|ev)_[a-z_]+", text)):
                v = w[1:]
                if v in known:
                    self.assertIn(v, ok, f"{p.name}: {v} has no token in the catalogue")

    def test_tokenizer_never_includes_the_state(self):
        for p in self.sources:
            if p.name in ("candidates.cpp", "candidates.h", "context_builder.cpp", "context_builder.h"):
                continue
            self.assertNotIn("npc_state_gen", p.read_text(), p.name)
            self.assertNotIn("npc_store.h", p.read_text(), p.name)


class ContextBuilderFirewall(unittest.TestCase):
    """T28b: the ContextBuilder reads the NPC's state through the variables of the generated list only, and every one of them
    has a token (or is a derived source declared in gen_tok2.py): never an objective variable, never a variable without token."""

    def test_variables_named_in_the_builder(self):
        from schema import Catalogue
        vs = Catalogue.load().entries["variable"]
        text = re.sub(r"//.*", "", (TOK / "src" / "context_builder.cpp").read_text())
        gen = (TOK / "generated" / "context_map_gen.h").read_text()
        listed = set(re.findall(r'SourceDef\{"[A-Z_]*", "[^"]*", "([a-z_0-9]+)"\}', gen))
        named = {w for w in re.findall(r'"([a-z][a-z_0-9]*)"', text) if w in vs}
        engine = {v.id for v in vs.values() if v.visibility == "engine"}
        self.assertEqual(sorted(named & engine), [], "the builder names an objective variable")
        self.assertEqual(sorted(named - listed), [], "variables read by the builder but absent from the generated list")
        for v in listed:
            if v in vs:
                self.assertNotEqual(vs[v].visibility, "engine", v)

    def test_map_is_up_to_date(self):
        r = subprocess.run([sys.executable, str(TOK / "gen_tok2.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipIf(NATIVE is None, "libemergence_tok2_capi.so not built")
class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tk = Tokenizer()

    def test_fingerprints(self):
        self.assertEqual(NATIVE.layout_fingerprint, self.tk.layout.fingerprint)
        self.assertEqual(NATIVE.interface_fingerprint, self.tk.interface.fingerprint)
        self.assertEqual(NATIVE.vocab_fingerprint, self.tk.vocab.fingerprint)
        self.assertEqual(NATIVE.header(), self.tk.header())

    def test_golden_cases_arrays_bit_for_bit(self):
        n = 0
        for line in (ROOT / "ai" / "tok2" / "golden" / "cases.jsonl").read_text().splitlines():
            d = json.loads(line)
            text = json.dumps(d["context"], separators=(",", ":"))
            if "error" in d["expect"]:
                with self.assertRaises(NativeRefusal, msg=d["name"]):
                    NATIVE.encode_json(text)
                continue
            nat = NATIVE.encode_json(text)
            py = self.tk.encode(DecisionContext.loads(text, self.tk))
            self.assertEqual(same_arrays(py, nat), [], d["name"])
            self.assertEqual(f"{nat.digest:08x}", d["expect"]["digest"], d["name"])
            self.assertEqual(nat.n, py.n)
            n += 1
        self.assertGreater(n, 30)

    def test_sampler_situations_arrays_bit_for_bit(self):
        from situations.sampler import SituationSampler
        s = SituationSampler(7)
        texts, pys = [], []
        for i in range(150):
            sit = s.sample(i)
            texts.append(sit.context.dumps(s.tokenizer))
            pys.append(sit.encoded)
        out, status = NATIVE.encode_batch(texts)
        self.assertEqual(int(status.sum()), 0)
        for t, py, nat in zip(texts, pys, out):
            self.assertEqual(same_arrays(py, nat), [])
            self.assertEqual(nat.digest, py.digest())
            self.assertEqual(NATIVE.encode_json(t).digest, py.digest())      # single-call path too

    def test_deterministic(self):
        line = json.loads((ROOT / "ai" / "tok2" / "golden" / "cases.jsonl").read_text().splitlines()[0])
        text = json.dumps(line["context"], separators=(",", ":"))
        self.assertEqual(NATIVE.encode_json(text).digest, NATIVE.encode_json(text).digest)

    def test_half_rounding_matches_numpy(self):
        rng = np.random.default_rng(1)
        xs = np.concatenate([rng.normal(0, 1, 20000), rng.uniform(-20, 20, 20000), 10 ** rng.uniform(-12, 1.5, 20000),
                             [0.0, -0.0, 1e-9, -1e-9, 65504.0, 65519.9, 5.960464477539063e-8, 2.9802322387695312e-8]])
        for x in xs:
            h = np.float16(float(x))
            want = 0 if h == 0 else int(h.view(np.uint16))
            self.assertEqual(NATIVE.to_half_bits(float(x)), want, repr(float(x)))

    def test_crc32_matches_zlib(self):
        import zlib
        data = bytes(range(256)) * 7
        self.assertEqual(NATIVE.crc32(data), zlib.crc32(data))
        self.assertEqual(NATIVE.crc32(data[:100], NATIVE.crc32(b"abc")), zlib.crc32(data[:100], zlib.crc32(b"abc")))

    def test_c_guards(self):
        import ctypes as C
        # a null text in a batch is refused for that item only
        lib = NATIVE._lib
        good = json.dumps(json.loads((ROOT / "ai" / "tok2" / "golden" / "cases.jsonl").read_text().splitlines()[0])["context"]).encode()
        arr = (C.c_char_p * 2)(None, good)
        lens = (C.c_size_t * 2)(0, len(good))
        bufs = np.zeros(2 * NATIVE.size, np.uint8)
        from tok2.native import _Info
        infos, status = (_Info * 2)(), (C.c_int * 2)()
        ok = lib.em_tok2_encode_batch(NATIVE._h, arr, lens, 2, bufs.ctypes.data, infos, status)
        self.assertEqual((status[0], status[1], ok), (2, 0, 1))
        # a corrupt type id in the buffer is refused by the mask (no shift out of range)
        enc = NATIVE.encode_json(good)
        enc.arrays["type_id"][0] = 200
        with self.assertRaises(NativeRefusal):
            NATIVE.feasibility(enc)

    def test_stale_library_is_refused(self):
        from unittest import mock
        with mock.patch.object(NATIVE._lib, "em_tok2_layout_fingerprint", return_value=1):
            with self.assertRaises(NativeUnavailable):
                NATIVE._check_fresh()

    def test_mask_through_c_interface(self):
        s_rec = [{"type": "SELF", "key": "me", "fields": {}}, {"type": "PLACE", "key": "@PLACE", "fields": {}},
                 {"type": "THING", "key": "@T1", "fields": {"kind": "mortar_tub", "props": {"graspable": False}}}]
        text = json.dumps({"header": NATIVE.header(), "known_keys": None, "records": s_rec})
        enc = NATIVE.encode_json(text)
        m = NATIVE.feasibility(enc)
        take = m.gestures.index("take")
        self.assertFalse(m.gesture_ok[take])
        self.assertFalse(m.refs[take, 0, 3])
        s_rec[2]["fields"]["props"] = {"graspable": True}
        m2 = NATIVE.feasibility(NATIVE.encode_json(json.dumps({"header": NATIVE.header(), "known_keys": None, "records": s_rec})))
        self.assertTrue(m2.gesture_ok[take])
        self.assertTrue(m2.refs[take, 0, 3])


if __name__ == "__main__":
    unittest.main()
