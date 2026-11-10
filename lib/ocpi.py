# -*- coding: utf-8 -*-
"""Client for the OCPI 2.3.0 API of «ich tanke Strom» (BFE/SFOE).

Documentation:
https://github.com/SFOE/ichtankestrom_Documentation/blob/main/How%20to%20query%20ich%20tanke%20strom.md
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from lib import download as dl


log = logging.getLogger(__name__)

BASE_URL = "https://api.emobility-prod.prometheon.bfe.admin.ch/ocpi"
PAGE_LIMIT = 1000  # max. for locations and tariffs
STATUS_LIMIT = 5000  # max. for the status endpoint (no offset support)
# /status is queried from the time of the previous run (server timestamp of
# its response) minus a small overlap for records that become visible late.
# Duplicates are harmless: the newest value per EVSE wins.
STATUS_OVERLAP = timedelta(minutes=2)
# used if there is no previous run (no state file): start with this window
# and halve it until the response is below the limit (otherwise it is an
# undefined subset), but not below the minimum
STATUS_INITIAL_WINDOW = timedelta(days=7)
STATUS_MIN_WINDOW = timedelta(minutes=30)


class OCPIError(Exception):
    pass


def _get(http, url, params=None):
    r = http.get(url, params=params, headers={"Accept": "application/json"}, timeout=dl.TIMEOUT)
    r.raise_for_status()
    body = r.json()
    if body.get("status_code") != 1000:
        raise OCPIError(f"{url}: {body.get('status_code')} {body.get('status_message')}")
    return r, body


def fetch_all(http, module):
    """Fetch all objects of a paginated module (e.g. `locations`, `tariffs`)."""
    url = f"{BASE_URL}/{module}"
    params = {"limit": PAGE_LIMIT}
    records = []
    total = None
    while url:
        log.debug(f"GET {url} {params or ''}")
        r, body = _get(http, url, params)
        records.extend(body["data"] or [])
        total = r.headers.get("X-Total-Count", total)
        # the Link header contains the complete URL of the next page
        url = r.links.get("next", {}).get("url")
        params = None
    if total is not None and int(total) != len(records):
        raise OCPIError(f"{module}: expected {total} objects, got {len(records)}")
    return sorted(records, key=lambda o: (o["country_code"], o["party_id"], o["id"]))


def fetch_status_initial(http, now):
    """Fetch as many recent status values as possible without hitting the limit."""
    window = STATUS_INITIAL_WINDOW
    while True:
        date_from = now - window
        records, server_ts = fetch_status_since(http, date_from, warn=False)
        if len(records) < STATUS_LIMIT or window / 2 < STATUS_MIN_WINDOW:
            if len(records) >= STATUS_LIMIT:
                log.warning(f"Status endpoint returned {len(records)} records (= limit) for the initial window")
            return records, server_ts, date_from
        window = window / 2


def fetch_status_since(http, date_from, warn=True):
    """Fetch the EVSE status values received since `date_from`.

    Returns (records, server timestamp of the response).
    """
    params = {
        "date_from": date_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": STATUS_LIMIT,
    }
    _, body = _get(http, f"{BASE_URL}/status", params)
    records = body["data"] or []
    server_ts = _ts(body["timestamp"])
    if warn and len(records) >= STATUS_LIMIT:
        log.warning(
            f"Status endpoint returned {len(records)} records (= limit), "
            "some status changes might be missing."
        )
    return records, server_ts


def _key(cc, party, location_id, evse_uid):
    return (cc, party, location_id, evse_uid)


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_status_snapshot(locations, previous, updates):
    """Combine all known status values to a snapshot of all current EVSEs.

    For each EVSE of `locations` the newest (by `last_updated`) of these is used:
    - the status contained in the location object,
    - the status of the previous snapshot,
    - the status values from the status endpoint.
    EVSEs that are no longer part of a location are dropped.
    """
    prev = {
        _key(s["country_code"], s["party_id"], s["location_id"], s["evse_uid"]): s
        for s in previous
    }
    upd = {}
    for s in updates:
        k = _key(s["country_code"], s["party_id"], s["location_id"], s["evse_uid"])
        if k not in upd or _ts(s["last_updated"]) > _ts(upd[k]["last_updated"]):
            upd[k] = s

    snapshot = []
    for loc in locations:
        for evse in loc.get("evses") or []:
            k = _key(loc["country_code"], loc["party_id"], loc["id"], evse["uid"])
            candidates = [
                {"status": evse["status"], "last_updated": evse["last_updated"]},
                prev.get(k),
                upd.get(k),
            ]
            best = max(
                (c for c in candidates if c),
                key=lambda c: _ts(c["last_updated"]),
            )
            snapshot.append({
                "country_code": loc["country_code"],
                "party_id": loc["party_id"],
                "location_id": loc["id"],
                "evse_uid": evse["uid"],
                "evse_id": evse.get("evse_id"),
                "status": best["status"],
                "last_updated": best["last_updated"],
            })
    return sorted(snapshot, key=lambda s: _key(s["country_code"], s["party_id"], s["location_id"], s["evse_uid"]))


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json_array(path, records):
    """Write a JSON array with one object per line (small, readable git diffs)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n")
        f.write(",\n".join(json.dumps(r, ensure_ascii=False) for r in records))
        f.write("\n]\n")


def download_all(out_dir):
    http = dl.session()
    now = datetime.now(timezone.utc)
    status_path = os.path.join(out_dir, "status.json")
    state_path = os.path.join(out_dir, "status_state.json")

    locations = fetch_all(http, "locations")
    log.info(f"Fetched {len(locations)} locations")
    tariffs = fetch_all(http, "tariffs")
    log.info(f"Fetched {len(tariffs)} tariffs")
    state = load_json(state_path, {})
    if state.get("last_status_fetch") and os.path.exists(status_path):
        date_from = _ts(state["last_status_fetch"]) - STATUS_OVERLAP
        updates, server_ts = fetch_status_since(http, date_from)
    else:
        log.info("No previous status fetch, starting with the initial window")
        updates, server_ts, date_from = fetch_status_initial(http, now)
    log.info(f"Fetched {len(updates)} status updates since {date_from:%Y-%m-%dT%H:%M:%SZ}")
    snapshot = build_status_snapshot(locations, load_json(status_path, []), updates)
    log.info(f"Status snapshot contains {len(snapshot)} EVSEs")

    write_json_array(os.path.join(out_dir, "locations.json"), locations)
    write_json_array(os.path.join(out_dir, "tariffs.json"), tariffs)
    write_json_array(status_path, snapshot)
    # only store the new state once the snapshot is written
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"last_status_fetch": server_ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")}, f)
        f.write("\n")
