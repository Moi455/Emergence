#!/usr/bin/env python3
"""corpus_report.py - statistical audit of a corpus of situations (and of its labels when they exist).

  python3 corpus_report.py --states data/states.jsonl                 # generator-side audit (no API needed)
  python3 corpus_report.py --states data/states.jsonl --labels data/labels.jsonl   # + teacher-side audit

Generator-side: families, entities/events/memories per situation, trait and value distributions on the -10..+10
scale, range usage per variable, frequency of every action among the candidates, response-class coverage per family
(does each situation offer an aggressive, an avoidant, a cooperative, a deceptive ... way out?), relation coverage and
contradictions, village/society coverage, multi-level situations, duplicates and near-duplicates, generation biases.
Teacher-side (needs labels): alt_rate global and per family, actions the teacher keeps asking for, ambiguity rate,
actions never or always rated best.
"""
import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import representation as rp  # noqa: E402

KIN = {"child", "parent", "sibling", "spouse"}
VILLAGE_EVENTS = {"village_alert", "leader_decree", "council_call", "collective_request", "border_incident"}
INSTITUTION_EVENTS = {"institution_accusation", "inquiry", "poll_open", "notice_seen", "claim_title", "interrogate"}


def mean(x):
    return sum(x) / len(x) if x else 0.0


def sd(x):
    if len(x) < 2:
        return 0.0
    m = mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def levels_of(st):
    """Which levels of society a situation touches (individual, family, group, village, institution, inter_village)."""
    lv = set()
    ents = {e["id"]: e for e in st.get("entities", [])}
    for ev in st.get("events", []):
        t = ev["type"]
        who = [ents.get(ev.get("agent")), ents.get(ev.get("target"))]
        victim = ents.get((ev.get("content") or {}).get("victim") or (ev.get("content") or {}).get("accused"))
        if any(w for w in who + [victim] if w):
            lv.add("individual")
        if any(w and w["link"] in KIN for w in who + [victim]):
            lv.add("family")
        if t in VILLAGE_EVENTS:
            lv.add("village")
        if t in INSTITUTION_EVENTS or (ev.get("content") or {}).get("by") in ("council", "guard", "court"):
            lv.add("institution")
        if t == "border_incident":
            lv.add("inter_village")
        home = (st.get("village") or {}).get("id")
        if home and any(w and w.get("village") not in (None, home) for w in who):          # 0.4: a person from another village
            lv.add("inter_village")
        if t in ("poll_open", "claim_title", "notice_seen") and st.get("groups"):
            lv.add("group")
    v = st.get("village")
    if v and v.get("problem", {}).get("kind", "none") != "none" and ("village" in lv or "institution" in lv):
        lv.add("village")
    if st.get("groups") and any(g.get("identification", 0) >= 60 for g in st["groups"]) and len(lv) >= 1:
        lv.add("group")
    return lv


def skeleton(rec):
    st = rec["state"]
    return (rec["family"], tuple(sorted({c["a"] for c in rec["cands"]})), tuple(sorted(e["type"] for e in st["events"])),
            tuple(sorted(e["link"] for e in st["entities"])))


def jaccard(a, b):
    return len(a & b) / max(1, len(a | b))


def report(states, labels, out_json=None):
    n = len(states)
    R = {"n": n}
    lines = []
    P = lines.append
    P(f"# Corpus report: {n} situations\n")
    # ---------------- composition
    fam = Counter(s["family"] for s in states)
    R["families"] = dict(fam)
    P("## 1. Families\n")
    P("| family | n | % |\n|---|---|---|")
    for k, v in sorted(fam.items(), key=lambda kv: -kv[1]):
        P(f"| {k} | {v} | {100 * v / n:.1f} |")
    cnt = defaultdict(list)
    for s in states:
        st = s["state"]
        cnt["entities"].append(len(st["entities"]))
        cnt["events"].append(len(st["events"]))
        cnt["memories"].append(len(st["memories"]))
        cnt["goals"].append(len(st["goals"]))
        cnt["candidates"].append(len(s["cands"]))
        cnt["titles"].append(len(st.get("titles", [])))
    P("\n## 2. Size of a situation\n")
    P("| quantity | mean | min | max |\n|---|---|---|---|")
    for k, v in cnt.items():
        P(f"| {k} | {mean(v):.2f} | {min(v)} | {max(v)} |")
    R["sizes"] = {k: round(mean(v), 2) for k, v in cnt.items()}
    # ---------------- scalar distributions on the model scale
    vals = defaultdict(list)
    kinds = {}
    for s in states:
        for group, name, v, kind, vmax, owner in rp.scalars_of(s["state"]):
            if kind in ("BOOL", "ORD"):
                continue
            key = f"{group}.{name}"
            vals[key].append(rp.to10(v, kind, vmax))
            kinds[key] = kind
    P("\n## 3. Variables on the model scale (integers)\n")
    P("`used` = how many of the possible integer values (21 for bipolar, 11 for unipolar) appear in at least 0.5% of the observations; "
      "`extreme` = share of |value| >= 7 (bipolar) or >= 8 (unipolar); `zero` = share exactly at 0.\n")
    P("| variable | n | mean | sd | used | extreme % | zero % |\n|---|---|---|---|---|---|---|")
    for key in sorted(vals):
        v = vals[key]
        bip = kinds[key] in ("B100", "B1", "B2")
        c = Counter(v)
        used = sum(1 for x, k in c.items() if k / len(v) >= .005)
        ext = sum(1 for x in v if (abs(x) >= 7 if bip else x >= 8)) / len(v)
        P(f"| {key} | {len(v)} | {mean(v):+.1f} | {sd(v):.1f} | {used}/{21 if bip else 11} | {100 * ext:.0f} | {100 * c.get(0, 0) / len(v):.0f} |")
    R["scalar_stats"] = {k: {"n": len(v), "mean": round(mean(v), 2), "sd": round(sd(v), 2)} for k, v in vals.items()}
    P("\n### Trait histograms (value -10..+10, counts per 10)\n")
    P("```")
    for key in sorted(k for k in vals if k.startswith("self.trait")):
        c = Counter(vals[key])
        P(f"{key.split('.')[-1]:12s} " + " ".join(f"{c.get(x, 0):3d}" for x in range(-10, 11, 1)))
    P("             " + " ".join(f"{x:3d}" for x in range(-10, 11)))
    P("```")
    # ---------------- actions among candidates
    act = Counter()
    by_fam_act = defaultdict(Counter)
    for s in states:
        for c in s["cands"]:
            act[c["a"]] += 1
            by_fam_act[s["family"]][c["a"]] += 1
    tot = sum(act.values())
    P("\n## 4. Actions among the candidates (what the teacher can choose from)\n")
    P(f"{len(act)} distinct actions offered; {tot} candidate slots. Most frequent and rarest:\n")
    P("| action | slots | % of slots | in % of situations |\n|---|---|---|---|")
    in_sit = Counter()
    for s in states:
        for a in {c['a'] for c in s['cands']}:
            in_sit[a] += 1
    for a, v in act.most_common(15):
        P(f"| {a} | {v} | {100 * v / tot:.1f} | {100 * in_sit[a] / n:.0f} |")
    P("| ... | | | |")
    for a, v in act.most_common()[-8:]:
        P(f"| {a} | {v} | {100 * v / tot:.2f} | {100 * in_sit[a] / n:.1f} |")
    R["actions_offered"] = dict(act)
    # ---------------- response-class coverage
    P("\n## 5. Response-class coverage per family\n")
    P("Share of situations whose candidate list contains at least one action of each class "
      "(aggress, avoid, cooperate, resist, confront, deceive, negotiate, inform, repair, continue). A class that is rare in a family where it "
      "would be a natural reaction is a hole in `build_candidates()`.\n")
    classes = list(rp.ACTION_CLASS)
    P("| family | " + " | ".join(classes) + " | mean classes |\n|---|" + "---|" * (len(classes) + 1))
    cov = {}
    for f in sorted(fam):
        rows = [s for s in states if s["family"] == f]
        per = []
        nc = []
        for c in classes:
            per.append(sum(1 for s in rows if any(rp.class_of(x["a"]) == c for x in s["cands"])) / len(rows))
        for s in rows:
            nc.append(len({rp.class_of(x["a"]) for x in s["cands"]} - {"other"}))
        cov[f] = per
        P(f"| {f} | " + " | ".join(f"{100 * p:.0f}" for p in per) + f" | {mean(nc):.1f} |")
    R["class_coverage"] = {f: dict(zip(classes, [round(p, 2) for p in per])) for f, per in cov.items()}
    thin = [s for s in states if len({rp.class_of(x["a"]) for x in s["cands"]} - {"other"}) < 3]
    P(f"\nSituations offering fewer than 3 response classes: {len(thin)} ({100 * len(thin) / n:.1f}%).")
    R["thin_candidate_sets"] = len(thin)
    # ---------------- relations
    links = Counter()
    contra = Counter()
    n_ent = 0
    for s in states:
        for e in s["state"]["entities"]:
            n_ent += 1
            links[e["link"]] += 1
            r = {k: rp.to10(v, "B100") if k in ("affection", "trust", "respect", "romance", "debt") else rp.to10(v, "U100")
                 for k, v in e["rel"].items()}
            if r["affection"] >= 5 and r["trust"] <= -5:
                contra["loved but distrusted"] += 1
            if r["affection"] <= -5 and r["respect"] >= 5:
                contra["disliked but respected"] += 1
            if r["fear"] >= 5 and r["affection"] >= 4:
                contra["feared and loved"] += 1
            if r["grudge"] >= 6 and r["trust"] >= 4:
                contra["grudge but trusted"] += 1
            if r["trust"] >= 5 and e.get("suspicion", 0) >= 50:
                contra["trusted but suspected"] += 1
    P("\n## 6. Relations\n")
    P(f"{n_ent} entity slots; {n_ent / n:.2f} per situation.\n")
    P("| link | n | % |\n|---|---|---|")
    for k, v in links.most_common():
        P(f"| {k} | {v} | {100 * v / n_ent:.1f} |")
    P("\nExplicable contradictions (state as a share of entity slots):\n")
    for k, v in contra.most_common():
        P(f"- {k}: {v} ({100 * v / n_ent:.1f}%)")
    R["contradictions"] = dict(contra)
    # ---------------- village / society
    withv = [s for s in states if s["state"].get("village")]
    P("\n## 7. Village / society coverage\n")
    if not withv:
        P("**No village or society variable exists in this corpus.**")
        R["village_coverage"] = 0
    else:
        P(f"{len(withv)} of {n} situations carry a village token ({100 * len(withv) / n:.0f}%). "
          f"Household token: {sum(1 for s in states if s['state'].get('household'))}; group tokens: "
          f"{sum(len(s['state'].get('groups', [])) for s in states)}.\n")
        pk = Counter(s["state"]["village"]["problem"]["kind"] for s in withv)
        P("Collective problem kinds: " + ", ".join(f"{k} {v}" for k, v in pk.most_common()) + "\n")
        sv = defaultdict(list)
        for s in withv:
            v = s["state"]["village"]
            sv["belonging"].append(rp.to10(v["belonging"], "U100"))
            sv["loyalty"].append(rp.to10(v["loyalty"], "B100"))
            sv["leader_trust"].append(rp.to10(v["leader_trust"], "B100"))
            sv["leader_legit"].append(rp.to10(v["leader_legit"], "B100"))
            sv["economy"].append(rp.to10(v["economy"], "B100"))
            sv["security"].append(rp.to10(v["security"], "B100"))
            sv["tension"].append(rp.to10(v["tension"], "U100"))
        P("| village variable | mean | sd |\n|---|---|---|")
        for k, v in sv.items():
            P(f"| {k} | {mean(v):+.1f} | {sd(v):.1f} |")
        vc = Counter()
        for s in withv:
            v = s["state"]["village"]
            lt, lg, lo = rp.to10(v["leader_trust"], "B100"), rp.to10(v["leader_legit"], "B100"), rp.to10(v["loyalty"], "B100")
            ec = rp.to10(v["economy"], "B100")
            if lt <= -4 and lo >= 5:
                vc["dislikes leader but loyal to village"] += 1
            if lt >= 4 and lo <= -2:
                vc["trusts leader but not the village"] += 1
            if ec <= -4 and lg >= 4:
                vc["poor village, legitimate leader"] += 1
            if ec >= 4 and lg <= -4:
                vc["rich village, illegitimate leader"] += 1
            if lt <= -4 and lg >= 4:
                vc["distrusted but legitimate leader"] += 1
        P("\nCollective/individual contradictions: " + (", ".join(f"{k} {v}" for k, v in vc.most_common()) or "none"))
        R["village_coverage"] = round(len(withv) / n, 3)
        R["village_contradictions"] = dict(vc)
    lv = [levels_of(s["state"]) for s in states]
    multi = sum(1 for x in lv if len(x) >= 2)
    P(f"\n### Levels touched by a situation\n")
    lc = Counter(l for x in lv for l in x)
    P(", ".join(f"{k} {v} ({100 * v / n:.0f}%)" for k, v in lc.most_common()))
    P(f"\nSituations touching at least two levels: **{multi}** ({100 * multi / n:.1f}%).")
    R["multi_level"] = round(multi / n, 3)
    R["levels"] = dict(lc)
    # ---------------- duplicates
    sk = Counter(skeleton(s) for s in states)
    dup = sum(v - 1 for v in sk.values() if v > 1)
    P("\n## 8. Duplication\n")
    P(f"Identical skeletons (family + candidate actions + event types + link types): {dup} situations are repeats of an earlier skeleton "
      f"({100 * dup / n:.1f}%). Skeletons repeat naturally with few actions; what matters is that the NUMBERS differ.")
    toks = [set(s["text"].split()) for s in states]
    near = 0
    byf = defaultdict(list)
    for i, s in enumerate(states):
        byf[s["family"]].append(i)
    for idx in byf.values():
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                if jaccard(toks[idx[a]], toks[idx[b]]) >= .95:
                    near += 1
    P(f"Near-duplicate pairs (same family, >= 95% identical tokens of the teacher text): {near}.")
    R["near_duplicate_pairs"] = near
    R["skeleton_repeats"] = dup
    # ---------------- biases
    P("\n## 9. Generation biases\n")
    P("A trait should not depend on the family (traits are drawn before the scenario). Largest deviations of a family's mean from the global mean, in standard deviations:\n")
    dev = []
    for key in (k for k in vals if k.startswith("self.trait") or k.startswith("self.value")):
        g_m, g_s = mean(vals[key]), sd(vals[key]) or 1
        for f in fam:
            xs = [rp.to10(v, kind, vm) for s in states if s["family"] == f
                  for (grp, nm, v, kind, vm, ow) in rp.scalars_of(s["state"]) if f"{grp}.{nm}" == key]
            if len(xs) >= 25:
                dev.append((abs(mean(xs) - g_m) / g_s, key, f, mean(xs) - g_m))
    dev.sort(reverse=True)
    for d, key, f, diff in dev[:6]:
        P(f"- {key} in {f}: {diff:+.1f} ({d:.2f} sd)")
    R["max_family_trait_deviation_sd"] = round(dev[0][0], 2) if dev else 0
    # ---------------- teacher side
    if labels:
        lab = {l["id"]: l for l in labels}
        have = [s for s in states if s["id"] in lab]
        P(f"\n## 10. Teacher side ({len(have)} labelled situations)\n")
        alt_by = defaultdict(lambda: [0, 0, 0, 0])      # n, alt, n_low_max, alt_when_low
        amb = defaultdict(lambda: [0, 0])
        top_counter = Counter()
        best_never = Counter()
        altc = Counter()
        for s in have:
            l = lab[s["id"]]
            sc = l["scores"]
            mx = max(sc)
            f = s["family"]
            alt_by[f][0] += 1
            a_ = l.get("alt")
            if a_:
                alt_by[f][1] += 1
                altc[a_.split()[0] if a_.split() else a_] += 1
            if mx <= 2:
                alt_by[f][2] += 1
                alt_by[f][3] += bool(a_)
            tops = [i for i, x in enumerate(sc) if x == mx]
            amb[f][0] += 1
            amb[f][1] += len(tops) >= 2 and len({rp.class_of(s["cands"][i]["a"]) for i in tops}) >= 2
            for i in tops:
                top_counter[s["cands"][i]["a"]] += 1 / len(tops)
        N = sum(v[0] for v in alt_by.values())
        A = sum(v[1] for v in alt_by.values())
        P(f"**alt_rate (teacher proposes an option that is not in OPTS): {100 * A / N:.1f}%**\n")
        P("| family | n | alt % | situations where best listed score <= 2 | alt % among those | ambiguous % |\n|---|---|---|---|---|---|")
        for f, (nn, aa, low, alow) in sorted(alt_by.items(), key=lambda kv: -kv[1][1] / max(1, kv[1][0])):
            P(f"| {f} | {nn} | {100 * aa / nn:.0f} | {low} | {100 * alow / max(1, low):.0f} | {100 * amb[f][1] / amb[f][0]:.0f} |")
        P("\nA high alt rate is only a signal of a missing option when the best listed score is low: read the 'among those' column.\n")
        P("Actions the teacher asks for most often (first word of `alt`):\n")
        for a_, v in altc.most_common(12):
            P(f"- {a_}: {v}")
        tot_top = sum(top_counter.values())
        P("\nActions most often rated best:\n")
        for a_, v in top_counter.most_common(8):
            P(f"- {a_}: {100 * v / tot_top:.1f}%")
        offered = set(act)
        never = sorted(a for a in offered if top_counter.get(a, 0) == 0)
        P(f"\nOffered but never rated best: {', '.join(never) if never else 'none'}")
        amb_all = sum(v[1] for v in amb.values()) / N
        P(f"\nAmbiguous situations (several top options of different response classes): **{100 * amb_all:.1f}%** "
          "(the teacher finds several defensible reactions: keep them, they are information, and use soft labels).")
        R["alt_rate"] = round(A / N, 3)
        R["ambiguous_rate"] = round(amb_all, 3)
        R["alt_by_family"] = {f: round(v[1] / v[0], 3) for f, v in alt_by.items()}
    else:
        P("\n## 10. Teacher side\n\nNo labels yet: alt_rate, ambiguity and unused actions are measured after the teacher run "
          "(`python3 run_pipeline.py --target 1000`, then rerun this report with `--labels data/labels.jsonl`).")
    text = "\n".join(lines)
    if out_json:
        json.dump(R, open(out_json, "w"), indent=1)
    return text, R


def read_jsonl(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", required=True)
    ap.add_argument("--labels", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    states = read_jsonl(a.states)
    labels = read_jsonl(a.labels) if a.labels and os.path.exists(a.labels) else None
    text, R = report(states, labels, a.json or None)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
        print(f"wrote {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
