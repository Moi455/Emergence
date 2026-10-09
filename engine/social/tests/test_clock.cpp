// D30 calendar and the separate life clock.
#include "emergence/social/clock.h"
#include "emergence/testing/check.h"

using namespace em::social;

TEST(calendar) {
  WorldClock c;
  c.advance_real(5'400);                 // 1 h 30 real
  CHECK_EQ(c.day(), 1);
  CHECK(!c.night());
  c.advance_real(3'600 + 60);            // 1 h 01 into the day: night (last 30 min)
  CHECK(c.night());
  WorldClock y;
  y.advance_real(7 * 3'600);
  CHECK_EQ(y.year(), 1);
  CHECK_EQ(y.season(), 0);
  y.advance_real(105 * 60);              // + 1 h 45
  CHECK_EQ(y.season(), 1);
}

TEST(life_clock_matches_charter) {
  CHECK_EQ(LifeClock::lifespan_real_seconds(), 150LL * 3'600);           // charter § 25: ~150 h
  CHECK_EQ(LifeClock::age_tenths(15 * 3'600), 140);                     // childhood ends at 14
  CHECK_EQ(LifeClock::age_tenths(21 * 3'600), 180);                     // adult at 18
  // charter § 3: a child of 7 met again 5 calendar years later (35 h) is a young adult (~26)
  const std::int64_t seven = 15 * 3'600 / 2;                            // 7 years of age
  const std::int32_t later = LifeClock::age_tenths(seven + 35 * 3'600);
  CHECK(later >= 250 && later <= 275);
  CHECK(LifeClock::age_tenths(1'000 * 3'600) == 750);
}

EMERGENCE_TEST_MAIN()
