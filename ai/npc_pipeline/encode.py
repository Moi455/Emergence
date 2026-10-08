#!/usr/bin/env python3
"""encode.py - MODEL representation of a situation: a sequence of fixed-width tokens (format "tok-1").

This is the oracle of the C++ encoder: the engine must produce exactly these integers for the same canonical state.
No dependency (standard library only); numbers come from representation.to10, so the model reads the same integers
as the teacher text.

A token has two parts:
  cat[9]  int16  [type, c0, c1, c2, c3, c4, p0, p1, p2]
                 type   token type id (TOKEN_TYPES)
                 c0..c4 categorical ids in the shared vocabulary (0 = pad/absent, 1 = <unk>)
                 p0..p2 pointers: index of another token of the SAME sequence, -1 = none
  num[F]  int8   scalar slots, integers -10..+10 (bipolar) or 0..10 (unipolar, log quantities, booleans)
The meaning of every slot of every token type is in LAYOUT (exported to token_layout.json).

Order of a sequence: SELF, SELF_STATE, VILLAGE, OTHER_VILLAGE x4, HOUSEHOLD, ENTITY*, EVENT*, MEMORY*, GOAL*,
TITLE*, INV*, ITEM*, CAND* (the candidates always last; the model outputs one score per CAND token).

  python3 encode.py --build-vocab states.jsonl     # (re)build model_vocab.json from a corpus + the constants
  python3 encode.py --layout token_layout.json      # export the layout table
  python3 encode.py                                 # self-test
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys

import representation as rp

FORMAT = "tok-1"
F = 33                      # scalar slots per token
NCAT = 9                    # type + 5 categories + 3 pointers
MAX_TOKENS = 64
MAX_CANDS = 16
HERE = os.path.dirname(os.path.abspath(__file__))
VOCAB_FILE = os.path.join(HERE, "model_vocab.json")

TOKEN_TYPES = ["PAD", "SELF", "SELF_STATE", "VILLAGE", "OTHER_VILLAGE", "HOUSEHOLD", "ENTITY", "EVENT", "MEMORY", "GOAL",
               "TITLE", "INV", "ITEM", "CAND"]
TT = {n: i for i, n in enumerate(TOKEN_TYPES)}

TRAITS = ["aggression", "courage", "empathy", "sociability", "honesty", "impulsivity", "curiosity", "tolerance", "justice",
          "ambition", "grudge"]
VALUES = ["kin_protection", "property_respect", "honor", "life_value", "romantic_fidelity", "taboo_sensitivity"]
DRIVES = ["libido", "social_need", "achievement", "hoarding"]
STATES_U = ["hunger", "thirst", "pain", "fear", "shock", "confusion"]
STATES_S = ["fatigue", "anger", "stress", "joy"]
NORMS = ["kin", "property", "honor", "life", "fidelity", "truth", "fairness", "taboo"]
SEASONS = ["spring", "summer", "autumn", "winter"]
OUTFITS = ["everyday", "work", "festival", "cold", "night", "mourning"]

# (slot name, kind, vmax) per token type; categories and pointers listed separately
LAYOUT = {
    "SELF": {"cat": ["age_cat", "love_status", "job", "outfit_worn", "-"], "ptr": ["-", "-", "-"],
             "num": [(f"trait.{k}", "B100") for k in TRAITS] + [("temperament.reactivity", "U100"), ("temperament.resilience", "U100")]
             + [(f"value.{k}", "U100") for k in VALUES] + [(f"drive.{k}", "U100") for k in DRIVES] + [("age", "QLOG", 90)]
             + [(f"owns.{o}", "BOOL") for o in OUTFITS] + [("outfit.wear", "U100")]},
    "SELF_STATE": {"cat": ["current_action", "place_type", "weather", "tool_in_hand", "season"], "ptr": ["-", "-", "-"],
                   "num": [(f"state.{k}", "U100") for k in STATES_U] + [(f"state.{k}", "B100") for k in STATES_S]
                   + [("stock.food", "B100"), ("stock.fuel", "B100"), ("stock.tools", "B100"),
                      ("body.hp", "U100"), ("body.strength", "U100"), ("body.job_skill", "U100"), ("body.load_ratio", "U1"),
                      ("activity.progress", "U1"), ("activity.commitment", "U100"), ("activity.secs_since_decision", "QLOG", 3600),
                      ("time.hour_sin", "B1"), ("time.hour_cos", "B1"), ("time.season_sin", "B1"), ("time.season_cos", "B1"),
                      ("hours_since_meal", "QLOG", 24)]},
    "VILLAGE": {"cat": ["village_id", "frontier", "problem_kind", "problem_need", "-"], "ptr": ["-", "-", "-"],
                "num": [("belonging", "U100"), ("loyalty", "B100"), ("leader_trust", "B100"), ("leader_legit", "B100"),
                        ("institution_trust", "B100"), ("economy", "B100"), ("food", "B100"), ("security", "B100"), ("rep", "B100"),
                        ("tension", "U100"), ("cohesion", "U100")] + [(f"custom.{k}", "U100") for k in NORMS]
                + [("problem.urgency", "U100"), ("problem.progress", "U100")]},
    "OTHER_VILLAGE": {"cat": ["village_id", "-", "-", "-", "-"], "ptr": ["-", "-", "-"],
                      "num": [("relation", "B100"), ("trade_dep", "U100"), ("threat", "U100"), ("my_ties", "U100")]},
    "HOUSEHOLD": {"cat": ["-", "-", "-", "-", "-"], "ptr": ["-", "-", "-"],
                  "num": [("size", "QLOG", 12), ("head", "BOOL"), ("cohesion", "U100"), ("wealth", "B100"), ("honor", "B100")]},
    "ENTITY": {"cat": ["link", "age_cat", "love_status", "visible_action", "village"], "ptr": ["threat_via", "-", "-"],
               "num": [(f"rel.{k}", "B100") for k in ("affection", "trust", "respect", "romance", "debt")]
               + [(f"rel.{k}", "U100") for k in ("fear", "familiarity", "grudge")]
               + [("mood_toward", "B100"), ("urge_to_interact", "B100"), ("suspicion", "U100"), ("indirect_threat", "U100"),
                  ("perceived", "U1"), ("distance", "QLOG", 30), ("beauty", "U100"), ("days_since_contact", "QLOG", 60),
                  ("rep_trust", "B100"), ("rep_danger", "B100"), ("understanding", "ORD"), ("age", "QLOG", 90)]
               + [(f"wears.{o}", "BOOL") for o in OUTFITS]},
    "EVENT": {"cat": ["type", "role", "source", "content_a", "content_b"], "ptr": ["agent", "target", "subject"],
              "num": [("intensity", "U100"), ("salience", "U100"), ("understanding", "ORD"), ("reliability", "U1"), ("intent", "U1"),
                      ("delay", "QLOG", 300), ("out_of_world", "BOOL"), ("has_intent", "BOOL")]
              + [(f"norm.{k}", "U100") for k in NORMS]
              + [("holders", "QLOG", 20), ("offer.gain", "B100"), ("offer.price", "QLOG", 200), ("offer.qty", "QLOG", 20),
                 ("offer.round", "ORD"), ("question.sens", "U100"), ("style.order", "BOOL")]},
    "MEMORY": {"cat": ["type", "source", "what", "broke", "outcome"], "ptr": ["agent", "target", "third"],
               "num": [("valence", "B100"), ("importance", "U100"), ("severity", "U100"), ("certainty", "U1"), ("age_days", "QLOG", 365),
                       ("defining", "BOOL"), ("secret", "BOOL"), ("focus_knows_yes", "BOOL"), ("focus_knows_no", "BOOL")]},
    "GOAL": {"cat": ["type", "target", "-", "-", "-"], "ptr": ["target", "partner", "-"],
             "num": [("priority", "U100"), ("progress", "U1"), ("deadline_h", "QLOG", 168)]},
    "TITLE": {"cat": ["title", "my_role", "-", "-", "-"], "ptr": ["holder", "claimant1", "claimant2"],
              "num": [("authority", "U100"), ("conf", "U1"), ("legit", "B100"), ("n_claimants", "ORD")]},
    "INV": {"cat": ["item", "-", "-", "-", "-"], "ptr": ["-", "-", "-"],
            "num": [("qty", "QLOG", 20), ("quality", "U100"), ("wear", "U100"), ("in_hand", "BOOL")]},
    "ITEM": {"cat": ["item", "owner_kind", "-", "-", "-"], "ptr": ["owner", "-", "-"], "num": [("qty", "QLOG", 20)]},
    "CAND": {"cat": ["action", "arg1", "arg2", "arg3", "arg4"], "ptr": ["entity", "event", "memory_or_option"], "num": []},
}
for _t, _l in LAYOUT.items():
    assert len(_l["num"]) <= F, (_t, len(_l["num"]))

ID_RE = re.compile(r"\b([EVM])\d+\b")


def q(value, kind, vmax=None):
    return rp.to10(value, kind, vmax)


def norm_text(s):
    """'E2:theft' -> 'E:theft', 'counter:V1' -> 'counter:V'; ids become pointers, never vocabulary."""
    return ID_RE.sub(lambda m: m.group(1), str(s))


# ------------------------------------------------------------------------------------------------ vocabulary
class Vocab:
    def __init__(self, table=None):
        self.table = table or {"<pad>": 0, "<unk>": 1}
        self.frozen = table is not None

    def id(self, ns, value):
        if value is None or value == "" or value == "-":
            return 0
        key = f"{ns}:{value}"
        i = self.table.get(key)
        if i is None:
            if self.frozen:
                return 1
            i = self.table[key] = len(self.table)
        return i

    def save(self, path):
        h = hashlib.sha256(json.dumps(self.table, sort_keys=True).encode()).hexdigest()[:16]
        json.dump({"format": FORMAT, "hash": h, "size": len(self.table), "table": self.table}, open(path, "w"), indent=0, sort_keys=True)
        return h

    @staticmethod
    def load(path=VOCAB_FILE):
        d = json.load(open(path))
        v = Vocab(d["table"])
        v.hash = d["hash"]
        return v


# ------------------------------------------------------------------------------------------------ encoder
class Seq:
    def __init__(self, vocab):
        self.v = vocab
        self.cat, self.num = [], []

    def add(self, ttype, cats=(), ptrs=(), nums=()):
        cats = list(cats) + [0] * (5 - len(cats))
        ptrs = list(ptrs) + [-1] * (3 - len(ptrs))
        nums = list(nums) + [0] * (F - len(nums))
        assert len(cats) == 5 and len(ptrs) == 3 and len(nums) == F
        for x in nums:
            assert -10 <= x <= 10, (ttype, nums)
        self.cat.append([TT[ttype]] + cats + ptrs)
        self.num.append(nums)
        return len(self.cat) - 1


def encode(rec, vocab):
    """-> dict(cat=[[9]...], num=[[F]...], cand_first=int, n_cands=int). Raises if the sequence is too long."""
    st = rec["state"]
    me = st["me"]
    V = vocab
    s = Seq(V)
    lay = LAYOUT
    ptr = {"me": 0}

    def nums_of(tt, d):
        out = []
        for spec in lay[tt]["num"]:
            name, kind = spec[0], spec[1]
            vmax = spec[2] if len(spec) > 2 else None
            x = d.get(name, 0)
            out.append(q(x if x is not None else 0, kind, vmax))
        return out

    # SELF
    d = {f"trait.{k}": me["traits"].get(k, 0) for k in TRAITS}
    d.update({f"temperament.{k}": me["temperament"][k] for k in me["temperament"]})
    d.update({f"value.{k}": me["values"][k] for k in VALUES})
    d.update({f"drive.{k}": me["drives"][k] for k in DRIVES})
    d["age"] = me["age"]
    wd = me.get("wardrobe") or {"has": [], "worn": None, "wear": 0}
    d.update({f"owns.{o}": o in wd["has"] for o in OUTFITS})
    d["outfit.wear"] = wd["wear"]
    s.add("SELF", [V.id("age_cat", me["age_cat"]), V.id("love", me["love_status"]), V.id("job", me["job"]), V.id("outfit", wd["worn"])],
          [], nums_of("SELF", d))
    # SELF_STATE
    d = {f"state.{k}": me["states"][k] for k in STATES_U + STATES_S}
    d.update({f"stock.{k}": me["stock_gap"][k] for k in ("food", "fuel", "tools")})
    d.update({f"body.{k}": me["body"][k] for k in ("hp", "strength", "job_skill", "load_ratio")})
    d.update({f"activity.{k}": me["activity"][k] for k in ("progress", "commitment", "secs_since_decision")})
    hang = 2 * math.pi * me["hour"] / 24
    sang = 2 * math.pi * SEASONS.index(me["season"]) / 4
    d.update({"time.hour_sin": math.sin(hang), "time.hour_cos": math.cos(hang), "time.season_sin": math.sin(sang),
              "time.season_cos": math.cos(sang), "hours_since_meal": me.get("hours_since_meal", 0)})
    s.add("SELF_STATE", [V.id("action", me["current_action"]), V.id("place", me["place_type"]), V.id("weather", me["weather"]),
                         V.id("item", me.get("tool_in_hand", "hands")), V.id("season", me["season"])], [], nums_of("SELF_STATE", d))
    # VILLAGE, OTHER_VILLAGE, HOUSEHOLD
    vil = st.get("village")
    if vil:
        d = {k: vil[k] for k in ("belonging", "loyalty", "leader_trust", "leader_legit", "institution_trust", "economy", "food",
                                 "security", "rep", "tension", "cohesion")}
        d.update({f"custom.{k}": vil["norms"][k] for k in NORMS})
        d["problem.urgency"], d["problem.progress"] = vil["problem"]["urgency"], vil["problem"]["progress"]
        s.add("VILLAGE", [V.id("village", vil["id"]), V.id("frontier", vil["frontier"]), V.id("problem", vil["problem"]["kind"]),
                          V.id("need", vil["problem"]["need"])], [], nums_of("VILLAGE", d))
        for o in vil["others"]:
            s.add("OTHER_VILLAGE", [V.id("village", o["id"])], [], nums_of("OTHER_VILLAGE", o))
    hh = st.get("household")
    if hh:
        s.add("HOUSEHOLD", [], [], nums_of("HOUSEHOLD", hh))
    # ENTITY (pointer to threat_via filled after all entities exist)
    ents = st["entities"]
    for e in ents:
        d = {f"rel.{k}": v for k, v in e["rel"].items()}
        d.update({k: e.get(k, 0) for k in ("mood_toward", "urge_to_interact", "suspicion", "indirect_threat", "perceived", "distance",
                                           "beauty", "days_since_contact", "rep_trust", "rep_danger", "understanding", "age")})
        d.update({f"wears.{o}": e.get("worn") == o for o in OUTFITS})
        vv = e.get("village")
        vcat = "same" if (vil is None or vv in (None, vil["id"])) else vv
        ptr[e["id"]] = s.add("ENTITY", [V.id("link", e["link"]), V.id("age_cat", e["age_cat"]), V.id("love", e["love_status"]),
                                        V.id("action", e["visible_action"]), V.id("village", vcat)], [], nums_of("ENTITY", d))
    for e in ents:
        if e.get("threat_via") in ptr:
            s.cat[ptr[e["id"]]][6] = ptr[e["threat_via"]]
    # EVENT
    for ev in st["events"]:
        c = ev["content"] or {}
        d = {k: ev.get(k, 0) for k in ("intensity", "salience", "understanding", "reliability", "delay")}
        d["out_of_world"] = ev["out_of_world"]
        d["intent"], d["has_intent"] = ev.get("intent", 0), "intent" in ev
        d.update({f"norm.{k}": ev["norm"][k] for k in NORMS})
        d["holders"] = ev.get("holders", 0)
        if ev["type"] == "offer":
            d.update({"offer.gain": c.get("gain", 0), "offer.price": c.get("price", 0), "offer.qty": c.get("qty", 0),
                      "offer.round": min(10, c.get("round", 0))})
        if ev["type"] == "question":
            d["question.sens"] = c.get("sens", 0)
        d["style.order"] = c.get("style") == "order"
        ca = c.get("kind") or c.get("attr") or c.get("claim") or c.get("topic", "").split(":")[0] or c.get("unknown_concept") \
            or c.get("question") or c.get("item") or c.get("place") or ""
        cb = c.get("act") or c.get("step") or c.get("activity") or c.get("good") or c.get("pressure") or c.get("title") \
            or c.get("dest") or c.get("skill") or c.get("item") or c.get("ask") or c.get("service") or c.get("rule") or ""
        if ev["type"] == "offer":
            ca = "offer_" + c.get("side", "")
        subj = c.get("victim") or c.get("subject") or c.get("about") or c.get("for") or (c.get("topic", "").split(":")[-1] if ":" in c.get("topic", "") else None)
        ptr[ev["id"]] = s.add("EVENT", [V.id("event", ev["type"]), V.id("role", ev["role"]), V.id("source", ev["source"]),
                                        V.id("content", norm_text(ca)), V.id("content", norm_text(cb))],
                              [ptr.get(ev["agent"], -1), ptr.get(ev["target"], -1), ptr.get(subj, -1)], nums_of("EVENT", d))
    # MEMORY
    for m in st["memories"]:
        d = {k: m.get(k, 0) for k in ("valence", "importance", "severity", "certainty", "age_days")}
        d.update({"defining": m.get("defining"), "secret": m.get("secret"), "focus_knows_yes": m.get("focus_knows") == "yes",
                  "focus_knows_no": m.get("focus_knows") == "no"})
        ptr[m["id"]] = s.add("MEMORY", [V.id("memory", m["type"]), V.id("source", m["source"]), V.id("item", m.get("what")),
                                        V.id("norm", m.get("broke")), V.id("outcome", m.get("outcome"))],
                             [ptr.get(m["agent"], -1), ptr.get(m["target"], -1), ptr.get(m.get("third"), -1)], nums_of("MEMORY", m | d))
    # GOAL
    for g in st["goals"]:
        tgt = g["target"]
        s.add("GOAL", [V.id("goal", g["type"]), V.id("goal_target", None if tgt in ptr else tgt)],
              [ptr.get(tgt, -1), ptr.get(g.get("partner"), -1)], nums_of("GOAL", g))
    # TITLE
    for t in st.get("titles", []):
        cl = t["claimants"] + [None, None]
        d = {"authority": t["authority"], "conf": t["conf"], "legit": t["legit"], "n_claimants": min(10, len(t["claimants"]))}
        s.add("TITLE", [V.id("title", t["title"]), V.id("role", t["my_role"])],
              [ptr.get(t["holder"], -1), ptr.get(cl[0], -1), ptr.get(cl[1], -1)], nums_of("TITLE", d))
    # INV
    for it in me.get("inventory", [])[:8]:
        d = dict(it)
        d["in_hand"] = it["type"] == me.get("tool_in_hand")
        s.add("INV", [V.id("item", it["type"])], [], nums_of("INV", d))
    # ITEM (on the ground / nearby)
    for it in st.get("items", []):
        ok = "entity" if it["owner"] in ptr and it["owner"] != "me" else it["owner"]
        s.add("ITEM", [V.id("item", it["type"]), V.id("owner", ok)], [ptr.get(it["owner"], -1) if it["owner"] != "none" else -1],
              nums_of("ITEM", it))
    # CAND
    first = len(s.cat)
    for c in rec["cands"]:
        a, args = c["a"], c["args"]
        cats = [V.id("fn", a)]
        p_ent = p_ev = p_x = -1
        for k, x in args.items():
            if x is None:
                continue
            xs = str(x)
            if k == "e":
                p_ent = ptr.get(xs, -1) if xs != "self" else 0
                if xs in ("self", "all"):
                    cats.append(V.id("arg", f"e={xs}"))
                continue
            if k in ("p", "q", "site", "poll", "doc") and xs in ptr:
                p_ev = ptr[xs]
                continue
            if k == "mem" and xs in ptr:
                p_x = ptr[xs]
                continue
            if k == "option":
                if xs in ptr:
                    p_x = ptr[xs]
                else:
                    cats.append(V.id("arg", f"option={xs}"))
                continue
            if k in ("p", "f", "content", "topic") and ID_RE.search(xs):     # fact or proposal naming people/events
                ids = ID_RE.findall(xs)
                m_ = re.search(r"\b[EVM]\d+\b", xs)
                if m_ and m_.group(0) in ptr:
                    if m_.group(0).startswith("V") and p_ev < 0:
                        p_ev = ptr[m_.group(0)]
                    elif p_x < 0:
                        p_x = ptr[m_.group(0)]
            if len(cats) < 5:
                cats.append(V.id("arg", f"{k}={norm_text(xs)}"))
        if p_ent < 0 and p_ev >= 0 and s.cat[p_ev][6] >= 0:
            p_ent = s.cat[p_ev][6]          # "accept V1" also points at the person who proposed V1 (one hop, not two)
        s.add("CAND", cats[:5], [p_ent, p_ev, p_x], [])
    n_c = len(rec["cands"])
    if len(s.cat) > MAX_TOKENS or n_c > MAX_CANDS:
        raise ValueError(f"sequence too long: {len(s.cat)} tokens, {n_c} candidates")
    return {"cat": s.cat, "num": s.num, "cand_first": first, "n_cands": n_c}


def layout_table():
    out = {"format": FORMAT, "F": F, "NCAT": NCAT, "max_tokens": MAX_TOKENS, "max_cands": MAX_CANDS,
           "token_types": TOKEN_TYPES, "cat_fields": ["type", "c0", "c1", "c2", "c3", "c4", "p0", "p1", "p2"], "types": {}}
    for t, l in LAYOUT.items():
        out["types"][t] = {"cat": l["cat"], "ptr": l["ptr"],
                           "num": [{"slot": i, "name": s_[0], "kind": s_[1], **({"vmax": s_[2]} if len(s_) > 2 else {})}
                                   for i, s_ in enumerate(l["num"])]}
    return out


def build_vocab(paths):
    """Vocabulary = every categorical value of the constants + every value seen in the given corpora, ids by sorted key."""
    import generate_states as gs
    v = Vocab()
    for a in gs.ACTION_IDS:
        v.id("fn", a)
        v.id("action", a)
    for path in paths:
        for line in open(path, encoding="utf-8"):
            encode(json.loads(line), v)
    keys = sorted(k for k in v.table if k not in ("<pad>", "<unk>"))
    table = {"<pad>": 0, "<unk>": 1}
    for k in keys:
        table[k] = len(table)
    return Vocab(table)


def _selftest():
    import random
    import generate_states as gs
    rng = random.Random(3)
    recs = [gs.gen_situation(rng, i, rng.choice(list(gs.FAMILIES)), 99, 4, 2, False) for i in range(400)]
    v = Vocab()
    lens, unk = [], 0
    for r in recs:
        e = encode(r, v)
        lens.append(len(e["cat"]))
        assert e["cand_first"] + e["n_cands"] == len(e["cat"])
        for row in e["cat"]:
            for p in row[6:]:
                assert -1 <= p < len(e["cat"])
    # determinism
    e1 = encode(recs[0], v)
    e2 = encode(json.loads(json.dumps(recs[0])), v)
    assert e1 == e2
    if os.path.exists(VOCAB_FILE):
        fv = Vocab.load()
        for r in recs:
            e = encode(r, fv)
            unk += sum(1 for row in e["cat"] for x in row[1:6] if x == 1)
    print(f"encode {FORMAT}: 400 situations, tokens mean {sum(lens) / len(lens):.1f} max {max(lens)} (limit {MAX_TOKENS}); "
          f"pointers valid; deterministic; <unk> with frozen vocab: {unk}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-vocab", nargs="*")
    ap.add_argument("--layout", default="")
    a = ap.parse_args()
    if a.build_vocab:
        v = build_vocab(a.build_vocab)
        h = v.save(VOCAB_FILE)
        print(f"vocabulary: {len(v.table)} entries, hash {h} -> {VOCAB_FILE}")
        return
    if a.layout:
        json.dump(layout_table(), open(a.layout, "w"), indent=1)
        print("layout ->", a.layout)
        return
    _selftest()


if __name__ == "__main__":
    main()
