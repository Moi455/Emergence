#!/usr/bin/env python3
"""social_rules.py - ENGINE-side rules that give the model the facts it needs to judge people.

Ownership and theft, concealment, apparent intent (accident or not), means-end candidates from
object affordances, physical reachability, and the decision context built from a memory store.
The model never computes these; it receives them as token fields and decides.
"""
import math
from collections import deque

from memory_service import MemoryStore, DAY


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ------------------------------------------------------------------ ownership
def believed_owner(store, item_id, now):
    """Who this NPC thinks owns the item, and how sure it is (from seen use, claims, deeds)."""
    w = {}
    for m in store.mems.values():
        if m["kind"] in ("owns", "told_owner", "deed_read") and m["obj"] == item_id:
            w[m["agent"]] = w.get(m["agent"], 0) + m["certainty"] * store.SRC_W.get(m["source"], .5)
    if not w:
        return None, 0.0
    o = max(w, key=w.get)
    return o, round(min(1.0, w[o]), 2)


def resolve_take(actor, store, item, now):
    """Truth is the engine's (rightful_owner); the actor acts on its BELIEF. An honest mistake is possible."""
    actually_owned = item.get("rightful_owner") not in (None, actor)
    believed, conf = believed_owner(store, item["id"], now)
    believes_owned = believed not in (None, actor) and conf >= .4
    if not actually_owned:
        return {"type": "take", "intentional": False, "mistake": False, "victim": None}
    return {"type": "theft", "intentional": believes_owned, "mistake": not believes_owned, "victim": item["rightful_owner"]}


# ---------------------------------------------------------------- concealment
def conceal(item, actor, place, covered_by_placed_blocks=False, in_closed_container=False):
    item.update(hidden_by=actor, place=place, covered=covered_by_placed_blocks, container_closed=in_closed_container)
    return item


def concealment_evidence(item):
    """How strongly the scene suggests the object was hidden on purpose (0..1). A finder sees this, not the hider's mind."""
    if item.get("hidden_by") is None:
        return 0.0
    return .9 if item.get("covered") else .6 if item.get("container_closed") else .3


def found_hidden_event(item, finder_store, now):
    witnessed = any(m["kind"] == "hid_item" and m["obj"] == item["id"] for m in finder_store.mems.values())
    return {"type": "found_hidden", "item": item["id"], "deliberate_evidence": concealment_evidence(item),
            "hider_known": witnessed, "owner_believed": believed_owner(finder_store, item["id"], now)[0]}


# ---------------------------------------------------------- accident or not
BASE_INTENT = {"strike": .8, "shove": .6, "theft": .85, "insult": .9, "take": .2, "trip": .1, "drop": .1,
               "collapse": .15, "misfire": .15, "tool_break": .1}


def apparent_intent(kind, repeated=0, prior_threat=0, actor_clumsy=0, apologized=0, hid_afterwards=0):
    """Evidence of intent visible to a witness (0..1). The engine keeps the true flag separately."""
    x = BASE_INTENT.get(kind, .5) + .2 * repeated + .2 * prior_threat - .3 * actor_clumsy - .2 * apologized + .1 * hid_afterwards
    return round(clamp(x, 0, 1), 2)


def interpret_intent(evidence, trust, grudge):
    """The same act is read differently by a friend and an enemy (bias from relation), before any model call."""
    return round(clamp(evidence - .25 * trust / 100.0 + .25 * grudge / 100.0, 0, 1), 2)


# -------------------------------------------------------------- means - ends
AFFORD = {"stone": ["stackable", "bridge", "blockers"], "wood": ["stackable", "bridge", "blockers", "fuel"],
          "dirt": ["stackable", "bridge", "blockers"], "ladder": ["climbable"], "rope": ["climbable"],
          "chest": ["container", "hiding"], "torch": ["light", "signal"], "bell": ["signal"],
          "fire": ["signal", "danger"], "cart": ["carry"], "boat": ["cross_water"]}
GOAL_RULES = {
    "reach_high": [("place", {"pattern": "pile"}, "stackable"), ("use", {}, "climbable")],
    "cross_gap": [("place", {"pattern": "line"}, "bridge"), ("use", {}, "cross_water")],
    "block_path": [("place", {"pattern": "wall"}, "blockers")],
    "hide_item": [("conceal", {}, "container"), ("place", {"pattern": "fill"}, "stackable")],
    "call_attention": [("use", {}, "signal")],
    "carry_load": [("use", {}, "carry")],
}


def means_for_goal(goal, nearby_types):
    """Generic candidates 'use object X for goal G' from affordance tags. No scenario is scripted."""
    out = []
    for fn, args, tag in GOAL_RULES.get(goal, []):
        for t in nearby_types:
            if tag in AFFORD.get(t, []):
                out.append({"f": fn, "a": dict(args, block=t) if fn == "place" else dict(args, item=t), "via": tag})
    return out


# ------------------------------------------------------------ physical world
def reachable(grid, start, goal):
    """grid rows of chars; '#' and 'w' (water) block, anything else passes."""
    h, w = len(grid), len(grid[0])
    q, seen = deque([start]), {start}
    while q:
        x, y = q.popleft()
        if (x, y) == goal:
            return True
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and grid[ny][nx] not in "#w":
                seen.add((nx, ny))
                q.append((nx, ny))
    return False


# ---------------------------------------------------------- decision context
def suspicion(store, other):
    """Distrust of `other` that needs no explanation: refuted claims and conflicting versions it supplied."""
    refuted = sum(1 for e in store.events if e["type"] == "claim_refuted" and e["teller"] == other)
    lost = 0
    for m in store.mems.values():
        if m["told_by"] == other and m["event_ref"] and store.conflict_degree(m["event_ref"]) > 0 and m["certainty"] < .3:
            lost += 1
    return int(min(100, 35 * refuted + 12 * lost))


def decision_context(store, focus, entities, now, enemies=(), loved=(), k=8):
    """What the model receives about people and memories (the token fields), computed by the engine."""
    ctx = {"entities": {}, "memories": []}
    for e in entities:
        ctx["entities"][e] = {
            "rep_trust": store.reputation(e, "trust", now)["value"], "rep_danger": store.reputation(e, "danger", now)["value"],
            "suspicion": suspicion(store, e), "indirect_threat": store.indirect_threat(e, enemies, loved, now)}
    for m in store.recall(now, k=k, entities=[focus] + list(entities)):
        tok = store.to_token(m, now)
        tok["focus_knows"] = store.knows(focus, m["id"])
        tok["conflict"] = store.conflict_degree(m["event_ref"]) if m["event_ref"] else 0
        ctx["memories"].append(tok)
    return ctx
