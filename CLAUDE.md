# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A git scraper for the Swiss BFE e-mobility open data («ich tanke Strom»: EV charging stations, tariffs and their real-time status). A GitHub Actions cron job (`.github/workflows/download.yml`, every 8 min) runs `download_data.py` and commits the JSON files in `data/`. Since November 2026 the main source is the OCPI 2.3.0 REST API (`https://api.emobility-prod.prometheon.bfe.admin.ch/ocpi/`, public, docs: https://github.com/SFOE/ichtankestrom_Documentation); the old OICP files are discontinued and only downloaded best-effort. The git history *is* the dataset; `build_parquet.py` turns it into monthly Parquet files (`parquet/`) of status intervals, which `analyse_timeseries.ipynb` analyses with DuckDB.

## Commands

```bash
uv sync                                   # install deps (Python 3.11, see .python-version)
uv run download_data.py --verbose         # fetch the latest data into data/
uv run extract_git_history.py -i data/<file>.json -o emob_history.jsonl [--start-at <sha>]
uv run build_parquet.py --month 2026-10 --ref origin/main   # needs that month's history locally (git fetch --shallow-since=...)
uv run jupyter notebook analyse_timeseries.ipynb             # DuckDB analysis of parquet/ (PARQUET_DIR env var to override)
```

There are no tests and no linter configured.

## Layout

- `download_data.py` – docopt CLI. Downloads the GeoJSON (required), the legacy OICP files (failures only logged) and the OCPI data via `lib/ocpi.py`. Each source fails independently; the script exits 1 if a required source failed, and the workflow still commits partial results. URLs containing `status` get a `-status` suffix so the two OICP files don't collide.
- `lib/ocpi.py` – OCPI client. `fetch_all()` follows the `Link: rel="next"` header and checks `X-Total-Count`; `build_status_snapshot()` merges, per EVSE of the current locations, the newest `last_updated` of (location EVSE status, previous `data/ocpi/status.json`, `/status` since the last successful run). The last run is the server `timestamp` of the previous `/status` response, stored in `data/ocpi/status_state.json` and committed with `status.json` (only written after the snapshot), queried with 2 min overlap; without state, the window starts at 7 days and is halved until the response is below the 5000 limit (a response at the limit is an undefined subset). Output files are JSON arrays with one object per line, sorted by CPO identity.
- `lib/download.py` – `requests` session with `Retry` (5 retries, backoff 2, retries also on 403/429/5xx) and a custom User-Agent.
- `lib/git_history.py` – `iterate_file_versions(path)` yields `(index, committed_datetime, sha, bytes)` for every commit touching the file, oldest first. The ref is hard-coded to `main`; the `start_commit` parameter is unused.
- `lib/timeseries.py` – reads every committed version of the OICP and OCPI status files (`git log` + one `git cat-file --batch` process), normalises the status (`STATUS_MAP`) and compresses the snapshots to intervals per EVSE (`build_intervals`). Intervals are cut at month boundaries; an EVSE missing from a snapshot closes its interval. Both sources are kept (`source` column); choosing between them during the overlap is done at read time.
- `build_parquet.py` – CLI around `lib/timeseries.py`; writes `parquet/status_intervals_YYYY-MM.parquet` and `parquet/snapshots_YYYY-MM.parquet` (zstd). Default month: previous month.
- `analyse_timeseries.ipynb` – DuckDB views `intervals_raw`, `snapshots` and `intervals` (combined series, OICP before `CUTOVER`, OCPI after). Generated from code cells only; keep outputs cleared when committing.
- `extract_git_history.py` – writes each file version as one JSON Lines record plus `_git_committed_datetime` (arrays are wrapped as `{"data": [...]}`).
- `check_data.ipynb` – legacy, flattens the legacy OICP status file history into records and caches them as `data_cache/*.pks` pickles (git-ignored).
- `.github/workflows/build-parquet.yml` – monthly (2nd, 03:17 UTC) or manual with `month` input: shallow-fetches the month's history, runs `build_parquet.py`, commits `parquet/` and pushes with `pull --rebase` retries (the download workflow pushes concurrently).
- `.github/workflows/check-scraper.yml` – every 6 h, opens/closes a `scraper-health` issue if `data/ocpi/status.json` or the GeoJSON file has not been committed for 2 h.

## Data files (`data/`)

- `ocpi/locations.json` – OCPI `Location` objects incl. `evses[].connectors[]`. Objects are identified by `country_code` + `party_id` + `id` (IDs alone are not unique).
- `ocpi/tariffs.json` – OCPI `Tariff` objects; `connector.tariff_ids` refer to `Tariff.id` of the same `country_code` + `party_id`.
- `ocpi/status_state.json` – `{"last_status_fetch": ...}`, state for the incremental `/status` query.
- `ocpi/status.json` – status snapshot: `country_code`, `party_id`, `location_id`, `evse_uid`, `evse_id`, `status`, `last_updated`.
- `ch.bfe.ladestellen-elektromobilitaet_de.json` (~27 MB) – GeoJSON (still provided after the switch) FeatureCollection, `id`/`location_id` = EVSE ID, `properties.Availability`, German HTML `description`.

Legacy OICP (no longer updated after the switch):

- `ch.bfe.ladestellen-elektromobilitaet.json` (~29 MB) – OICP master data, `EVSEData[].EVSEDataRecord[]`.
- `ch.bfe.ladestellen-elektromobilitaet-status.json` (~1.3 MB) – OICP status, `EVSEStatuses[]` with `OperatorID`, `OperatorName`, `EVSEStatusRecord[]{EvseID, EVSEStatus}`.

## Conventions and pitfalls

- OCPI API quirks (verified Nov 2026): `/status` has no `offset` (HTTP 400) and max `limit=5000`, it stores only the latest value per EVSE; `date_to` is ignored on all endpoints; the EVSE status embedded in `/locations` lags behind `/status`. No endpoint provides historical data. Rate limit ~60 req/min (429 + `Retry-After`, handled by urllib3 `Retry`).
- DuckDB 2.x: relations have no `fetchone()`/`fetchall()` any more; use `con.execute(sql, params).fetchone()` (and `.df()` for DataFrames).
- `parquet/` is generated: rebuild a month with `build_parquet.py` instead of editing files. Changing `STATUS_MAP` or the interval logic requires rebuilding all months.
- **Never edit files in `data/` by hand** and don't commit them from a dev branch – they are owned by the automated workflow and change every few minutes. Expect frequent `Latest data: …` commits on `main`; rebase rather than merge when syncing.
- The files are large: don't `cat`/`Read` them whole; use `head -c`, `jq`, or Python to inspect.
- History extraction needs a full (non-shallow) clone of `main` (`git fetch --unshallow`); a shallow clone silently yields only recent versions.
- The dependency is declared as `docopts` in `pyproject.toml` but imported as `docopt`; keep `uv.lock` in sync (`uv lock`) when changing dependencies, since CI runs `uv sync --locked`.
- Keep the sources in `download_data.py` and the `FILES` list in `check-scraper.yml` consistent when adding or renaming data files.
- Commit messages for code changes: short, imperative, English.
