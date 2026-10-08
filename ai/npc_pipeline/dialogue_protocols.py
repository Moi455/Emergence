#!/usr/bin/env python3
"""dialogue_protocols.py - how questions and negotiations are RESOLVED by the engine.

The model never invents facts. For a question the engine looks the answer up in the
answerer's memory and tells the model how sure the NPC is ('know') and how private the
topic is ('sens'); the model picks a MODE (truth, vague, lie, refuse, unknown, redirect)
and the engine builds the answer from the real belief. For a negotiation the engine
computes what an offer is worth to each side and keeps the state; the model picks a MOVE.
"""
import random

from memory_service import MemoryStore, HOUR, DAY


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ================================================================ questions
SENS_BASE = {"home_of": 40, "where_is": 20, "wealth_of": 70, "job_of": 10, "title_holder": 5, "partner_of": 30, "secret": 90}
MODES = ["truth", "vague", "lie", "refuse", "unknown", "redirect"]


def build_question(store, answerer, asker, attr, subject, now, affection_to_subject=0, trust_in_asker=0,
                   familiarity_with_asker=50, job_hint=None):
    if subject == answerer:
        belief = {"value": "self", "confidence": 1.0, "source": "self", "n": 1}
    else:
        belief = store.lookup(attr, subject, now, job_hint=job_hint)
    sens = SENS_BASE[attr]
    sens += 25 if affection_to_subject > 40 else 0
    sens -= 20 if trust_in_asker > 40 else 0
    sens += 15 if familiarity_with_asker < 20 else 0
    sens -= 50 if subject == asker else 0
    c = belief["confidence"]
    return {"type": "question", "attr": attr, "subject": subject, "asker": asker, "belief": belief,
            "know": "sure" if c >= .7 else "likely" if c >= .35 else "vague" if c > .06 else "none",
            "sens": int(clamp(sens, 0, 100))}


def _bucket(coins):
    return "poor" if coins < 10 else "modest" if coins < 30 else "comfortable" if coins < 80 else "rich"


def apply_answer(mode, q, rng, alt_values=(), redirect_to=None):
    """Turn the model's chosen MODE into an answer built from the real belief."""
    b, c = q["belief"], q["belief"]["confidence"]
    if mode == "truth" and c <= .06:
        mode = "unknown"                              # nothing to tell: the engine forces honesty about ignorance
    feigned = mode == "unknown" and c >= .35          # claiming ignorance while knowing
    ans = {"mode": mode, "attr": q["attr"], "subject": q["subject"], "content": None, "asserted_conf": 0.0, "feigned_ignorance": feigned}
    v = b["value"]
    if mode == "truth":
        ans["content"], ans["asserted_conf"] = v, c
    elif mode == "vague":
        if q["attr"] == "wealth_of":
            ans["content"] = _bucket(v)
        elif q["attr"] in ("home_of", "where_is"):
            top = v[0][0] if isinstance(v, list) else v
            ans["content"] = top.split("_")[0]          # 'house_12' -> 'house'
        else:
            ans["content"] = "someone"
        ans["asserted_conf"] = c * .6
    elif mode == "lie":
        if q["attr"] == "wealth_of" and v is not None:
            ans["content"] = round(v * rng.choice([.2, .3, 3, 4]))
        elif alt_values:
            ans["content"] = rng.choice(list(alt_values))
        ans["asserted_conf"] = .8
        ans["is_lie"] = True
    elif mode == "redirect":
        ans["content"] = {"ask": redirect_to}
    return ans


def asker_update(asker_store, answerer, ans, trust_in_answerer, now):
    """What the asker keeps. A believed lie becomes a wrong belief; a refusal is remembered as a refusal."""
    attr, subj, mode = ans["attr"], ans["subject"], ans["mode"]
    if mode in ("truth", "vague", "lie") and ans["content"] is not None:
        cert = clamp(trust_in_answerer / 100.0 * .9 + .05, .05, .9) * (1 if mode != "vague" else .7)
        if attr == "home_of":
            return asker_store.add("told_home", agent=subj, place=ans["content"], t=now, source="told", told_by=answerer, certainty=cert, importance=35)
        if attr == "where_is":
            return asker_store.add("told_at", agent=subj, place=ans["content"], t=now, source="told", told_by=answerer, certainty=cert, importance=20)
        if attr == "wealth_of":
            coins = ans["content"] if isinstance(ans["content"], (int, float)) else {"poor": 5, "modest": 20, "comfortable": 50, "rich": 120}[ans["content"]]
            return asker_store.add("told_wealth", agent=subj, t=now, source="told", told_by=answerer, certainty=cert,
                                   importance=30, payload={"coins": coins})
        if attr == "title_holder":
            return asker_store.add("told_title", t=now, source="told", told_by=answerer, certainty=cert,
                                   importance=30, payload={"title": subj, "holder": ans["content"]})
    if mode in ("refuse", "unknown", "redirect"):
        return asker_store.add("refused_info", agent=answerer, target=subj, t=now, source="seen", importance=15,
                               valence=-5 if mode == "refuse" else 0, payload={"attr": attr, "mode": mode})
    return None


# ============================================================ negotiation
PRICES = {"bread": 2, "meat": 6, "apple": 1, "water_jug": 1, "firewood": 3, "coal": 5, "stone": 2, "axe": 25,
          "hoe": 20, "seeds": 2, "cloth": 8, "knife": 15, "coin": 1, "hide": 7}
FOOD = {"bread", "meat", "apple"}
MOVES = ["accept", "concede_small", "concede_big", "hold", "raise", "sweeten", "bluff_walk", "walk"]


def need_factor(npc, good):
    if good in FOOD:
        return npc.get("hunger", 0) / 100.0
    if good in ("firewood", "coal"):
        return max(0, npc.get("fuel_gap", 0)) / 100.0
    if good in ("axe", "hoe", "knife"):
        return max(0, npc.get("tools_gap", 0)) / 100.0
    return 0.0


def worth(npc, good, qty):
    """What `qty` of `good` is worth to this NPC, in coins (market price shaped by its own need)."""
    return PRICES[good] * qty * (1 + need_factor(npc, good))


class Negotiation:
    """Buyer wants `qty` of `good` from the seller for coins. Prices are totals in coins."""

    def __init__(self, buyer, seller, good, qty, rng):
        self.buyer, self.seller, self.good, self.qty, self.rng = buyer, seller, good, qty, rng
        self.market = PRICES[good] * qty
        self.res_buyer = worth(buyer, good, qty)                        # most the buyer will pay
        self.res_seller = PRICES[good] * qty * (.7 + .5 * need_factor(seller, good) * 2)   # least the seller will take
        self.offers, self.status, self.log, self.sweet = [], "open", [], None

    def last(self, by):
        return next((o["price"] for o in reversed(self.offers) if o["by"] == by), None)

    def features(self, whom):
        other = "seller" if whom == "buyer" else "buyer"
        p = self.last(other)
        if p is None:
            return None
        gain = (self.res_buyer - p) if whom == "buyer" else (p - self.res_seller)
        return {"price": p, "gain": int(clamp(100 * gain / max(1, self.market), -100, 100)),
                "fair": "cheap" if p < .85 * self.market else "expensive" if p > 1.15 * self.market else "fair",
                "round": len(self.offers)}

    def move(self, by, mv):
        mine, theirs = self.last(by), self.last("seller" if by == "buyer" else "buyer")
        res = self.res_buyer if by == "buyer" else self.res_seller
        sign = 1 if by == "buyer" else -1                                 # buyer concedes upward, seller downward
        if self.status != "open":
            return None
        if mv == "accept":
            if theirs is None:
                return None
            self.status = "deal"
            self.deal_price = theirs
            self.log.append((by, mv, theirs))
            return theirs
        if mv == "walk" or mv == "bluff_walk":
            if mv == "walk":
                self.status = "walked"
            self.log.append((by, mv, mine))
            return mine
        base = mine if mine is not None else (self.market * (.7 if by == "buyer" else 1.3))
        if mv in ("concede_small", "concede_big") and theirs is not None:
            frac = .25 if mv == "concede_small" else .6
            new = base + frac * (theirs - base)
        elif mv == "raise":
            new = base * (1 - .1 * sign) if by == "seller" else base * .9
            new = base * (1.1 if by == "seller" else .9)
        elif mv == "sweeten":
            self.sweet = {"by": by, "item": "apple" if by == "seller" else "bread"}
            new = base
        else:
            new = base
        new = round(new, 1)
        self.offers.append({"by": by, "price": new})
        self.log.append((by, mv, new))
        return new

    def void(self, reason):
        self.status = "void"
        self.log.append(("engine", "void", reason))


def policy(role, neg, rng):
    """Stub for the model: decides a MOVE from what it is shown (gain, fair, round)."""
    f = neg.features(role)
    if f is None:
        return "hold"
    if f["gain"] >= 5:
        return "accept"
    if f["round"] >= 9:
        return "walk"
    return "concede_big" if f["round"] >= 5 else "concede_small" if rng.random() < .8 else "hold"


def run(neg, rng, max_rounds=12, disturb=None, alt=None):
    """Alternate turns. `disturb(round, neg)` may break the deal (e.g. the goods are sold elsewhere)."""
    neg.move("buyer", "hold")
    neg.move("seller", "hold")
    turn = "buyer"
    for r in range(max_rounds):
        if disturb and disturb(r, neg):
            neg.void("goods_unavailable")
            if alt:
                return alt(neg)
            return neg
        mv = policy(turn, neg, rng)
        neg.move(turn, mv)
        if neg.status != "open":
            break
        turn = "seller" if turn == "buyer" else "buyer"
    return neg


def settle(neg, buyer_inv, seller_inv, buyer_store, seller_store, now):
    """Execute a deal atomically (all or nothing) and write both memories."""
    if neg.status != "deal":
        return False
    price = int(round(neg.deal_price))
    if buyer_inv.get("coin", 0) < price or seller_inv.get(neg.good, 0) < neg.qty:
        neg.void("cannot_pay_or_deliver")
        return False
    buyer_inv["coin"] -= price
    seller_inv["coin"] = seller_inv.get("coin", 0) + price
    seller_inv[neg.good] -= neg.qty
    buyer_inv[neg.good] = buyer_inv.get(neg.good, 0) + neg.qty
    fair = .85 * neg.market <= price <= 1.15 * neg.market
    for st, other in ((buyer_store, "seller"), (seller_store, "buyer")):
        st.add("deal_fair" if fair else "deal_hard", agent=other, t=now, importance=25, valence=15 if fair else -10,
               payload={"good": neg.good, "qty": neg.qty, "price": price})
    return True
