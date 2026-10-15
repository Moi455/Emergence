"""laws.py - the laws of the body and the mind (docs/14, task T21b): their checker.

    LawChecker(cat).problems()   # what check.py and gen_cpp.py enforce on data/laws.toml

A law's numbers (rates, half-lives, fractions, thresholds) are variables of the catalogue, not constants of the C++ engine.
Every variable written by the `engine` has a [[law]] (it lists the variable) OR a `no_law_reason`, never both. A law declares
its `basis` (physics or design), the OBJECTIVE facts it depends on (`depends_on`: no private variable, no truth forbidden to
the tokens) and the own state it reads (`reads`: no forbidden truth either). The law never decides in place of the model.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import Catalogue, EXERTIONS, LAW_BASES, LAW_DURATION_SUFFIXES, LAW_FORMS  # noqa: E402
import forgetting  # noqa: E402

NAME = re.compile(r"^[a-z][a-z0-9_]*$")
INT64 = 1 << 62
WRITERS_OF_LAWS = ("engine", "derived")   # a law writes an engine variable or a derived one


class LawChecker:
    def __init__(self, cat: Catalogue):
        self.cat = cat

    def forbidden(self, v) -> str:
        """Why a variable may never be read by a law ('' = it may): a truth the tokens may not carry."""
        if v.id in forgetting.FORBIDDEN_VARS or v.scale == "id":
            return "a truth of the world forbidden to the tokens"
        return ""

    def problems(self) -> list:
        cat, p = self.cat, []
        laws = cat["law"]
        covered: dict[str, list[str]] = {}
        for law in laws.values():
            p += self._law(law)
            for name in law.variables:
                covered.setdefault(name, []).append(law.id)
        for v in cat["variable"].values():
            if "engine" not in v.writer:
                if v.no_law_reason:
                    p.append(f"variable {v.id}: no_law_reason on a variable the engine does not write")
                continue
            if v.id not in covered and not v.no_law_reason.strip():
                p.append(f"variable {v.id}: written by the engine, needs a [[law]] listing it or a no_law_reason")
            if v.id in covered and v.no_law_reason.strip():
                p.append(f"variable {v.id}: has both a law ({covered[v.id][0]}) and a no_law_reason")
        return p

    def _law(self, law) -> list:
        cat, p = self.cat, []
        who = f"law {law.id}"
        if not law.basis:
            p.append(f"{who}: basis is required (one of {LAW_BASES})")
        elif law.basis not in LAW_BASES:
            p.append(f"{who}: basis '{law.basis}' not in {LAW_BASES}")
        if law.form not in LAW_FORMS:
            p.append(f"{who}: form '{law.form}' not in {LAW_FORMS}")
        if not law.unit.strip():
            p.append(f"{who}: unit is required")
        if not law.doc_ref.strip():
            p.append(f"{who}: doc_ref is required")
        if not NAME.match(law.id):
            p.append(f"{who}: the id must be a C++-friendly name [a-z][a-z0-9_]*")
        for name in law.variables:
            v = cat["variable"].get(name)
            if v is None:
                p.append(f"{who}: unknown variable '{name}'")
            elif not any(w in v.writer for w in WRITERS_OF_LAWS):
                p.append(f"{who}: variable '{name}' is written by {v.writer}, a law writes an engine or a derived variable")
        if len(set(law.variables)) != len(law.variables):
            p.append(f"{who}: a variable is listed twice")
        for name, val in law.params.items():
            if not NAME.match(name):
                p.append(f"{who}: param '{name}' is not a [a-z][a-z0-9_]* name")
            if isinstance(val, bool) or not isinstance(val, int):
                p.append(f"{who}: param '{name}' must be an integer (all laws are integer arithmetic)")
            elif abs(val) >= INT64:
                p.append(f"{who}: param '{name}' is out of range")
            if any(name.endswith(s) for s in LAW_DURATION_SUFFIXES) and isinstance(val, int) and val <= 0:
                p.append(f"{who}: duration '{name}' must be > 0")
        if law.by_exertion:
            if len(law.by_exertion) != len(EXERTIONS):
                p.append(f"{who}: by_exertion needs {len(EXERTIONS)} values ({', '.join(EXERTIONS)}), got {len(law.by_exertion)}")
            elif any(isinstance(x, bool) or not isinstance(x, int) for x in law.by_exertion):
                p.append(f"{who}: by_exertion values must be integers")
        for name in law.depends_on:
            v = cat["variable"].get(name)
            if v is None:
                p.append(f"{who}: depends_on unknown variable '{name}'")
                continue
            if v.visibility == "private":
                p.append(f"{who}: depends_on '{name}' is private (not an objective fact): list it in `reads` if it is the NPC's own state")
            why = self.forbidden(v)
            if why:
                p.append(f"{who}: depends_on '{name}' is {why}")
        for name in law.reads:
            v = cat["variable"].get(name)
            if v is None:
                p.append(f"{who}: reads unknown variable '{name}'")
                continue
            why = self.forbidden(v)
            if why:
                p.append(f"{who}: reads '{name}' which is {why}")
        return p
