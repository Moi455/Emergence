#!/usr/bin/env python3
"""selftest_quota_stress.py - the provider's daily quota is lower than config.json says (e.g. you misread 500 RPM/RPD).
The run must survive real 429 'per day' errors, sleep until the reset and still finish."""
import json, os, shutil, subprocess, sys, tempfile, time
_REQ = ["generate_states.py", "plan_contract.py", "social_rules.py", "dialogue_protocols.py", "memory_service.py", "teacher_tools.py",
        "teacher_run.py", "gemini_client.py", "run_pipeline.py", "mock_gemini_server.py", "teacher_prompt.md"]
_miss = [x for x in _REQ if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), x))]
if _miss:
    sys.exit("Your folder is incomplete. Missing: " + ", ".join(_miss) + "\nUnzip the complete archive again:  python3 -m zipfile -e npc_pipeline.zip ~/")

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8792
work = tempfile.mkdtemp(prefix="npc_stress_")
for f in os.listdir(HERE):
    if f.endswith((".py", ".md")):
        shutil.copy(os.path.join(HERE, f), work)
env = dict(os.environ, NPC_SIM_DAY_SECONDS="8", GEMINI_API_KEY="selftest", GEMINI_BASE_URL=f"http://127.0.0.1:{PORT}")
mock = subprocess.Popen([sys.executable, "mock_gemini_server.py", "--port", str(PORT), "--rpm", "300", "--rpd", "10", "--p503", "0",
                         "--pbad", "0", "--plen", "0", "--pflat", "0"], cwd=work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
json.dump({"rpm": 200, "tpm": 3000000, "rpd": 40, "rpd_reserve": 0, "per_call": 8, "workers": 3, "variant": "codes", "thinking": "low",
           "target": 160, "data_dir": "data", "log_dir": "logs", "states_seed": 3, "timeout": 20}, open(os.path.join(work, "config.json"), "w"))
ok = True
try:
    r0 = subprocess.run([sys.executable, "run_pipeline.py", "--stage", "states"], cwd=work, env=env, capture_output=True, text=True)
    if r0.returncode != 0:
        print((r0.stdout + r0.stderr)[-1500:])
        sys.exit("cannot continue without situations")
    r = subprocess.run([sys.executable, "run_pipeline.py", "--stage", "run"], cwd=work, env=env, capture_output=True, text=True, timeout=200)
    n = sum(1 for _ in open(os.path.join(work, "data/labels.jsonl")))
    log = open(os.path.join(work, "logs/run.log")).read()
    stats = json.loads(subprocess.run(["curl", "-s", f"http://127.0.0.1:{PORT}/stats"], capture_output=True, text=True).stdout)
    for cond, msg in ((n >= 160, f"target reached despite a daily quota 4x lower than configured ({n} labelled)"),
                      (stats["429d"] > 0, f"real daily 429 errors were received ({stats['429d']})"),
                      ("daily quota reached" in log, "the run announced it was sleeping until the reset")):
        print(("PASS  " if cond else "FAIL  ") + msg)
        ok = ok and cond
finally:
    mock.terminate()
    shutil.rmtree(work, ignore_errors=True)
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
