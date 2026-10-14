"""Write the village plan as VXI1 (docs/interfaces.md § 2): module name, pivot in world voxels, quarter turns around +y.
Input: instances.json from dump_instances.js, in the prototype's glTF axes; output in world axes (z_world = -z_gltf)."""
import sys, json, struct, zlib
L = json.load(open(sys.argv[1]))
out = bytearray(b'VXI1') + struct.pack('<HI', 1, len(L))
for name, x, y, z, r in L:
    nm = name.encode()
    out += struct.pack('<B', len(nm)) + nm + struct.pack('<iiiBB', x, y, -z, r, 0)
out += struct.pack('<I', zlib.crc32(bytes(out)) & 0xffffffff)
open(sys.argv[2], 'wb').write(out)
print('instances', len(L), 'bytes', len(out))
