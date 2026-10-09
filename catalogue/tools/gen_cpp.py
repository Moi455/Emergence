"""gen_cpp.py - generate the C++ tables of the social engine from the catalogue (decision D31: one source of truth).

    python3 catalogue/tools/gen_cpp.py      # writes engine/social/generated/emergence/social/catalogue_gen.h

Gestures with their parameters (value lists, D10 intimate and minor-whitelist masks), conditions, and variables
with their governor bounds in TENTHS (the engine stores tenths of the charter scale). A fingerprint of the
model interface is embedded so the engine can refuse a model trained on another catalogue.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import model_interface  # noqa: E402
from governor import ADULT_AGE, tenths  # noqa: E402

OUT = ROOT.parent / "engine" / "social" / "generated" / "emergence" / "social" / "catalogue_gen.h"
WRITER_BITS = {"engine": 1, "T_jump": 2, "T_step": 4, "T_slow": 8, "birth": 16, "action": 32, "derived": 64}
SCALES = ("bipolar10", "unipolar10", "qty", "ratio", "enum", "id", "mref", "word", "bool", "list", "proposition", "time")
FAMILIES = ("move", "posture", "grasp", "force", "tool", "transform", "consume", "care", "perceive", "communicate", "meta")
PARAM_TYPES = ("ref", "enum", "qty", "duration", "condition", "expression", "bool")
MAX_PARAMS, MAX_VALUES = 6, 12


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


def cpp_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class CppGenerator:
    def __init__(self, cat: Catalogue):
        self.cat = cat
        self.L: list[str] = []

    def emit(self, line: str = ""):
        self.L.append(line)

    def enum(self, name: str, base: str, ids: list[str]):
        self.emit(f"enum class {name} : {base} {{")
        for i in ids:
            self.emit(f"  {ident(i)},")
        self.emit("  kCount")
        self.emit("};")
        self.emit(f"inline constexpr std::array<std::string_view, {len(ids)}> k{name}Names = {{")
        self.emit("  " + ", ".join(cpp_str(i) for i in ids))
        self.emit("};")
        self.emit()

    def gestures(self):
        acts = list(self.cat["action"].values())
        self.enum("Gesture", "std::uint8_t", [a.id for a in acts])
        self.emit("inline constexpr std::array<GestureSpec, %d> kGestures = {{" % len(acts))
        for a in acts:
            if len(a.params) > MAX_PARAMS:
                raise SystemExit(f"{a.id}: more than {MAX_PARAMS} params")
            ps = []
            for p in a.params:
                if len(p.values) > MAX_VALUES:
                    raise SystemExit(f"{a.id}.{p.name}: more than {MAX_VALUES} values")
                imask = sum(1 << i for i, v in enumerate(p.values) if v in p.intimate_values)
                allowed = a.minor_whitelist.get(p.name)
                mmask = (1 << len(p.values)) - 1 if allowed is None else sum(1 << i for i, v in enumerate(p.values) if v in allowed)
                vals = ", ".join(cpp_str(v) for v in p.values)
                ps.append(f"ParamSpec{{{cpp_str(p.name)}, ParamType::{ident(p.type)}, {len(p.values)}, {{{vals}}}, "
                          f"0x{imask:x}, 0x{mmask:x}, {str(p.ordinal).lower()}, {str(p.optional).lower()}, "
                          f"{str(p.name in a.party_params).lower()}, {str(p.name in a.minor_whitelist).lower()}}}")
            fam = FAMILIES.index(a.family)
            self.emit(f"  GestureSpec{{{cpp_str(a.id)}, Family::{ident(a.family)}, {str(bool(a.contact)).lower()}, "
                      f"{str(a.minor_person_ok).lower()}, {len(ps)}, {{")
            for x in ps:
                self.emit(f"    {x},")
            self.emit("  }},")
            del fam
        self.emit("}};")
        self.emit()

    def conditions(self):
        ids = sorted(c.id for c in self.cat["concept"].values() if c.category == "condition")
        self.enum("Condition", "std::uint8_t", ids)

    def variables(self):
        vs = sorted(self.cat["variable"].values(), key=lambda v: v.id)
        self.enum("Var", "std::uint16_t", [v.id for v in vs])
        self.emit("inline constexpr std::array<VariableSpec, %d> kVariables = {{" % len(vs))
        for v in vs:
            comp = self.cat["component"].get(v.holder)
            engine_only = bool(comp is not None and comp.engine_only)
            bits = sum(WRITER_BITS[w] for w in v.writer)
            self.emit(f"  VariableSpec{{{cpp_str(v.id)}, {cpp_str(v.holder)}, Scale::{ident(v.scale)}, 0x{bits:02x}, "
                      f"{tenths(v.step)}, {tenths(v.rate)}, {tenths(v.slow_rate)}, {str(bool(v.intimate)).lower()}, "
                      f"{str(engine_only).lower()}}},")
        self.emit("}};")
        self.emit()

    def generate(self) -> str:
        fp = fnv1a64(model_interface.ModelInterface(self.cat).text())
        self.emit("// GENERATED by catalogue/tools/gen_cpp.py from catalogue/ - do not edit (decision D31).")
        self.emit("#pragma once")
        self.emit("#include <array>\n#include <cstdint>\n#include <string_view>\n")
        self.emit("namespace em::social::gen {\n")
        self.emit(f"inline constexpr std::uint64_t kCatalogueFingerprint = 0x{fp:016x}ull;  // of model_interface.json")
        self.emit(f"inline constexpr int kMaxParams = {MAX_PARAMS};\ninline constexpr int kMaxValues = {MAX_VALUES};")
        self.emit(f"inline constexpr int kAdultAgeYears = {int(ADULT_AGE)};   // D10, read from life_stage\n")
        self.emit("enum class Scale : std::uint8_t { " + ", ".join(ident(x) for x in SCALES) + " };")
        self.emit("enum class Family : std::uint8_t { " + ", ".join(ident(x) for x in FAMILIES) + " };")
        self.emit("enum class ParamType : std::uint8_t { " + ", ".join(ident(x) for x in PARAM_TYPES) + " };")
        self.emit("namespace writer { " + " ".join(f"inline constexpr std::uint8_t {k} = 0x{b:02x};" for k, b in WRITER_BITS.items()) + " }\n")
        self.emit("struct ParamSpec {\n  std::string_view name;\n  ParamType type;\n  std::uint8_t n_values;\n"
                  "  std::array<std::string_view, kMaxValues> values;\n  std::uint16_t intimate_mask;   // D10: refused with a minor\n"
                  "  std::uint16_t minor_mask;      // D10: values allowed when a minor is involved\n  bool ordinal;\n  bool optional;\n"
                  "  bool party;                    // D10: may designate a person involved\n"
                  "  bool whitelisted;              // D10: REQUIRED and checked against minor_mask when a minor is involved\n};\n")
        self.emit("struct GestureSpec {\n  std::string_view id;\n  Family family;\n  bool contact;\n  bool minor_person_ok;   // D10\n  std::uint8_t n_params;\n"
                  "  std::array<ParamSpec, kMaxParams> params;\n};\n")
        self.emit("struct VariableSpec {\n  std::string_view id;\n  std::string_view holder;\n  Scale scale;\n  std::uint8_t writers;\n"
                  "  std::int16_t step_tenths;      // per decision\n  std::int16_t rate_tenths;      // per game day (T_step)\n"
                  "  std::int16_t slow_tenths;      // per life-year (T_slow)\n  bool intimate;\n  bool engine_only;\n};\n")
        self.gestures()
        self.conditions()
        self.variables()
        self.emit("}  // namespace em::social::gen")
        return "\n".join(self.L) + "\n"


def main():
    text = CppGenerator(Catalogue.load()).generate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"écrit {OUT} ({len(text.splitlines())} lignes)")


if __name__ == "__main__":
    main()
