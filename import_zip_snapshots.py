#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build monthly Parquet files from OICP snapshots archived as ZIP files

Usage:
  import_zip_snapshots.py --zip-dir <dir> --month <YYYY-MM>... [--ref <ref>] [--output <dir>] [--verbose]
  import_zip_snapshots.py (-h | --help)

Options:
  -h, --help              Show this screen.
  -z, --zip-dir <dir>     Directory with <YYYY-Week-WW>/<YYYY-MM-DDTHHMMSS>.zip archives.
  -m, --month <YYYY-MM>   Month to build (repeatable).
  -r, --ref <ref>         Git ref to read the history from [default: HEAD].
  -o, --output <dir>      Output directory [default: parquet].
  --verbose               Option to enable more verbose output.

Backfills months before (or overlapping) the start of this repository's
history from another scraper that stored every snapshot as an LZMA ZIP named
after its UTC download time (e.g. the ebp-group/225469-BFE-Ladeinfrastruktur-Data
repository). Only the OICP status file in the ZIPs is used.

ZIP snapshots are used up to the first OICP commit in git; from there on the git
history is used, as in build_parquet.py. The `commit` column of the snapshots
file contains `zip:<path relative to --zip-dir>` for ZIP snapshots.
Output is the same as build_parquet.py and overwrites the files of the month.
"""

import glob
import logging
import os
import zipfile
from datetime import datetime, timedelta, timezone

import pyarrow.parquet as pq
from docopt import docopt

from lib import timeseries as ts


log = logging.getLogger(__name__)

ZIP_STATUS_MEMBER = os.path.basename(ts.OICP_STATUS_FILE)
MAX_GAP = timedelta(hours=1)


def month_range(month):
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def list_zips(zip_dir):
    """[(download time UTC, relative path)] of all ZIP snapshots, oldest first."""
    zips = []
    for path in glob.glob(os.path.join(zip_dir, "*", "*.zip")):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            stamp = datetime.strptime(name, "%Y-%m-%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            log.warning(f"Skipping {path}: unexpected file name")
            continue
        zips.append((stamp, os.path.relpath(path, zip_dir).replace(os.sep, "/")))
    return sorted(zips)


def read_zip_snapshots(zip_dir, zips):
    for stamp, rel in zips:
        try:
            with zipfile.ZipFile(os.path.join(zip_dir, rel)) as zf:
                content = zf.read(ZIP_STATUS_MEMBER)
            records = ts.parse_oicp(content)
        except (KeyError, zipfile.BadZipFile, ValueError) as e:
            log.warning(f"Skipping {rel}: {e}")
            continue
        yield stamp, f"zip:{rel}", records


def git_snapshots(commits):
    for stamp, sha, content in ts.read_blobs(commits, ts.OICP_STATUS_FILE):
        yield stamp, sha, ts.parse_oicp(content)


def build_month(zip_dir, all_zips, ref, start, end):
    path = ts.OICP_STATUS_FILE
    commits = [c for c in ts.list_commits(ref, path, since=start, until=end) if start <= c[0] < end]
    git_before = ts.last_commit_before(ref, path, start)
    if git_before:
        # git already covers the start of the month: build_parquet.py is enough
        log.warning("git history covers the whole month, ZIP snapshots are not needed")

    first_git = commits[0][0] if commits else None
    git_from = start if git_before else first_git
    zips = [z for z in all_zips if z[0] < end and (git_from is None or z[0] < git_from)]
    # the archive has gaps of weeks or months: a neighbouring snapshot is only
    # used for the start state / the end of the month if it is close enough
    zips_before = [z for z in zips if start - MAX_GAP <= z[0] < start]
    zips = ([zips_before[-1]] if zips_before and not git_before else []) + [z for z in zips if z[0] >= start]
    if git_before:
        commits.insert(0, git_before)

    git_after = [c for c in ts.list_commits(ref, path, since=end, until=end + MAX_GAP) if c[0] >= end]
    end_known = bool(git_after) or any(end <= z[0] < end + MAX_GAP for z in all_zips)
    log.info(f"oicp: {len(zips)} ZIP snapshots, {len(commits)} git snapshots, end known: {end_known}")

    def snapshots():
        yield from read_zip_snapshots(zip_dir, zips)
        yield from git_snapshots(commits)

    return ts.build_intervals("oicp", snapshots(), start, end, end_known)


def main():
    arguments = docopt(__doc__)
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if arguments["--verbose"] else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    zip_dir = arguments["--zip-dir"]
    out_dir = arguments["--output"]
    os.makedirs(out_dir, exist_ok=True)
    all_zips = list_zips(zip_dir)
    log.info(f"Found {len(all_zips)} ZIP snapshots in {zip_dir}")

    for month in arguments["--month"]:
        start, end = month_range(month)
        log.info(f"Building {month} ({start:%Y-%m-%d} - {end:%Y-%m-%d})")
        intervals, snapshots = build_month(zip_dir, all_zips, arguments["--ref"], start, end)
        if not snapshots:
            log.warning(f"No snapshots for {month}, nothing written")
            continue

        intervals.sort(key=lambda r: (r["source"], r["evse_id"], r["valid_from"]))
        iv_table = ts.to_table(intervals, ts.INTERVAL_SCHEMA)
        snap_table = ts.to_table(snapshots, ts.SNAPSHOT_SCHEMA)
        iv_path = os.path.join(out_dir, f"status_intervals_{month}.parquet")
        snap_path = os.path.join(out_dir, f"snapshots_{month}.parquet")
        pq.write_table(iv_table, iv_path, compression="zstd")
        pq.write_table(snap_table, snap_path, compression="zstd")
        log.info(f"Wrote {iv_table.num_rows} intervals to {iv_path}, {snap_table.num_rows} snapshots to {snap_path}")


if __name__ == "__main__":
    main()
