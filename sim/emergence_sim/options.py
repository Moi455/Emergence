"""Engine-side option filter for a learned decider (the Transformer).

Lists what an NPC CAN do right now, never what it SHOULD do: no utility, no
threshold on a want. Only physical, legal and hard-rule limits (age, a living
target, food in the house, a coin to pay, the romance rule, a chief to
challenge...). The model chooses among these options; the engine executes.

Targets are picked by salience (who is here, who matters in the NPC's life),
which is perception, not preference. Each option also carries its contract
form (function + arguments) so the model reads it as a CAND token of tok-1.

Order matters only when there are more than 16 options: the list is built
from the most basic options to the rarest, and the tail is dropped.
"""
from .model import AFF, TRUST, ROMANCE, FAM, GRUDGE
from .rules import romance_ok

MAX_OPTIONS = 16

EXPEDITION = {"sea": "expedition:beyond_the_sea", "mountain": "expedition:beyond_the_peaks",
              "desert": "expedition:beyond_the_dunes", "forest": "expedition:beyond_the_deep_forest"}
# job -> contract function of its daily work (CAND token), from the job's "fn" in content.json
WORK_FN_FALLBACK = "craft"


class Option:
    """Same fields as decide.Cand (actions.execute reads key, kind, target, extra), plus the contract form."""
    __slots__ = ("key", "kind", "u", "factors", "target", "extra", "fn", "args")

    def __init__(self, key, kind, fn, args=None, target=None, extra=None):
        self.key = key
        self.kind = kind
        self.u = 0
        self.factors = []
        self.target = target
        self.extra = extra
        self.fn = fn
        self.args = args or {}


def salient(sim, n, same_village=True, exclude_household=False):
    """People who matter to n, most salient first (presence, then the strength of the tie). Deterministic."""
    out = []
    for o in sorted(n.rel):
        m = sim.npcs[o]
        if not m.alive or m.exiled:
            continue
        if same_village and m.village != n.village:
            continue
        if exclude_household and m.hh == n.hh:
            continue
        r = n.rel[o]
        here = 50 if (m.loc == n.loc and n.loc is not None) else 0
        out.append((-(abs(r[AFF]) + r[GRUDGE] + r[ROMANCE] + r[FAM] // 2 + here), o))
    out.sort()
    return [o for _, o in out]


def feasible(sim, n):
    """-> list of Option (at most MAX_OPTIONS). Never filters on what n wants."""
    O = []
    h = sim.hh(n)
    v = sim.villages[n.village]
    age = sim.age(n)
    adult = age >= sim.ADULT
    hour = sim.hour
    night = hour >= 21 or hour < 6
    food = h.goods.get("food", 0)
    coin = n.coin + h.coin

    # body
    O.append(Option("sleep", "sleep", "sleep", {"l": "home"}))
    if food >= 4:
        O.append(Option("eat_home", "eat", "eat", {"i": "food", "l": "home"}))
    if not n.exiled and coin >= max(1, sim.price(n.village, "food") // 2) and v.market.get("food", 0) >= 4:
        O.append(Option("eat_tavern", "eat", "eat", {"i": "food", "l": "square"}))
    O.append(Option("rest", "rest", "rest", {"l": "home"}))

    # occupation (what the NPC's status allows)
    if age < sim.APPR:
        O.append(Option("play", "play", "leisure", {"a": "hopscotch"}))
    elif not n.exiled:
        if n.job is None and n.learning:
            m = sim.npcs[n.mentor] if n.mentor is not None else None
            if m is not None and m.alive and m.village == n.village:
                O.append(Option("learn", "learn", "assist", {"e": f"E{m.id}", "skill": n.learning}, target=m.id))
            else:
                O.append(Option("seek_master", "social", "ask", {"skill": n.learning}, target=f"{n.village}:square"))
            if n.skills.get(n.learning, 0) >= 10:
                O.append(Option("practice", "work", "craft", {"skill": n.learning}))
        elif n.job is not None:
            spec = sim.jobs[n.job]
            if spec.get("trader"):
                O.append(Option("trade_trip", "trade", "negotiate", {"offer": "goods"}))
            else:
                O.append(Option("work", "work", spec.get("fn") or WORK_FN_FALLBACK, {"skill": spec["craft"]}))
            if n.titles and "chief" in n.titles and sim.governed.get(v.id) != sim.day:
                O.append(Option("govern", "govern", "decree", {"topic": "decree"}))

    # company
    if not n.exiled:
        evening = 17 <= hour <= 21
        if age >= 14:
            place = f"{n.village}:tavern" if evening else f"{n.village}:square"
            O.append(Option("tavern" if evening else "square", "social", "chat", {"l": "square"}, target=place))
        near = salient(sim, n, same_village=True, exclude_household=True)
        for o in near[:2]:
            O.append(Option("visit", "visit", "chat", {"e": f"E{o}"}, target=o))
        if food < 4 and near:
            O.append(Option("ask_food", "visit", "request", {"e": f"E{near[0]}", "i": "food"}, target=near[0]))

    # agenda: weddings, funerals, festivals in their time window
    for it in n.agenda:
        tick, kind, place, ref = it
        if kind == "own_wedding" or not (tick - 6 <= sim.t <= tick + 4):
            continue
        fn, args = ("mourn", {}) if kind == "funeral" else ("leisure", {"a": "dancing"})
        O.append(Option("attend_" + kind, "attend", fn, args, target=place, extra=it))

    # care for a sick or hurt member of the household
    if age >= 12:
        for i in h.members:
            m = sim.npcs[i]
            if m.id != n.id and m.alive and (m.sick >= 20 or m.hp < 60):
                O.append(Option("care", "care", "heal", {"e": f"E{m.id}"}, target=m.id))
                break

    # inner life
    if not n.exiled:
        O.append(Option("pray", "pray", "pray", {}))
    if n.grief > 0:
        O.append(Option("mourn", "mourn", "mourn", {}))

    # romance: hard rule (adults, no kin, orientation) is the only filter
    if adult:
        crush = None
        for o in salient(sim, n, same_village=False):
            if n.rel[o][ROMANCE] > 0 and romance_ok(sim, n, sim.npcs[o]):
                crush = o
                break
        if crush is not None:
            O.append(Option("court", "court", "flirt", {"e": f"E{crush}"}, target=crush))

    # conflict and crime: possible, never encouraged by the engine
    if age >= 14:
        foe = None
        best = 0
        for o in salient(sim, n, same_village=True):
            g = n.rel[o][GRUDGE]
            if g > best:
                foe, best = o, g
        if foe is not None:
            O.append(Option("confront", "confront", "threaten", {"e": f"E{foe}"}, target=foe))
        O.append(Option("steal_food", "steal", "steal", {"i": "food"}))
        O.append(Option("steal_coin", "steal", "steal", {"offer": "goods"}))
    if adult:
        for mm in n.mem:
            if mm[1] == "affair_seen" and mm[2] is not None and sim.npcs[mm[2]].alive and sim.npcs[mm[2]].village == n.village:
                O.append(Option("blackmail", "confront", "blackmail", {"e": f"E{mm[2]}"}, target=mm[2]))
                break

    # the frontier (daylight departures, fit enough to walk)
    if adult and v.frontier and not night and n.hp >= 50:
        O.append(Option("explore", "explore", "go_to", {"p": EXPEDITION[v.frontier]}))
    for it in n.agenda:
        if it[1] == "search" and sim.t <= it[0]:
            O.append(Option("search_missing", "explore", "search", {"p": EXPEDITION.get(v.frontier, "")}, target=it[3], extra=it))
            break

    # politics
    if adult and not n.exiled:
        if v.next_election - sim.day <= 30 and v.chief != n.id:
            O.append(Option("campaign", "social", "campaign", {"e": "self"}, target=f"{n.village}:square"))
        if v.chief is not None and v.chief != n.id and age >= 25 and v.next_election - sim.day > 60:
            O.append(Option("challenge", "social", "contest_claim", {"e": f"E{v.chief}", "title": "mayor"}, target=v.chief))
        if n.job and hour == 10 and not any(sim.groups[g].kind == "guild" for g in n.groups):
            craft = sim.jobs[n.job]["craft"]
            if not any(g.alive and g.kind == "guild" and g.craft == craft and g.village == n.village for g in sim.groups):
                peers = sum(1 for m in sim.villagers(n.village, True) if m.skills.get(craft, 0) >= 30)
                if peers >= 3:
                    O.append(Option("found_guild", "social", "found_group", {"skill": craft}, target=craft))
        if hour == 18 and not any(sim.groups[g].kind == "cult" for g in n.groups):
            if not any(g.alive and g.kind == "cult" and g.village == n.village for g in sim.groups):
                O.append(Option("found_cult", "social", "found_group", {"f": "legend:gods"}))
    return O[:MAX_OPTIONS]


def still_valid(sim, n, c):
    """Options are listed for every waking NPC before any of them acts (one batch per tick).
    An earlier NPC of the same batch may have used the food or ended a life; such an option falls back to rest."""
    if isinstance(c.target, int) and not sim.npcs[c.target].alive:
        return False
    if c.key == "eat_home" and sim.hh(n).goods.get("food", 0) < 4:
        return False
    if c.key == "eat_tavern" and sim.villages[n.village].market.get("food", 0) < 4:
        return False
    return True


REST = Option("rest", "rest", "rest", {"l": "home"})
