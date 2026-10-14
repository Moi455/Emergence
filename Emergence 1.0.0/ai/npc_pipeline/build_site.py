#!/usr/bin/env python3
"""build_site.py - construction that cannot get stuck, owned by the ACTION engine.

A building is DATA: a blueprint (position -> block). A build site holds the blueprint, its origin and the
materials delivered so far. Work is always recomputed as the DIFFERENCE between blueprint and world:
  * a block someone destroyed simply comes back as a task
  * a boulder in the way comes back as a 'clear' task
  * missing material becomes a 'needs' list (which the decision model reads and answers by gathering)
Nothing stores 'step 14 of 80', so there is no state to corrupt. Two modes use the same data:
  * hands-on: NPCs place blocks (tool-dependent speed and neatness)
  * ritual / time-lapse: the witch or mason finishes the diff over time once materials are in the stock.

  python3 build_site.py      # self-tests
"""
import random
import sys
from collections import Counter

TOOL_SPEED = {"hands": 1.0, "trowel": 1.5, "shovel": 3.0, "pickaxe": 0.0}      # blocks per tick when placing
TOOL_NEAT = {"hands": 1.0, "trowel": 1.0, "shovel": .5, "pickaxe": 0.0}


def house_blueprint(w=5, d=5, h=3, door="south"):
    """Parametric house: floor, 4 walls, a door gap, roof. y is vertical."""
    bp = {}
    for x in range(w):
        for z in range(d):
            bp[(x, 0, z)] = "plank"
            bp[(x, h + 1, z)] = "plank"
    for y in range(1, h + 1):
        for x in range(w):
            for z in range(d):
                if x in (0, w - 1) or z in (0, d - 1):
                    bp[(x, y, z)] = "wood"
    dx, dz = {"south": (w // 2, d - 1), "north": (w // 2, 0), "east": (w - 1, d // 2), "west": (0, d // 2)}[door]
    for y in (1, 2):
        bp.pop((dx, y, dz), None)
    return bp


class World(dict):
    """position -> block; missing means air. The ground is below y=0."""


class BuildSite:
    def __init__(self, blueprint, origin, world):
        ox, oy, oz = origin
        self.bp = {(x + ox, y + oy, z + oz): b for (x, y, z), b in blueprint.items()}
        self.world = world
        self.stock = Counter()
        self.status = "planned"
        self.events = []

    def tasks(self):
        """Difference between the blueprint and the world, bottom-up."""
        t = []
        for pos, b in self.bp.items():
            cur = self.world.get(pos)
            if cur == b:
                continue
            if cur is not None:
                t.append(("clear", pos, cur))
            t.append(("place", pos, b))
        # blocks inside the footprint that the blueprint does not want (e.g. a boulder in the doorway)
        for pos, b in self.world.items():
            if pos not in self.bp and self._inside(pos):
                t.append(("clear", pos, b))
        t.sort(key=lambda x: (x[1][1], x[1][0], x[1][2], x[0] != "clear"))
        return t

    def _inside(self, pos):
        xs, ys, zs = zip(*self.bp)
        return min(xs) <= pos[0] <= max(xs) and min(ys) <= pos[1] <= max(ys) and min(zs) <= pos[2] <= max(zs)

    def needs(self):
        want = Counter(b for kind, pos, b in self.tasks() if kind == "place")
        return {b: n - self.stock[b] for b, n in want.items() if n > self.stock[b]}

    def done(self):
        return not self.tasks()

    def step(self, workers):
        """workers: list of tools in hand. Returns the events of this tick."""
        ev = []
        queue = self.tasks()
        for tool in workers:
            if not queue:
                break
            kind, pos, b = queue.pop(0)
            if kind == "clear":
                if tool == "hands":
                    ev.append({"type": "blocked", "reason": "cannot_break_by_hand", "pos": pos})
                    continue
                self.world.pop(pos, None)
                self.stock[b] += 1                      # recovered material
                ev.append({"type": "cleared", "pos": pos})
            else:
                if TOOL_SPEED.get(tool, 0) <= 0:
                    ev.append({"type": "blocked", "reason": "tool_cannot_place", "pos": pos})
                    continue
                if self.stock[b] <= 0:
                    ev.append({"type": "blocked", "reason": "missing_material", "material": b})
                    continue
                self.stock[b] -= 1
                self.world[pos] = b
                ev.append({"type": "placed", "pos": pos})
        self.status = "done" if self.done() else ("waiting_materials" if self.needs() and not self.stock else "building")
        self.events += ev
        return ev

    def time_lapse(self, minutes, mason_skill=1.0):
        """Ritual / mason mode: same diff, finished over time, consuming the stock; stops when material runs out."""
        per_min = int(20 * mason_skill)
        for _ in range(minutes):
            n = 0
            for kind, pos, b in self.tasks():
                if n >= per_min:
                    break
                if kind == "clear":
                    self.world.pop(pos, None)
                    self.stock[b] += 1
                elif self.stock[b] > 0:
                    self.stock[b] -= 1
                    self.world[pos] = b
                else:
                    continue
                n += 1
            if self.done() or n == 0:
                break
        self.status = "done" if self.done() else ("waiting_materials" if self.needs() else "building")
        return self.status


# --------------------------------------------------------------------------
def _tests():
    rng = random.Random(4)
    n = 0

    def check(c, msg):
        nonlocal n
        n += 1
        if not c:
            print("FAIL:", msg)
            sys.exit(1)
    bp = house_blueprint()
    # 1) hands-on build with disturbances: vandalism, a boulder in the doorway, a material shortage
    world = World()
    site = BuildSite(bp, (10, 0, 10), world)
    need0 = site.needs()
    check(sum(need0.values()) == len(bp), "needs = every block at the start")
    site.stock.update({"plank": need0["plank"], "wood": need0["wood"] - 12})            # 12 wood short
    door = (10 + 2, 1, 10 + 4)
    world[door] = "boulder"                                                           # unforeseen obstacle
    for tick in range(400):
        site.step(["trowel", "trowel", "shovel"])
        if tick == 40:                                                                  # vandal removes 6 blocks
            for pos in rng.sample([p for p in world if p in site.bp], 6):
                world.pop(pos)
        if site.status == "waiting_materials" or (site.needs() and not site.stock["wood"] and tick > 60):
            break
    check(site.needs().get("wood", 0) > 0, "shortage reported as a needs list")
    check(not site.done(), "unfinished while wood is missing")
    site.stock.update(site.needs())                                                   # the model sent someone to gather what is missing
    for _ in range(400):
        site.step(["trowel", "trowel", "shovel"])
        if site.done():
            break
    check(site.done(), "site completes after the shortage is solved")
    extra = [p for p in world if p not in site.bp and site._inside(p)]
    check(world[door] is not None if door in site.bp else door not in world, "obstacle in the doorway was cleared")
    check(all(world.get(p) == b for p, b in site.bp.items()) and not extra, "world equals blueprint exactly, no stray block")
    check(site.step(["trowel"]) == [] and site.tasks() == [], "idempotent once finished")
    # 2) destruction after completion heals itself
    for p in list(site.bp)[:10]:
        world.pop(p)
    check(len(site.tasks()) == 10, "damage becomes tasks")
    site.stock.update({b: c for b, c in site.needs().items()})
    site.time_lapse(30)
    check(site.done(), "time-lapse repairs the building")
    # 3) hands cannot break blocks; pickaxe cannot place
    s2 = BuildSite(bp, (0, 0, 0), World())
    s2.world[(1, 1, 1)] = "boulder"
    s2.stock.update(s2.needs())
    ev = s2.step(["hands"] * 50)
    check(any(e.get("reason") == "cannot_break_by_hand" for e in ev) or all(e["type"] == "placed" for e in ev), "hands do not clear")
    ev = BuildSite(bp, (0, 0, 0), World()).step(["pickaxe"])
    check(ev and ev[0]["reason"] == "tool_cannot_place", "a pickaxe cannot place")
    # 4) ritual mode: the witch finishes the diff once the cauldron (stock) is full
    w3 = World()
    s3 = BuildSite(bp, (5, 0, 5), w3)
    s3.stock.update(s3.needs())
    check(s3.time_lapse(30) == "done" and all(w3.get(p) == b for p, b in s3.bp.items()), "ritual build completes from the stock")
    s4 = BuildSite(bp, (5, 0, 5), World())
    s4.stock.update({"plank": 10})
    check(s4.time_lapse(30) == "waiting_materials" and "wood" in s4.needs(), "ritual stops and reports what is missing")
    print(f"{n} build tests passed (house of {len(bp)} blocks)")


if __name__ == "__main__":
    _tests()
