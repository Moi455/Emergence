#include "emergence/act/perception/percept_rules.h"

#include <algorithm>

#include "emergence/social/vocab_gen.h"

namespace em::act::perception {

Vocabulary::Vocabulary() {
  namespace sg = em::social::gen;
  for (std::size_t i = 0; i < sg::kWords.size(); ++i) words_.emplace(sg::kWords[i], std::uint16_t(i));
  for (std::size_t i = 0; i < sg::kKinds.size(); ++i) kinds_.emplace(sg::kKinds[i], std::uint16_t(i));
}
std::uint16_t Vocabulary::word(std::string_view s) const {
  auto it = words_.find(s);
  return it == words_.end() ? std::uint16_t(0) : it->second;
}
std::uint16_t Vocabulary::kind(std::string_view s) const {
  auto it = kinds_.find(s);
  return it == kinds_.end() ? std::uint16_t(0) : it->second;
}

std::uint16_t Vocabulary::kind_symbol(std::uint16_t i) { return std::uint16_t(em::social::gen::kWords.size() + i); }
std::uint16_t Vocabulary::symbol(std::string_view name) const {
  if (std::uint16_t k = kind(name)) return kind_symbol(k);
  return word(name);
}
std::string_view Vocabulary::symbol_name(std::uint16_t sym) {
  namespace sg = em::social::gen;
  if (sym < sg::kWords.size()) return sg::kWords[sym];
  const std::size_t k = sym - sg::kWords.size();
  return k < sg::kKinds.size() ? sg::kKinds[k] : std::string_view{};
}

CatalogueThings::CatalogueThings() {
  Vocabulary v;
  props_.reserve(gen::kProperties.size());
  for (const gen::PropertyInfo& p : gen::kProperties) props_.push_back({v.word(p.id), p.cat, p.perceptible, p.in_vector});
  namespace sg = em::social::gen;
  by_sort_.assign(sg::kKinds.size(), ThingProfile{});
  for (const gen::ThingInfo& t : gen::kItemTypes) {
    const std::uint16_t k = v.kind(t.id);
    if (k == 0) continue;
    ThingProfile& p = by_sort_[k];
    p.known = true;
    p.kind_word = Vocabulary::kind_symbol(k);
    p.lookalike_word = t.lookalike.empty() ? std::uint16_t(0) : v.word(t.lookalike);
    p.color_word = t.color.empty() ? std::uint16_t(0) : v.kind(t.color);
    p.mass_g = t.mass_g;
    p.props = t.props;
  }
  for (const gen::SpeciesInfo& s : gen::kSpecies) {
    const std::uint16_t k = v.kind(s.id);
    if (k == 0) continue;
    ThingProfile& p = by_sort_[k];
    p.known = true;
    p.kind_word = Vocabulary::kind_symbol(k);
    p.lookalike_word = s.lookalike.empty() ? std::uint16_t(0) : v.word(s.lookalike);
    (void)s.animal;
  }
}

ThingProfile CatalogueThings::profile(gen::EntityKind, std::uint16_t sort) const {
  return sort < by_sort_.size() ? by_sort_[sort] : ThingProfile{};
}

std::string_view PerceptRules::name(Field f) {
  static constexpr std::array<std::string_view, std::size_t(Field::kCount)> kNames = {
#define EM_X(n) #n,
      EM_PERCEPT_FIELDS(EM_X)
#undef EM_X
  };
  return kNames[std::size_t(f)];
}

PerceptRules::PerceptRules() {
  for (std::size_t i = 0; i < std::size_t(Field::kCount); ++i) {
    min_clarity_[i] = 1001;
    rules_[i] = nullptr;
    const std::string_view n = name(Field(i));
    for (const gen::PerceptRule& r : gen::kRules)
      if (r.target == n) { rules_[i] = &r; min_clarity_[i] = r.min_clarity; break; }
    if (!rules_[i]) complete_ = false;
  }
}

}  // namespace em::act::perception
