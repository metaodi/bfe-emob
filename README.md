# bfe-emob

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
| `data/ocpi/status.json` | `GET /status` + locations | Snapshot of the current status of every EVSE: `country_code`, `party_id`, `location_id`, `evse_uid`, `evse_id`, `status` (`AVAILABLE`, `CHARGING`, `OUTOFORDER`, `INOPERATIVE`, `UNKNOWN`, `REMOVED`, …), `last_updated` |

How the status snapshot is built: the `/status` endpoint only returns status values received since `date_from`, at most 5000 records and without `offset`, so a complete snapshot cannot be fetched in one request. The status contained in the locations is complete but not up to date. Therefore each run takes, per EVSE of the current locations, the newest value (by `last_updated`) of
1. the status in the location object,
2. the previous snapshot (`data/ocpi/status.json` in the repo),
3. the status values received in the last 2 hours from `/status`.

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
- **[`check-scraper.yml`](.github/workflows/check-scraper.yml)** runs every 6 hours and checks whether `data/ocpi/status.json` and the GeoJSON file were committed in the last 2 hours. If not, it opens (or comments on) an issue labelled `scraper-health`; once the data is fresh again, the issue is closed automatically.

## Setup

The project uses Python 3.11 and [uv](https://docs.astral.sh/uv/):

```bash
uv sync          # installs runtime and dev dependencies (jupyter, pandas)
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

### Analyse the status history

The notebook [`check_data.ipynb`](check_data.ipynb) walks through all versions of the (legacy OICP) status file, flattens them into records (`Timestamp`, `OperatorID`, `OperatorName`, `EvseID`, `EVSEStatus`), caches them as pickle files in `data_cache/` and combines them into one pandas DataFrame:

```bash
uv run jupyter notebook check_data.ipynb
```

## Project structure

```
download_data.py          # downloads GeoJSON, OCPI API and legacy OICP data into data/
extract_git_history.py    # exports all git versions of a file as JSON Lines
check_data.ipynb          # analysis of the status history with pandas
lib/download.py           # HTTP helpers (requests with retry/backoff)
lib/ocpi.py               # OCPI API client (pagination, status snapshot)
lib/git_history.py        # iterates over all versions of a file on branch main (GitPython)
data/                     # scraped data (updated automatically)
data/ocpi/                # data from the OCPI API
data_cache/               # local cache for the notebook (ignored by git)
```

## License

Code: [MIT](LICENSE). The data is provided by the Swiss Federal Office of Energy (BFE) via [opendata.swiss](https://opendata.swiss) / geo.admin.ch; see their terms of use.
