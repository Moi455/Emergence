"""HTN expansion (option -> contract plan) and tier-2 abstract execution.

Each executor returns (plan, hours, outcome). The plan uses only functions and
conditions of ai/CONTRAT_PNJ.md, so it validates with plan_contract.validate_plan.
Outcome is the PlanResult payload: status, reason, gains.
"""
from .model import AFF, TRUST, RESPECT, ROMANCE, FAM, GRUDGE, DEBT, clamp, Group
from . import social

OUTDOOR_SITES = {"sea", "forest", "mine", "fields", "saltpans", "quarry", "well", "shipyard", "march"}


def S(f, until=None, interrupt=None, **a):
    st = {"f": f, "a": a}
    if until:
        st["until"] = until
    if interrupt:
        st["interrupt_if"] = interrupt
    return st


def P(*steps, on_done="report"):
    return {"steps": list(steps), "on_done": on_done}


def E(n_or_id):
    return f"E{n_or_id if isinstance(n_or_id, int) else n_or_id.id}"


def ok(**gains):
    return {"status": "done", "reason": None, "gains": gains}


def fail(reason, **gains):
    return {"status": "failed", "reason": reason, "gains": gains}


def home(sim, n):
    h = sim.hh(n)
    return f"{h.village}:home:{h.id}"


def pay(sim, n, cost):
    h = sim.hh(n)
    if n.coin >= cost:
        n.coin -= cost
        return True
    if n.coin + h.coin >= cost:
        h.coin -= cost - n.coin
        n.coin = 0
        return True
    return False


# ------------------------------------------------------------------ dispatch
def execute(sim, n, c):
    k = c.key
    if k == "sleep":
        return sleep(sim, n)
    if k == "eat_home":
        h = sim.hh(n)
        h.goods["food"] = h.goods.get("food", 0) - (4 if sim.age(n) >= 12 else 3)
        n.hunger = max(0, n.hunger - 70)
        sim.move(n, home(sim, n))
        return P(S("return_home"), S("eat", item="food")), 1, ok(hunger=-70)
    if k == "eat_tavern":
        v = sim.villages[n.village]
        if v.market.get("food", 0) >= 4 and pay(sim, n, max(1, v.prices["food"] // 2)):
            v.market["food"] -= 4
            v.purse += max(1, v.prices["food"] // 2)
            n.hunger = max(0, n.hunger - 70)
            place = f"{n.village}:tavern"
            sim.move(n, place)
            pres = sim.present(place, n.id)
            if pres and sim.rng.pm(500):
                social.interact(sim, n, pres[sim.rng.below(len(pres))], place, "chat", pres)
            return P(S("go_to", place=place), S("eat", item="food")), 1, ok(hunger=-70)
        return P(S("go_to", place=f"{n.village}:tavern"), S("eat", item="food")), 1, fail("no_food_for_sale")
    if k == "ask_food":
        return ask_food(sim, n, sim.npcs[c.target])
    if k in ("steal_food", "steal_coin"):
        return steal(sim, n, k == "steal_food")
    if k == "play":
        return socialize(sim, n, f"{n.village}:square", "play", 3)
    if k == "learn":
        return learn(sim, n, sim.npcs[c.target])
    if k == "seek_master":
        return seek_master(sim, n)
    if k == "practice":
        return practice(sim, n)
    if k == "work":
        return work(sim, n)
    if k == "trade_trip":
        return trade(sim, n)
    if k == "govern":
        return govern(sim, n)
    if k in ("tavern", "square"):
        return socialize(sim, n, c.target, "chat", 2)
    if k == "visit":
        return visit(sim, n, sim.npcs[c.target], "visit")
    if k == "court":
        return visit(sim, n, sim.npcs[c.target], "court")
    if k == "pray":
        return pray(sim, n)
    if k == "mourn":
        n.grief = max(0, n.grief - 15)
        n.stress = max(0, n.stress - 5)
        place = f"{n.village}:temple"
        sim.move(n, place)
        return P(S("go_to", place=place), S("mourn")), 2, ok(grief=-15)
    if k == "care":
        return care(sim, n, sim.npcs[c.target])
    if k == "explore":
        return explore(sim, n)
    if k == "search_missing":
        return search_missing(sim, n, c.extra)
    if k == "confront":
        return confront(sim, n, sim.npcs[c.target])
    if k == "blackmail":
        return blackmail(sim, n, sim.npcs[c.target])
    if k == "campaign":
        return socialize(sim, n, c.target, "campaign", 2)
    if k == "challenge":
        return challenge(sim, n)
    if k == "found_guild":
        return found_group(sim, n, "guild", c.target)
    if k == "found_cult":
        return found_group(sim, n, "cult", None)
    if k.startswith("attend_"):
        return attend(sim, n, c.extra)
    # rest
    sim.move(n, home(sim, n))
    return P(S("return_home"), S("rest", until=["elapsed_over(3600)"])), 1, ok()


def dress(sim, n, c, plan):
    k = c.kind
    winter = sim.season() == "winter"
    mourning = n.grief >= 40
    if k == "sleep":
        o = "night"
    elif k == "attend" and c.extra and c.extra[1] in ("wedding", "festival"):
        o = "mourning" if mourning and c.extra[1] == "festival" else "festive"
    elif k == "attend" and c.extra and c.extra[1] == "funeral":
        o = "mourning"
    elif mourning:
        o = "mourning"
    elif c.key in ("govern", "campaign", "challenge"):
        o = "court"
    elif k in ("explore", "trade"):
        o = "cold" if winter else "travel"
    elif k in ("work", "learn"):
        site = sim.jobs[n.job]["site"] if n.job else "fields"
        o = "cold" if (winter and site in OUTDOOR_SITES) else "work"
    elif k == "court":
        o = "festive" if n.joy > 20 else "everyday"
    else:
        o = "cold" if (winter and c.key in ("square", "play")) else "everyday"
    if o != n.outfit:
        n.outfit = o
        n.outfit_changes += 1
    if plan is not None:
        plan["outfit"] = o


# ------------------------------------------------------------------ body
def sleep(sim, n):
    hr = sim.hour
    night = hr >= 21 or hr < 6
    hours = ((6 - hr) % 24) if night else 2
    hours = clamp(hours, 2, 10)
    if n.exiled:
        sim.move(n, f"{n.village}:wilds")
    else:
        sim.move(n, home(sim, n))
    return (P(S("return_home"), S("sleep", until=["time_after(360)"], interrupt=["attacked", "hears(call_for_help)"])),
            hours, ok(fatigue=-12 * hours))


def ask_food(sim, n, m):
    place = home(sim, m)
    sim.move(n, place)
    plan = P(S("go_to", entity=E(m)), S("request", entity=E(m), proposal="F:share_food"))
    r = m.rel.get(n.id)
    hm = sim.hh(m)
    will = (r[AFF] + r[TRUST] // 2 if r else -20) + m.tr["empathy"] // 2 + (50 if sim.close_kin(m, n) else 0)
    if will > 20 and hm.goods.get("food", 0) >= 40:
        hm.goods["food"] -= 30
        h = sim.hh(n)
        h.goods["food"] = h.goods.get("food", 0) + 30
        sim.rel_add(n, m.id, aff=8, trust=6, debt=10)
        sim.rel_add(m, n.id, aff=2)
        sim.remember(n, "helped", m.id, 40, 40)
        return plan, 2, ok(food=30)
    sim.rel_add(n, m.id, aff=-5)
    return plan, 2, fail("refused")


def pray(sim, n):
    place = f"{n.village}:temple"
    sim.move(n, place)
    n.stress = max(0, n.stress - 12)
    n.grief = max(0, n.grief - 6)
    n.joy = clamp(n.joy + 3, -100, 100)
    pres = sim.present(place, n.id)
    for m in pres:
        if m.job == "priest" and sim.rng.pm(400):
            social.interact(sim, m, n, place, "comfort", pres)
            break
    return P(S("go_to", place=place), S("pray")), 1, ok(stress=-12)


def care(sim, n, m):
    sim.move(n, home(sim, n))
    healer = n.job == "healer"
    gain = 3 + (n.skills.get("healing", 0) // 6 if healer else n.skills.get("healing", 0) // 15)
    if healer:
        v = sim.villages[n.village]
        if v.market.get("medicine", 0) >= 2:
            v.market["medicine"] -= 2
            gain += 6
    m.sick = max(0, m.sick - gain)
    m.hp = min(100, m.hp + 3)
    sim.rel_add(m, n.id, aff=4, trust=3)
    return P(S("approach", entity=E(m)), S("heal" if healer else "assist", entity=E(m))), 2, ok(care=gain)


# ------------------------------------------------------------------ work
def work(sim, n):
    rng = sim.rng
    spec = sim.jobs[n.job]
    craft = spec["craft"]
    site = spec["site"]
    place = f"{n.village}:{site}"
    sim.move(n, place)
    h = sim.hh(n)
    v = sim.villages[n.village]
    sk = n.skills.get(craft, 0)
    season = sim.season()
    plan = work_plan(spec, place)
    # special roles
    if n.job == "healer":
        return heal_round(sim, n, plan)
    if n.job == "priest":
        pres = sim.present(f"{n.village}:temple", n.id)
        for m in pres[:3]:
            m.stress = max(0, m.stress - 5)
            sim.rel_add(m, n.id, respect=2)
        gain_skill(sim, n, craft, 1)
        return plan, 4, ok(rite=1)
    if n.job == "guard":
        gain_skill(sim, n, craft, 1)
        return plan, 4, ok(watch=1)
    if n.job == "scribe":
        gain_skill(sim, n, craft, 1)
        # a scribe keeping the accounts may uncover a chief's embezzlement
        if v.chief is not None and rng.pm(30):
            for mm in sim.npcs[v.chief].mem:
                if mm[1] == "embezzle_secret":
                    sim.remember(n, "embezzle", v.chief, -60, 80)
                    sim.ev("embezzlement_exposed", [n.id, v.chief], v.id, f"{n.name}, scribe, découvre que {sim.npcs[v.chief].name} puise dans le trésor de {v.name}")
                    sim.npcs[v.chief].mem.remove(mm)
                    break
        return plan, 4, ok(records=1)
    # productivity: skill, tools, season, age, health
    prod = (sk + 30)
    if h.tools <= 0:
        prod //= 2
    a = sim.age(n)
    if a >= 65:
        prod = prod * 6 // 10
    prod = prod * n.hp // 100
    if spec.get("seasonal"):
        prod = prod * {"spring": 10, "summer": 13, "autumn": 18, "winter": 1}[season] // 10
    if n.job == "fisher" and season == "winter":
        prod = prod * 6 // 10
    # inputs
    for g, q in sorted(spec.get("needs", {}).items()):
        need = int(q * 10)
        have = h.goods.get(g, 0)
        if have < need:
            buy = min(need - have, v.market.get(g, 0))
            cost = (buy * v.prices[g] + 9) // 10
            if buy > 0 and cost <= h.coin:
                v.market[g] -= buy
                h.coin -= cost
                v.purse += cost
                h.goods[g] = have + buy
        if h.goods.get(g, 0) < need:
            prod = prod * 3 // 10
        else:
            h.goods[g] -= need
    gains = {}
    for g, q in sorted(spec["makes"].items()):
        amount = int(q * 10) * prod // 100
        if amount > 0:
            if g == "water":
                # the well is communal: carried water goes to the village, the carrier is paid by the market
                v.market["water"] = v.market.get("water", 0) + amount
                wage = amount * v.prices["water"] * 9 // 100 + 2
                v.purse -= wage
                h.coin += wage
            else:
                h.goods[g] = h.goods.get(g, 0) + amount
            gains[g] = amount
    h.tools = max(0, h.tools - 2)
    gain_skill(sim, n, craft, 1)
    # mentor teaching an apprentice in the same shift is handled by learn()
    # accidents
    danger = spec.get("danger", 0)
    if danger:
        wx = sim.weather(n.village)
        mult = 3 if (wx == "storm" and site in OUTDOOR_SITES) else 1
        ppm = danger * 180 * mult * (110 - sk) // 100
        if rng.below(100000) < ppm // 10:
            accident(sim, n, place, danger)
            return plan, 4, fail("accident", **gains)
    return plan, 4, ok(**gains)


def work_plan(spec, place):
    f = spec["fn"]
    tool = spec["tool"]
    stop = ["hp_below(30)", "sees(danger)"]
    if f == "dig":
        body = S("dig", until=["found(ore)"], interrupt=stop + ["tool_broken"], dir="forward", length=8, tool=tool)
    elif f == "cut":
        body = S("cut", interrupt=stop, target="wood", tool=tool)
    elif f == "hunt":
        body = S("hunt", interrupt=stop, target="C:" + spec["target"])
    elif f == "harvest":
        body = S("harvest", interrupt=stop, kind=spec["target"], place=place)
    elif f == "place":
        body = S("place", block="stone", pattern="wall", tool=tool)
    elif f == "build":
        body = S("build", blueprint="C:" + spec["target"], place=place)
    elif f == "fetch_water":
        body = S("fetch_water", place=place)
    elif f == "heal":
        body = S("heal", entity="E:sick")
    elif f == "pray":
        body = S("pray")
    elif f == "observe":
        body = S("observe", place=place, interrupt=["hears(call_for_help)", "attacked"])
    else:
        body = S("craft", recipe="C:" + spec["target"])
    steps = [S("go_to", place=place)]
    if tool in ("pickaxe", "shovel", "trowel", "axe", "hoe") and f in ("dig", "cut", "place", "till", "craft", "build"):
        steps.append(S("equip", tool=tool))
    steps.append(body)
    return P(*steps, on_done="routine")


def gain_skill(sim, n, craft, base):
    s = n.skills.get(craft, 0)
    if sim.rng.below(100) < max(4, (100 - s) // 2):
        n.skills[craft] = min(100, s + base)


def heal_round(sim, n, plan):
    v = sim.villages[n.village]
    sick = [m for m in sim.villagers(n.village) if m.sick > 0 or m.hp < 50][:3]
    sk = n.skills.get("healing", 0)
    healed = 0
    for m in sick:
        g = 4 + sk // 8
        if v.market.get("medicine", 0) >= 1:
            v.market["medicine"] -= 1
            g += 6
        m.sick = max(0, m.sick - g)
        m.hp = min(100, m.hp + 5)
        sim.rel_add(m, n.id, aff=3, trust=3, respect=4)
        healed += 1
    gain_skill(sim, n, "healing", 1)
    # healers also gather simple herbs if they know the lore
    if n.skills.get("herbal_lore", 0) >= 20:
        v.market["medicine"] = v.market.get("medicine", 0) + 3
    return plan, 4, ok(patients=healed)


def accident(sim, n, place, danger):
    rng = sim.rng
    v = sim.villages[n.village]
    sev = rng.range(15, 50) + danger * 8
    if n.job == "miner" and rng.pm(250):
        # a collapse: everyone in the mine is at risk
        victims = [n] + [m for m in sim.present(place, n.id) if m.plan_kind == "work"]
        dead = []
        for m in victims:
            m.hp -= rng.range(30, 110)
            if m.hp <= 0:
                dead.append(m)
        sim.ev("collapse", [m.id for m in victims], v.id,
               f"Éboulement dans la mine de {v.name} : {len(dead)} mort(s), {len(victims) - len(dead)} blessé(s)")
        for m in dead:
            sim.die(m, "collapse")
        for m in victims:
            if m.alive:
                m.fear = clamp(m.fear + 50, 0, 100)
        return
    n.hp -= sev
    n.fear = clamp(n.fear + 30, 0, 100)
    if n.hp <= 0:
        cause = "drowned" if n.job in ("fisher",) else "accident"
        sim.die(n, cause)
    else:
        sim.ev("accident", [n.id], v.id, f"{n.name} se blesse en travaillant ({sim.jobs[n.job]['fr']})")


# ------------------------------------------------------------------ learning
def learn(sim, n, m):
    craft = n.learning
    spec_site = None
    for job, sp in sim.jobs.items():
        if sp["craft"] == craft:
            spec_site = sp["site"]
            break
    place = f"{m.village}:{spec_site or 'square'}"
    sim.move(n, place)
    ms = m.skills.get(craft, 0)
    s = n.skills.get(craft, 0)
    gained = 0
    if s < ms - 5 and sim.rng.below(100) < 35 + ms // 2:
        gained = 1 + (1 if sim.rng.pm(300 + (n.tr["curiosity"] + 100)) else 0)
        n.skills[craft] = min(ms - 5, s + gained)
    sim.rel_add(n, m.id, respect=1, fam=2, aff=1)
    sim.rel_add(m, n.id, fam=2, aff=1)
    if sim.rng.pm(300):
        social.interact(sim, m, n, place, "chat", ())
    plan = P(S("go_to", entity=E(m)), S("assist", entity=E(m), task="C:" + craft), S("observe", entity=E(m)))
    return plan, 4, ok(skill=gained)


def seek_master(sim, n):
    craft = n.learning
    place = f"{n.village}:square"
    sim.move(n, place)
    best, bs = None, None
    guilds = [g for g in sim.groups if g.alive and g.kind == "guild" and g.craft == craft and g.village == n.village]
    for m in sim.villagers(n.village, True):
        sk = m.skills.get(craft, 0)
        if sk < 40 or m.exiled or len(m.apprentices) >= 2:
            continue
        r = m.rel.get(n.id)
        s = sk + (r[AFF] + r[TRUST] if r else -10) + (40 if sim.close_kin(m, n) else 0)
        if bs is None or s > bs:
            best, bs = m, s
    plan = P(S("go_to", place=place), S("ask", entity="E:master", topic="C:" + craft))
    if best is None:
        n.stress = clamp(n.stress + 5, 0, 100)
        return plan, 2, fail("no_master")
    plan = P(S("go_to", entity=E(best)), S("request", entity=E(best), proposal="F:apprenticeship:" + craft))
    r = best.rel.get(n.id)
    will = (r[AFF] + r[TRUST] if r else 0) + best.tr["empathy"] // 2 + best.drv["achievement"] // 3 - 10
    closed = any(g.closed and best.id in g.members for g in guilds)
    if closed and not sim.close_kin(best, n):
        will -= 80
    if sim.close_kin(best, n):
        will += 60
    if will > 0:
        sim.set_mentor(n, best)
        return plan, 2, ok(mentor=best.id)
    sim.rel_add(n, best.id, aff=-3)
    return plan, 2, fail("refused" if not closed else "guild_closed")


def practice(sim, n):
    craft = n.learning
    s = n.skills.get(craft, 0)
    if sim.rng.below(100) < 10 + (n.tr["curiosity"] + 100) // 20:
        n.skills[craft] = s + 1  # a rediscovery is announced by crafts_daily
    sim.move(n, home(sim, n))
    return P(S("return_home"), S("craft", recipe="C:" + craft)), 3, ok()


# ------------------------------------------------------------------ social
def socialize(sim, n, place, mode, hours):
    sim.move(n, place)
    pres = sim.present(place, n.id)
    if mode == "play":
        pres = [m for m in pres if sim.age(m) < 14]
    k = 1 + (1 if n.tr["sociability"] > 0 else 0) + (1 if mode == "campaign" else 0)
    acts = []
    if pres:
        for _ in range(k):
            ws = []
            for m in pres:
                r = n.rel.get(m.id)
                ws.append(10 + (r[FAM] + max(0, r[AFF]) + r[ROMANCE] * 2 if r else 0))
            m = sim.rng.weighted(pres, ws)
            acts.append(social.interact(sim, n, m, place, mode, pres))
    fn = {"play": ("leisure", {"activity": "C:play"}), "campaign": ("campaign", {"entity": "E:crowd"})}.get(mode, ("chat", {"entity": "E:crowd"}))
    f, a = fn
    if pres:
        if f == "chat":
            a = {"entity": E(pres[0])}
    plan = P(S("go_to", place=place), S(f, **a), on_done="report")
    if mode == "campaign":
        sim.counts["campaign"] = sim.counts.get("campaign", 0) + 1
    if not pres:
        return plan, hours, fail("nobody_there")
    return plan, hours, ok(talks=len(acts), acts=[x for x in acts if x])


def visit(sim, n, m, mode):
    travel = 0
    if m.village != n.village:
        travel = travel_hours(sim, n.village, m.village)
    place = m.loc or home(sim, m)
    sim.move(n, place)
    plan = P(S("go_to", entity=E(m)), S("greet", entity=E(m)),
             S("flirt" if mode == "court" else "chat", entity=E(m)))
    if not m.alive or m.plan_kind in ("explore", "trade", "sleep") or (m.loc and m.loc.split(":")[0] != m.village):
        return plan, 1 + travel, fail("absent")
    acts = []
    for _ in range(2):
        acts.append(social.interact(sim, n, m, place, mode, ()))
    if sim.rng.pm(500):
        acts.append(social.interact(sim, m, n, place, mode, ()))
    return plan, 2 + travel, ok(acts=[x for x in acts if x])


def attend(sim, n, it):
    tick, kind, place, ref = it
    if it in n.agenda:
        n.agenda.remove(it)
    vid = place.split(":")[0]
    travel = travel_hours(sim, n.village, vid) if vid != n.village else 0
    sim.move(n, place)
    pres = sim.present(place, n.id)
    hours = 3 + travel
    mode = "chat"
    if kind == "funeral":
        n.grief = max(0, n.grief - 10)
        f = "mourn"
        for m in pres[:3]:
            if m.grief >= 40:
                social.interact(sim, n, m, place, "comfort", pres)
    elif kind == "wedding":
        n.joy = clamp(n.joy + 10, -100, 100)
        f = "leisure"
    else:
        n.joy = clamp(n.joy + 8, -100, 100)
        n.stress = max(0, n.stress - 10)
        f = "leisure"
    k = 2 + (n.tr["sociability"] > 30)
    acts = []
    if pres:
        for _ in range(k):
            ws = []
            for m in pres:
                r = n.rel.get(m.id)
                ws.append(15 + (r[FAM] + max(0, r[AFF]) + r[ROMANCE] * 2 if r else 0))
            m = sim.rng.weighted(pres, ws)
            acts.append(social.interact(sim, n, m, place, mode, pres))
    # at a fair, traders and households buy what they lack at the town market
    if kind == "festival":
        hold = sim.hh(n)
        town = sim.villages[vid]
        if hold.goods.get("food", 0) < 60 and town.market.get("food", 0) > 100 and pay(sim, n, town.prices["food"] * 3):
            town.market["food"] -= 30
            town.purse += town.prices["food"] * 3
            hold.goods["food"] = hold.goods.get("food", 0) + 30
    if f == "mourn":
        plan = P(S("go_to", place=place), S("mourn"))
    else:
        plan = P(S("go_to", place=place), S("leisure", activity="C:" + kind))
    return plan, hours, ok(acts=[x for x in acts if x])


# ------------------------------------------------------------------ economy
def travel_hours(sim, a, b):
    va, vb = sim.villages[a].pos, sim.villages[b].pos
    dx, dy = va[0] - vb[0], va[1] - vb[1]
    km10 = isqrt_int(int((dx * dx + dy * dy) * 100))  # km x 10
    return max(1, km10 * int(sim.C["travel_hours_per_km"] * 10) // 100)


def isqrt_int(x):
    if x <= 0:
        return 0
    r = int(x ** 0.5)
    while r * r > x:
        r -= 1
    while (r + 1) * (r + 1) <= x:
        r += 1
    return r


def trade(sim, n):
    """A trader buys what is cheap here, carries it to the village where it sells best, and returns."""
    rng = sim.rng
    v = sim.villages[n.village]
    best = None
    for dest in sim.vlist:
        if dest.id == v.id:
            continue
        fee = dest.decrees.get("market_fee_pct", 0)
        for g in sim.goods:
            if g in ("boat", "jewel") and v.market.get(g, 0) < 10:
                continue
            p0, p1 = v.prices[g], dest.prices[g] * (100 - fee) // 100
            margin = p1 - p0
            if margin > 0 and v.market.get(g, 0) >= 20:
                score = margin * 100 - travel_hours(sim, v.id, dest.id) * 10
                if best is None or score > best[0]:
                    best = (score, dest, g, p0, p1)
    sk = n.skills.get(sim.jobs[n.job]["craft"], 0)
    if best is None:
        return socialize(sim, n, f"{n.village}:square", "chat", 2)
    _, dest, g, p0, p1 = best
    th = travel_hours(sim, v.id, dest.id)
    budget = n.coin + sim.hh(n).coin // 2
    qty = min(v.market[g] // 2, budget * 10 // max(1, p0), 200 + sk * 4)  # tenths: a cart load
    if qty < 10:
        return socialize(sim, n, f"{n.village}:square", "chat", 2)
    cost = qty * p0 // 10
    pay(sim, n, cost)
    v.purse += cost
    v.market[g] -= qty
    plan = P(S("go_to", place=f"{v.id}:market"), S("take_from", place=f"{v.id}:market", item=g),
             S("go_to", place=f"{dest.id}:market", interrupt=["attacked", "sees(danger)"]),
             S("give", entity="E:buyer", item=g), S("return_home"))
    # robbery by outlaws on the road
    bands = [m for m in sim.npcs if m.alive and m.exiled]
    if bands and rng.pm(min(300, 40 * len(bands))):
        robber = bands[rng.below(len(bands))]
        robber.coin += cost
        sim.ev("robbery", [robber.id, n.id], dest.id, f"{n.name} est détroussé·e sur la route de {dest.name} par {robber.name}, hors-la-loi")
        sim.rel_add(n, robber.id, grudge=40, aff=-30)
        sim.remember(n, "theft_victim", robber.id, -60, 70)
        n.fear = clamp(n.fear + 40, 0, 100)
        sim.move(n, f"road:{v.id}-{dest.id}")
        return plan, th * 2, fail("robbed", lost=qty)
    fee = dest.decrees.get("market_fee_pct", 0)
    revenue = min(qty * dest.prices[g] // 10, dest.purse)
    dest.purse -= revenue
    toll = revenue * fee // 100
    dest.treasury += toll
    dest.market[g] = dest.market.get(g, 0) + qty
    profit = revenue - toll - cost
    n.coin += revenue - toll
    if toll > 0:
        if dest.chief is not None:
            sim.rel_add(n, dest.chief, aff=-1)
    # bring back what is cheap there and dear at home
    back = None
    for g2 in sim.goods:
        m2 = v.prices[g2] - dest.prices[g2]
        if m2 > 0 and dest.market.get(g2, 0) >= 20 and (back is None or m2 > back[0]):
            back = (m2, g2)
    if back:
        g2 = back[1]
        q2 = min(dest.market[g2] // 2, n.coin * 10 // max(1, dest.prices[g2]), 200 + sk * 4)
        if q2 >= 10:
            c_buy = q2 * dest.prices[g2] // 10
            c_sell = min(q2 * v.prices[g2] // 10, v.purse)
            n.coin -= c_buy
            dest.purse += c_buy
            dest.market[g2] -= q2
            v.market[g2] = v.market.get(g2, 0) + q2
            v.purse -= c_sell
            n.coin += c_sell
            profit += c_sell - c_buy
    # share profit with household
    h = sim.hh(n)
    share = max(0, n.coin - 40)
    h.coin += share // 2
    n.coin -= share // 2
    gain_skill(sim, n, sim.jobs[n.job]["craft"], 1)
    sim.move(n, f"{dest.id}:market")
    # meeting people at the destination market
    pres = sim.present(f"{dest.id}:market", n.id) + sim.present(f"{dest.id}:square", n.id)
    if pres:
        social.interact(sim, n, pres[rng.below(len(pres))], f"{dest.id}:market", "chat", pres)
    return plan, th * 2 + 2, ok(good=g, qty=qty, profit=profit, dest=dest.id)


def steal(sim, n, food):
    rng = sim.rng
    vid = n.village
    if n.exiled:
        # outlaws raid any village
        vid = sim.vlist[rng.below(len(sim.vlist))].id
    victims = [h for h in sim.hhs if h.alive and h.village == vid and h.id != n.hh]
    if not victims:
        return P(S("wander")), 1, fail("no_target")
    def loot(h):
        return h.goods.get("food", 0) if food else h.coin
    # prefer a rich household, and one we hold a grudge against
    def pref(h):
        g = 0
        for i in h.members:
            r = n.rel.get(i)
            if r:
                g += r[GRUDGE] - r[AFF]
        return loot(h) + g * 2
    victims.sort(key=lambda h: (-pref(h), h.id))
    h = victims[0]
    place = f"{vid}:home:{h.id}"
    sim.move(n, place)
    item = "food" if food else "coin"
    plan = P(S("go_to", place=place, interrupt=["sees(danger)"]),
             S("steal", place=place, item=item, interrupt=["sees(danger)", "addressed"]), S("flee"))
    guards = sum(1 for m in sim.villagers(vid, True) if m.job == "guard")
    owners_home = [sim.npcs[i] for i in h.members if sim.npcs[i].alive and sim.npcs[i].loc == place]
    p_caught = 200 + guards * 40 + len(owners_home) * 150 - (n.tr["courage"] + 100) // 2
    if sim.villages[vid].decrees.get("curfew") and sim.hour >= 20:
        p_caught += 150
    if rng.below(1000) < p_caught:
        witness = owners_home[0] if owners_home else None
        vname = sim.villages[vid].name
        sim.ev("theft_caught", [n.id] + ([witness.id] if witness else []), vid,
               f"{n.name} est pris·e en train de voler {'des vivres' if food else 'de l argent'} chez les {h.name} à {vname}")
        for i in h.members:
            m = sim.npcs[i]
            if m.alive:
                sim.rel_add(m, n.id, grudge=25, aff=-25, trust=-40)
                sim.remember(m, "theft_victim", n.id, -50, 60)
        if witness:
            sim.remember(witness, "saw_theft", n.id, -40, 60)
        n.joy = clamp(n.joy - 20, -100, 100)
        social.accuse(sim, n, witness or sim.npcs[h.members[0]], "theft", [witness] if witness else [])
        if witness and witness.tr["aggression"] > 30 and rng.pm(400):
            social.fight(sim, witness, n, place, owners_home, "shove")
        return plan, 1, fail("caught")
    if food:
        q = min(h.goods.get("food", 0), 40)
        h.goods["food"] -= q
        sim.hh(n).goods["food"] = sim.hh(n).goods.get("food", 0) + q
        gains = {"food": q}
    else:
        q = min(h.coin, 30)
        h.coin -= q
        n.coin += q
        gains = {"coin": q}
    sim.counts["theft_ok"] = sim.counts.get("theft_ok", 0) + 1
    if n.val["honor"] > 50:
        n.stress = clamp(n.stress + 15, 0, 100)
    return plan, 1, ok(**gains)


# ------------------------------------------------------------------ conflict
def confront(sim, n, m):
    place = m.loc or home(sim, m)
    sim.move(n, place)
    plan = P(S("approach", entity=E(m)), S("accuse", entity=E(m), fact="F:grievance"))
    if m.plan_kind in ("explore", "trade") or not m.alive:
        return plan, 1, fail("absent")
    r = n.rel[m.id]
    # reconciliation is possible with an apology
    if m.tr["empathy"] > 30 and m.tr["honesty"] > 0 and sim.rng.pm(300 + m.val["honor"] * 3):
        sim.rel_add(n, m.id, grudge=-30, aff=10)
        sim.rel_add(m, n.id, grudge=-10, aff=5)
        n.anger = max(0, n.anger - 40)
        plan["steps"].append(S("forgive", entity=E(m)))
        return plan, 1, ok(reconciled=True)
    social.interact(sim, n, m, place, "chat", sim.present(place))
    n.anger = clamp(n.anger + 20, 0, 100)
    if r[GRUDGE] >= 60 and n.tr["aggression"] > 20 and sim.age(n) >= 14:
        mode = "strike" if n.anger > 70 else "shove"
        plan["steps"].append(S("attack", entity=E(m), mode=mode))
        social.fight(sim, n, m, place, sim.present(place), mode)
        return plan, 1, ok(fight=mode)
    plan["steps"].append(S("insult", entity=E(m)))
    social._insult(sim, n, m, r, m.r(n.id), place, sim.present(place))
    return plan, 1, ok()


def blackmail(sim, n, m):
    plan = P(S("approach", entity=E(m)), S("blackmail", entity=E(m), memory="M:affair"))
    sim.move(n, m.loc or home(sim, m))
    hm = sim.hh(m)
    for mm in list(n.mem):
        if mm[1] == "affair_seen" and mm[2] == m.id:
            n.mem.remove(mm)
            break
    if hm.coin >= 20 and m.tr["courage"] < 30:
        hm.coin -= 20
        n.coin += 20
        sim.rel_add(m, n.id, grudge=40, aff=-40)
        sim.ev("blackmail", [n.id, m.id], n.village, f"{n.name} fait chanter {m.name}")
        return plan, 1, ok(coin=20)
    # refusal: the secret comes out
    sim.rel_add(m, n.id, grudge=50, aff=-50)
    if m.partner is not None and sim.npcs[m.partner].alive and m.affair is not None:
        social.expose_affair(sim, sim.npcs[m.partner], m, sim.npcs[m.affair], n)
    return plan, 1, fail("refused")


# ------------------------------------------------------------------ politics
def govern(sim, n):
    v = sim.villages[n.village]
    sim.governed[v.id] = sim.day
    place = f"{v.id}:square"
    sim.move(n, place)
    steps = [S("go_to", place=place)]
    judged = 0
    for acc in list(v.accusations)[:4]:
        v.accusations.remove(acc)
        c = sim.npcs[acc["culprit"]]
        vic = sim.npcs[acc["victim"]]
        if not c.alive:
            continue
        evidence = len(acc["witnesses"]) * 30 + (40 if acc["kind"] == "theft" else 60)
        r = n.rel.get(c.id)
        bias = (r[AFF] if r else 0) // 2 + (80 if sim.is_kin(n, c) and n.val["honor"] < 60 else 0)
        guilty = evidence - bias + n.tr["justice"] // 3 > 30
        if len(steps) < 4:
            steps.append(S("summon", entity=E(c)))
        judged += 1
        if guilty:
            pun = v.decrees["theft_punishment"] if acc["kind"] == "theft" else ("execution" if n.tr["aggression"] > 40 and n.val["life_value"] < 50 else "exile")
            punish(sim, v, n, c, vic, acc["kind"], pun)
        else:
            sim.ev("verdict", [n.id, c.id, vic.id], v.id, f"{n.name} acquitte {c.name}, accusé·e de {'vol' if acc['kind'] == 'theft' else 'meurtre'} par {vic.name}" + (" (c'est un parent)" if bias >= 80 else ""), guilty=False)
            for k in sim.npcs:
                if k.alive and (k.id == vic.id or sim.close_kin(k, vic)) and k.tr["justice"] > 20:
                    sim.rel_add(k, n.id, grudge=20, aff=-15, trust=-20)
                    sim.rel_add(k, c.id, grudge=25)
                    sim.remember(k, "verdict_unjust", n.id, -50, 70, c.id)
    # famine relief from the treasury
    relief = 0
    if v.decrees.get("famine_relief") and v.treasury > 50:
        hungry = [h for h in sim.hhs if h.alive and h.village == v.id and h.goods.get("food", 0) < 10 * len(h.members)]
        for h in hungry[:8]:
            q = min(40, v.market.get("food", 0))
            cost = q * v.prices["food"] // 10
            if q > 0 and cost <= v.treasury:
                v.treasury -= cost
                v.purse += cost
                v.market["food"] -= q
                h.goods["food"] = h.goods.get("food", 0) + q
                relief += 1
                for i in h.members:
                    sim.rel_add(sim.npcs[i], n.id, aff=4, respect=4, trust=3)
        if relief >= 3:
            sim.ev("famine_relief", [n.id], v.id, f"{n.name} distribue des vivres du trésor à {relief} foyers de {v.name}")
    # public works paid by the treasury: wages go to the poorest working households
    works = 0
    reserve = 300 + 4 * len(sim.villagers(v.id))
    if v.treasury > reserve:
        budget = (v.treasury - reserve) // 3
        poor = sorted((h for h in sim.hhs if h.alive and h.village == v.id and any(sim.npcs[i].job for i in h.members)),
                      key=lambda h: (h.coin, h.id))[:10]
        for h in poor:
            wage = budget // max(1, len(poor))
            h.coin += wage
            v.treasury -= wage
            works += 1
            for i in h.members:
                if sim.npcs[i].job:
                    sim.rel_add(sim.npcs[i], n.id, respect=2, aff=1)
    # embezzlement by a dishonest chief
    if n.tr["honesty"] < -20 and n.drv["hoarding"] > 55 and v.treasury > 100 and sim.rng.pm(60):
        take = v.treasury // 5
        v.treasury -= take
        n.coin += take
        sim.remember(n, "embezzle_secret", n.id, 10, 60)
        sim.ev("embezzlement", [n.id], v.id)
        pres = sim.present(place, n.id)
        for w in pres[:3]:
            if sim.rng.pm(150 + (w.tr["curiosity"] + 100)):
                sim.remember(w, "embezzle", n.id, -60, 80)
                sim.ev("embezzlement_exposed", [w.id, n.id], v.id, f"{w.name} surprend {n.name} à puiser dans le trésor de {v.name}")
                break
    # review decrees each season
    if sim.day % 90 == 0:
        sim.set_decrees(v, n)
    # amnesty for outlaws by a merciful chief
    if n.tr["empathy"] > 40 and sim.rng.pm(20):
        for m in sim.npcs:
            if m.alive and m.exiled and m.origin == v.id:
                m.exiled = False
                sim.ev("pardon", [n.id, m.id], v.id, f"{n.name} gracie {m.name}, qui peut revenir à {v.name}")
                h = sim.new_household(v.id, m.family)
                h.goods = {"food": 40}
                sim.join(m, h)
                break
    steps.append(S("decree", rule="F:village_rules"))
    if relief:
        steps.append(S("give", entity="E:poor", item="food"))
    return P(*steps[:6]), 3, ok(judged=judged, relief=relief, works=works)


def punish(sim, v, judge, c, vic, kind, pun):
    rng = sim.rng
    fr = {"fine": "à une amende", "stocks": "au pilori", "exile": "au bannissement", "execution": "à mort"}[pun]
    sim.ev("verdict", [judge.id, c.id, vic.id], v.id, f"{judge.name} condamne {c.name} {fr} pour {'vol' if kind == 'theft' else 'meurtre'}", guilty=True, punishment=pun)
    if pun == "fine":
        fine = min(30, c.coin + sim.hh(c).coin)
        pay(sim, c, fine)
        sim.hh(vic).coin += fine
    elif pun == "stocks":
        for m in sim.villagers(v.id):
            if m.id != c.id:
                sim.rel_add(m, c.id, respect=-5)
        c.stress = clamp(c.stress + 30, 0, 100)
        sim.rel_add(c, judge.id, grudge=20)
    elif pun == "execution":
        sim.die(c, "execution")
        return
    else:
        exile(sim, v, c, judge)


def exile(sim, v, c, judge):
    sim.rel_add(c, judge.id, grudge=50, aff=-40)
    # some go to kin in another village, the others take to the woods
    host = None
    for o, r in sorted(c.rel.items()):
        m = sim.npcs[o]
        if m.alive and m.village != v.id and r[AFF] >= 40 and not m.exiled:
            host = m
            break
    if host is not None and c.tr["aggression"] < 30:
        h = sim.hh(host)
        sim.join(c, h)
        sim.move(c, f"{h.village}:home:{h.id}")
        sim.ev("exile", [c.id, judge.id], v.id, f"{c.name}, banni·e de {v.name}, trouve refuge chez {host.name} à {sim.villages[h.village].name}")
        return
    c.exiled = True
    if c.partner is not None:
        p = sim.npcs[c.partner]
        p.partner = None
        c.partner = None
    h = sim.new_household(v.id, "bande")
    h.goods = {"food": 30}
    sim.join(c, h)
    sim.move(c, f"{v.id}:wilds")
    c.job = None
    n_out = sum(1 for m in sim.npcs if m.alive and m.exiled)
    sim.ev("exile", [c.id, judge.id], v.id, f"{c.name} est banni·e de {v.name} et vit désormais hors-la-loi")
    if n_out >= 3 and not any(g.kind == "band" and g.alive for g in sim.groups):
        g = Group(len(sim.groups), "Les Sans-Toit", "band", v.id, c.id, None, sim.day)
        g.members = [m.id for m in sim.npcs if m.alive and m.exiled]
        sim.groups.append(g)
        for m in g.members:
            sim.npcs[m].groups.append(g.id)
        sim.ev("outlaw_band", g.members, None, f"Les bannis se regroupent en une bande : « {g.name} »")


def challenge(sim, n):
    v = sim.villages[n.village]
    chief = sim.npcs[v.chief]
    place = f"{v.id}:square"
    sim.move(n, place)
    v.next_election = sim.day + 7
    sim.rel_add(chief, n.id, grudge=30, aff=-20)
    sim.ev("challenge", [n.id, chief.id], v.id, f"{n.name} conteste l'autorité de {chief.name} et exige une élection à {v.name}")
    for m in sim.present(place, n.id)[:6]:
        social.interact(sim, n, m, place, "campaign", ())
    return P(S("go_to", place=place), S("contest_claim", entity=E(chief), title="C:chief"),
             S("call_vote", question="F:new_chief", options="F:candidates")), 2, ok()


def found_group(sim, n, kind, craft):
    v = sim.villages[n.village]
    place = f"{v.id}:{'tavern' if kind == 'guild' else 'square'}"
    sim.move(n, place)
    if kind == "guild":
        name = f"Guilde des {sim.jobs[n.job]['fr']}s de {v.name}"
        closed = n.drv["hoarding"] > 60
        g = Group(len(sim.groups), name, "guild", v.id, n.id, craft, sim.day, closed)
    else:
        frontier = v.frontier_fr or "l'horizon"
        name = f"Cercle de ceux qui croient en l'au-delà de {frontier}"
        g = Group(len(sim.groups), name, "cult", v.id, n.id, None, sim.day)
    sim.groups.append(g)
    n.groups.append(g.id)
    joined = 0
    for m in sim.villagers(v.id, True):
        if m.id == n.id or m.exiled:
            continue
        r = m.rel.get(n.id)
        ok_ = (m.skills.get(craft, 0) >= 30) if kind == "guild" else (m.belief >= 45)
        if ok_ and (r[AFF] + r[RESPECT] if r else 0) > -10:
            g.members.append(m.id)
            m.groups.append(g.id)
            joined += 1
    if kind == "cult":
        for m in sim.villagers(v.id, True):
            if m.job == "priest":
                sim.rel_add(m, n.id, grudge=15, respect=-10)
    sim.ev("guild_founded" if kind == "guild" else "cult_founded", [n.id], v.id,
           f"{n.name} fonde « {name} »" + (" (fermée aux étrangers)" if kind == "guild" and g.closed else "") + f" : {joined + 1} membres")
    plan = P(S("go_to", place=place), S("found_group", name="C:" + kind, purpose="F:" + (craft or "beyond")))
    return plan, 2, ok(members=joined + 1)


# ------------------------------------------------------------------ frontier
def explore(sim, n):
    rng = sim.rng
    v = sim.villages[n.village]
    fr = v.frontier
    halving = sim.C["frontier"]["danger_halving_m"][fr]
    skill_map = {"sea": "fishing", "forest": "hunting", "mountain": "mining", "desert": "desert_ways"}
    sk = n.skills.get(skill_map[fr], 0)
    halving = halving * (100 + sk) // 100
    if fr == "sea" and sim.hh(n).goods.get("boat", 0) >= 10:
        halving = halving * 3 // 2
    halving = halving * (10 + min(n.expeditions, 10)) // 10   # knowing the land
    # how deep: the risk this NPC accepts (courage, recklessness, faith in the beyond), misjudged by a margin
    risk = 5 + (n.tr["courage"] + 100) // 8 + (n.tr["impulsivity"] + 100) // 16 + n.belief // 5   # permille of death accepted
    depth = 0
    while depth < 5000 and survive_ppm(depth + 10, halving) >= 1000000 - risk * 1000:
        depth += 10
    depth = depth * rng.range(75, 110) // 100
    # survival = 2^(-depth/halving), integer approximation in ppm
    survive = survive_ppm(depth, halving)
    hours = 8 + depth // 60
    place = f"{v.id}:march"
    sim.move(n, place)
    n.expeditions += 1
    n.last_exp = sim.day
    plan = P(S("go_to", place=place, interrupt=["unsafe", "hp_below(40)"]),
             S("investigate", place="P:beyond", interrupt=["unsafe", "hp_below(40)"]),
             S("return_home", interrupt=["attacked"]))
    if rng.below(1000000) >= survive:
        plan["fate"] = "vanish"
        plan["depth"] = depth
        return plan, hours, fail("vanished", depth=depth)
    record = depth > max((m.max_depth for m in sim.npcs if m.village == v.id), default=0)
    n.max_depth = max(n.max_depth, depth)
    n.hp -= rng.range(0, 25)
    n.fear = clamp(n.fear + depth // 40, 0, 100)
    n.belief = clamp(n.belief + 5, 0, 100)
    if record and depth >= 700:
        sim.ev("record_depth", [n.id], v.id, f"{n.name} revient de {v.frontier_fr} après s'être aventuré·e à {depth} m, plus loin que quiconque à {v.name}", depth=depth)
    # a deep return brings back a strange tale: a new legend
    if depth >= 600 and rng.pm(200 + depth // 10):
        seed = rng.pick(sim.C["legend_seeds"][fr])
        L = sim.add_legend(f"{n.name} jure avoir aperçu {seed} au-delà de {v.frontier_fr}", fr, v.id, n.id, "tale")
        n.legends.append(L.id)
        n.belief = clamp(n.belief + 15, 0, 100)
        for m in sim.villagers(v.id, True):
            r = m.rel.get(n.id)
            if r and r[RESPECT] < 90:
                sim.rel_add(m, n.id, respect=3)
    sim.ev("expedition", [n.id], v.id)
    return plan, hours, ok(depth=depth)


def survive_ppm(depth, halving):
    # 2^(-d/h) in ppm with integers: halve once per full halving, interpolate the remainder linearly
    k, rem = divmod(depth, halving)
    if k >= 20:
        return 0
    base = 1000000 >> k
    return base - (base // 2) * rem // halving


def vanish(sim, n):
    v = sim.villages[n.village]
    depth = n.plan.get("depth", 0)
    sim.ev("vanished", [n.id], v.id, f"{n.name} ne revient pas de {v.frontier_fr} (parti·e à {depth} m)", depth=depth)
    title = f"La disparition de {n.name} dans {v.frontier_fr}"
    L = sim.add_legend(title, v.frontier, v.id, n.id, "vanished")
    # kin search and grieve; the tale spreads from those who loved them
    for o, r in sorted(n.rel.items()):
        m = sim.npcs[o]
        if not m.alive:
            continue
        if r[AFF] >= 30 or sim.close_kin(m, n):
            if L.id not in m.legends:
                m.legends.append(L.id)
            m.belief = clamp(m.belief + 3, 0, 100)
            m.fear = clamp(m.fear + 20, 0, 100)
            if sim.close_kin(m, n) and sim.age(m) >= sim.ADULT and m.village == n.village:
                m.agenda.append((sim.t + 24 * 5, "search", f"{v.id}:march", n.id))
    sim.die(n, "vanished")


def search_missing(sim, n, it):
    if it in n.agenda:
        n.agenda.remove(it)
    v = sim.villages[n.village]
    lost = sim.npcs[it[3]]
    place = f"{v.id}:march"
    sim.move(n, place)
    depth = 200 + (n.tr["courage"] + 100)
    plan = P(S("go_to", place=place, interrupt=["unsafe"]), S("search", entity=E(lost), place="P:march"), S("return_home"))
    if sim.rng.below(1000000) >= survive_ppm(depth, sim.C["frontier"]["danger_halving_m"][v.frontier] * 2):
        plan["fate"] = "vanish"
        plan["depth"] = depth
        return plan, 10, fail("vanished")
    if sim.rng.pm(80):
        sim.ev("rescue", [n.id, lost.id], v.id, f"{n.name} retrouve dans {v.frontier_fr} les affaires de {lost.name}, sans trace du corps")
        n.grief = max(0, n.grief - 15)
    n.belief = clamp(n.belief + 3, 0, 100)
    return plan, 10, ok(found=False)
