"""
Figures for the window-size sweep — owner: Sur

Reads only the result bundle written by run_sweep.py (results/summary.csv and
results/curves.csv.gz), so every figure can be regenerated from saved data:

  python3 window_sweep/make_figures.py            # -> window_sweep/results/figures/*.png

Figures:
  goodput_<scenario>.png   goodput over time around the change, one line per window size,
                           per-node and global windows side by side, plain LinUCB as reference;
                           dots mark the mean adaptation time
  window_adaptation.png    adaptation time vs W, every scenario (+ S6 return), both window modes
  window_steady_level.png  steady-state goodput G* vs W
  window_goodput.png       mean goodput over the whole run vs W (S1 shows the cost of forgetting)
  alpha_check.png          mean goodput and adaptation time vs the exploration parameter alpha

Colors (validated with the dataviz palette checker): per-node window = blue,
global window = orange, plain LinUCB = neutral gray reference; window size W is
shown as light -> dark steps of the mode's hue. The numbers behind every figure
are in summary.csv (the table view).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import os
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))

# Light-mode chart tokens (dataviz reference palette).
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
MODE_COLOR = {"per_node": "#2a78d6", "global": "#eb6834"}  # categorical slots 1, 2
MODE_RAMP = {
    "per_node": ["#86b6ef", "#2a78d6", "#104281"],  # ordinal: small -> large W
    "global": ["#f2a07c", "#eb6834", "#a3401a"],
}
REFERENCE = INK_2  # plain LinUCB
MODE_NAME = {"per_node": "per-node window", "global": "global window"}
SCENARIO_NAME = {
    "s1_stable": "S1 stable",
    "s2_traffic_burst": "S2 traffic burst",
    "s3_price_shift": "S3 price shift",
    "s4_thermal_throttle": "S4 thermal throttle",
    "s5_network_degradation": "S5 network degradation",
    "s6_outage_recovery": "S6 outage + recovery",
}


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
            "font.size": 9,
            "text.color": INK,
            "axes.labelcolor": INK_2,
            "axes.titlecolor": INK,
            "axes.titlesize": 10,
            "axes.titleweight": "semibold",
            "axes.titlelocation": "left",
            "axes.edgecolor": AXIS,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelcolor": MUTED,
            "ytick.labelcolor": MUTED,
            "xtick.major.size": 0,
            "ytick.major.size": 0,
            "xtick.major.pad": 4,
            "ytick.major.pad": 4,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "grid.linestyle": "-",
            "lines.linewidth": 1.5,
            "lines.solid_capstyle": "round",
            "lines.solid_joinstyle": "round",
            "legend.frameon": False,
            "legend.fontsize": 8,
            "legend.labelcolor": INK_2,
        }
    )


# ── Reading the bundle ───────────────────────────────────────────────────────


def _num(value: str) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def read_summary(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def read_curves(path: str) -> dict[tuple[str, str], tuple[list[float], list[float]]]:
    curves: dict[tuple[str, str], tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    with gzip.open(path, "rt", newline="") as f:
        for row in csv.DictReader(f):
            t, g = curves[row["label"], row["scenario"]]
            t.append(float(row["t_s"]))
            g.append(float(row["goodput"]))
    return curves


def _select(summary, scenario, family, mode=None, window=None, alpha=None):
    out = []
    for r in summary:
        if r["scenario"] != scenario or r["family"] != family:
            continue
        if mode is not None and r["mode"] != mode:
            continue
        if window is not None and _num(r["window"]) != window:
            continue
        if alpha is not None and _num(r["alpha"]) != alpha:
            continue
        out.append(r)
    return out


def _default_alpha(summary) -> float:
    plain = [_num(r["alpha"]) for r in summary if r["family"] == "linucb"]
    return plain[0] if plain else 1.0


# ── Figures ──────────────────────────────────────────────────────────────────


def _compact(x: float, _pos=None) -> str:
    return f"{x / 1000:g}K" if x >= 1000 else f"{x:g}"


def _change_lines(ax, t0: float, t_return: float | None) -> None:
    for t, text in ((t0, "change"), (t_return, "node returns")):
        if t is None:
            continue
        ax.axvline(t, color=MUTED, linewidth=0.8, zorder=1)
        ax.text(t + 4, 1.0, text, transform=ax.get_xaxis_transform(), color=MUTED, fontsize=7.5, va="top")


def goodput_figure(summary, curves, scenario: str, windows: list[int], t0: float, t_return, out: str) -> None:
    alpha = _default_alpha(summary)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4), sharey=True)
    for ax, mode in zip(axes, ("per_node", "global"), strict=True):
        plain = _select(summary, scenario, "linucb", alpha=alpha)
        if plain:
            t, g = curves[plain[0]["label"], scenario]
            ax.plot(t, g, color=REFERENCE, linewidth=1.2, label="plain LinUCB (no window)", zorder=2)
        for color, w in zip(MODE_RAMP[mode], windows, strict=True):
            rows = _select(summary, scenario, "sw_linucb", mode=mode, window=w, alpha=alpha)
            if not rows:
                continue
            t, g = curves[rows[0]["label"], scenario]
            ax.plot(t, g, color=color, label=f"W = {_compact(w)}", zorder=3)
            adapt = _num(rows[0].get("adaptation_s"))
            if adapt is not None and not math.isnan(adapt):
                i = min(int(round(t0 + adapt)), len(g) - 1)
                ax.plot(
                    [t[i]],
                    [g[i]],
                    "o",
                    markersize=6,
                    color=color,
                    markeredgecolor=SURFACE,
                    markeredgewidth=1.5,
                    zorder=4,
                )
        _change_lines(ax, t0, t_return)
        ax.set_xlim(t0 - 60, max(t[-1] for t, _ in curves.values()) + 1)
        ax.set_title(MODE_NAME[mode].capitalize())
        ax.set_xlabel("simulated time (s)")
        # below the axis, so it never sits on top of a dip
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncols=4)
    axes[0].set_ylabel("goodput (SLO-met requests / s)")
    fig.suptitle(
        f"{SCENARIO_NAME[scenario]}: goodput over time, mean of all seeds (dots = mean adaptation time)",
        x=0.01,
        ha="left",
        fontsize=10.5,
        fontweight="semibold",
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=170, bbox_inches="tight")
    plt.close(fig)


def window_figure(
    summary,
    metric: str,
    ylabel: str,
    title: str,
    windows: list[int],
    extended_from: int | None,
    scenarios: list[tuple[str, str]],
    out: str,
) -> None:
    """metric vs W, one panel per (scenario, prefix), both modes, plain LinUCB as a reference line."""
    alpha = _default_alpha(summary)
    cols = 4 if len(scenarios) > 6 else 3
    rows_n = math.ceil(len(scenarios) / cols)
    fig, axes = plt.subplots(rows_n, cols, figsize=(3.3 * cols, 2.7 * rows_n), squeeze=False)
    for ax in axes.flat[len(scenarios) :]:
        ax.set_visible(False)
    for ax, (scenario, prefix) in zip(axes.flat, scenarios, strict=False):
        key = prefix + metric
        for mode in ("per_node", "global"):
            pts = []
            for w in windows:
                rows = _select(summary, scenario, "sw_linucb", mode=mode, window=w, alpha=alpha)
                if rows and _num(rows[0].get(key)) is not None:
                    r = rows[0]
                    pts.append((w, _num(r[key]), _num(r.get(key + "_lo")), _num(r.get(key + "_hi"))))
            pts = [p for p in pts if p[1] is not None and not math.isnan(p[1])]
            if not pts:
                continue
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            lo = [p[2] if p[2] is not None else p[1] for p in pts]
            hi = [p[3] if p[3] is not None else p[1] for p in pts]
            color = MODE_COLOR[mode]
            ax.fill_between(xs, lo, hi, color=color, alpha=0.10, linewidth=0, zorder=2)
            ax.plot(
                xs,
                ys,
                color=color,
                marker="o",
                markersize=5,
                markeredgecolor=SURFACE,
                markeredgewidth=1.2,
                label=MODE_NAME[mode],
                zorder=3,
            )
        plain = _select(summary, scenario, "linucb", alpha=alpha)
        if plain and _num(plain[0].get(key)) is not None and not math.isnan(_num(plain[0][key])):
            ax.axhline(_num(plain[0][key]), color=REFERENCE, linewidth=1.0, zorder=1, label="plain LinUCB")
        if extended_from is not None:
            ax.axvspan(extended_from / 1.25, windows[-1] * 1.25, color=GRID, alpha=0.35, linewidth=0, zorder=0)
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(FixedLocator(windows))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(_compact))
        ax.set_xlim(windows[0] / 1.25, windows[-1] * 1.25)
        name = SCENARIO_NAME[scenario] + (" — after the node returns" if prefix == "return_" else "")
        ax.set_title(name, fontsize=9)
        ax.set_xlabel("window size W (outcomes)")
        ax.set_ylabel(ylabel)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    # bottom centre: never collides with the (long) title, whatever the figure width
    fig.legend(handles, labels, loc="lower center", ncols=3, bbox_to_anchor=(0.5, 0.0))
    shade = " Shaded: extra window sizes beyond the brief's sweep." if extended_from else ""
    fig.suptitle(
        title + " (mean of all seeds, band = 95% bootstrap CI)." + shade,
        x=0.01,
        y=0.995,
        ha="left",
        va="top",
        fontsize=10,
        fontweight="semibold",
        color=INK,
    )
    fig.tight_layout(rect=(0, 0.05 if rows_n > 1 else 0.1, 1, 0.955 if rows_n > 1 else 0.9))
    fig.savefig(out, dpi=170)
    plt.close(fig)


def alpha_figure(summary, out: str) -> None:
    rows = [r for r in summary if r["family"] == "sw_linucb"]
    by_cell: dict[str, dict[float, dict]] = defaultdict(dict)
    counts: dict[tuple, int] = defaultdict(int)
    for r in rows:
        counts[r["mode"], r["window"], r["scenario"]] += 1
    # the alpha-check cell is the (mode, window) with the most distinct alphas
    cells = defaultdict(set)
    for r in rows:
        cells[r["mode"], r["window"]].add(_num(r["alpha"]))
    mode, window = max(cells, key=lambda k: len(cells[k]))
    for r in rows:
        if r["mode"] == mode and r["window"] == window:
            by_cell[r["scenario"]][_num(r["alpha"])] = r
    scenarios = [s for s in SCENARIO_NAME if len(by_cell.get(s, {})) > 1]
    if not scenarios:
        return
    alphas = sorted(set().union(*(by_cell[s].keys() for s in scenarios)))
    fig, axes = plt.subplots(2, len(scenarios), figsize=(3.3 * len(scenarios), 5.0), squeeze=False)
    color = MODE_COLOR[mode]
    for j, s in enumerate(scenarios):
        for i, (metric, ylabel) in enumerate(
            (("goodput_mean", "mean goodput (req/s)"), ("adaptation_s", "adaptation time (s)"))
        ):
            ax = axes[i][j]
            pts = [
                (
                    a,
                    _num(by_cell[s][a].get(metric)),
                    _num(by_cell[s][a].get(metric + "_lo")),
                    _num(by_cell[s][a].get(metric + "_hi")),
                )
                for a in alphas
                if a in by_cell[s]
            ]
            pts = [p for p in pts if p[1] is not None and not math.isnan(p[1])]
            if pts:
                xs = list(range(len(pts)))
                ax.fill_between(xs, [p[2] for p in pts], [p[3] for p in pts], color=color, alpha=0.10, linewidth=0)
                ax.plot(
                    xs,
                    [p[1] for p in pts],
                    color=color,
                    marker="o",
                    markersize=5,
                    markeredgecolor=SURFACE,
                    markeredgewidth=1.2,
                )
                ax.set_xticks(xs, [f"{p[0]:g}" for p in pts])
            ax.set_xlabel("exploration α")
            ax.set_ylabel(ylabel)
            if i == 0:
                ax.set_title(SCENARIO_NAME[s], fontsize=9)
    fig.suptitle(
        f"Exploration check: sliding-window LinUCB ({MODE_NAME[mode]}, W = {_compact(float(window))}), "
        "mean of all seeds, band = 95% bootstrap CI",
        x=0.01,
        ha="left",
        fontsize=10,
        fontweight="semibold",
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=170)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.path.join(_HERE, "results"))
    ap.add_argument("--out", default=None, help="figure folder (default: <results>/figures)")
    args = ap.parse_args(argv)

    _style()
    summary = read_summary(os.path.join(args.results, "summary.csv"))
    curves = read_curves(os.path.join(args.results, "curves.csv.gz"))
    out_dir = args.out or os.path.join(args.results, "figures")
    os.makedirs(out_dir, exist_ok=True)

    sw_windows = sorted({int(_num(r["window"])) for r in summary if r["family"] == "sw_linucb"})
    import yaml  # the brief's default sweep values come from sweep.yaml

    with open(os.path.join(_HERE, "sweep.yaml")) as f:
        sweep = yaml.safe_load(f)
    default_sizes = sweep["window_sweep"]["sizes"]
    extended = sweep["window_sweep"]["extended_sizes"]
    windows = [w for w in sw_windows if w in default_sizes + extended]
    shown = [default_sizes[0], default_sizes[len(default_sizes) // 2], default_sizes[-1]]

    with open(os.path.join(os.path.dirname(_HERE), "standins", "toy_cluster.yaml")) as f:
        cluster = yaml.safe_load(f)
    t0 = cluster["t0_s"]
    scenarios = [s for s in SCENARIO_NAME if any(r["scenario"] == s for r in summary)]
    for s in scenarios:
        t_return = cluster["scenarios"]["s6_outage_recovery"]["return_s"] if s == "s6_outage_recovery" else None
        goodput_figure(summary, curves, s, shown, t0, t_return, os.path.join(out_dir, f"goodput_{s}.png"))

    panels = [(s, "") for s in scenarios] + (
        [("s6_outage_recovery", "return_")] if "s6_outage_recovery" in scenarios else []
    )
    ext_from = extended[0] if extended and extended[0] in windows else None
    window_figure(
        summary,
        "adaptation_s",
        "adaptation time (s)",
        "Adaptation time vs window size",
        windows,
        ext_from,
        panels,
        os.path.join(out_dir, "window_adaptation.png"),
    )
    window_figure(
        summary,
        "g_star",
        "G* (req/s)",
        "Steady-state goodput G* after the change vs window size",
        windows,
        ext_from,
        panels,
        os.path.join(out_dir, "window_steady_level.png"),
    )
    window_figure(
        summary,
        "goodput_mean",
        "mean goodput (req/s)",
        "Mean goodput over the whole run vs window size",
        windows,
        ext_from,
        [(s, "") for s in scenarios],
        os.path.join(out_dir, "window_goodput.png"),
    )
    alpha_figure(summary, os.path.join(out_dir, "alpha_check.png"))
    print(f"figures written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
