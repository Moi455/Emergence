"""Exports: training trajectories (JSONL) and viewer data (JSON).

Trajectory sampling uses a hash of (seed, tick, npc), never the sim RNG, so
turning export on or off does not change the simulation.
"""
import json

from .rng import hash_ints
from .model import AFF, TRUST, RESPECT, ROMANCE, FAM, GRUDGE, DEBT, REL_FIELDS

TRAJ_SCHEMA = "sim-traj-0.1"


def age_cat(a):
    return "child" if a < 12 else "teen" if a < 18 else "adult" if a < 60 else "elder"


def link(sim, n, m):
    if m.id == n.partner:
        return "spouse"
    if m.id in n.parents:
        return "parent"
    if m.id in n.children:
        return "child"
    if sim.close_kin(n, m):
        return "sibling"
    if sim.is_kin(n, m):
        return "kin"
    if n.mentor == m.id:
        return "master"
    if m.id in n.apprentices:
        return "apprentice"
    if m.hh == n.hh:
        return "household"
    r = n.rel.get(m.id)
    if r:
        if r[GRUDGE] >= 50:
            return "enemy"
        if r[ROMANCE] >= 50:
            return "lover" if n.affair == m.id else "crush"
        if r[AFF] >= 50:
            return "friend"
        if r[FAM] >= 20:
            return "acquaintance"
    return "stranger"


def to_state(sim, n):
    """Decision input in the vocabulary of ai/npc_pipeline/samples/schema.json (0.3), plus village and outfit."""
    a = sim.age(n)
    h = sim.hh(n)
    v = sim.villages[n.village]
    love = "married" if n.partner is not None else "engaged" if n.engaged is not None else "single"
    me = {
        "uid": n.id, "age": a, "age_cat": age_cat(a), "sex": n.sex, "love_status": love,
        "job": n.job or ("apprentice" if n.learning else "none"), "current_action": n.plan_kind,
        "place_type": (n.loc or "home").split(":")[1] if n.loc and ":" in n.loc else "home",
        "weather": sim.weather(n.village), "season": sim.season(), "hour": sim.hour,
        "traits": dict(n.tr), "values": dict(n.val), "drives": dict(n.drv),
        "states": {"hunger": n.hunger, "thirst": n.thirst, "pain": 100 - n.hp, "fear": n.fear, "fatigue": n.fatigue,
                   "anger": n.anger, "stress": n.stress, "joy": n.joy, "grief": n.grief, "lonely": n.lonely, "sick": n.sick},
        "stock_gap": {"food": h.goods.get("food", 0) // 10 - 3 * len(h.members), "coin": h.coin + n.coin},
        "body": {"hp": n.hp, "job_skill": n.skills.get(sim.jobs[n.job]["craft"], 0) if n.job else 0},
        "outfit": n.outfit, "belief_beyond": n.belief, "titles": list(n.titles),
        "skills": {c: s for c, s in sorted(n.skills.items()) if s >= 10},
    }
    village = {"id": v.id, "kind": v.kind, "pop": None, "unrest": v.unrest, "tax_pct": v.decrees["tax_pct"],
               "food_price": v.prices.get("food"), "is_chief": v.chief == n.id, "frontier": v.frontier}
    ents = []
    scored = []
    for o, r in n.rel.items():
        m = sim.npcs[o]
        if not m.alive:
            continue
        here = 50 if (m.loc == n.loc and n.loc is not None) else 0
        scored.append((-(abs(r[AFF]) + r[GRUDGE] + r[ROMANCE] + r[FAM] // 2 + here), o))
    scored.sort()
    for _, o in scored[:6]:
        m = sim.npcs[o]
        r = n.rel[o]
        ents.append({"id": f"E{o}", "uid": o, "link": link(sim, n, m), "age": sim.age(m), "age_cat": age_cat(sim.age(m)),
                     "love_status": "married" if m.partner is not None else "single", "job": m.job,
                     "here": m.loc == n.loc, "rel": {REL_FIELDS[i]: r[i] for i in range(7)}})
    mems = sorted(n.mem, key=lambda x: (-x[4], -x[0]))[:9]
    memories = [{"day": m[0], "kind": m[1], "about": m[2], "valence": m[3], "salience": m[4], "hearsay": m[6] is not None} for m in mems]
    return {"me": me, "village": village, "entities": ents, "memories": memories}


def traj_begin(sim, n, reason, cands, scores, best, plan, outcome):
    if sim.traj_f is None:
        return
    if hash_ints(sim.seed, 5, sim.t, n.id) % 1000000 >= sim.traj_ppm:
        return
    rec = {
        "schema_version": TRAJ_SCHEMA, "seed": sim.seed, "tick": sim.t, "npc": n.id,
        "request": {"reason": reason},
        "state": to_state(sim, n),
        "brain": sim.brain.name,
        "candidates": [{"id": c.key, "kind": c.kind, "target": c.target if isinstance(c.target, (int, str)) else None,
                        "utility": c.u, "factors": c.factors, "fn": getattr(c, "fn", None), "args": getattr(c, "args", None)}
                       for c in cands],
        "scores": scores, "chosen": best.key,
        "plan": {k: v for k, v in plan.items() if k in ("steps", "on_done")} if plan else None,
        "outfit": n.outfit,
        "immediate": outcome,
    }
    n.pending_traj = rec


def traj_end(sim, n):
    rec = n.pending_traj
    n.pending_traj = None
    plan = n.plan or {}
    out = rec.pop("immediate", None) or {}
    rec["result"] = {"status": "interrupted" if plan.get("interrupted") else out.get("status", "done"),
                     "reason": out.get("reason"), "gains": out.get("gains", {}), "ended_tick": sim.t,
                     "after": {"hunger": n.hunger, "fatigue": n.fatigue, "joy": n.joy, "stress": n.stress, "hp": n.hp}}
    sim.traj_f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    sim.traj_count += 1


# ------------------------------------------------------------------ viewer
def viewer_data(sim, elapsed_s=None):
    D = sim.DPY
    people = []
    for n in sim.npcs:
        top = sorted(n.rel.items(), key=lambda kv: (-(abs(kv[1][AFF]) + kv[1][GRUDGE] + kv[1][ROMANCE]), kv[0]))[:10]
        people.append({
            "id": n.id, "n": n.name, "s": n.sex, "b": n.born, "d": n.died, "c": n.cause, "v": n.village, "o": n.origin,
            "j": n.job, "p": list(n.parents), "sp": n.partners, "k": n.children, "al": n.alive,
            "sk": {c: s for c, s in sorted(n.skills.items(), key=lambda kv: -kv[1]) if s >= 10},
            "ti": n.titles, "g": n.groups, "le": n.legends, "be": n.belief, "ex": n.exiled,
            "xp": n.expeditions, "md": n.max_depth, "ou": n.outfit, "oc": n.outfit_changes,
            "tr": n.tr, "va": n.val, "dr": n.drv, "or": n.orient,
            "st": [n.hunger, n.fatigue, n.lonely, n.stress, n.joy, n.anger, n.grief, n.hp, n.sick],
            "r": [[o, r[AFF], r[TRUST], r[RESPECT], r[ROMANCE], r[FAM], r[GRUDGE]] for o, r in top],
            "m": [[m[0], m[1], m[2], m[3], m[4], m[6] is not None] for m in sorted(n.mem, key=lambda x: -x[4])[:12]],
            "ev": n.lifelog[-60:], "mi": n.tracked, "ap": n.apprentices, "me": n.mentor, "lr": n.learning,
        })
    villages = []
    for v in sim.vlist:
        villages.append({"id": v.id, "name": v.name, "kind": v.kind, "pos": v.pos, "frontier": v.frontier,
                         "frontier_fr": v.frontier_fr, "chief": v.chief, "decrees": v.decrees, "treasury": v.treasury,
                         "chiefs": v.chief_history, "lost": v.lost_crafts, "legends": v.legends, "unrest": v.unrest})
    graph = {}
    for v in sim.vlist:
        edges = []
        vs = sim.villagers(v.id)
        ids = {n.id for n in vs}
        for n in vs:
            for o, r in n.rel.items():
                if o in ids and o > n.id:
                    r2 = sim.npcs[o].rel.get(n.id)
                    aff = (r[AFF] + (r2[AFF] if r2 else 0)) // 2
                    gr = max(r[GRUDGE], r2[GRUDGE] if r2 else 0)
                    rom = max(r[ROMANCE], r2[ROMANCE] if r2 else 0)
                    if aff >= 55 or gr >= 45 or rom >= 60:
                        edges.append([n.id, o, aff, gr, rom])
        graph[v.id] = edges
    minds = {n.id: n.mind for n in sim.npcs if n.tracked}
    return {
        "schema_version": "sim-viewer-0.1", "seed": sim.seed, "days": sim.day, "dpy": D, "dpm": sim.DPM,
        "elapsed_s": elapsed_s, "decisions": sim.decisions, "interactions": sim.interactions,
        "counts": sim.counts, "villages": villages, "people": people, "events": sim.events,
        "monthly": sim.monthly, "crafts": sim.craft_series, "craft_names": {c: s["fr"] for c, s in sim.crafts.items()},
        "job_names": {j: s["fr"] for j, s in sim.jobs.items()}, "outfits": sim.C["outfits"],
        "groups": [{"id": g.id, "name": g.name, "kind": g.kind, "v": g.village, "f": g.founder, "m": g.members,
                    "craft": g.craft, "day": g.founded, "closed": g.closed, "alive": g.alive} for g in sim.groups],
        "legends": [{"id": L.id, "t": L.title, "f": L.frontier, "v": L.village, "h": L.hero, "day": L.day,
                     "k": L.kind, "n": L.tellers, "b": sum(1 for n in sim.npcs if n.alive and L.id in n.legends)} for L in sim.legends],
        "graph": graph, "minds": minds, "live": sim.live,
        "lost_world": sorted(sim.lost_world),
    }
