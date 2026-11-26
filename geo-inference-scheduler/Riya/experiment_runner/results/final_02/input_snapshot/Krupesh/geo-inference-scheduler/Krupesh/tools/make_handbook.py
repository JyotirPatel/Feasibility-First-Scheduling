"""Build Krupesh/Group20_Interface_and_Dependency_Handbook.pdf.

    cd geo-inference-scheduler/Krupesh && python tools/make_handbook.py

Content is kept here as data so it can be reviewed and regenerated. Owner: Krupesh.
"""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parents[1] / "Group20_Interface_and_Dependency_Handbook.pdf"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
pdfmetrics.registerFont(TTFont("DV", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DV-B", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("DV-I", str(FONT_DIR / "DejaVuSans.ttf")))  # no oblique installed
pdfmetrics.registerFont(TTFont("DVM", str(FONT_DIR / "DejaVuSansMono.ttf")))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-B")

INK = colors.HexColor("#1b1b1a")
MUTED = colors.HexColor("#5b5a56")
RULE = colors.HexColor("#d9d8d3")
ACCENT = colors.HexColor("#2a78d6")
SOFT = colors.HexColor("#eef4fc")
CODEBG = colors.HexColor("#f5f5f2")
WARN = colors.HexColor("#fdf3e3")
PERSON = {
    "Krupesh": colors.HexColor("#2a78d6"),
    "Parikshit": colors.HexColor("#1baf7a"),
    "Jyotir": colors.HexColor("#eb6834"),
    "Sur": colors.HexColor("#6250d6"),
    "Riya": colors.HexColor("#c98500"),
}

S = {
    "title": ParagraphStyle(
        "title", fontName="DV-B", fontSize=21, leading=26, textColor=INK, spaceAfter=4
    ),
    "sub": ParagraphStyle(
        "sub", fontName="DV", fontSize=10.5, leading=14, textColor=MUTED, spaceAfter=10
    ),
    "h1": ParagraphStyle(
        "h1",
        fontName="DV-B",
        fontSize=14.5,
        leading=18,
        textColor=INK,
        spaceBefore=10,
        spaceAfter=6,
    ),
    "h2": ParagraphStyle(
        "h2", fontName="DV-B", fontSize=11.5, leading=15, textColor=INK, spaceBefore=8, spaceAfter=4
    ),
    "body": ParagraphStyle(
        "body",
        fontName="DV",
        fontSize=9.2,
        leading=13,
        textColor=INK,
        spaceAfter=4,
        alignment=TA_LEFT,
    ),
    "small": ParagraphStyle("small", fontName="DV", fontSize=8, leading=10.5, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="DV", fontSize=7.9, leading=10, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="DV-B", fontSize=7.9, leading=10, textColor=INK),
    "code": ParagraphStyle("code", fontName="DVM", fontSize=7.0, leading=9.3, textColor=INK),
    "bullet": ParagraphStyle(
        "bullet",
        fontName="DV",
        fontSize=9.2,
        leading=13,
        leftIndent=11,
        bulletIndent=2,
        textColor=INK,
        spaceAfter=1.5,
    ),
}


def P(text, style="body"):
    return Paragraph(text, S[style])


def C(text, bold=False):
    return Paragraph(text, S["cellb" if bold else "cell"])


def bullets(items):
    return [Paragraph(t, S["bullet"], bulletText="•") for t in items]


def table(rows, widths, header=True, zebra=True):
    data = [
        [C(c, bold=(header and i == 0)) if isinstance(c, str) else c for c in r]
        for i, r in enumerate(rows)
    ]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT)]
    if zebra:
        for i in range(2 if header else 1, len(rows), 2):
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafaf8")))
    t.setStyle(TableStyle(st))
    return t


def _wrap(text: str, width: int = 110) -> list[str]:
    """Word-wrap each line to the box width, continuation lines indented under the original."""
    out = []
    for line in text.strip("\n").split("\n"):
        if len(line) <= width:
            out.append(line)
            continue
        indent = " " * (len(line) - len(line.lstrip()) + 2)
        out += textwrap.wrap(
            line,
            width=width,
            subsequent_indent=indent,
            break_on_hyphens=False,
            break_long_words=False,
        )
    return out


def codebox(text, title=None, bg=CODEBG):
    lines = [escape(ln).replace(" ", "&nbsp;") for ln in _wrap(text)]
    body = Paragraph("<br/>".join(lines), S["code"])
    rows = [[body]]
    if title:
        rows.insert(0, [Paragraph(f"<b>{escape(title)}</b>", S["cellb"])])
    t = Table(rows, colWidths=[170 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.6, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
            + ([("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE)] if title else [])
        )
    )
    return t


def note(text, bg=WARN):
    t = Table([[Paragraph(text, S["body"])]], colWidths=[170 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


# ── diagrams ──────────────────────────────────────────────────────────────────


def _arrow(d, x1, y1, x2, y2, color=MUTED, label=None, lx=0, ly=4):
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1))
    import math

    a = math.atan2(y2 - y1, x2 - x1)
    s = 5
    d.add(
        Polygon(
            [
                x2,
                y2,
                x2 - s * math.cos(a - 0.4),
                y2 - s * math.sin(a - 0.4),
                x2 - s * math.cos(a + 0.4),
                y2 - s * math.sin(a + 0.4),
            ],
            fillColor=color,
            strokeColor=color,
        )
    )
    if label:
        d.add(
            String(
                (x1 + x2) / 2 + lx,
                (y1 + y2) / 2 + ly,
                label,
                fontName="DV",
                fontSize=6.6,
                fillColor=INK,
                textAnchor="middle",
            )
        )


def _box(d, x, y, w, h, title, sub, color):
    d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=colors.white, strokeColor=color, strokeWidth=1.6))
    d.add(Rect(x, y + h - 14, w, 14, rx=4, ry=4, fillColor=color, strokeColor=color))
    d.add(
        String(
            x + w / 2,
            y + h - 10.5,
            title,
            fontName="DV-B",
            fontSize=8,
            fillColor=colors.white,
            textAnchor="middle",
        )
    )
    for i, line in enumerate(sub):
        d.add(
            String(
                x + w / 2,
                y + h - 26 - i * 9,
                line,
                fontName="DV",
                fontSize=6.8,
                fillColor=INK,
                textAnchor="middle",
            )
        )


def dependency_diagram():
    """Hub view: Krupesh in the centre; each spoke = what flows in and out. Arrow = provider -> needer."""
    d = Drawing(170 * mm, 106 * mm)
    W, H = 100, 50
    pos = {
        "Krupesh": (191, 122),
        "Parikshit": (0, 122),
        "Riya": (382, 122),
        "Jyotir": (191, 240),
        "Sur": (191, 4),
    }
    sub = {
        "Parikshit": ["simulator + telemetry", "6 event traces"],
        "Krupesh": ["router + API contract", "decision log + integration"],
        "Riya": ["metrics, runner, CIs", "figures + report"],
        "Jyotir": ["feasibility filter", "6 baselines"],
        "Sur": ["LinUCB, SW-LinUCB", "context vector + reward"],
    }
    for k, (x, y) in pos.items():
        _box(d, x, y, W, H, k, sub[k], PERSON[k])
    kx, ky = pos["Krupesh"]

    def h_pair(other, in_label, out_label, left):
        ox, oy = pos[other]
        a, b = (ox + W, kx) if left else (ox, kx + W)
        y_in, y_out = ky + 34, ky + 16
        if left:
            _arrow(d, a, y_in, b, y_in, PERSON[other], in_label, ly=3)
            _arrow(d, b, y_out, a, y_out, PERSON["Krupesh"], out_label, ly=-9)
        else:
            _arrow(d, a, y_in, b, y_in, PERSON[other], in_label, ly=3)
            _arrow(d, b, y_out, a, y_out, PERSON["Krupesh"], out_label, ly=-9)

    def v_pair(other, in_label, out_label, above):
        ox, oy = pos[other]
        x_in, x_out = kx + 32, kx + 68
        if above:
            y_o, y_k = oy, ky + H
        else:
            y_o, y_k = oy + H, ky
        _arrow(d, x_in, y_o, x_in, y_k, PERSON[other])
        _arrow(d, x_out, y_k, x_out, y_o, PERSON["Krupesh"])
        ym = (y_o + y_k) / 2 - 3
        d.add(
            String(
                x_in - 5, ym, in_label, fontName="DV", fontSize=6.6, fillColor=INK, textAnchor="end"
            )
        )
        d.add(
            String(
                x_out + 5,
                ym,
                out_label,
                fontName="DV",
                fontSize=6.6,
                fillColor=INK,
                textAnchor="start",
            )
        )

    h_pair("Parikshit", "telemetry v1 + outcomes", "API contract + client", left=True)
    # Riya: Krupesh provides logs (out), Riya provides metric spec (in)
    rx, _ = pos["Riya"]
    _arrow(d, kx + W, ky + 34, rx, ky + 34, PERSON["Krupesh"], "decision logs + runs", ly=3)
    _arrow(d, rx, ky + 16, kx + W, ky + 16, PERSON["Riya"], "metric spec (sign-off)", ly=-9)
    v_pair("Jyotir", "FilterFn + 6 baselines", "Policy interface + runner", above=True)
    v_pair("Sur", "Policy classes + reward_fn", "Policy interface + reward hook", above=False)
    return d


def loop_diagram():
    d = Drawing(170 * mm, 50 * mm)
    steps = [
        ("Simulator", "Parikshit", "arrivals, telemetry"),
        ("Filter", "Jyotir", "hard rules"),
        ("Policy", "Sur / Jyotir", "choose()"),
        ("Router engine", "Krupesh", "guard + log"),
        ("Node runs it", "Parikshit", "→ Outcome"),
        ("Learn", "Sur", "reward → update()"),
    ]
    owner_color = {
        "Parikshit": PERSON["Parikshit"],
        "Jyotir": PERSON["Jyotir"],
        "Sur": PERSON["Sur"],
        "Sur / Jyotir": PERSON["Sur"],
        "Krupesh": PERSON["Krupesh"],
    }
    w, h, gap = 70, 44, 10.5
    for i, (t, o, sub) in enumerate(steps):
        x = 4 + i * (w + gap)
        _box(d, x, 70, w, h, t, [o, sub], owner_color[o])
        if i < len(steps) - 1:
            _arrow(d, x + w, 92, x + w + gap, 92)
    d.add(Line(4 + 5 * (w + gap) + w / 2, 70, 4 + 5 * (w + gap) + w / 2, 40, strokeColor=MUTED))
    _arrow(
        d,
        4 + 5 * (w + gap) + w / 2,
        40,
        4 + 3 * (w + gap) + w / 2 + 8,
        40,
        label="feedback (delayed)",
        ly=3,
    )
    _arrow(d, 4 + 3 * (w + gap) + w / 2, 40, 4 + 3 * (w + gap) + w / 2, 70)
    d.add(
        String(
            4 + 3 * (w + gap) + w / 2 + 4,
            26,
            "decision log row → Riya (metrics, figures)",
            fontName="DV",
            fontSize=7,
            fillColor=INK,
        )
    )
    return d


# ── content ───────────────────────────────────────────────────────────────────

TELEMETRY = [
    ["Field", "Type", "Unit / allowed values", "Used by"],
    ["schema_version", "str", '"1.0"', "router (rejects other major versions)"],
    ["t", "float", "simulation time, s (≥ 0)", "router: telemetry age, local load accounting"],
    ["node_id", "str", "unique per node", "all"],
    ["status", "str", "up | down | warming", "filter (status rule), context (warming flag)"],
    ["rtt_ms", "dict[str, float]", "ms per user region, ≥ 0", "min-RTT, static-weighted, context"],
    ["queue_len", "int", "≥ 0 waiting requests", "least-load, power-of-two, context"],
    ["running", "int", "≥ 0 in service", "least-load, context"],
    ["capacity", "int", "≥ 1 max concurrent", "context (queue/capacity)"],
    ["kv_used_frac", "float", "0..1 KV cache used", "filter (memory), context"],
    ["models_loaded", "list[str]", 'e.g. ["llama-3-8b"]', "filter (model)"],
    ["power_headroom_kw", "float", "kW below the site cap", "filter (power ≥ 2 kW)"],
    ["temperature_c", "float", "°C", "filter (< 85 °C), reward thermal term"],
    ["energy_price_usd_kwh", "float", "USD/kWh ≥ 0", "lowest-energy, static-weighted, reward"],
    ["gpu_price_usd_hr", "float", "USD per GPU-hour ≥ 0", "context, cost"],
    [
        "kv_capacity_tokens",
        "int | null",
        "extension (optional): KV size in tokens",
        "filter memory rule F2",
    ],
]

REQUEST_ROWS = [
    ["Field", "Type", "Meaning"],
    ["request_id", "str", "unique per run, e.g. r-000123"],
    ["t_arrival", "float", "simulation time (s) the request arrives"],
    ["user_region", "str", "key into rtt_ms, e.g. nyc"],
    ["model", "str", "must be in models_loaded of the chosen node"],
    ["input_tokens", "int ≥ 1", "prompt length"],
    ["expected_output_tokens", "int ≥ 1", "router's estimate of output length"],
    ["slo_class", "str", "interactive | batch"],
    ["ttft_slo_ms", "float > 0", "TTFT promise (250 ms interactive). NOTE: not slo_ms"],
]

OUTCOME_ROWS = [
    ["Field", "Type", "Meaning"],
    ["request_id", "str", "same id as /route"],
    ["ttft_ms", "float", "network + queue + prefill"],
    ["e2e_ms", "float", "ttft + decode (≥ ttft_ms)"],
    ["slo_met", "bool", "ttft_ms ≤ ttft_slo_ms and not failed"],
    ["energy_kwh", "float ≥ 0", "energy attributed to this request"],
    ["cost_usd", "float ≥ 0", "energy cost + GPU rent share"],
    ["failed", "bool (ext.)", "node went down while holding the request"],
    ["t_complete", "float (ext.)", "simulation time the request finished"],
    ["reward", "float", "filled by the ROUTER before policy.update(); senders leave it out"],
]

DECISION_LOG = [
    ["#", "Column", "#", "Column", "#", "Column"],
    ["1", "run_id", "7", "decision", "13", "e2e_ms"],
    ["2", "seed", "8", "node_id", "14", "slo_met"],
    ["3", "scenario", "9", "feasible_nodes (JSON)", "15", "energy_kwh"],
    ["4", "policy", "10", "filtered_out (JSON)", "16", "cost_usd"],
    ["5", "request_id", "11", "reject_reason", "17", "reward"],
    ["6", "t_arrival", "12", "ttft_ms", "", ""],
]

MATRIX = [
    ["Person", "Needs FROM (what, from whom, by when)", "Provides TO (what, to whom, by when)"],
    [
        "Krupesh",
        "Telemetry schema v1 (Parikshit, W1) · feasibility filter interface (Jyotir, W1 stub / W2 full) · "
        "policy classes + reward (Sur, W2 plain / W3 windowed) · simulator that calls /telemetry and /feedback (Parikshit, W2)",
        "API contract + Policy interface (everyone, W1) · decision-log format (Riya, W1) · running end-to-end "
        "system + logs (Riya, W2→) · weekly integration report (all)",
    ],
    [
        "Parikshit",
        "API contract (Krupesh, W1)",
        "Telemetry schema v1 (Krupesh, Jyotir, Sur, W1) · running simulator (W1 5 nodes) · 6 event traces (Riya, W3) · "
        "real-data loaders (Riya, W2)",
    ],
    [
        "Jyotir",
        "Telemetry schema v1 (Parikshit, W1) · Policy interface (Krupesh, W1)",
        "Filter module (Krupesh, Sur; W1 stub, W2 full) · 5–6 baselines (Krupesh, W2) · baseline logs on 6 traces (Riya, W3) · "
        "rule/threshold table (Riya, W3)",
    ],
    [
        "Sur",
        "Telemetry schema v1 (Parikshit, W1) · filter (Jyotir, W1 stub) · Policy interface + Outcome type (Krupesh, W1)",
        "LinUCB (Krupesh, W2) · SW-LinUCB (Krupesh, W3) · window sweep W∈{200,…,5000} (Riya, W3) · citations (Riya, W3)",
    ],
    [
        "Riya",
        "Decision-log format (Krupesh, W1) · running system (Krupesh, W2) · 6 traces (Parikshit, W2–W3) · baseline logs (Jyotir, W3) · "
        "sweep results (Sur, W3)",
        "Adaptation-time spec (all, W1) + code (W2) · experiment-bundle format (all, W3) · report + figures (all, W4)",
    ],
]

PEER = [
    ["Provider", "Needer", "Artifact", "Due"],
    [
        "Parikshit",
        "Jyotir, Sur",
        "Telemetry schema v1 (field names + units): the filter rules and the context vector read it",
        "end of W1",
    ],
    [
        "Parikshit",
        "Riya",
        "Six replayable event traces S1–S6 (+ real-data loaders)",
        "S1/S2 W2, all W3",
    ],
    [
        "Jyotir",
        "Sur",
        "Filter callable: the bandit only ever scores filtered candidates",
        "stub W1, full W2",
    ],
    ["Jyotir", "Riya", "Baseline decision logs on all six traces; rule/threshold table", "W3"],
    ["Sur", "Riya", "Window-sweep results (W ∈ {200, 500, 1000, 2000, 5000}); citations", "W3"],
    [
        "Riya",
        "all",
        "Adaptation-time definition (sign-off) and experiment-bundle format",
        "spec W1, bundle W3",
    ],
]

NEEDS_FROM = [
    ["From", "Exactly what Krupesh's router needs", "Where it plugs in", "Status / due"],
    [
        "Parikshit",
        "Telemetry records with the 14 v1 fields (table §3.1), one per node per tick, sent via "
        "router.ingest_telemetry(list[NodeState]) or POST /telemetry",
        "engine.ingest_telemetry() · POST /telemetry",
        "MISSING → mock_simulator. Due W1–W2",
    ],
    [
        "Parikshit",
        "One Outcome per routed request when it finishes or fails (failed=True), via router.feedback() or "
        "POST /feedback; simulated clock only",
        "engine.feedback() · POST /feedback",
        "MISSING → mock. Due W2",
    ],
    [
        "Parikshit",
        "A driver loop that calls route() for every arrival in simulated time",
        "reference: MockCluster.run() in mocks/mock_simulator.py",
        "MISSING → mock. Due W2",
    ],
    [
        "Jyotir",
        "Feasibility filter returning allowed + reasons",
        "FilterFn via jyotir_adapter.py",
        "DONE (original, unmodified). Fix F1/F2 requested",
    ],
    [
        "Jyotir",
        "Baselines implementing Policy",
        "registry.py: jyotir:<name>",
        "DONE (all 6 via adapter)",
    ],
    [
        "Sur",
        "LinUCB and SW-LinUCB as Policy subclasses (choose/update, delayed feedback)",
        "EXTRA_POLICIES in registry.py",
        "MISSING → mock_policy. Due W2 / W3",
    ],
    [
        "Sur",
        "reward_fn(outcome, node_at_dispatch) -> float (brief §6.3)",
        "reward_fn of the engine (make_engine in app.py)",
        "MISSING → mock_reward. Due W1–W2",
    ],
    [
        "Riya",
        "Nothing for the router to run. Agreement on the decision-log format and adaptation-time spec",
        "decision_log_format.md",
        "format DONE; spec needs sign-off",
    ],
]

OPEN = [
    ["#", "Decision", "Provisional default", "Owner to decide"],
    [
        "1",
        "Adaptation-time settings (90 %, 10 s, G* window 60–120 s)",
        "brief values; 5 s trailing average",
        "all (Riya leads)",
    ],
    ["2", "5 vs 10 nodes in main experiments", "5 nodes", "all"],
    ["3", "Window counted globally or per node", "global (Cheung et al.)", "Sur"],
    ["4", "Reward weights", "w = 1.0 / 0.3 / 0.2 / 0.1", "Sur"],
    [
        "5",
        "Exact filter limits; fix F1/F2; extra queue/capacity rule?",
        "85 °C, 2 kW, KV 0.90 (Jyotir's file)",
        "Jyotir",
    ],
    ["6", "Reason strings", "Jyotir's (temperature_high, …)", "Jyotir + Krupesh"],
    ["7", "Optional telemetry field kv_capacity_tokens", "optional extension", "Parikshit"],
    ["8", "Report format; calendar dates", "Markdown draft; not set", "all"],
]

TIMELINE = [
    ["Week", "Krupesh", "Parikshit", "Jyotir", "Sur", "Riya"],
    [
        "1",
        "API contract, log format, router skeleton ✔",
        "telemetry schema; 5 nodes; tests",
        "rules + config ✔",
        "context vector + reward draft",
        "metrics spec; adaptation-time code",
    ],
    [
        "2",
        "router + filter + baselines end to end ✔",
        "latency model; real traces",
        "5 baselines through filter ✔",
        "plain LinUCB",
        "runner + first baseline numbers",
    ],
    [
        "3",
        "LinUCB plugged in; integration fixes",
        "6 event traces",
        "baselines on 6 traces; edge tests",
        "SW-LinUCB; W sweep",
        "full runs, CIs, ablations",
    ],
    [
        "4",
        "final review; design section",
        "simulator section",
        "re-runs; baselines section",
        "method section",
        "figures, report, slides",
    ],
]


AGENT = {
    "Jyotir": """\
ROLE: You are helping Jyotir (AMS 560 Group 20) finish the feasibility filter + static baselines.
REPO: geo-inference-scheduler/Jyotir/ (Jyotir's own code). Do not edit any other member's folder.
CONTRACT (owner Krupesh, file Krupesh/api_contract/types.py, Krupesh/router_service/policy_base.py):
  - Telemetry record fields (brief 10.1): schema_version, t, node_id, status(up|down|warming), rtt_ms{region:ms},
    queue_len, running, capacity, kv_used_frac(0..1), models_loaded[list], power_headroom_kw, temperature_c,
    energy_price_usd_kwh, gpu_price_usd_hr, optional kv_capacity_tokens.
  - Request fields: request_id, t_arrival, user_region, model, input_tokens, expected_output_tokens,
    slo_class, ttft_slo_ms   (use ttft_slo_ms, not slo_ms).
  - Policy: choose(request, candidates) -> node_id ; update(request, node_id, outcome) -> None.
TASKS:
  1. FIX F1 (safety): in feasibility_filter/filter.py::_check_node a "warming" node returns before the
     model/memory/power/temperature rules. Make "warming" only decide allow/deny (allow_warming_nodes);
     a warming node must still pass every other rule. Add a test: warming + 99 C -> rejected
     "temperature_high".
  2. F2: memory rule must include this request:
     kv_used_frac + (input_tokens + expected_output_tokens) / kv_capacity_tokens > kv_cache_max_frac
     -> "memory_full"; if kv_capacity_tokens is missing, keep the current kv_used_frac >= limit check.
  3. Keep reason strings exactly: node_down, node_warming, model_missing, memory_full, power_limit,
     temperature_high. Filter returns (allowed: list[dict], rejected: list[{node_id, reason}]).
  4. Replace "from stubs.stub_policy import Policy, Outcome" by Krupesh's Policy/Outcome when the team
     merges (Krupesh/router_service/policy_base.py, Krupesh/api_contract/types.py).
  5. Produce baseline decision logs on all 6 scenarios via Krupesh's runner (format: Krupesh/decision_log/
     decision_log_format.md) and give them to Riya. Write the rule/threshold table for the report.
ACCEPTANCE: pytest Jyotir/edge_case_tests passes; then in Krupesh/: pytest -o addopts= tests passes
  (test_known_issue_F1... must be updated to expect rejection after the fix);
  python -m integration.run_end_to_end prints constraint_violations: 0 and log_problems: [].
""",
    "Parikshit": """\
ROLE: You are helping Parikshit (AMS 560 Group 20) build the node simulator + telemetry + event traces.
REPO: put code in geo-inference-scheduler/Parikshit/ (or the agreed src layout). Do not edit others' folders.
CONTRACT (owner Krupesh): Krupesh/api_contract/types.py (NodeState, Request, Outcome),
  Krupesh/api_contract/api_contract.md (HTTP), Krupesh/integration/mocks/mock_simulator.py (reference loop).
BUILD:
  1. SimPy simulator of 5-10 heterogeneous nodes (brief section 5): state = rtt to each user region, queue,
     running, capacity, KV used, models loaded, power headroom, temperature, energy + GPU price,
     status up/down/warming.
  2. Latency: TTFT = T_network + T_queue + T_prefill; T_prefill = a_p + b_p*input_tokens;
     T_decode = out_tokens * t_tok * (1 + c*load); e2e = TTFT + T_decode. A node cannot start a request
     whose KV would overflow.
  3. Telemetry v1 exactly as brief 10.1 (field names + units above), one record per node per tick (1 s).
  4. Six replayable event traces, 600 s, change at t0 = 200 s: S1 stable, S2 burst x3 for 120 s,
     S3 price shift, S4 thermal throttle (node must really exceed the throttle point and can cross 85 C),
     S5 +80 ms RTT on a popular node, S6 node down at 200 s, back at 400 s warming (slower) then up.
  5. Fixed seed per run; generate the whole workload before the run so every policy sees the same requests.
INTEGRATION CALLS (simulated time only; never block on wall-clock):
  every tick:            router.ingest_telemetry(list[NodeState])    or POST /telemetry {"records":[...]}
  every arrival:         d = router.route(Request)                   or POST /route
  if d.decision=="route": submit to node d.node_id
  when a request ends:   router.feedback(Outcome(...))               or POST /feedback
                         failed=True if the node went down while holding it; slo_met = ttft_ms <= ttft_slo_ms
ACCEPTANCE: replace MockCluster in Krupesh/integration/run_end_to_end.py with your simulator; run it in-process
  and over HTTP; decision log must validate (log_problems: []); unit tests for latency + telemetry validity.
""",
    "Sur": """\
ROLE: You are helping Sur (AMS 560 Group 20) implement LinUCB, sliding-window LinUCB, context vector, reward.
REPO: geo-inference-scheduler/Sur/ (or agreed layout). Do not edit others' folders.
CONTRACT (owner Krupesh): implement Krupesh/router_service/policy_base.py::Policy
  class MyPolicy(Policy):
      def choose(self, request: Request, candidates: list[NodeState]) -> str   # node_id from candidates
      def update(self, request: Request, node_id: str, outcome: Outcome) -> None
  reward function signature: reward_fn(outcome: Outcome, node_at_dispatch: NodeState) -> float
RULES THE ROUTER ENFORCES:
  - candidates are ALREADY filtered (feasible only); returning anything else raises RuntimeError.
  - feedback is DELAYED (seconds of sim time) and may arrive out of order: in choose(), store the context
    vector x of the chosen node keyed by request.request_id; in update(), pop it and use outcome.reward
    (the router computes reward with your reward_fn BEFORE calling update).
  - failed requests arrive with outcome.failed=True and slo_met=False.
ALGORITHMS (brief 6.4-6.5): per node a: A_a = lambda*I, b_a = 0; theta = A^-1 b;
  score = theta.x + alpha*sqrt(x^T A^-1 x); choose max; update A += x x^T, b += r x.
  Sliding window: keep last W observations; on eviction A -= x x^T, b -= r x. Sweep W in
  {200, 500, 1000, 2000, 5000}. Window global vs per-node is a TEAM decision.
CONTEXT (brief 6.2): input length, expected output, SLO class, rtt to user region, queue, running,
  KV used, energy + GPU price, temperature, warming flag; FIXED scaling constants from config (no data
  leakage). REWARD (6.3): r = w1*[SLO met] - w2*latency - w3*energy_cost - w4*thermal, terms in 0..1.
REGISTER: Krupesh/router_service/registry.py: EXTRA_POLICIES["sur:linucb"] = lambda seed, **p: LinUCB(seed=seed, **p)
  and pass your reward_fn where mock_reward is used (app.py make_engine, integration/run_end_to_end.py).
ACCEPTANCE: in Krupesh/: python -m integration.run_end_to_end --policy sur:sw_linucb -> log_problems: [],
  constraint_violations: 0; unit tests: closed-form theta check, window add/remove restores A and b.
""",
    "Riya": """\
ROLE: You are helping Riya (AMS 560 Group 20) build metrics, adaptation time, experiment runner, CIs, figures.
INPUT CONTRACT (owner Krupesh): one decision log per run, format Krupesh/decision_log/decision_log_format.md:
  17 frozen columns in order: run_id, seed, scenario, policy, request_id, t_arrival, decision, node_id,
  feasible_nodes(JSON), filtered_out(JSON), reject_reason, ttft_ms, e2e_ms, slo_met, energy_kwh, cost_usd,
  reward; plus outcome_status (ok|failed|rejected|unfinished), t_complete, router_wall_ms, ...
  Read with Krupesh/decision_log/writer.py::read_log; validate with validate_log.
COMPUTE ONLY FROM LOGS (never from simulator memory):
  goodput = SLO-met requests / duration; p95/p99 TTFT and e2e over completed rows; rejection rate;
  energy and cost per SLO-met request.
  Adaptation time (brief 8, team sign-off needed): G(t) goodput in 1 s bins, 5 s moving average;
  G* = mean G over [t0+60, t0+120); adaptation = first t >= t0 with G >= 0.9 G* for 10 s in a row, minus t0;
  never -> "did not recover"; always report G*, deepest dip, lost goodput vs oracle.
  Report the metric's NOISE FLOOR: compute it on S1 (no change) too.
EXPERIMENTS: every policy x 6 scenarios x >= 10 seeds, identical workloads/traces per seed; 95% bootstrap
  CIs; paired differences per seed; tune hyper-parameters on separate seeds (not the reported ones);
  bundle per run = config + seed + git commit + decision log + summary table.
ACCEPTANCE: metrics reproduce on a hand-built log with known answers; figures regenerate from bundles only.
""",
}

ROLE_CH = {
    "Jyotir": dict(
        role="Feasibility filter + static baselines.",
        status="EXISTS — connected to the router unchanged through Krupesh/integration/jyotir_adapter.py. "
        "His 14 tests pass; his folder is byte-identical to his last commit.",
        receives=[
            "<b>Policy interface</b> — Krupesh/router_service/policy_base.py (same signatures as his stub).",
            "<b>Typed contract</b> — Krupesh/api_contract/types.py (Request, NodeState, Outcome, FilterResult).",
            "<b>Runner for baseline logs</b> — Krupesh/integration/run_end_to_end.py; log format in decision_log_format.md.",
        ],
        needed=[
            "<b>F1 (safety):</b> warming nodes must still pass model/memory/power/temperature rules.",
            "<b>F2:</b> memory rule must include this request's tokens (needs kv_capacity_tokens).",
            "<b>Imports:</b> switch stubs.stub_policy → Krupesh's Policy/Outcome when the team merges.",
            "<b>Field name:</b> ttft_slo_ms (not slo_ms) — the adapter maps it until then.",
            "<b>To Riya:</b> baseline decision logs on all six scenarios; rule/threshold table.",
        ],
    ),
    "Parikshit": dict(
        role="Node simulator, telemetry schema, six event traces, real-data loaders.",
        status="MISSING — the router is tested against Krupesh/integration/mocks/mock_simulator.py (a labelled mock).",
        receives=[
            "<b>API contract</b> — Krupesh/api_contract/api_contract.md and schemas.py (HTTP), types.py (Python).",
            "<b>Reference call order</b> — mocks/mock_simulator.py::MockCluster.run.",
            "<b>HTTP client</b> — router_service/client.py::HttpRouter (same methods as the engine).",
        ],
        needed=[
            "<b>Telemetry v1</b> every tick: router.ingest_telemetry(list[NodeState]) or POST /telemetry.",
            "<b>route()</b> for every arrival, in simulated time.",
            "<b>Outcome</b> per routed request on completion/failure: router.feedback() or POST /feedback.",
            "<b>To Jyotir/Sur:</b> the frozen telemetry schema. <b>To Riya:</b> six replayable event traces.",
            "<b>Optional:</b> kv_capacity_tokens field (enables F2).",
        ],
    ),
    "Sur": dict(
        role="LinUCB, sliding-window LinUCB, context vector, reward, window sweep, citations.",
        status="MISSING — the router is tested with mocks/mock_policy.py and mocks/mock_reward.py (labelled mocks).",
        receives=[
            "<b>Policy interface</b> — router_service/policy_base.py; registry hook EXTRA_POLICIES.",
            "<b>Reward hook</b> — RewardFn = (Outcome, NodeState) -> float, called by the engine before update().",
            "<b>Delayed-feedback pattern</b> — mocks/mock_policy.py (cache by request_id).",
        ],
        needed=[
            "<b>LinUCB</b> (W2) and <b>SW-LinUCB</b> (W3) as Policy subclasses registered as sur:linucb / sur:sw_linucb.",
            "<b>reward_fn</b> with weights in a config file.",
            "<b>To Riya:</b> window-sweep results (W ∈ {200, 500, 1000, 2000, 5000}) and citations.",
        ],
    ),
    "Riya": dict(
        role="Metrics incl. adaptation time, experiment runner, bootstrap CIs, ablations, figures, report.",
        status="MISSING — not needed for the router to run; she consumes decision logs.",
        receives=[
            "<b>Decision-log format v1</b> — Krupesh/decision_log/decision_log_format.md; reader/validator in writer.py.",
            "<b>Running system</b> — integration/run_end_to_end.py (in-process or HTTP) producing one log per run.",
        ],
        needed=[
            "<b>Adaptation-time spec</b> for team sign-off (and its noise floor measured on S1).",
            "<b>Experiment-bundle format</b> (config, seed, git commit, log, summary) — W3.",
            "<b>Report + figures</b> regenerated only from bundles — W4.",
        ],
    ),
}


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("DV", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        20 * mm, 12 * mm, "AMS 560 Group 20 · Interface & Dependency Handbook · prepared by Krupesh"
    )
    canvas.drawRightString(190 * mm, 12 * mm, f"page {doc.page}")
    canvas.setStrokeColor(RULE)
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.restoreState()


def build() -> Path:
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title="Group 20 Interface & Dependency Handbook",
        author="Krupesh (AMS 560 Group 20)",
        subject="Contracts and cross-team dependencies for the feasibility-first router",
    )
    st = []
    st += [
        P("Interface &amp; Dependency Handbook", "title"),
        P(
            "AMS 560 · Group 20 · Change-Aware, Feasibility-First Scheduling for AI Inference · "
            f"prepared by Krupesh (architecture &amp; integration) · {date.today().isoformat()}",
            "sub",
        ),
    ]
    st.append(
        note(
            "<b>How to use this document.</b> Every module talks to the router only through the contracts in "
            "Section 3. Each teammate has a chapter (Section 5) with what you receive from Krupesh, what Krupesh "
            "and others need from you, an acceptance checklist, and an <b>Agent brief</b> you can paste into your "
            "AI coding agent as its instructions. Values marked <i>provisional</i> need team approval (Section 7). "
            "Source of truth for code: <font name='DVM'>geo-inference-scheduler/Krupesh/</font> (not pushed to the shared repository yet).",
            bg=SOFT,
        )
    )
    st.append(Spacer(1, 6))

    st.append(P("1. The system in one loop", "h1"))
    st.append(
        P(
            "A real HTTP router (Krupesh) decides which simulated GPU site serves each LLM request. "
            "Hard safety rules (Jyotir) run first; a policy (Jyotir's baselines or Sur's LinUCB) chooses among "
            "the remaining sites; the simulated node (Parikshit) serves it and reports the outcome; the router "
            "computes the reward (Sur), updates the policy and writes one decision-log row that Riya turns into "
            "metrics and figures."
        )
    )
    st.append(loop_diagram())
    st.append(
        table(
            [
                ["Module", "Owner", "Status today", "Where it plugs into the router"],
                [
                    "Router service, API contract, decision log, integration",
                    "Krupesh",
                    "DONE (32 tests)",
                    "Krupesh/router_service, api_contract, decision_log, integration",
                ],
                [
                    "Feasibility filter + 6 baselines",
                    "Jyotir",
                    "EXISTS, used unchanged",
                    "FilterFn + Policy via integration/jyotir_adapter.py",
                ],
                [
                    "Simulator + telemetry + 6 traces",
                    "Parikshit",
                    "MISSING (mock used)",
                    "ingest_telemetry / route / feedback calls",
                ],
                [
                    "LinUCB + SW-LinUCB + reward",
                    "Sur",
                    "MISSING (mocks used)",
                    "Policy subclass + reward_fn",
                ],
                ["Metrics, runner, CIs, figures", "Riya", "MISSING", "reads decision logs only"],
            ],
            [52 * mm, 20 * mm, 32 * mm, 66 * mm],
        )
    )

    st.append(PageBreak())
    st.append(P("2. Who depends on whom", "h1"))
    st.append(
        P(
            "Arrows point from the person who provides an artifact to the person who needs it. "
            "Colours follow the provider. Week numbers (W1–W4) follow the Work Distribution timeline."
        )
    )
    st.append(P("2.1 Krupesh's router in the middle (arrow = provider → needer)", "h2"))
    st.append(dependency_diagram())
    st.append(P("2.2 Dependencies between the other teammates", "h2"))
    st.append(table(PEER, [26 * mm, 26 * mm, 84 * mm, 34 * mm]))
    st.append(CondPageBreak(70 * mm))
    st.append(P("2.3 Full matrix — everyone", "h2"))
    st.append(table(MATRIX, [20 * mm, 75 * mm, 75 * mm]))

    st.append(PageBreak())
    st.append(P("3. Shared contracts (exact)", "h1"))
    st.append(
        P(
            "Owner: Krupesh for the API, Python interfaces and decision log; Parikshit for telemetry v1. "
            "Field names, types and units below are frozen v1 from Project Brief §10. Changing any of them "
            "needs a message to the whole group."
        )
    )
    st.append(P("3.1 Telemetry record v1 (one per node per tick) — owner Parikshit", "h2"))
    st.append(table(TELEMETRY, [36 * mm, 26 * mm, 50 * mm, 58 * mm]))
    st.append(CondPageBreak(60 * mm))
    st.append(P("3.2 Request (POST /route body)", "h2"))
    st.append(table(REQUEST_ROWS, [44 * mm, 26 * mm, 100 * mm]))
    st.append(P("3.3 Decision (POST /route response)", "h2"))
    st.append(
        codebox(
            '{"request_id": "r-000123", "decision": "route" | "reject", "node_id": "us-east-1" | null,\n'
            ' "policy": "jyotir:static_weighted", "feasible_nodes": ["us-east-1"],\n'
            ' "filtered_out": {"us-west-2": "temperature_high"}, "reject_reason": null | "no_feasible_node"}'
        )
    )
    st.append(
        P(
            "Filter reason strings (Jyotir's): node_down · node_warming · model_missing · memory_full · power_limit · temperature_high.",
            "small",
        )
    )
    st.append(CondPageBreak(70 * mm))
    st.append(P("3.4 Outcome (POST /feedback body, sent when the request finishes)", "h2"))
    st.append(table(OUTCOME_ROWS, [30 * mm, 26 * mm, 114 * mm]))
    st.append(CondPageBreak(80 * mm))
    st.append(P("3.5 Python plug-in interfaces", "h2"))
    st.append(
        codebox(
            "# Krupesh/router_service/policy_base.py          implemented by Jyotir (baselines) and Sur (bandits)\n"
            "class Policy:\n"
            "    def choose(self, request: Request, candidates: list[NodeState]) -> str: ...   # node_id\n"
            "    def update(self, request: Request, node_id: str, outcome: Outcome) -> None: ...\n\n"
            "# Krupesh/api_contract/types.py\n"
            "FilterFn = Callable[[Request, list[NodeState]], FilterResult]   # Jyotir  -> allowed + {node: reason}\n"
            "RewardFn = Callable[[Outcome, NodeState], float]                # Sur     -> reward for update()\n\n"
            "# Krupesh/router_service/engine.py  (what the simulator calls, in simulated time)\n"
            "router.ingest_telemetry(list[NodeState])   # every tick       (HTTP: POST /telemetry)\n"
            "decision = router.route(Request)           # every arrival    (HTTP: POST /route)\n"
            "reward = router.feedback(Outcome)          # on completion    (HTTP: POST /feedback)",
            title="Plug-in points",
        )
    )
    st.append(
        P(
            "Guarantees enforced by the router: (1) policies only ever see feasible nodes; (2) a choice outside "
            "them raises instead of routing; (3) empty feasible set → deliberate reject 'no_feasible_node'; "
            "(4) feedback is delayed and the reward is computed by the router before update(); "
            "(5) between telemetry ticks the router adds its own recent placements to queue_len/kv_used_frac.",
            "small",
        )
    )
    st.append(CondPageBreak(60 * mm))
    st.append(
        P("3.6 Decision log v1 — 17 frozen columns, in order (owner Krupesh, consumer Riya)", "h2")
    )
    st.append(table(DECISION_LOG, [8 * mm, 46 * mm, 8 * mm, 46 * mm, 8 * mm, 54 * mm]))
    st.append(
        P(
            "Extensions after column 17: outcome_status (ok/failed/rejected/unfinished), t_complete, user_region, "
            "model, slo_class, ttft_slo_ms, input/expected tokens, chosen_node_status, telemetry_age_s, "
            "constraint_violation (must be null), true_state_violation, router_wall_ms (real time, never simulated).",
            "small",
        )
    )

    st.append(PageBreak())
    st.append(P("4. What Krupesh's router needs from each teammate", "h1"))
    st.append(
        P(
            "These are the dependencies <b>on</b> Krupesh's work: until each item exists, the router runs with the "
            "labelled mock named in the last column."
        )
    )
    st.append(table(NEEDS_FROM, [19 * mm, 70 * mm, 47 * mm, 34 * mm]))

    st.append(P("5. One chapter per teammate", "h1"))
    for i, (name, ch) in enumerate(ROLE_CH.items()):
        if i:
            st.append(PageBreak())
        head = Table(
            [
                [
                    Paragraph(
                        f"<font color='white'><b>5.{i + 1} {name}</b> — {ch['role']}</font>",
                        S["body"],
                    )
                ]
            ],
            colWidths=[170 * mm],
        )
        head.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PERSON[name]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        st.append(head)
        st.append(Spacer(1, 4))
        st.append(P(f"<b>Status:</b> {ch['status']}"))
        st.append(P("You receive from Krupesh", "h2"))
        st += bullets(ch["receives"])
        st.append(P("Krupesh and the team need from you", "h2"))
        st += bullets(ch["needed"])
        st.append(Spacer(1, 4))
        st.append(
            KeepTogether(
                [
                    P("Agent brief — paste this into your AI coding agent", "h2"),
                    codebox(AGENT[name], title=f"AGENT BRIEF · {name}"),
                ]
            )
        )

    st.append(PageBreak())
    st.append(P("6. How to verify an integration (any teammate)", "h1"))
    st.append(
        codebox(
            "cd geo-inference-scheduler/Krupesh\n"
            "pip install -r requirements.txt\n"
            "pytest -o addopts= tests                          # must stay green (32 tests today)\n"
            "python -m integration.run_end_to_end              # closed loop with Jyotir's original code\n"
            "python -m integration.run_end_to_end --policy mock:learning --outage\n"
            "uvicorn router_service.app:app --port 8000 &      # real HTTP service, docs at /docs\n"
            "python -m integration.run_end_to_end --mode http --url http://127.0.0.1:8000\n\n"
            'Expected in every summary:  "log_problems": []   and   "constraint_violations": 0',
            title="Commands",
        )
    )
    st += bullets(
        [
            "Implement only against <font name='DVM'>api_contract/types.py</font> and <font name='DVM'>router_service/policy_base.py</font>.",
            "Register your policy in <font name='DVM'>router_service/registry.py</font> (EXTRA_POLICIES) or pass your function as filter_fn / reward_fn.",
            "Delete the matching file in <font name='DVM'>integration/mocks/</font> once your module is connected.",
            "Never edit another member's folder; propose changes in a pull request reviewed by one teammate.",
        ]
    )

    st.append(P("7. Open decisions that need the team", "h1"))
    st.append(table(OPEN, [8 * mm, 70 * mm, 54 * mm, 38 * mm]))
    st.append(P("8. Timeline (Work Distribution §7) — ✔ = done in Krupesh's build", "h1"))
    st.append(table(TIMELINE, [14 * mm, 36 * mm, 30 * mm, 30 * mm, 30 * mm, 30 * mm]))
    st.append(P("9. Glossary", "h1"))
    st.append(
        table(
            [
                ["Term", "Meaning"],
                ["TTFT", "time to first token = network + queue + prefill"],
                ["SLO / goodput", "the promise (TTFT ≤ 250 ms) / requests per second that kept it"],
                ["Telemetry", "numbers each node reports every tick (Section 3.1)"],
                ["Feasible node", "passes every hard rule; the only nodes a policy may choose"],
                [
                    "Delayed feedback",
                    "the outcome arrives when the request finishes, seconds after the decision",
                ],
                [
                    "Mock / adapter",
                    "temporary stand-in for a missing module / wrapper that lets original code fit the interface",
                ],
                [
                    "Simulated vs wall time",
                    "experiments use only simulated time; router_wall_ms measures real HTTP time",
                ],
            ],
            [38 * mm, 132 * mm],
        )
    )
    st.append(Spacer(1, 6))
    st.append(
        P(
            "Prepared with AI assistance (Claude Code) under Krupesh's direction; contracts verified by the test "
            "suite in Krupesh/tests. Team review required before submission.",
            "small",
        )
    )
    doc.build(st, onFirstPage=on_page, onLaterPages=on_page)
    return OUT


if __name__ == "__main__":
    print(build())
