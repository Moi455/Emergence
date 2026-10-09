#!/usr/bin/env python3
"""memory_service.py - the ENGINE-owned memory of one NPC (never the model's job).

The model only receives the few memories recalled for the current situation
(as tokens). Everything else happens here:
  * store with consolidation of repeated events (30 'chat' events = one record, count 30)
  * forgetting: strength = importance x exp(-age/tau); important and recalled memories last longer;
    'defining' memories never fade; capacity per NPC (light 300, advanced ~1000), weakest evicted first
  * recall: top-K by strength + relevance (entities, place, kinds) + emotion
  * transmission: told memories get lower certainty, drift (honest error) or are falsified (lie)
  * beliefs: lookup(attr, subject) answers 'where does Paul live', 'where is Paul now',
    'how much money has Paul', 'who is the lawyer' from memories, with a confidence
  * contradictions: an observation refuting a told claim lowers that claim and the trust in the teller

  python3 memory_service.py     # runs the self-tests
"""
import math, random, sys

HOUR, DAY = 3600.0, 86400.0
JOB_WEALTH_PRIOR = {"smith": 40, "trader": 60, "farmer": 15, "miner": 20, "woodcutter": 12,
                    "carpenter": 25, "cook": 15, "healer": 30, "hunter": 12, "none": 5}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class MemoryStore:
    def __init__(self, owner, capacity=300, rng=None):
        self.owner, self.capacity = owner, capacity
        self.rng = rng or random.Random(0)
        self.mems, self._n = {}, 0
        self.events = []            # engine events produced here (e.g. claim_refuted)

    # ------------------------------------------------------------------ store
    def add(self, kind, agent=None, target=None, obj=None, place=None, t=0.0, source="seen", told_by=None,
            certainty=1.0, importance=30, valence=0, secret=False, defining=False, payload=None,
            witnesses=None, event_ref=None):
        if not defining:
            for m in self.mems.values():       # consolidation of repeated events
                if (m["kind"], m["agent"], m["target"], m["place"], m["source"], m["told_by"]) == \
                        (kind, agent, target, place, source, told_by) and t - m["t"] < 1800 and not m["defining"]:
                    m["count"] += 1
                    m["t"] = t
                    m["importance"] = max(m["importance"], importance)
                    m["payload"].update(payload or {})
                    return m["id"]
        self._n += 1
        mid = f"M{self._n}"
        self.mems[mid] = dict(id=mid, kind=kind, agent=agent, target=target, obj=obj, place=place, t=t,
                              source=source, told_by=told_by, certainty=certainty, importance=importance,
                              valence=valence, secret=secret, defining=defining, count=1, recalls=0,
                              last_recall=t, payload=dict(payload or {}), distortion=0.0,
                              witnesses=list(witnesses or []), told_to=[], event_ref=event_ref)
        self._evict(t)
        return mid

    # ------------------------------------------------------------- forgetting
    def strength(self, m, now):
        age = max(0.0, now - m["t"])
        tau = (0.5 + m["importance"] / 20.0) * DAY
        tau *= 1 + 0.3 * math.log1p(m["recalls"] + m["count"] - 1)
        s = (m["importance"] / 100.0) * math.exp(-age / tau)
        return max(s, 0.8) if m["defining"] else s

    def _evict(self, now):
        extra = len(self.mems) - self.capacity
        if extra > 0:
            victims = sorted((m for m in self.mems.values() if not m["defining"]), key=lambda m: self.strength(m, now))
            for m in victims[:extra]:
                del self.mems[m["id"]]

    def forget(self, now, floor=0.02):
        gone = [i for i, m in self.mems.items() if self.strength(m, now) < floor]
        for i in gone:
            del self.mems[i]
        return len(gone)

    # ----------------------------------------------------------------- recall
    def recall(self, now, k=8, entities=(), place=None, kinds=()):
        scored = []
        for m in self.mems.values():
            st = self.strength(m, now)
            if st < 0.02:
                continue
            rel = (.6 if (m["agent"] in entities or m["target"] in entities) else 0) + \
                  (.2 if place and m["place"] == place else 0) + (.2 if m["kind"] in kinds else 0)
            scored.append((.5 * st + rel + .2 * abs(m["valence"]) / 100.0, m))
        scored.sort(key=lambda x: -x[0])
        out = [m for _, m in scored[:k]]
        for m in out:
            m["recalls"] += 1
            m["last_recall"] = now
        return out

    def to_token(self, m, now):
        """What the decision model receives for one recalled memory."""
        return {"kind": m["kind"], "source": m["source"], "agent": m["agent"], "target": m["target"],
                "age_days": round((now - m["t"]) / DAY, 2), "certainty": round(m["certainty"], 2),
                "importance": m["importance"], "valence": m["valence"], "defining": m["defining"], "secret": m["secret"]}

    # ----------------------------------------------------------- transmission
    def retell(self, mid, listener, now, teller_trust=0.7, lie=False, alt_place=None):
        """Copy a memory into the listener's store. Honest drift grows with doubt; a lie falsifies the payload."""
        m = self.mems[mid]
        payload, place, dist = dict(m["payload"]), m["place"], m["distortion"]
        if self.rng.random() < .15 * (1 - m["certainty"] + .2):
            payload = {k: (round(v * self.rng.uniform(.8, 1.25)) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                       for k, v in payload.items()}
            dist += .2
        if lie:
            payload = {k: (round(v * self.rng.choice([.3, .5, 2, 3])) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                       for k, v in payload.items()}
            if alt_place:
                place = alt_place
            dist = 1.0
        new = listener.add(m["kind"], m["agent"], m["target"], m["obj"], place, now, "told", told_by=self.owner,
                           certainty=clamp(m["certainty"] * teller_trust, .05, .95), importance=m["importance"] * .6,
                           valence=m["valence"] * .7, payload=payload)
        listener.mems[new]["distortion"] = dist
        listener.mems[new]["event_ref"] = m.get("event_ref")
        if listener.owner not in m["told_to"]:
            m["told_to"].append(listener.owner)       # I remember whom I told
        return new

    # --------------------------------------------------------------- beliefs
    def _about(self, subject, kinds):
        return [m for m in self.mems.values() if m["kind"] in kinds and (m["agent"] == subject or m["target"] == subject)]

    def lookup(self, attr, subject, now, job_hint=None):
        """Belief about `subject`. Returns {value, confidence, source, n} or confidence 0 when nothing is known."""
        none = {"value": None, "confidence": 0.0, "source": None, "n": 0}
        if attr == "where_is":
            w = {}
            for m in self._about(subject, ("seen_at", "told_at")):
                w[m["place"]] = w.get(m["place"], 0) + m["certainty"] * math.exp(-(now - m["t"]) / (2 * HOUR))
            if not w:
                return none
            tot = sum(w.values())
            ranked = sorted(((p, x / tot) for p, x in w.items()), key=lambda z: -z[1])[:3]
            return {"value": ranked, "confidence": round(min(1.0, tot), 2), "source": "seen", "n": len(w)}
        if attr == "home_of":
            w, src = {}, {}
            for m in self._about(subject, ("seen_at", "told_home")):
                if m["kind"] == "seen_at" and not m["payload"].get("night"):
                    continue
                x = m["certainty"] * m["count"] * math.exp(-(now - m["t"]) / (30 * DAY))
                w[m["place"]] = w.get(m["place"], 0) + x
                src[m["place"]] = m["source"] if m["place"] not in src or m["source"] == "seen" else src[m["place"]]
            if not w:
                return none
            best = max(w, key=w.get)
            return {"value": best, "confidence": round(min(1.0, w[best] / 2.5), 2), "source": src[best], "n": len(w)}
        if attr == "wealth_of":
            pts = [(m["payload"]["coins"], m["certainty"] * math.exp(-(now - m["t"]) / (14 * DAY)))
                   for m in self._about(subject, ("saw_money", "told_wealth")) if "coins" in m["payload"]]
            if pts:
                tw = sum(w for _, w in pts)
                est = sum(v * w for v, w in pts) / tw
                conf = min(1.0, tw)
                return {"value": round(est), "confidence": round(conf, 2), "precision": round(.15 + .5 * (1 - conf), 2),
                        "source": "seen", "n": len(pts)}
            prior = JOB_WEALTH_PRIOR.get(job_hint or "none", 10)
            return {"value": prior, "confidence": .05, "precision": .8, "source": "guess", "n": 0}
        if attr == "job_of":
            ms = self._about(subject, ("saw_work", "told_job"))
            if not ms:
                return none
            m = max(ms, key=lambda x: x["certainty"] * x["t"])
            return {"value": m["payload"].get("job"), "confidence": round(m["certainty"], 2), "source": m["source"], "n": len(ms)}
        if attr == "title_holder":          # subject = a title name
            w = {}
            for m in self.mems.values():
                if m["kind"] in ("notice_read", "told_title") and m["payload"].get("title") == subject:
                    h = m["payload"].get("holder")
                    w[h] = w.get(h, 0) + m["certainty"] * math.exp(-(now - m["t"]) / (20 * DAY))
            if not w:
                return none
            tot = sum(w.values())
            ranked = sorted(((h, x / tot) for h, x in w.items()), key=lambda z: -z[1])
            return {"value": ranked[0][0], "confidence": round(min(1.0, tot) * ranked[0][1], 2), "source": "read",
                    "n": len(w), "alternatives": ranked[1:]}
        raise ValueError("unknown attribute " + attr)

    # ----------------------------------------------- what others know (first order)
    def knows(self, other, mid):
        """Does `other` know what memory `mid` says? 'yes' (was there, or I told them), 'no' (I know they were elsewhere), 'unknown'."""
        m = self.mems[mid]
        if other in m["witnesses"] or other in m["told_to"] or other == m["agent"] or other == m["target"]:
            return "yes"
        for o in self.mems.values():
            if o["kind"] == "seen_at" and o["agent"] == other and abs(o["t"] - m["t"]) < 1800:
                return "yes" if o["place"] == m["place"] else "no"
        return "unknown"

    # ------------------------------------------- several versions of one event
    @staticmethod
    def _sig(m):
        return tuple(sorted((k, str(v)) for k, v in m["payload"].items() if k not in ("night", "alt_places")))

    SRC_W = {"seen": 1.0, "read": .8, "told": .6, "inferred": .5}

    def versions(self, event_ref):
        """Every version of one event, merged by content. Contradiction = more than one version."""
        groups = {}
        for m in self.mems.values():
            if m["event_ref"] == event_ref:
                g = groups.setdefault(self._sig(m), {"payload": m["payload"], "support": 0.0, "mids": [], "sources": set()})
                g["support"] += m["certainty"] * self.SRC_W.get(m["source"], .5)
                g["mids"].append(m["id"])
                g["sources"].add(m["source"])
        tot = sum(g["support"] for g in groups.values()) or 1.0
        out = sorted(groups.values(), key=lambda g: -g["support"])
        for g in out:
            g["p"] = round(g["support"] / tot, 2)
            g["sources"] = sorted(g["sources"])
        return out

    def conflict_degree(self, event_ref):
        v = self.versions(event_ref)
        return 0 if len(v) < 2 else len(v) - 1

    def revise(self, event_ref, evidence_payload, now, source="seen"):
        """New evidence about an event: matching versions gain, others lose; wrong tellers are reported."""
        sig = tuple(sorted((k, str(v)) for k, v in evidence_payload.items()))
        evs = []
        for m in list(self.mems.values()):
            if m["event_ref"] != event_ref:
                continue
            if self._sig(m) == sig:
                m["certainty"] = max(m["certainty"], .9 if source == "seen" else .7)
            elif m["source"] != "seen" or source == "seen":
                ev = self.refute(m["id"], now)
                if ev and m["told_by"]:
                    evs.append(ev)
        return evs

    # -------------------------------------------------- deductions (inferred)
    def infer(self, kind, subject, claim, strength, now, basis=(), target=None, importance=40, valence=0):
        """The model's conclusion (or an engine rule) stored as an INFERRED memory, kept apart from what was seen or told."""
        return self.add(kind, agent=subject, target=target, t=now, source="inferred", certainty=strength,
                        importance=importance, valence=valence, payload=dict(claim, basis=list(basis)))

    # ---------------------------------------------------------- reputation
    TRUST_EFFECT = {"theft": -60, "lie_revealed": -50, "promise_broken": -40, "accusation_false": -30,
                    "help_given": 40, "promise_kept": 30, "deal_fair": 20, "gift": 25}
    DANGER_EFFECT = {"strike": 50, "threat": 40, "kill": 90, "murder": 90, "shove": 15, "fight": 30, "defended": -10}

    def reputation(self, subject, dim, now):
        table = self.TRUST_EFFECT if dim == "trust" else self.DANGER_EFFECT
        tot, n = 0.0, 0.0
        for m in self.mems.values():
            if m["agent"] != subject or m["kind"] not in table:
                continue
            w = m["certainty"] * self.SRC_W.get(m["source"], .5) * math.exp(-(now - m["t"]) / (45 * DAY)) * m["count"] ** .5
            tot += table[m["kind"]] * w
            n += w
        return {"value": round(100 * math.tanh(tot / 80.0)), "confidence": round(1 - math.exp(-n), 2), "n_eff": round(n, 2)}

    def place_reputation(self, place, now):
        d, v, taboo, k = 0.0, 0.0, False, 0
        for m in self.mems.values():
            if m["place"] != place:
                continue
            w = m["certainty"] * math.exp(-(now - m["t"]) / (60 * DAY))
            k += 1
            v += m["valence"] * w
            if m["kind"] in ("strike", "kill", "murder", "fire", "collapse", "wild_animal"):
                d += 40 * w
            if m["kind"] in ("kill", "murder", "burial"):
                taboo = True
        return {"danger": round(min(100, d)), "fondness": round(clamp(v / max(1, k), -100, 100)), "taboo": taboo, "n": k}

    # ----------------------------------------------- beliefs about OTHERS' ties
    def link_belief(self, b, c, now):
        pts = [(m["payload"].get("affinity", 0), m["certainty"] * math.exp(-(now - m["t"]) / (60 * DAY)), m["payload"].get("rel"))
               for m in self.mems.values() if m["kind"] == "link_belief" and {m["agent"], m["target"]} == {b, c}]
        if not pts:
            return {"affinity": 0, "confidence": 0.0, "rel": None}
        tw = sum(w for _, w, _ in pts)
        return {"affinity": round(sum(a * w for a, w, _ in pts) / tw), "confidence": round(min(1.0, tw), 2),
                "rel": max(pts, key=lambda x: x[1])[2]}

    def indirect_threat(self, subject, enemies, loved, now):
        """Threat that comes from who `subject` is tied to, not from anything it did to me."""
        thr = 0.0
        for e in enemies:
            lb = self.link_belief(subject, e, now)
            if lb["affinity"] > 30:
                thr += .5 * lb["affinity"] * lb["confidence"]
        for l_ in loved:
            lb = self.link_belief(subject, l_, now)
            if lb["affinity"] < -30:
                thr += .6 * -lb["affinity"] * lb["confidence"]
        thr += max(0, self.reputation(subject, "danger", now)["value"]) * .3
        return round(min(100, thr))

    # --------------------------------------------------------- contradictions
    def refute(self, mid, now):
        """An observation proved a told claim false: drop the claim and report the teller (trust update)."""
        m = self.mems.get(mid)
        if not m:
            return None
        m["certainty"] = min(m["certainty"], .05)
        ev = {"type": "claim_refuted", "teller": m["told_by"], "memory": mid, "t": now}
        self.events.append(ev)
        return ev


# --------------------------------------------------------------------------
def _tests():
    n = 0

    def check(c, msg):
        nonlocal n
        n += 1
        if not c:
            print("FAIL:", msg)
            sys.exit(1)
    t0 = 100 * DAY
    pierre, marie = MemoryStore("Pierre", rng=random.Random(1)), MemoryStore("Marie", rng=random.Random(2))
    # T1: Pierre saw Paul sleeping at house_12 three nights and once in the field today
    for d in (3, 2, 1):
        pierre.add("seen_at", agent="Paul", place="house_12", t=t0 - d * DAY, payload={"night": True}, importance=40)
    pierre.add("seen_at", agent="Paul", place="field_3", t=t0 - 600, payload={"night": False}, importance=20)
    h = pierre.lookup("home_of", "Paul", t0)
    check(h["value"] == "house_12" and h["confidence"] >= .5, "home from repeated night sightings")
    w = pierre.lookup("where_is", "Paul", t0)
    check(w["value"][0][0] == "field_3", "where is Paul now: the latest sighting wins")
    # T2: unknown
    check(marie.lookup("home_of", "Paul", t0)["confidence"] == 0.0, "no knowledge, zero confidence")
    # T3: told, certainty drops
    first = [m for m in pierre.mems.values() if m["kind"] == "seen_at" and m["place"] == "house_12"][0]
    told = pierre.retell(first["id"], marie, t0, teller_trust=.7)
    check(marie.mems[told]["source"] == "told" and marie.mems[told]["certainty"] < 1, "told memory is less certain")
    hm = marie.lookup("home_of", "Paul", t0)
    check(hm["value"] == "house_12" and hm["confidence"] < h["confidence"], "second-hand belief is weaker")
    # T4: a lie, then a refuting observation
    liar, dupe = MemoryStore("Luc", rng=random.Random(3)), MemoryStore("Anna", rng=random.Random(4))
    liar.add("seen_at", agent="Paul", place="house_12", t=t0 - DAY, payload={"night": True}, importance=40)
    lid = list(liar.mems)[0]
    bad = liar.retell(lid, dupe, t0, teller_trust=.9, lie=True, alt_place="cellar_7")
    check(dupe.lookup("home_of", "Paul", t0)["value"] == "cellar_7", "the lie is believed")
    ev = dupe.refute(bad, t0 + HOUR)
    check(ev["teller"] == "Luc" and dupe.mems[bad]["certainty"] <= .05, "refutation lowers the claim and blames the teller")
    # T5: wealth
    pierre.add("saw_money", agent="Paul", t=t0 - 2 * DAY, payload={"coins": 30}, importance=30)
    wl = pierre.lookup("wealth_of", "Paul", t0)
    check(abs(wl["value"] - 30) <= 3 and wl["precision"] < .6, "wealth estimate from a sighting")
    g = marie.lookup("wealth_of", "Paul", t0, job_hint="smith")
    check(g["source"] == "guess" and g["confidence"] < .1, "pure guess is flagged as a guess")
    # T6: forgetting
    s = MemoryStore("S", rng=random.Random(5))
    s.add("chat", agent="X", t=0, importance=5)
    s.add("betrayal", agent="X", t=0, importance=90, defining=True)
    gone = s.forget(60 * DAY)
    check(gone >= 1 and any(m["defining"] for m in s.mems.values()) and not any(m["kind"] == "chat" for m in s.mems.values()), "weak fades, defining stays")
    # T7: recall relevance
    r = pierre.recall(t0, k=3, entities=("Paul",))
    check(all(m["agent"] == "Paul" or m["target"] == "Paul" for m in r), "recall favours the entity at hand")
    # T8: consolidation and capacity
    c = MemoryStore("C", capacity=50, rng=random.Random(6))
    for i in range(30):
        c.add("chat", agent="Y", t=1000 + i * 60)
    check(len(c.mems) == 1 and list(c.mems.values())[0]["count"] == 30, "30 chats = 1 record")
    for i in range(400):
        c.add("seen_at", agent=f"A{i}", place=f"p{i}", t=2000 + i * 4000, importance=10 + i % 50)
    c.add("oath", agent="Z", t=5000, defining=True)
    check(len(c.mems) <= 51 and any(m["kind"] == "oath" for m in c.mems.values()), "capacity respected, defining kept")
    # T9: rumour chain
    a, b, d = MemoryStore("a", rng=random.Random(7)), MemoryStore("b", rng=random.Random(8)), MemoryStore("d", rng=random.Random(9))
    ida = a.add("saw_money", agent="Paul", t=t0, payload={"coins": 100}, importance=60)
    idb = a.retell(ida, b, t0, .8)
    idd = b.retell(idb, d, t0, .8)
    check(d.mems[idd]["certainty"] < b.mems[idb]["certainty"] < a.mems[ida]["certainty"], "certainty decays along the rumour chain")
    # T10: titles
    x = MemoryStore("x")
    x.add("notice_read", t=t0 - DAY, payload={"title": "lawyer", "holder": "Pierre"}, importance=50, certainty=.9)
    th = x.lookup("title_holder", "lawyer", t0)
    check(th["value"] == "Pierre" and th["confidence"] > .5, "who is the lawyer: from a notice that was read")
    x.add("notice_read", t=t0 - 3600, payload={"title": "lawyer", "holder": "Sophie"}, importance=50, certainty=.9, source="read2")
    th2 = x.lookup("title_holder", "lawyer", t0)
    check(th2["confidence"] < th["confidence"] and th2["alternatives"], "two claimants lower the confidence")
    print(f"{n} memory tests passed")


if __name__ == "__main__":
    _tests()
