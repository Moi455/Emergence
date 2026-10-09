#!/usr/bin/env python3
"""teacher_run.py - label NPC situations with Gemini 3.5 Flash-Lite, unattended.

  python3 teacher_run.py probe     # 1 minute: checks key, model, JSON mode, thinking levels
  python3 teacher_run.py pilot     # compares output variants and thinking levels, picks the best
  python3 teacher_run.py run       # labels until the target is reached; safe to stop and relaunch
  python3 teacher_run.py status    # progress, quota used today, estimated days left
  python3 teacher_run.py export    # builds data/intent_dataset.jsonl (train/val/test split)

Everything is resumable: labels are appended to data/labels.jsonl as soon as they arrive.
Quotas (RPM, input TPM, requests per day) come from config.json and are enforced here, including
sleeping until the daily reset (midnight Pacific time) when the daily quota is used up.
"""
import argparse
import hashlib
import json
import math
import os
import random
import signal
import sys
import threading
import time
from collections import Counter, defaultdict, deque

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import teacher_tools as tt                      # noqa: E402
from gemini_client import ApiError, GeminiClient, Limiter, day_key, seconds_to_next_day  # noqa: E402

DEFAULT_CFG = {
    "model": "gemini-3.5-flash-lite",
    "rpm": 15, "tpm": 250000, "rpd": 500, "rpd_reserve": 5,
    "per_call": 16, "workers": 4,
    "variant": "auto",              # none | text | codes | auto (chosen by the pilot)
    "thinking": "auto",             # minimal | low | medium | high | auto (chosen by the pilot)
    "target": 50000, "pilot_n": 96, "pilot_levels": ["minimal", "low"],
    "data_dir": "data", "log_dir": "logs",
    "timeout": 240, "max_api_attempts": 7,
}
SCORES = [0, 1, 2, 3, 4]


class Fatal(Exception):
    pass


class Stopped(Exception):
    pass


# --------------------------------------------------------------------------- config, logging, files
def load_cfg(path):
    cfg = dict(DEFAULT_CFG)
    if path and os.path.exists(path):
        cfg.update(json.load(open(path)))
    return cfg


class Env:
    def __init__(self, cfg):
        self.cfg = cfg
        self.data = os.path.abspath(cfg["data_dir"])
        self.logs = os.path.abspath(cfg["log_dir"])
        os.makedirs(self.data, exist_ok=True)
        os.makedirs(self.logs, exist_ok=True)
        self.p = {k: os.path.join(self.data, v) for k, v in dict(
            states="states.jsonl", labels="labels.jsonl", rejected="rejected.jsonl", limiter="limiter.json",
            caps="capabilities.json", pilot="pilot_report.json", choice="pilot_choice.json",
            dataset="intent_dataset.jsonl").items()}
        self.logfile = os.path.join(self.logs, "run.log")
        self._lock = threading.Lock()

    def log(self, msg):
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
        with self._lock:
            print(line, flush=True)
            with open(self.logfile, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def append(self, key, obj):
        with self._lock:
            with open(self.p[key], "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")

    def iter_jsonl(self, key):
        if not os.path.exists(self.p[key]):
            return
        with open(self.p[key], encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        pass                      # a line cut by a crash is simply ignored

    def read_jsonl(self, key):
        return list(self.iter_jsonl(key))

    def count_lines(self, key):
        if not os.path.exists(self.p[key]):
            return 0
        with open(self.p[key], "rb") as f:
            return sum(1 for _ in f)

    def read_states(self, slim=True, limit=None):
        """States without the heavy 'state' field (only the teacher text and the options are needed to label)."""
        out = []
        for s in self.iter_jsonl("states"):
            out.append({"id": s["id"], "family": s["family"], "text": s["text"], "cands": s["cands"], "view": s["view"]}
                       if slim else s)
            if limit and len(out) >= limit:
                break
        return out


# --------------------------------------------------------------------------- schema and prompts
def make_schema(variant):
    props = {"id": {"type": "string"}}
    if variant == "text":
        props["why"] = {"type": "string", "description": "max 15 words, the key reason"}
    if variant == "codes":
        props["k"] = {"type": "array", "items": {"type": "string", "enum": sorted(tt.DRIVERS)}, "minItems": 1, "maxItems": 3}
    props["s"] = {"type": "array", "items": {"type": "integer", "enum": SCORES}, "minItems": 2, "maxItems": 16}
    props["alt"] = {"type": ["string", "null"]}
    return {"type": "object", "properties": {"r": {"type": "array", "items": {
        "type": "object", "properties": props, "required": ["id", "s"]}}}, "required": ["r"]}


def render(rec, perm=None):
    """Text of one situation; `perm` reorders the options (perm[new_index] = old_index)."""
    if perm is None:
        return rec["text"]
    import generate_states as gs
    v = json.loads(json.dumps(rec["view"]))
    old = v["opts"]
    v["opts"] = [[i] + old[j][1:] for i, j in enumerate(perm)]
    return gs.view_text(v)


# --------------------------------------------------------------------------- the teacher
class Teacher:
    def __init__(self, env, client, limiter, variant, thinking, stop):
        self.env, self.client, self.limiter, self.stop = env, client, limiter, stop
        self.variant, self.thinking = variant, (None if thinking in (None, "none", "default") else thinking)
        self.system = tt.load_system(variant)
        self.schema = make_schema(variant)
        self.lock = threading.Lock()
        self.stats = Counter()
        self.consec_429 = 0
        self.consec_bad = 0

    # ---- one HTTP exchange with all retry policy
    def _call(self, user):
        est = int((len(self.system) + len(user)) / 2.6)
        backoff = 5.0
        for attempt in range(self.env.cfg["max_api_attempts"]):
            if not self.limiter.acquire(est):
                raise Stopped()
            try:
                res = self.client.generate(self.system, user, self.schema, self.thinking)
                with self.lock:
                    self.consec_429 = 0
                    self.consec_bad = 0
                    self.stats["requests"] += 1
                    self.stats["total_tokens"] += res["usage"].get("total_tokens", 0)
                    for k, v in res["usage"].items():
                        self.stats["usage:" + k] += v
                return res
            except ApiError as e:
                self.stats["errors:" + e.kind] += 1
                if e.kind == "rate_day":
                    self.env.log("daily quota reached: sleeping until the reset (midnight Pacific)")
                    self.limiter.block_until_next_day()
                elif e.kind == "rate_minute":
                    with self.lock:
                        self.consec_429 += 1
                        n = self.consec_429
                    if n >= 8:
                        self.env.log("8 consecutive 429: assuming the daily quota is gone")
                        self.limiter.block_until_next_day()
                    else:
                        self.limiter.block_for(e.retry_after or (65 if n < 4 else 15 * 60))
                elif e.kind in ("server", "timeout", "other"):
                    self.stop.wait(backoff + random.random() * 2)
                    backoff = min(backoff * 2, 120)
                elif e.kind == "auth":
                    raise Fatal(f"API key refused ({e.status}): {e.message[:200]}")
                else:
                    raise                                   # bad_request, blocked, empty: caller decides
        raise ApiError("server", None, "too many attempts")

    # ---- label a list of situations (possibly splitting on safety blocks)
    def label(self, rows, shuffle=None, depth=0):
        labels, rejected = {}, {}
        perms = {}
        if shuffle is not None:
            for r in rows:
                rng = random.Random(f"{shuffle}:{r['id']}")
                p = list(range(len(r["cands"])))
                rng.shuffle(p)
                perms[r["id"]] = p
        pending, reason = list(rows), None
        for attempt in range(2):
            if not pending:
                break
            blocks = [f"### {r['id']}\n{render(r, perms.get(r['id']))}" for r in pending]
            user = "\n\n".join(blocks) + f"\n\nBased on the {len(pending)} situations above, return the JSON: one object per situation, same order, one score per option."
            try:
                res = self._call(user)
            except ApiError as e:
                reason = e.kind
                self.stats["failed_calls:" + e.kind] += 1
                if e.kind == "bad_request":
                    with self.lock:
                        self.consec_bad += 1
                        if self.consec_bad >= 3:
                            raise Fatal("the API keeps rejecting the request (check model name, config, key): " + e.message[:300])
                break
            got, errs = tt.parse_answer(res["text"], {r["id"]: len(r["cands"]) for r in pending})
            for e in errs:
                self.stats["parse:" + e] += 1
            for sid, lab in got.items():
                if shuffle is not None:                      # map scores back to the original option order
                    p = perms[sid]
                    orig = [0] * len(p)
                    for new_i, old_i in enumerate(p):
                        orig[old_i] = lab["s"][new_i]
                    lab["s"] = orig
                labels[sid] = lab
            pending = [r for r in pending if r["id"] not in labels]
            reason = reason or ("invalid_output" if pending else None)
        if pending:
            if len(pending) > 1 and depth < 3 and reason in ("blocked", "empty", "invalid_output"):
                mid = len(pending) // 2                      # isolate the offending situation by halving
                for part in (pending[:mid], pending[mid:]):
                    l2, r2 = self.label(part, shuffle, depth + 1)
                    labels.update(l2)
                    rejected.update(r2)
            else:
                for r in pending:
                    rejected[r["id"]] = reason or "unknown"
        for sid in list(labels):                             # quality gate: a flat answer carries no information
            s = labels[sid]["s"]
            if len(s) > 3 and len(set(s)) == 1:
                rejected[sid] = "flat"
                del labels[sid]
        return labels, rejected


# --------------------------------------------------------------------------- shared setup
def build(env, variant=None, thinking=None, stop=None):
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set. In fish:  set -gx GEMINI_API_KEY 'your-key'")
    stop = stop or threading.Event()
    cfg = env.cfg
    client = GeminiClient(key, cfg["model"], timeout=cfg["timeout"], log=env.log)
    caps = {}
    if os.path.exists(env.p["caps"]):
        caps = json.load(open(env.p["caps"])).get("caps", {})
    client.caps.update({k: v for k, v in caps.items() if k in client.caps})
    limiter = Limiter(cfg["rpm"], cfg["tpm"], cfg["rpd"], env.p["limiter"], stop, rpd_reserve=cfg["rpd_reserve"])
    choice = json.load(open(env.p["choice"])) if os.path.exists(env.p["choice"]) else {}
    v = variant or (cfg["variant"] if cfg["variant"] != "auto" else choice.get("variant", "codes"))
    t = thinking or (cfg["thinking"] if cfg["thinking"] != "auto" else choice.get("thinking", "low"))
    return Teacher(env, client, limiter, v, t, stop), stop


# --------------------------------------------------------------------------- probe
def cmd_probe(env, a):
    teacher, stop = build(env)
    cl = teacher.client
    env.log(f"model={cl.model}  base={cl.base}")
    ok_levels, usage_keys, trial = [], set(), {}
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "n": {"type": "integer"}}, "required": ["ok", "n"]}
    for lvl in ("minimal", "low", "medium", "high", None):
        try:
            if not teacher.limiter.acquire(200):
                return
            res = cl.generate("Reply with JSON only.", "Return {\"ok\": true, \"n\": 3}.", schema, lvl)
            usage_keys |= set(res["usage"])
            trial[str(lvl)] = res["usage"]
            if lvl:
                ok_levels.append(lvl)
            env.log(f"thinking={lvl!s:8} OK  text={res['text'][:60]!r} usage={res['usage']}")
        except ApiError as e:
            if getattr(e, "level_rejected", False):
                env.log(f"thinking={lvl!s:8} REJECTED by the model: {e.message[:140]}")
                continue
            if e.kind == "auth":
                sys.exit(f"API key refused: {e.message[:200]}")
            if e.kind in ("rate_minute", "rate_day"):
                env.log("rate limited during the probe; waiting 65 s")
                stop.wait(65)
            env.log(f"thinking={lvl!s:8} FAILED {e.kind}: {e.message[:160]}")
    states = env.read_states(limit=3)
    if not states:
        env.log("realistic test skipped: no situations yet (run:  python3 run_pipeline.py --stage states)")
    if states:
        for variant in ("none", "text", "codes"):
            t = Teacher(env, cl, teacher.limiter, variant, (ok_levels[0] if ok_levels else None), stop)
            lab, rej = t.label(states)
            env.log(f"realistic test, variant={variant}: labelled {len(lab)}/{len(states)}  rejected={rej}")
    json.dump({"caps": cl.caps, "thinking_ok": ok_levels, "usage_keys": sorted(usage_keys), "trial_usage": trial},
              open(env.p["caps"], "w"), indent=1)
    env.log(f"saved {env.p['caps']}  (thinking levels accepted: {ok_levels or 'none'}; client adaptations: {cl.caps})")


# --------------------------------------------------------------------------- pilot
def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r, i = [0.0] * len(xs), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def pearson(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def cmd_pilot(env, a):
    cfg = env.cfg
    states = env.read_states(limit=cfg["pilot_n"])
    if len(states) < 16:
        sys.exit("generate states first (python3 run_pipeline.py --stage states)")
    caps = json.load(open(env.p["caps"])) if os.path.exists(env.p["caps"]) else {}
    levels = [l for l in cfg.get("pilot_levels", ["minimal", "low"]) if l in caps.get("thinking_ok", ["low"])] or [None]
    arms = [(v, t) for v in ("none", "text", "codes") for t in levels]
    base, stop = build(env)
    signal.signal(signal.SIGINT, lambda *x: stop.set())
    per = cfg["per_call"]
    report = []
    for variant, thinking in arms:
        if stop.is_set():
            break
        t = Teacher(env, base.client, base.limiter, variant, thinking, stop)
        res = {}
        for name, shuffle in (("A", None), ("B", 1)):
            labs, rej = {}, {}
            for i in range(0, len(states), per):
                l, r = t.label(states[i:i + per], shuffle)
                labs.update(l)
                rej.update(r)
            res[name] = (labs, rej)
        la, ra = res["A"]
        lb, rb = res["B"]
        common = [i for i in la if i in lb]
        sp, top1 = [], 0
        for i in common:
            c = pearson(ranks(la[i]["s"]), ranks(lb[i]["s"]))
            if c is not None:
                sp.append(c)
            ma, mb = max(la[i]["s"]), max(lb[i]["s"])
            top1 += bool({j for j, x in enumerate(la[i]["s"]) if x == ma} & {j for j, x in enumerate(lb[i]["s"]) if x == mb})
        # position bias in pass A: correlation between option position and score
        pos, sco = [], []
        for lab in la.values():
            for j, x in enumerate(lab["s"]):
                pos.append(j / max(1, len(lab["s"]) - 1))
                sco.append(x)
        bias = pearson(pos, sco)
        nreq = max(1, t.stats["requests"])
        row = {"variant": variant, "thinking": thinking, "valid_rate": round((len(la) + len(lb)) / (2 * len(states)), 3),
               "flat_rate": round(sum(1 for x in list(ra.values()) + list(rb.values()) if x == "flat") / (2 * len(states)), 3),
               "self_spearman": round(sum(sp) / len(sp), 3) if sp else None, "self_top1": round(top1 / max(1, len(common)), 3),
               "position_bias": round(bias, 3) if bias is not None else None,
               "tokens_per_request": round(t.stats["total_tokens"] / nreq), "requests": t.stats["requests"],
               "alt_rate": round(sum(1 for l in la.values() if l.get("alt")) / max(1, len(la)), 3),
               "errors": {k: v for k, v in t.stats.items() if k.startswith(("errors", "parse", "failed"))}}
        report.append(row)
        env.log("arm " + json.dumps(row))
    ok = [r for r in report if r["valid_rate"] >= .9 and r["flat_rate"] <= .05 and r["self_spearman"] is not None]
    pool = ok or [r for r in report if r["self_spearman"] is not None]
    if not pool:
        sys.exit("no usable arm: check data/capabilities.json and logs/run.log")
    best = max(pool, key=lambda r: (r["self_spearman"], -r["tokens_per_request"]))
    json.dump(report, open(env.p["pilot"], "w"), indent=1)
    json.dump({"variant": best["variant"], "thinking": best["thinking"] or "default", "why": "highest self-agreement among valid arms",
               "warning": None if ok else "no arm met the quality gates"}, open(env.p["choice"], "w"), indent=1)
    print("\n variant  thinking  valid  flat  self-rho  top1  pos-bias  tok/req")
    for r in report:
        print(f" {r['variant']:7s}  {str(r['thinking']):8s}  {r['valid_rate']:.2f}  {r['flat_rate']:.2f}  {r['self_spearman']}  {r['self_top1']}  {r['position_bias']}  {r['tokens_per_request']}")
    env.log(f"chosen: variant={best['variant']} thinking={best['thinking']}  (self-agreement is a consistency proxy, NOT accuracy: check your hand-labelled cases)")


# --------------------------------------------------------------------------- run
def cmd_run(env, a):
    cfg = env.cfg
    teacher, stop = build(env)
    signal.signal(signal.SIGINT, lambda *x: (env.log("stop requested: finishing current requests"), stop.set()))
    signal.signal(signal.SIGTERM, lambda *x: stop.set())
    states = env.read_states()
    for s_ in states:
        s_.pop("view", None)                      # not needed without option shuffling
    if not states:
        sys.exit("no states: run  python3 run_pipeline.py --stage states")
    done = {r["id"] for r in env.read_jsonl("labels")} | {r["id"] for r in env.read_jsonl("rejected")}
    todo = [s for s in states if s["id"] not in done]
    target = a.target or cfg["target"]
    n_labels = len({r["id"] for r in env.read_jsonl("labels")})
    env.log(f"variant={teacher.variant} thinking={teacher.thinking} per_call={cfg['per_call']} workers={cfg['workers']}  "
            f"labelled={n_labels}/{target}  todo={len(todo)}")
    chunks = deque(todo[i:i + cfg["per_call"]] for i in range(0, len(todo), cfg["per_call"]))
    lock, counters, fatal = threading.Lock(), Counter(labelled=n_labels), []
    transient = defaultdict(int)

    def worker():
        while not stop.is_set():
            with lock:
                if counters["labelled"] >= target or not chunks:
                    return
                rows = chunks.popleft()
            try:
                labs, rej = teacher.label(rows)
            except Stopped:
                return
            except Fatal as e:
                fatal.append(str(e))
                stop.set()
                return
            except ApiError as e:
                key = rows[0]["id"]
                transient[key] += 1
                env.log(f"chunk {key}: {e.kind}; {'retrying later' if transient[key] < 3 else 'giving up for now'}")
                if transient[key] < 3:
                    with lock:
                        chunks.append(rows)
                continue
            for sid, lab in labs.items():
                env.append("labels", {"id": sid, "scores": lab["s"], "drivers": lab.get("k"), "why": lab.get("why"), "alt": lab.get("alt"),
                                      "variant": teacher.variant, "thinking": teacher.thinking, "model": cfg["model"]})
            for sid, why in rej.items():
                env.append("rejected", {"id": sid, "reason": why})
            with lock:
                counters["labelled"] += len(labs)
                counters["rejected"] += len(rej)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(cfg["workers"])]
    for t in threads:
        t.start()
    last, t0 = 0, time.time()
    while any(t.is_alive() for t in threads):
        time.sleep(1)
        if time.time() - last >= (60 if a.verbose else 300):
            last = time.time()
            used, rpd = teacher.limiter.used_today(), teacher.limiter.rpd
            msg = f"labelled {counters['labelled']}/{target}  rejected {counters['rejected']}  requests today {used}/{rpd}  tokens {teacher.stats['total_tokens']}"
            if used >= rpd:
                msg += f"  WAITING for quota reset in {seconds_to_next_day() / 3600:.1f} h"
            env.log(msg)
    if fatal:
        env.log("FATAL: " + fatal[0])
        sys.exit(2)
    n_req = max(1, teacher.stats["requests"])
    env.log(f"done for now: labelled {counters['labelled']}/{target}, rejected {counters['rejected']}, "
            f"{teacher.stats['requests']} requests in {(time.time() - t0) / 60:.1f} min, avg {teacher.stats['total_tokens'] / n_req:.0f} tokens/request, "
            f"errors: { {k: v for k, v in teacher.stats.items() if k.startswith(('errors', 'parse', 'failed'))} }")
    if counters["labelled"] < target and not stop.is_set():
        env.log("target not reached and nothing left to label: generate more states (run_pipeline.py --stage states --more)")


# --------------------------------------------------------------------------- status, export
def cmd_status(env, a):
    cfg = env.cfg
    labels = {r["id"] for r in env.read_jsonl("labels")}
    rej = Counter(r["reason"] for r in env.read_jsonl("rejected"))
    lim = json.load(open(env.p["limiter"])) if os.path.exists(env.p["limiter"]) else {"day": "-", "count": 0}
    per_day = max(1, cfg["rpd"] - cfg["rpd_reserve"]) * cfg["per_call"] * 0.9
    left = max(0, cfg["target"] - len(labels))
    print(f"states {env.count_lines('states')}   labelled {len(labels)}/{cfg['target']}   rejected {sum(rej.values())} {dict(rej)}")
    print(f"requests today ({lim['day']}): {lim['count']}/{cfg['rpd']}   ~{per_day:.0f} situations/day  ->  ~{left / per_day:.1f} days left")
    if os.path.exists(env.p["choice"]):
        print("pilot choice:", json.load(open(env.p["choice"])))


def split_of(sid):
    h = int(hashlib.md5(sid.encode()).hexdigest(), 16) % 100
    return "test" if h < 5 else "val" if h < 10 else "train"


def cmd_export(env, a):
    labels = {r["id"]: r for r in env.iter_jsonl("labels")}
    fam, alts, top, fam_of = Counter(), Counter(), defaultdict(list), {}
    n = 0
    with open(env.p["dataset"], "w", encoding="utf-8") as f:
        for s in env.iter_jsonl("states"):
            fam_of[s["id"]] = s["family"]
            lab = labels.get(s["id"])
            if not lab:
                continue
            soft = [round(x, 4) for x in tt.softmax(lab["scores"], 1.0)]
            f.write(json.dumps({"id": s["id"], "family": s["family"], "split": split_of(s["id"]), "state": s["state"], "cands": s["cands"],
                                "scores": lab["scores"], "soft": soft, "drivers": lab.get("drivers"), "alt": lab.get("alt")},
                               ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
            fam[s["family"]] += 1
            top[s["family"]].append(max(lab["scores"]))
            if lab.get("alt"):
                alts[lab["alt"]] += 1
    rej = Counter()
    for r in env.iter_jsonl("rejected"):
        rej[(fam_of.get(r["id"], "?"), r["reason"])] += 1
    print(f"wrote {n} labelled situations to {env.p['dataset']}")
    print("splits:", dict(Counter(split_of(i) for i in labels)))
    print("\nlabelled per family (and rejected, which can reveal a topic the model refuses or fails on):")
    for k, v in sorted(fam.items(), key=lambda kv: -kv[1]):
        rj = sum(c for (f2, _), c in rej.items() if f2 == k)
        print(f"  {k:22s} {v:6d}   rejected {rj:5d}   mean best score {sum(top[k]) / len(top[k]):.2f}")
    if alts:
        print("\nmost frequent 'missing option' proposals (add them to the candidate generator):")
        for k, v in alts.most_common(15):
            print(f"  {v:4d}  {k}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["probe", "pilot", "run", "status", "export"])
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--target", type=int, default=0)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    env = Env(load_cfg(a.config))
    {"probe": cmd_probe, "pilot": cmd_pilot, "run": cmd_run, "status": cmd_status, "export": cmd_export}[a.cmd](env, a)


if __name__ == "__main__":
    main()
