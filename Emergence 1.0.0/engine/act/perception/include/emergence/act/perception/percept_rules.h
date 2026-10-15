// PerceptRules: the percept rules of the catalogue (gen::kRules, perception_gen.h) resolved once into the form the
// engine reads at each tick, and the ThingCatalog: what the world knows of the SORT of a thing (its properties).
//
// The truth stays on the world side: the ThingCatalog hands out ALL the properties of a sort (toxicity included), and the
// perception keeps only the perceptible ones (Catalogue.perceptible_properties) filtered by clarity. A rule whose source
// is engine-only cannot exist (the generator refuses it; the test re-checks the generated table).
#pragma once
#include <array>
#include <cstdint>
#include <span>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "emergence/act/entity_store.h"
#include "emergence/act/perception_gen.h"

namespace em::act::perception {

// Every percept variable the engine writes, in one list (X-macro): the field's rule is looked up by this name.
#define EM_PERCEPT_FIELDS(X)                                                                                               \
  X(ep_condition) X(ep_posture) X(ep_motion) X(ep_build) X(ep_attire) X(ep_wounds) X(ep_age) X(ep_sex) X(ep_held)         \
  X(ep_health) X(ep_marks) X(ep_expression) X(ep_signs) X(ep_gaze) X(ep_dist) X(ep_dir) X(pc_kind_seen) X(pc_color_seen)  \
  X(pc_props_seen) X(pc_state_seen) X(pc_amount_seen) X(pc_display) X(pc_motion) X(pc_depth_seen) X(pc_dist) X(pc_dir)    \
  X(pc_file) X(pc_file_certainty) X(pp_indoors) X(pp_light) X(pp_noise) X(pp_crowd_seen) X(pp_air_felt) X(ev_actor)       \
  X(ev_gesture) X(ev_target) X(ev_sense) X(ev_age)

enum class Field : std::uint8_t {
#define EM_X(n) n,
  EM_PERCEPT_FIELDS(EM_X)
#undef EM_X
  kCount
};

// One property of the catalogue as the perception sees it.
struct PropertyDesc {
  std::uint16_t word = 0;        // id in kWords (the word the NPC would use)
  gen::PropCat cat = gen::PropCat::Intrinsic;
  bool perceptible = false;      // seen or felt on the thing (derived ones: all their sources perceptible)
  bool in_vector = false;        // intrinsic magnitude kept in the object vector (mass, reach...)
};

// What the world knows of a sort of thing. Everything here is TRUE data; the perception filters it.
struct ThingProfile {
  bool known = false;
  std::uint16_t kind_word = 0;        // SYMBOL of the true sort (kind_symbol: kWords.size() + index in kKinds)
  std::uint16_t lookalike_word = 0;   // SYMBOL of its look-alike class (a word of kWords: they are not in kKinds; 0 = none)
  std::uint16_t color_word = 0;       // id in kKinds of its apparent colour (0 = none)
  std::uint32_t mass_g = 0;
  std::array<std::uint64_t, 2> props{};   // bit i = property i of properties()
};

class ThingCatalog {
 public:
  virtual ~ThingCatalog() = default;
  virtual ThingProfile profile(gen::EntityKind kind, std::uint16_t sort) const = 0;
  virtual std::span<const PropertyDesc> properties() const = 0;
};

// The implementation backed by the generated tables (sort = index in kKinds, as written by Spawn).
class CatalogueThings final : public ThingCatalog {
 public:
  CatalogueThings();
  ThingProfile profile(gen::EntityKind kind, std::uint16_t sort) const override;
  std::span<const PropertyDesc> properties() const override { return props_; }

 private:
  std::vector<PropertyDesc> props_;
  std::vector<ThingProfile> by_sort_;   // indexed by sort
};

// Looks a word up in the two symbol tables of the inner language (0 = absent). Built once.
class Vocabulary {
 public:
  Vocabulary();
  std::uint16_t word(std::string_view s) const;   // index in kWords
  std::uint16_t kind(std::string_view s) const;   // index in kKinds
  // pc_kind_seen holds a SYMBOL of the inner language: a word is its index in kWords, a kind is kWords.size() + its index
  // in kKinds (the order of the symbol registry). One number, one meaning, whichever table the name lives in.
  std::uint16_t symbol(std::string_view name) const;   // 0 when unknown
  static std::string_view symbol_name(std::uint16_t symbol);   // "" when out of range
  static std::uint16_t kind_symbol(std::uint16_t kinds_index);
 private:
  std::unordered_map<std::string_view, std::uint16_t> words_, kinds_;
};

class PerceptRules {
 public:
  PerceptRules();
  // Minimum clarity (per-mille) from which the field is written; 1001 if the field has no rule (never written).
  std::uint16_t min_clarity(Field f) const { return min_clarity_[std::size_t(f)]; }
  const gen::PerceptRule& rule(Field f) const { return *rules_[std::size_t(f)]; }
  bool complete() const { return complete_; }   // every Field has a rule in the generated table
  static std::string_view name(Field f);

 private:
  std::array<std::uint16_t, std::size_t(Field::kCount)> min_clarity_{};
  std::array<const gen::PerceptRule*, std::size_t(Field::kCount)> rules_{};
  bool complete_ = true;
};

}  // namespace em::act::perception
