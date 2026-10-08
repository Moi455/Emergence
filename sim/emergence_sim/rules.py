"""Hard rules shared by the decider and the interactions."""


def romance_ok(sim, a, b):
    """HARD RULE (CLAUDE.md I6): no romance involving anyone under the adult age, ever.
    Plus kin taboo (norm, on by default), orientation, and a plausible age gap."""
    if a.id == b.id or not a.alive or not b.alive:
        return False
    aa, ab = sim.age(a), sim.age(b)
    if aa < sim.ADULT or ab < sim.ADULT:
        return False
    if abs(aa - ab) > 20:
        return False
    if sim.norms["kin_romance_taboo"] and sim.is_kin(a, b):
        return False
    for x, y in ((a, b), (b, a)):
        same = x.sex == y.sex
        if x.orient == 0 and same:
            return False
        if x.orient == 1 and not same:
            return False
    return True
