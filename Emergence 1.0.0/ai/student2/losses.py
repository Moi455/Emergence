"""losses.py - cross-entropy per head, summed with weights; only the heads that exist for a decision count.

Every target is NO_LABEL (-100) where its head does not apply (a parameter the gesture does not have, a write that was
not made, a condition argument of another type): those entries are ignored.

Weighting. A term is a SUM over its valid entries divided by max(n, B / 8): a frequent head (n >= B / 8) is a plain mean,
a rare head (a stop condition on one decision in ten, a speech on one in five) is divided by B / 8 instead of its own
tiny n, so that a batch with two examples of a rare head does not weigh as much as a batch where every example has
one. The 21-level numeric head has SOFT ORDINAL targets: 0.6 on the level, 0.2 on each neighbour (a half-level
mistake is cheap, a far one is not). Logits are float32 (the model casts them).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import torch
import torch.nn.functional as F

from .spec import NO_LABEL

# heads whose output and target share a name: logits [.., classes] against labels [..]
FLAT = ("gesture", "ref", "manner", "cond", "cond_ref", "cond_num", "cond_word", "n_writes", "w_target", "w_var", "w_enum",
        "w_num", "w_qty", "w_ptr", "plan_gesture", "plan_ref", "plan_repeat", "plan_period", "plan_parent", "stop",
        "stop_ref", "stop_num", "stop_word")
SPEECH = (("sym", "seq_sym"), ("arity", "seq_arity"), ("count", "seq_count"), ("slot", "seq_slot"))
ORDINAL = {"w_num"}                    # the 21-level heads: soft targets
SOFT = (0.2, 0.6, 0.2)


@dataclass
class LossWeights:
    default: float = 1.0
    per_head: dict = field(default_factory=lambda: {"cond_ref": 0.5, "cond_num": 0.5, "cond_word": 0.5, "cond": 0.5,
                                                   "w_target": 0.5, "w_var": 0.5, "w_enum": 0.5, "w_num": 0.5,
                                                   "w_qty": 0.5, "w_ptr": 0.5, "n_writes": 0.5, "stop": 0.5, "stop_ref": 0.5,
                                                   "stop_num": 0.5, "stop_word": 0.5, "plan_period": 0.5})

    def of(self, name: str) -> float:
        return self.per_head.get(name, self.default)


def soft_ordinal_nll(logp: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """-sum_k q_k log p_k for a target distribution q = SOFT around the level (renormalised at the ends). [N] per entry."""
    L = logp.shape[-1]
    t = target.clamp(min=0)
    lo, hi = (t - 1).clamp(min=0), (t + 1).clamp(max=L - 1)
    w_lo = torch.where(t > 0, SOFT[0], 0.0)
    w_hi = torch.where(t < L - 1, SOFT[2], 0.0)
    w_c = SOFT[1]
    z = w_lo + w_c + w_hi                                                                   # renormalised at the ends
    pick = lambda k: logp.gather(-1, k.unsqueeze(-1)).squeeze(-1)                         # noqa: E731
    return -(w_lo * pick(lo) + w_c * pick(t) + w_hi * pick(hi)) / z


def masked_ce(logits: torch.Tensor, target: torch.Tensor, batch: int, ordinal: bool = False):
    """-> (loss, n valid, n correct). loss = sum over valid entries / max(n, batch / 8)."""
    flat_l = logits.reshape(-1, logits.shape[-1])
    flat_t = target.reshape(-1)
    valid = flat_t != NO_LABEL
    n = valid.sum()
    if ordinal:
        nll = soft_ordinal_nll(F.log_softmax(flat_l, -1), flat_t) * valid
        total = nll.sum()
    else:
        total = F.cross_entropy(flat_l, flat_t, ignore_index=NO_LABEL, reduction="sum")
    loss = total / n.clamp(min=batch / 8)
    correct = ((flat_l.argmax(-1) == flat_t) & valid).sum()
    return loss, n, correct


class StudentLoss:
    def __init__(self, weights: LossWeights | None = None):
        self.w = weights or LossWeights()

    def __call__(self, out: dict, batch) -> tuple[torch.Tensor, dict, dict]:
        T = batch.targets
        B = batch.size
        total, parts, acc = None, {}, {}
        terms = [(name, out[name], T[name]) for name in FLAT]
        sp = out.get("speech")
        if sp is not None:
            t = sp["targets"]
            for k, name in SPEECH:
                target = t[name.removeprefix("seq_")]
                if k == "slot":                                  # the slot is 1-based in the targets, the logits are 0-based
                    target = torch.where(target > 0, target - 1, target)
                terms.append((f"s_{k}", sp[k], target))
        for name, logits, target in terms:
            loss, n, correct = masked_ce(logits.float(), target, B, ordinal=name in ORDINAL)
            parts[name] = loss
            acc[name] = (correct.float() / n.clamp(min=1)).detach()
            acc[name + "#"] = n.detach()
            term = self.w.of(name.removeprefix("s_") if name.startswith("s_") else name) * loss
            total = term if total is None else total + term
        return total, parts, acc
