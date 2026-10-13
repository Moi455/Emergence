#!/usr/bin/env bash
# Emergence 1.0.0 - lance le generateur continu de donnees d'entrainement (Gemini, quota gratuit de Monsieur).
#
#   scripts/run_generator.sh start  [NOM] [options du generateur...]   en arriere-plan (nohup), journal dans le dossier de la serie
#   scripts/run_generator.sh stop   [NOM]                              arret propre (SIGTERM : finit la requete en cours, sauvegarde)
#   scripts/run_generator.sh status [NOM]                              l'etat du processus + le bilan (python3 -m teacher.generator --status)
#   scripts/run_generator.sh logs   [NOM]                              suit generator.log
#   scripts/run_generator.sh foreground [NOM] [options...]             au premier plan (c'est ce que lance le service systemd)
#
# NOM est le nom de la serie (defaut : serie1). Tout est ecrit HORS du depot :
#   ${EMERGENCE_DATASET_DIR:-~/.local/share/emergence/dataset}/NOM/{dataset.jsonl,journal.jsonl,state.json,quota.json,generator.log,generator.pid}
# La cle Gemini est lue par le chargeur existant (GEMINI_API_KEY ou ~/.config/emergence/API_Keys, droits 600) : elle ne passe jamais ici.
# Les options (ex. --days 7, --k 8, --models a,b) sont transmises telles quelles ; --call est toujours ajoute.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cmd="${1:-status}"; shift || true
name="serie1"
if [[ $# -gt 0 && "$1" != -* ]]; then name="$1"; shift; fi
base="${EMERGENCE_DATASET_DIR:-$HOME/.local/share/emergence/dataset}"
dir="$base/$name"
pidfile="$dir/generator.pid"
log="$dir/generator.log"
alive() { [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; }
py() { cd "$ROOT/ai" && exec python3 -u -m teacher.generator --name "$name" --out "$base" "$@"; }

case "$cmd" in
  start)
    mkdir -p "$dir"
    if alive; then echo "deja en marche (pid $(cat "$pidfile")), serie $name"; exit 0; fi
    cd "$ROOT/ai"
    nohup setsid python3 -u -m teacher.generator --name "$name" --out "$base" --call "$@" >>"$log" 2>&1 < /dev/null &
    echo $! > "$pidfile"
    echo "lance : serie $name, pid $(cat "$pidfile"), journal $log"
    ;;
  foreground)
    mkdir -p "$dir"
    py --call "$@"
    ;;
  stop)
    if ! alive; then echo "pas de processus pour la serie $name"; rm -f "$pidfile"; exit 0; fi
    pid="$(cat "$pidfile")"; kill -TERM "$pid"
    for _ in $(seq 1 180); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    if kill -0 "$pid" 2>/dev/null; then echo "toujours en marche apres 180 s (requete en cours ?) : pid $pid"; exit 1; fi
    rm -f "$pidfile"; echo "arrete, etat sauvegarde"
    ;;
  status)
    if alive; then echo "en marche (pid $(cat "$pidfile"))"; else echo "arrete"; fi
    (cd "$ROOT/ai" && python3 -m teacher.generator --name "$name" --out "$base" --status)
    ;;
  logs)
    exec tail -n 40 -f "$log"
    ;;
  *)
    sed -n '2,13p' "${BASH_SOURCE[0]}"; exit 2
    ;;
esac
