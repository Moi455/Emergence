"""body.py - plausible bodies and weather for the NPC: needs follow the hour, the felt air follows the season and
the walls, strength follows the age, and a few people are hurt, ill, drunk or bleeding. Values on the charter scales
(0..10 unipolar; -10..+10 for the thermal need). Nothing here decides anything: it only sets a starting state."""
from __future__ import annotations

import math

from .draw import Draw

SLEEP_CURVE = ((0, 7.2), (5, 7.0), (7, 4.0), (9, 1.5), (17, 2.8), (21, 5.5), (24, 7.2))   # sleepiness by hour
MEALS = (7.0, 12.5, 19.0)                                                                  # hours of the meals


def interpolate(curve, x: float) -> float:
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return curve[-1][1]


def daylight(hour: float) -> float:
    """0 at night, 1 at noon."""
    return max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0))


class Climate:
    """The felt air as an index into PLACE.air_felt (0 freezing .. 5 hot)."""
    BASE = {"winter": 1.2, "spring": 2.8, "summer": 4.2, "autumn": 2.5}

    def __init__(self, draw: Draw):
        self.d = draw

    def index(self, season: str, hour: float, indoors: bool) -> float:
        x = self.BASE[season] + (-1.0 if hour < 6 or hour > 21 else 0.5 if 11 <= hour <= 17 else 0.0)
        if indoors:
            x = 0.45 * x + 0.55 * 3.1
        return x + self.d.rng.gauss(0, 0.6)

    @staticmethod
    def word(values: list[str], x: float) -> str:
        order = ["freezing", "cold", "cool", "mild", "warm", "hot"]
        w = order[int(min(len(order) - 1, max(0, round(x))))]
        return w if w in values else values[min(len(values) - 1, max(0, round(x)))]


class BodyModel:
    def __init__(self, draw: Draw):
        self.d = draw

    def strength(self, age: float) -> float:
        base = 1.5 + age * 0.3 if age < 14 else 5.2 if age < 50 else 5.2 - (age - 50) * 0.13
        return self.d.gauss(base, 1.2)

    def make(self, age: float, hour: float, air: float, tavern: bool, load_mass: float) -> tuple[dict, bool]:
        d = self.d
        hurt, sick = d.chance(0.09), d.chance(0.06)
        bleeding = d.uniform(1, 5) if (hurt and d.chance(0.25)) else 0.0
        drunk = d.uniform(1, 6) if (age >= 16 and d.chance(0.12 if tavern else 0.01)) else 0.0
        pain = d.uniform(2, 7) if hurt else d.clip(abs(d.rng.gauss(0, 0.4)) + (0.4 if age > 60 else 0.0))
        sickness = d.uniform(2, 7) if sick else d.clip(abs(d.rng.gauss(0, 0.2)))
        strength = self.strength(age)
        sleep = d.gauss(interpolate(SLEEP_CURVE, hour), 1.3)
        since_meal = min(min((hour - m) % 24 for m in MEALS), 5.5)
        hunger = d.gauss(0.95 * since_meal * (0.5 if hour < 5 or hour >= 22 else 1.0) + 0.6, 1.0)
        working = 0.0 if hour < 6 or hour > 22 else min(hour - 6, 14) * 0.28
        exhaustion = d.gauss(working + (1.5 if hurt or sick else 0.0) + (0.5 if age > 60 else 0.0) - 0.4, 1.1)
        consciousness = d.gauss(10 - 0.4 * drunk - (0.5 * (pain - 5) if pain > 5 else 0.0), 0.2)
        if d.chance(0.01):
            consciousness = d.uniform(3, 6)
        return {
            "body.consciousness": min(10.0, consciousness),
            "body.breath": d.gauss(9.4 - 2.0 * (sickness > 3) - 1.0 * (age > 60), 0.5),
            "body.bleeding": bleeding, "body.pain": pain, "body.sickness": sickness, "body.intox": drunk,
            "body.strength": strength, "body.endurance": d.gauss(strength - 0.3 * sickness, 1.2),
            "body.load": round(min(1.0, load_mass / (strength * 5.0 + 10.0)), 2),
            "body.mobility": round(max(0.2, 1.0 - (0.08 * pain if hurt else 0.0) - (0.05 if age > 70 else 0.0)), 2),
            "body.manipulation": round(max(0.2, 1.0 - (0.06 * pain if hurt and d.chance(0.4) else 0.0)), 2),
            "need.sleep": sleep, "need.hunger": hunger, "need.exhaustion": exhaustion,
            "need.thirst": d.gauss(1.4 + max(0.0, air - 3.5) * 1.3 + 0.2 * hunger, 0.9),
            "need.thermal": d.gauss((air - 3.1) * 2.2, 0.8, -10.0, 10.0),
            "need.reserves": d.gauss(7.2 - 0.3 * (hunger > 7) * 3, 1.3),
        }, hurt
