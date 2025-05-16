#  ── extractors.py  (drop-in replacement) ────────────────────────────────
import re, json, curl_cffi, urllib.parse
from bs4 import BeautifulSoup
from helpers import _html, _clean     # Import _clean from helpers






def _find_first(node, key):
    """Depth-first search for the first occurrence of `key` in nested dict/list."""
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            if key in n:
                return n[key]
            stack.extend(n.values())
        elif isinstance(n, list):
            stack.extend(n)
    return None

# Helper function for Walmart JSON parsing
def _find_walmart_product_data(data):
    """Navigate Walmart's complex JSON structure to find product data."""
    if not data:
        return None
        
    # Try multiple paths where price data might be stored
    if "product" in data:
        return data["product"]
    
    for key in ["__PRELOADED_STATE__", "data", "contents", "productByLine", "products"]:
        if key in data:
            data = data[key]
            if isinstance(data, dict) and "offering" in data:
                return data
            if isinstance(data, dict) and "price" in data:
                return data
    
    return None

# Helper function to extract price from Walmart product data
def _extract_walmart_price(data):
    """Extract price from Walmart product data structure."""
    if not data:
        return None
        
    # Check common price locations
    if "price" in data:
        price_data = data["price"]
        if isinstance(price_data, dict):
            for key in ["current", "currentPrice", "priceAmount", "price"]:
                if key in price_data and price_data[key]:
                    return price_data[key]
    
    # Check offering price structure
    if "offering" in data and "pricesInfo" in data["offering"]:
        price_info = data["offering"]["pricesInfo"]
        if "currentPrice" in price_info:
            return price_info["currentPrice"]["price"]
    
    return None

# ── AMAZON ───────────────────────────────────────────────────────────────
def fetch_amazon_price(url: str):
    import re, json
    soup = BeautifulSoup(_html(url), "lxml")
    
    # Extract Amazon ASIN (their SKU format)
    asin = None
    asin_match = re.search(r'/dp/([A-Z0-9]{10})(?:[/?]|$)', url)
    if not asin_match:
        asin_match = re.search(r'/gp/product/([A-Z0-9]{10})(?:[/?]|$)', url)
    if asin_match:
        asin = asin_match.group(1)
    
    # If not in URL, try to find in the page
    if not asin:
        asin_input = soup.find("input", {"id": "ASIN"})
        if asin_input and asin_input.get("value"):
            asin = asin_input["value"]

    # hidden add-to-cart inputs (fastest)
    tag = soup.find("input", {"name": re.compile(r"customerVisiblePrice.*\[amount\]")})
    if tag:
        price = _clean(tag["value"])
        cur = soup.find(
                  "input",
                  {"name": re.compile(r"customerVisiblePrice.*\[currencyCode\]")}
               )["value"]
        return price, cur, asin

    # JSON-LD fallback
    ld = soup.find("script", type="application/ld+json")
    if ld:
        data = json.loads(ld.string)
        offers = data.get("offers", {})
        price = offers.get("price") or offers.get("value")
        cur = offers.get("priceCurrency", "USD")
        if price:
            return float(price), cur, asin

    raise ValueError("Amazon price not found")

# ───────── TARGET via RedSky API ───────────────────────────────────────────
def fetch_target_price(url: str):
    import re, curl_cffi, json
    # TCIN is Target's SKU
    tcin_match = re.search(r'/A-(\d+)', url)
    if not tcin_match:
        # Try alternate URL format
        tcin_match = re.search(r'(?:/-|/p)/([A-Za-z0-9]{8,})(?:[/?]|$)', url)
    
    if not tcin_match:
        raise ValueError("Could not extract Target TCIN from URL")
        
    tcin = tcin_match.group(1)

    api = (
        "https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1"
        "?key=eb2551d2d6ea49278afeb0f96ea59f0a"
        f"&tcin={tcin}&pricing_store_id=3991&has_store_id=false"
        "&excludes=taxonomy,bulk_ship"
    )
    block = (curl_cffi.requests.get(api, impersonate="chrome124")
             .json()["data"]["product"]["price"])

    raw = (block.get("current_retail") or
           block.get("formatted_current_price") or
           block.get("formatted_current_price_range") or
           block.get("formatted_current_price_combined"))

    if not raw:
        raise ValueError("Price missing in RedSky JSON")

    # → "$73.49 - $157.49"  →  "73.49"
    first_num = re.search(r'([0-9]+\.[0-9]+)', str(raw)).group(1)
    return float(first_num), "USD", tcin

# ───────── WALMART - extracting SKU along with price ──────────────────────
def fetch_walmart_price(url: str):
    """Extract Walmart price and SKU using only HTML parsing"""
    import re, time, random
    from bs4 import BeautifulSoup
    
    # Extract the product ID from the URL
    item_id_match = re.search(r'/(\d+)(?:[/?]|$)', urllib.parse.urlsplit(url).path)
    if not item_id_match:
        raise ValueError("Could not extract Walmart product ID from URL")
        
    item_id = item_id_match.group(1)
    
    # Create random session data to appear more like a real browser
    session_id = f"s{random.randint(100000000, 999999999)}"
    visitor_id = f"v{random.randint(1000000000000, 9999999999999)}"
    
    # Custom headers that closely mimic a real browser session
    browser_headers = {
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.{random.randint(4200, 4299)}.{random.randint(60, 99)} Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": "\"Chromium\";v=\"124\", \"Google Chrome\";v=\"124\", \"Not-A.Brand\";v=\"99\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "Cache-Control": "max-age=0",
        # Cookies that help avoid detection
        "Cookie": f"vtc={visitor_id}; s_vi=[CS]{session_id}[CE]; wmt.c=0"
    }
    
    # Add random delay to simulate human browsing
    time.sleep(random.uniform(2, 4))
    
    # Strategy 1: Try browsing the mobile product page first
    mobile_url = f"https://www.walmart.com/ip/product/{item_id}?selected=true"
    
    response = curl_cffi.requests.get(
        mobile_url,
        headers=browser_headers,
        impersonate="chrome124",
        timeout=20
    )
    
    # Check if we got a valid response
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "lxml")
        
        # Look for additional SKU (may be different from URL item_id)
        sku = _extract_walmart_sku(soup, item_id)
        
        # Walmart injects the product data as JSON in a script tag
        for script in soup.find_all("script", type="application/json"):
            if "__PRELOADED_STATE__" in script.text:
                try:
                    # Extract the JSON and parse it
                    json_str = script.string
                    data = json.loads(json_str)
                    
                    # Navigate the complex JSON structure to find the price
                    product_data = _find_walmart_product_data(data)
                    if product_data:
                        price = _extract_walmart_price(product_data)
                        if price:
                            return float(price), "USD", sku or item_id
                except Exception as e:
                    print(f"Error parsing Walmart JSON: {e}")
        
        # Direct HTML extraction approach
        price_elem = soup.select_one('span[itemprop="price"], [data-automation-id="price-value"]')
        if price_elem:
            price_text = price_elem.get_text().strip()
            price = re.search(r'(\d+\.\d+)', price_text)
            if price:
                return float(price.group(1)), "USD", sku or item_id
        
        # Alternative: Look for meta tags with price
        meta_price = soup.find("meta", {"property": "product:price:amount"})
        if meta_price and meta_price.get("content"):
            return float(meta_price["content"]), "USD", sku or item_id
    
    # Strategy 2: Try the standard product page
    time.sleep(random.uniform(1.5, 3))
    
    # Add referer to second request to look more legitimate
    browser_headers["Referer"] = mobile_url
    browser_headers["sec-fetch-site"] = "same-origin"
    
    standard_url = f"https://www.walmart.com/ip/{item_id}"
    response = curl_cffi.requests.get(
        standard_url,
        headers=browser_headers,
        impersonate="chrome124",
        timeout=20
    )
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "lxml")
        
        # Try to extract SKU again
        sku = _extract_walmart_sku(soup, item_id)
        
        # Check for price in various locations in the HTML
        price_containers = [
            soup.select_one('[data-testid="price-value"]'),
            soup.select_one('[data-automation-id="price-value"]'),
            soup.select_one('.price-characteristic'),
            soup.select_one('[itemprop="price"][content]')
        ]
        
        for container in price_containers:
            if container:
                if container.has_attr('content'):
                    return float(container['content']), "USD", sku or item_id
                else:
                    price_text = container.get_text().strip()
                    price_match = re.search(r'(\d+\.\d+)', price_text)
                    if price_match:
                        return float(price_match.group(1)), "USD", sku or item_id
    
    # Fallback to just returning price and the item_id as SKU
    raise ValueError("Could not extract Walmart price from any source")

# Helper function to extract Walmart's SKU (which might be different from the URL ID)
def _extract_walmart_sku(soup, default_id):
    """Extract Walmart's internal SKU from the page"""
    # Look for SKU/item number in the page
    sku_containers = [
        soup.select_one('[data-testid="product-sku"]'),
        soup.select_one('.prod-ProductId'),
        soup.select_one('[itemprop="sku"]'),
        soup.select_one('[data-automation-id="product-sku"]')
    ]
    
    for container in sku_containers:
        if container:
            # Extract text and look for digits
            text = container.get_text().strip()
            sku_match = re.search(r'(?:Item|SKU|#)\s*(?:number|num)?(?:\s*:)?\s*(\d+)', text, re.I)
            if sku_match:
                return sku_match.group(1)
            
            # If we have text with just digits, use that
            digits_only = re.search(r'^\s*(\d+)\s*$', text)
            if digits_only:
                return digits_only.group(1)
    
    # Look for it in meta tags
    meta_sku = soup.find("meta", {"property": "product:retailer_item_id"})
    if meta_sku and meta_sku.get("content"):
        return meta_sku["content"]
    
    # Try to find it in script tags
    for script in soup.find_all("script"):
        if script.string and "sku" in script.string.lower():
            sku_match = re.search(r'"sku"\s*:\s*"(\d+)"', script.string)
            if sku_match:
                return sku_match.group(1)
    
    # Fallback to URL ID if we can't find a better SKU
    return default_id

# ── BABYLIST ─────────────────────────────────────────────────────────────
def fetch_babylist_price(url: str):
    soup = BeautifulSoup(_html(url), "lxml")

    # ── 1.  Collect SKU ----------------------------------------------------
    sku = None

    # a) canonical /item/<SKU>
    canonical = soup.find("link", {"rel": "canonical"})
    if canonical and canonical.get("href"):
        m = re.search(r'/item/([^/]+)(?:[/?]|$)', canonical["href"])
        if m:
            sku = m.group(1)

    # b) og:url
    if not sku:
        meta_og = soup.find("meta", {"property": "og:url"})
        if meta_og and meta_og.get("content"):
            m = re.search(r'/item/([^/]+)(?:[/?]|$)', meta_og["content"])
            if m:
                sku = m.group(1)

    # c) JSON-LD
    if not sku:
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string)
                sku = data.get("sku") or data.get("productID")
                if sku:
                    break
            except Exception:
                pass

    # d) NEW — activeProductId in raw HTML
    if not sku:
        m = re.search(r'"activeProductId&quot;:(\d+)', soup.decode())
        if not m:
            m = re.search(r'"activeProductId":(\d+)', soup.text)
        if m:
            sku = m.group(1)

    # ── 2.  Collect price --------------------------------------------------
    box = soup.select_one('div[class^="PriceTag-styles__PriceTag__numerals"]')
    if box:
        price = _clean("".join(box.stripped_strings))
        return price, "USD", sku

    meta = soup.find("meta", {"property": "product:price:amount"})
    if meta:
        cur = soup.find("meta", {"property": "product:price:currency"})
        return float(meta["content"]), (cur["content"] if cur else "USD"), sku

    raise ValueError("Babylist price not found")

# ── domain → extractor map ───────────────────────────────────────────────
DOMAIN_EXTRACTOR = {
    # Amazon
    "amazon.com": fetch_amazon_price, "www.amazon.com": fetch_amazon_price,
    "smile.amazon.com": fetch_amazon_price,
    # Target
    "target.com": fetch_target_price, "www.target.com": fetch_target_price,
    # Walmart
    "walmart.com": fetch_walmart_price, "www.walmart.com": fetch_walmart_price,
    # Babylist
    "babylist.com": fetch_babylist_price, "www.babylist.com": fetch_babylist_price,
}