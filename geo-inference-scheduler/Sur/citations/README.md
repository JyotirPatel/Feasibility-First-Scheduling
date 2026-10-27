# Sur / citations

**Owner:** Sur. **Used by:** Riya, for the report's Related Work and Method sections, and Krupesh, for the novelty wording.

This folder holds the references for the bandit part of the project. `references.bib` has the BibTeX entries. Every entry was checked on 2026-10-25/26:
- The three entries with a DOI were checked against Crossref, the record the publisher (ACM, INFORMS, Springer) deposits: title, authors, venue, volume/issue and pages.
- The other three were checked against the official proceedings pages: PMLR for the AISTATS and ALT papers, the NeurIPS proceedings site for Russac et al.
- Pages are left out where the official record has none. That covers Russac et al., where citing papers disagree, and the LNCS volume number of Garivier & Moulines, which Crossref does not list.

## How to credit them (professor's first comment)

LinUCB and sliding-window LinUCB are **existing methods we use**. They are not our contribution. The project's contribution is the integrated, feasibility-first, change-aware scheduling loop and the recovery benchmark. Suggested wording:

> We use LinUCB [Li et al., 2010] as the node-selection policy and its sliding-window variant [Cheung et al., 2019] to forget stale outcomes after a change. Both are existing methods; our contribution is the integrated, feasibility-first, change-aware scheduling loop around them and a recovery benchmark with six controlled change events.

## References (plain text)

| Key | Reference | What we use it for |
|---|---|---|
| `li2010contextual` | L. Li, W. Chu, J. Langford, R. E. Schapire. *A Contextual-Bandit Approach to Personalized News Article Recommendation.* WWW 2010, pp. 661–670. doi:10.1145/1772690.1772758 | The LinUCB algorithm: one ridge-regression model per arm (node) plus an upper-confidence exploration bonus. This is `linucb/`. |
| `cheung2019learning` | W. C. Cheung, D. Simchi-Levi, R. Zhu. *Learning to Optimize under Non-Stationarity.* AISTATS 2019, PMLR 89:1079–1087 | Sliding-window UCB for non-stationary linear bandits: estimate only from the last W rounds. This is `sliding_window_linucb/`. |
| `cheung2022hedging` | W. C. Cheung, D. Simchi-Levi, R. Zhu. *Hedging the Drift: Learning to Optimize Under Nonstationarity.* Management Science 68(3):1696–1713, 2022. doi:10.1287/mnsc.2021.4024 | The journal version of the above. Cite it alongside, or instead if the report prefers journal versions. |
| `garivier2011switching` | A. Garivier, E. Moulines. *On Upper-Confidence Bound Policies for Switching Bandit Problems.* ALT 2011, Springer LNCS, pp. 174–188. doi:10.1007/978-3-642-24412-4_16 | Why forgetting helps when rewards change: discounted UCB and sliding-window UCB for non-contextual bandits with abrupt changes. |
| `russac2019weighted` | Y. Russac, C. Vernade, O. Cappé. *Weighted Linear Bandits for Non-Stationary Environments.* NeurIPS 2019 | The main alternative to a sliding window: exponential discounting (D-LinUCB). Mention it in related work as an alternative we did not use. |
| `faury2021technical` | L. Faury, Y. Russac, M. Abeille, C. Calauzènes. *A Technical Note on Non-Stationary Parametric Bandits: Existing Mistakes and Preliminary Solutions.* ALT 2021, PMLR 132:619–626 | Caveat for the report (see below). |

## A caveat to state honestly

Faury et al. (2021) report mistakes in the regret analyses of existing forgetting-based methods for drifting (generalized) linear bandits. They give fixes that need an extra assumption on the arm set, or that come with worse rates in general. Our project does not rely on any regret bound: we use sliding-window LinUCB as a practical method and evaluate it empirically. So the report should not quote the original regret bound as a guarantee. Something like this is accurate:

> Theoretical regret guarantees for forgetting-based linear bandits have been revisited (Faury et al., 2021); we therefore treat sliding-window LinUCB as a practical heuristic and evaluate it empirically.

## Two implementation choices worth one sentence in the method section

- **Disjoint models.** As in the LinUCB paper's "disjoint" variant, each node has its own model (A_a, b_a). Cheung et al. analyse a single shared parameter vector; we apply their windowing idea to each node's model.
- **What "the last W" means.** Cheung et al. count the window over all rounds. The team's documents also mention a per-node window. Both are implemented, and the window sweep compares them; see `../window_sweep/RESULTS.md`.
