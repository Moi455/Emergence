#!/usr/bin/env bash
# Série de captures du ciel (L03) : aube, matin, midi, fin d'après-midi, coucher, crépuscule, nuit étoilée.
# Reproductible : mêmes arguments, mêmes octets. Dossier de sortie : EM_CAPTURE_DIR (défaut : lab/captures/AAAA-MM-JJ).
#   scripts/serie_ciel.sh
set -euo pipefail
ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$ici/lab.sh"
sortie="${EM_CAPTURE_DIR:-$ici/../lab/captures/$(date +%F)}"
mkdir -p "$sortie"
# nom  élévation  azimut  regard(azimut)  hauteur(°)  exposition  nuages  voile  turbidité  brume
prise() {
  local nom="$1"; shift
  "$lab" capture --scene ciel --sun-elevation "$1" --sun-azimuth "$2" --cam-azimuth "$3" --cam-elevation "$4" --cam-height 20 \
    --exposure "$5" --clouds "$6" --veil "$7" --turbidity "$8" --haze "$9" --out "$sortie/ciel_${nom}.png"
}
prise aube            2.5    80   55   12   1.8   0.30 0.25 3.5 0.50
prise matin          20    100   70   14   1.2   0.30 0.20 3.0 0.30
prise midi           62    180  120   22   1.0   0.35 0.25 2.5 0.20
prise fin_apres_midi 14    255  225   14   1.2   0.35 0.25 3.0 0.30
prise coucher         3    255  225   17   1.5   0.35 0.30 4.0 0.40
prise crepuscule     -1.5  260  240   16   4.0   0.30 0.35 3.0 0.30
prise nuit          -22    260  200   24  16.0   0.15 0.00 3.0 0.10
