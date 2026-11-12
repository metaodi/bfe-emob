# 225469-BFE-Ladeinfrastruktur-Data

A [git scraper](https://simonwillison.net/2020/Oct/9/git-scraping/) for the Swiss Federal Office of Energy (BFE / SFOE) e-mobility data: the locations and the real-time status of public charging stations for electric vehicles in Switzerland.

A GitHub Actions workflow downloads the latest data every few minutes and commits it to this repository. The history of the data is therefore kept in the git history and can be extracted for analysis (e.g. how charging point availability changes over time).

## Data

The data is published by the BFE via «[ich tanke Strom](https://github.com/SFOE/ichtankestrom_Documentation)». In November 2026 the BFE switched to a new data infrastructure with an [OCPI 2.3.0](https://evroaming.org/ocpi/) based REST API; the old OICP files are discontinued.

### OCPI API (new)

Source: `https://api.emobility-prod.prometheon.bfe.admin.ch/ocpi/` (public, no authentication, see the [API documentation](https://github.com/SFOE/ichtankestrom_Documentation/blob/main/How%20to%20query%20ich%20tanke%20strom.md)). The files are JSON arrays with one object per line (for readable git diffs), sorted by `country_code`, `party_id` and `id`.

| File | Source | Content |
|------|--------|---------|
| `data/ocpi/locations.json` | `GET /locations` (all pages) | OCPI `Location` objects (charging sites) incl. their EVSEs and connectors |
| `data/ocpi/tariffs.json` | `GET /tariffs` (all pages) | OCPI `Tariff` objects, referenced by `connector.tariff_ids` (same `country_code` + `party_id`) |
| `data/ocpi/status_state.json` | – | Time of the last successful `/status` query (see below) |
| `data/ocpi/status.json` | `GET /status` + locations | Snapshot of the current status of every EVSE: `country_code`, `party_id`, `location_id`, `evse_uid`, `evse_id`, `status` (`AVAILABLE`, `CHARGING`, `OUTOFORDER`, `INOPERATIVE`, `UNKNOWN`, `REMOVED`, …), `last_updated` |

How the status snapshot is built: the `/status` endpoint only returns status values received since `date_from`, at most 5000 records and without `offset`, so a complete snapshot cannot be fetched in one request. The status contained in the locations is complete but not up to date. Therefore each run takes, per EVSE of the current locations, the newest value (by `last_updated`) of
1. the status in the location object,
2. the previous snapshot (`data/ocpi/status.json` in the repo),
3. the status values received since the last successful run from `/status`.

The time of the last successful run is stored in `data/ocpi/status_state.json` (server timestamp of the previous `/status` response). It is committed together with `status.json`, so if a run or its commit fails, the next run continues from the last committed state. The query starts 2 minutes earlier to catch records that become visible late; duplicates are harmless because the newest value per EVSE wins. Without a state file (first run), the largest window below the 5000 record limit is queried (starting with 7 days, halved until the response is below the limit), so the first snapshot is as up to date as possible.

EVSEs that are no longer part of any location are dropped from the snapshot.

### GeoJSON

| File | Source | Content |
|------|--------|---------|
| `data/ch.bfe.ladestellen-elektromobilitaet_de.json` | [`data/…_de.json`](https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/ch.bfe.ladestellen-elektromobilitaet_de.json) | GeoJSON `FeatureCollection` (EPSG:4326) with one point per charging point, its availability and a German HTML description (as used on map.geo.admin.ch). Remains available after the switch (also as `_fr`, `_it`, `_en`). |

### OICP files (legacy, discontinued)

These files were the main source until November 2026. They are still downloaded as long as they are available; afterwards, failures are only logged and the last version remains in the repository. Their history is kept in git.

| File | Source | Content |
|------|--------|---------|
| `data/ch.bfe.ladestellen-elektromobilitaet.json` | [`data/oicp/…`](https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/oicp/ch.bfe.ladestellen-elektromobilitaet.json) | Static master data of all charging points (EVSE) in [OICP](https://github.com/hubject/oicp) format (`EVSEData` → `EVSEDataRecord`) |
| `data/ch.bfe.ladestellen-elektromobilitaet-status.json` | [`status/oicp/…`](https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/status/oicp/ch.bfe.ladestellen-elektromobilitaet.json) | Real-time status per charging point in OICP format (`EVSEStatuses` → `EVSEStatusRecord` with `EvseID` and `EVSEStatus`) |

Note: neither the old files nor the new API provide historical data, only the current state. The history exists only in the git history of this repository.

## Automation

- **[`download.yml`](.github/workflows/download.yml)** runs every 8 minutes (and manually via `workflow_dispatch`), executes `download_data.py` and commits the files with the message `Latest data: <timestamp>` if anything changed. If one source fails, the other files are still committed and the run is marked as failed.
- **[`build-parquet.yml`](.github/workflows/build-parquet.yml)** runs on the 2nd of every month, builds the Parquet files of the previous month (see [Time series](#time-series-parquet)) and commits them to `parquet/`. It can be started manually with a `month` input (`YYYY-MM`) to backfill earlier months. It shares a concurrency group with `download.yml`, so no data download runs while the Parquet files are built.
- **[`check-scraper.yml`](.github/workflows/check-scraper.yml)** runs every 6 hours and checks whether `data/ocpi/status.json` and the GeoJSON file were committed in the last 2 hours. If not, it opens (or comments on) an issue labelled `scraper-health`; once the data is fresh again, the issue is closed automatically.

## Time series (Parquet)

The git history contains a snapshot of the status every few minutes, from two sources with different formats (OICP until November 2026, OCPI afterwards). `build_parquet.py` combines them into one continuous time series of **status intervals** per EVSE and writes one Parquet file per month to `parquet/`. The raw data in git is not changed; the formats are only normalised when building the Parquet files.

- `parquet/status_intervals_YYYY-MM.parquet` – one row per EVSE and period with unchanged status `[valid_from, valid_to)` (UTC, commit time of the snapshot). Intervals are cut at month boundaries, so every file is self-contained. Both sources are included (`source` = `oicp` / `ocpi`).
- `parquet/snapshots_YYYY-MM.parquet` – one row per snapshot (`source`, `observed_at`, `commit`, `evse_count`), to check coverage and gaps.

**Before the start of this repository (23 October 2025):** `parquet/*_2025-07.parquet` (28–30 July 2025) and the part of `parquet/*_2025-10.parquet` before 23 October 2025 (from 16 October) were built with `import_zip_snapshots.py` from the OICP snapshots archived as ZIP files in [ebp-group/225469-BFE-Ladeinfrastruktur-Data](https://github.com/ebp-group/225469-BFE-Ladeinfrastruktur-Data). For these snapshots, `commit` is `zip:<week folder>/<file>.zip` and `observed_at` is the download time from the ZIP's file name. That archive has gaps of weeks or months, so data from neighbouring snapshots is only carried across a month boundary if they are less than an hour apart. Don't rebuild these months with `build_parquet.py`, which would drop the ZIP data; rebuild them with:

```bash
uv run import_zip_snapshots.py --zip-dir ../225469-BFE-Ladeinfrastruktur-Data --month 2025-07 --month 2025-10 --ref main
```

| Column | Description |
|--------|-------------|
| `source` | `oicp` or `ocpi` |
| `evse_id` | EVSE ID, e.g. `CH*SUI*E…` – OICP `EvseID` and OCPI `evse_id` are identical for ~98 % of the EVSEs |
| `operator_id` | e.g. `CH*SUI` |
| `location_id`, `evse_uid` | OCPI only |
| `status` | common vocabulary, see below |
| `status_raw` | original status value of the source |
| `valid_from`, `valid_to` | start (inclusive) and end (exclusive) of the interval |
| `status_last_updated` | OCPI only: time of the status change reported by the operator |

Status mapping:

| `status` | OICP | OCPI |
|----------|------|------|
| `AVAILABLE` | `Available` | `AVAILABLE` |
| `OCCUPIED` | `Occupied`, `Reserved` | `CHARGING`, `BLOCKED`, `RESERVED` |
| `OUT_OF_SERVICE` | `OutOfService` | `OUTOFORDER`, `INOPERATIVE`, `PLANNED` |
| `UNKNOWN` | `Unknown` | `UNKNOWN` |
| `REMOVED` | `EvseNotFound` | `REMOVED` |

Notes:
- An EVSE missing from a snapshot ends its interval; it starts a new one when it reappears (gaps are visible in the data).
- The last interval of a month ends at the month boundary if a later snapshot exists, otherwise at the last snapshot.
- During the transition both sources overlap. Which source is used when is decided when reading (see the notebook), not when building.
- The coverage changes at the switch: OCPI does not contain all operators yet (Nov 2026: 5003 instead of ~20'000 EVSEs).

## Setup

The project uses Python 3.11 and [uv](https://docs.astral.sh/uv/):

```bash
uv sync          # installs runtime and dev dependencies (jupyter, pandas, duckdb, matplotlib)
```

## Usage

### Download the latest data

```bash
uv run download_data.py [--verbose]
```

### Extract the history from git

If you need the full history as a file, you can extract it from the git history (the repository must be cloned with full history, i.e. not shallow):

```bash
uv run extract_git_history.py -i data/ch.bfe.ladestellen-elektromobilitaet_de.json -o emob_history.jsonl --start-at 7d398e70718a3f519230aa35ee4dc6a75faf5be2
uv run extract_git_history.py -i data/ocpi/status.json -o status_history.jsonl
```

Note: this generates a large [JSON Lines](https://jsonlines.org/) file, where each line is one version of the file with an additional `_git_committed_datetime` field (JSON arrays such as `data/ocpi/*.json` are wrapped in a `data` field). `--start-at` is optional and skips all versions before the given commit.

### Build the Parquet files

The history of the month (plus a few days before it) must be available locally:

```bash
git fetch --shallow-since=2026-09-28 origin main     # or a full clone
uv run build_parquet.py --month 2026-10 --ref origin/main
uv run build_parquet.py --month 2026-10 --month 2026-11 --ref origin/main
```

Without `--month` the previous month is built. A month takes about 1–2 minutes (~1.2 million intervals, ~4 MB).

### Analyse the time series

The notebook [`analyse_timeseries.ipynb`](analyse_timeseries.ipynb) reads all Parquet files with [DuckDB](https://duckdb.org/) and combines the two sources to one series (OICP until a configurable `CUTOVER`, by default the last OICP snapshot; OCPI afterwards). It shows the coverage, the status distribution over time, occupancy by hour and weekday, statistics per operator, the duration of charging sessions, the history of a single EVSE and a comparison of OICP and OCPI during the overlap.

```bash
uv run jupyter notebook analyse_timeseries.ipynb
# other directory: PARQUET_DIR=/path/to/parquet uv run jupyter notebook
```

Ad-hoc queries also work directly with DuckDB:

```sql
SELECT status, count(*) FROM 'parquet/status_intervals_*.parquet' GROUP BY ALL;
```

### Legacy notebook

The notebook [`check_data.ipynb`](check_data.ipynb) walks through all versions of the (legacy OICP) status file, flattens them into records (`Timestamp`, `OperatorID`, `OperatorName`, `EvseID`, `EVSEStatus`), caches them as pickle files in `data_cache/` and combines them into one pandas DataFrame:

```bash
uv run jupyter notebook check_data.ipynb
```

## Project structure

```
download_data.py          # downloads GeoJSON, OCPI API and legacy OICP data into data/
extract_git_history.py    # exports all git versions of a file as JSON Lines
build_parquet.py          # builds the monthly Parquet time series from the git history
import_zip_snapshots.py   # backfills Parquet months from an archive of ZIP snapshots (2025-07, 2025-10)
analyse_timeseries.ipynb  # analysis of the Parquet files with DuckDB
check_data.ipynb          # legacy: analysis of the OICP status history with pandas
lib/download.py           # HTTP helpers (requests with retry/backoff)
lib/ocpi.py               # OCPI API client (pagination, status snapshot)
lib/timeseries.py         # reads both status sources from git and builds status intervals
lib/git_history.py        # iterates over all versions of a file on branch main (GitPython)
data/                     # scraped data (updated automatically)
data/ocpi/                # data from the OCPI API
parquet/                  # monthly Parquet files (built automatically)
data_cache/               # local cache for the notebook (ignored by git)
```

## License

Code: [MIT](LICENSE). The data is provided by the Swiss Federal Office of Energy (BFE) via [opendata.swiss](https://opendata.swiss) / geo.admin.ch; see their terms of use.
