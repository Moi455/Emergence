extends Node3D
## Shows the generated terrain around a settlement with greedy-meshed LOD
## rings (2 cm, then 4 cm voxels). Command line (after --):
##   --site town|port|miners|oasis|foresters   --shot path.png   --seed N
## With --shot, saves a screenshot and quits.

var site := "town"
var shot := ""
var world_seed := 1

func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in args.size():
		if args[i] == "--site" and i + 1 < args.size(): site = args[i + 1]
		if args[i] == "--shot" and i + 1 < args.size(): shot = args[i + 1]
		if args[i] == "--seed" and i + 1 < args.size(): world_seed = int(args[i + 1])
	var world := EmergenceWorld.new()
	var info: Dictionary = world.generate(world_seed, 20000)
	var at := Vector2.ZERO
	for s in info["settlements"]:
		if s["kind"] == site: at = Vector2(s["x_m"], s["z_m"])
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.cull_mode = BaseMaterial3D.CULL_BACK
	mat.roughness = 0.95
	var rings := [[0, 0, 24]]  # [lod, inner, outer] in chunks of that LOD
	for r in rings:
		var mesh: ArrayMesh = world.build_terrain_mesh(at.x, at.y, r[0], r[1], r[2])
		var st: Dictionary = world.last_mesh_stats()
		print("EMERGENCE ring lod=%d chunks=%d quads=%d build_ms=%.0f" % [r[0], st["chunks"], st["quads"], st["ms"]])
		var mi := MeshInstance3D.new()
		mi.mesh = mesh
		mi.material_override = mat
		add_child(mi)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-38, -35, 0)
	sun.shadow_enabled = true
	add_child(sun)
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_SKY
	env.environment.sky = Sky.new()
	env.environment.sky.sky_material = ProceduralSkyMaterial.new()
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.environment.fog_enabled = true
	env.environment.fog_density = 0.004
	add_child(env)
	var cam := Camera3D.new()
	cam.position = Vector3(0, 6.0, 12.0)
	cam.fov = 70
	cam.far = 2000
	add_child(cam)
	cam.look_at(Vector3(0, 0.5, -10))
	if shot != "":
		for i in 4:
			await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(shot)
		print("EMERGENCE screenshot ", shot)
		get_tree().quit()
