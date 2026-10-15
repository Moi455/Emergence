"""gen_cpp.py - generate the C++ tables of the social engine from the catalogue (decision D31: one source of truth).

    python3 catalogue/tools/gen_cpp.py          # writes engine/social/generated/emergence/social/*.h
    python3 catalogue/tools/gen_cpp.py --check  # exit 1 when a generated file or var_registry.json is stale

Identifiers are STABLE (append-only registries, task T02): a gesture, a condition, a variable or a word keeps its
numeric id when the catalogue grows. Gestures and conditions follow ai/student2/output_registry.json, words and
kinds follow catalogue/generated/vocab_registry.json (seeded from ai/tok2/registry.json order), variables follow
catalogue/generated/var_registry.json (both owned by this generator, appended to on each run). The values of an
enum param follow the model's manner head (output_registry.json); a value the param no longer offers is cleared
from its valid_mask. A catalogue entry that
disappears stays in its slot as `retired_N` (compiles, refused by the governor, never reused).

Gestures (in the order of the model's gesture head) with their parameters (value lists,
D10 intimate and minor-whitelist masks), conditions, and variables with their governor bounds in TENTHS (the
engine stores tenths of the charter scale). A fingerprint is embedded so the engine can refuse a model trained on
another catalogue: FNV-1a 64 of the text of model_interface.json followed by this very file without the line that
declares kCatalogueFingerprint (the fingerprint cannot hash itself). The generator refuses to run on a catalogue
that does not validate.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import model_interface  # noqa: E402
import forgetting  # noqa: E402
from governor import ADULT_AGE, LEDGER_CAPACITY, MAX_DAY_JUMP, MAX_YEAR_JUMP, SELF_HOLDERS, tenths  # noqa: E402

FP_MARK = "@@FINGERPRINT@@"   # placeholder of the fingerprint line while the body is hashed
OUT = ROOT.parent / "engine" / "social" / "generated" / "emergence" / "social" / "catalogue_gen.h"
WRITER_BITS = {"engine": 1, "T_jump": 2, "T_step": 4, "T_slow": 8, "birth": 16, "action": 32, "derived": 64}
SCALES = ("bipolar10", "unipolar10", "qty", "ratio", "enum", "id", "mref", "word", "bool", "list", "proposition", "time")
FAMILIES = ("move", "posture", "grasp", "force", "tool", "transform", "consume", "care", "perceive", "communicate", "meta")
PARAM_TYPES = ("ref", "enum", "qty", "duration", "condition", "expression", "bool")
MAX_PARAMS, MAX_VALUES = 6, 16   # 16 = the width of the uint16 masks


CPP_KEYWORDS = {"alignas", "alignof", "and", "asm", "auto", "bool", "break", "case", "catch", "char", "class", "const",
                "continue", "default", "delete", "do", "double", "else", "enum", "explicit", "export", "extern", "false",
                "float", "for", "friend", "goto", "if", "inline", "int", "long", "mutable", "namespace", "new", "not",
                "operator", "or", "private", "protected", "public", "register", "return", "short", "signed", "sizeof",
                "static", "struct", "switch", "template", "this", "throw", "true", "try", "typedef", "typename", "union",
                "unsigned", "using", "virtual", "void", "volatile", "while", "xor", "concept", "requires", "module"}


def ident(name: str) -> str:
    """A catalogue id as a C++ identifier (keywords get a trailing underscore: throw -> throw_)."""
    return name + "_" if name in CPP_KEYWORDS else name


def fnv1a64(text: str) -> int:
    h = 0xcbf29ce484222325
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def cpp_str(s: str) -> str:
    """A C++ string literal. Control characters become 3-digit octal escapes (never swallow a following digit)."""
    out = []
    for ch in s:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7f:
            out.append("\\%03o" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def check_identifiers(what: str, ids: list, reserved: tuple = ()) -> None:
    """The generated identifiers must be valid C++ and unique once keywords are sanitised."""
    seen: dict[str, str] = {}
    for i in ids:
        c = ident(i)
        if not _IDENT.match(c):
            raise SystemExit(f"{what}: '{i}' is not a valid C++ identifier")
        if c in reserved:
            raise SystemExit(f"{what}: '{i}' collides with the reserved enumerator '{c}'")
        if c in seen:
            raise SystemExit(f"{what}: '{i}' and '{seen[c]}' give the same C++ identifier '{c}'")
        seen[c] = i


# ---------------------------------------------------------------------------------------------------------
# Stable identifiers: append-only registries.
AI_DIR = ROOT.parent / "ai"
GESTURE_REGISTRY = AI_DIR / "student2" / "output_registry.json"   # gestures, conditions (read only)
SYMBOL_REGISTRY = AI_DIR / "tok2" / "registry.json"               # symbols: words and kinds (read only)
VAR_REGISTRY = ROOT / "generated" / "var_registry.json"           # variables (owned by this generator)
VAR_SCHEMA = "var-registry-1"
VOCAB_REGISTRY = ROOT / "generated" / "vocab_registry.json"   # words and kinds (owned by this generator)


class RegistryStale(Exception):
    """A registry I do not own lacks entries of the catalogue (the message names the command that fixes it)."""


class Slot:
    """One id of an append-only registry: its name, and whether the catalogue still has it (else it is retired)."""
    __slots__ = ("index", "name", "live")

    def __init__(self, index: int, name: str, live: bool):
        self.index, self.name, self.live = index, name, live

    @property
    def cpp(self) -> str:
        """The C++ enumerator: the catalogue id, or retired_N for a retired slot (the id is never reused)."""
        return ident(self.name) if self.live else f"retired_{self.index}"


class StableOrder:
    """Registered names keep their place; the live names the registry lacks follow, sorted (they will be appended)."""

    def __init__(self, registered: list, live):
        live = set(live)
        if len(set(registered)) != len(registered):
            raise SystemExit("a registry holds a name twice")
        self.registered = list(registered)
        self.pending = sorted(live - set(registered))
        names = self.registered + self.pending
        self.slots = [Slot(i, n, n in live) for i, n in enumerate(names)]

    def __len__(self):
        return len(self.slots)

    @property
    def names(self) -> list:
        return [s.name for s in self.slots]

    @property
    def fingerprint(self) -> int:
        return fnv1a64("\n".join(self.names))


class AppendOnlyFile:
    """A JSON file of append-only name lists (catalogue/generated/*_registry.json). A name that leaves the catalogue
    stays with "retired": true and keeps its index forever; one that comes back takes its old index."""
    SCHEMA = ""
    LISTS: tuple = ()

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lists: dict = {k: [] for k in self.LISTS}
        if self.path.exists():
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if d.get("schema") != self.SCHEMA:
                raise SystemExit(f"{self.path}: schema {d.get('schema')!r}, expected {self.SCHEMA!r}")
            self.lists = {k: d[k] for k in self.LISTS}

    def updated(self, live: dict, hints: dict | None = None):
        """A copy with the new names appended (in the order of hints[list] when given, else sorted) and the retired
        flags brought up to date."""
        new = type(self).__new__(type(self))
        new.path = self.path
        new.lists = {}
        for k in self.LISTS:
            want = set(live[k])
            known = {e["name"] for e in self.lists[k]}
            rank = {n: i for i, n in enumerate((hints or {}).get(k, []))}
            out = [{"name": e["name"], **({} if e["name"] in want else {"retired": True})} for e in self.lists[k]]
            out += [{"name": n} for n in sorted(want - known, key=lambda n: (rank.get(n, len(rank)), n))]
            new.lists[k] = out
        return new

    def names(self, key: str) -> list:
        return [e["name"] for e in self.lists[key]]

    def text(self) -> str:
        return json.dumps({"schema": self.SCHEMA, **self.lists}, indent=1, ensure_ascii=False) + "\n"

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.text(), encoding="utf-8")


class VarRegistry(AppendOnlyFile):
    """Every variable ever in the catalogue (catalogue/generated/var_registry.json)."""
    SCHEMA, LISTS = VAR_SCHEMA, ("vars",)

    def __init__(self, path: Path = VAR_REGISTRY):
        super().__init__(path)

    @property
    def entries(self) -> list:
        return self.lists["vars"]


class VocabRegistry(AppendOnlyFile):
    """Every word and every kind ever in the inner language (catalogue/generated/vocab_registry.json). Seeded in the
    order of ai/tok2/registry.json, then owned here: a word the catalogue drops keeps its slot (retired_N)."""
    SCHEMA, LISTS = "vocab-registry-1", ("words", "kinds")

    def __init__(self, path: Path = VOCAB_REGISTRY):
        super().__init__(path)


class Orders:
    """The stable orders of one generation run. `strict`: a registry owned by the AI side that lacks entries of
    the catalogue is an error (the C++ ids would not match the model's); otherwise the news are appended virtually."""

    def __init__(self, cat: Catalogue, strict: bool = True, gesture_registry: Path = GESTURE_REGISTRY,
                 symbol_registry: Path = SYMBOL_REGISTRY, var_registry: VarRegistry | None = None,
                 vocab_registry: VocabRegistry | None = None):
        import language
        out = json.loads(Path(gesture_registry).read_text(encoding="utf-8"))
        sym = json.loads(Path(symbol_registry).read_text(encoding="utf-8"))["symbols"]
        vocab = language.Vocabulary(cat)
        self.gestures = StableOrder([e["name"] for e in out["gestures"]], cat["action"])
        self.conditions = StableOrder([e["name"] for e in out["conditions"]],
                                      (c.id for c in cat["concept"].values() if c.category == "condition"))
        # manner heads: the value order of a head is the model's; a param finds its head in the gesture signature
        self.heads = {h["name"]: list(h["values"]) for h in out["manner"]}
        self.param_head = {}
        for e in out["gestures"]:
            for part in e["sig"].split("|"):
                f = part.split(":")
                if f[0] == "enum":
                    self.param_head[(e["name"], f[1])] = f[2]
        self.pending_values: list = []
        for gid in sorted(cat["action"]):
            for prm in cat["action"][gid].params:
                head = self.param_head.get((gid, prm.name))
                if prm.type == "enum" and head in self.heads:
                    for v in prm.values:
                        if v not in self.heads[head]:
                            self.heads[head].append(v)
                            self.pending_values.append(f"{head}.{v}")
        for h, vs in self.heads.items():
            if len(vs) > MAX_VALUES:
                raise SystemExit(f"manner head {h}: {len(vs)} values > {MAX_VALUES}")
        known = set(sym)
        self.symbol_registered = list(sym)
        self.symbol_pending = sorted((set(vocab.words) | vocab.kinds) - known)
        hint = self.symbol_registered + self.symbol_pending
        self.vocab_registry = (vocab_registry or VocabRegistry()).updated(
            {"words": vocab.words, "kinds": vocab.kinds}, {"words": hint, "kinds": hint})
        self.words = StableOrder(self.vocab_registry.names("words"), vocab.words)
        self.kinds = StableOrder(self.vocab_registry.names("kinds"), vocab.kinds)
        self.var_registry = (var_registry or VarRegistry()).updated({"vars": cat["variable"]})
        self.variables = StableOrder(self.var_registry.names("vars"), cat["variable"])
        if strict:
            stale = []
            if self.gestures.pending or self.conditions.pending or self.pending_values:
                stale.append("gestures/conditions/manner values: "
                             + ", ".join((self.gestures.pending + self.conditions.pending + self.pending_values)[:6])
                             + " -> `cd ai && python3 -m student2.output_registry --update`")
            if self.symbol_pending:
                stale.append("symbols: " + ", ".join(self.symbol_pending[:6]) + " -> `cd ai && python3 -m tok2.registry --update`")
            if stale:
                raise RegistryStale("; ".join(stale))

    def param_values(self, gesture: str, prm) -> list:
        """[(value name, live)] of an enum param in the MODEL's order (its manner head), else in catalogue order. A
        value of the head that this param does not offer is not live (refused), so a shared head cannot leak."""
        head = self.param_head.get((gesture, prm.name))
        if prm.type != "enum" or head not in self.heads:
            return [(v, True) for v in prm.values]
        return [(v, v in prm.values) for v in self.heads[head]]

    def value_index(self, gesture: str, prm, value: str) -> int:
        return [n for n, _ in self.param_values(gesture, prm)].index(value)

    @property
    def symbol_names(self) -> list:
        return self.symbol_registered + self.symbol_pending


class CppGenerator:
    def __init__(self, cat: Catalogue, orders: "Orders | None" = None):
        self.cat = cat
        self.orders = orders or Orders(cat)
        self.L: list[str] = []

    def emit(self, line: str = ""):
        self.L.append(line)

    def enum(self, name: str, base: str, order: StableOrder):
        """The enum follows the registry order; a retired slot is `retired_N` (its catalogue name is in a comment)."""
        slots = order.slots
        check_identifiers(f"enum {name}", [s.cpp for s in slots], reserved=("kCount",))
        self.emit(f"enum class {name} : {base} {{")
        for sl in slots:
            self.emit(f"  {sl.cpp}," + ("" if sl.live else f"   // retired: {sl.name}"))
        self.emit("  kCount")
        self.emit("};")
        self.emit(f"inline constexpr std::array<std::string_view, {len(slots)}> k{name}Names = {{")
        self.emit("  " + ", ".join(cpp_str(sl.name if sl.live else sl.cpp) for sl in slots))
        self.emit("};")
        self.emit(f"inline constexpr std::uint64_t k{name}RegistryFingerprint = 0x{order.fingerprint:016x}ull;"
                  "   // FNV-1a 64 of the registry names, one per line")
        self.emit()

    def gestures(self):
        order = self.orders.gestures                                    # = the gestures head of output_registry.json
        self.enum("Gesture", "std::uint8_t", order)
        self.emit("inline constexpr std::array<GestureSpec, %d> kGestures = {{" % len(order))
        for sl in order.slots:
            if not sl.live:
                self.emit(f"  GestureSpec{{{cpp_str(sl.cpp)}, Family::meta, false, false, false, 0, {{}}, true}},   // retired: {sl.name}")
                continue
            a = self.cat["action"][sl.name]
            if len(a.params) > MAX_PARAMS:
                raise SystemExit(f"{a.id}: more than {MAX_PARAMS} params")
            ps = []
            for p in a.params:
                vl = self.orders.param_values(a.id, p)
                if len(vl) > MAX_VALUES:
                    raise SystemExit(f"{a.id}.{p.name}: more than {MAX_VALUES} values")
                valid = sum(1 << i for i, (_, live) in enumerate(vl) if live)
                imask = sum(1 << i for i, (v, live) in enumerate(vl) if live and v in p.intimate_values)
                allowed = a.minor_whitelist.get(p.name)
                mmask = valid if allowed is None else sum(1 << i for i, (v, live) in enumerate(vl) if live and v in allowed)
                vals = ", ".join(cpp_str(v) for v, _ in vl)
                ps.append(f"ParamSpec{{{cpp_str(p.name)}, ParamType::{ident(p.type)}, {len(vl)}, {{{vals}}}, "
                          f"0x{imask:x}, 0x{mmask:x}, {str(p.ordinal).lower()}, {str(p.optional).lower()}, "
                          f"{str(p.name in a.party_params).lower()}, {str(p.name in a.minor_whitelist).lower()}, "
                          f"{str('agent' in p.accepts).lower()}, 0x{valid:x}}}")
            if a.family not in FAMILIES:
                raise SystemExit(f"{a.id}: unknown family {a.family}")
            self.emit(f"  GestureSpec{{{cpp_str(a.id)}, Family::{ident(a.family)}, {str(bool(a.contact)).lower()}, "
                      f"{str(bool(a.intimate)).lower()}, {str(bool(a.minor_person_ok)).lower()}, {len(ps)}, {{")
            for x in ps:
                self.emit(f"    {x},")
            self.emit("  }, false},")
        self.emit("}};")
        self.emit()

    def conditions(self):
        order = self.orders.conditions
        self.enum("Condition", "std::uint8_t", order)
        self.emit("inline constexpr std::array<bool, %d> kConditionLive = {" % len(order))
        self.emit("  " + ", ".join(str(sl.live).lower() for sl in order.slots))
        self.emit("};   // false = retired slot")
        self.emit()

    def variables(self):
        order = self.orders.variables
        self.enum("Var", "std::uint16_t", order)
        self.emit("inline constexpr std::array<VariableSpec, %d> kVariables = {{" % len(order))
        for sl in order.slots:
            if not sl.live:
                self.emit(f"  VariableSpec{{{cpp_str(sl.cpp)}, \"\", Scale::bool_, 0x00, 0, 0, 0, false, false, false, true}},"
                          f"   // retired: {sl.name}")
                continue
            v = self.cat["variable"][sl.name]
            comp = self.cat["component"].get(v.holder)
            engine_only = bool(comp is not None and comp.engine_only)
            bits = sum(WRITER_BITS[w] for w in v.writer)
            self.emit(f"  VariableSpec{{{cpp_str(v.id)}, {cpp_str(v.holder)}, Scale::{ident(v.scale)}, 0x{bits:02x}, "
                      f"{tenths(v.step)}, {tenths(v.rate)}, {tenths(v.slow_rate)}, {str(bool(v.intimate)).lower()}, "
                      f"{str(engine_only).lower()}, {str(v.holder in SELF_HOLDERS).lower()}, false}},")
        self.emit("}};")
        self.emit()

    def generate(self) -> str:
        self.emit("// GENERATED by catalogue/tools/gen_cpp.py from catalogue/ - do not edit (decision D31).")
        self.emit("#pragma once")
        self.emit("#include <array>\n#include <cstdint>\n#include <string_view>\n")
        self.emit("namespace em::social::gen {\n")
        self.emit(FP_MARK)
        self.emit(f"inline constexpr std::uint64_t kSymbolRegistryFingerprint = 0x{fnv1a64(chr(10).join(self.orders.symbol_names)):016x}ull;"
                  "   // FNV-1a 64 of the tok-2 symbols (words and kinds are positions in that order)")
        self.emit(f"inline constexpr int kMaxParams = {MAX_PARAMS};\ninline constexpr int kMaxValues = {MAX_VALUES};")
        self.emit(f"inline constexpr int kAdultAgeYears = {int(ADULT_AGE)};   // D10, read from life_stage")
        self.emit(f"inline constexpr int kLedgerCapacity = {LEDGER_CAPACITY};   // governor.py LEDGER_CAPACITY")
        self.emit(f"inline constexpr int kMaxDayJump = {MAX_DAY_JUMP}, kMaxYearJump = {MAX_YEAR_JUMP};   // governor.py\n")
        self.emit("enum class Scale : std::uint8_t { " + ", ".join(ident(x) for x in SCALES) + " };")
        self.emit("enum class Family : std::uint8_t { " + ", ".join(ident(x) for x in FAMILIES) + " };")
        self.emit("enum class ParamType : std::uint8_t { " + ", ".join(ident(x) for x in PARAM_TYPES) + " };")
        self.emit("namespace writer { " + " ".join(f"inline constexpr std::uint8_t {k} = 0x{b:02x};" for k, b in WRITER_BITS.items()) + " }\n")
        self.emit("struct ParamSpec {\n  std::string_view name;\n  ParamType type;\n  std::uint8_t n_values;\n"
                  "  std::array<std::string_view, kMaxValues> values;\n  std::uint16_t intimate_mask;   // D10: refused with a minor\n"
                  "  std::uint16_t minor_mask;      // D10: values allowed when a minor is involved\n  bool ordinal;\n  bool optional;\n"
                  "  bool party;                    // D10: may designate a person involved\n"
                  "  bool whitelisted;              // D10: REQUIRED and checked against minor_mask when a minor is involved\n"
                  "  bool accepts_agent;            // may designate a person (an absent one counts unknown, D10)\n"
                  "  std::uint16_t valid_mask;      // values this param offers (values are in the model's manner-head order; others are refused)\n};\n")
        self.emit("struct GestureSpec {\n  std::string_view id;\n  Family family;\n  bool contact;           // a ref param accepts an agent (D10)\n"
                  "  bool intimate;          // D10: refused as soon as a possible minor is involved\n  bool minor_person_ok;   // D10\n  std::uint8_t n_params;\n"
                  "  std::array<ParamSpec, kMaxParams> params;\n  bool retired;           // a slot of the registry the catalogue no longer has: always refused\n};\n")
        self.emit("struct VariableSpec {\n  std::string_view id;\n  std::string_view holder;\n  Scale scale;\n  std::uint8_t writers;\n"
                  "  std::int16_t step_tenths;      // per decision\n  std::int16_t rate_tenths;      // per game day (T_step)\n"
                  "  std::int16_t slow_tenths;      // per life-year (T_slow)\n  bool intimate;\n  bool engine_only;\n"
                  "  bool self_holder;              // held by the actor himself (mind_static, mind_dynamic, needs, body): D10 looks at the actor only\n"
                  "  bool retired;                  // a slot of the registry the catalogue no longer has: always refused\n};\n")
        self.gestures()
        self.conditions()
        self.variables()
        self.emit("}  // namespace em::social::gen")
        body = "\n".join(l for l in self.L if l != FP_MARK) + "\n"
        fp = fnv1a64(model_interface.ModelInterface(self.cat).text() + body)
        line = (f"inline constexpr std::uint64_t kCatalogueFingerprint = 0x{fp:016x}ull;"
                "  // FNV-1a 64 of model_interface.json text + this file without this line")
        return "\n".join(line if l == FP_MARK else l for l in self.L) + "\n"


# ---------------------------------------------------------------------------------------------------------
# NPC state: one struct per component held by an agent, one record struct per record component (beliefs...).
STATE_OUT = OUT.parent / "npc_state_gen.h"
FORGETTING_OUT = OUT.parent / "forgetting_gen.h"
PARITY_OUT = ROOT.parent / "engine" / "social" / "tests" / "forgetting_parity.inc"
VOCAB_OUT = OUT.parent / "vocab_gen.h"
FIELDS_OUT = OUT.parent / "npc_fields_gen.h"
AGENT_COMPONENTS = ("mind_static", "mind_dynamic", "body", "needs", "lifecycle", "carrier", "activity", "beliefs",
                    "relations", "memory", "goals")
FIELD_TYPES = {"bipolar10": "std::int16_t", "unipolar10": "std::int16_t", "ratio": "std::int16_t",
               "qty": "std::int32_t", "bool": "bool", "enum": "std::uint8_t", "word": "std::uint16_t",
               "mref": "MRef", "id": "EntityId", "time": "GameTime", "proposition": "Proposition", "list": "ListRef"}
COL_TYPES = {"std::int16_t": "I16", "std::int32_t": "I32", "bool": "Bool", "std::uint8_t": "U8", "std::uint16_t": "U16",
             "MRef": "MRef", "EntityId": "Entity", "GameTime": "Time", "Proposition": "Prop", "ListRef": "List"}
# Inclusive bounds of a stored value, checked by the save codec at load (a value outside is reset to the initial one).
# bipolar10 / unipolar10 are tenths of the charter scale (governor.SCALE_BOUNDS), ratio is per-mille. The catalogue
# declares no range for a qty (milli-units of a unit) or a timestamp: only an engine sanity bound (QTY_BOUND, TIME_BOUND).
SCALE_RANGE = {"bipolar10": (-100, 100), "unipolar10": (0, 100), "ratio": (0, 1000), "bool": (0, 1)}
QTY_BOUND = 1 << 30
TIME_BOUND = 1 << 50
FIELD_NOTES = {"ratio": "per-mille", "qty": "milli-units of its unit", "enum": "value index", "word": "vocabulary id",
               "mref": "persistent id of one of the NPC's own records", "id": "objective id (engine only)",
               "time": "game seconds", "list": "handle into a side table (variable-size data)"}


def camel(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("_"))


class StateGenerator:
    def __init__(self, cat: Catalogue, orders: Orders | None = None):
        self.cat = cat
        self.orders = orders or Orders(cat)

    def fields(self, comp: str):
        return sorted((v for v in self.cat["variable"].values() if v.holder == comp), key=lambda v: v.id)

    def struct(self, comp: str, L: list):
        c = self.cat["component"][comp]
        check_identifiers(f"struct {camel(comp)}", [v.id for v in self.fields(comp)])
        L.append(f"// {comp}: {c.label_fr}" + (f" (records, {c.max_count} per NPC)" if c.max_count else ""))
        L.append(f"struct {camel(comp)} {{")
        for v in self.fields(comp):
            t = FIELD_TYPES[v.scale]
            note = FIELD_NOTES.get(v.scale, "tenths of the charter scale" if "10" in v.scale else "")
            init = "{}" if t in ("Proposition", "MRef", "EntityId", "GameTime", "ListRef") else "{}"
            L.append(f"  {t} {ident(v.id)}{init};" + (f"  // {note}" if note else ""))
        L.append("};")
        L.append("")

    def generate_state(self) -> str:
        L = ["// GENERATED by catalogue/tools/gen_cpp.py from catalogue/ - do not edit (decision D31).",
             "#pragma once", "#include <cstdint>", "", '#include "emergence/social/state_types.h"', "",
             "namespace em::social::gen {", "",
             "using em::social::EntityId; using em::social::GameTime; using em::social::ListRef;",
             "using em::social::MRef; using em::social::Proposition; using em::social::RecordPool;", ""]
        records = [c.id for c in self.cat["component"].values() if c.part_of and c.holder == "agent"]
        for comp in AGENT_COMPONENTS:
            self.struct(comp, L)
        for comp in sorted(records):
            self.struct(comp, L)
        L.append("// Everything one NPC holds. Record pools have the catalogue's max_count (forgetting is an engine law).")
        L.append("struct NpcState {")
        for comp in AGENT_COMPONENTS:
            L.append(f"  {camel(comp)} {comp};")
        for comp in sorted(records):
            cap = self.cat["component"][comp].max_count
            L.append(f"  RecordPool<{camel(comp)}, {cap}> {comp}_records;")
        L.append("};")
        L.append("")
        L.append("}  // namespace em::social::gen")
        L.append("")
        L.append("// RecordPool::add asks the law of forgetting (found by ADL on the record type).")
        L.append('#include "emergence/social/forgetting_gen.h"')
        return "\n".join(L) + "\n"

    def value_range(self, v) -> tuple:
        """Inclusive (min, max) of a stored value, from the catalogue: enum = its declared values, word = the symbol
        tables, tenths and per-mille from the charter scales."""
        if v.scale in SCALE_RANGE:
            return SCALE_RANGE[v.scale]
        if v.scale == "enum":
            n = len(v.values) or len([c for c in self.cat["concept"].values() if c.category == v.values_from])
            return 0, max(n, 1) - 1
        if v.scale == "word":
            return 0, max(len(self.orders.words), len(self.orders.kinds)) - 1
        if v.scale == "qty":
            return -QTY_BOUND, QTY_BOUND
        if v.scale == "time":
            return -TIME_BOUND, TIME_BOUND
        if v.scale in ("id", "mref", "list"):
            return 0, 0xFFFFFFFF
        return 0, 0   # proposition: checked as a tree

    def generate_fields(self) -> str:
        """Field descriptors for the save codec (T04): per component, the kind (struct name), the variable name (the
        catalogue id), the storage type, offsetof and sizeof. Same field order as the struct (sorted by id)."""
        L = ["// GENERATED by catalogue/tools/gen_cpp.py from catalogue/ - do not edit. Field descriptors of the NPC state",
             "// (kind, variable name, storage type, offsetof) read by NpcStateCodec: the save is by NAMES, never a raw copy.",
             "#pragma once", "#include <array>", "#include <cstddef>", "",
             '#include "emergence/social/field_desc.h"', '#include "emergence/social/npc_state_gen.h"', "",
             "namespace em::social::gen {", ""]
        records = sorted(c.id for c in self.cat["component"].values() if c.part_of and c.holder == "agent")
        for comp in list(AGENT_COMPONENTS) + records:
            fl = self.fields(comp)
            st = camel(comp)
            L.append(f"inline constexpr std::array<FieldDesc, {len(fl)}> k{st}Fields = {{{{")
            for v in fl:
                t = FIELD_TYPES[v.scale]
                n = ident(v.id)
                lo, hi = self.value_range(v)
                L.append(f'  {{"{v.id}", ColType::{COL_TYPES[t]}, offsetof({st}, {n}), sizeof({st}::{n}), {lo}ll, {hi}ll}},')
            L.append("}};")
            cap = self.cat["component"][comp].max_count if comp in records else 0
            L.append(f'inline constexpr ComponentDesc k{st}Desc{{"{comp}", {"true" if comp in records else "false"}, {cap or 0}, k{st}Fields}};')
            L.append("")
        L.append("// Visitors: f(const ComponentDesc&, Struct&) for the flat components, f(const ComponentDesc&, RecordPool&) for the pools.")
        L.append("template <class S, class F>")
        L.append("void visit_components(S& s, F&& f) {")
        for comp in AGENT_COMPONENTS:
            L.append(f"  f(k{camel(comp)}Desc, s.{comp});")
        L.append("}")
        L.append("template <class S, class F>")
        L.append("void visit_pools(S& s, F&& f) {")
        for comp in records:
            L.append(f"  f(k{camel(comp)}Desc, s.{comp}_records);")
        L.append("}")
        L.append("")
        L.append("}  // namespace em::social::gen")
        return "\n".join(L) + "\n"

    def generate_vocab(self) -> str:
        """kWords / kKinds follow catalogue/generated/vocab_registry.json (seeded from tok-2's order); a retired
        slot is "retired_N" so that no later word moves."""
        words, kinds = self.orders.words, self.orders.kinds
        L = ["// GENERATED by catalogue/tools/gen_cpp.py - the symbol tables of the inner language (proposition ids), in the stable",
             "// append-only order of vocab_registry.json (first seeded from ai/tok2/registry.json); retired slots are retired_N.",
             "#pragma once", "#include <array>", "#include <cstdint>", "#include <string_view>", "", "namespace em::social::gen {", ""]
        for tag, order in (("Words", words), ("Kinds", kinds)):
            L.append(f"inline constexpr std::array<std::string_view, {len(order)}> k{tag} = {{")
            names = [sl.name if sl.live else sl.cpp for sl in order.slots]
            L += ["  " + ", ".join(cpp_str(w) for w in names[i:i + 8]) + "," for i in range(0, len(names), 8)]
            L.append("};")
            L.append(f"inline constexpr std::uint64_t k{tag}RegistryFingerprint = 0x{order.fingerprint:016x}ull;")
        L.append("")
        L.append("}  // namespace em::social::gen")
        return "\n".join(L) + "\n"


class ForgettingGenerator:
    """gen::forgetting_score / forgetting_protected from data/forgetting.toml, integer arithmetic like the oracle
    (tools/forgetting.py). The parity helpers (SplitMix64, randomize) draw records exactly as the oracle does."""

    def __init__(self, cat: Catalogue):
        self.cat = cat
        self.oracle = forgetting.ForgettingOracle(cat)

    def cap(self, record: str) -> int:
        return self.cat["component"][record].max_count

    def generate(self) -> str:
        kinds = self.oracle.kinds
        for r in kinds:
            check_identifiers("forgetting record", [r])
        L = ["// GENERATED by catalogue/tools/gen_cpp.py from catalogue/data/forgetting.toml - do not edit (decision D31, T05).",
             "// The law of forgetting (docs/14 7.5): an integer score per record (the lowest is forgotten first, a tie forgets the",
             "// oldest) and the records that are never forgotten. It never reads the truth of the world (checked by tools/forgetting.py).",
             "#pragma once", "#include <algorithm>", "#include <array>", "#include <cstdint>", "#include <string_view>", "",
             '#include "emergence/social/npc_state_gen.h"', "", "namespace em::social::gen {", "",
             f"inline constexpr GameTime kSeasonSeconds = {forgetting.SEASON_SECONDS};   // D30: 1 h 45 real x 16 game seconds",
             "", "enum class RecordKind : std::uint8_t {"]
        L += [f"  {ident(r)}," for r in kinds] + ["  kCount", "};",
                f"inline constexpr std::array<std::string_view, {len(kinds)}> kRecordKindNames = {{",
                "  " + ", ".join(cpp_str(r) for r in kinds), "};",
                f"inline constexpr std::array<int, {len(kinds)}> kRecordCapacity = {{{', '.join(str(self.cap(r)) for r in kinds)}}};   // max_count",
                "",
                "// 100 for a brand-new event, halving at each half-life (linear in between), 0 after ten half-lives.",
                "constexpr std::int64_t forgetting_recency(std::int64_t age, std::int64_t half_life) {",
                "  if (age < 0) age = 0;",
                "  const std::int64_t whole = age / half_life, rest = age % half_life;",
                "  if (whole >= 10) return 0;",
                "  std::int64_t r = 1000 >> whole;",
                "  r -= r * rest / (2 * half_life);",
                "  return r / 10;",
                "}",
                "constexpr std::int32_t forgetting_clamp(std::int64_t x) {",
                "  return static_cast<std::int32_t>(std::clamp<std::int64_t>(x, INT32_MIN, INT32_MAX));",
                "}", ""]
        for r in kinds:
            law, T = self.oracle.laws[r], camel(r)
            L.append(f"inline constexpr RecordKind forgetting_kind(const {T}&) {{ return RecordKind::{ident(r)}; }}")
            L.append(f"// {r}: the Kind is checked by the record type; a mismatching Kind scores 0.")
            L.append(f"inline std::int32_t forgetting_score(RecordKind kind, const {T}& r, GameTime now) {{")
            L.append(f"  if (kind != RecordKind::{ident(r)}) return 0;")
            if not any(t.get("kind") == "recency" for t in law.terms):
                L.append("  (void)now;")
            L.append("  std::int64_t s = 0;")
            for t in law.terms:
                f = f"r.{ident(t['var'])}"
                w = t["weight"]
                if t.get("kind", "value") == "recency":
                    L.append(f"  s += {w} * forgetting_recency(now - {f}, {t['half_life_seasons']} * kSeasonSeconds);")
                elif "cap" in t:
                    L.append(f"  s += {w} * std::min<std::int64_t>({f}, {t['cap']});")
                else:
                    L.append(f"  s += {w} * static_cast<std::int64_t>({f});")
            L.append("  return forgetting_clamp(s);")
            L.append("}")
            cond = " || ".join(f"r.{ident(n)}" for n in law.protect) or "false"
            L.append(f"inline bool forgetting_protected(RecordKind kind, const {T}&{' r' if law.protect else ''}) {{")
            L.append(f"  return kind == RecordKind::{ident(r)} && ({cond});")
            L.append("}")
            L.append("")
        L += ["// ---- parity with tools/forgetting.py (tests): the same SplitMix64 draws, field by field ----",
              "struct SplitMix64 {",
              "  std::uint64_t s;",
              "  std::uint64_t next() {",
              "    s += 0x9E3779B97F4A7C15ull;",
              "    std::uint64_t z = s;",
              "    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;",
              "    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;",
              "    return z ^ (z >> 31);",
              "  }",
              "};",
              "constexpr std::int64_t forgetting_draw(std::uint64_t u, std::int64_t lo, std::int64_t hi) {",
              "  return lo + static_cast<std::int64_t>(u % static_cast<std::uint64_t>(hi - lo + 1));",
              "}",
              "constexpr GameTime forgetting_draw_time(std::uint64_t u, GameTime now) {",
              "  return u % 17 == 0 ? 0 : now + kSeasonSeconds - static_cast<GameTime>(u % (14 * static_cast<std::uint64_t>(kSeasonSeconds)));",
              "}", ""]
        for r in kinds:
            law, T = self.oracle.laws[r], camel(r)
            L.append(f"inline void forgetting_randomize({T}& r, SplitMix64& rng, GameTime now) {{")
            if not any(self.cat["variable"][n].scale == "time" for n in law.fields):
                L.append("  (void)now;")
            if not law.fields:
                L.append("  (void)r; (void)rng;")
            for n in law.fields:
                v = self.cat["variable"][n]
                ty = FIELD_TYPES[v.scale]
                if v.scale == "time":
                    val = "forgetting_draw_time(rng.next(), now)"
                elif v.scale == "bool":
                    val = "forgetting_draw(rng.next(), 0, 1) != 0"
                else:
                    lo, hi = forgetting.DRAW_RANGE[v.scale]
                    val = f"static_cast<{ty}>(forgetting_draw(rng.next(), {lo}, {hi}))"
                L.append(f"  r.{ident(n)} = {val};")
            L.append("}")
        L += ["", "}  // namespace em::social::gen"]
        return "\n".join(L) + "\n"

    def generate_parity(self) -> str:
        return ("// GENERATED by catalogue/tools/gen_cpp.py - hash of the Python oracle (tools/forgetting.py) over "
                f"{forgetting.PARITY_RECORDS} records.\n"
                f"inline constexpr int kParityRecords = {forgetting.PARITY_RECORDS};\n"
                f"inline constexpr unsigned long long kParityHash = 0x{self.oracle.parity_hash():016x}ull;\n"
                f"inline constexpr long long kParityNow = {forgetting.PARITY_NOW};\n"
                "inline constexpr unsigned long long kParitySeed = 0xE5CA1AB1Eull;\n")


def build(cat: Catalogue, orders: "Orders | None" = None) -> dict:
    """{path: text} of every generated file (nothing written)."""
    orders = orders or Orders(cat)
    sg = StateGenerator(cat, orders)
    fg = ForgettingGenerator(cat)
    return {OUT: CppGenerator(cat, orders).generate(), STATE_OUT: sg.generate_state(), FIELDS_OUT: sg.generate_fields(), VOCAB_OUT: sg.generate_vocab(),
            FORGETTING_OUT: fg.generate(), PARITY_OUT: fg.generate_parity(),
            VAR_REGISTRY: orders.var_registry.text(), VOCAB_REGISTRY: orders.vocab_registry.text()}


def main(argv=None) -> int:
    check = "--check" in (sys.argv[1:] if argv is None else argv)
    cat = Catalogue.load()
    problems = cat.validate() + forgetting.ForgettingChecker(cat).problems()
    if problems:
        sys.stderr.write("catalogue does not validate, nothing generated:\n" + "\n".join("  " + p for p in problems) + "\n")
        return 1
    try:
        files = build(cat)
    except RegistryStale as e:
        sys.stderr.write(f"a registry is stale, nothing generated: {e}\n")
        return 1
    if check:
        stale = [p.name for p, t in files.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        if stale:
            sys.stderr.write(f"stale: {', '.join(stale)} -> run python3 catalogue/tools/gen_cpp.py\n")
            return 1
        print("generated C++ tables up to date")
        return 0
    for p, t in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    print("écrit " + ", ".join(p.name for p in files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
