"""tomledit.py - edit one-line inline-table entries ({ id = "x", ... }) of catalogue/data/*.toml by id.

Used by maintenance scripts: Files().set("r_affection", "rate", 2.0); .drop(id, key); .save().
"""
import glob
import json
import re
from pathlib import Path

DATA = str(Path(__file__).resolve().parents[1] / "data") + "/"


def lit(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(lit(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {lit(x)}" for k, x in v.items()) + " }"
    raise TypeError(v)


VALUE = r'("(?:[^"\\]|\\.)*"|\[[^\]]*\]|\{[^}]*\}|[^,}]+)'


class Files:
    def __init__(self):
        self.text = {p: open(p).read() for p in glob.glob(DATA + "*.toml")}

    def find(self, eid):
        hits = []
        for p, t in self.text.items():
            for m in re.finditer(r'^(\s*\{ id = "' + re.escape(eid) + r'",.*\},?)\s*$', t, re.M):
                hits.append((p, m))
        if len(hits) != 1:
            raise SystemExit(f"{eid}: {len(hits)} matches")
        return hits[0]

    def get(self, eid):
        return self.find(eid)[1].group(1)

    def put(self, eid, line):
        p, m = self.find(eid)
        self.text[p] = self.text[p][:m.start(1)] + line + self.text[p][m.end(1):]

    def set(self, eid, key, value):
        line = self.get(eid)
        pat = re.compile(r'(, |\{ )' + key + r' = ' + VALUE)
        new = f"{key} = {lit(value)}"
        if pat.search(line):
            line = pat.sub(lambda m: m.group(1) + new, line, count=1)
        else:
            line = re.sub(r'\s*\},?$', lambda m: f", {new} " + m.group(0).lstrip(), line, count=1)
        self.put(eid, line)

    def drop(self, eid, key):
        line = self.get(eid)
        self.put(eid, re.sub(r', ' + key + r' = ' + VALUE, '', line, count=1))

    def save(self):
        for p, t in self.text.items():
            open(p, "w").write(t)
