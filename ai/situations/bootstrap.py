"""bootstrap.py - the one place where the sampler puts the catalogue and the tokenizer on sys.path.

Imported by the package `__init__`, so every module of `situations` finds `schema`, `governor`, `language` and
`tok2` without touching sys.path itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for sub in ("ai", "catalogue/tools", "catalogue"):            # last inserted = first searched
    path = str(ROOT / sub)
    if path not in sys.path:
        sys.path.insert(0, path)
