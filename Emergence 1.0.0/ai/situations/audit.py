"""audit.py - an INDEPENDENT D10 check of every generated situation (defense in depth: it does not trust the
generator's own precautions and shares no constant with it). A violation raises; the sampler never returns an
unaudited situation.

It rebuilds the governor's view from the TRUTH of the scene (the real ages, `people`) and from the NPC's own
records (apparent age, beliefs about ages, how well each person is known), and asks the GOVERNOR:
  * every proposition (belief, heard, memory, goal, commitment, request) passes `check_record`, with the cited
    records (b:, m:, g:) and perceived events (@V) unfolded from the records;
  * every EVENT passes `check_gesture`, every PLAN step too (the step and the next one, and each gesture of the whole
    chain with its own target), and what the plan means to say passes `check_record` as an utterance; a GROUP's
    aim passes it as a belief;
  * a goal's parent is another goal of the same mind, and the parents never loop;
  * no intimate symbol (flag `intimate` of the catalogue) in any text or list field of any record;
  * intimate fields (the ones the interface takes from an intimate variable) and intimate links only for an adult
    NPC and toward a person he knows by sight (`known_by == "seen"`) whom the governor does not take for a possible
    minor: adult in truth, in appearance if he is here, in the age he believes if he is not (a belief
    `(state X age_years N)` is then in his mind); a drive for intimacy stays low while his attention is on a
    possible minor;
  * the table key -> person is consistent with the file (the apparent age is within a few years of the true one),
    and a person known by description carries no name;
  * no physical quality (beautiful, ugly) said of a possible minor.
The age of majority is the governor's (hard_rules.toml); the intimate links are read from the concept flags.
"""
from __future__ import annotations

import re

from governor import ADULT_AGE, UNKNOWN, Governor, Party

from .pools import Pools

import language  # noqa: E402  (path set by pools)

TOKEN = re.compile(r"\(|\)|[^\s()]+")
PHYSICAL = ("w_beautiful", "w_ugly")
ATTENTION_DRIVE_CAP = 2.0
AGE_TOLERANCE = 5.0                 # years between the apparent age in a file and the true age of the person
PROP_KINDS = {"BELIEF": "belief", "HEARD": "belief", "MEMORY": "memory", "GOAL": "goal", "COMMIT": "agreement"}


class D10Violation(AssertionError):
    pass


class D10Audit:
    def __init__(self, pools: Pools):
        cat = pools.cat
        self.cat = cat
        self.gov = Governor(cat)
        self.vocab = self.gov.vocab
        self.adult = float(ADULT_AGE)
        self.intimate_links = frozenset(c.id for c in cat["concept"].values() if c.category == "link" and c.intimate)
        self.intimate_fields = self._intimate_fields(pools.interface)
        self.bad = self._intimate_symbols()
        self.parser = language.Parser()

    def _intimate_fields(self, interface) -> dict[str, frozenset[str]]:
        """token type -> its fields that come from a variable flagged intimate (read from the interface)."""
        variables = self.cat["variable"]
        out = {}
        for typ, spec in interface.token_types.items():
            names = frozenset(n for n, f in spec["fields"].items() if getattr(variables.get(f.get("from", "")), "intimate", False))
            if names:
                out[typ] = names
        return out

    def _intimate_symbols(self) -> frozenset[str]:
        cat = self.cat
        out = {c.id for c in cat["concept"].values() if c.intimate} | {v.id for v in cat["variable"].values() if v.intimate}
        out |= {i.id for i in cat["interpretation"].values() if getattr(i, "intimate", False)}
        for a in cat["action"].values():
            if a.intimate:
                out.add(a.id)
            for p in a.params:
                out |= set(p.intimate_values)
        return frozenset(out)

    # ---- the governor's view --------------------------------------------------------------------------------
    def _believed_ages(self, records) -> dict:
        out = {}
        for r in records:
            if r.type in ("BELIEF", "HEARD") and r.fields.get("prop") and r.fields.get("polarity") is not False:
                for n in self._nodes(self.parser.parse(r.fields["prop"])):
                    a = n.args
                    if n.head == "state" and len(a) == 3 and a[1] == "age_years" and isinstance(a[2], str) and a[2].isdigit():
                        out.setdefault(a[0], float(a[2]))
        return out

    def _nodes(self, node):
        if isinstance(node, language.Node):
            yield node
            for x in node.args:
                yield from self._nodes(x)

    def _parties(self, me, records, people) -> dict:
        believed = self._believed_ages(records)
        self_age = next(r for r in records if r.type == "SELF").fields.get("age")
        parties = {"me": Party(real_age=me.age, believed_age=self_age, apparent_age=self_age, resolved=True)}
        for r in records:
            if r.type == "ENTITY":
                truth, seen = people.get(r.key), r.fields.get("look.age")
                here = bool(r.fields.get("present"))
                parties[r.key] = Party(real_age=truth.age if truth is not None else None,
                                       believed_age=believed.get(r.key, seen if here else None), apparent_age=seen,
                                       resolved=r.fields.get("known_by") == "seen", perceived=here)
            elif r.type == "GROUP":
                parties[r.key] = UNKNOWN
        for r in records:                                     # a name stands for the file that carries it
            if r.type == "ENTITY" and r.fields.get("name"):
                parties[r.fields["name"]] = parties[r.key]
        return parties

    def _party(self, parties: dict, key: str) -> Party:
        if key in parties:
            return parties[key]
        return Party(resolved=True, person=False) if key.startswith(("@T", "@L", "@PLACE", "@V")) else UNKNOWN

    # ---- the check --------------------------------------------------------------------------------------------
    def check(self, me, records, people: dict) -> None:
        problems: list[str] = []
        parties = self._parties(me, records, people)
        expand = self._expander(records)
        self_rec = next(r for r in records if r.type == "SELF")
        by_key = {r.key: r for r in records}
        self_adult = me.age >= self.adult and self_rec.fields.get("age", 0) >= self.adult
        for rec in records:
            f = rec.fields
            problems += self._symbols(rec)
            if rec.type in PROP_KINDS and f.get("prop"):
                problems += self._proposition(rec, PROP_KINDS[rec.type], parties, expand)
                if rec.type == "GOAL":
                    problems += self._parent(rec, by_key)
            elif rec.type == "GROUP" and f.get("goal"):
                problems += self._proposition(rec, "belief", parties, expand, field="goal")
            elif rec.type == "REQUEST" and f.get("prop"):
                problems += self._proposition(rec, "goal", parties, expand, utterance=True)
            elif rec.type == "EVENT":
                problems += self._event(rec, parties)
            elif rec.type == "PLAN":
                problems += self._plan(rec, parties, expand)
            elif rec.type == "SELF_MIND":
                problems += self._own_intimate_fields(rec, self_adult)
            elif rec.type == "SELF_STATE":
                problems += self._own_intimate_fields(rec, self_adult) + self._attention(rec, parties)
            elif rec.type == "ENTITY":
                problems += self._entity(rec, people, self_adult, parties)
            elif rec.type == "TASTE":
                problems += self._taste(rec, me)
        if problems:
            raise D10Violation("; ".join(problems))

    def _expander(self, records):
        by_key = {r.key: r for r in records}

        def expand(ref):
            r = by_key.get(ref)
            if r is None:
                return None
            if r.type in ("BELIEF", "MEMORY", "GOAL", "HEARD") and r.fields.get("prop"):
                return language.Expression(r.fields["prop"], self.vocab, bare=True)
            if r.type == "EVENT":
                f = r.fields
                hows = "".join(f" (how {m})" for m in f.get("manner") or [])
                return language.Expression(f"(did {f['actor']} {f['gesture']}{' ' + f['target'] if f.get('target') else ''}{hows})",
                                           self.vocab, bare=True)
            return None
        return expand

    # ---- text ---------------------------------------------------------------------------------------------------
    def _symbols(self, rec) -> list[str]:
        """Every symbol of every text or list field (a proposition, a manner, a gesture, a technique, a step…)."""
        out = []
        for name, value in rec.fields.items():
            if rec.type == "ENTITY" and name == "link":
                continue                                         # checked with its conditions (_entity)
            hit = sorted({s for s in self._tokens(value) if s in self.bad})
            if hit:
                out.append(f"{rec.key}.{name}: intimate symbols {hit}")
        return out

    def _tokens(self, value):
        if isinstance(value, str):
            yield from TOKEN.findall(value)
        elif isinstance(value, (list, tuple)):
            for x in value:
                yield from self._tokens(x)
        elif isinstance(value, dict):
            for x in value.values():
                yield from self._tokens(x)

    # ---- propositions ---------------------------------------------------------------------------------------------
    def _parent(self, rec, by_key) -> list[str]:
        """A sub-goal points at another goal of his, and the chain of parents ends."""
        seen, key = {rec.key}, rec.fields.get("parent")
        while key:
            parent = by_key.get(key)
            if parent is None or parent.type != "GOAL":
                return [f"{rec.key}: its parent {key} is not a goal of his"]
            if key in seen:
                return [f"{rec.key}: the parents of this goal loop"]
            seen.add(key)
            key = parent.fields.get("parent")
        return []

    def _proposition(self, rec, kind, parties, expand, utterance: bool = False, field: str = "prop") -> list[str]:
        e = language.Expression(rec.fields[field], self.vocab, bare=not utterance)
        if not e.ok:
            return [f"{rec.key}: not a sentence of the language ({'; '.join(e.problems)})"]
        v = self.gov.check_record(kind, e, parties["me"], parties, expand=expand)
        out = [] if v.allowed else [f"{rec.key}: the governor refuses the proposition ({v.code})"]
        for n in self._nodes(e.root):
            if n.head == "quality" and len(n.args) == 3 and n.args[1] in PHYSICAL and \
                    self._party(parties, n.args[0]).may_be_minor():
                out.append(f"{rec.key}: a physical quality said of a possible minor")
        return out

    def _gesture(self, rec, name, g, params, target, parties) -> list[str]:
        a = self.cat["action"].get(g)
        if a is None:
            return [f"{rec.key}.{name}: '{g}' is not a gesture"]
        ref = next((p.name for p in a.params if p.type == "ref"), None)
        got = {ref: self._party(parties, target)} if (ref and target) else {}
        v = self.gov.check_gesture(g, params, parties["me"] if rec.type == "PLAN" else self._party(parties, rec.fields.get("actor", "me")), got)
        return [] if v.allowed else [f"{rec.key}: the governor refuses {g} ({v.code})"]

    def _event(self, rec, parties) -> list[str]:
        f = rec.fields
        a = self.cat["action"].get(f["gesture"])
        if a is None:
            return [f"{rec.key}: '{f['gesture']}' is not a gesture"]
        params, out = {}, []
        for m in f.get("manner") or []:
            owners = [p.name for p in a.params if p.type == "enum" and m in p.values]
            if not owners:
                out.append(f"{rec.key}: manner '{m}' is not a manner of {a.id}")
            for name in owners:
                params[name] = m
        return out + self._gesture(rec, "gesture", f["gesture"], params, f.get("target"), parties)

    def _plan(self, rec, parties, expand) -> list[str]:
        f = rec.fields
        out = []
        for step in ("step", "next"):
            if f.get(step):
                out += self._gesture(rec, step, f[step], {}, f.get("target"), parties)
        targets = iter(f.get("step_targets") or [])                  # one target per step that takes one, in order
        for g in f.get("steps") or []:
            a = self.cat["action"].get(g)
            takes = a is not None and any(p.type == "ref" for p in a.params)
            out += self._gesture(rec, "steps", g, {}, next(targets, None) if takes else None, parties)
        if f.get("says"):
            out += self._proposition(rec, "goal", parties, expand, utterance=True, field="says")
        return out

    # ---- fields -----------------------------------------------------------------------------------------------------
    def _own_intimate_fields(self, rec, self_adult) -> list[str]:
        have = [n for n in self.intimate_fields.get(rec.type, ()) if rec.fields.get(n) not in (None, [])]
        return [f"{rec.key}.{n}: an NPC who may be a minor has an intimate field" for n in have] if have and not self_adult else []

    def _attention(self, rec, parties) -> list[str]:
        att = rec.fields.get("attention")
        out = []
        if att and att.startswith("@E") and self._party(parties, att).may_be_minor():
            for n in self.intimate_fields.get("SELF_STATE", ()):
                if (rec.fields.get(n) or 0) > ATTENTION_DRIVE_CAP:
                    out.append(f"{n} {rec.fields[n]} while his attention is on {att}, who may be a minor")
        return out

    def _entity(self, rec, people, self_adult, parties) -> list[str]:
        f, out = rec.fields, []
        p, seen = people.get(rec.key), f.get("look.age")
        if f.get("known_by") == "described" and f.get("name"):
            out.append(f"{rec.key}: a person known by description carries a name")
        if p is not None and f.get("name") is not None and f["name"] != p.name:
            out.append(f"{rec.key}: the file says {f['name']} but the table says {p.name}")
        if p is not None and seen is not None and abs(seen - p.age) > AGE_TOLERANCE:
            out.append(f"{rec.key}: looks {seen} but the table says {p.age:.1f}: the key map drifted")
        intimate = f.get("link") in self.intimate_links or any(f.get(n) is not None for n in self.intimate_fields.get("ENTITY", ()))
        if intimate and not (self_adult and p is not None and p.age >= self.adult and f.get("known_by") == "seen"
                             and not self._party(parties, rec.key).may_be_minor()):
            out.append(f"{rec.key}: intimate link or attraction toward a person who is not a clear adult he knows by sight")
        return out

    def _taste(self, rec, me) -> list[str]:
        c = rec.fields.get("concept")
        return [f"{rec.key}: a minor's taste for a physical quality"] if c in PHYSICAL and me.age < self.adult else []
