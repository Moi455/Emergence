"""schema.py - the fixed part of the teacher's prompt and the shape of its answer.

    DecisionSchema(tk).instructions()    the system text: role, gestures, stop conditions, inner language, writable variables, rules
    DecisionSchema(tk).response_schema() the JSON schema for Gemini structured output (OpenAPI subset, no oneOf)
    DecisionSchema(tk).json_schema()     the same shape in standard JSON-schema spelling (lowercase types)
    DecisionSchema(tk).gbnf()            an equivalent GBNF grammar for a local model (llama.cpp style; not run here)

All lists (gestures, parameters, values, variables, bounds, words) are generated from model_interface.json and the
catalogue: a catalogue change changes the prompt. The answer is ONE gesture; what is said is the `speech` field.
"""
from __future__ import annotations

import hashlib
import json
import re

from .spec import GestureSpec, OutputSpec, WritableVar
from .toolkit import Toolkit

REF_KINDS = (("ENTITY", "@E"), ("GROUP", "@G"), ("THING", "@T"), ("INV", "@T"), ("PLACE", "@PLACE"), ("LOCUS", "@L"),
             ("BELIEF", "b:"), ("relative_direction_head", "direction"), ("forms", "form"))
MAX_WHY_WORDS = 30
EXAMPLES = (
    {"why": "He is rude to me, I answer him sharply.", "gesture": "speak",
     "params": [("to", "@E2"), ("volume", "loud"), ("tone", "angry")],
     "speech": "(request (not (did you speak (to @E3))))", "writes": [("self", "anger", "6")]},
    {"why": "Nothing to do for now, I watch the road.", "gesture": "wait", "params": [("until", "(c_elapsed 30)")],
     "speech": "", "writes": []},
    {"why": "My bowl is on the ground, I pick it up.", "gesture": "take",
     "params": [("target", "@T2"), ("from", "ground"), ("hold", "in_hand"), ("stealth", "open"),
                ("contact_zone", "hands")], "speech": "", "writes": [("@E2", "r_trust", "3")]},
)


# ------------------------------------------------------------------------------------------- instruction text
class InstructionBuilder:
    """The system text, section by section. Every list comes from the spec or the catalogue."""

    def __init__(self, tk: Toolkit, vocabulary: str = "full"):
        self.tk, self.spec, self.vocabulary = tk, tk.spec, vocabulary

    def build(self) -> str:
        parts = [self.role(), self.answer_format(), self.gestures(), self.manners(), self.conditions(), self.language(),
                 self.writes(), self.rules()]
        if self.vocabulary != "none":
            parts.append(self.words())
        parts.append(self.examples())
        return "\n\n".join(parts) + "\n"

    # ---- role and format
    def role(self) -> str:
        return ("== ROLE ==\n"
                "You are one inhabitant of a medieval-fantasy village in a simulated world. You are given your own mind "
                "at this moment: what you perceive, believe, remember and want (never the hidden truth of the world). "
                "Decide what you do in the next seconds, in character: as this person really would, with their "
                "temperament, feelings, needs, relations and knowledge, not as a polite assistant would. People can be "
                "kind, selfish, afraid, proud, deceitful or violent, according to who they are and what they know. "
                "Doing nothing is a choice only when nothing in your mind calls for more. You know only what your "
                "records say; you can be wrong.")

    def answer_format(self) -> str:
        return ("== ANSWER FORMAT ==\n"
                "Reply with one JSON object and nothing else:\n"
                f'  "why": at most {MAX_WHY_WORDS} words, your reason (discarded afterwards, think briefly here first);\n'
                f'  "gesture": exactly one gesture id from GESTURES;\n'
                '  "params": a list of {"name", "value"} (both strings), one per parameter of that gesture; every parameter '
                "is required unless marked ?; do not repeat a name;\n"
                '  "speech": the content you say or write, as one S-expression of the inner language (see SPEECH), only '
                'for the gestures that take "speech"; otherwise an empty string;\n'
                f'  "writes": at most {self.spec.max_writes} changes to your own variables (see WRITES), usually 0 to 2: '
                'a list of {"target", "variable", "value"} (all strings).\n'
                "Keys such as me, @E1, @T3, @L1, @G1, @PLACE, b:2, m:1, g:1 are those printed in your records; use "
                "only keys that appear there. A key kind: @E person, @G group, @T thing or animal, @L known place, "
                "@PLACE where you are, b: belief, m: memory, g: goal.")

    # ---- gestures
    def _ref(self, p) -> str:
        kinds = []
        for tok in p.tokens:
            for name, short in REF_KINDS:
                if re.search(rf"\b{name}\b", tok) and short not in kinds:
                    kinds.append(short)
        label = "|".join(kinds) or "ref"
        return f"{label}[{','.join(p.accepts)}]"

    def _param(self, p) -> str:
        opt = "?" if p.optional else ""
        if p.kind == "enum":
            return f"{p.name}{opt}:<{p.head}>"
        if p.kind == "ref":
            return f"{p.name}{opt}:{self._ref(p)}"
        if p.kind == "condition":
            return f"{p.name}{opt}:COND"
        return f'{p.name}{opt}:"speech"'

    def gesture_line(self, g: GestureSpec) -> str:
        parts = [self._param(p) for p in g.params if p.kind != "expression"]
        if g.expression_param is not None:
            parts.append('speech (the "speech" field)')
        return f"  {g.id}" + (" " + " ".join(parts) if parts else "")

    def gestures(self) -> str:
        lines = [self.gesture_line(g) for g in self.spec.gestures.values()]
        return ("== GESTURES (one per answer) ==\n"
                'Each line: gesture id, then its parameters name:type. <scale> = pick a value of that scale (see MANNER '
                "SCALES); @E|@T... = a key of those kinds, whose real nature must be one of [the listed classes] (you "
                "cannot eat a stone, or take a place); COND = a stop condition (see STOP CONDITIONS). A parameter marked ? "
                "may be left out. direction = one of: " + ", ".join(self.spec.directions) + ".\n" + "\n".join(lines))

    def manners(self) -> str:
        lines = []
        for head, h in self.spec.manner_heads.items():
            lines.append(f"  {head}: " + (" < ".join(h["values"]) if h["ordinal"] else " | ".join(h["values"])))
        return ("== MANNER SCALES ==\n"
                "A < B < C = ordered, weakest to strongest; A | B = unordered choices. A slap is a light open-hand "
                "strike, a beating is hard or full blows continued until the other yields.\n" + "\n".join(lines))

    def conditions(self) -> str:
        words = {"quantity": "N", "entity": "KEY", "place": "@L|@PLACE", "kind": "KIND", "concept": "WORD", "time": "TIME"}
        lines = []
        for cid, args in self.spec.conditions.items():
            lines.append(f"  ({cid}" + "".join(f" {words.get(a, a)}" for a in args) + ")" if args else f"  {cid}")
        return ("== STOP CONDITIONS (COND: when the engine stops the gesture and asks you again) ==\n"
                "Write a bare id, or the id with its arguments in parentheses: c_done  or  (c_elapsed 30). They are "
                "read on what you perceive, never on the hidden world. N = a number, KEY = a record key, KIND = a kind "
                "word, WORD = a concept word, TIME = a time word.\n" + "\n".join(lines))

    # ---- inner language
    def language(self) -> str:
        cat, v = self.tk.cat, self.tk.vocab
        by = {}
        for c in cat["concept"].values():
            by.setdefault(c.category, []).append(c)
        words = lambda cat_name: " ".join(sorted(c.id for c in by.get(cat_name, [])))   # noqa: E731
        preds = " ".join(f"{c.id}({','.join(c.args)})" for c in sorted(by["predicate"], key=lambda c: c.id)
                         if c.id != "did")
        return ("== SPEECH (the inner language) ==\n"
                'Only for speak and write. S-expression in prefix order, e.g. (assert (has @E1 bread)). Parentheses do not count; '
                f"every other symbol does: at most {self.spec.max_symbols} symbols, nesting of propositions inside "
                f"believes/wants/intends/says/that at most {self.spec.max_depth}, at most {self.spec.max_pointers} pointers "
                "per proposition. There is no word for lying, threatening, promising or insulting: you compose them "
                "(a threat is an assert of an if; a promise an offer; a lie an assert of what you believe false).\n"
                "  UTT := (MOOD PROP) | (FORMULA) | (FORMULA UTT)\n"
                f"  MOOD: {words('mood')}\n"
                f"  FORMULA: {words('formula')}\n"
                "  PROP := (PRED ARG...) | (not P) | (and P P) | (or P P) | (if P P) | (because P P) | (TIME P) | "
                "(EVID P) | (that b:N) | b:N | (did AGENT GESTURE [TARGET] ROLE...)\n"
                f"  TIME: {words('time')}\n"
                f"  EVID: {words('evidential')}\n"
                "  ROLE := (with REF) | (to REF) | (into REF) | (how MANNER) | (says PROP)   (at most "
                "3; says only with speak/write)\n"
                f"  PRED(argument types): {preds}\n"
                "  ARG := REF | KIND[:N] | N | DEGREE | WORD | PROP | HOLE\n"
                "  REF := me | you | this | here | @E1 | @T2 | @G1 | @L1 | @V1 | @PLACE | n:ID | someone | anyone | "
                "everyone | no_one | (described WORD+)\n"
                f"  DEGREE: {words('degree')} ; QUANTIFIER: {words('quantifier')}\n"
                f"  HOLE (only inside ask): {words('wh')}\n"
                "Pointers: me you @E @T @G @L @V @PLACE b: m: g: must be keys of your records ((that b:7) repeats "
                "what you hold in belief b:7); n:ID is a name printed next to a person. Argument types: agent = a "
                "person, entity = person/thing/group/place, item = a thing, place, group, kind = a kind word (item, "
                "material, species, form), concept = a concept word, quantity = number or degree, time = a time word, "
                "proposition = a PROP, event = a perceived event @V or a (did ...) frame.")

    # ---- writes
    def writes(self) -> str:
        groups: dict[str, list[WritableVar]] = {}
        for w in self.spec.writes.values():
            groups.setdefault(self._group(w), []).append(w)
        out = ["== WRITES (changes to your own variables; each is {target, variable, value}; give the NEW value) ==",
               "The governor bounds every write: steps are clipped, only emotions (and a few marked jump) can change at "
               "once; traits and values move at most 0.1 per decision and almost never need writing. Write only what "
               "this moment really changes in you: usually emotions, a relation toward someone present, a belief you "
               "just formed, a new goal. Numbers use the scale printed in your records."]
        for title, ws in sorted(groups.items(), key=lambda kv: kv[0]):
            out.append(f"  {title}: " + "; ".join(self._var(w) for w in ws))
        out.append('Creating a record: target "new" with variable b_proposition, g_desired or m_content and an '
                   "S-expression as value (a proposition, not an utterance: (PRED ARG...) or (past (did ...))). "
                   'Values: numbers like "3.5"; true/false for bool; a listed word for enum/word; a record key for mref; '
                   "hours for time (time_until: hours from now, 0 or more).")
        return "\n".join(out)

    @staticmethod
    def _group(w: WritableVar) -> str:
        tgt = {"self": "target self", "entity": "target @E or @G key", "belief": "target b: key or new",
               "goal": "target g: key or new", "memory": "target m: key or new", "plan": "target p: key"}[w.target_kind]
        return f"{tgt} ({w.mode})"

    @staticmethod
    def _var(w: WritableVar) -> str:
        if w.numeric:
            b = w.bounds
            return f"{w.id} [{b[0]:g}..{b[1]:g}]" if b else w.id
        if w.scale == "enum" or (w.scale == "word" and w.values):
            return f"{w.id} = " + "|".join(w.values[:12]) + ("|..." if len(w.values) > 12 else "")
        return f"{w.id} = {w.scale}"

    # ---- rules
    def rules(self) -> str:
        return ("== HARD RULES ==\n"
                "1. Never make a child or teenager (anyone under 18, or who may be: age unknown, seen young, known only "
                "by name) the actor or the target of anything romantic or sexual, in a gesture, a word or a write. The "
                "engine refuses it in any case.\n"
                "2. Act only through the gestures above, on keys present in your records. Speech is the only place for "
                "words; a social act (a threat, a promise, a theft) is not a gesture.\n"
                "3. You know only your records. What a person really is, owns or intends is not known to you.\n"
                "4. One gesture per answer. Leave speech empty unless the gesture takes it.")

    # ---- vocabulary
    def words(self) -> str:
        v, spec = self.tk.vocab, self.spec
        skip = {"gesture", "manner", "condition", "predicate", "direction", "mood", "formula", "time", "evidential",
                "wh", "degree", "quantifier", "event_role", "logic", "property"}
        by: dict[str, list[str]] = {}
        for w, cs in sorted(v.cats.items()):
            for c in sorted(cs - skip):
                by.setdefault(c, []).append(w)
        lines = [f"  {c}: " + " ".join(ws) for c, ws in sorted(by.items())]
        props = sorted(w for w, cs in v.cats.items() if "property" in cs)
        lines.append("  property (words for a state of a thing): " + " ".join(props))
        text = ("== WORDS (the only words the inner language knows, by category; a word may belong to several) ==\n"
                + "\n".join(lines))
        if self.vocabulary == "full":
            cat = self.tk.cat
            kinds = []
            for table, name in (("item_type", "item"), ("material", "material"), ("species", "species"), ("form", "form")):
                kinds.append(f"  {name}: " + " ".join(sorted(cat[table])))
            text += ("\n== KINDS (things, materials, living species, forms; a kind may carry a count: bread:3) ==\n"
                     + "\n".join(kinds))
        return text

    # ---- examples
    def examples(self) -> str:
        out = ["== EXAMPLES (format only; keys are examples, use yours) =="]
        for e in EXAMPLES:
            out.append(json.dumps(DecisionSchema.example_object(e), separators=(",", ":")))
        return "\n".join(out)


# ------------------------------------------------------------------------------------------- schemas
class DecisionSchema:
    """Facade: instructions + response schema (+ grammar) for one catalogue state."""

    FIELDS = ("why", "gesture", "params", "speech", "writes")

    def __init__(self, tk: Toolkit | None = None, vocabulary: str = "full"):
        self.tk = tk or Toolkit()
        self.spec: OutputSpec = self.tk.spec
        self.vocabulary = vocabulary

    @staticmethod
    def example_object(e: dict) -> dict:
        return {"why": e["why"], "gesture": e["gesture"], "params": [{"name": n, "value": v} for n, v in e["params"]],
                "speech": e["speech"], "writes": [{"target": t, "variable": n, "value": v} for t, n, v in e["writes"]]}

    # ---- text
    def instructions(self) -> str:
        return InstructionBuilder(self.tk, self.vocabulary).build()

    # ---- JSON schema
    def _object(self, props: dict, required: list, gemini: bool) -> dict:
        t = (lambda x: x.upper()) if gemini else (lambda x: x)           # noqa: E731
        node = {"type": t("object"), "properties": props, "required": required}
        if gemini:
            node["propertyOrdering"] = list(props)
        return node

    def _schema(self, gemini: bool) -> dict:
        t = (lambda x: x.upper()) if gemini else (lambda x: x)           # noqa: E731
        string = {"type": t("string")}
        write_vars = sorted(self.spec.writes)
        param = self._object({"name": {**string, "enum": self.spec.param_names}, "value": string}, ["name", "value"], gemini)
        write = self._object({"target": string, "variable": {**string, "enum": write_vars}, "value": string},
                             ["target", "variable", "value"], gemini)
        props = {
            "why": string,
            "gesture": {**string, "enum": self.spec.gesture_ids},
            "params": {"type": t("array"), "items": param},
            "speech": string,
            "writes": {"type": t("array"), "items": write, "maxItems": self.spec.max_writes},
        }
        return self._object(props, list(self.FIELDS), gemini)

    def response_schema(self) -> dict:
        """For generationConfig.responseSchema (Gemini): uppercase OpenAPI types, propertyOrdering, no oneOf."""
        return self._schema(gemini=True)

    def json_schema(self) -> dict:
        return self._schema(gemini=False)

    # ---- GBNF
    def gbnf(self) -> str:
        """Same shape as the JSON schema, keys in the fixed order why, gesture, params, speech, writes. Strings are
        free text (the validator checks them); enums are closed. Untested against a llama.cpp build here."""
        q = lambda s: '"\\"' + s + '\\""'                                  # noqa: E731
        alt = lambda xs: " | ".join(q(x) for x in xs)                      # noqa: E731
        return "\n".join([
            f'root ::= "{{" ws {q("why")} ws ":" ws string ws "," ws {q("gesture")} ws ":" ws gesture ws "," ws '
            f'{q("params")} ws ":" ws params ws "," ws {q("speech")} ws ":" ws string ws "," ws {q("writes")} ws ":" ws writes ws "}}"',
            f"gesture ::= {alt(self.spec.gesture_ids)}",
            f"pname ::= {alt(self.spec.param_names)}",
            f"wvar ::= {alt(sorted(self.spec.writes))}",
            f'param ::= "{{" ws {q("name")} ws ":" ws pname ws "," ws {q("value")} ws ":" ws string ws "}}"',
            f'write ::= "{{" ws {q("target")} ws ":" ws string ws "," ws {q("variable")} ws ":" ws wvar ws "," ws '
            f'{q("value")} ws ":" ws string ws "}}"',
            'params ::= "[" ws "]" | "[" ws param ( ws "," ws param ){0,9} ws "]"',
            f'writes ::= "[" ws "]" | "[" ws write ( ws "," ws write ){{0,{self.spec.max_writes - 1}}} ws "]"',
            'string ::= "\\"" ( [^"\\\\\\n] | "\\\\" ["\\\\/bfnrt] )* "\\""',
            "ws ::= [ \\t\\n]*",
            ""])

    # ---- bookkeeping
    def fingerprint(self) -> str:
        blob = json.dumps(self.response_schema(), sort_keys=True) + self.instructions()
        return hashlib.sha256(blob.encode()).hexdigest()[:16]
