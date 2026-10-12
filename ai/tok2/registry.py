"""registry.py - stable identifiers: type ids, symbol ids and field columns, APPEND-ONLY (registry.json).

The weights of a trained model are tied to these numbers. They must not move when the catalogue grows:
  python3 -m tok2.registry            (from ai/)  what the interface needs that the registry does not have yet
  python3 -m tok2.registry --update               append the news at the END; never reorder, never reuse; whatever
                                                  the interface no longer has stays reserved (marked retired)
  python3 -m tok2.registry --check                exit 1 when the registry is not up to date (CI)
A new type gets the next id, a new field the next free columns of its type's block, a new symbol the next id.
Every field records its meaning (scale, unit, list_of) and a vector its components (name, scale, unit, column):
  - a change of meaning (scale, unit, block, codec, a component's scale or unit, the ORDER of the components) is a
    CONFLICT no update can solve: give the field a new name;
  - a vector grows only by appending: a new component takes the next free column of the type's block (so the
    columns of a vector are not always contiguous), the old ones never move;
  - how held objects are pooled (sum for the masses, max for the rest) is PINNED per component: the registry decides,
    a later change of codecs.SUM_COMPONENTS only seeds NEW components, and a pinned sum-pooled component that disappears (a rename of `mass`) is a conflict unless another
    component takes over the sum (add its name to codecs.SUM_COMPONENTS before the update);
  - a component the interface no longer has stays reserved (retired); a RENAMED component is a retired one plus
    a new one (the old column is never reused, so a model trained on it is never misread).
The widths of the blocks are the maximum used by any type (retired columns included). The registry is checked when
it is loaded (unique ids, no overlapping columns, widths consistent).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .codecs import VectorCodec, default_pool, make_codec
from .errors import TokenError, clip, listing, short
from .interface import InputVocabulary, ModelInterface

REGISTRY_PATH = Path(__file__).with_name("registry.json")
SCHEMA = "tok2-registry-2"
LEGACY_SCHEMA = "tok2-registry-1"             # no recorded meaning, no widths: read, completed by the next --update
BLOCKS = ("num", "cat", "ptr", "prop")


@dataclass
class ComponentEntry:
    name: str
    col: int
    scale: str
    unit: str = ""
    retired: bool = False
    pool: str | None = None                   # "sum" or "max": how held objects are pooled; None = not recorded yet
    rank: int | None = None                   # position in the interface's declared order at the last update

    def to_dict(self) -> dict:
        d = {"name": self.name, "col": self.col, "scale": self.scale, "unit": self.unit}
        if self.pool is not None:
            d["pool"] = self.pool
        if self.rank is not None:
            d["rank"] = self.rank
        if self.retired:
            d["retired"] = True
        return d


@dataclass
class FieldEntry:
    block: str
    col: int                                  # first column (for a vector: the column of its first component)
    width: int                                # columns used (for a vector: number of components, retired included)
    codec: str
    scale: str = ""
    unit: str = ""
    list_of: str = ""
    components: list[ComponentEntry] | None = None
    retired: bool = False

    def columns(self) -> list[int]:
        return [c.col for c in self.components] if self.components is not None else list(range(self.col, self.col + self.width))

    def end(self) -> int:
        cols = self.columns()
        return max(cols) + 1 if cols else self.col

    def to_dict(self) -> dict:
        d = {"block": self.block, "col": self.col, "width": self.width, "codec": self.codec, "scale": self.scale,
             "unit": self.unit, "list_of": self.list_of}
        if self.components is not None:
            d["components"] = [c.to_dict() for c in self.components]
        if self.retired:
            d["retired"] = True
        return d


@dataclass
class TypeEntry:
    id: int
    fields: dict[str, FieldEntry] = field(default_factory=dict)
    retired: bool = False

    def end(self, block: str) -> int:
        return max((f.end() for f in self.fields.values() if f.block == block), default=0)

    def to_dict(self) -> dict:
        d = {"id": self.id, "fields": {n: f.to_dict() for n, f in self.fields.items()}}
        if self.retired:
            d["retired"] = True
        return d


@dataclass
class FieldNeed:
    """What the interface needs of one field."""
    block: str
    width: int
    codec: str
    scale: str
    unit: str
    list_of: str
    components: list[tuple[str, str, str]] | None = None      # (name, scale, unit) in the interface's order


class Needs:
    """What an interface needs from the registry: its types, their fields, and its symbols."""

    def __init__(self, interface: ModelInterface):
        self.types: dict[str, dict[str, FieldNeed]] = {}
        for tname, spec in interface.token_types.items():
            fields = {}
            for fname in sorted(spec["fields"]):
                fs = spec["fields"][fname]
                c = make_codec(fname, fs, f"{tname}.{fname}")
                comps = list(zip(c.components, c.scales, c.units)) if isinstance(c, VectorCodec) else None
                fields[fname] = FieldNeed(c.block, c.width, c.kind, fs.get("scale", ""), fs.get("unit", ""),
                                          fs.get("list_of", ""), comps)
            if sum(1 for s in fields.values() if s.block == "prop") > 1:
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
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("schema") not in (SCHEMA, LEGACY_SCHEMA):
                raise TokenError(f"{p}: schema {short(data.get('schema'))}, expected {SCHEMA!r}: run "
                                 f"`python3 -m tok2.registry --update` after checking the old ids are kept")
            types = {}
            for n, t in data["types"].items():
                fields = {}
                for f, e in t["fields"].items():
                    comps = None if "components" not in e else [
                        ComponentEntry(c["name"], c["col"], c["scale"], c.get("unit", ""), c.get("retired", False), c.get("pool"),
                                       c.get("rank"))
                        for c in e["components"]]
                    fields[f] = FieldEntry(e["block"], e["col"], e["width"], e["codec"], e.get("scale", ""),
                                           e.get("unit", ""), e.get("list_of", ""), comps, e.get("retired", False))
                types[n] = TypeEntry(t["id"], fields, t.get("retired", False))
            reg = cls(types, list(data["symbols"]))
            declared = data.get("widths")
            if declared is None and data["schema"] == SCHEMA:
                raise TokenError(f"{p}: `widths` is mandatory in {SCHEMA}")
            reg.validate(declared)
        except TokenError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError) as e:
            raise TokenError(f"{p}: malformed ({type(e).__name__}: {short(e, 120)})") from None
        return reg

    def validate(self, declared_widths: dict | None = None) -> None:
        """Integrity of the file itself (a hand edit, a bad merge): unique ids, no overlapping columns, unique
        symbols, every column inside the declared width of its block."""
        def integer(x) -> bool:
            return isinstance(x, int) and not isinstance(x, bool)

        ids = [t.id for t in self.types.values()]
        if any(not integer(i) or i < 1 or i > 255 for i in ids) or len(set(ids)) != len(ids):
            raise TokenError("registry: type ids must be unique integers in 1..255")
        if not all(isinstance(s, str) for s in self.symbols):
            raise TokenError("registry: symbols must be strings")
        if len(set(self.symbols)) != len(self.symbols):
            dup = sorted({s for s in self.symbols if self.symbols.count(s) > 1})
            raise TokenError(f"registry: duplicate symbols {dup[:5]}")
        for tname, t in self.types.items():
            for fname, f in t.fields.items():
                if f.block not in BLOCKS:
                    raise TokenError(f"registry: {tname}.{fname}: unknown block {f.block!r}")
                if not integer(f.col) or not integer(f.width) or f.col < 0 or f.width < 1:
                    raise TokenError(f"registry: {tname}.{fname}: col and width must be integers (col >= 0, width >= 1)")
                if not all(isinstance(x, str) for x in (f.codec, f.scale, f.unit, f.list_of)):
                    raise TokenError(f"registry: {tname}.{fname}: codec, scale, unit and list_of must be strings")
                if f.components is not None:
                    if len({c.name for c in f.components}) != len(f.components):
                        raise TokenError(f"registry: {tname}.{fname}: duplicate component names")
                    if any(not integer(c.col) or c.col < 0 or not isinstance(c.name, str) for c in f.components):
                        raise TokenError(f"registry: {tname}.{fname}: component columns must be integers >= 0")
                    if f.width != len(f.components):
                        raise TokenError(f"registry: {tname}.{fname}: width {f.width} != {len(f.components)} components")
                    if any(c.pool not in (None, "sum", "max") for c in f.components):
                        raise TokenError(f"registry: {tname}.{fname}: pool must be sum or max")
        if declared_widths is not None and (not isinstance(declared_widths, dict) or not all(
                integer(v) for v in declared_widths.values())):
            raise TokenError("registry: widths must be a dict of integers")
        widths = self.widths()
        if declared_widths is not None and declared_widths != widths:
            raise TokenError(f"registry: declared widths {declared_widths} differ from the columns' {widths}")
        for tname, t in self.types.items():
            for block in BLOCKS:
                if block == "prop":
                    continue                    # one proposition per row, always at column 0 (retired ones are not read)
                seen: dict[int, str] = {}
                for fname, f in t.fields.items():
                    if f.block != block:
                        continue
                    for c in f.columns():
                        if c < 0 or c >= widths[block]:
                            raise TokenError(f"registry: {tname}.{fname} column {c} is outside the {block} width {widths[block]}")
                        if c in seen:
                            raise TokenError(
                                f"registry: {tname} {block} column {c} is used by both {seen[c]} and {fname}. This is "
                                "what a merge of two branches that each added a field to the same type produces. Repair: "
                                f"renumber the MOST RECENT of the two columns by hand in registry.json (to the first free "
                                f"{block} column of {tname}, then fix `widths`), and ONLY if no model has been trained "
                                "on it; otherwise rename the newer field in the catalogue so it gets a fresh column")
                        seen[c] = fname

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "widths": self.widths(), "types": {n: t.to_dict() for n, t in self.types.items()},
                "symbols": self.symbols}

    def save(self, path: Path = REGISTRY_PATH) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- what differs from an interface ------------------------------------------------------------
    @staticmethod
    def _vector_changes(e: FieldEntry, need: FieldNeed):
        """(new components, components to retire, retired ones back, pooling not recorded, conflicts)."""
        reg = {c.name: c for c in e.components}
        want = [c[0] for c in need.components]
        conflicts, new, back, unpinned = [], [], [], []
        for name, scale, unit in need.components:
            c = reg.get(name)
            if c is None:
                new.append((name, scale, unit))
                continue
            if (c.scale, c.unit) != (scale, unit):
                conflicts.append(f"component {clip(name, 30)}: registered as ({c.scale}, {c.unit!r}), now ({scale}, {unit!r}); "
                                 "rename the COMPONENT (it gets a new column, the old one stays reserved)")
            elif c.retired:
                back.append(name)
            if c.pool is None or c.rank is None:
                unpinned.append(name)
        # the declared order of the components already registered must not change; a component added in the middle
        # of the interface's list is fine (it is appended to the registry, and the declared order is re-recorded)
        # (retired components are left out: one that comes back takes its old column and is ranked afresh)
        by_rank = sorted((c for c in e.components if c.name in set(want) and not c.retired),
                         key=lambda c: (c.rank if c.rank is not None else len(e.components) + 1, e.components.index(c)))
        known_in_order = [c.name for c in by_rank]
        wanted_known = [n for n in want if n in reg and not reg[n].retired]
        if known_in_order != wanted_known:
            conflicts.append("the registered components are reordered or swapped (their declared order must not change; "
                             "a NEW component may be declared anywhere, it is appended in the registry): put them back "
                             "in their registered order, or rename the moved COMPONENT (a new column)")
        retire = [c.name for c in e.components if c.name not in set(want) and not c.retired]
        lost_sum = [c.name for c in e.components if c.pool == "sum" and not c.retired and c.name not in set(want)]
        if lost_sum:
            still = any((reg[n].pool if n in reg and reg[n].pool else default_pool(n)) == "sum" for n in want)
            if not still:
                conflicts.append(f"the sum-pooled component {', '.join(map(str, lost_sum))} disappears and no component takes "
                                 "over the sum: a rename of a mass would silently change how held objects are pooled; "
                                 "add the new name to codecs.SUM_COMPONENTS before updating the registry")
        return new, retire, back, unpinned, conflicts

    def diff(self, interface: ModelInterface) -> tuple[list[str], list[str]]:
        """(additions an update can make, conflicts it cannot)."""
        need = Needs(interface)
        add, conflicts = [], []
        for tname, fields in need.types.items():
            t = self.types.get(tname)
            if t is None:
                add.append(f"new type {tname}")
                continue
            for fname, n in fields.items():
                e = t.fields.get(fname)
                where = f"{tname}.{fname}"
                if e is None:
                    add.append(f"new field {where}")
                    continue
                bad = []
                if (e.block, e.codec) != (n.block, n.codec):
                    bad.append(f"registered as {e.block}/{e.codec}, now {n.block}/{n.codec}")
                legacy = e.scale == ""                      # registered before the meaning was recorded
                if not legacy and (e.scale, e.unit, e.list_of) != (n.scale, n.unit, n.list_of):
                    bad.append(f"meaning changed: ({e.scale}, {e.unit!r}, {e.list_of!r}) -> ({n.scale}, {n.unit!r}, {n.list_of!r})")
                if n.components is None and e.width != n.width:
                    bad.append(f"width {e.width} -> {n.width}")
                comp_conflicts = []
                if n.components is not None:
                    if e.components is None:
                        if not legacy or e.width != len(n.components):
                            bad.append("registered without components or with another width")
                    else:
                        new, retire, back, unpinned, comp_conflicts = self._vector_changes(e, n)
                        if not comp_conflicts:
                            if new:
                                add.append(f"{where}: {len(new)} new components ({listing([c[0] for c in new[:4]], 80)})")
                            if retire:
                                add.append(f"{where}: components retired ({listing(retire[:4], 80)})")
                            if back:
                                add.append(f"{where}: components back ({listing(back[:4], 80)})")
                            if unpinned:
                                add.append(f"{where}: pooling and order of {len(unpinned)} components not recorded yet")
                if comp_conflicts:
                    conflicts.append(f"{where}: " + "; ".join(comp_conflicts))
                if bad:
                    conflicts.append(f"{where}: " + "; ".join(bad) + " (rename the field: a column never changes meaning)")
                elif not comp_conflicts:
                    if e.retired:
                        add.append(f"field {where} is back")
                    elif e.scale == "" and n.scale:
                        add.append(f"{where}: meaning not recorded yet")
            for fname, e in t.fields.items():
                if fname not in fields and not e.retired:
                    add.append(f"field {tname}.{fname} retired (the interface no longer has it)")
            if t.retired:
                add.append(f"type {tname} is back")
        for tname, t in self.types.items():
            if tname not in need.types and not t.retired:
                add.append(f"type {tname} retired (the interface no longer has it)")
        known = set(self.symbols)
        new_symbols = [s for s in need.symbols if s not in known]
        if new_symbols:
            add.append(f"{len(new_symbols)} new symbols: {listing(new_symbols[:6], 100)}")
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
        types = {n: TypeEntry(t.id, {f: FieldEntry(
            e.block, e.col, e.width, e.codec, e.scale, e.unit, e.list_of,
            None if e.components is None else [ComponentEntry(**vars(c)) for c in e.components], e.retired)
            for f, e in t.fields.items()}, t.retired) for n, t in self.types.items()}
        next_id = max((t.id for t in types.values()), default=0) + 1
        for tname, fields in need.types.items():
            t = types.get(tname)
            if t is None:
                t = types[tname] = TypeEntry(next_id)
                next_id += 1
            t.retired = False
            for fname, n in fields.items():
                e = t.fields.get(fname)
                if e is None:
                    start = 0 if n.block == "prop" else t.end(n.block)        # a proposition is always at column 0
                    e = t.fields[fname] = FieldEntry(n.block, start, n.width, n.codec, n.scale, n.unit, n.list_of)
                    if n.components is not None:
                        e.components = [ComponentEntry(c, start + i, s, u, False, default_pool(c), i)
                                        for i, (c, s, u) in enumerate(n.components)]
                    continue
                e.retired = False
                e.scale, e.unit, e.list_of = e.scale or n.scale, e.unit or n.unit, e.list_of or n.list_of
                if n.components is not None:
                    if e.components is None:          # registered before components were recorded: same order, same width
                        e.components = [ComponentEntry(c, e.col + i, s, u, False, default_pool(c), i)
                                        for i, (c, s, u) in enumerate(n.components)]
                    want = {c[0] for c in n.components}
                    reg = {c.name: c for c in e.components}
                    for name, scale, unit in n.components:
                        if name not in reg:
                            e.components.append(ComponentEntry(name, t.end(n.block), scale, unit, False, default_pool(name), len(e.components)))
                        else:
                            reg[name].retired = False
                    order = {name: k for k, (name, _, _) in enumerate(n.components)}
                    for c in e.components:
                        if c.pool is None:
                            c.pool = default_pool(c.name)
                        if c.name not in want:
                            c.retired = True
                            c.rank = None                 # a retired component takes no part in the ordering
                        else:
                            c.rank = order[c.name]
                    e.width = len(e.components)
                    e.col = e.components[0].col
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
        reg = Registry(types, symbols)
        reg.validate()
        return reg

    # ---- what the layout reads -------------------------------------------------------------------
    def widths(self) -> dict[str, int]:
        """Block widths: the maximum end of any column of any type (retired columns stay reserved)."""
        return {b: max((t.end(b) for t in self.types.values()), default=0) for b in BLOCKS}


FLAGS = {"--update", "--check"}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    unknown = [a for a in args if a not in FLAGS]
    if unknown:
        print(f"option inconnue : {', '.join(unknown)} (options : {', '.join(sorted(FLAGS))})", file=sys.stderr)
        return 2
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
