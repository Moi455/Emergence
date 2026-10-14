"""Speech-act interactions between two NPCs (frames, never free text: CLAUDE.md I5).

The initiator picks an act by utility (its personality, its relation to the
other, what it remembers); the other answers by its own state. Witnesses
present at the place remember public acts, which then travel as gossip.
"""
from .model import AFF, TRUST, RESPECT, ROMANCE, FAM, GRUDGE, DEBT, clamp
from .rules import romance_ok

DEED_KINDS = {"saw_theft", "theft_victim", "brawl", "murder", "affair_seen", "kindness", "embezzle", "liar",
              "heroism", "insulted", "helped", "verdict_unjust", "vanished", "betrayed", "rescued", "cowardice"}


def compat(a, b):
    d = (abs(a.tr["curiosity"] - b.tr["curiosity"]) + abs(a.tr["justice"] - b.tr["justice"]) +
         abs(a.tr["honesty"] - b.tr["honesty"]) + abs(a.tr["sociability"] - b.tr["sociability"]) +
         abs(a.val["piety"] - b.val["piety"]))
    return 30 - d // 12


def chemistry(sim, a, b):
    from .rng import hash_ints
    lo, hi = (a.id, b.id) if a.id < b.id else (b.id, a.id)
    return hash_ints(sim.seed, 911, lo, hi) % 101


def interact(sim, a, b, place, mode="chat", witnesses=()):
    """One exchange initiated by a toward b. Returns the act name."""
    sim.interactions += 1
    ra = sim.rel_add(a, b.id, fam=3)
    rb = sim.rel_add(b, a.id, fam=3)
    if ra is None or rb is None:
        return None
    a.lonely = max(0, a.lonely - 10)
    b.lonely = max(0, b.lonely - 10)
    rng = sim.rng
    ag_a, ag_b = sim.age(a), sim.age(b)
    acts, w = [], []

    def opt(name, weight):
        if weight > 0:
            acts.append(name)
            w.append(weight)

    opt("chat", 40 + a.tr["sociability"] // 2 + (30 if mode in ("chat", "play", "visit") else 0))
    gossip = pick_gossip(a, b)
    if gossip is not None and ag_a >= 10:
        opt("gossip", 25 + a.tr["sociability"] // 4 + (20 if place.endswith("tavern") else 0))
    if a.legends and ag_a >= 8:
        unknown = [l for l in a.legends if l not in b.legends]
        if unknown:
            opt("legend", 8 + a.belief // 3 + (25 if place.endswith("tavern") else 0) + (40 if mode == "campaign_cult" else 0))
    if ra[AFF] > 30:
        opt("compliment", 10 + a.tr["empathy"] // 5 + ra[AFF] // 5)
    if ra[GRUDGE] > 30 or (a.anger > 40 and a.tr["aggression"] > 20):
        opt("insult", 5 + ra[GRUDGE] // 2 + max(0, a.tr["aggression"]) // 4 + a.anger // 3)
    if romance_ok(sim, a, b) and (a.partner is None or a.partner == b.id or a.val["romantic_fidelity"] < 35):
        if a.partner is None or a.partner == b.id or a.drv["libido"] > 60:
            opt("flirt", 5 + a.drv["libido"] // 3 + ra[ROMANCE] // 2 + (60 if mode == "court" else 0) + (25 if a.partner is None and b.partner is None else 0))
        if (a.partner is None and b.partner is None and a.engaged is None and b.engaged is None
                and ra[ROMANCE] >= 55 and ra[AFF] >= 35):
            opt("propose", 50 + (60 if mode == "court" else 0))
    if b.grief >= 40:
        opt("comfort", a.tr["empathy"] // 2 + ra[AFF] // 2 + 10)
    if a.tr["honesty"] < -50 and ag_a >= 14:
        rival = None
        for o, r in sorted(a.rel.items()):
            if r[GRUDGE] >= 40 and o in b.rel and o != b.id and sim.npcs[o].alive:
                rival = o
                break
        if rival is not None:
            opt("deceive", 3 + ra[GRUDGE] // 8 + (-a.tr["honesty"] - 50) // 5)
    if mode == "campaign":
        opt("lobby", 120)
    if mode == "cult":
        opt("legend", 120)
    if not acts:
        return None
    act = rng.weighted(acts, w)
    fn = ACTS[act]
    fn(sim, a, b, ra, rb, place, witnesses)
    seen = PERCEIVED.get(act)
    if seen:
        sim.perceive(b, seen[0], a.id, "target", seen[1])
        if act in INTERRUPTS:
            sim.interrupt(b)          # charter 8: the situation changed, b decides again
            for w_ in witnesses[:6]:
                if w_.id not in (a.id, b.id):
                    sim.perceive(w_, seen[0], a.id, "witness", seen[1] // 2)
    return act


# act -> (event type b perceives, intensity); deceit looks like information to its target
PERCEIVED = {"chat": ("chat_overture", 15), "gossip": ("inform", 30), "deceive": ("inform", 30), "legend": ("legend", 30),
             "compliment": ("compliment", 30), "insult": ("insult", 50), "flirt": ("flirt", 40), "propose": ("proposal", 70),
             "comfort": ("help_given", 40), "lobby": ("request", 30)}
INTERRUPTS = ("insult", "propose")


def pick_gossip(a, b):
    best, bs = None, -1
    for m in a.mem:
        if m[1] in DEED_KINDS and m[2] is not None and m[2] != b.id and m[4] > bs:
            best, bs = m, m[4]
    return best


def _chat(sim, a, b, ra, rb, place, wit):
    c = compat(a, b)
    da = clamp(c // 5 + 2 + b.tr["empathy"] // 30, -3, 8)
    db = clamp(c // 5 + 2 + a.tr["empathy"] // 30, -3, 8)
    sim.rel_add(a, b.id, aff=da, trust=1)
    sim.rel_add(b, a.id, aff=db, trust=1)
    a.joy = clamp(a.joy + 2, -100, 100)
    b.joy = clamp(b.joy + 2, -100, 100)


def _gossip(sim, a, b, ra, rb, place, wit):
    m = pick_gossip(a, b)
    if m is None:
        return _chat(sim, a, b, ra, rb, place, wit)
    day, kind, about, val, sal, extra, src, false = m
    trust = rb[TRUST]
    if about is None or about == b.id:
        return
    # b already knows?
    for x in b.mem:
        if x[1] == kind and x[2] == about and x[5] == extra:
            return
    weight = clamp(50 + trust // 2, 0, 100)
    sim.remember(b, kind, about, val * weight // 100, sal * 3 // 4, extra, a.id, false)
    if val < 0:
        sim.rel_add(b, about, aff=val * weight // 400, trust=val * weight // 300, respect=val * weight // 400)
    else:
        sim.rel_add(b, about, aff=val * weight // 400, respect=val * weight // 300)
    sim.rel_add(b, a.id, trust=1, fam=1)
    m[4] = max(0, sal - 5)
    # an affair reaching the betrayed spouse
    target = sim.npcs[about]
    if kind == "affair_seen" and extra is not None:
        lover = extra
        if b.partner == about:
            expose_affair(sim, b, target, sim.npcs[lover], a)


def expose_affair(sim, spouse, cheater, lover, informer):
    sim.rel_add(spouse, cheater.id, aff=-60, trust=-80, grudge=60, romance=-50)
    sim.rel_add(spouse, lover.id, grudge=70, aff=-50)
    spouse.anger = clamp(spouse.anger + 70, 0, 100)
    spouse.joy = clamp(spouse.joy - 50, -100, 100)
    spouse.stress = clamp(spouse.stress + 40, 0, 100)
    sim.remember(spouse, "betrayed", cheater.id, -90, 95, lover.id)
    who = f" (par {informer.name})" if informer is not None else ""
    sim.ev("affair_exposed", [spouse.id, cheater.id, lover.id], spouse.village,
           f"{spouse.name} apprend la liaison de {cheater.name} avec {lover.name}{who}")
    # separation if the betrayal outweighs the bond
    r = spouse.rel.get(cheater.id)
    if r and r[AFF] < -10 and spouse.val["romantic_fidelity"] >= 40 and spouse.partner == cheater.id:
        separate(sim, spouse, cheater)


def separate(sim, a, b):
    a.partner = None
    b.partner = None
    h = sim.hh(a)
    nh = sim.new_household(h.village, b.family)
    sim.join(b, nh)
    share = h.coin // 3
    h.coin -= share
    nh.coin = share
    nh.goods = {"food": 60, "wood": 20}
    nh.tools = 100 if b.job else 0
    sim.move(b, f"{nh.village}:home:{nh.id}")
    sim.ev("separation", [a.id, b.id], h.village, f"{a.name} et {b.name} se séparent ; {b.first} quitte la maison")


def _legend(sim, a, b, ra, rb, place, wit):
    unknown = [l for l in a.legends if l not in b.legends]
    if not unknown:
        return _chat(sim, a, b, ra, rb, place, wit)
    lid = unknown[sim.rng.below(len(unknown))]
    gain = clamp(4 + rb[TRUST] // 15 + (b.tr["curiosity"] + 100) // 40, 0, 15)
    b.legends.append(lid)
    if len(b.legends) > 12:
        b.legends.pop(0)
    b.belief = clamp(b.belief + gain, 0, 100)
    sim.legends[lid].tellers += 1
    sim.rel_add(b, a.id, aff=2, fam=2)
    for w in wit[:4]:
        if w.id != b.id and lid not in w.legends and sim.rng.pm(300):
            w.legends.append(lid)
            w.belief = clamp(w.belief + gain // 2, 0, 100)


def _compliment(sim, a, b, ra, rb, place, wit):
    sim.rel_add(b, a.id, aff=4 + b.val["honor"] // 30, trust=1)
    sim.rel_add(a, b.id, aff=1)
    b.joy = clamp(b.joy + 5, -100, 100)


def _insult(sim, a, b, ra, rb, place, wit):
    sim.rel_add(b, a.id, aff=-10, grudge=8 + max(0, b.tr["grudge"]) // 10, trust=-3)
    b.anger = clamp(b.anger + 20 + b.val["honor"] // 5, 0, 100)
    a.anger = max(0, a.anger - 10)
    sim.remember(b, "insulted", a.id, -30, 30)
    for w in wit[:6]:
        if w.id not in (a.id, b.id):
            sim.rel_add(w, a.id, respect=-2)
    # retaliation: a brawl
    if b.anger > 55 and b.tr["aggression"] + b.tr["courage"] // 2 > 10 and sim.age(b) >= 14:
        fight(sim, b, a, place, wit, "strike" if b.anger > 80 else "shove")


def fight(sim, a, b, place, wit, mode):
    rng = sim.rng
    sa = 50 + a.tr["aggression"] // 4 + a.tr["courage"] // 4 + min(sim.age(a), 40) - max(0, sim.age(a) - 50) + a.hp // 4
    sb = 50 + b.tr["aggression"] // 4 + b.tr["courage"] // 4 + min(sim.age(b), 40) - max(0, sim.age(b) - 50) + b.hp // 4
    win, lose = (a, b) if rng.below(sa + sb) < sa else (b, a)
    dmg = rng.range(5, 25) if mode == "shove" else rng.range(15, 45)
    lose.hp -= dmg
    win.hp -= dmg // 3
    lethal = False
    if mode == "strike" and win.val["life_value"] < 30 and win.anger > 85 and rng.pm(80):
        lose.hp = 0
        lethal = True
    for x, y in ((a, b), (b, a)):
        sim.rel_add(x, y.id, grudge=15, aff=-15)
        sim.perceive(y, mode, x.id, "target", 80 if mode == "strike" else 60)
        sim.interrupt(y)
    lose.fear = clamp(lose.fear + 30, 0, 100)
    vname = sim.villages[a.village].name
    witnesses = [w for w in wit if w.id not in (a.id, b.id)][:8]
    for w in witnesses:
        sim.remember(w, "brawl", a.id, -20, 40, b.id)
        sim.perceive(w, mode, a.id, "witness", 40)
    if lose.hp <= 0:
        kind = "murder" if lethal else "brawl"
        sim.ev("murder" if lethal else "brawl", [win.id, lose.id], a.village,
               f"{win.name} tue {lose.name} lors d'une rixe à {vname}" if lethal else f"Rixe à {vname} : {lose.name} succombe aux coups de {win.name}")
        for w in witnesses:
            sim.remember(w, "murder", win.id, -90, 95, lose.id)
        sim.die(lose, "murder" if lethal else "fight", killer=win.id)
        accuse(sim, win, lose, "murder", witnesses)
        # the victim's kin swear revenge
        for o in sorted(lose.rel):
            k = sim.npcs[o]
            if k.alive and sim.close_kin(k, lose) and k.id != win.id:
                sim.rel_add(k, win.id, grudge=60, aff=-60)
                k.anger = clamp(k.anger + 50, 0, 100)
    else:
        sim.ev("brawl", [a.id, b.id], a.village, f"Bagarre entre {a.name} et {b.name} à {vname} ({lose.first} a le dessous)")


def accuse(sim, culprit, victim, kind, witnesses):
    v = sim.villages[culprit.village]
    v.accusations.append({"culprit": culprit.id, "victim": victim.id, "kind": kind,
                          "witnesses": [w.id for w in witnesses], "day": sim.day})


def _flirt(sim, a, b, ra, rb, place, wit):
    if not romance_ok(sim, a, b):  # hard rule, checked twice
        return
    chem = chemistry(sim, a, b) + compat(a, b) // 2
    pick = 45 - b.drv["libido"] // 10 + (30 if (b.partner is not None and b.partner != a.id) else 0)
    if b.partner is not None and b.partner != a.id:
        pick += b.val["romantic_fidelity"] // 2
    sim.rel_add(a, b.id, romance=3 + chem // 20)
    if chem >= pick:
        sim.rel_add(b, a.id, romance=4 + chem // 15, aff=3)
        b.joy = clamp(b.joy + 5, -100, 100)
        a.joy = clamp(a.joy + 6, -100, 100)
        # an affair starts when both are taken (by others) or one is, and both are in love
        rab, rba = a.rel[b.id][ROMANCE], b.rel[a.id][ROMANCE]
        taken = (a.partner is not None and a.partner != b.id) or (b.partner is not None and b.partner != a.id)
        if taken and rab >= 60 and rba >= 60 and a.affair is None and b.affair is None:
            a.affair, b.affair = b.id, a.id
            sim.remember(a, "affair_secret", b.id, 40, 80)
            sim.remember(b, "affair_secret", a.id, 40, 80)
            sim.ev("affair", [a.id, b.id], a.village)
        if taken:
            cheater = a if (a.partner is not None and a.partner != b.id) else b
            other = b if cheater is a else a
            for w in wit[:6]:
                if w.id in (a.id, b.id) or sim.age(w) < 14:
                    continue
                if sim.rng.pm(250 + (w.tr["curiosity"] + 100)):
                    sim.remember(w, "affair_seen", cheater.id, -40, 70, other.id)
                    if w.id == cheater.partner:
                        expose_affair(sim, w, cheater, other, None)
    else:
        a.joy = clamp(a.joy - 6, -100, 100)
        sim.rel_add(b, a.id, aff=-1)
        if a.rel[b.id][ROMANCE] > 30 and sim.rng.pm(150):
            a.rel[b.id][ROMANCE] -= 10


def _propose(sim, a, b, ra, rb, place, wit):
    if not romance_ok(sim, a, b) or a.partner is not None or b.partner is not None:
        return
    yes = rb[ROMANCE] >= 45 and rb[AFF] >= 25
    # family approval: a feud between the houses, or parents who hate the suitor
    hostile = 0
    for p in b.parents:
        if p is not None and sim.npcs[p].alive:
            r = sim.npcs[p].rel.get(a.id)
            if r and (r[GRUDGE] >= 40 or r[AFF] <= -30):
                hostile += 1
    feud = a.hh in sim.hh(b).feud
    elope = False
    if yes and (hostile or feud):
        if rb[ROMANCE] >= 85 and ra[ROMANCE] >= 85 and (b.tr["impulsivity"] + a.tr["courage"]) > 40:
            elope = True
        elif b.val["kin_protection"] > 50:
            yes = False
    if not yes:
        a.joy = clamp(a.joy - 25, -100, 100)
        sim.rel_add(a, b.id, romance=-15)
        sim.remember(a, "rejected", b.id, -40, 50)
        return
    if elope:
        sim.marry(a, b, elope=True)
        for p in b.parents:
            if p is not None and sim.npcs[p].alive:
                sim.rel_add(sim.npcs[p], a.id, grudge=30)
                sim.rel_add(sim.npcs[p], b.id, aff=-20)
        return
    a.engaged, b.engaged = b.id, a.id
    wed = sim.t + 5 * 24 + (14 - sim.hour) % 24
    for x in (a, b):
        x.agenda.append((wed, "own_wedding", None, (b if x is a else a).id))
        x.joy = clamp(x.joy + 30, -100, 100)
    sim.ev("engagement", [a.id, b.id], b.village, f"{a.name} demande {b.name} en mariage : c'est oui")


def _comfort(sim, a, b, ra, rb, place, wit):
    b.grief = max(0, b.grief - 8 - a.tr["empathy"] // 20)
    b.stress = max(0, b.stress - 5)
    sim.rel_add(b, a.id, aff=6, trust=4)
    sim.rel_add(a, b.id, aff=2)
    sim.remember(b, "kindness", a.id, 30, 30)


def _deceive(sim, a, b, ra, rb, place, wit):
    rival = None
    for o, r in sorted(a.rel.items()):
        if r[GRUDGE] >= 40 and o in b.rel and o != b.id and sim.npcs[o].alive:
            rival = o
            break
    if rival is None:
        return
    lie = sim.rng.pick(["saw_theft", "embezzle", "cowardice"])
    sim.remember(b, lie, rival, -40, 50, None, a.id, True)
    sim.rel_add(b, rival, aff=-8 * (50 + rb[TRUST] // 2) // 100, trust=-6)
    sim.counts["lies"] = sim.counts.get("lies", 0) + 1


def _lobby(sim, a, b, ra, rb, place, wit):
    gain = clamp(3 + compat(a, b) // 10 + a.tr["sociability"] // 25, 0, 10)
    sim.rel_add(b, a.id, respect=gain, aff=gain // 2, trust=gain // 2)


ACTS = {"chat": _chat, "gossip": _gossip, "legend": _legend, "compliment": _compliment, "insult": _insult,
        "flirt": _flirt, "propose": _propose, "comfort": _comfort, "deceive": _deceive, "lobby": _lobby}
