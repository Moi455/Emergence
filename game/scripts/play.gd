extends Node3D
## Playable terrain: walk, run, fly and dig in the 2 cm voxel world generated
## by the C++ core, with LOD rings streamed around the player out to ~700 m.
##
## Controls: mouse look (click to capture, Esc to release), WASD move,
## Shift run, Space jump, F fly (Space / C up and down), left click dig,
## right click place earth, 1-4 brush size, H info panel, L shadows.
##
## Command line (after --): --site market_town|sea_village|mountain_village|
## desert_village|forest_village  --seed N  --shot path.png  --view high
## --autotest (digs in front of the camera, checks the hole, saves path_dig.png)

const SHADER := preload("res://shaders/terrain_quads.gdshader")
const MAX_QUADS_PER_DRAW := 262144

var world := EmergenceWorld.new()
var site := "market_town"
var world_seed := 1
var shot := ""
var view_high := false
var autotest := false

var player: CharacterBody3D
var head: Node3D
var camera: Camera3D
var sun: DirectionalLight3D
var terrain_root: Node3D
var collider: CollisionShape3D
var hud: Label
var regions := {}            # key -> Array[MeshInstance3D]
var region_quads := {}       # key -> quad count
var buckets := {}            # quads -> ArrayMesh shared by every region
var palette: Texture2D
var collision_chunk := Vector3i(1 << 30, 0, 0)
var collision_dirty := true
var flying := false
var brush := 0.25
var yaw := 0.0
var pitch := -0.15
var quiet_frames := 0
var frames := 0
var gen_ms := 0.0


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in args.size():
		var a := args[i]
		var nxt := args[i + 1] if i + 1 < args.size() else ""
		if a == "--site": site = nxt
		elif a == "--seed": world_seed = int(nxt)
		elif a == "--shot": shot = nxt
		elif a == "--view": view_high = nxt == "high"
		elif a == "--autotest": autotest = true

	var t0 := Time.get_ticks_msec()
	var info: Dictionary = world.generate(world_seed, 20000)
	gen_ms = Time.get_ticks_msec() - t0
	var at := Vector2(10000, 10000)
	for s in info["settlements"]:
		if s["id"] == site or s["kind"] == site:
			at = Vector2(s["x_m"], s["z_m"])
	world.set_anchor(at.x, at.y)
	print("EMERGENCE world seed=%d fingerprint=%s generated in %.0f ms, site %s at (%.0f, %.0f)" % [
		world_seed, info["fingerprint"], gen_ms, site, at.x, at.y])

	palette = EmergenceWorld.material_palette()
	terrain_root = Node3D.new()
	terrain_root.name = "Terrain"
	add_child(terrain_root)
	_make_environment()
	_make_player()
	_make_hud()

	world.start_streaming({"lods": 6, "half": 8, "ao_max_lod": 2})
	world.set_view(player.position)
	_update_collision(true)


func _make_environment() -> void:
	sun = DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-42, -35, 0)
	sun.light_energy = 0.9
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 120.0
	add_child(sun)
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = Sky.new()
	var sky := ProceduralSkyMaterial.new()
	sky.sky_horizon_color = Color(0.72, 0.78, 0.85)
	sky.ground_horizon_color = Color(0.72, 0.78, 0.85)
	env.sky.sky_material = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.6
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.fog_enabled = true
	env.fog_light_color = Color(0.72, 0.78, 0.86)
	env.fog_density = 0.0016
	env.fog_aerial_perspective = 0.6
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)


func _make_player() -> void:
	player = CharacterBody3D.new()
	player.name = "Player"
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.3
	capsule.height = 1.75
	shape.shape = capsule
	shape.position.y = 0.875
	player.add_child(shape)
	player.floor_snap_length = 0.3
	player.floor_max_angle = deg_to_rad(50)
	head = Node3D.new()
	head.position.y = 1.62
	player.add_child(head)
	camera = Camera3D.new()
	camera.fov = 75
	camera.near = 0.03
	camera.far = 2500
	head.add_child(camera)
	add_child(player)
	var g := world.ground_height(Vector3.ZERO)
	player.position = Vector3(0, g + 0.2, 0)
	if view_high:
		head.position = Vector3(0, 14, 18)
		pitch = -0.45

	var body := StaticBody3D.new()
	body.name = "TerrainCollision"
	collider = CollisionShape3D.new()
	body.add_child(collider)
	add_child(body)


func _make_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	hud = Label.new()
	hud.position = Vector2(12, 10)
	hud.add_theme_color_override("font_shadow_color", Color.BLACK)
	layer.add_child(hud)
	var cross := Label.new()
	cross.text = "+"
	cross.set_anchors_preset(Control.PRESET_CENTER)
	cross.add_theme_font_size_override("font_size", 22)
	layer.add_child(cross)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		if Input.mouse_mode != Input.MOUSE_MODE_CAPTURED:
			Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
			return
		if event.button_index == MOUSE_BUTTON_LEFT:
			_edit(true)
		elif event.button_index == MOUSE_BUTTON_RIGHT:
			_edit(false)
	elif event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		yaw -= event.relative.x * 0.0025
		pitch = clamp(pitch - event.relative.y * 0.0025, -1.5, 1.5)
	elif event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_ESCAPE: Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
			KEY_F: flying = not flying
			KEY_H: hud.visible = not hud.visible
			KEY_L: sun.shadow_enabled = not sun.shadow_enabled
			KEY_1: brush = 0.1
			KEY_2: brush = 0.25
			KEY_3: brush = 0.5
			KEY_4: brush = 1.0


func _edit(dig: bool) -> void:
	var dir := -camera.global_transform.basis.z
	var hit: Dictionary = world.raycast(camera.global_position, dir, 6.0)
	if not hit["hit"]:
		return
	if dig:
		world.dig(hit["position"] + dir * brush * 0.5, brush)
	else:
		var p: Vector3 = hit["position"] + hit["normal"] * brush
		if p.distance_to(player.position + Vector3(0, 0.9, 0)) > brush + 0.5:
			world.place(p, brush, "dirt")
	collision_dirty = true


func _physics_process(delta: float) -> void:
	player.rotation.y = yaw
	head.rotation.x = pitch
	var input := Vector3.ZERO
	if Input.is_key_pressed(KEY_W): input.z -= 1
	if Input.is_key_pressed(KEY_S): input.z += 1
	if Input.is_key_pressed(KEY_A): input.x -= 1
	if Input.is_key_pressed(KEY_D): input.x += 1
	var wish := (player.transform.basis * input.normalized())
	if flying:
		var v := wish * (40.0 if Input.is_key_pressed(KEY_SHIFT) else 12.0)
		if Input.is_key_pressed(KEY_SPACE): v.y += 10.0
		if Input.is_key_pressed(KEY_C): v.y -= 10.0
		player.velocity = v
		player.position += v * delta
		return
	if collider.shape == null:
		return  # wait for the ground under the player
	var speed := 5.0 if Input.is_key_pressed(KEY_SHIFT) else 1.6
	player.velocity.x = wish.x * speed
	player.velocity.z = wish.z * speed
	if player.is_on_floor():
		if Input.is_key_pressed(KEY_SPACE):
			player.velocity.y = 4.2
	else:
		player.velocity.y -= 9.8 * delta
	player.move_and_slide()
	if player.position.y < world.ground_height(player.position) - 30.0:
		player.position.y = world.ground_height(player.position) + 1.0  # fell out of the world
		player.velocity = Vector3.ZERO


func _process(_delta: float) -> void:
	frames += 1
	world.set_view(player.position)
	var batch: Array = world.poll_regions(24)
	for r in batch:
		_apply_region(r)
	quiet_frames = quiet_frames + 1 if batch.is_empty() else 0
	_update_collision(false)
	if hud.visible and frames % 10 == 0:
		_update_hud()
	if shot != "":
		_maybe_shoot()


func _apply_region(r: Dictionary) -> void:
	var key: String = r["key"]
	if regions.has(key):
		for mi in regions[key]:
			mi.queue_free()
		regions.erase(key)
		region_quads.erase(key)
	if r["removed"] or r["quad_count"] == 0:
		return
	var count: int = r["quad_count"]
	var size: float = r["size"]
	var parts: Array = []
	var offset := 0
	while offset < count:
		var n: int = min(count - offset, MAX_QUADS_PER_DRAW)
		var mi := MeshInstance3D.new()
		mi.mesh = _bucket(n)
		var mat := ShaderMaterial.new()
		mat.shader = SHADER
		mat.set_shader_parameter("quads", r["quads"])
		mat.set_shader_parameter("palette", palette)
		mat.set_shader_parameter("quad_count", count)
		mat.set_shader_parameter("quad_offset", offset)
		mat.set_shader_parameter("cell", r["cell"])
		mi.material_override = mat
		mi.custom_aabb = AABB(Vector3(0, 0, -size), Vector3(size, size, size))
		mi.position = r["origin"]
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON if int(r["lod"]) <= 2 else GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		terrain_root.add_child(mi)
		parts.append(mi)
		offset += n
	regions[key] = parts
	region_quads[key] = count


func _bucket(n: int) -> ArrayMesh:
	var b := 1024
	while b < n:
		b *= 2
	if not buckets.has(b):
		buckets[b] = EmergenceWorld.quad_index_mesh(b)
	return buckets[b]


func _update_collision(force: bool) -> void:
	var m: Vector3 = world.to_map(player.position)
	var c := Vector3i(floori(m.x / 1.28), floori(m.y / 1.28), floori(m.z / 1.28))
	if not force and not collision_dirty and c == collision_chunk:
		return
	collision_chunk = c
	collision_dirty = false
	var faces: PackedVector3Array = world.collision_faces(player.position, 1)
	var shape := ConcavePolygonShape3D.new()
	shape.backface_collision = true
	shape.set_faces(faces)
	collider.shape = shape


func _update_hud() -> void:
	var st: Dictionary = world.streaming_stats()
	var total := 0
	for k in region_quads:
		total += region_quads[k]
	var m: Vector3 = world.to_map(player.position)
	hud.text = "%d fps   %s\nx %.1f  z %.1f  altitude %.1f m   %s\nterrain: %.2f M quads in %d regions, %d to build, cache %.0f MB\nbrush %.0f cm   F fly   left dig   right place   H hide" % [
		Engine.get_frames_per_second(), RenderingServer.get_video_adapter_name(),
		m.x, m.z, m.y, "flying" if flying else "walking",
		total / 1e6, regions.size(), st.get("pending", 0), st.get("cache_mb", 0.0), brush * 100]


func _maybe_shoot() -> void:
	var st: Dictionary = world.streaming_stats()
	var done: bool = int(st.get("pending", 1)) == 0 and quiet_frames > 30
	if not done and frames < 6000:
		return
	var total := 0
	for k in region_quads:
		total += region_quads[k]
	var path := shot
	shot = ""  # one capture only
	print("EMERGENCE streamed %d regions, %.2f M quads, %d chunks generated, busy %.0f ms, after %d frames" % [
		regions.size(), total / 1e6, st.get("chunks_generated", 0), st.get("busy_ms", 0.0), frames])
	_update_hud()
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png(path)
	print("EMERGENCE screenshot ", path)
	if autotest:
		await _autotest(path)
	get_tree().quit()


func _autotest(shot_path: String) -> void:
	var dir := -camera.global_transform.basis.z
	var before: Dictionary = world.raycast(camera.global_position, dir, 60.0)
	print("EMERGENCE raycast ", before)
	if not before["hit"]:
		return
	var p: Vector3 = before["position"]
	var changed := 0
	for i in 6:
		changed += world.dig(p + dir * (0.4 * i), 0.6)
	var after: Dictionary = world.raycast(camera.global_position, dir, 60.0)
	var deeper: float = (after["position"] - camera.global_position).length() - (p - camera.global_position).length() if after["hit"] else 99.0
	print("EMERGENCE dig: %d chunks changed, ray now hits %.2f m further (%s)" % [changed, deeper, "OK" if deeper > 1.0 else "FAIL"])
	quiet_frames = 0
	var waited := 0
	while waited < 600:
		await get_tree().process_frame
		waited += 1
		if int(world.streaming_stats().get("pending", 1)) == 0 and quiet_frames > 10:
			break
	await RenderingServer.frame_post_draw
	var path := shot_path.get_basename() + "_dig.png"
	get_viewport().get_texture().get_image().save_png(path)
	print("EMERGENCE screenshot ", path)
