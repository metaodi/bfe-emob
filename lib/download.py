# -*- coding: utf-8 -*-
import logging
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


log = logging.getLogger(__name__)

HEADERS = {'user-agent': 'Mozilla Firefox Mozilla/5.0; metaodi bfe-emob at github'}
TIMEOUT = 60


def session():
    """Return a requests session with retries (incl. 429 with Retry-After)."""
    retry_strategy = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[403, 429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    http = requests.Session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)
    http.headers.update(HEADERS)
    return http


def _download_request(url, verify=True):
    r = session().get(url, timeout=TIMEOUT, verify=verify)
    r.raise_for_status()
    return r


def download(url, encoding='utf-8', verify=True):
    r = _download_request(url, verify=verify)
    if encoding:
        r.encoding = encoding
    return r.text


def download_content(url, verify=True):
    r = _download_request(url, verify=verify)
    return r.content


def jsondownload(url, verify=True):
    r = _download_request(url, verify=verify)
    return r.json()


def download_file(url, path, verify=True):
    r = _download_request(url, verify=verify)
    with open(path, 'wb') as f:
        for chunk in r.iter_content(1024):
            f.write(chunk)
