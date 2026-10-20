#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
read_vxm.py — lecteur minimal et vérificateur du format d'échange `.vxm` v1 (docs/19a § 1).

Sert de référence au chargeur Rust (L08) : il relit le fichier octet par octet, refuse tout ce qui
est douteux (signature, version, drapeaux inconnus, CRC, troncature, doublons, ordre, bornes) et
rend des tableaux numpy. Lecture seule : aucune dépendance au générateur.

    python3 read_vxm.py chene_42.vxm            # résumé + vérifications
    python3 read_vxm.py orientation.vxm --orientation   # contrôle rouge en +x, bleu en +z
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

MAGIC = b"VXM1"
VERSION = 1
FLAG_ZLIB, FLAG_SKY, FLAG_PAL = 1, 2, 4
KNOWN_FLAGS = FLAG_ZLIB | FLAG_SKY | FLAG_PAL
KIND_BARK, KIND_LEAF, KIND_TWIG, KIND_FLOWER, KIND_FRUIT = 1, 2, 3, 4, 5
KIND_NAMES = {1: "ecorce", 2: "feuille", 3: "rameau", 4: "fleur", 5: "fruit"}


class VxmError(ValueError):
    """Fichier .vxm invalide."""


@dataclass
class VxmLod:
    lod: int
    min: Tuple[int, int, int]
    dims: Tuple[int, int, int]
    x: np.ndarray        # u16 relatifs à `min`
    y: np.ndarray
    z: np.ndarray
    kind: np.ndarray     # u8
    ramp: np.ndarray     # u8
    pal: Optional[np.ndarray] = None
    sky: Optional[np.ndarray] = None

    @property
    def count(self) -> int:
        return len(self.x)

    def world(self) -> np.ndarray:
        """Cellules (x est, y haut, z nord) en voxels du niveau, pivot = (0, 0, 0)."""
        return np.stack([self.x, self.y, self.z], axis=1).astype(np.int64) + np.array(self.min, np.int64)

    def cell_set(self) -> set:
        w = self.world()
        return set(zip(w[:, 0].tolist(), w[:, 1].tolist(), w[:, 2].tolist(),
                       self.kind.tolist(), self.ramp.tolist()))

    def bbox(self) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
        w = self.world()
        return tuple(w.min(axis=0).tolist()), tuple(w.max(axis=0).tolist())


@dataclass
class Vxm:
    flags: int
    header: dict
    lods: List[VxmLod]
    size: int

    def lod(self, k: int) -> VxmLod:
        for s in self.lods:
            if s.lod == k:
                return s
        raise KeyError(f"LOD {k} absent")


def tint_variant(kind: int, ramp: int, roles: List[str]) -> int:
    """Variante de 2 bits de la teinte de végétation (19a § 5.3) : écorce 0, écorce secondaire 1,
    rameau 2 ; fleur et fruit : rang de la rampe dans son rôle ; feuille : 0 (tirée au shader)."""
    if kind == KIND_BARK:
        return 1 if roles[ramp] == "bark_alt" else 0
    if kind == KIND_TWIG:
        return 2
    if kind in (KIND_FLOWER, KIND_FRUIT):
        role = roles[ramp]
        return ramp - roles.index(role)
    return 0


class _Cursor:
    def __init__(self, data: bytes, pos: int, end: int):
        self.d, self.p, self.end = data, pos, end

    def take(self, n: int) -> bytes:
        if n < 0 or self.p + n > self.end:
            raise VxmError("fichier tronqué")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b


def parse_vxm(data: bytes) -> Vxm:
    if len(data) < 16:
        raise VxmError("fichier trop court")
    if data[:4] != MAGIC:
        raise VxmError("signature VXM1 absente")
    crc_stored = struct.unpack_from("<I", data, len(data) - 4)[0]
    if zlib.crc32(data[:-4]) & 0xFFFFFFFF != crc_stored:
        raise VxmError("CRC32 invalide")
    version, flags, json_len = struct.unpack_from("<HHI", data, 4)
    if version != VERSION:
        raise VxmError(f"version {version} non prise en charge (attendu {VERSION})")
    if flags & ~KNOWN_FLAGS:
        raise VxmError(f"drapeaux inconnus : {flags:#x}")
    cur = _Cursor(data, 12, len(data) - 4)
    try:
        header = json.loads(cur.take(json_len).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise VxmError(f"en-tête JSON illisible : {e}")
    if header.get("format") != "vxm-1":
        raise VxmError("en-tête : format différent de vxm-1")
    for key in ("lods", "ramps", "ramp_roles", "steps", "voxel_m", "species", "seed_int"):
        if key not in header:
            raise VxmError(f"en-tête : champ « {key} » absent")
    if len(header["ramps"]) != len(header["ramp_roles"]):
        raise VxmError("en-tête : ramps et ramp_roles de longueurs différentes")
    n_ramps = len(header["ramps"])
    if flags & FLAG_PAL and "palette" not in header:
        raise VxmError("drapeau pal sans palette dans l'en-tête")
    lods: List[VxmLod] = []
    for expected in header["lods"]:
        lod, = struct.unpack("<B", cur.take(1))
        if cur.take(3) != b"\0\0\0":
            raise VxmError("octets réservés non nuls")
        mn = struct.unpack("<3i", cur.take(12))
        dims = struct.unpack("<3I", cur.take(12))
        count, body_len = struct.unpack("<II", cur.take(8))
        if lod != expected or (lods and lod <= lods[-1].lod):
            raise VxmError(f"LOD {lod} inattendu ou hors ordre (en-tête : {header['lods']})")
        if count == 0:
            raise VxmError(f"LOD {lod} vide")
        body = cur.take(body_len)
        if flags & FLAG_ZLIB:
            try:
                body = zlib.decompress(body)
            except zlib.error as e:
                raise VxmError(f"LOD {lod} : corps zlib invalide ({e})")
        per = 8 + (1 if flags & FLAG_PAL else 0) + (1 if flags & FLAG_SKY else 0)
        if len(body) != count * per:
            raise VxmError(f"LOD {lod} : corps de {len(body)} octets au lieu de {count * per}")
        off = 0

        def arr(dtype, width):
            nonlocal off
            a = np.frombuffer(body, dtype=dtype, count=count, offset=off)
            off += count * width
            return a
        x, y, z = arr("<u2", 2), arr("<u2", 2), arr("<u2", 2)
        kind, ramp = arr("u1", 1), arr("u1", 1)
        pal = arr("u1", 1) if flags & FLAG_PAL else None
        sky = arr("u1", 1) if flags & FLAG_SKY else None
        s = VxmLod(lod, mn, dims, x, y, z, kind, ramp, pal, sky)
        _check_lod(s, n_ramps)
        lods.append(s)
    if cur.p != cur.end:
        raise VxmError("octets en trop après la dernière section")
    return Vxm(flags, header, lods, len(data))


def _check_lod(s: VxmLod, n_ramps: int):
    for name, a, d in (("x", s.x, s.dims[0]), ("y", s.y, s.dims[1]), ("z", s.z, s.dims[2])):
        if int(a.max()) >= d:
            raise VxmError(f"LOD {s.lod} : {name} hors de la boîte")
    if int(s.kind.min()) < 1 or int(s.kind.max()) > 5:
        raise VxmError(f"LOD {s.lod} : sorte hors de 1..5")
    if int(s.ramp.max()) >= n_ramps:
        raise VxmError(f"LOD {s.lod} : indice de rampe hors de l'en-tête")
    # ordre (y, z, x) strictement croissant : trié et chaque cellule une seule fois
    key = (s.y.astype(np.int64) * (1 << 20) + s.z.astype(np.int64)) * (1 << 20) + s.x.astype(np.int64)
    if np.any(np.diff(key) <= 0):
        raise VxmError(f"LOD {s.lod} : voxels non triés par (y, z, x) ou cellule en double")


def read_vxm(path: str) -> Vxm:
    with open(path, "rb") as f:
        return parse_vxm(f.read())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lecteur et vérificateur .vxm v1")
    ap.add_argument("file")
    ap.add_argument("--orientation", action="store_true", help="vérifie la scène d'orientation (rouge +x, bleu +z)")
    a = ap.parse_args(argv)
    try:
        v = read_vxm(a.file)
    except (VxmError, OSError) as e:
        print(f"ERREUR : {e}")
        return 1
    h = v.header
    print(f"{a.file} : {v.size:,} octets, {h['species']} graine {h['seed']} {h.get('height_m')} m {h.get('season')}, "
          f"flags {v.flags:#x}, {len(h['ramps'])} rampes")
    for s in v.lods:
        kinds = {KIND_NAMES[k]: int((s.kind == k).sum()) for k in range(1, 6) if (s.kind == k).any()}
        print(f"  LOD {s.lod} : {s.count:,} voxels, min {s.min}, dims {s.dims}, {kinds}")
    if a.orientation:
        w = v.lod(0).world()
        red = w[v.lod(0).kind == KIND_FLOWER][0].tolist()
        blue = w[v.lod(0).kind == KIND_FRUIT][0].tolist()
        ok = red == [1, 0, 0] and blue == [0, 0, 1]
        print(f"  rouge {red} (attendu [1, 0, 0]), bleu {blue} (attendu [0, 0, 1]) : {'OK' if ok else 'ECHEC'}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
