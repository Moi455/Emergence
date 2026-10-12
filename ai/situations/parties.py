"""parties.py - the governor's view of who is in a scene, on the GENERATOR side.

A `Party` (governor.py) carries the real age, the age the NPC believes, the apparent age and whether the person is
resolved (a seen, recognised file). The book is filled while the mind is built: the real age comes from the true
scene, the apparent one from the NPC's own ENTITY record. DENY BY DEFAULT: a person whose file carries no seen
age (absent, ghost) is a possible minor. audit.py builds its own parties again from the finished records.
"""
from __future__ import annotations

from governor import THING, UNKNOWN, Party

from .scene import Person


class PartyBook:
    THING_PREFIXES = ("@T", "@L", "@PLACE", "@V")

    def __init__(self, me: Person):
        self.truth: dict[str, Person] = {"me": me}
        self.parties: dict[str, Party] = {"me": Party(real_age=me.age, believed_age=me.age, apparent_age=me.age, resolved=True)}

    def add_person(self, key: str, person: Person, entity_fields: dict | None, believed_age: float | None = None) -> None:
        """A person of the NPC's mind: `entity_fields` are the fields of his ENTITY record (None: a ghost, no file).
        A person who is not here is not perceived: no apparent age to check, but the age the NPC believes (a belief
        `(state X age_years N)`) and the real age must be adult."""
        self.truth[key] = person
        if entity_fields is None:
            self.parties[key] = UNKNOWN
            return
        seen = entity_fields.get("look.age")
        here = bool(entity_fields.get("present"))
        self.parties[key] = Party(real_age=person.age, believed_age=believed_age if believed_age is not None else (seen if here else None), apparent_age=seen,
                                  resolved=entity_fields.get("known_by") == "seen", perceived=here)

    def party(self, key: str) -> Party:
        if key in self.parties:
            return self.parties[key]
        if key.startswith(self.THING_PREFIXES):
            return THING
        return UNKNOWN                                   # anyone, someone, a group, a name: denied by default

    def may_be_minor(self, key: str) -> bool:
        return self.party(key).may_be_minor()

    def min_age(self, key: str) -> float:
        """The youngest age the key can be: true, apparent (for plausibility rules such as 'a child has no trade')."""
        p = self.truth.get(key)
        party = self.parties.get(key)
        ages = [x for x in ((p.age if p else None), (party.apparent_age if party else None)) if x is not None]
        return min(ages) if ages else 0.0

    def content_parties(self) -> dict:
        return dict(self.parties)
