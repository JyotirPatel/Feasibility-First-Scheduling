"""Make Krupesh/ importable (api_contract, router_service, decision_log, integration)."""

import sys
from pathlib import Path

KRUPESH = Path(__file__).resolve().parents[1]
if str(KRUPESH) not in sys.path:
    sys.path.insert(0, str(KRUPESH))
