"""
================================================================================
Test Scraper - test_scraper.py
================================================================================
Description :
A standalone script to test the `Shein` scraper logic locally.
Reads URLs from `test_urls.txt`, scrapes them sequentially, and outputs
results to `Outputs/test_100_results.json`. Includes the 10-URL session refresh logic.
"""
import json
import time
import random
from Shein import Shein
from setup_session import setup_browser_session

urls = []
with open("test_urls.txt", "r", encoding="utf-8") as f:
    for line in f:
        url = line.strip()
        if url and not url.startswith('#'):
            urls.append(url)
        if len(urls) >= 1:
            break

results = []
scrapes_since_refresh = 0

for i, url in enumerate(urls):
    if scrapes_since_refresh >= 10:
        print(f"\n[ACTION REQUIRED] 10 URLs scraped. Pausing to refresh CAPTCHA session.")
        setup_browser_session()
        scrapes_since_refresh = 0

    print(f"\n[{i+1}/{len(urls)}] Testing URL: {url}")
    scraper = Shein(url)
    result = scraper.scrape(verbose=True)
    if result:
        print("SUCCESS! Extracted data:")
        print(f"SKU: {result.get('sku')}")
        print(f"Reviews: {result.get('reviews')}")
        print(f"Available Sizes: {result.get('available_sizes')}")
        results.append(result)
    else:
        print("FAILED to extract data.")

    scrapes_since_refresh += 1
    
    delay = random.uniform(5.0, 15.0)
    print(f"\nSleeping for {delay:.2f} seconds before next request...")
    time.sleep(delay)

    with open("Outputs/test_100_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)
