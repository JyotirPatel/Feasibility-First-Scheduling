"""
Result tables for the window-size sweep — owner: Sur

Builds every table in RESULTS.md directly from results/summary.csv, so the
numbers in the write-up always equal the bundle:

  python3 window_sweep/make_tables.py            # -> window_sweep/results/tables.md
  python3 window_sweep/make_tables.py --update   # also rewrites the tables inside RESULTS.md

tests/test_figures_and_tables.py fails if a table in RESULTS.md differs from
what this script generates, so after a re-run, run it with --update (and then
re-read the findings text, which is written by hand).

Every number is "mean [95% bootstrap CI]" over the seeds (brief §8), and every
adaptation time is shown next to its steady level G* (work distribution §6).
"""

from __future__ import annotations

import argparse
import csv
import math
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
BRIEF_SIZES = (200, 500, 1000, 2000, 5000)
EXTRA_SIZES = (10000, 20000)
PLAIN = "linucb[alpha=1]"
BASELINE_NAMES = {
    "baseline:StaticWeighted": "static-weighted",
    "baseline:MinRTT": "min-RTT",
    "baseline:LeastLoad": "least-load",
    "baseline:PowerOfTwo": "power-of-two",
    "baseline:RoundRobin": "round-robin",
    "baseline:LowestEnergy": "lowest-energy",
}
SCENARIOS = (
    "s1_stable",
    "s2_traffic_burst",
    "s3_price_shift",
    "s4_thermal_throttle",
    "s5_network_degradation",
    "s6_outage_recovery",
)


def sw(mode: str, w: int, alpha: str = "1") -> str:
    return f"sw_linucb[{mode},W={w},alpha={alpha}]"


def load(path: str) -> dict[tuple[str, str], dict]:
    with open(path, newline="") as f:
        return {(r["label"], r["scenario"]): r for r in csv.DictReader(f)}


def _f(row: dict, key: str) -> float:
    value = row.get(key, "")
    return float(value) if value not in ("", None) else math.nan


def ci(row: dict, key: str, scale: float = 1.0, digits: int = 1, unit: str = "") -> str:
    """'mean [lo, hi]' for one summary column."""
    v, lo, hi = (_f(row, k) * scale for k in (key, key + "_lo", key + "_hi"))
    if math.isnan(v):
        return "n/a"
    return f"{v:.{digits}f}{unit} [{lo:.{digits}f}, {hi:.{digits}f}]"


def alpha_window(s: dict[tuple[str, str], dict]) -> tuple[str, int]:
    """(mode, W) of the exploration check: the sliding-window runs with an alpha other than 1."""
    found = {
        (r["mode"], int(float(r["window"])))
        for r in s.values()
        if r["family"] == "sw_linucb" and float(r["alpha"]) != 1.0
    }
    if len(found) != 1:
        raise ValueError(f"expected one exploration-check window, found {sorted(found)}")
    return found.pop()


def recovered(row: dict, prefix: str = "") -> str:
    return f"{row[prefix + 'recovered_runs']}/{row['seeds']}"


def w_label(w: int) -> str:
    return f"{w} *(extra)*" if w in EXTRA_SIZES else str(w)


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def render(s: dict[tuple[str, str], dict]) -> dict[str, str]:
    """{table title: markdown table}"""
    out: dict[str, str] = {}
    sizes = BRIEF_SIZES + EXTRA_SIZES

    # A — S1: the cost of forgetting
    rows = []
    for w in sizes:
        p, g = s[sw("per_node", w), "s1_stable"], s[sw("global", w), "s1_stable"]
        rows.append(
            [
                w_label(w),
                ci(p, "goodput_mean"),
                ci(p, "slo_rate", 100, unit=" %"),
                ci(g, "goodput_mean"),
                ci(g, "slo_rate", 100, unit=" %"),
            ]
        )
    p = s[PLAIN, "s1_stable"]
    rows.append(["plain LinUCB", ci(p, "goodput_mean"), ci(p, "slo_rate", 100, unit=" %"), "—", "—"])
    out["Table A — S1 stable: the cost of forgetting"] = table(
        ["W", "per-node: mean goodput (req/s)", "per-node: SLO met", "global: mean goodput (req/s)", "global: SLO met"],
        rows,
    )

    # B — S6 after the node returns (anchored at 400 s), one table per window mode
    for mode, letter in (("per_node", "B1"), ("global", "B2")):
        rows = []
        for label, name in [(sw(mode, w), w_label(w)) for w in sizes] + [(PLAIN, "plain LinUCB")]:
            r = s[label, "s6_outage_recovery"]
            rows.append(
                [
                    name,
                    ci(r, "return_adaptation_s"),
                    recovered(r, "return_"),
                    ci(r, "return_g_star"),
                    ci(r, "return_deepest_dip"),
                    ci(r, "return_rush_s"),
                    ci(r, "return_node_share_after", 100, 0, " %"),
                    f"{r['return_node_abandoned_runs']}/{r['seeds']}",
                ]
            )
        mode_name = "per-node" if mode == "per_node" else "global"
        out[f"Table {letter} — S6 after the node returns (from 400 s), {mode_name} windows"] = table(
            [
                "W",
                "adaptation (s)",
                "recovered",
                "G* (req/s)",
                "deepest dip (req/s)",
                "rush (s)",
                "returned node's traffic share after warm-up",
                "seeds where it was abandoned",
            ],
            rows,
        )

    # C — S2 traffic burst
    picks = [
        (PLAIN, "plain LinUCB"),
        *((sw("per_node", w), f"per-node W = {w}") for w in BRIEF_SIZES),
        (sw("global", 1000), "global W = 1000"),
        (sw("global", 5000), "global W = 5000"),
        ("baseline:LeastLoad", "least-load"),
        ("baseline:RoundRobin", "round-robin"),
        ("baseline:StaticWeighted", "static-weighted"),
    ]
    rows = []
    for label, name in picks:
        r = s[label, "s2_traffic_burst"]
        rows.append(
            [name, ci(r, "goodput_mean"), ci(r, "adaptation_s"), recovered(r), ci(r, "g_star"), ci(r, "deepest_dip")]
        )
    out["Table C — S2 traffic burst (3× arrivals for 120 s)"] = table(
        [
            "policy",
            "mean goodput (req/s)",
            "adaptation (s)",
            "recovered",
            "G* during the burst (req/s)",
            "deepest dip (req/s)",
        ],
        rows,
    )

    # D — exploration check, at the window the sweep ran it with
    mode, window = alpha_window(s)
    rows = []
    for a in ("0.1", "0.5", "1", "2"):
        label = sw(mode, window, a)
        s1, s2, s6 = (s[label, sc] for sc in ("s1_stable", "s2_traffic_burst", "s6_outage_recovery"))
        rows.append(
            [
                a + (" (default)" if a == "1" else ""),
                ci(s1, "goodput_mean"),
                ci(s2, "adaptation_s"),
                ci(s2, "g_star"),
                ci(s6, "adaptation_s"),
                ci(s6, "g_star"),
            ]
        )
    mode_name = "per-node" if mode == "per_node" else "global"
    out[f"Table D — exploration check ({mode_name} window, W = {window})"] = table(
        [
            "α",
            "S1 mean goodput (req/s)",
            "S2 adaptation (s)",
            "S2 G* (req/s)",
            "S6 adaptation at t0 (s)",
            "S6 G* (req/s)",
        ],
        rows,
    )

    # E — mean goodput in every scenario
    policies = [
        (PLAIN, "plain LinUCB"),
        *((sw("per_node", w), f"per-node W = {w}") for w in (200, 500, 1000, 2000, 5000)),
        (sw("global", 5000), "global W = 5000"),
        *BASELINE_NAMES.items(),
    ]
    rows = [[name] + [ci(s[label, sc], "goodput_mean") for sc in SCENARIOS] for label, name in policies]
    out["Table E — mean goodput (req/s) in every scenario"] = table(
        ["policy", "S1", "S2", "S3", "S4", "S5", "S6"], rows
    )

    # F — S3 cost per SLO-met request
    cost_rows = [(label, name, _f(s[label, "s3_price_shift"], "cost_per_good_usd")) for label, name in policies]
    rows = [
        [name, ci(s[label, "s3_price_shift"], "cost_per_good_usd", 1e6)]
        for label, name, _ in sorted(cost_rows, key=lambda t: t[2])
    ]
    out["Table F — S3 price shift: cost per SLO-met request (µ$)"] = table(["policy", "cost (µ$)"], rows)

    # G — S6 hard-rule violations by nodes the filter allowed
    labels = [PLAIN] + [sw(m, w) for m in ("per_node", "global") for w in sizes] + list(BASELINE_NAMES)
    names = {PLAIN: "plain LinUCB", **BASELINE_NAMES}
    viol = sorted(
        ((int(s[label, "s6_outage_recovery"]["hard_rule_violations"]), label) for label in labels), reverse=True
    )
    rows = [
        [
            names.get(label, label.replace("sw_linucb[", "").replace(",alpha=1]", "").replace(",", " ")),
            f"{v:,}",
            f"{v / int(s[label, 's6_outage_recovery']['seeds']):,.0f}",
        ]
        for v, label in viol
    ]
    out["Table G — S6: hard-rule violations by nodes the filter allowed"] = table(
        ["policy", "total over all seeds", "per run"], rows
    )
    return out


def update_document(path: str, tables: dict[str, str]) -> None:
    """Replace the body of every '### <title>' section in a Markdown file with the generated table."""
    with open(path) as f:
        text = f.read()
    for title, md in tables.items():
        head = f"### {title}\n\n"
        start = text.find(head)
        if start < 0:
            raise SystemExit(f"{path}: has no section '### {title}'")
        start += len(head)
        end = text.find("\n\n", start)
        text = text[:start] + md + (text[end:] if end >= 0 else "\n")
    with open(path, "w") as f:
        f.write(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(_HERE, "results"))
    ap.add_argument(
        "--update",
        nargs="?",
        const=os.path.join(_HERE, "RESULTS.md"),
        default=None,
        help="also rewrite the tables inside this Markdown file (default: window_sweep/RESULTS.md)",
    )
    args = ap.parse_args(argv)
    tables = render(load(os.path.join(args.results, "summary.csv")))
    path = os.path.join(args.results, "tables.md")
    with open(path, "w") as f:
        f.write("# Window-sweep tables (generated by make_tables.py from summary.csv)\n\n")
        for title, md in tables.items():
            f.write(f"### {title}\n\n{md}\n\n")
    print(f"tables written to {path}")
    if args.update:
        update_document(args.update, tables)
        print(f"tables updated in {args.update}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
