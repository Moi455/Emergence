"""status.py - what a series did: `python3 -m teacher.generator --name NAME --status`.

Read from the journal (one line per request), the quota file and the dataset header lines. Days are QUOTA days (Pacific
time, midnight reset), which is what the daily limits count. Per day and per model: requests (errors apart), input / output /
thought tokens, valid decisions (first reply, after repair), repair rate, refusal codes by family of gestures, share of
passive gestures.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
import time
from collections import Counter, defaultdict

from .dataset import LineMeta
from .quota import LEDGER_NAME, PacificDay, QuotaConfig, QuotaDesk
from .series import AppendFile, SeriesDirectory
from .spec import PASSIVE_GESTURES

# finishReason values (or the "NO_CANDIDATE:" prefix of gemini.py) that mean the model refused on content
BLOCKED_FINISH = ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY", "RECITATION", "NO_CANDIDATE")


def structure_family(seed, index) -> str:
    """The family of structure (docs/14 10.2) of situation (seed, index): conflict, loss, debt... ("?" if unknown)."""
    try:
        from situations.sampler import SituationSampler
        return SituationSampler.structure_of(int(seed), int(index))
    except Exception:    # noqa: BLE001  (a status report never breaks the generator)
        return "?"


def content_refused(record: dict) -> bool:
    """A request the model refused on content: finishReason SAFETY and the like, or an empty reply."""
    finish = str(record.get("finish") or "")
    return finish.startswith(BLOCKED_FINISH) or not str(record.get("raw") or "").strip()


class StatusReport:
    def __init__(self, series: SeriesDirectory, qc: QuotaConfig | None = None, now: float | None = None):
        self.series, self.qc, self.now = series, qc, now if now is not None else time.time()

    # ---- the journal
    def records(self):
        p = self.series.journal
        if not p.exists():
            return
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    yield r

    def compute(self) -> dict:
        days: dict = defaultdict(lambda: defaultdict(lambda: {
            "batches": 0, "repairs": 0, "errors": 0, "prompt": 0, "output": 0, "thoughts": 0, "latency": 0.0, "asked": 0,
            "valid_first": 0, "valid_repair": 0, "sent_to_repair": 0, "codes": Counter(), "families": defaultdict(Counter),
            "gestures": Counter(), "traced": 0, "content": defaultdict(Counter)}))
        for r in self.records():
            day, model = r.get("pday", "?"), r.get("model", "?")
            m = days[day][model]
            if r.get("kind") == "error":
                m["errors"] += 1
                continue
            if r.get("kind") not in ("batch", "repair"):
                continue
            u = r.get("usage", {})
            m["prompt"] += u.get("prompt", 0)
            m["output"] += u.get("output", 0)
            m["thoughts"] += u.get("thoughts", 0)
            m["latency"] += r.get("latency_s", 0.0)
            first = r["kind"] == "batch"
            if first:                                       # content refusals (SAFETY, empty reply) by family of structure
                refused = content_refused(r)
                seed = (r.get("cursor") or [0])[0]
                for x in r.get("results", []):
                    fam = structure_family(seed, x["index"]) if "index" in x else "?"
                    m["content"][fam]["asked"] += 1
                    m["content"][fam]["refused"] += refused
            m["batches" if first else "repairs"] += 1
            for x in r.get("results", []):
                ok = x.get("code") == "ok"
                if first:
                    m["asked"] += 1
                    m["valid_first"] += ok
                else:
                    m["valid_repair"] += ok
                    m["sent_to_repair"] += 1
                    continue                                # families / codes are those of the first pass only
                m["codes"][x.get("code", "?")] += 1
                fam = x.get("family") or "?"
                m["families"][fam]["ok" if ok else x.get("code", "?")] += 1
                if ok:
                    m["gestures"][x.get("gesture", "")] += 1
                    m["traced"] += 1 if x.get("traced") else 0
        return days

    # ---- text
    def text(self) -> str:
        out = [f"series {self.series.name}: {self.series.path}"]
        st = self.series.state
        if st.exists():
            s = json.loads(st.read_text(encoding="utf-8"))
            out.append(f"state: {s.get('valid', 0)} valid labels, {s.get('refused', 0)} refused, {s.get('batches', 0)} batches, "
                       f"{s.get('requests', 0)} requests, {s.get('restarts', 0)} restarts, next situation "
                       f"{s.get('seed', 0)}:{s.get('next_index', 0)}, updated {s.get('updated', '?')}")
        ds = AppendFile(self.series.dataset)
        out.append(f"dataset.jsonl: {ds.count_lines()} lines" + self._headers())
        days = self.compute()
        for day in sorted(days):
            out.append(f"\n== quota day {day} (Pacific)")
            tot = Counter()
            for model, m in sorted(days[day].items()):
                asked = m["asked"]
                valid = m["valid_first"] + m["valid_repair"]
                n_req = m["batches"] + m["repairs"]
                rep_rate = (m["repairs"] / m["batches"]) if m["batches"] else 0
                recovered = (m["valid_repair"] / m["sent_to_repair"]) if m["sent_to_repair"] else 0
                passive = sum(v for g, v in m["gestures"].items() if g in PASSIVE_GESTURES)
                okn = sum(m["gestures"].values())
                out.append(f"  {model}: {n_req} requests ({m['batches']} batches + {m['repairs']} repairs), {m['errors']} errors; "
                           f"tokens in {m['prompt']} / out {m['output']} / thoughts {m['thoughts']}"
                           + (f"; mean {m['prompt'] // n_req} in per request, {m['latency'] / n_req:.1f} s" if n_req else ""))
                out.append(f"    decisions asked {asked}, valid {valid} ({m['valid_first']} at once + {m['valid_repair']} after repair"
                           f"{f'; {valid / asked:.0%} of asked' if asked else ''}); repair requests per batch {rep_rate:.2f}, "
                           f"repair recovered {recovered:.0%}; passive gestures {passive / okn:.0%} of the valid ones" if okn else
                           f"    decisions asked {asked}, valid {valid}")
                if m["traced"] or m["codes"].get("incoherent_trace"):
                    out.append(f"    planner: {m['traced']} valid first-pass decisions with a non-empty trace"
                               f"{f' ({m['traced'] / okn:.0%} of the valid)' if okn else ''}; incoherent_trace refusals "
                               f"{m['codes'].get('incoherent_trace', 0)}")
                blocked = {f: c for f, c in sorted(m["content"].items()) if c["refused"]}
                if blocked:
                    out.append("    content refusals (finishReason SAFETY or empty reply) by family: " + ", ".join(
                        f"{f} {c['refused']}/{c['asked']}" for f, c in blocked.items()))
                if m["codes"]:
                    out.append("    first-pass codes: " + json.dumps(dict(m["codes"].most_common())))
                for fam, c in sorted(m["families"].items()):
                    bad = {k: v for k, v in c.items() if k != "ok"}
                    if bad:
                        out.append(f"    refusals in family {fam or '?'}: {json.dumps(bad)} (of {sum(c.values())})")
                tot.update({"req": n_req, "in": m["prompt"], "out": m["output"], "valid": valid, "asked": asked})
            out.append(f"  day total: {tot['req']} requests, {tot['in']} tokens in, {tot['out']} out, {tot['valid']} valid decisions "
                       f"of {tot['asked']} asked")
        if self.qc is not None:
            desk = QuotaDesk(self.qc, self.series.path.parent / LEDGER_NAME)
            out.append("\n== quota now")
            for row in desk.table(self.now):
                lim = " ".join(f"{k}={v:g}" for k, v in row["limits"].items()) or "unknown"
                learned = f" (learned: {row['learned']})" if row["learned"] else ""
                until = ""
                if row["exhausted_until"]:
                    wait = (row["exhausted_until"] - self.now) / 3600
                    until = f", OUT ({row['why']}) for {wait:.1f} h more, until {PacificDay.key(row['exhausted_until'])} Pacific"
                elif row["blocked_for_s"]:
                    until = f", cooling down {row['blocked_for_s']:.0f} s"
                shared = f" [pool {row['pool']}]" if row["pool"] != row["model"] else ""
                out.append(f"  {row['model']}{shared}: {row['requests']} requests / {row['input_tokens']} tokens today (all series); "
                           f"limits {lim}{learned}{until}")
                if row["probe_log"]:                       # when does the daily quota really reopen? (429 = refused, 200 = reopened)
                    stamp = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M")      # noqa: E731
                    out.append("      daily-quota tries (UTC): " + ", ".join(f"{stamp(t)} {code}" for t, code, _ in row["probe_log"][-8:]))
        return "\n".join(out)

    def _headers(self) -> str:
        counts = Counter()
        try:
            with open(self.series.dataset, encoding="utf-8") as f:
                for line in f:
                    try:
                        counts[LineMeta.of(line).hdr] += 1
                    except Exception:   # noqa: BLE001
                        counts["unreadable"] += 1
        except OSError:
            return ""
        return "; interface:layout " + ", ".join(f"{h}={n}" for h, n in counts.most_common()) if counts else ""
