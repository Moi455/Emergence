// Material class table, loaded from data/materials.csv (content is data,
// never hard-coded). Class ids are part of the save format.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

#include "emergence/world/voxel_id.h"

namespace em {

struct Material {
  MaterialClass id = 0;
  std::string name;
  std::string category;
  int density_kg_m3 = 0;
  int hardness = 0;
  int flammability = 0;
  uint32_t color = 0;  // 0xRRGGBB
};

class MaterialTable {
 public:
  // Returns false and fills error on malformed input.
  bool load_csv(const std::string& path, std::string* error);
  bool parse_csv(const std::string& text, std::string* error);

  const Material* find(const std::string& name) const;
  // Class id by name; aborts if missing (generator needs every name it uses).
  MaterialClass require(const std::string& name) const;
  const Material& get(MaterialClass id) const { return by_id_[id]; }
  bool has(MaterialClass id) const { return id < by_id_.size() && !by_id_[id].name.empty(); }
  size_t size() const { return count_; }
  int schema_version() const { return schema_version_; }

  // Default table shipped with the engine (EMERGENCE_DATA_DIR/materials.csv).
  static const MaterialTable& builtin();

 private:
  std::vector<Material> by_id_;
  size_t count_ = 0;
  int schema_version_ = 0;
};

}  // namespace em
