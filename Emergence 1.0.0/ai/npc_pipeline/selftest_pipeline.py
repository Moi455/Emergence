#!/usr/bin/env python3
"""selftest_pipeline.py - proves the whole unattended pipeline works WITHOUT any API key, against a local mock server.

  python3 selftest_pipeline.py          # about 1-2 minutes

It checks: probe (thinking levels, capability fallbacks), pilot, daily-quota sleeping, 503/429 retries,
safety-block splitting, malformed JSON handling, resume after an interruption, export and splits.
It does NOT prove that the live Gemini API accepts the payload: use `teacher_run.py probe` with your key for that.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

_REQ = ["generate_states.py", "plan_contract.py", "social_rules.py", "dialogue_protocols.py", "memory_service.py", "teacher_tools.py",
        "teacher_run.py", "gemini_client.py", "run_pipeline.py", "mock_gemini_server.py", "teacher_prompt.md"]
_miss = [x for x in _REQ if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), x))]
if _miss:
    sys.exit("Your folder is incomplete. Missing: " + ", ".join(_miss) + "\nUnzip the complete archive again:  python3 -m zipfile -e npc_pipeline.zip ~/")

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8791


def main():
    work = tempfile.mkdtemp(prefix="npc_selftest_")
    for f in os.listdir(HERE):
        if f.endswith((".py", ".md")):
            shutil.copy(os.path.join(HERE, f), work)
    env = dict(os.environ, NPC_SIM_DAY_SECONDS="10", GEMINI_API_KEY="selftest", GEMINI_BASE_URL=f"http://127.0.0.1:{PORT}")
    mock = subprocess.Popen([sys.executable, "mock_gemini_server.py", "--port", str(PORT), "--rpm", "200", "--rpd", "34", "--p503", ".05",
                             "--pbad", ".04", "--plen", ".04", "--pflat", ".03", "--poison-mod", "53", "--reject-minimal", "--latency", "0.35", "--force-every", "20"],
                            cwd=work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    cfg = {"rpm": 150, "tpm": 3000000, "rpd": 34, "rpd_reserve": 4, "per_call": 8, "workers": 4, "variant": "auto", "thinking": "auto",
           "target": 120, "pilot_n": 16, "data_dir": "data", "log_dir": "logs", "states_seed": 5, "timeout": 20}
    json.dump(cfg, open(os.path.join(work, "config.json"), "w"))
    ok = True

    def check(c, msg):
        nonlocal ok
        print(("PASS  " if c else "FAIL  ") + msg, flush=True)
        ok = ok and c

    def pipeline(*args, timeout=150):
        return subprocess.run([sys.executable, "run_pipeline.py", *args], cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
    try:
        r = pipeline("--stage", "states")
        check(r.returncode == 0, "states generated and validated")
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-1500:])
            raise SystemExit("cannot continue without situations")
        r = pipeline("--stage", "probe")
        caps = json.load(open(os.path.join(work, "data/capabilities.json")))
        check("minimal" not in caps["thinking_ok"] and "low" in caps["thinking_ok"], f"probe separates accepted/refused thinking levels: {caps['thinking_ok']}")
        check(caps["caps"]["thinking"] is True, "a refused level does not disable thinking for good")
        r = pipeline("--stage", "pilot")
        choice = json.load(open(os.path.join(work, "data/pilot_choice.json")))
        check(r.returncode == 0 and choice["variant"] in ("none", "text", "codes"), f"pilot chose {choice}")
        # run, interrupted after a few seconds, then resumed
        p = subprocess.Popen([sys.executable, "run_pipeline.py", "--stage", "run"], cwd=work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        lp = os.path.join(work, "data/labels.jsonl")
        t_end = time.time() + 40
        while time.time() < t_end:                      # interrupt as soon as some labels exist: deterministic, not timing-dependent
            if os.path.exists(lp) and sum(1 for _ in open(lp)) >= 16:
                break
            time.sleep(.1)
        p.send_signal(signal.SIGINT)
        p.wait(timeout=60)
        labels_path = os.path.join(work, "data/labels.jsonl")
        n1 = sum(1 for _ in open(labels_path)) if os.path.exists(labels_path) else 0
        check(0 < n1 < 120, f"the first run really was interrupted midway ({n1} labelled of 120)")
        r = pipeline("--stage", "run", timeout=240)
        lab = [json.loads(l) for l in open(labels_path)]
        rej = [json.loads(l) for l in open(os.path.join(work, "data/rejected.jsonl"))] if os.path.exists(os.path.join(work, "data/rejected.jsonl")) else []
        ids = [x["id"] for x in lab]
        check(len(ids) == len(set(ids)), f"no duplicate labels after interruption+resume ({n1} before, {len(ids)} after)")
        check(len(ids) >= 120, f"target reached: {len(ids)} labelled")
        states = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(work, "data/states.jsonl"))}
        check(all(len(x["scores"]) == len(states[x["id"]]["cands"]) for x in lab), "every label has one score per option")
        poison = [i for i in states if int(i[1:]) % 53 == 0 and int(i[1:]) > 0]
        done_poison = [i for i in poison if i in set(ids)]
        check(not done_poison, "situations the 'safety filter' always blocks end up rejected, not mislabelled")
        blocked = [r2["id"] for r2 in rej if r2["reason"] == "blocked"]
        check(all(int(i[1:]) % 53 == 0 for i in blocked), "splitting isolated exactly the blocked situations (no innocent neighbour rejected)")
        check(len([r2 for r2 in rej if r2["reason"] in ("blocked",)]) >= 1, f"blocked situations recorded: {sum(1 for r2 in rej if r2['reason']=='blocked')}")
        stats = json.loads(subprocess.run(["curl", "-s", f"http://127.0.0.1:{PORT}/stats"], capture_output=True, text=True).stdout)
        check(stats["429d"] == 0, f"our limiter never hit the daily cap (mock saw {stats['429d']} daily 429)")
        check(stats["503"] > 0 and stats["bad_json"] + stats["bad_len"] > 0, f"failures were injected and survived: {stats}")
        r = pipeline("--stage", "export")
        ds = [json.loads(l) for l in open(os.path.join(work, "data/intent_dataset.jsonl"))]
        check(len(ds) == len(set(ids)) and {d["split"] for d in ds} == {"train", "val", "test"}, f"export: {len(ds)} rows with splits {sorted({d['split'] for d in ds})}")
        check(all(abs(sum(d["soft"]) - 1) < 1e-2 for d in ds), "soft labels sum to 1")
    finally:
        mock.terminate()
        shutil.rmtree(work, ignore_errors=True)
    print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
