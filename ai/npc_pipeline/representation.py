#!/usr/bin/env python3
"""representation.py - the THREE representations of a situation, and the registry that classifies every variable.

  1. CANONICAL   what the generator and the dataset store. Full resolution (-100..100, 0..100, 0..1, hours...).
                 Nothing is ever compressed here. This is the source of truth.
  2. TEACHER     what the labelling LLM reads: integers -10..+10 (bipolar) or 0..10 (unipolar), plus names and
                 context. Derived from CANONICAL by to10(); it can be richer than the model input, never poorer.
  3. MODEL       what the small network receives: the same integers as the TEACHER scale, divided by 10 by the
                 tensor encoder, categorical variables as embeddings, booleans as 0/1, quantities log-scaled.
                 The label was produced from the integer view, so feeding the same integers keeps input and label
                 consistent; the canonical values stay in the dataset in case a finer resolution is wanted later.

Classes of variable (every scalar the generator can emit must appear in REG; a test enforces it):
  B100/B1/B2   graded and BIPOLAR (negative and positive both meaningful)  -> integer -10..+10
  U100/U1      graded and UNIPOLAR (0 = absent, no negative meaning)       -> integer 0..10
  ORD          small ordinal integer, kept as is (0..4 understanding, 0..3 force)
  QLOG         real quantity with a wide range                              -> log-scaled 0..10 for the model
  BOOL, CAT, PTR  boolean, category, pointer to another token
Why unipolar variables are 0..10 and not -10..+10: hunger = -6 or fear = -3 has no meaning; spending half of the
scale on values that never occur wastes resolution and invites the teacher to invent a semantics.
"""
import math

REG = {}


def _reg(group, names, kind, vmax=None):
    for n in names.split():
        REG[(group, n)] = (kind, vmax)


TRAITS = "aggression courage empathy sociability honesty impulsivity curiosity tolerance justice ambition grudge"
_reg("self.trait", TRAITS, "B100")
_reg("self.temperament", "reactivity resilience", "U100")
_reg("self.value", "kin_protection property_respect honor life_value romantic_fidelity taboo_sensitivity", "U100")
_reg("self.drive", "libido social_need achievement hoarding", "U100")
_reg("self.state", "hunger thirst pain fear shock confusion", "U100")
_reg("self.state", "fatigue anger stress joy", "B100")
_reg("self.stock", "food fuel tools", "B100")
_reg("self.body", "hp strength job_skill", "U100")
_reg("self.body", "load_ratio", "U1")
_reg("self.activity", "progress", "U1")
_reg("self.wardrobe", "wear", "U100")          # 0.4: wear of the outfit ME has on
_reg("self.activity", "commitment", "U100")
_reg("self.activity", "secs_since_decision", "QLOG", 3600)
_reg("entity.rel", "affection trust respect romance debt", "B100")
_reg("entity.rel", "fear familiarity grudge", "U100")
_reg("entity.social", "mood_toward urge_to_interact", "B100")
_reg("entity.social", "suspicion indirect_threat", "U100")
_reg("entity.perception", "chemistry", "B1")
_reg("entity.perception", "perceived", "U1")
_reg("entity.perception", "distance", "QLOG", 30)
_reg("entity.perception", "beauty", "U100")
_reg("entity.perception", "days_since_contact", "QLOG", 60)
_reg("entity.perception", "rep_trust rep_danger", "B100")
_reg("entity.perception", "understanding", "ORD")
_reg("event", "intensity salience", "U100")
_reg("event", "understanding", "ORD")
_reg("event", "reliability intent", "U1")
_reg("event", "delay", "QLOG", 300)
_reg("event", "out_of_world", "BOOL")
_reg("event", "holders", "QLOG", 20)          # 0.4: other known holders of a skill (0 = ME is the last one)
_reg("event.norm", "kin property honor life fidelity truth fairness taboo", "U100")
_reg("memory", "importance severity", "U100")
_reg("memory", "certainty", "U1")
_reg("memory", "valence", "B100")
_reg("memory", "age_days", "QLOG", 365)
_reg("memory", "defining secret", "BOOL")
_reg("goal", "priority", "U100")
_reg("goal", "progress", "U1")
_reg("goal", "deadline_h", "QLOG", 168)
_reg("title", "authority", "U100")
_reg("title", "conf", "U1")
_reg("title", "legit", "B100")
_reg("inventory", "quality wear", "U100")
_reg("inventory", "qty", "QLOG", 20)
# --- village / society layer
_reg("village.personal", "belonging", "U100")
_reg("village.personal", "loyalty leader_trust leader_legit institution_trust", "B100")
_reg("village.collective", "rep economy food security", "B100")
_reg("village.collective", "tension cohesion", "U100")
_reg("village.norm", "kin property honor life fidelity truth fairness taboo", "U100")
_reg("village.problem", "urgency progress", "U100")
_reg("village.other", "relation", "B100")
_reg("village.other", "trade_dep threat my_ties", "U100")
_reg("household", "cohesion", "U100")
_reg("household", "wealth honor", "B100")
_reg("household", "size", "QLOG", 12)
_reg("household", "head", "BOOL")
_reg("group", "identification cohesion rank", "U100")


def rnd(x):
    """Round half away from zero (Python's round() is banker's rounding, which would make +2.5 and -2.5 asymmetric)."""
    return int(math.copysign(math.floor(abs(x) + .5), x))


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def to10(value, kind, vmax=None):
    """Canonical value -> integer on the teacher / model scale."""
    if kind == "B100":
        return clamp(rnd(value / 10.0), -10, 10)
    if kind == "U100":
        return clamp(rnd(value / 10.0), 0, 10)
    if kind == "U1":
        return clamp(rnd(value * 10.0), 0, 10)
    if kind == "B1":
        return clamp(rnd(value * 10.0), -10, 10)
    if kind == "ORD":
        return int(value)
    if kind == "QLOG":
        return clamp(rnd(10.0 * math.log1p(max(0.0, value)) / math.log1p(vmax)), 0, 10)
    if kind == "BOOL":
        return int(bool(value))
    raise ValueError(kind)


# a few variables are stored with a different native scale than their group default: handled explicitly
POLITENESS = ("event.frame", "politeness", "B2")


def _walk(d, group, out):
    for k, v in d.items():
        spec = REG.get((group, k))
        if spec is None:
            continue
        if isinstance(v, (int, float, bool)):
            out.append((group, k, v, spec[0], spec[1]))


def scalars_of(state):
    """Every registered scalar present in a state, as (group, name, canonical value, kind, vmax, owner)."""
    out = []

    def add(d, group, owner):
        tmp = []
        _walk(d, group, tmp)
        out.extend(t + (owner,) for t in tmp)
    me = state["me"]
    add(me.get("traits", {}), "self.trait", "me")
    add(me.get("temperament", {}), "self.temperament", "me")
    add(me.get("values", {}), "self.value", "me")
    add(me.get("drives", {}), "self.drive", "me")
    add(me.get("states", {}), "self.state", "me")
    add(me.get("stock_gap", {}), "self.stock", "me")
    add(me.get("body", {}), "self.body", "me")
    add(me.get("activity", {}), "self.activity", "me")
    for i in me.get("inventory", []):
        add(i, "inventory", "me")
    for e in state.get("entities", []):
        add(e.get("rel", {}), "entity.rel", e["id"])
        add(e, "entity.social", e["id"])
        add(e, "entity.perception", e["id"])
    for ev in state.get("events", []):
        add(ev, "event", ev["id"])
        add(ev.get("norm", {}), "event.norm", ev["id"])
    for m in state.get("memories", []):
        add(m, "memory", m["id"])
    for g in state.get("goals", []):
        add(g, "goal", "goal")
    for t in state.get("titles", []):
        add(t, "title", t["title"])
    v = state.get("village")
    if v:
        add(v, "village.personal", "village")
        add(v, "village.collective", "village")
        add(v.get("norms", {}), "village.norm", "village")
        add(v.get("problem", {}), "village.problem", "village")
        for o in v.get("others", []):
            add(o, "village.other", o["id"])
    if state.get("household"):
        add(state["household"], "household", "household")
    for g in state.get("groups", []):
        add(g, "group", g.get("kind", "group"))
    return out


def model_features(state):
    """Integer view used both by the teacher text and by the model: {owner: {group.name: int}}."""
    feats = {}
    for group, name, val, kind, vmax, owner in scalars_of(state):
        feats.setdefault(owner, {})[f"{group.split('.')[-1] if group.startswith('self.') else group}.{name}"] = to10(val, kind, vmax)
    for ev in state.get("events", []):
        fr = ev.get("frame") or {}
        if "politeness" in fr:
            feats.setdefault(ev["id"], {})["frame.politeness"] = clamp(rnd(fr["politeness"] * 5), -10, 10)
    return feats


# --------------------------------------------------------------------------- the classification table
CATEGORICAL = {
    "self": "age_cat love_status job current_action weather place_type tool_in_hand",
    "entity": "link age_cat love_status visible_action village",
    "event": "type role source speech_act style",
    "memory": "type source what broke outcome focus_knows",
    "goal": "type",
    "title": "title my_role",
    "village": "id frontier problem.kind problem.need other.id",
    "group": "kind",
}


def classification_rows():
    names = {"B100": "bipolar, -100..100", "B1": "bipolar, -1..1", "B2": "bipolar, -2..2", "U100": "unipolar, 0..100",
             "U1": "unipolar, 0..1", "ORD": "ordinal integer", "QLOG": "quantity (log scale)", "BOOL": "boolean"}
    out = []
    for (group, name), (kind, vmax) in REG.items():
        model = {"B100": "-10..+10", "B1": "-10..+10", "B2": "-10..+10", "U100": "0..10", "U1": "0..10", "ORD": "as is",
                 "QLOG": "0..10 (log)", "BOOL": "0/1"}[kind]
        out.append((group, name, names[kind], model))
    return out


ACTION_CLASS = {
    "aggress": "attack chase restrain expel destroy steal threaten blackmail",
    "avoid": "flee avoid hide return_home wander",
    "cooperate": "accept assist give follow accompany endorse heal comfort promise contribute supply teach vote",
    "resist": "refuse tear_down_notice break_commitment contest_claim leave_group",
    "confront": "accuse insult interrogate order summon decree enforce",
    "deceive": "deceive conceal bribe",
    "negotiate": "negotiate propose request lobby campaign hire post_job",
    "inform": "inform ask warn call_for_help post_notice publish answer read observe search investigate",
    "repair": "apologize forgive compliment thank embrace",
    "continue": "continue wait rest leisure",
}
CLASS_OF = {a: c for c, names in ACTION_CLASS.items() for a in names.split()}


def class_of(action):
    return CLASS_OF.get(action, "other")


if __name__ == "__main__":
    assert to10(25, "B100") == 3 and to10(-25, "B100") == -3 and to10(24, "B100") == 2 and to10(-24, "B100") == -2
    assert to10(0.95, "U1") == 10 and to10(-1, "B1") == -10 and to10(0, "QLOG", 100) == 0 and to10(100, "QLOG", 100) == 10
    print(f"{len(REG)} registered variables; round-trip checks passed")
