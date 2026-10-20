#!/usr/bin/env bash
# Série AVANT/APRÈS de l'occlusion ambiante tracée (L14) : sans occlusion à gauche, avec à droite (même soleil, même caméra),
# sur la scène « arbre » (le chêne 42 côté ÉCLAIRÉ : creux de la couronne, pied du tronc) et la scène « materiaux » (mur de
# pierre, joints, dessous du toit, pied de mur), à 10 h, 18 h 15 et 18 h 45 de l'horloge du labo. Chaque prise donne
# <nom>.png (AVANT à gauche, APRÈS à droite), <nom>_AVANT.png et <nom>_APRES.png.
# Reproductible : mêmes arguments, mêmes octets. Dossier de sortie : EM_CAPTURE_DIR (défaut : lab/captures/AAAA-MM-JJ).
# Options supplémentaires transmises à `capture` (par exemple `--ao-force 1.2`, `--ao-rayons 8`).
#   scripts/serie_ao.sh
set -euo pipefail
ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lab="$ici/lab.sh"
sortie="${EM_CAPTURE_DIR:-$ici/../lab/captures/$(date +%F)}"
mkdir -p "$sortie"
# Chêne : la caméra du côté du soleil (derrière elle), regard vers le houppier.
#   prise  heure  x  y  z  (mètres relatifs à la scène)
arbre() {
  local nom="$1" heure="$2" x="$3" y="$4" z="$5" cible="$6"; shift 6
  "$lab" capture --scene arbre --camera="$x,$y,$z" --look-at "$cible" --champ 60 --hour "$heure" --ao-ab "$@" \
    --largeur 1280 --hauteur 720 --out "$sortie/06_ao_arbre_${nom}.png"
}
arbre eclaire_1000 10    11.8 2 -7.6  0,7.5,0 "$@"
arbre eclaire_1815 18.25 -13.2 2 4.6  0,7.5,0 "$@"
arbre eclaire_1845 18.75 -12.8 2 5.7  0,7.5,0 "$@"
# Couronne et pied du tronc de plus près.
arbre couronne_1845 18.75 -6 3 3      0,6,0 "$@"
arbre pied_1845     18.75 -3.2 1.2 1.6 0,1.2,0 "$@"
# Auvent de bâti : mur de pierre (joints), dessous du toit, pied de mur.
bati() {
  local tir="$1" heure="$2" suffixe="$3"; shift 3
  "$lab" capture --scene materiaux --mode voxel --shot "$tir" --hour "$heure" --exposure 0.9 --ao-ab "$@" \
    --largeur 1280 --hauteur 720 --out "$sortie/06_ao_materiaux_${tir}_${suffixe}.png"
}
for tir in pierre_pres pied_mur toit_haut ensemble_ouest; do
  bati "$tir" 10 1000 "$@"
  bati "$tir" 18.25 1815 "$@"
  bati "$tir" 18.75 1845 "$@"
done
