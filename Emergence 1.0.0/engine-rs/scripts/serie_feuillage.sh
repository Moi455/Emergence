#!/usr/bin/env bash
# Série de captures du feuillage vivant et de la lumière chaude (L10 étendue) : le chêne 42 à 10 h, midi, 18 h 15 et
# 18 h 45, caméra du côté ÉCLAIRÉ (le soleil derrière la caméra) et, à 18 h 15 et 18 h 45, en CONTRE-JOUR (le soleil
# derrière l'arbre : translucidité et liseré). Latitude 46° N, jour 172. Reproductible : mêmes arguments, mêmes octets.
# Dossier de sortie : EM_CAPTURE_DIR (défaut : lab/captures/AAAA-MM-JJ). Options supplémentaires transmises à `capture`
# (par exemple `--sans-feuillage` pour l'état d'avant la translucidité).
#   scripts/serie_feuillage.sh
#   scripts/serie_feuillage.sh --sans-feuillage        (comparaison A/B)
set -euo pipefail
ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$ici/lab.sh"
sortie="${EM_CAPTURE_DIR:-$ici/../lab/captures/$(date +%F)}"
mkdir -p "$sortie"
# Le soleil est à l'azimut A (convention de l'horloge du labo) : la caméra éclairée est à 14 m dans sa direction.
# prise  heure  x  y  z  (positions en mètres relatives à la scène ; regard vers le houppier)
prise() {
  local nom="$1" heure="$2" x="$3" y="$4" z="$5"; shift 5
  "$lab" capture --scene arbre --camera="$x,$y,$z" --look-at 0,7.5,0 --champ 60 --hour "$heure" "$@" \
    --out "$sortie/05_feuillage_${nom}.png"
}
prise eclaire_1000     10    11.8 2 -7.6  "$@"
prise eclaire_1200     12    0    2 -14   "$@"
prise eclaire_1815     18.25 -13.2 2 4.6  "$@"
prise eclaire_1845     18.75 -12.8 2 5.7  "$@"
prise contrejour_1815  18.25 13.2 2 -4.6  "$@"
prise contrejour_1845  18.75 12.8 2 -5.7  "$@"
