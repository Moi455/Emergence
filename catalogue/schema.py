"""schema.py - the single catalogue of Emergence: every state variable, entity kind, property,
physical action, language concept, interpretation and hard rule, plus the stories that justify them.

Data lives in catalogue/data/*.toml (read with tomllib, no dependency). Each file holds arrays of
tables named after an entry kind, e.g. [[variable]], [[action]], [[story]]. A file may mix kinds.

Three layers are kept apart on purpose (decision of Monsieur, 9 Oct 2026):
  * physical actions  ([[action]])          : gestures the engine executes, parameterised by manner;
  * language          ([[concept]], [[grammar]]) : what an NPC says is an expression composed by the
                                               Transformer, never a dedicated verb (no 'blackmail');
  * interpretations   ([[interpretation]])  : what observers make of objective facts (theft, betrayal);
                                               never offered as an option.

The bulk of the catalogue comes from FIRST PRINCIPLES (what a body can do, what matter can undergo,
what language can say), not from examples: simple primitives whose combinations nobody plans.
Stories ([[story]]) are only PROBES: 'can the catalogue express this?'. A failed probe reveals a gap,
filled by a general primitive, never by an entry specific to the story. Stories never justify an entry
and never constrain behaviour. (Later, 'light rails' = cultural scripts NPCs know and may follow or not.)
"""
from __future__ import annotations

import dataclasses
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

SCALES = ("bipolar10", "unipolar10", "qty", "ratio", "enum", "id", "mref", "word", "bool", "list", "proposition", "time")
# id   = an objective identifier: engine only, may never carry a token.
# mref = a pointer to one of the NPC's OWN records (mental file of a person/object/place/group, a remembered
#        event, its goal, its belief): the only kind of pointer the model may read.
# word = a vocabulary word (a concept, an interpretation, a perceptual class): never an objective entity.
CLOCKS = ("real", "day", "life", "none")
# own_mind: its own feelings and dispositions; interoception: what its body feels (SELF only);
# perception: what it sees/hears/smells now (apparent values); belief: what it holds true, remembers, wants.
CHANNELS = ("own_mind", "interoception", "perception", "belief")
TOKEN_CHANNELS = {"SELF": ("own_mind", "interoception", "belief", "perception"), "SELF_MIND": ("own_mind",),
                  "SELF_STATE": ("own_mind",), "TASTE": ("own_mind",), "SKILL": ("belief",),
                  "ENTITY": ("perception", "belief"), "GROUP": ("belief",), "THING": ("perception", "belief"),
                  "PLACE": ("perception",), "EVENT": ("perception",), "BELIEF": ("belief",), "HEARD": ("belief",),
                  "MEMORY": ("belief",), "GOAL": ("belief",), "PLAN": ("belief",), "REQUEST": ("belief",),
                  "COMMIT": ("belief",), "INV": ("interoception", "perception")}   # real seconds | calendar (day 1 h 30, year 7 h, D30) | life clock
WRITERS = ("engine", "T_jump", "T_step", "T_slow", "birth", "action", "derived")
VISIBILITY = ("private", "observable", "public", "engine")
STATUS = ("N", "E", "R")                 # core, extension, postponed
STORY_STATUS = ("todo", "expressible", "gap")      # probe result
ACTION_FAMILIES = ("move", "posture", "grasp", "force", "tool", "transform", "consume", "care",
                   "perceive", "communicate", "meta")
PARAM_TYPES = ("ref", "enum", "qty", "duration", "condition", "expression", "bool")
REF_TARGETS = ("agent", "animal", "item", "structure", "terrain", "voxel", "water", "fire", "place", "trace",
               "belief", "form", "group", "direction", "plant")
# entity / place / item params are the NPC's OWN mental files (mref), never objective ids
# Arguments never point to an objective id: 'entity' = one of the NPC's own mental files (identified with a
# certainty), 'event' = an event the NPC remembers or describes, 'place' = a place as the NPC knows it.
ARG_TYPES = ("agent", "entity", "item", "place", "group", "role", "agreement", "event", "concept", "proposition",
             "quantity", "time", "gesture", "variable", "emotion", "interpretation", "kind", "name", "technique")
# Words that name an interpretation or a social scheme; they may never be the id of a physical action.
FORBIDDEN_ACTION_IDS = ("steal", "betray", "murder", "kill", "blackmail", "bribe", "threaten", "deceive",
                        "lie", "seduce", "insult", "compliment", "promise", "beat_up", "slap", "punch",
                        "rob", "cheat", "gossip", "flirt", "propose", "negotiate", "apologize", "thank")


@dataclass
class Entry:
    id: str
    label_fr: str = ""
    note: str = ""
    file: str = field(default="", compare=False)


@dataclass
class EntityKind(Entry):
    components: list[str] = field(default_factory=list)
    driven_by: str = "engine"            # 'transformer' (NPC, player proxy) or 'engine' (fauna, phenomena)


@dataclass
class Component(Entry):
    holder: str = ""                     # entity kind id, or 'relation' / 'belief' / 'episode' ...
    engine_only: bool = False            # True: the Transformer may never write its variables (body, needs...)
    part_of: str = ""                    # record structure inside another component (a belief inside 'beliefs')
    channel: str = ""                    # how the NPC knows what this component holds (CHANNELS); "" = it does not:
                                         # no variable of it may carry a token
    max_count: int = 0                   # records kept per holder (0 = single, not a record)


@dataclass
class Variable(Entry):
    holder: str = ""                     # component id
    scale: str = "bipolar10"
    unit: str = ""
    values: list[str] = field(default_factory=list)   # for enum
    writer: list[str] = field(default_factory=list)
    step: float = 0.0                    # governor bound per decision on the charter scale (T_step)
    slow_rate: float = 0.0               # T_slow bound: at most this much per LIVED YEAR (robust to clock compression)
    rate: float = 0.0                    # T_step bound: at most this much per GAME DAY (decisions come several times a second)
    values_from: str = ""                # enum whose values are the concepts of this category (single source)
    clock: str = ""                      # which clock its dynamics follow (CLOCKS); required when dynamics are given
    intimate: bool | None = None         # D10: never raised toward / from a minor (real, believed or apparent age);
                                         # MUST be declared on relations and drives
    visibility: str = "private"
    dynamics: str = ""
    token: str = ""
    status: str = "N"


@dataclass
class Property(Entry):
    category: str = "intrinsic"          # intrinsic (measured on the thing) | affordance (derived) | state (changes)
    applies_to: list[str] = field(default_factory=list)
    scale: str = "bool"
    unit: str = ""
    derived_from: list[str] = field(default_factory=list)   # property ids an affordance is computed from
    perceptible: bool | None = None      # MUST be declared: seen/felt on the thing, or known only by belief
    in_vector: bool = False              # intrinsic magnitudes the affordances do not convey (mass, reach...); affordances
                                         # and states are always in the object vector when perceptible
    rule: str = ""                       # how the engine computes or changes it (physics, not decision)


@dataclass
class Material(Entry):
    """A material class. Voxel classes come from engine/data/materials.csv (ids frozen); proposals are appended."""
    num: int = -1                        # class id in materials.csv; -1 = proposed, not yet in the engine
    category: str = ""
    density_kg_m3: float = 0.0
    hardness: int = 0                    # 0..100
    flammability: int = 0                # 0..100
    toughness: int = -1                  # 0..100 resistance to breaking; -1 = to fill
    cohesion: str = ""                   # natural | built | loose | fluid
    conductivity: int = -1               # heat, 0..100
    melting_c: int = -1                  # -1 = does not melt in this world
    edible: int = 0                      # nutrition 0..10 (food materials only)
    color: str = ""


@dataclass
class Process(Entry):
    """A physical transformation the engine applies to matter (cutting, heating...). Not a decision."""
    inputs: str = ""
    conditions: list[str] = field(default_factory=list)     # property / affordance ids required
    effect: str = ""


@dataclass
class Form(Entry):
    """A part shape (blade, shaft, vessel, wheel...). An object is an assembly of parts, each a form made of a
    material; the object's properties follow from its parts. Any assembly is possible, also unplanned ones."""
    gives: list[str] = field(default_factory=list)          # property ids this form can contribute
    rule: str = ""                                          # how material and size scale what it gives


@dataclass
class ItemType(Entry):
    """A KNOWN archetype (common knowledge: 'a sickle is a curved blade on a grip'), never a limit.
    The engine can hold objects matching no archetype (a knife lashed to a stick)."""
    category: str = ""
    parts: list[str] = field(default_factory=list)          # 'form:material'
    mass_kg: float = 0.0
    properties: dict = field(default_factory=dict)          # property id -> value (overrides, slot, potency...)
    made_by: list[str] = field(default_factory=list)        # process ids
    good: str = ""                                          # sim/data/content.json good it maps to, if any
    lookalike: str = ""                                     # perceptual class shared with look-alikes (debased coin ~ silver coin)


@dataclass
class Species(Entry):
    """A living species (plant or animal). Products are species x part: wool of the sheep, apple of the apple tree."""
    kingdom: str = ""                    # plant | animal
    habitat: list[str] = field(default_factory=list)     # sea, river, forest, mountain, desert, meadow, fields, village, marches
    domestic: bool = False
    products: list[str] = field(default_factory=list)    # 'part:material' (wool:wool, meat:flesh, fruit:vegetable)
    danger: int = 0                      # 0..10 to a human
    diet: str = ""                       # animals: herbivore, carnivore, omnivore, scavenger
    behavior: str = ""                   # the engine law (fauna is not driven by a Transformer)
    lookalike: str = ""                  # perceptual class shared with look-alikes (death cap ~ edible mushroom);
                                         # perception shows the true species only to a skilled eye


@dataclass
class Param:
    name: str
    type: str
    accepts: list[str] = field(default_factory=list)          # for type ref: what it may point to (REF_TARGETS)
    values: list[str] = field(default_factory=list)
    optional: bool = False
    note: str = ""
    intimate_values: list[str] = field(default_factory=list)   # D10: these values are refused with a minor
    ordinal: bool = False                # a manner scale (force, pace...): at most 5 bins (AI budget)


@dataclass
class Action(Entry):
    family: str = ""
    params: list[Param] = field(default_factory=list)
    requires: dict = field(default_factory=dict)       # param name (or "held") -> property id it must have
    effects: str = ""
    perceptibility: str = ""
    duration: str = ""
    animation: list[str] = field(default_factory=list)
    intimate: bool = False               # D10: refused when actor or target is a minor by real, believed or apparent age
    uses: list[str] = field(default_factory=list)            # technique concepts whose mastery shapes the outcome
    contact: bool = False                # touches a body: must declare minor_whitelist (D10)
    minor_whitelist: dict = field(default_factory=dict)      # param -> values allowed when actor or target is a minor
    status: str = "N"


@dataclass
class Concept(Entry):
    category: str = ""                   # predicate, deontic, source, link, mode, time, logic, quantity, ...
    args: list[str] = field(default_factory=list)          # argument types of a predicate (see ARG_TYPES)
    refers: str = ""                     # id of a catalogue entry this word names, if any
    intimate: bool | None = None         # D10: refused in any goal, belief write, utterance or agreement involving a
                                         # minor; MUST be declared on link words


@dataclass
class Grammar(Entry):
    rule: str = ""


@dataclass
class Interpretation(Entry):
    facts: list[str] = field(default_factory=list)     # objective facts the engine records
    norms: list[str] = field(default_factory=list)     # norm beliefs that make it salient


@dataclass
class HardRule(Entry):
    text_fr: str = ""
    applies_to: list[str] = field(default_factory=list)


@dataclass
class Story(Entry):
    charter: list[str] = field(default_factory=list)   # charter paragraphs, e.g. ['§8', '§20']
    text_fr: str = ""
    status: str = "todo"
    # decomposition: ids of catalogue entries the story needs
    actions: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    interpretations: list[str] = field(default_factory=list)
    utterances: list[str] = field(default_factory=list)  # expressions in the inner language


KINDS: dict[str, type[Entry]] = {
    "entity": EntityKind, "component": Component, "variable": Variable, "property": Property,
    "action": Action, "concept": Concept, "grammar": Grammar, "interpretation": Interpretation,
    "hard_rule": HardRule, "story": Story, "material": Material, "process": Process, "form": Form, "item_type": ItemType, "species": Species,
}
ENGINE_MATERIALS = Path(__file__).resolve().parents[1] / "engine" / "data" / "materials.csv"
PROPERTY_CATEGORIES = ("intrinsic", "affordance", "state")
STORY_REFS = {"actions": "action", "concepts": "concept", "variables": "variable", "entities": "entity",
              "properties": "property", "interpretations": "interpretation"}


class CatalogueError(Exception):
    pass


class Catalogue:
    """All entries, indexed by kind then id. load() parses, validate() returns the list of problems."""

    def __init__(self):
        self.entries: dict[str, dict[str, Entry]] = {k: {} for k in KINDS}
        self.load_errors: list[str] = []

    # ---- loading -------------------------------------------------------------------------------
    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "Catalogue":
        cat = cls()
        for path in sorted(Path(data_dir).glob("*.toml")):
            with open(path, "rb") as f:
                doc = tomllib.load(f)
            for kind, rows in doc.items():
                if kind not in KINDS:
                    cat.load_errors.append(f"{path.name}: unknown entry kind [[{kind}]]")
                    continue
                for row in rows:
                    cat._add(kind, row, path.name)
        cat._load_engine_materials()
        return cat

    def _load_engine_materials(self):
        """Voxel material classes are owned by the engine: read them, never copy them."""
        if not ENGINE_MATERIALS.exists():
            return
        lines = [l for l in ENGINE_MATERIALS.read_text().splitlines() if l and not l.startswith("#")]
        head = lines[1].split(",")                       # lines[0] is schema_version
        for l in lines[2:]:
            r = dict(zip(head, l.split(",")))
            mid = r["name"]
            row = {"id": mid, "num": int(r["id"]), "category": r["category"], "density_kg_m3": float(r["density_kg_m3"]),
                   "hardness": int(r["hardness"]), "flammability": int(r["flammability"]), "color": r["color"]}
            extra = self.entries["material"].pop(mid, None)       # a toml row may complete an engine material
            if extra is not None:
                for k in ("toughness", "cohesion", "conductivity", "melting_c", "edible", "label_fr", "note"):
                    row[k] = getattr(extra, k)
            self._add("material", row, "engine/data/materials.csv")

    def _add(self, kind: str, row: dict, fname: str):
        klass = KINDS[kind]
        names = {f.name for f in dataclasses.fields(klass)} - {"file"}
        unknown = set(row) - names
        if unknown:
            self.load_errors.append(f"{fname}: [[{kind}]] {row.get('id', '?')}: unknown fields {sorted(unknown)}")
            row = {k: v for k, v in row.items() if k in names}
        if "id" not in row:
            self.load_errors.append(f"{fname}: [[{kind}]] without id")
            return
        if kind == "action":
            row = dict(row)
            try:
                row["params"] = [Param(**p) for p in row.get("params", [])]
            except TypeError as e:
                self.load_errors.append(f"{fname}: action {row['id']}: bad param ({e})")
                row["params"] = []
        entry = klass(**row, file=fname)
        if entry.id in self.entries[kind]:
            self.load_errors.append(f"{fname}: duplicate {kind} id '{entry.id}' (first in {self.entries[kind][entry.id].file})")
            return
        self.entries[kind][entry.id] = entry

    # ---- access --------------------------------------------------------------------------------
    def __getitem__(self, kind: str) -> dict[str, Entry]:
        return self.entries[kind]

    def count(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.entries.items()}

    def item_properties(self, parts: list[str], explicit: dict | None = None) -> set[str]:
        """Properties an assembly of parts can have: what its forms give, plus explicit ones.
        Works for any assembly, archetype or not (the engine's reference, not a decision)."""
        out = set(explicit or {})
        for part in parts:
            fo = self["form"].get(part.partition(":")[0])
            if fo is not None:
                out.update(fo.gives)
        return out

    def perceptible_properties(self) -> list[str]:
        """What the model may see of an object: perceptible properties, and affordances whose sources are all
        perceptible (edible is not visible if it rests on a hidden toxicity: that is known by belief)."""
        props = self["property"]
        def ok(pid, seen=()):
            pr = props[pid]
            if not pr.perceptible:
                return False
            return all(ok(d, seen + (pid,)) for d in pr.derived_from if d in props and d not in seen)
        return [pid for pid in props if ok(pid)]

    def object_vector(self) -> list[str]:
        """The fixed vector describing a perceived thing to the model (THING.props)."""
        props = self["property"]
        return [p for p in self.perceptible_properties()
                if props[p].category in ("affordance", "state") or props[p].in_vector]

    def citations(self) -> dict[str, dict[str, list[str]]]:
        """kind -> id -> ids of the stories that cite it."""
        out: dict[str, dict[str, list[str]]] = {k: {} for k in STORY_REFS.values()}
        for s in self.entries["story"].values():
            for attr, kind in STORY_REFS.items():
                for ref in getattr(s, attr):
                    out[kind].setdefault(ref, []).append(s.id)
        return out

    # ---- validation ----------------------------------------------------------------------------
    def validate(self, strict: bool = False) -> list[str]:
        """Problems as text lines. strict=True also requires every probe story to be expressible."""
        p = list(self.load_errors)
        p += self._check_enums()
        p += self._check_refs()
        p += self._check_layers()
        p += self._check_hard_rules()
        if strict:
            p += self._check_coverage()
        return p

    def _check_enums(self) -> list[str]:
        p = []
        for v in self["variable"].values():
            if v.scale not in SCALES:
                p.append(f"variable {v.id}: scale '{v.scale}' not in {SCALES}")
            for w in v.writer:
                if w not in WRITERS:
                    p.append(f"variable {v.id}: writer '{w}' not in {WRITERS}")
            if not v.writer:
                p.append(f"variable {v.id}: no writer")
            if "T_step" in v.writer and (v.step <= 0 or v.rate <= 0):
                p.append(f"variable {v.id}: writer T_step needs a step > 0 (per decision) and a rate > 0 (per game day)")
            if "T_slow" in v.writer and (v.slow_rate <= 0 or v.step <= 0):
                p.append(f"variable {v.id}: writer T_slow needs a slow_rate > 0 (per life-year) and a step > 0 (per decision)")
            if v.dynamics and v.clock not in CLOCKS:
                p.append(f"variable {v.id}: dynamics without a clock ({CLOCKS})")
            # no truth in tokens, enforced by structure (rule no_truth_in_tokens)
            if v.token and v.scale == "id":
                p.append(f"variable {v.id}: an objective id cannot carry a token (use scale mref)")
            if v.token and v.visibility == "engine":
                p.append(f"variable {v.id}: engine-only visibility cannot carry a token")
            if v.token and v.holder in self["component"]:
                ch = self._channel(v.holder)
                for part in v.token.split(";"):
                    m = re.match(r"\s*([A-Z_]+)", part)
                    if not m:
                        continue
                    allowed = TOKEN_CHANNELS.get(m.group(1))
                    if not ch:
                        p.append(f"variable {v.id}: component '{v.holder}' has no channel, it cannot reach a token")
                    elif allowed is not None and ch not in allowed:
                        p.append(f"variable {v.id}: token {m.group(1)} cannot come from channel '{ch}'")
            if v.visibility not in VISIBILITY:
                p.append(f"variable {v.id}: visibility '{v.visibility}' not in {VISIBILITY}")
            if v.status not in STATUS:
                p.append(f"variable {v.id}: status '{v.status}'")
            if v.scale == "enum" and not v.values and not v.values_from:
                p.append(f"variable {v.id}: enum without values")
            if v.values_from:
                cat_ids = [c.id for c in self["concept"].values() if c.category == v.values_from]
                if not cat_ids:
                    p.append(f"variable {v.id}: values_from unknown concept category '{v.values_from}'")
                elif v.values and v.values != cat_ids:
                    p.append(f"variable {v.id}: values differ from concept category '{v.values_from}'")
        for a in self["action"].values():
            if a.family not in ACTION_FAMILIES:
                p.append(f"action {a.id}: family '{a.family}' not in {ACTION_FAMILIES}")
            for prm in a.params:
                if prm.type not in PARAM_TYPES:
                    p.append(f"action {a.id}: param {prm.name} type '{prm.type}' not in {PARAM_TYPES}")
                if prm.type == "enum" and not prm.values:
                    p.append(f"action {a.id}: enum param {prm.name} without values")
                if prm.ordinal and len(prm.values) > 5:
                    p.append(f"action {a.id}: ordinal param {prm.name} has more than 5 bins")
                if prm.type == "enum" and not prm.ordinal and len(prm.values) > 12:
                    p.append(f"action {a.id}: param {prm.name} has more than 12 values")
                if prm.type == "ref":
                    if not prm.accepts:
                        p.append(f"action {a.id}: ref param {prm.name} without accepts")
                    for t in prm.accepts:
                        if t not in REF_TARGETS:
                            p.append(f"action {a.id}: ref param {prm.name} accepts unknown '{t}'")
                for iv in prm.intimate_values:
                    if iv not in prm.values:
                        p.append(f"action {a.id}: intimate value '{iv}' not among {prm.name} values")
            for t in a.uses:
                if t not in self["concept"] or self["concept"][t].category != "technique":
                    p.append(f"action {a.id}: uses unknown technique '{t}'")
            pnames = {prm.name for prm in a.params} | {"held"}
            for pn, r in a.requires.items():
                if pn not in pnames:
                    p.append(f"action {a.id}: requires on unknown param '{pn}'")
                if r not in self["property"]:
                    p.append(f"action {a.id}: requires unknown property '{r}'")
            touches_agent = any(prm.type == "ref" and "agent" in prm.accepts for prm in a.params)
            if a.contact and not a.minor_whitelist:
                p.append(f"action {a.id}: contact gesture without minor_whitelist (D10)")
            for pn, vals in a.minor_whitelist.items():
                prm = next((x for x in a.params if x.name == pn), None)
                if prm is None or any(v not in prm.values for v in vals):
                    p.append(f"action {a.id}: minor_whitelist on unknown param or value '{pn}'")
                elif any(v in prm.intimate_values for v in vals):
                    p.append(f"action {a.id}: minor_whitelist allows an intimate value of '{pn}' (D10)")
            if any(prm.intimate_values for prm in a.params) and not a.contact:
                p.append(f"action {a.id}: has intimate values but is not declared contact")
        for s in self["story"].values():
            if s.status not in STORY_STATUS:
                p.append(f"story {s.id}: status '{s.status}'")
            if not s.text_fr:
                p.append(f"story {s.id}: no text_fr")
            if s.status == "expressible" and not (s.actions or s.utterances or s.variables):
                p.append(f"story {s.id}: marked expressible but no decomposition given")
        for pr in self["property"].values():
            if pr.perceptible is None:
                p.append(f"property {pr.id}: perceptible must be declared (true or false)")
            if pr.category not in PROPERTY_CATEGORIES:
                p.append(f"property {pr.id}: category '{pr.category}'")
            if pr.scale not in SCALES:
                p.append(f"property {pr.id}: scale '{pr.scale}'")
            if pr.category == "affordance" and not pr.derived_from:
                p.append(f"property {pr.id}: affordance without derived_from")
        for e in self["entity"].values():
            if e.driven_by not in ("transformer", "engine"):
                p.append(f"entity {e.id}: driven_by '{e.driven_by}'")
        return p

    def _channel(self, comp_id: str) -> str:
        c = self["component"].get(comp_id)
        while c is not None and not c.channel and c.part_of:
            c = self["component"].get(c.part_of)
        return c.channel if c is not None else ""

    def _check_refs(self) -> list[str]:
        p = []
        for s in self["story"].values():
            for attr, kind in STORY_REFS.items():
                for ref in getattr(s, attr):
                    if ref not in self[kind]:
                        p.append(f"story {s.id}: unknown {kind} '{ref}'")
        for v in self["variable"].values():
            if v.holder and v.holder not in self["component"]:
                p.append(f"variable {v.id}: unknown holder component '{v.holder}'")
            elif v.holder and self["component"][v.holder].engine_only and any(w.startswith("T_") for w in v.writer):
                p.append(f"variable {v.id}: component '{v.holder}' is engine-only, the Transformer cannot write it")
        for e in self["entity"].values():
            for c in e.components:
                if c not in self["component"]:
                    p.append(f"entity {e.id}: unknown component '{c}'")
        for c in self["component"].values():
            if c.channel and c.channel not in CHANNELS:
                p.append(f"component {c.id}: channel '{c.channel}' not in {CHANNELS}")
            if c.part_of and c.part_of not in self["component"]:
                p.append(f"component {c.id}: part_of unknown component '{c.part_of}'")
        for c in self["concept"].values():
            for a in c.args:
                if a not in ARG_TYPES:
                    p.append(f"concept {c.id}: argument type '{a}' not in ARG_TYPES")
        for pr in self["property"].values():
            for k in pr.applies_to:
                if k not in self["entity"]:
                    p.append(f"property {pr.id}: unknown entity kind '{k}'")
        for pr in self["property"].values():
            for d in pr.derived_from:
                if d not in self["property"]:
                    p.append(f"property {pr.id}: derived from unknown property '{d}'")
        for pc in self["process"].values():
            for c in pc.conditions:
                if c not in self["property"]:
                    p.append(f"process {pc.id}: unknown condition property '{c}'")
        for fo in self["form"].values():
            for g in fo.gives:
                if g not in self["property"]:
                    p.append(f"form {fo.id}: gives unknown property '{g}'")
        for it in self["item_type"].values():
            if not it.parts:
                p.append(f"item_type {it.id}: no parts")
            for part in it.parts:
                form, _, mat = part.partition(":")
                if form not in self["form"]:
                    p.append(f"item_type {it.id}: unknown form '{form}'")
                if mat not in self["material"]:
                    p.append(f"item_type {it.id}: unknown material '{mat}'")
            for k in it.properties:
                if k not in self["property"]:
                    p.append(f"item_type {it.id}: unknown property '{k}'")
            for pc in it.made_by:
                if pc not in self["process"]:
                    p.append(f"item_type {it.id}: unknown process '{pc}'")
        lookalikes = {c.id for c in self["concept"].values() if c.category == "lookalike"}
        for x in list(self["species"].values()) + list(self["item_type"].values()):
            if x.lookalike and x.lookalike not in lookalikes:
                p.append(f"{x.id}: lookalike '{x.lookalike}' is not a declared lookalike word")
        for sp in self["species"].values():
            if sp.kingdom not in ("plant", "animal"):
                p.append(f"species {sp.id}: kingdom '{sp.kingdom}'")
            for prod in sp.products:
                mat = prod.partition(":")[2]
                if mat not in self["material"]:
                    p.append(f"species {sp.id}: product material '{mat}' unknown")
        for c in self["concept"].values():
            if c.refers and not any(c.refers in self[k] for k in KINDS):
                p.append(f"concept {c.id}: refers to unknown entry '{c.refers}'")
        return p

    def _check_hard_rules(self) -> list[str]:
        """D10 must be structural: the intimate flags exist where the rule needs them."""
        p = []
        if "D10_minors" not in self["hard_rule"]:
            p.append("hard_rule D10_minors missing")
        for v in self["variable"].values():
            if (v.holder == "relation" or v.id.startswith("need_") or v.id == "attracted_to") and v.intimate is None:
                p.append(f"variable {v.id}: intimate must be declared (true or false) on relations and drives (D10)")
        for c in self["concept"].values():
            if c.category == "link" and c.intimate is None:
                p.append(f"concept {c.id}: intimate must be declared (true or false) on link words (D10)")
        for vid in ("r_attraction", "need_intimacy", "attracted_to"):
            v = self["variable"].get(vid)
            if v is None or not v.intimate:
                p.append(f"variable {vid}: must exist and be flagged intimate (D10)")
        for cid in ("spouse", "betrothed", "lover", "former_spouse"):
            c = self["concept"].get(cid)
            if c is None or not c.intimate:
                p.append(f"concept {cid}: must exist and be flagged intimate (D10)")
        return p

    def _check_layers(self) -> list[str]:
        """The three layers never mix: no interpretation or social scheme is a physical action."""
        p = []
        interp = set(self["interpretation"])
        for a in self["action"]:
            if a in FORBIDDEN_ACTION_IDS or a in interp:
                p.append(f"action {a}: names an interpretation or a social scheme, not a gesture")
        return p

    def _check_coverage(self) -> list[str]:
        """Probes only: an entry never needs a story; a story that cannot be expressed is a gap."""
        return [f"story {s.id}: {s.status}" for s in self["story"].values() if s.status != "expressible"]
