"""violence_meter.py - how much force the sampler puts in its situations, and with which motives (T12b).

    python3 -m situations.violence_meter --n 15000            (from ai/)  shares, motives, entropy, D10 audit

Read from the finished situations, independently of the plot the builder says it wrote: a situation "has an aim of
force" if one of his goals, a group aim or a belief carries `dead`, a state of pain on a person, or a gesture of force
with a person for target; "a group" if a GROUP record carries such an aim; "a multi-step plan" if a PLAN serves such a
goal with three steps or more. The audit D10 (and the prudence rule) runs on every situation inside the sampler; the
meter also counts the situations whose NPC or targets are minors.
"""
from __future__ import annotations

import argparse
import math
from collections import Counter

import language

from .sampler import SituationSampler

FORCE = ("strike", "push", "grab", "pull")


class ForceReader:
    """Finds the aims of force in the propositions of a context."""

    def __init__(self):
        self.parser = language.Parser()

    def targets(self, text: str) -> list[str]:
        out = []
        stack = [self.parser.parse(text)]
        while stack:
            n = stack.pop()
            a = n.args
            if n.head == "dead" and a and isinstance(a[0], str):
                out.append(a[0])
            elif n.head == "state" and len(a) == 3 and a[1] == "pain" and a[2] in ("high", "very_high") and a[0] != "me":
                out.append(a[0])         # his own pain is a need, not an aim of force
            elif n.head == "did" and len(a) >= 3 and a[1] in FORCE and isinstance(a[2], str):
                out.append(a[2])
            elif n.head == "not" and a and isinstance(a[0], language.Node) and a[0].head in ("at", "leads") and a[0].args \
                    and isinstance(a[0].args[0], str) and a[0].args[0] != "me":
                out.append(a[0].args[0])         # to drive him out, to unseat him
            stack += [x for x in a if isinstance(x, language.Node)]
        return [t for t in out if t.startswith("@E") or t == "me"]


class ViolenceMeter:
    def __init__(self, seed: int = 0, n: int = 2000):
        self.seed, self.n = seed, n
        self.sampler = SituationSampler(seed)
        self.reader = ForceReader()
        self.c: Counter = Counter()
        self.motives: Counter = Counter()
        self.kinds: Counter = Counter()
        self.forms: Counter = Counter()
        self.by_structure: Counter = Counter()
        self.structures: Counter = Counter()
        self.minor_targets = 0
        self.minor_npc = 0

    def run(self) -> None:
        for i in range(self.n):
            sit = self.sampler.sample(i)
            self.structures[sit.structure] += 1
            recs = sit.context.records
            by_type: dict = {}
            for r in recs:
                by_type.setdefault(r.type, []).append(r)
            mine = sit.scene.self_.age
            goal_hit = [g for g in by_type.get("GOAL", []) if self.reader.targets(g.fields["prop"])]
            group_hit = [g for g in by_type.get("GROUP", []) if g.fields.get("goal") and self.reader.targets(g.fields["goal"])]
            belief_hit = [b for b in by_type.get("BELIEF", []) if self.reader.targets(b.fields["prop"])]
            any_force = bool(goal_hit or group_hit)
            self.c["situations"] += 1
            if goal_hit:
                self.c["goal_of_force"] += 1
            if group_hit:
                self.c["group_aim_of_force"] += 1
            if belief_hit:
                self.c["belief_of_force"] += 1
            if any_force:
                self.c["force_goal_or_group"] += 1
                self.by_structure[sit.structure] += 1
            if goal_hit and group_hit:
                self.c["goal_and_group"] += 1
            if sit.plot is not None:
                self.c["plot"] += 1
                self.kinds[sit.plot.kind] += 1
                self.motives[sit.plot.motive] += 1
                self.forms.update(sit.plot.forms)
                if sit.plot.grouped:
                    self.c["plot_grouped"] += 1
                if sit.plot.dilemma:
                    self.c["plot_dilemma"] += 1
            force_goals = {g.key for g in goal_hit}
            plans = [p for p in by_type.get("PLAN", []) if p.fields.get("goal") in force_goals]
            if plans:
                self.c["plan_for_force"] += 1
                if any(len(p.fields["steps"]) >= 3 for p in plans):
                    self.c["plan_for_force_3plus"] += 1
            for r in goal_hit + group_hit:
                for t in self.reader.targets(r.fields.get("prop") or r.fields["goal"]):
                    if t == "me":
                        if mine < 18:
                            self.minor_targets += 1
                    elif sit.people[t].age < 18:
                        self.minor_targets += 1
            if any_force and mine < 18:
                self.minor_npc += 1

    def entropy(self, counter: Counter) -> float:
        total = sum(counter.values())
        return -sum(v / total * math.log2(v / total) for v in counter.values()) if total else 0.0

    def report(self) -> str:
        n = self.c["situations"]
        pc = lambda k: f"{self.c[k] / n:.2%} ({self.c[k]})"  # noqa: E731
        out = [f"{n} situations (seed {self.seed}), audit D10 + prudence: no anomaly (an anomaly would have raised)",
               f"aim of force in his goals: {pc('goal_of_force')}; in a group aim: {pc('group_aim_of_force')}; goal OR group: "
               f"{pc('force_goal_or_group')}; both: {pc('goal_and_group')}",
               f"a belief that somebody means harm: {pc('belief_of_force')}",
               f"plots written: {pc('plot')}; grouped: {self.c['plot_grouped'] / max(1, self.c['plot']):.0%} of the plots; "
               f"with a dilemma: {self.c['plot_dilemma'] / max(1, self.c['plot']):.0%} of the plots",
               f"a plan serving a goal of force: {pc('plan_for_force')}; of 3 steps or more: {pc('plan_for_force_3plus')}",
               "kinds: " + ", ".join(f"{k} {v / max(1, self.c['plot']):.0%}" for k, v in self.kinds.most_common()),
               "motives: " + ", ".join(f"{k} {v / max(1, self.c['plot']):.0%}" for k, v in self.motives.most_common()),
               f"entropy of the motives: {self.entropy(self.motives):.2f} bits (max {math.log2(max(1, len(self.motives))):.2f}); "
               f"of the forms: {self.entropy(self.forms):.2f} bits ({len(self.forms)} forms)",
               "forms: " + ", ".join(f"{k} {v}" for k, v in self.forms.most_common()),
               "share of the situations with an aim of force, by family of structure: " + ", ".join(
                   f"{k} {self.by_structure[k] / v:.0%}" for k, v in sorted(self.structures.items())),
               f"aims of force at a minor: {self.minor_targets}; situations with an aim of force whose NPC is a minor: {self.minor_npc}"]
        return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    m = ViolenceMeter(a.seed, a.n)
    m.run()
    print(m.report())


if __name__ == "__main__":
    main()
