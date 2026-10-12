"""layout.py - who is in the NPC's mind and under which key: the persons whose files he has (@E1…), the ones he
knows but whose files the context selector left out (ghosts), the things he sees (@T…), what he carries, the
places and groups he knows.

The order is the one the teacher relies on to map keys to the true scene: the persons present (known or within
15 m) first, then the absent ones, cut at the budget of the ENTITY type; the rest are ghosts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .scene import Person, Present, Scene


@dataclass
class Entry:
    """A person of the NPC's mind: his key, the truth about him, and what he really is to the NPC."""
    key: str
    person: Person
    link: str                                        # the TRUE link (the file may say otherwise)
    present: Present | None = None
    fields: dict = field(default_factory=dict)       # his ENTITY fields, once built
    believed_age: float | None = None                # the age the NPC believes of a person who is not here


class Layout:
    def __init__(self, scene: Scene, caps: dict, n_loci: int, n_groups: int):
        every = [(x.person, x.link, x) for x in scene.present if x.known or x.dist < 15] + [(p, l, None) for p, l in scene.absent]
        filed, overflow = every[:caps["ENTITY"]], every[caps["ENTITY"]:]
        self.entries = [Entry(f"@E{i + 1}", p, l, x) for i, (p, l, x) in enumerate(filed)]
        self.by_pid = {e.person.pid: e for e in self.entries}
        ghosts = [(p, l) for p, l, _ in overflow] + list(scene.ghosts)
        self.ghosts = [Entry(f"@E{len(self.entries) + 1 + i}", p, l) for i, (p, l) in enumerate(ghosts)]
        self.things = scene.things[:caps["THING"]]
        self.tkeys = [f"@T{i + 1}" for i in range(len(self.things))]
        self.carried = scene.carried[:caps["INV"]]
        self.ikeys = [f"@T{len(self.things) + i + 1}" for i in range(len(self.carried))]
        self.loci = [f"@L{i + 1}" for i in range(n_loci)]
        self.groups = [f"@G{i + 1}" for i in range(n_groups)]
        self.pkeys = [e.key for e in self.entries]
        self.here = [e.key for e in self.entries if e.present is not None]

    def people(self, me: Person) -> dict[str, Person]:
        """key -> the true person, 'me' and the ghosts included."""
        return {"me": me} | {e.key: e.person for e in self.entries} | {g.key: g.person for g in self.ghosts}
