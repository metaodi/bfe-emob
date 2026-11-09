# -*- coding: utf-8 -*-
"""Download JSON files

Usage:
  scrape.py [--verbose]
  scrape.py (-h | --help)
  scrape.py --version

Options:
  -h, --help                    Show this screen.
  --version                     Show version.
  --verbose                     Option to enable more verbose output.
"""

import logging
import os
import sys
from docopt import docopt
from lib import download as dl
from lib import ocpi


log = logging.getLogger(__name__)
arguments = docopt(__doc__, version="Download JSON files 1.0")

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.captureWarnings(True)

if arguments["--verbose"]:
    log.setLevel(logging.DEBUG)

# GeoJSON files (still available after the switch to the new data infrastructure)
geojson_urls = [
    "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/ch.bfe.ladestellen-elektromobilitaet_de.json",
]

# Legacy OICP files: will be discontinued with the switch to the new
# «ich tanke Strom» OCPI API (announced for mid-November 2026).
# Failures are only logged as a warning, the last version stays in data/.
legacy_oicp_urls = [
    "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/oicp/ch.bfe.ladestellen-elektromobilitaet.json",
    "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/status/oicp/ch.bfe.ladestellen-elektromobilitaet.json",
]


def download_url(url):
    log.debug(f"Download {url}...")
    filename = url.split("/")[-1]
    if "status" in url:
        filename = filename.replace(".json", "-status.json")

    dl_path = os.path.join("data", filename)
    dl.download_file(url, dl_path)
    log.debug("\tDone.")


errors = []

for url in geojson_urls:
    try:
        download_url(url)
    except Exception as e:
        log.exception(f"Download of {url} failed")
        errors.append(e)

for url in legacy_oicp_urls:
    try:
        download_url(url)
    except Exception as e:
        log.warning(f"Legacy OICP file {url} not available: {e}")

try:
    ocpi.download_all(os.path.join("data", "ocpi"))
except Exception as e:
    log.exception("Download from the OCPI API failed")
    errors.append(e)

if errors:
    sys.exit(1)
