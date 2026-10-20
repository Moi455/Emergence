// Convention of i_step_targets (T28b), shared with the executor (T22): the list may START with one header item, bit 31 set,
// whose low 31 bits are the pointer (tagged MRef) to the TARGET OF THE WHOLE PLAN (PLAN.target of the dossier). It is not a
// step target: whoever walks the steps must skip it (skip_target_header). A list without header is a plain list of step
// targets. Provisional: the catalogue variable i_target (T28c) will replace it; then the header disappears.
#pragma once
#include <cstdint>
#include <span>

namespace em::social {

inline constexpr std::uint32_t kPlanTargetHeader = 0x80000000u;

constexpr bool is_target_header(std::uint32_t item) { return (item & kPlanTargetHeader) != 0; }
constexpr std::uint32_t strip_target_header(std::uint32_t item) { return item & ~kPlanTargetHeader; }
constexpr std::uint32_t make_target_header(std::uint32_t ref) { return ref | kPlanTargetHeader; }
// The step targets of a list read from the side table (the header, if any, removed).
inline std::span<const std::uint32_t> skip_target_header(std::span<const std::uint32_t> items) {
  return (!items.empty() && is_target_header(items[0])) ? items.subspan(1) : items;
}

}  // namespace em::social
