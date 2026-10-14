#!/usr/bin/env python3
"""sim_adapter.py - turns the headless simulation's trajectories (sim-traj-0.1, emergence/sim/) into generator-0.4
records that build_dataset.py --sim-trajectories accepts.

What comes from the simulation (real, lived values): ME's age, sex, love status, job, current action, place, weather,
season, hour, traits, values, drives, needs, outfit, village; the people around ME (link, age, love status, relation
scalars) and ME's memories about them (kind, valence, salience, hearsay).
What is filled in by the generator (the simulation does not model it yet): temperament, fear toward each person, the
village scalars other than unrest, the household, titles, a routine event, goals; then build_candidates() proposes the
options and the reference decider labels them (source=2 in build_dataset).
The simulation's own candidates and utilities are kept in meta (sim_choice) but not used as labels: they live in the
simulation's action vocabulary (work, play, trade_trip...), not in the NPC contract.

Usage:
    python3 sim_adapter.py IN.jsonl OUT.jsonl            # prints coverage and rejected records
    python3 build_dataset.py --n 0 --name sim_seed7 --sim-trajectories OUT.jsonl
"""
import argparse
import hashlib
import json
import random
import sys
from collections import Counter

import generate_states as gs

VILLAGE = {"port": "sea_village", "mine": "mountain_village", "oasis": "desert_village", "bois": "forest_village",
           "bourg": "market_town"}
# sim job -> job of personnages/data/fiches.json (closest trade when the fiches have no such job)
JOB = {"salter": "saltworker", "shipwright": "boatwright", "caravaneer": "caravaner", "mason": "stonecutter",
       "dyer": "weaver", "glassblower": "potter", "brewer": "innkeeper", "jeweler": "smith", "water_carrier": "farmer"}
ACTION = {"play": "leisure", "eat": "eat", "sleep": "sleep", "social": "chat", "trade": "chat", "learn": "craft",
          "visit": "go_to", "pray": "rest", "court": "chat", "rest": "rest", "govern": "chat", "attend": "leisure",
          "care": "rest"}
PLACE = {"home": "home", "square": "square", "fields": "field", "tavern": "square", "forest": "forest",
         "workshop": "workshop", "temple": "square", "sea": "road", "mine": "mine", "saltpans": "field",
         "smithy": "workshop", "shipyard": "workshop", "quarry": "mine", "well": "well", "market": "square",
         "bakery": "workshop", "wilds": "road"}
LINK = {"kin": "sibling", "crush": "friend", "acquaintance": "neighbor", "lover": "partner", "master": "employer",
        "apprentice": "employee", "household": "neighbor"}
MEMORY = {"helped": ("help_given", None), "kindness": ("gift", None), "betrayed": ("promise_broken", None),
          "liar": ("lie_revealed", None), "insulted": ("insult", None), "theft_victim": ("theft", None),
          "brawl": ("strike", None), "murder": ("strike", "life"), "saw_theft": ("theft", None),
          "rejected": ("insult", None), "cowardice": ("insult", None), "embezzle": ("theft", None),
          "verdict_unjust": ("accusation", None)}        # other kinds (birth, deaths, weddings, affairs) are not kept yet
AGE_ORDER = ["child", "teen", "adult", "elder"]
FIXES = Counter()


def younger_cat(a, b):
    """Hard rules depend on the age category: when the two tables disagree, keep the younger one."""
    return min(a, b, key=AGE_ORDER.index)


def ci(x, lo, hi):
    return int(max(lo, min(hi, round(x))))


def convert(r, idx):
    sm, sv = r["state"]["me"], r["state"]["village"]
    key = f"{r.get('seed')}:{r['tick']}:{r['npc']}"
    rng = random.Random(int(hashlib.md5(key.encode()).hexdigest()[:12], 16))
    me = gs.gen_self(rng, "routine", r.get("seed", 0))
    me["age"] = sm["age"]
    me["age_cat"] = younger_cat(gs.age_cat(sm["age"]), sm["age_cat"])
    me["sex"] = sm["sex"]
    me["love_status"] = sm["love_status"] if gs.is_adult(me["age_cat"]) or sm["love_status"] == "single" else "single"
    job = JOB.get(sm["job"], sm["job"])
    me["job"] = job if job in gs.JOB_ACTION or job == "none" else "none"
    act = sm["current_action"]
    me["current_action"] = gs.JOB_ACTION[me["job"]][0] if act == "work" and me["job"] in gs.JOB_ACTION else ACTION.get(act, "idle")
    me["place_type"] = PLACE.get(sm["place_type"], "road")
    me["weather"], me["season"], me["hour"] = sm["weather"], sm["season"], float(sm["hour"])
    for k, v in sm["traits"].items():
        if k in me["traits"]:
            me["traits"][k] = v
    if "ambition" in sm["drives"]:
        me["traits"]["ambition"] = sm["drives"]["ambition"]
    for grp in ("values", "drives", "states"):
        for k, v in sm[grp].items():
            if k in me[grp]:
                me[grp][k] = v
    if "food" in sm["stock_gap"]:
        me["stock_gap"]["food"] = sm["stock_gap"]["food"]
    me["body"]["hp"] = sm["body"].get("hp", me["body"]["hp"])
    me["body"]["job_skill"] = sm["body"].get("job_skill", me["body"]["job_skill"]) if me["job"] != "none" else 0
    # people: those present first, then the strongest ties; at most 4 (generator limit)
    sents = sorted(r["state"]["entities"], key=lambda e: (not e["here"], -abs(e["rel"]["affection"])))[:4]
    links = [LINK.get(e["link"], e["link"]) for e in sents]
    links = [l if l in gs.LINK_PRIORS else "neighbor" for l in links]
    for i, (l, e) in enumerate(zip(links, sents)):    # the generator's kin ages: a parent is at least 16 years older
        gap = (sm["age"] - e["age"]) if l == "child" else (e["age"] - sm["age"]) if l == "parent" else 99
        if gap < 16:
            links[i] = "friend"
            FIXES["kin_age_relabelled_friend"] += 1
    ents = gs.gen_entities(rng, "routine", me, len(links), r.get("seed", 0), list(links)) if links else []
    uid2id = {}
    for e, s in zip(ents, sents):
        e["age"] = s["age"]
        e["age_cat"] = younger_cat(gs.age_cat(s["age"]), s["age_cat"])
        e["love_status"] = s["love_status"] if gs.is_adult(e["age_cat"]) else "single"
        for k, v in s["rel"].items():
            if k == "familiarity":
                e["rel"]["familiarity"] = v
            elif k in e["rel"]:
                e["rel"][k] = v
        if not gs.is_adult(e["age_cat"]) or not gs.is_adult(me["age_cat"]) or e["link"] in gs.BLOOD:
            e["rel"]["romance"] = 0
        if e["rel"]["trust"] > 20:
            e["suspicion"] = min(e.get("suspicion", 0), 40)
        gap = (me["age"] - e["age"]) if e["link"] == "child" else (e["age"] - me["age"]) if e["link"] == "parent" else 99
        if gap < 16:
            e["link"] = "friend"
            FIXES["kin_age_relabelled_friend"] += 1
        if s["here"]:
            e["distance"] = min(e["distance"], 8.0)
        uid2id[s["uid"]] = e["id"]
    me["wardrobe"]["worn"] = sm["outfit"] if sm["outfit"] in gs.OUTFITS else "everyday"
    items = []
    titles = gs.gen_titles(rng, me, ents)
    village, household = gs.gen_village(rng, me, ents, titles, "routine")
    home = VILLAGE.get(sv["id"], village["id"])
    for o in village["others"]:                       # the generator drew another home: swap ids, keep the scalars
        if o["id"] == home:
            o["id"] = village["id"]
    village["id"] = home
    village["frontier"] = gs.VILLAGES[home][0]
    village["tension"] = ci(sv.get("unrest", 0), 0, 100)
    for e in ents:
        e["village"] = village["id"] if e["link"] != "stranger" else e.get("village", village["id"])
    events = gs.build_events(rng, "routine", me, ents, items, titles, village)[:2]
    gs.apply_event_effects(rng, me, ents, events)
    mems = gs.gen_memories(rng, me, ents, "routine", events)     # memories that explain the relation values
    real = []
    for m in sorted(r["state"]["memories"], key=lambda m: -m["salience"]):
        if m["about"] in uid2id and m["kind"] in MEMORY:
            t, broke = MEMORY[m["kind"]]
            val = ci(m["valence"], -100, 100)
            real.append({"type": t, "agent": uid2id[m["about"]], "target": "me", "valence": val,
                         "importance": ci(m["salience"], 0, 100), "age_days": max(1, r["tick"] // 24 - m["day"]),
                         "certainty": .6 if m["hearsay"] else .95, "defining": m["salience"] >= 70, "source": "told" if m["hearsay"] else "seen",
                         "why": "", "secret": False, "payload": {}, "what": "", "broke": (broke or gs.MEM_BROKE.get(t, "")) if val <= -20 else "",
                         "third": None, "outcome": "unresolved" if val <= -20 else "none", "severity": ci(abs(val), 5, 100) if val <= -20 else 0})
    mems = (real + mems)[:9]
    for i, m in enumerate(mems, 1):
        m["id"] = f"M{i}"
        m.setdefault("focus_knows", None)
    goals = gs.gen_goals(rng, me, ents, events, "routine")
    cands = gs.build_candidates(rng, me, ents, events, items, False, mems, titles, goals, village)
    rec = {"id": f"sim{r.get('seed', 0)}_{r['tick']}_{r['npc']}", "schema": gs.VERSION, "family": "routine",
           "state": {"me": me, "entities": ents, "events": events, "memories": mems, "goals": goals, "items": items,
                     "titles": titles, "village": village, "household": household},
           "cands": cands, "sim_choice": r.get("chosen")}
    rec["view"] = gs.view_of_state(rec["state"], cands)
    rec["text"] = gs.view_text(rec["view"])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    a = ap.parse_args()
    ok, bad, unk = 0, Counter(), Counter()
    with open(a.out, "w", encoding="utf-8") as f:
        for i, line in enumerate(open(a.inp, encoding="utf-8")):
            r = json.loads(line)
            sm = r["state"]["me"]
            for k, tab in (("job", JOB), ("current_action", ACTION), ("place_type", PLACE)):
                v = sm[k]
                if v not in tab and not (k == "job" and (v in gs.JOB_ACTION or v == "none")) and not (k == "current_action" and v == "work"):
                    unk[f"{k}:{v}"] += 1
            if r["state"]["village"]["id"] not in VILLAGE:
                unk["village:" + r["state"]["village"]["id"]] += 1
            rec = convert(r, i)
            v = gs.validate(rec)
            if v:
                bad.update(v)
                continue
            f.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n")
            ok += 1
    print(f"{ok} records written to {a.out}; rejected by the validator: {sum(bad.values())} {dict(bad.most_common(8))}")
    if FIXES:
        print("adjusted:", dict(FIXES))
    if unk:
        print("values with no mapping (defaulted):", dict(unk.most_common(12)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
