"""keys.py - how a record of the NPC's mind is designated inside one decision.

Pointers of the inner language (@E3, @T5, @G1, @L2, @V4, @PLACE, b:7, m:2, g:1, and since 19a h:3 heard, q:1 asked,
c:2 agreed) and the private keys of records the language cannot point to (p:, k:, t:, and the fixed keys me, me.mind, me.state, wake). A key is
canonical: ASCII digits, no leading zero, at most 12 digits (so one record has one string).
"""
from __future__ import annotations

import re

NUM_BODY = r"0|[1-9][0-9]{0,11}"                 # a canonical integer: the exported form
NUM = f"(?:{NUM_BODY})"
FIXED_KEYS = ("me", "me.mind", "me.state", "wake", "@PLACE")
# Always used with fullmatch (never match or search): `$` would let a trailing newline through.
KEY = re.compile(rf"(?:me|me\.mind|me\.state|wake|@PLACE|@[ETGLV]{NUM}|[bmghqcpkt]:{NUM})", re.ASCII)
NAME = re.compile(rf"n:{NUM}", re.ASCII)
COUNT = re.compile(NUM, re.ASCII)
COUNT_MAX = 10_000_000                              # a number or a count in a proposition


def is_key(key) -> bool:
    return isinstance(key, str) and KEY.fullmatch(key) is not None


def is_name(sym) -> bool:
    return isinstance(sym, str) and NAME.fullmatch(sym) is not None


def is_count(text) -> bool:
    """A canonical non-negative integer written in ASCII digits, at most COUNT_MAX."""
    return isinstance(text, str) and COUNT.fullmatch(text) is not None and int(text) <= COUNT_MAX
