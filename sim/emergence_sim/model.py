"""Data model: NPC, Household, Village, Group, Legend. Integer state everywhere.

Ranges follow docs/npc/variables_v0.2_noyau.md: traits -100..100, values/drives/states 0..100.
"""

TRAITS = ("aggression", "courage", "empathy", "sociability", "honesty", "impulsivity",
          "curiosity", "tolerance", "justice", "grudge")
VALUES = ("kin_protection", "property_respect", "honor", "life_value", "romantic_fidelity",
          "taboo_sensitivity", "piety")
DRIVES = ("libido", "social_need", "achievement", "hoarding", "ambition")

# relation vector indices
AFF, TRUST, RESPECT, ROMANCE, FAM, GRUDGE, DEBT = range(7)
REL_FIELDS = ("affection", "trust", "respect", "romance", "familiarity", "grudge", "debt")


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class NPC:
    __slots__ = (
        "id", "first", "family", "sex", "born", "village", "origin", "hh", "job", "alive", "died", "cause",
        "tr", "val", "drv",
        "hunger", "fatigue", "lonely", "stress", "joy", "anger", "fear", "grief", "hp", "sick", "thirst",
        "skills", "coin", "partner", "partners", "engaged", "affair", "parents", "children",
        "rel", "mem", "loc", "busy_until", "plan", "plan_kind", "last_t", "outfit",
        "mentor", "apprentices", "learning", "titles", "groups", "legends", "belief",
        "exiled", "expeditions", "max_depth", "agenda", "lifelog", "tracked", "mind",
        "deeds", "outfit_changes", "pending_traj", "orient", "last_exp", "seen", "goals",
    )

    def __init__(self, id_):
        self.id = id_
        self.hh = None
        self.job = None
        self.village = None
        self.origin = None
        self.alive = True
        self.died = None
        self.cause = None
        self.tr = {}
        self.val = {}
        self.drv = {}
        self.hunger = 20
        self.fatigue = 20
        self.lonely = 30
        self.stress = 10
        self.joy = 0          # -100..100
        self.anger = 0
        self.fear = 0
        self.grief = 0
        self.hp = 100
        self.sick = 0         # 0 = healthy, else severity 1..100
        self.thirst = 0
        self.skills = {}
        self.coin = 0
        self.partner = None
        self.partners = []    # history of spouses
        self.engaged = None
        self.affair = None
        self.parents = (None, None)
        self.children = []
        self.rel = {}         # other id -> [aff, trust, respect, romance, fam, grudge, debt]
        self.mem = []         # [day, kind, about, valence, salience, extra, source, false]
        self.loc = None
        self.busy_until = 0
        self.plan = None
        self.plan_kind = "idle"
        self.last_t = 0
        self.outfit = "everyday"
        self.mentor = None
        self.apprentices = []
        self.learning = None  # craft being learned
        self.titles = []
        self.groups = []
        self.legends = []
        self.belief = 0       # belief in the world beyond the frontiers, 0..100
        self.exiled = False
        self.expeditions = 0
        self.max_depth = 0
        self.last_exp = -9999     # day of the last expedition
        self.seen = []            # recent percepts [tick, event type, agent, role, intensity], at most 6
        self.goals = []           # persistent goals {type, target, priority, since}, at most 4 (charter 9)
        self.agenda = []      # [(tick, kind, place, ref)] invitations: wedding, funeral, festival, trial
        self.lifelog = []     # indices into sim.events
        self.tracked = False
        self.mind = []        # decision traces for the mind viewer (tracked NPCs only)
        self.deeds = []
        self.outfit_changes = 0
        self.pending_traj = None
        self.orient = 0       # 0 attracted to other sex, 1 same sex, 2 both

    @property
    def name(self):
        return f"{self.first} {self.family}"

    def age(self, day, days_per_year):
        return (day - self.born) // days_per_year

    def r(self, other_id):
        v = self.rel.get(other_id)
        if v is None:
            v = [0, 0, 0, 0, 0, 0, 0]
            self.rel[other_id] = v
        return v


class Household:
    __slots__ = ("id", "village", "members", "goods", "coin", "tools", "name", "alive", "feud")

    def __init__(self, id_, village, name):
        self.id = id_
        self.village = village
        self.name = name
        self.members = []
        self.goods = {}
        self.coin = 0
        self.tools = 0        # tool units (x100 = wear points)
        self.alive = True
        self.feud = {}        # other household id -> since day


class Village:
    __slots__ = ("id", "name", "kind", "pos", "frontier", "frontier_fr", "chief", "chief_since",
                 "next_election", "decrees", "market", "prices", "treasury", "groups", "legends",
                 "unrest", "accusations", "job_targets", "known_crafts", "stats", "festival_day",
                 "chief_history", "lost_crafts", "purse")

    def __init__(self, spec):
        self.id = spec["id"]
        self.name = spec["name"]
        self.kind = spec["kind"]
        self.pos = spec["pos"]
        self.frontier = spec["frontier"]
        self.frontier_fr = spec["frontier_fr"]
        self.chief = None
        self.chief_since = 0
        self.next_election = 0
        self.decrees = {"tax_pct": 5, "theft_punishment": "fine", "famine_relief": True, "market_fee_pct": 0,
                        "kin_taboo": True, "curfew": False}
        self.market = {}
        self.prices = {}
        self.treasury = 0
        self.groups = []
        self.legends = []
        self.unrest = 0
        self.accusations = []
        self.job_targets = dict(spec["jobs"])
        self.known_crafts = set()
        self.stats = []
        self.festival_day = None
        self.chief_history = []
        self.lost_crafts = []
        self.purse = 0            # coin held by the village market (closed money loop)


class Group:
    __slots__ = ("id", "name", "kind", "village", "founder", "members", "craft", "founded", "closed", "alive")

    def __init__(self, id_, name, kind, village, founder, craft, day, closed=False):
        self.id = id_
        self.name = name
        self.kind = kind          # guild | cult | band
        self.village = village
        self.founder = founder
        self.members = [founder]
        self.craft = craft
        self.founded = day
        self.closed = closed
        self.alive = True


class Legend:
    __slots__ = ("id", "title", "frontier", "village", "hero", "day", "kind", "tellers")

    def __init__(self, id_, title, frontier, village, hero, day, kind):
        self.id = id_
        self.title = title
        self.frontier = frontier
        self.village = village
        self.hero = hero
        self.day = day
        self.kind = kind          # vanished | tale | record
        self.tellers = 0
