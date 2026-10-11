"""registry.py - stable identifiers: type ids, symbol ids and field columns, APPEND-ONLY (registry.json).

The weights of a trained model are tied to these numbers. They must not move when the catalogue grows:
  python3 -m tok2.registry            (from ai/)  what the interface needs that the registry does not have yet
  python3 -m tok2.registry --update               append the news at the END; never reorder, never reuse; whatever
                                                  the interface no longer has stays reserved (marked retired)
  python3 -m tok2.registry --check                exit 1 when the registry is not up to date (CI)
A new type gets the next id, a new field the next free columns of its type's block, a new symbol the next id. A
field whose block, width or codec changed is a conflict no update can solve: give it a new name. The widths of the
blocks are the maximum used by any type (retired fields included: their columns stay reserved).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .codecs import make_codec
from .errors import TokenError
from .interface import InputVocabulary, ModelInterface

REGISTRY_PATH = Path(__file__).with_name("registry.json")
SCHEMA = "tok2-registry-1"
BLOCKS = ("num", "cat", "ptr", "prop")


@dataclass
class FieldEntry:
    block: str
    col: int
    width: int
    codec: str
    retired: bool = False

    def shape(self) -> tuple:
        return (self.block, self.width, self.codec)

    def to_dict(self) -> dict:
        d = {"block": self.block, "col": self.col, "width": self.width, "codec": self.codec}
        if self.retired:
            d["retired"] = True
        return d


@dataclass
class TypeEntry:
    id: int
    fields: dict[str, FieldEntry] = field(default_factory=dict)
    retired: bool = False

    def end(self, block: str) -> int:
        return max((f.col + f.width for f in self.fields.values() if f.block == block), default=0)

    def to_dict(self) -> dict:
        d = {"id": self.id, "fields": {n: f.to_dict() for n, f in self.fields.items()}}
        if self.retired:
            d["retired"] = True
        return d


class Needs:
    """What an interface needs from the registry: its types, their fields' shapes, and its symbols."""

    def __init__(self, interface: ModelInterface):
        self.types: dict[str, dict[str, tuple]] = {}
        for tname, spec in interface.token_types.items():
            fields = {}
            for fname in sorted(spec["fields"]):
                c = make_codec(fname, spec["fields"][fname], f"{tname}.{fname}")
                fields[fname] = (c.block, c.width, c.kind)
            if sum(1 for s in fields.values() if s[0] == "prop") > 1:
                raise TokenError(f"{tname}: more than one proposition field")
            self.types[tname] = fields
        self.symbols: list[str] = InputVocabulary.required(interface)


class Registry:
    def __init__(self, types: dict[str, TypeEntry] | None = None, symbols: list[str] | None = None):
        self.types: dict[str, TypeEntry] = types or {}
        self.symbols: list[str] = symbols or []

    # ---- files ------------------------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path = REGISTRY_PATH) -> "Registry":
        p = Path(path)
        if not p.exists():
            raise TokenError(f"{p} is missing: create it with `python3 -m tok2.registry --update` (from ai/)")
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise TokenError(f"{p}: schema {data.get('schema')!r}, expected {SCHEMA!r}")
        types = {n: TypeEntry(t["id"], {f: FieldEntry(e["block"], e["col"], e["width"], e["codec"], e.get("retired", False))
                                        for f, e in t["fields"].items()}, t.get("retired", False))
                 for n, t in data["types"].items()}
        return cls(types, list(data["symbols"]))

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "types": {n: t.to_dict() for n, t in self.types.items()}, "symbols": self.symbols}

    def save(self, path: Path = REGISTRY_PATH) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- what differs from an interface ------------------------------------------------------------
    def diff(self, interface: ModelInterface) -> tuple[list[str], list[str]]:
        """(additions an update can make, conflicts it cannot)."""
        need = Needs(interface)
        add, conflicts = [], []
        for tname, fields in need.types.items():
            t = self.types.get(tname)
            if t is None:
                add.append(f"new type {tname}")
                continue
            for fname, shape in fields.items():
                e = t.fields.get(fname)
                if e is None:
                    add.append(f"new field {tname}.{fname}")
                elif e.shape() != shape:
                    conflicts.append(f"{tname}.{fname}: registered as {e.shape()}, the interface now needs {shape} "
                                     f"(rename the field: a column never changes meaning)")
                elif e.retired:
                    add.append(f"field {tname}.{fname} is back")
            if t.retired:
                add.append(f"type {tname} is back")
        known = set(self.symbols)
        new_symbols = [s for s in need.symbols if s not in known]
        if new_symbols:
            add.append(f"{len(new_symbols)} new symbols: {', '.join(new_symbols[:6])}{'...' if len(new_symbols) > 6 else ''}")
        return add, conflicts

    def require(self, interface: ModelInterface) -> None:
        add, conflicts = self.diff(interface)
        if conflicts:
            raise TokenError("the interface conflicts with the tok-2 registry: " + "; ".join(conflicts))
        if add:
            raise TokenError("the interface has elements the tok-2 registry does not know (" + "; ".join(add[:5])
                             + ("; ..." if len(add) > 5 else "") + "): run `python3 -m tok2.registry --update` from ai/")

    def updated(self, interface: ModelInterface) -> "Registry":
        """A new registry with the news appended at the end. Nothing already registered moves."""
        need = Needs(interface)
        add, conflicts = self.diff(interface)
        if conflicts:
            raise TokenError("; ".join(conflicts))
        types = {n: TypeEntry(t.id, {f: FieldEntry(**vars(e)) for f, e in t.fields.items()}, t.retired)
                 for n, t in self.types.items()}
        next_id = max((t.id for t in types.values()), default=0) + 1
        for tname, fields in need.types.items():
            t = types.get(tname)
            if t is None:
                t = types[tname] = TypeEntry(next_id)
                next_id += 1
            t.retired = False
            for fname, (block, width, codec) in fields.items():
                e = t.fields.get(fname)
                if e is None:
                    t.fields[fname] = FieldEntry(block, t.end(block), width, codec)
                else:
                    e.retired = False
        for tname, t in types.items():
            for fname, e in t.fields.items():
                if tname not in need.types or fname not in need.types[tname]:
                    e.retired = True
            if tname not in need.types:
                t.retired = True
        known = set(self.symbols)
        symbols = list(self.symbols) + [s for s in need.symbols if s not in known]
        if not self.symbols:
            symbols = need.symbols
        if len(set(symbols)) != len(symbols):
            raise TokenError("duplicate symbols in the registry")
        return Registry(types, symbols)

    # ---- what the layout reads -------------------------------------------------------------------
    def widths(self) -> dict[str, int]:
        """Block widths: the maximum end of any column of any type (retired columns stay reserved)."""
        return {b: max((t.end(b) for t in self.types.values()), default=0) for b in BLOCKS}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    iface = ModelInterface()
    reg = Registry.load() if REGISTRY_PATH.exists() else Registry()
    add, conflicts = reg.diff(iface)
    for line in conflicts:
        print("CONFLIT :", line)
    for line in add:
        print("à ajouter :", line)
    if conflicts:
        return 1
    if "--update" in args:
        if add or not REGISTRY_PATH.exists():
            new = reg.updated(iface)
            new.save()
            print(f"écrit {REGISTRY_PATH}: {len(new.types)} types, {len(new.symbols)} symboles, "
                  f"largeurs {new.widths()}")
        else:
            print("registre déjà à jour")
        return 0
    if not add:
        print("registre à jour")
    return 1 if add and "--check" in args else 0


if __name__ == "__main__":
    sys.exit(main())
