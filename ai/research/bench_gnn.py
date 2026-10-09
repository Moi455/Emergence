"""bench_gnn.py - cost of a message-passing GNN over the social graph of the 500 NPCs (docs/07, sections 3-4).

  python3 ai/research/bench_gnn.py               # ~20 s

Two variants of an MPNN layer (message = MLP(h_src, edge), mean aggregation, residual MLP update):
  scatter : index_add_ (float atomics, the usual PyTorch Geometric path) - fast but NOT bitwise reproducible
  csr     : edges sorted by destination, deterministic segment sum via cumsum differences - reproducible
Graph: N = 500 nodes, k relations per node (k = 20, 60, 150), 8 edge features (trust, affection, fear...).
The point is not the speed (tiny either way) but where a GNN could sit without reading objective truth: see docs/07.
Results: ai/research/results/gnn.json
"""
import torch
import torch.nn as nn

from common import CudaTimer, save


class MPNNLayer(nn.Module):
    def __init__(self, d, e=8):
        super().__init__()
        self.msg = nn.Sequential(nn.Linear(d + e, d), nn.GELU(), nn.Linear(d, d))
        self.upd = nn.Sequential(nn.LayerNorm(2 * d), nn.Linear(2 * d, d), nn.GELU(), nn.Linear(d, d))

    def forward(self, h, src, dst, ef, deg, aggregate):
        m = self.msg(torch.cat([h[src], ef], -1))
        agg = aggregate(m, dst, h.shape[0]) / deg.clamp(min=1).unsqueeze(-1)
        return h + self.upd(torch.cat([h, agg], -1))


class Aggregators:
    @staticmethod
    def scatter(m, dst, n):
        return torch.zeros(n, m.shape[1], device=m.device, dtype=m.dtype).index_add_(0, dst, m)

    @staticmethod
    def make_csr(dst_sorted, n):
        counts = torch.bincount(dst_sorted, minlength=n)
        ends = counts.cumsum(0)

        def csr(m, dst, n_):
            c = torch.cat([torch.zeros(1, m.shape[1], device=m.device, dtype=torch.float32), m.float().cumsum(0)])
            return (c[ends] - c[ends - counts]).to(m.dtype)
        return csr


class SocialGraph:
    def __init__(self, n, k, seed=0):
        g = torch.Generator().manual_seed(seed)
        dst = torch.arange(n).repeat_interleave(k)
        src = torch.randint(0, n, (n * k,), generator=g)
        order = torch.argsort(dst, stable=True)
        self.src, self.dst = src[order].cuda(), dst[order].cuda()
        self.ef = torch.randn(n * k, 8, generator=g).cuda()
        self.deg = torch.bincount(self.dst, minlength=n).float()
        self.n = n


def main():
    rows = []
    for d, L in ((128, 2), (256, 3)):
        for k in (20, 60, 150):
            graph = SocialGraph(500, k)
            for dtype in (torch.float32, torch.float16):
                layers = nn.ModuleList([MPNNLayer(d) for _ in range(L)]).cuda().to(dtype).eval()
                h0 = torch.randn(500, d, device="cuda", dtype=dtype)
                ef, deg = graph.ef.to(dtype), graph.deg.to(dtype)
                for name, agg in (("scatter", Aggregators.scatter), ("csr", Aggregators.make_csr(graph.dst, 500))):
                    def run():
                        h = h0
                        for lay in layers:
                            h = lay(h, graph.src, graph.dst, ef, deg, agg)
                        return h
                    with torch.inference_mode():
                        t = CudaTimer.measure(run, iters=50)
                        a, b = run(), run()
                    row = {"d": d, "layers": L, "k": k, "edges": 500 * k, "dtype": str(dtype).split(".")[-1],
                           "aggregate": name, "ms": t["median_ms"], "bitwise_reproducible": bool(torch.equal(a, b))}
                    rows.append(row)
                    print(f"GNN d={d} L={L} k={k:<3} E={500 * k:<6} {row['dtype']:>8} {name:>7}: {t['median_ms']:.3f} ms"
                          f" | reproducible={row['bitwise_reproducible']}", flush=True)
    print("saved", save("gnn.json", {"rows": rows}))


if __name__ == "__main__":
    main()
