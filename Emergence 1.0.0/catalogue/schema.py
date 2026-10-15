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
CHANNELS = ("own_mind", "interoception", "perception", "belief", "setting")
TOKEN_PART = re.compile(r"^([A-Z][A-Z_]*)(?:\.[a-z_][a-z0-9_.]*)?(?: \(.*\))?(?: [/a-zA-Z_.]+)*$")
TOKEN_CHANNELS = {"SELF": ("own_mind", "interoception", "belief", "perception"), "SELF_MIND": ("own_mind",),
                  "SELF_STATE": ("own_mind",), "TASTE": ("own_mind",), "SKILL": ("belief",),
                  "ENTITY": ("perception", "belief"), "GROUP": ("belief",), "THING": ("perception", "belief"),
                  "PLACE": ("perception",), "EVENT": ("perception",), "BELIEF": ("belief",), "HEARD": ("belief",),
                  "MEMORY": ("belief",), "GOAL": ("belief",), "PLAN": ("belief",), "REQUEST": ("belief",),
                  "COMMIT": ("belief",), "INV": ("belief", "perception"), "LOCUS": ("belief",),
                  "WAKE": ("setting",)}   # real seconds | calendar (day 1 h 30, year 7 h, D30) | life clock
WRITERS = ("engine", "T_jump", "T_step", "T_slow", "birth", "action", "derived")
VISIBILITY = ("private", "observable", "public", "engine")
STATUS = ("N", "E", "R")                 # core, extension, postponed
STORY_STATUS = ("todo", "expressible", "gap")      # probe result
ACTION_FAMILIES = ("move", "posture", "grasp", "force", "tool", "transform", "consume", "care",
                   "perceive", "communicate", "meta")
PARAM_TYPES = ("ref", "enum", "qty", "duration", "condition", "expression", "bool")
CONTACT_ZONES = ("head", "face", "shoulder", "arms", "hands", "back", "torso", "legs", "body")
MINOR_ZONES = ("head", "shoulder", "arms", "hands", "back", "legs")   # the only zones ever touched on a minor (D10)
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
    words_from: str = ""                 # list of words: the category of [[percept_word]] it may hold (a closed, declared set)
    clock: str = ""                      # which clock its dynamics follow (CLOCKS); required when dynamics are given
    list_of: str = ""                    # element type of a list that reaches a token (mref, word, enum, qty, proposition)
    components: list[str] = field(default_factory=list)   # named axes of a vector value as it reaches a token
                                         # (["sin", "cos"]); ["@object_vector"] = Catalogue.object_vector
    reads: list[str] = field(default_factory=list)   # derived variables in a BELIEF channel: the variables they read
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
    # time and matter flow (T07, docs/16 4.6); all optional until T08 fills them
    trigger: str = ""                                       # what starts it (contact, heat, tool, time...)
    clock: str = ""                                         # PROCESS_CLOCKS: how its duration is counted
    nominal_game_s: int = 0                                 # nominal duration in game seconds (0 = instant / unset)
    consumes: list[str] = field(default_factory=list)       # material ids taken in
    produces: list[str] = field(default_factory=list)       # material ids given out


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
    mountable: bool = False              # an animal one can ride (mount) : read from the species, a flag, not a rule
    # time of crops and herds (T07, docs/16 4.6); all optional until T08 fills them
    sow_seasons: list[str] = field(default_factory=list)    # SEASONS in which it is sown / bred
    days_to_mature: int = 0                                 # game days from sowing / birth to harvest / adulthood
    harvest_window_days: int = 0                            # game days during which the harvest stays good
    product_regrow_days: int = 0                            # game days between two takes of a product (milk, wool, fruit)


@dataclass
class Site(Entry):
    """A KIND OF PLACE OR CONSTRUCTION (house, barn, wall, bridge, well, field, mine, temple, market, village, city, forest,
    river, cave, road, sky...), perceived through lc_kind / pc_kind_seen, usable in recipe, exists and channel.
    Part of the kinds table (vocabulary `sortes`, factored): not a grammar word."""
    category: str = ""                   # building | work | land | settlement | wild | water | route | sky
    built: bool = False                  # made by hands: one can channel INTO it (a form), it is also a structure


@dataclass
class PerceptWord(Entry):
    """A word for what can be PERCEIVED (a build, a mark, a sign of health, a state, the weather, a colour, a wound):
    the closed set a list variable declares with `words_from`. In the kinds table, so it is also speakable:
    (appears @E1 bald). One table: what is seen and what is said are the same words."""
    category: str = ""                   # build | mark | sign | health | attire | state | weather | strange | color | wound


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
    contact: bool | None = None          # MUST be declared when a ref param accepts an agent (D10)
    party_params: list[str] = field(default_factory=list)    # params that may designate a person involved (D10)
    minor_person_ok: bool = False        # may this gesture involve a minor at all? then minor_whitelist applies
    minor_whitelist: dict = field(default_factory=dict)      # param -> values allowed when a minor is involved;
                                                             # with a minor, every whitelisted param is REQUIRED
    status: str = "N"
    # time of a gesture (T07, docs/16 4.6, docs/14 4.3-4.4); optional until T08, required by check.py --strict
    natural_end: bool | None = None      # True: it ends by itself (a swallow); False: it needs a stop condition; None = undeclared
    cadence_ms: int = 0                  # engine cycle in REAL milliseconds (one blow, one step); 0 = undeclared
    productive: bool = False             # work that task compression may speed up (never bodily harm)


@dataclass
class DurationLevel(Entry):
    """A chosen duration word (brief, a_while, long), counted in GAME seconds (docs/14 4.4)."""
    game_s: int = 0


@dataclass
class Illness(Entry):
    """A disease of the body laws (contagion, illness_course): how it passes, how it runs, what shows."""
    transmission: list[str] = field(default_factory=list)   # ILLNESS_TRANSMISSIONS
    incubation_days: int = 0                                # game days before the first sign
    course_days: int = 0                                    # game days from first sign to cure or death
    symptoms: list[str] = field(default_factory=list)       # percept_word ids (what others can SEE)
    lethality: int = 0                                      # 0..100 percent of the sick who die untreated


@dataclass
class Concept(Entry):
    category: str = ""                   # predicate, deontic, source, link, mode, time, logic, quantity, ...
    args: list[str] = field(default_factory=list)          # argument types of a predicate (see ARG_TYPES)
    refers: str = ""                     # id of a catalogue entry this word names, if any
    intimate: bool | None = None         # D10: refused in any goal, belief write, utterance or agreement involving a
                                         # minor; MUST be declared on link words
    answers: bool | None = None          # a formula that may answer ONE precise item: (yes h:2), (no q:1)
    wh_ok: bool | None = None            # a predicate whose proposition may hold a question hole: (not (knows me (at @E9 where)))
    arg_classes: list = field(default_factory=list)   # per argument, the classes it may be (agent, animal, item, structure, plant,
                                         # land, place, group…); [] = free. Checked when the class of the argument is KNOWN
                                         # (a person word, or a pointer whose record kind the caller gives): (dead @T1) with
                                         # @T1 a knife, (owns me @L1) with @L1 a forest are refused


@dataclass
class Grammar(Entry):
    rule: str = ""
    ranks: dict = field(default_factory=dict)            # keyword ranks by word category (ELIZA's precedence number): which
                                                         # words decide what an utterance is ABOUT (tools/shapes.py Keyworder)


@dataclass
class Shape(Entry):
    """A SHAPE of speech: a decomposition pattern over the S-expression of an utterance (ELIZA's decomposition rule).
    It RECOGNISES « this is a promise, a threat, a recruitment, a rendezvous » for analysis, tests and the teacher's audit.
    It is never a word of the language, never an action, never an option offered to the model, and decides nothing
    (D28: social acts stay combinations of words; this only names the combination after the fact)."""
    pattern: str = ""                    # (offer (future (did me ...))) ; _ any ; ?x binds ; <category> a word of a category ; ... the rest
    rank: int = 1                        # precedence when several shapes match (the highest wins), like a keyword rank


@dataclass
class Interpretation(Entry):
    """A judgement an observer may make about events (theft, betrayal...). NEVER an option: a word to judge with."""
    facts: list[str] = field(default_factory=list)     # objective facts the engine records (truth, for the chronicle)
    cues: list[str] = field(default_factory=list)      # what an observer can perceive or believe that points to it
    norms: list[str] = field(default_factory=list)     # norm beliefs that make it salient
    intimate: bool = False                             # D10: a judgement about an intimate act (adultery)


@dataclass
class HardRule(Entry):
    text_fr: str = ""
    applies_to: list[str] = field(default_factory=list)
    adult_age_years: int = 0             # D10: pinned here, never parsed from free text


@dataclass
class Migration(Entry):
    """Step 17: what an old contract function, condition or sim/ variable becomes (id = the old name)."""
    old_kind: str = ""                   # function | condition | trait | value | drive | relation
    becomes: str = ""                    # gesture | speech | interpretation | belief | variable | engine | removed
    to: list[str] = field(default_factory=list)   # new catalogue ids (actions, concepts, interpretations, variables)
    how: str = ""


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
    trace: list[str] = field(default_factory=list)       # the story decomposed STEP BY STEP, as the written thought would write it:
                                                         # "phase | kind | content" (checked by tools/probes.py)


@dataclass
class Forgetting(Entry):
    """The law of forgetting of one kind of record (docs/14 7.5): what the engine drops when the store is full.
    The id is the record (a component with part_of); the law is data/forgetting.toml, checked by tools/forgetting.py."""
    record: str = ""                     # a record component (entities.toml, max_count)
    protect: list[str] = field(default_factory=list)   # bool variables of the record: spared while one is true (evicted only when the whole store is protected)
    score: list[dict] = field(default_factory=list)    # terms {var, weight, cap?, kind? = value|recency, half_life_seasons?};
                                         # the lowest score is forgotten first, a tie forgets the oldest


KINDS: dict[str, type[Entry]] = {
    "entity": EntityKind, "component": Component, "variable": Variable, "property": Property,
    "action": Action, "concept": Concept, "grammar": Grammar, "interpretation": Interpretation,
    "hard_rule": HardRule, "shape": Shape, "story": Story, "site": Site, "percept_word": PerceptWord, "material": Material, "process": Process, "form": Form, "item_type": ItemType, "species": Species, "migration": Migration,
    "duration_level": DurationLevel, "illness": Illness, "forgetting": Forgetting,
}
ENGINE_MATERIALS = Path(__file__).resolve().parents[1] / "engine" / "data" / "materials.csv"
SEASONS = ("spring", "summer", "autumn", "winter")
PROCESS_CLOCKS = ("real", "calendar", "game", "life")   # docs/14 4.4: engine cycle, slow process, chosen duration; life = life clock (T08d)
ILLNESS_TRANSMISSIONS = ("contact", "air", "water", "bite", "wound", "birth")
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
        if kind == "forgetting" and "id" not in row and "record" in row:
            row = dict(row, id=row["record"])        # a law of forgetting is named after its record
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

    def words_of(self, category: str) -> list[str]:
        """The closed set of words a list variable may hold (`words_from`): the percept words of the category, and for
        `state` also the perceptible STATE properties (burning, locked, lit, wet…): one word, one meaning."""
        out = [w.id for w in self["percept_word"].values() if w.category == category]
        if category == "state":
            out += [p.id for p in self["property"].values() if p.category == "state" and p.perceptible]
        return sorted(out)

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
        p += self._check_time_fields()
        if strict:
            p += self._check_coverage()
            p += self._check_gesture_time()
        return p

    def _check_time_fields(self) -> list[str]:
        """Time and matter fields (T07). Optional: an unset field (0, empty, None) is never a problem here."""
        p = []
        for a in self["action"].values():
            if a.cadence_ms < 0:
                p.append(f"action {a.id}: cadence_ms {a.cadence_ms} < 0")
            if a.natural_end is not None and not isinstance(a.natural_end, bool):
                p.append(f"action {a.id}: natural_end must be true or false")
        for pc in self["process"].values():
            if pc.clock and pc.clock not in PROCESS_CLOCKS:
                p.append(f"process {pc.id}: clock '{pc.clock}' not in {PROCESS_CLOCKS}")
            if pc.nominal_game_s < 0:
                p.append(f"process {pc.id}: nominal_game_s {pc.nominal_game_s} < 0")
            for field_name in ("consumes", "produces"):
                for m in getattr(pc, field_name):
                    if m not in self["material"]:
                        p.append(f"process {pc.id}: {field_name} unknown material '{m}'")
        for sp in self["species"].values():
            for s in sp.sow_seasons:
                if s not in SEASONS:
                    p.append(f"species {sp.id}: sow_season '{s}' not in {SEASONS}")
            for name in ("days_to_mature", "harvest_window_days", "product_regrow_days"):
                if getattr(sp, name) < 0:
                    p.append(f"species {sp.id}: {name} < 0")
        for d in self["duration_level"].values():
            if d.game_s <= 0:
                p.append(f"duration_level {d.id}: game_s must be > 0")
        for il in self["illness"].values():
            for t in il.transmission:
                if t not in ILLNESS_TRANSMISSIONS:
                    p.append(f"illness {il.id}: transmission '{t}' not in {ILLNESS_TRANSMISSIONS}")
            for s in il.symptoms:
                if s not in self["percept_word"]:
                    p.append(f"illness {il.id}: symptom '{s}' is not a percept word")
            if not 0 <= il.lethality <= 100:
                p.append(f"illness {il.id}: lethality {il.lethality} not in 0..100")
            if il.incubation_days < 0 or il.course_days < 0:
                p.append(f"illness {il.id}: negative duration")
        return p

    def _check_gesture_time(self) -> list[str]:
        """--strict: every gesture declares how it ends and how fast the engine cycles it."""
        p = []
        for a in self["action"].values():
            if a.natural_end is None:
                p.append(f"action {a.id}: natural_end undeclared")
            if a.cadence_ms <= 0:
                p.append(f"action {a.id}: cadence_ms undeclared")
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
            if v.token and v.scale == "list" and v.list_of not in ("mref", "word", "enum", "qty", "proposition"):
                p.append(f"variable {v.id}: a list that reaches a token must declare list_of (mref, word, enum, qty, proposition)")
            if v.token and not v.holder:
                p.append(f"variable {v.id}: a token needs a holder component")
            if v.components:
                if not (v.scale == "qty" or (v.scale == "list" and v.list_of == "qty")):
                    p.append(f"variable {v.id}: components only on a qty or a list of qty")
                if "@object_vector" in v.components and v.components != ["@object_vector"]:
                    p.append(f"variable {v.id}: @object_vector stands alone")
                if len(set(v.components)) != len(v.components) or not all(re.fullmatch(r"@object_vector|[a-z][a-z0-9_]*", c) for c in v.components):
                    p.append(f"variable {v.id}: components must be unique lowercase identifiers")
            elif v.token and v.scale == "list" and v.list_of == "qty":
                p.append(f"variable {v.id}: a list of qty that reaches a token must name its components (its width)")
            if v.token and v.holder in self["component"]:
                ch = self._channel(v.holder)
                for part in v.token.split(";"):
                    m = TOKEN_PART.match(part.strip())
                    if not m:
                        p.append(f"variable {v.id}: token part '{part.strip()}' is not TYPE[.field] [(note)]")
                        continue
                    if m.group(1) not in TOKEN_CHANNELS:
                        p.append(f"variable {v.id}: unknown token type '{m.group(1)}'")
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
            if v.words_from:
                if v.scale not in ("list", "word") or (v.scale == "list" and v.list_of != "word"):
                    p.append(f"variable {v.id}: words_from only on a word or a list of words")
                if not self.words_of(v.words_from):
                    p.append(f"variable {v.id}: words_from '{v.words_from}' names no percept words")
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
                if prm.type == "enum" and not prm.ordinal and len(prm.values) > 16:
                    p.append(f"action {a.id}: param {prm.name} has more than 16 values")
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
            if touches_agent and a.contact is None:
                p.append(f"action {a.id}: a ref accepts an agent, contact must be declared (D10)")
            if a.contact and not a.party_params:
                p.append(f"action {a.id}: contact gesture without party_params (D10)")
            if (a.intimate or any(prm.intimate_values for prm in a.params)) and not a.contact:
                p.append(f"action {a.id}: an intimate gesture or manner must be a contact gesture (D10 counts its persons)")
            if a.contact:                               # any pointer of a contact gesture may be handed a person (review 10)
                for prm in a.params:
                    if prm.type == "ref" and prm.name not in a.party_params:
                        p.append(f"action {a.id}: contact gesture, ref '{prm.name}' must be a party param (D10)")
            for pp in a.party_params:
                if pp not in pnames:
                    p.append(f"action {a.id}: party param '{pp}' unknown")
            if a.contact and a.minor_person_ok and not a.minor_whitelist and a.family != "force":
                p.append(f"action {a.id}: allowed with a minor but no minor_whitelist (D10)")
            for pn, vals in a.minor_whitelist.items():
                prm = next((x for x in a.params if x.name == pn), None)
                if prm is not None and set(vals) == set(prm.values) and not prm.intimate_values:
                    p.append(f"action {a.id}: minor_whitelist on '{pn}' lists every value, it filters nothing")
            zp = next((x for x in a.params if x.name == "contact_zone"), None)
            if a.contact and a.minor_person_ok and a.family in ("care", "tool", "perceive", "grasp") and zp is None:
                p.append(f"action {a.id}: contact gesture allowed with a minor needs a contact_zone param (D10)")
            if zp is not None and a.minor_person_ok:
                allowed = set(a.minor_whitelist.get("contact_zone", []))
                if not allowed or not allowed <= set(MINOR_ZONES):
                    p.append(f"action {a.id}: contact_zone whitelist must be within {MINOR_ZONES} (D10)")
            for pn, vals in a.minor_whitelist.items():
                prm = next((x for x in a.params if x.name == pn), None)
                if prm is None or any(v not in prm.values for v in vals):
                    p.append(f"action {a.id}: minor_whitelist on unknown param or value '{pn}'")
                elif any(v in prm.intimate_values for v in vals):
                    p.append(f"action {a.id}: minor_whitelist allows an intimate value of '{pn}' (D10)")
            if any(prm.intimate_values for prm in a.params) and not a.contact:
                p.append(f"action {a.id}: has intimate values but is not declared contact")
        p += self._check_kind_tables()
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

    SITE_CATEGORIES = ("building", "work", "land", "settlement", "wild", "water", "route", "sky")
    PERCEPT_CATEGORIES = ("build", "mark", "sign", "health", "attire", "state", "weather", "strange", "color", "wound")

    def _check_kind_tables(self) -> list[str]:
        """The kinds table (sortes of the language): sites and percept words have their own ids, found nowhere else
        (a word, one meaning), and a declared category; every percept category is used by a list variable."""
        p = []
        taken: dict[str, str] = {}
        for kind in ("item_type", "material", "species", "form", "concept", "action"):
            for i in self[kind]:
                taken.setdefault(i, kind)
        for kind, cats in (("site", self.SITE_CATEGORIES), ("percept_word", self.PERCEPT_CATEGORIES)):
            for e in self[kind].values():
                if e.category not in cats:
                    p.append(f"{kind} {e.id}: category '{e.category}' not in {cats}")
                if e.id in taken:
                    p.append(f"{kind} {e.id}: the id is already a {taken[e.id]} (one word, one meaning)")
                taken.setdefault(e.id, kind)
        for s in self["site"].values():
            if s.built and s.category not in ("building", "work"):
                p.append(f"site {s.id}: only a building or a work can be built")
        used = {v.words_from for v in self["variable"].values() if v.words_from}
        for cat in self.PERCEPT_CATEGORIES:
            if cat not in used:
                p.append(f"percept words of category '{cat}': no list variable declares words_from = '{cat}'")
        for sp in self["species"].values():
            if sp.mountable and sp.kingdom != "animal":
                p.append(f"species {sp.id}: mountable only for an animal")
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
        for mg in self["migration"].values():
            if mg.becomes not in ("gesture", "speech", "interpretation", "belief", "variable", "engine", "removed"):
                p.append(f"migration {mg.id}: becomes '{mg.becomes}'")
            for t in mg.to:
                if not any(t in self[k] for k in ("action", "concept", "interpretation", "variable")):
                    p.append(f"migration {mg.id}: unknown target '{t}'")
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
        elif self["hard_rule"]["D10_minors"].adult_age_years != 18:
            p.append("hard_rule D10_minors: adult_age_years must be pinned to 18")
        for v in self["variable"].values():               # a derived belief-channel variable reads beliefs only
            if v.token and "derived" in v.writer and self._channel(v.holder) == "belief":
                if not v.reads:
                    p.append(f"variable {v.id}: derived in a belief channel, it must declare what it reads")
                for r in v.reads:
                    src = self["variable"].get(r)
                    if src is None:
                        p.append(f"variable {v.id}: reads unknown variable '{r}'")
                    elif self._channel(src.holder) not in ("belief", "perception", "own_mind", "interoception"):
                        p.append(f"variable {v.id}: reads '{r}', which carries objective truth")
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
        out = []
        for s in self["story"].values():
            if s.status == "gap" and s.note.strip():
                continue                                  # a documented gap (what is missing is said in `note`) is allowed
            if s.status != "expressible":
                out.append(f"story {s.id}: {s.status}" + (" (a gap needs a note saying what is missing)" if s.status == "gap" else ""))
        return out
