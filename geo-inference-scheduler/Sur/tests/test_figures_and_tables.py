"""The figure and table scripts (window_sweep/make_figures.py, make_tables.py) work on the shipped bundle,
and every table in window_sweep/RESULTS.md is exactly what make_tables.py generates from summary.csv."""

import os

import pytest

from sur_factories import SUR_DIR
from window_sweep import make_figures, make_tables

RESULTS = os.path.join(SUR_DIR, "window_sweep", "results")
HAVE_BUNDLE = os.path.exists(os.path.join(RESULTS, "summary.csv"))
EXPECTED_FIGURES = {f"goodput_{s}.png" for s in make_tables.SCENARIOS} | {
    "window_adaptation.png",
    "window_steady_level.png",
    "window_goodput.png",
    "alpha_check.png",
}


@pytest.mark.skipif(not HAVE_BUNDLE, reason="no result bundle yet (run window_sweep/run_sweep.py)")
def test_make_figures_writes_every_figure(tmp_path):
    assert make_figures.main(["--results", RESULTS, "--out", str(tmp_path)]) == 0
    written = {p for p in os.listdir(tmp_path) if p.endswith(".png")}
    assert written == EXPECTED_FIGURES
    assert all(os.path.getsize(tmp_path / p) > 10_000 for p in written)


@pytest.mark.skipif(not HAVE_BUNDLE, reason="no result bundle yet (run window_sweep/run_sweep.py)")
def test_results_md_tables_equal_the_bundle():
    tables = make_tables.render(make_tables.load(os.path.join(RESULTS, "summary.csv")))
    with open(os.path.join(SUR_DIR, "window_sweep", "RESULTS.md")) as f:
        text = f.read()
    for title, md in tables.items():
        assert f"### {title}\n\n{md}\n" in text, f"RESULTS.md: '{title}' is missing or differs from summary.csv"


def test_update_document_replaces_only_the_table_bodies(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("intro\n\n### T1\n\n| old |\n|---|\n| 1 |\n\ntext after\n\n### T2\n\n(placeholder)\n")
    make_tables.update_document(str(doc), {"T1": "| new |\n|---|\n| 2 |", "T2": "| b |\n|---|\n| 3 |"})
    assert doc.read_text() == (
        "intro\n\n### T1\n\n| new |\n|---|\n| 2 |\n\ntext after\n\n### T2\n\n| b |\n|---|\n| 3 |\n"
    )
    with pytest.raises(SystemExit):
        make_tables.update_document(str(doc), {"T3": "| x |"})


def test_confidence_interval_formatting():
    row = {"x": "0.5", "x_lo": "0.25", "x_hi": "0.75"}
    assert make_tables.ci(row, "x") == "0.5 [0.2, 0.8]"  # round-half-even of 0.25 -> 0.2, 0.75 -> 0.8
    assert make_tables.ci(row, "x", 100, 0, " %") == "50 % [25, 75]"
    assert make_tables.ci({"x": ""}, "x") == "n/a"
