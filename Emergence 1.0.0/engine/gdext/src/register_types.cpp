#include <gdextension_interface.h>

#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/core/defs.hpp>
#include <godot_cpp/godot.hpp>

#include "emergence_world.h"

namespace {

void initialize(godot::ModuleInitializationLevel level) {
  if (level != godot::MODULE_INITIALIZATION_LEVEL_SCENE) return;
  GDREGISTER_CLASS(em_godot::EmergenceWorld);
}

void uninitialize(godot::ModuleInitializationLevel) {}

}  // namespace

extern "C" GDExtensionBool GDE_EXPORT emergence_library_init(GDExtensionInterfaceGetProcAddress get_proc_address,
                                                             GDExtensionClassLibraryPtr library,
                                                             GDExtensionInitialization* init) {
  godot::GDExtensionBinding::InitObject obj(get_proc_address, library, init);
  obj.register_initializer(initialize);
  obj.register_terminator(uninitialize);
  obj.set_minimum_library_initialization_level(godot::MODULE_INITIALIZATION_LEVEL_SCENE);
  return obj.init();
}
