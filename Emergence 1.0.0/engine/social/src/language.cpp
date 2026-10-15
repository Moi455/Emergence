// Port of catalogue/tools/language.py (T13). Every method below mirrors the Python method of the same name, in the
// same order, so that the problems come out identical (see tests/test_language.cpp and language_vectors.inc).
#include "emergence/social/language.h"

#include <algorithm>
#include <cstdint>
#include <string_view>
#include <unordered_map>

#include "emergence/social/vocab_gen.h"

namespace em::social {

#include "language_tables.inc"

using SV = std::string_view;
namespace {
using namespace lang_tables;
using sv = std::string_view;
}  // namespace

std::string_view to_string(LangProblem p) {
  static constexpr sv names[] = {
      "parse_trailing", "parse_not_list", "parse_end", "parse_close", "parse_head", "parse_missing_close",
      "too_many_symbols", "hole_misplaced", "too_deep",
      "utt_not_list", "mood_arity", "formula_pointer", "formula_extra", "utt_head",
      "not_proposition", "second_mood", "described_as_prop", "logic_arity", "that_target", "wrap_arity", "timeop_arity",
      "not_predicate", "pred_arity", "arg_class",
      "time_mark_node", "span_shape", "span_count", "span_unit", "for_duration", "unknown_symbol", "bad_quantity",
      "not_time_mark",
      "did_shape", "not_gesture", "gesture_target", "too_many_roles", "role_bad", "role_twice", "says_frame", "says_shape",
      "how_bad", "role_shape", "role_manner", "role_none", "role_accept", "role_held",
      "wh_outside", "arg_cannot", "arg_node",
      "described_empty", "described_order", "described_words", "described_expected", "clause_head", "clause_holes",
      "of_expected", "of_arity", "of_quantity", "of_group_head", "of_not_group", "of_bad",
      "pointers_max", "too_long", "charset"};
  static_assert(sizeof(names) / sizeof(names[0]) == static_cast<std::size_t>(LangProblem::kCount));
  const auto i = static_cast<std::size_t>(p);
  return i < static_cast<std::size_t>(LangProblem::kCount) ? names[i] : sv("?");
}

// ------------------------------------------------------------------------------------------- vocabulary
class LanguageVocabulary {
 public:
  LanguageVocabulary() {
    words_.reserve(std::size(kWords) * 2);
    for (const auto& w : kWords) words_.emplace(sv(w.word), &w);
    kinds_.reserve(std::size(kKinds) * 2);
    for (const auto& k : kKinds) kinds_.emplace(sv(k.name), k.flags);
    for (const auto& c : kConcepts) concepts_.emplace(sv(c.id), &c);
    for (const auto& a : kActions) actions_.emplace(sv(a.id), &a);
    for (const auto& r : kRefWords) ref_words_.emplace(sv(r.word), r.types);
  }
  std::uint64_t cats(sv w) const {
    const auto it = words_.find(w);
    return it == words_.end() ? 0 : it->second->cats;
  }
  bool has_word(sv w) const { return words_.count(w) != 0; }
  bool is(sv w, std::uint64_t cat) const { return (cats(w) & cat) != 0; }
  bool intimate_word(sv w) const {
    const auto it = words_.find(w);
    return it != words_.end() && it->second->intimate;
  }
  int kind_flags(sv base) const {   // -1: not a kind
    const auto it = kinds_.find(base);
    return it == kinds_.end() ? -1 : it->second;
  }
  bool is_kind(sv base) const { return kinds_.count(base) != 0; }
  bool has_flag(sv base, int f) const { const int k = kind_flags(base); return k >= 0 && (k & f) != 0; }
  const ConceptRow* concept_row(sv id) const {
    const auto it = concepts_.find(id);
    return it == concepts_.end() ? nullptr : it->second;
  }
  const ActionRow* action(sv id) const {
    const auto it = actions_.find(id);
    return it == actions_.end() ? nullptr : it->second;
  }
  const std::uint64_t* ref_word(sv w) const {
    const auto it = ref_words_.find(w);
    return it == ref_words_.end() ? nullptr : &it->second;
  }

 private:
  std::unordered_map<sv, const WordRow*> words_;
  std::unordered_map<sv, int> kinds_;
  std::unordered_map<sv, const ConceptRow*> concepts_;
  std::unordered_map<sv, const ActionRow*> actions_;
  std::unordered_map<sv, std::uint64_t> ref_words_;
};

Parser::Parser() : vocab_(std::make_unique<LanguageVocabulary>()) {}
Parser::~Parser() = default;
Parser::Parser(Parser&&) noexcept = default;
Parser& Parser::operator=(Parser&&) noexcept = default;

// ------------------------------------------------------------------------------------------- small helpers
namespace {

constexpr sv kHole = "the_one";
constexpr sv kCiting = "bmghqc";

bool ascii_digits(sv s) {   // s.isascii() and s.isdigit(): non-empty, ASCII digits only
  if (s.empty()) return false;
  for (const char c : s)
    if (c < '0' || c > '9') return false;
  return true;
}

// ^(@E\d+|@T\d+|@G\d+|@L\d+|@V\d+|@PLACE|[bmghqc]:\d+|n:\d+)\Z
bool is_pointer(sv s) {
  if (s == "@PLACE") return true;
  if (s.size() >= 3 && s[0] == '@' && (s[1] == 'E' || s[1] == 'T' || s[1] == 'G' || s[1] == 'L' || s[1] == 'V'))
    return ascii_digits(s.substr(2));
  if (s.size() >= 3 && s[1] == ':' && (kCiting.find(s[0]) != sv::npos || s[0] == 'n')) return ascii_digits(s.substr(2));
  return false;
}

bool starts(sv s, sv p) { return s.substr(0, p.size()) == p; }
sv base_of(sv s) { return s.substr(0, s.find(':')); }

std::uint64_t accepts_of(std::uint64_t expected, bool default_self) {
  for (const auto& r : kAccepts)
    if (r.expected == expected) return r.accepts;
  return default_self ? expected : 0;
}

bool is_nesting_head(sv h) {
  static constexpr sv heads[] = {"believes", "wants", "intends", "says", "may", "owes", "norm", "custom", "recipe", "that", "knows"};
  return std::find(std::begin(heads), std::end(heads), h) != std::end(heads);
}

}  // namespace

// ------------------------------------------------------------------------------------------- parser + validator
struct LangBuilder {
  using Expr = TypedExpression;
  using Item = TypedExpression::Item;
  using Node = TypedExpression::Node;
  struct TypesResult { std::uint64_t types = 0; LangProblem err = LangProblem::kCount; };   // kCount = no error

  Expr& e;
  const LanguageVocabulary& v;
  PointerKinds kinds;           // filtered pointer_kinds
  bool bare;
  int clause_holes = 0;

  LangBuilder(Expr& expr, const LanguageVocabulary& voc, bool b) : e(expr), v(voc), bare(b) {}

  // ---- tree access
  bool is_node(const Item& i) const { return i.node >= 0; }
  sv text(const Item& i) const { return e.sv(i); }
  const Node& node(const Item& i) const { return e.nodes_[static_cast<std::size_t>(i.node)]; }
  const Item* args(const Item& i) const { return e.args_.data() + node(i).first; }
  std::uint32_t nargs(const Item& i) const { return node(i).n; }
  sv head(const Item& i) const { return e.sv(node(i).head); }
  void problem(LangProblem p) { e.problems_.push_back(p); }
  bool cat(sv w, std::uint64_t c) const { return v.is(w, c); }

  // ---- parser (Parser._expr): tokens are (offset, length) in the text
  struct Tok { std::uint32_t off, len; };
  std::vector<Tok> toks;
  std::size_t pos = 0;
  std::vector<Item> scratch;

  void tokenize() {
    const sv t = e.text_;
    std::size_t i = 0;
    while (i < t.size()) {
      const char c = t[i];
      if (c == ' ' || (c >= '\t' && c <= '\r')) { ++i; continue; }
      if (c == '(' || c == ')') { toks.push_back({static_cast<std::uint32_t>(i), 1}); ++i; continue; }
      std::size_t j = i;
      while (j < t.size() && t[j] != '(' && t[j] != ')' && t[j] != ' ' && !(t[j] >= '\t' && t[j] <= '\r')) ++j;
      toks.push_back({static_cast<std::uint32_t>(i), static_cast<std::uint32_t>(j - i)});
      i = j;
    }
  }
  sv tok(std::size_t i) const { return e.sv(Item{toks[i].off, toks[i].len, -1}); }

  // Returns false (with the problem pushed) on a syntax error.
  bool parse_expr(Item& out) {
    if (pos >= toks.size()) { problem(LangProblem::parse_end); return false; }
    const Tok t = toks[pos];
    const sv ts = tok(pos);
    ++pos;
    if (ts == ")") { problem(LangProblem::parse_close); return false; }
    if (ts != "(") { out = Item{t.off, t.len, -1}; return true; }
    if (pos >= toks.size() || tok(pos) == "(" || tok(pos) == ")") { problem(LangProblem::parse_head); return false; }
    Item h{toks[pos].off, toks[pos].len, -1};
    ++pos;
    const std::size_t base = scratch.size();
    while (pos < toks.size() && tok(pos) != ")") {
      Item a;
      if (!parse_expr(a)) return false;
      scratch.push_back(a);
    }
    if (pos >= toks.size()) { problem(LangProblem::parse_missing_close); return false; }
    ++pos;
    Node n;
    n.head = h;
    n.first = static_cast<std::uint32_t>(e.args_.size());
    n.n = static_cast<std::uint32_t>(scratch.size() - base);
    e.args_.insert(e.args_.end(), scratch.begin() + static_cast<std::ptrdiff_t>(base), scratch.end());
    scratch.resize(base);
    e.nodes_.push_back(n);
    out = Item{h.off, h.len, static_cast<std::int32_t>(e.nodes_.size() - 1)};
    return true;
  }

  // ---- Vocabulary.types
  TypesResult types(sv sym) const {
    TypesResult r;
    if (is_pointer(sym)) {
      if (starts(sym, "@E")) r.types = kTy_agent | kTy_entity;
      else if (starts(sym, "@T")) r.types = kTy_item | kTy_entity;
      else if (starts(sym, "@G")) r.types = kTy_group | kTy_role | kTy_entity | kTy_agent;
      else if (starts(sym, "@L") || sym == "@PLACE") r.types = kTy_place;
      else if (starts(sym, "@V")) r.types = kTy_event;
      else if (sym[0] == 'b' || sym[0] == 'g' || sym[0] == 'c') r.types = kTy_proposition;
      else if (sym[0] == 'm' || sym[0] == 'h' || sym[0] == 'q') r.types = kTy_event | kTy_proposition;
      else r.types = kTy_agent | kTy_entity | kTy_place | kTy_group | kTy_name;
      return r;
    }
    if (const std::uint64_t* rw = v.ref_word(sym)) { r.types = *rw; return r; }
    const std::size_t colon = sym.find(':');
    const sv base = sym.substr(0, colon);
    const sv qty = colon == sv::npos ? sv() : sym.substr(colon + 1);
    std::uint64_t out = 0;
    if (v.is_kind(base) || v.is(base, kCat_lookalike)) {
      if (!qty.empty() && !ascii_digits(qty)) { r.err = LangProblem::bad_quantity; return r; }
      if (v.has_flag(base, kQuality)) out |= kTy_concept;
      else if (v.has_flag(base, kSite)) out |= qty.empty() ? (kTy_kind | kTy_concept | kTy_entity | kTy_place) : (kTy_kind | kTy_entity | kTy_place);
      else out |= qty.empty() ? kKindTypes : kKindQtyTypes;
    }
    if (ascii_digits(sym)) out |= kTy_quantity;
    const std::uint64_t cs = v.cats(sym);
    if (cs) for (const auto& row : kCategoryTypes) if (cs & row.cat) out |= row.types;
    if (!out && !v.has_word(sym)) { r.err = LangProblem::unknown_symbol; return r; }
    r.types = out;
    return r;
  }

  // ---- ref_targets (str form) and (Item form)
  std::uint64_t ref_targets_sym(sv sym) const {
    if (sym == "somewhere" || sym == "nowhere") return kTag_place | kTag_terrain | kTag_direction;
    if (sym == "something" || sym == "nothing") return kTag_animal | kTag_item | kTag_structure | kTag_terrain | kTag_plant;
    if (sym == kHole) return kTag_agent | kTag_animal | kTag_item | kTag_place | kTag_structure | kTag_group;
    if (starts(sym, "@E") || sym == "me" || sym == "you" || sym == "someone" || sym == "anyone" || sym == "everyone" ||
        sym == "no_one" || starts(sym, "n:"))
      return kTag_agent | (starts(sym, "n:") ? (kTag_place | kTag_group) : 0);
    if (sym == "us" || starts(sym, "@G")) return kTag_group | kTag_agent;
    if (starts(sym, "@T") || sym == "this")
      return kTag_animal | kTag_item | kTag_structure | kTag_terrain | kTag_voxel | kTag_water | kTag_fire | kTag_trace | kTag_plant;
    if (starts(sym, "@L") || sym == "@PLACE" || sym == "here") return kTag_place | kTag_water | kTag_terrain;
    if (starts(sym, "@V")) return 0;
    if (starts(sym, "b:") || starts(sym, "g:") || starts(sym, "m:")) return kTag_belief;
    if (starts(sym, "h:") || starts(sym, "q:") || starts(sym, "c:")) return 0;
    if (v.is(sym, kCat_direction)) return kTag_direction;
    const sv base = base_of(sym);
    if (v.has_flag(base, kQuality)) return 0;
    if (v.has_flag(base, kSite)) {
      if (v.has_flag(base, kBuilt)) return kTag_place | kTag_structure | kTag_form;
      if (v.has_flag(base, kWater)) return kTag_place | kTag_water;
      if (v.has_flag(base, kSky)) return kTag_place | kTag_direction;
      return kTag_place | kTag_terrain;
    }
    if (v.has_flag(base, kSpecies)) {
      std::uint64_t out = kTag_animal | kTag_plant;
      if (v.has_flag(base, kItemOrMaterial)) out |= kTag_item | kTag_structure;
      return out;
    }
    if (v.has_flag(base, kForm)) return kTag_form;
    if (v.is_kind(base) || v.is(base, kCat_lookalike)) return kTag_item | kTag_structure | kTag_plant;
    return 0;
  }
  std::uint64_t ref_targets_node(const Item& it) const {
    if (head(it) == "of") return kTag_agent | kTag_group;
    for (std::uint32_t i = 0; i < nargs(it); ++i) {
      const Item& a = args(it)[i];
      if (!is_node(a) && v.has_flag(base_of(text(a)), kSite)) return kTag_place | kTag_structure;
    }
    return kTag_agent | kTag_animal | kTag_item;
  }
  std::uint64_t targets(const Item& it) const {   // Expression._targets
    if (!is_node(it)) {
      const auto k = kinds.find(text(it));
      if (k != kinds.end()) return ref_targets_sym(k->second);
      return ref_targets_sym(text(it));
    }
    return ref_targets_node(it);
  }

  // ---- _classes: 0 = unknown
  std::uint64_t classes(const Item& it) const {
    if (is_node(it)) return 0;
    sv a = text(it);
    const auto k = kinds.find(a);
    if (k != kinds.end()) a = k->second;
    if (a == "me" || a == "you" || a == "someone" || a == "anyone" || a == "no_one" || starts(a, "n:")) return kTag_agent;
    if (a == "us" || a == "everyone" || starts(a, "@G")) return kTag_group | kTag_agent;
    if (starts(a, "@E")) return kTag_agent | kTag_animal;
    if (is_pointer(a) || v.ref_word(a)) return 0;
    const sv base = base_of(a);
    std::uint64_t out = 0;
    if (v.has_flag(base, kSite)) {
      if (v.has_flag(base, kBuilt)) return kTag_structure | kTag_place | kTag_land;
      return v.has_flag(base, kLand) ? (kTag_land | kTag_place) : kTag_place;
    }
    if (v.has_flag(base, kSpecies)) out |= v.has_flag(base, kPlant) ? kTag_plant : v.has_flag(base, kAnimal) ? kTag_animal : 0;
    if (v.has_flag(base, kItemOrMaterial)) out |= kTag_item | kTag_structure;
    return out;
  }

  // ---- the whole thing
  void collect_symbols(const Item& it, std::vector<sv>& out) const {
    out.push_back(is_node(it) ? head(it) : text(it));
    if (is_node(it)) for (std::uint32_t i = 0; i < nargs(it); ++i) collect_symbols(args(it)[i], out);
  }

  void validate() {
    std::vector<sv> syms;
    collect_symbols(e.root_, syms);
    if (static_cast<int>(syms.size()) > kLangMaxSymbols) problem(LangProblem::too_many_symbols);
    if (bare) prop(e.root_, false); else utterance(e.root_);
    const auto holes = std::count(syms.begin(), syms.end(), kHole);
    if (holes != clause_holes) problem(LangProblem::hole_misplaced);
    if (depth(e.root_) > kLangMaxDepth) problem(LangProblem::too_deep);
  }

  void utterance(const Item& it) {
    if (!is_node(it)) { problem(LangProblem::utt_not_list); return; }
    const sv h = head(it);
    const Item* a = args(it);
    std::uint32_t n = nargs(it);
    if (cat(h, kCat_mood)) {
      if (n != 1) { problem(LangProblem::mood_arity); return; }
      prop(a[0], h == "ask");
    } else if (cat(h, kCat_formula)) {
      if (n > 0 && !is_node(a[0]) && is_pointer(text(a[0]))) {
        const ConceptRow* c = v.concept_row(h);
        if (!(c != nullptr && c->answers) || (text(a[0])[0] != 'h' && text(a[0])[0] != 'q' && text(a[0])[0] != 'c'))
          problem(LangProblem::formula_pointer);
        ++a; --n;
      }
      if (n > 1) problem(LangProblem::formula_extra);
      for (std::uint32_t i = 0; i < n; ++i) utterance(a[i]);
    } else {
      problem(LangProblem::utt_head);
    }
  }

  void prop(const Item& it, bool allow_wh) {
    if (!is_node(it)) {
      if (!(is_pointer(text(it)) && kCiting.find(text(it)[0]) != sv::npos)) problem(LangProblem::not_proposition);
      return;
    }
    const sv h = head(it);
    const Item* a = args(it);
    const std::uint32_t n = nargs(it);
    if (cat(h, kCat_mood) || cat(h, kCat_formula)) { problem(LangProblem::second_mood); return; }
    if (h == "described") { problem(LangProblem::described_as_prop); return; }
    if (cat(h, kCat_logic)) {
      const std::uint32_t want = (h == "not" || h == "that") ? 1 : 2;
      if (n != want) { problem(LangProblem::logic_arity); return; }
      if (h == "that") {
        if (!(!is_node(a[0]) && is_pointer(text(a[0])) && kCiting.find(text(a[0])[0]) != sv::npos)) problem(LangProblem::that_target);
        return;
      }
      for (std::uint32_t i = 0; i < n; ++i) prop(a[i], allow_wh);
      return;
    }
    if (cat(h, kCat_time) || cat(h, kCat_evidential)) {
      if (n != 1) { problem(LangProblem::wrap_arity); return; }
      prop(a[0], allow_wh);
      return;
    }
    if (cat(h, kCat_time_op)) {
      if (n != 2) { problem(LangProblem::timeop_arity); return; }
      time_mark(a[0], h);
      prop(a[1], allow_wh);
      return;
    }
    if (h == "did") { event(it, allow_wh); return; }
    const ConceptRow* c = v.concept_row(h);
    if (c == nullptr || !(c->cat & kCat_predicate)) { problem(LangProblem::not_predicate); return; }
    if (static_cast<int>(n) != c->nargs) { problem(LangProblem::pred_arity); return; }
    pointer_budget(it);
    for (std::uint32_t i = 0; i < n; ++i)
      arg(a[i], c->argty[i], allow_wh || (c->wh_ok && c->argty[i] == kTy_proposition));
    for (std::uint32_t i = 0; i < n; ++i) {
      const std::uint64_t allowed = c->argclass[i];
      if (!allowed) continue;
      const std::uint64_t known = classes(a[i]);
      if (known && !(known & allowed)) problem(LangProblem::arg_class);
    }
  }

  void time_mark(const Item& a, sv op) {
    if (is_node(a)) {
      if (head(a) != "span") { problem(LangProblem::time_mark_node); return; }
      bool all_str = true;
      for (std::uint32_t i = 0; i < nargs(a); ++i) all_str = all_str && !is_node(args(a)[i]);
      if (nargs(a) != 2 || !all_str) { problem(LangProblem::span_shape); return; }
      const sv n = text(args(a)[0]), unit = text(args(a)[1]);
      if (!ascii_digits(n) && !v.is(n, kCat_quantity)) problem(LangProblem::span_count);
      if (!v.is(unit, kCat_time_unit)) problem(LangProblem::span_unit);
      return;
    }
    if (op == "for") { problem(LangProblem::for_duration); return; }
    const TypesResult t = types(text(a));
    if (t.err != LangProblem::kCount) { problem(t.err); return; }
    if (!(t.types & (kTy_time | kTy_event))) problem(LangProblem::not_time_mark);
  }

  void event(const Item& it, bool allow_wh) {
    const Item* a = args(it);
    const std::uint32_t n = nargs(it);
    if (n < 2) { problem(LangProblem::did_shape); return; }
    arg(a[0], kTy_agent, allow_wh);
    const ActionRow* act = is_node(a[1]) ? nullptr : v.action(text(a[1]));
    if (act == nullptr) { problem(LangProblem::not_gesture); return; }
    const sv g = text(a[1]);
    const ParamRow* refs[kMaxParams];
    int n_refs = 0;
    for (int i = 0; i < act->nparams; ++i)
      if (act->params[i].type == 0) refs[n_refs++] = &act->params[i];
    std::uint32_t r0 = 2;
    if (r0 < n && (!is_node(a[r0]) || head(a[r0]) == "described" || head(a[r0]) == "of")) {
      arg(a[r0], kTy_entity, allow_wh);
      if (n_refs > 0 && !(!is_node(a[r0]) && v.is(text(a[r0]), kCat_wh)))
        if (!(targets(a[r0]) & refs[0]->accepts)) problem(LangProblem::gesture_target);
      ++r0;
    }
    if (n - r0 > static_cast<std::uint32_t>(kLangMaxRoles)) problem(LangProblem::too_many_roles);
    std::vector<sv> seen;
    for (std::uint32_t i = r0; i < n; ++i) {
      const Item& r = a[i];
      const ParamRow* param = nullptr;
      if (is_node(r)) for (int k = 0; k < act->nparams; ++k) if (head(r) == act->params[k].name) { param = &act->params[k]; break; }
      const bool role_ok = is_node(r) && (head(r) == "says" || head(r) == "how" || head(r) == "with" || (param != nullptr && v.has_word(head(r))));
      if (!role_ok) { problem(LangProblem::role_bad); continue; }
      const sv rh = head(r);
      if (std::find(seen.begin(), seen.end(), rh) != seen.end() && rh != "how") problem(LangProblem::role_twice);
      seen.push_back(rh);
      const Item* ra = args(r);
      const std::uint32_t rn = nargs(r);
      if (rh == "says") {
        if (g != "speak" && g != "write") problem(LangProblem::says_frame);
        if (rn != 1) problem(LangProblem::says_shape); else prop(ra[0], allow_wh);
      } else if (rh == "how") {
        bool bad = rn != 1 || is_node(ra[0]);
        if (!bad) {
          bool in_vals = false;
          for (int k = 0; k < act->nparams && !in_vals; ++k)
            for (int j = 0; j < act->params[k].n_values; ++j)
              if (text(ra[0]) == kValues[act->params[k].first_value + j]) { in_vals = true; break; }
          bad = !in_vals && !v.is(text(ra[0]), kCat_degree);
        }
        if (bad) problem(LangProblem::how_bad);
      } else if (rn != 1) {
        problem(LangProblem::role_shape);
      } else {
        role(g, rh, param, ra[0], allow_wh);
      }
    }
  }

  void role(sv, sv name, const ParamRow* param, const Item& ref, bool allow_wh) {
    arg(ref, kTy_entity, allow_wh);
    if (!is_node(ref) && v.is(text(ref), kCat_wh)) return;
    if (name == "with" && companion(ref)) return;
    if (param == nullptr) { problem(LangProblem::role_none); return; }
    if (param->type == 0) {
      if (!(targets(ref) & param->accepts)) problem(LangProblem::role_accept);
    } else if (param->type == 1 && name == "with" && has_value(*param, "held")) {
      if (!(targets(ref) & kTag_item)) problem(LangProblem::role_held);
    } else {
      problem(LangProblem::role_manner);
    }
  }
  static bool has_value(const ParamRow& p, sv val) {
    for (int j = 0; j < p.n_values; ++j) if (val == kValues[p.first_value + j]) return true;
    return false;
  }

  bool companion(const Item& ref) const {
    if (is_node(ref)) {
      if (head(ref) == "of") return true;
      if (head(ref) != "described") return false;
      for (std::uint32_t i = 0; i < nargs(ref); ++i)
        if (!is_node(args(ref)[i]) && v.is_kind(base_of(text(args(ref)[i])))) return false;
      return true;
    }
    const std::uint64_t t = targets(ref);
    return (t & (kTag_agent | kTag_group)) && !(t & kTag_item);
  }

  void arg(const Item& a, std::uint64_t expected, bool allow_wh) {
    if (expected == kTy_proposition) { prop(a, allow_wh); return; }
    if (expected == kTy_event && is_node(a) && head(a) != "described" && head(a) != "of") { prop(a, allow_wh); return; }
    if (is_node(a)) {
      if (head(a) == "described") { described(a, expected); return; }
      if (head(a) == "of") { part_of(a, expected, allow_wh); return; }
      problem(LangProblem::arg_node);
      return;
    }
    if (v.is(text(a), kCat_wh)) {
      if (!allow_wh) problem(LangProblem::wh_outside);
      return;
    }
    const TypesResult t = types(text(a));
    if (t.err != LangProblem::kCount) { problem(t.err); return; }
    if (!(t.types & accepts_of(expected, true))) problem(LangProblem::arg_cannot);
  }

  void described(const Item& a, std::uint64_t expected) {
    const Item* x = args(a);
    const std::uint32_t n = nargs(a);
    std::uint32_t n_clauses = 0;
    bool node_before_last = false;
    for (std::uint32_t i = 0; i < n; ++i) {
      if (is_node(x[i])) { ++n_clauses; if (i + 1 < n) node_before_last = true; }
    }
    if (n == 0) { problem(LangProblem::described_empty); return; }
    if (n_clauses > 1 || node_before_last) { problem(LangProblem::described_order); return; }
    for (std::uint32_t i = 0; i < n; ++i) {
      if (is_node(x[i])) continue;
      if (!((v.cats(text(x[i])) & kDescriptionCats) || v.is_kind(base_of(text(x[i]))))) { problem(LangProblem::described_words); return; }
    }
    if (!(accepts_of(expected, false) & (kTy_agent | kTy_item | kTy_entity | kTy_place))) { problem(LangProblem::described_expected); return; }
    for (std::uint32_t i = 0; i < n; ++i) {
      if (is_node(x[i])) continue;
      const TypesResult t = types(text(x[i]));
      if (t.err != LangProblem::kCount) problem(t.err);
    }
    for (std::uint32_t i = 0; i < n; ++i) if (is_node(x[i])) relative_clause(x[i]);
  }

  void relative_clause(const Item& c) {
    const sv h = head(c);
    if (h != "did") {
      const ConceptRow* row = v.concept_row(h);
      if (row == nullptr || !(row->cat & kCat_predicate)) { problem(LangProblem::clause_head); return; }
    }
    prop(c, false);
    const int holes = own_holes(c);
    clause_holes += holes;
    if (holes != 1) problem(LangProblem::clause_holes);
  }
  int own_holes(const Item& it) const {
    if (!is_node(it)) return text(it) == kHole ? 1 : 0;
    if (head(it) == "described") return 0;
    int s = 0;
    for (std::uint32_t i = 0; i < nargs(it); ++i) s += own_holes(args(it)[i]);
    return s;
  }

  void part_of(const Item& a, std::uint64_t expected, bool) {
    if (!(accepts_of(expected, false) & (kTy_agent | kTy_entity | kTy_group))) { problem(LangProblem::of_expected); return; }
    if (nargs(a) != 2) { problem(LangProblem::of_arity); return; }
    const Item& q = args(a)[0];
    const Item& g = args(a)[1];
    if (is_node(q) || !(ascii_digits(text(q)) || v.is(text(q), kCat_quantity) || v.is(text(q), kCat_fraction)))
      problem(LangProblem::of_quantity);
    if (is_node(g)) {
      if (head(g) != "described") problem(LangProblem::of_group_head); else described(g, kTy_entity);
    } else if (!(ref_targets_sym(text(g)) & (kTag_group | kTag_agent))) {
      problem(LangProblem::of_not_group);
    }
  }

  void pointer_budget(const Item& it) {
    if (pointers(it) > kLangMaxPointers) problem(LangProblem::pointers_max);
  }
  int pointers(const Item& it) const {
    int n = 0;
    for (std::uint32_t i = 0; i < nargs(it); ++i) {
      const Item& a = args(it)[i];
      if (!is_node(a)) n += (is_pointer(text(a)) || (v.ref_word(text(a)) != nullptr && text(a) != kHole)) ? 1 : 0;
      else if (head(a) == "of" || head(a) == "described") n += pointers(a);
    }
    return n;
  }
  int depth(const Item& it) const {
    if (!is_node(it)) return 0;
    int inner = 0;
    bool has_node_arg = false;
    for (std::uint32_t i = 0; i < nargs(it); ++i) {
      inner = std::max(inner, depth(args(it)[i]));
      has_node_arg = has_node_arg || is_node(args(it)[i]);
    }
    const bool clause = head(it) == "described" && has_node_arg;
    return inner + ((is_nesting_head(head(it)) || clause) ? 1 : 0);
  }
};

// ------------------------------------------------------------------------------------------- Parser::parse
TypedExpression Parser::parse(std::string_view text, const ParseOptions& opt) const {
  TypedExpression e;
  if (text.size() > kLangMaxText) { e.problems_.push_back(LangProblem::too_long); return e; }
  for (const char c : text) {
    const auto u = static_cast<unsigned char>(c);
    if (!(u == '\t' || u == '\n' || u == '\r' || (u >= 0x20 && u <= 0x7e))) { e.problems_.push_back(LangProblem::charset); return e; }
  }
  e.text_ = std::string(text);
  LangBuilder b(e, *vocab_, opt.bare);
  if (opt.pointer_kinds != nullptr)
    for (const auto& [k, x] : *opt.pointer_kinds)
      if (is_pointer(k) && vocab_->is_kind(base_of(x))) b.kinds.emplace(k, x);
  // a bare citation: `(assert b:7)` -> `b:7`
  std::size_t lo = 0, hi = e.text_.size();
  const auto ws = [](char c) { return c == ' ' || (c >= '\t' && c <= '\r'); };
  while (lo < hi && ws(e.text_[lo])) ++lo;
  while (hi > lo && ws(e.text_[hi - 1])) --hi;
  if (opt.bare && lo < hi && is_pointer(sv(e.text_).substr(lo, hi - lo)) && kCiting.find(e.text_[lo]) != sv::npos) {
    e.root_ = TypedExpression::Item{static_cast<std::uint32_t>(lo), static_cast<std::uint32_t>(hi - lo), -1};
    b.validate();
    return e;
  }
  b.tokenize();
  TypedExpression::Item root;
  if (!b.parse_expr(root)) return e;
  if (b.pos < b.toks.size()) { e.problems_.push_back(LangProblem::parse_trailing); return e; }
  if (root.node < 0) { e.problems_.push_back(LangProblem::parse_not_list); return e; }
  e.root_ = root;
  b.validate();
  return e;
}

// ------------------------------------------------------------------------------------------- TypedExpression
int TypedExpression::symbol_count() const {
  if (root_.len == 0 && nodes_.empty()) return 0;
  return root_.node < 0 ? 1 : static_cast<int>(nodes_.size() + [&] {   // heads + leaves
    int leaves = 0;
    for (const auto& a : args_) leaves += a.node < 0 ? 1 : 0;
    return leaves;
  }());
}

void TypedExpression::unparse(const Item& i, std::string& out) const {
  if (i.node < 0) { out.append(sv(i)); return; }
  const Node& n = nodes_[static_cast<std::size_t>(i.node)];
  out += '(';
  out.append(sv(n.head));
  for (std::uint32_t k = 0; k < n.n; ++k) { out += ' '; unparse(args_[n.first + k], out); }
  out += ')';
}

std::string TypedExpression::canonical_text() const {
  std::string s;
  if (root_.len != 0 || !nodes_.empty()) unparse(root_, s);
  return s;
}

std::vector<std::string> TypedExpression::intimate_symbols() const {
  static const LanguageVocabulary vocab;
  std::vector<std::string> out;
  if (root_.len == 0 && nodes_.empty()) return out;
  const auto walk = [&](auto&& self, const Item& i) -> void {
    const SV s = i.node < 0 ? this->sv(i) : this->sv(nodes_[static_cast<std::size_t>(i.node)].head);
    if (vocab.intimate_word(s)) out.emplace_back(s);
    if (i.node >= 0) for (std::uint32_t k = 0; k < nodes_[static_cast<std::size_t>(i.node)].n; ++k) self(self, args_[nodes_[static_cast<std::size_t>(i.node)].first + k]);
  };
  walk(walk, root_);
  return out;
}

// ------------------------------------------------------------------------------------------- Proposition <-> text
namespace {
// symbol layout: kRef = kind code << 20 | number (20 bits); kName = id (24 bits); kNumber = n (24 bits);
// kWord = index in gen::kWords; kKind = index in gen::kKinds;
// kKindQty = count << 11 | (1 if the base is a word, e.g. a look-alike) << 10 | index (10 bits).
constexpr SV kRefKinds[] = {"", "@E", "@T", "@G", "@L", "@V", "@PLACE", "b:", "m:", "g:", "h:", "q:", "c:"};

int word_index(SV s) {
  static const auto idx = [] {
    std::vector<std::pair<sv, int>> v;
    for (std::size_t i = 0; i < gen::kWords.size(); ++i) v.emplace_back(gen::kWords[i], static_cast<int>(i));
    std::sort(v.begin(), v.end());
    return v;
  }();
  const auto it = std::lower_bound(idx.begin(), idx.end(), std::make_pair(s, -1));
  return (it != idx.end() && it->first == s) ? it->second : -1;
}
int kind_index(SV s) {
  static const auto idx = [] {
    std::vector<std::pair<sv, int>> v;
    for (std::size_t i = 0; i < gen::kKinds.size(); ++i) v.emplace_back(gen::kKinds[i], static_cast<int>(i));
    std::sort(v.begin(), v.end());
    return v;
  }();
  const auto it = std::lower_bound(idx.begin(), idx.end(), std::make_pair(s, -1));
  return (it != idx.end() && it->first == s) ? it->second : -1;
}
bool canonical_number(SV s, std::uint64_t limit, std::uint32_t& out) {   // ASCII digits, no leading zero, < limit
  if (!ascii_digits(s) || s.size() > 12 || (s.size() > 1 && s[0] == '0')) return false;
  std::uint64_t n = 0;
  for (const char c : s) n = n * 10 + static_cast<std::uint64_t>(c - '0');
  if (n >= limit) return false;
  out = static_cast<std::uint32_t>(n);
  return true;
}
}  // namespace

ConvertStatus TypedExpression::to_proposition(Proposition& out) const {
  if (!ok() || (root_.len == 0 && nodes_.empty())) return ConvertStatus::not_valid;
  Proposition p;
  ConvertStatus st = ConvertStatus::ok;
  const auto walk = [&](auto&& self, const Item& i) -> void {
    if (st != ConvertStatus::ok) return;
    if (i.node >= 0) {
      const Node& n = nodes_[static_cast<std::size_t>(i.node)];
      const int w = word_index(sv(n.head));
      if (w < 0 || !p.push(Proposition::make(Proposition::kWord, static_cast<std::uint32_t>(w)), static_cast<std::uint8_t>(n.n))) {
        st = ConvertStatus::not_valid;
        return;
      }
      for (std::uint32_t k = 0; k < n.n; ++k) self(self, args_[n.first + k]);
      return;
    }
    const SV s = sv(i);
    std::uint32_t num = 0;
    std::uint32_t symbol = 0;
    if (is_pointer(s)) {
      if (s[0] == 'n') {
        const SV digits = s.substr(2);
        if (digits.size() > 1 && digits[0] == '0') { st = ConvertStatus::noncanonical; return; }
        if (!canonical_number(digits, 1u << 24, num)) { st = ConvertStatus::out_of_range; return; }
        symbol = Proposition::make(Proposition::kName, num);
      } else {
        std::uint32_t code = 6;
        if (s != "@PLACE") {
          const SV k = s[0] == '@' ? s.substr(0, 2) : s.substr(0, 2);
          code = 0;
          for (std::uint32_t c = 1; c < std::size(kRefKinds); ++c) if (kRefKinds[c] == k) code = c;
          const SV digits = s.substr(2);
          if (digits.size() > 1 && digits[0] == '0') { st = ConvertStatus::noncanonical; return; }
          if (!canonical_number(digits, 1u << 20, num)) { st = ConvertStatus::out_of_range; return; }
        }
        symbol = Proposition::make(Proposition::kRef, (code << 20) | num);
      }
    } else if (ascii_digits(s)) {
      if (s.size() > 1 && s[0] == '0') { st = ConvertStatus::noncanonical; return; }
      if (!canonical_number(s, 1u << 24, num)) { st = ConvertStatus::out_of_range; return; }
      symbol = Proposition::make(Proposition::kNumber, num);
    } else if (s.find(':') != SV::npos) {
      const SV base = base_of(s), qty = s.substr(s.find(':') + 1);
      if (qty.empty() || (qty.size() > 1 && qty[0] == '0')) { st = ConvertStatus::noncanonical; return; }
      if (!canonical_number(qty, 1u << 13, num)) { st = ConvertStatus::out_of_range; return; }
      int idx = kind_index(base);
      std::uint32_t is_word = 0;
      if (idx < 0) { idx = word_index(base); is_word = 1; }
      if (idx < 0) { st = ConvertStatus::not_valid; return; }
      symbol = Proposition::make(Proposition::kKindQty, (num << 11) | (is_word << 10) | static_cast<std::uint32_t>(idx));
    } else if (const int w = word_index(s); w >= 0) {
      symbol = Proposition::make(Proposition::kWord, static_cast<std::uint32_t>(w));
    } else if (const int k = kind_index(s); k >= 0) {
      symbol = Proposition::make(Proposition::kKind, static_cast<std::uint32_t>(k));
    } else {
      st = ConvertStatus::not_valid;
      return;
    }
    if (!p.push(symbol, 0)) st = ConvertStatus::not_valid;
  };
  walk(walk, root_);
  if (st != ConvertStatus::ok) return st;
  if (!p.well_formed()) return ConvertStatus::not_valid;
  out = p;
  return ConvertStatus::ok;
}

std::string Parser::to_text(const Proposition& p) {
  if (!p.well_formed()) return {};
  static const LanguageVocabulary vocab;
  std::string out;
  int i = 0;
  bool bad = false;
  const auto symbol_text = [&](std::uint32_t s, std::string& dst) {
    const std::uint32_t val = Proposition::value(s);
    switch (Proposition::tag(s)) {
      case Proposition::kWord: if (val < gen::kWords.size()) dst.append(gen::kWords[val]); else bad = true; break;
      case Proposition::kKind: if (val < gen::kKinds.size()) dst.append(gen::kKinds[val]); else bad = true; break;
      case Proposition::kKindQty: {
        const std::uint32_t idx = val & 0x3FF;
        const bool word = (val >> 10) & 1;
        if (word ? idx < gen::kWords.size() : idx < gen::kKinds.size()) dst.append(word ? gen::kWords[idx] : gen::kKinds[idx]); else bad = true;
        dst += ':';
        dst += std::to_string(val >> 11);
        break;
      }
      case Proposition::kNumber: dst += std::to_string(val); break;
      case Proposition::kName: dst += "n:"; dst += std::to_string(val); break;
      case Proposition::kRef: {
        const std::uint32_t code = val >> 20;
        if (code == 0 || code >= std::size(kRefKinds)) { bad = true; break; }
        dst.append(kRefKinds[code]);
        if (code != 6) dst += std::to_string(val & 0xFFFFF);
        break;
      }
      default: bad = true;
    }
  };
  const auto walk = [&](auto&& self, bool utterance_ctx) -> void {
    if (bad || i >= p.size()) { bad = true; return; }
    const std::uint32_t s = p.symbol(i);
    const int kids = p.children(i);
    ++i;
    const bool word = Proposition::tag(s) == Proposition::kWord;
    // a word without children is an empty list only as a formula in utterance position: (yes). Anywhere else it is a
    // leaf: "quality" is a predicate head with arguments and a bare concept word as an argument.
    const bool formula = word && Proposition::value(s) < gen::kWords.size() &&
                         vocab.is(gen::kWords[Proposition::value(s)], kCat_formula);
    const bool list = word && (kids > 0 || (formula && utterance_ctx));
    if (list) out += '(';
    symbol_text(s, out);
    for (int k = 0; k < kids; ++k) { out += ' '; self(self, formula); }
    if (list) out += ')';
  };
  walk(walk, true);
  return bad ? std::string() : out;
}

}  // namespace em::social
