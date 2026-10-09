"""Sim: population setup, hourly event-driven loop, and daily systems
(economy, health, life cycle, politics, crafts, festivals, statistics).

Time unit: 1 tick = 1 game hour. Each NPC is woken only when its plan ends
(bucket per tick), never polled. Goods are stored in tenths of a unit (int).
"""
import json
import math
import os

from . import SCHEMA_VERSION
from .rng import Rng, hash_ints
from .model import (NPC, Household, Village, Group, Legend, TRAITS, VALUES, DRIVES,
                    AFF, TRUST, RESPECT, ROMANCE, FAM, GRUDGE, DEBT, clamp)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONTENT = os.path.join(HERE, "..", "data", "content.json")

# Event kinds kept in the chronicle (others are counted only).
NOTABLE = {
    "birth", "death", "wedding", "engagement", "elopement", "separation", "apprenticeship", "craft_lost",
    "craft_lost_village", "craft_rediscovered", "theft_caught", "brawl", "murder", "verdict", "exile", "election",
    "decree", "challenge", "embezzlement", "embezzlement_exposed", "expedition", "vanished", "record_depth",
    "legend_born", "epidemic", "epidemic_end", "accident", "collapse", "adoption", "guild_founded", "cult_founded",
    "feud", "feud_peace", "affair_exposed", "festival", "robbery", "outlaw_band", "pardon", "famine",
    "famine_relief", "migration", "blackmail", "lie_exposed", "orphaned", "rescue", "chief_died", "starvation",
}

DPY_DEFAULT = 360
ESSENTIAL = ("food", "water", "wood", "salt")


def load_content(path=None):
    with open(path or DEFAULT_CONTENT, encoding="utf-8") as f:
        return json.load(f)


class Sim:
    def __init__(self, seed=1, content=None, traj_ppm=0, traj_path=None, tracked=12, live_hours=48, brain=None):
        self.seed = seed
        from .brain import ReferenceBrain, Governor
        self.brain = brain or ReferenceBrain()
        self.governor = Governor()
        self.fallbacks = 0
        self.C = content or load_content()
        cal = self.C["calendar"]
        self.DPM = cal["days_per_month"]
        self.MPY = cal["months_per_year"]
        self.DPY = self.DPM * self.MPY
        self.ADULT = self.C["adult_age"]
        self.APPR = self.C["apprentice_age"]
        self.ELDER = self.C["elder_age"]
        self.rng = Rng(seed)
        self.t = 0
        self.npcs = []
        self.hhs = []
        self.vlist = []
        self.villages = {}
        self.groups = []
        self.legends = []
        self.events = []
        self.counts = {}
        self.places = {}
        self.buckets = {}
        self.jobs = self.C["jobs"]
        self.goods = list(self.C["goods"].keys())
        self.crafts = self.C["crafts"]
        self.norms = self.C["norms"]
        self.monthly = []
        self.craft_series = []
        self.live = []           # last live_hours of positions
        self.live_hours = live_hours
        self.end_tick = None
        self.traj_ppm = traj_ppm
        self.traj_path = traj_path
        self.traj_f = open(traj_path, "w", encoding="utf-8") if traj_path and traj_ppm > 0 else None
        self.traj_count = 0
        self.decisions = 0
        self.interactions = 0
        self.n_tracked = tracked
        self.lost_world = set()
        self.governed = {}      # village id -> last day the chief held council
        self.epidemic = {}       # village id -> start day
        self.world_crafts = set()
        self.mort_ppm = self._mortality_table()
        self.setup()

    # ------------------------------------------------------------------ time
    @property
    def day(self):
        return self.t // 24

    @property
    def hour(self):
        return self.t % 24

    def month(self, day=None):
        d = self.day if day is None else day
        return (d // self.DPM) % self.MPY

    def year(self, day=None):
        d = self.day if day is None else day
        return d // self.DPY

    def season(self, day=None):
        return self.C["calendar"]["seasons"][self.month(day)]

    def age(self, n):
        return (self.day - n.born) // self.DPY

    def weather(self, vid, day=None):
        d = self.day if day is None else day
        h = hash_ints(self.seed, 77, d, ord(vid[0]) * 31 + len(vid)) % 100
        s = self.season(d)
        if s == "winter":
            return "snow" if h < 30 else "storm" if h < 45 else "rain" if h < 60 else "clear"
        if s == "autumn":
            return "storm" if h < 15 else "rain" if h < 45 else "clear"
        return "storm" if h < 5 else "rain" if h < 25 else "clear"

    # ------------------------------------------------------------- helpers
    def _mortality_table(self):
        # Natural mortality per day in ppm, by age. Precomputed once (rounded ints).
        tab = []
        for a in range(0, 121):
            if a < 5:
                py = 0.03
            elif a < 15:
                py = 0.004
            else:
                py = 0.002 + 0.0008 * math.exp(0.1 * (a - 20))
            py = min(py, 0.9)
            tab.append(int(round(py / DPY_DEFAULT * 1e6)))
        return tab

    def ev(self, kind, actors=(), village=None, text="", **data):
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if kind not in NOTABLE:
            return None
        e = {"i": len(self.events), "t": self.t, "k": kind, "a": list(actors), "v": village, "x": text}
        if data:
            e["d"] = data
        self.events.append(e)
        for a in actors:
            if a is not None and 0 <= a < len(self.npcs):
                self.npcs[a].lifelog.append(e["i"])
        return e

    def schedule(self, n, until):
        if until <= self.t:
            until = self.t + 1
        n.busy_until = until
        self.buckets.setdefault(until, []).append(n.id)

    def interrupt(self, n):
        """Wake an NPC at the next tick (its old wake-up entry becomes stale)."""
        if n.alive and n.busy_until > self.t + 1 and n.plan_kind not in ("explore", "trade"):
            if n.plan is not None:
                n.plan["interrupted"] = True
            self.schedule(n, self.t + 1)

    def move(self, n, place):
        if n.loc == place:
            return
        if n.loc is not None:
            s = self.places.get(n.loc)
            if s is not None:
                s.discard(n.id)
        n.loc = place
        if place is not None:
            self.places.setdefault(place, set()).add(n.id)

    def present(self, place, exclude=None):
        s = self.places.get(place)
        if not s:
            return []
        out = []
        for i in sorted(s):
            if i == exclude:
                continue
            m = self.npcs[i]
            if m.alive and m.busy_until > self.t and m.plan_kind != "sleep":
                out.append(m)
        return out

    def villagers(self, vid, adults_only=False):
        out = []
        for h in self.hhs:
            if h.alive and h.village == vid:
                for i in h.members:
                    n = self.npcs[i]
                    if n.alive and (not adults_only or self.age(n) >= self.ADULT):
                        out.append(n)
        out.sort(key=lambda n: n.id)
        return out

    def anc2(self, n):
        s = {n.id}
        for p in n.parents:
            if p is not None:
                s.add(p)
                pp = self.npcs[p].parents
                for g in pp:
                    if g is not None:
                        s.add(g)
        return s

    def is_kin(self, a, b):
        """Related within the taboo degree: parent/child, siblings, grandparents, aunts/uncles, first cousins."""
        return bool(self.anc2(a) & self.anc2(b))

    def close_kin(self, a, b):
        return (b.id in a.parents or a.id in b.parents or a.partner == b.id or
                (a.parents[0] is not None and a.parents[0] in b.parents) or
                (a.parents[1] is not None and a.parents[1] in b.parents))

    def perceive(self, n, etype, agent, role, intensity):
        """n saw or underwent something (event type of the model vocabulary). Perception only: no state change."""
        if not n.alive:
            return
        n.seen.append([self.t, etype, agent, role, intensity])
        if len(n.seen) > 6:
            del n.seen[0]

    def remember(self, n, kind, about, valence, salience, extra=None, source=None, false=False):
        if not n.alive:
            return
        cap = self.norms["max_memories_per_npc"]
        n.mem.append([self.day, kind, about, valence, salience, extra, source, false])
        if len(n.mem) > cap:
            k = min(range(len(n.mem)), key=lambda i: (n.mem[i][4], n.mem[i][0]))
            n.mem.pop(k)

    def rel_add(self, n, other, aff=0, trust=0, respect=0, romance=0, fam=0, grudge=0, debt=0):
        if n.id == other or not n.alive:
            return
        r = n.rel.get(other)
        if r is None:
            if len(n.rel) >= self.norms["max_relations_per_npc"]:
                self._evict_rel(n)
            r = [0, 0, 0, 0, 0, 0, 0]
            n.rel[other] = r
        r[AFF] = clamp(r[AFF] + aff, -100, 100)
        r[TRUST] = clamp(r[TRUST] + trust, -100, 100)
        r[RESPECT] = clamp(r[RESPECT] + respect, -100, 100)
        r[ROMANCE] = clamp(r[ROMANCE] + romance, 0, 100)
        r[FAM] = clamp(r[FAM] + fam, 0, 100)
        r[GRUDGE] = clamp(r[GRUDGE] + grudge, 0, 100)
        r[DEBT] = clamp(r[DEBT] + debt, -100, 100)
        return r

    def _evict_rel(self, n):
        worst, wv = None, None
        for o, r in n.rel.items():
            m = self.npcs[o]
            if m.id == n.partner or m.id in n.parents or m.id in n.children:
                continue
            v = abs(r[AFF]) + r[FAM] + r[GRUDGE] + r[ROMANCE] + (0 if m.alive else -500)
            if wv is None or v < wv or (v == wv and o < worst):
                worst, wv = o, v
        if worst is not None:
            del n.rel[worst]

    def skill(self, n, craft):
        return n.skills.get(craft, 0)

    def price(self, vid, good):
        return self.villages[vid].prices.get(good, self.C["goods"][good]["base_price"])

    def hh(self, n):
        return self.hhs[n.hh]

    # --------------------------------------------------------------- setup
    def new_npc(self, village, sex, born, family, parents=(None, None), first=None):
        n = NPC(len(self.npcs))
        rng = self.rng
        names = self.C["names"][village]
        n.sex = sex
        n.first = first or rng.pick(names[sex])
        n.family = family
        n.born = born
        n.village = village
        n.origin = village
        n.parents = parents
        ps = [self.npcs[p] for p in parents if p is not None]
        for k in TRAITS:
            base = rng.trait()
            if ps:
                inh = sum(p.tr[k] for p in ps) // len(ps)
                base = (base + inh) // 2
            n.tr[k] = clamp(base, -100, 100)
        for k in VALUES:
            base = rng.trait(0, 100)
            if ps:
                base = (base + sum(p.val[k] for p in ps) // len(ps)) // 2
            n.val[k] = base
        for k in DRIVES:
            n.drv[k] = rng.trait(0, 100)
        r = rng.below(100)
        n.orient = 0 if r < 88 else 1 if r < 94 else 2
        n.belief = clamp(rng.trait(0, 60), 0, 100)
        self.npcs.append(n)
        for p in ps:
            p.children.append(n.id)
            self.rel_add(p, n.id, aff=80, trust=50, fam=90)
            self.rel_add(n, p.id, aff=70, trust=70, respect=40, fam=90)
        return n

    def new_household(self, village, name):
        h = Household(len(self.hhs), village, name)
        self.hhs.append(h)
        return h

    def join(self, n, h):
        if n.hh is not None and n.hh != h.id:
            old = self.hhs[n.hh]
            if n.id in old.members:
                old.members.remove(n.id)
            if not [i for i in old.members if self.npcs[i].alive]:
                old.alive = False
        n.hh = h.id
        if n.id not in h.members:
            h.members.append(n.id)
        n.village = h.village

    def pick_job(self, v, rng):
        jobs = sorted(v.job_targets.items())
        return rng.weighted([j for j, _ in jobs], [w for _, w in jobs])

    def setup(self):
        rng = self.rng
        D = self.DPY
        for spec in self.C["villages"]:
            v = Village(spec)
            self.vlist.append(v)
            self.villages[v.id] = v
        for v in self.vlist:
            fams = self.C["names"][v.id]["family"]
            target = next(s["pop"] for s in self.C["villages"] if s["id"] == v.id)
            pop = 0
            couples = []
            while pop < target:
                fam = rng.pick(fams)
                h = self.new_household(v.id, fam)
                kind = rng.below(100)
                members = []
                if kind < 70:  # couple + children
                    am = rng.range(19, 58)
                    af = clamp(am + rng.range(-8, 5), 18, 56)
                    pm = self._maybe_parents(couples, am, rng)
                    m = self.new_npc(v.id, "m", -am * D - rng.below(D), fam, pm)
                    f = self.new_npc(v.id, "f", -af * D - rng.below(D), rng.pick(fams), self._maybe_parents(couples, af, rng, avoid=m))
                    m.partner, f.partner = f.id, m.id
                    m.partners.append(f.id)
                    f.partners.append(m.id)
                    for a, b in ((m, f), (f, m)):
                        self.rel_add(a, b.id, aff=rng.range(30, 90), trust=rng.range(30, 90), romance=rng.range(20, 80), fam=95, respect=30)
                    members += [m, f]
                    nk = rng.below(6) if af < 45 else rng.below(3)
                    for _ in range(nk):
                        ka = rng.range(0, max(0, min(af - 18, 20)))
                        c = self.new_npc(v.id, rng.pick(["f", "m"]), -ka * D - rng.below(D), fam, (m.id, f.id))
                        members.append(c)
                    couples.append((m, f))
                    if rng.below(100) < 15 and am > 30:   # an elder parent lives with them
                        ga = am + rng.range(20, 30)
                        g = self.new_npc(v.id, rng.pick(["f", "m"]), -ga * D - rng.below(D), fam)
                        m.parents = (g.id, None) if m.parents == (None, None) else m.parents
                        if m.parents[0] == g.id:
                            g.children.append(m.id)
                            self.rel_add(g, m.id, aff=80, trust=60, fam=95)
                            self.rel_add(m, g.id, aff=70, trust=70, respect=50, fam=95)
                        members.append(g)
                elif kind < 85:  # single adult
                    a = rng.range(18, 50)
                    s = self.new_npc(v.id, rng.pick(["f", "m"]), -a * D - rng.below(D), fam, self._maybe_parents(couples, a, rng))
                    members.append(s)
                else:  # widowed elder, maybe with a grandchild
                    a = rng.range(55, 80)
                    s = self.new_npc(v.id, rng.pick(["f", "m"]), -a * D - rng.below(D), fam)
                    members.append(s)
                for n in members:
                    self.join(n, h)
                pop += len(members)
            # jobs, skills, goods
            for h in self.hhs:
                if h.village != v.id:
                    continue
                workers = 0
                for i in h.members:
                    n = self.npcs[i]
                    a = self.age(n)
                    if a >= self.ADULT:
                        n.job = self.pick_job(v, rng)
                        cr = self.jobs[n.job]["craft"]
                        n.skills[cr] = clamp(25 + min(a - 18, 30) + rng.range(-10, 25), 20, 95)
                        if rng.below(100) < 35:
                            j2 = self.pick_job(v, rng)
                            c2 = self.jobs[j2]["craft"]
                            if c2 != cr:
                                n.skills[c2] = rng.range(10, 45)
                        n.coin = rng.range(5, 40) + (60 if self.jobs[n.job].get("trader") else 0)
                        workers += 1
                    elif a >= self.APPR:
                        n.job = None
                        par = [self.npcs[p] for p in n.parents if p is not None and self.npcs[p].job]
                        if par:
                            p = par[rng.below(len(par))]
                            cr = self.jobs[p.job]["craft"]
                            n.learning = cr
                            n.skills[cr] = rng.range(3, 20)
                            n.mentor = p.id
                            p.apprentices.append(n.id)
                    else:
                        n.job = None
                h.goods = {"food": 10 * 8 * len(h.members), "wood": 10 * 8, "water": 10 * 3 * len(h.members), "salt": 10 * 2}
                h.coin = rng.range(10, 60) * max(1, workers)
                h.tools = 100 * max(1, workers)
            # acquaintances inside the village
            vs = self.villagers(v.id)
            for n in vs:
                for _ in range(8 + (n.tr["sociability"] + 100) // 25):
                    o = vs[rng.below(len(vs))]
                    if o.id != n.id:
                        f = rng.range(10, 60)
                        a = rng.range(-20, 50)
                        self.rel_add(n, o.id, aff=a, trust=a // 2, fam=f, respect=rng.range(-10, 40))
                        self.rel_add(o, n.id, aff=a + rng.range(-15, 15), trust=a // 2, fam=f, respect=rng.range(-10, 40))
            # market stock and prices
            for g in self.goods:
                v.market[g] = self.target_stock(v, g)
                v.prices[g] = self.C["goods"][g]["base_price"]
            v.treasury = 200
            v.purse = 3000
        # merchants know merchants across villages
        traders = [n for n in self.npcs if n.job and self.jobs[n.job].get("trader")]
        for n in traders:
            for _ in range(4):
                o = traders[rng.below(len(traders))]
                if o.village != n.village:
                    self.rel_add(n, o.id, aff=rng.range(0, 40), trust=rng.range(0, 40), fam=rng.range(10, 40))
                    self.rel_add(o, n.id, aff=rng.range(0, 40), trust=rng.range(0, 40), fam=rng.range(10, 40))
        # old legends and initial chiefs
        for v in self.vlist:
            if v.frontier:
                for k in range(2):
                    title = rng.pick(self.C["legend_seeds"][v.frontier])
                    self.add_legend(f"On raconte qu'au-delà de {v.frontier_fr} il y a {title}.", v.frontier, v.id, None, "tale", announce=False)
                for n in self.villagers(v.id):
                    if rng.below(100) < 45:
                        n.legends.append(v.legends[rng.below(len(v.legends))])
            self.elect(v, initial=True)
        for n in self.npcs:
            if n.job:
                self.world_crafts.add(self.jobs[n.job]["craft"])
            self.world_crafts.update(c for c, s in n.skills.items() if s >= 20)
        # tracked NPCs for the mind viewer: spread over villages and ages
        alive = [n for n in self.npcs if n.alive]
        step = max(1, len(alive) // max(1, self.n_tracked))
        for k in range(self.n_tracked):
            alive[(k * step + step // 2) % len(alive)].tracked = True
        for n in self.npcs:
            h = self.hhs[n.hh]
            self.move(n, f"{h.village}:home:{h.id}")
            self.schedule(n, 1 + rng.below(6))
        self.ev("setup", text="Création du monde")

    def _maybe_parents(self, couples, age, rng, avoid=None):
        if rng.below(100) >= 40:
            return (None, None)
        D = self.DPY
        ok = []
        for m, f in couples:
            fa = (0 - f.born) // D
            if 18 <= fa - age <= 42 and (avoid is None or (m.id not in avoid.parents and f.id not in avoid.parents)):
                ok.append((m.id, f.id))
        if not ok:
            return (None, None)
        return ok[rng.below(len(ok))]

    def target_stock(self, v, g):
        pop = max(20, len(self.villagers(v.id)))
        per = {"food": 30, "water": 20 if v.kind == "oasis" else 2, "wood": 8, "salt": 3, "tools": 1, "ore": 3,
               "cloth": 2, "ale": 4, "glass": 1, "medicine": 1, "dye": 1, "stone": 3, "jewel": 0, "boat": 0}.get(g, 1)
        return max(20, pop * per)  # tenths

    # ------------------------------------------------------------- legends
    def add_legend(self, title, frontier, vid, hero, kind, announce=True):
        L = Legend(len(self.legends), title, frontier, vid, hero, self.day, kind)
        self.legends.append(L)
        if vid:
            self.villages[vid].legends.append(L.id)
        if announce:
            self.ev("legend_born", [hero] if hero is not None else [], vid, f"Naissance d'une légende à {self.villages[vid].name} : « {title} »", legend=L.id)
        return L

    # ------------------------------------------------------------- run
    def run(self, days, progress=None):
        end = self.t + days * 24
        self.end_tick = end
        from .decide import decide_batch
        while self.t < end:
            if self.t % 24 == 0:
                self.daily()
            ids = self.buckets.pop(self.t, None)
            if ids:
                due = []
                for i in sorted(set(ids)):
                    n = self.npcs[i]
                    if n.alive and n.busy_until == self.t:
                        due.append(n)
                decide_batch(self, due)
            if end - self.t <= self.live_hours:
                self.snapshot_live()
            self.t += 1
            if progress and self.t % (24 * 30) == 0:
                progress(self)
        if self.traj_f:
            self.traj_f.flush()

    def snapshot_live(self):
        row = []
        for n in self.npcs:
            if n.alive:
                row.append([n.id, n.loc, n.plan_kind, n.outfit])
        self.live.append({"t": self.t, "p": row})

    # ------------------------------------------------------------- daily
    def daily(self):
        d = self.day
        if d % self.DPM == 0 and d > 0:
            self.monthly_stats()
        self.economy_daily()
        self.health_daily()
        self.life_daily()
        self.politics_daily()
        self.crafts_daily()
        self.society_daily()
        if d % 7 == 0:
            self.decay_weekly()

    # ---------------- economy
    def economy_daily(self):
        rng = self.rng
        winter = self.season() == "winter"
        for v in self.vlist:
            for g in self.goods:
                tgt = self.target_stock(v, g)
                st = v.market.get(g, 0)
                base = self.C["goods"][g]["base_price"]
                p = base * tgt // max(st, tgt // 8, 1)
                v.prices[g] = clamp(p, max(1, base // 4), base * 8)
        for h in self.hhs:
            if not h.alive:
                continue
            v = self.villages[h.village]
            mem = [self.npcs[i] for i in h.members if self.npcs[i].alive]
            if not mem:
                h.alive = False
                continue
            # consumption
            # food is eaten meal by meal (actions.eat); here only the daily need, for reserves and purchases
            need_food = sum(10 if self.age(n) >= 12 else 6 for n in mem)
            if v.kind == "oasis":
                h.goods["water"] = h.goods.get("water", 0) + 7 * len(mem)   # what the family draws itself at the well
                before = h.goods.get("water", 0)
                if not self._consume(h, v, "water", 10 * len(mem)):
                    short = 10 * len(mem) - before - v.market.get("water", 0)
                    for n in mem:
                        n.thirst = clamp(n.thirst + 5 + 30 * max(0, short) // (10 * len(mem)), 0, 100)
                else:
                    for n in mem:
                        n.thirst = 0
            if winter:
                if not self._consume(h, v, "wood", 10):
                    for n in mem:
                        a = self.age(n)
                        n.hp -= 4 if (a < 6 or a >= 65) else 1
                        n.stress = clamp(n.stress + 5, 0, 100)
            # kitchen garden and hens: every household grows a little food
            season = self.season()
            garden = {"spring": 4, "summer": 6, "autumn": 7, "winter": 1}[season] * len(mem)
            if v.kind in ("mine", "oasis"):
                garden = garden * 6 // 10
            h.goods["food"] = h.goods.get("food", 0) + garden
            # spoilage, salt preserves
            f = h.goods.get("food", 0)
            if f > 0:
                if h.goods.get("salt", 0) >= 1:
                    h.goods["salt"] -= 1
                    h.goods["food"] = f - f // 200
                else:
                    h.goods["food"] = f - f // 80
            # sell surplus to the village market, buy shortfalls; stock up for winter in autumn
            days = 40 if season in ("autumn", "winter") else 10
            reserve = {"food": need_food * days, "wood": 60 if winter else 30, "water": 30 * len(mem), "salt": 20}
            for g in self.goods:
                have = h.goods.get(g, 0)
                keep = reserve.get(g, 0)
                if g == "tools":
                    continue
                credit = 600 if g in ESSENTIAL else 0   # merchants advance coin for staples
                if have > keep + 10 and v.purse > -credit:
                    q = have - keep
                    room = self.target_stock(v, g) * 2 - v.market.get(g, 0)
                    if room <= 0:
                        continue  # glut: the market buys no more than twice its needs
                    q = min(q, room)
                    gain = q * v.prices[g] * 9 // 100
                    if gain > v.purse + credit:
                        q = q * (v.purse + credit) // max(1, gain)
                        gain = q * v.prices[g] * 9 // 100
                    if q <= 0:
                        continue
                    v.purse -= gain
                    tax = gain * v.decrees["tax_pct"] // 100
                    h.goods[g] = have - q
                    v.market[g] = v.market.get(g, 0) + q
                    h.coin += gain - tax
                    v.treasury += tax
            for g, want in (("food", need_food * days // 2), ("wood", 30 if winter else 0), ("salt", 10), ("water", 20 * len(mem) if v.kind == "oasis" else 0)):
                have = h.goods.get(g, 0)
                if have < want:
                    q = min(want - have, v.market.get(g, 0))
                    cost = (q * v.prices[g] + 9) // 10
                    if cost > h.coin and v.prices[g] > 0:
                        q = h.coin * 10 // v.prices[g]
                        cost = (q * v.prices[g] + 9) // 10
                    if q > 0:
                        h.goods[g] = have + q
                        v.market[g] -= q
                        h.coin -= cost
                        v.purse += cost
            # houses need upkeep: stone and timber every ten days
            if (self.day + h.id) % 10 == 0:
                for g in ("stone", "wood"):
                    if not self._consume(h, v, g, 10):
                        for n in mem:
                            n.stress = clamp(n.stress + 3, 0, 100)
            # hunger drives families away: exodus towards a village with food
            if h.goods.get("food", 0) < 5 * len(mem) and rng.pm(30):
                hungry = sum(1 for n in mem if n.hunger >= 70)
                if hungry * 2 > len(mem) and not any(n.exiled for n in mem):
                    self.migrate(h, v)
                    continue
            # comfortable households buy finery and ale: money flows back to the crafts
            if h.coin > 120 and (self.day + h.id) % 7 == 0:
                for g in ("cloth", "ale", "glass", "dye", "jewel"):
                    if v.market.get(g, 0) >= 10 and h.coin - v.prices[g] > 80:
                        v.market[g] -= 10
                        h.coin -= v.prices[g]
                        v.purse += v.prices[g]
                        for i in h.members:
                            m = self.npcs[i]
                            if m.alive:
                                m.joy = clamp(m.joy + 3, -100, 100)
                        if g != "ale":
                            break
            # tools
            workers = sum(1 for n in mem if n.job)
            if h.tools < 60 * workers and v.market.get("tools", 0) >= 10 and h.coin >= v.prices["tools"]:
                v.market["tools"] -= 10
                h.coin -= v.prices["tools"]
                v.purse += v.prices["tools"]
                h.tools += 100
        # village markets: natural decay of perishables; the market's margin above its working
        # purse goes to the village treasury (market dues), which the chief spends back
        for v in self.vlist:
            keep = 30 * max(20, len(self.villagers(v.id)))
            if v.purse > keep:
                v.treasury += (v.purse - keep) // 2
                v.purse -= (v.purse - keep) // 2
            for g in ("food", "ale", "water"):
                v.market[g] = v.market.get(g, 0) * 99 // 100

    def migrate(self, h, v):
        best, bs = None, None
        for w in self.vlist:
            if w.id == v.id:
                continue
            kin = 0
            for i in h.members:
                for o, r in self.npcs[i].rel.items():
                    m = self.npcs[o]
                    if m.alive and m.village == w.id and r[AFF] > 30:
                        kin += 1
            sc = kin * 20 + w.market.get("food", 0) // 50 - w.prices.get("food", 4) * 10
            if bs is None or sc > bs:
                best, bs = w, sc
        mem = [self.npcs[i] for i in h.members if self.npcs[i].alive]
        h.village = best.id
        for n in mem:
            n.village = best.id
            if n.job and n.job not in best.job_targets:
                n.job = "farmer"
                n.skills["farming"] = max(n.skills.get("farming", 0), 15)
            if n.mentor is not None and self.npcs[n.mentor].village != best.id:
                self.npcs[n.mentor].apprentices = [a for a in self.npcs[n.mentor].apprentices if a != n.id]
                n.mentor = None
            self.move(n, f"{best.id}:home:{h.id}")
            self.interrupt(n)
        h.goods["food"] = h.goods.get("food", 0) + 20 * len(mem)
        names = ", ".join(n.first for n in mem[:4]) + ("…" if len(mem) > 4 else "")
        self.ev("migration", [n.id for n in mem], best.id, f"Chassée par la faim, la famille {h.name} ({names}) quitte {v.name} pour {best.name}")

    def _consume(self, h, v, g, q):
        have = h.goods.get(g, 0)
        if have >= q:
            h.goods[g] = have - q
            return True
        h.goods[g] = 0
        missing = q - have
        if g == "water":
            # communal well: water carried to the village is shared, carriers are paid by the market
            avail = min(missing, v.market.get("water", 0))
            v.market["water"] = v.market.get("water", 0) - avail
            return avail >= missing
        # buy at market if possible
        avail = min(missing, v.market.get(g, 0))
        cost = (avail * v.prices[g] + 9) // 10
        if avail > 0 and cost <= h.coin:
            v.market[g] -= avail
            h.coin -= cost
            v.purse += cost
            missing -= avail
        if missing <= 0:
            return True
        return False

    # ---------------- health
    def health_daily(self):
        rng = self.rng
        d = self.day
        winter = self.season() == "winter"
        for v in self.vlist:
            if v.id not in self.epidemic and rng.ppm(1600 if winter else 400):
                vs = self.villagers(v.id)
                if vs:
                    for _ in range(rng.range(1, 3)):
                        n = vs[rng.below(len(vs))]
                        if n.sick == 0:
                            n.sick = rng.range(20, 60)
                    self.epidemic[v.id] = d
                    self.ev("epidemic", [], v.id, f"Une fièvre se déclare à {v.name}.")
        healers = {v.id: [] for v in self.vlist}
        for n in self.npcs:
            if n.alive and n.job == "healer" and not n.exiled:
                healers[n.village].append(n)
        sick_by_v = {v.id: 0 for v in self.vlist}
        for n in self.npcs:
            if not n.alive:
                continue
            a = self.age(n)
            if n.sick:
                sick_by_v[n.village] += 1
                h = self.hhs[n.hh]
                # contagion
                for i in h.members:
                    m = self.npcs[i]
                    if m.alive and m.sick == 0 and m.id != n.id and rng.pm(120) and not self.immune(m):
                        m.sick = rng.range(15, 50)
                if rng.pm(300):
                    vs_ = self.villagers(n.village)
                    for _ in range(2):
                        m = vs_[rng.below(len(vs_))]
                        if m.alive and m.sick == 0 and rng.pm(200) and not self.immune(m):
                            m.sick = rng.range(15, 50)
                care = 0
                hs = healers[n.village]
                if hs:
                    best = max(hs, key=lambda x: (x.skills.get("healing", 0), -x.id))
                    care = best.skills.get("healing", 0) // 12
                    if self.villages[n.village].market.get("medicine", 0) >= 1:
                        self.villages[n.village].market["medicine"] -= 1
                        care += 4
                frail = 4 if (a < 5 or a >= 65) else 0
                n.sick = clamp(n.sick + rng.range(-8, 5) + frail - care - (n.hp >= 60), 0, 120)
                n.hp -= n.sick // 25
                if n.sick == 0:
                    self.remember(n, "recovered", None, 30, 20)
            # hunger / thirst damage and healing
            if n.hunger >= 95:
                n.hp -= 5
            if n.thirst >= 60:
                n.hp -= 6
            if n.hunger < 70 and n.thirst < 50 and n.sick == 0 and n.hp < 100:
                n.hp = min(100, n.hp + 3)
            # natural mortality
            death = None
            if n.hp <= 0:
                death = "sickness" if n.sick else ("thirst" if n.thirst >= 60 else "starvation" if n.hunger >= 90 else "cold" if winter else "wounds")
            elif rng.ppm(self.mort_ppm[min(a, 120)]):
                death = "old_age" if a >= 55 else "illness"
            if death:
                self.die(n, death)
        for v in self.vlist:
            if v.id in self.epidemic and sick_by_v[v.id] == 0:
                self.ev("epidemic_end", [], v.id, f"La fièvre quitte {v.name}.")
                del self.epidemic[v.id]

    def immune(self, n):
        for m in n.mem:
            if m[1] == "recovered" and self.day - m[0] < 2 * self.DPY:
                return True
        return False

    # ---------------- life cycle
    def life_daily(self):
        rng = self.rng
        d = self.day
        for n in list(self.npcs):
            if not n.alive:
                continue
            a = self.age(n)
            # births
            if n.sex == "f" and n.partner is not None and self.ADULT <= a <= 42:
                p = self.npcs[n.partner]
                if p.alive and p.sex == "m" and p.hh == n.hh and not n.exiled:
                    h = self.hhs[n.hh]
                    kids = sum(1 for c in n.children if self.npcs[c].alive and self.age(self.npcs[c]) < 12)
                    food_ok = h.goods.get("food", 0) > 10 * len(h.members)
                    pm = 220 if kids < 2 else 110 if kids < 4 else 30   # per 100 000 per day
                    if not food_ok:
                        pm //= 2
                    if rng.below(100000) < pm:
                        self.birth(n, p)
            # coming of age
            if (d - n.born) % self.DPY == 0 and d != n.born:
                if a == self.APPR:
                    self.choose_apprenticeship(n)
                elif a == self.ADULT:
                    self.become_adult(n)
            if n.job and a >= 75 and n.job != "priest":
                n.job = None
                self.ev("retire", [n.id], n.village)
        # weddings and funerals due
        for n in self.npcs:
            if n.alive and n.engaged is not None and n.agenda:
                for it in list(n.agenda):
                    if it[1] == "own_wedding" and it[0] // 24 <= d:
                        n.agenda.remove(it)
                        other = self.npcs[n.engaged]
                        if other.alive and other.engaged == n.id and n.id < other.id:
                            self.marry(n, other)
                        elif not other.alive:
                            n.engaged = None

    def birth(self, mother, father):
        rng = self.rng
        h = self.hhs[mother.hh]
        # naming tradition: reuse the name of a dead grandparent
        sex = "f" if rng.below(2) else "m"
        first = None
        for p in (father, mother):
            for g in p.parents:
                if g is not None:
                    gp = self.npcs[g]
                    if not gp.alive and gp.sex == sex and rng.pm(500):
                        first = gp.first
        c = self.new_npc(h.village, sex, self.day, father.family if rng.below(100) < 85 else mother.family,
                         (father.id, mother.id), first)
        self.join(c, h)
        self.move(c, f"{h.village}:home:{h.id}")
        self.schedule(c, self.t + 2)
        for p in (father, mother):
            p.joy = clamp(p.joy + 40, -100, 100)
            self.remember(p, "birth", c.id, 80, 70)
        for i in h.members:
            m = self.npcs[i]
            if m.alive and m.id != c.id:
                self.rel_add(c, m.id, aff=50, fam=80, trust=50)
                self.rel_add(m, c.id, aff=50, fam=80)
        txt = f"Naissance de {c.name}, enfant de {mother.name} et {father.name} ({self.villages[h.village].name})"
        if first:
            txt += f", qui porte le nom d'un aïeul disparu"
        self.ev("birth", [c.id, mother.id, father.id], h.village, txt)
        # childbirth risk, lowered by a healer
        risk = 12
        healers = [m for m in self.villagers(h.village, True) if m.job == "healer"]
        if healers:
            risk = max(2, 12 - max(x.skills.get("healing", 0) for x in healers) // 10)
        if rng.below(1000) < risk:
            self.die(mother, "childbirth")

    def choose_apprenticeship(self, n):
        """Age 12: pick a craft (parent's by default, a village shortage, or curiosity)."""
        rng = self.rng
        v = self.villages[n.village]
        par = [self.npcs[p] for p in n.parents if p is not None and self.npcs[p].alive and self.npcs[p].job]
        options = []
        weights = []
        for p in par:
            options.append(self.jobs[p.job]["craft"])
            weights.append(60 + n.val["kin_protection"] // 2)
        # shortage: craft with fewest practitioners relative to target
        counts = {}
        for m in self.villagers(v.id, True):
            if m.job:
                counts[m.job] = counts.get(m.job, 0) + 1
        for job, tgt in sorted(v.job_targets.items()):
            have = counts.get(job, 0)
            if have * 100 < tgt * 70:
                options.append(self.jobs[job]["craft"])
                weights.append((tgt - have) * 3 + (n.drv["achievement"] // 4))
        if n.tr["curiosity"] > 40:
            rare = sorted(c for c, s in self.crafts.items() if s["rare"])
            c = rare[rng.below(len(rare))]
            options.append(c)
            weights.append(n.tr["curiosity"] // 3)
        if not options:
            options, weights = ["farming"], [1]
        craft = rng.weighted(options, weights)
        n.learning = craft
        # find a master: parent first
        for p in par:
            if self.skill(p, craft) >= 30 and len(p.apprentices) < 3:
                self.set_mentor(n, p)
                return

    def set_mentor(self, n, m, announce=True):
        if n.mentor is not None and n.mentor < len(self.npcs):
            old = self.npcs[n.mentor]
            if n.id in old.apprentices:
                old.apprentices.remove(n.id)
        n.mentor = m.id
        m.apprentices.append(n.id)
        self.rel_add(n, m.id, respect=15, trust=10, fam=10)
        self.rel_add(m, n.id, aff=5, fam=10)
        if announce:
            cr = self.crafts[n.learning]["fr"] if n.learning in self.crafts else n.learning
            self.ev("apprenticeship", [n.id, m.id], n.village, f"{n.name} devient l'apprenti·e de {m.name} ({cr})", craft=n.learning)

    def craft_job(self, craft, vid):
        v = self.villages[vid]
        best = None
        for job, spec in sorted(self.jobs.items()):
            if spec["craft"] == craft:
                if best is None or job in v.job_targets:
                    best = job
        return best

    def become_adult(self, n):
        rng = self.rng
        if n.mentor is not None:
            m = self.npcs[n.mentor]
            if n.id in m.apprentices:
                m.apprentices.remove(n.id)
            n.mentor = None
        cr = n.learning
        if cr and self.skill(n, cr) >= 15:
            n.job = self.craft_job(cr, n.village)
        else:
            # best known craft, else unskilled farm work
            known = sorted(((s, c) for c, s in n.skills.items()), reverse=True)
            if known and known[0][0] >= 15:
                n.job = self.craft_job(known[0][1], n.village)
            else:
                n.job = "farmer"
                n.skills["farming"] = max(n.skills.get("farming", 0), 5)
        n.learning = None if (n.job and self.jobs[n.job]["craft"] == cr) else n.learning
        if n.job is None:
            n.job = "farmer"
        n.coin += 5

    def marry(self, a, b, elope=False):
        rng = self.rng
        a.engaged = b.engaged = None
        a.partner, b.partner = b.id, a.id
        a.partners.append(b.id)
        b.partners.append(a.id)
        # residence rule: whoever has a site-bound job keeps their village; else the woman's (or a's)
        bound = {"fisher", "salter", "shipwright", "woodcutter", "hunter", "herbalist", "miner", "jeweler",
                 "glassblower", "dyer", "caravaneer", "water_carrier"}
        stay = a
        if b.job in bound and a.job not in bound:
            stay = b
        elif a.job in bound and b.job not in bound:
            stay = a
        elif a.village != b.village:
            stay = a if a.sex == "f" else b
        mover = b if stay is a else a
        if mover.village != stay.village:
            self.ev("migration", [mover.id], stay.village, f"{mover.name} quitte {self.villages[mover.village].name} pour vivre à {self.villages[stay.village].name}")
        # new household for the couple unless one already heads one with no other adult couple
        h = self.new_household(stay.village, stay.family)
        for n in (a, b):
            self.join(n, h)
            # children from a previous union follow the parent
            for c in n.children:
                cn = self.npcs[c]
                if cn.alive and self.age(cn) < self.ADULT and cn.hh != h.id and (cn.parents[0] == n.id or cn.parents[1] == n.id):
                    other_parent = [p for p in cn.parents if p != n.id]
                    if not other_parent or other_parent[0] is None or not self.npcs[other_parent[0]].alive:
                        self.join(cn, h)
            self.move(n, f"{h.village}:home:{h.id}")
        h.coin = (a.coin + b.coin) // 2 + 20
        h.goods = {"food": 120, "wood": 60, "salt": 20, "water": 60}
        h.tools = 100
        for n in (a, b):
            n.joy = clamp(n.joy + 50, -100, 100)
            self.remember(n, "wedding", (b if n is a else a).id, 90, 90)
            n.outfit = "festive"
        v = self.villages[stay.village]
        txt = f"Mariage de {a.name} et {b.name} à {v.name}" if not elope else f"{a.name} et {b.name} s'enfuient pour s'unir malgré leurs familles"
        guests = set()
        for n in (a, b):
            for o, r in n.rel.items():
                if r[AFF] >= 40 and self.npcs[o].alive:
                    guests.add(o)
        guests.discard(a.id)
        guests.discard(b.id)
        if not elope:
            for g in sorted(guests):
                m = self.npcs[g]
                if m.village == v.id or self.close_kin(m, a) or self.close_kin(m, b):
                    m.joy = clamp(m.joy + 15, -100, 100)
                    m.agenda.append((self.t + 14, "wedding", f"{v.id}:temple", a.id))
                    self.rel_add(m, a.id, aff=3, fam=3)
                    self.rel_add(m, b.id, aff=3, fam=3)
        # jealousy: rivals with strong romance toward either spouse
        for m in self.npcs:
            if not m.alive or m.id in (a.id, b.id):
                continue
            for n, sp in ((a, b), (b, a)):
                r = m.rel.get(n.id)
                if r and r[ROMANCE] >= 55:
                    self.rel_add(m, sp.id, grudge=r[ROMANCE] // 2, aff=-20)
                    m.joy = clamp(m.joy - 30, -100, 100)
                    self.remember(m, "heartbreak", n.id, -60, 60)
                    r[ROMANCE] //= 2
        self.ev("elopement" if elope else "wedding", [a.id, b.id], v.id, txt, guests=len(guests))
        self._feud_peace(a, b)

    def _feud_peace(self, a, b):
        for x, y in ((a, b), (b, a)):
            for p in x.parents:
                if p is None:
                    continue
                ph = self.hhs[self.npcs[p].hh]
                for q in y.parents:
                    if q is None:
                        continue
                    qh = self.npcs[q].hh
                    if qh in ph.feud:
                        del ph.feud[qh]
                        self.hhs[qh].feud.pop(ph.id, None)
                        self.ev("feud_peace", [a.id, b.id], a.village, f"Le mariage de {a.name} et {b.name} met fin à la querelle entre les familles {ph.name} et {self.hhs[qh].name}")

    def die(self, n, cause, killer=None):
        if not n.alive:
            return
        n.alive = False
        n.died = self.day
        n.cause = cause
        self.move(n, None)
        v = self.villages[n.village]
        a = self.age(n)
        causes = {"old_age": "de vieillesse", "illness": "de maladie", "sickness": "de la fièvre", "starvation": "de faim",
                  "cold": "de froid", "thirst": "de soif", "wounds": "de ses blessures", "childbirth": "en couches",
                  "accident": "d'un accident", "collapse": "dans un éboulement", "drowned": "en mer",
                  "murder": "assassiné·e", "vanished": "disparu·e", "execution": "exécuté·e", "fight": "dans une rixe"}
        txt = f"{n.name} ({a} ans, {self.jobs[n.job]['fr'] if n.job else 'sans métier'}) meurt {causes.get(cause, cause)}"
        if cause != "vanished":
            self.ev("death", [n.id] + ([killer] if killer is not None else []), n.village, txt, cause=cause, age=a)
        self.counts["death_" + cause] = self.counts.get("death_" + cause, 0) + 1
        # spouse
        if n.partner is not None:
            p = self.npcs[n.partner]
            if p.partner == n.id:
                p.partner = None
        if n.engaged is not None:
            e = self.npcs[n.engaged]
            if e.engaged == n.id:
                e.engaged = None
                e.agenda = [x for x in e.agenda if x[1] != "own_wedding"]
        if n.affair is not None:
            o = self.npcs[n.affair]
            if o.affair == n.id:
                o.affair = None
        # grief, funeral invitations
        for m in self.npcs:
            if not m.alive:
                continue
            r = m.rel.get(n.id)
            if r is None:
                continue
            kin = self.close_kin(m, n)
            if r[AFF] >= 30 or kin:
                g = (r[AFF] if r[AFF] > 0 else 0) // 2 + (40 if kin else 0) + (30 if m.partner == n.id or n.partner == m.id else 0)
                m.grief = clamp(m.grief + g, 0, 100)
                m.joy = clamp(m.joy - g // 2, -100, 100)
                self.remember(m, "death_kin" if kin else "death_friend", n.id, -g, clamp(40 + g, 0, 100), cause)
                if m.village == n.village and cause != "vanished":
                    m.agenda.append((self.t + 24 + 10 - (self.t % 24), "funeral", f"{n.village}:temple", n.id))
                self.interrupt(m)
            elif r[GRUDGE] >= 50:
                m.joy = clamp(m.joy + 10, -100, 100)
        # mentor / apprentices
        for ap in n.apprentices:
            x = self.npcs[ap]
            if x.mentor == n.id:
                x.mentor = None
        n.apprentices = []
        if n.mentor is not None:
            m = self.npcs[n.mentor]
            if n.id in m.apprentices:
                m.apprentices.remove(n.id)
        # titles
        if v.chief == n.id:
            v.chief = None
            v.next_election = self.day + 10
            self.ev("chief_died", [n.id], v.id, f"{v.name} n'a plus de chef : {n.name} est mort·e. Élection dans 10 jours.")
        for g in self.groups:
            if g.alive and n.id in g.members:
                g.members.remove(n.id)
                if not g.members:
                    g.alive = False
        # household: inheritance, orphans
        h = self.hhs[n.hh]
        living = [self.npcs[i] for i in h.members if self.npcs[i].alive]
        heirs = [m for m in living if self.age(m) >= self.ADULT]
        h.coin += n.coin
        n.coin = 0
        if not heirs:
            kids = [m for m in living if self.age(m) < self.ADULT]
            if kids:
                self.place_orphans(kids, h, n)
            elif not living:
                h.alive = False

    def place_orphans(self, kids, h, dead):
        rng = self.rng
        # nearest kin: grandparents, then aunts and uncles (children of grandparents), then a kind family
        cand = []
        for k in kids:
            for p in k.parents:
                if p is None:
                    continue
                pp = self.npcs[p]
                for g in pp.parents:
                    if g is not None and self.npcs[g].alive and self.age(self.npcs[g]) < 80:
                        cand.append(self.npcs[g])
                    if g is not None:
                        for s in self.npcs[g].children:
                            sn = self.npcs[s]
                            if sn.alive and s != p and self.age(sn) >= self.ADULT and not sn.exiled:
                                cand.append(sn)
            break
        kin = True
        if not cand:
            kin = False
            vs = [m for m in self.villagers(h.village, True) if not m.exiled and m.hh != h.id]
            if vs:
                vs.sort(key=lambda m: (-(m.tr["empathy"] + (100 if m.partner is not None else 0) + (60 if m.orient == 1 and m.partner is not None else 0)), m.id))
                cand = vs[:3]
        if not cand:
            return
        host = cand[0]
        hh = self.hhs[host.hh]
        hh.coin += h.coin
        h.coin = 0
        for g, q in list(h.goods.items()):
            hh.goods[g] = hh.goods.get(g, 0) + q
            h.goods[g] = 0
        for k in kids:
            self.join(k, hh)
            self.move(k, f"{hh.village}:home:{hh.id}")
            self.rel_add(k, host.id, aff=30, trust=30, fam=40)
            self.rel_add(host, k.id, aff=40, fam=40)
        h.alive = False
        names = ", ".join(k.first for k in kids)
        self.ev("adoption" if not kin else "orphaned", [k.id for k in kids] + [host.id], hh.village,
                f"{names}, orphelin·e·s de {dead.name}, sont recueilli·e·s par {host.name}" + ("" if kin else " (sans lien de sang)"))

    # ---------------- politics
    def elect(self, v, initial=False):
        rng = self.rng
        adults = [n for n in self.villagers(v.id, True) if not n.exiled]
        if not adults:
            return
        def standing(n):
            best = max(n.skills.values()) if n.skills else 0
            return n.drv["ambition"] + n.val["honor"] // 2 + min(self.age(n), 60) // 2 + best // 3
        cands = sorted([n for n in adults if n.drv["ambition"] >= 55 and self.age(n) >= 25], key=lambda n: (-standing(n), n.id))[:4]
        if v.chief is not None and self.npcs[v.chief].alive and self.npcs[v.chief] not in cands:
            cands.append(self.npcs[v.chief])
        if not cands:
            cands = sorted(adults, key=lambda n: (-standing(n), n.id))[:2]
        votes = {c.id: 0 for c in cands}
        if initial:
            win = cands[0]
            votes[win.id] = len(adults)
        else:
            for vo in adults:
                best, bs = None, None
                for c in cands:
                    if c.id == vo.id:
                        s = 1000
                    else:
                        r = vo.rel.get(c.id)
                        s = (r[AFF] + r[TRUST] + r[RESPECT] - r[GRUDGE] * 2) if r else -20
                        if self.is_kin(vo, c):
                            s += 60
                        if set(vo.groups) & set(c.groups):
                            s += 30
                        if v.chief == c.id:
                            s -= v.unrest
                    if bs is None or s > bs:
                        best, bs = c, s
                votes[best.id] += 1
            win = max(cands, key=lambda c: (votes[c.id], -c.id))
        old = v.chief
        if old is not None and old != win.id:
            o = self.npcs[old]
            if "chief" in o.titles:
                o.titles.remove("chief")
            if o.alive:
                self.rel_add(o, win.id, grudge=o.drv["ambition"] // 3)
        v.chief = win.id
        v.chief_since = self.day
        v.next_election = self.day + 5 * self.DPY
        if "chief" not in win.titles:
            win.titles.append("chief")
        v.chief_history.append({"day": self.day, "chief": win.id, "votes": {str(k): x for k, x in votes.items()}})
        self.set_decrees(v, win, announce=not initial)
        title = "bailli" if v.kind == "town" else "chef"
        if not initial:
            tally = ", ".join(f"{self.npcs[c].first} {x}" for c, x in sorted(votes.items(), key=lambda kv: -kv[1]))
            self.ev("election", [win.id] + [c.id for c in cands if c.id != win.id], v.id,
                    f"{win.name} est élu·e {title} de {v.name} ({tally})", votes=votes)
        for vo in adults:
            if vo.id != win.id:
                self.rel_add(vo, win.id, fam=5)

    def set_decrees(self, v, chief, announce=True):
        tr, val, drv = chief.tr, chief.val, chief.drv
        old = dict(v.decrees)
        v.decrees["tax_pct"] = clamp(5 + (drv["hoarding"] - 50) // 8 + (drv["ambition"] - 50) // 10 - tr["empathy"] // 20, 0, 20)
        if tr["justice"] >= 30 and tr["aggression"] >= 20:
            pun = "exile"
        elif tr["aggression"] >= 40:
            pun = "stocks"
        else:
            pun = "fine"
        v.decrees["theft_punishment"] = pun
        v.decrees["famine_relief"] = tr["empathy"] >= -10 or val["honor"] >= 70
        if v.kind == "town":
            v.decrees["market_fee_pct"] = clamp((drv["hoarding"] + drv["ambition"] - 80) // 12, 0, 15)
        v.decrees["curfew"] = tr["aggression"] >= 50 and tr["tolerance"] <= -20
        if announce and old != v.decrees:
            pun_fr = {"fine": "amende", "stocks": "pilori", "exile": "bannissement"}[pun]
            txt = f"{chief.name} fixe l'impôt à {v.decrees['tax_pct']} %, punit le vol par {pun_fr}"
            if v.kind == "town":
                txt += f", taxe les marchands étrangers à {v.decrees['market_fee_pct']} %"
            if v.decrees["curfew"]:
                txt += ", impose un couvre-feu"
            if not v.decrees["famine_relief"]:
                txt += " et supprime l'aide en cas de disette"
            self.ev("decree", [chief.id], v.id, txt, decrees=dict(v.decrees))

    def politics_daily(self):
        for v in self.vlist:
            if self.day >= v.next_election or (v.chief is None and self.day >= v.next_election):
                self.elect(v)

    # ---------------- crafts: transmission and loss
    def crafts_daily(self):
        if self.day % 7:
            return
        known_v = {v.id: set() for v in self.vlist}
        world = set()
        series = {}
        for n in self.npcs:
            if not n.alive:
                continue
            for c, s in n.skills.items():
                if s >= 20:
                    known_v[n.village].add(c)
                    world.add(c)
                    key = (n.village, c)
                    series[key] = series.get(key, 0) + 1
        for v in self.vlist:
            lost = v.known_crafts - known_v[v.id]
            for c in sorted(lost):
                if c in world:
                    self.ev("craft_lost_village", [], v.id, f"Plus personne à {v.name} ne maîtrise la {self.crafts[c]['fr']}", craft=c)
                v.lost_crafts.append((self.day, c))
            v.known_crafts = known_v[v.id]
        for c in sorted(self.world_crafts - world):
            self.ev("craft_lost", [], None, f"Savoir perdu : la {self.crafts[c]['fr']} a disparu du monde avec son dernier maître", craft=c)
            self.lost_world.add(c)
        for c in sorted(world - self.world_crafts):
            if c in self.lost_world:
                holders = [n for n in self.npcs if n.alive and n.skills.get(c, 0) >= 20]
                h = holders[0] if holders else None
                self.ev("craft_rediscovered", [h.id] if h else [], h.village if h else None,
                        f"La {self.crafts[c]['fr']} renaît grâce à {h.name if h else 'un inconnu'}", craft=c)
                self.lost_world.discard(c)
        self.world_crafts = world
        if self.day % self.DPM == 0:
            self.craft_series.append({"day": self.day, "c": {f"{k[0]}|{k[1]}": x for k, x in sorted(series.items())}})

    # ---------------- society: festivals, feuds, lies, unrest, bands
    def society_daily(self):
        rng = self.rng
        d = self.day
        dm = d % self.DPM
        m = self.month()
        # seasonal fair at the market town
        if dm == 14 and m in (2, 5, 8, 11):
            town = next(v for v in self.vlist if v.kind == "town")
            names = {2: "foire de printemps", 5: "fête de la Saint-Jean", 8: "foire des moissons", 11: "fête du solstice"}
            n_inv = 0
            for n in self.npcs:
                if n.alive and not n.exiled and self.age(n) >= 6 and rng.below(200) < 60 + n.tr["sociability"] // 2 + (60 if n.village == town.id else 0):
                    n.agenda.append((self.t + 10, "festival", f"{town.id}:square", None))
                    n_inv += 1
            self.ev("festival", [], town.id, f"{names[m].capitalize()} à {town.name} ({n_inv} venus de tous les villages)")
        # lies get debunked
        for n in self.npcs:
            if not n.alive:
                continue
            for mm in list(n.mem):
                if mm[7] and rng.pm(15):
                    n.mem.remove(mm)
                    src = mm[6]
                    if src is not None:
                        self.rel_add(n, src, trust=-40, aff=-20, respect=-20)
                        self.remember(n, "liar", src, -50, 60)
                        liar = self.npcs[src]
                        if liar.alive:
                            self.ev("lie_exposed", [src, n.id] + ([mm[2]] if mm[2] is not None else []), n.village,
                                    f"{n.name} découvre que {liar.name} a menti au sujet de {self.npcs[mm[2]].name if mm[2] is not None else 'quelqu un'}")
        # household feuds from accumulated grudges
        if d % 7 == 3:
            pair = {}
            for n in self.npcs:
                if not n.alive or self.age(n) < 14:
                    continue
                for o, r in n.rel.items():
                    if r[GRUDGE] >= 40:
                        on = self.npcs[o]
                        if on.alive and on.hh != n.hh:
                            k = (min(n.hh, on.hh), max(n.hh, on.hh))
                            pair[k] = pair.get(k, 0) + r[GRUDGE]
            for (a, b), s in sorted(pair.items()):
                ha, hb = self.hhs[a], self.hhs[b]
                if s >= 260 and b not in ha.feud and ha.alive and hb.alive:
                    ha.feud[b] = d
                    hb.feud[a] = d
                    self.ev("feud", [], ha.village, f"Querelle ouverte entre les familles {ha.name} ({self.villages[ha.village].name}) et {hb.name} ({self.villages[hb.village].name})", hh=[a, b])
                    for i in ha.members:
                        for j in hb.members:
                            self.rel_add(self.npcs[i], j, grudge=10, aff=-10)
                            self.rel_add(self.npcs[j], i, grudge=10, aff=-10)
        # unrest, monthly
        if dm == 1:
            for v in self.vlist:
                adults = [n for n in self.villagers(v.id, True) if not n.exiled]
                if not adults or v.chief is None:
                    continue
                s = 0
                for n in adults:
                    r = n.rel.get(v.chief)
                    s += (r[GRUDGE] - r[AFF] // 2 if r else 0) + n.hunger // 3 + n.stress // 4
                v.unrest = clamp(s // len(adults) + v.decrees["tax_pct"] * 2, 0, 100)
            # famine detection
            for v in self.vlist:
                vs = self.villagers(v.id)
                if vs and sum(1 for n in vs if n.hunger >= 70) * 100 // len(vs) >= 25:
                    self.ev("famine", [], v.id, f"Disette à {v.name} : un habitant sur quatre a faim")

    def decay_weekly(self):
        for n in self.npcs:
            if not n.alive:
                continue
            res = 2 + n.val["piety"] // 50
            n.grief = max(0, n.grief - 4 - res)
            n.stress = max(0, n.stress - 3)
            n.joy = n.joy * 9 // 10
            for mm in n.mem:
                if mm[4] > 0 and mm[1] not in ("death_kin", "wedding", "birth"):
                    mm[4] -= 1
            for o in list(n.rel):
                r = n.rel[o]
                if r[FAM] > 0:
                    r[FAM] -= 1
                if r[GRUDGE] > 0 and n.tr["grudge"] < 30:
                    r[GRUDGE] -= 1
                if not self.npcs[o].alive and r[FAM] < 20 and o not in n.parents and o not in n.children and o != n.partner:
                    del n.rel[o]
            if n.agenda:
                n.agenda = [a for a in n.agenda if a[0] >= self.t - 48 or a[1] == "own_wedding"]
            if n.belief > 0:
                n.belief -= 1

    # ---------------- statistics
    def monthly_stats(self):
        row = {"day": self.day, "v": {}}
        for v in self.vlist:
            vs = self.villagers(v.id)
            adults = [n for n in vs if self.age(n) >= self.ADULT]
            hh = [h for h in self.hhs if h.alive and h.village == v.id]
            couples = sum(1 for n in vs if n.partner is not None) // 2
            friends = enemies = 0
            for n in vs:
                for o, r in n.rel.items():
                    if r[AFF] >= 60:
                        friends += 1
                    if r[GRUDGE] >= 50:
                        enemies += 1
            row["v"][v.id] = {
                "pop": len(vs), "adults": len(adults), "children": len(vs) - len(adults),
                "households": len(hh), "couples": couples,
                "food_pc": (sum(h.goods.get("food", 0) for h in hh) // 10) // max(1, len(vs)),
                "coin_pc": sum(h.coin for h in hh) // max(1, len(vs)),
                "prices": dict(v.prices), "market": {g: q // 10 for g, q in v.market.items()},
                "joy": sum(n.joy for n in vs) // max(1, len(vs)),
                "stress": sum(n.stress for n in vs) // max(1, len(vs)),
                "hunger": sum(n.hunger for n in vs) // max(1, len(vs)),
                "sick": sum(1 for n in vs if n.sick),
                "belief": sum(n.belief for n in vs) // max(1, len(vs)),
                "unrest": v.unrest, "chief": v.chief, "treasury": v.treasury,
                "friend_links": friends, "enemy_links": enemies,
                "crafts": len(v.known_crafts),
                "outlaws": sum(1 for n in vs if n.exiled),
            }
        self.monthly.append(row)
