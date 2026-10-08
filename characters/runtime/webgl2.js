// Villagers for a raw WebGL2 engine (the playable village prototype), no dependency.
// The generator runs in the page: seed -> skinned mesh + atlas; clips are sampled on the CPU
// and sent as one mat4 per skinning bone (the first 53; eyes, jaw and attachment points
// come after them and carry no weight) to the vertex shader.
//
//   const v = makeVillager(seed, catalog, { village, outfit: 'work', lod: 0 });
//   const gv = uploadVillager(gl, v);          // VAO + atlas texture
//   const prog = villagerProgram(gl);          // or splice VILLAGER_VS into your own shader
//   each frame: gv.pose('walk', time); gv.draw(prog, viewProj, model, sunDir);
import { generateVillager, composeOutfit, meshOutfit } from '../gen/villager.js';
import { makeClips, sampleClip, skinMatrices } from '../gen/anim.js';

export const SKIN_BONES = 53;

export function makeVillager(seed, catalog, opts = {}) {
  const v = generateVillager(seed, catalog, opts);
  const outfit = opts.outfit || 'everyday';
  const mesh = meshOutfit(v.base, composeOutfit(v, outfit, catalog), opts.lod || 0);
  const clips = Object.fromEntries(makeClips(v.base.sk, v.bp, v.base.voxel).map(c => [c.name, c]));
  return { v, mesh, clips, outfit };
}

// Change of clothes at run time: same skeleton, new mesh.
export function changeOutfit(villager, catalog, outfit, lod = 0) {
  villager.mesh = meshOutfit(villager.v.base, composeOutfit(villager.v, outfit, catalog), lod);
  villager.outfit = outfit;
  return villager;
}

export const VILLAGER_VS = `#version 300 es
precision highp float;
layout(location=0) in vec3 aPos;
layout(location=1) in vec2 aUV;
layout(location=2) in uvec4 aJoints;
layout(location=3) in vec4 aWeights;
uniform mat4 uBones[53];
uniform mat4 uModel, uViewProj;
out vec2 vUV; out vec3 vWorld;
void main() {
  mat4 skin = aWeights.x * uBones[aJoints.x] + aWeights.y * uBones[aJoints.y] + aWeights.z * uBones[aJoints.z] + aWeights.w * uBones[aJoints.w];
  vec4 w = uModel * skin * vec4(aPos, 1.0);
  vWorld = w.xyz; vUV = aUV;
  gl_Position = uViewProj * w;
}`;

export const VILLAGER_FS = `#version 300 es
precision highp float;
in vec2 vUV; in vec3 vWorld;
uniform sampler2D uAtlas;
uniform vec3 uSun;
out vec4 frag;
void main() {
  vec3 n = normalize(cross(dFdx(vWorld), dFdy(vWorld))); // flat voxel faces
  vec3 c = texture(uAtlas, vUV).rgb;                       // sRGB albedo with baked occlusion
  c = pow(c, vec3(2.2));
  float sun = max(dot(n, uSun), 0.0);
  float sky = 0.55 + 0.45 * n.y;
  vec3 lit = c * (vec3(1.0, 0.93, 0.82) * sun * 1.6 + vec3(0.62, 0.66, 0.74) * sky * 0.75);
  frag = vec4(pow(lit, vec3(1.0 / 2.2)), 1.0);
}`;

function compile(gl, type, src) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
  return s;
}
export function villagerProgram(gl, vs = VILLAGER_VS, fs = VILLAGER_FS) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs)); gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  p.u = { bones: gl.getUniformLocation(p, 'uBones'), model: gl.getUniformLocation(p, 'uModel'), vp: gl.getUniformLocation(p, 'uViewProj'), atlas: gl.getUniformLocation(p, 'uAtlas'), sun: gl.getUniformLocation(p, 'uSun') };
  return p;
}

export function uploadVillager(gl, villager) {
  const m = villager.mesh;
  const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
  const buf = (data, loc, size, type, integer) => {
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(loc);
    if (integer) gl.vertexAttribIPointer(loc, size, type, 0, 0); else gl.vertexAttribPointer(loc, size, type, false, 0, 0);
    return b;
  };
  const bufs = [buf(m.positions, 0, 3, gl.FLOAT), buf(m.uvs, 1, 2, gl.FLOAT), buf(m.joints, 2, 4, gl.UNSIGNED_SHORT, true), buf(m.weights, 3, 4, gl.FLOAT)];
  const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, m.indices, gl.STATIC_DRAW);
  gl.bindVertexArray(null);
  const tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, m.atlas.w, m.atlas.h, 0, gl.RGBA, gl.UNSIGNED_BYTE, m.atlas.data);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const base = villager.v.base;
  const mats = skinMatrices(base.sk, base.voxel, null);
  return {
    vao, tex, count: m.indices.length, bufs, ib, mats,
    // world matrix of any bone (e.g. RightHandProp to attach a tool): mats[i] * bind head
    boneIndex: name => base.sk.byName[name],
    clipDuration: name => villager.clips[name] ? villager.clips[name].duration : 0,
    pose(clipName, t) { const c = villager.clips[clipName]; skinMatrices(base.sk, base.voxel, c ? sampleClip(c, t) : null, mats); },
    draw(p, viewProj, model, sun = [-0.45, 0.8, 0.4]) {
      gl.useProgram(p);
      gl.uniformMatrix4fv(p.u.bones, false, mats.subarray(0, SKIN_BONES * 16)); gl.uniformMatrix4fv(p.u.model, false, model); gl.uniformMatrix4fv(p.u.vp, false, viewProj);
      const l = Math.hypot(...sun); gl.uniform3f(p.u.sun, sun[0] / l, sun[1] / l, sun[2] / l);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex); gl.uniform1i(p.u.atlas, 0);
      gl.bindVertexArray(vao); gl.drawElements(gl.TRIANGLES, this.count, gl.UNSIGNED_INT, 0); gl.bindVertexArray(null);
    },
    dispose() { bufs.forEach(b => gl.deleteBuffer(b)); gl.deleteBuffer(ib); gl.deleteTexture(tex); gl.deleteVertexArray(vao); },
  };
}
