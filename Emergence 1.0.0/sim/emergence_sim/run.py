"""Command line: run the village simulation and write viewer data and trajectories.

  python3 -m emergence_sim.run --seed 7 --years 1 --out out/
"""
import argparse
import json
import os
import time

from .core import Sim
from .export import viewer_data


def fingerprint(sim):
    """Stable digest of the whole social state (determinism tests)."""
    from .rng import hash_ints
    h = 0
    for n in sim.npcs:
        vals = [n.id, int(n.alive), n.hunger, n.fatigue, n.hp, n.coin, n.partner or -1, len(n.rel), len(n.mem)]
        vals += [n.skills[c] for c in sorted(n.skills)]
        for o in sorted(n.rel):
            vals += [o] + n.rel[o]
        h = hash_ints(h, *vals)
    for hh in sim.hhs:
        h = hash_ints(h, hh.id, hh.coin, *[hh.goods.get(g, 0) for g in sim.goods])
    return f"{h:016x}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--years", type=float, default=1.0)
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--out", default="out")
    ap.add_argument("--traj-ppm", type=int, default=0, help="decisions exported per million (0 = none)")
    ap.add_argument("--tracked", type=int, default=12)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--brain", choices=("reference", "transformer"), default="reference",
                    help="who decides: the frozen utility rules, or the Transformer of ai/student")
    ap.add_argument("--model", default=None, help="checkpoint .pt of ai/student/train_student.py (none = untrained weights)")
    ap.add_argument("--config", default="tiny", help="model size when no checkpoint: tiny, small, base, large")
    ap.add_argument("--device", default="cpu", help="cpu or cuda")
    ap.add_argument("--temperature", type=float, default=0.0, help="0 = best option; > 0 = deterministic sampling")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    traj = os.path.join(a.out, f"trajectories_seed{a.seed}.jsonl") if a.traj_ppm else None
    t0 = time.time()
    brain = None
    if a.brain == "transformer":
        from .brain import TransformerBrain
        brain = TransformerBrain(checkpoint=a.model, config=a.config, device=a.device, temperature=a.temperature, seed=a.seed)
    sim = Sim(seed=a.seed, traj_ppm=a.traj_ppm, traj_path=traj, tracked=a.tracked, brain=brain)
    days = a.days if a.days is not None else int(a.years * sim.DPY)

    def progress(s):
        if a.quiet:
            return
        alive = sum(1 for n in s.npcs if n.alive)
        print(f"  an {s.day / s.DPY:5.2f}  vivants {alive:4d}  décisions {s.decisions:8d}  événements {len(s.events):6d}  {time.time() - t0:6.1f}s", flush=True)

    sim.run(days, progress)
    el = time.time() - t0
    data = viewer_data(sim, round(el, 1))
    data["fingerprint"] = fingerprint(sim)
    p = os.path.join(a.out, f"viewer_seed{a.seed}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    alive = sum(1 for n in sim.npcs if n.alive)
    print(json.dumps({"seed": a.seed, "days": days, "seconds": round(el, 1), "alive": alive, "ever": len(sim.npcs),
                      "decisions": sim.decisions, "interactions": sim.interactions, "events": len(sim.events),
                      "trajectories": sim.traj_count, "fingerprint": data["fingerprint"],
                      "brain": sim.brain.name, "brain_stats": sim.brain.stats(), "fallbacks": sim.fallbacks,
                      "viewer_data": p, "viewer_mb": round(os.path.getsize(p) / 1e6, 2)}, ensure_ascii=False))
    return sim


if __name__ == "__main__":
    main()
