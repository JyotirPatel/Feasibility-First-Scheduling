# Sur / checkpoints / simulator

**Owner:** Sur. This folder holds the learned policy state saved by `window_sweep/run_sweep.py` on **Parikshit's simulator through Krupesh's router**. These are the current checkpoints of the shipped default policies: plain LinUCB, and sliding-window LinUCB with a per-node window of W = 500 and α = 1, at the end of S1 and S6, seed 0. The sweep writes them automatically; see `../README.md` for the file list, the format and how to load a file.
