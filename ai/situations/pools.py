"""pools.py - the words a situation is made of, drawn from the catalogue (never written here).

The sampler only BUILDS situations (what an NPC perceives, believes, remembers, wants); it never decides what
the NPC does. Everything it may write comes from the catalogue or the model interface, so a catalogue change
changes the situations.
"""
from __future__ import annotations

import sys
from functools import cached_property
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "catalogue")); sys.path.insert(0, str(ROOT / "catalogue" / "tools"))
sys.path.insert(0, str(ROOT / "ai"))
from schema import Catalogue  # noqa: E402
from tok2 import ModelInterface  # noqa: E402


class Pools:
    def __init__(self, cat: Catalogue | None = None, interface: ModelInterface | None = None):
        self.cat = cat or Catalogue.load()
        self.interface = interface or ModelInterface()

    # ---- the language ---------------------------------------------------------------------------
    def concepts(self, category: str) -> list[str]:
        return sorted(c.id for c in self.cat["concept"].values() if c.category == category)

    @cached_property
    def intimate_symbols(self) -> frozenset[str]:
        """Concepts, variables, interpretations and manners flagged intimate (D10)."""
        out = {c.id for c in self.cat["concept"].values() if c.intimate}
        out |= {v.id for v in self.cat["variable"].values() if v.intimate}
        out |= {i.id for i in self.cat["interpretation"].values() if getattr(i, "intimate", False)}
        out |= {x for a in self.cat["action"].values() for p in a.params for x in p.intimate_values}
        out |= {a.id for a in self.cat["action"].values() if a.intimate}
        return frozenset(out)

    @cached_property
    def interpretations(self) -> list[str]:
        return sorted(self.cat["interpretation"])

    @cached_property
    def gestures(self) -> dict[str, list[str]]:
        """family -> gesture ids (no intimate gesture)."""
        out: dict[str, list[str]] = {}
        for a in sorted(self.cat["action"].values(), key=lambda a: a.id):
            if not a.intimate:
                out.setdefault(a.family, []).append(a.id)
        return out

    def enum(self, token_type: str, field: str) -> list[str]:
        return list(self.interface.token_types[token_type]["fields"][field]["values"])

    # ---- the world ------------------------------------------------------------------------------
    @cached_property
    def items_by_category(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for it in sorted(self.cat["item_type"].values(), key=lambda i: i.id):
            out.setdefault(it.category, []).append(it.id)
        return out

    @cached_property
    def animals(self) -> list[str]:
        return sorted(s.id for s in self.cat["species"].values() if s.kingdom == "animal")

    def animals_of(self, habitats: tuple[str, ...], domestic: bool | None = None) -> list[str]:
        return sorted(s.id for s in self.cat["species"].values() if s.kingdom == "animal"
                      and set(s.habitat) & set(habitats) and (domestic is None or s.domestic == domestic))

    @cached_property
    def object_vector(self) -> list[str]:
        return list(self.interface.object_vector)

    def item_vector(self, kind: str) -> dict:
        """The perceptible properties of a known kind, approximated from its parts (the engine will compute them
        from the real assembly): affordances given by its forms, explicit values, mass."""
        it = self.cat["item_type"][kind]
        have = self.cat.item_properties(it.parts, it.properties)
        props = self.cat["property"]
        out: dict = {}
        for p in self.object_vector:
            pr = props[p]
            if p == "mass":
                out[p] = float(it.mass_kg)
            elif p in it.properties and not isinstance(it.properties[p], bool) and pr.scale != "bool":
                out[p] = float(it.properties[p]) if pr.scale == "qty" else min(10.0, max(0.0, float(it.properties[p])))
            elif pr.scale == "bool":
                out[p] = p in have or any(d in have for d in pr.derived_from)
        return out
