#!/usr/bin/env bash
# Série A/B de la scène « materiaux » (L23p) : matière continue (A) contre variation par voxel (B), même soleil et
# même caméra. De près (pierre, pied de mur, bois, toit), à moyenne distance (ensemble, contre-jour) et de loin (20 m),
# à 10 h et à la golden hour (18 h 24 de l'horloge du labo). Chaque prise donne <nom>.png (A à gauche, B à droite), <nom>_A.png et <nom>_B.png.
# Reproductible : mêmes arguments, mêmes octets. Dossier de sortie : EM_CAPTURE_DIR (défaut : lab/captures/AAAA-MM-JJ).
#   scripts/serie_materiaux.sh
set -euo pipefail
ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$ici/lab.sh"
sortie="${EM_CAPTURE_DIR:-$ici/../lab/captures/$(date +%F)}"
mkdir -p "$sortie"
prise() {
  local tir="$1" heure="$2" suffixe="$3"
  "$lab" capture --scene materiaux --mode ab --shot "$tir" --hour "$heure" --exposure 0.9 \
    --largeur 1280 --hauteur 720 --out "$sortie/03_materiaux_${tir}_${suffixe}.png"
}
for tir in pierre_pres pied_mur bois_pres toit_haut ensemble_moyen ensemble_loin; do
  prise "$tir" 10 1000
done
# golden hour : le soleil est au nord-ouest, on regarde le dos du mur et l'auvent par l'ouest
for tir in dos_pres bois_pres toit_haut ensemble_ouest contrejour_moyen loin_ouest; do
  prise "$tir" 18.4 1824
done
