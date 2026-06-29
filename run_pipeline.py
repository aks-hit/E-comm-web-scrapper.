"""
================================================================================
Run Pipeline - run_pipeline.py
================================================================================
Description :
The main orchestrator for the Shein Web Scraper.
This script coordinates a fully automated 3-phase pipeline:
1. Discovery: Uses Playwright to navigate category pages and harvest product URLs.
2. Cleaning: Deduplicates and sanitizes the harvested URLs.
3. Scraping: Orchestrates the main execution engine (main.py) to extract
   data using undetected-chromedriver, with an initial manual CAPTCHA warmup.
"""
import argparse
import asyncio
import os
import subprocess
import sys

from playwright.async_api import async_playwright

DEFAULT_CATEGORIES = [
    "https://us.shein.com/Women-Tops-c-1771.html",
    "https://us.shein.com/Women-Dresses-c-1727.html",
    "https://us.shein.com/Men-Tops-c-1970.html",
    "https://us.shein.com/Men-Bottoms-c-1976.html",
]

async def auto_scroll(page, steps=10, pause_ms=1000):
    """
    Scrolls the Playwright page down repeatedly to trigger lazy loading of products.

    Args:
        page (Page): The Playwright page object.
        steps (int): The number of scroll steps to perform.
        pause_ms (int): Time to wait between scrolls in milliseconds.
    """
    print(f"Scrolling page to load lazy products ({steps} steps)...")
    for i in range(steps):
        await page.evaluate("window.scrollBy(0, 1000);")
        await page.wait_for_timeout(pause_ms)
    await page.evaluate("window.scrollTo(0, 0);")

async def extract_urls(page):
    """
    Extracts all product URLs from the current page using JavaScript.

    Args:
        page (Page): The Playwright page object.

    Returns:
        list: A list of unique product URLs found on the page.
    """
    js_code = """
    () => {
        const links = Array.from(document.querySelectorAll('a[href*="-p-"]')).map(a => a.href);
        return [...new Set(links)];
    }
    """
    return await page.evaluate(js_code)

async def run_discovery(target_urls, output_file, max_urls=1000):
    """
    Phase 1: Mass Discovery. Navigates category pages to discover product URLs.

    Args:
        target_urls (list): A list of category URLs to scrape.
        output_file (str): The file path where discovered URLs should be saved.
        max_urls (int): The maximum number of URLs to discover before stopping.

    Returns:
        list: A list of all unique URLs collected.
    """
    print(f"--- Phase 1: Mass Discovery (Target: {max_urls} URLs) ---")
    collected = set()
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    
    # Load existing if any
    if os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    collected.add(line.strip())
    
    if len(collected) >= max_urls:
        print(f"Already have {len(collected)} URLs. Skipping discovery.")
        return list(collected)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            from playwright_stealth import Stealth
            await Stealth().apply_stealth_async(page)
        except ImportError:
            pass
            
        for cat_url in target_urls:
            if len(collected) >= max_urls:
                break
                
            print(f"\nProcessing category: {cat_url}")
            page_num = 1
            empty_pages = 0
            
            while len(collected) < max_urls and empty_pages < 3:
                # Append page number
                sep = "&" if "?" in cat_url else "?"
                url_with_page = f"{cat_url}{sep}page={page_num}"
                
                print(f"Navigating to {url_with_page}...")
                await page.goto(url_with_page, wait_until="domcontentloaded")
                
                # Check for bot block / wait for products
                print("Waiting up to 30 seconds for products to load or CAPTCHA to be solved...")
                try:
                    await page.wait_for_selector('a[href*="-p-"]', timeout=30000)
                except Exception:
                    print("Timeout waiting for products. Moving to next category.")
                    break
                    
                await auto_scroll(page, steps=15, pause_ms=800)
                
                new_urls = await extract_urls(page)
                
                added = 0
                newly_added = []
                for u in new_urls:
                    if ".html" in u:
                        u = u.split(".html")[0] + ".html"
                    if u not in collected:
                        collected.add(u)
                        newly_added.append(u)
                        added += 1
                        
                if added == 0:
                    empty_pages += 1
                else:
                    empty_pages = 0
                        
                print(f"Extracted {len(new_urls)} URLs. {added} were new. Total collected: {len(collected)}/{max_urls}")
                
                # Keep appending to file
                with open(output_file, "a", encoding="utf-8") as f:
                    for u in newly_added:
                        f.write(u + "\n")
                
                page_num += 1

        await browser.close()
    return list(collected)

def clean_urls(input_file):
    """
    Phase 2: URL Cleaning. Reads the input file, deduplicates URLs, and strips query parameters.

    Args:
        input_file (str): The path to the file containing raw URLs.
    """
    print("\n--- Phase 2: URL Cleaning ---")
    if not os.path.exists(input_file):
        print(f"{input_file} not found.")
        return
        
    with open(input_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    clean_set = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip query params
        if ".html" in line:
            line = line.split(".html")[0] + ".html"
        clean_set.add(line)
        
    with open(input_file, "w", encoding="utf-8") as f:
        f.write("# One product URL per line. Lines starting with # are ignored.\n")
        for u in clean_set:
            f.write(u + "\n")
            
    print(f"Cleaned raw lines down to {len(clean_set)} unique clean URLs.")

def run_scraping(input_file, target=0):
    """
    Phase 3: Mass Scraping. Triggers the main backend scraper to process the cleaned URLs.

    Args:
        input_file (str): The path to the file containing cleaned URLs.
        target (int): Maximum number of URLs to scrape.
    """
    print("\n--- Phase 3: Mass Scraping ---")
    
    cmd = [
        sys.executable, "main.py"
    ]
    if target > 0:
        cmd.extend(["--target", str(target)])
        
    print(f"Executing: {' '.join(cmd)}")
    subprocess.run(cmd)

async def main():
    """
    Main orchestrator entry point. Parses arguments and runs the 3-phase pipeline.
    """
    parser = argparse.ArgumentParser(description="End-to-End Orchestrator Pipeline")
    parser.add_argument("--categories", type=str, help="Path to text file with category URLs (1 per line)")
    parser.add_argument("--target", type=int, default=1000, help="Target number of URLs to discover")
    parser.add_argument("--out", type=str, default="Inputs/urls.txt", help="Output file for URLs")
    args = parser.parse_args()
    
    categories = DEFAULT_CATEGORIES
    if args.categories and os.path.exists(args.categories):
        with open(args.categories, "r", encoding="utf-8") as f:
            categories = [line.strip() for line in f if line.strip()]
            
    print(f"Loaded {len(categories)} categories to scrape.")
    
    # Phase 1
    await run_discovery(categories, args.out, max_urls=args.target)
    
    # Phase 2
    clean_urls(args.out)
    
    print("\n--- Pre-Scraping: Session Warmup ---")
    print("Launching manual browser to solve initial Captchas and save cookies...")
    try:
        # Find the first unscraped URL to use for session warmup
        first_unscraped_url = None
        scraped_urls = set()
        unified_json_path = "Outputs/products.json"
        if os.path.exists(unified_json_path):
            try:
                import json
                with open(unified_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            if "url" in item:
                                scraped_urls.add(item["url"])
            except Exception:
                pass
                
        with open(args.out, "r", encoding="utf-8") as f:
            for line in f:
                url = line.strip()
                if url and not url.startswith("#"):
                    if url not in scraped_urls:
                        first_unscraped_url = url
                        break
                        
        from setup_session import setup_browser_session
        setup_browser_session(test_url=first_unscraped_url)
    except Exception as e:
        print(f"Warning: Could not run setup_session automatically: {e}")
    
    # Phase 3
    run_scraping(args.out, target=args.target)
    
    print("\nAll phases complete! Check outputs directory for data.")

if __name__ == "__main__":
    asyncio.run(main())
