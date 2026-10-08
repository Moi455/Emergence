#!/usr/bin/env python3
"""generate_states.py (schema 0.4)

Generates synthetic NPC decision situations (state + candidate actions) for
teacher labelling and for student pre-training.

Coherence principles
  * personality comes from 5 latent factors, so traits correlate
  * body/needs derive from clock, injuries and recent events
  * relations derive from the link type (spouse, child, rival...)
  * a few "contradictions" are injected on purpose (loved but distrusted,
    wounded but numb...) and each one is EXPLAINED by a memory or a state,
    so that the label never needs an impossible story
  * hard safety rules: no romantic/sexual action involving a child category,
    none between kin; verified by --check

Usage (fish or bash):
  python3 generate_states.py --n 2000 --seed 1 --out states.jsonl --check
  python3 generate_states.py --dump-actions-md
  python3 generate_states.py --dump-schema schema.json
"""
import argparse, hashlib, json, math, random, sys
from collections import Counter

VERSION = "0.4"

# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
TRAITS = ["aggression", "courage", "empathy", "sociability", "honesty",
          "impulsivity", "curiosity", "tolerance", "justice", "ambition", "grudge"]  # [-100,100]
TEMPERAMENT = ["reactivity", "resilience"]                             # [0,100]
VALUES = ["kin_protection", "property_respect", "honor", "life_value",
          "romantic_fidelity", "taboo_sensitivity"]                    # [0,100]
DRIVES = ["libido", "social_need", "achievement", "hoarding"]          # [0,100]
STATES_U = ["hunger", "thirst", "pain", "fear", "shock", "confusion"]  # [0,100]
STATES_S = ["fatigue", "anger", "stress", "joy"]                       # [-100,100]
STOCK = ["food", "fuel", "tools"]                                      # [-100,100]
REL_S = ["affection", "trust", "respect", "romance", "debt"]           # [-100,100]
REL_U = ["fear", "familiarity", "grudge"]                              # [0,100]
NORMS = ["kin", "property", "honor", "life", "fidelity", "truth", "fairness", "taboo"]

SCHEMA = {
    "version": VERSION,
    "self": {"traits": TRAITS, "temperament": TEMPERAMENT, "values": VALUES,
             "drives": DRIVES, "states_unsigned": STATES_U,
             "states_signed": STATES_S, "stock_gap": STOCK,
             "body": ["hp", "strength", "load_ratio", "job_skill"],
             "activity": ["progress", "commitment", "secs_since_decision"],
             "time": ["hour_sin", "hour_cos", "season_sin", "season_cos"],
             "categories": ["age_cat", "love_status", "job", "current_action",
                            "weather", "place_type", "tool_in_hand"]},
    "inventory": {"scalars": ["qty", "quality", "wear"], "categories": ["item_type"], "max": 8},
    "title": {"scalars": ["authority", "confidence", "legitimacy", "n_claimants"],
              "categories": ["title_concept", "my_role"], "pointers": ["holder", "claimants"], "max": 6},
    "link": {"scalars": ["believed_affinity", "confidence"], "categories": ["link_kind"], "pointers": ["a", "b"], "max": 6,
             "status": "specified; third-party ties (who likes whom); the generator only produces them as link_belief memories"},
    "place": {"scalars": ["danger", "fondness", "taboo", "n_memories"], "max": 1,
              "status": "specified; computed by memory_service.place_reputation"},
    "object": {"scalars": ["value", "owner_known_conf", "concealed_evidence", "owned_by_me", "owned_by_other"],
               "categories": ["item_type"], "pointers": ["believed_owner"], "max": 8,
               "status": "specified; nearby objects with believed owner (social_rules.believed_owner)"},
    "group": {"scalars": ["identification", "cohesion", "rank"], "categories": ["group_kind"], "pointers": ["leader"], "max": 3,
              "status": "specified only (case 29)"},
    "entity": {"relation_signed": REL_S, "relation_unsigned": REL_U,
               "mood": ["mood_toward", "urge_to_interact"],
               "social_flags": ["suspicion", "indirect_threat"],
               "perception": ["chemistry", "perceived", "distance", "beauty",
                              "days_since_contact", "rep_trust", "rep_danger",
                              "understanding"],
               "categories": ["kin_links", "age_cat", "love_status",
                              "visible_action"]},
    "event": {"scalars": ["intensity", "salience", "understanding",
                          "reliability", "delay", "out_of_world",
                          "force", "politeness", "negation", "conditional", "apparent_intent"],
              "norm_violation": NORMS,
              "categories": ["type", "role", "source", "speech_act", "modality"]},
    "memory": {"scalars": ["age_days", "certainty", "importance", "valence",
                           "defining", "secret", "focus_knows", "conflict"], "categories": ["type", "role", "source"]},
    "goal": {"scalars": ["priority", "progress", "deadline_h"],
             "categories": ["type", "target"], "pointers": ["partner"]},
}

# --------------------------------------------------------------------------
# Action vocabulary (model output).  args codes:
#  E entity  I item  R resource node  L location  A activity  F fact/claim
#  P proposal id  K skill  M mode  C commitment id
# --------------------------------------------------------------------------
try:
    import social_rules as sr
    import dialogue_protocols as dp
    from plan_contract import FUNCTIONS, CONDITIONS, TOOLS, TOOL_TABLE, DIRS, validate_plan, resolve_preconditions
    import representation as rp
except ModuleNotFoundError as _e:
    sys.exit(f"Missing project file: {_e.name}.py. Your folder is incomplete. Unzip the complete archive again: "
             "python3 -m zipfile -e npc_pipeline.zip ~/")

# Functions of the shared contract; keep the old "ACTIONS" shape for the rest of this file.
ACTIONS = [dict(id=f["id"], cat=f["cat"],
                args=",".join(f"{k}:{v['type']}{'?' if v['optional'] else ''}" for k, v in f["args"].items()),
                core=f["core"], note=f["desc"]) for f in FUNCTIONS.values()]
ACTION_IDS = [a["id"] for a in ACTIONS]

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def is_adult(cat):
    """'elder' is an adult too: romance rules apply to adult + elder."""
    return cat in ("adult", "elder")


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def ci(x, lo, hi):
    return int(clamp(round(x), lo, hi))


def sc(x):
    return ci(40 * x, -100, 100)


def age_cat(age):
    return "child" if age < 14 else "adolescent" if age < 18 else "adult" if age < 60 else "elder"


def pair_uniform(world_seed, a, b):
    h = hashlib.md5(f"{world_seed}|{a}|{b}".encode()).hexdigest()
    return (int(h[:12], 16) / float(16 ** 12)) * 2 - 1


HOUR_W = [1, 1, 1, 1, 1, 3, 6, 8, 9, 9, 9, 9, 7, 6, 8, 8, 8, 8, 7, 6, 5, 3, 2, 1]
SEASONS = ["spring", "summer", "autumn", "winter"]
WEATHER_W = {"spring": [("clear", 4), ("cloudy", 3), ("rain", 3), ("fog", 1), ("wind", 1)],
             "summer": [("clear", 7), ("cloudy", 2), ("rain", 1), ("storm", 1)],
             "autumn": [("clear", 3), ("cloudy", 4), ("rain", 4), ("fog", 2), ("wind", 2)],
             "winter": [("clear", 3), ("cloudy", 3), ("snow", 4), ("fog", 2), ("wind", 1)]}
LOCS = ["home", "field", "forest", "mine", "well", "square", "workshop", "road"]
ITEMS = {"bread": "food", "apple": "food", "meat": "food", "water_jug": "drink",
         "firewood": "fuel", "coal": "fuel", "stone": "material", "axe": "tool",
         "hoe": "tool", "seeds": "seed", "cloth": "material", "knife": "tool"}
JOBS_ADULT = [("farmer", 4), ("woodcutter", 1.5), ("miner", 1.5), ("smith", 1),
              ("carpenter", 1), ("cook", 1), ("healer", .5), ("trader", 1), ("hunter", 1)]
JOB_ACTION = {"farmer": ["till", "plant", "harvest", "fetch_water"], "woodcutter": ["cut"],
              "miner": ["dig"], "smith": ["craft"], "carpenter": ["craft", "place"],
              "cook": ["craft"], "healer": ["craft"], "trader": ["chat"], "hunter": ["search"],
              "apprentice": ["craft", "dig"]}
ACTION_PLACE = {"till": "field", "plant": "field", "harvest": "field", "fetch_water": "well", "dig": "mine", "cut": "forest", "place": "workshop", "search": "forest",
                "craft": "workshop", "chat": "square", "sleep": "home", "rest": "home",
                "eat": "home", "go_to": "road", "wander": "road", "leisure": "square",
                "wait": "square", "idle": "home"}
JOB_TOOLS = {"farmer": ("hoe", "shovel"), "woodcutter": ("axe",), "miner": ("pickaxe", "shovel"),
             "smith": ("trowel",), "carpenter": ("axe", "trowel"), "apprentice": ("trowel", "pickaxe")}
TITLES = ["mayor", "deputy", "lawyer", "elder", "judge", "treasurer", "scribe", "tax_collector"]
ACTIVITIES = ["hopscotch", "storytelling", "dice", "dancing", "wrestling_for_fun", "fishing_trip"]
COMMIT_BY_ACTION = {"sleep": 70, "craft": 60, "till": 50, "plant": 50, "harvest": 55,
                    "dig": 55, "cut": 55, "place": 45, "search": 25, "fetch_water": 35, "chat": 25, "leisure": 30,
                    "rest": 20, "wander": 10, "wait": 8, "idle": 5, "go_to": 30, "eat": 40}

# link priors: (mu, sd) for relation scalars
LINK_PRIORS = {
    "spouse":   dict(affection=(60, 25), trust=(50, 30), respect=(40, 25), fear=(5, 8), fam=(95, 4), grudge=(8, 12)),
    "partner":  dict(affection=(55, 25), trust=(40, 30), respect=(35, 25), fear=(5, 8), fam=(80, 12), grudge=(8, 12)),
    "child":    dict(affection=(85, 12), trust=(35, 25), respect=(10, 20), fear=(0, 3), fam=(100, 1), grudge=(3, 6)),
    "parent":   dict(affection=(65, 30), trust=(45, 30), respect=(50, 25), fear=(12, 15), fam=(100, 1), grudge=(10, 15)),
    "sibling":  dict(affection=(50, 35), trust=(40, 30), respect=(25, 25), fear=(8, 12), fam=(100, 2), grudge=(15, 20)),
    "friend":   dict(affection=(55, 25), trust=(45, 25), respect=(30, 25), fear=(3, 6), fam=(70, 18), grudge=(5, 10)),
    "neighbor": dict(affection=(15, 30), trust=(15, 30), respect=(15, 25), fear=(5, 10), fam=(55, 22), grudge=(10, 15)),
    "colleague": dict(affection=(10, 30), trust=(20, 30), respect=(20, 30), fear=(6, 10), fam=(60, 20), grudge=(10, 15)),
    "employer": dict(affection=(0, 30), trust=(10, 30), respect=(30, 30), fear=(22, 20), fam=(55, 20), grudge=(10, 15)),
    "employee": dict(affection=(5, 30), trust=(15, 30), respect=(20, 30), fear=(4, 8), fam=(55, 20), grudge=(8, 12)),
    "rival":    dict(affection=(-40, 25), trust=(-20, 30), respect=(10, 30), fear=(20, 25), fam=(55, 22), grudge=(45, 25)),
    "enemy":    dict(affection=(-75, 15), trust=(-70, 20), respect=(-30, 30), fear=(40, 30), fam=(50, 25), grudge=(70, 20)),
    "stranger": dict(affection=(0, 15), trust=(0, 15), respect=(0, 15), fear=(10, 15), fam=(3, 5), grudge=(0, 4)),
}
KIN = {"child", "parent", "sibling", "spouse"}   # loved ones protected by the 'kin' norm
BLOOD = {"child", "parent", "sibling"}           # blood relatives: adult romance is governed by the taboo value, not by a hard rule
ALLOW_ADULT_KIN_ROMANCE = True                   # design decision (see --no-adult-kin-romance); children are NEVER allowed
ADULT_ONLY_LINKS = {"spouse", "partner", "employer", "employee", "colleague"}
LINK_LABEL = {"spouse": "spouse", "partner": "partner", "child": "my child", "parent": "my parent",
              "sibling": "my sibling", "friend": "friend", "neighbor": "neighbor",
              "colleague": "colleague", "employer": "employer", "employee": "employee",
              "rival": "rival", "enemy": "enemy", "stranger": "stranger"}


def choose_w(rng, pairs):
    items, ws = zip(*pairs)
    return rng.choices(items, weights=ws)[0]


# --------------------------------------------------------------------------
# Self
# --------------------------------------------------------------------------
def gen_self(rng, fam, world_seed):
    r = rng.random()
    age = rng.randint(6, 13) if r < .06 else rng.randint(14, 17) if r < .12 else \
        rng.randint(18, 59) if r < .82 else rng.randint(60, 82)
    if fam in ("romance", "harmful_proposal", "kin_advance") and age < 18:
        age = rng.randint(18, 59)
    ac = age_cat(age)
    z = {k: rng.gauss(0, 1) for k in "AXCOH"}
    g = lambda: rng.gauss(0, 1)
    traits = {
        "aggression": sc(-.5 * z["A"] + .6 * z["H"] + .5 * g()),
        "courage": sc(.3 * z["X"] + .3 * z["H"] - .1 * z["A"] + .8 * g()),
        "empathy": sc(.7 * z["A"] + .1 * z["O"] + .5 * g()),
        "sociability": sc(.8 * z["X"] + .2 * z["A"] + .4 * g()),
        "honesty": sc(.5 * z["A"] + .5 * z["C"] + .6 * g()),
        "impulsivity": sc(.7 * z["H"] - .5 * z["C"] + .5 * g()),
        "curiosity": sc(.8 * z["O"] + .1 * z["X"] + .5 * g()),
        "justice": sc(.3 * z["A"] + .4 * z["C"] + .2 * z["O"] + .8 * g()),
        "grudge": sc(-.4 * z["A"] + .4 * z["H"] + .7 * g()),
        # 0.4: tolerance (acceptance of strangers, other villages, odd customs) and ambition (wants status, wealth, titles)
        "tolerance": sc(.5 * z["O"] + .35 * z["A"] - .2 * z["H"] + .6 * g()),
        "ambition": sc(.4 * z["X"] + .35 * z["C"] - .3 * z["A"] + .25 * z["H"] + .6 * g()),
    }
    flips = []
    for k in TRAITS:           # deliberate "out of character" traits
        if rng.random() < .05:
            traits[k] = rng.randint(-100, 100)
            flips.append(k)
    temperament = {"reactivity": ci(50 + 22 * (.6 * z["H"] + .6 * g()), 0, 100),
                   "resilience": ci(55 + 20 * (.4 * z["C"] - .3 * z["H"] + .6 * g()), 0, 100)}
    values = {
        "kin_protection": ci(65 + 12 * z["A"] + 20 * g(), 0, 100),
        "property_respect": ci(55 + .25 * traits["honesty"] + 20 * g(), 0, 100),
        "honor": ci(50 + .2 * traits["aggression"] + 25 * g(), 0, 100),
        "life_value": ci(65 + .2 * traits["empathy"] - .2 * traits["aggression"] + 15 * g(), 0, 100),
        "romantic_fidelity": ci(55 + .2 * traits["honesty"] + 25 * g(), 0, 100),
    }
    values["taboo_sensitivity"] = ci(65 + .2 * (values["honor"] - 50) + 18 * g(), 0, 100)
    hour = rng.choices(range(24), weights=HOUR_W)[0] + rng.random()
    season = rng.choice(SEASONS)
    weather = choose_w(rng, WEATHER_W[season])
    if ac == "child":
        job = "none"
    elif ac == "adolescent":
        job = rng.choice(["apprentice", "none"])
    elif ac == "adult":
        job = choose_w(rng, JOBS_ADULT)
    else:
        job = choose_w(rng, [("farmer", 2), ("none", 2), ("cook", 1), ("carpenter", 1)])
    night = hour < 5 or hour >= 22
    if night and rng.random() < .6:
        doing = "sleep"
    elif 6 <= hour < 18 and job in JOB_ACTION and rng.random() < .65:
        doing = rng.choice(JOB_ACTION[job])
    else:
        doing = rng.choice(["rest", "leisure", "wander", "wait", "chat", "go_to", "idle"])
    place = ACTION_PLACE.get(doing, "road")
    if doing == "dig":
        place = "mine"
    if doing == "craft" and job == "cook":
        place = "home"
    status = choose_w(rng, {"child": [("single", 1)],
                            "adolescent": [("single", 8), ("courting", 2)],
                            "adult": [("single", 30), ("courting", 10), ("partnered", 15), ("married", 35), ("separated", 5), ("widowed", 5)],
                            "elder": [("married", 40), ("widowed", 40), ("single", 10), ("separated", 10)]}[ac])
    # body / needs
    h_meal = rng.uniform(.5, 11)
    h_drink = rng.uniform(.3, 8)
    hunger = clamp(7 * h_meal - 8 + rng.gauss(0, 8), 0, 100)
    thirst = clamp(11 * h_drink - 6 + rng.gauss(0, 8) + (8 if season == "summer" else 0), 0, 100)
    wake = 5.5 + rng.gauss(0, .8)
    awake = (hour - wake) % 24
    if doing == "sleep":
        fatigue = clamp(40 + rng.gauss(0, 15), -100, 100)
    else:
        fatigue = clamp(9 * (awake - 9) + rng.gauss(0, 12), -100, 100)
    injured = rng.random() < .12
    hp = rng.randint(15, 70) if injured else rng.choice([rng.randint(85, 100)] * 4 + [rng.randint(70, 85)])
    pain = clamp(max((100 - hp) * .85 + rng.gauss(0, 6), (100 - hp) * .7), 0, 100) if hp < 90 else clamp(rng.gauss(2, 3), 0, 15)
    base_age_factor = {"child": .6, "adolescent": .85, "adult": 1, "elder": .65}[ac]
    me = {
        "uid": rng.randint(1, 10 ** 6), "age": age, "age_cat": ac, "love_status": status,
        "job": job, "current_action": doing, "place_type": place, "weather": weather,
        "season": season, "hour": round(hour, 2),
        "traits": traits, "temperament": temperament, "values": values,
        "drives": {
            "libido": 0 if ac == "child" else ci(rng.uniform(10, 80) * (.5 if ac == "elder" else 1), 0, 100),
            "social_need": ci(25 + .2 * traits["sociability"] + 18 * g(), 0, 100),
            "achievement": ci(45 + .15 * traits["ambition"] + 16 * g() - (12 if job == "none" else 0), 0, 100),
            "hoarding": ci(25 + 14 * g(), 0, 100)},
        "states": {"hunger": hunger, "thirst": thirst, "pain": pain, "fear": clamp(abs(rng.gauss(0, 6)), 0, 100),
                   "shock": 0.0, "confusion": 0.0, "fatigue": fatigue,
                   "anger": clamp(rng.gauss(-15, 15), -100, 100),
                   "stress": clamp(rng.gauss(0, 18) + .2 * hunger, -100, 100),
                   "joy": clamp(rng.gauss(10, 25) - .2 * hunger - .3 * pain, -100, 100)},
        "stock_gap": {"food": sc(rng.gauss(0, .9) + (.6 if season == "winter" else 0)),
                      "fuel": sc(rng.gauss(0, .8) + (1.1 if season == "winter" else -.4 if season == "summer" else 0)),
                      "tools": sc(rng.gauss(0, .8))},
        "body": {"hp": hp, "strength": ci(55 * base_age_factor + 18 * g() + 10, 5, 100),
                 "load_ratio": round(clamp(rng.betavariate(2, 4), 0, 1), 2),
                 "job_skill": 0 if job == "none" else ci(15 + max(0, age - 16) * 1.5 + 10 * g(), 0, 98)},
        "activity": {"progress": round(rng.random(), 2),
                     "commitment": ci(COMMIT_BY_ACTION.get(doing, 10) + 10 * g(), 0, 100),
                     "secs_since_decision": rng.randint(0, 600)},
        "flips": flips, "hours_since_meal": round(h_meal, 1),
    }
    # inventory: tools and goods (the model sees one token per item; max 8)
    inv = []
    for t_ in ("pickaxe", "shovel", "trowel", "axe", "hoe"):
        if rng.random() < (.7 if t_ in JOB_TOOLS.get(job, ()) else .25):
            inv.append({"type": t_, "qty": 1, "quality": rng.randint(30, 95), "wear": rng.randint(0, 80)})
    have = {i_["type"] for i_ in inv}
    for it in rng.sample([x for x in ITEMS if x not in have], rng.randint(0, 3)):
        inv.append({"type": it, "qty": rng.randint(1, 5), "quality": rng.randint(30, 95), "wear": 0})
    me["inventory"] = inv
    tools_here = [i["type"] for i in inv if i["type"] in TOOLS]
    me["tool_in_hand"] = rng.choice(tools_here) if tools_here and rng.random() < .5 else "hands"
    me["wardrobe"] = gen_wardrobe(rng, me)
    return me


OUTFITS = ["everyday", "work", "festival", "cold", "night", "mourning"]   # outfit slots of the Skins thread (+ mourning)


def gen_wardrobe(rng, me):
    """Which outfits ME owns and wears (garments themselves live in personnages/data/villagers.json)."""
    has = ["everyday"]
    if me["job"] != "none":
        has.append("work")
    for o, p_ in (("festival", .75), ("cold", .8), ("night", .55), ("mourning", .35 if me["age_cat"] in ("adult", "elder") else .05)):
        if rng.random() < p_:
            has.append(o)
    doing = me["current_action"]
    if doing == "sleep" and "night" in has and rng.random() < .8:
        worn = "night"
    elif doing in JOB_ACTION.get(me["job"], []) and "work" in has and rng.random() < .7:
        worn = "work"
    elif me["season"] == "winter" and "cold" in has and rng.random() < .6:
        worn = "cold"
    else:
        worn = "everyday" if rng.random() < .85 else rng.choice(has)
    return {"has": has, "worn": worn, "wear": rng.randint(0, 90)}


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------
def entity_age(rng, link, my_age):
    if link == "child":
        a = my_age - rng.randint(18, 40)
        return a if a >= 0 else None
    if link == "parent":
        a = my_age + rng.randint(18, 40)
        return a if a <= 92 else None
    if link == "sibling":
        a = my_age + rng.randint(-10, 10)
    elif link in ("spouse", "partner"):
        a = my_age + rng.randint(-8, 8)
    elif link == "employer":
        a = max(25, my_age + rng.randint(-5, 20))
    elif link == "employee":
        a = max(16, my_age + rng.randint(-15, 5))
    elif my_age < 18:
        a = my_age + rng.randint(-3, 3)
    else:
        a = my_age + rng.randint(-12, 12)
    a = int(clamp(a, 3, 92))
    if link in ADULT_ONLY_LINKS and a < 18:
        return None
    return a


def link_weights(me, used):
    ac = me["age_cat"]
    w = {}
    if ac in ("child", "adolescent"):
        w = {"parent": 4, "sibling": 3, "friend": 3, "neighbor": 1, "stranger": 1, "rival": .5}
    else:
        if me["love_status"] == "married":
            w["spouse"] = 3
        if me["love_status"] in ("partnered", "courting"):
            w["partner"] = 3
        if me["age"] >= 25:
            w["child"] = 2 if ac == "adult" else 3
        if me["age"] <= 62:
            w["parent"] = 1.5
        w.update({"sibling": 1.5, "friend": 3, "neighbor": 2, "colleague": 2 if ac == "adult" else .5,
                  "employer": 1 if ac == "adult" else 0, "employee": 1 if ac == "adult" else 0,
                  "rival": 1, "enemy": .5, "stranger": 2})
    for u in used:
        if u in ("spouse", "partner"):
            w.pop(u, None)
    return {k: v for k, v in w.items() if v > 0}


def make_entity(rng, me, eid, link, world_seed, flip_ok=True):
    age = entity_age(rng, link, me["age"])
    if age is None:
        return None
    ac = age_cat(age)
    pri = LINK_PRIORS[link]
    g = rng.gauss
    rel = {k: g(*pri[k]) for k in ("affection", "trust", "respect", "fear", "grudge")}
    fam = clamp(g(*pri["fam"]), 0, 100)
    hidden = {"honesty": rng.gauss(0, 45), "aggression": rng.gauss(0, 45)}
    explain = []
    if flip_ok and rng.random() < .12:             # explained contradiction
        k = rng.choice(["affection", "trust", "respect"])
        rel[k] = -rel[k] if abs(rel[k]) > 20 else rel[k] + rng.choice([-50, 50])
        explain.append("flip_" + k)
    rel["fear"] = clamp(rel["fear"] + .2 * max(0, hidden["aggression"]), 0, 100)
    beauty = clamp(rng.gauss(55, 18), 5, 98)
    chem = pair_uniform(world_seed, me["uid"], eid)
    romance = 0.0
    if is_adult(me["age_cat"]) and is_adult(ac) and link not in KIN and link not in ("employer", "employee"):
        romance = 55 * chem + .3 * (beauty - 55) + .4 * rel["affection"] * (fam / 100) + g(0, 10)
        if link in ("partner",):
            romance = max(romance, 30) + g(20, 15)
    elif link == "spouse":
        romance = g(45, 25)
    debt = 0.0
    if rng.random() < .15:
        debt = rng.choice([-1, 1]) * rng.uniform(15, 70)
    dist = rng.uniform(1, 20)
    perceived = clamp(1 - dist / 30 + g(0, .1), .2, 1)
    love = {"spouse": "married", "partner": "partnered"}.get(link)
    if love is None:
        love = {"child": "single", "adolescent": "single"}.get(ac) or \
            choose_w(rng, [("single", 30), ("courting", 8), ("partnered", 12), ("married", 35), ("widowed", 8), ("separated", 4)])
        if ac in ("child", "adolescent"):
            love = "single"
    rep_trust = clamp(.5 * hidden["honesty"] + .5 * rel["trust"] + g(0, 15), -100, 100)
    rep_danger = clamp(.7 * hidden["aggression"] + .3 * rel["fear"] + g(0, 15), -100, 100)
    ent = {
        "id": eid, "uid": rng.randint(1, 10 ** 6), "link": link, "age": age, "age_cat": ac,
        "love_status": love, "is_player": False, "hidden": hidden,
        "rel": {"affection": ci(rel["affection"], -100, 100), "trust": ci(rel["trust"], -100, 100),
                "respect": ci(rel["respect"], -100, 100), "romance": ci(romance, -100, 100),
                "debt": ci(debt, -100, 100), "fear": ci(rel["fear"], 0, 100),
                "familiarity": ci(fam, 0, 100), "grudge": ci(rel["grudge"], 0, 100)},
        "mood_toward": ci(.6 * rel["affection"] - .3 * rel["grudge"] + g(0, 15), -100, 100),
        "urge_to_interact": ci(.5 * rel["affection"] + .3 * (me["drives"]["social_need"] - 50) + g(0, 20), -100, 100),
        "chemistry": round(chem, 3), "perceived": round(perceived, 2), "distance": round(dist, 1),
        "beauty": ci(beauty, 0, 100),
        "days_since_contact": int(rng.expovariate(1 / (.3 + (100 - fam) / 8))),
        "rep_trust": ci(rep_trust, -100, 100), "rep_danger": ci(rep_danger, -100, 100),
        "understanding": 4 if perceived > .7 else rng.choice([2, 3]),
        "visible_action": rng.choice(["none", "none", "till", "chat", "rest", "craft", "dig", "leisure", "go_to"]),
        "explain": explain,
        "suspicion": ci((rng.uniform(20, 70) if rel["trust"] < -30 else rng.uniform(0, 15)) + (20 if "flip_trust" in explain else 0), 0, 100),
        "worn": rng.choices(OUTFITS, weights=[10, 4, 1, 2, .3, .3])[0],
        "indirect_threat": 0, "threat_via": None,
    }
    if link in ("spouse", "partner", "child", "parent", "sibling") or ent["rel"]["familiarity"] > 60:
        ent["days_since_contact"] = min(ent["days_since_contact"], 3)
    return ent


def gen_entities(rng, fam, me, n, world_seed, force=None):
    ents, used, tries = [], [], 0
    force = list(force or [])
    while len(ents) < n and tries < 40:
        tries += 1
        link = force.pop(0) if force else choose_w(rng, list(link_weights(me, used).items()))
        e = make_entity(rng, me, f"E{len(ents) + 1}", link, world_seed)
        if e is None:
            continue
        used.append(link)
        ents.append(e)
    return ents


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------
def ent_by(ents, pred):
    c = [e for e in ents if pred(e)]
    return c


def norm_vec(ev, me, ents):
    """PLACEHOLDER appraisal table. The real table is built offline."""
    v = dict.fromkeys(NORMS, 0)
    t = ev["type"]
    tgt = next((e for e in ents if e["id"] == ev.get("target")), None)
    kin_tgt = tgt is not None and tgt["link"] in KIN
    inten = ev["intensity"]
    if t in ("theft",):
        v["property"], v["fairness"] = 60, 40
    elif t in ("shove", "strike", "threat"):
        v["life"] = {"shove": 15, "strike": 40, "threat": 30}[t]
        v["honor"] = 20 if ev.get("target") == "me" else 0
    elif t == "insult":
        v["honor"] = 50
    elif t in ("lie_revealed",):
        v["truth"], v["honor"] = 70, 30
    elif t == "promise_broken":
        v["truth"], v["honor"], v["fairness"] = 40, 30, 30
    elif t in ("flirt", "kiss", "embrace") and ev.get("romantic"):
        v["fidelity"] = 50 if t == "flirt" else 80
    elif t == "proposal" and ev["content"].get("kind") == "harm":
        act = ev["content"]["act"]
        v["life"] = {"kill": 90, "beat": 50, "lock_up": 40}.get(act, 20)
        v["property"] = 60 if act == "steal_from" else 0
        v["fairness"] = 50
    elif t == "proposal" and ev["content"].get("kind") == "accompany" and str(ev["content"].get("dest", "")).startswith("beyond"):
        v["life"] = 25                       # the marches: crossing is (believed) deadly
    if t == "interrogate" and ev["content"].get("pressure") != "polite":
        v["honor"], v["fairness"] = max(v["honor"], 30), max(v["fairness"], 40)
    agent_ent = next((e for e in ents if e["id"] == ev.get("agent")), None)
    if (ev.get("romantic") or ev["content"].get("kind") == "romance") and agent_ent is not None \
            and agent_ent["link"] in BLOOD:
        v["taboo"] = 90
    if kin_tgt and t not in ("gift", "help_given", "compliment"):
        v["kin"] = ci(60 + .3 * inten, 0, 100)
    if ev["content"].get("kind") == "harm":
        victim = next((e for e in ents if e["id"] == ev["content"].get("victim")), None)
        if victim is not None and victim["link"] in KIN:
            v["kin"] = 90
    return {k: ci(x, 0, 100) for k, x in v.items()}


def mk_event(rng, etype, agent, target, role="target", source="seen", content=None,
             intensity=None, oow=False, romantic=False):
    inten = intensity if intensity is not None else rng.randint(20, 90)
    return {"type": etype, "agent": agent, "target": target, "role": role, "source": source,
            "content": content or {}, "intensity": inten,
            "salience": ci(.7 * inten + (15 if role == "target" else 0) + rng.randint(-8, 8), 0, 100),
            "understanding": 4 if source == "seen" else 3,
            "reliability": 1.0 if source == "seen" else round(rng.uniform(.4, .9), 2),
            "delay": rng.randint(0, 90), "out_of_world": oow, "romantic": romantic}


def pick_agent(rng, ents, prefer_player=False, pred=None):
    c = [e for e in ents if (pred is None or pred(e))]
    if not c:
        return None
    pl = [e for e in c if e["is_player"]]
    return rng.choice(pl) if (prefer_player and pl) else rng.choice(c)


def make_proposal(rng, me, agent, ents, kind=None):
    kinds = ["leisure", "trade", "task", "accompany"]
    if is_adult(me["age_cat"]) and is_adult(agent["age_cat"]) and agent["link"] not in KIN:
        kinds += ["romance"]
    kind = kind or rng.choice(kinds)
    if kind == "leisure":
        return {"kind": "leisure", "activity": rng.choice(ACTIVITIES)}
    if kind == "trade":
        give, get = rng.sample(list(ITEMS), 2)
        return {"kind": "trade", "you_give": get, "you_get": give}
    if kind == "task":
        return {"kind": "task", "task": rng.choice(["harvest", "dig", "craft", "build_shed"]), "where": rng.choice(LOCS)}
    if kind == "accompany":
        return {"kind": "accompany", "dest": rng.choice(["forest", "mine", "road", "field"]), "for": rng.choice(["1h", "3h", "a day"])}
    return {"kind": "romance", "step": rng.choice(["walk_together", "kiss", "intimacy"])}


def gen_titles(rng, me, ents):
    """Titles are DATA: a name, who the NPC believes holds it, how sure, and the authority it attaches to it."""
    out = []
    for t_ in rng.sample(TITLES, rng.randint(0, 2)):
        adults = [e for e in ents if is_adult(e["age_cat"])]
        holder = rng.choice(adults)["id"] if adults and rng.random() < .65 else None
        h = next((e for e in ents if e["id"] == holder), None)
        legit = ci(.5 * h["rel"]["respect"] + .3 * h["rel"]["trust"] + rng.gauss(0, 15), -100, 100) if h else 0
        out.append({"title": t_, "holder": holder, "claimants": [], "conf": round(rng.uniform(.5, .95), 2) if holder else 0.0,
                    "legit": legit, "authority": ci(rng.gauss(55, 22), 0, 100), "my_role": "none"})
    return out


# --------------------------------------------------------------------------
# Village and household layer (0.4). Five villages (decision D8), one per frontier plus a central market town
# (proposal P8). Everything here is what ME believes or feels, not a global truth.
# --------------------------------------------------------------------------
VILLAGES = {   # id: (frontier side, economy, customs bias on the 8 norms)
    "sea_village":      ("west",   "fishing salt boats",     {"kin": 5, "life": 5, "fairness": 5}),
    "mountain_village": ("north",  "mining stone metal",     {"honor": 10, "property": 5}),
    "desert_village":   ("east",   "herding dyes glass",     {"kin": 15, "taboo": 10, "honor": 5}),
    "forest_village":   ("south",  "wood hunting charcoal",  {"life": -5, "fidelity": 5}),
    "market_town":      ("center", "grain crafts market",    {"property": 15, "fairness": 10, "truth": 5}),
}
VILLAGE_IDS = list(VILLAGES)
PROBLEMS = ["grain_shortage", "raid_threat", "flood", "sickness", "field_dispute", "well_dry", "bridge_broken", "wolf_attacks"]
PROBLEM_NEED = {"grain_shortage": "food", "raid_threat": "defense", "flood": "labor", "sickness": "care", "field_dispute": "judgment",
                "well_dry": "labor", "bridge_broken": "labor", "wolf_attacks": "defense"}
FRONTIERS = {"west": "beyond_the_sea", "north": "beyond_the_peaks", "east": "beyond_the_dunes", "south": "beyond_the_deep_forest"}


def gen_village(rng, me, ents, titles, fam):
    """What ME perceives of its village, its household and the four other villages."""
    home = choose_w(rng, [(v, 1.4 if v == "market_town" else 1) for v in VILLAGE_IDS])
    g = lambda: rng.gauss(0, 1)
    winter = me["season"] == "winter"
    food = ci(-.45 * me["stock_gap"]["food"] + 20 * g() - (15 if winter else 0), -100, 100)
    tension = ci(30 + 18 * g(), 0, 100)
    problem = {"kind": "none", "need": "none", "urgency": 0, "progress": 0}
    if fam == "village_problem" or rng.random() < .3:
        kind = rng.choice(PROBLEMS)
        if food < -30 and rng.random() < .5:
            kind = "grain_shortage"
        problem = {"kind": kind, "need": PROBLEM_NEED[kind], "urgency": ci(rng.uniform(30, 95), 0, 100),
                   "progress": ci(rng.uniform(0, 60), 0, 100)}
        tension = ci(tension + .3 * problem["urgency"], 0, 100)
    else:
        pass
    security = ci(30 + 25 * g() - (.6 * problem["urgency"] if problem["need"] == "defense" else 0), -100, 100)
    mayor = next((t_ for t_ in titles if t_["title"] in ("mayor", "elder") and t_["holder"]), None)
    leader_legit = ci(mayor["legit"] if mayor else 15 + 30 * g(), -100, 100)
    age_bonus = min(30, max(0, me["age"] - 15) * .6)
    belonging = ci(45 + age_bonus + 15 * g() - .1 * me["traits"]["tolerance"], 0, 100)
    loyalty = ci(.7 * (belonging - 45) + .2 * me["values"]["honor"] - 10 + 18 * g(), -100, 100)
    leader_trust = ci(.6 * leader_legit + 20 * g() - .2 * tension, -100, 100)
    customs = {}
    bias = VILLAGES[home][2]
    for k in NORMS:
        customs[k] = ci(55 + bias.get(k, 0) + 12 * g(), 0, 100)
    others = []
    for vid in VILLAGE_IDS:
        if vid == home:
            continue
        rel_ = 10 + 30 * g() + (.15 * me["traits"]["tolerance"])
        others.append({"id": vid, "relation": ci(rel_, -100, 100), "trade_dep": ci(rng.uniform(5, 80), 0, 100),
                       "threat": ci(max(0, -rel_) * .8 + rng.uniform(0, 25), 0, 100), "my_ties": ci(rng.expovariate(1 / 15), 0, 100)})
    village = {"id": home, "frontier": VILLAGES[home][0], "economy": ci(10 + 30 * g() + .3 * food, -100, 100),
               "food": food, "security": security, "rep": ci(10 + 30 * g(), -100, 100),
               "tension": tension, "cohesion": ci(65 - .5 * tension + 15 * g(), 0, 100),
               "belonging": belonging, "loyalty": loyalty, "leader_trust": leader_trust, "leader_legit": leader_legit,
               "institution_trust": ci(.5 * leader_trust + 20 * g(), -100, 100),
               "norms": customs, "problem": problem, "others": others}
    hh_kin = [e for e in ents if e["link"] in ("spouse", "partner", "child", "parent", "sibling")]
    head = is_adult(me["age_cat"]) and (me["love_status"] in ("married", "widowed") or me["age"] >= 35) and \
        not any(e["link"] == "parent" and e["age"] < 80 for e in hh_kin) and rng.random() < .8
    household = {"size": max(1, len(hh_kin) + 1 + rng.randint(0, 3)), "head": head,
                 "cohesion": ci(60 + 20 * g() - .2 * tension, 0, 100),
                 "wealth": ci(-.5 * (me["stock_gap"]["food"] + me["stock_gap"]["tools"]) / 2 + 25 * g(), -100, 100),
                 "honor": ci(15 + 30 * g(), -100, 100)}
    for e in ents:   # where each person lives, as ME believes it
        if e["link"] in KIN or e["link"] in ("partner",):
            e["village"] = home
        elif e["link"] == "stranger":
            e["village"] = rng.choice([o["id"] for o in others]) if rng.random() < .6 else home
        else:
            e["village"] = home if rng.random() < .88 else rng.choice([o["id"] for o in others])
    return village, household


def upsert_title(rng, titles, name, holder, conf, claimants=None):
    t_ = next((x for x in titles if x["title"] == name), None)
    if t_ is None:
        t_ = {"title": name, "holder": None, "claimants": [], "conf": 0.0, "legit": 0,
              "authority": ci(rng.gauss(55, 22), 0, 100), "my_role": "none"}
        titles.append(t_)
    t_["holder"], t_["conf"], t_["claimants"] = holder, round(conf, 2), list(claimants or [])
    t_["legit"] = 0 if holder is None else t_["legit"] or rng.randint(-30, 60)
    return t_


def build_events(rng, fam, me, ents, items, titles=None, village=None):
    titles = titles if titles is not None else []
    ev = []
    others = ents
    a = pick_agent(rng, others, prefer_player=fam in ("proposal", "harmful_proposal", "request", "out_of_world", "commitment"))
    if fam == "routine":
        if others and rng.random() < .3:
            ev.append(mk_event(rng, "greeting", rng.choice(others)["id"], "me", intensity=15))
    elif fam == "urgent_need":
        me["states"]["hunger"] = max(me["states"]["hunger"], rng.uniform(65, 95))
        me["states"]["thirst"] = max(me["states"]["thirst"], rng.uniform(40, 90)) if rng.random() < .5 else me["states"]["thirst"]
    elif fam == "greeting" and a:
        ev.append(mk_event(rng, rng.choice(["greeting", "chat_overture"]), a["id"], "me", intensity=20))
    elif fam == "proposal" and a:
        ev.append(mk_event(rng, "proposal", a["id"], "me", content=make_proposal(rng, me, a, ents), intensity=40))
    elif fam == "harmful_proposal" and a:
        victims = [e for e in ents if e is not a and e["age_cat"] != "child"]
        victims.sort(key=lambda e: e["link"] not in KIN)
        if victims:
            v = victims[0] if rng.random() < .7 else rng.choice(victims)
            ev.append(mk_event(rng, "proposal", a["id"], "me", intensity=55,
                               content={"kind": "harm", "act": rng.choice(["beat", "steal_from", "abandon", "kill", "lock_up", "insult"]),
                                        "victim": v["id"]}))
    elif fam == "request" and a:
        ev.append(mk_event(rng, "request", a["id"], "me", intensity=35,
                           content={"kind": rng.choice(["item", "loan", "help_task", "favor"]), "item": rng.choice(list(ITEMS))}))
    elif fam == "provocation" and a:
        t = rng.choice(["insult", "threat", "shove", "strike"])
        ev.append(mk_event(rng, t, a["id"], "me", intensity={"insult": rng.randint(30, 70), "threat": rng.randint(40, 85),
                                                            "shove": rng.randint(30, 60), "strike": rng.randint(55, 95)}[t]))
    elif fam == "wrongdoing_witnessed" and len(ents) >= 2:
        x, y = rng.sample(ents, 2)
        t = rng.choice(["theft", "strike", "insult", "shove"])
        ev.append(mk_event(rng, t, x["id"], y["id"], role="witness", intensity=rng.randint(30, 90),
                           content={"item": rng.choice(list(ITEMS))} if t == "theft" else {}))
    elif fam == "kindness" and a:
        ev.append(mk_event(rng, rng.choice(["gift", "help_given", "compliment"]), a["id"], "me", intensity=45,
                           content={"item": rng.choice(list(ITEMS))}))
    elif fam == "romance":
        pool = [e for e in ents if is_adult(e["age_cat"]) and e["link"] not in KIN]
        spouse = next((e for e in ents if e["link"] in ("spouse", "partner")), None)
        if spouse and len(pool) >= 2 and rng.random() < .4:
            other = rng.choice([e for e in pool if e is not spouse])
            ev.append(mk_event(rng, rng.choice(["flirt", "kiss"]), spouse["id"], other["id"], role="witness",
                               intensity=60, romantic=True))
        elif pool:
            ev.append(mk_event(rng, rng.choice(["flirt", "kiss", "embrace"]), rng.choice(pool)["id"], "me",
                               intensity=50, romantic=True))
    elif fam == "betrayal" and a:
        t = rng.choice(["lie_revealed", "promise_broken", "accusation"])
        ev.append(mk_event(rng, t, a["id"], "me", role="target", source=rng.choice(["seen", "told"]), intensity=rng.randint(40, 90),
                           content={"claim": rng.choice(["stole", "lied", "betrayed", "slandered"])}))
        a["explain"].append("betrayed")
    elif fam == "danger":
        t = rng.choice(["noise_danger", "fire", "wild_animal"])
        ev.append(mk_event(rng, t, None, None, role="witness", intensity=rng.randint(50, 95)))
        if ents and rng.random() < .5:
            ev.append(mk_event(rng, "injury", None, rng.choice(ents)["id"], role="witness", intensity=rng.randint(40, 90)))
    elif fam == "out_of_world":
        who = a["id"] if a else None
        ev.append(mk_event(rng, "utterance", who, "me", intensity=30, oow=True,
                           content={"unknown_concept": rng.choice(["car", "telephone", "police", "television", "airplane"])}))
    elif fam == "opportunity":
        it = rng.choice(list(ITEMS))
        items.append({"type": it, "qty": rng.randint(1, 4), "owner": "none"})
        ev.append(mk_event(rng, "found_item", None, None, role="witness", intensity=rng.randint(25, 55), content={"item": it}))
    elif fam == "rumor" and len(ents) >= 2:
        x, y = rng.sample(ents, 2)
        ev.append(mk_event(rng, "inform", x["id"], "me", source="told", intensity=30,
                           content={"about": y["id"], "claim": rng.choice(["stole", "lied", "is_ill", "loves_someone", "hit_someone"])}))
    elif fam == "kin_advance" and ents:
        k = ents[0]
        if rng.random() < .5:
            ev.append(mk_event(rng, "proposal", k["id"], "me", intensity=50,
                               content={"kind": "romance", "step": rng.choice(["walk_together", "kiss", "intimacy"])}))
        else:
            ev.append(mk_event(rng, rng.choice(["flirt", "kiss"]), k["id"], "me", intensity=50, romantic=True))
    elif fam == "notice_read" and ents:
        subj = rng.choice([e for e in ents if is_adult(e["age_cat"])] or ents)
        kind = rng.choice(["announce_title", "claim_title", "call_vote", "decree", "ad"])
        title = "mayor" if kind == "call_vote" else rng.choice(["lawyer", "mayor", "scribe", "tax_collector", "elder"])
        content = {"kind": kind, "title": title, "subject": subj["id"]}
        if kind == "decree":
            content["rule"] = rng.choice(["no_digging_near_wells", "night_curfew", "tax_on_grain"])
        if kind == "ad":
            svc = rng.choice(["legal_help", "healing", "tool_repair"])
            content = {"kind": "ad", "service": svc, "title": {"legal_help": "lawyer", "healing": "healer", "tool_repair": "smith"}[svc],
                       "subject": subj["id"]}
        ev.append(mk_event(rng, "notice_seen", subj["id"], None, role="witness", source="read", content=content,
                           intensity=rng.randint(25, 60)))
        if kind == "announce_title":
            upsert_title(rng, titles, title, subj["id"], .85)
        elif kind == "claim_title":
            upsert_title(rng, titles, title, None, 0.0, [subj["id"]])
    elif fam == "title_dispute" and len(ents) >= 2:
        for c_ in ents[:2]:
            ev.append(mk_event(rng, "claim_title", c_["id"], None, role="witness", intensity=55, content={"title": "mayor"}))
        upsert_title(rng, titles, "mayor", None, 0.0, [ents[0]["id"], ents[1]["id"]])
    elif fam == "election" and len(ents) >= 2:
        caller = rng.choice([e for e in ents if is_adult(e["age_cat"])] or ents)
        ev.append(mk_event(rng, "poll_open", caller["id"], None, role="witness", intensity=50,
                           content={"question": "who_is_mayor", "options": [ents[0]["id"], ents[1]["id"], "blank"],
                                    "closes_in": rng.choice(["1h", "1d"])}))
        upsert_title(rng, titles, "mayor", None, 0.0, [ents[0]["id"], ents[1]["id"]])
    elif fam == "extortion" and len(ents) >= 2:
        upsert_title(rng, titles, rng.choice(["mayor", "judge", "tax_collector"]), ents[0]["id"], .95)
        ev.append(mk_event(rng, "interrogate", ents[0]["id"], "me", intensity=rng.randint(50, 90),
                           content={"topic": "secret_about:" + ents[1]["id"], "pressure": rng.choice(["polite", "threat", "bribe"])}))
    elif fam == "legal_need" and len(ents) >= 2:
        ev.append(mk_event(rng, "accusation", ents[0]["id"], "me", intensity=rng.randint(45, 85),
                           content={"claim": rng.choice(["stole", "slandered", "damaged_field"])}))
        known = rng.random() < .5
        upsert_title(rng, titles, "lawyer", ents[1]["id"] if known else None, rng.uniform(.6, .95) if known else 0.0)
    elif fam == "info_request" and len(ents) >= 2:
        asker, subj = ents[0], ents[1]
        attr = rng.choice(["home_of", "where_is", "wealth_of", "job_of", "partner_of"])
        fam_s = subj["rel"]["familiarity"]
        know = "sure" if fam_s >= 70 else "likely" if fam_s >= 35 else "vague" if fam_s >= 12 else "none"
        sens = dp.SENS_BASE[attr] + (25 if subj["rel"]["affection"] > 40 else 0) - (20 if asker["rel"]["trust"] > 40 else 0) \
            + (15 if asker["rel"]["familiarity"] < 20 else 0)
        ev.append(mk_event(rng, "question", asker["id"], "me", intensity=30,
                           content={"attr": attr, "subject": subj["id"], "know": know, "sens": int(clamp(sens, 0, 100))}))
    elif fam == "village_problem" and ents and village and village["problem"]["kind"] != "none":
        pb = village["problem"]
        holders = [e for e in ents if is_adult(e["age_cat"]) and any(t_["holder"] == e["id"] for t_ in titles)]
        caller = holders[0] if holders else (pick_agent(rng, ents, pred=lambda e: is_adult(e["age_cat"])) or ents[0])
        ask = {"food": "levy", "defense": "volunteer", "labor": "volunteer", "care": "contribute", "judgment": "contribute"}[pb["need"]]
        content = {"kind": pb["kind"], "need": pb["need"], "ask": rng.choice([ask, ask, "contribute"])}
        if pb["need"] == "food":
            content["item"] = rng.choice(["bread", "apple", "meat", "seeds"])
        ev.append(mk_event(rng, "collective_request", caller["id"], None, role="witness", source=rng.choice(["heard", "seen", "read"]),
                           intensity=ci(pb["urgency"], 20, 100), content=content))
    elif fam == "apprenticeship" and ents:
        young = sorted([e for e in ents if e["age_cat"] != "child"], key=lambda e: e["age"]) or ents
        if me["job"] not in ("none", "apprentice") and me["body"]["job_skill"] >= 40:
            a2 = young[0] if rng.random() < .7 else rng.choice(young)
            e_ = mk_event(rng, "request", a2["id"], "me", intensity=rng.randint(30, 60),
                          content={"kind": "teach", "skill": me["job"], "pay": rng.choice(["none", "labor", "coins", "goods"])})
        else:
            olds = sorted([e for e in ents if is_adult(e["age_cat"])], key=lambda e: -e["age"]) or ents
            a2 = olds[0]
            e_ = mk_event(rng, "proposal", a2["id"], "me", intensity=rng.randint(30, 60),
                          content={"kind": "apprenticeship", "skill": choose_w(rng, JOBS_ADULT),
                                   "terms": rng.choice(["free", "labor_for_years", "coins"])})
        e_["holders"] = rng.choice([0, 0, 1, 1, 2, 3, 5, 8])          # OTHER holders of this skill ME knows of (0 = last holder)
        ev.append(e_)
    elif fam == "frontier" and ents and village:
        side = village["frontier"] if village["frontier"] != "center" else rng.choice(list(FRONTIERS))
        if rng.random() < .55 and a:
            ev.append(mk_event(rng, "proposal", a["id"], "me", intensity=rng.randint(35, 70),
                               content={"kind": "accompany", "dest": FRONTIERS[side], "for": rng.choice(["a day", "a week"]),
                                        "why": rng.choice(["treasure", "lost_person", "trade_route", "curiosity", "flee_debt"])}))
        else:
            teller = a or rng.choice(ents)
            ev.append(mk_event(rng, "legend", teller["id"], "me", source="told", intensity=rng.randint(20, 60),
                               content={"place": FRONTIERS[side], "claim": rng.choice(["treasure", "monsters", "lost_village",
                                                                                         "no_return", "other_people", "gods"])}))
    elif fam == "festival" and ents:
        kind = rng.choice(["wedding", "harvest_feast", "funeral", "market_day", "saint_day"])
        who = rng.choice(ents)
        content = {"kind": kind, "when": rng.choice(["now", "soon", "tonight"])}
        if kind in ("wedding", "funeral"):
            content["for"] = who["id"]
        ev.append(mk_event(rng, "celebration", who["id"] if kind == "wedding" else None, None, role="witness",
                           source=rng.choice(["heard", "seen"]), intensity=rng.randint(30, 70), content=content))
    elif fam in ("negotiation", "intervillage_trade") and ents:
        o = ents[0]
        if fam == "intervillage_trade" and village:
            o = next((e for e in ents if e.get("village") not in (None, village["id"])), ents[0])
        good = rng.choice(["bread", "meat", "firewood", "coal", "axe", "cloth", "stone", "apple"])
        qty = rng.randint(1, 5)
        npc = {"hunger": me["states"]["hunger"], "fuel_gap": me["stock_gap"]["fuel"], "tools_gap": me["stock_gap"]["tools"]}
        side = rng.choice(["buy", "sell"])                      # what the OTHER person wants to do with ME
        market = dp.PRICES[good] * qty
        price = round(market * rng.uniform(.5, 1.6), 1)
        mine = dp.worth(npc, good, qty)
        gain = (price - .7 * market) if side == "buy" else (mine - price)
        ev.append(mk_event(rng, "offer", o["id"], "me", intensity=40, content={
            "side": side, "good": good, "qty": qty, "price": price, "round": rng.randint(0, 4),
            "gain": int(clamp(100 * gain / max(1, market), -100, 100)),
            "fair": "cheap" if price < .85 * market else "expensive" if price > 1.15 * market else "fair"}))
        if village and o.get("village") not in (None, village["id"]):
            ev[-1]["content"]["from"] = o["village"]
    elif fam == "commitment" and a:
        ev.append(mk_event(rng, rng.choice(["request", "noise_danger", "greeting"]), a["id"], "me", intensity=40,
                           content={"kind": "help_task", "item": "axe"}))
    for e_ in ev:
        if e_["type"] in ("shove", "strike", "theft", "insult", "threat", "accusation", "lie_revealed", "promise_broken"):
            clumsy = rng.random() < .25
            e_["intent"] = sr.apparent_intent(e_["type"] if e_["type"] in sr.BASE_INTENT else "strike",
                                              repeated=int(rng.random() < .25), prior_threat=int(rng.random() < .2),
                                              actor_clumsy=int(clumsy), apologized=int(clumsy and rng.random() < .5))
    for e_ in ev:
        if e_["type"] in ("proposal", "request") and "style" not in e_["content"]:
            e_["content"]["style"] = rng.choices(["invite", "polite_request", "plain", "order"], weights=[3, 3, 2, 2])[0]
    if me["current_action"] == "sleep" and not ev:
        ev.append(mk_event(rng, "noise_danger", None, None, role="witness", intensity=rng.randint(40, 80)))
    for i, e in enumerate(ev, 1):
        e["id"] = f"V{i}"
        e["norm"] = norm_vec(e, me, ents)
    return ev


def apply_event_effects(rng, me, ents, events):
    s, t = me["states"], me["traits"]
    for e in events:
        if e["delay"] > 120:
            continue
        sev = e["intensity"] / 100
        ty = e["type"]
        tgt_me = e["target"] == "me"
        if ty in ("shove", "strike", "threat", "fire", "wild_animal", "noise_danger"):
            s["fear"] += 60 * sev * (1 - t["courage"] / 200)
            if tgt_me or ty in ("fire", "wild_animal", "noise_danger"):
                s["shock"] += 50 * sev
            if tgt_me and e["agent"]:
                s["anger"] += 40 * sev * (.5 + t["aggression"] / 200)
            if ty in ("strike", "shove") and tgt_me:
                me["body"]["hp"] = ci(me["body"]["hp"] - 25 * sev, 5, 100)
                s["pain"] = max(s["pain"], 20 + 50 * sev)
        elif ty == "insult" and tgt_me:
            s["anger"] += 50 * sev * (.5 + me["values"]["honor"] / 100)
            s["joy"] -= 25 * sev
        elif ty in ("lie_revealed", "promise_broken", "accusation", "theft") and (tgt_me or ty == "theft"):
            s["anger"] += 45 * sev * (1 if tgt_me else .4)
            s["joy"] -= 30 * sev * (1 if tgt_me else .3)
            s["stress"] += 20 * sev
        elif ty in ("gift", "help_given", "compliment"):
            s["joy"] += 30 * sev
        elif ty in ("flirt", "kiss", "embrace") and tgt_me:
            s["joy"] += 15
        elif ty in ("proposal", "request") and tgt_me and e["content"].get("style") == "order":
            s["anger"] += 20 * sev * (.5 + t["aggression"] / 200)          # being commanded irritates
        elif ty == "interrogate" and tgt_me:
            pr = e["content"].get("pressure")
            s["stress"] += 25 * sev
            if pr != "polite":
                s["anger"] += 30 * sev
            if pr == "threat":
                s["fear"] += 40 * sev * (1 - t["courage"] / 200)
        elif ty == "collective_request":
            s["stress"] += 20 * sev
        elif ty == "legend":
            s["joy"] += 5 if t["curiosity"] > 0 else -5
        elif ty == "injury":
            tg = next((x for x in ents if x["id"] == e["target"]), None)
            if tg and (tg["link"] in KIN or tg["rel"]["affection"] > 40):
                s["fear"] += 30
                s["stress"] += 30
                s["shock"] += 40 * sev
        if e["out_of_world"]:
            s["confusion"] += 60 * sev + 20
    for k in STATES_U:
        s[k] = clamp(s[k], 0, 100)
    for k in STATES_S:
        s[k] = clamp(s[k], -100, 100)
    if s["shock"] > 60:
        s["pain"] *= .5                      # numbness explains low pain with low hp
    me["body"]["hp"] = int(me["body"]["hp"])
    for k in STATES_U + STATES_S:
        s[k] = ci(s[k], -100 if k in STATES_S else 0, 100)


# --------------------------------------------------------------------------
# Memories and goals
# --------------------------------------------------------------------------
MEM_BROKE = {"theft": "property", "strike": "life", "threat": "life", "insult": "honor", "lie_revealed": "truth",
             "promise_broken": "truth", "accusation": "fairness", "kiss": "fidelity"}
MEM_OBJECT = {"theft", "gift", "help_given"}


def gen_memories(rng, me, ents, fam, events=()):
    """0.4: a memory has CONTENT (what, severity, broken norm, third party, outcome), so 'E2 stole my bread, E3 told me,
    nothing was ever repaid' is representable (point 4 of the devs' revision)."""
    mems = []

    def add(t, agent, target, val, imp, age, defining=False, why="", secret=False, payload=None):
        m_ = {"type": t, "agent": agent, "target": target, "valence": val, "importance": imp,
              "age_days": age, "certainty": round(rng.uniform(.7, 1), 2), "defining": defining,
              "source": "seen", "why": why, "secret": secret, "payload": payload or {},
              "what": rng.choice(list(ITEMS)) if t in MEM_OBJECT else "", "broke": "", "third": None, "outcome": "none",
              "severity": 0}
        if val <= -20:
            m_["broke"] = MEM_BROKE.get(t, "")
            m_["severity"] = ci(abs(val) + rng.gauss(0, 12), 5, 100)
            m_["outcome"] = choose_w(rng, [("unresolved", 5), ("repaid", 1), ("forgiven", 1.5), ("avenged", 1), ("punished", 1)])
        others_ = [e for e in ents if e["id"] not in (agent, target)]
        if others_ and why not in ("knowledge", "ties") and rng.random() < .25:     # learnt from someone else
            m_["source"], m_["third"] = "told", rng.choice(others_)["id"]
            m_["certainty"] = round(rng.uniform(.4, .85), 2)
        mems.append(m_)
    for e in ents:
        if e.get("threat_via"):                     # the engine derives indirect threat from beliefs about ties
            add("link_belief", e["id"], e["threat_via"], 20, 40, rng.randint(2, 40), False, "ties",
                payload={"affinity": rng.randint(50, 90), "rel": "ally"})
    for e in ents:
        r = e["rel"]
        if r["trust"] < -40 or "betrayed" in e["explain"]:
            add(rng.choice(["lie_revealed", "promise_broken"]), e["id"], "me", -60, 75, rng.randint(5, 200), True, "trust")
        if r["grudge"] > 50 or (r["affection"] < -50 and r["grudge"] > 35):
            add(rng.choice(["strike", "insult", "theft"]), e["id"], "me", -70, 80, rng.randint(5, 300), True, "grudge")
        if r["debt"] < -30:
            add("help_given", e["id"], "me", 55, 65, rng.randint(3, 90), False, "debt_owed")
        if r["fear"] > 50:
            add(rng.choice(["threat", "strike"]), e["id"], "me", -65, 70, rng.randint(3, 200), False, "fear")
        if r["affection"] > 60 and e["link"] not in KIN and rng.random() < .6:
            add(rng.choice(["gift", "help_given", "kiss" if e["rel"]["romance"] > 40 else "chat"]), e["id"], "me", 60, 55, rng.randint(2, 120))
    for ev in events:                               # what ME knows about the subject of a question
        if ev["type"] == "question":
            fam_ = next((x["rel"]["familiarity"] for x in ents if x["id"] == ev["content"]["subject"]), 0)
            if ev["content"]["know"] in ("sure", "likely"):
                kind = {"home_of": "seen_at", "where_is": "seen_at", "wealth_of": "saw_money", "job_of": "saw_work",
                        "partner_of": "seen_at"}[ev["content"]["attr"]]
                add(kind, ev["content"]["subject"], None, 0, 35, rng.randint(1, 20), False, "knowledge",
                    payload={"night": ev["content"]["attr"] == "home_of"})
    if fam == "extortion" and len(ents) >= 2:
        add("theft", ents[1]["id"], "someone", -40, 70, rng.randint(2, 60), False, "secret", True)
    for _ in range(rng.randint(0, 2)):
        if ents:
            e = rng.choice(ents)
            k_ = rng.choice(["chat", "greeting", "help_given", "insult"])
            val_ = {"insult": rng.randint(-40, -5), "help_given": rng.randint(20, 60)}.get(k_, rng.randint(-5, 30))
            add(k_, e["id"], "me", val_, rng.randint(10, 40), rng.randint(1, 60))
    mems = mems[:9]
    for i, m in enumerate(mems, 1):
        m["id"] = f"M{i}"
    focus = next((ev["agent"] for ev in events if ev.get("agent") and ev["agent"] != "me"), None)
    for m in mems:                                  # does the person ME is dealing with know what ME remembers?
        if focus is None:
            m["focus_knows"] = None
        elif focus in (m["agent"], m["target"]):
            m["focus_knows"] = "yes"
        else:
            m["focus_knows"] = rng.choices(["no", "unknown", "yes"], weights=[55, 30, 15])[0]
    return mems


def gen_goals(rng, me, ents, events, fam):
    goals = []
    s = me["states"]
    if s["hunger"] > 60:
        goals.append({"type": "need", "target": "food", "priority": ci(s["hunger"], 0, 100), "progress": 0.0, "deadline_h": 1})
    if s["fatigue"] > 70:
        goals.append({"type": "need", "target": "sleep", "priority": ci(s["fatigue"], 0, 100), "progress": 0.0, "deadline_h": 3})
    for e in ents:
        if e["rel"]["grudge"] > 60 and rng.random() < .4:
            goals.append({"type": "vengeance", "target": e["id"], "priority": ci(e["rel"]["grudge"], 0, 100), "progress": 0.0, "deadline_h": 72})
    if me["job"] != "none" and rng.random() < .5:
        goals.append({"type": "project", "target": rng.choice(["harvest_field", "stock_firewood", "repair_tools"]),
                      "priority": rng.randint(25, 65), "progress": round(rng.random(), 2), "deadline_h": rng.randint(8, 120)})
    if fam == "commitment":
        pl = next((e for e in ents if e["is_player"]), ents[0] if ents else None)
        if pl:
            goals.append({"type": "accompany", "target": pl["id"], "priority": rng.randint(50, 85),
                          "progress": round(rng.random() * .6, 2), "deadline_h": rng.randint(1, 6)})
    for e in ents:                        # a common goal can force cooperation with someone ME dislikes
        if e["rel"]["affection"] < -30 and rng.random() < .3:
            goals.append({"type": "shared_task", "target": rng.choice(["harvest_field", "defend_village", "build_shed"]),
                          "priority": rng.randint(45, 80), "progress": 0.0, "deadline_h": rng.randint(6, 48), "partner": e["id"]})
            break
    if fam == "legal_need":
        goals.append({"type": "seek_help", "target": "lawyer", "priority": rng.randint(55, 85), "progress": 0.0, "deadline_h": 24})
    return sorted(goals, key=lambda g_: -g_["priority"])[:4]


# --------------------------------------------------------------------------
# Candidates (what the teacher scores and what the model chooses among)
# --------------------------------------------------------------------------
def can_romance(me, e):
    """Hard rule: both adults. Blood relatives allowed only if the design flag is on
    (then the decision belongs to the model, driven by the taboo norm and value)."""
    if not is_adult(me["age_cat"]) or not is_adult(e["age_cat"]):
        return False
    return e["link"] not in BLOOD or ALLOW_ADULT_KIN_ROMANCE


SOCIETY_EXT = {"teach", "contribute", "supply"}   # extension functions the village layer needs even without --ext


def build_candidates(rng, me, ents, events, items, include_ext=False, mems=(), titles=(), goals=(), village=None):
    C, seen = [], set()

    def add(act, /, **args):
        key = (act, tuple(sorted(args.items())))
        if key in seen:
            return
        if not include_ext and act not in SOCIETY_EXT and not next(x for x in ACTIONS if x["id"] == act)["core"]:
            return
        seen.add(key)
        C.append({"a": act, "args": args})

    eids = {e["id"]: e for e in ents}
    s = me["states"]
    add("continue" if me["current_action"] != "idle" else "wait")
    own = [i_["type"] for i_ in me.get("inventory", [])] + [it["type"] for it in items if it["owner"] in ("me", "none")]
    if s["hunger"] >= 50:
        foods = [x for x in dict.fromkeys(own) if ITEMS.get(x) == "food"]
        for x in foods[:2]:
            add("eat", i=x)
        if not foods:
            add("go_to", l="home"); add("search", i="food")
    if s["thirst"] >= 50:
        if "water_jug" in own:
            add("drink", i="water_jug")
        else:
            add("fetch_water", l="well")
        add("go_to", l="well")
    if s["fatigue"] >= 60:
        add("sleep", l="home"); add("rest")
    wd = me.get("wardrobe")
    if wd:                                       # an outfit fitting the moment, when ME owns it and is not wearing it
        occ = []
        if 5 <= me["hour"] < 9 and me["job"] != "none":
            occ.append("work")
        if me["weather"] in ("snow", "wind", "storm") or me["season"] == "winter":
            occ.append("cold")
        if me["hour"] >= 21 or me["hour"] < 5:
            occ.append("night")
        if wd["worn"] != "everyday" and rng.random() < .5:
            occ.append("everyday")
        for ev in events:
            if ev["type"] == "celebration":
                occ.append("mourning" if ev["content"]["kind"] == "funeral" else "festival")
        for o in dict.fromkeys(occ):
            if o in wd["has"] and o != wd["worn"]:
                add("dress", outfit=o)
    crisis = False
    for ev in events:
        t, ag, tg = ev["type"], ev["agent"], ev["target"]
        agent = eids.get(ag)
        if t == "proposal":
            add("accept", p=ev["id"]); add("refuse", p=ev["id"]); add("ask", e=ag, f="details")
            if ev["content"].get("kind") == "harm":
                crisis = True
                add("attack", e=ag, m="shove"); add("expel", e=ag, l="home"); add("threaten", e=ag, f="consequence")
                add("call_for_help"); add("avoid", e=ag)
                vic = ev["content"].get("victim")
                if vic:
                    add("warn", e=vic, f=f"{ag}:plans_harm")
            else:
                add("propose", e=ag, p=f"counter:{ev['id']}"); add("chat", e=ag)
                if ev["content"].get("kind") == "romance" and agent and agent["link"] in BLOOD:
                    add("expel", e=ag, l="home"); add("insult", e=ag); add("avoid", e=ag)
                if ev["content"].get("kind") == "accompany":
                    add("accompany", e=ag)
                    if str(ev["content"].get("dest", "")).startswith("beyond"):
                        add("warn", e=ag, f="danger"); add("inform", e=next((x for x in eids if x != ag), ag), f=f"{ag}:goes_beyond")
        elif t == "request" and ev["content"].get("kind") == "teach":
            add("teach", e=ag, skill=ev["content"]["skill"]); add("accept", p=ev["id"]); add("refuse", p=ev["id"])
            add("ask", e=ag, f="why"); add("negotiate", e=ag, move="raise"); add("propose", e=ag, p=f"counter:{ev['id']}")
        elif t == "request":
            add("accept", p=ev["id"]); add("refuse", p=ev["id"]); add("ask", e=ag, f="why"); add("assist", e=ag, task="their_task")
        elif t in ("greeting", "chat_overture"):
            add("greet", e=ag); add("chat", e=ag); add("avoid", e=ag); add("approach", e=ag)
        elif t in ("insult", "threat", "shove", "strike") and tg == "me":
            crisis = t != "insult" or crisis
            add("insult", e=ag); add("attack", e=ag, m="shove"); add("threaten", e=ag, f="retaliation")
            add("avoid", e=ag); add("call_for_help"); add("ask", e=ag, f="why"); add("apologize", e=ag)
            if t in ("threat", "strike"):
                add("flee", e=ag); add("defend", e="self")
        elif t in ("theft", "strike", "shove", "insult") and tg != "me":
            add("accuse", e=ag, f=f"{t}"); add("chase", e=ag); add("call_for_help"); add("assist", e=tg, task="help_victim")
            add("inform", e=tg if tg in eids else ag, f=f"{ag}:{t}")
        elif t in ("gift", "help_given", "compliment"):
            add("thank", e=ag); add("compliment", e=ag); add("give", e=ag, i=ev["content"].get("item", "bread")); add("embrace", e=ag)
        elif t in ("flirt", "kiss", "embrace"):
            if tg == "me" and agent and can_romance(me, agent):
                add("flirt", e=ag); add("kiss", e=ag); add("avoid", e=ag); add("chat", e=ag); add("refuse", p=ev["id"])
                if me["place_type"] == "home" and agent["rel"]["romance"] > 20:
                    add("be_intimate", e=ag)
                if agent["link"] in BLOOD:
                    add("expel", e=ag, l="home"); add("insult", e=ag)
            elif tg != "me":
                add("accuse", e=ag, f="infidelity"); add("ask", e=ag, f="explanation"); add("avoid", e=ag); add("observe", e=tg)
                add("insult", e=tg)
        elif t in ("lie_revealed", "promise_broken", "accusation"):
            add("accuse", e=ag, f=ev["content"].get("claim", "lied")); add("ask", e=ag, f="why"); add("forgive", e=ag)
            add("avoid", e=ag); add("insult", e=ag); add("attack", e=ag, m="strike")
            third = next((x for x in eids if x != ag), None)
            if third:
                add("inform", e=third, f=f"{ag}:{ev['content'].get('claim', 'lied')}")
        elif t in ("noise_danger", "fire", "wild_animal"):
            crisis = True
            add("flee", l="home"); add("investigate" if include_ext else "observe", l="source"); add("call_for_help"); add("warn", e=next(iter(eids), "all"), f="danger")
            add("defend", e="self"); add("assist", e=next(iter(eids), "all"), task="evacuate")
        elif t == "injury":
            add("assist", e=tg, task="aid"); add("comfort", e=tg); add("call_for_help"); add("heal" if include_ext else "observe", e=tg)
        elif t == "question":
            subj, know = ev["content"]["subject"], ev["content"]["know"]
            modes = ["vague", "lie", "refuse", "unknown"] + (["truth"] if know != "none" else [])
            for m_ in modes:
                add("answer", e=ag, q=ev["id"], m=m_)
            helper = next((x["id"] for x in ents if x["id"] not in (ag, subj) and x["rel"]["familiarity"] >= 50), None)
            if helper:
                add("answer", e=ag, q=ev["id"], m="redirect")
            add("ask", e=ag, topic="why_do_you_ask"); add("negotiate", e=ag, move="hold"); add("avoid", e=ag)
            if subj in eids:
                add("warn", e=subj, f=f"{ag}_asks_about_you")
        elif t == "offer":
            add("accept", p=ev["id"]); add("refuse", p=ev["id"]); add("ask", e=ag, topic="why_that_price"); add("avoid", e=ag)
            for mv in ("concede_small", "hold", "raise", "sweeten", "walk"):
                add("negotiate", e=ag, move=mv)
        elif t == "notice_seen":
            kind, subj, title = ev["content"].get("kind"), ev["content"].get("subject"), ev["content"].get("title")
            if kind == "announce_title":
                add("ask", e=subj, topic=title); add("go_to", e=subj); add("compliment", e=subj)
                add("contest_claim", e=subj, title=title); add("tear_down_notice", doc=ev["id"])
                add("post_notice", content=f"counter:{title}")
            elif kind == "claim_title":
                add("endorse", e=subj, title=title); add("contest_claim", e=subj, title=title)
                add("claim_title", title=title); add("ask", e=subj, topic=title); add("tear_down_notice", doc=ev["id"])
            elif kind == "call_vote":
                add("vote", poll=ev["id"], option=subj); add("vote", poll=ev["id"], option="blank")
                add("campaign", e=subj); add("tear_down_notice", doc=ev["id"])
            elif kind == "decree":
                add("tear_down_notice", doc=ev["id"]); add("accuse", e=subj, f="abuse_of_power")
                add("ask", e=subj, topic="decree"); add("inform", e=next(iter(eids), subj), f="decree")
            else:
                add("go_to", e=subj); add("ask", e=subj, topic=ev["content"].get("service", "service"))
        elif t == "claim_title":
            title = ev["content"]["title"]
            add("endorse", e=ag, title=title); add("contest_claim", e=ag, title=title); add("claim_title", title=title)
            add("ask", e=ag, topic="why"); add("insult", e=ag); add("avoid", e=ag)
        elif t == "poll_open":
            for o_ in ev["content"]["options"]:
                add("vote", poll=ev["id"], option=o_)
            for o_ in ev["content"]["options"][:2]:
                add("campaign", e=o_)
            add("tear_down_notice", doc=ev["id"])
        elif t == "interrogate":
            top = ev["content"]["topic"].split(":")[-1]
            sec = next((m_ for m_ in mems if m_.get("secret")), None)
            if sec:
                add("inform", e=ag, mem=sec["id"])
            add("refuse", p=ev["id"]); add("deceive", e=ag, f="denial"); add("ask", e=ag, topic="why")
            add("bribe", e=ag, offer="goods"); add("negotiate", e=ag, move="concede_small"); add("call_for_help")
            add("flee", e=ag); add("attack", e=ag, m="shove"); add("warn", e=top, f="boss_asks")
            crisis = crisis or ev["content"].get("pressure") == "threat"
        elif t == "utterance":
            add("ask", e=ag, f="what_do_you_mean"); add("observe", e=ag); add("avoid", e=ag); add("chat", e=ag)
        elif t == "collective_request":
            c_ = ev["content"]
            add("contribute", site=ev["id"]); add("refuse", p=ev["id"]); add("ask", e=ag, topic=c_["kind"])
            add("accuse", e=ag, f="mismanagement"); add("go_to", l="home")
            gift = {"food": ("bread", "apple", "meat", "seeds"), "defense": ("axe", "knife", "pickaxe"), "labor": ("shovel", "pickaxe", "stone"),
                    "care": ("cloth", "bread", "water_jug"), "judgment": ()}[c_["need"]]
            mine_ = [x for x in own if x in gift]
            if mine_:
                add("supply", site=ev["id"], i=mine_[0])
                if c_["need"] == "food":
                    add("store", i=mine_[0], l="home")                                   # hoarding
            other_ = next((x for x in eids if x != ag), None)
            if other_:
                add("inform", e=other_, f=f"problem:{c_['kind']}")
            if rng.random() < .5:
                add("post_notice", content=f"plan:{c_['kind']}")
            if rng.random() < .3 and is_adult(me["age_cat"]):
                add("claim_title", title="mayor")
        elif t == "legend":
            add("ask", e=ag, f="proof"); add("chat", e=ag); add("observe", e=ag)
            add("propose", e=ag, p=f"expedition:{ev['content']['place']}")
            other_ = next((x for x in eids if x != ag), None)
            if other_:
                add("inform", e=other_, f=f"legend:{ev['content']['claim']}")
        elif t == "celebration":
            k_ = ev["content"]["kind"]
            add("go_to", l="square"); add("leisure", a="dancing" if k_ != "funeral" else "storytelling")
            for_ = ev["content"].get("for")
            if for_ in eids:
                add("comfort" if k_ == "funeral" else "compliment", e=for_)
                if k_ == "wedding":
                    add("give", e=for_, i=next((x for x in own if ITEMS.get(x) in ("food", "material")), "bread"))
        elif t == "found_item":
            it = ev["content"]["item"]
            add("pick_up", i=it); add("claim", i=it); add("inform", e=next(iter(eids), "all"), f=f"found:{it}")
        elif t == "inform":
            add("ask", e=ag, f="proof"); add("chat", e=ag); add("inform", e=ev["content"]["about"], f=f"{ag}:said_{ev['content']['claim']}")
            if rng.random() < .3:
                add("deceive", e=ev["content"]["about"], f="denial")
    for g_ in goals:
        if g_["type"] == "seek_help":
            lw = next((x for x in titles if x["title"] == "lawyer"), None)
            if lw and lw["holder"] and lw["conf"] >= .5:
                add("go_to", e=lw["holder"]); add("ask", e=lw["holder"], topic="my_case")
            else:
                other = next((e["id"] for e in ents[1:]), next(iter(eids), None))
                add("ask", e=other, topic="who_is_lawyer"); add("post_notice", content="seeking:lawyer")
            add("negotiate", e=ents[0]["id"] if ents else None, move="concede_small")
    if crisis:
        add("flee", l="home")
        add("call_for_help")
        aggressor = next((ev["agent"] for ev in events if ev["agent"] in eids and ev["target"] == "me"
                          and ev["type"] in ("threat", "shove", "strike", "proposal")), None)
        if me["age_cat"] != "child" and aggressor:
            add("attack", e=aggressor, m="shove")
    # filler: plausible neutral options
    pool = [("rest", {}), ("wander", {}), ("go_to", {"l": "square"}), ("go_to", {"l": "home"}), ("leisure", {"a": rng.choice(ACTIVITIES)})]
    if me["job"] in JOB_ACTION:
        ja = JOB_ACTION[me["job"]][0]
        jargs = {"till": {"l": "field"}, "harvest": {"kind": "vegetable"}, "dig": {"dir": "forward", "length": 10, "tool": "pickaxe"},
                 "cut": {"target": "tree", "tool": "axe"}, "fetch_water": {"l": "well"}, "plant": {"seed": "seeds"},
                 "place": {"block": "stone", "tool": "trowel"}, "craft": {"recipe": "tool_repair"}}.get(ja, {})
        if ja != "chat":
            pool.append((ja, jargs))
    for e in ents[:3]:
        pool += [("chat", {"e": e["id"]}), ("greet", {"e": e["id"]}), ("observe", {"e": e["id"]})]
        if e["rel"]["affection"] > 40:
            pool.append(("embrace", {"e": e["id"]}))
        if can_romance(me, e) and e["link"] not in BLOOD and e["rel"]["romance"] >= 30:
            pool += [("flirt", {"e": e["id"]}), ("kiss", {"e": e["id"]})]
            if me["place_type"] == "home" and me["drives"]["libido"] >= 50 and e["rel"]["romance"] >= 40:
                pool.append(("be_intimate", {"e": e["id"]}))
    rng.shuffle(pool)
    for a_, args in pool[:rng.randint(3, 5)]:
        add(a_, **args)
    # hard safety masks
    out = []
    for c in C:
        a_, args = c["a"], c["args"]
        e = eids.get(args.get("e"))
        if a_ in ("flirt", "kiss", "be_intimate") and not (e and can_romance(me, e)):
            continue
        if a_ == "attack" and args.get("m") == "lethal" and me["age_cat"] == "child":
            continue
        if a_ == "steal":
            continue
        out.append(c)
    rng.shuffle(out)
    out = out[:16]
    # keep 'continue' in
    if not any(c["a"] in ("continue", "wait") for c in out):
        out[-1] = {"a": "continue", "args": {}}
    for i, c in enumerate(out):
        c["i"] = i
    return out


# --------------------------------------------------------------------------
# Compact, binned, sparse view for the teacher LLM
# --------------------------------------------------------------------------
def bs(v):
    return "--" if v <= -60 else "-" if v <= -25 else "" if v < 25 else "+" if v < 60 else "++"


def bu(v):
    return "" if v < 25 else "some" if v < 55 else "high" if v < 80 else "max"


def tod(h):
    return "night" if h < 5 or h >= 22 else "morning" if h < 11 else "midday" if h < 14 else "afternoon" if h < 18 else "evening"


def sparse(d, f):
    return {k: f(v) for k, v in d.items() if f(v)}


def _i(value, kind, vmax=None):
    return rp.to10(value, kind, vmax)


def _nz(d, kind):
    """Integers on the teacher/model scale, zeros omitted."""
    out = {}
    for k, x in d.items():
        q = _i(x, kind)
        if q:
            out[k] = q
    return out


def view_of_state(st, cands):
    """0.4 view: the teacher reads the SAME integers as the model (-10..+10 bipolar, 0..10 unipolar, zeros omitted),
    produced by representation.to10. Replaces the 5-level symbols of 0.3 (point 1 of the devs' revision)."""
    me, ents, events, mems, goals = st["me"], st["entities"], st["events"], st["memories"], st["goals"]
    items, titles, vil, hh = st.get("items", []), st.get("titles", []), st.get("village"), st.get("household")
    m = {"age": me["age_cat"], "love": me["love_status"], "job": me["job"], "doing": me["current_action"],
         "place": me["place_type"], "time": tod(me["hour"]), "season": me["season"], "weather": me["weather"],
         "traits": _nz(me["traits"], "B100"), "values": _nz(me["values"], "U100"), "drives": _nz(me["drives"], "U100")}
    stt = _nz({k: me["states"][k] for k in STATES_U}, "U100")
    stt.update(_nz({k: me["states"][k] for k in STATES_S}, "B100"))
    m["state"] = stt
    m["stock_gap"] = _nz(me["stock_gap"], "B100")
    b = me["body"]
    m["body"] = {k: x for k, x in (("hp", _i(b["hp"], "U100")), ("strength", _i(b["strength"], "U100")),
                                   ("skill", _i(b["job_skill"], "U100")), ("load", _i(b["load_ratio"], "U1"))) if x}
    m["activity"] = {k: x for k, x in (("progress", _i(me["activity"]["progress"], "U1")),
                                       ("commitment", _i(me["activity"]["commitment"], "U100"))) if x}
    if me.get("tool_in_hand", "hands") != "hands":
        m["tool"] = me["tool_in_hand"]
    if me.get("wardrobe"):
        m["wearing"] = {"worn": me["wardrobe"]["worn"], "wear": _i(me["wardrobe"]["wear"], "U100"), "owns": me["wardrobe"]["has"]}
    v = {"me": m}
    home = vil["id"] if vil else None
    if vil:
        v["village"] = {"id": vil["id"], "side": vil["frontier"],
                        "me": {k: _i(vil[k], "U100" if k == "belonging" else "B100") for k in
                               ("belonging", "loyalty", "leader_trust", "leader_legit", "institution_trust")},
                        "all": {k: _i(vil[k], "U100" if k in ("tension", "cohesion") else "B100") for k in
                                ("economy", "food", "security", "rep", "tension", "cohesion")},
                        "customs": {k: _i(x, "U100") for k, x in vil["norms"].items()},
                        "others": [{"id": o["id"], "rel": _i(o["relation"], "B100"), "dep": _i(o["trade_dep"], "U100"),
                                    "threat": _i(o["threat"], "U100"), "ties": _i(o["my_ties"], "U100")} for o in vil["others"]]}
        pb = vil["problem"]
        if pb["kind"] != "none":
            v["village"]["problem"] = {"kind": pb["kind"], "need": pb["need"], "urgency": _i(pb["urgency"], "U100"),
                                       "progress": _i(pb["progress"], "U100")}
    if hh:
        v["household"] = {"size": hh["size"], "head": bool(hh["head"]), "cohesion": _i(hh["cohesion"], "U100"),
                          "wealth": _i(hh["wealth"], "B100"), "honor": _i(hh["honor"], "B100")}
    v["others"] = {}
    for e in ents:
        r = e["rel"]
        rel = _nz({k: r[k] for k in REL_S}, "B100")
        rel.update(_nz({k: r[k] for k in ("fear", "grudge")}, "U100"))
        soc = {k: x for k, x in (("mood", _i(e["mood_toward"], "B100")), ("urge", _i(e["urge_to_interact"], "B100")),
                                 ("suspicion", _i(e.get("suspicion", 0), "U100")),
                                 ("ties_threat", _i(e.get("indirect_threat", 0), "U100"))) if x}
        o = {"is": LINK_LABEL[e["link"]], "age": e["age_cat"], "dist": int(round(e["distance"])),
             "knows": _i(r["familiarity"], "U100"), "rel": rel, "soc": soc, "beauty": _i(e["beauty"], "U100"),
             "last_seen": e["days_since_contact"]}
        if e.get("village") and e["village"] != home:
            o["from"] = e["village"]
        if e["perceived"] < .65:
            o["seen"] = "unclear"
        rp_ = _nz({"trust": e["rep_trust"], "danger": e["rep_danger"]}, "B100")
        if rp_:
            o["rep"] = rp_
        if e["visible_action"] != "none":
            o["doing"] = e["visible_action"]
        if e.get("worn", "everyday") != "everyday":
            o["wears"] = e["worn"]
        v["others"][e["id"]] = o
    v["events"] = []
    for ev in events:
        d = {"id": ev["id"], "type": ev["type"], "from": ev["agent"] or "-", "to": ev["target"] or "-",
             "int": _i(ev["intensity"], "U100")}
        if ev["role"] != "target":
            d["role"] = ev["role"]
        if ev["source"] != "seen":
            d["src"] = ev["source"]
        if ev["reliability"] < .95:
            d["reliable"] = _i(ev["reliability"], "U1")
        if ev["content"]:
            d["what"] = dict(ev["content"])
            if ev["type"] == "question":
                d["what"]["sens"] = _i(ev["content"]["sens"], "U100")
            if ev["type"] == "offer":
                d["what"]["gain"] = _i(ev["content"]["gain"], "B100")
        if "holders" in ev:
            d["holders"] = ev["holders"]
        if "intent" in ev:
            d["intent"] = _i(ev["intent"], "U1")
        if ev["out_of_world"]:
            d["note"] = "concept does not exist in this world"
        v["events"].append(d)
    v["mem"] = []
    for x in mems:
        d = {"id": x["id"], "type": x["type"], "who": x["agent"], "to": x["target"], "val": _i(x["valence"], "B100"),
             "imp": _i(x["importance"], "U100"), "ago_d": x["age_days"], "sure": _i(x["certainty"], "U1"),
             "secret": bool(x.get("secret")), "focus": {"yes": "yes", "no": "no", "unknown": "?"}.get(x.get("focus_knows"))}
        for k in ("what", "broke"):
            if x.get(k):
                d[k] = x[k]
        if x.get("severity"):
            d["sev"] = _i(x["severity"], "U100")
        if x.get("outcome", "none") != "none":
            d["outcome"] = x["outcome"]
        if x.get("third"):
            d["told_by"] = x["third"]
        if x.get("defining"):
            d["defining"] = True
        v["mem"].append(d)
    v["inv"] = [{"type": i_["type"], "qty": i_["qty"], "worn": i_["wear"] >= 60 and i_["type"] in TOOLS} for i_ in me.get("inventory", [])]
    v["titles"] = []
    for t_ in titles:
        d_ = {"title": t_["title"], "authority": _i(t_["authority"], "U100")}
        if t_["claimants"]:
            d_["claimants"] = t_["claimants"]
        if t_["holder"]:
            d_["holder"] = t_["holder"]
            d_["sure"] = _i(t_["conf"], "U1")
            d_["legit"] = _i(t_["legit"], "B100")
        v["titles"].append(d_)
    v["goals"] = [dict({"type": g_["type"], "target": g_["target"], "prio": _i(g_["priority"], "U100"), "due_h": g_["deadline_h"]},
                       **({"with": g_["partner"]} if g_.get("partner") else {})) for g_ in goals]
    if items:
        v["items"] = [{"type": i["type"], "owner": i["owner"]} for i in items]
    v["opts"] = [[c["i"], c["a"]] + [str(x) for x in c["args"].values()] for c in cands]
    return v


def view_of(me, ents, events, mems, goals, cands, items, titles=()):
    """Compatibility wrapper (0.3 signature)."""
    return view_of_state({"me": me, "entities": ents, "events": events, "memories": mems, "goals": goals, "items": items,
                          "titles": titles}, cands)


def view_text(v):
    """Line-based DSL of the view, with integers (0.4). Much cheaper in tokens than JSON."""
    def kv(d):
        return " ".join(f"{k}={x}" for k, x in d.items())
    m = v["me"]
    L = [f"ME {m['age']} {m['love']} {m['job']}; doing {m['doing']}@{m['place']}; {m['time']} {m['season']} {m['weather']}"]
    for key in ("traits", "values", "drives", "state", "stock_gap", "body", "activity"):
        if m.get(key):
            L.append(f" {key}: {kv(m[key])}")
    if m.get("tool"):
        L.append(f" in hand: {m['tool']}")
    if m.get("wearing"):
        w_ = m["wearing"]
        L.append(f" wearing: {w_['worn']} outfit (wear={w_['wear']}); owns: {' '.join(w_['owns'])}")
    vl = v.get("village")
    if vl:
        L.append(f"HOME {vl['id']} ({vl['side']}) | me: {kv(vl['me'])} | village: {kv(vl['all'])}")
        L.append(f" customs: {kv(vl['customs'])}")
        if vl.get("problem"):
            p_ = vl["problem"]
            L.append(f" PROBLEM {p_['kind']} need={p_['need']} urgency={p_['urgency']} progress={p_['progress']}")
        L.append(" OTHER VILLAGES " + "; ".join(f"{o['id']} rel={o['rel']} dep={o['dep']} threat={o['threat']} ties={o['ties']}"
                                                for o in vl["others"]))
    hh = v.get("household")
    if hh:
        L.append(f"HOUSEHOLD size={hh['size']}" + (" head" if hh["head"] else "") +
                 f" cohesion={hh['cohesion']} wealth={hh['wealth']} honor={hh['honor']}")
    if v.get("inv"):
        L.append("INV " + ", ".join(f"{i_['type']}" + (f" x{i_['qty']}" if i_["qty"] > 1 else "") + ("(worn)" if i_["worn"] else "") for i_ in v["inv"]))
    for t_ in v.get("titles", []):
        bits = [f"TITLE {t_['title']}"]
        if t_.get("holder"):
            bits.append(f"holder={t_['holder']} sure={t_['sure']} legit={t_['legit']}")
        if t_.get("claimants"):
            bits.append("claimants=" + ",".join(t_["claimants"]))
        bits.append(f"auth={t_['authority']}")
        L.append(" ".join(bits))
    for eid, o in v["others"].items():
        bits = [f"{eid} {o['is']} {o['age']} dist={o['dist']}m knows={o['knows']}"]
        for k in ("from", "seen", "doing", "wears"):
            if o.get(k):
                bits.append(f"{k}={o[k]}")
        bits.append(f"beauty={o['beauty']} last_seen={o['last_seen']}d")
        line = " ".join(bits) + " | " + (kv(o["rel"]) if o["rel"] else "-")
        if o.get("soc"):
            line += " | " + kv(o["soc"])
        if o.get("rep"):
            line += " | rep " + kv(o["rep"])
        L.append(line)
    for ev in v["events"]:
        extra = ""
        if ev.get("what"):
            extra += " " + json.dumps(ev["what"], separators=(",", ":"), ensure_ascii=False)
        for k in ("role", "src", "reliable", "intent", "holders", "note"):
            if ev.get(k) is not None and ev.get(k) != "":
                extra += f" {k}={ev[k]}"
        L.append(f"EVENT {ev['id']} {ev['type']} {ev['from']}->{ev['to']} int={ev['int']}{extra}")
    for x in v["mem"]:
        bits = [f"MEM {x['id']} {x['type']} {x['who']}->{x['to'] or '-'} val={x['val']} imp={x['imp']} {x['ago_d']}d sure={x['sure']}"]
        for k, lab in (("what", "what"), ("sev", "sev"), ("broke", "broke"), ("outcome", "outcome"), ("told_by", "told_by")):
            if x.get(k):
                bits.append(f"{lab}={x[k]}")
        if x.get("defining"):
            bits.append("DEFINING")
        if x.get("secret"):
            bits.append("SECRET")
        if x.get("focus"):
            bits.append(f"focus:{x['focus']}")
        L.append(" ".join(bits))
    for g_ in v["goals"]:
        L.append(f"GOAL {g_['type']} {g_['target']} prio={g_['prio']} due={g_['due_h']}h" + (f" with={g_['with']}" if g_.get("with") else ""))
    if v.get("items"):
        L.append("ITEMS " + ", ".join(f"{i['type']}({i['owner']})" for i in v["items"]))
    L.append("OPTS " + " | ".join(" ".join(str(y) for y in o) for o in v["opts"]))
    return "\n".join(L)


# --------------------------------------------------------------------------
# Assembly, validation
# --------------------------------------------------------------------------
FAMILIES = {"routine": 3, "urgent_need": 2, "greeting": 2, "proposal": 4, "harmful_proposal": 3,
            "request": 2, "provocation": 3, "wrongdoing_witnessed": 3, "kindness": 2, "romance": 3,
            "betrayal": 3, "danger": 2, "out_of_world": 1, "opportunity": 2, "rumor": 2, "commitment": 2,
            "kin_advance": 0.8, "info_request": 2.5, "negotiation": 2.5, "notice_read": 2, "title_dispute": 2, "election": 2, "extortion": 2, "legal_need": 1.5,
            "village_problem": 3, "apprenticeship": 2, "intervillage_trade": 1.5, "frontier": 1.2, "festival": 1.5}
NEEDS_ENTS = {"greeting": 1, "proposal": 1, "harmful_proposal": 2, "request": 1, "provocation": 1,
              "wrongdoing_witnessed": 2, "kindness": 1, "romance": 2, "betrayal": 1, "rumor": 2, "commitment": 1,
              "out_of_world": 1, "kin_advance": 1, "info_request": 2, "negotiation": 1, "notice_read": 1, "title_dispute": 2, "election": 2,
              "extortion": 2, "legal_need": 2, "village_problem": 1, "apprenticeship": 1, "intervillage_trade": 1, "frontier": 1, "festival": 1}


def gen_situation(rng, idx, fam, world_seed, max_ent, max_ev, include_ext):
    me = gen_self(rng, fam, world_seed)
    n_min = NEEDS_ENTS.get(fam, 0)
    n = max(n_min, rng.randint(max(1, n_min), max_ent)) if max_ent >= n_min else n_min
    force = []
    if fam == "harmful_proposal":
        force = ["stranger" if not is_adult(me["age_cat"]) else "friend", rng.choice(["spouse", "sibling", "parent", "friend"])]
    if fam == "romance" and me["love_status"] in ("married", "partnered"):
        force = [("spouse" if me["love_status"] == "married" else "partner")]
    if fam in ("commitment", "intervillage_trade"):
        force = ["stranger"]
    if fam == "kin_advance":
        force = [rng.choice(["sibling", "sibling", "parent", "child"])]
    ents = gen_entities(rng, fam, me, n, world_seed, force)
    foes = [e for e in ents if e["rel"]["affection"] < -30]
    for e in ents:                       # a threat that comes only from ties to someone ME dislikes
        if foes and e not in foes and e["link"] not in KIN and rng.random() < .25:
            e["indirect_threat"], e["threat_via"] = rng.randint(25, 80), rng.choice(foes)["id"]
    need_adults = {"notice_read": 1, "title_dispute": 2, "election": 2, "extortion": 2, "legal_need": 2}
    if fam in need_adults:
        ents.sort(key=lambda e: not is_adult(e["age_cat"]))
        for i_, e_ in enumerate(ents, 1):
            e_["id"] = f"E{i_}"
        if sum(is_adult(e_["age_cat"]) for e_ in ents[:need_adults[fam]]) < need_adults[fam]:
            fam = "routine"
    if fam == "kin_advance" and not (ents and is_adult(ents[0]["age_cat"]) and ents[0]["link"] in BLOOD):
        fam = "routine"          # no adult blood relative could be built for this self
    if fam in ("proposal", "harmful_proposal", "request", "out_of_world", "commitment", "romance", "extortion", "notice_read", "legal_need") and ents and rng.random() < .6:
        pl = ents[0] if fam != "romance" else next((e for e in ents if is_adult(e["age_cat"]) and e["link"] not in KIN), None)
        if pl is not None:
            pl["is_player"] = True
    items = []
    for _ in range(rng.randint(0, 2)):
        items.append({"type": rng.choice(list(ITEMS)), "qty": rng.randint(1, 3),
                      "owner": rng.choice(["me", "none"] + [e["id"] for e in ents])})
    titles = gen_titles(rng, me, ents)
    village, household = gen_village(rng, me, ents, titles, fam)
    if fam == "intervillage_trade" and ents[0]["link"] == "stranger":
        ents[0]["village"] = rng.choice([o["id"] for o in village["others"]])
    events = build_events(rng, fam, me, ents, items, titles, village)[:max_ev]
    apply_event_effects(rng, me, ents, events)
    mems = gen_memories(rng, me, ents, fam, events)
    goals = gen_goals(rng, me, ents, events, fam)
    cands = build_candidates(rng, me, ents, events, items, include_ext, mems, titles, goals, village)
    rec = {"id": f"s{idx:06d}", "schema": VERSION, "family": fam,
           "state": {"me": me, "entities": ents, "events": events, "memories": mems, "goals": goals, "items": items, "titles": titles,
                     "village": village, "household": household},
           "cands": cands}
    rec["view"] = view_of_state(rec["state"], cands)
    rec["text"] = view_text(rec["view"])
    return rec


KEYMAP = {"q": "query", "e": "entity", "i": "item", "l": "place", "p": "proposal", "f": "fact", "m": "mode",
          "a": "activity", "r": "place", "k": "skill", "mem": "memory"}


def candidate_to_plan(c):
    """What the decision engine would hand to the action engine for this candidate (one step, default conditions)."""
    args = {KEYMAP.get(k, k): v for k, v in c["args"].items() if v is not None}
    return {"steps": [{"f": c["a"], "a": args}], "on_done": "report"}


def validate(rec):
    bad = []
    st = rec["state"]
    me, ents, evs, mems = st["me"], st["entities"], st["events"], st["memories"]
    ids = {e["id"] for e in ents}
    if age_cat(me["age"]) != me["age_cat"]:
        bad.append("age_cat")
    if me["age_cat"] in ("child", "adolescent") and me["love_status"] != "single" and me["age_cat"] == "child":
        bad.append("child_love_status")
    for e in ents:
        if age_cat(e["age"]) != e["age_cat"]:
            bad.append("ent_age_cat")
        if e["link"] == "child" and me["age"] - e["age"] < 16:
            bad.append("kin_age_child")
        if e["link"] == "parent" and e["age"] - me["age"] < 16:
            bad.append("kin_age_parent")
        if (not is_adult(me["age_cat"]) or not is_adult(e["age_cat"])) and e["link"] != "spouse" and e["rel"]["romance"] != 0:
            bad.append("romance_with_minor")
        if e["link"] in BLOOD and e["rel"]["romance"] != 0:
            bad.append("romance_with_kin")
        r = e["rel"]
        if (r["trust"] < -40 or r["grudge"] > 50 or r["fear"] > 50) and not any(m["agent"] == e["id"] for m in mems):
            bad.append("unexplained_relation")
        for k, lo, hi in [("affection", -100, 100), ("trust", -100, 100), ("fear", 0, 100), ("grudge", 0, 100), ("familiarity", 0, 100)]:
            if not lo <= r[k] <= hi:
                bad.append("range_rel")
    s = me["states"]
    if me["body"]["hp"] < 60 and s["pain"] < 25 and s["shock"] < 59:
        bad.append("hp_pain_incoherent")
    for k in STATES_U:
        if not 0 <= s[k] <= 100:
            bad.append("range_state")
    for k in STATES_S:
        if not -100 <= s[k] <= 100:
            bad.append("range_state")
    if me["current_action"] == "sleep" and not evs:
        bad.append("sleep_without_wakeup")
    for ev in evs:
        for k in ("agent", "target"):
            if ev[k] not in (None, "me") and ev[k] not in ids:
                bad.append("event_ref")
        if ev.get("romantic") or ev["content"].get("kind") == "romance":
            people = [x for x in ents if x["id"] in (ev["agent"], ev["target"])]
            if any(not is_adult(x["age_cat"]) for x in people) or \
                    (ev["target"] == "me" and not is_adult(me["age_cat"])) or \
                    (ev["agent"] == "me" and not is_adult(me["age_cat"])):
                bad.append("romantic_event_minor")
            if not ALLOW_ADULT_KIN_ROMANCE and any(x["link"] in BLOOD for x in people):
                bad.append("romantic_event_kin_disabled")
    cs = rec["cands"]
    if [c["i"] for c in cs] != list(range(len(cs))):
        bad.append("cand_index")
    if not any(c["a"] in ("continue", "wait") for c in cs):
        bad.append("no_continue")
    evids = {e["id"] for e in evs}
    for c in cs:
        a, args = c["a"], c["args"]
        if a not in ACTION_IDS:
            bad.append("unknown_action")
        if a in ("accept", "refuse") and args.get("p") not in evids:
            bad.append("proposal_ref")
        e = next((x for x in ents if x["id"] == args.get("e")), None)
        if a in ("flirt", "kiss", "be_intimate"):
            if e is None or not is_adult(me["age_cat"]) or not is_adult(e["age_cat"]) \
                    or (e["link"] in BLOOD and not ALLOW_ADULT_KIN_ROMANCE):
                bad.append("forbidden_romantic_action")
        if a == "attack" and args.get("m") == "lethal" and me["age_cat"] == "child":
            bad.append("child_lethal")
    mem_ids = {m_["id"] for m_ in mems}
    for c in cs:
        errs = validate_plan(candidate_to_plan(c))
        if errs:
            bad.append("cand_contract:" + errs[0].split(":", 2)[-1][:40])
        if "mem" in c["args"] and c["args"]["mem"] not in mem_ids:
            bad.append("cand_memory_ref")
        for key in ("poll", "doc"):
            if key in c["args"] and c["args"][key] not in evids:
                bad.append("cand_event_ref")
        if c["args"].get("option") not in (None, "blank") and c["args"]["option"] not in ids:
            bad.append("cand_option_ref")
    for e in ents:
        if e.get("threat_via") and not any(m_["type"] == "link_belief" and m_["agent"] == e["id"] for m_ in mems):
            bad.append("threat_without_link_memory")
        if e.get("suspicion", 0) > 40 and e["rel"]["trust"] > 20 and "flip_trust" not in e["explain"]:
            bad.append("unexplained_suspicion")
    for ev in evs:
        if "intent" in ev and not 0 <= ev["intent"] <= 1:
            bad.append("intent_range")
        if ev["type"] == "question" and ev["content"]["know"] in ("sure", "likely") and not any(m_["why"] == "knowledge" for m_ in mems):
            bad.append("know_without_memory")
    for c in cs:
        if c["a"] == "answer":
            ev_ = next((x for x in evs if x["id"] == c["args"].get("q")), None)
            if ev_ is None:
                bad.append("answer_ref")
            elif c["args"].get("m") == "truth" and ev_["content"]["know"] == "none":
                bad.append("truth_without_knowledge")
    for t_ in st.get("titles", []):
        if t_["holder"] is not None and t_["holder"] not in ids:
            bad.append("title_holder_ref")
        if any(x not in ids for x in t_["claimants"]):
            bad.append("title_claimant_ref")
    vil, hh = st.get("village"), st.get("household")
    if vil is not None:                                         # 0.4 village layer
        if vil["id"] not in VILLAGES or len(vil["others"]) != len(VILLAGES) - 1 or vil["id"] in {o["id"] for o in vil["others"]}:
            bad.append("village_ids")
        for k in ("belonging", "tension", "cohesion"):
            if not 0 <= vil[k] <= 100:
                bad.append("village_range")
        for k in ("loyalty", "leader_trust", "leader_legit", "institution_trust", "economy", "food", "security", "rep"):
            if not -100 <= vil[k] <= 100:
                bad.append("village_range")
        if vil["problem"]["kind"] != "none" and vil["problem"]["kind"] not in PROBLEMS:
            bad.append("village_problem_kind")
        for e in ents:
            if e.get("village") not in VILLAGES:
                bad.append("entity_village")
            elif e["link"] in KIN and e["village"] != vil["id"]:
                bad.append("kin_in_other_village")
        if rec["family"] == "village_problem" and not any(ev["type"] == "collective_request" for ev in evs):
            bad.append("village_problem_without_request")
    if hh is not None and (hh["size"] < 1 or not 0 <= hh["cohesion"] <= 100):
        bad.append("household_range")
    for m_ in mems:
        if m_.get("third") is not None and m_["third"] not in ids:
            bad.append("memory_third_ref")
        if m_.get("third") is not None and m_["third"] in (m_["agent"], m_["target"]):
            bad.append("memory_third_is_party")
        if m_.get("valence", 0) >= 0 and m_.get("broke"):
            bad.append("memory_broke_on_positive")
    for c in cs:
        if c["a"] == "teach":
            ev_ = next((x for x in evs if x["type"] == "request" and x["content"].get("kind") == "teach"), None)
            if ev_ is None or me["job"] in ("none", "apprentice") or c["args"].get("skill") != me["job"]:
                bad.append("teach_without_skill")
        if c["a"] == "dress":
            wd = me.get("wardrobe") or {}
            if c["args"].get("outfit") not in wd.get("has", []) or c["args"].get("outfit") == wd.get("worn"):
                bad.append("dress_outfit_not_owned_or_worn")
        if c["a"] in ("contribute", "supply") and c["args"].get("site") not in evids:
            bad.append("cand_site_ref")
    blob = json.dumps(rec["view"]) + rec["text"]
    for banned in ("is_player", "chemistry", "uid", "hidden", "norm"):
        if banned in blob:
            bad.append("view_leak:" + banned)
    return bad


WORK_TASKS = {"miner": ["tunnel_for_ore", "shaft_down"], "farmer": ["till_field", "harvest_veg", "plant_field", "fetch_water"],
              "woodcutter": ["cut_trees"], "carpenter": ["build_wall", "build_floor"], "smith": ["build_wall"],
              "apprentice": ["build_floor", "tunnel_for_ore"]}


def gen_work_program(rng, idx, world_seed):
    """Scripted expert: chooses tool, length and safety conditions from the NPC's traits.
    Teaches the model the *form* of work plans for free; the LLM teacher is kept for social/political choices."""
    for _ in range(50):
        me = gen_self(rng, "routine", world_seed)
        if me["job"] in WORK_TASKS and me["age_cat"] in ("adult", "adolescent"):
            break
    task = rng.choice(WORK_TASKS[me["job"]])
    inv = {i["type"]: i for i in me["inventory"]}
    tools = [t_ for t_ in inv if t_ in TOOLS]
    tr, st_ = me["traits"], me["states"]
    skill, fatigue, hunger = me["body"]["job_skill"], st_["fatigue"], st_["hunger"]
    steps, why = [], []
    need = {"tunnel_for_ore": ["pickaxe", "shovel"], "shaft_down": ["shovel", "pickaxe"], "till_field": ["hoe"],
            "cut_trees": ["axe"], "build_wall": ["trowel", "shovel"], "build_floor": ["trowel", "shovel"]}.get(task)
    tool = None
    if need:
        avail = [t_ for t_ in need if t_ in tools]
        if not avail:                                   # the expert fetches or reports: nothing to teach here
            return None
        tool = avail[0]
        if task in ("tunnel_for_ore", "shaft_down") and "shovel" in avail and "pickaxe" in avail:
            clean = skill >= 55 and tr["impulsivity"] < 0 and fatigue < 40
            tool = "shovel" if (clean or task == "shaft_down" and tr["impulsivity"] < 20) else "pickaxe"
            why.append("clean" if tool == "shovel" else "fast")
        if task.startswith("build") and "trowel" in avail and tr["impulsivity"] > 50 and fatigue > 30 and "shovel" in avail:
            tool = "shovel"
            why.append("rough")
    interrupt = ["tool_broken"]
    if tr["courage"] < 20:
        interrupt.append("sees(danger)")
    if me["body"]["hp"] < 70 or fatigue > 40:
        interrupt.append("hp_below(35)")
    if hunger >= 60 and len(interrupt) < 3:
        interrupt.append(f"hunger_above({min(95, int(hunger) + 20)})")
    until = []
    length = ci(6 + skill / 10 + (4 if tr["curiosity"] > 0 else 0) - (4 if fatigue > 40 else 0) + rng.randint(-2, 4), 3, 30)
    site = rng.choice(["mine", "forest", "field", "square", "workshop"])
    if task == "tunnel_for_ore":
        if tr["curiosity"] > -20:
            until = ["found(ore)"]
        steps = [{"f": "dig", "a": {"dir": "forward", "length": length, "tool": tool}, "until": until, "interrupt_if": interrupt[:3]}]
        site = "mine"
    elif task == "shaft_down":
        steps = [{"f": "dig", "a": {"dir": "down", "length": ci(length / 2, 2, 15), "tool": tool}, "interrupt_if": interrupt[:3]}]
        site = "mine"
    elif task == "till_field":
        steps = [{"f": "till", "a": {"place": "field", "tool": "hoe"}, "interrupt_if": interrupt[:3]}]
        site = "field"
    elif task == "plant_field":
        steps = [{"f": "plant", "a": {"seed": "seeds", "place": "field"}, "interrupt_if": interrupt[:3]}]
        site = "field"
    elif task == "harvest_veg":
        steps = [{"f": "harvest", "a": {"kind": "vegetable", "place": "field"}, "until": ["inventory_full"], "interrupt_if": interrupt[:3]}]
        site = "field"
    elif task == "fetch_water":
        steps = [{"f": "fetch_water", "a": {"place": "well"}}]
        site = "well"
    elif task == "cut_trees":
        steps = [{"f": "cut", "a": {"target": "tree", "tool": "axe"}, "until": ["inventory_full"], "interrupt_if": interrupt[:3]}]
        site = "forest"
    else:
        steps = [{"f": "place", "a": {"block": "stone", "pattern": "wall" if task == "build_wall" else "floor", "tool": tool},
                  "interrupt_if": interrupt[:3]}]
        site = "workshop"
    prog = [{"f": "go_to", "a": {"place": site}}]
    if tool and me["tool_in_hand"] != tool:
        prog.append({"f": "equip", "a": {"tool": tool}})
    plan = {"steps": prog + steps, "on_done": "report"}
    errs = validate_plan(plan)
    _, perr = resolve_preconditions(plan, list(inv), me["tool_in_hand"])
    state = {"job": me["job"], "age_cat": me["age_cat"], "traits": me["traits"], "job_skill": skill,
             "fatigue": ci(fatigue, -100, 100), "hunger": ci(hunger, 0, 100), "hp": me["body"]["hp"],
             "tool_in_hand": me["tool_in_hand"], "inventory": me["inventory"], "task": task}
    return {"id": f"w{idx:06d}", "kind": "work_program", "task": task, "why": why, "state": state, "program": plan,
            "contract_errors": errs, "precondition_error": perr}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="")
    ap.add_argument("--max-entities", type=int, default=4)
    ap.add_argument("--max-events", type=int, default=2)
    ap.add_argument("--families", default="", help="comma list name=weight")
    ap.add_argument("--ext", action="store_true", help="include extension actions")
    ap.add_argument("--no-adult-kin-romance", action="store_true",
                    help="design switch: forbid romantic actions between adult blood relatives (default: the model decides)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dump-actions-md", action="store_true")
    ap.add_argument("--work-programs", type=int, default=0, help="generate N scripted work programs instead of situations")
    ap.add_argument("--dump-schema", default="")
    a = ap.parse_args()
    if a.dump_actions_md:
        cats = []
        for x in ACTIONS:
            if x["cat"] not in cats:
                cats.append(x["cat"])
        print("| Category | Action (args) | Level |\n|---|---|---|")
        for c in cats:
            acts = [x for x in ACTIONS if x["cat"] == c]
            fmt = lambda x: f"`{x['id']}({x['args'].replace('|', '/')})`" if x["args"] else f"`{x['id']}`"
            txt = ", ".join(fmt(x) for x in acts if x["core"])
            ext = ", ".join(fmt(x) for x in acts if not x["core"])
            if txt:
                print(f"| {c} | {txt} | core |")
            if ext:
                print(f"| {c} | {ext} | extension |")
        return
    if a.dump_schema:
        json.dump({"schema": SCHEMA, "actions": ACTIONS}, open(a.dump_schema, "w"), indent=1)
        return
    global ALLOW_ADULT_KIN_ROMANCE
    ALLOW_ADULT_KIN_ROMANCE = not a.no_adult_kin_romance
    if a.work_programs:
        rng = random.Random(a.seed)
        out = open(a.out, "w", encoding="utf-8") if a.out else None
        tools, errs, n_ok = Counter(), Counter(), 0
        i = 0
        while n_ok < a.work_programs and i < a.work_programs * 20:
            r = gen_work_program(rng, n_ok, a.seed * 7919)
            i += 1
            if r is None:
                continue
            n_ok += 1
            tools[(r["task"], next((s_["a"].get("tool") for s_ in r["program"]["steps"] if "tool" in s_["a"]), None))] += 1
            for e in r["contract_errors"]:
                errs[e] += 1
            if r["precondition_error"]:
                errs["pre:" + r["precondition_error"]] += 1
            if out:
                out.write(json.dumps(r, separators=(",", ":")) + "\n")
        print(f"work programs: {n_ok}; contract/precondition errors: {dict(errs) if errs else 'none'}", file=sys.stderr)
        print("task/tool mix:", dict(sorted(tools.items(), key=lambda kv: str(kv[0]))), file=sys.stderr)
        sys.exit(1 if errs else 0)
    fams = dict(FAMILIES)
    if not ALLOW_ADULT_KIN_ROMANCE:
        fams.pop("kin_advance", None)
    if a.families:
        fams = {k: float(v) for k, v in (p.split("=") for p in a.families.split(","))}
    rng = random.Random(a.seed)
    world_seed = a.seed * 7919
    names, ws = zip(*fams.items())
    out = open(a.out, "w", encoding="utf-8") if a.out else None
    viol, fam_count, lens, ncands = Counter(), Counter(), [], []
    for i in range(a.n):
        fam = rng.choices(names, weights=ws)[0]
        rec = gen_situation(rng, i, fam, world_seed, a.max_entities, a.max_events, a.ext)
        fam_count[fam] += 1
        if a.check:
            for b in validate(rec):
                viol[b] += 1
        lens.append(len(rec["text"]))
        ncands.append(len(rec["cands"]))
        if out:
            out.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n")
    if out:
        out.close()
    print(f"generated {a.n} situations, {len(ACTION_IDS)} actions in vocabulary", file=sys.stderr)
    print("families:", dict(fam_count), file=sys.stderr)
    print(f"teacher text size: mean {sum(lens) / len(lens):.0f} chars, max {max(lens)}; candidates mean {sum(ncands) / len(ncands):.1f}", file=sys.stderr)
    if a.check:
        print("violations:", dict(viol) if viol else "none", file=sys.stderr)
        sys.exit(1 if viol else 0)


if __name__ == "__main__":
    main()
