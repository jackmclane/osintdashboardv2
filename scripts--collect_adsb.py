"""Optional ADS-B collector — live aircraft positions for the same watched
chokepoints as the AIS collector. Aviation counterpart to collect_ais.py:
same idea (who's transiting a chokepoint right now), different transport.

Uses OpenSky Network's free REST API (https://opensky-network.org):

  GET https://opensky-network.org/api/states/all?lamin=&lomin=&lamax=&lomax=

Anonymous access works but is heavily rate-limited and OpenSky is known to
throttle/block requests from cloud & datacenter IP ranges (which includes
GitHub Actions runners) more aggressively than residential ones. A free
registered account raises the limit — set OPENSKY_CLIENT_ID /
OPENSKY_CLIENT_SECRET (OAuth2 client-credentials, see
https://opensky-network.org/apidoc/rest.html) in .env for a better shot at
reliable results. If you see empty results from GitHub Actions even with
credentials, run this script locally/on a home connection instead — that's a
known OpenSky-side limitation, not a bug here.

Setup:
  1. (Optional but recommended) free account at https://opensky-network.org
     -> put OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET in .env
  2. Set `adsb.enabled: true` in config.yaml (zones default to the same
     chokepoints as `ais.zones`)
  3. Run:  python scripts/collect_adsb.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from osint import db  # noqa: E402
from osint.collect import load_config  # noqa: E402

STATES_URL = "https://opensky-network.org/api/states/all"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)

# OpenSky state vector field order — fixed by their API, not our choice.
# https://opensky-network.org/apidoc/rest.html#response
IDX = {
    "icao24": 0, "callsign": 1, "longitude": 5, "latitude": 6,
    "baro_altitude": 7, "velocity": 9, "true_track": 10,
}


def state_to_row(state: list, zone_name: str) -> dict | None:
    """Pure parser (unit-testable without network)."""
    try:
        lat, lon = state[IDX["latitude"]], state[IDX["longitude"]]
    except IndexError:
        return None
    if lat is None or lon is None:
        return None
    icao24 = (state[IDX["icao24"]] or "").strip()
    if not icao24:
        return None
    callsign = (state[IDX["callsign"]] or "").strip() or None
    return {
        "icao24": icao24,
        "callsign": callsign,
        "zone": zone_name,
        "lat": lat,
        "lon": lon,
        "velocity": state[IDX["velocity"]] if len(state) > IDX["velocity"] else None,
        "heading": state[IDX["true_track"]] if len(state) > IDX["true_track"] else None,
        "baro_alt": state[IDX["baro_altitude"]] if len(state) > IDX["baro_altitude"] else None,
    }


def _get_token(client_id: str, client_secret: str) -> str | None:
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as exc:  # noqa: BLE001
        print(f"[adsb] OAuth2 token request failed ({exc}); falling back to anonymous")
        return None


def collect_zone(zone: dict, headers: dict) -> list[dict]:
    (lat_min, lon_min), (lat_max, lon_max) = zone["bbox"]
    params = {"lamin": lat_min, "lomin": lon_min, "lamax": lat_max, "lomax": lon_max}
    try:
        resp = requests.get(STATES_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        states = resp.json().get("states") or []
    except Exception as exc:  # noqa: BLE001 — one zone failing != run dead
        print(f"  [adsb] FAILED zone '{zone['name']}': {exc}")
        return []
    rows = [state_to_row(s, zone["name"]) for s in states]
    return [r for r in rows if r]


def main() -> int:
    cfg = load_config()
    ac = cfg.get("adsb", {})
    if not ac.get("enabled", False):
        print("[adsb] disabled in config.yaml (adsb.enabled: false). Skipping.")
        return 0

    zones = ac.get("zones") or cfg.get("ais", {}).get("zones", [])
    if not zones:
        print("[adsb] no zones configured under adsb.zones (or ais.zones). Skipping.")
        return 0

    headers = {"User-Agent": "personal-osint/1.0"}
    client_id = os.environ.get("OPENSKY_CLIENT_ID")
    client_secret = os.environ.get("OPENSKY_CLIENT_SECRET")
    if client_id and client_secret:
        token = _get_token(client_id, client_secret)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    else:
        print("[adsb] no OPENSKY_CLIENT_ID/SECRET set — using anonymous access "
              "(low rate limit, may be blocked from cloud IPs).")

    all_rows: list[dict] = []
    for zone in zones:
        rows = collect_zone(zone, headers)
        print(f"  [adsb] {zone['name']}: {len(rows)} aircraft")
        all_rows.extend(rows)

    conn = db.connect()
    db.init_db(conn)
    n = db.upsert_aircraft_positions(conn, all_rows)
    conn.close()
    print(f"[adsb] stored {n} aircraft positions across {len(zones)} zone(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
