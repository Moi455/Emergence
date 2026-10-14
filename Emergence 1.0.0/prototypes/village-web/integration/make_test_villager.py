#!/usr/bin/env python3
"""Generate a test villager (.glb) that follows docs/interfaces.md §3-§7.

Stand-in until the "Skins des villageois" thread delivers the real characters:
pseudo-voxel body (5 cm cells), Godot humanoid bone names (fingers omitted),
attachment bones, rigid skinning (1 influence), and the priority-1 clips the
village needs first: idle, walk, run, swing_axe, talk_calm, wave, sit_idle.

Custom vertex attribute _DYEZONE (float): 0 skin, 1 torso, 2 legs, 3 feet/belt,
4 hair. The game multiplies the vertex colour by the NPC's dye for that zone.

Usage: python3 make_test_villager.py out.glb
No dependency beyond the standard library. Deterministic.
"""
import json, math, struct, sys

# ---------------------------------------------------------------- skeleton
# name, parent, head position in rest pose (metres, character faces +Z, feet at y=0)
BONES = [
    ("Root", None, (0, 0, 0)),
    ("Hips", "Root", (0, 0.95, 0)),
    ("Spine", "Hips", (0, 1.05, 0)),
    ("Chest", "Spine", (0, 1.20, 0)),
    ("UpperChest", "Chest", (0, 1.33, 0)),
    ("Neck", "UpperChest", (0, 1.48, 0)),
    ("Head", "Neck", (0, 1.55, 0)),
    ("HeadProp", "Head", (0, 1.80, 0)),
    ("LeftShoulder", "UpperChest", (0.06, 1.44, 0)),
    ("LeftUpperArm", "LeftShoulder", (0.20, 1.44, 0)),
    ("LeftLowerArm", "LeftUpperArm", (0.46, 1.44, 0)),
    ("LeftHand", "LeftLowerArm", (0.70, 1.44, 0)),
    ("LeftHandProp", "LeftHand", (0.78, 1.44, 0)),
    ("RightShoulder", "UpperChest", (-0.06, 1.44, 0)),
    ("RightUpperArm", "RightShoulder", (-0.20, 1.44, 0)),
    ("RightLowerArm", "RightUpperArm", (-0.46, 1.44, 0)),
    ("RightHand", "RightLowerArm", (-0.70, 1.44, 0)),
    ("RightHandProp", "RightHand", (-0.78, 1.44, 0)),
    ("LeftUpperLeg", "Hips", (0.10, 0.92, 0)),
    ("LeftLowerLeg", "LeftUpperLeg", (0.10, 0.50, 0)),
    ("LeftFoot", "LeftLowerLeg", (0.10, 0.08, 0)),
    ("LeftToes", "LeftFoot", (0.10, 0.03, 0.12)),
    ("RightUpperLeg", "Hips", (-0.10, 0.92, 0)),
    ("RightLowerLeg", "RightUpperLeg", (-0.10, 0.50, 0)),
    ("RightFoot", "RightLowerLeg", (-0.10, 0.08, 0)),
    ("RightToes", "RightFoot", (-0.10, 0.03, 0.12)),
    ("BackProp", "UpperChest", (0, 1.30, -0.14)),
    ("HipProp", "Hips", (0.17, 0.92, 0.0)),
]
BI = {b[0]: i for i, b in enumerate(BONES)}

# boxes: bone, min corner, max corner, zone, rgb
SKIN, TORSO, LEGS, FEET, HAIR = 0, 1, 2, 3, 4
WHITE = (1, 1, 1)
BOXES = [
    ("Hips", (-0.17, 0.86, -0.11), (0.17, 1.05, 0.11), FEET, WHITE),        # belt + pelvis
    ("Spine", (-0.17, 1.05, -0.11), (0.17, 1.20, 0.11), TORSO, WHITE),
    ("Chest", (-0.18, 1.20, -0.12), (0.18, 1.33, 0.12), TORSO, WHITE),
    ("UpperChest", (-0.20, 1.33, -0.12), (0.20, 1.48, 0.12), TORSO, WHITE),
    ("Neck", (-0.05, 1.48, -0.05), (0.05, 1.55, 0.05), SKIN, WHITE),
    ("Head", (-0.11, 1.55, -0.12), (0.11, 1.79, 0.11), SKIN, WHITE),
    ("Head", (-0.12, 1.70, -0.13), (0.12, 1.82, 0.10), HAIR, WHITE),        # hair cap
    ("Head", (-0.12, 1.58, -0.14), (0.12, 1.72, -0.10), HAIR, WHITE),       # hair back
    ("Head", (0.04, 1.65, 0.11), (0.08, 1.68, 0.115), SKIN, (0.15, 0.12, 0.10)),   # eyes
    ("Head", (-0.08, 1.65, 0.11), (-0.04, 1.68, 0.115), SKIN, (0.15, 0.12, 0.10)),
    ("LeftUpperArm", (0.20, 1.38, -0.06), (0.46, 1.50, 0.06), TORSO, WHITE),
    ("LeftLowerArm", (0.46, 1.39, -0.05), (0.70, 1.49, 0.05), SKIN, WHITE),
    ("LeftHand", (0.70, 1.39, -0.05), (0.80, 1.49, 0.05), SKIN, WHITE),
    ("RightUpperArm", (-0.46, 1.38, -0.06), (-0.20, 1.50, 0.06), TORSO, WHITE),
    ("RightLowerArm", (-0.70, 1.39, -0.05), (-0.46, 1.49, 0.05), SKIN, WHITE),
    ("RightHand", (-0.80, 1.39, -0.05), (-0.70, 1.49, 0.05), SKIN, WHITE),
    ("LeftUpperLeg", (0.02, 0.50, -0.08), (0.17, 0.92, 0.08), LEGS, WHITE),
    ("LeftLowerLeg", (0.03, 0.08, -0.07), (0.16, 0.50, 0.07), LEGS, WHITE),
    ("LeftFoot", (0.03, 0.0, -0.07), (0.16, 0.08, 0.10), FEET, WHITE),
    ("LeftToes", (0.03, 0.0, 0.10), (0.16, 0.06, 0.16), FEET, WHITE),
    ("RightUpperLeg", (-0.17, 0.50, -0.08), (-0.02, 0.92, 0.08), LEGS, WHITE),
    ("RightLowerLeg", (-0.16, 0.08, -0.07), (-0.03, 0.50, 0.07), LEGS, WHITE),
    ("RightFoot", (-0.16, 0.0, -0.07), (-0.03, 0.08, 0.10), FEET, WHITE),
    ("RightToes", (-0.16, 0.0, 0.10), (-0.03, 0.06, 0.16), FEET, WHITE),
]
CELL = 0.05


def hash01(*v):
    h = 2166136261
    for x in v:
        h = ((h ^ (x & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    h ^= h >> 13; h = (h * 0x5bd1e995) & 0xFFFFFFFF; h ^= h >> 15
    return h / 4294967296.0


def build_mesh():
    pos, nrm, col, zon, jnt = [], [], [], [], []
    idx = []
    for bi, (bone, lo, hi, zone, rgb) in enumerate(BOXES):
        j = BI[bone]
        for axis in range(3):
            for side in (0, 1):
                u, v = [a for a in range(3) if a != axis]
                n = [0, 0, 0]; n[axis] = 1 if side else -1
                c = hi[axis] if side else lo[axis]
                nu = max(1, round((hi[u] - lo[u]) / CELL)); nv = max(1, round((hi[v] - lo[v]) / CELL))
                for iu in range(nu):
                    for iv in range(nv):
                        u0 = lo[u] + (hi[u] - lo[u]) * iu / nu; u1 = lo[u] + (hi[u] - lo[u]) * (iu + 1) / nu
                        v0 = lo[v] + (hi[v] - lo[v]) * iv / nv; v1 = lo[v] + (hi[v] - lo[v]) * (iv + 1) / nv
                        k = 0.86 + 0.14 * hash01(bi, axis, side, iu, iv)    # voxel-cell shading
                        base = len(pos)
                        for (a, b) in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
                            p = [0, 0, 0]; p[axis] = c; p[u] = a; p[v] = b
                            pos.append(p); nrm.append(n); col.append([rgb[0] * k, rgb[1] * k, rgb[2] * k]); zon.append(zone); jnt.append(j)
                        # winding: counter-clockwise seen from outside
                        cross_ok = ((u - axis) % 3 == 1) == bool(side)
                        if cross_ok:
                            idx += [base, base + 1, base + 2, base, base + 2, base + 3]
                        else:
                            idx += [base, base + 2, base + 1, base, base + 3, base + 2]
    return pos, nrm, col, zon, jnt, idx


# ---------------------------------------------------------------- animation
def qaxis(ax, ang):
    s = math.sin(ang / 2)
    return [ax[0] * s, ax[1] * s, ax[2] * s, math.cos(ang / 2)]


def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]


X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)
ID = [0, 0, 0, 1]


def pose_fn(clip):
    """returns f(phase in [0,1)) -> {bone: quat}, {bone: translation offset}"""
    tau = 2 * math.pi
    def idle(t):
        b = math.sin(t * tau)
        return ({"Chest": qaxis(X, 0.02 * b), "LeftUpperArm": qaxis(Z, -1.25), "RightUpperArm": qaxis(Z, 1.25),
                 "Head": qaxis(Y, 0.08 * math.sin(t * tau * 0.5 + 1))}, {"Hips": (0, 0.004 * b, 0)})
    def walk(t, amp=0.5, arm=0.45, bob=0.02):
        s = math.sin(t * tau); c = math.cos(t * tau)
        return ({"LeftUpperLeg": qaxis(X, -amp * s), "RightUpperLeg": qaxis(X, amp * s),
                 "LeftLowerLeg": qaxis(X, amp * 1.2 * max(0, c)), "RightLowerLeg": qaxis(X, amp * 1.2 * max(0, -c)),
                 "LeftUpperArm": qmul(qaxis(X, arm * s), qaxis(Z, -1.3)), "RightUpperArm": qmul(qaxis(X, -arm * s), qaxis(Z, 1.3)),
                 "LeftLowerArm": qaxis(Y, 0.3), "RightLowerArm": qaxis(Y, -0.3),
                 "Spine": qaxis(Y, 0.08 * s), "Chest": qaxis(X, 0.05 if amp > 0.6 else 0.0)},
                {"Hips": (0, -bob + bob * abs(math.cos(t * tau)), 0)})
    def run(t):
        return walk(t, amp=0.9, arm=0.9, bob=0.05)
    def swing_axe(t):
        # raise overhead (0..0.55), strike forward-down (0.55..0.7), recover
        if t < 0.55: k = t / 0.55; a = -0.3 - 2.5 * (0.5 - 0.5 * math.cos(k * math.pi))
        elif t < 0.7: k = (t - 0.55) / 0.15; a = -2.8 + 2.2 * k
        else: k = (t - 0.7) / 0.3; a = -0.6 + 0.3 * k
        return ({"RightUpperArm": qmul(qaxis(X, a), qaxis(Z, 1.1)), "LeftUpperArm": qmul(qaxis(X, a * 0.9), qaxis(Z, -1.1)),
                 "RightLowerArm": qaxis(X, -0.4), "LeftLowerArm": qaxis(X, -0.4),
                 "Spine": qaxis(X, 0.25 if 0.55 <= t < 0.8 else -0.08), "LeftUpperLeg": qaxis(X, -0.25), "RightUpperLeg": qaxis(X, 0.15)}, {})
    def talk_calm(t):
        s = math.sin(t * tau)
        return ({"LeftUpperArm": qaxis(Z, -1.2), "RightUpperArm": qmul(qaxis(X, -0.6 - 0.2 * s), qaxis(Z, 1.15)),
                 "RightLowerArm": qaxis(Y, -0.9 - 0.3 * s), "Head": qaxis(X, 0.06 * math.sin(t * tau * 2)),
                 "Neck": qaxis(Y, 0.1 * s)}, {})
    def wave(t):
        s = math.sin(t * tau * 2)
        return ({"LeftUpperArm": qaxis(Z, -1.25), "RightUpperArm": qaxis(Z, -0.3),
                 "RightLowerArm": qaxis(Z, -0.4 + 0.4 * s), "Head": qaxis(Z, -0.08)}, {})
    def sit_idle(t):
        b = math.sin(t * tau)
        return ({"LeftUpperLeg": qaxis(X, -1.55), "RightUpperLeg": qaxis(X, -1.55),
                 "LeftLowerLeg": qaxis(X, 1.55), "RightLowerLeg": qaxis(X, 1.55),
                 "LeftUpperArm": qmul(qaxis(X, -0.5), qaxis(Z, -1.3)), "RightUpperArm": qmul(qaxis(X, -0.5), qaxis(Z, 1.3)),
                 "Chest": qaxis(X, 0.02 * b)}, {"Hips": (0, -0.47, 0)})
    return {"idle": idle, "walk": walk, "run": run, "swing_axe": swing_axe, "talk_calm": talk_calm, "wave": wave, "sit_idle": sit_idle}[clip]


CLIPS = [  # name, duration s, loop, ref speed m/s, events (name, phase)
    ("idle", 3.0, True, 0.0, []),
    ("walk", 1.1, True, 1.4, [("footstep_l", 0.25), ("footstep_r", 0.75)]),
    ("run", 0.7, True, 3.6, [("footstep_l", 0.25), ("footstep_r", 0.75)]),
    ("swing_axe", 1.4, False, 0.0, [("impact", 0.68)]),
    ("talk_calm", 2.4, True, 0.0, []),
    ("wave", 1.2, False, 0.0, []),
    ("sit_idle", 4.0, True, 0.0, []),
]
FPS = 30


# ---------------------------------------------------------------- glTF writer
class Buf:
    def __init__(self): self.data = bytearray(); self.views = []; self.accs = []

    def add(self, fmt, rows, comp, typ, count, target=None, minmax=False):
        while len(self.data) % 4: self.data.append(0)
        off = len(self.data)
        for r in rows:
            self.data += struct.pack("<" + fmt, *(r if isinstance(r, (list, tuple)) else [r]))
        view = {"buffer": 0, "byteOffset": off, "byteLength": len(self.data) - off}
        if target: view["target"] = target
        self.views.append(view)
        acc = {"bufferView": len(self.views) - 1, "componentType": comp, "count": count, "type": typ}
        if minmax:
            n = len(rows[0]) if isinstance(rows[0], (list, tuple)) else 1
            cols = [[(r[i] if n > 1 else r) for r in rows] for i in range(n)]
            acc["min"] = [min(c) for c in cols]; acc["max"] = [max(c) for c in cols]
        self.accs.append(acc)
        return len(self.accs) - 1


def main(out):
    pos, nrm, col, zon, jnt, idx = build_mesh()
    B = Buf()
    a_pos = B.add("3f", pos, 5126, "VEC3", len(pos), 34962, minmax=True)
    a_nrm = B.add("3f", nrm, 5126, "VEC3", len(nrm), 34962)
    a_col = B.add("3f", col, 5126, "VEC3", len(col), 34962)
    a_zon = B.add("f", zon, 5126, "SCALAR", len(zon), 34962)
    a_jnt = B.add("4B", [[j, 0, 0, 0] for j in jnt], 5121, "VEC4", len(jnt), 34962)
    a_wgt = B.add("4f", [[1, 0, 0, 0]] * len(jnt), 5126, "VEC4", len(jnt), 34962)
    a_idx = B.add("I", idx, 5125, "SCALAR", len(idx), 34963)

    nodes = []
    for name, parent, head in BONES:
        ph = BONES[BI[parent]][2] if parent else (0, 0, 0)
        nodes.append({"name": name, "translation": [head[i] - ph[i] for i in range(3)]})
    for i, (name, parent, _) in enumerate(BONES):
        if parent: nodes[BI[parent]].setdefault("children", []).append(i)
    # inverse bind = translate(-head) (bones are unrotated in rest pose)
    ibm = []
    for _, _, h in BONES:
        ibm.append([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -h[0], -h[1], -h[2], 1])
    a_ibm = B.add("16f", ibm, 5126, "MAT4", len(ibm))
    mesh_node = len(nodes)
    nodes.append({"name": "villager_test_body", "mesh": 0, "skin": 0})
    scene_root = len(nodes)
    nodes.append({"name": "villager_test", "children": [BI["Root"], mesh_node]})

    animations = []
    for name, dur, loop, speed, events in CLIPS:
        f = pose_fn(name)
        n = max(2, round(dur * FPS) + 1)
        times = [dur * k / (n - 1) for k in range(n)]
        a_t = B.add("f", times, 5126, "SCALAR", n, minmax=True)
        samples = [f((k / (n - 1)) % 1.0 if loop else k / (n - 1)) for k in range(n)]
        bones_r = sorted({b for s in samples for b in s[0]}); bones_t = sorted({b for s in samples for b in s[1]})
        samplers, channels = [], []
        for b in bones_r:
            rows = [s[0].get(b, ID) for s in samples]
            samplers.append({"input": a_t, "output": B.add("4f", rows, 5126, "VEC4", n), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": BI[b], "path": "rotation"}})
        for b in bones_t:
            base = nodes[BI[b]]["translation"]
            rows = [[base[i] + s[1].get(b, (0, 0, 0))[i] for i in range(3)] for s in samples]
            samplers.append({"input": a_t, "output": B.add("3f", rows, 5126, "VEC3", n), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": BI[b], "path": "translation"}})
        animations.append({"name": name, "samplers": samplers, "channels": channels,
                           "extras": {"loop": loop, "ref_speed_mps": speed, "fps": FPS,
                                      "events": [{"name": e, "time": round(p * dur, 4)} for e, p in events]}})

    gltf = {
        "asset": {"version": "2.0", "generator": "emergence make_test_villager.py"},
        "scene": 0, "scenes": [{"nodes": [scene_root]}],
        "nodes": nodes,
        "meshes": [{"name": "villager_test_body", "primitives": [{
            "attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "COLOR_0": a_col, "_DYEZONE": a_zon,
                           "JOINTS_0": a_jnt, "WEIGHTS_0": a_wgt}, "indices": a_idx, "material": 0}]}],
        "materials": [{"name": "villager_palette", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0, "roughnessFactor": 1}}],
        "skins": [{"name": "humanoid", "joints": list(range(len(BONES))), "inverseBindMatrices": a_ibm, "skeleton": BI["Root"]}],
        "animations": animations,
        "accessors": B.accs, "bufferViews": B.views,
        "buffers": [{"byteLength": len(B.data)}],
        "extras": {"emergence": {"schema_version": 1, "kind": "test_villager",
                                 "dye_zones": ["skin", "torso", "legs", "feet_belt", "hair"],
                                 "note": "stand-in; fingers omitted; replaced by the villager thread's skins"}},
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    while len(js) % 4: js += b" "
    bin_ = bytes(B.data)
    while len(bin_) % 4: bin_ += b"\0"
    total = 12 + 8 + len(js) + 8 + len(bin_)
    with open(out, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A)); fh.write(js)
        fh.write(struct.pack("<II", len(bin_), 0x004E4942)); fh.write(bin_)
    print(f"{out}: {len(pos)} vertices, {len(idx)//3} triangles, {len(BONES)} bones, {len(CLIPS)} clips, {total/1024:.0f} KB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "villager_test.glb")
