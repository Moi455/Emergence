#!/usr/bin/env bash
# Série de captures de l'arbre (L09) : le chêne 42 de face, de trois quarts, en contre-jour, le feuillage de près
# (voxels visibles) et le tronc de près (matière continue), à 10 h, 17 h 30 et 19 h (latitude 46° N, jour 172).
# Reproductible : mêmes arguments, mêmes octets. Dossier de sortie : EM_CAPTURE_DIR (défaut : lab/captures/AAAA-MM-JJ).
#   scripts/serie_arbre.sh
set -euo pipefail
ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$ici/lab.sh"
sortie="${EM_CAPTURE_DIR:-$ici/../lab/captures/$(date +%F)}"
mkdir -p "$sortie"
# prise  heure  suffixe  [options de capture]
prise() {
  local tir="$1" heure="$2" suffixe="$3"; shift 3
  "$lab" capture --scene arbre --shot "$tir" --hour "$heure" "$@" --out "$sortie/02_arbre_${tir}_${suffixe}.png"
}
for tir in face trois_quarts feuillage tronc; do
  prise "$tir" 10   1000
  prise "$tir" 17.5 1730
  prise "$tir" 19   1900
done
prise contrejour 19 1900
