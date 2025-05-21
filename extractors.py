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
# ── WAYFAIR EXTRACTOR (logger removed) ──────────────────────────────────────
import json
import re
import random
import time
# Removed: from helpers import get_html # Not used
# from helpers import clean_price # Defined inline now
import curl_cffi.requests
from bs4 import BeautifulSoup
from urllib.parse import urlencode
import backoff
import datetime # Added for timestamp

# --- clean_price function (added for completeness) ---
def clean_price(price_input) -> float | None:
    if price_input is None:
        return None
    
    price_str = str(price_input)
    
    match = re.search(r'([\d.,]+)', price_str)
    if not match:
        return None
    
    cleaned_str = match.group(1)
    
    if ',' in cleaned_str and '.' in cleaned_str:
        if cleaned_str.rfind('.') > cleaned_str.rfind(','): 
            cleaned_str = cleaned_str.replace(',', '')
        else: 
            cleaned_str = cleaned_str.replace('.', '').replace(',', '.')
    elif ',' in cleaned_str:
        if cleaned_str.count(',') == 1 and re.search(r',\d{2}$', cleaned_str):
            cleaned_str = cleaned_str.replace(',', '.')
        else:
            cleaned_str = cleaned_str.replace(',', '')
    try:
        price_value = float(cleaned_str)
        return price_value
    except ValueError:
        return None

# --- Silence backoff library's own logging ---
import logging as py_logging # Use a different alias to avoid confusion if 'logging' module is used elsewhere
py_logging.getLogger('backoff').addHandler(py_logging.NullHandler())
py_logging.getLogger('backoff').propagate = False


# --- New print_success function ---
def print_success(method_description: str, price_value: float, currency: str, sku: str):
    """Prints the success message in the desired format."""
    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
    print(f"{current_time} - INFO - {method_description}: {price_value}")
    print(f"({price_value}, '{currency}', '{sku}')")

# Configure exponential backoff for handling rate limits
@backoff.on_exception(backoff.expo, 
                     (curl_cffi.requests.RequestsError, 
                      ConnectionError, 
                      TimeoutError), # Note: curl_cffi might raise RequestsError for timeouts too
                     max_tries=3,
                     jitter=backoff.full_jitter)
def rate_limited_request(url, user_agent, additional_headers=None):
    """Make a request with exponential backoff for rate limiting"""
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.wayfair.com/",
        "sec-ch-ua": '"Not/A)Brand";v="99", "Google Chrome";v="124", "Chromium";v="124"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }
    
    if additional_headers:
        headers.update(additional_headers)
    
    time.sleep(3) # Original delay
    
    try:
        response = curl_cffi.requests.get(
            url,
            impersonate="chrome124",
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 429:
            # This will be caught by backoff due to RequestsError being raised
            time_to_wait = 60 
            time.sleep(time_to_wait)
            raise curl_cffi.requests.RequestsError("Rate limited (429)") # Trigger backoff
            
        return response
    except Exception as e:
        # Removed logger.error, error will be propagated by backoff or Python
        raise

def fetch_wayfair_price(url: str, proxy=None): # proxy parameter is present but not used in rate_limited_request
    """Fetch price from Wayfair with focus on proven approach"""
    sku = extract_sku(url)
    if not sku:
        raise ValueError(f"Could not extract SKU from URL: {url}")
    
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    
    product_name = extract_product_name(url)
    canonical_url = build_canonical_url(sku, product_name)
    
    try:
        price_result = try_direct_fetch(canonical_url, sku, user_agent)
        if price_result:
            return price_result
    except Exception: # Catch generic exception if try_direct_fetch fails internally before returning
        pass # Continue to next method
    
    if url.lower().strip('/') != canonical_url.lower().strip('/'): # Avoid re-fetching if URLs are effectively the same
        try:
            price_result = try_direct_fetch(url, sku, user_agent)
            if price_result:
                return price_result
        except Exception:
            pass
    
    product_url = f"https://www.wayfair.com/product/{sku}"
    if product_url.lower().strip('/') != canonical_url.lower().strip('/') and product_url.lower().strip('/') != url.lower().strip('/'):
        try:
            price_result = try_direct_fetch(product_url, sku, user_agent)
            if price_result:
                return price_result
        except Exception:
            pass
            
    try:
        price_result = try_search_method(url, sku, user_agent)
        if price_result:
            return price_result
    except Exception:
        pass
    
    raise ValueError(f"Wayfair price not found for URL: {url}, SKU: {sku}")

def extract_sku(url):
    patterns = [
        # Original patterns (W-SKUs with 8+ digits)
        r'/pdp/[\w-]+-([A-Za-z]\d{8,})\.html',
        r'/([A-Za-z]\d{8,})\.html',
        r'[/-]([A-Za-z]\d{8,})[/\.]',
        r'[/-]([A-Za-z]\d{8,})$',
        
        # Added specific patterns for 4-letter + 4-number SKUs (exact match)
        r'/pdp/[\w-]+-([A-Za-z]{4}\d{4})\.html',  # Match in product URL with prefix
        r'[/-]([A-Za-z]{4}\d{4})\.html',          # Match in URL paths
        r'[/-]([A-Za-z]{4}\d{4})[/\.]',           # Match with following slash or dot
        r'[/-]([A-Za-z]{4}\d{4})$',               # Match at end of URL
        r'/([A-Za-z]{4}\d{4})\.html',             # Match direct filename
        r'/([A-Za-z]{4}\d{4})$',                  # Match direct path end
        
        # More generic patterns for other SKU formats
        r'/pdp/[\w-]+-([A-Za-z]\d{4,})\.html',
        r'/([A-Za-z]\d{4,})\.html',
        r'[/-]([A-Za-z]\d{4,})[/\.]',
        r'[/-]([A-Za-z]\d{4,})$',
        r'[-/]([A-Za-z]+\d+)\.html$'
    ]
    for pattern in patterns:
        m = re.search(pattern, url, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return None

def extract_product_name(url):
    pdp_match = re.search(r'/pdp/([\w-]+)-[A-Za-z]\d{8,}', url, re.IGNORECASE)
    if pdp_match:
        return pdp_match.group(1)
    parts = url.rstrip('/').split('/')
    if parts:
        last_part = parts[-1]
        product_name = re.sub(r'-[A-Za-z]\d{8,}\.html$', '', last_part)
        if product_name and product_name != last_part:
            return product_name
    return "product" # Default product name

def build_canonical_url(sku, product_name="product"):
    category = "furniture" # Default category
    return f"https://www.wayfair.com/{category}/pdp/{product_name}-{sku.lower()}.html"

def try_direct_fetch(url, sku, user_agent):
    try:
        response = rate_limited_request(url, user_agent)
        
        if response.status_code != 200:
            return None # Silently return None, fetch_wayfair_price will try next method
        
        soup = BeautifulSoup(response.text, "lxml")
        
        # Method 1: __WF_DATA__ blob
        blob = soup.find("script", id="__WF_DATA__")
        if blob and blob.string:
            try:
                data = json.loads(blob.string)
                price_data_path = data.get("props", {}).get("pageProps", {}).get("initialData", {}).get("data", {}).get("product", {}).get("price", {})
                if "value" in price_data_path:
                    price = price_data_path["value"]
                    price_f = float(price)
                    print_success("Extracted price from __WF_DATA__ (direct path)", price_f, "USD", sku)
                    return price_f, "USD", sku
                
                # Fallback recursive search in __WF_DATA__
                price = find_price_in_json(data)
                if price is not None:
                    price_f = float(price)
                    print_success("Extracted price from __WF_DATA__ (recursive)", price_f, "USD", sku)
                    return price_f, "USD", sku
            except Exception:
                pass # Failed to parse or extract from __WF_DATA__
        
        # Method 2: Direct HTML price search
        price_selectors = [
            "span[data-price]", "span[itemprop='price']", 
            "meta[property='product:price:amount']", "meta[itemprop='price']",
            "[data-enzyme-id*='price']", ".StandardPriceBlock", 
            ".PriceBlock", ".SalePrice", ".price"
        ]
        for selector in price_selectors:
            elements = soup.select(selector)
            for el in elements:
                price_str = el.get("data-price") or el.get("content") or el.get_text(strip=True)
                if price_str:
                    try:
                        price_value_cleaned = clean_price(price_str)
                        if price_value_cleaned is not None:
                            description = "Found price in HTML (attribute/content)" if el.get("data-price") or el.get("content") else "Found price in HTML (text)"
                            print_success(description, price_value_cleaned, "USD", sku)
                            return price_value_cleaned, "USD", sku
                        # Check for plain numeric after clean_price failed
                        if re.match(r'^\d+(\.\d+)?$', price_str.strip().lstrip('$')): # Check if it's just a number
                             price_f = float(price_str.strip().lstrip('$'))
                             print_success("Found numeric price in HTML (direct float)", price_f, "USD", sku)
                             return price_f, "USD", sku
                    except Exception:
                        pass # Price conversion failed
        
        # Method 3: JSON-LD
        for script_tag in soup.find_all("script", type="application/ld+json"):
            if script_tag.string:
                try:
                    data = json.loads(script_tag.string)
                    price = find_price_in_json(data) # find_price_in_json handles cleaning
                    if price is not None:
                        price_f = float(price) # find_price_in_json should ideally return float or None
                        print_success("Found price in JSON-LD", price_f, "USD", sku)
                        return price_f, "USD", sku
                except Exception:
                    pass # JSON-LD parsing or extraction failed
        
        return None # No price found by this method
    except Exception: # Catch any error during the direct fetch process itself
        return None


def try_search_method(url, sku, user_agent):
    try:
        product_name = extract_product_name(url).replace('-', ' ')
        search_term = f"{product_name} {sku}"
        encoded_search = urlencode({"keyword": search_term})
        search_url = f"https://www.wayfair.com/keyword.php?{encoded_search}"
        
        response = rate_limited_request(search_url, user_agent)
        
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.text, "lxml")
        product_cards = soup.select("[data-product-id], [data-sku], .ProductCard")
        for card in product_cards:
            card_sku = card.get("data-product-id") or card.get("data-sku")
            if card_sku and card_sku.upper() == sku:
                price_elements = card.select(".SalesPrice, .price, [data-enzyme-id*='price']")
                for el in price_elements:
                    price_text = el.get_text(strip=True)
                    if price_text:
                        price_value = clean_price(price_text)
                        if price_value is not None:
                            print_success("Found price via search", price_value, "USD", sku)
                            return price_value, "USD", sku
    except Exception:
        pass # Search extraction failed
    return None

def find_price_in_json(data, path="", depth=0):
    if depth > 10: return None
        
    if isinstance(data, dict):
        for key in ["currentPrice", "price", "value", "salePrice", "salesPrice", "finalPrice"]:
            if key in data and data[key] is not None:
                price_val = clean_price(data[key]) # clean_price returns float or None
                if price_val is not None: return price_val
        
        priority_keys = ["price", "pricing", "product", "data", "props", "pageProps", "initialData", "offers"]
        for key in priority_keys:
            if key in data:
                result = find_price_in_json(data[key], f"{path}.{key}", depth + 1)
                if result is not None: return result
        for key, value in data.items():
            if key not in priority_keys:
                result = find_price_in_json(value, f"{path}.{key}", depth + 1)
                if result is not None: return result
    elif isinstance(data, list):
        for i, item in enumerate(data[:10]): # Limit list iteration
            result = find_price_in_json(item, f"{path}[{i}]", depth + 1)
            if result is not None: return result
    return None

# --- Example Usage (Optional - for testing) ---
if __name__ == '__main__':
    test_urls = [
        # Replace with actual Wayfair product URLs you want to test
        # "https://www.wayfair.com/furniture/pdp/zipcode-design-denna-armless-accent-chair-w004906494.html",
        "https://www.wayfair.com/lighting/pdp/mercury-row-yearby-2-light-dimmable-vanity-light-w005639500.html",
        "https://www.wayfair.com/furniture/pdp/latitude-run-sovremennoj-knopkoj-s-pugovicami-s-obivkoj-iz-lnjanoj-tkani-s-podushkami-w011415677.html",
    ]

    for product_url in test_urls:
        print(f"\n--- Processing URL: {product_url} ---")
        try:
            # The print_success function is called internally by fetch_wayfair_price or its sub-functions
            result_tuple = fetch_wayfair_price(product_url)
            if not result_tuple: # Should be caught by ValueError, but as a fallback
                 print(f"Failed to fetch price for {product_url}")
            # result_tuple contains (price, currency, sku) if needed for further programmatic use
        except ValueError as e:
            # This catches "Could not extract SKU" or "Wayfair price not found"
            print(f"ERROR: {e}") 
        except curl_cffi.requests.RequestsError as e:
            print(f"REQUESTS_ERROR: All retries failed for {product_url} - {e}")
        except Exception as e:
            import traceback
            print(f"UNEXPECTED_ERROR for {product_url}: {e}")
            traceback.print_exc()
        print("--------------------------------------")
        time.sleep(random.uniform(2, 5)) # Delay between processing different products
# ── HOME DEPOT via Playwright (fixed waits) ───────────────────────────────
import re, json, time
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def fetch_homedepot_price(url: str):
    """
    1) Strip query & fragment → canonical PDP
    2) Stealth‐Chrome to load real HTML
    3) Parse the server blob or JSON‐LD, etc.
    Returns (price, currency, sku)
    """
    # ── 1️⃣ Derive the clean PDP URL ────────────────────────────────
    base = url.split("?", 1)[0].split("#", 1)[0]

    # ── 2️⃣ Launch stealth Chrome and load that base URL ─────────────
    import time, json, re
    import undetected_chromedriver as uc
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    opts = uc.ChromeOptions()
    opts.headless = True
    driver = uc.Chrome(options=opts)
    try:
        driver.get(base)
        # give the JS challenge + hydration 5 s
        time.sleep(5)
        html = driver.page_source
    finally:
        try: driver.quit()
        except: pass

    soup = BeautifulSoup(html, "lxml")

    # ── 3️⃣ Parse the JSON blob you already know works ─────────────────
    srv = soup.select_one("#thd-helmet__script--productStructureData")
    if srv and srv.string:
        data   = json.loads(srv.string)
        offers = data.get("offers", {}) or {}
        price  = offers.get("price")
        cur    = offers.get("priceCurrency", "USD")
        sku    = data.get("sku") or data.get("productID")
        if price is not None:
            return float(price), cur, sku

    # ── 4️⃣ Fallback to JSON‐LD ───────────────────────────────────────
    for ld in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(ld.string)
            if isinstance(d, list):
                d = next((x for x in d if x.get("@type")=="Product"), {})
            if d.get("@type")=="Product":
                offers = d.get("offers", {}) or {}
                if isinstance(offers, list):
                    offers = offers[0]
                price = offers.get("price")
                cur   = offers.get("priceCurrency", "USD")
                sku   = d.get("sku") or d.get("productID")
                if price is not None:
                    return float(price), cur, sku
        except:
            continue

    # ── 5️⃣ Last‐resort regex ─────────────────────────────────────────
    m = re.search(r"\$(\d{1,3}(?:,\d{3})*(?:\.\d{2}))", html)
    if m:
        return float(m.group(1).replace(",", "")), "USD", None

    raise ValueError(f"Home Depot price not found for URL: {url}")
import re
import time
from curl_cffi import requests
from helpers    import _clean

def fetch_mybobs_price(url: str):
    """
    1) Grab the PID from the /p/<pid> URL segment
    2) Call the exact same core.dxpapi.com search API as in bobs loop.py
    3) Return (price: float, 'USD', sku: str)
    """
    # 1️⃣ extract PID
    m = re.search(r'/p/(\d+)', url)
    if not m:
        raise ValueError(f"Could not find product ID in URL: {url}")
    pid = m.group(1)

    # 2️⃣ call DXP search API with *all* the original params :contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}
    api = "https://core.dxpapi.com/api/v1/core/"
    params = {
        "account_id":    "6804",
        "domain_key":    "mybobs",
        "auth_key":      "78zkm2v43h9aggad",
        "view_id":       "30003210",
        "request_id":    str(int(time.time() * 1000)),
        "_br_uid_2":     "",
        "url":           "mybobs.com",
        "ref_url":       "https://www.google.com/",
        "request_type":  "search",
        "fl":            (
            "pid,code,title,brand,price,sale_price,promotions,"
            "thumb_image,sku_thumb_images,sku_swatch_images,sku_color_group,"
            "sku_price,sku_finish,sku_color,sku_sale_price,url,price_range,"
            "sale_price_range,description,is_live,score,variant_title,"
            "variant_url,color,finance_eligible,finance_per_month,"
            "finance_no_of_payments,badges,outlet,clearance,original_price,"
            "yotpo_average_rating,yotpo_number_of_reviews,price_map,"
            "special_delivery_fee_indicator,price_zone4,finance_map,"
            "strikethrough_prices_map,badges_zone4"
        ),
        "realm":         "prod",
        "facet":         "true",
        "stats.field":   "price_zone4",
        "search_type":   "keyword",
        "rows":          "1",       # we only need the single product
        "start":         "0",
        "sort":          "",
        "segment":       "customer_geo:501",
        "fq":            'warehouse:("30003210")',
        "q":             pid,
    }
    headers = {"User-Agent": "insomnia/10.0.0"}

    resp = requests.get(api, params=params, headers=headers, timeout=20)
    resp.raise_for_status()  # now returns 200 instead of 400
    data = resp.json()

    # 3️⃣ pull out first doc
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        raise ValueError(f"No product data for PID {pid}")
    doc = docs[0]

    raw_price = doc.get("price")
    if raw_price is None:
        raise ValueError(f"No price in API response for PID {pid}")

    sku   = doc.get("code") or pid
    price = _clean(raw_price)

    return price, "USD", sku

# in extractors.py
import re
import json
import time
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.expected_conditions import any_of


from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException

from webdriver_manager.chrome import ChromeDriverManager
def fetch_ashley_price(url: str):
    """
    Uses Selenium to render any client-side JS (including CF’s “press & hold”),
    then extracts:
      1) schema.org JSON-LD
      2) microdata itemprop="price"
      3) OpenGraph meta price tags
      4) regex fallback over rendered HTML
    Returns (price: float, currency: str, sku: str)
    """
    # 1️⃣ Canonical URL (strip query params & fragments)
    base = url.split("?", 1)[0].split("#", 1)[0]

    # 2️⃣ Launch Selenium-managed Chrome
    chrome_options = Options()
    chrome_options.headless = True
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(base)

        # 2a️⃣ detect & solve Cloudflare “press & hold” slider if present
        try:
            knob = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".cf-browser-verification__button"))
            )
            # drag it all the way to the right
            ActionChains(driver) \
                .click_and_hold(knob) \
                .pause(1.0) \
                .move_by_offset(300, 0) \
                .release() \
                .perform()
        except (TimeoutException):
            # no slider appeared in 5s, move on
            pass

        # 2b️⃣ now wait up to 10s for a JSON-LD <script> (real PDP content)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "script[type='application/ld+json']"))
        )
        time.sleep(2)      # give any final JS a moment to finish
        html = driver.page_source

    finally:
        try:
            driver.quit()
        except:
            pass

    soup = BeautifulSoup(html, "lxml")

    # helper: extract SKU from URL
    sku_match = re.search(r"/([^/]+)\.html$", base)
    sku       = sku_match.group(1) if sku_match else ""

    # 3️⃣ Try schema.org JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string)
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") == "Product"), {})
            if data.get("@type") == "Product":
                offers = data.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0]
                price = offers.get("price")
                cur   = offers.get("priceCurrency", "USD")
                if price is not None:
                    return float(price), cur, sku
        except Exception:
            continue

    # 4️⃣ Microdata fallback
    price_tag = soup.find(attrs={"itemprop": "price"})
    if price_tag:
        raw = price_tag.get("content") or price_tag.get_text()
        try:
            price   = float(re.sub(r"[^\d.]", "", raw))
            cur_tag = soup.find(attrs={"itemprop": "priceCurrency"})
            cur     = cur_tag.get("content") if cur_tag and cur_tag.get("content") else "USD"
            return price, cur, sku
        except:
            pass

    # 5️⃣ OpenGraph meta fallback
    meta_amt = soup.find("meta", {"property": "product:price:amount"})
    if meta_amt and meta_amt.get("content"):
        price     = float(meta_amt["content"])
        meta_cur  = soup.find("meta", {"property": "product:price:currency"})
        cur       = meta_cur["content"] if meta_cur and meta_cur.get("content") else "USD"
        return price, cur, sku

    # 6️⃣ Regex last resort
    m = re.search(r"\$(\d{1,3}(?:,\d{3})*(?:\.\d{2}))", html)
    if m:
        return float(m.group(1).replace(",", "")), "USD", sku

    raise ValueError(f"Ashley price not found for URL: {url}")


# ---------- LIVING SPACES extractor via Selenium ----------
def fetch_livingspaces_price(url: str):
    """
    1) Strip query/fragment → canonical PDP
    2) GET HTML via _html()
    3) Parse utag_data JS blob for product_price & product_id
    4) Fallback: meta[itemprop=price] + meta[itemprop=priceCurrency]
    Returns (price: float, 'USD', sku: str)
    """
    # 1️⃣ canonical URL
    base = url.split("?", 1)[0].split("#", 1)[0]

    # 2️⃣ fetch HTML
    html = _html(base)
    soup = BeautifulSoup(html, "lxml")

    # 3️⃣ utag_data JS blob
    m = re.search(r"utag_data\s*=\s*(\{.*?\});", html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            prices = data.get("product_price") or []
            if isinstance(prices, list) and prices:
                price = float(prices[0])
                ids = data.get("product_id") or []
                sku   = str(ids[0]) if isinstance(ids, list) and ids else ""
                return price, "USD", sku
        except Exception:
            pass

    # 4️⃣ meta tags fallback
    price_meta = soup.find("meta", {"itemprop": "price"})
    cur_meta   = soup.find("meta", {"itemprop": "priceCurrency"})
    if price_meta and price_meta.get("content"):
        try:
            price = float(price_meta["content"])
            cur   = cur_meta.get("content", "USD") if cur_meta else "USD"
            # SKU from URL segment (last numeric chunk)
            m2 = re.search(r"-(\d+)$", base)
            sku = m2.group(1) if m2 else ""
            return price, cur, sku
        except:
            pass

    raise ValueError(f"Living Spaces price not found for URL: {url}")
# ── BEST BUY extractor via Playwright + stealth ─────────────────────────────
import re
import time
import json
import logging
import random
from typing import Tuple, Optional, Dict, Any, Union
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# List of common user agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 Edg/116.0.1938.62",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
]

class BestBuyPriceScraper:
    """A robust scraper for fetching Best Buy product information."""
    
    def __init__(self, headless: bool = True, timeout: int = 15):
        """
        Initialize the scraper with configurable options.
        
        Args:
            headless: Whether to run Chrome in headless mode
            timeout: Maximum time to wait for page elements in seconds
        """
        self.headless = headless
        self.timeout = timeout
        self.driver = None
    
    def _setup_driver(self) -> None:
        """Set up the undetected Chrome driver with anti-detection measures."""
        opts = uc.ChromeOptions()
        opts.headless = self.headless
        
        # Enhanced anti-detection measures
        opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        
        # Note: We skip experimental options as they're causing compatibility issues
        # with specific versions of undetected_chromedriver
        
        try:
            self.driver = uc.Chrome(options=opts)
            # Execute stealth JS to avoid detection
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
        except Exception as e:
            logger.error(f"Failed to initialize Chrome driver: {e}")
            raise
    
    def _close_driver(self) -> None:
        """Safely close the Chrome driver."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.warning(f"Error closing driver: {e}")
            finally:
                self.driver = None
    
    def _canonicalize_url(self, url: str) -> str:
        """
        Canonicalize the Best Buy URL by removing query parameters and fragments.
        Ensures the URL points to the product page.
        
        Args:
            url: The raw Best Buy product URL
            
        Returns:
            Cleaned canonical URL
        """
        # Remove query parameters and fragments
        base_url = url.split("?", 1)[0].split("#", 1)[0]
        
        # Validate it's a Best Buy product URL and has a product ID
        if not re.search(r'bestbuy\.com.*?/\d+\.p', base_url):
            raise ValueError(f"URL does not appear to be a valid Best Buy product page: {url}")
            
        return base_url
    
    def _extract_sku_from_url(self, url: str) -> Optional[str]:
        """Extract the product SKU from the URL."""
        m = re.search(r"/(\d+)\.p", url)
        return m.group(1) if m else None
    
    def _extract_from_hero_price(self, soup: BeautifulSoup) -> Optional[Tuple[float, str]]:
        """
        Extract price from the hero price element.
        
        Returns:
            Tuple of (price, currency) or None if not found
        """
        # Try multiple selectors as Best Buy occasionally changes their DOM
        selectors = [
            "div.priceView-hero-price span",
            "div.priceView-customer-price span",
            "div[data-testid='customer-price'] span",
            ".priceView-desktop-price span"
        ]
        
        for selector in selectors:
            hero = soup.select_one(selector)
            if hero and hero.get_text(strip=True):
                txt = hero.get_text(strip=True)
                # Remove currency symbol and commas, then convert to float
                try:
                    price = float(re.sub(r'[^\d.]', '', txt))
                    return price, "USD"
                except ValueError:
                    continue
                    
        return None
    
    def _extract_from_json_ld(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        Extract product data from JSON-LD script tags.
        
        Returns:
            Dictionary containing product data or None if not found
        """
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string)
                
                # Handle array of JSON-LD objects
                if isinstance(data, list):
                    data = next((d for d in data if d.get("@type") == "Product"), {})
                
                if data.get("@type") == "Product":
                    result = {}
                    
                    # Extract offers information
                    offers = data.get("offers", {}) or {}
                    if isinstance(offers, list) and offers:
                        offers = offers[0]
                    
                    # Get price and currency
                    price = offers.get("price")
                    currency = offers.get("priceCurrency", "USD")
                    
                    if price is not None:
                        try:
                            result["price"] = float(price)
                            result["currency"] = currency
                        except (ValueError, TypeError):
                            continue
                    
                    # Extract additional product data
                    result["name"] = data.get("name")
                    result["sku"] = data.get("sku") or data.get("mpn") or data.get("skuId")
                    result["brand"] = data.get("brand", {}).get("name") if isinstance(data.get("brand"), dict) else data.get("brand")
                    result["availability"] = offers.get("availability")
                    
                    # Only return if we have at least price and currency
                    if "price" in result and "currency" in result:
                        return result
                        
            except Exception as e:
                logger.debug(f"Error parsing JSON-LD: {e}")
                continue
                
        return None
    
    def _extract_from_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract additional product metadata from the page."""
        result = {}
        
        # Try to get product name
        title_tag = soup.find("title")
        if title_tag:
            result["title"] = title_tag.get_text(strip=True).replace(" - Best Buy", "")
        
        # Try to get product image
        og_image = soup.find("meta", property="og:image")
        if og_image:
            result["image_url"] = og_image.get("content")
            
        # Try to get product category
        breadcrumbs = soup.select("ol.c-breadcrumbs a")
        if breadcrumbs and len(breadcrumbs) > 1:
            result["category"] = breadcrumbs[-2].get_text(strip=True)
            
        return result
        
    def _check_availability(self, soup: BeautifulSoup) -> Dict[str, bool]:
        """
        Check if the product is available for purchase.
        
        Returns:
            Dictionary with availability status
        """
        result = {
            "in_stock": False,
            "purchasable": False
        }
        
        # Check for in-stock indicators
        add_to_cart = soup.select_one("button.add-to-cart-button")
        if add_to_cart and "disabled" not in add_to_cart.get("class", []):
            result["purchasable"] = True
            result["in_stock"] = True
            return result
            
        # Check for out-of-stock indicators
        sold_out = soup.select_one("button.sold-out")
        if sold_out:
            return result
            
        # Check shop-buttons area for status
        shop_buttons = soup.select_one("div.fulfillment-add-to-cart-button")
        if shop_buttons and "btn-disabled" not in shop_buttons.get_text():
            result["in_stock"] = True
            result["purchasable"] = True
            
        return result
        
    def fetch_price(self, url: str) -> Tuple[float, str, str]:
        """
        Fetch the price of a Best Buy product.
        
        Args:
            url: The Best Buy product URL
            
        Returns:
            Tuple of (price, currency, sku)
            
        Raises:
            ValueError: If the price cannot be found
        """
        try:
            return self.fetch_product_info(url)["price"], "USD", self.fetch_product_info(url)["sku"]
        except Exception as e:
            logger.error(f"Error fetching price: {e}")
            raise ValueError(f"BestBuy price not found for URL: {url}")
        
    def fetch_product_info(self, url: str) -> Dict[str, Any]:
        """
        Fetch comprehensive product information from Best Buy.
        
        Args:
            url: The Best Buy product URL
            
        Returns:
            Dictionary containing product information including:
            - price: float
            - currency: str
            - sku: str
            - name: str (if available)
            - brand: str (if available)
            - availability: dict with in_stock and purchasable statuses
            - image_url: str (if available)
            - category: str (if available)
            
        Raises:
            ValueError: If product information cannot be retrieved
        """
        canonical_url = self._canonicalize_url(url)
        sku_from_url = self._extract_sku_from_url(canonical_url)
        
        try:
            self._setup_driver()
            
            # Load the page with retry mechanism
            for attempt in range(3):
                try:
                    logger.info(f"Loading URL (attempt {attempt+1}): {canonical_url}")
                    self.driver.get(canonical_url)
                    
                    # Wait for the price element to be present
                    try:
                        WebDriverWait(self.driver, self.timeout).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "div.priceView-hero-price, div.priceView-customer-price"))
                        )
                    except TimeoutException:
                        # If we can't find the price element, at least wait for page to load
                        WebDriverWait(self.driver, self.timeout).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )
                        # Add a small delay for any JS to finish rendering
                        time.sleep(random.uniform(1, 2))
                    
                    # Get the page source and parse with BeautifulSoup
                    html = self.driver.page_source
                    soup = BeautifulSoup(html, "html.parser")
                    
                    # Prepare the result with the SKU from URL as fallback
                    result = {"sku": sku_from_url}
                    
                    # Try to get price from various sources
                    hero_price = self._extract_from_hero_price(soup)
                    if hero_price:
                        result["price"] = hero_price[0]
                        result["currency"] = hero_price[1]
                        
                    # Try to extract from JSON-LD as an alternative/supplement
                    json_ld_data = self._extract_from_json_ld(soup)
                    if json_ld_data:
                        # Use JSON-LD data where we don't already have info
                        for key, value in json_ld_data.items():
                            if value and (key not in result or not result[key]):
                                result[key] = value
                    
                    # Check if we have the essential price information
                    if "price" not in result or result["price"] is None:
                        if attempt < 2:
                            logger.warning(f"Price not found, retrying (attempt {attempt+1})")
                            time.sleep(random.uniform(2, 4))
                            continue
                        else:
                            raise ValueError("Price not found after multiple attempts")
                    
                    # Get additional metadata
                    metadata = self._extract_from_metadata(soup)
                    for key, value in metadata.items():
                        if key not in result or not result[key]:
                            result[key] = value
                    
                    # Check availability
                    result["availability"] = self._check_availability(soup)
                    
                    return result
                    
                except (TimeoutException, WebDriverException) as e:
                    if attempt < 2:
                        logger.warning(f"Browser error on attempt {attempt+1}: {e}")
                        # Close and reopen the browser
                        self._close_driver()
                        self._setup_driver()
                    else:
                        raise
            
            raise ValueError(f"Failed to retrieve product information after multiple attempts")
            
        except Exception as e:
            logger.error(f"Error fetching product info: {e}")
            raise
            
        finally:
            self._close_driver()


def fetch_bestbuy_price(url: str) -> Tuple[float, str, str]:
    """
    Fetch the price, currency, and SKU of a Best Buy product.
    
    Args:
        url: The Best Buy product URL
        
    Returns:
        Tuple of (price, currency, sku)
        
    Raises:
        ValueError: If the price cannot be found
    """
    scraper = BestBuyPriceScraper(headless=True)
    return scraper.fetch_price(url)


# Example usage
if __name__ == "__main__":
    try:
        # Sample Best Buy product URL
        url = "https://www.bestbuy.com/site/sony-playstation-5-slim-disc-console/6574179.p"
        
        # Basic price fetch
        price, currency, sku = fetch_bestbuy_price(url)
        print(f"Price: ${price} {currency}, SKU: {sku}")
        
        # Comprehensive product info
        scraper = BestBuyPriceScraper()
        product_info = scraper.fetch_product_info(url)
        print(f"\nComprehensive product info:")
        for key, value in product_info.items():
            print(f"{key}: {value}")
            
    except Exception as e:
        print(f"Error: {e}")

#Lowes
import re
import json
from bs4 import BeautifulSoup
from helpers import _html, _clean

def fetch_lowes_price(url: str):
    """
    1) Strip off any query-string or fragment
    2) GET HTML via your _html() helper
    3) Try schema.org JSON-LD for Product → offers.price
    4) Fallback to <meta property="product:price:amount"/>
    5) Last resort: regex for "price":123.45 in the payload
    Returns (price: float, currency: str, sku: str)
    """
    # 1️⃣ canonical URL
    base = url.split("?",1)[0].split("#",1)[0]

    # 2️⃣ fetch
    html = _html(base)
    soup = BeautifulSoup(html, "lxml")

    # 3️⃣ JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
            # sometimes it's a list of records
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") == "Product"), {})
            if data.get("@type") == "Product":
                offers = data.get("offers", {}) or {}
                if isinstance(offers, list):
                    offers = offers[0]
                raw_price = offers.get("price")
                if raw_price is not None:
                    price = float(raw_price)
                    cur   = offers.get("priceCurrency", "USD")
                    sku   = data.get("sku") or data.get("mpn") or ""
                    return price, cur, str(sku)
        except Exception:
            continue

    # 4️⃣ <meta> fallback
    meta_amt = soup.find("meta", {"property": "product:price:amount"})
    if meta_amt and meta_amt.get("content"):
        price = _clean(meta_amt["content"])
        meta_cur = soup.find("meta", {"property": "product:price:currency"})
        cur   = (meta_cur["content"] if meta_cur and meta_cur.get("content") else "USD")
        # SKU: last numeric segment of the path
        m = re.search(r"/(\d+)$", base)
        sku = m.group(1) if m else ""
        return price, cur, sku

    # 5️⃣ Regex last-resort
    m2 = re.search(r'"price"\s*:\s*([\d.]+)', html)
    if m2:
        price = float(m2.group(1))
        # try to find a sku field in the blob
        m3 = re.search(r'"sku"\s*:\s*"([^"]+)"', html)
        if m3:
            sku = m3.group(1)
        else:
            # fallback to URL segment
            m = re.search(r"/(\d+)$", base)
            sku = m.group(1) if m else ""
        return price, "USD", sku

    raise ValueError(f"Lowe's price not found for URL: {url}")


#Raymour
import re
import json
from bs4 import BeautifulSoup
from helpers import _html, _clean

def fetch_raymour_price(url: str):
    """
    Raymour & Flanigan PDP scraper:
      1) canonicalize URL
      2) GET via _html()
      3) JSON-LD Product → offers.price
      4) fallback: .price-sales span
      5) fallback: regex $xxx.xx
    Returns (price: float, 'USD', sku: str)
    """
    # 1️⃣ strip off query/fragments
    base = url.split('?',1)[0].split('#',1)[0]

    # 2️⃣ pull numeric SKU off the end
    sku_m = re.search(r'-(\d+)$', base)
    sku   = sku_m.group(1) if sku_m else ''

    # 3️⃣ fetch & parse
    html = _html(base)
    soup = BeautifulSoup(html, 'lxml')

    # 4️⃣ try JSON-LD
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            # if it’s an array, pick the Product object
            if isinstance(data, list):
                data = next((d for d in data if d.get('@type')=='Product'), {})
            if data.get('@type') == 'Product':
                offers = data.get('offers') or {}
                if isinstance(offers, list):
                    offers = offers[0]
                raw = offers.get('price')
                if raw is not None:
                    return float(raw), offers.get('priceCurrency','USD'), sku
        except Exception:
            continue

    # 5️⃣ fallback: look for <span class="price-sales">
    sale = soup.select_one('span.price-sales, .price-sales')
    if sale and sale.get_text(strip=True):
        price = _clean(sale.get_text())
        return price, 'USD', sku

    # 6️⃣ last-resort regex
    m = re.search(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2}))', html)
    if m:
        return float(m.group(1).replace(',','')), 'USD', sku

    raise ValueError(f"Raymour price not found for URL: {url}")

#Crate
import re
import json
from bs4 import BeautifulSoup
from helpers import _html, _clean

def fetch_crateandbarrel_price(url: str):
    """
    Crate & Barrel PDP scraper:
      1) Canonicalize URL
      2) GET HTML via _html()
      3) Try schema.org JSON-LD for Product → offers.price
      4) Fallback: <meta property="product:price:amount">
      5) Fallback: span.price or .price-display
      6) Regex last-resort for $xx.xx
    Returns (price: float, 'USD', sku: str)
    """
    # 1️⃣ strip off any query or fragment
    base = url.split('?',1)[0].split('#',1)[0]

    # 2️⃣ fetch the page
    html = _html(base)
    soup = BeautifulSoup(html, 'lxml')

    # 3️⃣ JSON-LD
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or '{}')
            # if list, find the Product
            if isinstance(data, list):
                data = next((d for d in data if d.get('@type')=='Product'), {})
            if data.get('@type') == 'Product':
                offers = data.get('offers') or {}
                if isinstance(offers, list):
                    offers = offers[0]
                raw_price = offers.get('price')
                if raw_price is not None:
                    cur = offers.get('priceCurrency','USD')
                    # sku may live on the product
                    sku = data.get('sku') or data.get('mpn') or ''
                    return float(raw_price), cur, str(sku)
        except Exception:
            continue

    # 4️⃣ meta tag fallback
    m_amt = soup.find('meta', {'property':'product:price:amount'})
    if m_amt and m_amt.get('content'):
        price = _clean(m_amt['content'])
        m_cur = soup.find('meta', {'property':'product:price:currency'})
        cur   = m_cur['content'] if m_cur and m_cur.get('content') else 'USD'
        # sku from URL path
        m_sku = re.search(r'/s(\d+)', base)
        sku   = m_sku.group(1) if m_sku else ''
        return price, cur, sku

    # 5️⃣ common price span
    span = soup.select_one('span.price, .price-display')
    if span and span.get_text(strip=True):
        price = _clean(span.get_text())
        m_sku = re.search(r'/s(\d+)', base)
        sku   = m_sku.group(1) if m_sku else ''
        return price, 'USD', sku

    # 6️⃣ regex fallback
    m = re.search(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2}))', html)
    if m:
        price = float(m.group(1).replace(',',''))
        m_sku = re.search(r'/s(\d+)', base)
        sku   = m_sku.group(1) if m_sku else ''
        return price, 'USD', sku

    raise ValueError(f"Crate&Barrel price not found for URL: {url}")

#Dollar Tree
import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from helpers import _html, _clean

def fetch_dollartree_price(url: str):
    """
    Dollar Tree PDP scraper, updated SKU logic:
      1) canonicalize URL
      2) GET via _html()
      3) JSON-LD → offers.price + sku/productID
      4) <meta> → price + URL segment SKU
      5) itemprop → price + URL segment SKU
      6) regex → price + URL segment SKU
    """
    # 1️⃣ canonical URL
    base = url.split("?",1)[0].split("#",1)[0]

    # 2️⃣ fetch
    html = _html(base)
    soup = BeautifulSoup(html, "lxml")

    # helper: always grab last non-empty path segment as SKU
    path = urlparse(base).path
    segments = [seg for seg in path.split("/") if seg]
    url_sku  = segments[-1] if segments else ""

    # 3️⃣ JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type")=="Product"), {})
            if data.get("@type")=="Product":
                offers = data.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0]
                raw = offers.get("price")
                if raw is not None:
                    cur = offers.get("priceCurrency","USD")
                    sku = data.get("sku") or data.get("productID") or url_sku
                    return float(raw), cur, str(sku)
        except:
            continue

    # 4️⃣ meta tag fallback
    meta_amt = soup.find("meta", {"property":"product:price:amount"})
    if meta_amt and meta_amt.get("content"):
        price    = _clean(meta_amt["content"])
        meta_cur = soup.find("meta", {"property":"product:price:currency"})
        cur      = meta_cur["content"] if meta_cur and meta_cur.get("content") else "USD"
        return price, cur, url_sku

    # 5️⃣ microdata fallback
    price_tag = soup.find(attrs={"itemprop":"price"})
    if price_tag:
        raw      = price_tag.get("content") or price_tag.get_text()
        price    = _clean(raw)
        cur_tag  = soup.find(attrs={"itemprop":"priceCurrency"})
        cur      = cur_tag.get("content") if cur_tag and cur_tag.get("content") else "USD"
        return price, cur, url_sku

    # 6️⃣ regex fallback
    m2 = re.search(r"\$(\d{1,3}(?:\.\d{2}))", html)
    if m2:
        return float(m2.group(1)), "USD", url_sku

    raise ValueError(f"Dollar Tree price not found for URL: {url}")

#West Elm
def fetch_westelm_price(url: str):
    """
    1) Strip query/fragment from URL
    2) GET HTML via _html()
    3) Extract the internal 'skus' JSON blob
    4) Parse it, collect all variants' sellingPrice
    5) Return the lowest sellingPrice and its SKU
    6) Fallback: schema.org JSON-LD
    7) Fallback: simple price regex
    """
    # 1️⃣ canonicalize URL
    base = url.split("?",1)[0].split("#",1)[0]

    # 2️⃣ fetch HTML
    html = _html(base)

    # 3️⃣ locate and extract 'skus' JSON object
    skus_idx = html.find('"skus":')
    if skus_idx != -1:
        start = html.find('{', skus_idx)
        if start != -1:
            count = 0
            for i in range(start, len(html)):
                if html[i] == '{': count += 1
                elif html[i] == '}': count -= 1
                if count == 0:
                    end = i + 1
                    break
            else:
                end = None
            if end:
                skus_text = html[start:end]
                try:
                    skus_dict = json.loads(skus_text)
                    variants = []
                    for sku_id, info in skus_dict.items():
                        price_info = info.get('price', {})
                        sp = price_info.get('sellingPrice')
                        if sp is not None:
                            variants.append((float(sp), sku_id))
                    if variants:
                        low_price, low_sku = min(variants, key=lambda x: x[0])
                        return low_price, 'USD', low_sku
                except json.JSONDecodeError:
                    pass

    # 4️⃣ JSON-LD fallback
    soup = BeautifulSoup(html, 'lxml')
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or '{}')
            if isinstance(data, list):
                data = next((d for d in data if d.get('@type')=='Product'), {})
            if data.get('@type') == 'Product':
                offers = data.get('offers') or {}
                if isinstance(offers, list): offers = offers[0]
                raw = offers.get('price')
                if raw is not None:
                    sku = data.get('sku') or data.get('mpn') or ''
                    return float(raw), offers.get('priceCurrency','USD'), sku
        except:
            continue

    # 5️⃣ regex fallback
    m = re.search(r"\$(\d{1,3}(?:,\d{3})*\.\d{2})", html)
    if m:
        return float(m.group(1).replace(',', '')), 'USD', ''

    raise ValueError(f"West Elm price not found for URL: {url}")

#At Home

# In extractors.py, add imports up top:
import re
import json
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from helpers import _html, _clean

def fetch_athome_price(url: str):
    """
    1) Canonicalize URL (strip ?…#…)
    2) GET HTML via _html()
    3) Try JSON-LD <script type="application/ld+json">
    4) Fallback: <meta property="product:price:amount">
    5) Fallback: microdata itemprop="price"
    6) Last-resort regex for $xx.xx
    Returns (price: float, currency: str, sku: str)
    """
    # 1️⃣ Canonical URL
    base = url.split("?",1)[0].split("#",1)[0]

    # 1b) SKU = last numeric path segment
    path = urlparse(base).path.rstrip("/")
    sku  = path.split("/")[-1]

    # 2️⃣ Fetch page
    html = _html(base)
    soup = BeautifulSoup(html, "lxml")

    # 3️⃣ JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type")=="Product"), {})
            if data.get("@type") == "Product":
                offers = data.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0]
                raw = offers.get("price") or offers.get("priceCurrency") and offers.get("price") 
                if raw is not None:
                    cur = offers.get("priceCurrency", "USD")
                    return float(raw), cur, sku
        except:
            continue

    # 4️⃣ <meta> tags
    m_amt = soup.find("meta", {"property":"product:price:amount"})
    if m_amt and m_amt.get("content"):
        price = _clean(m_amt["content"])
        m_cur = soup.find("meta", {"property":"product:price:currency"})
        cur   = m_cur["content"] if m_cur and m_cur.get("content") else "USD"
        return price, cur, sku

    # 5️⃣ microdata
    tag_p = soup.find(attrs={"itemprop":"price"})
    if tag_p:
        raw = tag_p.get("content") or tag_p.get_text()
        price = _clean(raw)
        tag_c = soup.find(attrs={"itemprop":"priceCurrency"})
        cur   = tag_c.get("content") if tag_c and tag_c.get("content") else "USD"
        return price, cur, sku

    # 6️⃣ regex fallback
    m = re.search(r"\$(\d{1,3}(?:,\d{3})*\.\d{2})", html)
    if m:
        return float(m.group(1).replace(",","")), "USD", sku

    raise ValueError(f"AtHome price not found for URL: {url}")

# Matress Firm
def fetch_mattressfirm_price(url: str):
    """
    Extract the price of the Queen variant from a Mattress Firm product page
    
    1) Strip query/fragment to get base URL
    2) Fetch HTML
    3) Extract variants data matching the exact format seen on Mattress Firm
    4) Find the Queen variant by exact matching with size="Queen"
    5) Multiple fallbacks if the main approach fails
    
    Returns (price: float, currency: str, sku: str)
    """
    import json
    import re
    from urllib.parse import urlparse, parse_qs
    from bs4 import BeautifulSoup
    
    # Helper function for HTML fetching (needs to be implemented)
    def _html(url):
        # Your existing implementation
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        return response.text
    
    # 1️⃣ Canonicalize URL
    base = url.split("?", 1)[0].split("#", 1)[0]
    
    # Get the variant ID if present in URL
    query_params = parse_qs(urlparse(url).query)
    target_variant_id = query_params.get('variantid', [None])[0]
    
    # 2️⃣ Fetch HTML
    html = _html(base)
    
    # 3️⃣ Look for exact format seen in the JSON blob provided
    # First, look for the "sizes" array with objects containing "size":"Queen"
    sizes_array_pattern = re.search(r'(\[{"id":"[^"]+","title":"[^"]+","size":"[^"]+".*?"variants":)', html, re.DOTALL)
    if sizes_array_pattern:
        # Get the full array by finding the opening [ and matching closing ]
        start_idx = sizes_array_pattern.start(1)
        
        # Count brackets to find the closing bracket of the array
        count = 0
        for i in range(start_idx, len(html)):
            if html[i] == '[': 
                count += 1
            elif html[i] == ']': 
                count -= 1
                if count == 0:
                    end_idx = i + 1
                    break
        
        if 'end_idx' in locals():
            try:
                # Extract the array and add closing bracket to make valid JSON
                array_json = html[start_idx:end_idx]
                # Try to parse it with some adjustments if needed
                if not array_json.endswith(']'):
                    array_json += ']'
                
                # Look for a complete subset that's valid JSON
                for end_pos in range(len(array_json), 0, -1):
                    try:
                        partial_json = array_json[:end_pos]
                        if partial_json.count('[') == partial_json.count(']'):
                            variants = json.loads(partial_json)
                            break
                    except json.JSONDecodeError:
                        continue
                
                # Look for Queen size in the variants
                if 'variants' in locals():
                    for variant in variants:
                        if isinstance(variant, dict) and variant.get('size') == 'Queen':
                            price = variant.get('price')
                            variant_id = variant.get('variantId')
                            if price is not None and variant_id is not None:
                                return float(price), 'USD', str(variant_id)
            except (json.JSONDecodeError, ValueError):
                pass
    
    # 4️⃣ Direct search for the Queen variant object
    queen_pattern = re.search(r'{"id":"Queen","title":"Queen","size":"Queen","variantId":(\d+),"price":(\d+\.\d+)', html)
    if queen_pattern:
        try:
            variant_id = queen_pattern.group(1)
            price = float(queen_pattern.group(2))
            return price, 'USD', variant_id
        except (ValueError, IndexError):
            pass
    
    # 5️⃣ Look for the size object that contains Queen
    size_obj_pattern = re.search(r'"size":{"id":"Queen","title":"Queen","size":"Queen","variantId":(\d+),"price":(\d+\.\d+)', html)
    if size_obj_pattern:
        try:
            variant_id = size_obj_pattern.group(1)
            price = float(size_obj_pattern.group(2))
            return price, 'USD', variant_id
        except (ValueError, IndexError):
            pass
            
    # 6️⃣ Another approach - look for a specific string pattern
    queen_variant_pattern = re.search(r'size":"Queen"[^}]*"variantId":(\d+)[^}]*"price":(\d+\.\d+)', html)
    if queen_variant_pattern:
        try:
            variant_id = queen_variant_pattern.group(1)
            price = float(queen_variant_pattern.group(2))
            return price, 'USD', variant_id
        except (ValueError, IndexError):
            pass
    
    # 7️⃣ Alternative search strategy - find all JSON-like structures with "Queen" and "price"
    all_queen_items = re.findall(r'{[^{]*"size"\s*:\s*"Queen"[^}]*"price"\s*:\s*(\d+\.\d+)[^}]*"variantId"\s*:\s*(\d+)[^}]*}', html)
    if not all_queen_items:
        all_queen_items = re.findall(r'{[^{]*"variantId"\s*:\s*(\d+)[^}]*"size"\s*:\s*"Queen"[^}]*"price"\s*:\s*(\d+\.\d+)[^}]*}', html)
    
    if all_queen_items:
        try:
            if len(all_queen_items[0]) == 2:
                # Handling different match group orders
                if all_queen_items[0][0].isdigit() and '.' in all_queen_items[0][1]:
                    # Format: variantId, price
                    variant_id = all_queen_items[0][0]
                    price = float(all_queen_items[0][1])
                else:
                    # Format: price, variantId
                    price = float(all_queen_items[0][0])
                    variant_id = all_queen_items[0][1]
                return price, 'USD', variant_id
        except (ValueError, IndexError):
            pass
    
    # 8️⃣ General JSON pattern matching approach
    soup = BeautifulSoup(html, 'html.parser')  # or use 'lxml' if available
    scripts = soup.find_all('script')
    
    for script in scripts:
        script_content = script.string or ''
        if 'variantId' in script_content and 'Queen' in script_content:
            # Try to extract JSON objects containing both Queen and variantId
            matches = re.findall(r'{[^{]*"size"\s*:\s*"Queen"[^}]*"variantId"\s*:\s*(\d+)[^}]*"price"\s*:\s*(\d+\.\d+)[^}]*}', script_content)
            if matches:
                try:
                    variant_id = matches[0][0]
                    price = float(matches[0][1])
                    return price, 'USD', variant_id
                except (IndexError, ValueError):
                    pass
            
            # Also check the reverse order
            matches = re.findall(r'{[^{]*"variantId"\s*:\s*(\d+)[^}]*"size"\s*:\s*"Queen"[^}]*"price"\s*:\s*(\d+\.\d+)[^}]*}', script_content)
            if matches:
                try:
                    variant_id = matches[0][0]
                    price = float(matches[0][1])
                    return price, 'USD', variant_id
                except (IndexError, ValueError):
                    pass
                    
    # 9️⃣ Look for JSON-LD structured data
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '{}')
            if isinstance(data, list):
                data = next((d for d in data if d.get('@type') == 'Product'), {})
            if data.get('@type') == 'Product':
                offers = data.get('offers', {})
                if isinstance(offers, list):
                    # Look for Queen-specific offers
                    queen_offer = next((o for o in offers if 'queen' in (o.get('name', '') + o.get('description', '')).lower()), None)
                    if queen_offer:
                        price = queen_offer.get('price')
                        if price is not None:
                            return float(price), queen_offer.get('priceCurrency', 'USD'), target_variant_id or str(queen_offer.get('sku', ''))
        except (json.JSONDecodeError, AttributeError):
            continue
    
    # 🔟 Last resort regex approaches
    # Look for price near "Queen" text
    queen_price_pattern = re.search(r'[Qq]ueen.*?\$(\d{1,3}(?:,\d{3})*\.\d{2})', html)
    if not queen_price_pattern:
        queen_price_pattern = re.search(r'\$(\d{1,3}(?:,\d{3})*\.\d{2}).*?[Qq]ueen', html)
    
    if queen_price_pattern:
        price_str = queen_price_pattern.group(1).replace(',', '')
        sku = target_variant_id or '5637329081'  # Fallback to the one in the provided JSON if available
        return float(price_str), 'USD', sku
    
    raise ValueError(f"Queen variant price not found for URL: {url}")

# ── KOHL’S EXTRACTOR ──────────────────────────────────────────────────────────
# ── KOHL’S EXTRACTOR (productV2JsonData) ──────────────────────────────────
import re, json
from bs4 import BeautifulSoup
from helpers import _html

def fetch_kohls_price(url: str):
    """
    Returns (price: float, currency: str, sku: str)
    by extracting the productV2JsonData JS blob from a Kohl’s PDP.
    """
    html = _html(url)
    
    # 1️⃣ Try to grab the productV2JsonData blob
    m = re.search(
        r'var\s+productV2JsonData\s*=\s*(\{.*?\});',
        html, flags=re.DOTALL
    )
    if m:
        try:
            data = json.loads(m.group(1))
            price_block = data.get("price", {})
            # yourPrice → minPrice
            your = price_block.get("yourPriceInfo", {}) \
                              .get("yourPrice", {})
            price = your.get("minPrice")
            if price is None:
                # fallback to salePrice or regularPrice.minPrice
                price = price_block.get("salePrice") \
                     or price_block.get("regularPrice", {}).get("minPrice")
            price = float(price)

            # Kohl’s always uses USD here
            currency = "USD"

            # webID is the Kohl’s “product” identifier
            sku = str(data.get("webID", "")).strip()

            return price, currency, sku
        except Exception as e:
            # if JSON parse or key lookup failed, fall back
            pass

    # 2️⃣ Fallback → JSON-LD Offer (rarely used)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            jd = json.loads(tag.string)
        except:
            continue
        offers = jd.get("offers")
        if isinstance(offers, dict) and offers.get("price"):
            return float(offers["price"]), offers.get("priceCurrency", "USD"), jd.get("sku", "")

    # 3️⃣ Last-resort regex
    m2 = re.search(r'"yourPrice"\s*:\s*\{\s*"minPrice"\s*:\s*([\d.]+)', html)
    if m2:
        return float(m2.group(1)), "USD", ""

    raise ValueError(f"Kohl’s price not found for URL: {url}")



DOMAIN_EXTRACTOR = {
    "amazon.com": fetch_amazon_price, "www.amazon.com": fetch_amazon_price,
    "smile.amazon.com": fetch_amazon_price,
    "target.com": fetch_target_price, "www.target.com": fetch_target_price,
    "walmart.com": fetch_walmart_price, "www.walmart.com": fetch_walmart_price,
    "babylist.com": fetch_babylist_price, "www.babylist.com": fetch_babylist_price,
    "wayfair.com": fetch_wayfair_price,
    "www.wayfair.com": fetch_wayfair_price,
    "homedepot.com":   fetch_homedepot_price,
    "www.homedepot.com": fetch_homedepot_price,
    "mybobs.com":    fetch_mybobs_price,
    "www.mybobs.com": fetch_mybobs_price,
    "ashleyfurniture.com":    fetch_ashley_price,
    "www.ashleyfurniture.com": fetch_ashley_price,
    "livingspaces.com":       fetch_livingspaces_price,
    "www.livingspaces.com":   fetch_livingspaces_price,
    "bestbuy.com":     fetch_bestbuy_price,
    "www.bestbuy.com": fetch_bestbuy_price,
    "lowes.com":     fetch_lowes_price,
    "www.lowes.com": fetch_lowes_price,
    'raymourflanigan.com':    fetch_raymour_price,
    'www.raymourflanigan.com':fetch_raymour_price,
    'crateandbarrel.com':     fetch_crateandbarrel_price,
    'www.crateandbarrel.com': fetch_crateandbarrel_price,
    "dollartree.com":     fetch_dollartree_price,
    "www.dollartree.com": fetch_dollartree_price,
    "westelm.com":      fetch_westelm_price,
    "www.westelm.com":  fetch_westelm_price,
    "athome.com":       fetch_athome_price,
    "www.athome.com":   fetch_athome_price,
    "mattressfirm.com":     fetch_mattressfirm_price,
    "www.mattressfirm.com": fetch_mattressfirm_price,
    "kohls.com":     fetch_kohls_price,
    "www.kohls.com": fetch_kohls_price,
    
}
