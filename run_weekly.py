
import csv, urllib.parse, time
from helpers   import COMPETITOR_MAP
from extractors import DOMAIN_EXTRACTOR    # from previous message
from price_tracker import init_db, _save  # reuse the DB helpers

init_db()

with open("targets.csv", newline="") as f:
    for row in csv.DictReader(f):
        url   = row["link"].strip()
        art   = row["art_no"].strip()
        comp  = row["competitor"].strip().lower()

        # 1️⃣  figure out which extractor to call
        domain = COMPETITOR_MAP.get(comp) \
                 or urllib.parse.urlparse(url).netloc.lower()
        fn = DOMAIN_EXTRACTOR.get(domain)
        if not fn:
            print(f"[SKIP] No extractor for {domain}")
            continue

        # 2️⃣  fetch price
        try:
            price, cur = fn(url)
            _save(art, comp, url, price, cur)     # extended _save helper
            print(f"{art} | {comp:<8} → {price:>7} {cur}")
            time.sleep(2)                         # be polite
        except Exception as e:
            print(f"[FAIL] {art} | {comp}: {e}")
