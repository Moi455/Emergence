// FeasibilityMask: it follows the NPC's belief, not the truth (the mask reads only the arrays of the tokenizer).
#include <cstdio>
#include <string>

#include "emergence/social/tokenizer/mask.h"
#include "emergence/testing/check.h"

using namespace em::social::tok2;

namespace {

Tokenizer& tk() { static Tokenizer t; return t; }

std::string context(const std::string& records) {
  return "{\"header\":" + tk().header_json() + ",\"known_keys\":null,\"records\":[" + records + "]}";
}
const char* kBase = "{\"type\":\"SELF\",\"key\":\"me\",\"fields\":{}},{\"type\":\"PLACE\",\"key\":\"@PLACE\",\"fields\":{}}";

Encoded encode(const std::string& extra) {
  Encoded e;
  tk().encode(tk().load_context(context(std::string(kBase) + (extra.empty() ? "" : "," + extra))), e);
  return e;
}
std::string thing(int n, const std::string& props) {
  return "{\"type\":\"THING\",\"key\":\"@T" + std::to_string(n) + "\",\"fields\":{\"kind\":\"mortar_tub\",\"props\":" + props + "}}";
}
bool allowed(const MaskResult& m, const FeasibilityMask& fm, const char* gesture, int k, int slot) {
  return m.gestures[std::size_t(fm.gesture_index(gesture))].refs[std::size_t(k)].allowed[std::size_t(slot)];
}

}  // namespace

TEST(mask_follows_the_belief_not_the_truth) {
  FeasibilityMask fm(tk());
  MaskResult m;
  // The NPC believes the tub is NOT graspable (it may well be: the mask never sees the world).
  fm.compute(encode(thing(1, "{\"graspable\":false,\"climbable\":true}")), m);
  CHECK(!allowed(m, fm, "take", 0, 3));            // slot 3 = the third record (PLACE, SELF, THING by registry order)
  CHECK(allowed(m, fm, "climb", 0, 3));
  CHECK(!m.gestures[std::size_t(fm.gesture_index("take"))].feasible);   // nothing else to take
  // Same thing, believed graspable.
  fm.compute(encode(thing(1, "{\"graspable\":true}")), m);
  CHECK(allowed(m, fm, "take", 0, 3));
  CHECK(m.gestures[std::size_t(fm.gesture_index("take"))].feasible);
  // Nothing known about its properties: not masked (the NPC may try; failing is physical and perceived).
  fm.compute(encode(thing(1, "{\"mass\":2.0}")), m);
  CHECK(allowed(m, fm, "take", 0, 3));
}

TEST(mask_gesture_needs_a_candidate) {
  FeasibilityMask fm(tk());
  MaskResult m;
  fm.compute(encode(""), m);                                   // no thing, no person
  CHECK(!m.gestures[std::size_t(fm.gesture_index("take"))].feasible);
  CHECK(!m.gestures[std::size_t(fm.gesture_index("eat"))].feasible);
  CHECK(m.gestures[std::size_t(fm.gesture_index("rest"))].feasible);
  CHECK(m.gestures[std::size_t(fm.gesture_index("go"))].feasible);     // a direction is a target
  CHECK(m.gestures[std::size_t(fm.gesture_index("speak"))].feasible);  // the listener is optional
  CHECK(m.gestures[std::size_t(fm.gesture_index("speak"))].refs[0].allowed[0]);   // "nobody" for an optional pointer
  CHECK(m.feasible_count() > 0 && m.feasible_count() < kMaskGestures);
}

TEST(mask_absent_person_cannot_be_touched) {
  FeasibilityMask fm(tk());
  MaskResult m;
  const std::string here = "{\"type\":\"ENTITY\",\"key\":\"@E1\",\"fields\":{\"present\":true,\"dist\":2.0}}";
  const std::string gone = "{\"type\":\"ENTITY\",\"key\":\"@E2\",\"fields\":{\"present\":false}}";
  fm.compute(encode(here + "," + gone), m);
  CHECK(allowed(m, fm, "strike", 0, 1));        // @E1 (ENTITY rows come first: registry order)
  CHECK(!allowed(m, fm, "strike", 0, 2));       // @E2 is known absent: not a target of a contact gesture
  CHECK(allowed(m, fm, "go", 0, 2));            // but one can go where one believes him to be
}

TEST(mask_is_deterministic_and_reads_only_arrays) {
  FeasibilityMask fm(tk());
  MaskResult a, b;
  const Encoded e = encode(thing(1, "{\"graspable\":true}") + "," + thing(2, "{\"graspable\":false}"));
  fm.compute(e, a);
  fm.compute(e, b);
  bool same = true;
  for (int g = 0; g < kMaskGestures; ++g)
    for (int k = 0; k < kMaskRefs; ++k) same = same && a.gestures[std::size_t(g)].refs[std::size_t(k)].allowed == b.gestures[std::size_t(g)].refs[std::size_t(k)].allowed;
  CHECK(same);
}

TEST(mask_self_rules) {
  FeasibilityMask fm(tk());
  MaskResult m;
  // ENTITY rows come first, then PLACE, SELF, THING: with one thing, SELF is slot 2, the thing slot 3
  fm.compute(encode(thing(1, "{\"binds\":true,\"graspable\":true}")), m);
  CHECK(!allowed(m, fm, "grab", 0, 2));       // one does not grab oneself
  CHECK(!allowed(m, fm, "take", 0, 2));
  CHECK(!allowed(m, fm, "strike", 0, 2));
  CHECK(!allowed(m, fm, "push", 0, 2));
  CHECK(!allowed(m, fm, "pull", 0, 2));
  CHECK(allowed(m, fm, "touch", 0, 2));       // touching one's own wound
  CHECK(allowed(m, fm, "examine", 0, 2));
  CHECK(allowed(m, fm, "search", 0, 2));
  CHECK(allowed(m, fm, "tie", 0, 2));         // bandaging oneself: tie (self) with a cloth
  CHECK(allowed(m, fm, "tie", 2, 3));         // ... with the cloth (the item that binds)
  CHECK(m.gestures[std::size_t(fm.gesture_index("tie"))].feasible);
}

TEST(mask_treating_a_wounded_person_or_a_child_is_not_masked) {
  FeasibilityMask fm(tk());
  MaskResult m;
  const std::string hurt = "{\"type\":\"ENTITY\",\"key\":\"@E1\",\"fields\":{\"present\":true,\"look.age\":6.0,\"look.wounds\":7.0}}";
  fm.compute(encode(hurt), m);
  CHECK(allowed(m, fm, "touch", 0, 1));
  CHECK(allowed(m, fm, "work", 0, 1));        // pressing a bandage
  CHECK(allowed(m, fm, "examine", 0, 1));
  CHECK(allowed(m, fm, "take", 0, 1));        // carrying a wounded child
  CHECK(allowed(m, fm, "tie", 0, 1));
}

EMERGENCE_TEST_MAIN()
