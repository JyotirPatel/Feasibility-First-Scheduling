"""Compare a saved source.json across Windows/Linux without false CRLF changes."""

import argparse
import hashlib
import json
from pathlib import Path


def compare(saved, root):
    rows = []
    for name, expected in saved["source_sha256"].items():
        normalized = name.replace("\\", "/")
        p = root / normalized
        if not p.exists():
            status = "missing"
        else:
            content = p.read_bytes()
            lf = content.replace(b"\r\n", b"\n")
            digest = lambda b: hashlib.sha256(b).hexdigest()
            if digest(content) == expected:
                status = "exact"
            elif expected in [digest(lf), digest(lf.replace(b"\n", b"\r\n"))]:
                status = "line_endings_only"
            else:
                status = "content_changed"
        rows.append({"path": normalized, "status": status})
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--output")
    a = ap.parse_args()
    result = compare(
        json.loads(Path(a.source).read_text(encoding="utf-8")),
        Path(__file__).resolve().parents[2],
    )
    text = json.dumps(result, indent=2)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
    print(text)
