"""propositions.py - typed propositions of the inner language for beliefs, goals, memories and requests.

Each template is a general predicate of the catalogue (owns, at, quality, link, did...) filled from the NPC's own
files (its pointers), never a story. Every result is checked by the language validator (catalogue/tools/
language.py) and then by the GOVERNOR (D10, with the parties of the scene): an invalid one is dropped and counted,
a refused one is counted apart. D10 by construction: no intimate symbol is generated here (links such as spouse
reach the model through ENTITY.link, between adults only, see scene.py); a deed is told only with a gesture the
governor allows for those people; no physical quality (beauty, ugliness) is said of a possible minor.
Plausibility by age: no trade or craft for a child, a link only between ages that fit it.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .draw import Draw
from .gestures import YOUNG, GestureChooser
from .parties import PartyBook
from .pools import Pools
from .scene import LinkRules

import language  # noqa: E402  (path set by pools)

PHYSICAL_QUALITIES = ("w_beautiful", "w_ugly")          # never said of a possible minor
WORK_MIN_AGE = 14.0                                     # a trade, a craft: from this age
CHILD_TECHNIQUES = ("t_climbing", "t_swimming", "t_music", "t_foraging", "t_fishing", "t_stealth", "t_riding")
MAX_HOWS = 3                                            # event roles after the target (language.MAX_ROLES)


@dataclass
class Refs:
    """The NPC's pointers usable in a proposition (keys of its records). Build it with keywords."""
    persons: list[str] = field(default_factory=list)        # @E keys, present, absent or ghosts (not 'me')
    absent: list[str] = field(default_factory=list)         # @E keys of persons not here
    things: list[str] = field(default_factory=list)         # @T keys (seen things and carried ones)
    loci: list[str] = field(default_factory=list)           # @L keys
    groups: list[str] = field(default_factory=list)         # @G keys
    here: list[str] = field(default_factory=list)           # @E keys of persons present
    animals: frozenset = frozenset()                        # @T keys that are animals
    owners: dict = field(default_factory=dict)              # @T key -> owner key as the NPC believes it
    links: dict = field(default_factory=dict)               # @E key -> ENTITY.link (what he is to the NPC)

    def anyone(self, rng) -> str:
        return rng.choice(self.persons + ["me"]) if self.persons else "me"


class PropositionFactory:
    def __init__(self, rng: random.Random, pools: Pools):
        self.rng, self.pools = rng, pools
        self.d = Draw(rng)
        self.vocab = language.Vocabulary(pools.cat)
        self.gov = pools.governor
        self.chooser = GestureChooser(pools)
        self.rules = LinkRules(pools)
        bad = pools.intimate_symbols
        self.bad = bad
        self.words = {c: [w for w in pools.concepts(c) if w not in bad] for c in (
            "degree", "quality", "occupation", "technique", "link", "deontic", "role_word")}
        self.words["quality"] = [w for w in self.words["quality"] if w not in ("w_true", "w_false")]   # not of a person
        self.words["link"] = [w for w in self.words["link"] if w != "stranger"]
        # not the number of years (a belief about an age is the engine's, and 'pregnancy' is not a bootstrap topic)
        self.traits = sorted(w for w, cs in self.vocab.cats.items()
                             if "variable" in cs and w not in bad and w not in ("age_years", "pregnancy"))
        # kinds that can be given, taken, worth: an item type that is also a species (beans) is a plant to the language
        self.kinds = sorted(k for ks in pools.items_by_category.values() for k in ks
                            if "item" in language.ref_targets(k, self.vocab))
        self.parties: PartyBook | None = None
        self.me_age = 30.0
        self.owner_party = None
        self.dropped = 0            # not a valid sentence of the language
        self.refused = 0            # valid but refused by the governor (D10)
        self.made = 0

    def arm(self, rng: random.Random, parties: PartyBook, me_age: float) -> None:
        """Re-arm for the next situation (the vocabulary is built once)."""
        self.rng = rng
        self.d = Draw(rng)
        self.parties, self.me_age = parties, me_age

    # ---- validation (public) ---------------------------------------------------------------------------
    def validate(self, text: str, kind: str = "belief") -> str | None:
        """`text` if it is a sentence of the language that the governor allows, else None. kind: belief | goal |
        memory (a bare proposition) or request (a full utterance, in the hearer's terms)."""
        e = language.Expression(text, self.vocab, bare=kind != "request")
        if not e.ok or any(s in self.bad for s in e.root.symbols()):
            self.dropped += 1
            return None
        v = self.gov.check_record("goal" if kind == "request" else kind, e, self.parties.party("me"),
                                  self.parties.content_parties())
        if not v.allowed:
            self.refused += 1
            return None
        self.made += 1
        return text

    def _first(self, makers, kind: str):
        """Try the makers in a random order until one gives a valid proposition (a maker returns text or None)."""
        makers = list(makers)
        self.rng.shuffle(makers)
        for m in makers:
            t = m()
            if t is not None:
                p = self.validate(t, kind)
                if p is not None:
                    return p
        return None

    # ---- pieces -------------------------------------------------------------------------------------
    def _w(self, cat: str) -> str:
        return self.rng.choice(self.words[cat])

    def _kind(self, count: bool = False) -> str:
        k = self.rng.choice(self.kinds)
        return f"{k}:{self.rng.randint(2, 12)}" if count and self.rng.random() < 0.3 else k

    def _age(self, key: str) -> float:
        return self.me_age if key == "me" else self.parties.min_age(key)

    def _true_age(self, key: str) -> float:
        return self.me_age if key == "me" else self.parties.truth[key].age

    def _quality(self, subject: str) -> str:
        words = self.words["quality"]
        if self.parties.may_be_minor(subject) or self._age(subject) < 18.0:
            words = [w for w in words if w not in PHYSICAL_QUALITIES]
        return self.rng.choice(words)

    def _pair(self, r: Refs) -> tuple[str, str] | None:
        pool = r.persons + ["me"]
        if len(pool) < 2:
            return None
        a, b = self.rng.sample(pool, 2)
        return a, b

    def _target_class(self, r: Refs, key: str) -> str | None:
        if key == "me" or key.startswith(("@E", "n:")):
            return "agent"
        if key.startswith("@T"):
            return "animal" if key in r.animals else "item"
        if key.startswith(("@L", "@PLACE")):
            return "place"
        return None

    def _deed(self, r: Refs, actor: str, target: str) -> str | None:
        """(did ACTOR gesture TARGET [(how …)]) with a gesture the governor allows between these two."""
        if actor == target:
            return None
        cls = self._target_class(r, target) if target not in ("anyone", "someone") else "agent"
        if cls is None:
            return None
        young = actor != "anyone" and self._age(actor) < YOUNG
        pick = self.chooser.pick(self.d, cls, self.parties.party(actor), self.parties.party(target), young=young)
        if pick is None or len(pick.manner) > MAX_HOWS:
            return None
        hows = "".join(f" (how {m})" for m in pick.manner)
        return f"(did {actor} {pick.gesture} {target}{hows})"

    # ---- beliefs ------------------------------------------------------------------------------------
    def belief(self, r: Refs) -> str | None:
        rng, P = self.rng, r.anyone
        subj = lambda: P(rng)  # noqa: E731
        makers = [
            self._owns(r) if r.things else None,
            lambda: f"(has {subj()} {self._kind(True)})",
            lambda: f"(at {subj()} {rng.choice(r.loci)})" if r.loci else None,
            lambda: f"(at {rng.choice(r.here)} @PLACE)" if r.here else None,
            lambda: f"(lives_at {subj()} {rng.choice(r.loci)})" if r.loci else None,
            self._quality_belief(r),
            lambda: self._state(subj()),
            lambda: self._works(subj()),
            lambda: self._link(r),
            lambda: self._knows(subj()),
            lambda: f"(worth {self._kind()} {rng.randint(1, 40)})",
            lambda: self._norm(r),
            lambda: self._past_deed(r),
            lambda: self._believes(r),
            lambda: f"(member {subj()} {rng.choice(r.groups)})" if r.groups else None,
            lambda: self._holds(subj()),
        ]
        return self._first([m for m in makers if m is not None], "belief")

    def _owns(self, r: Refs):
        def make():
            t = self.rng.choice(r.things)
            believed = r.owners.get(t)
            if believed and self.rng.random() < 0.6:          # what the NPC already believes of this thing
                return f"(owns {believed} {t})"
            return f"(owns {r.anyone(self.rng)} {t})"
        return make

    def _quality_belief(self, r: Refs):
        def make():
            s = r.anyone(self.rng)
            return f"(quality {s} {self._quality(s)} {self._w('degree')})"
        return make

    def _state(self, s: str) -> str | None:
        return f"(state {s} {self.rng.choice(self.traits)} {self._w('degree')})" if self.traits else None

    def _works(self, s: str) -> str | None:
        return f"(works_as {s} {self._w('occupation')})" if self._age(s) >= WORK_MIN_AGE else None

    def _holds(self, s: str) -> str | None:
        return f"(holds {s} {self._w('role_word')})" if self._age(s) >= WORK_MIN_AGE else None

    def _knows(self, s: str) -> str | None:
        age = self._age(s)
        if age < YOUNG:
            return None
        techniques = self.words["technique"] if age >= WORK_MIN_AGE else [t for t in CHILD_TECHNIQUES if t in self.words["technique"]]
        return f"(knows_how {s} {self.rng.choice(techniques)})" if techniques else None

    def _believes(self, r: Refs) -> str | None:
        who, s = r.anyone(self.rng), r.anyone(self.rng)
        return f"(believes {who} (quality {s} {self._quality(s)} {self._w('degree')}))" if who != s else None

    def _norm(self, r: Refs) -> str | None:
        deed = self._deed(r, "anyone", self.rng.choice(r.things or ["@PLACE"]))
        return f"(norm {self._w('deontic')} {deed})" if deed else None

    def _past_deed(self, r: Refs) -> str | None:
        pair = self._pair(r)
        deed = self._deed(r, *pair) if pair else None
        return f"(past {deed})" if deed else None

    def _link(self, r: Refs) -> str | None:
        """(link X L Y) = X is the L of Y. Toward `me` it repeats ENTITY.link; between two others, a link that fits
        their ages. Never the same person twice, never an intimate link."""
        rng = self.rng
        known = [k for k in r.persons if r.links.get(k) not in (None, "stranger") and r.links[k] not in self.bad]
        if known and rng.random() < 0.5:
            x = rng.choice(known)
            return f"(link {x} {r.links[x]} me)"
        if len(r.persons) < 2:
            return None
        a, b = rng.sample(r.persons, 2)                    # two others: `me` only through ENTITY.link above
        fits = [w for w in self.words["link"] if self.rules.fits(w, self._true_age(a), self._true_age(b))]
        return f"(link {a} {rng.choice(fits)} {b})" if fits else None

    # ---- goals --------------------------------------------------------------------------------------
    def goal(self, r: Refs) -> tuple[str, str] | None:
        """-> (proposition, mode): achieve, avoid or maintain."""
        rng = self.rng
        young, works = self.me_age < YOUNG, self.me_age >= WORK_MIN_AGE
        friends = [k for k in r.persons if self.rules.fits("friend", self._true_age(k), self.me_age)
                   and r.links.get(k) not in ("friend", "spouse", "betrothed", "lover", "parent", "child", "sibling")]
        makers = [
            (lambda: f"(has me {self._kind(True)})", "achieve"),
            (lambda: f"(at me {rng.choice(r.loci)})" if r.loci else None, "achieve"),
            (lambda: f"(owns me {rng.choice(r.things)})" if r.things else None, "achieve"),
            (lambda: f"(quality me {self._quality('me')} high)", "maintain"),
            (lambda: f"(works_as me {self._w('occupation')})" if works else None, "maintain"),
            (lambda: f"(knows_how me {self._w('technique')})" if not young and works else None, "achieve"),
            (lambda: f"(link {rng.choice(friends)} friend me)" if friends else None, "achieve"),
            (lambda: f"(state me {rng.choice(('hunger', 'thirst', 'exhaustion', 'pain'))} low)", "achieve"),
            (lambda: f"(state me {rng.choice(('hunger', 'thirst', 'exhaustion', 'pain'))} high)", "avoid"),
        ]
        order = list(range(len(makers)))
        rng.shuffle(order)
        for i in order:
            text = makers[i][0]()
            if text is not None:
                ok = self.validate(text, "goal")
                if ok is not None:
                    return ok, makers[i][1]
        return None

    # ---- memories -----------------------------------------------------------------------------------
    def memory(self, r: Refs) -> tuple[str, str] | None:
        """-> (proposition, role): what part the NPC played in the remembered event."""
        rng, P = self.rng, r.anyone
        when = lambda: rng.choice(("past", "long_ago"))  # noqa: E731

        def deed(a: str, b: str, role) -> tuple[str | None, str]:
            d = self._deed(r, a, b)
            return (f"({when()} {d})" if d else None), (role() if callable(role) else role)

        pair = lambda: self._pair(r)  # noqa: E731
        makers = [
            lambda: deed(P(rng), "me", "target"),
            lambda: deed("me", P(rng), "actor"),
            lambda: (lambda p: deed(p[0], p[1], lambda: rng.choice(("witness", "told"))) if p else (None, "told"))(pair()),
            lambda: (f"({when()} (dead {rng.choice(r.absent)}))", rng.choice(("told", "told", "witness"))) if r.absent else (None, "told"),
        ]
        rng.shuffle(makers)
        for m in makers:
            text, role = m()
            if text is not None:
                ok = self.validate(text, "memory")
                if ok is not None:
                    return ok, role
        return None

    # ---- what someone asked of the NPC: a full utterance, frozen in the HEARER's terms --------------
    def request(self, r: Refs, asker: str) -> str | None:
        """me = the NPC who heard it, `asker` = the pointer to whoever asked (language_grammar.toml: freezing)."""
        rng = self.rng
        young = self.me_age < YOUNG

        def work():
            if young:
                return None
            deed = self._deed(r, "me", rng.choice(r.things or [asker]))
            return f"(request {deed})" if deed else None
        makers = [
            lambda: f"(request (did me give {self._kind()} (to {asker})))",
            lambda: f"(offer (did {asker} give {self._kind(True)} (to me)))",
            lambda: f"(ask (at {rng.choice(r.persons)} where))" if r.persons else None,
            work,
        ]
        return self._first(makers, "request")
