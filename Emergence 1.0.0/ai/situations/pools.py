"""pools.py - the words a situation is made of, drawn from the catalogue (never written here).

The sampler only BUILDS situations (what an NPC perceives, believes, remembers, wants); it never decides what
the NPC does. Everything it may write comes from the catalogue or the model interface, so a catalogue change
changes the situations.
"""
from __future__ import annotations

from functools import cached_property

from governor import Governor
from schema import Catalogue
from tok2 import ModelInterface


class Pools:
    def __init__(self, cat: Catalogue | None = None, interface: ModelInterface | None = None):
        self.cat = cat or Catalogue.load()
        self.interface = interface or ModelInterface()

    @cached_property
    def governor(self) -> Governor:
        return Governor(self.cat)

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
    def intimate_links(self) -> frozenset[str]:
        return frozenset(c.id for c in self.cat["concept"].values() if c.category == "link" and c.intimate)

    @cached_property
    def intimate_fields(self) -> dict[str, tuple[str, ...]]:
        """token type -> the fields that carry an intimate variable (read from the interface, never listed)."""
        out: dict[str, tuple[str, ...]] = {}
        for typ, spec in self.interface.token_types.items():
            names = tuple(n for n, f in spec["fields"].items()
                          if getattr(self.cat["variable"].get(f.get("from", "")), "intimate", False))
            if names:
                out[typ] = names
        return out

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
    def weapon_categories(self) -> frozenset[str]:
        """Item categories that are arms (a blade, a blunt weapon, a polearm, a ranged weapon, ammunition)."""
        return frozenset(c for c in self.items_by_category if c in ("blade", "blunt", "polearm", "ranged", "ammo"))

    def place_items(self, categories) -> list[str]:
        """Every item of these categories, once each (an object is as likely as any other, not as likely as its
        category's share); no boat on dry land."""
        return [k for cat in categories for k in self.items_by_category.get(cat, ()) if k not in self.water_kinds]

    @cached_property
    def water_kinds(self) -> frozenset[str]:
        return frozenset(k for k in self.cat["item_type"] if "boat" in k)

    @cached_property
    def category_of(self) -> dict[str, str]:
        return {it.id: it.category for it in self.cat["item_type"].values()}

    def item_has(self, kind: str, prop: str) -> bool:
        """True only when the catalogue makes it CERTAIN that the item has the property (edible and drinkable are
        read from nutrition and hydration; the rest from the perceptible vector, see item_vector)."""
        it = self.cat["item_type"].get(kind)
        if it is None:
            return False
        if prop in ("edible", "drinkable"):
            have = set(self.cat.item_properties(it.parts, it.properties))
            return {"edible": "nutrition", "drinkable": "hydration"}[prop] in have
        return self.item_vector(kind).get(prop) is True

    @cached_property
    def animals(self) -> list[str]:
        return sorted(s.id for s in self.cat["species"].values() if s.kingdom == "animal")

    def animals_of(self, habitats: tuple[str, ...], domestic: bool | None = None) -> list[str]:
        return sorted(s.id for s in self.cat["species"].values() if s.kingdom == "animal"
                      and set(s.habitat) & set(habitats) and (domestic is None or s.domestic == domestic))

    @cached_property
    def object_vector(self) -> list[str]:
        return list(self.interface.object_vector)

    # what an adult can do with a mass (kg): the engine decides from the real body; here a plausible bootstrap
    MASS_AFFORDANCES = {"graspable": 25.0, "carryable": 40.0, "throwable": 3.0}

    def item_vector(self, kind: str) -> dict:
        """The perceptible properties of a known kind at rest, as far as the catalogue makes them CERTAIN: mass,
        explicit values, what its forms give, mass-based handling, not burning. Anything else stays unknown
        (absent), never a false 'no' (the engine will compute the real assembly)."""
        it = self.cat["item_type"][kind]
        have = self.cat.item_properties(it.parts, it.properties)
        props = self.cat["property"]
        out: dict = {"mass": float(it.mass_kg), "burning": False}
        for p in self.object_vector:
            pr = props[p]
            if p in it.properties and not isinstance(it.properties[p], bool) and pr.scale != "bool":
                x = float(it.properties[p])
                out[p] = x if pr.scale == "qty" else min(10.0, max(0.0, x))
            elif pr.scale == "bool" and (p in have or it.properties.get(p) is True):
                out[p] = True
            elif p in self.MASS_AFFORDANCES and it.mass_kg > 0:
                out[p] = it.mass_kg <= self.MASS_AFFORDANCES[p]
        if "capacity" in have or "capacity" in it.properties:
            out["contains"] = True
        return {p: v for p, v in out.items() if p in self.object_vector}
