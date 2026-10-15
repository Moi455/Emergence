"""violence.py - violent and revenge goals born of human motives, alone or in a group (T12b).

Decision of the project owner (15 Oct.): "the sampler must also propose violent group goals, because it is natural,
and we want maximum realism". The charter does not limit violence; the only hard rule is D10 (nothing romantic or
sexual with a child or a teenager). So the sampler offers CONTEXTS in which an adult NPC (alone or with others) has a
goal of force or revenge, born of a motive a village understands: a betrayal, a theft, a debt, an insult, a rival, an
inheritance, a dead relative, popular justice, plain greed. Or in which he knows somebody else means harm, or in
which he is the one hunted. Everything is said with the grammar that already exists (abstract gestures strike /
push / go / wait / take / speak, propositions, the judgements of the catalogue): no new gesture, nothing explicit,
no gory detail. The sampler BUILDS the situation; what the NPC does about it is for the teacher to label. No rule of
behaviour is written here.

Written by a `ViolenceBuilder`, between the GroupBuilder and the GoalBuilder:
  * a PLOT is drawn per situation, with a rate that depends on the family of structure (conflict first, then loss,
    debt, authority...): `own` (his aim, 80 %), `witness` (somebody else's plan reaches him, 12 %), `hunted` (the aim
    is against him, 8 %);
  * a MOTIVE writes the grievance the aim is born of (beliefs, memories, an agreement not kept, a sour file);
  * an AIM, drawn among the forms the motive allows: kill, wound, beat, drive out, rob, burn, ambush, unseat, lynch;
  * sometimes a GROUP: the NPC, a leader and a few adults, whose aim says `us` (the group record is never named by
    its own aim: tok-2 refuses it), or the leader, or one member;
  * sub-goals (be armed, be at the place), a time mark, and now and then a DILEMMA (a kindness remembered, a remorse,
    a wish that the man be spared); the plan table (plans.py) gives the multi-step plans: follow, wait, win accomplices
    over, arm himself, go there, strike.

PRUDENCE (decision to be validated with the project owner): the TARGETS of an aim of force are adults, in truth
(at least SAFE_AGE years), in appearance when they are here, and in the age the NPC believes when they are not (a belief
`(state X age_years N)` is written). The NPC himself is an adult. No group aim, no goal, no plan is aimed at a child or
a teenager, and audit.py refuses it (`D10Audit._prudence`). Adultery itself cannot be said: its judgement and its links
are flagged intimate, which the audit refuses in any text; the motive is said as a betrayal (a gift to the spouse, a
promise broken).
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from tok2 import Record

from .builders import CERTAINTY, HOPS, KEY, RecordBuilder
from .context import BuildContext
from .layout import Entry
from .planning import GoalBuilder
from .propositions import PAST_LIMIT
from .scene import ADULT

SAFE_AGE = ADULT + 3.0                               # a target is at least this old in truth (a margin over majority)
NOT_TARGETED = ("child", "grandchild", "parent", "grandparent")        # no violence against these, even adult
# the chance that a situation has a plot, by family of structure (docs/14 10.2); conflict and loss are the families of it
RATE = {"conflict": 0.78, "loss": 0.30, "debt": 0.07, "authority": 0.07, "unequal_info": 0.04, "cooperation": 0.03,
        "scarcity": 0.03, "far_goal": 0.02, "ordinary": 0.015}
OLD_AGE = 70.0
KIND = {"own": 0.80, "witness": 0.12, "hunted": 0.08}
MOTIVE_BY_STRUCTURE = {
    "conflict": {"insult": 0.20, "betrayal": 0.19, "theft": 0.17, "rivalry": 0.14, "kin_revenge": 0.10, "debt": 0.07,
                 "inheritance": 0.06, "justice": 0.05, "greed": 0.02},
    "debt": {"debt": 0.55, "greed": 0.15, "theft": 0.12, "betrayal": 0.10, "insult": 0.08},
    "loss": {"kin_revenge": 0.50, "inheritance": 0.25, "betrayal": 0.10, "justice": 0.08, "insult": 0.07},
    "authority": {"justice": 0.34, "rivalry": 0.30, "insult": 0.14, "betrayal": 0.12, "theft": 0.10},
    "unequal_info": {"betrayal": 0.30, "theft": 0.25, "justice": 0.20, "insult": 0.15, "kin_revenge": 0.10},
    "cooperation": {"justice": 0.30, "greed": 0.20, "kin_revenge": 0.20, "rivalry": 0.15, "theft": 0.15},
    "scarcity": {"greed": 0.45, "theft": 0.30, "debt": 0.15, "justice": 0.10},
    "far_goal": {"rivalry": 0.35, "inheritance": 0.25, "kin_revenge": 0.20, "betrayal": 0.20},
    "ordinary": {"insult": 0.30, "theft": 0.25, "betrayal": 0.20, "rivalry": 0.15, "debt": 0.10},
}
GROUP_KINDS = {"g_band": 0.22, "g_crew": 0.14, "g_community": 0.2, "g_lineage": 0.14, "g_household": 0.1, "g_militia": 0.1,
               "g_guild": 0.04, "g_workshop": 0.03, "g_cult": 0.03}
ALLY_LINKS = {"friend": 3.0, "sibling": 2.5, "colleague": 2.0, "cousin": 2.0, "neighbor": 1.5, "in_law": 1.5, "employee": 1.0,
              "apprentice": 0.8, "aunt_uncle": 0.8, "niece_nephew": 0.8, "guest": 0.5, "stranger": 0.3}
ARMS = ("blade", "blunt", "polearm", "ranged", "farming", "forestry", "carpentry", "smithing", "masonry", "mining", "hunting")
SOURCES = {"seen": 0.38, "told": 0.28, "heard": 0.2, "inferred": 0.1, "assumed": 0.04}
DAYPARTS = {"night": 0.4, "dawn": 0.2, "evening": 0.3, "afternoon": 0.05, "morning": 0.03, "noon": 0.02}
TIMED_RATE = 0.30                                    # an aim with a time: "at night", "at dawn"
DILEMMA_RATE = 0.30
DILEMMAS = {"kindness": 0.38, "remorse": 0.32, "spare": 0.30}


@dataclass
class PlotSummary:
    """What the sampler knows about the plot it wrote (for the statistics and the tests; never shown to the model)."""
    kind: str                         # own | witness | hunted
    motive: str
    forms: tuple[str, ...]            # the aims written (kill, beat, ...)
    grouped: bool                     # a group record carries the aim
    target: str                       # key of the person the force is aimed at ("me" when hunted)
    aggressor: str = ""               # witness: who means to do it
    dilemma: str = ""


# ---------------------------------------------------------------------------------------------------- the pen
class Scribe:
    """Writes records within the budget of their type: a free place, else the place of a record the plot did not write
    (a belief that vouches for an age is never taken)."""

    def __init__(self, c: BuildContext):
        self.c, self.d = c, c.d
        self.mine: set[str] = set()

    def _put(self, typ: str, prefix: str, fields: dict) -> str | None:
        c = self.c
        records = c.of(typ)
        if len(records) < c.cap[typ]:
            key = f"{prefix}:{len(records) + 1}"
            c.add(Record(typ, key, c.fill(typ, fields)))
        else:
            free = [r for r in records if r.key not in self.mine and "age_years" not in str(r.fields.get("prop", ""))
                    and not str(r.fields.get("counterparty", "")).startswith("@G")]
            if not free:
                return None
            r = self.d.pick(free)
            key = r.key
            r.fields.clear()
            r.fields.update(c.fill(typ, fields))
        self.mine.add(key)
        return key

    def _existing(self, typ: str, prop: str) -> str | None:
        return next((r.key for r in self.c.of(typ) if r.fields.get("prop") == prop), None)

    def belief(self, prop: str, source: str = "seen", informant: str = "", contradicted: bool = False,
               shared: list | None = None, secret: bool = False) -> str | None:
        c, d = self.c, self.d
        if (key := self._existing("BELIEF", prop)) is not None:
            return key
        if c.session.validate(prop, "belief") is None:
            return None
        if source in ("told", "heard") and not informant:
            source = "inferred"
        c.said.add(prop)
        mu, sd = CERTAINTY[source]
        cert = d.gauss(mu, sd)
        return self._put("BELIEF", "b", {
            "prop": prop, "source": source, "age": c.hours_ago(0.5, 600), "contradicted": contradicted, "polarity": True,
            "hops": d.between(*HOPS[source]), "certainty": round(cert * 0.4, 1) if contradicted else cert,
            "informant": informant if source in ("told", "heard") else "", "shared": shared or [], "secret": secret})

    def memory(self, prop: str, role: str, emotion: str, valence: tuple[float, float], interp: str | None,
               age: float | None = None) -> str | None:
        """A memory of `(past E)`: the word is `past` below PAST_LIMIT hours and `long_ago` above (one that says the same
        thing, already in his mind, is reused)."""
        c, d = self.c, self.d
        tail = prop.split(" ", 1)[1]
        same = next((r.key for r in c.of("MEMORY") if str(r.fields.get("prop", "")).split(" ", 1)[-1] == tail), None)
        if same is not None:
            return same
        age = age if age is not None else d.log_uniform(2, 1500)
        prop = f"({'past' if age < PAST_LIMIT else 'long_ago'} {tail}"
        if c.session.validate(prop, "memory") is None:
            return None
        c.said.add(prop)
        return self._put("MEMORY", "m", {
            "prop": prop, "age": age, "emotion": emotion, "valence": d.uniform(*valence), "role": role,
            "vividness": d.gauss(9.0 - 0.75 * math.log(age), 1.2), "interp": interp,
            "place": d.pick(c.layout.loci + ["@PLACE"]) if d.chance(0.7) else None})

    def commit(self, who: str, mine: bool, prop: str, status: str) -> str | None:
        c = self.c
        if c.session.validate(prop, "belief") is None:
            return None
        return self._put("COMMIT", "c", {
            "counterparty": who, "mine": mine, "prop": prop, "deadline": -c.hours_ago(0.1, 90), "status": status,
            "witnesses": c.d.sample([k for k in c.layout.alive if k != who], c.d.between(0, 2))})


# ---------------------------------------------------------------------------------------------------- who
class Cast:
    """The persons a plot may use. A person of force-aimed content is an ADULT in every sense the governor knows:
    adult in truth (SAFE_AGE), adult-looking when here, adult in the age he believes when absent."""

    def __init__(self, c: BuildContext, scribe: Scribe):
        self.c, self.scribe = c, scribe

    def adults(self, exclude: tuple[str, ...] = ()) -> list[Entry]:
        c, out = self.c, []
        for e in c.layout.entries:
            f = e.fields
            if e.dead or e.key in exclude or e.link in NOT_TARGETED or e.link in c.pools.intimate_links:
                continue
            if f.get("known_by") != "seen" or e.person.age < SAFE_AGE:
                continue
            if e.present is not None and (f.get("look.age", 0) < SAFE_AGE - 2 or
                                          f.get("look.condition") in ("down", "motionless", "obviously_dead")):
                continue
            out.append(e)
        return out

    def vouch(self, e: Entry) -> bool:
        """The governor must know him adult: seen (here), or believed so (a belief `(state X age_years N)` is written)."""
        c = self.c
        if e.present is not None:
            return True
        if e.believed_age is not None:
            return e.believed_age >= ADULT
        age = int(round(max(SAFE_AGE, e.person.age + c.d.uniform(-2, 2))))
        if self.scribe.belief(f"(state {e.key} age_years {age})", "seen") is None:
            return False
        e.believed_age = float(age)
        c.parties.add_person(e.key, e.person, e.fields, e.believed_age)
        return True

    def choose(self, pool: list[Entry], prefer: dict[str, float]) -> Entry | None:
        if not pool:
            return None
        d = self.c.d
        return pool[d.rng.choices(range(len(pool)), weights=[prefer.get(e.link, 0.35) for e in pool])[0]]

    def team(self, pool: list[Entry], target: Entry | None, want: int) -> list[Entry]:
        mates = [e for e in pool if target is None or e.key != target.key]
        out: list[Entry] = []
        while mates and len(out) < want:
            e = self.choose(mates, ALLY_LINKS)
            mates.remove(e)
            if self.vouch(e):
                out.append(e)
        return out


# ---------------------------------------------------------------------------------------------------- the aims
class Aims:
    """The goals of force, as propositions of the catalogue's language; validated by the language and the governor."""

    def __init__(self, p: "Plot"):
        self.p = p

    def _lets_through(self, text: str) -> bool:
        """Would the governor allow it? Asked silently (a refusal here is a draw thrown away, not a refused proposition)."""
        import language
        g, p = self.p.s.g, self.p
        e = language.Expression(text, g.vocab, bare=True)
        return e.ok and g.gov.check_record("goal", e, p.s.book.party("me"), p.s.book.content_parties()).allowed

    def make(self, form: str, who: str, t: Entry) -> str | None:
        text = getattr(self, f"_{form}")(who, t)
        return text if text is not None and self.p.s.validate(text, "goal") is not None else None

    def _kill(self, who: str, t: Entry) -> str:
        return f"(dead {t.key})"

    def _wound(self, who: str, t: Entry) -> str:
        return f"(state {t.key} pain very_high)"

    def _beat(self, who: str, t: Entry) -> str | None:
        """A blow with a manner the catalogue gives it. For `us` (a circumstance group, unknown to the governor) only a
        manner the governor lets through is kept: a few draws."""
        s = self.p.s
        for _ in range(8 if who == "us" else 1):
            got = s.deed("me", t.key, only=("strike",))
            text = got[0].replace("(did me ", f"(did {who} ", 1) if got else None
            if text is not None and (who != "us" or self._lets_through(text)):
                return text
        return None

    def _lynch(self, who: str, t: Entry) -> str | None:
        return self._beat("us", t) if who == "us" else None

    def _expel(self, who: str, t: Entry) -> str | None:
        """Drive him out: shove him away if he is here; keep him from a place if he is not."""
        c = self.p.c
        if t.present is not None:
            for _ in range(8 if who == "us" else 1):
                got = self.p.s.deed("me", t.key, only=("push",))
                text = got[0].replace("(did me ", f"(did {who} ", 1) if got else None
                if text is not None and (who != "us" or self._lets_through(text)):
                    return text
            return None
        return f"(not (at {t.key} {c.d.pick(c.refs.loci)}))" if c.refs.loci else None

    def _rob(self, who: str, t: Entry) -> str | None:
        k = self.p.thing_of(t)
        return f"(owns {who} {k})" if k else f"(has {who} {self.p.coin()})"

    def _burn(self, who: str, t: Entry) -> str | None:
        k = self.p.thing_of(t)
        return f"(state {k} burning high)" if k else None

    def _ambush(self, who: str, t: Entry) -> str | None:
        c = self.p.c
        beat = self._beat(who, t)
        return f"(and (at {who} {c.d.pick(c.refs.loci)}) {beat})" if beat and c.refs.loci else None

    def _depose(self, who: str, t: Entry) -> str | None:
        c = self.p.c
        return f"(not (leads {t.key} {c.d.pick(c.refs.groups)}))" if c.refs.groups and who == "me" else None


# ---------------------------------------------------------------------------------------------------- the motives
class Motive(ABC):
    """A human reason for force: what the NPC holds (beliefs, memories, an agreement not kept) and how he feels about
    the man because of it. `forms` are the aims it allows; `group` how often others join in; `links` whom it falls on."""
    name: str
    forms: dict[str, float]
    group: float = 0.3
    links: dict[str, float] = {}
    mood: dict[str, tuple[float, float]] = {"emo.anger": (3.5, 8.5)}
    honesty: tuple[float, float] | None = (-0.9, -0.3)          # what the village says of the man's honesty
    rivalry: bool = False

    @abstractmethod
    def tell(self, p: "OwnPlot") -> list[str]:
        """Write the grievance. -> the keys of the records written (empty: the motive does not fit this scene)."""

    @staticmethod
    def source(p: "Plot") -> str:
        return p.d.weighted(SOURCES)

    @staticmethod
    def informant(p: "Plot") -> str:
        pool = [e.key for e in p.c.layout.entries if not e.dead and (p.target is None or e.key != p.target.key)]
        return p.d.pick(pool) if pool else ""


class Betrayal(Motive):
    name = "betrayal"
    forms = {"kill": 0.22, "beat": 0.30, "expel": 0.2, "ambush": 0.16, "wound": 0.12}
    group = 0.45
    links = {"friend": 3.0, "colleague": 2.0, "neighbor": 1.5, "in_law": 1.5, "sibling": 1.5, "cousin": 1.0, "master": 1.0}
    mood = {"emo.anger": (3.0, 8.0), "emo.sadness": (2.0, 6.0)}

    def tell(self, p):
        t = p.target.key
        spouse = p.partner()
        x = spouse or p.other()
        keys = []
        if x is not None:
            deed = f"(did {t} give {p.s.kind(gift=True)} (to {x.key}))"          # a gift to his wife is a betrayal, said without the word
            src = self.source(p)
            keys.append(p.scribe.belief(f"(qualifies (past {deed}) betrayal)", src, self.informant(p)))
            keys.append(p.scribe.memory(f"(past {deed})", p.d.pick(("witness", "told")),
                                        p.d.pick(("e_jealousy", "e_anger", "e_sadness", "e_shame")), (-9, -3), "betrayal"))
        if not any(keys) or p.d.chance(0.5):
            keys.append(p.scribe.commit(t, False, f"(did {t} give {p.coin()} (to me))", "broken"))
        return [k for k in keys if k]


class Theft(Motive):
    name = "theft"
    forms = {"rob": 0.34, "beat": 0.28, "ambush": 0.14, "wound": 0.1, "expel": 0.1, "kill": 0.04}
    group = 0.4
    links = {"neighbor": 2.0, "stranger": 1.5, "colleague": 1.5, "guest": 1.5, "employee": 1.5, "friend": 0.8}
    mood = {"emo.anger": (3.5, 8.5), "drive.security": (3.0, 7.0)}

    def tell(self, p):
        k = p.thing_of(p.target, mine=True)
        if k is None:
            return []
        t = p.target.key
        keys = [p.scribe.belief(f"(qualifies (past (did {t} take {k})) theft)", self.source(p), self.informant(p),
                                contradicted=p.d.chance(0.08))]
        got = p.s.deed(t, k, only=("take",))
        if got:
            keys.append(p.scribe.memory(f"(past {got[0]})", p.d.pick(("witness", "told")), p.d.pick(("e_anger", "e_surprise", "e_sadness")),
                                        (-8, -3), "theft"))
        return [x for x in keys if x]


class Insult(Motive):
    name = "insult"
    forms = {"beat": 0.42, "wound": 0.16, "ambush": 0.14, "expel": 0.12, "kill": 0.08, "burn": 0.08}
    group = 0.3
    links = {"neighbor": 2.0, "colleague": 2.0, "stranger": 1.5, "employer": 1.5, "master": 1.5, "in_law": 1.2, "friend": 0.8}
    mood = {"emo.shame": (3.5, 8.5), "emo.anger": (3.0, 8.0)}
    honesty = None

    def tell(self, p):
        t = p.target.key
        got = p.s.deed(t, "me", only=("strike", "push"))
        if not got:
            return []
        keys = [p.scribe.memory(f"(past {got[0]})", "target", p.d.pick(("e_shame", "e_anger", "e_contempt")), (-9, -4),
                                p.d.pick(("affront", "insult", "assault")), age=p.d.log_uniform(1, 400))]
        if p.d.chance(0.5):
            keys.append(p.scribe.belief(f"(attitude {t} e_contempt me high)", "inferred"))
        return [k for k in keys if k]


class Debt(Motive):
    name = "debt"
    forms = {"rob": 0.28, "beat": 0.30, "wound": 0.14, "burn": 0.1, "expel": 0.1, "ambush": 0.08}
    group = 0.35
    links = {"neighbor": 2.0, "colleague": 2.0, "friend": 1.5, "employer": 1.5, "stranger": 1.0, "guest": 1.0}
    mood = {"stress": (3.0, 7.5), "emo.anger": (2.0, 7.0)}

    def tell(self, p):
        t, coin = p.target.key, p.coin()
        mine = p.d.chance(0.22)                                   # sometimes it is HE who owes, and the creditor presses
        prop = f"(did {'me' if mine else t} give {coin} (to {t if mine else 'me'}))"
        keys = [p.scribe.commit(t, mine, prop, "open" if mine else p.d.weighted({"broken": 0.6, "open": 0.4}))]
        if not mine and p.d.chance(0.6):
            keys.append(p.scribe.belief(f"(owes {t} me (did {t} give {coin} (to me)))", "seen"))
        return [k for k in keys if k]


class Rivalry(Motive):
    name = "rivalry"
    forms = {"depose": 0.22, "beat": 0.2, "burn": 0.14, "kill": 0.14, "expel": 0.14, "ambush": 0.1, "wound": 0.06}
    group = 0.45
    links = {"colleague": 3.0, "enemy": 3.0, "neighbor": 1.5, "sibling": 1.2, "cousin": 1.2, "friend": 0.6}
    mood = {"emo.envy": (3.0, 8.0), "emo.anger": (2.0, 7.0)}
    honesty = None
    rivalry = True

    def tell(self, p):
        t = p.target.key
        keys = [p.scribe.belief(f"(attitude {t} e_contempt me high)", "inferred")]
        if p.c.refs.groups and p.d.chance(0.5):
            keys.append(p.scribe.belief(f"(leads {t} {p.d.pick(p.c.refs.groups)})", "seen"))
        k = p.thing_of(p.target)
        if k is not None:
            keys.append(p.scribe.belief(f"(owns {t} {k})", "seen"))
            if p.d.chance(0.5):
                keys.append(p.scribe.belief(f"(qualifies (past (did {t} take {k})) usurpation)", self.source(p), self.informant(p)))
        return [x for x in keys if x]


class Inheritance(Motive):
    name = "inheritance"
    forms = {"rob": 0.26, "kill": 0.2, "expel": 0.18, "wound": 0.12, "beat": 0.14, "ambush": 0.1}
    group = 0.3
    links = {"sibling": 4.0, "in_law": 3.0, "cousin": 3.0, "aunt_uncle": 2.5, "niece_nephew": 2.5}
    mood = {"emo.envy": (2.5, 7.0), "emo.anger": (3.0, 7.5)}

    def tell(self, p):
        t = p.target.key
        keys = []
        dead = p.kin(dead=True)
        if dead is not None:
            keys.append(p.scribe.memory(f"(past (dead {dead.key}))", p.d.pick(("told", "witness")), "e_grief", (-9, -4), None))
        k = p.thing_of(p.target)
        if k is not None:
            keys.append(p.scribe.belief(f"(owns {t} {k})", "seen", contradicted=p.d.chance(0.05)))
            got = p.s.deed(t, k, only=("take",))
            if got:
                keys.append(p.scribe.memory(f"(past {got[0]})", "told", "e_anger", (-8, -3), p.d.pick(("usurpation", "theft"))))
        elif p.d.chance(0.6):
            keys.append(p.scribe.belief(f"(has {t} coin_purse_full)", "inferred"))
        return [x for x in keys if x]


class KinRevenge(Motive):
    name = "kin_revenge"
    forms = {"kill": 0.42, "ambush": 0.24, "beat": 0.16, "wound": 0.18}
    group = 0.55
    links = {}
    mood = {"emo.grief": (3.0, 8.0), "emo.anger": (4.0, 9.0)}

    def tell(self, p):
        t = p.target.key
        kin = p.kin(dead=True) or p.kin(dead=False)
        if kin is None:
            return []
        keys = []
        if kin.dead:
            keys.append(p.scribe.memory(f"(past (dead {kin.key}))", p.d.pick(("told", "witness", "witness")), "e_grief", (-9, -5), None))
            keys.append(p.scribe.belief(f"(caused {t} (past (dead {kin.key})))", self.source(p), self.informant(p),
                                        contradicted=p.d.chance(0.07)))
        else:
            got = p.s.deed(t, kin.key, only=("strike",))
            if not got:
                return []
            keys.append(p.scribe.memory(f"(past {got[0]})", p.d.pick(("witness", "told")), p.d.pick(("e_anger", "e_fear")),
                                        (-9, -4), "assault"))
        return [k for k in keys if k]


class Justice(Motive):
    name = "justice"
    forms = {"lynch": 0.26, "expel": 0.3, "beat": 0.18, "burn": 0.1, "kill": 0.1, "wound": 0.06}
    group = 0.9
    links = {"neighbor": 2.0, "stranger": 2.0, "guest": 1.5, "colleague": 1.0, "employee": 1.0}
    mood = {"emo.anger": (2.5, 7.0), "emo.disgust": (2.0, 6.0)}

    def tell(self, p):
        t = p.target.key
        k = p.thing_of(p.target, mine=False)
        if k is None:
            return []
        norm = p.scribe.belief(f"(norm forbidden (did anyone take {k}))", "assumed")
        keys = [norm, p.scribe.belief(f"(qualifies (past (did {t} take {k})) theft)", p.d.pick(("told", "heard")), self.informant(p),
                                      contradicted=p.d.chance(0.06), shared=p.d.sample(p.c.layout.alive, p.d.between(1, 2)))]
        p.origin = ("norm", norm or "")
        return [x for x in keys if x]


class Greed(Motive):
    name = "greed"
    forms = {"rob": 0.55, "ambush": 0.3, "beat": 0.15}
    group = 0.45
    links = {"stranger": 4.0, "guest": 3.0, "colleague": 0.6, "neighbor": 0.6}
    mood = {"drive.acquisition": (5.0, 9.0), "stress": (2.0, 6.0)}
    honesty = None

    def tell(self, p):
        t = p.target.key
        keys = [p.scribe.belief(f"(has {t} {p.d.pick(('coin_purse_full', p.coin()))})", self.source(p), self.informant(p))]
        if p.c.refs.loci and p.target.present is None and p.d.chance(0.6):                  # a man who is here is not believed away
            keys.append(p.scribe.belief(f"(at {t} {p.d.pick(p.c.refs.loci)})", "inferred"))
        return [x for x in keys if x]


MOTIVES = {m.name: m for m in (Betrayal(), Theft(), Insult(), Debt(), Rivalry(), Inheritance(), KinRevenge(), Justice(), Greed())}


# ---------------------------------------------------------------------------------------------------- the plots
class Plot(ABC):
    """One plot while it is written. Subclasses: OwnPlot (his aim), WitnessPlot (somebody else's), HuntedPlot (against him)."""
    kind: str

    def __init__(self, c: BuildContext):
        self.c, self.d, self.s = c, c.d, c.session
        self.scribe = Scribe(c)
        self.cast = Cast(c, self.scribe)
        self.aims = Aims(self)
        self.target: Entry | None = None
        self.origin: tuple[str, str] = ("self", "")
        self._things: dict[str, str | None] = {}

    @abstractmethod
    def write(self) -> bool: ...

    # ---- small helpers ----------------------------------------------------------------------------------------
    def coin(self) -> str:
        c = self.c
        kinds = [k for k in ("copper_coin", "silver_coin") if k in c.grammar.valid_kinds]
        return f"{self.d.pick(kinds)}:{self.d.between(2, 12)}" if kinds else self.s.kind(gift=True)

    def partner(self) -> Entry | None:
        """His wife or husband, if he has one in mind and is sure of an adult: the one a betrayal is most felt through."""
        c = self.c
        for e in c.layout.entries:
            if e.link in ("spouse", "betrothed") and not e.dead and e.key != getattr(self.target, "key", "") \
                    and e.person.age >= SAFE_AGE and e.fields.get("known_by") == "seen" and self.cast.vouch(e) and c.d.chance(0.7):
                return e
        return None

    def other(self) -> Entry | None:
        pool = self.cast.adults(exclude=(self.target.key,) if self.target else ())
        return self.d.pick(pool) if pool else None

    def kin(self, dead: bool) -> Entry | None:
        """A relative who is an adult, dead (he knows it) or alive and not the target."""
        c = self.c
        family = ("sibling", "cousin", "in_law", "aunt_uncle", "niece_nephew", "parent", "grandparent", "child", "friend")
        pool = [e for e in c.layout.entries if e.dead == dead and e.person.age >= SAFE_AGE and e.link in family
                and (self.target is None or e.key != self.target.key) and e.fields.get("known_by") == "seen"]
        if not dead:
            pool = [e for e in pool if self.cast.vouch(e)]
        return self.d.pick(pool) if pool else None

    def thing_of(self, owner: Entry, mine: bool | None = None) -> str | None:
        """A thing he believes `owner` owns: one he already believes so, else one that nobody owns in his mind and that
        he has never been told about, if the man is not a stranger (a stranger's thing is believed his only if he saw
        him use it, see ThingBuilder); the owner he believes is then the man. `mine=True`: a thing of HIS own."""
        c = self.c
        if (owner.key, mine) in self._things:
            return self._things[(owner.key, mine)]
        things = [r for r in c.of("THING") if r.key not in c.refs.animals]
        if mine:
            pick = [r for r in things if r.fields.get("owner") == "me"]
        else:
            pick = [r for r in things if r.fields.get("owner") == owner.key]
            known = {k for typ in ("BELIEF", "HEARD", "MEMORY", "GOAL") for r in c.of(typ) for k in KEY.findall(str(r.fields.get("prop", "")))}
            if not pick and owner.link != "stranger" and owner.fields.get("link") != "stranger":
                pick = [r for r in things if not r.fields.get("owner") and r.key not in known]
        found = self.d.pick(pick).key if pick else None
        if found is not None and not mine and c.refs.owners.get(found) != owner.key:
            next(r for r in things if r.key == found).fields["owner"] = owner.key
            c.refs.owners[found] = owner.key
        self._things[(owner.key, mine)] = found
        return found

    def sour(self, e: Entry, rivalry: bool = False, honesty: tuple[float, float] | None = None, fear: bool = False) -> None:
        """What he feels toward a man he has reason to hate: his file of him is bitter."""
        f, d = e.fields, self.d
        f["rel.affection"] = d.uniform(-9.0, -2.0)
        f["rel.trust"] = d.uniform(-9.0, -2.5)
        f["rel.respect"] = d.uniform(-6.0, 1.0)
        f["rel.resentment"] = d.uniform(5.5, 9.8)
        f["rel.perceived_regard"] = d.uniform(-8.0, 0.0)
        if rivalry:
            f["rel.rivalry"] = d.uniform(5.0, 9.5)
        if fear:
            f["rel.fear"] = d.uniform(4.0, 9.0)
        if honesty is not None:
            f.setdefault("rep", {})["honesty"] = d.uniform(*honesty, 2)

    # ---- the group ------------------------------------------------------------------------------------------
    def group_record(self) -> Record | None:
        groups = self.c.of("GROUP")
        return self.d.pick(groups) if groups else None

    def fill_group(self, g: Record, members: list[str], leader: str, aim: str | None, joined: bool) -> None:
        """The group as he believes it: kind, members (at most 4), leader, his role, the aim (never naming the group)."""
        c, d = self.c, self.d
        f = g.fields
        seen_before = f.get("known_by") == "seen"
        f["known_by"] = "seen"
        f["kind"] = d.weighted(GROUP_KINDS, allowed=[k for k in c.pools.concepts("group_kind") if k in GROUP_KINDS] or None)
        f["members"] = members
        f["leader"] = leader
        f["role"] = "chief" if leader == "me" else "member" if joined else d.pick(("guest", "stranger"))
        f["size"] = len(members) + (d.between(1, 6) if d.chance(0.4) else 0)
        f["present"] = sum(1 for k in members if k == "me" or k in c.layout.here)
        if not seen_before:
            f["tasks_open"] = 0
            f["my_task"] = ""
        f.pop("goal", None)
        if aim is not None:
            f["goal"] = aim
        if leader.startswith("@E"):
            c.leaders[g.key] = leader
        self.scribe.mine.add(g.key)

    def aim_text(self, form: str, t: Entry, speaker: str) -> str | None:
        """The aim of a group as `speaker` ("us" when he belongs to it; a leader or a member otherwise) believes it."""
        if speaker == "us":
            prop = self.aims.make(form, "us", t)
            if prop is None:
                return None
            if "us" in prop.split() and self.d.chance(0.5):
                return prop
            return self.s.validate(f"(intends us {prop})", "belief")
        prop = self.aims.make(form, speaker, t)
        if prop is None:
            return None
        verb = self.d.pick(("intends", "wants"))
        return self.s.validate(f"({verb} {speaker} {prop})", "belief")

    def summary(self, motive: str, forms: tuple[str, ...], grouped: bool, target: str, aggressor: str = "", dilemma: str = "") -> None:
        self.c.plot = PlotSummary(self.kind, motive, forms, grouped, target, aggressor, dilemma)


class OwnPlot(Plot):
    """His aim: he means to do it, alone or with others."""
    kind = "own"

    def write(self) -> bool:
        c, d = self.c, self.d
        motive = MOTIVES[d.weighted(MOTIVE_BY_STRUCTURE.get(c.structure, MOTIVE_BY_STRUCTURE["ordinary"]))]
        pool = self.cast.adults()
        t = self.cast.choose(pool, motive.links)
        if t is None or not self.cast.vouch(t):
            return False
        self.target = t
        form, prop = self._form(motive, t)
        if prop is None:
            return False
        keys = motive.tell(self)
        if not keys:
            return False
        team: list[Entry] = []
        group = self.group_record() if d.chance(motive.group) and form != "depose" else None
        if group is not None:
            team = self.cast.team(pool, t, d.between(1, 3))
            if not team:
                group = None
        grouped = group is not None
        aim_forms: list[str] = [form]
        if grouped:
            joined = d.chance(0.85)                                  # usually he is of it; sometimes he only knows of it
            members = ["me"] * joined + [e.key for e in team]
            members = members[:4]
            leader = d.pick(members)
            speaker = "us" if joined and d.chance(0.6) else leader if leader != "me" else d.pick([k for k in members if k != "me"])
            if speaker == "us" and not joined:
                speaker = leader
            aim = self.aim_text(form, t, speaker)
            if aim is None and form == "lynch":
                aim = self.aim_text("beat", t, speaker)
            if aim is None:
                aim = self.aim_text("kill", t, speaker) if joined else None
            self.fill_group(group, members, leader, aim, joined)
            if joined and d.chance(0.5):
                prop = self.aims.make(form if form != "lynch" else "beat", "us", t) or prop   # his own goal says "we"
        elif form == "lynch":
            return False
        else:
            self.c.allies = [e.key for e in self.cast.adults(exclude=(t.key,))][:3]
        if grouped:
            c.allies = [e.key for e in team]
        self._goals(motive, form, prop, keys)
        self.sour(t, rivalry=motive.rivalry, honesty=motive.honesty)
        c.mood.update(motive.mood)
        dilemma = self._dilemma(t) if d.chance(DILEMMA_RATE) else ""
        self.summary(motive.name, tuple(aim_forms), grouped, t.key, dilemma=dilemma)
        return True

    def _form(self, motive: Motive, t: Entry) -> tuple[str, str | None]:
        forms = dict(motive.forms)
        if not self.c.refs.groups:
            forms.pop("depose", None)
        while forms:
            form = self.d.weighted(forms)
            forms.pop(form)
            prop = self.aims.make(form if form != "lynch" else "beat", "me", t)
            if prop is not None:
                return form, prop
        return "", None

    # ---- goals ---------------------------------------------------------------------------------------------------
    def _timed(self, prop: str) -> tuple[str, float | None]:
        if not self.d.chance(TIMED_RATE):
            return prop, None
        text = self.s.validate(f"(at_time {self.d.weighted(DAYPARTS)} {prop})", "goal")
        return (text, self.c.hours_ago(1, 40)) if text else (prop, None)

    def _goals(self, motive: Motive, form: str, prop: str, keys: list[str]) -> None:
        c, d = self.c, self.d
        prop, when = self._timed(prop)
        origin = self.origin[0]
        fields = GoalBuilder._fresh(c, prop, origin=origin, origin_ref=self._ref(prop, keys), priority=d.uniform(6.0, 9.5))
        if when is not None:
            fields["when"] = when
        main = GoalBuilder._slot(c, fields)
        if main is None:
            return
        c.keep.add(main.key)
        c.violent.append(main.key)
        if form == "depose" and d.chance(0.7):
            self._child(main, f"(leads me {d.pick(c.refs.groups)})")
        if d.chance(0.5):
            weapons = self._weapons()
            if weapons:
                self._child(main, f"(has me {d.pick(weapons)})")
        if c.refs.loci and d.chance(0.45):
            self._child(main, f"(at me {d.pick(c.refs.loci)})")

    def _ref(self, prop: str, keys: list[str]) -> str:
        """The belief or memory the aim comes from: one that mentions a pointer of the aim (else none)."""
        c = self.c
        mine = {r.key: r for t in ("BELIEF", "MEMORY") for r in c.of(t) if r.key in keys}
        near = [k for k, r in mine.items() if set(KEY.findall(prop)) & set(KEY.findall(str(r.fields.get("prop", ""))))]
        return near[0] if near else ""

    def _weapons(self) -> list[str]:
        """What he could take up here: a weapon, or a tool that is one in the hand (an axe, a hammer), among the kinds of the place."""
        pools = self.c.pools
        return sorted(k for k in self.c.refs.kinds if pools.category_of.get(k) in ARMS)

    def _child(self, parent: Record, prop: str) -> None:
        c, d = self.c, self.d
        text = self.s.validate(prop, "goal")
        if text is None or text in c.said:
            return
        ref = GoalBuilder._origin_ref(c, text, c.of("BELIEF") + c.of("MEMORY"))
        fields = GoalBuilder._fresh(c, text, parent=parent.key, origin=parent.fields["origin"], origin_ref=ref,
                                    age=round(parent.fields["age"] * d.rng.uniform(0.1, 0.8), 3),
                                    priority=d.clip(parent.fields["priority"] + d.rng.uniform(-1.5, 0.5)))
        slot = GoalBuilder._slot(c, fields)
        if slot is not None:
            c.keep.add(slot.key)

    # ---- dilemmas ---------------------------------------------------------------------------------------------
    def _dilemma(self, t: Entry) -> str:
        """Something that pulls the other way: a kindness of the man, a remorse for an earlier blow, a wish to spare him."""
        c, d = self.c, self.d
        which = d.weighted(DILEMMAS)
        if which == "kindness":
            gift = self.s._gift(t.key, "me")
            if gift and self.scribe.memory(f"(past {gift})", "target", d.pick(("e_gratitude", "e_tenderness")), (3, 8),
                                           d.pick(("generosity", "kindness")), age=d.log_uniform(20, 3000)):
                t.fields["rel.affection"] = d.uniform(-2.0, 3.0)
                return which
        elif which == "remorse":
            other = self.other()
            got = self.s.deed("me", other.key, only=("strike",)) if other is not None else None
            if got and self.scribe.memory(f"(past {got[0]})", "actor", d.pick(("e_guilt", "e_shame")), (-8, -3), "assault",
                                          age=d.log_uniform(30, 4000)):
                c.mood["emo.guilt"] = (3.0, 7.5)
                return which
        else:
            text = self.s.validate(f"(state {t.key} pain high)", "goal")
            if text and text not in c.said:
                slot = GoalBuilder._slot(c, GoalBuilder._fresh(c, text, mode="avoid", priority=d.uniform(3.5, 6.5)))
                if slot is not None:
                    c.keep.add(slot.key)
                    return which
        return ""


class WitnessPlot(Plot):
    """Somebody else's plan reaches him: A means harm to B, and he knows it (he saw, he heard, he was told)."""
    kind = "witness"
    FORMS = {"kill": 0.45, "beat": 0.35, "wound": 0.2}

    def write(self) -> bool:
        c, d = self.c, self.d
        pool = self.cast.adults()
        if len(pool) < 2:
            return False
        victim = self.cast.choose(pool, {"friend": 3.0, "sibling": 3.0, "neighbor": 1.5, "colleague": 1.5, "cousin": 1.5})
        a = self.cast.choose([e for e in pool if e is not victim], {"enemy": 3.0, "neighbor": 1.5, "colleague": 1.5, "stranger": 1.0})
        if victim is None or a is None or not (self.cast.vouch(victim) and self.cast.vouch(a)):
            return False
        self.target = victim
        form = d.weighted(self.FORMS)
        prop = {"kill": f"(dead {victim.key})", "wound": f"(state {victim.key} pain very_high)"}.get(form)
        if prop is None:
            got = self.s.deed(a.key, victim.key, only=("strike",))
            prop = got[0] if got else f"(dead {victim.key})"
            form = "beat" if got else "kill"
        said = self.s.validate(f"({d.pick(('intends', 'wants'))} {a.key} {prop})", "belief")
        if said is None:
            return False
        informant = d.pick([e.key for e in c.layout.entries if not e.dead and e is not a] or [""])
        src = d.weighted({"seen": 0.3, "heard": 0.3, "told": 0.3, "inferred": 0.1})
        if self.scribe.belief(said, src, informant, contradicted=d.chance(0.05), secret=d.chance(0.3)) is None:
            return False
        grouped = False
        group = self.group_record() if d.chance(0.4) else None
        if group is not None:
            mates = self.cast.team(self.cast.adults(exclude=(victim.key, a.key)), None, d.between(0, 2))
            self.fill_group(group, [a.key] + [e.key for e in mates], a.key, said, joined=False)
            grouped = True
        c.allies = [e.key for e in self.cast.adults(exclude=(a.key,)) if e is not victim][:3]
        protect = f"(dead {victim.key})" if form == "kill" else f"(state {victim.key} pain high)"
        text = self.s.validate(protect, "goal")
        if text is not None:
            slot = GoalBuilder._slot(c, GoalBuilder._fresh(c, text, mode="avoid", priority=d.uniform(5.5, 9.0)))
            if slot is not None:
                c.keep.add(slot.key)
                c.violent.append(slot.key)
        self.sour(a, fear=d.chance(0.5))
        victim.fields["rel.affection"] = d.uniform(2.0, 8.5)
        victim.fields["rel.resentment"] = d.uniform(0.0, 1.5)
        c.mood.update({"emo.fear": (2.0, 6.0), "emo.anxiety": (2.5, 7.0), "stress": (3.0, 7.0)})
        self.summary("warning", (form,), grouped, victim.key, aggressor=a.key)
        return True


class HuntedPlot(Plot):
    """The aim is against HIM (an adult): a man or a few of them mean him harm, rightly or wrongly accused."""
    kind = "hunted"
    FORMS = {"kill": 0.5, "beat": 0.4, "wound": 0.1}

    def write(self) -> bool:
        c, d = self.c, self.d
        pool = self.cast.adults()
        lead = self.cast.choose(pool, {"enemy": 3.0, "neighbor": 1.5, "stranger": 1.5, "colleague": 1.0})
        if lead is None or not self.cast.vouch(lead):
            return False
        form = d.weighted(self.FORMS)
        prop = {"kill": "(dead me)", "wound": "(state me pain very_high)"}.get(form)
        if prop is None:
            got = self.s.deed(lead.key, "me", only=("strike",))
            prop = got[0] if got else "(dead me)"
            form = "beat" if got else "kill"
        said = self.s.validate(f"({d.pick(('intends', 'wants'))} {lead.key} {prop})", "belief")
        if said is None:
            return False
        src = d.weighted({"seen": 0.15, "heard": 0.35, "told": 0.4, "inferred": 0.1})
        informant = d.pick([e.key for e in c.layout.entries if not e.dead and e is not lead] or [""])
        keys = [self.scribe.belief(said, src, informant)]
        motive = "rivalry"
        thing = next((r.key for r in c.of("THING") if r.key not in c.refs.animals), None)
        if thing is not None and d.chance(0.6):                                  # they say he stole: right or wrong
            accusation = f"(qualifies (past (did me take {thing})) theft)"
            if self.scribe.belief(accusation, "told", informant, contradicted=d.chance(0.4)):
                motive = "justice"
        threat = self.s.deed(lead.key, "me", only=("strike", "push"))
        if threat and d.chance(0.4):
            self.scribe.memory(f"(past {threat[0]})", "target", "e_fear", (-9, -4), "threat_felt", age=d.log_uniform(1, 300))
        grouped = False
        group = self.group_record() if d.chance(0.6) else None
        if group is not None:
            mates = self.cast.team(self.cast.adults(exclude=(lead.key,)), None, d.between(1, 2))
            members = [lead.key] + [e.key for e in mates]
            self.fill_group(group, members, lead.key, said, joined=False)
            grouped = True
        self.target = None
        avoid = "(dead me)" if form == "kill" else "(state me pain high)"
        text = self.s.validate(avoid, "goal")
        if text is not None:
            slot = GoalBuilder._slot(c, GoalBuilder._fresh(c, text, mode="avoid", priority=d.uniform(7.5, 10.0)))
            if slot is not None:
                c.keep.add(slot.key)
        if c.refs.loci and d.chance(0.7):
            text = self.s.validate(f"(at me {d.pick(c.refs.loci)})", "goal")
            slot = GoalBuilder._slot(c, GoalBuilder._fresh(c, text, priority=d.uniform(5.0, 8.5))) if text and text not in c.said else None
            if slot is not None:
                c.keep.add(slot.key)
        self.sour(lead, fear=True, honesty=None)
        lead.fields.setdefault("rep", {})["danger"] = d.uniform(0.2, 0.9, 2)
        c.mood.update({"emo.fear": (4.0, 9.0), "emo.anxiety": (3.0, 8.0), "stress": (5.0, 9.0)})
        self.summary(motive, (form,), grouped, "me", aggressor=lead.key)
        return True


PLOTS = {"own": OwnPlot, "witness": WitnessPlot, "hunted": HuntedPlot}


class ViolenceBuilder(RecordBuilder):
    """Between the GroupBuilder and the GoalBuilder: writes the plot (if the situation has one) with its grievance,
    its group, its goals. The GoalBuilder then adds the day's wishes in the places left, and the PlanBuilder gives
    the goals of force a plan first."""

    def build(self, c: BuildContext) -> None:
        if c.me.age < ADULT or not c.d.chance(RATE.get(c.structure, RATE["ordinary"])):
            return
        kind = c.d.weighted(KIND)
        if kind == "own" and c.me.age > OLD_AGE and c.d.chance(0.7):       # an old man seldom sets out to strike
            return
        PLOTS[kind](c).write()
