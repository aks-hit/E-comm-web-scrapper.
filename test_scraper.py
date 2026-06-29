"""
================================================================================
Test Scraper - test_scraper.py
================================================================================
Description :
A standalone script to test the `Shein` scraper logic locally on a single URL.
Reads the first URL from `Inputs/urls.txt`, scrapes it, and outputs the result.
Useful for debugging parsing logic changes.
"""
import json
import os
from Shein import Shein
import undetected_chromedriver as uc
from Logger import Logger

def main():
    logger = Logger("./Logs/test_scraper.log", clean=True)
    
    input_file = "Inputs/urls.txt"
    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found. Please add a URL to test.")
        return

    # Read the first non-empty URL
    test_url = None
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            url = line.strip()
            if url and not url.startswith('#'):
                test_url = url.split(" ")[0]
                break
                
    if not test_url:
        print("No valid URLs found in Inputs/urls.txt.")
        return

    print(f"Testing URL: {test_url}")
    
    # Initialize driver
    profile_path = os.path.abspath(os.path.join(os.getcwd(), 'ChromeProfile'))
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={profile_path}")
    options.add_argument("--profile-directory=Default")
    
    print("Launching browser...")
    driver = uc.Chrome(options=options, version_main=131)
    
    try:
        scraper = Shein(test_url, driver=driver, logger=logger)
        result = scraper.scrape(verbose=True)
        
        if result:
            print("\nSUCCESS! Extracted data:")
            print(json.dumps(result, indent=4))
        else:
            print("\nFAILED to extract data.")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
