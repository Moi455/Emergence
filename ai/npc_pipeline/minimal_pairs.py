#!/usr/bin/env python3
"""minimal_pairs.py - sensitivity pairs with an EXPECTED DIRECTION (point 9 of the devs' revision).

Each probe takes a generated situation, sets ONE variable to a low and to a high value, keeps everything else
(same candidates, same order) and states which way the probability of some options must move. The directions are
written by hand from common sense about people, NOT read from the reference decider, so the same file tests:
  * the reference decider (sanity: it should pass most probes),
  * the student (roadmap S7: "the student beats the reference on minimal pairs"),
  * the teacher (pilot S3: does Gemini react to a one-variable change? the 'noise' probe = same situation twice).

  python3 minimal_pairs.py --per-probe 60 --out pairs.jsonl     # writes the pairs and prints the reference's pass rates
  python3 minimal_pairs.py                                      # self-test (small)
"""
import argparse
import copy
import json
import math
import random
import sys
from collections import defaultdict

import generate_states as gs
import reference_decider as rd


def ent(st, eid):
    return next((e for e in st["entities"] if e["id"] == eid), None)


def agent_of(st, etype=None):
    ev = next((e for e in st["events"] if (etype is None or e["type"] == etype) and e["agent"]), None)
    return ent(st, ev["agent"]) if ev else None


def set_me(path, lo, hi):
    def f(st, high):
        d = st["me"]
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = hi if high else lo
        return True
    return f


def set_agent_rel(key, lo, hi, etype=None):
    def f(st, high):
        a = agent_of(st, etype)
        if a is None:
            return False
        a["rel"][key] = hi if high else lo
        return True
    return f


def set_village(key, lo, hi):
    def f(st, high):
        if not st.get("village"):
            return False
        st["village"][key] = hi if high else lo
        return True
    return f


def set_event(key, lo, hi, content=False):
    def f(st, high):
        if not st["events"]:
            return False
        d = st["events"][0]["content"] if content else st["events"][0]
        if key not in d and not content and key != "holders":
            return False
        d[key] = hi if high else lo
        return True
    return f


def opt(*acts, arg=None):
    def f(c, st):
        if c["a"] not in acts:
            return False
        return arg is None or arg(c, st)
    return f


def targets_agent(c, st):
    ev = next((e for e in st["events"] if e["agent"]), None)
    return ev is not None and c["args"].get("e") == ev["agent"]


def not_partner(c, st):
    e = ent(st, c["args"].get("e"))
    return e is not None and e["link"] not in ("spouse", "partner")


def accept_first(c, st):
    return st["events"] and c["args"].get("p") == st["events"][0]["id"]


def no_romance_kind(st):
    return st["events"] and (st["events"][0]["content"] or {}).get("kind") not in ("romance", "harm")


# name: (families, mutation, option selector, expected sign of change high-vs-low, precondition on the base state)
PROBES = {
    "aggression_retaliation": (["provocation"], set_me(["traits", "aggression"], -70, 70), opt("insult", "attack", "threaten"), +1, None),
    "empathy_helps_victim": (["wrongdoing_witnessed", "danger"], set_me(["traits", "empathy"], -70, 70), opt("assist", "comfort"), +1, None),
    "hunger_eats": (["urgent_need", "routine"], set_me(["states", "hunger"], 10, 90), opt("eat", arg=None), +1, None),
    "fatigue_rests": (["routine", "greeting"], set_me(["states", "fatigue"], -40, 85), opt("rest", "sleep"), +1, None),
    "courage_stays": (["danger"], set_me(["traits", "courage"], -70, 70), opt("flee"), -1, None),
    "trust_accepts": (["proposal", "request"], set_agent_rel("trust", -35, 60), opt("accept", arg=accept_first), +1, no_romance_kind),
    "grudge_refuses": (["proposal", "request"], set_agent_rel("grudge", 0, 50), opt("accept", arg=accept_first), -1, no_romance_kind),
    "taboo_rejects_kin_advance": (["kin_advance"], set_me(["values", "taboo_sensitivity"], 10, 95), opt("accept", "kiss", "flirt", "be_intimate"), -1, None),
    "fidelity_resists_flirt": (["romance"], set_me(["values", "romantic_fidelity"], 10, 95), opt("flirt", "kiss", "be_intimate", arg=not_partner), -1,
                               lambda st: st["me"]["love_status"] in ("married", "partnered")),
    "honesty_does_not_lie": (["info_request"], set_me(["traits", "honesty"], -70, 70), opt("answer", arg=lambda c, st: c["args"].get("m") == "lie"), -1, None),
    "life_value_refuses_harm": (["harmful_proposal"], set_me(["values", "life_value"], 10, 95), opt("accept", arg=accept_first), -1, None),
    "loyalty_contributes": (["village_problem"], set_village("loyalty", -70, 70), opt("contribute", "supply"), +1, None),
    "hoarding_hoards": (["village_problem"], set_me(["drives", "hoarding"], 5, 95), opt("store"), +1, None),
    "commitment_continues": (["routine"], set_me(["activity", "commitment"], 5, 95), opt("continue", "wait"), +1, None),
    "curiosity_goes_beyond": (["frontier"], set_me(["traits", "curiosity"], -70, 70), opt("accept", "accompany", "propose", "ask"), +1, None),
    "last_holder_teaches": (["apprenticeship"], set_event("holders", 8, 0), opt("teach", "accept", arg=lambda c, st: c["a"] == "teach" or accept_first(c, st)), +1,
                            lambda st: any((e["content"] or {}).get("kind") == "teach" for e in st["events"])),
    "gain_accepts_offer": (["negotiation", "intervillage_trade"], set_event("gain", -70, 70, content=True), opt("accept", arg=accept_first), +1, None),
    "tolerance_trades_with_foreigner": (["intervillage_trade"], set_me(["traits", "tolerance"], -70, 70), opt("accept", arg=accept_first), +1,
                                        lambda st: (agent_of(st) or {}).get("village") not in (None, st["village"]["id"])),
    "justice_accuses": (["wrongdoing_witnessed", "betrayal"], set_me(["traits", "justice"], -70, 70), opt("accuse", "chase"), +1, None),
    "ambition_claims_title": (["title_dispute", "village_problem"], set_me(["traits", "ambition"], -70, 70), opt("claim_title"), +1, None),
    "debt_owed_helps": (["request"], set_agent_rel("debt", 60, -60), opt("accept", arg=accept_first), +1, no_romance_kind),
    "fear_of_interrogator_talks": (["extortion"], set_agent_rel("fear", 0, 50), opt("inform", arg=lambda c, st: "mem" in c["args"]), +1, None),
    "festival_dresses_up": (["festival"], set_me(["traits", "sociability"], -70, 70), opt("dress", "leisure", "go_to",
                            arg=lambda c, st: c["a"] != "go_to" or c["args"].get("l") == "square"), +1, None),
    "cold_weather_dresses_warm": (["routine", "greeting", "proposal"], set_me(["weather"], "clear", "snow"),
                                  opt("dress", arg=lambda c, st: c["args"].get("outfit") == "cold"), +1, None),
    "noise_witness": (["proposal", "routine", "provocation", "village_problem"], lambda st, high: True, opt("continue", "wait"), 0, None),
}


def refresh(rec):
    rec["view"] = gs.view_of_state(rec["state"], rec["cands"])
    rec["text"] = gs.view_text(rec["view"])
    return rec


def make_pairs(per_probe, seed=1):
    rng = random.Random(seed)
    out = []
    for name, (fams, mut, sel, sign, pre) in PROBES.items():
        got, tries = 0, 0
        while got < per_probe and tries < per_probe * 60:
            tries += 1
            fam = rng.choice(fams)
            base = gs.gen_situation(rng, tries, fam, 4242, 4, 1, False)
            if base["family"] != fam or gs.validate(base):
                continue
            if pre and not pre(base["state"]):
                continue
            idx = [c["i"] for c in base["cands"] if sel(c, base["state"])]
            if not idx:
                continue
            pair = []
            for high in (False, True):
                r = copy.deepcopy(base)
                if not mut(r["state"], high):
                    break
                refresh(r)
                if gs.validate(r):
                    break
                pid = f"p{len(out) // 2 + 1:06d}"
                r["id"] = f"{pid}{'h' if high else 'l'}"
                r["pair"] = {"pair_id": pid, "probe": name, "variant": "high" if high else "low", "options": idx, "sign": sign}
                pair.append(r)
            if len(pair) == 2:
                out += pair
                got += 1
    return out


def prob_of(probs, idx):
    return sum(probs[i] for i in idx)


def score_pairs(recs, probs_fn, margin=0.0):
    """probs_fn(rec) -> list of probabilities over rec['cands']. Returns {probe: (passed, total)}; for sign 0 the
    probe passes when the change is below 0.02 (a deterministic decider always passes it)."""
    by = defaultdict(dict)
    for r in recs:
        by[r["pair"]["pair_id"]][r["pair"]["variant"]] = r
    res = defaultdict(lambda: [0, 0])
    for pid, d in by.items():
        lo, hi = d["low"], d["high"]
        info = lo["pair"]
        dp = prob_of(probs_fn(hi), info["options"]) - prob_of(probs_fn(lo), info["options"])
        ok = abs(dp) < .02 if info["sign"] == 0 else dp * info["sign"] > margin
        res[info["probe"]][0] += int(ok)
        res[info["probe"]][1] += 1
    return dict(res)


def ref_probs(rec):
    return rd.decide(rec)["soft"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-probe", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    n = a.per_probe or 15
    recs = make_pairs(n, a.seed)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
    res = score_pairs(recs, ref_probs)
    tot = [sum(v[0] for v in res.values()), sum(v[1] for v in res.values())]
    print(f"{len(recs) // 2} pairs over {len(PROBES)} probes" + (f" -> {a.out}" if a.out else ""))
    for k in PROBES:
        if k in res:
            p, t = res[k]
            print(f"  {k:34s} reference {p:3d}/{t:<3d} {100 * p / t:5.1f} %")
        else:
            print(f"  {k:34s} (no pair could be built)")
    print(f"reference overall {tot[0]}/{tot[1]} = {100 * tot[0] / max(1, tot[1]):.1f} %")


if __name__ == "__main__":
    main()
