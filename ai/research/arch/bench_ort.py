"""bench_ort.py - the shipped-runtime question: ONNX Runtime (CUDA EP, CUDA graph) vs PyTorch on the same policy.

  ~/.venvs/emergence-ort/bin/python ai/research/arch/bench_ort.py     # venv: onnx + onnxruntime-gpu 1.31, ~3 min

The stateless policy (small, base; lots of 8 and 32; FP16) is exported to ONNX (opset 18, export-friendly path: the
embedding tables are gathered then summed, ONNX has no fused embedding_bag) and run by ONNX Runtime's CUDA
execution provider with CUDA-graph capture (enable_cuda_graph) and IO binding on preallocated GPU buffers, as the
C++ game would. Compared with the same export path in PyTorch (CUDA graph). Also checks that both give the same
gesture for every NPC of the lot (parity, docs/07 section 6 asks >= 99.9 % on trained weights).
Results: ai/research/arch/results/ort.json
"""
import os
import tempfile

import numpy as np
import onnxruntime as ort
import torch

from arch_common import SIZES, Brain, BrainConfig, CudaTimer, GraphRunner, Tok2InputFactory, save_result, warm_gpu

INPUTS = ("type_id", "num", "known", "cat", "cat_known", "ptr", "ptr_known", "prop_rows", "prop_sym", "prop_arity", "prop_depth", "prop_slot",
          "prop_num", "feasible", "gumbel")
OUTPUTS = ("gesture", "pointers", "manner", "write_ptr", "write_var", "write_val", "value")


class Exportable(torch.nn.Module):
    """Positional inputs, tuple outputs (what ONNX wants)."""

    def __init__(self, brain):
        super().__init__()
        self.brain = brain

    def forward(self, *args):
        out = self.brain(dict(zip(INPUTS, args)))
        return tuple(out[k] for k in OUTPUTS)


class OrtRunner:
    def __init__(self, path, inputs):
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        prov = [("CUDAExecutionProvider", {"enable_cuda_graph": "1", "device_id": "0"})]
        self.sess = ort.InferenceSession(path, so, providers=prov)
        self.binding = self.sess.io_binding()
        self.inputs = inputs                                       # torch tensors on the GPU, kept alive
        used = {i.name for i in self.sess.get_inputs()}           # the exporter drops unused inputs
        for name, t in zip(INPUTS, inputs):
            if name in used:
                self.binding.bind_input(name, "cuda", 0, self._np_type(t), list(t.shape), t.data_ptr())
        for o in self.sess.get_outputs():
            self.binding.bind_output(o.name, "cuda")
        self.run()                                                 # first run captures the graph

    @staticmethod
    def _np_type(t):
        return {torch.float16: np.float16, torch.float32: np.float32, torch.int64: np.int64,
                torch.bool: np.bool_}[t.dtype]

    def run(self):
        self.sess.run_with_iobinding(self.binding)

    def outputs(self):
        return [o.numpy() for o in self.binding.get_outputs()]


def main():
    warm_gpu()
    rows = []
    tmp = tempfile.mkdtemp()
    for size in ("small", "base"):
        torch.manual_seed(0)
        brain = Brain(BrainConfig(name=size, **SIZES[size])).cuda().half().eval()   # NOT folded: export path
        model = Exportable(brain)
        for B in (8, 32):
            b = Tok2InputFactory("cuda", seed=B).make(B)
            args = tuple(b[k].contiguous() for k in INPUTS)
            path = os.path.join(tmp, f"{size}_{B}.onnx")
            with torch.inference_mode():
                torch.onnx.export(model, args, path, input_names=list(INPUTS), output_names=list(OUTPUTS),
                                  opset_version=18, dynamo=False)
                runner = GraphRunner(lambda **kw: model(*[kw[k] for k in INPUTS]), dict(zip(INPUTS, args)))
                t_pt = CudaTimer.measure(runner.replay, iters=40)["median_ms"]
                g_pt = runner.replay()[0].cpu().numpy()
            o = OrtRunner(path, args)
            t_ort = CudaTimer.measure(o.run, iters=40)["median_ms"]
            g_ort = o.outputs()[0]
            same = float((g_pt == g_ort).mean())
            rows.append({"size": size, "B": B, "torch_graph_ms": t_pt, "ort_cuda_graph_ms": t_ort,
                         "gesture_parity": same, "onnx_MB": os.path.getsize(path) / 2**20})
            print(f"{size:>6} B={B:<3} torch+graph {t_pt:6.2f} ms | ORT CUDA EP + graph {t_ort:6.2f} ms | "
                  f"same gesture {same * 100:.1f} % | onnx {rows[-1]['onnx_MB']:.1f} MB", flush=True)
            del o
    print("saved", save_result("ort.json", {"rows": rows, "onnxruntime": ort.__version__}))


if __name__ == "__main__":
    main()
