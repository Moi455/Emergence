// The C++ governor must agree with its Python oracle (catalogue/tools/governor.py) on every shared vector,
// and must hold the hard rule D10 on its own.
#include "emergence/social/governor.h"
#include "emergence/testing/check.h"

using namespace em::social;

#include "governor_vectors.inc"

namespace {
const Party* pal(int i) { return i < 0 ? nullptr : &kPalette[i]; }
}

TEST(write_vectors_match_oracle) {
  Governor g;
  WriteLedger led;
  int seq = -1, mismatches = 0;
  for (const WriteCase& c : kWrites) {
    if (c.seq != seq) { led = WriteLedger(); seq = c.seq; }
    Verdict v = g.check_write(c.var, c.old_v, c.proposed, led, static_cast<std::uint32_t>(c.target),
                              pal(c.intimate_target), pal(c.actor), c.creating);
    if (v.allowed != c.allowed || (v.allowed && v.value != c.value)) ++mismatches;
  }
  CHECK_EQ(mismatches, 0);
}

TEST(gesture_vectors_match_oracle) {
  Governor g;
  int mismatches = 0;
  for (const GestureCase& c : kGestureCases) {
    GestureCall call;
    call.gesture = c.gesture;
    for (int i = 0; i < gen::kMaxParams; ++i) {
      call.value[i] = c.value[i];
      call.party[i] = pal(c.party[i]);
    }
    if (g.check_gesture(call, pal(c.actor)).allowed != c.allowed) ++mismatches;
  }
  CHECK_EQ(mismatches, 0);
}

TEST(d10_romantic_touch_refused_with_a_child) {
  Governor g;
  const Party adult{300, 300, 310, true}, child{90, 90, 90, true};
  GestureCall call;
  call.gesture = gen::Gesture::touch;
  const gen::GestureSpec& t = gen::kGestures[static_cast<int>(gen::Gesture::touch)];
  for (int i = 0; i < t.n_params; ++i) {
    const auto& p = t.params[i];
    if (p.name == "target") { call.value[i] = 0; call.party[i] = &child; }
    if (p.name == "manner") call.value[i] = 3;       // romantic
    if (p.name == "with") call.value[i] = 0;         // hand
    if (p.name == "contact_zone") call.value[i] = 4; // hands
  }
  CHECK(!g.check_gesture(call, &adult).allowed);
}

TEST(engine_owns_the_body) {
  Governor g;
  WriteLedger led;
  CHECK(!g.check_write(gen::Var::pain, 20, 0, led, 1, nullptr, nullptr, false).allowed);
}

EMERGENCE_TEST_MAIN()
