#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Régénère tests/vecteurs/chene_42_echantillon.txt depuis le lecteur de référence `read_vxm.py` (L04).

    python3 -I gen_echantillon.py ~/.local/share/emergence/lab_assets/trees/chene_42.vxm > chene_42_echantillon.txt

Contenu : une ligne « L lod count min dims » par niveau, puis 10 000 lignes « S x y z kind variante » :
le voxel de rang i * (count // 10000) du LOD 0 (ordre du fichier : y, z, x), x y z en voxels du niveau,
pivot = (0, 0, 0), kind = code du fichier (1..5), variante = `tint_variant` de read_vxm.py.
"""
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ICI, "..", "..", "..", "..", "..", "tools", "vegetation"))
import read_vxm as rv  # noqa: E402


def main():
    v = rv.read_vxm(sys.argv[1])
    roles = v.header["ramp_roles"]
    for s in v.lods:
        print("L", s.lod, s.count, *s.min, *s.dims)
    s0 = v.lod(0)
    w = s0.world()
    pas = s0.count // 10000
    for i in range(10000):
        k = i * pas
        x, y, z = (int(a) for a in w[k])
        kind, ramp = int(s0.kind[k]), int(s0.ramp[k])
        print("S", x, y, z, kind, rv.tint_variant(kind, ramp, roles))


main()
