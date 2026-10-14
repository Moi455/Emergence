#!/usr/bin/env bash
# Emergence 1.0.0 - every test. Usage: scripts/test_all.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0
run() { echo "== $*"; if ! "$@"; then echo "!! ÉCHEC : $*"; fail=1; fi; }
cd "$ROOT"
run python3 catalogue/tools/check.py
run python3 catalogue/tools/gen_cpp.py --check
run python3 -m unittest discover -s catalogue/tests
run python3 -m unittest discover -s ai/tok2/tests -t ai
run python3 -m unittest discover -s ai/situations/tests -t ai
run python3 -m unittest discover -s ai/teacher/tests -t ai
run python3 -m unittest discover -s ai/student2/tests -t ai
if command -v cmake >/dev/null; then
  BUILD="${EMERGENCE_BUILD_DIR:-$ROOT/build}"
  run cmake -S engine -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
  run cmake --build "$BUILD" -j
  run ctest --test-dir "$BUILD" --output-on-failure
fi
exit $fail
