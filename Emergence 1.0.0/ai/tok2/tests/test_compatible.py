"""T09 : les registres en ajout seul. Les versions de HEAD (`git show HEAD:...`) doivent rester un PRÉFIXE des versions
du répertoire de travail : rien n'est renuméroté, retiré ni réordonné ; seuls des ajouts en fin de liste et des
élargissements (pointeurs, signatures de geste) sont permis. Après le commit de T09, HEAD est le nouvel état : le test
reste vrai (préfixe non strict) et garde les états futurs.

Les cas d'or de `tok2/golden` sont comparés de la même façon : même nom => même verdict et même empreinte, ce qui
couvre l'élargissement de `member` (arg_classes) et celui de WAKE.trigger / put.where. Les en-têtes (interface,
disposition) changent par construction ; un cas dont le CONTEXTE change doit être expliqué ici (`REWRITTEN`).
"""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# cas dont le contexte a été réécrit exprès (ENTITY est devenu un porteur valide de WAKE.trigger, T08b) ; le verdict reste
REWRITTEN = {"bad_pointer_of_the_wrong_kind"}


def at_head(rel: str) -> str:
    try:
        out = subprocess.run(["git", "show", f"HEAD:./{rel}"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise unittest.SkipTest("git indisponible")
    if out.returncode != 0:
        raise unittest.SkipTest(f"{rel} absent de HEAD")
    return out.stdout


def head_json(rel: str) -> dict:
    return json.loads(at_head(rel))


def now_json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def widens(old: str, new: str) -> bool:
    """Une signature de geste ne peut que s'élargir : mêmes paramètres, listes de sortes de pointeur plus larges."""
    a, b = old.split("|"), new.split("|")
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x == y:
            continue
        px, py = x.split(":"), y.split(":")
        if px[0] != "ref" or py[0] != "ref" or px[:3] != py[:3] or len(px) != len(py):
            return False
        if not set(px[3].split("/")) <= set(py[3].split("/")) or px[4:] != py[4:]:
            return False
    return True


class RegistriesAreAppendOnly(unittest.TestCase):
    def assertPrefix(self, old: list, new: list, what: str):
        self.assertGreaterEqual(len(new), len(old), what)
        for i, (a, b) in enumerate(zip(old, new)):
            self.assertEqual(a, b, f"{what}[{i}] a changé")

    def test_tok2_registry(self):
        old, new = head_json("ai/tok2/registry.json"), now_json("ai/tok2/registry.json")
        self.assertEqual(old["schema"], new["schema"])
        self.assertEqual(old["widths"], new["widths"], "les largeurs de bloc ne bougent pas")
        self.assertPrefix(old["symbols"], new["symbols"], "symbols")
        self.assertTrue(set(old["types"]) <= set(new["types"]))
        for t, o in old["types"].items():
            n = new["types"][t]
            self.assertEqual(o["id"], n["id"], f"id du type {t}")
            for f, of in o["fields"].items():
                self.assertIn(f, n["fields"], f"{t}.{f} retiré")
                nf = n["fields"][f]
                for k in ("block", "col", "width", "codec", "scale", "unit", "list_of"):
                    self.assertEqual(of.get(k), nf.get(k), f"{t}.{f}.{k}")
            used = {}
            for f, nf in n["fields"].items():
                for c in range(nf["col"], nf["col"] + nf["width"]):
                    self.assertNotIn((nf["block"], c), used, f"{t}.{f} recouvre {used.get((nf['block'], c))}")
                    used[(nf["block"], c)] = f"{t}.{f}"

    def test_output_registry(self):
        old, new = head_json("ai/student2/output_registry.json"), now_json("ai/student2/output_registry.json")
        # T11 : le schéma 1 -> 2 n'ajoute que la capacité `plan_steps` et la liste `lists` ; rien d'ancien ne bouge
        self.assertIn((old["schema"], new["schema"]), {(new["schema"], new["schema"]), ("student2-output-registry-1", "student2-output-registry-2")})
        self.assertEqual(old["manner_reserve"], new["manner_reserve"])
        self.assertEqual(old["capacity"], {k: v for k, v in new["capacity"].items() if k in old["capacity"]}, "capacity")
        for k in ("gestures", "conditions", "write_vars"):
            self.assertGreaterEqual(len(new[k]), len(old[k]), k)
            for i, (a, b) in enumerate(zip(old[k], new[k])):
                self.assertEqual(a["name"], b["name"], f"{k}[{i}]")
                self.assertTrue(a["sig"] == b["sig"] or widens(a["sig"], b["sig"]),
                                f"{k}[{i}] {a['name']}: signature en CONFLIT\n  {a['sig']}\n  {b['sig']}")
        for k in ("forms", "enum_values", "directions"):
            self.assertPrefix(old[k], new[k], k)
        self.assertGreaterEqual(len(new["manner"]), len(old["manner"]))
        for a, b in zip(old["manner"], new["manner"]):
            self.assertEqual((a["name"], a["capacity"]), (b["name"], b["capacity"]))
            self.assertPrefix(a["values"], b["values"], "manner." + a["name"])
        for k, cap in new["capacity"].items():
            key = {"gestures": "gestures", "conditions": "conditions", "write_vars": "write_vars"}.get(k)
            if key:
                self.assertLessEqual(len(new[key]), cap, k)

    def test_the_output_registry_loader_accepts_the_old_one(self):
        """Ce que `Checkpoint.check` appelle : le registre de sortie d'un ancien point de contrôle est une extension."""
        from student2.output_registry import OutputRegistry
        old = head_json("ai/student2/output_registry.json")
        self.assertEqual(OutputRegistry.load().compatible(old), [])

    def test_var_and_vocab_registries(self):
        for rel, keys in (("catalogue/generated/var_registry.json", ("vars",)),
                          ("catalogue/generated/vocab_registry.json", ("words", "kinds"))):
            old, new = head_json(rel), now_json(rel)
            self.assertEqual(old["schema"], new["schema"])
            for k in keys:
                self.assertPrefix(old[k], new[k], f"{rel}:{k}")


class CppIdentifiersDoNotMove(unittest.TestCase):
    """Les identifiants C++ de gestes, conditions, variables, mots et sortes suivent l'ordre des registres."""
    DIR = "engine/social/generated/emergence/social/"

    @staticmethod
    def names(text: str, array: str) -> list:
        import re
        m = re.search(array + r"\s*=\s*\{(.*?)\};", text, re.S)
        return re.findall(r'"([^"]*)"', m.group(1))

    @staticmethod
    def enum(text: str, name: str) -> list:
        import re
        m = re.search(r"enum class " + name + r"[^{]*\{(.*?)\};", text, re.S)
        return [x.strip() for x in m.group(1).split(",") if x.strip()]

    def test_arrays_and_enums_are_prefixes(self):
        for f, arrays, enums in (("catalogue_gen.h", ("kGestureNames", "kConditionNames", "kVarNames"), ("Gesture", "Condition", "Var")),
                                 ("vocab_gen.h", ("kWords", "kKinds"), ())):
            old = at_head(self.DIR + f)
            new = (ROOT / self.DIR / f).read_text(encoding="utf-8")
            for a in arrays + ("kWords", "kKinds")[:0]:
                o, n = self.names(old, a), self.names(new, a)
                self.assertEqual(n[:len(o)], o, f"{f}:{a}")
            for e in enums:
                o, n = self.enum(old, e)[:-1], self.enum(new, e)[:-1]        # sans la sentinelle kCount
                self.assertEqual(n[:len(o)], o, f"{f}:enum {e}")


class GoldenCasesAreStable(unittest.TestCase):
    """L'élargissement de `member` (arg_classes = [[agent, group], [group]]) ne change pas la forme vue par tok-2."""

    def test_old_golden_cases_keep_their_verdict_and_digest(self):
        old = [json.loads(line) for line in at_head("ai/tok2/golden/cases.jsonl").splitlines() if line]
        new = {c["name"]: c for c in (json.loads(line) for line in
                                      (ROOT / "ai/tok2/golden/cases.jsonl").read_text(encoding="utf-8").splitlines() if line)}
        for c in old:
            self.assertIn(c["name"], new, f"cas retiré : {c['name']}")
            self.assertEqual(c["expect"], new[c["name"]]["expect"], f"verdict ou empreinte changés : {c['name']}")
            if c["name"] not in REWRITTEN:
                a, b = dict(c["context"]), dict(new[c["name"]]["context"])
                a.pop("header", None), b.pop("header", None)
                self.assertEqual(a, b, f"contexte réécrit : {c['name']}")

    def test_member_keeps_its_signature_in_the_grammar_seen_by_tok2(self):
        """`arg_classes` (agent|group, ou group) n'est pas dans ce que tok-2 lit : `predicates.member` est inchangé,
        comme tous les prédicats qui existaient et toutes les clés de la grammaire."""
        old = head_json("ai/tok2/golden/layout.json")["grammar"]
        new = now_json("ai/tok2/golden/layout.json")["grammar"]
        self.assertEqual(old["predicates"]["member"], new["predicates"]["member"])
        self.assertEqual(new["predicates"]["member"], ["agent", "group"])
        for name, args in old["predicates"].items():
            self.assertEqual(args, new["predicates"][name], name)
        self.assertEqual(old["accepts"], new["accepts"])
        for k in old:
            self.assertIn(k, new, k)


if __name__ == "__main__":
    unittest.main()
