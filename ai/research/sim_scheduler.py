"""sim_scheduler.py - who thinks when: an event-driven scheduler for 200 decisions/s over 500 NPCs (docs/07, section 3).

  python3 ai/research/sim_scheduler.py            # ~10 s, CPU only, no model: it measures the SCHEDULE, not the brain

The scheduler decides WHEN an NPC thinks, never WHAT it does (no decision rule, D17/D18). Sources of a decision:
  P0 danger      the engine perceives a threat cue (weapon drawn nearby, being hit, fire, scream)   -> within ~1 s
  P1 addressed   someone speaks to the NPC, a request arrives
  P2 gesture end the current gesture reached its stop condition, failed or was blocked (charte section 8)
  P3 notable     a new entity in view, a loud noise ; filtered by the NPC's own PLAN.commitment (a model output)
  P4 heartbeat   nothing happened for max_idle seconds (awake 8 s, asleep 60 s)
Each 100 ms tick takes the highest classes first (then the oldest); nominal 20 per tick (200/s), burst up to 64
per tick when P0 is waiting, the burst is repaid by a token bucket (average stays <= 200/s).
The workload is synthetic (gesture durations, conversation turns, a knife in a tavern, a fire in a village).
Results: ai/research/results/scheduler.json
"""
import heapq
import math
import random
import statistics

from common import save

TICK = 0.1
TALK_M, SCREAM_M, SIGHT_M = 8.0, 60.0, 35.0     # hearing a voice, hearing a scream, seeing a danger
RATE = 200.0
NOMINAL, BURST, BUCKET_MAX = 18, 64, 400.0   # nominal under the refill (20/tick): the bucket recovers (review 10 Oct)
CLASSES = ("P0_danger", "P1_addressed", "P2_gesture_end", "P3_notable", "P4_heartbeat")


class Npc:
    __slots__ = ("id", "village", "asleep", "commitment", "last", "pending", "pending_since", "decisions", "cues", "seen_events", "danger_event", "x", "y")

    def __init__(self, i, rng):
        self.cues = []
        self.seen_events = set()
        self.danger_event = None
        self.id, self.village = i, i // 100
        self.x, self.y = rng.uniform(0, 200), rng.uniform(0, 200)     # metres inside the village (review 10 Oct)
        self.asleep = False
        self.commitment = rng.uniform(0, 10)
        self.last = 0.0
        self.pending = None
        self.pending_since = 0.0
        self.decisions = 0


class Scheduler:
    def __init__(self, n=500, seed=1):
        self.rng = random.Random(seed)
        self.npcs = [Npc(i, self.rng) for i in range(n)]
        self.events = []          # (time, seq, npc, class)
        self.seq = 0
        self.bucket = BUCKET_MAX
        self.latency = {c: [] for c in CLASSES}
        self.cue_latency = {c: [] for c in CLASSES}
        self.bucket_trace = []
        self.per_tick = []
        self.bursts = {}

    def near(self, npc, radius):
        return [o for o in self.npcs[npc.village * 100:(npc.village + 1) * 100]
                if o is not npc and (o.x - npc.x) ** 2 + (o.y - npc.y) ** 2 <= radius * radius]

    def push(self, t, npc, cls, event=None):
        self.seq += 1
        heapq.heappush(self.events, (t, self.seq, npc, cls, event))

    def gesture_duration(self, npc):
        # routine gestures: walking somewhere, a series of strikes, eating... median ~4 s, long tail
        return 30.0 if npc.asleep else min(60.0, self.rng.lognormvariate(math.log(4.0), 0.8))

    def raise_flag(self, t, npc, cls):
        """An engine-side cue arrives. P3 only interrupts if it beats the NPC's own commitment (a model output)."""
        npc.cues.append((t, cls))           # every perception is timed until the NPC's next decision (any class)
        if cls == 3 and self.rng.uniform(0, 10) < npc.commitment * 0.8:
            return
        if npc.pending is None or cls < npc.pending:
            npc.pending_since = t          # latency of a cue is counted from its own arrival
            npc.pending = cls
            if cls == 0:
                self.bursts.setdefault(round(t, 1), []).append(npc.id)

    def decide(self, t, npc):
        cls = npc.pending
        self.latency[CLASSES[cls]].append(t - npc.pending_since)
        for t0, c in npc.cues:              # unbiased: each perception's delay to the next decision, whatever won
            self.cue_latency[CLASSES[c]].append(t - t0)
        npc.cues = []
        if cls == 0 and self.rng.random() < 0.5:   # half of those who react cry out: heard within SCREAM_M
            for o in self.near(npc, SCREAM_M):
                if not o.asleep or self.rng.random() < 0.3:          # a scream wakes some sleepers
                    self.push(t + self.rng.uniform(0.2, 0.6), o, 0, npc.danger_event)
        npc.pending, npc.last = None, t
        npc.decisions += 1
        # the decision starts a gesture; its end (stop condition) is a future P2 ; a talker is answered (P1)
        self.push(t + self.gesture_duration(npc), npc, 2)
        if not npc.asleep and self.rng.random() < 0.12:     # speech: the addressee P1, other hearers in range P3
            hearers = [o for o in self.near(npc, TALK_M) if not o.asleep]
            if hearers:
                addressee = self.rng.choice(hearers)
                for o in hearers:
                    self.push(t + self.rng.uniform(1.0, 3.0), o, 1 if o is addressee else 3)

    def scenario(self, horizon):
        for npc in self.npcs:
            self.push(self.rng.uniform(0, 5), npc, 2)
        t = 0.0
        while t < horizon:                                     # background notable perceptions, ~0.05/s per NPC
            t += self.rng.expovariate(500 * 0.05)
            self.push(t, self.rng.choice(self.npcs), 3)
        dangers = [(600.0, 40, 1), (1200.0, 100, 3)]
        dangers += [(t0, 15, int(t0 // 120) % 5) for t0 in range(180, int(horizon), 120)]   # recurrent smaller dangers
        for k, (t0, size, village) in enumerate(dangers):
            px, py = self.rng.uniform(0, 200), self.rng.uniform(0, 200)
            radius = SIGHT_M * (1.0 + size / 40.0)                   # a big fire is seen from further away
            for npc in self.npcs[village * 100:(village + 1) * 100]:   # those who SEE it, awake
                if (npc.x - px) ** 2 + (npc.y - py) ** 2 <= radius * radius and not npc.asleep:
                    self.push(t0 + self.rng.uniform(0, 0.3), npc, 0, k)

    def night(self, t):
        # one third of the cycle asleep (D30: night 30 min of a 1 h 30 day), staggered by village
        for npc in self.npcs:
            phase = ((t / 5400.0) + npc.village * 0.03) % 1.0
            npc.asleep = phase > 0.667

    def run(self, horizon=2700.0):
        self.scenario(horizon)
        t = 0.0
        while t < horizon:
            t = round(t + TICK, 6)
            if int(t * 10) % 50 == 0:
                self.night(t)
            while self.events and self.events[0][0] <= t:
                t_ev, _, npc, cls, event = heapq.heappop(self.events)
                if event is not None:                      # the same danger perceived again is not a new cue
                    if event in npc.seen_events:
                        continue
                    npc.seen_events.add(event)
                    npc.danger_event = event
                self.raise_flag(t_ev, npc, cls)
            for npc in self.npcs:                               # heartbeat
                if npc.pending is None and t - npc.last > (60.0 if npc.asleep else 8.0):
                    self.raise_flag(t, npc, 4)
            self.bucket = min(BUCKET_MAX, self.bucket + RATE * TICK)
            waiting = sorted((n for n in self.npcs if n.pending is not None), key=lambda n: (n.pending, n.pending_since))
            n_danger = sum(1 for n in waiting if n.pending == 0)
            cap = min(BURST, NOMINAL + n_danger)               # the burst only serves dangers
            cap = int(min(cap, self.bucket, len(waiting)))
            for npc in waiting[:cap]:
                self.decide(t, npc)
            self.bucket -= cap
            self.per_tick.append(cap)
            self.bucket_trace.append(self.bucket)
        return self.report(horizon)

    def report(self, horizon):
        def pct(xs, q):
            xs = sorted(xs)
            return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None
        out = {"decisions_per_s": sum(self.per_tick) / horizon, "max_per_tick": max(self.per_tick)}
        out["per_perception_latency"] = {c: {"n": len(xs), "p50_s": pct(xs, 0.5), "p95_s": pct(xs, 0.95)}
                                         for c, xs in self.cue_latency.items()}
        out["bucket_min"] = min(self.bucket_trace) if self.bucket_trace else None
        out["burst_ticks_served"] = sum(1 for c in self.per_tick if c > NOMINAL)
        out["raised_vs_served"] = {c: {"raised": len(self.cue_latency[c]), "won_a_decision": len(self.latency[c])} for c in CLASSES}
        for c, xs in self.latency.items():
            out[c] = {"n": len(xs), "p50_s": pct(xs, 0.5), "p95_s": pct(xs, 0.95), "p99_s": pct(xs, 0.99),
                      "max_s": max(xs) if xs else None}
        per_npc = [n.decisions / horizon for n in self.npcs]
        out["per_npc_decisions_per_s"] = {"mean": statistics.mean(per_npc), "min": min(per_npc), "max": max(per_npc)}
        return out


def main():
    rep = Scheduler().run()
    for k, v in rep.items():
        print(f"{k:<26} {v}")
    print("saved", save("scheduler.json", rep))


if __name__ == "__main__":
    main()
