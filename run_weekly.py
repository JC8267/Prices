import csv, time, urllib.parse
from helpers     import COMPETITOR_MAP
from price_tracker import init_db, _save          # <- 6-arg helper lives here
from extractors   import DOMAIN_EXTRACTOR         # <- NO _save here!


def normalise_header(row):
    """
    Return a copy where keys are stripped + lower-cased,
    e.g. ' Art_No '  →  'art_no'
    """
    return {k.strip().lower(): (v.strip() if isinstance(v, str) else v)
            for k, v in row.items()}

init_db()

with open("targets.csv", newline="", encoding="utf-8-sig") as f:
    for raw in csv.DictReader(f):
        row = normalise_header(raw)

        # --- tolerant look-ups --------------------------------------------
        art = row.get("art_no") or row.get("art no") or row.get("article") \
              or next(iter(row.values()))          # 1st col as last resort
        comp = row.get("competitor") or row.get("retailer")
        url  = row.get("link") or row.get("url")

        if not all([art, comp, url]):
            print(f"[SKIP] Missing column in row: {row}")
            continue

        # map 'wal-mart' → 'walmart.com', etc.
        domain = COMPETITOR_MAP.get(comp.lower()) \
                 or urllib.parse.urlparse(url).netloc.lower()
        fn = DOMAIN_EXTRACTOR.get(domain)
        if fn is None:
            print(f"[SKIP] No extractor for {domain}")
            continue

        try:
            # Updated to handle the competitor_sku return value
            result = fn(url)
            
            # Handle both old (price, currency) and new (price, currency, sku) return formats
            if len(result) == 3:
                price, cur, comp_sku = result
                _save(art, comp, url, price, cur, comp_sku)
                print(f"{art} | {comp:<9} → {price:>8} {cur} | SKU: {comp_sku}")
            else:
                price, cur = result
                _save(art, comp, url, price, cur)
                print(f"{art} | {comp:<9} → {price:>8} {cur}")
                
            time.sleep(2)
        except Exception as e:
            print(f"[FAIL] {art} | {comp}: {e}")