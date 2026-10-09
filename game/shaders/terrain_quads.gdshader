// Terrain by vertex pulling (architecture § 4): the vertex buffer is a shared
// list of vertex numbers; each region's quads (8 bytes each, layout in
// engine/core/mesh/include/emergence/mesh/greedy.h) are read from a texture
// and expanded here into the four corners of the quad. VRAM per quad: 8 bytes.
shader_type spatial;
render_mode cull_back;

uniform sampler2D quads : filter_nearest, repeat_disable;
uniform sampler2D palette : filter_nearest, repeat_disable;  // sRGB bytes, decoded below (texelFetch skips the hint on some drivers)
uniform int quad_count = 0;
uniform int quad_offset = 0;
uniform float cell = 0.02;  // voxel edge in metres at this level of detail
uniform float ao_strength = 0.55;

varying vec3 v_local;    // map position in voxels of this level, for colour noise
varying vec3 v_n;        // map normal
varying float v_ao;

uint word(int texel) {
	vec4 t = texelFetch(quads, ivec2(texel % 2048, texel / 2048), 0);
	uvec4 b = uvec4(round(t * 255.0));
	return b.r | (b.g << 8u) | (b.b << 16u) | (b.a << 24u);
}

void vertex() {
	int vid = int(VERTEX.x + 0.5);
	int qi = vid / 4 + quad_offset;
	int corner = vid % 4;
	if (qi >= quad_count) {
		VERTEX = vec3(0.0);
		NORMAL = vec3(0.0, 1.0, 0.0);
		COLOR = vec4(0.0);
		v_ao = 3.0;
		v_local = vec3(0.0);
		v_n = vec3(0.0);
	} else {
		uint lo = word(qi * 2);
		uint hi = word(qi * 2 + 1);
		ivec3 p = ivec3(int(lo & 63u), int((lo >> 6u) & 63u), int((lo >> 12u) & 63u));
		int w = int((lo >> 18u) & 63u) + 1;
		int h = int((lo >> 24u) & 63u) + 1;
		int dir = int(lo >> 30u) | (int(hi & 1u) << 2);
		int cls = int((hi >> 1u) & 511u);
		uint ao = (hi >> 10u) & 255u;
		int slot = int((hi >> 18u) & 511u);
		ivec3 chunk = ivec3(slot & 7, slot >> 6, (slot >> 3) & 7);
		// Map axes: n normal, U the quad's w axis, V its h axis.
		ivec3 n; ivec3 U; ivec3 V;
		if (dir < 2) { n = ivec3(dir == 0 ? 1 : -1, 0, 0); U = ivec3(0, 0, 1); V = ivec3(0, 1, 0); }
		else if (dir < 4) { n = ivec3(0, dir == 2 ? 1 : -1, 0); U = ivec3(1, 0, 0); V = ivec3(0, 0, 1); }
		else { n = ivec3(0, 0, dir == 4 ? 1 : -1); U = ivec3(1, 0, 0); V = ivec3(0, 1, 0); }
		vec3 ng = vec3(float(n.x), float(n.y), -float(n.z));
		vec3 ug = vec3(float(U.x), float(U.y), -float(U.z));
		vec3 vg = vec3(float(V.x), float(V.y), -float(V.z));
		// Godot's front faces are clockwise: triangles (0,1,2) (0,2,3) over
		// corners (0,0) (1,0) (1,1) (0,1) face the wrong way when U x V points
		// along the normal; then walk the corners the other way round.
		ivec2 uv = corner == 0 ? ivec2(0, 0) : corner == 1 ? ivec2(1, 0) : corner == 2 ? ivec2(1, 1) : ivec2(0, 1);
		if (dot(cross(ug, vg), ng) > 0.0 && (corner == 1 || corner == 3)) uv = uv.yx;
		vec3 base = vec3(chunk * 64 + p) + vec3(max(n, ivec3(0)));
		vec3 pm = base + vec3(U * (uv.x * w) + V * (uv.y * h));
		v_local = pm;
		v_n = vec3(n);
		VERTEX = vec3(pm.x, pm.y, -pm.z) * cell;
		NORMAL = ng;
		int ci = uv.x + 2 * uv.y;
		v_ao = float((ao >> uint(2 * ci)) & 3u);
		vec3 srgb = texelFetch(palette, ivec2(cls % 64, cls / 64), 0).rgb;
		COLOR = vec4(mix(srgb / 12.92, pow((srgb + 0.055) / 1.055, vec3(2.4)), step(0.04045, srgb)), 1.0);
	}
}

float hash13(vec3 p) {
	p = fract(p * 0.1031);
	p += dot(p, p.zyx + 31.32);
	return fract((p.x + p.y) * p.z);
}

void fragment() {
	// A merged quad spans many voxels: find the voxel under this pixel from
	// the interpolated position, for a small per-voxel brightness variation.
	vec3 vox = floor(v_local - v_n * 0.5);
	float k = 0.94 + 0.08 * hash13(vox);
	float ao = mix(1.0 - ao_strength, 1.0, v_ao / 3.0);
	ALBEDO = COLOR.rgb * k * ao;
	ROUGHNESS = 0.92;
	SPECULAR = 0.2;
}
