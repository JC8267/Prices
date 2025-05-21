# helpers.py  – shared utilities (headers, polite rate-limit, HTTP wrapper)

import random
import re
import time
import urllib.parse
from collections import defaultdict
from threading import Lock

import curl_cffi

# ────────────────────────────────── HEADERS ──────────────────────────────────
UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.%d.%d Safari/537.36"
)

HEADERS = {
    "User-Agent": UA_DESKTOP % (
        random.randint(4200, 4299),
        random.randint(60, 99)
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest":  "document",
    "Sec-Fetch-Mode":  "navigate",
    "Sec-Fetch-Site":  "none",
    "Sec-Fetch-User":  "?1",
}

# ───────────────────────────── rate-limit decorator ──────────────────────────
_RATE_LOCK   = Lock()
_LAST_HIT    = defaultdict(float)    # domain → last request timestamp

PER_DOMAIN_DELAY = {                 # seconds between hits to same domain
    "amazon.com":   3,
    "target.com":   2,
    "walmart.com":  2,
    "babylist.com": 2,
}

def polite(func):
    """Throttle outbound HTTP so we never hammer one host too fast."""
    def wrapper(url: str, *args, **kwargs):
        dom = urllib.parse.urlparse(url).netloc.split(":")[0].lower()
        base_dom = ".".join(dom.split(".")[-2:])      # strip subdomain

        min_delay = PER_DOMAIN_DELAY.get(base_dom, 1.5)
        with _RATE_LOCK:
            elapsed  = time.time() - _LAST_HIT[base_dom]
            wait_for = max(0, min_delay - elapsed)
            _LAST_HIT[base_dom] = time.time() + wait_for

        if wait_for:
            time.sleep(wait_for + random.uniform(0, 0.75))  # jitter

        return func(url, *args, **kwargs)
    return wrapper

# ──────────────────────────── HTTP helper functions ─────────────────────────
@polite
def _html(url: str) -> str:
    """Return page HTML with Chrome-124 TLS fingerprint + polite delay."""
    return curl_cffi.requests.get(
        url,
        headers=HEADERS,
        impersonate="chrome124",
        timeout=20,
    ).text

@polite
def _get_json(url: str):
    """GET → .json() with rate-limit & impersonation."""
    return curl_cffi.requests.get(
        url,
        headers={"Accept": "application/json", **HEADERS},
        impersonate="chrome124",
        timeout=20,
    ).json()

def _clean(txt) -> float:
    """Strip $, commas, spaces → float."""
    return float(re.sub(r"[^\d.]", "", str(txt)))

# ───────────────────────── competitor → domain map ──────────────────────────
COMPETITOR_MAP = {
    "amazon":   "amazon.com",
    "target":   "target.com",
    "wal-mart": "walmart.com",   # matches hyphen spelling in CSV
    "walmart":  "walmart.com",
    "babylist": "babylist.com",
}
