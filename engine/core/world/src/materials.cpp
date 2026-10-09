#include "emergence/world/materials.h"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>

namespace em {

namespace {
std::vector<std::string> split(const std::string& s, char sep) {
  std::vector<std::string> out;
  std::string cur;
  for (char c : s) {
    if (c == sep) {
      out.push_back(cur);
      cur.clear();
    } else if (c != '\r') {
      cur.push_back(c);
    }
  }
  out.push_back(cur);
  return out;
}
}  // namespace

bool MaterialTable::load_csv(const std::string& path, std::string* error) {
  std::ifstream in(path);
  if (!in) {
    if (error) *error = "cannot open " + path;
    return false;
  }
  std::stringstream ss;
  ss << in.rdbuf();
  return parse_csv(ss.str(), error);
}

bool MaterialTable::parse_csv(const std::string& text, std::string* error) {
  by_id_.assign(kMaxClasses, Material{});
  count_ = 0;
  schema_version_ = 0;
  std::istringstream in(text);
  std::string line;
  bool header_seen = false;
  int line_no = 0;
  auto fail = [&](const std::string& msg) {
    if (error) *error = "materials.csv line " + std::to_string(line_no) + ": " + msg;
    return false;
  };
  while (std::getline(in, line)) {
    ++line_no;
    if (line.empty() || line[0] == '#' || line == "\r") continue;
    auto f = split(line, ',');
    if (f[0] == "schema_version") {
      if (f.size() < 2) return fail("schema_version without value");
      schema_version_ = std::atoi(f[1].c_str());
      continue;
    }
    if (!header_seen) {
      if (f[0] != "id") return fail("expected header line starting with 'id'");
      header_seen = true;
      continue;
    }
    if (f.size() != 7) return fail("expected 7 fields");
    int id = std::atoi(f[0].c_str());
    if (id < 0 || id >= kMaxClasses) return fail("id out of range");
    Material& m = by_id_[static_cast<size_t>(id)];
    if (!m.name.empty()) return fail("duplicate id");
    if (find(f[1])) return fail("duplicate name " + f[1]);
    m.id = static_cast<MaterialClass>(id);
    m.name = f[1];
    m.category = f[2];
    m.density_kg_m3 = std::atoi(f[3].c_str());
    m.hardness = std::atoi(f[4].c_str());
    m.flammability = std::atoi(f[5].c_str());
    m.color = static_cast<uint32_t>(std::strtoul(f[6].c_str(), nullptr, 16));
    ++count_;
  }
  if (schema_version_ != 1) return fail("unsupported schema_version");
  if (!has(0) || by_id_[0].name != "air") return fail("class 0 must be air");
  return true;
}

const Material* MaterialTable::find(const std::string& name) const {
  for (const auto& m : by_id_)
    if (m.name == name) return &m;
  return nullptr;
}

MaterialClass MaterialTable::require(const std::string& name) const {
  const Material* m = find(name);
  if (!m) {
    std::fprintf(stderr, "material '%s' missing from materials.csv\n", name.c_str());
    std::abort();
  }
  return m->id;
}

const MaterialTable& MaterialTable::builtin() {
  static const MaterialTable table = [] {
    MaterialTable t;
    std::string err;
    if (!t.load_csv(std::string(EMERGENCE_DATA_DIR) + "/materials.csv", &err)) {
      std::fprintf(stderr, "%s\n", err.c_str());
      std::abort();
    }
    return t;
  }();
  return table;
}

}  // namespace em
