#!/usr/bin/env python3
"""reference_decider.py - the rule-based REFERENCE decider (utility AI), schema 0.4.

Reads a canonical situation (state + candidates, as written by generate_states.py) and gives every candidate
  * a utility (float), the sum of named DRIVER contributions (need, fear, anger, kin, trust, desire, debt, norm,
    habit, curiosity: the same closed list the teacher uses in its "codes" variant),
  * a score 0..4 on the teacher's scale, and a soft target (softmax of the utilities).

Role in the project (architecture 8.2): fast CPU decider for players without a dedicated GPU, comparison baseline,
and FREE labels to pre-train the student before the teacher's labels exist. The student must beat it, so these labels
are a bootstrap, never the final target. It reads only what the model can see (no hidden traits, no is_player, no uid).

It never decides the candidates: the generator (or the engine) proposes them; this module only scores them.

  python3 reference_decider.py                 # self-test
  python3 reference_decider.py --in states.jsonl --show 3
"""
import argparse
import json
import math
import sys

DRIVERS = ("need", "fear", "anger", "kin", "trust", "desire", "debt", "norm", "habit", "curiosity")
VERSION = "ref-0.4"
KIN = {"child", "parent", "sibling", "spouse"}
BLOOD = {"child", "parent", "sibling"}
ROMANTIC = {"flirt", "kiss", "be_intimate"}
TEMP = 0.35            # softmax temperature of the soft target (utility units)
STEP = 0.45            # utility gap worth one point on the 0..4 scale
ABSURD = -0.9          # below this utility the score is 0 whatever the others


def adult(cat):
    return cat in ("adult", "elder")


class Ctx:
    """Normalised view of a situation (all values -1..1 or 0..1)."""

    def __init__(self, rec):
        st = rec["state"]
        self.st, self.cands = st, rec["cands"]
        me = st["me"]
        self.me = me
        self.t = {k: v / 100 for k, v in me["traits"].items()}
        for k in ("tolerance", "ambition"):           # 0.3 records have no such traits
            self.t.setdefault(k, 0.0)
        self.v = {k: v / 100 for k, v in me["values"].items()}
        self.d = {k: v / 100 for k, v in me["drives"].items()}
        self.s = {k: v / 100 for k, v in me["states"].items()}
        self.gap = {k: v / 100 for k, v in me["stock_gap"].items()}
        self.hp = me["body"]["hp"] / 100
        self.strength = me["body"]["strength"] / 100
        self.commit = me["activity"]["commitment"] / 100
        self.progress = me["activity"]["progress"]
        self.hour = me["hour"]
        self.night = self.hour < 5 or self.hour >= 22
        self.adult = adult(me["age_cat"])
        self.ents = {e["id"]: e for e in st["entities"]}
        self.events = {e["id"]: e for e in st["events"]}
        self.mems = {m["id"]: m for m in st["memories"]}
        self.vil = st.get("village")
        self.hh = st.get("household")
        self.titles = st.get("titles", [])
        self.goals = st.get("goals", [])
        self.inv = {i["type"]: i for i in me.get("inventory", [])}
        self.attached = me["love_status"] in ("married", "partnered", "courting")
        # how loud is the situation: the strongest event that concerns ME
        self.urgency = max([ev["salience"] / 100 * (1.0 if ev["target"] == "me" else .7) for ev in st["events"]] + [0])
        self.crisis = any(ev["type"] in ("fire", "wild_animal", "noise_danger", "strike", "threat") or
                          (ev["content"] or {}).get("kind") == "harm" or
                          (ev["type"] == "interrogate" and (ev["content"] or {}).get("pressure") == "threat")
                          for ev in st["events"])
        self.need_peak = max(self.s["hunger"], self.s["thirst"], self.s["pain"], max(0, self.s["fatigue"]))

    # ---------------------------------------------------------------- relations
    def rel(self, eid):
        e = self.ents.get(eid)
        if e is None:
            return None
        r = e["rel"]
        return {"aff": r["affection"] / 100, "trust": r["trust"] / 100, "respect": r["respect"] / 100,
                "romance": r["romance"] / 100, "debt": r["debt"] / 100, "fear": r["fear"] / 100,
                "fam": r["familiarity"] / 100, "grudge": r["grudge"] / 100, "kin": e["link"] in KIN,
                "blood": e["link"] in BLOOD, "link": e["link"], "adult": adult(e["age_cat"]), "child": e["age_cat"] == "child",
                "mood": e["mood_toward"] / 100, "urge": e["urge_to_interact"] / 100, "susp": e.get("suspicion", 0) / 100,
                "rep_danger": e["rep_danger"] / 100, "rep_trust": e["rep_trust"] / 100, "beauty": e["beauty"] / 100,
                "foreign": bool(self.vil and e.get("village") not in (None, self.vil["id"])),
                "partner": e["link"] in ("spouse", "partner"), "e": e}

    def village_rel(self, vid):
        if not self.vil:
            return 0.0
        o = next((x for x in self.vil["others"] if x["id"] == vid), None)
        return o["relation"] / 100 if o else 0.0

    def events_from(self, eid):
        return [ev for ev in self.st["events"] if ev["agent"] == eid]

    def mem_bad_from(self, eid):
        """Unresolved harm ME remembers from eid, weighted by importance, certainty and recency."""
        tot = 0.0
        for m in self.st["memories"]:
            if m["agent"] == eid and m["valence"] < 0:
                w = m["importance"] / 100 * m["certainty"] * (1.3 if m.get("defining") else 1.0)
                w *= 1.0 if m.get("outcome", "unresolved") in ("unresolved", "none") else .4
                w *= 1 / (1 + m["age_days"] / 120)
                tot += w * (-m["valence"] / 100)
        return min(1.0, tot)

    def mem_good_from(self, eid):
        tot = 0.0
        for m in self.st["memories"]:
            if m["agent"] == eid and m["valence"] > 0:
                tot += m["importance"] / 100 * m["certainty"] * (m["valence"] / 100) / (1 + m["age_days"] / 90)
        return min(1.0, tot)

    def title_of(self, eid):
        return [t for t in self.titles if t["holder"] == eid]


# ------------------------------------------------------------------------------------------------ utilities
class U:
    """Accumulates driver contributions for one candidate."""

    def __init__(self):
        self.c = dict.fromkeys(DRIVERS, 0.0)
        self.base = 0.0

    def add(self, driver, x):
        self.c[driver] += x
        return self

    @property
    def total(self):
        return self.base + sum(self.c.values())


def social_base(c, r, u):
    """Liking, trust, grudge and fear toward the target of a social act."""
    if r is None:
        return
    u.add("trust", .45 * r["aff"] + .15 * r["trust"] + .1 * r["mood"])
    u.add("kin", .25 * c.v["kin_protection"] if r["kin"] else 0)
    u.add("anger", -.35 * r["grudge"] - .3 * c.mem_bad_from(r["e"]["id"]))
    u.add("fear", -.3 * r["fear"])
    if r["foreign"]:
        u.add("norm", .25 * c.t["tolerance"] - .1 + .15 * c.village_rel(r["e"].get("village")))


def busy_cost(c, u, k=1.0):
    """Leaving the current activity costs commitment; urgent needs override sociability."""
    u.add("habit", -k * (.45 * c.commit + .1 * c.progress))
    u.add("need", -.35 * max(0.0, c.need_peak - .6))


def score_accept_like(c, ev, u, sign=1.0):
    """Utility of ACCEPTING a proposal / request / offer (refuse uses the opposite, plus pride)."""
    k = ev["content"] or {}
    ag = ev["agent"]
    r = c.rel(ag)
    kind = k.get("kind")
    t = ev["type"]
    if r:
        u.add("trust", sign * (.35 * r["trust"] + .3 * r["aff"] + .15 * r["respect"]))
        u.add("anger", sign * (-.3 * r["grudge"] - .25 * c.mem_bad_from(ag)))
        u.add("fear", sign * .25 * r["fear"])                # people one fears are obeyed
        if r["foreign"]:
            u.add("norm", sign * (.2 * c.t["tolerance"] + .15 * c.village_rel(r["e"].get("village"))))
    style = k.get("style")
    if style == "order":
        u.add("norm", sign * (-.35 * c.v["honor"] - .2 * c.t["aggression"] + (.3 * r["respect"] if r else 0)))
    if t == "offer":
        u.add("desire", sign * (1.2 * k.get("gain", 0) / 100 + (.25 if k.get("fair") == "cheap" else -.2 if k.get("fair") == "expensive" else 0)))
        u.add("need", sign * (.3 * c.s["hunger"] if k.get("good") in ("bread", "meat", "apple") and k.get("side") == "sell" else 0))
        u.add("habit", sign * -.08 * k.get("round", 0))
        return
    if t == "interrogate":
        pr = k.get("pressure")
        u.add("fear", sign * (.5 if pr == "threat" else .1) * (1 - c.t["courage"]) / 2)
        u.add("desire", sign * (.3 if pr == "bribe" else 0) * (1 - c.t["honesty"]) / 2)
        return
    if t == "collective_request":
        vil = c.vil or {}
        u.add("norm", sign * (.6 * vil.get("loyalty", 0) / 100 + .4 * vil.get("belonging", 50) / 100 + .2 * c.t["justice"]))
        u.add("trust", sign * .3 * vil.get("leader_trust", 0) / 100)
        u.add("need", sign * (.6 * vil.get("problem", {}).get("urgency", 0) / 100))
        u.add("desire", sign * -.35 * c.d["hoarding"])
        u.add("need", sign * -.3 * max(0, c.gap["food"]) if k.get("need") == "food" else 0)
        return
    if kind == "harm":
        vic = c.rel(k.get("victim"))
        act = k.get("act")
        sev = {"kill": 1.0, "beat": .6, "lock_up": .5, "steal_from": .4, "abandon": .4, "insult": .2}.get(act, .4)
        u.add("anger", sign * (.5 * c.t["aggression"] + (.6 * vic["grudge"] + .3 * c.mem_bad_from(vic["e"]["id"]) - .4 * vic["aff"] if vic else 0)))
        u.add("norm", sign * -sev * (1.3 * c.v["life_value"] + .5 * c.t["empathy"] + .3 * c.t["justice"]))
        if act == "steal_from":
            u.add("norm", sign * -.8 * c.v["property_respect"])
            u.add("desire", sign * .3 * c.d["hoarding"])
        if vic and vic["kin"]:
            u.add("kin", sign * -1.5 * c.v["kin_protection"])
        u.base += sign * -.4
        return
    if kind == "romance" or t in ("flirt", "kiss", "embrace"):
        if r is None or not (c.adult and r["adult"]):
            u.base += sign * -5.0                            # hard rule, defence in depth (never generated)
            return
        step = k.get("step", "walk_together")
        need_rom = {"walk_together": .0, "kiss": .25, "intimacy": .45}.get(step, .2)
        u.add("desire", sign * (1.2 * (r["romance"] - need_rom) + .4 * c.d["libido"] * (step == "intimacy") + .2 * r["beauty"] - .1))
        if c.attached and not r["partner"]:
            u.add("norm", sign * -1.2 * c.v["romantic_fidelity"])
        if r["blood"]:
            taboo = c.v["taboo_sensitivity"] + (c.vil["norms"]["taboo"] / 100 if c.vil else .6)
            u.add("norm", sign * -1.6 * taboo)
        return
    if kind == "teach":
        holders = ev.get("holders", 3)
        u.add("norm", sign * (.5 / (1 + holders) + .2 * c.t["empathy"] + .15 * c.d["achievement"]))   # transmit a craft before it dies
        u.add("desire", sign * {"coins": .25, "goods": .2, "labor": .15, "none": -.1}.get(k.get("pay"), 0))
        u.add("need", sign * (-.3 * max(0, c.s["fatigue"]) - .2 * c.commit))
        return
    if kind == "apprenticeship":
        holders = ev.get("holders", 3)
        u.add("desire", sign * (.35 * c.d["achievement"] + .25 * c.t["ambition"] + .3 * c.t["curiosity"]
                                + (.3 if c.me["job"] in ("none", "apprentice") else -.3)))
        u.add("norm", sign * (.25 / (1 + holders)))
        u.add("need", sign * {"free": .2, "labor_for_years": -.25, "coins": -.15}.get(k.get("terms"), 0))
        return
    if kind == "trade":
        mine = k.get("you_give")
        u.add("desire", sign * (.15 - (.3 if mine in c.inv and mine in ("axe", "hoe", "knife") else 0)))
        u.add("need", sign * (.3 * c.s["hunger"] if k.get("you_get") in ("bread", "meat", "apple") else .1 * max(0, c.gap["fuel"])))
        return
    if kind == "leisure":
        u.add("desire", sign * (.45 * c.d["social_need"] + .25 * c.t["sociability"] + .15 * c.s["joy"] - .3 * max(0, c.s["fatigue"])))
        busy_cost(c, u, .8 * sign)
        return
    if kind == "task":
        u.add("trust", sign * .15)
        u.add("need", sign * (-.35 * max(0, c.s["fatigue"]) - .3 * c.need_peak))
        busy_cost(c, u, .8 * sign)
        return
    if kind == "accompany":
        dest = str(k.get("dest", ""))
        if dest.startswith("beyond"):
            u.add("curiosity", sign * (.6 * c.t["curiosity"] + .3 * c.t["courage"] + (.3 if k.get("why") in ("treasure", "curiosity") else 0)))
            u.add("fear", sign * (-.7 * c.v["life_value"] - .4 * c.s["fear"] - .3))
            u.add("kin", sign * (-.3 * c.v["kin_protection"] if c.hh and c.hh.get("head") else 0))
            if k.get("for") == "a week":
                u.base += sign * -.25
        else:
            u.add("trust", sign * .1)
        busy_cost(c, u, .7 * sign)
        return
    if t == "request":
        u.add("norm", sign * (.35 * c.t["empathy"] + .1))
        u.add("debt", sign * (-.6 * r["debt"] if r else 0))     # ME owes them (debt < 0) -> accept
        u.add("desire", sign * -.3 * c.d["hoarding"])
        busy_cost(c, u, .5 * sign)
        return
    u.add("trust", sign * .05)


def utility(c, cand):
    a, args = cand["a"], cand["args"]
    u = U()
    eid = args.get("e")
    r = c.rel(eid) if eid else None
    ev = c.events.get(args.get("p") or args.get("q") or args.get("site") or args.get("poll") or args.get("doc") or "")
    mine_events = [x for x in c.st["events"] if x["target"] == "me"]
    ev_from = c.events_from(eid) if eid else []
    hostile_from = [x for x in ev_from if x["type"] in ("insult", "threat", "shove", "strike", "accusation", "lie_revealed",
                                                        "promise_broken", "interrogate")]
    hostile = max([x["intensity"] / 100 for x in hostile_from] + [0])
    kind_from = any(x["type"] in ("gift", "help_given", "compliment") for x in ev_from)
    greet_from = any(x["type"] in ("greeting", "chat_overture") for x in ev_from)
    danger = max([x["intensity"] / 100 for x in c.st["events"] if x["type"] in ("fire", "wild_animal", "noise_danger")] + [0])

    # ------------------------------------------------------------- hard rules (never learned)
    if a in ROMANTIC and (r is None or not c.adult or not r["adult"]):
        u.base = -5.0
        return u

    if a in ("continue", "wait"):
        u.add("habit", .3 + .9 * c.commit + .2 * c.progress - (.25 if a == "wait" else 0))
        u.add("need", -.9 * max(0.0, c.need_peak - .45))
        u.add("fear", -1.0 * danger)
        u.base -= .9 * c.urgency
        if c.me["current_action"] == "sleep" and not c.night:
            u.base -= .4
    elif a in ("rest", "sleep"):
        f = max(0.0, c.s["fatigue"])
        u.add("need", 1.3 * f + (.4 if a == "sleep" and c.night else -.3 if a == "sleep" else 0) + .3 * c.s["pain"])
        u.base -= .3 + .5 * c.urgency
        u.add("fear", -.8 * danger)
    elif a == "eat":
        u.add("need", 1.8 * c.s["hunger"] - .35)
        u.base -= .4 * c.urgency
    elif a == "drink":
        u.add("need", 1.8 * c.s["thirst"] - .3)
        u.base -= .4 * c.urgency
    elif a == "fetch_water":
        u.add("need", 1.1 * c.s["thirst"] - .2)
        u.add("habit", .35 if c.me["job"] == "farmer" and not c.night else 0)
        u.base -= .3 + .6 * c.urgency
    elif a == "go_to":
        l = args.get("l")
        if eid:                                                   # go see a person (lawyer, title holder, service)
            g = next((x for x in c.goals if x["type"] == "seek_help"), None)
            u.add("need", .8 * g["priority"] / 100 if g and c.title_of(eid) else 0)
            u.add("curiosity", .3 * c.t["curiosity"] + .2 * c.t["ambition"])
            social_base(c, r, u)
            u.base -= .25
        elif l == "home":
            u.add("need", .6 * c.s["hunger"] * (not any(c.inv.get(x) for x in ("bread", "apple", "meat"))) + .3 * max(0, c.s["fatigue"]))
            u.add("fear", .6 * c.s["fear"] + .4 * danger)
            u.add("habit", .2 if c.hour >= 19 else 0)
            u.base -= .45 + .3 * c.urgency
        elif l == "well":
            u.add("need", .9 * c.s["thirst"] - .2)
            u.base -= .45 + .4 * c.urgency
        else:
            u.add("desire", .3 * c.d["social_need"] + .15 * c.t["sociability"])
            cel = next((x for x in c.st["events"] if x["type"] == "celebration"), None)
            if cel and l == "square":
                u.add("norm", .45 + .25 * (c.vil["belonging"] / 100 if c.vil else .5) + (.2 if cel["content"].get("when") == "now" else 0))
            u.base -= .55 + .4 * c.urgency * (cel is None)
    elif a == "search":
        u.add("need", 1.3 * c.s["hunger"] if args.get("i") == "food" else 0)
        u.add("curiosity", .2 * c.t["curiosity"])
        u.base -= .5
    elif a in ("till", "plant", "harvest", "dig", "cut", "craft", "place"):
        u.add("habit", .5 + .3 * c.me["body"]["job_skill"] / 100)
        u.add("desire", .35 * c.d["achievement"] + .15 * c.t["ambition"])
        u.add("need", -.6 * max(0, c.s["fatigue"]) - .4 * c.need_peak + .2 * max(0, c.gap["tools"] if a == "craft" else c.gap["food"]))
        u.base -= (.9 if c.night else .2) + .7 * c.urgency
    elif a == "leisure":
        u.add("desire", .4 * c.d["social_need"] + .25 * c.t["sociability"] + .2 * max(0, c.s["joy"]) - .25 * c.d["achievement"])
        cel = next((x for x in c.st["events"] if x["type"] == "celebration"), None)
        if cel:
            u.add("norm", (.5 if cel["content"]["kind"] != "funeral" else .2) + .2 * (c.vil["belonging"] / 100 if c.vil else .5))
        u.add("habit", .2 if 17 <= c.hour < 22 else -.15)
        u.base -= .45 + .7 * c.urgency
    elif a == "wander":
        u.add("curiosity", .25 * c.t["curiosity"])
        u.base -= .6 + .5 * c.urgency
    elif a in ("greet", "chat", "approach", "compliment"):
        social_base(c, r, u)
        u.add("desire", .3 * c.d["social_need"] + .2 * c.t["sociability"] + (.1 * r["urge"] if r else 0))
        if greet_from:
            u.add("norm", {"greet": .7, "chat": .45, "approach": .2, "compliment": .1}[a] * (1 + .3 * c.t["sociability"]))
        if kind_from and a == "compliment":
            u.add("trust", .3)
        if out_of_world := any(x["out_of_world"] for x in ev_from):
            u.add("curiosity", -.2)
        u.add("anger", -.5 * hostile)
        u.base -= {"greet": .35, "chat": .3, "approach": .4, "compliment": .45}[a] + .35 * c.urgency * (not greet_from)
        busy_cost(c, u, .5)
    elif a == "observe":
        u.add("curiosity", .3 * c.t["curiosity"] + (.4 if any(x["out_of_world"] for x in c.st["events"]) else 0))
        u.add("fear", .4 * (r["susp"] if r else 0) + .3 * (r["rep_danger"] if r else 0) + .35 * danger)
        u.base -= .45
    elif a == "avoid":
        if r:
            u.add("fear", .7 * r["fear"] + .3 * max(0, r["rep_danger"]) + .5 * hostile * (1 - c.t["courage"]) / 2)
            u.add("anger", .3 * r["grudge"] + .2 * c.mem_bad_from(eid))
            u.add("trust", -.4 * r["aff"] - .2 * c.t["sociability"])
            if any((x["content"] or {}).get("kind") == "romance" or x.get("romantic") for x in ev_from):
                u.add("norm", .6 * c.v["taboo_sensitivity"] if r["blood"] else .4 * c.v["romantic_fidelity"] * c.attached)
        if any(x["out_of_world"] for x in ev_from):
            u.add("fear", .2 * c.s["confusion"])
        u.base -= .5
    elif a == "embrace":
        social_base(c, r, u)
        u.add("desire", .3 * (r["aff"] if r else 0) + .15 * c.t["sociability"] + (.4 if kind_from else 0))
        u.add("trust", .3 * (r["fam"] - .6) if r else 0)
        if r and r["kin"] and any(x["type"] == "injury" for x in c.st["events"]):
            u.add("kin", .3)
        u.base -= .55 + .4 * c.urgency
        busy_cost(c, u, .6)
        if c.night and c.me["current_action"] == "sleep":
            u.base -= .4
    elif a in ROMANTIC:
        social_base(c, r, u)
        lvl = {"flirt": 0, "kiss": .2, "be_intimate": .45}[a]
        adv = any(x.get("romantic") or (x["content"] or {}).get("kind") == "romance" for x in ev_from)
        u.add("desire", 1.3 * (r["romance"] - lvl) + .3 * c.d["libido"] + .15 * r["beauty"] + (.35 if adv else 0))
        if c.attached and not r["partner"]:
            u.add("norm", -1.3 * c.v["romantic_fidelity"])
        if r["e"]["love_status"] in ("married", "partnered") and not r["partner"]:
            u.add("norm", -.4 * c.v["romantic_fidelity"])
        if r["blood"]:
            taboo = c.v["taboo_sensitivity"] + (c.vil["norms"]["taboo"] / 100 if c.vil else .6)
            u.add("norm", -1.8 * taboo)
        if a == "be_intimate" and c.me["place_type"] != "home":
            u.base -= .8
        busy_cost(c, u, .6)
        u.add("need", -.8 * max(0.0, c.need_peak - .4))
        u.base -= .45 + .6 * c.urgency
    elif a in ("accept", "refuse") and ev is not None:
        sign = 1.0 if a == "accept" else -1.0
        tmp = U()
        score_accept_like(c, ev, tmp, sign)
        for k_, x in tmp.c.items():
            u.add(k_, .9 * x)
        u.base += .9 * tmp.base
        if a == "refuse":
            st_ = (ev["content"] or {}).get("style")
            u.add("norm", .15 * c.v["honor"] + (.15 * c.t["aggression"] if st_ == "order" else 0))
            u.base -= .1
        else:
            u.base += .05
    elif a == "ask":
        topic = args.get("f") or args.get("topic") or ""
        u.add("curiosity", .35 * c.t["curiosity"] + .1)
        if r:
            u.add("trust", -.25 * r["trust"] + .15 * r["fam"])
        if any(x["out_of_world"] for x in ev_from):
            u.add("curiosity", .6 * c.s["confusion"] + .3)
        if topic in ("details", "why", "explanation", "proof", "why_do_you_ask", "why_that_price"):
            u.add("trust", .2 * (1 - (r["trust"] if r else 0)) / 2 + (.25 if topic == "proof" else 0))
        if topic == "my_case" or topic == "who_is_lawyer":
            g = next((x for x in c.goals if x["type"] == "seek_help"), None)
            u.add("need", .9 * g["priority"] / 100 if g else 0)
        if c.vil and topic == c.vil["problem"]["kind"]:
            u.add("norm", .2 * c.vil["belonging"] / 100)
        u.add("anger", -.2 * max(0, c.s["anger"]) - .2 * hostile * c.t["aggression"])
        u.base -= .3 + (.25 if topic == "why_do_you_ask" else 0)
    elif a == "propose":
        p_ = args.get("p", "")
        if p_.startswith("expedition:"):
            u.add("curiosity", .6 * c.t["curiosity"] + .3 * c.t["courage"] + .2 * c.t["ambition"])
            u.add("fear", -.6 * c.v["life_value"])
            u.base -= .4
        else:
            u.add("desire", .25 * c.t["ambition"] + .25 * c.d["hoarding"] + .1)
            social_base(c, r, u)
            u.base -= .45
    elif a == "insult":
        u.add("anger", .7 * max(0, c.s["anger"]) + .45 * c.t["aggression"] + .4 * (r["grudge"] if r else 0) + .3 * c.mem_bad_from(eid)
              + .7 * hostile * (.5 + c.v["honor"]))
        u.add("norm", -.3 * c.t["empathy"] - .15 * c.t["honesty"] + (.2 * c.v["honor"] if hostile else 0))
        if r:
            u.add("fear", -.6 * r["fear"] - .3 * max(0, r["rep_danger"]))
            u.add("trust", -.45 * r["aff"] - .2 * r["respect"])
            if r["child"]:
                u.add("norm", -.6)
            if r["blood"] and any(x.get("romantic") or (x["content"] or {}).get("kind") == "romance" for x in ev_from):
                u.add("norm", .5 * c.v["taboo_sensitivity"])
        u.base -= .65
    elif a in ("attack", "threaten", "chase", "expel"):
        m_ = args.get("m", "")
        harm_vs_kin = any((x["content"] or {}).get("kind") == "harm" and (c.rel((x["content"] or {}).get("victim")) or {}).get("kin")
                          for x in ev_from)
        harm_any = any((x["content"] or {}).get("kind") == "harm" for x in ev_from)
        wrong = any(x["type"] in ("theft", "strike", "shove", "insult") and x["target"] != "me" for x in ev_from)
        u.add("anger", .7 * max(0, c.s["anger"]) + .45 * c.t["aggression"] + .35 * (r["grudge"] if r else 0) + .25 * c.mem_bad_from(eid)
              + .8 * hostile * (.4 + .6 * c.v["honor"]))
        u.add("kin", .9 * c.v["kin_protection"] if harm_vs_kin else 0)
        u.add("norm", (.4 * c.v["life_value"] if harm_any else 0) + (.4 * c.t["justice"] if wrong and a == "chase" else 0)
              - (.7 * c.v["life_value"] if a == "attack" else .2 * c.v["life_value"]) - .3 * c.t["empathy"])
        if r:
            u.add("fear", -(.7 if a == "attack" else .4) * r["fear"] * (1 - c.t["courage"]) - .4 * max(0, r["rep_danger"]) * (a == "attack"))
            u.add("trust", -.5 * r["aff"])
            if r["child"]:
                u.add("norm", -1.0)
        u.add("need", (.3 * c.strength - .2 + (-.4 * (1 - c.hp)) if a in ("attack", "chase") else 0))
        if a == "expel" and r and r["blood"] and any(x.get("romantic") or (x["content"] or {}).get("kind") == "romance" for x in ev_from):
            u.add("norm", .9 * c.v["taboo_sensitivity"])
        u.add("fear", .2 * c.t["courage"])
        u.base -= {"attack": 1.0 if m_ != "strike" else 1.2, "threaten": .75, "chase": .8, "expel": .7}[a]
    elif a == "flee":
        threat = max(hostile, danger, (r["fear"] if r else 0) * .6)
        u.add("fear", 1.2 * threat * (1 - .7 * c.t["courage"]) + .6 * c.s["fear"] + .3 * (1 - c.hp))
        u.add("kin", -.4 * c.v["kin_protection"] * any(c.rel(x)["kin"] for x in c.ents if c.rel(x)["e"]["distance"] < 8) * (danger > 0))
        u.base -= .55
    elif a == "defend":
        threat = max(hostile, danger)
        u.add("fear", .6 * threat * (.5 + c.t["courage"]) + .2 * c.strength)
        u.base -= .45
    elif a == "call_for_help":
        threat = max(hostile, danger, .6 * any((x["content"] or {}).get("kind") == "harm" for x in c.st["events"]),
                     .6 * any(x["type"] == "injury" for x in c.st["events"]))
        u.add("fear", .9 * threat * (1 - .4 * c.t["courage"]) + .3 * c.s["fear"])
        u.add("trust", .1 * c.t["sociability"])
        u.base -= .6
    elif a == "apologize":
        social_base(c, r, u)
        u.add("norm", .3 * c.t["empathy"] - .35 * c.v["honor"] + .15 * c.t["honesty"])
        u.add("fear", .3 * (r["fear"] if r else 0))
        u.base -= .7
    elif a == "forgive":
        social_base(c, r, u)
        u.add("norm", .4 * c.t["empathy"] - .5 * c.t["grudge"] + .15)
        u.add("anger", -.4 * max(0, c.s["anger"]))
        u.base -= .55
    elif a == "accuse":
        f = args.get("f", "")
        certain = max([x["reliability"] for x in ev_from] + [.5])
        u.add("norm", .5 * c.t["justice"] + .3 * c.v["honor"] * (f in ("lied", "slandered", "stole", "betrayed")) + .2)
        u.add("anger", .5 * max(0, c.s["anger"]) + .3 * (r["grudge"] if r else 0) + .3 * hostile)
        if f == "infidelity":
            u.add("norm", .8 * c.v["romantic_fidelity"])
            u.add("kin", .3)
        if f == "mismanagement" and c.vil:
            u.add("trust", -.6 * c.vil["leader_trust"] / 100 + .2 * c.t["ambition"])
            u.base -= .3
        if f == "abuse_of_power" and c.vil:
            u.add("trust", -.4 * c.vil["leader_legit"] / 100)
        if r:
            u.add("fear", -.5 * r["fear"])
            u.add("trust", -.3 * r["aff"])
        u.add("trust", .3 * (certain - .7))
        u.base -= .6
    elif a in ("assist", "comfort", "heal"):
        task = args.get("task", "")
        u.add("norm", .55 * c.t["empathy"] + (.4 * c.t["justice"] if task == "help_victim" else 0) + .1)
        if r:
            u.add("trust", .4 * r["aff"])
            u.add("kin", .8 * c.v["kin_protection"] if r["kin"] else 0)
            u.add("anger", -.3 * r["grudge"])
        hurt = any(x["type"] == "injury" and x["target"] == eid for x in c.st["events"]) or \
            any(x["type"] == "celebration" and x["content"].get("kind") == "funeral" and x["content"].get("for") == eid for x in c.st["events"])
        u.add("need", .5 if hurt else 0)
        if task == "evacuate":
            gravity = min(1.0, 1.4 * danger)
            u.add("fear", (.5 * c.t["courage"] - .3) * danger)
            u.add("norm", .3 * gravity - .3)
            for k_ in ("trust", "kin"):
                u.c[k_] *= gravity
        if task == "their_task":
            busy_cost(c, u, .6)
        u.base -= .55 + (.0 if hurt or task in ("evacuate", "help_victim") else .2)
    elif a in ("inform", "warn"):
        f = args.get("f", "") or ""
        social_base(c, r, u)
        u.add("desire", .15 * c.t["sociability"])
        if "plans_harm" in f or f in ("danger", "boss_asks") or f.endswith("_asks_about_you"):
            gravity = min(1.0, 1.4 * danger) if f == "danger" else 1.0
            u.add("kin", gravity * .8 * c.v["kin_protection"] if r and r["kin"] else 0)
            u.add("norm", gravity * (.35 * c.t["empathy"] + .2 * c.t["justice"]))
            u.add("fear", .4 * danger)
            u.base += .15 * gravity
        elif f.startswith("legend:") or f.startswith("found:"):
            u.add("desire", .25 * c.t["sociability"] - (.3 * c.d["hoarding"] if f.startswith("found:") else 0))
            u.add("norm", .25 * c.t["honesty"] if f.startswith("found:") else 0)
        elif f.startswith("problem:"):
            u.add("norm", .3 * (c.vil["belonging"] / 100 if c.vil else .5))
        elif ":" in f:                                         # tell X that Y did something (gossip or justice)
            about = f.split(":")[0]
            ra = c.rel(about)
            u.add("norm", .35 * c.t["justice"] + (.2 * c.t["honesty"]))
            u.add("anger", .3 * (ra["grudge"] if ra else 0) - .3 * (ra["aff"] if ra else 0))
        if args.get("mem"):                                   # betray a secret to the one who presses ME
            mem = c.mems.get(args["mem"])
            subj = c.rel(mem["agent"]) if mem else None
            u.add("fear", .7 * (r["fear"] if r else 0) + .4 * any((x["content"] or {}).get("pressure") == "threat" for x in ev_from))
            u.add("trust", -.5 * (subj["aff"] if subj else 0) - .3 * c.t["honesty"] * 0)
            u.add("norm", .25 * c.t["justice"] - .25 * c.v["honor"])
            u.add("desire", .3 * (1 - c.t["honesty"]) / 2 * any((x["content"] or {}).get("pressure") == "bribe" for x in ev_from))
        u.base -= .55
    elif a in ("deceive", "bribe"):
        u.add("norm", -.8 * c.t["honesty"] - .2 * c.v["honor"])
        u.add("fear", .4 * c.s["fear"] + .4 * (r["fear"] if r else 0))
        u.add("trust", -.2 * (r["trust"] if r else 0))
        if a == "bribe":
            u.add("desire", -.4 * c.d["hoarding"])
        u.base -= .65
    elif a == "negotiate":
        mv = args.get("move")
        offer = next((x for x in ev_from if x["type"] == "offer"), None)
        gain = (offer["content"]["gain"] / 100) if offer else 0
        rnd_ = offer["content"].get("round", 0) if offer else 0
        val = {"concede_small": .25 * c.t["empathy"] + .3 * gain + .1 * rnd_,
               "hold": .15 + .2 * c.d["hoarding"] + .1 * c.t["courage"],
               "raise": .35 * c.t["ambition"] + .3 * c.d["hoarding"] - .25 * c.t["empathy"] - .3 * gain - .1 * rnd_,
               "sweeten": .25 * c.t["empathy"] + .2 * (r["aff"] if r else 0) + .1,
               "walk": -.8 * gain - .4 * (r["trust"] if r else 0) - .15 + .12 * rnd_}.get(mv, 0)
        u.add("desire", val)
        if args.get("move") == "raise" and any((x["content"] or {}).get("kind") == "teach" for x in ev_from):
            u.add("desire", .3 * c.d["hoarding"] + .2)
        u.base -= .4
    elif a == "answer":
        q = ev or {}
        cq = q.get("content", {}) or {}
        sens = cq.get("sens", 30) / 100
        subj = c.rel(cq.get("subject"))
        protect = (.6 * subj["aff"] + (.4 if subj["kin"] else 0)) if subj else 0
        trust_asker = (r["trust"] + r["aff"]) / 2 if r else 0
        mode = args.get("m")
        val = {"truth": .5 * c.t["honesty"] + .4 * trust_asker - sens * (.4 + protect) + .1,
               "vague": .1 + .3 * sens + .1 * protect,
               "lie": -.7 * c.t["honesty"] + .5 * sens * protect - .3,
               "refuse": .5 * sens - .3 * trust_asker + .2 * c.v["honor"] - .2,
               "unknown": -.3 * c.t["honesty"] + .4 * sens * protect - .15,
               "redirect": .2 * c.t["sociability"] - .1}.get(mode, 0)
        u.add("trust" if mode in ("truth", "refuse") else "norm", val)
        u.base -= .2
    elif a == "thank":
        u.add("norm", (.9 if kind_from else 0) + .3 * c.t["sociability"] + .2 * c.t["empathy"])
        social_base(c, r, u)
        u.base -= .3 if kind_from else .9
    elif a == "give":
        social_base(c, r, u)
        u.add("debt", -.6 * (r["debt"] if r else 0) + (.3 if kind_from else 0))
        u.add("desire", -.5 * c.d["hoarding"])
        u.add("norm", .3 * c.t["empathy"])
        u.base -= .65
    elif a in ("vote", "campaign", "endorse"):
        opt = args.get("option") if a == "vote" else eid
        ro = c.rel(opt) if opt and opt != "blank" else None
        if ro:
            u.add("trust", .45 * ro["respect"] + .35 * ro["trust"] + .3 * ro["aff"] - .3 * ro["grudge"])
            u.add("kin", .4 if ro["kin"] else 0)
        elif opt == "blank":
            others = [c.rel(x) for x in (c.events.get(args.get("poll", ""), {}) or {}).get("content", {}).get("options", []) if x in c.ents]
            best = max([(x["respect"] + x["trust"]) / 2 for x in others if x] + [0])
            u.add("trust", -.5 * best - .1)
        u.add("norm", .25 * (c.vil["belonging"] / 100 if c.vil else .5))
        u.base -= {"vote": .15, "campaign": .6 - .3 * c.t["ambition"] - .2 * c.t["sociability"], "endorse": .45}[a]
    elif a == "claim_title":
        u.add("desire", .8 * c.t["ambition"] + .2 * c.t["courage"] - .1)
        if c.vil:
            u.add("trust", -.3 * c.vil["leader_trust"] / 100)
        u.base -= .75
    elif a == "contest_claim":
        u.add("trust", -.4 * (r["respect"] + r["trust"]) / 2 if r else 0)
        u.add("norm", .3 * c.t["justice"])
        u.add("desire", .3 * c.t["ambition"])
        u.add("fear", -.3 * (r["fear"] if r else 0))
        u.base -= .6
    elif a == "tear_down_notice":
        u.add("anger", .3 * c.t["aggression"] + .3 * max(0, c.s["anger"]))
        u.add("norm", -.3 * c.v["property_respect"] - (.3 * c.vil["leader_legit"] / 100 if c.vil else 0))
        u.base -= .75
    elif a == "post_notice":
        u.add("desire", .35 * c.t["ambition"] + .15 * c.t["sociability"])
        if args.get("content", "").startswith("seeking:"):
            g = next((x for x in c.goals if x["type"] == "seek_help"), None)
            u.add("need", .5 * g["priority"] / 100 if g else 0)
        u.base -= .6
    elif a in ("pick_up", "claim"):
        u.add("desire", .4 * c.d["hoarding"] + .2 * max(0, c.gap["food"]) + .1)
        u.add("norm", -.25 * c.v["property_respect"])
        u.base -= .3
    elif a == "teach":
        tmp = U()
        req = next((x for x in ev_from if (x["content"] or {}).get("kind") == "teach"), None)
        if req:
            score_accept_like(c, req, tmp, 1.0)
        for k_, x in tmp.c.items():
            u.add(k_, x)
        u.add("norm", .1)
        u.base -= .05
    elif a in ("contribute", "supply"):
        tmp = U()
        if ev is not None:
            score_accept_like(c, ev, tmp, 1.0)
        for k_, x in tmp.c.items():
            u.add(k_, x)
        if a == "supply":
            u.add("desire", -.25 * c.d["hoarding"])
            u.base -= .1
    elif a == "store":                                       # hoard food at home during a shortage
        u.add("desire", .7 * c.d["hoarding"] + .3 * max(0, c.gap["food"]))
        u.add("norm", -.4 * (c.vil["loyalty"] / 100 if c.vil else 0) - .2 * c.t["empathy"])
        u.add("kin", .2 * c.v["kin_protection"] * (c.hh["size"] > 2 if c.hh else 0))
        u.base -= .6
    elif a == "accompany":
        tmp = U()
        prop = next((x for x in ev_from if (x["content"] or {}).get("kind") == "accompany"), None)
        if prop:
            score_accept_like(c, prop, tmp, 1.0)
        for k_, x in tmp.c.items():
            u.add(k_, x)
        g = next((x for x in c.goals if x["type"] == "accompany" and x["target"] == eid), None)
        u.add("habit", .7 * g["priority"] / 100 if g else 0)
        u.base -= .1
    elif a == "dress":
        o = args.get("outfit")
        cel = next((x for x in c.st["events"] if x["type"] == "celebration"), None)
        cold = c.me["weather"] in ("snow", "wind", "storm") or c.me["season"] == "winter"
        fit = {"work": .6 if 5 <= c.hour < 9 and c.me["job"] != "none" else -.3,
               "cold": .5 + (.3 if c.me["weather"] == "snow" else 0) if cold else -.5,
               "night": .5 + .4 * max(0, c.s["fatigue"]) if c.night else -.6,
               "festival": (.5 + .3 * c.t["sociability"] + .2 * c.t["ambition"]) if cel and cel["content"]["kind"] != "funeral" else -.6,
               "mourning": (.6 + .4 * c.v["honor"]) if cel and cel["content"]["kind"] == "funeral" else -.8,
               "everyday": .25 if not c.night else -.2}.get(o, -.3)
        u.add("norm" if o in ("festival", "mourning") else "need" if o in ("cold", "night") else "habit", fit)
        u.add("norm", .15 * (c.vil["norms"]["honor"] / 100 if c.vil else .5) if o in ("festival", "mourning") else 0)
        u.base -= .25 + .5 * c.urgency * (cel is None)
    else:
        u.base -= .8                                         # unknown to the reference: rarely chosen
    if c.crisis and a not in ("flee", "call_for_help", "defend", "attack", "avoid", "threaten", "warn", "assist", "expel",
                              "refuse", "deceive", "negotiate", "inform", "bribe", "chase", "observe"):
        u.base -= .25
    return u


def decide(rec):
    """-> dict(util, scores, soft, drivers, best)."""
    c = Ctx(rec)
    us = [utility(c, cand) for cand in rec["cands"]]
    util = [x.total for x in us]
    umax = max(util)
    scores = []
    for x in util:
        s = 4 - (umax - x) / STEP
        s = 0 if x < ABSURD else max(0, min(4, int(math.floor(s + .5))))
        scores.append(s)
    m = max(util)
    e = [math.exp((x - m) / TEMP) for x in util]
    z = sum(e)
    soft = [round(x / z, 4) for x in e]
    best = util.index(umax)
    contrib = us[best].c
    drivers = [k for k, x in sorted(contrib.items(), key=lambda kv: -abs(kv[1])) if abs(x) >= .15][:3] or ["habit"]
    return {"util": [round(x, 4) for x in util], "scores": scores, "soft": soft, "drivers": drivers, "best": best,
            "label_source": VERSION}


# ------------------------------------------------------------------------------------------------ self-test
def _selftest():
    import random
    import generate_states as gs
    rng = random.Random(5)
    n, bad = 0, 0
    dist = [0] * 5
    for i in range(600):
        fam = rng.choice(list(gs.FAMILIES))
        rec = gs.gen_situation(rng, i, fam, 77, 4, 2, False)
        out = decide(rec)
        assert len(out["scores"]) == len(rec["cands"]) and 4 in out["scores"]
        assert abs(sum(out["soft"]) - 1) < 1e-3
        for cand, s in zip(rec["cands"], out["scores"]):
            dist[s] += 1
            e = next((x for x in rec["state"]["entities"] if x["id"] == cand["args"].get("e")), None)
            if cand["a"] in ROMANTIC and (e is None or not adult(e["age_cat"]) or not adult(rec["state"]["me"]["age_cat"])):
                bad += s > 0
        n += 1
    assert bad == 0, "romantic action scored with a minor"
    # directional checks on hand-made minimal pairs
    rec = gs.gen_situation(random.Random(1), 0, "provocation", 77, 2, 1, False)
    def best_of(r, act):
        o = decide(r)
        return max([u for u, c in zip(o["util"], r["cands"]) if c["a"] == act] + [-9])
    lo = json.loads(json.dumps(rec)); hi = json.loads(json.dumps(rec))
    lo["state"]["me"]["traits"]["aggression"] = -80
    hi["state"]["me"]["traits"]["aggression"] = 80
    assert best_of(hi, "insult") > best_of(lo, "insult"), "aggression must raise insult"
    tot = sum(dist)
    print(f"reference decider {VERSION}: {n} situations scored; score distribution 0..4 = "
          + " ".join(f"{k}:{100 * v / tot:.0f}%" for k, v in enumerate(dist)) + "; hard rules held; directional check passed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="")
    ap.add_argument("--show", type=int, default=0)
    a = ap.parse_args()
    if not a.inp:
        _selftest()
        return
    for i, line in enumerate(open(a.inp, encoding="utf-8")):
        if i >= a.show:
            break
        rec = json.loads(line)
        out = decide(rec)
        print(f"### {rec['id']} [{rec['family']}] drivers={out['drivers']}")
        print(rec["text"].split("OPTS")[0].strip()[:1500])
        order = sorted(range(len(rec["cands"])), key=lambda j: -out["util"][j])
        for j in order:
            c = rec["cands"][j]
            print(f"  {out['scores'][j]}  {out['util'][j]:+.2f}  {c['a']} {' '.join(str(x) for x in c['args'].values())}")
        print()


if __name__ == "__main__":
    main()
