"""
================================================================================
Urls Input File Adder - urls_input_file_adder.py
================================================================================
Description :
A utility script used primarily during the URL Cleaning phase (Phase 2).
It reads `urls.txt` from the ./Inputs/ directory, deduplicates the URLs, 
sanitizes them using utilities from `urls_utils.py`, and overwrites the file 
with clean, ready-to-scrape entries.

Usage:
1. Place raw URLs in `./Inputs/urls.txt` (or let Phase 1 auto-populate it).
2. Run this script directly or let `run_pipeline.py` call it.
3. The file will be cleaned in-place.

Outputs:
- Overwritten `./Inputs/urls.txt` containing cleaned, deduplicated URLs.
- Console/log warnings for validation failures.

Dependencies:
- Python >= 3.8
- colorama
- Logger module from the project
"""
import argparse
import os
import sys
from pathlib import Path
from colorama import Style
from Logger import Logger
from urls_utils import load_urls_to_process, preprocess_urls, write_urls_to_file

class BackgroundColors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"

INPUT_DIRECTORY = "./Inputs/"
INPUT_FILE = f"{INPUT_DIRECTORY}urls.txt"
logger = Logger(f"./Logs/{Path(__file__).stem}.log", clean=True)

def main():
    parser = argparse.ArgumentParser(description="URLs Input File Adder - Cleans and deduplicates urls.txt")
    parser.parse_args()

    print(f"{BackgroundColors.BOLD}{BackgroundColors.GREEN}Welcome to the {BackgroundColors.CYAN}URLs Input File Adder{BackgroundColors.GREEN}!{Style.RESET_ALL}")
    
    if not os.path.exists(INPUT_FILE):
        print(f"{BackgroundColors.RED}Input file {INPUT_FILE} not found.{Style.RESET_ALL}")
        sys.exit(1)

    raw_urls = load_urls_to_process(INPUT_FILE)
    if raw_urls is None:
        sys.exit(1)

    # Sanitize and deduplicate
    cleaned_urls = preprocess_urls(raw_urls)
    unique_urls = list(dict.fromkeys(cleaned_urls)) # keep order but deduplicate

    print(f"{BackgroundColors.GREEN}Found {len(raw_urls)} raw URLs, cleaned down to {len(unique_urls)} unique URLs.{Style.RESET_ALL}")

    write_urls_to_file(unique_urls, INPUT_FILE, recursive=False, sort=False)
    print(f"{BackgroundColors.GREEN}Successfully updated {INPUT_FILE}.{Style.RESET_ALL}")

if __name__ == "__main__":
    main()
