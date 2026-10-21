#!/usr/bin/env bash
# Cuit les maisons du générateur de Monsieur en .vxh + .json (hors dépôt, comme les arbres).
#   tools/maisons/cuire.sh                 # graines gravit, a, ferme, hameau
#   tools/maisons/cuire.sh gravit autre    # graines au choix
# Variables : EM_MAISONS_HTML (défaut : « générateurs de voxels/nouvelle référence.html »),
#             EM_MAISONS_OUT (défaut : ~/.local/share/emergence/lab_assets/maisons).
set -euo pipefail
ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
racine="$(cd "$ici/../.." && pwd)"
html="${EM_MAISONS_HTML:-$racine/générateurs de voxels/nouvelle référence.html}"
sortie="${EM_MAISONS_OUT:-$HOME/.local/share/emergence/lab_assets/maisons}"
if [[ $# -eq 0 ]]; then set -- gravit a ferme hameau; fi
exec node "$ici/cuire.mjs" "$html" "$sortie" "$@"
