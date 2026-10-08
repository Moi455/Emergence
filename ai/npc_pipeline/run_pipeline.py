#!/usr/bin/env python3
"""run_pipeline.py - the one command. Generates situations, checks the API, picks the best prompt variant,
labels until the target is reached (sleeping through daily quota resets) and exports the dataset.

  python3 run_pipeline.py                   # everything, resumable; relaunch it any time
  python3 run_pipeline.py --stage states    # only (re)generate the situations
  python3 run_pipeline.py --stage probe|pilot|run|export
  python3 run_pipeline.py --target 20000    # change the goal (more situations are generated if needed)
"""
import argparse
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REQUIRED = ["generate_states.py", "plan_contract.py", "social_rules.py", "dialogue_protocols.py", "memory_service.py",
            "teacher_tools.py", "teacher_run.py", "gemini_client.py", "teacher_prompt.md"]
_missing = [f for f in REQUIRED if not os.path.exists(os.path.join(HERE, f))]
if _missing:
    sys.exit("Your folder is incomplete. Missing: " + ", ".join(_missing) +
             "\nUnzip the complete archive again:  python3 -m zipfile -e npc_pipeline.zip ~/")
import teacher_run as tr  # noqa: E402

CONFIG_TEXT = {
    "_comment": "Edit with: gedit config.json. rpd = REQUESTS PER DAY (check the real value in AI Studio > Rate limits).",
    "model": "gemini-3.5-flash-lite",
    "rpm": 15, "tpm": 250000, "rpd": 500, "rpd_reserve": 5,
    "per_call": 16, "workers": 4,
    "variant": "auto", "thinking": "auto",
    "target": 50000, "pilot_n": 96, "pilot_levels": ["minimal", "low"],
    "data_dir": "data", "log_dir": "logs",
    "states_seed": 20261004,
}


def run(cmd, env=None):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def stage_states(cfg_path, cfg, target):
    env = tr.Env(cfg)
    need = int(target * 1.15) + 200
    have = env.count_lines("states")
    if have >= need:
        print(f"states: {have} available (need {need})")
        return
    out = env.p["states"]
    tmp = out + ".new"
    try:
        run([sys.executable, os.path.join(HERE, "generate_states.py"), "--n", str(need), "--seed", str(cfg.get("states_seed", 1)),
             "--out", tmp, "--check"])
    except subprocess.CalledProcessError:
        sys.exit("generate_states.py failed (see the message above). The usual cause is an incomplete folder: "
                 "unzip the complete archive again.")
    os.replace(tmp, out)         # same seed => the first `have` states are identical, existing labels stay valid
    print(f"states: wrote {need} situations to {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--stage", default="all", choices=["all", "states", "probe", "pilot", "run", "export"])
    ap.add_argument("--target", type=int, default=0)
    a = ap.parse_args()
    if not os.path.exists(a.config):
        json.dump(CONFIG_TEXT, open(a.config, "w"), indent=2)
        print(f"created {a.config} with default values (edit it with: gedit {a.config})")
    cfg = tr.load_cfg(a.config)
    if a.target:
        cfg["target"] = a.target
    env = tr.Env(cfg)
    stages = ["states", "probe", "pilot", "run", "export"] if a.stage == "all" else [a.stage]
    ns = argparse.Namespace(config=a.config, target=cfg["target"], verbose=False)
    for st in stages:
        if st == "states":
            stage_states(a.config, cfg, cfg["target"])
        elif st == "probe":
            if os.path.exists(env.p["caps"]) and a.stage == "all":
                print("probe: already done (delete data/capabilities.json to redo)")
            else:
                tr.cmd_probe(env, ns)
        elif st == "pilot":
            need = cfg["variant"] == "auto" or cfg["thinking"] == "auto"
            if a.stage == "all" and (os.path.exists(env.p["choice"]) or not need):
                print("pilot: already done or not needed")
            else:
                tr.cmd_pilot(env, ns)
        elif st == "run":
            tr.cmd_run(env, ns)
        elif st == "export":
            tr.cmd_export(env, ns)


if __name__ == "__main__":
    main()
