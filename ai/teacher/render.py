"""render.py - an NPC situation (the records of his mind) -> compact English text for the teacher.

ONLY the mind is rendered (situation.context.records): what the NPC perceives, believes, remembers and wants. The
true scene (situation.scene) is never read here: the teacher must not know more than the NPC (rule "no truth in
tokens"). Every record keeps its key (me, @E1, @T3, b:2, @L1, @PLACE...) so the teacher can answer with it, and every
proposition is shown as its S-expression (the language the teacher answers in) followed by an English gloss.

Only SALIENT traits, values, emotions, drives and body readings are listed; a number not listed is low or neutral.
Fields the sections do not know are still printed (generic formatting), so a new catalogue field never vanishes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from language import EnglishPrinter, LanguageError, Node

from .toolkit import Toolkit


# ----------------------------------------------------------------------------------------------------- units
class Units:
    """Numbers the way a person would say them. Distances in metres, ages in years, delays from hours."""

    HEADINGS = ("ahead", "ahead-right", "right", "behind-right", "behind", "behind-left", "left", "ahead-left")

    @staticmethod
    def num(v) -> str:
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, float):
            return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 10 else f"{v:.1f}".rstrip("0").rstrip(".")
        return str(v)

    @classmethod
    def span(cls, hours: float) -> str:
        """A duration given in hours."""
        s = hours * 3600
        if s < 90:
            return f"{round(s)} s"
        if s < 5400:
            return f"{round(s / 60)} min"
        if hours < 72:
            return f"{round(hours)} h"
        if hours < 24 * 90:
            return f"{round(hours / 24)} d"
        return f"{round(hours / (24 * 30))} months"

    @classmethod
    def ago(cls, hours: float) -> str:
        return f"{cls.span(hours)} ago"

    @staticmethod
    def dist(m: float) -> str:
        return f"{m:.0f} m" if m >= 10 else f"{m:.1f} m"

    @classmethod
    def heading(cls, d: dict) -> str:
        """{sin, cos} of the bearing relative to where the NPC looks (assumed clockwise: sin > 0 is to his right)."""
        a = math.atan2(d.get("sin", 0.0), d.get("cos", 1.0)) % (2 * math.pi)
        return cls.HEADINGS[int((a + math.pi / 8) // (math.pi / 4)) % 8]

    @staticmethod
    def clock(d: dict) -> str:
        a = math.atan2(d.get("sin", 0.0), d.get("cos", 1.0)) % (2 * math.pi)
        minutes = int(round(a / (2 * math.pi) * 24 * 60)) % (24 * 60)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    @staticmethod
    def day_part(clock: str) -> str:
        h = int(clock[:2])
        return ("night" if h < 5 else "dawn" if h < 8 else "morning" if h < 12 else "afternoon" if h < 18
                else "evening" if h < 22 else "night")


# ----------------------------------------------------------------------------------------------------- glosses
class GlossPrinter(EnglishPrinter):
    """EnglishPrinter with sentence templates for the commonest predicates (the base printer stays the fallback)."""

    TEMPLATES = {
        "owns": "{0} owns {1}", "has": "{0} has {1}", "at": "{0} is at {1}", "is_a": "{0} is a {1}",
        "named": "{0} is named {1}", "made": "{0} made {1}", "worth": "{0} is worth {1}", "count": "{0} count {1}",
        "dead": "{0} is dead", "knows_how": "{0} knows how to {1}", "able": "{0} is able to {1}",
        "works_as": "{0} works as {1}", "member": "{0} is a member of {1}", "leads": "{0} leads {1}",
        "holds": "{0} holds the role {1}", "lives_at": "{0} lives at {1}", "exists": "{0} exists at {1}",
        "state": "{0} {1} is {2}", "quality": "{0} is {1} ({2})", "located": "{0} is {1} {2}",
        "attitude": "{0}'s {1} toward {2} is {3}", "link": "{0} is {1} to {2}", "route": "route from {0} to {1}",
        "believes": "{0} believes that ({1})", "wants": "{0} wants ({1})", "intends": "{0} intends ({1})",
        "owes": "{0} owes {1}: ({2})", "may": "{0} may ({1})", "norm": "norm [{0}]: ({1})",
        "custom": "custom of {0}: ({1})", "recipe": "recipe for {0}: ({1})", "caused": "{0} caused {1}",
        "qualifies": "{0} counts as {1}", "party_to": "{0} is party to {1}",
    }
    TAGS = {"past", "now", "future", "habitual", "soon", "long_ago", "today", "tomorrow", "at_festival",
            "before_winter", "each_day", "each_season", "each_year", "seen_myself", "heard_said", "think", "sure", "maybe"}

    def render(self, node) -> str:
        if isinstance(node, Node):
            h, n = node.head, len(node.args)
            if h in self.TAGS and n == 1:
                return f"[{h.replace('_', ' ')}] {self.render(node.args[0])}"
            if h == "did" and n >= 2:
                return self._did(node)
            tpl = self.TEMPLATES.get(h)
            if tpl is not None and tpl.count("{") == n:
                return tpl.format(*[self.render(a) for a in node.args])
        return super().render(node)

    def _did(self, node) -> str:
        agent, gesture, rest = node.args[0], node.args[1], node.args[2:]
        out = [self.render(agent), self.render(gesture)]
        for r in rest:
            if isinstance(r, Node) and r.head == "how" and r.args:
                out.append(f"({self.render(r.args[0])})")
            else:
                out.append(self.render(r))
        return " ".join(out)


class Glosser:
    """'(S-expression) "English gloss"' for a proposition; the bare S-expression when it does not parse."""

    def __init__(self, tk: Toolkit):
        self.tk, self.printer = tk, GlossPrinter()

    def sexp(self, text: str) -> str:
        return " ".join(str(text).split())

    def show(self, text) -> str:
        if text in (None, ""):
            return "(unknown)"
        s = self.sexp(text)
        try:
            gloss = self.printer.render(self.tk.parser.parse(s))
        except LanguageError:
            return s
        return f'{s} "{gloss}"'


# ----------------------------------------------------------------------------------------------------- context
@dataclass
class Field:
    """A scalar field of a record, as shown to the teacher."""
    name: str            # the word shown: a catalogue variable id when the field has one
    value: object
    scale: str


class RenderContext:
    """The records of one situation, indexed, and the helpers every section shares."""

    def __init__(self, tk: Toolkit, records):
        self.tk, self.records = tk, list(records)
        self.by_key = {r.key: r for r in self.records}
        self.by_type: dict[str, list] = {}
        for r in self.records:
            self.by_type.setdefault(r.type, []).append(r)
        self.glosser = Glosser(tk)
        types = tk.interface.token_types
        self.var_of = {(t, f): spec["from"] for t, s in types.items() for f, spec in s["fields"].items() if "from" in spec}
        self.scale_of = {(t, f): spec["scale"] for t, s in types.items() for f, spec in s["fields"].items()}

    def of(self, typ: str) -> list:
        return self.by_type.get(typ, [])

    def one(self, typ: str):
        rs = self.of(typ)
        return rs[0] if rs else None

    def label(self, rec, name: str) -> str:
        """The word to show for a field: the catalogue variable when it has a short one the teacher can write."""
        var = self.var_of.get((rec.type, name))
        return var if var and var in self.tk.spec.writes else name.split(".")[-1]

    def fmt(self, v) -> str:
        """Generic value formatting."""
        if isinstance(v, dict):
            if "sin" in v and "cos" in v and "certainty" not in v:
                return Units.heading(v)
            return ", ".join(f"{k} {self.fmt(x)}" for k, x in v.items())
        if isinstance(v, (list, tuple)):
            return ", ".join(self.fmt(x) for x in v) if v else "none"
        return Units.num(v)

    def leftovers(self, rec, handled: set) -> list[str]:
        out = []
        for k, v in rec.fields.items():
            if k in handled or v in (None, [], {}):
                continue
            out.append(f"{k} {self.fmt(v)}")
        return out


class Salience:
    """What deserves a line: deviations from neutral, so that 200 numbers become a dozen."""

    @staticmethod
    def pick(items: list, minimum: float, bipolar: bool = False, limit: int = 8) -> list:
        sel = [(n, v) for n, v in items if isinstance(v, (int, float)) and not isinstance(v, bool)
               and (abs(v) if bipolar else v) >= minimum]
        sel.sort(key=lambda x: -abs(x[1]))
        return sel[:limit]

    @staticmethod
    def words(sel: list) -> str:
        return ", ".join(f"{n} {Units.num(v)}" for n, v in sel)


# ----------------------------------------------------------------------------------------------------- sections
class Section:
    title = ""

    def lines(self, c: RenderContext) -> list[str]:
        raise NotImplementedError

    def render(self, c: RenderContext) -> str:
        body = self.lines(c)
        return f"== {self.title} ==\n" + "\n".join(body) if body else ""


class WakeSection(Section):
    title = "WHY YOU DECIDE NOW (key: wake)"

    def lines(self, c):
        out = []
        for r in c.of("WAKE"):
            f = r.fields
            bits = [f"{k} {c.fmt(v)}" for k, v in f.items() if v not in (None, [], {})]
            out.append("The engine asks you to decide now: " + ", ".join(bits) + ".")
        return out


class OtherSection(Section):
    """Record types no section knows (a catalogue that grew): printed generically, so nothing is silently lost."""
    title = "OTHER RECORDS"
    KNOWN = {"SELF", "SELF_MIND", "SELF_STATE", "PLACE", "LOCUS", "ENTITY", "GROUP", "THING", "INV", "EVENT", "HEARD",
             "REQUEST", "BELIEF", "MEMORY", "GOAL", "PLAN", "COMMIT", "SKILL", "TASTE", "WAKE"}

    def lines(self, c):
        return [f"{r.key} ({r.type}): " + "; ".join(c.leftovers(r, set())) for r in c.records if r.type not in self.KNOWN]


class SelfSection(Section):
    title = "WHO YOU ARE (key: me)"

    BODY_ALERTS = (("body.pain", 1.5, True), ("body.bleeding", 0.5, True), ("body.sickness", 1.0, True),
                   ("body.intox", 1.0, True), ("body.breath", 7.0, False), ("body.consciousness", 9.5, False),
                   ("body.load", 0.7, True), ("body.mobility", 0.99, False), ("body.manipulation", 0.99, False))

    def lines(self, c):
        me, mind, state = c.one("SELF"), c.one("SELF_MIND"), c.one("SELF_STATE")
        out = []
        if me is not None:
            f = me.fields
            ident = [f.get("sex"), f"{Units.num(f['age'])} years old" if "age" in f else None,
                     f.get("age_stage"), f.get("posture")]
            out.append("You are " + ", ".join(str(x) for x in ident if x) + ".")
            body = []
            for name, lim, high in self.BODY_ALERTS:
                v = f.get(name)
                if isinstance(v, (int, float)) and ((v >= lim) if high else (v < lim)):
                    body.append(f"{c.label(me, name)} {Units.num(v)}")
            for name in ("need.hunger", "need.thirst", "need.sleep", "need.exhaustion", "need.reserves"):
                v = f.get(name)
                if isinstance(v, (int, float)) and v >= 3.5:
                    body.append(f"{c.label(me, name)} {Units.num(v)}")
            v = f.get("need.thermal")
            if isinstance(v, (int, float)) and abs(v) >= 3:
                body.append(f"thermal {'cold' if v < 0 else 'hot'} {Units.num(v)}")
            if body:
                out.append("Body (0-10, high = worse unless said): " + ", ".join(body) + ".")
            else:
                out.append("Body: fine.")
            cap = [f"{n.split('.')[1]} {Units.num(f[n])}" for n in ("body.strength", "body.endurance") if n in f]
            if cap:
                out.append("Physical capacity (0-10): " + ", ".join(cap) + ".")
            if f.get("held"):
                out.append(f"You hold {len(f['held'])} object(s) in hand (also listed in your belongings).")
            out += self._rest(c, me, f, {"sex", "age", "age_stage", "posture", "time", "place", "season", "held"}
                              | {n for n, _, _ in self.BODY_ALERTS} | {k for k in f if k.startswith("need.")}
                              | {"body.strength", "body.endurance"})
        if mind is not None:
            f = mind.fields
            tr = [(c.label(mind, n), v) for n, v in f.items() if n.startswith(("trait.", "temper.baseline"))]
            sel = Salience.pick(tr, 4.0, bipolar=True)
            if sel:
                out.append("Character (-10..10, only strong ones): " + Salience.words(sel) + ".")
            ab = [(c.label(mind, n), v) for n, v in f.items() if n.startswith(("ability.", "temper.resilience"))]
            hi = Salience.pick(ab, 6.5)
            lo = [(n, v) for n, v in ab if isinstance(v, (int, float)) and v <= 1.5]
            if hi or lo:
                out.append("Abilities (0-10): " + Salience.words(hi + lo) + ".")
            va = [(c.label(mind, n), v) for n, v in f.items() if n.startswith("value.")]
            sel = Salience.pick(va, 5.0)
            if sel:
                out.append("What you value (0-10, only strong): " + Salience.words(sel) + ".")
            if f.get("attracted_to"):
                out.append("Attracted to: " + ", ".join(f["attracted_to"]) + ".")
            out += self._rest(c, mind, f, {n for n in f if n.startswith(("trait.", "temper.", "ability.", "value."))}
                              | {"attracted_to"})
        if state is not None:
            f = state.fields
            emo = [(c.label(state, n), v) for n, v in f.items() if n.startswith("emo.")]
            sel = Salience.pick(emo, 2.0)
            out.append("Emotions now (0-10, only felt ones): " + (Salience.words(sel) if sel else "calm") + ".")
            dr = [(c.label(state, n), v) for n, v in f.items() if n.startswith("drive.")]
            sel = Salience.pick(dr, 4.0)
            if sel:
                out.append("Drives (0-10, pressing ones): " + Salience.words(sel) + ".")
            other = [(c.label(state, n), f.get(n)) for n in ("stress", "masking", "self_regard", "mood.valence", "mood.energy")]
            sel = Salience.pick(other, 3.0, bipolar=True)
            if sel:
                out.append("Mood: " + Salience.words(sel) + ".")
            if f.get("attention"):
                out.append(f"Your attention is on {f['attention']}.")
            out += self._rest(c, state, f, {n for n in f if n.startswith(("emo.", "drive.", "mood."))}
                              | {"stress", "masking", "self_regard", "attention"})
        return out

    @staticmethod
    def _rest(c, rec, f, handled):
        left = c.leftovers(rec, handled)
        return [f"{rec.key}: " + "; ".join(left) + "."] if left else []


class WhereWhenSection(Section):
    title = "WHERE AND WHEN (keys: @PLACE, @L...)"

    def lines(self, c):
        me, place = c.one("SELF"), c.one("PLACE")
        out = []
        if me is not None:
            t = me.fields.get("time")
            if isinstance(t, dict):
                clk = Units.clock(t)
                sure = t.get("certainty")
                out.append(f"Season: {me.fields.get('season', 'unknown')}. You feel it is about {clk} ({Units.day_part(clk)})"
                           + (f" (reliability of this feeling {Units.num(sure)} of 1)" if sure is not None else "") + ".")
        if place is not None:
            f = place.fields
            bits = ["indoors" if f.get("indoors") else "outdoors"]
            for k, label in (("crowd", "people around"), ("light", "light (0-10)"), ("noise", "noise (0-10)"),
                             ("air_felt", "air"), ("sun", "sun"), ("weather", "weather"), ("signs", "signs")):
                if f.get(k) not in (None, [], {}):
                    bits.append(f"{label} {c.fmt(f[k])}")
            bits += c.leftovers(place, {"indoors", "crowd", "light", "noise", "air_felt", "sun", "weather", "signs"})
            out.append("@PLACE: " + ", ".join(bits) + ".")
        for r in c.of("LOCUS"):
            f = r.fields
            bits = []
            if "dist" in f:
                bits.append(f"{Units.dist(f['dist'])} {Units.heading(f['dir'])}" if "dir" in f else Units.dist(f["dist"]))
            if f.get("kind"):
                bits.append(str(f["kind"]))
            if f.get("owner"):
                bits.append(f"owner (believed) {f['owner']}")
            bits += c.leftovers(r, {"dist", "dir", "kind", "owner"})
            out.append(f"{r.key}: a place you know, " + ", ".join(bits) + ".")
        return out


class PeopleSection(Section):
    title = "PEOPLE YOU KNOW OR SEE (keys: @E..., groups @G...)"

    REL_MIN = 2.0

    def lines(self, c):
        out = []
        for r in c.of("ENTITY"):
            f = r.fields
            head = [r.key]
            if f.get("name"):
                head.append(f["name"])
            head.append(f.get("link", "unknown") if f.get("link") != "stranger" else "stranger")
            if not f.get("present"):
                head.append("not here (remembered)")
            elif "dist" in f:
                head.append(f"{Units.dist(f['dist'])} {Units.heading(f['dir'])}" if "dir" in f else Units.dist(f["dist"]))
            if f.get("known_by") and f["known_by"] != "seen":
                head.append({"name_only": "known by name only", "described": "known by description only"}.get(
                    f["known_by"], f"known: {f['known_by']}"))
            if f.get("id_certainty") is not None and f["id_certainty"] < 6:
                head.append(f"not sure who (certainty {Units.num(f['id_certainty'])}/10)")
            look = []
            if "look.age" in f:
                look.append(f"looks about {Units.num(round(f['look.age']))}")
            if f.get("look.sex") and f["look.sex"] != "unclear":
                look.append(f["look.sex"])
            for k in ("look.posture", "look.motion", "look.expression", "look.condition"):
                v = f.get(k)
                if v and v not in ("still", "neutral", "active"):
                    look.append(str(v))
            if f.get("look.wounds"):
                look.append(f"wounds {Units.num(f['look.wounds'])}")
            for k in ("look.build", "look.attire", "look.marks", "look.signs", "look.health"):
                if f.get(k):
                    look.append(f"{k.split('.')[1]}: {c.fmt(f[k])}")
            if f.get("look.held"):
                look.append("holds something")
            if f.get("look.gaze"):
                look.append("looking at " + str(f["look.gaze"]))
            rel = [(c.label(r, n), v) for n, v in f.items() if n.startswith("rel.") and n != "rel.familiarity"]
            sel = Salience.pick(rel, self.REL_MIN, bipolar=True, limit=5)
            bits = ["; ".join(look)] if look else []
            if sel:
                bits.append("toward them: " + Salience.words(sel))
            if f.get("rel.familiarity") is not None:
                bits.append(f"familiarity {Units.num(f['rel.familiarity'])}")
            if f.get("rep"):
                bits.append("reputation: " + c.fmt(f["rep"]))
            handled = {"name", "link", "present", "dist", "dir", "known_by", "id_certainty", "rep"} | {
                n for n in f if n.startswith(("look.", "rel."))}
            bits += c.leftovers(r, handled)
            out.append(" | ".join([" ".join(head)] + bits))
        for r in c.of("GROUP"):
            f = r.fields
            rel = [(c.label(r, n), v) for n, v in f.items() if n.startswith("rel.")]
            sel = Salience.pick(rel, self.REL_MIN, bipolar=True, limit=5)
            out.append(" | ".join([f"{r.key} a group ({f.get('known_by', 'seen')})"]
                                  + (["toward them: " + Salience.words(sel)] if sel else [])
                                  + c.leftovers(r, {"known_by"} | {n for n in f if n.startswith("rel.")})))
        return out


class ThingsSection(Section):
    title = "THINGS AROUND YOU AND IN YOUR HANDS (keys: @T...)"

    def lines(self, c):
        out = []
        for r in c.of("THING") + c.of("INV"):
            f = r.fields
            head = [f"{r.key} {f.get('kind', 'something')}"]
            if r.type == "INV":
                head.append("carried by you")
            elif "dist" in f:
                head.append(f"{Units.dist(f['dist'])} {Units.heading(f['dir'])}" if "dir" in f else Units.dist(f["dist"]))
            bits = []
            if f.get("display") or f.get("motion"):
                bits.append("behaviour: " + ", ".join(str(x) for x in (f.get("display"), f.get("motion")) if x))
            if f.get("amount") and f["amount"] != "unknown":
                bits.append(f"quantity {f['amount']}")
            if "owner" in f and f["owner"] is not None:
                bits.append("owner you believe: " + ("you" if f["owner"] == "me" else str(f["owner"])))
            elif r.type == "THING" and "props" in f:
                bits.append("owner: nobody you know")
            if f.get("file_certainty") is not None and f["file_certainty"] < 7:
                bits.append(f"not sure what it is ({Units.num(f['file_certainty'])}/10)")
            if f.get("depth"):
                bits.append(f"depth {f['depth']}")
            props = f.get("props") or {}
            if props:
                num = [f"{k} {Units.num(v)}" for k, v in props.items() if not isinstance(v, bool)]
                yes = [k for k, v in props.items() if v is True]
                if num:
                    bits.append(", ".join(num))
                if yes:
                    bits.append("can/is: " + " ".join(yes))
            if f.get("state"):
                bits.append("state: " + c.fmt(f["state"]))
            bits += c.leftovers(r, {"kind", "dist", "dir", "display", "motion", "amount", "owner", "file_certainty",
                                    "depth", "props", "state", "file"})
            out.append(" | ".join([" ".join(head)] + bits))
        return out


class HappenedSection(Section):
    title = "WHAT JUST HAPPENED (keys: @V..., h:..., q:...)"

    def lines(self, c):
        out = []
        for r in c.of("EVENT"):
            f = r.fields
            s = f"{r.key} {Units.ago(f['age'])}, {f.get('sense', 'seen')}: {f.get('actor', '?')} does {f.get('gesture', '?')}"
            if f.get("target"):
                s += f" to {f['target']}"
            if f.get("with"):
                s += f" with {f['with']}"
            if f.get("from_to"):
                s += f" ({f['from_to']})"
            if f.get("manner"):
                s += f", manner: {c.fmt(f['manner'])}"
            left = c.leftovers(r, {"actor", "gesture", "target", "sense", "age", "manner", "with", "from_to"})
            out.append(s + ("; " + "; ".join(left) if left else ""))
        for r in c.of("HEARD"):
            f = r.fields
            who = f.get("informant")
            out.append(f"{r.key} {Units.ago(f['age'])}, {f.get('source', 'told')}" + (f" by {who}" if who else "")
                       + f": {c.glosser.show(f.get('prop'))}")
        for r in c.of("REQUEST"):
            f = r.fields
            out.append(f"{r.key} {Units.ago(f['age'])}, {f.get('from', '?')} says to you: {c.glosser.show(f.get('prop'))}")
        return out


class BeliefsSection(Section):
    title = "WHAT YOU BELIEVE (keys: b:...; certainty 0-10)"

    def lines(self, c):
        out = []
        for r in c.of("BELIEF"):
            f = r.fields
            src = [str(f.get("source", "?"))]
            if f.get("informant"):
                src.append(f"via {f['informant']}")
            if f.get("hops"):
                src.append(f"{f['hops']} hop(s)")
            bits = [" ".join(src)]
            if f.get("age") is not None:
                bits.append(Units.ago(f["age"]))
            if f.get("certainty") is not None:
                bits.append(f"certainty {Units.num(f['certainty'])}")
            if f.get("importance") is not None and f["importance"] >= 3:
                bits.append(f"important {Units.num(f['importance'])}")
            if f.get("polarity") is False:
                bits.append("you hold it FALSE")
            if f.get("contradicted"):
                bits.append("contradicted")
            if f.get("secret"):
                bits.append("secret")
            if f.get("shared"):
                bits.append("told to " + c.fmt(f["shared"]))
            left = c.leftovers(r, {"prop", "source", "informant", "hops", "age", "certainty", "importance", "polarity",
                                   "contradicted", "secret", "shared", "weight"})
            out.append(f"{r.key} {c.glosser.show(f.get('prop'))} | " + ", ".join(bits + left))
        return out


class MemoriesSection(Section):
    title = "WHAT YOU REMEMBER (keys: m:...)"

    def lines(self, c):
        out = []
        for r in c.of("MEMORY"):
            f = r.fields
            bits = []
            if f.get("age") is not None:
                bits.append(Units.ago(f["age"]))
            if f.get("emotion"):
                bits.append(f"felt {str(f['emotion']).replace('e_', '')}")
            if f.get("role"):
                bits.append(f"your part: {f['role']}")
            if f.get("place"):
                bits.append(f"at {f['place']}")
            if f.get("interp"):
                bits.append(f"you judged it: {f['interp']}")
            for k in ("defining", "secret"):
                if f.get(k):
                    bits.append(k)
            if f.get("importance") is not None and f["importance"] >= 3:
                bits.append(f"important {Units.num(f['importance'])}")
            left = c.leftovers(r, {"prop", "age", "emotion", "role", "place", "interp", "defining", "secret", "importance",
                                   "valence", "vividness"})
            out.append(f"{r.key} {c.glosser.show(f.get('prop'))} | " + ", ".join(bits + left))
        return out


class GoalsSection(Section):
    title = "WHAT YOU WANT, YOUR PLAN AND YOUR PROMISES (keys: g:..., p:..., c:...)"

    def lines(self, c):
        out = []
        for r in c.of("GOAL"):
            f = r.fields
            bits = [f"{f.get('mode', 'achieve')}, {f.get('status', 'active')}"]
            if f.get("priority") is not None:
                bits.append(f"priority {Units.num(f['priority'])}")
            if f.get("progress") is not None:
                bits.append(f"progress {round(f['progress'] * 100)}%")
            if f.get("origin"):
                bits.append(f"origin {f['origin']}" + (f" ({f['origin_ref']})" if f.get("origin_ref") else ""))
            if f.get("deadline") is not None:
                bits.append(f"deadline in {Units.span(f['deadline'])}")
            left = c.leftovers(r, {"prop", "mode", "status", "priority", "progress", "origin", "origin_ref", "age", "deadline"})
            out.append(f"{r.key} {c.glosser.show(f.get('prop'))} | " + ", ".join(bits + left))
        for r in c.of("PLAN"):
            f = r.fields
            bits = [f"next step {f.get('step', '?')}"]
            if f.get("goal"):
                bits.append(f"serves {f['goal']}")
            if f.get("commitment") is not None:
                bits.append(f"commitment {Units.num(f['commitment'])}/10")
            if f.get("progress") is not None:
                bits.append(f"progress {round(f['progress'] * 100)}%")
            out.append(f"{r.key} your current plan: " + ", ".join(bits))
        for r in c.of("COMMIT"):
            f = r.fields
            who = f.get("counterparty", "?")
            tag = f"you owe {who}" if f.get("mine") else f"{who} owes you"
            bits = [str(f.get("status", "open"))]
            if f.get("deadline") is not None:
                bits.append(f"due in {Units.span(f['deadline'])}")
            if f.get("witnesses"):
                bits.append("witnesses " + c.fmt(f["witnesses"]))
            out.append(f"{r.key} {tag}: {c.glosser.show(f.get('prop'))} | " + ", ".join(bits))
        return out


class SkillsSection(Section):
    title = "WHAT YOU CAN DO WELL, WHAT YOU LIKE (keys: k:..., t:...)"

    def lines(self, c):
        out = []
        sk = [f"{r.fields.get('technique')} {Units.num(r.fields.get('self_estimate'))}" for r in c.of("SKILL")]
        if sk:
            out.append("Skills (your own estimate, 0-10): " + ", ".join(sk) + ".")
        ta = [f"{r.fields.get('concept')} {Units.num(r.fields.get('attitude'))}" for r in c.of("TASTE")]
        if ta:
            out.append("Tastes (-10 hate .. 10 love): " + ", ".join(ta) + ".")
        return out


# ----------------------------------------------------------------------------------------------------- renderer
class SituationRenderer:
    """Situation (or bare records) -> the user message of the teacher."""

    SECTIONS = (WakeSection, SelfSection, WhereWhenSection, PeopleSection, ThingsSection, HappenedSection, BeliefsSection,
                MemoriesSection, GoalsSection, SkillsSection, OtherSection)
    CLOSING = "Decide what you do next, in character. Answer with the JSON object only."

    def __init__(self, tk: Toolkit | None = None):
        self.tk = tk or Toolkit()

    def render(self, situation) -> str:
        """Only situation.context.records is read; situation.scene (the truth) is never touched."""
        return self.render_records(situation.context.records)

    def render_records(self, records) -> str:
        ctx = RenderContext(self.tk, records)
        blocks = [s().render(ctx) for s in self.SECTIONS]
        return "\n\n".join(b for b in blocks if b) + "\n\n" + self.CLOSING
