// SpeechRouter (T24, docs/14 sections 6.1 and 7, docs/11): a speech said in the inner language is FROZEN for each
// hearer by the I/YOU swap of ELIZA (`me` becomes the speaker's dossier in the hearer's mind, `you` his own `me`, `us`
// is frozen into a group referent), heard according to the distance, the noise and the attention (the CLARITY that the
// perception computes), judged ONCE by the governor (check_utterance, said = true, every hearer counts for D10), and
// then written as dossiers in the mind of every hearer: a HEARD belief ("he said that ..."), a request, referents.
//
// RULES. The router never judges the meaning (no "promise kept", no "threat": the speech shapes of shapes.py are
// passive and live elsewhere). Each hearer gets HIS version: a word may be missed (an identity becomes `someone`),
// the certainty follows the clarity, a speech not understood is BELIEF.unintelligible. Nothing true passes: a person is
// translated through what the SPEAKER believes (his name for the file), never through r_true_entity; a mistaken
// speaker is transmitted as "the one he calls Aldric". Real ages are used by the governor only, to refuse.
//
// TRANSLATION OF A PERSON (intended behaviour, docs/14 section 6.3). A pointer of the speaker is translated through the
// NAME the speaker gives to his file, never through r_true_entity: the hearer's own file of the same name if he has one
// (lowest serial), else a new referent "the one he calls <name>" (r_known_by = name_only, r_true_entity = 0). So a
// mistaken speaker transmits his belief, not the person; the hearer's file is chosen by the hearer's own knowledge of
// the name, which is what a person hearing "Aldric did it" does. docs/15 T24 says "celui qu'il appelle Aldric": same thing.
//
// REFUSALS ARE ENGINE-ONLY. A SpeechRefusal (d10_hearer, d10_intimate...) betrays that a hearer may be a minor: it must
// NEVER be returned to the model nor written in any dossier (the router writes nothing for a refused speech; tests check
// that no mind changes). Log it in the engine journal only.
//
// Pure part (parity with the Python oracle, tests/speech_vectors.inc): Perspective, unfold_speech, freeze_speech.
// Stateful part: SpeechRouter::route (deterministic: speeches in the order (when, speaker, content), hearers by
// EntityId, 1 or n threads give the same bytes).
#pragma once
#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "emergence/social/mind_writer.h"

namespace em::social {

// ---- pure part -------------------------------------------------------------------------------------------------

// shapes.py Perspective: swap `me` -> speaker_key and `you` -> hearer_self on the leaves of a text (heads untouched).
class Perspective {
 public:
  explicit Perspective(std::string speaker_key, std::string hearer_self = "me");
  bool valid() const { return valid_; }   // the speaker must be a pointer of the hearer's mind
  std::string text(std::string_view utterance) const;   // canonical text of the swapped tree; empty when malformed

 private:
  std::string key_, self_;
  bool valid_ = false;
};

// The speech with every cited record (b: m: g: h: q: c: @V) replaced by its frozen copy, as governor.py unfolds it
// (`(that X)` becomes the content of X; depth at most 2). `on_cite` sees each cited reference. nullopt = a citation
// without copy, too deep, or an ill-formed text.
std::optional<std::string> unfold_speech(const TypedExpression& utterance, const RecordLookup& expand,
                                         const std::function<void(std::string_view)>& on_cite = {});

enum class FreezeStatus : std::uint8_t { ok, unexpanded, untranslated, invalid_for_hearer };

struct FreezeOptions {
  std::string speaker_key;                                     // pointer of the hearer's mind for the speaker, "@E7"
  RecordLookup expand;                                         // the speaker's cited records
  bool already_unfolded = false;                               // the text is the result of unfold_speech
  // speaker pointer (@E @G @T @L @V) -> hearer text; nullopt = cannot be translated. @PLACE and n: pass unchanged.
  std::function<std::optional<std::string>(std::string_view)> translate;
  std::function<std::optional<std::string>()> freeze_us;      // the group pointer that replaces `us`; empty = `us` stays
  int miss_index = -1;                                         // index in misheard_candidates() of the identity missed
};

struct FreezeResult {
  FreezeStatus status = FreezeStatus::invalid_for_hearer;
  std::string text;   // the hearer's version, canonical, a VALID utterance when status == ok
};

// The identities (@E @G n:) of an unfolded text in depth-first order: what a hearer may fail to catch.
std::vector<std::string> misheard_candidates(std::string_view unfolded_text);

// The same from an already unfolded text (what the router keeps between its two phases).
FreezeResult freeze_unfolded(std::string_view unfolded_text, const FreezeOptions& opt);

// unfold -> miss one identity (`someone`) -> swap me/you -> freeze us -> translate pointers -> validate for the hearer.
FreezeResult freeze_speech(const TypedExpression& utterance, const FreezeOptions& opt);

// ---- stateful part ---------------------------------------------------------------------------------------------

// What the router needs from the world. Reads must be safe from several threads at once.
class SpeechWorld : public PartySource {
 public:
  virtual NpcBundle* mind(EntityId who) const = 0;   // null = not simulated (an unknown hearer: a possible minor)
  // The hearer's own file for the speaker when he recognises him (the perception's FileDirectory), 0 = none.
  virtual MRef file_of(EntityId hearer, EntityId speaker) const = 0;
};

// What the perception reports of a speech heard (the same fields as act::perception::HeardSpeech).
struct HeardUtterance {
  EntityId listener = 0, speaker = 0;
  std::uint32_t content = 0;   // PropRef in the SPEAKER's arena
  std::uint16_t clarity = 0;   // 0..1000
  bool addressed = false, intelligible = false;
  GameTime when = 0;
};

struct SpeechConfig {
  unsigned threads = 1;
  std::uint16_t clear_clarity = 600;   // below it a word may be missed
  std::uint16_t min_clarity = 300;     // below it nothing is understood
  std::size_t heard_cap = 8;           // heard_unprocessed keeps this many belief serials
};

enum class HearKind : std::uint8_t { belief, unintelligible, request, referent, group };

// One typed write in a hearer's mind (the audit log; the dossiers themselves are already written).
struct HearCall {
  EntityId hearer = 0, speaker = 0;
  HearKind kind = HearKind::belief;
  std::uint32_t serial = 0;       // serial of the record written
  std::uint16_t hops = 0;
  std::int16_t certainty = 0;     // tenths
  GameTime when = 0;
  bool operator==(const HearCall&) const = default;
};

struct SpeechRefusal {
  EntityId speaker = 0;
  std::uint32_t content = 0;
  Reason reason = Reason::ok;
  GameTime when = 0;
  std::size_t hearers = 0;
  bool operator==(const SpeechRefusal&) const = default;
};

// A file created for a speaker the hearer did not know: the world should remember it (FileDirectory::set).
struct NewFile {
  EntityId hearer = 0, speaker = 0;
  MRef file;
  bool operator==(const NewFile&) const = default;
};

struct SpeechStats {
  std::uint64_t speeches = 0, refused = 0, invalid = 0, deliveries = 0, unintelligible = 0, requests = 0;
  std::uint64_t referents = 0, groups = 0, missed_words = 0, untranslated = 0;
  std::uint64_t refused_by_reason[static_cast<std::size_t>(Reason::kCount)] = {};
};

struct SpeechReport {
  std::vector<HearCall> calls;
  std::vector<SpeechRefusal> refusals;
  std::vector<NewFile> new_files;
  SpeechStats stats;
  std::uint64_t digest() const;   // FNV-1a of calls, refusals and new files: equal for any number of threads
};

class SpeechRouter {
 public:
  explicit SpeechRouter(const SpeechWorld& world, SpeechConfig cfg = {}) : world_(world), cfg_(cfg) {}
  // Routes the speeches heard this tick. The report stays valid until the next call.
  const SpeechReport& route(std::span<const HeardUtterance> heard);
  const SpeechConfig& config() const { return cfg_; }

 private:
  const SpeechWorld& world_;
  SpeechConfig cfg_;
  SpeechReport report_;
  // Per hearer: the last referent created for each unnamed speaker or unnamed person ((speaker, symbol) -> serial),
  // reused while the record lives, so that a stranger who speaks at every tick does not push real files out of the
  // 96 relations. A cache of the router (not saved); at most 32 entries per hearer.
  std::map<EntityId, std::vector<std::pair<std::string, std::uint32_t>>> memory_;
};

}  // namespace em::social
