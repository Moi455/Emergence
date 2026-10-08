#!/usr/bin/env python3
"""plan_contract.py - contract between the DECISION engine (AI) and the ACTION engine.

The decision engine emits a PLAN: a short program of function calls with
"until" (stop with success) and "interrupt_if" (stop and wake the decision
engine) conditions. The action engine executes it alone, tick after tick, and
only calls the decision engine again when the plan ends or is interrupted.

  python3 plan_contract.py          # runs the self-tests
"""
import json, re, sys

MAX_STEPS = 6
MAX_COND = 3

DIRS = ["forward", "back", "left", "right", "up", "down"]
TOOLS = ["pickaxe", "shovel", "trowel", "axe", "hoe", "hands"]

# Tool physics (used by the action engine and by the scripted work expert).
# dig_*: removing blocks.  place_*: putting blocks/material back.
TOOL_TABLE = {
    "pickaxe": dict(dig_speed=3, dig_shape="irregular hole (blocks scatter)", dig_volume=1, place=None,
                    note="fast, messy: a hole, never a straight square tunnel"),
    "shovel":  dict(dig_speed=2, dig_shape="clean cubes, large", dig_volume=3, place="big untidy piles",
                    note="clean big cubes; places big messy heaps"),
    "trowel":  dict(dig_speed=1, dig_shape="fine, precise", dig_volume=1, place="fine, precise",
                    note="slow; digs and places finely; used for construction"),
    "axe":     dict(dig_speed=0, dig_shape=None, dig_volume=0, place=None, note="cuts wood only"),
    "hoe":     dict(dig_speed=0, dig_shape=None, dig_volume=0, place=None, note="tills soil only"),
    "hands":   dict(dig_speed=0, dig_shape=None, dig_volume=0, place="finest",
                    note="cannot break blocks, only flowers, fruits, vegetables; finest placing"),
}
HAND_BREAKABLE = ["flower", "fruit", "vegetable"]

# --------------------------------------------------------------------------
# Function library.  args: name:type ; type codes
#   E entity   I item   T tool   B block/material   P place   D direction
#   N integer 1..64   C concept (any registry word, incl. user-made titles)
#   F frame (speech content)   M memory id   O poll/notice/document id
#   X free token from a closed list given in desc
# --------------------------------------------------------------------------
FUNCTIONS = {}


def F(id_, cat, args="", core=True, desc="", needs=None):
    spec = {}
    for part in [p for p in args.split(",") if p]:
        name, typ = part.split(":")
        opt = typ.endswith("?")
        spec[name] = dict(type=typ.rstrip("?"), optional=opt)
    FUNCTIONS[id_] = dict(id=id_, cat=cat, args=spec, core=core, desc=desc, needs=needs)


# body
F("eat", "body", "item:I"); F("drink", "body", "item:I?,place:P?"); F("sleep", "body", "place:P?")
F("rest", "body")
# movement
F("go_to", "move", "place:P?,entity:E?"); F("follow", "move", "entity:E"); F("approach", "move", "entity:E")
F("avoid", "move", "entity:E"); F("flee", "move", "entity:E?,place:P?"); F("wander", "move")
F("wait", "move", "secs:N?"); F("hide", "move", "place:P?", False); F("return_home", "move")
# tools and voxel work (the verb depends on the tool: see TOOL_TABLE)
F("equip", "work", "tool:T", True, "take a tool in hand (the action engine inserts it when missing)")
F("unequip", "work")
F("dig", "work", "dir:D,length:N,tool:T,width:N?,depth:N?", True,
  "remove blocks along a direction; pickaxe/shovel/trowel only", needs=["pickaxe", "shovel", "trowel"])
F("place", "work", "block:B,pattern:X?,tool:T?", True,
  "put blocks; pattern in {pile, line, wall, floor, fill}", needs=None)
F("till", "work", "place:P?,tool:T?", True, needs=["hoe"])
F("plant", "work", "seed:I,place:P?")
F("harvest", "work", "kind:X,place:P?", True, "kind in {flower, fruit, vegetable}; by hand")
F("cut", "work", "target:B,tool:T?", True, "trees and wood", needs=["axe"])
F("fetch_water", "work", "place:P?")
F("craft", "work", "recipe:C"); F("build", "work", "blueprint:C,place:P?", False, needs=["trowel"])
F("repair", "work", "target:C", False); F("tend_crop", "work", "place:P?", False)
F("hunt", "work", "target:C", False)
# inventory / property
F("pick_up", "inventory", "item:I"); F("drop", "inventory", "item:I")
F("store", "inventory", "item:I,place:P"); F("take_from", "inventory", "place:P,item:I")
F("give", "inventory", "entity:E,item:I"); F("steal", "inventory", "entity:E?,place:P?,item:I")
F("destroy", "inventory", "target:C", False); F("claim", "inventory", "item:I?,place:P?", False)
# speech acts (all are `say` with an act type; frames are built by the parser/engine)
F("greet", "speech", "entity:E"); F("chat", "speech", "entity:E")
F("inform", "speech", "entity:E,memory:M?,fact:F?", True, "share a memory (maybe distorted) or a claim")
F("deceive", "speech", "entity:E,fact:F"); F("ask", "speech", "entity:E,topic:C?,fact:F?,attr:X?,subject:E?", True, "attr in {home_of, where_is, wealth_of, job_of, partner_of, title_holder}")
F("propose", "speech", "entity:E,proposal:F"); F("request", "speech", "entity:E,proposal:F")
F("order", "speech", "entity:E,proposal:F"); F("accept", "speech", "proposal:O")
F("refuse", "speech", "proposal:O"); F("promise", "speech", "entity:E,proposal:F")
F("threaten", "speech", "entity:E,fact:F"); F("accuse", "speech", "entity:E,fact:F")
F("apologize", "speech", "entity:E"); F("thank", "speech", "entity:E"); F("compliment", "speech", "entity:E")
F("insult", "speech", "entity:E"); F("warn", "speech", "entity:E,fact:F"); F("call_for_help", "speech")
F("comfort", "speech", "entity:E"); F("forgive", "speech", "entity:E"); F("teach", "speech", "entity:E,skill:C", False)
# diplomacy and pressure
F("interrogate", "diplomacy", "entity:E,topic:C"); F("bribe", "diplomacy", "entity:E,offer:F")
F("answer", "diplomacy", "entity:E,query:O,mode:X", True, "mode in {truth, vague, lie, refuse, unknown, redirect}; the engine builds the content from the real belief")
F("blackmail", "diplomacy", "entity:E,memory:M")
F("negotiate", "diplomacy", "entity:E,move:X,sweetener:I?", True, "move in {concede_small, concede_big, hold, raise, sweeten, bluff_walk, walk}; the engine computes the figures")
F("lobby", "diplomacy", "entity:E,topic:C", False)
# documents and politics (titles are data: a name + what NPCs attach to it)
F("read", "politics", "doc:O"); F("post_notice", "politics", "content:F,board:P?")
F("tear_down_notice", "politics", "doc:O"); F("publish", "politics", "content:F", False, "newspaper issue")
F("write_letter", "politics", "entity:E,content:F", False)
F("call_vote", "politics", "question:F,options:F"); F("vote", "politics", "poll:O,option:X", True, "option = candidate id or blank")
F("campaign", "politics", "entity:E,audience:E?"); F("claim_title", "politics", "title:C")
F("contest_claim", "politics", "entity:E,title:C"); F("endorse", "politics", "entity:E,title:C")
F("appoint", "politics", "entity:E,title:C"); F("dismiss", "politics", "entity:E,title:C")
F("create_title", "politics", "name:C,duties:F?", True, "a title is only a name plus what people attach to it"); F("decree", "politics", "rule:F")
F("enforce", "politics", "rule:F,entity:E"); F("summon", "politics", "entity:E")
F("delegate", "politics", "task:F,entity:E", False)
# intimacy (adults only; engine-enforced)
F("flirt", "intimacy", "entity:E"); F("kiss", "intimacy", "entity:E")
F("embrace", "intimacy", "entity:E", True, "non-romantic hug allowed for any age")
F("be_intimate", "intimacy", "entity:E", True, "adults, mutual, private place only")
# concealment, groups, jobs, construction (extension: data model specified, not in the first tranche)
F("conceal", "inventory", "item:I,place:P", False, "hide an item on purpose")
F("found_group", "politics", "name:C,purpose:F?", False); F("join_group", "politics", "group:C", False)
F("leave_group", "politics", "group:C", False)
F("post_job", "politics", "task:F,pay:F", False); F("hire", "politics", "entity:E,task:F,pay:F", False)
F("start_build", "work", "blueprint:C,place:P", False); F("contribute", "work", "site:O", False)
F("supply", "work", "site:O,item:I", False)
# conflict
F("attack", "conflict", "entity:E,mode:X", True, "mode in {shove, strike, armed, lethal}")
F("defend", "conflict", "entity:E?"); F("chase", "conflict", "entity:E"); F("restrain", "conflict", "entity:E", False)
F("expel", "conflict", "entity:E,place:P?")
# care
F("heal", "care", "entity:E", False); F("assist", "care", "entity:E,task:C?")
# attention
F("observe", "attention", "entity:E?,place:P?"); F("search", "attention", "entity:E?,item:I?,place:P?")
F("eavesdrop", "attention", "entity:E", False); F("investigate", "attention", "place:P", False)
# leisure
F("leisure", "leisure", "activity:C,entity:E?"); F("pray", "leisure", "", False); F("mourn", "leisure", "", False)
# commitment
F("accompany", "commit", "entity:E"); F("break_commitment", "commit", "commitment:O"); F("continue", "commit")

# --------------------------------------------------------------------------
# Conditions.  name -> number of args
# until: stop successfully when true.  interrupt_if: stop and wake the AI.
# --------------------------------------------------------------------------
CONDITIONS = {
    "found": 1,            # found(ore) / found(gold) while digging or searching
    "sees": 1,             # sees(danger) / sees(E3) / sees(animal)
    "hears": 1,            # hears(noise) / hears(call_for_help)
    "hp_below": 1, "hunger_above": 1, "thirst_above": 1, "fatigue_above": 1,
    "tool_worn": 1, "tool_broken": 0, "inventory_full": 0,
    "entity_near": 2,      # entity_near(E3, 5)
    "attacked": 0, "obstacle": 0, "unsafe": 0,
    "time_after": 1,       # game minutes since midnight
    "elapsed_over": 1,     # seconds of game time
    "reached": 1, "addressed": 0, "message_from": 1, "done": 0,
}
COND_RE = re.compile(r"^(\w+)(?:\((.*)\))?$")


def parse_condition(s):
    m = COND_RE.match(s.strip())
    if not m:
        return None
    name, args = m.group(1), m.group(2)
    argl = [a.strip() for a in args.split(",")] if args else []
    return name, argl


def validate_plan(plan, check_args=True):
    """Return a list of error strings (empty = valid)."""
    errs = []
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["no_steps"]
    if len(steps) > MAX_STEPS:
        errs.append("too_many_steps")
    for i, st in enumerate(steps):
        f = st.get("f")
        spec = FUNCTIONS.get(f)
        if spec is None:
            errs.append(f"step{i}:unknown_function:{f}")
            continue
        args = st.get("a", {})
        if check_args:
            for name, a in spec["args"].items():
                if name not in args and not a["optional"]:
                    # a spec with all-optional alternatives (go_to place|entity) must have at least one
                    errs.append(f"step{i}:{f}:missing:{name}")
            for name, val in args.items():
                if name not in spec["args"]:
                    errs.append(f"step{i}:{f}:unknown_arg:{name}")
                    continue
                t = spec["args"][name]["type"]
                if t == "D" and val not in DIRS:
                    errs.append(f"step{i}:{f}:bad_dir")
                if t == "T" and val not in TOOLS:
                    errs.append(f"step{i}:{f}:bad_tool")
                if t == "N" and not (isinstance(val, int) and 1 <= val <= 64):
                    errs.append(f"step{i}:{f}:bad_number")
        for key in ("until", "interrupt_if"):
            conds = st.get(key, [])
            if len(conds) > MAX_COND:
                errs.append(f"step{i}:too_many_{key}")
            for c in conds:
                p = parse_condition(c)
                if p is None or p[0] not in CONDITIONS or len(p[1]) != CONDITIONS[p[0]]:
                    errs.append(f"step{i}:bad_condition:{c}")
        if f == "dig" and args.get("tool") in ("axe", "hoe", "hands"):
            errs.append(f"step{i}:dig_with_wrong_tool")
        if f == "harvest" and args.get("kind") not in HAND_BREAKABLE:
            errs.append(f"step{i}:harvest_kind")
        if f == "place" and args.get("pattern") not in (None, "pile", "line", "wall", "floor", "fill"):
            errs.append(f"step{i}:place_pattern")
    if plan.get("on_done", "report") not in ("report", "routine"):
        errs.append("bad_on_done")
    return errs


def resolve_preconditions(plan, inventory, tool_in_hand=None):
    """What the ACTION engine does before running: insert missing equip steps,
    or fail with a reason. Returns (steps, error or None)."""
    out, hand = [], tool_in_hand
    for st in plan["steps"]:
        spec = FUNCTIONS[st["f"]]
        want = st.get("a", {}).get("tool")
        if st["f"] == "equip":
            hand = st["a"]["tool"]
        elif spec["needs"]:
            if want is None:
                want = hand if hand in spec["needs"] else None
            if want is None:
                cand = next((t for t in spec["needs"] if t in inventory), None)
                if cand is None:
                    return out, f"missing_tool:{'|'.join(spec['needs'])}"
                want = cand
            if want not in spec["needs"]:
                return out, f"wrong_tool:{want}"
            if hand != want:
                if want not in inventory:
                    return out, f"missing_tool:{want}"
                out.append({"f": "equip", "a": {"tool": want}, "auto": True})
                hand = want
        out.append(st)
    return out, None


# --------------------------------------------------------------------------
# Self-tests
# --------------------------------------------------------------------------
EXAMPLE_PICKAXE = {
    "steps": [
        {"f": "equip", "a": {"tool": "pickaxe"}},
        {"f": "dig", "a": {"dir": "forward", "length": 15, "tool": "pickaxe"},
         "until": ["found(gold)"], "interrupt_if": ["hp_below(30)", "sees(danger)", "tool_broken"]},
    ],
    "on_done": "report",
}


def _tests():
    n = 0

    def check(cond, msg):
        nonlocal n
        n += 1
        if not cond:
            print("FAIL:", msg)
            sys.exit(1)
    check(validate_plan(EXAMPLE_PICKAXE) == [], "example plan valid")
    bad = json.loads(json.dumps(EXAMPLE_PICKAXE))
    bad["steps"][1]["a"]["tool"] = "hands"
    check("step1:dig_with_wrong_tool" in validate_plan(bad), "hands cannot dig")
    bad["steps"][1]["a"]["tool"] = "pickaxe"
    bad["steps"][1]["interrupt_if"] = ["hp_below"]
    check(any("bad_condition" in e for e in validate_plan(bad)), "condition arity")
    check("step0:unknown_function:teleport" in validate_plan({"steps": [{"f": "teleport"}]}), "unknown fn")
    # preconditions
    plan = {"steps": [{"f": "dig", "a": {"dir": "down", "length": 5, "tool": "shovel"}}]}
    steps, err = resolve_preconditions(plan, inventory=["shovel", "bread"])
    check(err is None and steps[0]["f"] == "equip" and steps[0]["auto"], "auto equip")
    steps, err = resolve_preconditions(plan, inventory=["bread"])
    check(err == "missing_tool:shovel", "missing tool reported")
    harvest = {"steps": [{"f": "harvest", "a": {"kind": "vegetable"}}]}
    check(validate_plan(harvest) == [], "harvest by hand")
    check(validate_plan({"steps": [{"f": "harvest", "a": {"kind": "stone"}}]}) != [], "hands cannot harvest stone")
    # a political plan
    pol = {"steps": [{"f": "post_notice", "a": {"content": "claim:mayor"}}, {"f": "campaign", "a": {"entity": "E1"}}]}
    check(validate_plan(pol) == [], "political plan")
    print(f"{n} contract tests passed; {len(FUNCTIONS)} functions "
          f"({sum(f['core'] for f in FUNCTIONS.values())} core), {len(CONDITIONS)} conditions")


if __name__ == "__main__":
    _tests()
