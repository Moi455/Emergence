"""memories.py - the feeling a remembered event leaves, derived from what happened and the part he played.

Force done to him leaves fear, anger and a bad feeling and is read as an assault or an affront; a gift to him
leaves gratitude and is read as generosity; a death leaves grief; a look or a walk leaves almost nothing. The
table is keyed by the kind of event (from the gesture and its family) and by his role (actor, target, witness,
told). It colours a memory; it never decides what he does.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .draw import Draw
from .propositions import Recalled


@dataclass(frozen=True)
class Colour:
    emotions: dict                                  # emotion id -> weight
    valence: tuple[float, float]                    # range of the signed feeling (charter scale)
    interps: dict = field(default_factory=dict)     # interpretation id -> weight ('' = none)
    interp_rate: float = 0.5                        # how often an interpretation is attached


BAD_DONE = Colour({"e_fear": 0.3, "e_anger": 0.3, "e_shame": 0.1, "e_anxiety": 0.12, "e_sadness": 0.1, "e_surprise": 0.08},
                  (-9, -3), {"assault": 0.55, "affront": 0.2, "threat_felt": 0.15, "injustice": 0.1}, 0.7)
BAD_DONE_BY_ME = Colour({"e_guilt": 0.3, "e_shame": 0.2, "e_pride": 0.15, "e_anger": 0.2, "e_fear": 0.15},
                        (-6, 3), {"assault": 0.4, "self_defense": 0.3, "affront": 0.2, "revenge": 0.1}, 0.7)
BAD_SEEN = Colour({"e_fear": 0.3, "e_disgust": 0.2, "e_anxiety": 0.2, "e_anger": 0.2, "e_surprise": 0.1},
                  (-8, -2), {"assault": 0.5, "affront": 0.2, "threat_felt": 0.2, "heroism": 0.1}, 0.6)
GIFT_RECEIVED = Colour({"e_gratitude": 0.55, "e_joy": 0.25, "e_tenderness": 0.12, "e_surprise": 0.08}, (3, 9),
                       {"generosity": 0.6, "kindness": 0.4}, 0.6)
GIFT_GIVEN = Colour({"e_pride": 0.3, "e_joy": 0.3, "e_tenderness": 0.25, "e_sadness": 0.05, "e_gratitude": 0.1}, (2, 8),
                    {"generosity": 0.6, "kindness": 0.4}, 0.5)
GIFT_SEEN = Colour({"e_joy": 0.35, "e_gratitude": 0.2, "e_tenderness": 0.2, "e_pride": 0.1, "e_surprise": 0.15}, (1, 6),
                   {"generosity": 0.5, "kindness": 0.5}, 0.4)
TAKEN_FROM_ME = Colour({"e_anger": 0.4, "e_surprise": 0.2, "e_sadness": 0.15, "e_anxiety": 0.15, "e_shame": 0.1}, (-8, -2),
                       {"theft": 0.7, "taking_back": 0.1, "fraud": 0.2}, 0.7)
TAKEN_BY_ME = Colour({"e_guilt": 0.3, "e_pride": 0.2, "e_anxiety": 0.2, "e_joy": 0.2, "e_shame": 0.1}, (-5, 4),
                     {"theft": 0.5, "taking_back": 0.4, "trespass": 0.1}, 0.5)
CARE = Colour({"e_tenderness": 0.4, "e_gratitude": 0.25, "e_joy": 0.25, "e_surprise": 0.1}, (2, 8),
              {"kindness": 0.7, "rescue": 0.3}, 0.4)
DEATH = Colour({"e_grief": 0.42, "e_sadness": 0.25, "e_anger": 0.08, "e_guilt": 0.08, "e_fear": 0.05, "e_anxiety": 0.04,
                "e_surprise": 0.04, "e_confusion": 0.04}, (-9, -3), {"murder": 0.1, "accident": 0.15, "manslaughter": 0.05}, 0.3)
NEUTRAL = Colour({"e_surprise": 0.2, "e_confusion": 0.2, "e_boredom": 0.3, "e_anxiety": 0.1, "e_joy": 0.1, "e_contempt": 0.1},
                 (-2, 2), {}, 0.0)
MILD_GOOD = Colour({"e_joy": 0.4, "e_pride": 0.25, "e_tenderness": 0.15, "e_gratitude": 0.1, "e_surprise": 0.1}, (0, 5), {}, 0.0)


class MemoryColour:
    """Recalled -> (emotion, valence, interpretation or None)."""

    FORCE_FAMILIES = ("force",)

    def __init__(self, interpretations: set[str], emotions: list[str]):
        self.interps, self.emotions = interpretations, set(emotions)

    def colour_of(self, memory: Recalled, family: str | None) -> Colour:
        role, g = memory.role, memory.gesture
        if memory.death:
            return DEATH
        if g == "give":
            return {"target": GIFT_RECEIVED, "actor": GIFT_GIVEN}.get(role, GIFT_SEEN)
        if g == "take":
            return {"target": TAKEN_FROM_ME, "actor": TAKEN_BY_ME}.get(role, NEUTRAL)
        if family in self.FORCE_FAMILIES:
            return {"target": BAD_DONE, "actor": BAD_DONE_BY_ME}.get(role, BAD_SEEN)
        if family == "care" or g in ("eat", "drink") and role == "target":
            return CARE
        if family in ("consume", "tool", "transform") and role == "actor":
            return MILD_GOOD
        return NEUTRAL

    def __call__(self, d: Draw, memory: Recalled, family: str | None) -> tuple[str, float, str | None]:
        c = self.colour_of(memory, family)
        emotion = d.weighted(c.emotions, allowed=[e for e in c.emotions if e in self.emotions] or list(c.emotions))
        valence = d.uniform(*c.valence)
        if memory.role == "told":
            valence = round(valence * 0.6, 1)                   # a story told is felt less than a thing lived
        interp = None
        pool = {k: w for k, w in c.interps.items() if k in self.interps}
        if pool and d.chance(c.interp_rate):
            interp = d.weighted(pool)
        return emotion, valence, interp
