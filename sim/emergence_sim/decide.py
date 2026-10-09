"""Decision loop (decide_batch) and the frozen reference decider (candidates).

decide_batch is the socket: the brain (brain.py) chooses, this module executes.
candidates() below is the old reference decider: Utility AI over <=16 candidate options, then an HTN expansion of
the chosen option into a plan of 1..6 contract steps (ai/CONTRAT_PNJ.md), then an
abstract (tier-2) execution that resolves the plan by its duration and outcome.

The decider never moves anything itself: it scores the candidates the engine
proposes. Every score keeps its factor breakdown for the mind viewer (S9).
"""
from .model import AFF, TRUST, RESPECT, ROMANCE, FAM, GRUDGE, DEBT, clamp
from . import actions
from .export import traj_begin, traj_end
from .rules import romance_ok
from .options import still_valid, REST

MAX_CAND = 16

# hourly drift of needs by plan kind: (hunger, fatigue, lonely)
DRIFT = {
    "sleep": (1, -12, 0), "work": (4, 6, 1), "learn": (4, 6, 0), "explore": (4, 6, 2), "trade": (4, 5, 1),
    "social": (3, 3, -6), "visit": (3, 3, -8), "court": (3, 3, -8), "attend": (3, 3, -6), "eat": (1, 1, 1),
    "pray": (2, 1, -1), "mourn": (2, 2, 1), "care": (3, 4, -2), "rest": (2, -3, 1), "play": (4, 4, -8),
}
OUTDOOR = {"sea", "forest", "mine", "fields", "saltpans", "quarry", "well", "shipyard", "march"}


class Cand:
    __slots__ = ("key", "kind", "u", "factors", "target", "extra")

    def __init__(self, key, kind, u, factors, target=None, extra=None):
        self.key = key
        self.kind = kind
        self.u = u
        self.factors = factors
        self.target = target
        self.extra = extra


def advance(sim, n):
    dt = sim.t - n.last_t
    if dt <= 0:
        return
    dh, df, dl = DRIFT.get(n.plan_kind, (3, 3, 2))
    n.hunger = clamp(n.hunger + dh * dt, 0, 100)
    n.fatigue = clamp(n.fatigue + df * dt, 0, 100)
    n.lonely = clamp(n.lonely + dl * dt, 0, 100)
    n.anger = max(0, n.anger - 3 * dt)
    n.fear = max(0, n.fear - 4 * dt)
    if n.hunger >= 80 or n.thirst >= 50:
        n.stress = clamp(n.stress + dt, 0, 100)
    n.last_t = sim.t


def decide_batch(sim, npcs):
    """Every NPC that must decide at this tick, in id order: list the options, ask the brain once for
    all of them (one batch, so a Transformer runs one forward pass), then execute in id order."""
    brain = sim.brain
    batch, reasons = [], []
    for n in npcs:
        reason = "plan_done"
        if n.plan is not None:
            if n.plan.get("fate") == "vanish":
                actions.vanish(sim, n)
                continue
            if n.plan.get("interrupted"):
                reason = "interrupted"
        advance(sim, n)
        if n.pending_traj is not None:
            traj_end(sim, n)
        batch.append((n, brain.options(sim, n)))
        reasons.append(reason)
    if not batch:
        return
    choices = brain.choose(sim, batch)
    for (n, cands), reason, ch in zip(batch, reasons, choices):
        if not n.alive:
            continue                      # died earlier in this tick (a fight, a verdict)
        best = cands[ch.index]
        if not still_valid(sim, n, best):
            best = REST
            sim.fallbacks += 1
        if ch.deltas:
            sim.governor.apply(sim, n, ch.deltas)
        sim.decisions += 1
        plan, hours, outcome = actions.execute(sim, n, best)
        n.plan = plan
        n.plan_kind = best.kind
        actions.dress(sim, n, best, plan)
        if n.tracked:
            trace_mind(sim, n, cands, ch.scores, best, plan, outcome, reason)
        traj_begin(sim, n, reason, cands, ch.scores, best, plan, outcome)
        sim.schedule(n, sim.t + max(1, hours))


def decide(sim, n):
    """One NPC alone (tests, tools)."""
    decide_batch(sim, [n])


def trace_mind(sim, n, cands, scores, best, plan, outcome, reason):
    keep_all = sim.end_tick is not None and sim.end_tick - sim.t <= 72
    if not keep_all and sim.day % 30 not in (0, 1):
        return
    n.mind.append({
        "t": sim.t, "why": reason, "chosen": best.key,
        "c": [[c.key, c.u, s, c.factors[:5]] for c, s in zip(cands, scores)],
        "plan": plan.get("steps") if plan else None, "out": outcome,
        "st": [n.hunger, n.fatigue, n.lonely, n.stress, n.joy, n.anger, n.grief, n.hp],
    })
    if len(n.mind) > 400:
        del n.mind[:100]


# ---------------------------------------------------------------- candidates
def candidates(sim, n):
    C = []
    h = sim.hh(n)
    v = sim.villages[n.village]
    hour = sim.hour
    age = sim.age(n)
    night = hour >= 21 or hour < 6
    adult = age >= sim.ADULT
    tr, val, drv = n.tr, n.val, n.drv
    winter = sim.season() == "winter"

    # agenda: weddings, funerals, festivals
    for it in n.agenda:
        tick, kind, place, ref = it
        if kind == "own_wedding":
            continue
        if tick - 6 <= sim.t <= tick + 4:
            u = 650 + (n.tr["sociability"] // 2 if kind == "festival" else 0)
            if kind == "funeral":
                r = n.rel.get(ref)
                u += (r[AFF] if r else 0) * 2
            if kind == "festival" and n.grief >= 50:
                u -= 300
            C.append(Cand("attend_" + kind, "attend", u, [("agenda:" + kind, u)], target=place, extra=it))

    # sleep
    u = n.fatigue * 5 + (350 if night else -250) + (150 if (hour >= 22 or hour < 5) else 0)
    C.append(Cand("sleep", "sleep", u, [("fatigue", n.fatigue * 5), ("night" if night else "day", 350 if night else -250)]))

    # eat
    if n.hunger >= 25:
        meal = 100 if hour in (7, 12, 13, 19) else 0
        u = n.hunger * 7 + meal
        if h.goods.get("food", 0) >= 4:
            C.append(Cand("eat_home", "eat", u, [("hunger", n.hunger * 7), ("mealtime", meal)]))
        elif n.coin + h.coin >= sim.price(n.village, "food") and not n.exiled:
            C.append(Cand("eat_tavern", "eat", u - 40, [("hunger", n.hunger * 7), ("costs_coin", -40)]))
        else:
            # no food: ask kin/friends, or steal
            friend = best_rel(sim, n, lambda r, m: r[AFF] + r[TRUST], same_village=True)
            if friend is not None and not n.exiled:
                C.append(Cand("ask_food", "visit", n.hunger * 6, [("hunger", n.hunger * 6), ("friend", 0)], target=friend))
            u = n.hunger * 5 - val["property_respect"] * 3 - (tr["honesty"] + 100) - (0 if not n.exiled else -150)
            C.append(Cand("steal_food", "steal", u, [("hunger", n.hunger * 5), ("property_respect", -val["property_respect"] * 3), ("honesty", -(tr["honesty"] + 100))]))

    # work / learn / play
    if age < sim.APPR:
        u = 300 + n.lonely * 2 - n.fatigue * 2 - (400 if night else 0)
        C.append(Cand("play", "play", u, [("childhood", 300), ("lonely", n.lonely * 2)]))
    elif n.exiled:
        pass
    elif n.job is None and n.learning:
        m = sim.npcs[n.mentor] if n.mentor is not None else None
        if m is not None and m.alive and m.village == n.village:
            u = 380 + drv["achievement"] - n.fatigue * 3 - (500 if night else 0)
            C.append(Cand("learn", "learn", u, [("apprenticeship", 380), ("achievement", drv["achievement"]), ("fatigue", -n.fatigue * 3)], target=m.id))
        else:
            u = 200 + drv["achievement"] + (tr["curiosity"] + 100) // 2 - (500 if night else 0)
            C.append(Cand("seek_master", "social", u, [("needs_master", 200), ("achievement", drv["achievement"])], target=f"{n.village}:square"))
            if n.skills.get(n.learning, 0) >= 10:
                C.append(Cand("practice", "work", u - 60, [("self_taught", u - 60)]))
    elif n.job is not None and age < 75:
        spec = sim.jobs[n.job]
        u = 330 + drv["achievement"] * 2 - n.fatigue * 3 - n.sick * 5 - (100 - n.hp) * 3
        f = [("duty", 330), ("achievement", drv["achievement"] * 2), ("fatigue", -n.fatigue * 3)]
        poor = 0
        if h.coin < 20:
            poor += 120
        if h.goods.get("food", 0) < 30 * len(h.members):
            poor += 80
        if poor:
            u += poor
            f.append(("household_needs", poor))
        if night:
            u -= 600
            f.append(("night", -600))
        if spec.get("seasonal") and winter:
            u -= 250
            f.append(("winter_fields", -250))
        if sim.weather(n.village) == "storm" and spec["site"] in OUTDOOR:
            sd = -150 + tr["courage"]
            u += sd
            f.append(("storm", sd))
        if sim.day % 7 == 6:
            u -= 120 + val["piety"]
            f.append(("rest_day", -120 - val["piety"]))
        if spec.get("trader"):
            C.append(Cand("trade_trip", "trade", u + 40, f + [("trade", 40)]))
        else:
            C.append(Cand("work", "work", u, f))
        if n.titles and "chief" in n.titles and sim.governed.get(v.id) != sim.day:
            ug = 520 + len(v.accusations) * 80 - (500 if night else 0)
            C.append(Cand("govern", "govern", ug, [("chief", 520), ("cases", len(v.accusations) * 80)]))

    # socialize / court / visit
    if not n.exiled:
        evening = 17 <= hour <= 21
        if adult or age >= 14:
            u = n.lonely * 4 + tr["sociability"] + (250 if evening else 0) - (200 if n.fatigue > 80 else 0) - (300 if hour < 7 else 0)
            if v.decrees.get("curfew") and hour >= 20:
                u -= 200
            C.append(Cand("tavern" if evening else "square", "social", u,
                          [("lonely", n.lonely * 4), ("sociability", tr["sociability"]), ("evening", 250 if evening else 0)],
                          target=f"{n.village}:tavern" if evening else f"{n.village}:square"))
        friend = best_rel(sim, n, lambda r, m: r[AFF] * 2 + r[FAM] - (0 if m.hh != n.hh else 999), same_village=True)
        if friend is not None:
            r = n.rel[friend]
            u = n.lonely * 3 + r[AFF] * 2 - (400 if night else 0) - 60
            C.append(Cand("visit", "visit", u, [("lonely", n.lonely * 3), ("affection", r[AFF] * 2)], target=friend))
        if adult:
            crush = best_rel(sim, n, lambda r, m: r[ROMANCE] * 3 + r[AFF] if romance_ok(sim, n, m) else -999, same_village=False)
            if crush is not None and n.rel[crush][ROMANCE] >= 20:
                r = n.rel[crush]
                faithful = n.partner is not None and n.partner != crush
                u = drv["libido"] * 2 + r[ROMANCE] * 3 + (150 if evening else -100) - (400 if night else 0) - 200
                if n.partner == crush:
                    u -= 150  # spouses meet at home anyway
                f = [("libido", drv["libido"] * 2), ("romance", r[ROMANCE] * 3)]
                if faithful:
                    pen = val["romantic_fidelity"] * 5 + 150
                    u -= pen
                    f.append(("fidelity", -pen))
                if sim.npcs[crush].village != n.village:
                    u -= 120
                C.append(Cand("court", "court", u, f, target=crush))

    # piety, mourning, care
    if not n.exiled:
        u = val["piety"] * 2 + n.grief * 3 + n.stress * 2 + (300 if sim.day % 7 == 6 and 8 <= hour <= 11 else 0) - 200
        C.append(Cand("pray", "pray", u, [("piety", val["piety"] * 2), ("grief", n.grief * 3), ("stress", n.stress * 2)]))
    if n.grief >= 40:
        C.append(Cand("mourn", "mourn", n.grief * 5 - 100, [("grief", n.grief * 5)]))
    for i in h.members:
        m = sim.npcs[i]
        if m.id != n.id and m.alive and (m.sick >= 20 or m.hp < 60) and age >= 12:
            u = val["kin_protection"] * 2 + tr["empathy"] + m.sick * 2 + (100 - m.hp) * 2 + (200 if n.job == "healer" else 0) - 100
            C.append(Cand("care", "care", u, [("kin_protection", val["kin_protection"] * 2), ("severity", m.sick * 2 + (100 - m.hp) * 2)], target=m.id))
            break

    # frontier expedition
    if adult and v.frontier and not night and n.hp >= 70:
        young = sum(1 for c in n.children if sim.npcs[c].alive and sim.age(sim.npcs[c]) < 10)
        cult = 150 if any(sim.groups[g].kind == "cult" for g in n.groups) else 0
        dread = sum(60 for m in n.mem if m[1] in ("death_kin", "death_friend") and m[5] == "vanished")
        recent = 400 if sim.day - n.last_exp < 240 else 0
        u = ((tr["curiosity"] + 100) // 2 + (tr["courage"] + 100) // 2 + n.belief + min(len(n.legends), 3) * 10 +
             min(n.expeditions, 5) * 30 + cult - young * 80 - n.fear * 2 - dread - recent - 340)
        if sim.day % 7 == 6:
            u += 150   # rest day: time for an adventure
        if h.coin < 10 and h.goods.get("food", 0) < 20:
            u += 80
        C.append(Cand("explore", "explore", u, [("curiosity", (tr["curiosity"] + 100) // 2), ("courage", (tr["courage"] + 100) // 2),
                                               ("belief", n.belief), ("legends", min(len(n.legends), 3) * 10), ("young_children", -young * 80),
                                               ("dread_of_the_frontier", -dread), ("went_recently", -recent)]))
    for it in n.agenda:
        if it[1] == "search" and sim.t <= it[0]:
            C.append(Cand("search_missing", "explore", 560, [("missing_kin", 560)], target=it[3], extra=it))
            break

    # greed: steal coin
    if adult and drv["hoarding"] > 50 and val["property_respect"] < 40:
        u = drv["hoarding"] * 2 - val["property_respect"] * 3 - (tr["honesty"] + 100) - 150 + (100 if n.exiled else 0)
        C.append(Cand("steal_coin", "steal", u, [("hoarding", drv["hoarding"] * 2), ("property_respect", -val["property_respect"] * 3)]))

    # grudge: confront
    if age >= 14:
        foe = best_rel(sim, n, lambda r, m: r[GRUDGE], same_village=True)
        if foe is not None and n.rel[foe][GRUDGE] >= 45:
            r = n.rel[foe]
            u = r[GRUDGE] * 3 + n.anger * 3 + tr["aggression"] * 2 - val["life_value"] - 300 - (300 if night else 0)
            C.append(Cand("confront", "confront", u, [("grudge", r[GRUDGE] * 3), ("anger", n.anger * 3), ("aggression", tr["aggression"] * 2)], target=foe))

    # politics
    if adult and not n.exiled:
        if v.next_election - sim.day <= 30 and drv["ambition"] >= 60 and v.chief != n.id:
            u = drv["ambition"] * 4 - 120 - (400 if night else 0)
            C.append(Cand("campaign", "social", u, [("ambition", drv["ambition"] * 4), ("election_soon", 0)], target=f"{n.village}:square"))
        if v.chief is not None and v.chief != n.id and v.unrest >= 45 and drv["ambition"] >= 70 and sim.age(n) >= 25:
            r = n.rel.get(v.chief)
            dislike = (r[GRUDGE] - r[AFF]) if r else 0
            u = drv["ambition"] * 3 + v.unrest * 3 + dislike - 250 - (400 if night else 0)
            if v.next_election - sim.day > 60:
                C.append(Cand("challenge", "social", u, [("ambition", drv["ambition"] * 3), ("unrest", v.unrest * 3), ("dislike_chief", dislike)], target=v.chief))
        if n.job and drv["ambition"] >= 65 and not any(sim.groups[g].kind == "guild" for g in n.groups):
            craft = sim.jobs[n.job]["craft"]
            if not any(g.alive and g.kind == "guild" and g.craft == craft and g.village == n.village for g in sim.groups):
                peers = sum(1 for m in sim.villagers(n.village, True) if m.skills.get(craft, 0) >= 30) if hour == 10 else 0
                if peers >= 3:
                    u = drv["ambition"] * 3 + n.skills.get(craft, 0) - 150
                    C.append(Cand("found_guild", "social", u, [("ambition", drv["ambition"] * 3), ("peers", peers)], target=craft))
        if n.belief >= 70 and drv["ambition"] >= 50 and not any(sim.groups[g].kind == "cult" for g in n.groups) and hour == 18:
            if not any(g.alive and g.kind == "cult" and g.village == n.village for g in sim.groups):
                u = n.belief * 3 + drv["ambition"] * 2 - 150
                C.append(Cand("found_cult", "social", u, [("belief", n.belief * 3), ("ambition", drv["ambition"] * 2)]))
        # blackmail with a known secret
        if tr["honesty"] < -40 and h.coin < 40:
            for mm in n.mem:
                if mm[1] == "affair_seen" and mm[2] is not None and sim.npcs[mm[2]].alive and sim.npcs[mm[2]].village == n.village:
                    u = -tr["honesty"] * 3 + drv["hoarding"] * 2 - 200
                    C.append(Cand("blackmail", "confront", u, [("dishonesty", -tr["honesty"] * 3), ("secret", 0)], target=mm[2]))
                    break

    # rest is always possible
    C.append(Cand("rest", "rest", 140 + (100 - n.fatigue) // 4 if n.fatigue > 40 else 120, [("rest", 120)]))
    return C


def best_rel(sim, n, score, same_village=True):
    best, bs = None, None
    for o in sorted(n.rel):
        m = sim.npcs[o]
        if not m.alive or m.exiled:
            continue
        if same_village and m.village != n.village:
            continue
        s = score(n.rel[o], m)
        if bs is None or s > bs:
            best, bs = o, s
    return best
