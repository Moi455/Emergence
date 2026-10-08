#!/usr/bin/env bash
# Builds worldgen with several compilers and optimisation levels and checks
# that every build reproduces the golden fingerprints (invariant I2).
# Usage: worldgen/scripts/check_determinism.sh [engine_dir]
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
engine="${1:-$here/../engine}"
out="${TMPDIR:-/tmp}/worldgen-determinism"
status=0
for cfg in "g++ Release" "g++ Debug" "clang++ Release" "clang++ Debug"; do
  set -- $cfg
  command -v "$1" >/dev/null || { echo "skip $1 (not installed)"; continue; }
  dir="$out/$1-$2"
  cmake -S "$here" -B "$dir" -DCMAKE_CXX_COMPILER="$1" -DCMAKE_BUILD_TYPE="$2" -DEMERGENCE_ENGINE_DIR="$engine" >/dev/null
  cmake --build "$dir" --target test_worldgen -j >/dev/null
  exe="$dir/test_worldgen"; [ -x "$exe" ] || exe="$dir/engine/worldgen/test_worldgen"
  if "$exe" golden | grep -q "0 failed"; then echo "ok   $1 $2"; else echo "FAIL $1 $2"; status=1; fi
done
exit $status
