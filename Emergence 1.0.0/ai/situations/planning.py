"""planning.py - what the NPC wants over time, with whom, and how he means to get it: groups, goals, plans.

Three builders, in this order:
  * GroupBuilder fills the GROUP records (what he believes of a group he knows: its kind, members, leader, aim, his
    part in it);
  * GoalBuilder writes GOAL: the needs and wishes of the day, the long pursuits that break into sub-goals
    (`parent`), the goals that come from an agreement, and whatever the cause of his waking asks of them (an
    overdue deadline, a goal that seems reached, a meeting time, somebody he was looking for);
  * PlanBuilder writes up to two PLAN records (the reserve the model sees): a chain of 2 to 4 gestures for an
    active goal, with the state it is in (running, suspended, blocked, done), how far the step has got, how many
    times it failed, and a repeat period for a routine.

This BUILDS the context (what he was already doing, what he has in mind); it never decides what he does now:
the model chooses, and the teacher labels. Families of structure (docs/14 10.2) bias what is built, never what is
done: "far goal" favours a long pursuit with sub-goals, "cooperation" a group and a part in it, "debt" an
agreement falling due, and so on. D10: the governor is asked about every proposition and every step.
"""
from __future__ import annotations

import language
from tok2 import Record

from .builders import GOAL_ORIGIN, GOAL_STATUS, KEY, RecordBuilder
from .context import BuildContext
from .plans import PlanSketch, PlanTable

# the families of structure of docs/14 10.2 (share of the situations); a family biases what is built
STRUCTURES = {"far_goal": 0.15, "cooperation": 0.15, "conflict": 0.10, "debt": 0.10, "unequal_info": 0.10,
              "authority": 0.10, "loss": 0.10, "scarcity": 0.10, "ordinary": 0.10}
LADDER_RATE = {"far_goal": 0.95, "scarcity": 0.9, "cooperation": 0.6, "debt": 0.45, "authority": 0.4, "conflict": 0.35,
               "unequal_info": 0.35, "loss": 0.3, "ordinary": 0.25}
COMMIT_GOAL_RATE = {"debt": 0.9, "cooperation": 0.85}                  # any other family: COMMIT_GOAL_DEFAULT
COMMIT_GOAL_DEFAULT = 0.12
WHEN_RATE = 0.08                                                       # a goal with a rendezvous time
LONG_HOURS = (48.0, 500.0)                                             # a long pursuit takes days of game time
CHILD_GROUPS = ("g_household", "g_lineage", "g_community")             # the groups a child belongs to
# how many plans: 0, 1 or 2 (the model sees two PLAN tokens at most)
PLAN_COUNT = {0: 0.30, 1: 0.36, 2: 0.34}
# outcome of the step that ends and wakes him -> (plan status, step progress, attempts)
OUTCOMES = {"done": 0.55, "failed": 0.12, "blocked": 0.13, "interrupted": 0.12, "limit_reached": 0.08}
REPEAT = {"once": 0.87, "each_day": 0.05, "every": 0.05, "each_season": 0.02, "each_year": 0.01}
PERIODS_H = (2, 4, 6, 8, 12, 18, 24, 36, 48, 72, 120)                  # hours of game time (a year is about 4.7 days)
ROUTINE_HEADS = ("works_as", "quality")
OCCASIONS = ("when", "person", "group")
MEMBER_RATE = {"cooperation": 0.85, "authority": 0.7}                  # any other family: 0.4
DEFAULT_MEMBER_RATE = 0.4


class GroupBuilder(RecordBuilder):
    """GROUP: what he believes of the groups he knows. A group known by name or by description is a kind and
    perhaps a size; one he has seen gets members (at most 4, himself included if he belongs), a leader, an aim, his
    role and his part (an agreement he believes he has with it). All of it is belief, not truth."""

    def build(self, c: BuildContext) -> None:
        d, lay = c.d, c.layout
        everyone = [e for e in lay.entries if not e.dead]
        commits: dict[str, list[Record]] = {}
        for r in c.of("COMMIT"):
            commits.setdefault(r.fields["counterparty"], []).append(r)
        for g in c.of("GROUP"):
            f = g.fields
            f["kind"] = d.pick(self._kinds(c))
            if f["known_by"] != "seen":
                if f["known_by"] == "name_only" and d.chance(0.5):
                    f["size"] = d.between(3, 15)
                continue
            owed = commits.get(g.key, [])
            member = c.d.chance(1.0 if any(x.fields["mine"] for x in owed) and d.chance(0.8) else
                                MEMBER_RATE.get(c.structure, DEFAULT_MEMBER_RATE))
            others = d.sample(everyone, d.between(1 if member else 0, 3 if member else 4))
            members = (["me"] if member else []) + [e.key for e in others]
            leader = self._leader(c, members, member)
            f["members"] = members
            f["leader"] = leader
            f["role"] = self._role(c, member, leader)
            f["size"] = len(members) + (d.between(1, 9) if d.chance(0.5) else 0)
            f["present"] = sum(1 for k in members if k == "me" or k in lay.here)
            f["tasks_open"] = sum(1 for x in owed if x.fields["status"] == "open")
            mine = [x.key for x in owed if x.fields["mine"]]
            f["my_task"] = d.pick(mine) if mine else ""
            if leader.startswith("@E"):
                c.leaders[g.key] = leader
            aim = self._aim(c, members, leader)
            if aim is not None:
                f["goal"] = aim
            c.fill("GROUP", f)

    @staticmethod
    def _kinds(c: BuildContext) -> list[str]:
        kinds = c.pools.concepts("group_kind")
        child = [k for k in kinds if k in CHILD_GROUPS]
        return child if c.me.age < 14 and child else kinds

    def _leader(self, c: BuildContext, members: list[str], member: bool) -> str:
        d = c.d
        if member and c.me.age >= 18 and (d.chance(0.12) or (c.structure == "authority" and d.chance(0.4))):
            return "me"
        named = [k for k in members if k != "me"]
        return d.pick(named) if named and d.chance(0.8) else ""      # "" = he believes nobody leads it

    def _role(self, c: BuildContext, member: bool, leader: str) -> str:
        d = c.d
        if leader == "me":
            return "chief"
        if not member:
            return d.pick(("guest", "stranger"))
        roles = c.grammar.words["role_word"]
        if c.structure == "authority" and c.me.age >= 18 and roles and d.chance(0.6):
            return d.pick([r for r in roles if r != "chief"] or roles)
        return "member"

    def _aim(self, c: BuildContext, members: list[str], leader: str) -> str | None:
        """What he believes the group wants or means to do, as a proposition that does not name the group itself
        (the record is the group): about `us` if he belongs to it, else about whoever leads it or one of its members."""
        d, s = c.d, c.session
        who = "us" if "me" in members else leader or next((k for k in members), "")
        if not who or not d.chance(0.65):
            return None
        makers = [lambda: f"(has {who} {s.kind(True)})",
                  lambda: f"(at {who} {d.pick(c.refs.loci)})" if c.refs.loci else None,
                  lambda: f"(did {who} work @PLACE)",
                  lambda: f"(owns {who} {d.pick(c.refs.things)})" if c.refs.things else None]
        d.rng.shuffle(makers)
        for m in makers:
            text = m()
            if text is not None and s.validate(text, "belief") is not None:
                return text
        return None


class Pursuit:
    """Sub-goals of a goal: the propositions that are a step of the same pursuit (a place to be at, something to
    have, a skill to learn). Built from the predicate of the parent, validated by the language and the governor."""

    def __init__(self, c: BuildContext):
        self.c, self.s, self.d = c, c.session, c.d
        self.parser = language.Parser()

    def children(self, parent: str, count: int) -> list[str]:
        node = self.parser.parse(parent)
        makers = list(self._makers(node))
        self.d.rng.shuffle(makers)
        out: list[str] = []
        for text in makers:
            if len(out) >= count:
                break
            if text and text not in self.c.said and text not in out and self.s.validate(text, "goal") is not None:
                out.append(text)
        return out

    def _place(self) -> str | None:
        return self.d.pick(self.c.refs.loci) if self.c.refs.loci else None

    def _have(self) -> str:
        return f"(has me {self.s.kind(True)})"

    def _coins(self) -> str:
        coins = [k for k in self.c.pools.items_by_category.get("currency", ()) if k in self.c.grammar.valid_kinds]
        return f"(has me {self.d.pick(coins)}:{self.d.between(2, 12)})" if coins else self._have()

    def _tool(self) -> str:
        here = set(self.c.refs.kinds)                              # a tool that belongs to this place and this scene
        tools = [k for cat in ("farming", "forestry", "carpentry", "smithing", "kitchen", "fishing", "hunting", "trade")
                 for k in self.c.pools.items_by_category.get(cat, ()) if k in here]
        return f"(has me {self.d.pick(tools)})" if tools else self._have()

    def _makers(self, node):
        at = self._place()
        place = f"(at me {at})" if at else self._have()
        h, a = node.head, node.args
        while h in PlanTable.TIME_MARKS and not isinstance(a[-1], str):
            h, a = a[-1].head, a[-1].args
        if h == "has":
            yield place
            yield self._coins()
            yield self._tool()
        elif h == "owns":
            yield self._coins()
            yield place
        elif h == "works_as":
            yield f"(knows_how me {self.s._w('technique')})"
            yield self._tool()
            yield place
        elif h == "knows_how":
            yield place
            yield self._tool()
        elif h == "at":
            yield self._have()
            yield self._coins()
        elif h == "link":
            yield self._have()
            yield place
        elif h == "state":
            yield self._have()
            yield place
        elif h == "did":
            yield self._have()
            yield place
        else:
            yield self._have()
            yield place


class GoalBuilder(RecordBuilder):
    """GOAL: his wishes and needs, the long pursuits with their sub-goals, the goals that come from an agreement, and
    what the cause of his waking needs from them."""

    def build(self, c: BuildContext) -> None:
        self._wishes(c)
        self._conflict(c)
        self._pursuits(c)
        self._agreements(c)
        self._cause(c)
        for g in c.of("GOAL"):                                      # a pursuit is a priority, a quick wish is not
            g.fields.setdefault("priority", c.d.gauss(4.0, 2.2))

    # ---- slots -------------------------------------------------------------------------------------------------
    @staticmethod
    def _slot(c: BuildContext, fields: dict) -> Record | None:
        """A new goal, or (the budget being full) the place of a goal that matters less. -> the record."""
        goals = c.of("GOAL")
        if len(goals) < c.cap["GOAL"]:
            return c.add(Record("GOAL", f"g:{len(goals) + 1}", c.fill("GOAL", fields)))
        free = [g for g in goals if g.key not in c.keep]
        if not free:
            return None
        g = c.d.pick(free)
        g.fields.clear()
        g.fields.update(c.fill("GOAL", fields))
        return g

    @staticmethod
    def _fresh(c: BuildContext, prop: str, mode: str = "achieve", **extra) -> dict:
        """The fields of an active goal of his own."""
        fields = {"prop": prop, "mode": mode, "status": "active", "origin": "self", "origin_ref": "",
                  "age": c.hours_ago(0.1, 300), "progress": c.d.uniform(0, 0.6, 2)}
        fields.update(extra)
        c.said.add(prop)
        return fields

    # ---- the wishes of the day ---------------------------------------------------------------------------------
    def _wishes(self, c: BuildContext) -> None:
        d = c.d
        sources = c.of("BELIEF") + c.of("MEMORY")
        asked = [r.key for r in c.of("REQUEST")]
        deals = [r.key for r in c.of("COMMIT")]
        k = 0
        for _ in range(c.count("GOAL", 1)):
            got = c.session.goal()
            if got is None or got[0] in c.said:
                continue
            prop, mode = got
            c.said.add(prop)
            origin = c.enum("GOAL", "origin", GOAL_ORIGIN)
            if (origin == "asked" and not asked) or (origin == "agreement" and not deals):
                origin = "self"
            status = c.enum("GOAL", "status", GOAL_STATUS)
            ref = d.pick({"asked": asked, "agreement": deals}[origin]) if origin in ("asked", "agreement") else \
                self._origin_ref(c, prop, sources)
            k += 1
            fields = {"prop": prop, "mode": mode, "status": status, "origin": origin, "origin_ref": ref,
                      "age": c.hours_ago(0.1, 500), "progress": 1.0 if status == "achieved" else d.uniform(0, 0.9, 2),
                      "deadline": c.until(1, 500) if d.chance(0.4) else None}
            c.add(Record("GOAL", f"g:{k}", c.fill("GOAL", fields)))
        for g in c.of("GOAL"):
            if d.chance(WHEN_RATE) and g.fields["status"] == "active":
                self._rendezvous(c, g, c.hours_ago(1, 30))

    @staticmethod
    def _origin_ref(c: BuildContext, prop: str, pool: list[Record]) -> str:
        """A belief or a memory that has something to do with the goal: it mentions one of the same pointers."""
        keys = set(KEY.findall(prop))
        near = [r.key for r in pool if keys & set(KEY.findall(r.fields.get("prop", "")))]
        return c.d.pick(near) if near else ""

    @staticmethod
    def _rendezvous(c: BuildContext, g: Record, hours: float) -> bool:
        """The goal is to be done at a time of day: `(at_time dawn P)`, and `when` is how long until then."""
        parts = c.pools.concepts("daypart")
        if not parts or g.fields["prop"].startswith("(at_time"):
            return False
        text = c.session.validate(f"(at_time {c.d.pick(parts)} {g.fields['prop']})", "goal")
        if text is None:
            return False
        c.said.add(text)
        g.fields["prop"] = text
        g.fields["when"] = hours
        return True

    # ---- a situation about something he wants that another has --------------------------------------------------
    def _conflict(self, c: BuildContext) -> None:
        """Conflict: what he wants is somebody else's (the owner is believed, as everywhere)."""
        if c.structure != "conflict":
            return
        theirs = [t for t, o in c.refs.owners.items() if o and o != "me"]
        if theirs:
            prop = c.session.validate(f"(owns me {c.d.pick(theirs)})", "goal")
            slot = self._slot(c, self._fresh(c, prop, priority=c.d.uniform(5.5, 9.0))) if prop and prop not in c.said else None
            if slot is not None:
                c.keep.add(slot.key)

    # ---- long pursuits and their sub-goals ----------------------------------------------------------------------
    def _pursuits(self, c: BuildContext) -> None:
        d = c.d
        if c.structure == "scarcity" and not any(g.fields["prop"].startswith("(state me") for g in c.of("GOAL")):
            self._need_goal(c)
        if not d.chance(LADDER_RATE.get(c.structure, 0.25)):
            return
        parents = [g for g in c.of("GOAL") if g.fields["status"] in ("active", "paused") and g.fields["mode"] == "achieve"
                   and "parent" not in g.fields]
        d.rng.shuffle(parents)
        pursuit = Pursuit(c)
        for parent in parents[:2 if c.structure == "far_goal" else 1]:
            kids = pursuit.children(parent.fields["prop"], d.between(2, 3) if c.structure == "far_goal" else d.between(1, 2))
            if not kids:
                continue
            c.keep.add(parent.key)
            parent.fields["status"] = "active"
            parent.fields["deadline"] = c.hours_ago(*LONG_HOURS)            # a long pursuit is dated ahead
            parent.fields["priority"] = d.gauss(7.0, 1.2)
            parent.fields["progress"] = d.uniform(0, 0.4, 2)
            for prop in kids:
                self._child(c, parent, prop)

    def _child(self, c: BuildContext, parent: Record, prop: str) -> None:
        d, p = c.d, parent.fields
        status = c.enum("GOAL", "status", GOAL_STATUS)
        ref = p.get("origin_ref", "")
        if ref[:2] in ("b:", "m:"):                                  # a belief or a memory must mention the same things
            ref = self._origin_ref(c, prop, c.of("BELIEF") + c.of("MEMORY"))
        fields = self._fresh(c, prop, status=status, parent=parent.key, origin=p["origin"], origin_ref=ref,
                             age=round(p["age"] * d.rng.uniform(0.1, 0.8), 3),
                             priority=d.clip(p["priority"] + d.rng.uniform(-1.5, 0.5)))
        if status == "achieved":
            fields["progress"] = 1.0
        if d.chance(0.5):
            fields["deadline"] = c.hours_ago(1, LONG_HOURS[0])
        slot = self._slot(c, fields)
        if slot is not None:
            c.keep.add(slot.key)

    # ---- goals that come from an agreement ---------------------------------------------------------------------
    def _agreements(self, c: BuildContext) -> None:
        d = c.d
        rate = COMMIT_GOAL_RATE.get(c.structure, COMMIT_GOAL_DEFAULT)
        for cm in c.of("COMMIT"):
            f = cm.fields
            if f["mine"] and f["status"] == "open" and f["prop"] not in c.said and d.chance(rate):
                prop = c.session.validate(f["prop"], "goal")
                slot = self._slot(c, self._fresh(c, prop, origin="agreement", origin_ref=cm.key, deadline=f["deadline"],
                                                 priority=d.uniform(5.0, 9.0))) if prop else None
                if slot is not None:
                    c.keep.add(slot.key)

    # ---- what the cause of his waking needs ---------------------------------------------------------------------
    @staticmethod
    def _need_goal(c: BuildContext) -> Record | None:
        text = c.session.need_goal(c.d.pick(("exhaustion", "pain"))) or "(state me exhaustion low)"
        if text in c.said:                                           # he already has it in mind: a need comes back
            known = next((g for g in c.of("GOAL") if g.fields["prop"] == text), None)
            if known is not None:
                known.fields["status"] = "active"
                c.keep.add(known.key)
            return known
        slot = GoalBuilder._slot(c, GoalBuilder._fresh(c, text, age=c.hours_ago(0.1, 50), progress=c.d.uniform(0, 0.5, 2)))
        if slot is not None:
            c.keep.add(slot.key)
        return slot

    def _active(self, c: BuildContext) -> list[Record]:
        return [g for g in c.of("GOAL") if g.fields["status"] == "active"]

    def _any_active(self, c: BuildContext) -> Record | None:
        goals = self._active(c)
        return c.d.pick(goals) if goals else self._need_goal(c)

    def _cause(self, c: BuildContext) -> None:
        cause = c.cause
        if cause == "timer":
            self._timer(c)
        elif cause == "goal_check":
            self._goal_check(c)
        elif cause == "occasion":
            self._occasion(c)
        elif cause == "plan":
            goal = self._any_active(c)
            c.focus = goal.key if goal else ""

    def _timer(self, c: BuildContext) -> None:
        """A deadline has passed (a goal's, an agreement's), or a routine plan comes round again."""
        d = c.d
        owed = [x for x in c.of("COMMIT") if x.fields["status"] == "open"]
        variant = d.weighted({"goal": 0.5, "commit": 0.25 if owed else 0.0, "plan": 0.25})
        if variant == "plan":
            c.routine_wake = True
            return
        if variant == "commit":
            late = d.pick(owed)
            late.fields["deadline"] = -c.hours_ago(0.05, 60)
        else:
            late = self._any_active(c)
            if late is None:
                return
            late.fields["deadline"] = -c.hours_ago(0.05, 60)
            late.fields["status"] = "active"
        c.trigger = late.key

    def _goal_check(self, c: BuildContext) -> None:
        """A goal seems reached (its progress arrives at 1): he reads again and writes the verdict himself."""
        goal = self._any_active(c)
        if goal is None:
            return
        goal.fields["progress"] = c.d.uniform(0.97, 1.0, 2)
        goal.fields["status"] = "active"
        c.trigger = c.focus = goal.key

    def _occasion(self, c: BuildContext) -> None:
        """An opportunity: the hour of a rendezvous, somebody he was looking for, a group that gathers."""
        d, lay = c.d, c.layout
        found, goals = {}, {}
        goal = self._any_active(c)
        if goal is not None and self._rendezvous(c, goal, -d.uniform(0.0, 0.2, 3)):
            goal.fields["status"] = "active"
            found["when"] = goals["when"] = goal.key
        sought = [e for e in lay.entries if e.present is not None and not e.dead and e.fields["link"] != "stranger"
                  and e.fields["known_by"] == "seen"]
        if sought and c.refs.loci:
            e = d.pick(sought)
            prop = c.session.validate(f"(at {e.key} {d.pick(c.refs.loci)})", "goal")
            slot = self._slot(c, self._fresh(c, prop, priority=d.uniform(4.0, 8.0))) if prop and prop not in c.said else None
            if slot is not None:
                c.keep.add(slot.key)
                found["person"], goals["person"] = e.key, slot.key
        gathering = [g.key for g in c.of("GROUP") if g.fields.get("present", 0) >= 1 and (g.fields.get("my_task") or g.fields.get("tasks_open"))]
        if gathering:
            found["group"] = d.pick(gathering)
        if found:
            kind = d.pick(sorted(found))
            c.trigger = found[kind]
            if kind in goals:
                c.focus = goals[kind]


class PlanBuilder(RecordBuilder):
    """PLAN: up to two plans, each a chain of 2 to 4 gestures for an active (or paused) goal, in the state the engine
    would have recorded it: running (the gesture he chose is the next one), suspended (he chose another), blocked (a
    gesture did nothing he could perceive), done (a routine that ended and comes round again)."""

    def build(self, c: BuildContext) -> None:
        d, cap = c.d, c.cap["PLAN"]
        goals = [g for g in c.of("GOAL") if g.fields["status"] in ("active", "paused")]
        needed = c.cause == "plan" or c.routine_wake
        if not goals and needed:
            goals = [g for g in (GoalBuilder._need_goal(c),) if g is not None]
        want = max(d.weighted(PLAN_COUNT), 1 if needed or c.cause == "goal_check" and d.chance(0.7) else 0)
        want = min(want, cap)
        order = self._order(c, goals)
        table = PlanTable(c.pools, c.grammar.chooser)
        view = c.scene_view()
        sketches: list[tuple[Record, PlanSketch]] = []
        for attempt in range(2):
            for g in order:
                if len(sketches) >= want:
                    break
                if any(g is x for x, _ in sketches):
                    continue
                got = table.make(d, g.fields["prop"], view, c.parties)
                if got is not None:
                    sketches.append((g, got))
            if sketches or not needed or attempt:
                break
            more = GoalBuilder._need_goal(c)                      # no active goal can be served: a need to serve
            order = ([more] if more is not None else []) + order
        running = False
        for i, (goal, sketch) in enumerate(sketches):
            running = self._write(c, i, goal, sketch, first=i == 0, running=running)
        have = {r.fields["goal"] for r in c.of("PLAN") if r.fields["status"] != "abandoned"}
        for g in c.of("GOAL"):
            g.fields["has_plan"] = g.key in have

    @staticmethod
    def _order(c: BuildContext, goals: list[Record]) -> list[Record]:
        """The goal that wakes him first, then the sub-goals (the leaves of a pursuit), then the rest."""
        c.rng.shuffle(goals)
        parents = {g.fields.get("parent") for g in c.of("GOAL")}
        goals.sort(key=lambda g: (g.key != c.focus, g.fields["status"] != "active", g.key in parents))
        return goals

    def _write(self, c: BuildContext, i: int, goal: Record, sketch: PlanSketch, first: bool, running: bool) -> bool:
        d = c.d
        status, progress, attempts = self._state(c, first, running, goal)
        repeat, period = self._repeat(c, goal, first)
        if first and c.routine_wake:
            repeat, period = d.weighted({"every": 0.5, "each_day": 0.5}), None
            status, progress, attempts = d.weighted({"done": 0.7, "suspended": 0.3}), 1.0, 0
            if goal.fields["status"] == "paused":
                status = "suspended"
            if repeat == "every":
                period = d.pick(PERIODS_H)
        n = len(sketch.steps)
        k = n - 2 if status == "done" else d.between(0, n - 2)         # he is on the step k; the next one is k + 1
        steps = list(sketch.steps)
        fields = {"step": steps[k], "next": steps[k + 1], "goal": goal.key, "target": sketch.main, "steps": steps,
                  "step_targets": sketch.step_targets()[:4], "status": status, "progress": progress, "attempts": attempts,
                  "repeat": repeat, "commitment": d.uniform(1.0, 9.0)}
        if period is not None:
            fields["repeat_period"] = period
        if sketch.speaks_to is not None:
            said = self._says(c, sketch.speaks_to)
            if said is not None:
                fields["says"] = said
        c.add(Record("PLAN", f"p:{i + 1}", c.fill("PLAN", fields)))
        if first and c.routine_wake:
            c.trigger = f"p:{i + 1}"                                   # the period of the routine wakes him
        return running or status == "running"

    def _state(self, c: BuildContext, first: bool, running: bool, goal: Record) -> tuple[str, float, int]:
        """-> (status, progress of the step, failed attempts). The plan that wakes him has just ended a step."""
        d = c.d
        if goal.fields["status"] == "paused":
            return "suspended", d.uniform(0, 0.8, 2), 0
        if first and c.cause == "plan":
            c.outcome = d.weighted(OUTCOMES)
            return {"done": ("running", d.uniform(0.97, 1.0, 2), 0),
                    "failed": ("running", d.uniform(0.2, 0.9, 2), d.between(1, 2)),
                    "blocked": ("blocked", d.uniform(0.0, 0.6, 2), d.between(1, 3)),
                    "interrupted": ("suspended", d.uniform(0.1, 0.9, 2), 0),
                    "limit_reached": ("running", d.uniform(0.6, 1.0, 2), d.between(0, 1))}[c.outcome]
        if first and c.cause == "goal_check" and goal.key == c.focus:
            return "done", 1.0, 0                                       # it ended, and the goal seems reached
        roll = d.rng.random()
        if roll < 0.08:
            return "blocked", d.uniform(0.0, 0.7, 2), d.between(1, 3)
        if running or roll < 0.35 or not first and roll < 0.85:
            return "suspended", d.uniform(0.0, 0.85, 2), 0
        return "running", d.uniform(0.0, 0.9, 2), 1 if d.chance(0.1) else 0

    def _repeat(self, c: BuildContext, goal: Record, first: bool) -> tuple[str, int | None]:
        """A routine (his trade, a thing to keep true) comes round again; most plans are once."""
        d = c.d
        routine = goal.fields["mode"] == "maintain" or any(goal.fields["prop"].lstrip("(").startswith(h) for h in ROUTINE_HEADS)
        weights = dict(REPEAT)
        if routine:
            weights.update({"once": 0.3, "each_day": 0.35, "every": 0.2, "each_season": 0.1, "each_year": 0.05})
        repeat = d.weighted(weights)
        return repeat, (d.pick(PERIODS_H) if repeat == "every" else None)

    @staticmethod
    def _says(c: BuildContext, to: str) -> str | None:
        """What he means to say when he gets to the step `speak`: a full utterance in his own terms."""
        d, s = c.d, c.session
        makers = [lambda: f"(offer (did me give {s.kind(gift=True)} (to {to})))",
                  lambda: f"(ask (at {s.someone() or to} where))",
                  lambda: f"(request (did you go {d.pick(c.refs.loci)}))" if c.refs.loci else None,
                  lambda: f"(request (did you give {s.kind(gift=True)} (to me)))"]
        d.rng.shuffle(makers)
        for m in makers:
            text = m()
            if text is not None and s.validate(text, "request") is not None:
                return text
        return None
