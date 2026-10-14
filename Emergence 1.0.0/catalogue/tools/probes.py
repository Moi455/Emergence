"""probes.py - check that the PROBES (stories) really are expressible: every utterance and every line of every trace is
a valid sentence of the catalogue. A probe asks "can the catalogue say this?"; here the answer is machine-checked.

    python3 catalogue/tools/probes.py            # prints the problems, exit code 1 if any

A TRACE decomposes a story step by step, as the written thought (docs/09) would write it, one line per record:

    phase | kind | content

    phase  percept, belief, judgement, goal, utterance, commitment, plan, meeting, act
    kind   memory      a bare proposition (what happened, as perceived)           (past (did @E4 go @L5 (how discreet)))
           belief      a bare proposition held true                                (believes @E2 (dead @E4))
           heard       an utterance somebody said to the NPC, in his own terms     (assert (past (did @E4 go @L6)))
           goal        a bare proposition wanted                                   (dead @E4)
           commit      COUNTERPARTY then a bare proposition                        @G1 (caused us (dead @E4))
           utterance   an utterance the NPC says                                   (offer (at_time night (at us @L9)))
           plan_says   the utterance planned in PLAN.says                          (request (at_time (span 3 day) (at (of 5 @G1) @L1)))
           write       VARIABLE TARGET VALUE written by the model                  m_interpretation m:1 adultery
           gesture     GESTURE param=value ... (a step of the plan)                go target=@L9 pace=brisk
           condition   CONDITION ARG? (the stop condition of a step)               c_sees_ref @G1
           event       a bare proposition perceived (a collective percept too)    (past (did @G1 go @L9))

The pointers are the NPC's own records (@E persons, @L places, @G groups, b:/m:/g: his records, h:/q:/c: what he heard,
was asked or agreed). Nothing here is true of the world: a trace is a thought, not a fact.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import Catalogue  # noqa: E402
import language  # noqa: E402

BARE = ("memory", "belief", "goal", "event")
FULL = ("heard", "utterance", "plan_says")
KINDS = BARE + FULL + ("commit", "write", "gesture", "condition")
PHASES = ("percept", "belief", "judgement", "goal", "utterance", "commitment", "plan", "meeting", "act")
POINTER = language.POINTER


class ProbeChecker:
    """Checks every story of a catalogue; `problems()` lists what does not hold."""

    def __init__(self, cat: Catalogue):
        self.cat = cat
        self.vocab = language.Vocabulary(cat)

    def problems(self) -> list[str]:
        out = []
        for s in self.cat["story"].values():
            for u in s.utterances:
                e = language.Expression(u, self.vocab)
                if not e.ok:
                    out.append(f"story {s.id}: utterance {u}: {'; '.join(e.problems[:2])}")
            for i, line in enumerate(s.trace):
                out += [f"story {s.id}: trace {i + 1}: {p}" for p in self.check_line(line)]
        return out

    def check_line(self, line: str) -> list[str]:
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) != 3:
            return ["'phase | kind | content' expected"]
        phase, kind, content = parts
        if phase not in PHASES:
            return [f"phase '{phase}' not in {PHASES}"]
        if kind not in KINDS:
            return [f"kind '{kind}' not in {KINDS}"]
        if kind in BARE:
            return self._expr(content, bare=True)
        if kind in FULL:
            return self._expr(content, bare=False)
        return getattr(self, "_" + kind)(content)

    def _expr(self, text: str, bare: bool) -> list[str]:
        e = language.Expression(text, self.vocab, bare=bare)
        return [] if e.ok else [f"{text}: {'; '.join(e.problems[:2])}"]

    def _commit(self, content: str) -> list[str]:
        who, _, prop = content.partition(" ")
        if not (POINTER.match(who) and who.startswith(("@E", "@G"))):
            return [f"commit: a counterparty pointer (@E, @G) first, got '{who}'"]
        return self._expr(prop, bare=True)

    def _write(self, content: str) -> list[str]:
        var, _, rest = content.partition(" ")
        v = self.cat["variable"].get(var)
        if v is None:
            return [f"write: unknown variable '{var}'"]
        if not any(w.startswith("T_") for w in v.writer):
            return [f"write: '{var}' is not written by the model"]
        target, _, value = rest.partition(" ")
        if v.scale == "word" and value not in self.vocab.cats and value not in self.vocab.kinds:
            return [f"write: '{value}' is not a word"]
        if v.scale == "proposition":
            return self._expr(value, bare=True)
        if v.scale in ("bipolar10", "unipolar10", "qty", "ratio", "time"):
            try:
                float(value)
            except ValueError:
                return [f"write: '{value}' is not a number"]
        if v.scale == "bool" and value not in ("true", "false"):
            return [f"write: '{value}' is not a boolean"]
        if target != "me" and not POINTER.match(target) and target != "new":
            return [f"write: target '{target}' is not a pointer, 'me' or 'new'"]
        return []

    def _gesture(self, content: str) -> list[str]:
        toks = content.split()
        a = self.cat["action"].get(toks[0]) if toks else None
        if a is None:
            return [f"gesture: unknown gesture '{toks[0] if toks else ''}'"]
        params = {p.name: p for p in a.params}
        out = []
        for t in toks[1:]:
            name, _, val = t.partition("=")
            p = params.get(name)
            if p is None:
                out.append(f"gesture {a.id}: no parameter '{name}'")
            elif p.type == "enum" and val not in p.values:
                out.append(f"gesture {a.id}: {name}={val} not among {p.values}")
            elif p.type == "ref" and not POINTER.match(val) and val not in language.REF_WORDS:
                out.append(f"gesture {a.id}: {name} wants a pointer, got '{val}'")
        return out

    def _condition(self, content: str) -> list[str]:
        toks = content.split()
        c = self.cat["concept"].get(toks[0]) if toks else None
        if c is None or c.category != "condition":
            return [f"condition: '{toks[0] if toks else ''}' is not a stop condition"]
        if len(toks) - 1 != len(c.args):
            return [f"condition {c.id}: takes {len(c.args)} argument(s)"]
        return []


def main() -> int:
    problems = ProbeChecker(Catalogue.load()).problems()
    for p in problems:
        print("  -", p)
    print("OK" if not problems else f"{len(problems)} problème(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
