"""summarize.py - prints the tables of docs/09 from the raw results (ai/research/arch/results/*.json), so that every
[Mesuré] figure of the document can be traced back to a file.

  python3 ai/research/arch/summarize.py
"""
import json
import os
from collections import defaultdict

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load(name):
    p = os.path.join(RES, name)
    return json.load(open(p)) if os.path.exists(p) else None


def brains():
    d = load("arch_brains.json")
    print(f"## policy lots (CUDA graph, FP16, T=128) - {d['gpu']} {d['date']}")
    by = defaultdict(dict)
    meta = {}
    for r in d["rows"]:
        by[r["config"]][r["B"]] = r["graph_ms"]
        meta[r["config"]] = (r["params_M"], r["per_npc_state_KiB"], r["peak_alloc_MiB"])
    print("| config | params M | state KiB/NPC | B=8 | B=16 | B=32 | B=64 | GPU % at 200/s (lots of 32) |")
    for c, t in by.items():
        p, st, _ = meta[c]
        print(f"| {c} | {p:.1f} | {st:.0f} | " + " | ".join(f"{t.get(b, float('nan')):.2f}" for b in (8, 16, 32, 64))
              + f" | {t[32] * 10 / 10:.1f} % |")


def simple(name, keys):
    d = load(name)
    if not d:
        print(f"(no {name})")
        return
    print(f"## {name} - {d.get('gpu')} {d.get('date')}")
    for r in d["rows"]:
        print("  " + ", ".join(f"{k}={r[k]:.3g}" if isinstance(r.get(k), float) else f"{k}={r.get(k)}" for k in keys))


def probe():
    d = load("probe_belief.json")
    if not d:
        print("(no probe_belief.json)")
        return
    print(f"## probe - {d.get('date')} references {d['references']}")
    agg = defaultdict(lambda: defaultdict(list))
    for r in d["runs"]:
        for k, v in r["eval"].items():
            agg[r["model"]][k].append(v["acc"])
        agg[r["model"]]["_mflop"] = [r["mflop_per_decision"]]
        agg[r["model"]]["_params"] = [r["params"] / 1e6]
    cols = ["ALL", "true-belief", "false-belief", "false-belief/recent(<8)", "false-belief/mid(8-15)",
            "false-belief/old(16+)", "false-belief/initial", "true-belief/old(16+)"]
    print("| model | seeds | params M | MFLOP/dec | " + " | ".join(cols) + " |")
    for m, a in agg.items():
        cells = []
        for c in cols:
            v = a.get(c, [])
            cells.append(f"{100 * sum(v) / len(v):.1f}" + (f" ({100 * min(v):.0f}-{100 * max(v):.0f})" if len(v) > 1 else "")
                         if v else "-")
        print(f"| {m} | {len(a['ALL'])} | {a['_params'][0]:.2f} | {a['_mflop'][0]:.0f} | " + " | ".join(cells) + " |")
    n = {k: v["n"] for k, v in d["runs"][0]["eval"].items()}
    print("questions per category (held-out):", n)


def coalition():
    d = load("probe_coalition.json")
    if not d:
        print("(no probe_coalition.json)")
        return
    print(f"## coalition probe - {d.get('date')} world {d.get('world')}")
    agg = defaultdict(lambda: defaultdict(list))
    for r in d["runs"]:
        for k, v in r["eval"].items():
            if isinstance(v, (int, float)):
                agg[r["model"]][k].append(v)
        agg[r["model"]]["_mflop"] = [r["mflop_per_decision"]]
        agg[r["model"]]["_params"] = [r["params"] / 1e6]
    cols = ["success", "success_coalition", "success_no_coalition", "exact_invites", "secrecy_violation",
            "decisions_per_episode_per_villager", "success/hops<=1", "success/hops=2", "success/hops>=3"]
    print("| model | seeds | params M | MFLOP/dec | " + " | ".join(cols) + " |")
    for m, a in agg.items():
        cells = []
        for c in cols:
            v = a.get(c, [])
            scale = 1 if c.startswith("decisions") else 100
            cells.append(f"{scale * sum(v) / len(v):.1f}" + (f" ({scale * min(v):.0f}-{scale * max(v):.0f})"
                                                              if len(v) > 1 and scale == 100 else "") if v else "-")
        print(f"| {m} | {len(a['success'])} | {a['_params'][0]:.2f} | {a['_mflop'][0]:.0f} | " + " | ".join(cells) + " |")


def main():
    brains()
    simple("fusion.json", ["size", "mode", "B", "graph_ms"])
    simple("arch_speech.json", ["d", "layers", "B", "graph_ms", "utterances_per_s"])
    simple("arch_stream.json", ["kind", "graph_ms", "gpu_share_at_10Hz"])
    simple("arch_llm.json", ["model", "T", "B", "graph_ms", "gpu_share_at_200_per_s"])
    simple("arch_online.json", ["config", "sgd_step_ms_eager", "forward_ms_eager", "adapter_KiB_per_npc"])
    simple("arch_tick.json", ["policy", "parts_ms", "tick_ms", "gpu_share_at_200_per_s"])
    simple("arch_tick2.json", ["policy", "T", "parts_ms", "tick_ms", "gpu_share_at_200_per_s"])
    simple("arch_tick3.json", ["policy", "parts_ms", "tick_ms", "gpu_share_at_200_per_s"])
    simple("deliberation.json", ["part", "name", "graph_ms"])
    simple("ort.json", ["size", "B", "torch_graph_ms", "ort_cuda_graph_ms", "gesture_parity"])
    simple("gemm_rate.json", ["M", "K", "N", "fp16_accumulation", "tflops"])
    probe()
    coalition()
    st = load("state.json")
    if st:
        print("## state.json determinism (all True = bit-identical):",
              all(all(v.values()) for v in st["determinism"].values()), "| memory:", st["memory"])


if __name__ == "__main__":
    main()
