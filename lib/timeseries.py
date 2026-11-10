# -*- coding: utf-8 -*-
"""Build a continuous EVSE status time series from the git history.

Both status sources are read from git:
- legacy OICP: data/ch.bfe.ladestellen-elektromobilitaet-status.json
- OCPI:        data/ocpi/status.json

Every committed version of a file is a snapshot observed at the commit time.
Consecutive snapshots are compressed to status *intervals* per EVSE:
`[valid_from, valid_to)` with an unchanged status. The raw formats are kept
in git; this module only normalises them at read time.
"""
import json
import logging
import subprocess
from datetime import datetime, timezone

import pyarrow as pa


log = logging.getLogger(__name__)

OICP_STATUS_FILE = "data/ch.bfe.ladestellen-elektromobilitaet-status.json"
OCPI_STATUS_FILE = "data/ocpi/status.json"

# common status vocabulary (status_raw keeps the original value)
STATUS_MAP = {
    "oicp": {
        "Available": "AVAILABLE",
        "Occupied": "OCCUPIED",
        "Reserved": "OCCUPIED",
        "OutOfService": "OUT_OF_SERVICE",
        "Unknown": "UNKNOWN",
        "EvseNotFound": "REMOVED",
    },
    "ocpi": {
        "AVAILABLE": "AVAILABLE",
        "CHARGING": "OCCUPIED",
        "BLOCKED": "OCCUPIED",
        "RESERVED": "OCCUPIED",
        "OUTOFORDER": "OUT_OF_SERVICE",
        "INOPERATIVE": "OUT_OF_SERVICE",
        "PLANNED": "OUT_OF_SERVICE",
        "UNKNOWN": "UNKNOWN",
        "REMOVED": "REMOVED",
    },
}

INTERVAL_SCHEMA = pa.schema([
    ("source", pa.string()),
    ("evse_id", pa.string()),
    ("operator_id", pa.string()),
    ("location_id", pa.string()),
    ("evse_uid", pa.string()),
    ("status", pa.string()),
    ("status_raw", pa.string()),
    ("valid_from", pa.timestamp("s", tz="UTC")),
    ("valid_to", pa.timestamp("s", tz="UTC")),
    ("status_last_updated", pa.timestamp("s", tz="UTC")),
])

SNAPSHOT_SCHEMA = pa.schema([
    ("source", pa.string()),
    ("observed_at", pa.timestamp("s", tz="UTC")),
    ("commit", pa.string()),
    ("evse_count", pa.int32()),
])


def normalize_status(source, raw):
    return STATUS_MAP[source].get(raw, "UNKNOWN")


def _parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


# --- parsing of the raw snapshots -------------------------------------------

def parse_oicp(content):
    """Return {key: record} for an OICP status file."""
    data = json.loads(content)
    records = {}
    for operator in data.get("EVSEStatuses") or []:
        operator_id = operator.get("OperatorID")
        for r in operator.get("EVSEStatusRecord") or []:
            evse_id = r.get("EvseID")
            if not evse_id:
                continue
            records[evse_id] = {
                "evse_id": evse_id,
                "operator_id": operator_id,
                "location_id": None,
                "evse_uid": None,
                "status_raw": r.get("EVSEStatus"),
                "status_last_updated": None,
            }
    return records


def parse_ocpi(content):
    """Return {key: record} for an OCPI status snapshot (data/ocpi/status.json)."""
    records = {}
    for r in json.loads(content):
        key = (r["country_code"], r["party_id"], r["location_id"], r["evse_uid"])
        records[key] = {
            "evse_id": r.get("evse_id") or "*".join(key),
            "operator_id": f"{r['country_code']}*{r['party_id']}",
            "location_id": r["location_id"],
            "evse_uid": r["evse_uid"],
            "status_raw": r["status"],
            "status_last_updated": _parse_ts(r.get("last_updated")),
        }
    return records


SOURCES = {
    "oicp": (OICP_STATUS_FILE, parse_oicp),
    "ocpi": (OCPI_STATUS_FILE, parse_ocpi),
}


# --- git access --------------------------------------------------------------

def _git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def list_commits(ref, path, since=None, until=None):
    """[(commit time UTC, sha)] of all commits touching `path`, oldest first."""
    args = ["log", "--format=%H %cI", ref]
    if since:
        args.append(f"--since={since.isoformat()}")
    if until:
        args.append(f"--until={until.isoformat()}")
    commits = []
    for line in _git(*args, "--", path).splitlines():
        sha, ts = line.split(" ", 1)
        commits.append((datetime.fromisoformat(ts).astimezone(timezone.utc), sha))
    return sorted(commits)


def last_commit_before(ref, path, ts):
    commits = _git("log", "-1", "--format=%H %cI", f"--until={ts.isoformat()}", ref, "--", path).split()
    if not commits:
        return None
    return datetime.fromisoformat(commits[1]).astimezone(timezone.utc), commits[0]


def has_commit_since(ref, path, ts):
    return bool(_git("log", "-1", "--format=%H", f"--since={ts.isoformat()}", ref, "--", path).strip())


def read_blobs(commits, path):
    """Yield (ts, sha, content) for each commit using one `git cat-file --batch` process."""
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    try:
        for ts, sha in commits:
            proc.stdin.write(f"{sha}:{path}\n".encode())
            proc.stdin.flush()
            header = proc.stdout.readline().decode().split()
            if len(header) < 3 or header[1] == "missing":
                log.debug(f"{path} missing in {sha}")
                continue
            content = proc.stdout.read(int(header[2]))
            proc.stdout.read(1)  # trailing newline
            yield ts, sha, content
    finally:
        proc.stdin.close()
        proc.wait()


# --- interval building -------------------------------------------------------

def build_intervals(source, snapshots, period_start, period_end, end_known):
    """Compress snapshots to status intervals within [period_start, period_end).

    `snapshots` is an iterable of (ts, sha, records) ordered by time. A snapshot
    before `period_start` (state at the start of the period) is allowed.
    If `end_known` is true (the source has a later snapshot), open intervals are
    cut at `period_end`, otherwise at the time of the last snapshot.
    Returns (intervals, snapshot_rows).
    """
    intervals = []
    snapshot_rows = []
    open_ = {}  # key -> interval dict
    last_ts = None

    def close(key, ts):
        iv = open_.pop(key)
        iv["valid_to"] = ts
        if iv["valid_to"] > iv["valid_from"]:
            intervals.append(iv)

    for ts, sha, records in snapshots:
        if ts >= period_end:
            break
        obs = max(ts, period_start)
        if ts >= period_start:
            snapshot_rows.append({
                "source": source, "observed_at": ts, "commit": sha, "evse_count": len(records),
            })
        # EVSEs no longer present
        for key in [k for k in open_ if k not in records]:
            close(key, obs)
        for key, rec in records.items():
            status = normalize_status(source, rec["status_raw"])
            iv = open_.get(key)
            if iv and iv["status_raw"] == rec["status_raw"]:
                continue
            if iv:
                close(key, obs)
            open_[key] = {
                "source": source,
                **rec,
                "status": status,
                "valid_from": obs,
                "valid_to": None,
            }
        last_ts = obs

    end = period_end if end_known else last_ts
    for key in list(open_):
        close(key, end)
    return intervals, snapshot_rows


def build_source(source, ref, period_start, period_end):
    path, parser = SOURCES[source]
    commits = list_commits(ref, path, since=period_start, until=period_end)
    commits = [c for c in commits if period_start <= c[0] < period_end]
    before = last_commit_before(ref, path, period_start)
    if before and before not in commits:
        commits.insert(0, before)
    elif not before and commits:
        log.warning(f"{source}: no snapshot before {period_start} (shallow clone or start of the data)")
    if not commits:
        log.info(f"{source}: no snapshots in period")
        return [], []
    end_known = has_commit_since(ref, path, period_end)
    log.info(f"{source}: {len(commits)} snapshots, end known: {end_known}")

    snapshots = ((ts, sha, parser(content)) for ts, sha, content in read_blobs(commits, path))
    return build_intervals(source, snapshots, period_start, period_end, end_known)


def to_table(rows, schema):
    cols = {name: [r.get(name) for r in rows] for name in schema.names}
    return pa.table(cols, schema=schema)
