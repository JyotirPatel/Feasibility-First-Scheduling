# Sur / sliding_window_linucb

**Owner:** Sur. **Used by:** the router (Krupesh) as the main adaptive policy; `window_sweep/`.

`sw_linucb.py` implements sliding-window LinUCB (Cheung, Simchi-Levi & Zhu, 2019; brief §6.5). It works like `linucb/`, but each node's `A_a` and `b_a` contain only recent outcomes. When an outcome leaves the window it is subtracted back out: `A_a ← A_a − xxᵀ`, `b_a ← b_a − r·x`.

```python
from sliding_window_linucb import SlidingWindowLinUCB

policy = SlidingWindowLinUCB()  # reads configs/policies/sw_linucb.yaml
```

## The window (set in `configs/policies/sw_linucb.yaml`)

| Setting | Meaning |
|---|---|
| `window.size` | W, the number of outcomes kept. Swept over 200, 500, 1000, 2000 and 5000 in `window_sweep/`. |
| `window.mode: per_node` | The last W outcomes **of each node**. This is how Sur/README.md and the work distribution describe it, and it is the default. |
| `window.mode: global` | The last W outcomes **over all nodes**. This is the brief §6.5 reading, as in Cheung et al. |
| `window.rebuild_every` | Rebuild a node's A and b exactly from its window after this many removals, so subtraction never accumulates rounding error. |

Which mode to use is an open team question (brief §15). Both are implemented and tested, and the sweep compares them. One behaviour difference is tested in `test_only_a_global_window_rediscovers_a_node_it_had_abandoned`:

> LinUCB's uncertainty about a node, its matrix A, only changes when that node's own outcomes arrive. With a **per-node** window, a node the policy stopped picking keeps its old outcomes indefinitely, so it may never be tried again, even after it gets better; in that test it never was. With a **global** window those outcomes age out, the node's exploration bonus grows back, and it is retried.

The window sweep shows the same effect in S6, a node coming back after an outage.
- Per-node windows of W ≤ 2000 sent the recovered node under 1% of requests after its warm-up in 3–7 of 10 seeds (W = 5000: 1 of 10).
- The requests lost in the outage were the newest outcomes in its window and made the model's estimate for it erratic. At W = 200 and W = 1000 the node was dropped in exactly the seeds where that estimate was negative.
- Global windows always used it again, but rushed most requests onto it for 5–7 s (in 69 of 70 runs) while it was still warming up.

See `../window_sweep/RESULTS.md`, findings 4 and 5, for the numbers.

A node whose window empties goes back exactly to `A = λI, b = 0`. Outcomes enter the window in the order their feedback arrives. Checkpoints also save the window contents, and on load the model is rebuilt from them and checked against the saved A and b.

Tests: `tests/test_sw_linucb.py`.
