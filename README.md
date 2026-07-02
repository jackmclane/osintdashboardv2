# 🛰️ OSINT Monitor

A personal, near-zero-cost intelligence aggregator for one operator. It pulls
open sources into one schema, stores them in SQLite, detects cross-source
**signals**, writes a once-a-day **brief**, and shows everything in a Streamlit
dashboard — all runnable free on **GitHub Actions** + **Streamlit Cloud**.

> **X is intentionally not automated.** Automated X scraping is noisy and now
> expensive. This tool does the triage and tells you *where to look*; you open X
> and bring the human read on whatever the signals surface. That division of
> labour is the whole design.

## What it does

| Source | Cost | Notes |
|---|---|---|
| **GDELT** DOC 2.0 | free, no key | global news backbone |
| **RSS / Atom** | free | international press + government releases |
| **Prediction markets** | free, no key | Polymarket + Manifold (Kalshi/Metaculus are extension points) |
| **SEC EDGAR** full-text search | free, no key | 8-K/13D filings matching phrases you configure |
| **Sanctions / denied-party list** | free, no key | diffs the Commerce/State/Treasury consolidated screening list; flags new additions only |
| **AIS** (AISStream.io) | free key | optional; live vessel positions at chokepoints |
| **ADS-B** (OpenSky Network) | free (account recommended) | optional; live aircraft positions at the same chokepoints |
| **LLM brief** | ~cents/day | optional; one call/day; free digest fallback if no key |

Everything except the optional daily LLM call is **$0**. Well inside sub-$50.

## Architecture (4 thin layers)

```
osint/
  models.py        # the common Event schema + dedup id
  db.py            # SQLite: events, market_history, signals, ais/aircraft
                    # positions, sanctions_seen, starred
  normalize.py     # coarse free keyword tagging (region/topic) + title clustering
  collect.py       # orchestrator: sources -> store -> record markets -> signals
  signals.py       # market swings + news spikes + cross-source correlation
  sanctions.py     # diff-only: flags NEW additions to the consolidated
                    # screening list (not part of the 30-min loop — see below)
  brief.py         # once-a-day synthesis (1 LLM call) + free digest fallback
  sources/
    base.py        # Source interface
    rss.py         # RSS / Atom
    gdelt.py       # GDELT DOC 2.0
    markets.py     # Polymarket + Manifold (pure, testable parsers)
    edgar.py       # SEC EDGAR full-text search (8-K/13D etc.)
dashboard/app.py   # Streamlit UI: Signals strip, topic tabs, Markets, Filings,
                    # Starred, Brief — clustering + bookmarking built in
scripts/
  run_once.py         # frequent collector (no LLM, free)   -> every 30 min
  make_brief.py        # daily brief (one LLM call)          -> once a day
  collect_ais.py       # optional bounded AIS stream collector
  collect_adsb.py      # optional ADS-B snapshot (OpenSky)
  collect_sanctions.py # optional sanctions-list diff (low frequency)
config.yaml        # feeds, queries, market keywords, thresholds — edit THIS
.github/workflows/ # collect.yml (30m) · brief.yml (daily) · ais.yml (optional)
                    # · adsb.yml (optional) · sanctions.yml (optional, 6h)
```

The flow: **collect → normalize → store → detect signals → (daily) synthesize
→ display.** New sources are just new files in `sources/` returning `Event`s.
EDGAR follows that pattern and runs on the same 30-min cadence as RSS/GDELT.
AIS, ADS-B, and the sanctions diff are standalone bounded scripts on their own
schedules — see the "Free scheduled compute" note below on why.

## Run it locally (5 minutes)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # optional: add keys for the LLM brief / AIS

python scripts/run_once.py      # collect once -> data/osint.db
python scripts/make_brief.py    # (optional) build a brief
streamlit run dashboard/app.py  # open the dashboard
```

First run creates `data/osint.db`. Re-run the collector anytime; duplicates are
ignored automatically. No keys? Everything still works — the brief just uses the
free grouped digest.

## Deploy free

1. Push this folder to a new GitHub repo.
2. Repo → Settings → Actions → General → **Read and write permissions** (lets
   the jobs commit the updated DB back).
3. **Collection:** `collect.yml` runs every 30 min (GDELT + RSS + markets +
   signals) and commits `data/osint.db`.
4. **Brief:** `brief.yml` runs daily. Add repo secret **`ANTHROPIC_API_KEY`**
   (Settings → Secrets → Actions) for a synthesized brief; without it you get
   the free digest.
5. **Dashboard:** create a free app at share.streamlit.io pointing at
   `dashboard/app.py`. It reads the committed DB + latest brief.

> The DB is committed to the repo so the free Actions writer and the free
> Streamlit reader can share it — the pragmatic glue for a solo setup. If the
> repo ever gets heavy, move storage to a free Postgres tier (Supabase/Neon);
> only `db.py` changes.

## Signals — the point of the tool

Three cheap detectors run every collection (no LLM):

- **market_swing** — a tracked market's probability moved ≥ threshold (default
  10 points) over a window (default 24h). A sharp move often *precedes* the news.
- **news_spike** — a topic's event volume jumped ≥ ratio (default 2.5×) vs the
  prior window and cleared a floor. Something is developing on that theme.
- **correlated** — a `market_swing` and a `news_spike` land on the same topic
  in the same run. Either alone is a heuristic; both firing together on the
  same theme is a materially stronger tell, so it gets its own higher-priority
  signal instead of being left for you to notice.

A fourth, **sanctions_listing**, fires separately from `scripts/collect_sanctions.py`
when the consolidated screening list gets a genuinely new entry (see below).

Signals appear at the top of the dashboard and in the brief's "Check manually on
X" section — your cue to go get the human read. Tune all thresholds in
`config.yaml` under `signals:`.

## Maritime (AIS) — optional

1. Free key at https://aisstream.io → put it in `.env` (and as a repo secret for
   `ais.yml`).
2. Set `ais.enabled: true` in `config.yaml`; edit the chokepoint bounding boxes.
3. `python scripts/collect_ais.py` (bounded run) or let `ais.yml` snapshot on a
   schedule.

**Read this caveat:** AISStream is terrestrial AIS. Coverage in open ocean is
patchy, so a low vessel count mid-strait is a **coverage gap, not an empty sea.**
Never read absence as an event.

Vessel positions plot on a map in the Maritime tab alongside aircraft (see
below) — a quick visual read of what's transiting each chokepoint right now.

## Aircraft (ADS-B) — optional

Same idea as AIS, aviation instead of maritime, using the free [OpenSky
Network](https://opensky-network.org) REST API.

1. (Recommended) free account at opensky-network.org → put
   `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` in `.env` (and as repo
   secrets for `adsb.yml`). Anonymous access works but is heavily
   rate-limited.
2. Set `adsb.enabled: true` in `config.yaml`. Leave `adsb.zones` empty to
   reuse the same chokepoints as `ais.zones`, or define your own.
3. `python scripts/collect_adsb.py`

**Caveat:** OpenSky is known to throttle or block requests from cloud/
datacenter IP ranges — including GitHub Actions runners — more aggressively
than residential connections, even with credentials. If Actions comes back
empty, run this one locally instead.

## SEC filings — optional

Free-text search over SEC EDGAR (8-K, 13D, etc.) via the same API that backs
the official full-text search UI — no key required, but SEC's fair-access
policy requires a real, descriptive User-Agent.

1. Set `edgar.user_agent` in `config.yaml` to something like
   `"OSINT Monitor you@example.com"` — a real contact, not a placeholder.
2. Set `edgar.enabled: true` and adjust `edgar.forms` / `edgar.keywords` to
   phrases you actually care about (full-text search is a phrase index, not
   a firehose — there's no "give me every 8-K" query).
3. Runs automatically on the existing 30-min `collect.yml` schedule, same as
   RSS/GDELT. Shows up in its own **Filings** tab.

## Sanctions / denied-party list diff — optional

Flags **new** additions to the Commerce/State/Treasury consolidated
screening list (OFAC SDN, BIS Entity List, State Dept debarred list, etc.) —
free, no key, via the [trade.gov downloadable
mirror](https://www.trade.gov/consolidated-screening-list). The file itself
is multi-MB and only updates once a day, so this deliberately does **not**
run on the 30-min loop.

1. Set `sanctions.enabled: true` in `config.yaml`.
2. `python scripts/collect_sanctions.py`, or let `sanctions.yml` run it a
   few times a day.

The first run silently seeds a baseline (the list has tens of thousands of
entries — flagging all of them as "new" on activation would be pure noise).
Real diffs start showing up from the second run onward, as new Events tagged
`policy, sanctions` (visible in the Policy tab) plus a `sanctions_listing`
signal.

## Make it yours

- Edit `config.yaml`: add the RSS + government feeds you actually track, tune the
  GDELT queries, and set the market `keywords` to your regions/topics.
- Starter feeds are examples — **verify each URL resolves.**
- Add Kalshi/Metaculus by writing a parser alongside `markets.py` (Kalshi needs
  RSA-key auth; Metaculus exposes community forecasts via its API).

## Cost control

- The frequent collector makes **zero** LLM calls — it's free forever.
- The brief is **one** call per day. Default model is Haiku (~a fraction of a
  cent/day). Bump to `claude-sonnet-4-6` in `config.yaml` for richer synthesis.
- No paid data sources. X is manual on purpose.
- Story clustering, starring, the AIS/ADS-B map, and cross-source signal
  correlation are all pure code against data you already collected — zero
  marginal cost.
- **If your repo is private**, GitHub Actions gives you 2,000 free
  minutes/month (public repos get unlimited). `collect.yml` at 30-min cadence
  already uses a meaningful chunk of that; turning on `ais.yml` and `adsb.yml`
  at the same 30-min cadence adds more. `sanctions.yml` is deliberately
  low-frequency (every 6h) since the source data only updates once a day.
  Keep an eye on Settings → Actions → Usage if you enable everything on a
  private repo — dial cadences down (or make the repo public) before you hit
  the cap.

## Ethics & accuracy

Respect each source's ToS and rate limits, attribute everything, and don't
redistribute raw scraped data. Be skeptical of single-source claims — the brief
is told to flag them. And mind the AIS caveat above.

## Verified

The data logic (storage, dedup, tagging, RSS parsing, market parsers, both
signal detectors, the brief fallback, and AIS parsing/storage) ships with a
smoke test that passes end-to-end without any network access. Live API calls
run on your machine / in Actions, which have open internet.
