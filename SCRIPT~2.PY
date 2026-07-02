"""Optional sanctions-diff collector — flags NEW additions to the
Commerce/State/Treasury consolidated screening list (OFAC SDN, BIS Entity
List, State Dept debarred list, etc).

Free, no key. Deliberately NOT part of the 30-min collect.py loop — the
source file is multi-MB and only updates once a day, so this runs on its own
low-frequency schedule instead (see .github/workflows/sanctions.yml — default
every 6 hours, which is already more often than the source updates).

Run:  python scripts/collect_sanctions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from osint import db, sanctions  # noqa: E402
from osint.collect import load_config  # noqa: E402


def main() -> int:
    cfg = load_config()
    sc = cfg.get("sanctions", {})
    if not sc.get("enabled", False):
        print("[sanctions] disabled in config.yaml (sanctions.enabled: false). "
              "Skipping.")
        return 0

    conn = db.connect()
    db.init_db(conn)
    sanctions.run(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
