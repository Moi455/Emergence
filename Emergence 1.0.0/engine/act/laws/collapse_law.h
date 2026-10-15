// The time laws of matter 1 (T18): collapse. Clock "real" (matter.toml): evaluated at every step, not at a game duration.
//   - the margin of every structure is computed from what it carries; its load_margin is brought up to date by
//     EntityDelta; at <= 0 it collapses (Destroy, rubble Spawns);
//   - whatever rests on nothing falls to the highest surface under it (Move); the energy of the fall breaks a thing
//     whose break energy it exceeds (debris), or damages a structure.
// Effects are Operations only. Bodily harm of what is under a fall is the job of the body laws (T21), not done here.
#pragma once
#include "law_kit.h"

namespace em::act {

struct TickReport {
  std::uint32_t bodies = 0, margins_written = 0, collapsed = 0, fell = 0, shattered = 0;
};

class CollapseLaw {
 public:
  TickReport run(const LawContext& ctx, Emitter& out) const;
};

}  // namespace em::act
