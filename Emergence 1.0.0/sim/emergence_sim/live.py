"""Live observation: the state of one NPC, read from the running simulation, as a
record of the data thread's generator 0.4, then tokens tok-1 (ai/npc_pipeline/encode.py).

Every value comes from the simulation. A field the simulation does not model yet
gets a fixed neutral value, never a random one (sim_adapter.py fills them at random
because it builds training data; a live NPC must see the same thing twice in the
same situation). The neutral fields are listed in NEUTRAL and in sim/ETAT.md.

The mapping tables (sim job -> job of the fiches, village ids, places, links,
memory kinds) are imported from ai/npc_pipeline/sim_adapter.py: one table, owned
by the data thread.
"""
import os
import sys

from .model import AFF, TRUST, RESPECT, ROMANCE, FAM, GRUDGE, DEBT
from .export import link as sim_link

_AI = None


def ai_path():
    """Folder ai/npc_pipeline: $EMERGENCE_AI, then ../ai next to sim/, then the shared project copy."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for c in (os.environ.get("EMERGENCE_AI", ""), os.path.join(here, "..", "ai", "npc_pipeline"),
              "/mnt/project-files/projet-unifie/emergence/ai/npc_pipeline"):
        if c and os.path.isfile(os.path.join(c, "encode.py")):
            return os.path.abspath(c)
    raise ImportError("ai/npc_pipeline not found: set EMERGENCE_AI to the folder that holds encode.py")


def ai():
    """Imports encode, generate_states and sim_adapter from ai/npc_pipeline once."""
    global _AI
    if _AI is None:
        p = ai_path()
        if p not in sys.path:
            sys.path.insert(0, p)
        import encode
        import generate_states
        import sim_adapter
        _AI = (encode, generate_states, sim_adapter, encode.Vocab.load(os.path.join(p, "model_vocab.json")))
    return _AI


NEUTRAL = {
    "temperament": {"reactivity": 50, "resilience": 55},
    "body.strength": "55 adult, 35 child, 40 elder",
    "states.shock / confusion": 0,
    "entity.fear / mood_toward / urge_to_interact / suspicion / indirect_threat / rep_*": 0,
    "entity.beauty": 50,
    "village.loyalty / leader_legit / institution_trust / security / rep": 0,
    "village.belonging / cohesion": "70 / 50",
    "event content, reliability, understanding": "{}, 1.0, 4 (seen directly)",
    "goal progress, deadline": "0 (the engine does not measure goal progress yet)",
    "items, titles": "none yet (no spatial perception in the abstract sim)",
}
MAX_ENTITIES = 6
MAX_MEMORIES = 9
MAX_EVENTS = 3
MAX_GOALS = 4
# norms an event touches (0..100), for the EVENT token's norm vector
EVENT_NORMS = {"insult": {"honor": 50}, "strike": {"life": 60, "honor": 30}, "shove": {"honor": 30, "life": 20}}
OTHER_ORDER = ["sea_village", "mountain_village", "desert_village", "forest_village", "market_town"]


def ci(x, lo, hi):
    return int(max(lo, min(hi, round(x))))


def craft_job(sim, craft):
    """sim craft -> job name of the fiches (the vocabulary's skill=...)."""
    enc, gs, sa, V = ai()
    for job, spec in sorted(sim.jobs.items()):
        if spec["craft"] == craft:
            j = sa.JOB.get(job, job)
            return j if j in gs.JOB_ACTION else "none"
    return "none"


def love_status(sim, n):
    if n.partner is not None:
        return "married"
    if n.engaged is not None or n.affair is not None:
        return "courting"
    if n.partners:
        return "widowed"
    return "single"


def action_of(sim, kind, job):
    enc, gs, sa, V = ai()
    if kind == "work" and job in gs.JOB_ACTION:
        return gs.JOB_ACTION[job][0]
    return sa.ACTION.get(kind, "idle")


def job_of(sim, n):
    enc, gs, sa, V = ai()
    if n.job is None:
        return "apprentice" if n.learning and sim.age(n) >= sim.APPR else "none"
    j = sa.JOB.get(n.job, n.job)
    return j if j in gs.JOB_ACTION else "none"


def village_id(vid):
    enc, gs, sa, V = ai()
    return sa.VILLAGE.get(vid, vid)


def record(sim, n, options):
    """-> generator-0.4 record {state, cands} for encode.encode()."""
    enc, gs, sa, V = ai()
    age = sim.age(n)
    acat = gs.age_cat(age)
    h = sim.hh(n)
    v = sim.villages[n.village]
    job = job_of(sim, n)
    members = max(1, len(h.members))
    food_days = h.goods.get("food", 0) / (4 * members)
    wood_days = h.goods.get("wood", 0) / (2 * members)
    tr = dict(n.tr)
    tr["ambition"] = n.drv.get("ambition", 0)
    me = {
        "uid": n.id, "age": age, "age_cat": acat, "love_status": love_status(sim, n), "job": job,
        "current_action": action_of(sim, n.plan_kind, job),
        "place_type": sa.PLACE.get(n.loc.split(":")[1] if n.loc and ":" in n.loc else "home", "road"),
        "weather": sim.weather(n.village), "season": sim.season(), "hour": float(sim.hour),
        "traits": {k: tr.get(k, 0) for k in enc.TRAITS},
        "temperament": dict(NEUTRAL["temperament"]),
        "values": {k: n.val.get(k, 50) for k in enc.VALUES},
        "drives": {k: n.drv.get(k, 0) for k in enc.DRIVES},
        "states": {"hunger": n.hunger, "thirst": n.thirst, "pain": max(0, 100 - n.hp), "fear": n.fear, "shock": 0,
                   "confusion": 0, "fatigue": 2 * n.fatigue - 100, "anger": n.anger, "stress": n.stress, "joy": n.joy},
        "stock_gap": {"food": ci(100 - food_days * 100 / 30, -100, 100), "fuel": ci(100 - wood_days * 100 / 30, -100, 100),
                      "tools": ci(50 - h.tools * 25, -100, 100)},
        "body": {"hp": n.hp, "strength": 35 if acat == "child" else 40 if acat == "elder" else 55, "load_ratio": 0,
                 "job_skill": n.skills.get(sim.jobs[n.job]["craft"], 0) if n.job else 0},
        "activity": {"progress": 1.0, "commitment": 0, "secs_since_decision": 3600 * max(0, sim.t - n.last_t)},
        "hours_since_meal": min(24, n.hunger / 7),
        "inventory": [], "tool_in_hand": "hands",
        "wardrobe": {"has": list(enc.OUTFITS), "worn": n.outfit if n.outfit in enc.OUTFITS else "everyday", "wear": 0},
    }

    # what n perceived in the last day, strongest first (charter 8: a new percept is why n decides again)
    seen = sorted((p for p in n.seen if sim.t - p[0] <= 24 and p[2] is not None and sim.npcs[p[2]].alive),
                  key=lambda p: (-p[4], -p[0]))[:MAX_EVENTS]
    # people: the targets of the options, the authors of the percepts and the targets of the goals first
    # (their pointers must resolve), then the most salient ties
    want = []
    for o in [c.target for c in options] + [p[2] for p in seen] + [g["target"] for g in n.goals]:
        if isinstance(o, int) and o not in want and o != n.id and sim.npcs[o].alive:
            want.append(o)
    scored = []
    for o, r in n.rel.items():
        m = sim.npcs[o]
        if m.alive and o not in want:
            here = 50 if (m.loc == n.loc and n.loc is not None) else 0
            scored.append((-(abs(r[AFF]) + r[GRUDGE] + r[ROMANCE] + r[FAM] // 2 + here), o))
    scored.sort()
    want += [o for _, o in scored]
    ents = []
    for o in want[:MAX_ENTITIES]:
        m = sim.npcs[o]
        r = n.rel.get(o) or [0] * 7
        l = sa.LINK.get(sim_link(sim, n, m), sim_link(sim, n, m))
        l = l if l in gs.LINK_PRIORS else "neighbor"
        ma = sim.age(m)
        mcat = gs.age_cat(ma)
        romance = r[ROMANCE]
        if mcat in ("child", "teen") or acat in ("child", "teen") or l in gs.BLOOD or sim.is_kin(n, m):
            romance = 0                                  # hard rule, also in the model's input
        here = m.loc == n.loc and n.loc is not None
        same_v = m.village == n.village
        if here:
            dist = 2.0
        elif same_v:
            dist = 200.0
        else:
            a, b = sim.villages[n.village].pos, sim.villages[m.village].pos
            dist = 1000.0 * ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5
        ents.append({
            "id": f"E{o}", "link": l, "age": ma, "age_cat": mcat, "love_status": love_status(sim, m),
            "visible_action": action_of(sim, m.plan_kind, job_of(sim, m)) if here else "none",
            "village": village_id(m.village),
            "rel": {"affection": r[AFF], "trust": r[TRUST], "respect": r[RESPECT], "romance": romance, "debt": r[DEBT],
                    "fear": 0, "familiarity": r[FAM], "grudge": r[GRUDGE]},
            "mood_toward": 0, "urge_to_interact": 0, "suspicion": 0, "indirect_threat": 0,
            "perceived": 1.0 if here else 0.0, "distance": min(30.0, dist / 100.0), "beauty": 50,
            "days_since_contact": 0 if here else 1, "rep_trust": 0, "rep_danger": 0, "understanding": 4, "age": ma,
            "worn": m.outfit,
        })
    eids = {e["id"] for e in ents}

    events = []
    for p in seen:
        t0, etype, agent, role, inten = p
        norm = {k: 0 for k in enc.NORMS}
        norm.update(EVENT_NORMS.get(etype, {}))
        events.append({"id": f"V{len(events) + 1}", "type": etype, "role": role, "source": "seen",
                       "agent": f"E{agent}" if f"E{agent}" in eids else None, "target": "me" if role == "target" else None,
                       "content": {}, "intensity": inten, "salience": inten, "understanding": 4, "reliability": 1.0,
                       "delay": 3600 * (sim.t - t0), "out_of_world": False, "norm": norm, "holders": 1})
    goals = []
    for g in n.goals[:MAX_GOALS]:
        tgt = g["target"]
        goals.append({"type": g["type"], "target": f"E{tgt}" if isinstance(tgt, int) else tgt, "partner": None,
                      "priority": g["priority"], "progress": 0, "deadline_h": 0})

    mems = []
    for m in sorted(n.mem, key=lambda x: (-x[4], -x[0])):
        if m[1] not in sa.MEMORY:
            continue
        t, broke = sa.MEMORY[m[1]]
        about = f"E{m[2]}" if m[2] is not None else None
        val = ci(m[3], -100, 100)
        mems.append({"id": f"M{len(mems) + 1}", "type": t, "agent": about if about in eids else None, "target": "me",
                     "third": None, "valence": val, "importance": ci(m[4], 0, 100), "severity": ci(abs(val), 0, 100) if val < 0 else 0,
                     "certainty": .6 if m[6] is not None else .95, "age_days": max(1, sim.day - m[0]),
                     "defining": m[4] >= 70, "secret": False, "source": "told" if m[6] is not None else "seen",
                     "what": None, "broke": (broke or gs.MEM_BROKE.get(t, "")) if val <= -20 else "",
                     "outcome": "unresolved" if val <= -20 else "none", "focus_knows": None})
        if len(mems) >= MAX_MEMORIES:
            break

    home = village_id(v.id)
    customs = {k: 50 for k in enc.NORMS}
    for k, b in gs.VILLAGES.get(home, ("center", "", {}))[2].items():
        customs[k] = ci(50 + b, 0, 100)
    problem = {"kind": "none", "need": "none", "urgency": 0, "progress": 0}
    if sim.epidemic.get(v.id) is not None:
        problem = {"kind": "sickness", "need": "care", "urgency": 70, "progress": 0}
    vfood = v.market.get("food", 0) / max(1, 4 * len(sim.villagers(v.id)))
    chief_r = n.rel.get(v.chief) if v.chief is not None else None
    ties = {}
    for o in n.rel:
        m = sim.npcs[o]
        if m.alive and m.village != n.village:
            ties[m.village] = ties.get(m.village, 0) + 1
    others = []
    for vid in sorted(sim.villages):
        if vid == v.id:
            continue
        others.append({"id": village_id(vid), "relation": 0, "trade_dep": 30, "threat": 0, "my_ties": ci(ties.get(vid, 0) * 15, 0, 100)})
    village = {"id": home, "frontier": gs.VILLAGES[home][0] if home in gs.VILLAGES else "center",
               "economy": ci(v.treasury / 10, -100, 100), "food": ci(vfood * 100 / 7 - 50, -100, 100), "security": 0, "rep": 0,
               "tension": ci(v.unrest, 0, 100), "cohesion": 50, "belonging": 70 if n.village == n.origin else 40,
               "loyalty": 0, "leader_trust": chief_r[TRUST] if chief_r else 0, "leader_legit": 0, "institution_trust": 0,
               "norms": customs, "problem": problem, "others": others[:4]}
    household = {"size": members, "head": bool(h.members) and h.members[0] == n.id, "cohesion": 50,
                 "wealth": ci((h.coin - 50) / 2, -100, 100), "honor": 0}

    cands = []
    for c in options:
        args = {}
        for k, x in c.args.items():
            if k == "skill":
                x = craft_job(sim, x)
            elif k == "e" and x not in ("self", "all") and x not in eids:
                continue                                 # target fell outside the six people: the option stays, unpointed
            args[k] = x
        cands.append({"a": c.fn, "args": args})
    return {"state": {"me": me, "entities": ents, "events": events, "memories": mems, "goals": goals, "items": [], "titles": [],
                      "village": village, "household": household}, "cands": cands}


def tokens(sim, n, options):
    """-> dict(cat, num, cand_first, n_cands) in tok-1."""
    enc, gs, sa, V = ai()
    return enc.encode(record(sim, n, options), V)
