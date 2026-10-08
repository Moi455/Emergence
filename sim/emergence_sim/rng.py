"""Deterministic integer RNG (splitmix64). Never use the `random` module in the sim:
the C++ port must reproduce every draw bit for bit."""
MASK = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C15


def mix64(x):
    x = (x + GOLDEN) & MASK
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & MASK
    return x ^ (x >> 31)


def hash_ints(*vals):
    h = 0x243F6A8885A308D3
    for v in vals:
        h = mix64(h ^ (v & MASK))
    return h


class Rng:
    __slots__ = ("s",)

    def __init__(self, seed):
        self.s = mix64(seed & MASK)

    def next(self):
        self.s = (self.s + GOLDEN) & MASK
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def below(self, n):
        return (self.next() >> 11) % n if n > 0 else 0

    def range(self, lo, hi):
        """Uniform integer in [lo, hi]."""
        return lo + self.below(hi - lo + 1)

    def pm(self, permille):
        """True with probability permille/1000."""
        return self.below(1000) < permille

    def ppm(self, ppm):
        """True with probability ppm/1e6."""
        return self.below(1000000) < ppm

    def pick(self, seq):
        return seq[self.below(len(seq))]

    def weighted(self, items, weights):
        tot = 0
        for w in weights:
            tot += max(0, w)
        if tot <= 0:
            return items[self.below(len(items))]
        r = self.below(tot)
        for it, w in zip(items, weights):
            w = max(0, w)
            if r < w:
                return it
            r -= w
        return items[-1]

    def trait(self, lo=-100, hi=100):
        """Bell-ish integer: mean of three uniforms."""
        n = hi - lo + 1
        return lo + (self.below(n) + self.below(n) + self.below(n)) // 3
