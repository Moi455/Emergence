"""draw.py - the random draws of the sampler, in one place (weighted words, clipped Gaussians, scale priors).

Everything is seeded by the caller's `random.Random`: a situation is a pure function of (seed, index).
"""
from __future__ import annotations

import math
import random


class Draw:
    """Small vocabulary over a `random.Random`."""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def chance(self, p: float) -> bool:
        return self.rng.random() < p

    def pick(self, seq):
        return seq[self.rng.randrange(len(seq))]

    def weighted(self, weights: dict, allowed=None):
        """A key of `weights` with probability proportional to its weight; `allowed` restricts the keys (an
        allowed key missing from `weights` has weight 1)."""
        keys = [k for k in (allowed if allowed is not None else weights)]
        if not keys:
            raise ValueError("nothing to draw from")
        return self.rng.choices(keys, weights=[max(1e-9, weights.get(k, 1.0)) for k in keys])[0]

    def clip(self, x: float, lo: float = 0.0, hi: float = 10.0, nd: int = 1) -> float:
        return round(min(hi, max(lo, x)), nd)

    def gauss(self, mu: float, sd: float, lo: float = 0.0, hi: float = 10.0, nd: int = 1) -> float:
        return self.clip(self.rng.gauss(mu, sd), lo, hi, nd)

    def uniform(self, lo: float, hi: float, nd: int = 1) -> float:
        return round(self.rng.uniform(lo, hi), nd)

    def log_uniform(self, lo: float, hi: float, nd: int = 3) -> float:
        return round(math.exp(self.rng.uniform(math.log(lo), math.log(hi))), nd)

    def sample(self, seq, k: int) -> list:
        return self.rng.sample(list(seq), min(k, len(seq)))

    def between(self, lo: int, hi: int) -> int:
        return self.rng.randint(lo, hi)


class NumericPrior:
    """A plausible value from the scale alone, for a field the scene says nothing about: most feelings and needs
    are low, attitudes centred. Booleans are NOT drawn here (a flag has its own rate, decided by its builder)."""

    def __init__(self, draw: Draw):
        self.d = draw

    def sample(self, spec: dict):
        scale, d = spec["scale"], self.d
        if scale == "bipolar10":
            return d.gauss(0, 3, -10.0, 10.0)
        if scale == "unipolar10":
            return d.clip(abs(d.rng.gauss(0, 2.5)), 0.0, 10.0)
        if scale == "ratio":
            return round(d.rng.random(), 2)
        return None                                 # qty, time, bool, vectors: the builder decides or leaves unknown
