"""audit.py - an INDEPENDENT D10 check of every generated situation (defense in depth: it does not trust the
generator's own precautions). A violation raises; the sampler never returns an unaudited situation.

Policy of the bootstrap data (11 oct.): no intimate symbol in any proposition, manner, judgement or taste; intimate
fields (attraction, drive for intimacy, orientation) and intimate links only for an adult NPC and toward a person
who is an adult by truth, by appearance and by belief.
"""
from __future__ import annotations

from .pools import Pools
from .scene import ADULT, INTIMATE_LINKS, Person


class D10Violation(AssertionError):
    pass


class D10Audit:
    def __init__(self, pools: Pools):
        self.bad = pools.intimate_symbols
        import language  # noqa: PLC0415  (path set by pools)
        self.parser = language.Parser()

    def _symbols(self, text) -> list[str]:
        return self.parser.parse(str(text)).symbols()

    def check(self, me: Person, records, people: dict[str, Person]) -> None:
        problems: list[str] = []
        self_rec = next(r for r in records if r.type == "SELF")
        self_adult = me.age >= ADULT and self_rec.fields.get("age", 0) >= ADULT
        for rec in records:
            f = rec.fields
            if "prop" in f and f["prop"] is not None:
                hit = [s for s in self._symbols(f["prop"]) if s in self.bad]
                if hit:
                    problems.append(f"{rec.key}: intimate symbols {hit} in a proposition")
            for name in ("manner",):
                hit = [s for s in f.get(name) or [] if s in self.bad]
                if hit:
                    problems.append(f"{rec.key}: intimate manner {hit}")
            for name in ("interp", "concept"):
                if f.get(name) in self.bad:
                    problems.append(f"{rec.key}: intimate {name} {f[name]}")
            if rec.type == "SELF_MIND" and f.get("attracted_to") and not self_adult:
                problems.append("an NPC who may be a minor has an orientation field")
            if rec.type == "SELF_STATE" and f.get("drive.intimacy") is not None and not self_adult:
                problems.append("an NPC who may be a minor has a drive for intimacy")
            if rec.type == "ENTITY" and (f.get("link") in INTIMATE_LINKS or f.get("rel.attraction") is not None):
                p = people.get(rec.key)
                seen = f.get("look.age")
                if not (self_adult and p is not None and p.age >= ADULT and (seen is None or seen >= ADULT)):
                    problems.append(f"{rec.key}: intimate link or attraction with a possible minor")
        if problems:
            raise D10Violation("; ".join(problems))
