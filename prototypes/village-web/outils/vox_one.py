"""Voxelise une pièce du kit avec le convertisseur des devs (copie locale), sortie npz brute."""
import sys, time, numpy as np
sys.path.insert(0, '/tmp/claude-0/work/voxelizer')
from voxelizer.config import VoxelizeConfig
from voxelizer.loaders import load_scene
from voxelizer.surface import SurfaceVoxelizer
from voxelizer.solid import SolidFiller
from voxelizer.style import ColorStyler
from voxelizer.lattice import unpack

def run(src, out, seal=0, fill='solid'):
    cfg = VoxelizeConfig(fill=fill, seal_radius=seal, sharpen=0.0, saturation=1.0, contrast=1.0, max_dense_cells=250_000_000, max_entities=50_000_000)
    t=time.time()
    scene = load_scene(src, ())
    surf = SurfaceVoxelizer(cfg).voxelize(scene)
    f = SolidFiller(cfg).fill(surf, scene)
    names=[p.material.name for p in scene.primitives]
    x,y,z = unpack(f.keys)
    mat = np.array(names+['?'])[f.material.astype(int)]
    np.savez_compressed(out, xyz=np.stack([x,y,z],1).astype(np.int16), rgb=f.rgb, alpha=f.alpha, mat=mat, kind=f.kind)
    print(f"{src.split('/')[-1]} {len(f.keys)} vox surf={int((f.kind==0).sum())} int={int((f.kind==1).sum())} {time.time()-t:.1f}s notes={scene.notes}", flush=True)

if __name__=='__main__':
    run(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv)>3 else 0)
