"""partial.py - load an older checkpoint into the current model: what fits is copied, the rest starts from its initial weights.

A checkpoint is NOT loadable "as is" when the shapes changed (T09 grew the input vocabulary, T11 added heads). The
partial loader is the only way, and it says exactly what it did (`LoadReport`):

  copied      same name, same shape: copied
  remapped    a table indexed by input symbols (`embed.cat.emb`, `embed.prop.sym`, `decoder.sym`): the registry of tok-2 is
              append-only, so the old symbols keep their rows; the rows of the new symbols keep their initial weights. The
              decoder table also holds the two end rows (end of sequence, start): they MOVE to the end of the grown table
  new         a tensor of the current model the checkpoint does not have (a new head): its initial weights
  reset       same name, another shape that no rule maps: its initial weights (with both shapes)
  dropped     a tensor of the checkpoint the current model does not have: ignored

    model, payload = Checkpoint.load(path, runtime, partial=True)
    payload["load_report"]            # the report as a dict
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import torch


@dataclass
class LoadReport:
    copied: list = field(default_factory=list)
    remapped: dict = field(default_factory=dict)       # name -> {"old_rows", "new_rows", "kept", "moved"}
    new: list = field(default_factory=list)
    reset: dict = field(default_factory=dict)          # name -> {"old": shape, "new": shape}
    dropped: list = field(default_factory=list)

    def reinitialized(self) -> list[str]:
        """Every tensor (at least partly) at its initial weights: the new ones, the reset ones and the remapped tables
        (whose rows for the new symbols are initial)."""
        return self.reinitialized_of(self.to_dict())

    @staticmethod
    def reinitialized_of(report: dict) -> list[str]:
        return sorted([*report["new"], *report["reset"],
                       *(n for n, r in report["remapped"].items() if r["new_rows"] > r["kept"] + r["moved"])])

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        return (f"{len(self.copied)} copied, {len(self.remapped)} remapped, {len(self.new)} new, {len(self.reset)} reset, "
                f"{len(self.dropped)} dropped")


class PartialLoader:
    reinitialized_of = staticmethod(LoadReport.reinitialized_of)

    """Copy the compatible part of `state` (a state dict of an older checkpoint) into `model`."""

    VOCAB = ("embed.cat.emb.weight", "embed.prop.sym.weight")        # [vocab, width]
    VOCAB_END = ("decoder.sym.weight",)                              # [vocab + end + start, width]

    def __init__(self, model: torch.nn.Module):
        self.model = model

    def load(self, state: dict) -> LoadReport:
        report = LoadReport()
        current = self.model.state_dict()
        merged = {}
        for name, ref in current.items():
            old = state.get(name)
            if old is None:
                report.new.append(name)
            elif tuple(old.shape) == tuple(ref.shape):
                merged[name] = old.to(ref.dtype)
                report.copied.append(name)
            else:
                grown = self._remap(name, old, ref, report)
                if grown is None:
                    report.reset[name] = {"old": list(old.shape), "new": list(ref.shape)}
                else:
                    merged[name] = grown
        report.dropped = sorted(n for n in state if n not in current)
        report.reset = dict(sorted(report.reset.items()))
        self.model.load_state_dict({**current, **merged}, strict=True)
        return report

    def _remap(self, name: str, old: torch.Tensor, ref: torch.Tensor, report: LoadReport):
        if name not in self.VOCAB + self.VOCAB_END or old.shape[1:] != ref.shape[1:]:
            return None
        end = 2 if name in self.VOCAB_END else 0
        v_old, v_new = old.shape[0] - end, ref.shape[0] - end
        if v_old > v_new or v_old < 1:
            return None
        out = ref.detach().clone()
        out[:v_old] = old[:v_old].to(ref.dtype)                      # the old symbols keep their ids (append-only registry)
        if end:
            out[v_new:v_new + 2] = old[v_old:v_old + 2].to(ref.dtype)   # end of sequence, start: moved to the end of the table
        report.remapped[name] = {"old_rows": int(old.shape[0]), "new_rows": int(ref.shape[0]), "kept": int(v_old), "moved": end}
        return out
