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
from .gestures import INFANT, YOUNG, Choice, GestureChooser, Target
from .parties import PartyBook
from .pools import Pools
from .scene import LinkRules, Person

PHYSICAL_QUALITIES = ("w_beautiful", "w_ugly")          # never said of a possible minor
WORK_MIN_AGE = 14.0                                     # a trade, a craft: from this age
CHILD_TECHNIQUES = ("t_climbing", "t_swimming", "t_music", "t_foraging", "t_fishing", "t_stealth", "t_riding")
CONDITIONS = ("pain", "hunger", "thirst", "exhaustion", "stress", "sickness_felt", "intoxication")   # passing states
# what people hold to be forbidden, shameful, obligatory, admirable or allowed: deontic word -> gestures that make sense
NORM_DEEDS = {"forbidden": ("strike", "push", "grab", "take", "throw"), "shameful": ("strike", "push", "take", "throw"),
              "obligatory": ("give", "work", "pour", "scoop"), "admirable": ("give", "work", "scoop", "tie"),
              "permitted": ("eat", "drink", "sleep", "rest", "wear", "go", "take")}
# what a thing is worth, in copper, by category (a coin is worth its metal); noise is added
VALUE = {"bread": 2, "produce": 2, "meat": 5, "dish": 4, "drink": 3, "tableware": 4, "kitchen": 10, "container": 6,
         "clothing": 12, "headwear": 6, "footwear": 10, "furniture": 25, "textile": 10, "toy": 3, "game": 8, "light": 3,
         "farming": 15, "forestry": 18, "carpentry": 15, "smithing": 25, "masonry": 15, "fishing": 12, "hunting": 14,
         "blade": 30, "blunt": 20, "polearm": 25, "ranged": 35, "armor": 60, "jewel": 90, "writing": 20, "trade": 20,
         "music": 40, "religion": 15, "healing": 20, "medicine": 25, "magic_tool": 120, "magic_stock": 150,
         "metal_stock": 40, "vehicle": 120, "husbandry": 15, "mining": 18, "leather": 12, "fiber": 10, "building": 8}
COIN = {"copper_coin": 1, "silver_coin": 10, "gold_coin": 100, "debased_coin": 1, "coin_purse_full": 30}
MAX_HOWS = 3                                            # event roles after the target (language.MAX_ROLES)
PAST_LIMIT = 200.0                                      # game hours: `past` is more recent, `long_ago` is older


@dataclass
class Refs:
    """The NPC's pointers usable in a proposition (keys of its records). Build it with keywords. Persons are the
    living ones: the dead are apart, and a ghost (known, no file) is cited rarely."""
    filed: list[str] = field(default_factory=list)          # @E keys of living persons with a file (here or not)
    ghosts: list[str] = field(default_factory=list)         # @E keys of living persons without a file
    absent: list[str] = field(default_factory=list)         # living persons who are not here (files first)
    dead: list[str] = field(default_factory=list)           # persons he knows are dead
    things: list[str] = field(default_factory=list)         # @T keys (seen things and carried ones)
    loci: list[str] = field(default_factory=list)           # @L keys
    groups: list[str] = field(default_factory=list)         # @G keys
    here: list[str] = field(default_factory=list)           # @E keys of persons present
    animals: frozenset = frozenset()                        # @T keys that are animals
    thing_kinds: dict = field(default_factory=dict)         # @T key -> kind (item type or species)
    owners: dict = field(default_factory=dict)              # @T key -> owner key as the NPC believes it
    links: dict = field(default_factory=dict)               # @E key -> ENTITY.link (what he is to the NPC)
    kinds: list[str] = field(default_factory=list)          # item kinds that belong to this place and this person
    GHOST_RATE = 0.08

    @property
    def persons(self) -> list[str]:
        return self.filed + self.ghosts

    def someone(self, rng) -> str | None:
        """A living person other than him: mostly one with a file."""
        if self.ghosts and (not self.filed or rng.random() < self.GHOST_RATE):
            return rng.choice(self.ghosts)
        return rng.choice(self.filed) if self.filed else None

    def anyone(self, rng) -> str:
        return "me" if (not self.filed and not self.ghosts) or rng.random() < 0.25 else self.someone(rng)


@dataclass
class Belief:
    """A proposition he holds; `contradicted` when it was built to be wrong (and he has met the contradiction)."""
    prop: str
    contradicted: bool = False


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

    def session(self, rng: random.Random, book: PartyBook, me: Person, refs: Refs, needs: dict | None = None) -> "PropositionSession":
        return PropositionSession(self, rng, book, me, refs, needs)



class PropositionSession:
    """The propositions of ONE situation."""

    def __init__(self, grammar: PropositionGrammar, rng: random.Random, book: PartyBook, me: Person, refs: Refs,
                 needs: dict | None = None):
        self.g, self.rng, self.book, self.me, self.refs = grammar, rng, book, me, refs
        self.d = Draw(rng)
        self.needs = needs or {}                  # need -> level (0-10): a need goal follows its level

    # ---- validation -------------------------------------------------------------------------------------
    def validate(self, text: str, kind: str = "belief") -> str | None:
        return self.g.validate(text, kind, self.book.party("me"), self.book.content_parties())

    def _first(self, makers, kind: str):
        """Try the makers in a random order until one gives a valid proposition (a maker returns text, a Belief or
        None); -> the Belief."""
        makers = list(makers)
        self.rng.shuffle(makers)
        for m in makers:
            got = m()
            if got is None:
                continue
            got = got if isinstance(got, Belief) else Belief(got)
            if self.validate(got.prop, kind) is not None:
                return got
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

    def someone(self) -> str | None:
        return self.refs.someone(self.rng)

    def _quality(self, subject: str) -> str:
        words = self.g.words["quality"]
        if self.book.may_be_minor(subject) or self._age(subject) < 18.0:
            words = [w for w in words if w not in PHYSICAL_QUALITIES]
        return self.rng.choice(words)

    def _pair(self) -> tuple[str, str] | None:
        a = self.refs.anyone(self.rng)
        for _ in range(8):
            b = self.refs.anyone(self.rng)
            if b != a:
                return a, b
        return None

    def target(self, key: str) -> Target | None:
        r = self.refs
        if key in ("me", "anyone", "someone") or key.startswith(("@E", "n:")):
            p = self._person(key)
            return Target("agent", None, frozenset(("carried",)) if p is not None and p.age < 3 else frozenset())
        if key.startswith("@T"):
            return Target("animal" if key in r.animals else "item", r.thing_kinds.get(key))
        if key.startswith(("@L", "@PLACE")):
            return Target("place")
        return None

    def a_thing(self) -> str | None:
        return self.rng.choice(self.refs.things) if self.refs.things else None

    def deed(self, actor: str, target: str, only: tuple[str, ...] | None = None) -> tuple[str, Choice] | None:
        """(did ACTOR gesture TARGET [(how …)]) with a gesture the governor allows between these two."""
        t = self.target(target)
        if actor == target or t is None:
            return None
        age = self._age(actor) if actor not in ("anyone", "someone") else 30.0
        pick = self.g.chooser.pick(self.d, t, self.book.party(actor), self.book.party(target), age=age, only=only)
        if pick is None or len(pick.manner) > MAX_HOWS:
            return None
        hows = "".join(f" (how {m})" for m in pick.manner)
        return f"(did {actor} {pick.gesture} {target}{hows})", pick

    def _deed_text(self, actor: str, target: str, only=None) -> str | None:
        got = self.deed(actor, target, only)
        return got[0] if got else None

    def _gift(self, giver: str, taker: str) -> str | None:
        """(did GIVER give KIND (to TAKER)): a gift, the thing that is not done to a person but to a thing."""
        return f"(did {giver} give {self.kind(gift=True)} (to {taker}))" if giver != taker else None

    # ---- beliefs ------------------------------------------------------------------------------------
    def belief(self) -> Belief | None:
        rng, r = self.rng, self.refs
        subj = lambda: r.anyone(rng)  # noqa: E731
        adult = self.me.age >= YOUNG
        makers = [
            self._owns if r.things else None,
            lambda: f"(has {subj()} {self.kind(True)})",
            self._at_a_locus if r.absent and r.loci else None,
            lambda: f"(lives_at {subj()} {rng.choice(r.loci)})" if r.loci else None,
            self._quality_belief,
            lambda: self._state(subj()),
            lambda: self._condition(subj()),
            lambda: self._works(subj()),
            self._link,
            lambda: self._knows(subj()),
            self._worth if adult else None,
            self._norm if adult else None,
            self._past_deed,
            self._believes,
            lambda: f"(member {subj()} {rng.choice(r.groups)})" if r.groups else None,
            lambda: self._holds(subj()),
        ]
        return self._first([m for m in makers if m is not None], "belief")

    def _at_a_locus(self) -> str | None:
        r = self.refs
        who = r.absent[self.rng.randrange(len(r.absent))]
        return f"(at {who} {self.rng.choice(r.loci)})"

    def _owns(self) -> Belief | str:
        """(owns X T): what he believes of the thing's owner (THING.owner); when he has no such belief, a guess that
        he has already met the contradiction of."""
        r = self.refs
        t = self.rng.choice(r.things)
        believed = r.owners.get(t)
        if believed:
            return f"(owns {believed} {t})"
        who = self.refs.anyone(self.rng)
        return Belief(f"(owns {who} {t})", contradicted=True)

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
        who, s = self.refs.anyone(self.rng), self.refs.anyone(self.rng)
        return f"(believes {who} (quality {s} {self._quality(s)} {self._w('degree')}))" if who != s else None

    def worth_of(self, kind: str) -> int:
        """What a thing is worth, from what it is (a coin is its metal), with a merchant's noise."""
        base = COIN.get(kind) or VALUE.get(self.g.pools.category_of.get(kind, ""), 6)
        return max(1, round(base * self.rng.uniform(0.6, 1.6)))

    def _worth(self) -> str:
        k = self.kind().partition(":")[0]
        return f"(worth {k} {self.worth_of(k)})"

    def _norm(self) -> str | None:
        """(norm DEONTIC (did anyone GESTURE TARGET)): a rule that makes sense (striking is forbidden, giving is
        admirable, eating is allowed)."""
        deontic = self.rng.choice([w for w in NORM_DEEDS if w in self.g.words["deontic"]] or ["forbidden"])
        gestures = NORM_DEEDS[deontic]
        targets = [x for x in (self.a_thing(), "someone") if x]
        self.rng.shuffle(targets)
        for t in targets:
            deed = self._deed_text("anyone", t, only=gestures)
            if deed:
                return f"(norm {deontic} {deed})"
        return None

    def _past_deed(self) -> str | None:
        pair = self._pair()
        if pair is None:
            return None
        thing = self.a_thing()
        deed = self._deed_text(pair[0], thing if thing and self.rng.random() < 0.5 else pair[1])
        return f"(past {deed})" if deed else None

    def _link(self) -> str | None:
        """(link X L Y) = X is the L of Y. Toward `me` it repeats ENTITY.link; between two others, a link that fits
        their ages. Never the same person twice, never an intimate link."""
        r, rng = self.refs, self.rng
        known = [k for k in r.filed if r.links.get(k) not in (None, "stranger") and r.links[k] not in self.g.bad]
        if known and rng.random() < 0.5:
            x = rng.choice(known)
            return f"(link {x} {r.links[x]} me)"
        if len(r.filed) < 2:
            return None
        a, b = rng.sample(r.filed, 2)                      # two others: `me` only through ENTITY.link above
        fits = [w for w in self.g.words["link"] if self.g.rules.fits(w, self._true_age(a), self._true_age(b))]
        return f"(link {a} {rng.choice(fits)} {b})" if fits else None

    # ---- what someone said to him ---------------------------------------------------------------------
    def utterance(self, speaker: str) -> str | None:
        """What `speaker` could plausibly tell him: what he has, where he lives, his trade, a price, who is where,
        what he thinks of someone, who died, what happened. Not a random predicate."""
        rng, r = self.rng, self.refs
        other = lambda: next((x for x in (self.someone() for _ in range(6)) if x and x != speaker), None)  # noqa: E731
        makers = [
            lambda: f"(has {speaker} {self.kind(True)})",
            lambda: f"(lives_at {speaker} {rng.choice(r.loci)})" if r.loci else None,
            lambda: self._works(speaker),
            self._worth,
            lambda: self._at_a_locus() if r.absent and r.loci else None,
            lambda: (lambda o: f"(quality {o} {self._quality(o)} {self._w('degree')})" if o else None)(other()),
            lambda: (lambda o: self._past_deed_of(speaker, o))(other()),
            lambda: f"(dead {rng.choice(r.dead)})" if r.dead else None,
            lambda: next((f"(owns {speaker} {t})" for t in r.things if r.owners.get(t) == speaker), None),
        ]
        got = self._first([m for m in makers if m is not None], "belief")
        return got.prop if got else None

    def _past_deed_of(self, a: str, b: str | None) -> str | None:
        deed = self._deed_text(a, b) if b else None
        return f"(past {deed})" if deed else None

    # ---- goals --------------------------------------------------------------------------------------
    NEED_WORDS = (("hunger", "hunger"), ("thirst", "thirst"), ("exhaustion", "exhaustion"), ("pain", "pain"))

    def goal(self) -> tuple[str, str] | None:
        """-> (proposition, mode): achieve, avoid or maintain. A need becomes a goal in proportion to its level."""
        rng, r = self.rng, self.refs
        young, works = self.me.age < YOUNG, self.me.age >= WORK_MIN_AGE
        friends = [k for k in r.filed if self.g.rules.fits("friend", self._true_age(k), self.me.age)
                   and r.links.get(k) not in ("friend", "spouse", "betrothed", "lover", "parent", "child", "sibling")]

        def trade():
            occ = self.occupation_of("me")
            return f"(works_as me {occ if occ and rng.random() < 0.6 else self._w('occupation')})" if works else None
        makers = [  # (maker, mode, weight)
            (lambda: f"(has me {self.kind(True)})", "achieve", 1.0),
            (lambda: f"(at me {rng.choice(r.loci)})" if r.loci else None, "achieve", 0.7),
            (lambda: f"(owns me {rng.choice(r.things)})" if r.things else None, "achieve", 0.8),
            (lambda: f"(quality me {self._quality('me')} high)", "maintain", 0.3),
            (trade, "maintain", 0.4),
            (lambda: f"(knows_how me {self._w('technique')})" if not young and works else None, "achieve", 0.3),
            (lambda: f"(link {rng.choice(friends)} friend me)" if friends else None, "achieve", 0.4),
        ]
        for need, level in self.needs.items():
            if level >= 2.5:
                w = (level / 10.0) ** 2 * 5
                makers.append((lambda n=need: f"(state me {n} low)", "achieve", w))
                makers.append((lambda n=need: f"(state me {n} high)", "avoid", w * 0.25))
        pool = list(makers)
        while pool:
            i = rng.choices(range(len(pool)), weights=[m[2] for m in pool])[0]
            maker, mode, _ = pool.pop(i)
            text = maker()
            if text is not None and self.validate(text, "goal") is not None:
                return text, mode
        return None

    def need_goal(self, need: str) -> str | None:
        """A goal that follows from a need (used to justify a plan): (state me NEED low)."""
        return self.validate(f"(state me {need} low)", "goal")

    # ---- memories -----------------------------------------------------------------------------------
    def memory(self, death: bool = False) -> Recalled | None:
        """A remembered event, with the part he played; `past` if it is recent (< 200 h), `long_ago` if not. Deeds
        bear on things as often as on people; a death is remembered only when somebody is dead."""
        rng, r = self.rng, self.refs
        age = self.d.log_uniform(1, 5000)
        when = "past" if age < PAST_LIMIT else "long_ago"
        anyone = lambda: self.refs.anyone(rng)  # noqa: E731

        def deed(a: str, b: str | None, role: str) -> Recalled | None:
            got = self.deed(a, b) if a and b else None
            return Recalled(f"({when} {got[0]})", role, got[1].gesture, age) if got else None

        def gift(a: str, b: str, role: str) -> Recalled | None:
            text = self._gift(a, b)
            return Recalled(f"({when} {text})", role, "give", age) if text else None

        def other() -> Recalled | None:
            pair = self._pair()
            return deed(pair[0], pair[1], rng.choice(("witness", "told"))) if pair else None

        def dead() -> Recalled | None:
            return Recalled(f"({when} (dead {rng.choice(r.dead)}))", rng.choice(("told", "told", "witness")), None, age, True) \
                if r.dead else None
        if death:
            return dead()
        makers = [(lambda: deed(anyone(), "me", "target"), 0.14), (lambda: deed("me", self.a_thing(), "actor"), 0.24),
                  (lambda: deed(anyone(), self.a_thing(), rng.choice(("witness", "told"))), 0.22),
                  (lambda: gift(anyone(), "me", "target"), 0.04), (lambda: gift("me", anyone(), "actor"), 0.04),
                  (other, 0.14), (lambda: deed(self.someone(), self.a_thing(), "witness"), 0.1)]
        pool = list(makers)
        while pool:
            i = rng.choices(range(len(pool)), weights=[m[1] for m in pool])[0]
            got = pool.pop(i)[0]()
            if got is not None and self.validate(got.prop, "memory") is not None:
                return got
        return None

    # ---- what someone asked of the NPC: a full utterance, frozen in the HEARER's terms --------------
    def request(self, asker: str) -> str | None:
        """me = the NPC who heard it, `asker` = the pointer to whoever asked (language_grammar.toml: freezing). A baby
        is asked nothing; a small child only to hand something over."""
        if self.me.age < INFANT:
            return None
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
            lambda: f"(ask (at {self.someone() or asker} where))",
            work,
        ]
        got = self._first(makers, "request")
        return got.prop if got else None
