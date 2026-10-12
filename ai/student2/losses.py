"""losses.py - cross-entropy per head, summed with weights; only the heads that exist for a decision count.

Every target is NO_LABEL (-100) where its head does not apply (a parameter the gesture does not have, a write that was
not made, a condition argument of another type): those entries are ignored, and each term is averaged over its own
valid entries so that a rare head is not drowned by a frequent one. Logits are float32 (the model casts them).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import torch
import torch.nn.functional as F

from .spec import NO_LABEL

# heads whose output and target share a name: logits [.., classes] against labels [..]
FLAT = ("gesture", "ref", "manner", "cond", "cond_ref", "cond_num", "cond_word", "n_writes", "w_target", "w_var", "w_enum",
        "w_num", "w_qty", "w_ptr")
SPEECH = (("sym", "seq_sym"), ("arity", "seq_arity"), ("count", "seq_count"), ("slot", "seq_slot"))


@dataclass
class LossWeights:
    default: float = 1.0
    per_head: dict = field(default_factory=lambda: {"cond_ref": 0.5, "cond_num": 0.5, "cond_word": 0.5, "cond": 0.5,
                                                   "w_target": 0.5, "w_var": 0.5, "w_enum": 0.5, "w_num": 0.5,
                                                   "w_qty": 0.5, "w_ptr": 0.5, "n_writes": 0.5})

    def of(self, name: str) -> float:
        return self.per_head.get(name, self.default)


def masked_ce(logits: torch.Tensor, target: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """-> (mean loss over valid entries, number valid, number correct). Zero loss (with grad) when nothing is valid."""
    flat_l = logits.reshape(-1, logits.shape[-1])
    flat_t = target.reshape(-1)
    valid = flat_t != NO_LABEL
    n = valid.sum()
    loss = F.cross_entropy(flat_l, flat_t, ignore_index=NO_LABEL, reduction="sum") / n.clamp(min=1)
    correct = ((flat_l.argmax(-1) == flat_t) & valid).sum()
    return loss, n, correct


class StudentLoss:
    def __init__(self, weights: LossWeights | None = None):
        self.w = weights or LossWeights()

    def __call__(self, out: dict, batch) -> tuple[torch.Tensor, dict, dict]:
        T = batch.targets
        total, parts, acc = None, {}, {}
        terms = [(name, out[name], T[name]) for name in FLAT]
        sp = out.get("speech")
        if sp is not None:
            bi, si = sp["index"]
            for k, t in SPEECH:
                target = T[t][bi, si]
                if k == "slot":                                  # the slot is 1-based in the targets, the logits are 0-based
                    target = torch.where(target > 0, target - 1, target)
                terms.append((f"s_{k}", sp[k], target))
        for name, logits, target in terms:
            loss, n, correct = masked_ce(logits.float(), target)
            parts[name] = loss
            acc[name] = (correct.float() / n.clamp(min=1)).detach()
            acc[name + "#"] = n.detach()
            term = self.w.of(name.removeprefix("s_") if name.startswith("s_") else name) * loss
            total = term if total is None else total + term
        return total, parts, acc
