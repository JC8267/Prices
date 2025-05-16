import re  # make sure re is imported once at the top

import random
import curl_cffi

# ── Browser-like HTTP headers & TLS fingerprint for Akamai / CloudFront ──
UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.%d.%d Safari/537.36"
)

HEADERS = {
    "User-Agent": UA_DESKTOP % (
        random.randint(4200, 4299),   # Chrome build & patch → randomised
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

def _html(url: str) -> str:
    """
    Download a page with a Chrome-124 TLS fingerprint.
    This bypasses Target’s Akamai and Walmart’s CloudFront ‘bot’ templates.
    """
    return curl_cffi.requests.get(
        url,
        headers=HEADERS,
        impersonate="chrome124"   # ← key flag
    ).text


# ── Normalisation map from CSV “competitor” column → domain ───────────────
COMPETITOR_MAP = {
    "amazon":   "amazon.com",
    "target":   "target.com",
    "wal-mart": "walmart.com",   # matches the hyphen spelling in your sheet
    "walmart":  "walmart.com",
    "babylist": "babylist.com",
}


def _clean(txt: str) -> float:
    """Strip $, commas, and whitespace → float."""
    return float(re.sub(r"[^\d.]", "", str(txt)))