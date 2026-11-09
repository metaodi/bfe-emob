# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A git scraper for the Swiss BFE e-mobility open data (EV charging stations and their real-time status). A GitHub Actions cron job (`.github/workflows/download.yml`, every 8 min) runs `download_data.py` and commits the JSON files in `data/`. The git history *is* the dataset; `extract_git_history.py` and `check_data.ipynb` read it back out.

## Commands

```bash
uv sync                                   # install deps (Python 3.11, see .python-version)
uv run download_data.py --verbose         # fetch the latest data into data/
uv run extract_git_history.py -i data/<file>.json -o emob_history.jsonl [--start-at <sha>]
uv run jupyter notebook check_data.ipynb  # status-history analysis (pandas)
```

There are no tests and no linter configured.

## Layout

- `download_data.py` – docopt CLI; list of source URLs → `data/<basename>.json`. URLs containing `status` get a `-status` suffix so the two OICP files don't collide.
- `lib/download.py` – `requests` session with `Retry` (5 retries, backoff 2, retries also on 403/429/5xx) and a custom User-Agent.
- `lib/git_history.py` – `iterate_file_versions(path)` yields `(index, committed_datetime, sha, bytes)` for every commit touching the file, oldest first. The ref is hard-coded to `main`; the `start_commit` parameter is unused.
- `extract_git_history.py` – writes each file version as one JSON Lines record plus `_git_committed_datetime`.
- `check_data.ipynb` – flattens the status file history into records and caches them as `data_cache/*.pks` pickles (git-ignored).
- `.github/workflows/check-scraper.yml` – every 6 h, opens/closes a `scraper-health` issue if the status or GeoJSON file has not been committed for 2 h.

## Data files (`data/`)

- `ch.bfe.ladestellen-elektromobilitaet.json` (~29 MB) – OICP master data, `EVSEData[].EVSEDataRecord[]`.
- `ch.bfe.ladestellen-elektromobilitaet-status.json` (~1.3 MB) – OICP status, `EVSEStatuses[]` with `OperatorID`, `OperatorName`, `EVSEStatusRecord[]{EvseID, EVSEStatus}`.
- `ch.bfe.ladestellen-elektromobilitaet_de.json` (~27 MB) – GeoJSON FeatureCollection, `id`/`location_id` = EVSE ID, `properties.Availability`, German HTML `description`.

## Conventions and pitfalls

- **Never edit files in `data/` by hand** and don't commit them from a dev branch – they are owned by the automated workflow and change every few minutes. Expect frequent `Latest data: …` commits on `main`; rebase rather than merge when syncing.
- The files are large: don't `cat`/`Read` them whole; use `head -c`, `jq`, or Python to inspect.
- History extraction needs a full (non-shallow) clone of `main` (`git fetch --unshallow`); a shallow clone silently yields only recent versions.
- The dependency is declared as `docopts` in `pyproject.toml` but imported as `docopt`; keep `uv.lock` in sync (`uv lock`) when changing dependencies, since CI runs `uv sync --locked`.
- Keep the source URL list in `download_data.py` and the `FILES` list in `check-scraper.yml` consistent when adding or renaming data files.
- Commit messages for code changes: short, imperative, English.
