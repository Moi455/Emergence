#!/usr/bin/env bash
# Régénère engine-rs/crates/em_core/tests/vecteurs/cpp_vectors.inc.rs depuis le C++ du moteur (parité bit à bit).
# À relancer seulement si engine/core/base, engine/ops ou engine/act changent ; le fichier généré est versionné.
set -euo pipefail
ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
racine="$(cd "$ici/../.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
g++ -std=c++20 -O1 -Wall -Wextra -Wno-misleading-indentation -fno-fast-math -ffp-contract=off \
  -I"$racine/engine/core/base/include" -I"$racine/engine/ops/include" -I"$racine/engine/act/include" \
  "$ici/cpp_vectors.cpp" "$racine/engine/ops/src/digest.cpp" -o "$tmp/cpp_vectors"
"$tmp/cpp_vectors" > "$ici/../crates/em_core/tests/vecteurs/cpp_vectors.inc.rs"
echo "Vecteurs écrits dans crates/em_core/tests/vecteurs/cpp_vectors.inc.rs"
