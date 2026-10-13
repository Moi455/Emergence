"""phrasebook.py - a short list of VALID, varied sentences of the inner language for the teacher's instructions.

The first pilot showed the teacher inventing words ("(ask (are you well))", "friend" taken for a kind): the grammar is
described, but a model imitates examples better than rules. The sentences come from the `utterances` of
catalogue/data/stories.toml (written by the catalogue's authors, tied to their story) and are REVALIDATED here with the
language validator of the current catalogue: a sentence that stopped being valid disappears, nothing is kept by hand.

A function (greet, ask, propose, accept, refuse, threaten, promise, report, apologise...) is read from the sentence
itself (its mood or formula, then its proposition), so a sentence that the catalogue renames changes function with it.
Selection is deterministic (the same catalogue gives the same text, so Gemini's implicit prompt cache keeps working) and
spreads over the functions first, then over the shapes inside a function.

D10: a sentence that speaks of a romantic or intimate subject is never kept.
"""
from __future__ import annotations

import tomllib
from collections import defaultdict
from dataclasses import dataclass

from .toolkit import ROOT, Toolkit

STORIES = ROOT / "catalogue" / "data" / "stories.toml"
EXCLUDED_WORDS = ("romantic", "intimate", "spouse", "w_beautiful", "w_ugly", "pregnancy", "kiss", "seduc", "lover", "touch")
EXCLUDED_STORIES = ("seduc", "court", "adult", "couple", "marriage", "love", "hypocrisy", "custom_shifts", "lover", "intimacy")
DEFAULT_COUNT = 30

# mood / formula -> function (a word of the catalogue not listed here is its own function)
FUNCTION_OF_HEAD = {"hello": "greet", "welcome": "greet", "goodbye": "take leave", "ask": "ask a question",
                    "request": "request an act", "offer": "propose or bargain", "yes": "accept", "no": "refuse",
                    "sorry": "apologise", "help": "call for help", "watch_out": "warn", "ouch": "cry out",
                    "exclaim": "exclaim", "laugh": "laugh"}
# inner head of an assert -> function
FUNCTION_OF_ASSERT = {"if": "threaten or set a condition", "because": "justify", "heard_said": "report hearsay",
                      "seen_myself": "report what I saw", "past": "recount", "long_ago": "recount", "think": "give an opinion",
                      "wants": "say what I want", "norm": "state a custom", "quality": "judge", "attitude": "say how I feel",
                      "owns": "claim or state ownership", "has": "state a fact", "state": "state a fact", "holds": "state a role",
                      "count": "state a fact", "at": "say where", "located": "say where", "link": "state a relation",
                      "sure": "say what I am sure of", "maybe": "express doubt", "dead": "announce a death",
                      "qualifies": "judge an act", "caused": "state a cause", "route": "state a fact"}
SHORT_FIRST = frozenset({"greet", "take leave", "accept", "refuse", "apologise", "warn", "call for help", "laugh", "cry out"})
FUNCTION_ORDER = ("greet", "take leave", "ask a question", "request an act", "propose or bargain", "promise", "accept", "refuse",
                  "apologise", "warn", "call for help", "threaten or set a condition", "report hearsay", "report what I saw",
                  "recount", "justify", "give an opinion", "say what I want", "state a custom", "judge", "say how I feel",
                  "claim or state ownership", "state a fact", "say where", "state a relation", "express doubt")


@dataclass(frozen=True)
class Phrase:
    function: str
    text: str
    story: str


class PhraseBook:
    """Valid sentences of the current language, by function."""

    def __init__(self, tk: Toolkit, count: int = DEFAULT_COUNT, path=STORIES):
        self.tk, self.count, self.path = tk, count, path
        self.rejected: list[tuple[str, str]] = []

    # ---- reading
    def candidates(self) -> list[Phrase]:
        doc = tomllib.loads(self.path.read_text(encoding="utf-8"))
        out, seen = [], set()
        for story in doc.get("story", []):
            sid = story.get("id", "")
            if any(w in sid for w in EXCLUDED_STORIES):
                continue
            for u in story.get("utterances", []):
                text = " ".join(str(u).split())
                if text in seen:
                    continue
                seen.add(text)
                if any(w in text for w in EXCLUDED_WORDS):
                    continue
                e = self.tk.expression(text)
                if not e.ok:
                    self.rejected.append((text, "; ".join(e.problems)))
                    continue
                out.append(Phrase(self.function(text), text, sid))
        return out

    @staticmethod
    def function(text: str) -> str:
        """The function of an utterance, from its first word (mood or formula) and, for an assert, its proposition."""
        head = text.lstrip("(").split()[0].rstrip(")")
        if head == "offer" and text.startswith("(offer (future "):
            return "promise"
        if head in FUNCTION_OF_HEAD:
            return FUNCTION_OF_HEAD[head]
        if head == "assert":
            inner = text[len("(assert"):].strip()
            inner = inner[1:] if inner.startswith("(") else inner
            return FUNCTION_OF_ASSERT.get(inner.split()[0].rstrip(")") if inner else "", "state a fact")
        return head

    @staticmethod
    def shape(text: str) -> str:
        """The first two words, to spread the choice inside a function."""
        return " ".join([w for w in text.replace("(", " ").replace(")", " ").split()][:2])

    # ---- selection
    def select(self) -> list[Phrase]:
        by = defaultdict(list)
        for p in self.candidates():
            by[p.function].append(p)
        for ps in by.values():
            ps.sort(key=lambda p: (len(p.text), p.text))
        order = [f for f in FUNCTION_ORDER if f in by] + sorted(f for f in by if f not in FUNCTION_ORDER)
        chosen: list[Phrase] = []
        used_shapes: set = set()
        for round_ in range(4):                               # a first pass over every function, then more of each
            for f in order:
                pool = [p for p in by[f] if p not in chosen]
                fresh = [p for p in pool if (f, self.shape(p.text)) not in used_shapes] or ([] if round_ == 0 else pool)
                if not fresh or len(chosen) >= self.count:
                    continue
                # a plain interjection first (the shortest: "(hello)"), the others from the middle of the length-sorted pool
                pick = fresh[0] if (round_ == 0 and f in SHORT_FIRST) else fresh[len(fresh) // 2]
                chosen.append(pick)
                used_shapes.add((f, self.shape(pick.text)))
        return chosen[: self.count]

    # ---- text
    def section(self) -> str:
        phrases = self.select()
        lines = [f"  {p.function}: {p.text}" for p in phrases]
        return ("== SENTENCES THAT THE LANGUAGE ACCEPTS (a sample of valid ones, by what they do; the keys @E1, b:3, n:12... "
                "are examples: use the keys of YOUR records) ==\n" + "\n".join(lines) + "\n"
                "Compose in the same way, with WORDS from the list above only. A word of ordinary English that is not in "
                "the list does not exist here and the whole answer is refused: for instance '(ask (are you well))' is "
                "wrong because 'are' is not a predicate; ask about a state with the predicates that exist. "
                "When unsure, say less: a short valid sentence (hello), (yes), (no), (sorry) is better than an invented one.")
