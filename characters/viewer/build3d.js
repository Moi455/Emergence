// three.js helpers shared by the gallery and the thumbnail renderer: build a skinned
// villager straight from the generator's mesh buffers, and its animation clips.
import * as THREE from 'three';
import { makeClips } from '../gen/anim.js';

export function buildSkeleton(sk, voxel) {
  const bones = sk.bones.map(b => { const o = new THREE.Bone(); o.name = b.name; return o; });
  sk.bones.forEach((b, i) => {
    const p = b.parent >= 0 ? sk.bones[b.parent].head : [0, 0, 0];
    bones[i].position.set((b.head[0] - p[0]) * voxel, (b.head[1] - p[1]) * voxel, (b.head[2] - p[2]) * voxel);
    if (b.parent >= 0) bones[b.parent].add(bones[i]);
  });
  return bones;
}

export function buildMesh(mesh, bones) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(mesh.positions, 3));
  g.setAttribute('uv', new THREE.BufferAttribute(mesh.uvs, 2));
  g.setAttribute('skinIndex', new THREE.BufferAttribute(mesh.joints, 4));
  g.setAttribute('skinWeight', new THREE.BufferAttribute(mesh.weights, 4));
  g.setIndex(new THREE.BufferAttribute(mesh.indices, 1));
  g.computeVertexNormals(); // vertices are not shared between quads: flat normals
  const tex = new THREE.DataTexture(mesh.atlas.data, mesh.atlas.w, mesh.atlas.h, THREE.RGBAFormat);
  tex.magFilter = tex.minFilter = THREE.NearestFilter; tex.generateMipmaps = false;
  tex.colorSpace = THREE.SRGBColorSpace; tex.flipY = false; tex.needsUpdate = true;
  const mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.92, metalness: 0 });
  const m = new THREE.SkinnedMesh(g, mat);
  m.castShadow = true; m.receiveShadow = true;
  m.frustumCulled = false;
  return m;
}

export function attach(meshObj, bones) {
  const skel = new THREE.Skeleton(bones);
  meshObj.add(bones[0]);
  meshObj.bind(skel);
  return skel;
}

export function threeClips(sk, bp) {
  return makeClips(sk, bp).map(c => {
    const tracks = [];
    for (const [bn, t] of Object.entries(c.tracks))
      tracks.push(new THREE.QuaternionKeyframeTrack(bn + '.quaternion', t.times, t.rotations.flat()));
    if (c.rootY) {
      const hb = sk.bones[sk.byName.Hips], p = sk.bones[hb.parent].head;
      const vs = [];
      // translations are filled in by the caller-scale below (voxel units -> metres done by caller)
      c.rootY.values.forEach(v => vs.push(0, v, 0));
      tracks.push({ rootY: true, times: c.rootY.times, values: vs });
    }
    return { name: c.name, duration: c.duration, tracks };
  });
}

export function makeClip(c, hipsRest) {
  const tracks = c.tracks.map(t => {
    if (!t.rootY) return t;
    const vals = [];
    for (let i = 0; i < t.values.length; i += 3) vals.push(hipsRest.x, hipsRest.y + t.values[i + 1], hipsRest.z);
    return new THREE.VectorKeyframeTrack('Hips.position', t.times, vals);
  });
  return new THREE.AnimationClip(c.name, c.duration, tracks);
}

// One villager object: group with a skinned mesh per requested outfit sharing one skeleton.
export function villagerObject(base, meshes) {
  const group = new THREE.Group();
  const bones = buildSkeleton(base.sk, base.voxel);
  group.add(bones[0]);
  group.updateMatrixWorld(true);
  const skel = new THREE.Skeleton(bones);
  const objs = {};
  for (const [name, mesh] of Object.entries(meshes)) {
    const m = buildMesh(mesh, bones);
    m.bind(skel, new THREE.Matrix4());
    m.name = name; group.add(m); objs[name] = m;
  }
  const clips = threeClips(base.sk, base.bp).map(c => makeClip(c, bones[base.sk.byName.Hips].position));
  return { group, bones, skel, outfits: objs, clips };
}
