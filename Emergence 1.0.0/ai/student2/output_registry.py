"""output_registry.py - stable indices for the OUTPUT heads, append-only (the counterpart of tok-2's registry).

The weights of a head mean "index i = this gesture / this manner value / this variable". If the catalogue grows
(a new gesture, a new manner value, a new writable variable) and the indices were recomputed from sorted names, every
trained checkpoint would silently change meaning. So, like `ai/tok2/registry.json` does for the input, the output
indices are recorded once in `ai/student2/output_registry.json` and only ever APPENDED to:

  gestures, conditions, write_vars   name + signature (what its parameters mean): a changed signature is a CONFLICT,
                                     give the thing another name. One exception, a WIDENING: a pointer parameter that
                                     accepts MORE kinds of target (give an animal, take a plant, step 19a) keeps its
                                     index and its weights; only the feasibility mask grows. The signature is rewritten
                                     by --update, and an older checkpoint stays compatible (its signature is narrower).
  forms, enum_values, directions     names
  manner                             heads in order, each with its values in order and a fixed CAPACITY

Every list has a fixed capacity (`capacity`); the heads are sized by the capacity, the unused tail is masked ("reserve").
A catalogue that grows inside the capacity therefore keeps the shapes, so an older checkpoint still loads: its
registry must be a PREFIX of the current one (`compatible`), the new indices start from their initial weights.
Something the catalogue removes stays registered ("retired", masked, never reused). Growing past a capacity is a new
schema version (the shapes change).

    cd ai && python3 -m student2.output_registry            # what is missing
    cd ai && python3 -m student2.output_registry --update   # append the news (conflicts are errors)
    cd ai && python3 -m student2.output_registry --check    # exit 1 when stale
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tok2.interface import canonical_json, fnv1a64

SCHEMA = "student2-output-registry-1"
REGISTRY_PATH = Path(__file__).with_name("output_registry.json")
CAPACITY = {"gestures": 64, "conditions": 32, "write_vars": 128, "forms": 128, "enum_values": 128, "directions": 16,
            "manner_heads": 64}
MANNER_RESERVE = 4          # spare value slots given to a manner head when it is first registered
MANNER_MAX = 31             # values per head (+ the "none" level = 32 logits per head)
MANNER_FLAT = 640           # logits of the shared manner layer (sum of (capacity + 1) over the heads, plus room to grow)


class RegistryError(ValueError):
    """The registry is stale or in conflict with the catalogue (the message says the command)."""


class Needs:
    """What the current catalogue needs registered: ordered, with the signature that gives each item its meaning."""

    def __init__(self, spec, forms: list[str]):
        self.gestures = {}
        for gid in spec.gesture_ids:
            g = spec.gestures[gid]
            parts = []
            for p in g.params:
                if p.kind == "ref":
                    parts.append(f"ref:{p.name}:{int(p.optional)}:{'/'.join(sorted(p.accepts))}")
                elif p.kind == "enum":
                    parts.append(f"enum:{p.name}:{p.head}:{int(p.optional)}")
                else:
                    parts.append(f"{p.kind}:{p.name}")
            self.gestures[gid] = "|".join(parts)
        self.conditions = {c: ",".join(a) for c, a in sorted(spec.conditions.items())}
        self.write_vars = {v: f"{w.scale}|{w.mode}|{w.step}|{w.target_kind}|{int(w.creatable)}|{'/'.join(w.values)}"
                           for v, w in sorted(spec.writes.items())}
        self.forms = list(forms)
        self.directions = list(spec.directions)
        self.enum_values = []
        for w in spec.writes.values():
            for x in (("false", "true") if w.scale == "bool" else w.values if w.scale in ("enum", "word") else ()):
                if x not in self.enum_values:
                    self.enum_values.append(x)
        self.manner = {h: list(spec.manner_heads[h]["values"]) for h in sorted(spec.manner_heads)}


def widens(old: str, new: str) -> bool:
    """True when `new` is `old` with some pointer parameters accepting MORE targets (same names, order, optionality)."""
    po, pn = old.split("|"), new.split("|")
    if len(po) != len(pn):
        return False
    for a, b in zip(po, pn):
        if a == b:
            continue
        fa, fb = a.split(":"), b.split(":")
        if len(fa) != 4 or len(fb) != 4 or fa[0] != "ref" or fb[0] != "ref" or fa[:3] != fb[:3]:
            return False
        if not set(fa[3].split("/")) <= set(fb[3].split("/")):
            return False
    return True


class OutputRegistry:
    def __init__(self, data: dict | None = None):
        self.d = data or {"schema": SCHEMA, "capacity": dict(CAPACITY), "manner_reserve": MANNER_RESERVE,
                          "gestures": [], "conditions": [], "write_vars": [], "forms": [], "enum_values": [],
                          "directions": [], "manner": []}
        if self.d.get("schema") != SCHEMA:
            raise RegistryError(f"output registry schema {self.d.get('schema')!r}, expected {SCHEMA!r}")

    # ---- io
    @classmethod
    def load(cls, path: Path = REGISTRY_PATH) -> "OutputRegistry":
        return cls(json.loads(Path(path).read_text(encoding="utf-8"))) if Path(path).exists() else cls()

    def save(self, path: Path = REGISTRY_PATH) -> None:
        Path(path).write_text(json.dumps(self.d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self.d))

    # ---- access
    @property
    def capacity(self) -> dict:
        return self.d["capacity"]

    def names(self, kind: str) -> list[str]:
        return [e["name"] if isinstance(e, dict) else e for e in self.d[kind]]

    def index(self, kind: str) -> dict[str, int]:
        return {n: i for i, n in enumerate(self.names(kind))}

    def manner_heads(self) -> list[dict]:
        return self.d["manner"]

    @property
    def fingerprint(self) -> int:
        """Of what fixes the SHAPES (schema, capacities, the manner reserve): stable while the catalogue grows."""
        return fnv1a64(canonical_json({"schema": SCHEMA, "capacity": self.capacity, "manner_reserve": self.d["manner_reserve"],
                                       "manner_max": MANNER_MAX, "manner_flat": MANNER_FLAT,
                                       "manner_capacity": {h["name"]: h["capacity"] for h in self.d["manner"]}}))

    # ---- what is missing / in conflict
    def diff(self, need: Needs) -> tuple[list[str], list[str]]:
        add, bad = [], []
        for kind, want in (("gestures", need.gestures), ("conditions", need.conditions), ("write_vars", need.write_vars)):
            have = {e["name"]: e["sig"] for e in self.d[kind]}
            for n, sig in want.items():
                if n not in have:
                    add.append(f"{kind}: {n}")
                elif have[n] != sig:
                    if widens(have[n], sig):
                        add.append(f"{kind}: {n} widened")
                    else:
                        bad.append(f"{kind}: {n} changed meaning ({have[n]!r} -> {sig!r}): give it another name")
            if len(have) + sum(1 for n in want if n not in have) > self.capacity[kind]:
                bad.append(f"{kind}: more than the capacity {self.capacity[kind]} (a new schema version)")
        for kind, want in (("forms", need.forms), ("enum_values", need.enum_values), ("directions", need.directions)):
            have = set(self.d[kind])
            add += [f"{kind}: {n}" for n in want if n not in have]
            if len(have | set(want)) > self.capacity[kind]:
                bad.append(f"{kind}: more than the capacity {self.capacity[kind]} (a new schema version)")
        heads = {h["name"]: h for h in self.d["manner"]}
        for h, values in need.manner.items():
            if h not in heads:
                add.append(f"manner: {h}")
                if len(values) > MANNER_MAX:
                    bad.append(f"manner {h}: {len(values)} values > {MANNER_MAX}")
                continue
            for v in values:
                if v not in heads[h]["values"]:
                    add.append(f"manner {h}: {v}")
            if len(set(heads[h]["values"]) | set(values)) > heads[h]["capacity"]:
                bad.append(f"manner {h}: more values than its capacity {heads[h]['capacity']} (a new schema version)")
        if len(heads) + sum(1 for h in need.manner if h not in heads) > self.capacity["manner_heads"]:
            bad.append("manner: more heads than the capacity")
        total = sum(h["capacity"] + 1 for h in self.d["manner"]) + sum(
            min(MANNER_MAX, len(v) + self.d["manner_reserve"]) + 1 for h, v in need.manner.items() if h not in heads)
        if total > MANNER_FLAT:
            bad.append(f"manner: {total} logits > {MANNER_FLAT} (a new schema version)")
        return add, bad

    def require(self, need: Needs) -> None:
        add, bad = self.diff(need)
        if bad or add:
            raise RegistryError("; ".join(bad + add[:6]) + (f" (+{len(add) - 6} more)" if len(add) > 6 else "")
                                + ": run `cd ai && python3 -m student2.output_registry --update`")

    def updated(self, need: Needs) -> "OutputRegistry":
        add, bad = self.diff(need)
        if bad:
            raise RegistryError("; ".join(bad))
        new = OutputRegistry(self.to_dict())
        for kind, want in (("gestures", need.gestures), ("conditions", need.conditions), ("write_vars", need.write_vars)):
            have = set(new.names(kind))
            new.d[kind] += [{"name": n, "sig": s} for n, s in want.items() if n not in have]
            for e in new.d[kind]:                                  # a widened pointer mask: same index, wider signature
                if e["name"] in want and e["sig"] != want[e["name"]] and widens(e["sig"], want[e["name"]]):
                    e["sig"] = want[e["name"]]
        for kind, want in (("forms", need.forms), ("enum_values", need.enum_values), ("directions", need.directions)):
            new.d[kind] += [n for n in want if n not in set(new.d[kind])]
        heads = {h["name"]: h for h in new.d["manner"]}
        for h, values in need.manner.items():
            if h not in heads:
                entry = {"name": h, "values": [], "capacity": min(MANNER_MAX, len(values) + new.d["manner_reserve"])}
                new.d["manner"].append(entry)
                heads[h] = entry
            heads[h]["values"] += [v for v in values if v not in heads[h]["values"]]
        return new

    # ---- checkpoints
    def compatible(self, older: dict) -> list[str]:
        """Why a checkpoint made under `older` (a registry dict) cannot run under this one ([] = compatible):
        every list of the older registry must be a prefix of the current one, with equal signatures and capacities."""
        why = []
        if older.get("capacity") != self.capacity:
            why.append("capacities differ")
        for kind in ("gestures", "conditions", "write_vars", "forms", "enum_values", "directions"):
            a, b = older.get(kind, []), self.d[kind]
            same = len(b) >= len(a) and all(
                x == y or (isinstance(x, dict) and isinstance(y, dict) and x["name"] == y["name"] and widens(x["sig"], y["sig"]))
                for x, y in zip(a, b))
            if not same:
                why.append(f"{kind}: not an extension of the checkpoint's list")
        a, b = older.get("manner", []), self.d["manner"]
        for i, h in enumerate(a):
            if i >= len(b) or b[i]["name"] != h["name"] or b[i]["capacity"] != h["capacity"] or b[i]["values"][:len(h["values"])] != h["values"]:
                why.append(f"manner head {h['name']}: not an extension")
        return why


def main(argv=None) -> int:
    from teacher.toolkit import Toolkit
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    tk = Toolkit()
    need = Needs(tk.spec, sorted(tk.cat["form"]))
    reg = OutputRegistry.load()
    add, bad = reg.diff(need)
    if a.update:
        reg.updated(need).save()
        print(f"output registry updated: {len(add)} appended")
        return 0
    print("\n".join(bad + add) if (add or bad) else "output registry up to date")
    return 1 if (add or bad) and a.check else 0


if __name__ == "__main__":
    sys.exit(main())
