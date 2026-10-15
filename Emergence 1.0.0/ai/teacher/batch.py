"""batch.py - K situations per request, and one repair pass.

The fixed instructions weigh ~6 300 tokens and one situation ~1 800 (measured): grouping K situations in one request
divides the cost of the instructions by K. The answer is structured JSON:

    {"decisions": [ {"id": "S1", "why": ..., "gesture": ..., "params": [...], "speech": ..., "writes": [...]}, ... ]}

    BatchInstructions   the system text: the single-situation instructions, rewritten for a batch + the phrasebook
    BatchSchema         the Gemini response schema of a batch (the single schema, with an id, in an array)
    BatchPrompt         the user text of a batch, and of a repair request
    BatchAnswer         the JSON of a response -> one item per situation id (what is missing, duplicated, unknown)
    GroupedRound        ask K situations, validate each decision, send the refused ones back ONCE with the error
    Slot                one situation of a round, with its first and final verdict

Every decision goes through the SAME AnswerValidator as the single-situation pilot (language, pointers, bounds, governor).
A refusal by the hard rule D10 (`governor:d10_*`) is never sent back: the teacher is not asked to rephrase it, the
decision is dropped and counted. A repair is one request for all the refused decisions of the batch, one attempt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from .gemini import ApiResult
from .phrasebook import PhraseBook
from .render import SituationRenderer
from .schema import EXAMPLES, MAX_WHY_WORDS, PLANNER_EXAMPLE, DecisionSchema, InstructionBuilder
from .toolkit import Toolkit
from .validate import AnswerValidator, Outcome

NOT_REPAIRED = ("governor:d10", "truth_error")        # D10 is never negotiated; truth_error is our bug, not the teacher's


# ---------------------------------------------------------------------------------------------------- instructions
class BatchInstructionBuilder(InstructionBuilder):
    """The single-situation instructions, with the answer format of a batch and the phrasebook before the examples."""

    def __init__(self, tk: Toolkit, phrasebook: PhraseBook | None, vocabulary: str = "full", thoughts: bool = False):
        super().__init__(tk, vocabulary, thoughts=thoughts)
        self.phrasebook = phrasebook

    def answer_format(self) -> str:
        return ("== ANSWER FORMAT ==\n"
                "You receive several situations, S1, S2... Each one is a DIFFERENT inhabitant in its own place: nothing is "
                "shared between them, and the keys (me, @E1, @T3, b:2...) mean something only inside their own situation. "
                'Reply with one JSON object and nothing else: {"decisions": [...]}, with exactly one element per situation '
                "(any order). Each element is:\n"
                '  "id": the situation id (S1, S2...), copied exactly;\n'
                f'  "why": at most {MAX_WHY_WORDS} words, your reason (discarded afterwards, think briefly here first);\n'
                + (self.thought_format() if self.thoughts else "") +
                '  "gesture": exactly one gesture id from GESTURES;\n'
                '  "params": a list of {"name", "value"} (both strings), one per parameter of that gesture; every parameter '
                "is required unless marked ?; do not repeat a name;\n"
                '  "speech": the content you say or write, as one S-expression of the inner language (see SPEECH), only '
                'for the gestures that take "speech"; otherwise an empty string;\n'
                f'  "writes": at most {self.spec.max_writes} changes to your own variables (see WRITES), usually 0 to 2: '
                'a list of {"target", "variable", "value"} (all strings).\n'
                "Keys such as me, @E1, @T3, @L1, @G1, @PLACE, b:2, m:1, g:1 are those printed in the records of THAT situation; "
                "use only keys that appear there. A key kind: @E person, @G group, @T thing or animal, @L known place, "
                "@PLACE where you are, b: belief, m: memory, g: goal. Each situation is decided on its own, as that person "
                "would: do not make them all gentle, nor all alike.")

    def examples(self) -> str:
        if self.thoughts:
            items = [{"id": "S1", **DecisionSchema.example_object(PLANNER_EXAMPLE, PLANNER_EXAMPLE["thoughts"])}]
        else:
            items = [{"id": f"S{i + 1}", **DecisionSchema.example_object(e)} for i, e in enumerate(EXAMPLES)]
        out = ["== EXAMPLE (format only; keys are examples, use those of each situation) ==",
               json.dumps({"decisions": items}, separators=(",", ":"))]
        return "\n".join(out)

    def build(self) -> str:
        text = super().build()
        if self.phrasebook is None:
            return text
        marker = "== EXAMPLE"
        head, _, tail = text.partition(marker)
        return head + self.phrasebook.section() + "\n\n" + marker + tail


class BatchInstructions:
    def __init__(self, tk: Toolkit, phrasebook: PhraseBook | None = None, vocabulary: str = "full", thoughts: bool = False):
        self.builder = BatchInstructionBuilder(tk, phrasebook, vocabulary, thoughts)
        self._text: str | None = None

    def text(self) -> str:
        if self._text is None:
            self._text = self.builder.build()
        return self._text


# ---------------------------------------------------------------------------------------------------- schema
class BatchSchema:
    """{"decisions": [ item ]} where item is the single-decision schema with an `id` first."""

    def __init__(self, single: DecisionSchema):
        self.single = single

    def item(self, gemini: bool = True) -> dict:
        base = self.single._schema(gemini)
        t = (lambda x: x.upper()) if gemini else (lambda x: x)           # noqa: E731
        props = {"id": {"type": t("string")}, **base["properties"]}
        return self.single._object(props, ["id", *base["required"]], gemini)

    def response_schema(self, k: int, gemini: bool = True) -> dict:
        t = (lambda x: x.upper()) if gemini else (lambda x: x)           # noqa: E731
        arr = {"type": t("array"), "items": self.item(gemini)}
        if not gemini:
            arr["maxItems"] = k           # Gemini answers 400 "invalid argument" to maxItems on this nested array (measured 13 oct.)
        return self.single._object({"decisions": arr}, ["decisions"], gemini)


# ---------------------------------------------------------------------------------------------------- prompts
class BatchPrompt:
    LABEL = "S{}"

    def __init__(self, renderer: SituationRenderer):
        self.renderer = renderer

    def labels(self, k: int) -> list[str]:
        return [self.LABEL.format(i + 1) for i in range(k)]

    def render(self, slots: list["Slot"]) -> str:
        parts = [f"{len(slots)} situations: " + ", ".join(s.label for s in slots) + ". Answer each one, with its id."]
        for s in slots:
            parts.append(f"=== SITUATION {s.label} ===\n{self.renderer.render(s.situation).rstrip()}")
        return "\n\n".join(parts) + "\n"

    def render_repair(self, slots: list["Slot"]) -> str:
        parts = [f"REPAIR. The engine refused your answer to {len(slots)} of the situations below. For each one you see the "
                 "situation again, your refused answer and the reason. Answer each situation again in the same format "
                 "({\"decisions\": [...]}, with the same id), correcting exactly what is refused and nothing else that "
                 "needs no change. Use only words and keys that exist (see WORDS, SPEECH and the records)."]
        for s in slots:
            block = [f"=== SITUATION {s.label} ===", self.renderer.render(s.situation).rstrip()]
            if s.raw_item is not None:
                block.append("YOUR REFUSED ANSWER: " + json.dumps({k: v for k, v in s.raw_item.items() if k not in ("id", "why")},
                                                                   separators=(",", ":"), ensure_ascii=False))
            else:
                block.append("YOUR REFUSED ANSWER: none (that situation was missing or unreadable in your reply)")
            block.append(f"REFUSED BECAUSE: {s.first.code}" + (f": {s.first.detail}" if s.first.detail else ""))
            parts.append("\n".join(block))
        return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------------------------------- answers
@dataclass
class BatchAnswer:
    """The response of one request, per situation id."""
    items: dict = field(default_factory=dict)          # id -> dict (first one wins)
    duplicates: int = 0
    unknown: int = 0                                   # ids that were not asked
    problem: str = ""                                  # "" | invalid_json | bad_shape | no_text | truncated

    @classmethod
    def parse(cls, result: ApiResult, asked: list[str]) -> "BatchAnswer":
        a = cls()
        if not result.text:
            a.problem = "no_text"
            return a
        if result.finish == "MAX_TOKENS":
            a.problem = "truncated"
            return a
        s = result.text.strip()
        if s.startswith("```"):
            s = s.strip("`")
            s = s[4:] if s.lower().startswith("json") else s
        try:
            data = json.loads(s)
        except ValueError:
            a.problem = "invalid_json"
            return a
        lst = data.get("decisions") if isinstance(data, dict) else data if isinstance(data, list) else None
        if not isinstance(lst, list):
            a.problem = "bad_shape"
            return a
        for item in lst:
            label = item.get("id") if isinstance(item, dict) else None
            if label not in asked:
                a.unknown += 1
            elif label in a.items:
                a.duplicates += 1
            else:
                a.items[label] = item
        return a


@dataclass
class Slot:
    """One situation of a round: asked under a label, judged once, maybe repaired once."""
    label: str
    situation: object
    raw_item: dict | None = None
    first: Outcome | None = None
    second: Outcome | None = None                      # the verdict on the repaired answer
    final: Outcome | None = None
    repaired: bool = False
    model: str = ""                                    # the model whose answer became final

    @property
    def ok(self) -> bool:
        return self.final is not None and self.final.ok

    @property
    def repairable(self) -> bool:
        return (self.first is not None and not self.first.ok and not self.first.code.startswith(NOT_REPAIRED))


@dataclass
class RequestRecord:
    kind: str                                          # "batch" | "repair"
    model: str
    result: ApiResult
    labels: list
    prompt_chars: int
    answer: BatchAnswer


@dataclass
class RoundResult:
    slots: list
    requests: list
    unusable: bool = False                             # no valid decision at all, even after the repair
    skipped_repair: str = ""


# ---------------------------------------------------------------------------------------------------- a round
class GroupedRound:
    """caller(system, user, schema) -> (model, ApiResult) or None (stopped)."""

    def __init__(self, instructions: BatchInstructions, schema: BatchSchema, prompt: BatchPrompt, validator: AnswerValidator,
                 caller: Callable, can_call: Callable[[], bool] = lambda: True, repair: bool = True,
                 on_reply: Callable[[], None] = lambda: None):
        self.instructions, self.schema, self.prompt, self.validator = instructions, schema, prompt, validator
        self.caller, self.can_call, self.repair, self.on_reply = caller, can_call, repair, on_reply

    def run(self, situations: list) -> RoundResult | None:
        slots = [Slot(label, sit) for label, sit in zip(self.prompt.labels(len(situations)), situations)]
        rec = self._request("batch", slots, self.prompt.render(slots))
        if rec is None:
            return None
        self.on_reply()                                        # the first reply is held: the caller must not restart before it is written
        out = RoundResult(slots, [rec])
        self._judge(slots, rec, first=True)
        todo = [s for s in slots if s.repairable]
        if todo and self.repair:
            if not self.can_call():
                out.skipped_repair = "request cap reached"
            else:
                again = self._request("repair", todo, self.prompt.render_repair(todo))
                if again is not None:                          # None: stopped meanwhile; keep what the first reply gave
                    out.requests.append(again)
                    self._judge(todo, again, first=False)
        for s in slots:
            s.final = s.final or s.first                       # a first answer that was valid, else the first refusal
        out.unusable = not any(s.ok for s in slots)
        return out

    def _request(self, kind: str, slots: list[Slot], user: str) -> RequestRecord | None:
        system = self.instructions.text()
        schema = self.schema.response_schema(len(slots))
        got = self.caller(system, user, schema)
        if got is None:
            return None
        model, result = got
        labels = [s.label for s in slots]
        return RequestRecord(kind, model, result, labels, len(system) + len(user), BatchAnswer.parse(result, labels))

    def _judge(self, slots: list[Slot], rec: RequestRecord, first: bool) -> None:
        for s in slots:
            item = rec.answer.items.get(s.label)
            if item is None:
                code = rec.answer.problem or "missing"
                outcome = Outcome(None, code, "no decision for this situation in the reply")
            else:
                text = json.dumps({k: v for k, v in item.items() if k != "id"}, ensure_ascii=False)
                outcome = self.validator.validate(text, s.situation)
            if first:
                s.raw_item, s.first, s.model = item, outcome, rec.model
            else:
                s.repaired, s.second = True, outcome
                if outcome.ok:                                 # a repair only ever replaces a refusal by a valid decision
                    s.final, s.model, s.raw_item = outcome, rec.model, item
