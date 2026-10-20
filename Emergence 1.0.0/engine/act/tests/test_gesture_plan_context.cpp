// T22 x T28b: the plan facts of the executor are written for a plan laid out the way the ContextBuilder reads it (i_step_targets
// with the bit-31 header of the whole plan in front). The ContextBuilder then shows the step the executor advanced to.
#include "context_compare.h"
#include "emergence/social/tokenizer/context_builder.h"
#include "emergence/testing/check.h"
#include "gesture_rig.h"

using namespace em::act;
using namespace em::act::grig;
using namespace em::social;
using namespace em::social::tok2;
using namespace em::social::tok2::testing;
namespace sgen = em::social::gen;

namespace {
std::uint32_t word_id(const char* w) {
  for (std::size_t i = 0; i < sgen::kWords.size(); ++i) if (sgen::kWords[i] == w) return std::uint32_t(i);
  return 0;
}
}  // namespace

TEST(plan_facts_are_written_and_the_context_builder_sees_the_next_step) {
  Tokenizer tk;
  ContextBuilder builder(tk);
  Rig r;
  const EntityId a = r.person({0, 0, 0});
  NpcBundle& mind = *r.minds.mind(a);
  const std::uint32_t steps[] = {word_id("go"), word_id("look"), word_id("wait")};
  const std::uint32_t targets[] = {kPlanTargetHeader | 9u, 7u, 8u, 0u};   // header, then the targets of steps 0, 1, 2
  sgen::Intention in;
  in.i_steps = mind.side.put(steps);
  in.i_step_targets = mind.side.put(targets);
  in.i_status = 0;
  const MRef plan = mind.state.intention_records.add(in, [](const sgen::Intention&) { return 0; });
  Dec d(a, Gesture::go);
  d.with("pace", "walk").destination({15000, 0, 0}).given("target").plan(plan, 7);   // step 0 aims at the pointer 7
  CHECK(r.start(d).status == BeginStatus::Started);
  const sgen::Intention* rec = mind.state.intention_records.find(plan);
  CHECK(rec->i_status == 0 && rec->i_step_started == r.now);   // tracked: the header did not shift the targets
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done);
  CHECK(rec->i_step_index == 1000 && rec->i_step_progress == 1000);
  // The ContextBuilder reads the same record: the step is now `look`, the next `wait`, the target of the whole plan the header.
  ContextBuilder::Workspace ws;
  DecisionContext ctx;
  MindSource src{&mind, r.now, WakeInput{}, std::span<const FileLink>{}};
  builder.build(src, ws, ctx);
  const Record* pr = find_record(ctx, "p:" + std::to_string(plan.serial));
  CHECK(pr != nullptr);
  if (pr) {
    CHECK(field_of(tk, *pr, "step")->as_string() == "look");
    CHECK(field_of(tk, *pr, "next")->as_string() == "wait");
  }
  // And a gesture that is NOT PLAN.next (look is now next but with the wrong pointer) does not touch the plan.
  Dec other(a, Gesture::look);
  other.stop(Condition::c_done).plan(plan, 99);
  r.start(other);
  CHECK(rec->i_status == 1);   // suspended: the model chose something else
}

EMERGENCE_TEST_MAIN()
