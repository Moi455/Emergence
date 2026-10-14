extends Node3D
## Smoke test of the engine core from Godot: generates the world plan and
## prints its fingerprint, timings and settlements.

@export var world_seed: int = 1
@export var map_size_m: int = 20000

func _ready() -> void:
	var world := EmergenceWorld.new()
	var info: Dictionary = world.generate(world_seed, map_size_m)
	print("EMERGENCE plan fingerprint=%s total_ms=%.0f" % [info["fingerprint"], info["total_ms"]])
	for s in info["settlements"]:
		print("EMERGENCE settlement %s at (%.0f m, %.0f m) height %.1f m" % [s["kind"], s["x_m"], s["z_m"], world.surface_height_m(s["x_m"], s["z_m"])])
	if OS.has_feature("headless") or DisplayServer.get_name() == "headless":
		get_tree().quit()
