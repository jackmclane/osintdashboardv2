"""SEC EDGAR full-text search collector — free, no key, capital-markets signal.

Uses the same JSON API that backs the EDGAR full-text search UI
(https://www.sec.gov/edgar/search/). Verified live endpoint/shape:

  GET https://efts.sec.gov/LATEST/search-index
      ?q="phrase"&forms=8-K&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD

SEC's fair-access policy requires a descriptive User-Agent identifying you and
a real contact (https://www.sec.gov/os/webmaster-faq#developers) — generic or
missing User-Agents get blocked. Set `edgar.user_agent` in config.yaml to a
real value before enabling this.

Full-text search is a phrase index, not a firehose — there's no "give me
every 8-K" query. Configure `edgar.keywords` with phrases you actually care
about (material events, sanctions exposure, going-concern language, etc.);
each keyword becomes one query, results merge and dedupe like every other
source.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from ..models import Event
from .base import Source

SEARCH_API = "https://efts.sec.gov/LATEST/search-index"


def _filing_url(source: dict, hit_id: str) -> str | None:
    """Build the canonical Archives URL from a search hit. Falls back to the
    company's filing list if any piece is missing rather than guessing."""
    ciks = source.get("ciks") or []
    adsh = source.get("adsh")
    filename = hit_id.split(":", 1)[1] if ":" in hit_id else None
    if ciks and adsh and filename:
        cik_num = str(int(ciks[0]))  # strips leading zeros, as Archives URLs expect
        accession_nodash = adsh.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_nodash}/{filename}"
    if ciks:
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ciks[0]}&type=&dateb=&owner=include&count=40"
    return None


def hit_to_event(hit: dict, keyword: str) -> Event | None:
    """Pure parser (unit-testable without network)."""
    src = hit.get("_source", {})
    display_names = src.get("display_names") or []
    company = display_names[0] if display_names else "Unknown filer"
    form = src.get("form") or (src.get("root_forms") or ["?"])[0]
    file_date = src.get("file_date")
    url = _filing_url(src, hit.get("_id", ""))
    if not url:
        return None
    published_at = f"{file_date}T00:00:00+00:00" if file_date else None
    return Event(
        source="SEC EDGAR",
        source_type="filing",
        title=f"{form} — {company}",
        url=url,
        summary=f"Full-text match: “{keyword}”",
        published_at=published_at,
        region="",
        topics="markets, filing",
        raw="",
    )


class EDGARSource(Source):
    source_type = "filing"

    def __init__(
        self,
        keywords: list[str],
        forms: list[str] | None = None,
        user_agent: str = "",
        lookback_hours: int = 24,
        max_records: int = 10,
    ):
        self.keywords = keywords or []
        self.forms = forms or ["8-K"]
        self.user_agent = user_agent
        self.lookback_hours = lookback_hours
        self.max_records = max_records

    def collect(self) -> list[Event]:
        if not self.user_agent or "@" not in self.user_agent:
            print("  [edgar] SKIPPED — set edgar.user_agent to a real contact "
                  "in config.yaml (SEC blocks generic User-Agents).")
            return []
        if not self.keywords:
            print("  [edgar] no edgar.keywords configured. Skipping.")
            return []

        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=max(self.lookback_hours, 24))).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        headers = {"User-Agent": self.user_agent}

        seen_ids: set[str] = set()
        events: list[Event] = []
        for kw in self.keywords:
            params = {
                "q": f'"{kw}"',
                "forms": ",".join(self.forms),
                "startdt": start,
                "enddt": end,
            }
            try:
                resp = requests.get(SEARCH_API, params=params, headers=headers, timeout=30)
                resp.raise_for_status()
                hits = resp.json().get("hits", {}).get("hits", [])
            except Exception as exc:  # noqa: BLE001 — one bad keyword != run dead
                print(f"  [edgar] FAILED '{kw}': {exc}")
                continue
            got = 0
            for hit in hits[: self.max_records]:
                ev = hit_to_event(hit, kw)
                if ev and ev.id not in seen_ids:
                    seen_ids.add(ev.id)
                    events.append(ev)
                    got += 1
            print(f"  [edgar] '{kw}': {got} filings")
        return events
