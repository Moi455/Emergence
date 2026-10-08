#!/usr/bin/env bash
# Lance tous les tests existants. Usage : scripts/test_all.sh [--quick]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0
run() { echo "== $*"; if ! "$@"; then echo "!! ÉCHEC : $*"; fail=1; fi; }

cd "$ROOT/ai/npc_pipeline"
run python3 plan_contract.py
run python3 memory_service.py
run python3 build_site.py
run python3 representation.py
run python3 scenario_tests.py
run python3 generate_states.py --n 500 --check
if [[ "${1:-}" != "--quick" ]]; then
  run python3 selftest_pipeline.py
  run python3 selftest_quota_stress.py
fi

cd "$ROOT/tools/voxelizer"
if python3 -c "import numpy, scipy, PIL" 2>/dev/null; then
  run python3 -m unittest discover -s tests
else
  echo "!! numpy/scipy/Pillow absents : pip install -r tools/voxelizer/requirements.txt"; fail=1
fi

if [[ $fail -eq 0 ]]; then echo "TOUS LES TESTS PASSENT"; else echo "DES TESTS ÉCHOUENT"; fi
exit $fail
