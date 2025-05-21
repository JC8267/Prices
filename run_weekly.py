import csv
import time
import urllib.parse

from helpers       import COMPETITOR_MAP
from price_tracker import init_db, _save          # <- 6-arg helper lives here
from extractors    import DOMAIN_EXTRACTOR         # <- URL → (price,cur,sku)

def normalise_header(row):
    """
    Return a copy where keys are stripped + lower-cased,
    e.g. ' Art_No '  →  'art_no'
    """
    return {
        k.strip().lower(): (v.strip() if isinstance(v, str) else v)
        for k, v in row.items()
    }

# Ensure the SQLite table exists
init_db()

with open("targets.csv", newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for raw in reader:
        row = normalise_header(raw)

        # --- tolerant look-ups --------------------------------------------
        art  = (
            row.get("art_no")
            or row.get("art no")
            or row.get("article")
            or next(iter(row.values()), None)
        )
        comp = row.get("competitor") or row.get("retailer")
        url  = row.get("link")       or row.get("url")

        if not all([art, comp, url]):
            print(f"[SKIP] Missing column in row: {row}")
            continue

        # map 'wal-mart' → 'walmart.com', etc.
        domain = (
            COMPETITOR_MAP.get(comp.lower())
            or urllib.parse.urlparse(url).netloc.lower()
        )
        fn = DOMAIN_EXTRACTOR.get(domain)
        if fn is None:
            print(f"[SKIP] No extractor for {domain}")
            continue

        # --- scrape & save -----------------------------------------------
        try:
            result = fn(url)
            # normalize into (price, cur, sku)
            if len(result) == 3:
                price, cur, sku = result
            else:
                price, cur       = result
                sku              = ""      # no SKU returned

            # Now call _save with exactly 6 args:
            #   art_no, competitor, url, sku, price, currency
            _save(art, comp, url, sku, price, cur)

            # Log to stdout
            out = f"{art} | {comp:<9} → {price:>8} {cur}"
            if sku:
                out += f" | SKU: {sku}"
            print(out)

            # gentle pacing
            time.sleep(2)

        except Exception as e:
            print(f"[FAIL] {art} | {comp}: {e}")
