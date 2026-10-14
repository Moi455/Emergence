#!/usr/bin/env python3
"""Copy .claudeignore into .claude/settings.json (permissions.deny) so Claude Code enforces it.

Usage: python3 scripts/sync_claudeignore.py [--check]
--check exits 1 when settings.json is out of date, without writing.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def rule(pattern: str) -> str:
    if pattern.startswith("**/"):
        return f"Read({pattern}**)" if pattern.endswith("/") else f"Read({pattern})"
    return f"Read(./{pattern}**)" if pattern.endswith("/") else f"Read(./{pattern})"


def main() -> int:
    lines = (ROOT / ".claudeignore").read_text(encoding="utf-8").splitlines()
    deny = [rule(s) for s in (ln.strip() for ln in lines) if s and not s.startswith("#")]
    path = ROOT / ".claude" / "settings.json"
    settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if settings.get("permissions", {}).get("deny") == deny:
        print(f"settings.json up to date ({len(deny)} rules)")
        return 0
    if "--check" in sys.argv:
        print("settings.json is out of date: run scripts/sync_claudeignore.py")
        return 1
    settings.setdefault("permissions", {})["deny"] = deny
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"settings.json updated ({len(deny)} rules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
