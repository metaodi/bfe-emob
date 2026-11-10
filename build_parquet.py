#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build monthly Parquet files of the EVSE status time series from the git history

Usage:
  build_parquet.py [--month <YYYY-MM>]... [--ref <ref>] [--output <dir>] [--verbose]
  build_parquet.py (-h | --help)

Options:
  -h, --help              Show this screen.
  -m, --month <YYYY-MM>   Month to build (repeatable) [default: previous month].
  -r, --ref <ref>         Git ref to read the history from [default: HEAD].
  -o, --output <dir>      Output directory [default: parquet].
  --verbose               Option to enable more verbose output.

For each month two files are written:
  <output>/status_intervals_<YYYY-MM>.parquet
  <output>/snapshots_<YYYY-MM>.parquet
The history of the month (plus the last commit before it) must be available
locally, e.g. `git fetch --shallow-since=<YYYY-MM-01 minus a few days> origin main`.
"""

import logging
import os
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
from docopt import docopt

from lib import timeseries as ts


log = logging.getLogger(__name__)
arguments = docopt(__doc__)

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.DEBUG if arguments["--verbose"] else logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)


def month_range(month):
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def previous_month():
    now = datetime.now(timezone.utc)
    if now.month == 1:
        return f"{now.year - 1}-12"
    return f"{now.year}-{now.month - 1:02d}"


months = arguments["--month"]
if not months or months == ["previous month"]:
    months = [previous_month()]

out_dir = arguments["--output"]
os.makedirs(out_dir, exist_ok=True)

for month in months:
    start, end = month_range(month)
    log.info(f"Building {month} ({start:%Y-%m-%d} - {end:%Y-%m-%d})")
    intervals, snapshots = [], []
    for source in ts.SOURCES:
        iv, snap = ts.build_source(source, arguments["--ref"], start, end)
        intervals.extend(iv)
        snapshots.extend(snap)

    intervals.sort(key=lambda r: (r["source"], r["evse_id"], r["valid_from"]))
    iv_table = ts.to_table(intervals, ts.INTERVAL_SCHEMA)
    snap_table = ts.to_table(snapshots, ts.SNAPSHOT_SCHEMA)

    iv_path = os.path.join(out_dir, f"status_intervals_{month}.parquet")
    snap_path = os.path.join(out_dir, f"snapshots_{month}.parquet")
    pq.write_table(iv_table, iv_path, compression="zstd")
    pq.write_table(snap_table, snap_path, compression="zstd")
    log.info(f"Wrote {iv_table.num_rows} intervals to {iv_path}, {snap_table.num_rows} snapshots to {snap_path}")
