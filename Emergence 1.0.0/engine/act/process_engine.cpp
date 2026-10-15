#include "process_engine.h"

#include <algorithm>
#include <numeric>
#include <tuple>

namespace em::act {

ProcessEngine::ProcessEngine(const MatterCatalog& catalog, const EntityStore& store, const GroundModel& ground)
    : catalog_(catalog), store_(store), resolver_(catalog, store, ground), laws_(make_contact_laws()) {}

LawReport ProcessEngine::on_contact(const Contact& c, std::uint64_t tick, TouchedSet& touched, std::vector<Emission>& out) const {
  LawReport rep;
  if ((c.target != kNoEntity && touched.contains(c.target)) || (c.other != kNoEntity && touched.contains(c.other)) ||
      (c.tool != kNoEntity && touched.contains(c.tool))) {
    rep.outcome = Outcome::Conflict;
    return rep;
  }
  Resolved r = resolver_.resolve(c);
  LawContext ctx = context(tick);
  for (const auto& law : laws_) {
    Emitter em(out, touched, tick, c.author, c.decision_seq, static_cast<std::uint32_t>(out.size()));   // k = global rank in this batch
    LawReport lr;
    std::size_t mark = out.size();
    if (law->contact(ctx, c, r, em, lr)) return lr;
    out.resize(mark);   // a law that declines leaves nothing behind
  }
  return rep;
}

std::vector<LawReport> ProcessEngine::on_contacts(std::span<const Contact> contacts, std::uint64_t tick,
                                                  std::vector<Emission>& out) const {
  // Fair order: by a hash of (tick, author, decision_seq), not by author id (a low id would always win a conflict).
  // Ties (same author and decision_seq) are broken by the content of the contact, never by input position.
  auto h = [&](const Contact& c) {
    std::uint64_t x = tick * 0x9E3779B97F4A7C15ull ^ (std::uint64_t{c.author} << 32 | c.decision_seq);
    x ^= x >> 30; x *= 0xBF58476D1CE4E5B9ull; x ^= x >> 27; x *= 0x94D049BB133111EBull; x ^= x >> 31;
    return x;
  };
  auto key = [&](const Contact& c) {
    return std::make_tuple(h(c), c.author, c.decision_seq, c.tool, c.target, c.other, static_cast<int>(c.manner), c.speed_mm_s, c.at_joint);
  };
  std::vector<std::uint32_t> order(contacts.size());
  std::iota(order.begin(), order.end(), 0u);
  std::stable_sort(order.begin(), order.end(), [&](std::uint32_t a, std::uint32_t b) { return key(contacts[a]) < key(contacts[b]); });
  std::vector<LawReport> reports(contacts.size());
  TouchedSet touched;
  for (std::uint32_t i : order) reports[i] = on_contact(contacts[i], tick, touched, out);
  return reports;
}

TickReport ProcessEngine::tick_time(std::uint64_t tick, std::vector<Emission>& out) const {
  TouchedSet touched;
  Emitter em(out, touched, tick, ops::kWorldLaw, 0);
  return collapse_.run(context(tick), em);
}

std::size_t ProcessEngine::submit_all(ops::OperationBus& bus, std::span<const Emission> emissions) {
  std::size_t ok = 0;
  for (const Emission& e : emissions)
    if (bus.submit(e.op, e.decision_seq, e.k) == ops::SubmitResult::Accepted) ++ok;
  return ok;
}

std::vector<ProcessId> ProcessEngine::contact_processes() const {
  std::vector<ProcessId> v;
  for (const auto& l : laws_) v.push_back(l->process());
  return v;
}

std::uint64_t fingerprint(std::span<const Emission> emissions) {
  std::uint64_t h = 0xcbf29ce484222325ull;
  auto mix = [&](std::uint8_t b) { h ^= b; h *= 0x100000001b3ull; };
  for (const Emission& e : emissions) {
    std::vector<std::uint8_t> bytes = ops::encode(e.op);
    for (std::uint8_t b : bytes) mix(b);
    for (int s = 0; s < 32; s += 8) { mix(std::uint8_t(e.decision_seq >> s)); mix(std::uint8_t(e.k >> s)); }
  }
  return h;
}

}  // namespace em::act
