#!/usr/bin/env bash
# Builds the core with several compilers and optimisation levels, then checks
# that the world plan fingerprint is identical everywhere (invariant I2).
# Usage: scripts/check_determinism.sh [seed] [size_m]
set -euo pipefail
ENGINE="$(cd "$(dirname "$0")/.." && pwd)"
SEED="${1:-1}"
SIZE="${2:-20000}"
WORK="${TMPDIR:-/tmp}/emergence_determinism"
mkdir -p "$WORK"
declare -A FP
for cxx in g++ clang++; do
  command -v "$cxx" >/dev/null || continue
  for cfg in "Debug:-O0" "Release:-O3" "RelNative:-O3 -march=native"; do
    name="${cxx}_${cfg%%:*}"
    flags="${cfg#*:}"
    dir="$WORK/$name"
    cmake -S "$ENGINE" -B "$dir" -G Ninja -DCMAKE_CXX_COMPILER="$cxx" \
      -DCMAKE_BUILD_TYPE=None -DCMAKE_CXX_FLAGS="$flags" >/dev/null
    cmake --build "$dir" >/dev/null
    # Pinned plan and chunk fingerprints (test_world_plan, test_chunks).
    if ! (cd "$dir" && ctest --output-on-failure >/dev/null); then
      echo "$name: ctest FAILED"; exit 1; fi
    for threads in 1 4; do
      fp=$("$dir/sim/emergence_sim" plan --seed "$SEED" --size "$SIZE" --threads "$threads" | sed -n 's/^fingerprint: //p')
      FP["$name/t$threads"]="$fp"
      echo "$name threads=$threads  $fp"
    done
  done
done
ref=""
for k in "${!FP[@]}"; do
  if [[ -z "$ref" ]]; then ref="${FP[$k]}"; elif [[ "${FP[$k]}" != "$ref" ]]; then
    echo "MISMATCH: fingerprints differ"; exit 1; fi
done
echo "IDENTICAL: $ref"
