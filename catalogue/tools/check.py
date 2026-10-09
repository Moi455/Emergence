"""check.py - validate the catalogue. Exit code 1 if any problem.

    python3 catalogue/tools/check.py            # structure, references, the three layers
    python3 catalogue/tools/check.py --strict   # + every entry cited by a story, every story decomposed
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import Catalogue  # noqa: E402


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cat = Catalogue.load()
    problems = cat.validate(strict="--strict" in argv)
    counts = ", ".join(f"{k} {n}" for k, n in cat.count().items() if n)
    print(f"catalogue: {counts or 'vide'}")
    for line in problems:
        print("  -", line)
    print("OK" if not problems else f"{len(problems)} problème(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
