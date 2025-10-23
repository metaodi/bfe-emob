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
from docopt import docopt
from lib import download as dl


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

urls = [
    "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/oicp/ch.bfe.ladestellen-elektromobilitaet.json",
    "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/status/oicp/ch.bfe.ladestellen-elektromobilitaet.json",
    "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/ch.bfe.ladestellen-elektromobilitaet_de.json"
]

for url in urls:
    log.debug(f"Download {url}...")
    filename = url.split("/")[-1]
    if "status" in url:
        filename = filename.replace(".json", "-status.json")

    dl_path = os.path.join("data", filename)
    dl.download_file(url, dl_path)
    log.debug("\tDone.")