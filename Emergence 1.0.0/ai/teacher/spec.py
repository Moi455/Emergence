"""spec.py - what the teacher may answer: gestures with parameters, writable variables, conditions.

Read from catalogue/generated/model_interface.json ("output"), the contract of the Transformer's output heads. The
schema (instructions + JSON schema + grammar) and the validator are both built on these objects, so they cannot
disagree.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from tok2.interface import INTERFACE_PATH

# how a write names its target, from the "target" text of model_interface.json
TARGET_KINDS = (("self", "self"), ("ENTITY", "entity"), ("BELIEF", "belief"), ("GOAL", "goal"),
                ("MEMORY", "memory"), ("the current PLAN", "plan"))
# key prefixes that designate a record of each target kind
KEY_PREFIX = {"entity": ("@E", "@G"), "belief": ("b:", "h:"), "goal": ("g:",), "memory": ("m:",), "plan": ("p:",)}
PROPOSITION_KIND = {"belief": "belief", "goal": "goal", "memory": "memory", "plan": "plan"}     # record kind for governor.check_record
PASSIVE_GESTURES = frozenset({"wait", "look", "listen", "rest", "sleep", "stop"})


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: str                               # enum | ref | expression | condition
    optional: bool
    head: str = ""                          # enum: name of the manner scale
    values: tuple = ()                      # enum: allowed values (ordered when the scale is ordinal)
    accepts: tuple = ()                     # ref: what it may designate
    tokens: tuple = ()                      # ref: record types it may point to (informative)
    ordinal: bool = False


@dataclass(frozen=True)
class GestureSpec:
    id: str
    family: str
    params: tuple
    contact: bool

    def param(self, name: str) -> ParamSpec | None:
        return next((p for p in self.params if p.name == name), None)

    @property
    def expression_param(self) -> ParamSpec | None:
        return next((p for p in self.params if p.kind == "expression"), None)

    @property
    def passive(self) -> bool:
        return self.id in PASSIVE_GESTURES


@dataclass(frozen=True)
class WritableVar:
    id: str
    holder: str
    scale: str                              # bipolar10 unipolar10 qty ratio bool enum word mref time proposition list
    target_kind: str                        # self | entity | belief | goal | memory | plan
    creatable: bool                         # "or new record": target "new" creates a record
    writers: tuple
    step: float
    rate_per_day: float
    slow_per_life_year: float
    intimate: bool
    values: tuple = ()
    fields: tuple = ()                      # ((token type, field name), ...) where the dossiers show it

    @property
    def mode(self) -> str:
        """How the governor bounds it: jump (any value), step (per decision and per day), slow (per life year)."""
        if "T_jump" in self.writers and "T_step" not in self.writers:
            return "jump"
        if "T_step" in self.writers:
            return "step"
        return "slow"

    @property
    def numeric(self) -> bool:
        return self.scale in ("bipolar10", "unipolar10", "qty", "ratio")

    @property
    def bounds(self) -> tuple | None:
        return {"bipolar10": (-10.0, 10.0), "unipolar10": (0.0, 10.0), "ratio": (0.0, 1.0)}.get(self.scale)


@dataclass
class OutputSpec:
    gestures: dict = field(default_factory=dict)            # id -> GestureSpec
    manner_heads: dict = field(default_factory=dict)        # head -> {"values": [...], "ordinal": bool, "intimate": [...]}
    conditions: dict = field(default_factory=dict)          # condition id -> [argument types]
    writes: dict = field(default_factory=dict)              # variable id -> WritableVar (teacher-writable only)
    directions: tuple = ()
    max_writes: int = 4
    max_symbols: int = 20
    max_depth: int = 2
    max_pointers: int = 3
    unsupported_writes: tuple = ()                          # writable by the model but not by the teacher (lists)

    @classmethod
    def load(cls, families: dict | None = None, path=INTERFACE_PATH) -> "OutputSpec":
        """families: gesture id -> family (from the catalogue); absent -> ''."""
        raw = json.loads(path.read_bytes())
        out, inp = raw["output"], raw["input"]
        spec = cls(manner_heads=out["manner_heads"], conditions=dict(out["condition_args"]),
                   directions=tuple(out["relative_direction_head"]), max_writes=out["writes"]["max_per_decision"],
                   max_symbols=out["speech"]["max_symbols"], max_depth=out["speech"]["max_depth"],
                   max_pointers=out["max_pointers_per_gesture"])
        for gid in sorted(out["gestures"]):
            g = out["gestures"][gid]
            spec.gestures[gid] = GestureSpec(gid, (families or {}).get(gid, ""),
                                             tuple(cls._param(p, out["manner_heads"]) for p in g["params"]),
                                             bool(g["contact"]))
        fields_of: dict[str, list] = {}
        for tname, t in inp["token_types"].items():
            for fname, f in t["fields"].items():
                if "from" in f:
                    fields_of.setdefault(f["from"], []).append((tname, fname))
        unsupported = []
        for vid, w in sorted(out["writes"]["writable"].items()):
            if w["scale"] == "list":
                unsupported.append(vid)
                continue
            kind = next(k for prefix, k in TARGET_KINDS if w["target"].startswith(prefix))
            spec.writes[vid] = WritableVar(
                vid, w["holder"], w["scale"], kind, "new record" in w["target"], tuple(w["writer"]), float(w["step"]),
                float(w["rate_per_day"]), float(w["slow_per_life_year"]), bool(w["intimate"]), tuple(w["values"]),
                tuple(fields_of.get(vid, ())))
        spec.unsupported_writes = tuple(unsupported)
        return spec

    @staticmethod
    def _param(p: dict, heads: dict) -> ParamSpec:
        if "head" in p:
            h = heads[p["head"]]
            return ParamSpec(p["name"], "enum", bool(p["optional"]), head=p["head"], values=tuple(h["values"]),
                             ordinal=bool(h["ordinal"]))
        if "pointer" in p:
            return ParamSpec(p["name"], "ref", bool(p["optional"]), accepts=tuple(p["pointer"]), tokens=tuple(p.get("token", ())))
        return ParamSpec(p["name"], p["type"], bool(p["optional"]))

    @property
    def gesture_ids(self) -> list[str]:
        return list(self.gestures)

    @property
    def param_names(self) -> list[str]:
        return sorted({p.name for g in self.gestures.values() for p in g.params if p.kind != "expression"})
