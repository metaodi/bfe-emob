# -*- coding: utf-8 -*-
import logging
import requests
import time
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


log = logging.getLogger(__name__)


def _download_request(url, verify=True):
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
    headers = {'user-agent': 'Mozilla Firefox Mozilla/5.0; metaodi bfe-emob at github'}
    r = http.get(url, headers=headers, timeout=20, verify=verify)
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
