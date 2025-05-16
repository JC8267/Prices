#  ── extractors.py ────────────────────────────────────────────────────────────
import re, json, datetime, sqlite3, curl_cffi
from bs4 import BeautifulSoup

DB       = "prices.sqlite"
HEADERS  = {"User-Agent": "Mozilla/5.0"}

# ---------- helpers ----------------------------------------------------------
def _html(url):
    return curl_cffi.requests.get(url, headers=HEADERS, timeout=25).text

def _save(url, price, cur):
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO prices VALUES (?,?,?,?)",
            (url, datetime.date.today().isoformat(), price, cur)
        )

def _clean(txt):
    return float(re.sub(r"[^\d.]", "", txt))

# ---------- AMAZON -----------------------------------------------------------
def fetch_amazon_price(url):
    """
    Looks for the hidden 'customerVisiblePrice' inputs that Amazon’s add-to-cart
    form renders server-side. Fallback: JSON-LD offer block.
    """
    soup = BeautifulSoup(_html(url), "lxml")

    tag = soup.find(
        "input",
        {"name": re.compile(r"customerVisiblePrice.*\[amount\]")}
    )
    if tag:
        price = _clean(tag["value"])
        cur   = soup.find(
            "input",
            {"name": re.compile(r"customerVisiblePrice.*\[currencyCode\]")}
        )["value"]
    else:                               # ⇢ fallback: JSON-LD
        ld   = soup.find("script", type="application/ld+json")
        data = json.loads(ld.string) if ld else {}
        offers = data.get("offers", {})
        price = float(offers.get("price")) if offers else None
        cur   = offers.get("priceCurrency", "USD")

    if price is None:
        raise ValueError("Amazon price not found")

    return price, cur

# ---------- WALMART ----------------------------------------------------------
def fetch_walmart_price(url):
    """
    Walmart exposes the live price in a <span itemprop="price"> element that
    arrives with the initial HTML payload.                        :contentReference[oaicite:0]{index=0}
    """
    soup  = BeautifulSoup(_html(url), "lxml")
    price = soup.find("span", {"itemprop": "price"})
    cur   = soup.find("span", {"itemprop": "priceCurrency"})
    if not price:
        # fallback to Next.js JSON if the page was hydrated client-side
        nxt  = soup.find("script", id="__NEXT_DATA__")
        blob = json.loads(nxt.string) if nxt else {}
        price = blob.get("props", {})\
                    .get("pageProps", {})\
                    .get("initialData", {})\
                    .get("data", {})\
                    .get("product", {})\
                    .get("price", {})
        return float(price["price"]), price.get("currency", "USD")

    return _clean(price.text), cur.text if cur else "USD"

# ---------- BABYLIST ---------------------------------------------------------
def fetch_babylist_price(url):
    """
    Babylist splits the numerals & decimals into separate <span>s inside
    a div that begins with 'PriceTag-styles__PriceTag__numerals'.
    """
    soup = BeautifulSoup(_html(url), "lxml")
    box  = soup.select_one('div[class^="PriceTag-styles__PriceTag__numerals"]')
    if not box:                         # meta fallback
        meta = soup.find("meta", {"property": "product:price:amount"})
        if meta:
            return float(meta["content"]), soup.find(
                "meta", {"property": "product:price:currency"}
            )["content"]
        raise ValueError("Babylist price not found")

    price_txt = "".join(box.stripped_strings)  # e.g. "179."
    return _clean(price_txt), "USD"

# ---------- router -----------------------------------------------------------
DOMAIN_EXTRACTOR = {
    "amazon.com":   fetch_amazon_price,
    "www.amazon.com": fetch_amazon_price,
    "smile.amazon.com": fetch_amazon_price,
    "walmart.com":  fetch_walmart_price,
    "www.walmart.com": fetch_walmart_price,
    "babylist.com": fetch_babylist_price,
    "www.babylist.com": fetch_babylist_price,
}

def scrape_row(row):
    """
    row = {"url": "...", ...} from your targets.csv
    """
    url  = row["url"]
    dom  = url.split("/")[2].lower()
    fn   = DOMAIN_EXTRACTOR.get(dom)
    if not fn:
        raise NotImplementedError(f"No extractor mapped for {dom}")

    price, cur = fn(url)
    _save(url, price, cur)
    print(f"{dom:<12} → {price:>8} {cur}")
