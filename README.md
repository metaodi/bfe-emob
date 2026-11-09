# bfe-emob

A [git scraper](https://simonwillison.net/2020/Oct/9/git-scraping/) for the Swiss Federal Office of Energy (BFE / SFOE) e-mobility data: the locations and the real-time status of public charging stations for electric vehicles in Switzerland.

A GitHub Actions workflow downloads the latest data every few minutes and commits it to this repository. The history of the data is therefore kept in the git history and can be extracted for analysis (e.g. how charging point availability changes over time).

## Data

The data is published by the BFE on [data.geo.admin.ch](https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/) (see also the [DIEMO documentation](https://github.com/SFOE/DIEMO-Documentation)). The following files are downloaded to the `data` directory:

| File | Source | Content |
|------|--------|---------|
| `data/ch.bfe.ladestellen-elektromobilitaet.json` | [`data/oicp/…`](https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/oicp/ch.bfe.ladestellen-elektromobilitaet.json) | Static master data of all charging points (EVSE) in [OICP](https://github.com/hubject/oicp) format (`EVSEData` → `EVSEDataRecord`): address, operator, plugs, power, authentication modes, … |
| `data/ch.bfe.ladestellen-elektromobilitaet-status.json` | [`status/oicp/…`](https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/status/oicp/ch.bfe.ladestellen-elektromobilitaet.json) | Real-time status per charging point in OICP format (`EVSEStatuses` → `EVSEStatusRecord` with `EvseID` and `EVSEStatus`, e.g. `Available`, `Occupied`, `OutOfService`, `Unknown`) |
| `data/ch.bfe.ladestellen-elektromobilitaet_de.json` | [`data/…_de.json`](https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/ch.bfe.ladestellen-elektromobilitaet_de.json) | GeoJSON `FeatureCollection` (EPSG:4326) with one point per charging point, its availability and a German HTML description (as used on map.geo.admin.ch) |

## Automation

- **[`download.yml`](.github/workflows/download.yml)** runs every 8 minutes (and manually via `workflow_dispatch`), executes `download_data.py` and commits the files with the message `Latest data: <timestamp>` if anything changed.
- **[`check-scraper.yml`](.github/workflows/check-scraper.yml)** runs every 6 hours and checks whether the status and GeoJSON files were committed in the last 2 hours. If not, it opens (or comments on) an issue labelled `scraper-health`; once the data is fresh again, the issue is closed automatically.

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
```

Note: this generates a large [JSON Lines](https://jsonlines.org/) `emob_history.jsonl` file, where each line is one version of the file with an additional `_git_committed_datetime` field. `--start-at` is optional and skips all versions before the given commit.

### Analyse the status history

The notebook [`check_data.ipynb`](check_data.ipynb) walks through all versions of the status file, flattens them into records (`Timestamp`, `OperatorID`, `OperatorName`, `EvseID`, `EVSEStatus`), caches them as pickle files in `data_cache/` and combines them into one pandas DataFrame:

```bash
uv run jupyter notebook check_data.ipynb
```

## Project structure

```
download_data.py          # downloads the BFE JSON files into data/
extract_git_history.py    # exports all git versions of a file as JSON Lines
check_data.ipynb          # analysis of the status history with pandas
lib/download.py           # HTTP helpers (requests with retry/backoff)
lib/git_history.py        # iterates over all versions of a file on branch main (GitPython)
data/                     # scraped data (updated automatically)
data_cache/               # local cache for the notebook (ignored by git)
```

## License

Code: [MIT](LICENSE). The data is provided by the Swiss Federal Office of Energy (BFE) via [opendata.swiss](https://opendata.swiss) / geo.admin.ch; see their terms of use.
