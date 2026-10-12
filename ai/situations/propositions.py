"""propositions.py - typed propositions of the inner language for beliefs, goals, memories and requests.

Two objects: a `PropositionGrammar`, built once (the vocabulary, the words, the gesture chooser, the governor, the
counters), and a `PropositionSession` made for each situation (its random draws, the parties of the scene, the
pointers the NPC has). Nothing is shared between two situations but the grammar.

Each template is a general predicate of the catalogue (owns, at, quality, link, did...) filled from the NPC's own
files (its pointers), never a story. Every result is checked by the language validator (catalogue/tools/
language.py) and then by the GOVERNOR (D10, with the parties of the scene): an invalid one is dropped and counted,
a refused one is counted apart. D10 by construction: no intimate symbol is generated here (links such as spouse
reach the model through ENTITY.link, between adults only, see scene.py); a deed is told only with a gesture the
governor allows for those people; no physical quality (beauty, ugliness) is said of a possible minor.
Plausibility: no trade or craft for a child, a link only between ages that fit it, a trade that comes from the
person's occupation (sometimes mistaken), a person present is not "at" a faraway place, only stable traits are
told as traits, and things that belong to this place.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import language
from governor import Party

from .draw import Draw
from .gestures import YOUNG, Choice, GestureChooser, Target
from .parties import PartyBook
from .pools import Pools
from .scene import LinkRules, Person

PHYSICAL_QUALITIES = ("w_beautiful", "w_ugly")          # never said of a possible minor
WORK_MIN_AGE = 14.0                                     # a trade, a craft: from this age
CHILD_TECHNIQUES = ("t_climbing", "t_swimming", "t_music", "t_foraging", "t_fishing", "t_stealth", "t_riding")
CONDITIONS = ("pain", "hunger", "thirst", "exhaustion", "stress", "sickness_felt", "intoxication")   # passing states
MAX_HOWS = 3                                            # event roles after the target (language.MAX_ROLES)
PAST_LIMIT = 200.0                                      # game hours: `past` is more recent, `long_ago` is older


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
    thing_kinds: dict = field(default_factory=dict)         # @T key -> kind (item type or species)
    owners: dict = field(default_factory=dict)              # @T key -> owner key as the NPC believes it
    links: dict = field(default_factory=dict)               # @E key -> ENTITY.link (what he is to the NPC)
    kinds: list[str] = field(default_factory=list)          # item kinds that belong to this place and this person

    def anyone(self, rng) -> str:
        return rng.choice(self.persons + ["me"]) if self.persons else "me"


@dataclass
class Recalled:
    """A memory before it is coloured: the proposition, the part he played, the gesture, how old it is."""
    prop: str
    role: str                                               # actor | target | witness | told
    gesture: str | None                                     # None for a death
    age: float                                              # game hours
    death: bool = False


@dataclass
class Stats:
    made: int = 0
    invalid: int = 0            # not a valid sentence of the language
    refused: int = 0            # valid but refused by the governor (D10)

    @property
    def total(self) -> int:
        return self.made + self.invalid + self.refused


class PropositionGrammar:
    """Everything that does not change from one situation to the next."""

    def __init__(self, pools: Pools):
        self.pools = pools
        self.vocab = language.Vocabulary(pools.cat)
        self.gov = pools.governor
        self.chooser = GestureChooser(pools)
        self.rules = LinkRules(pools)
        self.stats = Stats()
        bad = self.bad = pools.intimate_symbols
        self.words = {c: [w for w in pools.concepts(c) if w not in bad] for c in (
            "degree", "quality", "occupation", "technique", "link", "deontic", "role_word")}
        self.words["quality"] = [w for w in self.words["quality"] if w not in ("w_true", "w_false")]   # not of a person
        self.words["link"] = [w for w in self.words["link"] if w != "stranger"]
        variables = pools.cat["variable"]
        # stable traits only: the NPC's temperament and values (never a relation r_*, never a passing state)
        self.traits = sorted(w for w, cs in self.vocab.cats.items() if "variable" in cs and w not in bad
                             and getattr(variables.get(w), "holder", "") == "mind_static"
                             and variables[w].scale in ("bipolar10", "unipolar10"))
        self.conditions = [w for w in CONDITIONS if "variable" in self.vocab.cats.get(w, ())]
        # kinds that can be given, taken, worth: an item type that is also a species (beans) is a plant to the language
        self.kinds = sorted(k for ks in pools.items_by_category.values() for k in ks
                            if "item" in language.ref_targets(k, self.vocab))
        self.valid_kinds = frozenset(self.kinds)
        # what one can hand over: small enough to carry (not a cupboard)
        self.gift_kinds = frozenset(k for k in self.kinds if pools.item_has(k, "graspable") and pools.item_has(k, "carryable")
                                    and pools.item_vector(k).get("mass", 99.0) <= 10.0)

    def validate(self, text: str, kind: str, owner: Party, parties: dict) -> str | None:
        """`text` if it is a sentence of the language that the governor allows, else None. kind: belief | goal |
        memory (a bare proposition) or request (a full utterance, in the hearer's terms)."""
        e = language.Expression(text, self.vocab, bare=kind != "request")
        if not e.ok or any(s in self.bad for s in e.root.symbols()):
            self.stats.invalid += 1
            return None
        v = self.gov.check_record("goal" if kind == "request" else kind, e, owner, parties)
        if not v.allowed:
            self.stats.refused += 1
            return None
        self.stats.made += 1
        return text

    def session(self, rng: random.Random, book: PartyBook, me: Person, refs: Refs) -> "PropositionSession":
        return PropositionSession(self, rng, book, me, refs)


class PropositionSession:
    """The propositions of ONE situation."""

    def __init__(self, grammar: PropositionGrammar, rng: random.Random, book: PartyBook, me: Person, refs: Refs):
        self.g, self.rng, self.book, self.me, self.refs = grammar, rng, book, me, refs
        self.d = Draw(rng)

    # ---- validation -------------------------------------------------------------------------------------
    def validate(self, text: str, kind: str = "belief") -> str | None:
        return self.g.validate(text, kind, self.book.party("me"), self.book.content_parties())

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

    # ---- pieces -----------------------------------------------------------------------------------------
    def _w(self, cat: str) -> str:
        return self.rng.choice(self.g.words[cat])

    def kind(self, count: bool = False, gift: bool = False) -> str:
        """An item kind that belongs here (this place, this scene, what he carries), sometimes with a count; with
        gift=True one that can be handed over."""
        pool = self.refs.kinds or self.g.kinds
        if gift:
            pool = [k for k in pool if k in self.g.gift_kinds] or sorted(self.g.gift_kinds)
        k = self.rng.choice(pool)
        return f"{k}:{self.rng.randint(2, 12)}" if count and self.rng.random() < 0.3 else k

    def _age(self, key: str) -> float:
        return self.me.age if key == "me" else self.book.min_age(key)

    def _true_age(self, key: str) -> float:
        return self.me.age if key == "me" else self.book.truth[key].age

    def _person(self, key: str) -> Person | None:
        return self.me if key == "me" else self.book.truth.get(key)

    def _quality(self, subject: str) -> str:
        words = self.g.words["quality"]
        if self.book.may_be_minor(subject) or self._age(subject) < 18.0:
            words = [w for w in words if w not in PHYSICAL_QUALITIES]
        return self.rng.choice(words)

    def _pair(self) -> tuple[str, str] | None:
        pool = self.refs.persons + ["me"]
        return tuple(self.rng.sample(pool, 2)) if len(pool) >= 2 else None

    def target(self, key: str) -> Target | None:
        r = self.refs
        if key in ("me", "anyone", "someone") or key.startswith(("@E", "n:")):
            return Target("agent")
        if key.startswith("@T"):
            return Target("animal" if key in r.animals else "item", r.thing_kinds.get(key))
        if key.startswith(("@L", "@PLACE")):
            return Target("place")
        return None

    def deed(self, actor: str, target: str) -> tuple[str, Choice] | None:
        """(did ACTOR gesture TARGET [(how …)]) with a gesture the governor allows between these two."""
        t = self.target(target)
        if actor == target or t is None:
            return None
        age = self._age(actor) if actor not in ("anyone", "someone") else 30.0
        pick = self.g.chooser.pick(self.d, t, self.book.party(actor), self.book.party(target), age=age)
        if pick is None or len(pick.manner) > MAX_HOWS:
            return None
        hows = "".join(f" (how {m})" for m in pick.manner)
        return f"(did {actor} {pick.gesture} {target}{hows})", pick

    def _deed_text(self, actor: str, target: str) -> str | None:
        got = self.deed(actor, target)
        return got[0] if got else None

    def _gift(self, giver: str, taker: str) -> str | None:
        """(did GIVER give KIND (to TAKER)): a gift, the thing that is not done to a person but to a thing."""
        return f"(did {giver} give {self.kind(gift=True)} (to {taker}))" if giver != taker else None

    # ---- beliefs ------------------------------------------------------------------------------------
    def belief(self) -> str | None:
        rng, r = self.rng, self.refs
        subj = lambda: r.anyone(rng)  # noqa: E731
        makers = [
            self._owns if r.things else None,
            lambda: f"(has {subj()} {self.kind(True)})",
            lambda: f"(at {rng.choice(r.absent)} {rng.choice(r.loci)})" if r.absent and r.loci else None,
            lambda: f"(at {rng.choice(r.here)} @PLACE)" if r.here else None,
            lambda: f"(lives_at {subj()} {rng.choice(r.loci)})" if r.loci else None,
            self._quality_belief,
            lambda: self._state(subj()),
            lambda: self._condition(subj()),
            lambda: self._works(subj()),
            self._link,
            lambda: self._knows(subj()),
            lambda: f"(worth {self.kind()} {rng.randint(1, 40)})",
            self._norm,
            self._past_deed,
            self._believes,
            lambda: f"(member {subj()} {rng.choice(r.groups)})" if r.groups else None,
            lambda: self._holds(subj()),
        ]
        return self._first([m for m in makers if m is not None], "belief")

    def _owns(self) -> str:
        r = self.refs
        t = self.rng.choice(r.things)
        believed = r.owners.get(t)
        if believed and self.rng.random() < 0.6:              # what the NPC already believes of this thing
            return f"(owns {believed} {t})"
        return f"(owns {r.anyone(self.rng)} {t})"

    def _quality_belief(self) -> str:
        s = self.refs.anyone(self.rng)
        return f"(quality {s} {self._quality(s)} {self._w('degree')})"

    def _state(self, s: str) -> str | None:
        return f"(state {s} {self.rng.choice(self.g.traits)} {self._w('degree')})" if self.g.traits else None

    def _condition(self, s: str) -> str | None:
        return f"(state {s} {self.rng.choice(self.g.conditions)} {self._w('degree')})" if self.g.conditions else None

    def occupation_of(self, s: str) -> str | None:
        """The trade the NPC believes of s: what the person does (Person.occupation), sometimes mistaken."""
        p, words = self._person(s), self.g.words["occupation"]
        if p is None or p.age < WORK_MIN_AGE or not words:
            return None
        if p.occupation in words and self.rng.random() < 0.8:
            return p.occupation
        return self.rng.choice(words) if (p.occupation or self.rng.random() < 0.1) else None

    def _works(self, s: str) -> str | None:
        occ = self.occupation_of(s)
        return f"(works_as {s} {occ})" if occ else None

    def _holds(self, s: str) -> str | None:
        return f"(holds {s} {self._w('role_word')})" if self._age(s) >= WORK_MIN_AGE else None

    def _knows(self, s: str) -> str | None:
        age = self._age(s)
        if age < YOUNG:
            return None
        words = self.g.words["technique"]
        techniques = words if age >= WORK_MIN_AGE else [t for t in CHILD_TECHNIQUES if t in words]
        return f"(knows_how {s} {self.rng.choice(techniques)})" if techniques else None

    def _believes(self) -> str | None:
        r = self.refs
        who, s = r.anyone(self.rng), r.anyone(self.rng)
        return f"(believes {who} (quality {s} {self._quality(s)} {self._w('degree')}))" if who != s else None

    def _norm(self) -> str | None:
        r = self.refs
        deed = self._deed_text("anyone", self.rng.choice(r.things or ["@PLACE"]))
        return f"(norm {self._w('deontic')} {deed})" if deed else None

    def _past_deed(self) -> str | None:
        pair = self._pair()
        deed = self._deed_text(*pair) if pair else None
        return f"(past {deed})" if deed else None

    def _link(self) -> str | None:
        """(link X L Y) = X is the L of Y. Toward `me` it repeats ENTITY.link; between two others, a link that fits
        their ages. Never the same person twice, never an intimate link."""
        r, rng = self.refs, self.rng
        known = [k for k in r.persons if r.links.get(k) not in (None, "stranger") and r.links[k] not in self.g.bad]
        if known and rng.random() < 0.5:
            x = rng.choice(known)
            return f"(link {x} {r.links[x]} me)"
        if len(r.persons) < 2:
            return None
        a, b = rng.sample(r.persons, 2)                    # two others: `me` only through ENTITY.link above
        fits = [w for w in self.g.words["link"] if self.g.rules.fits(w, self._true_age(a), self._true_age(b))]
        return f"(link {a} {rng.choice(fits)} {b})" if fits else None

    # ---- goals --------------------------------------------------------------------------------------
    def goal(self) -> tuple[str, str] | None:
        """-> (proposition, mode): achieve, avoid or maintain."""
        rng, r = self.rng, self.refs
        young, works = self.me.age < YOUNG, self.me.age >= WORK_MIN_AGE
        friends = [k for k in r.persons if self.g.rules.fits("friend", self._true_age(k), self.me.age)
                   and r.links.get(k) not in ("friend", "spouse", "betrothed", "lover", "parent", "child", "sibling")]

        def trade():
            occ = self.occupation_of("me")
            return f"(works_as me {occ if occ and rng.random() < 0.6 else self._w('occupation')})" if works else None
        makers = [
            (lambda: f"(has me {self.kind(True)})", "achieve"),
            (lambda: f"(at me {rng.choice(r.loci)})" if r.loci else None, "achieve"),
            (lambda: f"(owns me {rng.choice(r.things)})" if r.things else None, "achieve"),
            (lambda: f"(quality me {self._quality('me')} high)", "maintain"),
            (trade, "maintain"),
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

    def need_goal(self, need: str) -> str | None:
        """A goal that follows from a need (used to justify a plan): (state me NEED low)."""
        return self.validate(f"(state me {need} low)", "goal")

    # ---- memories -----------------------------------------------------------------------------------
    def memory(self) -> Recalled | None:
        """A remembered event, with the part he played; `past` if it is recent (< 200 h), `long_ago` if not."""
        rng, P, r = self.rng, self.refs.anyone, self.refs
        age = self.d.log_uniform(1, 5000)
        when = "past" if age < PAST_LIMIT else "long_ago"

        def deed(a: str, b: str, role: str) -> Recalled | None:
            got = self.deed(a, b)
            return Recalled(f"({when} {got[0]})", role, got[1].gesture, age) if got else None

        def gift(a: str, b: str, role: str) -> Recalled | None:
            text = self._gift(a, b)
            return Recalled(f"({when} {text})", role, "give", age) if text else None

        def other() -> Recalled | None:
            pair = self._pair()
            return deed(pair[0], pair[1], rng.choice(("witness", "told"))) if pair else None

        def death() -> Recalled | None:
            if not r.absent:
                return None
            return Recalled(f"({when} (dead {rng.choice(r.absent)}))", rng.choice(("told", "told", "witness")), None, age, True)

        makers = [lambda: deed(P(rng), "me", "target"), lambda: deed("me", P(rng), "actor"),
                  lambda: gift(P(rng), "me", "target"), lambda: gift("me", P(rng), "actor"), other, death]
        rng.shuffle(makers)
        for m in makers:
            got = m()
            if got is not None and self.validate(got.prop, "memory") is not None:
                return got
        return None

    # ---- what someone asked of the NPC: a full utterance, frozen in the HEARER's terms --------------
    def request(self, asker: str) -> str | None:
        """me = the NPC who heard it, `asker` = the pointer to whoever asked (language_grammar.toml: freezing)."""
        rng, r = self.rng, self.refs
        young = self.me.age < YOUNG

        def work():
            if young:
                return None
            deed = self._deed_text("me", rng.choice(r.things or [asker]))
            return f"(request {deed})" if deed else None
        makers = [
            lambda: f"(request (did me give {self.kind(gift=True)} (to {asker})))",
            lambda: f"(offer (did {asker} give {self.kind(True, gift=True)} (to me)))",
            lambda: f"(ask (at {rng.choice(r.persons)} where))" if r.persons else None,
            work,
        ]
        return self._first(makers, "request")
