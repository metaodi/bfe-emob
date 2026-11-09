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
STATUS_WINDOW = timedelta(hours=2)


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


def fetch_status_since(http, date_from):
    """Fetch the EVSE status values received since `date_from`."""
    params = {
        "date_from": date_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": STATUS_LIMIT,
    }
    _, body = _get(http, f"{BASE_URL}/status", params)
    records = body["data"] or []
    if len(records) >= STATUS_LIMIT:
        log.warning(
            f"Status endpoint returned {len(records)} records (= limit), "
            "some status changes might be missing."
        )
    return records


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

    locations = fetch_all(http, "locations")
    log.info(f"Fetched {len(locations)} locations")
    tariffs = fetch_all(http, "tariffs")
    log.info(f"Fetched {len(tariffs)} tariffs")
    updates = fetch_status_since(http, now - STATUS_WINDOW)
    log.info(f"Fetched {len(updates)} status updates")

    status_path = os.path.join(out_dir, "status.json")
    snapshot = build_status_snapshot(locations, load_json(status_path, []), updates)
    log.info(f"Status snapshot contains {len(snapshot)} EVSEs")

    write_json_array(os.path.join(out_dir, "locations.json"), locations)
    write_json_array(os.path.join(out_dir, "tariffs.json"), tariffs)
    write_json_array(status_path, snapshot)
