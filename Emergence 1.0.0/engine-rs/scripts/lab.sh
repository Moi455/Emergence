#!/usr/bin/env bash
# Lance le laboratoire (em_lab) sur la Quadro RTX 3000 : docs/19 § 7.1.
#
# Sur ce portable hybride, Vulkan ne liste la Quadro que si le pilote NVIDIA est désigné ; sans cela
# seul l'Intel intégré apparaît et l'hôte refuse de démarrer (sauf --allow-any-adapter).
#   scripts/lab.sh capture --scene hello
#   scripts/lab.sh bench --frames 600
#   scripts/lab.sh window            (Échap quitte, F12 capture)
# Variables : EM_ADAPTER (nom de l'adaptateur voulu, défaut « Quadro »), EM_CAPTURE_DIR (dossier des PNG).
set -euo pipefail
ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ici/.."
export PATH="$HOME/.cargo/bin:$PATH"
export VK_DRIVER_FILES="${VK_DRIVER_FILES:-/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json}"
export WGPU_BACKEND=vulkan
# Portable hybride : la présentation dans une fenêtre passe par le GPU NVIDIA désigné. Si la fenêtre
# échoue à présenter, relancer avec EM_PRIME_OFFLOAD=1 (ajoute __NV_PRIME_RENDER_OFFLOAD=1).
if [[ "${EM_PRIME_OFFLOAD:-0}" == "1" ]]; then
  export __NV_PRIME_RENDER_OFFLOAD=1
  export __GLX_VENDOR_LIBRARY_NAME=nvidia
fi
exec cargo run --release -q -p em_lab -- "$@"
