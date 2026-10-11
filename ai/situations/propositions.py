"""propositions.py - typed propositions of the inner language for beliefs, goals, memories and requests.

Each template is a general predicate of the catalogue (owns, at, quality, link, did...) filled from the NPC's own
files (its pointers), never a story. Every result is checked by the language validator (catalogue/tools/
language.py); an invalid one is dropped and counted. D10: no intimate symbol is ever generated here (links such as
spouse reach the model through ENTITY.link, between adults only, see scene.py).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .pools import Pools

import language  # noqa: E402  (path set by pools)


@dataclass
class Refs:
    """The NPC's pointers usable in a proposition (keys of its records)."""
    persons: list[str] = field(default_factory=list)        # @E keys (present or absent)
    things: list[str] = field(default_factory=list)         # @T keys
    loci: list[str] = field(default_factory=list)           # @L keys
    groups: list[str] = field(default_factory=list)         # @G keys

    def anyone(self, rng) -> str:
        return rng.choice(self.persons + ["me"]) if self.persons else "me"


class PropositionFactory:
    def __init__(self, rng: random.Random, pools: Pools):
        self.rng, self.pools = rng, pools
        self.vocab = language.Vocabulary(pools.cat)
        bad = pools.intimate_symbols
        self.words = {c: [w for w in pools.concepts(c) if w not in bad] for c in (
            "degree", "quality", "occupation", "technique", "link", "deontic", "role_word")}
        self.traits = sorted(w for w, cs in self.vocab.cats.items() if "variable" in cs and w not in bad)
        self.kinds = sorted(k for ks in pools.items_by_category.values() for k in ks)
        self.gestures = [g for fam, gs in pools.gestures.items() if fam != "communicate" for g in gs]
        self.dropped = 0
        self.made = 0

    # ---- validation ---------------------------------------------------------------------------------
    def _ok(self, text: str, mood: str | None = "assert") -> str | None:
        e = language.Expression(f"({mood} {text})" if mood else text, self.vocab)
        bad = self.pools.intimate_symbols
        if not e.ok or any(s in bad for s in e.root.symbols()):
            self.dropped += 1
            return None
        self.made += 1
        return text

    def _first(self, makers) -> str | None:
        """Try the makers in a random order until one gives a valid proposition."""
        makers = list(makers)
        self.rng.shuffle(makers)
        for m in makers:
            p = m()
            if p is not None:
                return p
        return None

    # ---- pieces -------------------------------------------------------------------------------------
    def _w(self, cat: str) -> str:
        return self.rng.choice(self.words[cat])

    def _kind(self, count: bool = False) -> str:
        k = self.rng.choice(self.kinds)
        return f"{k}:{self.rng.randint(2, 12)}" if count and self.rng.random() < 0.3 else k

    def _deed(self, r: Refs, actor: str, target: str) -> str | None:
        g = self.rng.choice(self.gestures)
        a = self.pools.cat["action"][g]
        manners = [v for p in a.params if p.type == "enum" for v in p.values if v not in self.pools.intimate_symbols]
        how = f" (how {self.rng.choice(manners)})" if manners and self.rng.random() < 0.6 else ""
        return f"(did {actor} {g} {target}{how})"

    # ---- beliefs ------------------------------------------------------------------------------------
    def belief(self, r: Refs) -> str | None:
        rng, P = self.rng, r.anyone
        makers = [
            lambda: self._ok(f"(owns {P(rng)} {rng.choice(r.things)})") if r.things else None,
            lambda: self._ok(f"(has {P(rng)} {self._kind(True)})"),
            lambda: self._ok(f"(at {P(rng)} {rng.choice(r.loci)})") if r.loci else None,
            lambda: self._ok(f"(lives_at {P(rng)} {rng.choice(r.loci)})") if r.loci else None,
            lambda: self._ok(f"(quality {P(rng)} {self._w('quality')} {self._w('degree')})"),
            lambda: self._ok(f"(state {P(rng)} {rng.choice(self.traits)} {self._w('degree')})") if self.traits else None,
            lambda: self._ok(f"(works_as {P(rng)} {self._w('occupation')})"),
            lambda: self._ok(f"(link {P(rng)} {self._w('link')} {P(rng)})"),
            lambda: self._ok(f"(knows_how {P(rng)} {self._w('technique')})"),
            lambda: self._ok(f"(worth {self._kind()} {rng.randint(1, 40)})"),
            lambda: self._ok(f"(norm {self._w('deontic')} {self._deed(r, 'anyone', rng.choice(r.things or ['@PLACE']))})"),
            lambda: self._ok(f"(past {self._deed(r, P(rng), P(rng))})"),
            lambda: self._ok(f"(believes {P(rng)} (quality {P(rng)} {self._w('quality')} {self._w('degree')}))"),
            lambda: self._ok(f"(member {P(rng)} {rng.choice(r.groups)})") if r.groups else None,
            lambda: self._ok(f"(holds {P(rng)} {self._w('role_word')})"),
        ]
        return self._first(makers)

    # ---- goals --------------------------------------------------------------------------------------
    def goal(self, r: Refs) -> str | None:
        rng = self.rng
        makers = [
            lambda: self._ok(f"(has me {self._kind(True)})"),
            lambda: self._ok(f"(at me {rng.choice(r.loci)})") if r.loci else None,
            lambda: self._ok(f"(owns me {rng.choice(r.things)})") if r.things else None,
            lambda: self._ok(f"(quality me {self._w('quality')} high)"),
            lambda: self._ok(f"(works_as me {self._w('occupation')})"),
            lambda: self._ok(f"(knows_how me {self._w('technique')})"),
            lambda: self._ok(f"(link me friend {rng.choice(r.persons)})") if r.persons else None,
            lambda: self._ok(f"(state me {rng.choice(('hunger', 'thirst', 'exhaustion', 'pain'))} low)"),
        ]
        return self._first(makers)

    # ---- memories -----------------------------------------------------------------------------------
    def memory(self, r: Refs) -> str | None:
        rng, P = self.rng, r.anyone
        when = lambda: rng.choice(("past", "long_ago"))  # noqa: E731
        makers = [
            lambda: self._ok(f"({when()} {self._deed(r, P(rng), 'me')})"),
            lambda: self._ok(f"({when()} {self._deed(r, 'me', P(rng))})"),
            lambda: self._ok(f"({when()} {self._deed(r, P(rng), P(rng))})"),
            lambda: self._ok(f"({when()} (dead {rng.choice(r.persons)}))") if r.persons else None,
        ]
        return self._first(makers)

    # ---- what someone asked of the NPC: a full utterance, frozen in the HEARER's terms --------------
    def request(self, r: Refs, asker: str) -> str | None:
        """me = the NPC who heard it, `asker` = the pointer to whoever asked (language_grammar.toml: freezing)."""
        rng = self.rng
        makers = [
            lambda: self._ok(f"(request (did me give {self._kind()} (to {asker})))", mood=None),
            lambda: self._ok(f"(offer (did {asker} give {self._kind(True)} (to me)))", mood=None),
            lambda: self._ok(f"(ask (at {rng.choice(r.persons)} where))", mood=None) if r.persons else None,
            lambda: self._ok(f"(request {self._deed(r, 'me', rng.choice(r.things or [asker]))})", mood=None),
        ]
        return self._first(makers)
