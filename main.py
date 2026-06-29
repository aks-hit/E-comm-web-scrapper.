"""
================================================================================
Main - main.py
================================================================================
Description :
The core execution engine for the Shein Web Scraper.
It automates the process of collecting data like product names, prices, descriptions,
and high-resolution images from Shein using undetected-chromedriver.

Key features include:
- Web scraping specifically targeted at SHEIN US
- Automated AI-powered CAPTCHA solving using Gemini Vision and CDP clicks
- Incremental saving of results to JSON to prevent data loss
- Filtering out already-scraped URLs (duplicate detection)
- Fallback to manual session warmup if AI solving fails repeatedly
- Optional AI marketing content generation

Usage:
1. Configure the .env file with necessary API keys (GEMINI_API_KEY).
2. Input URLs are automatically fed via run_pipeline.py, or manually via Inputs/urls.txt.
3. Run `python run_pipeline.py` (recommended) or `python main.py`.

Outputs:
- Scraped data incrementally appended to ./Outputs/products.json
- Downloaded product images and HTML snapshots in ./Outputs/<Product Name>/
- Logs in ./Logs/ for execution details

Dependencies:
- Python >= 3.8
- undetected-chromedriver, beautifulsoup4 for web scraping
- colorama for terminal coloring
- google-genai for AI integration

Assumptions & Notes:
- Respect robots.txt and terms of service for ethical scraping.
- API keys are required for CAPTCHA solving capabilities.
"""
import argparse  # Parse command-line arguments.
import atexit  # For playing a sound when the program finishes
import datetime  # For getting the current date and time
import json  # For JSON history file handling
import os  # For running a command in the terminal
import platform  # For getting the operating system name
import sys  # For system-specific parameters and functions
import time  # For adding delays between requests
from collections import OrderedDict  # For deterministic ordered mapping of named API keys
from colorama import Style  # For coloring the terminal
from dotenv import load_dotenv  # For loading environment variables
from Logger import Logger  # For logging output to both terminal and file
from pathlib import Path  # For handling file paths
from Shein import Shein  # Import the Shein class
from tqdm import tqdm  # Progress bar for URL processing
from typing import Dict, List, Optional, Tuple  # For type-annotated containers used by final verification functions
from urls_utils import load_urls_to_process, preprocess_urls, write_urls_to_file  # URL helpers


# Macros:
class BackgroundColors:  # Colors for the terminal
    CYAN = "\033[96m"  # Cyan
    GREEN = "\033[92m"  # Green
    YELLOW = "\033[93m"  # Yellow
    RED = "\033[91m"  # Red
    BOLD = "\033[1m"  # Bold


# Execution Constants:
VERBOSE = False  # Set to True to output verbose messages

TEST_URLs = [""]  # Test URLs for scraping

PLATFORMS_MAP = {
    "Shein": "shein",
}

PLATFORM_PREFIX_SEPARATOR = " - "  # Separator between platform prefix and product name in directory structure

# File Path Constants:
PROJECT_ROOT = str(Path(__file__).resolve().parents[[p.name for p in Path(__file__).resolve().parents].index("E-Commerces-WebScraper")])  # Project root directory
INPUT_DIRECTORY = "./Inputs/"  # The path to the input directory
INPUT_FILE = f"{INPUT_DIRECTORY}urls.txt"  # The path to the input file
OUTPUT_DIRECTORY = "./Outputs/"  # The path to the output directory
OUTPUT_FILE = f"{OUTPUT_DIRECTORY}output.txt"  # The path to the output file
CLEAR_INPUT_FILE = True  # When True, remove successfully scraped product lines from the input file
DELETE_LOCAL_HTML_FILE = True if CLEAR_INPUT_FILE else False  # When True, delete the local HTML file after processing if the line is cleared from input file

# Environment Variables:
ENV_PATH = "./.env"  # The path to the .env file
ENV_VARIABLES = {
    "GEMINI": "GEMINI_API_KEY"
}  # The environment variables to load from the .env file


# Logger Setup:
logger = Logger(f"./Logs/{Path(__file__).stem}.log", clean=True)  # Create a Logger instance
sys.stdout = logger  # Redirect stdout to the logger
sys.stderr = logger  # Redirect stderr to the logger

# Sound Constants:
SOUND_COMMANDS = {
    "Darwin": "afplay",
    "Linux": "aplay",
    "Windows": "start",
}  # The commands to play a sound for each operating system
SOUND_FILE = "./.assets/Sounds/NotificationSound.wav"  # The path to the sound file

# RUN_FUNCTIONS:
RUN_FUNCTIONS = {
    "Play Sound": True,  # Set to True to play a sound when the program finishes
}

# Delay Constants:
DELAY_BETWEEN_REQUESTS = 5  # Seconds to wait between processing URLs to avoid rate limiting
OUTPUT_DIRECTORY_RETRY_ATTEMPTS = 2   # Number of retries when the final product output directory is missing (2 retries -> 3 attempts total)

# Gemini AI Constants:
GEMINI_MARKETING_PROMPT_TEMPLATE = """You are an e-commerce marketing expert. Your task is to transform the product information below into a persuasive, catchy, direct, and formatted marketing text.

PRODUCT INFORMATION:
{product_description}

MANDATORY FORMAT (follow EXACTLY this format):
*{{{{PRODUCT NAME}}}} – {{{{SHORT DIFFERENTIAL}}}}*

💰 FROM *R${{{{OLD_PRICE}}}}* FOR ONLY *R${{{{CURRENT_PRICE}}}}* (IF OLD_PRICE IS GREATER THAN CURRENT_PRICE; IF OLD_PRICE IS LESS OR EQUAL, OMIT 'FROM *R${{{{OLD_PRICE}}}}*')
🎟️ *{{{{COUPON INFO / DISCOUNT %}}}}* (IF AVAILABLE, AND ONLY IF OLD_PRICE IS GREATER THAN CURRENT_PRICE)

*{{{{IMPACT PHRASE / MAIN BENEFIT}}}}*

✨ {{{{FEATURE 1}}}}
✨ {{{{FEATURE 2}}}}
✨ {{{{WHERE / HOW TO USE}}}}
✨ {{{{GIFT IDEA / OCCASION}}}}

🛒 Find it at {{{{STORE / PLATFORM}}}}:
👉 {{{{PRODUCT LINK}}}}

INSTRUCTIONS:
1. Use the provided information to fill each field
2. Be persuasive, creative, and catchy
3. Keep the format EXACTLY as shown
4. Use the actual product prices and discounts when available
5. The price line (💰) is mandatory when there is a price change
6. When there is no discount, OMIT only the discount line (🎟️)
7. When there is no old price, use the same value of the current price as the old price
8. When OLD_PRICE and CURRENT_PRICE are equal:
    - DO NOT use the format "FROM R$ X"
    - Use exclusively: 💰 FOR ONLY *R${{CURRENT_PRICE}}*
    - Do not show old price
    - Do not show the discount line
9. Always include the real product link
10. Create 2-3 striking main features
11. Suggest product use objectively
12. Include occasion/gift when it makes sense
13. For discounts, never use just "off", prefer something like "20% Discount!"
14. Final text MUST NOT exceed 1000 characters
15. Short and objective sentences are mandatory
16. Avoid long blocks or dense texts
17. SPACING IS MANDATORY:
   - 1 blank line after title
   - 1 blank line after price/discount
   - 1 blank line after impact phrase
   - 1 blank line after feature list
18. NEVER compress everything into a single block

────────────────────────────────────────
PRICE VALIDATION RULES (NEW - MANDATORY)
────────────────────────────────────────

19. PRICE CONSISTENCY VALIDATION:
   - OLD_PRICE CANNOT be less than CURRENT_PRICE
   - If this occurs, interpret it as inverted data and correct logically before generating output
   - Never invent values

20. MANDATORY DISCOUNT:
   - If OLD_PRICE > CURRENT_PRICE, the discount MUST be calculated correctly
   - The discount percentage must match exactly the difference between the values
   - Do not omit the discount in this case

21. IF PRICES ARE EQUAL:
    - Do not show the "FROM R$" line
    - Use only:
        💰 FOR ONLY *R${{CURRENT_PRICE}}*

────────────────────────────────────────
LINK AND PLATFORM RULES (NEW - MANDATORY)
────────────────────────────────────────

22. Always include product platform (e.g. Shein)

23. Always include product link


────────────────────────────────────────

Generate ONLY the formatted text, with no additional explanations."""  # Template for Gemini AI marketing text generation

GEMINI_LAST_KEY_INDEX = 0  # Index to keep track of the last used key in the Gemini prompt template for dynamic replacement
GEMINI_ALL_KEYS_EXHAUSTED_WAIT_SECONDS = 600  # Seconds to wait before restarting key rotation when all keys are exhausted.
GEMINI_MAX_ALL_KEYS_EXHAUSTED_CYCLES = 1  # Maximum all-keys-exhausted cycles per URL before failing the request.
GEMINI_MODEL_PRIORITY = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash",
    "gemma-3-27b-it",
]  # Deterministic model fallback priority for each API-key attempt.

# Image Upgrade Constants:
FILENAME_SIMILARITY_THRESHOLD = 0.70  # Minimum SequenceMatcher ratio for root-to-candidate basename similarity matching
PRODUCT_DATA_DIRECTORY_NAME = "Product Data"  # Directory name for storing product payload artifacts after final restructuring.
PRODUCT_METADATA_DIRECTORY_NAME = "Product Metadata"  # Directory name for storing metadata artifacts after final restructuring.
ROOT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg", ".heic", ".avif"}  # Supported image extensions for root media detection.
ROOT_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".m4v", ".mpeg", ".mpg", ".3gp", ".ts", ".m3u8"}  # Supported video extensions for root media detection.
ROOT_MEDIA_EXTENSIONS = ROOT_IMAGE_EXTENSIONS | ROOT_VIDEO_EXTENSIONS  # Union of root-level image and video extensions.
REFERENCE_TEXT_EXTENSIONS = {".txt", ".json", ".html", ".htm", ".md", ".xml", ".yaml", ".yml", ".csv", ".js", ".ts", ".css"}  # Text-based extensions used for media reference update pass.

# Functions Definitions:


def verbose_output(true_string="", false_string=""):
    """
    Outputs a message if the VERBOSE constant is set to True.

    :param true_string: The string to be outputted if the VERBOSE constant is set to True.
    :param false_string: The string to be outputted if the VERBOSE constant is set to False.
    :return: None
    """

    if VERBOSE and true_string != "":  # If VERBOSE is True and a true_string was provided
        print(true_string)  # Output the true statement string
    elif false_string != "":  # If a false_string was provided
        print(false_string)  # Output the false statement string


def verify_filepath_exists(filepath):
    """
    Verify if a file or folder exists at the specified path.

    :param filepath: Path to the file or folder
    :return: True if the file or folder exists, False otherwise
    """

    verbose_output(
        f"{BackgroundColors.GREEN}Verifying if the file or folder exists at the path: {BackgroundColors.CYAN}{filepath}{Style.RESET_ALL}"
    )  # Output the verbose message

    return os.path.exists(filepath)  # Return True if the file or folder exists, False otherwise


def ensure_input_file_exists():
    """
    Ensure the input file exists; create an empty one if missing.

    :param: None
    :return: True if the input file exists or was created successfully, False otherwise
    """

    if not verify_filepath_exists(INPUT_FILE):  # Verify if the input file exists
        try:  # Attempt to create an empty input file
            open(INPUT_FILE, "w", encoding="utf-8").close()  # Create an empty file at INPUT_FILE
            verbose_output(  # Verbose message indicating creation
                f"{BackgroundColors.GREEN}Created empty input file: {BackgroundColors.CYAN}{INPUT_FILE}{Style.RESET_ALL}"
            )  # Output the verbose message
            return True  # Return True when file was created successfully
        except Exception as e:  # If creating the file fails
            print(  # Print the failure message so user can see the error
                f"{BackgroundColors.RED}Failed to create input file {BackgroundColors.CYAN}{INPUT_FILE}{BackgroundColors.RED}: {e}{Style.RESET_ALL}"
            )  # Output reason for failure
            return False  # Return False to indicate failure to ensure file
    return True  # Return True when file already exists


def verify_dot_env_file():
    """
    Verifies if the .env file exists in the current directory.

    :return: True if the .env file exists, False otherwise
    """
    
    verbose_output(
        f"{BackgroundColors.GREEN}Verifying if the {BackgroundColors.CYAN}.env{BackgroundColors.GREEN} file exists...{Style.RESET_ALL}"
    )  # Output the verbose message

    env_path = Path(__file__).parent / ".env"  # Path to the .env file
    
    if not verify_filepath_exists(env_path):  # If the .env file does not exist
        print(f"{BackgroundColors.CYAN}.env{BackgroundColors.YELLOW} file not found at {BackgroundColors.CYAN}{env_path}{BackgroundColors.YELLOW}.{Style.RESET_ALL}")
        return False  # Return False

    return True  # Return True if the .env file exists


def verify_env_variables():
    """
    Verifies if the required environment variables are set in the .env file.

    :return: True if all required environment variables are set, False otherwise
    """

    missing_variables = []  # List to store missing environment variables

    for ref_name, env_var in ENV_VARIABLES.items():  # ENV_VARIABLES = {"REFERENCE_NAME": "ENV_VAR_NAME"}
        if os.getenv(env_var) is None:  # If the environment variable is not set
            missing_variables.append(f"{ref_name} ({env_var})")  # Add the missing variable to the list

    if missing_variables:  # If there are any missing variables
        print(
            f"{BackgroundColors.YELLOW}The following environment variables are missing from the .env file: "
            f"{BackgroundColors.CYAN}{', '.join(missing_variables)}{Style.RESET_ALL}"
        )
        return False  # Return False if any required environment variable is missing

    return True  # Return True if all required environment variables are set






















def scrape_product(url, api_keys):
    """
    Instantiates the appropriate scraper for the given URL and extracts the product data.

    Args:
        url (str): The product URL to scrape.

    Returns:
        dict: The extracted product data dictionary, or None if scraping fails or platform is unsupported.
    """
    platform = detect_platform(url)
    if not platform:
        print(f"{BackgroundColors.RED}Unsupported platform. Skipping URL: {url}{Style.RESET_ALL}")
        return None
    
    scraper_classes = {"shein": Shein}
    scraper_class = scraper_classes.get(platform)
    if not scraper_class:
        return None
        
    try:
        scraper = scraper_class(url, local_html_path=None, prefix="", output_directory="", api_keys=api_keys)
        product_data = scraper.scrape()
        return product_data
    except Exception as e:
        print(f"{BackgroundColors.RED}Error during scraping: {e}{Style.RESET_ALL}")
        return None

    














































def parse_arguments() -> argparse.Namespace:
    """
    Parse and return command-line arguments for the main program.

    :param: None
    :return: Parsed argument namespace containing all CLI flags.
    """

    parser = argparse.ArgumentParser(description="Shein Web Scraper pipeline execution script.")  # Create argument parser with description

    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug output (default: False)")  # Register verbose flag that sets True when provided
    parser.add_argument("--target", type=int, default=0, help="Maximum number of URLs to scrape (0 means unlimited)")
    args = parser.parse_args()  # Parse command-line arguments

    return args  # Return parsed argument namespace
























def setup_environment() -> bool:
    """
    Validate and load environment configuration from .env file.

    :param: None
    :return: True if environment setup succeeded, False otherwise.
    """

    if not verify_dot_env_file():  # Verify if the .env file exists
        print(f"{BackgroundColors.RED}Environment setup failed. Exiting...{Style.RESET_ALL}")
        return False  # Return False to signal environment setup failure

    load_dotenv(ENV_PATH)  # Load environment variables

    if not verify_env_variables():  # Verify if the required environment variables are set
        print(f"{BackgroundColors.RED}Environment variables missing. Exiting...{Style.RESET_ALL}")
        return False  # Return False to signal missing environment variables

    return True  # Return True to signal successful environment setup


def load_api_keys() -> Dict[str, str]:
    """
    Load and validate Gemini API keys from environment variables.

    :param: None
    :return: Ordered mapping of owner name to API key strings, or empty mapping if none configured.
    """

    api_keys_raw = os.getenv(ENV_VARIABLES["GEMINI"], "")  # Get raw GEMINI value from environment variables
    parsed = parse_gemini_api_keys(api_keys_raw)  # Parse raw env value into ordered mapping of name->key

    if not parsed:  # Verify if parsing produced at least one API key
        print(f"{BackgroundColors.RED}Error: No Gemini API keys configured in .env file.{Style.RESET_ALL}")  # Report missing API key configuration

    return parsed  # Return ordered mapping of validated API keys


def parse_gemini_api_keys(env_value: str) -> Dict[str, str]:
    """
    Parse GEMINI API keys from an environment variable into a name->key mapping.

    :param env_value: Raw environment variable string containing API key entries.
    :return: Ordered dictionary mapping owner name to API key string.
    """

    env_value = (env_value or "").strip()  # Normalize raw value and guard against None
    if not env_value:  # Return empty mapping for empty env values
        return OrderedDict()  # Return empty ordered dict when no keys configured

    entries = [entry.strip() for entry in env_value.split(",") if entry.strip()]  # Split on commas and trim whitespace
    named_keys: "OrderedDict[str, str]" = OrderedDict()  # Prepare ordered mapping for resulting keys

    contains_colon = any((":" in e) for e in entries)  # Determine whether at least one entry uses name:key format

    if contains_colon:  # Parse only entries with a colon when new-style format detected
        for entry in entries:  # Iterate over comma-separated entries preserving order
            if ":" not in entry:  # Ignore malformed entries that do not contain a colon
                continue  # Skip malformed entry without raising to remain tolerant
            name, key = entry.split(":", 1)  # Split only on the first colon to allow colons in keys
            name = name.strip()  # Trim whitespace around owner name
            key = key.strip()  # Trim whitespace around API key value
            if not name or not key:  # Ignore entries missing a name or key after trimming
                continue  # Skip malformed or empty entries gracefully
            named_keys[name] = key  # Store or override entry by owner name
    else:  # Fallback to old-style comma-separated keys without explicit names
        idx = 1  # Start incremental index counter for unnamed keys
        for entry in entries:  # Iterate entries to assign generated names in original order
            key = entry.strip()  # Normalize key string by trimming whitespace
            if not key:  # Ignore empty key tokens
                continue  # Skip empty entries without raising
            generated_name = f"key_{idx}"  # Build deterministic generated owner name for compatibility
            named_keys[generated_name] = key  # Assign generated name to the key in order
            idx += 1  # Increment generated name counter for next unnamed key

    return named_keys  # Return ordered mapping of owner->api_key


def initialize_directories() -> str:
    """
    Create required input and output directories.
    """
    os.makedirs(INPUT_DIRECTORY, exist_ok=True)
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
    
    staging_output_dir = os.path.join(OUTPUT_DIRECTORY, ".staging")
    os.makedirs(staging_output_dir, exist_ok=True)
    
    return staging_output_dir


def prepare_input_urls() -> tuple:
    """
    Load, preprocess, and parse input URLs into processing tuples.

    :param: None
    :return: Tuple of (urls_to_process list, total_urls count).
    """

    raw_lines = load_urls_to_process(INPUT_FILE)  # Load raw trimmed input lines from file
    
    if raw_lines is None:  # Verify if loading the input file failed (e.g., file not found)
        print(f"{BackgroundColors.RED}Error: Failed to read URLs from file: {BackgroundColors.CYAN}{INPUT_FILE}{BackgroundColors.RED}. Please ensure the file exists and is readable in that specified paths. Be careful with the parent directory of the file as well.{Style.RESET_ALL}")  # Print file read error with details and suggestions.
        return [], 0  # Return empty list and zero count when input file cannot be loaded

    normalized_lines = normalize_paths_to_unix(raw_lines)  # Normalize Windows-style paths to Unix-style before any downstream processing
    processed_lines = preprocess_urls(normalized_lines)  # Preprocess lines (strip, remove prefixes, sort)
    write_urls_to_file(processed_lines, INPUT_FILE, recursive=True, sort=True)  # Write preprocessed lines back to input file for deterministic retries and user reference

    urls_to_process = []  # Prepare list of tuples (url, local_html_path)
    for line in sorted(processed_lines, key=lambda s: s.lower()):  # Iterate preprocessed lines sorted alphabetically in a case-insensitive manner
        parts = line.split(maxsplit=1)  # Separate URL and optional local path
        url = parts[0]  # First token is URL
        local_html = parts[1] if len(parts) > 1 else None  # Optional local HTML path
        urls_to_process.append((url, local_html))  # Append tuple to processing list

    total_urls = len(urls_to_process)  # Total number of URLs to process after preprocessing

    return urls_to_process, total_urls  # Return parsed URL tuples and total count


def initialize_processing_context(staging_output_dir: str) -> dict:
    """
    Initialize shared runtime state dictionary for URL processing pipeline.

    :param staging_output_dir: Absolute path to the staging output directory.
    :return: Dictionary containing mutable processing state fields.
    """

    context = {
        "staging_output_dir": staging_output_dir,  # Staging area path for interim outputs
        "timestamped_output_dir": None,  # Will be created lazily on first successful scrape
        "successful_scrapes": 0,  # Counter for successful operations
        "has_amazon": False,  # Initialize flag to detect presence of Amazon URLs during processing
        "timestamped_output_dir_for_sorting": None,  # Initialize variable for output directory to sort
        "sorting_only_mode": False,  # Initialize flag for sorting-only mode
    }  # Build mutable context dictionary for pipeline state

    return context  # Return initialized processing context




def normalize_product_data_paths(product_data: dict) -> dict:
    """
    Normalize all path fields in product_data to Unix-style.

    :param product_data: Dictionary containing product data fields.
    :return: Dictionary with all path fields normalized to Unix-style.
    """

    if not isinstance(product_data, dict):  # Verify if product_data is a dictionary
        return product_data  # Return as is if not a dictionary

    path_keys = [
        "local_html_path",
        "html_path",
        "zip_path",
        "extracted_dir",
        "description_file",
        "product_directory",
        "product_dir",
        "input_source",
        "output_file",
        "output_dir",
    ]  # List of known path-related keys in product_data

    normalized = product_data.copy()  # Copy product_data to avoid mutating input

    for key in path_keys:  # Iterate over known path keys
        if key in normalized and isinstance(normalized[key], str):  # Verify key exists and is a string
            # Use normalize_paths_to_unix to normalize this single path string
            normalized[key] = normalize_paths_to_unix([normalized[key]])[0]

    return normalized  # Return normalized product_data


def reorder_product_data_fields(product_data: dict, url: str) -> dict:
    """
    Reorder product_data fields.

    :param product_data: Dictionary containing product data fields.
    :param url: Original source URL used to process this product.
    :return: Reordered dictionary with controlled field ordering.
    """
    
    verbose_output(f"{BackgroundColors.GREEN}Reordering product data fields for URL: {BackgroundColors.CYAN}{url}{Style.RESET_ALL}")  # Log the reordering action for this URL

    reordered_product_data = {"url": url}  # Initialize dictionary ensuring URL is first field

    if not isinstance(product_data, dict):  # Verify if product_data is not a valid dictionary
        return reordered_product_data  # Return minimal structure when input is invalid

    inserted_safe_name = False  # Track whether product_name_safe has been inserted after name

    for key, value in product_data.items():  # Iterate through original product data preserving order
        if key == "url":  # Verify if current key is URL to avoid duplication
            continue  # Skip URL since it is already normalized as first field

        reordered_product_data[key] = value  # Insert current field preserving original ordering rules

        if key == "name" and "product_name_safe" in product_data:  # Verify if name field is reached and safe name exists
            reordered_product_data["product_name_safe"] = product_data["product_name_safe"]  # Insert safe name immediately after name field
            inserted_safe_name = True  # Mark safe name as inserted after name field

    if not inserted_safe_name and "product_name_safe" in product_data:  # Verify if safe name was not inserted during ordered pass
        reordered_product_data["product_name_safe"] = product_data["product_name_safe"]  # Append safe name at end when name field is missing

    return reordered_product_data  # Return reordered product data with enforced field structure


def save_product_data_json(product_data: dict, product_dir: str, url: str) -> bool:
    """
    Append the product data dictionary to a unified products.json file.
    """
    product_data = normalize_product_data_paths(product_data)
    product_data = reorder_product_data_fields(product_data, url)
    json_path = os.path.join(OUTPUT_DIRECTORY, "products.json")
    product_name = product_data.get("product_name_safe", product_data.get("product_name", product_data.get("name", "unknown")))

    try:
        data = []
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    pass
        # Prevent duplicate entries by checking if the URL already exists
        existing_urls = {item.get("url", "") for item in data if isinstance(item, dict)}
        product_url = product_data.get("url", url)
        if product_url in existing_urls:
            print(f"{BackgroundColors.YELLOW}[SKIP] Product already in products.json: {BackgroundColors.CYAN}{product_name}{Style.RESET_ALL}")
            return True  # Return True since it's already saved
        data.append(product_data)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"{BackgroundColors.GREEN}[DEBUG] Saved to unified products.json: {BackgroundColors.CYAN}{product_name}{Style.RESET_ALL}")
        return True
    except Exception as e:
        print(f"{BackgroundColors.YELLOW}[WARNING] Failed to save to products.json for: {BackgroundColors.CYAN}{product_name}{BackgroundColors.YELLOW}: {e}{Style.RESET_ALL}")
        return False


def process_single_url(url: str, index: int, context: dict, api_keys: dict) -> bool:
    """
    Processes a single product URL: verifying format, scraping it, and saving the output incrementally.

    Args:
        url (str): The URL of the product to scrape.
        index (int): The loop index of the current URL (used for logging or tracking).
        context (dict): The global context dictionary containing configurations and metadata.

    Returns:
        bool: True if the product was successfully scraped and saved, False otherwise.
    """
    
    # Simple single attempt scraping
    product_data = scrape_product(url, api_keys)
    if product_data is None:
        context["needs_captcha_refresh"] = True
        return False
        
    if product_data:
        # Validate product data before saving
        name = str(product_data.get("name", "")).strip()
        price = str(product_data.get("current_price_integer", "")).strip()
        if name in ("", "Unknown Product", "None", "none", "null", "N/A"):
            print(f"{BackgroundColors.YELLOW}[SKIP] Invalid product name for {url}: '{name}'{Style.RESET_ALL}")
            return False
        if price in ("", "0", "None", "none"):
            print(f"{BackgroundColors.YELLOW}[SKIP] Invalid product price for {url}: '{price}'{Style.RESET_ALL}")
            return False
        # Save to JSON only once upon success
        save_product_data_json(product_data, "Outputs/products.json", url)
        
        # Pass the flag back via context
        if product_data.get("_captcha_encountered"):
            context["captcha_encountered_flag"] = True
            
        return True
        
    return False

def process_urls_pipeline(args, urls_to_process, total_urls, api_keys, context):
    """
    Orchestrates the scraping pipeline over a list of URLs, handling pauses and retries.

    Iterates through the provided list of URLs, calling `process_single_url` on each.
    Implements a random delay between requests and a browser session reset every 10 URLs
    to prevent IP bans or CAPTCHA loops.

    Args:
        args: Parsed command line arguments.
        urls_to_process (list): A list of product URLs to be scraped.
        total_urls (int): The total number of URLs initially parsed.
        api_keys (dict): The dictionary of API keys (e.g. Gemini).
        context (dict): The configuration dictionary for this run.
    """
    # Load previously scraped URLs to skip them
    scraped_urls = set()
    unified_json_path = "Outputs/products.json"
    import os, json
    
    if os.path.exists(unified_json_path):
        try:
            with open(unified_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if "url" in item:
                            name = str(item.get("name", "")).strip().lower()
                            # Do not count as scraped if the name indicates a failure
                            if name not in ["", "none", "null", "n/a", "na"]:
                                scraped_urls.add(item["url"])
        except Exception as e:
            pass
            
    urls_to_process = [u for u in urls_to_process if (u[0] if isinstance(u, tuple) else u) not in scraped_urls]
    
    filtered_out = total_urls - len(urls_to_process)
    if filtered_out > 0:
        print(f"{BackgroundColors.YELLOW}Filtered out {filtered_out} already scraped URLs.{Style.RESET_ALL}")

    if args.target > 0:
        if len(urls_to_process) > args.target:
            urls_to_process = urls_to_process[:args.target]
            print(f"Limiting scraping to {args.target} URLs as requested.")
        
    skipped_count = total_urls - len(urls_to_process)
    if skipped_count > 0:
        print(f"{BackgroundColors.YELLOW}Checkpoint: Skipped {skipped_count} total URLs. {len(urls_to_process)} remaining to scrape.{Style.RESET_ALL}")
        
    import time
    import random
    from setup_session import setup_browser_session

    scrapes_since_refresh = 0
    for index, item in enumerate(tqdm(urls_to_process, desc="Processing URLs", unit="url"), 1):
        try:
            # item is a tuple of (url, local_html_path)
            url = item[0] if isinstance(item, tuple) else item
            
            if context.get("needs_captcha_refresh"):
                print(f"\n{BackgroundColors.YELLOW}[ACTION REQUIRED] CAPTCHA encountered recently. Pausing to refresh CAPTCHA session.{Style.RESET_ALL}")
                setup_browser_session(test_url=url)
                context["needs_captcha_refresh"] = False

            success = process_single_url(url, index, context, api_keys)
            
            if context.get("captcha_encountered_flag"):
                # Captcha was seen but resolved, maybe we want to refresh before next
                context["needs_captcha_refresh"] = True
                context["captcha_encountered_flag"] = False

            if success:
                context["successful_scrapes"] += 1
                if url.startswith('http'):
                    delay = random.uniform(5.0, 15.0)
                    print(f"{BackgroundColors.CYAN}Sleeping for {delay:.2f} seconds before next request...{Style.RESET_ALL}")
                    time.sleep(delay)
            
        except Exception as e:
            print(f"{BackgroundColors.RED}Unexpected error processing {url}: {e}{Style.RESET_ALL}")

def finalize_execution(start_time: datetime.datetime, args: argparse.Namespace, context: dict, total_urls: int) -> None:
    """
    Print execution summary, timing, cleanup staging, and register exit handlers.

    :param start_time: Program start timestamp for execution time calculation.
    :param args: Parsed command-line arguments namespace.
    :param context: Mutable processing context dictionary.
    :param total_urls: Total number of URLs that were processed.
    :return: None
    """

    sorting_only_mode = context["sorting_only_mode"]  # Retrieve sorting-only mode flag from context
    successful_scrapes = context["successful_scrapes"]  # Retrieve successful scrapes counter from context
    staging_output_dir = context["staging_output_dir"]  # Retrieve staging output directory from context
    has_amazon = context["has_amazon"]  # Retrieve Amazon URL presence flag from context

    if not sorting_only_mode:  # Verify if not in sorting-only mode
        print(f"{BackgroundColors.GREEN}Successfully processed: {BackgroundColors.CYAN}{successful_scrapes}/{total_urls}{BackgroundColors.GREEN} URLs{Style.RESET_ALL}\n")  # Output the number of successful operations

    try:  # Clean up the staging directory if it's empty after processing all URLs
        if os.path.exists(staging_output_dir) and not os.listdir(staging_output_dir):  # If staging directory exists and is empty
            force_remove_path(staging_output_dir)  # Remove the empty staging directory using centralized deletion
            verbose_output(f"{BackgroundColors.GREEN}Removed empty staging directory: {BackgroundColors.CYAN}{staging_output_dir}{Style.RESET_ALL}")  # Output removal of empty staging directory
    except Exception:  # If an error occurs during cleanup, ignore it
        pass  # Best effort cleanup, ignore errors

    finish_time = datetime.datetime.now()  # Get the finish time of the program
    print(
        f"{BackgroundColors.GREEN}Execution time: {BackgroundColors.CYAN}{calculate_execution_time(start_time, finish_time)}{Style.RESET_ALL}"
    )  # Output the start and finish times
    print(
        f"{BackgroundColors.BOLD}{BackgroundColors.GREEN}Program finished.{Style.RESET_ALL}"
    )  # Output the end of the program message

    (
        atexit.register(play_sound) if RUN_FUNCTIONS["Play Sound"] else None
    )  # Register the play_sound function to be called when the program finishes


def main():
    """
    Main function.

    :param: None
    :return: None
    """

    print(
        f"{BackgroundColors.BOLD}{BackgroundColors.GREEN}Welcome to the {BackgroundColors.CYAN}Shein Web Scraper{BackgroundColors.GREEN} program!{Style.RESET_ALL}",
        end="\n",
    )  # Output the welcome message
    start_time = datetime.datetime.now()  # Get the start time of the program

    args = parse_arguments()  # Parse command-line arguments

    if args.verbose:  # Verify if verbose mode is enabled
        global VERBOSE  # Set the global VERBOSE variable to True when the --verbose flag is provided
        VERBOSE = True  # Enable verbose output





    if not setup_environment():  # Validate and load environment configuration
        return  # Exit on environment setup failure

    api_keys = load_api_keys()  # Load and validate Gemini API keys
    if not api_keys:  # Verify if at least one API key is available
        return  # Exit early when no keys are available

    if not ensure_input_file_exists():  # Ensure the input file exists, and if not, create it with instructions
        return  # Exit if unable to ensure input file

    staging_output_dir = initialize_directories()  # Create required input, output, and staging directories

    urls_to_process, total_urls = prepare_input_urls()  # Load and preprocess input URLs

    context = initialize_processing_context(staging_output_dir)  # Initialize shared runtime state

    if total_urls == 0:
        print(f"{BackgroundColors.YELLOW}No URLs to process.{Style.RESET_ALL}")
        return

    process_urls_pipeline(args, urls_to_process, total_urls, api_keys, context)  # Execute full URL processing pipeline

    pass  # Execute integrity verification and old product removal

    finalize_execution(start_time, args, context, total_urls)  # Print summary, timing, and finalize


if __name__ == "__main__":
    """
    This is the standard boilerplate that calls the main() function.

    :return: None
    """

    main()  # Call the main function
