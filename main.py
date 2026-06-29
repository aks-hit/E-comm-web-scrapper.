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
import re # For regular expressions in text processing
import shutil  # For removing directories
import subprocess  # For running system commands
import sys  # For system-specific parameters and functions
import time  # For adding delays between requests
from collections import OrderedDict  # For deterministic ordered mapping of named API keys
from colorama import Style  # For coloring the terminal
from dotenv import load_dotenv  # For loading environment variables
from Gemini import Gemini, PermanentApiFailureError, QuotaExceededError  # Imports for Gemini AI integration and custom exceptions
from Logger import Logger  # For logging output to both terminal and file
from pathlib import Path  # For handling file paths
from Shein import Shein  # Import the Shein class
from tkinter import Tk, messagebox  # For showing GUI warnings
from tqdm import tqdm  # Progress bar for URL processing
from typing import Dict, List, Optional, Tuple  # For type-annotated containers used by final verification functions
from urllib.parse import urlparse  # For parsing URL hostnames
from urls_utils import load_urls_to_process, preprocess_urls, write_urls_to_file, normalize_paths_to_unix  # URL helpers


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


def create_directory(full_directory_name, relative_directory_name):
    """
    Creates a directory.

    :param full_directory_name: Name of the directory to be created.
    :param relative_directory_name: Relative name of the directory to be created that will be shown in the terminal.
    :return: None
    """

    verbose_output(
        true_string=f"{BackgroundColors.GREEN}Creating the {BackgroundColors.CYAN}{relative_directory_name}{BackgroundColors.GREEN} directory...{Style.RESET_ALL}"
    )

    if os.path.isdir(full_directory_name):  # Verify if the directory already exists
        return  # Return if the directory already exists
    try:  # Try to create the directory
        os.makedirs(full_directory_name)  # Create the directory
    except OSError:  # If the directory cannot be created
        print(
            f"{BackgroundColors.GREEN}The creation of the {BackgroundColors.CYAN}{relative_directory_name}{BackgroundColors.GREEN} directory failed.{Style.RESET_ALL}"
        )


def detect_platform(url):
    """
    Detects the e-commerce platform from a given URL by verifying domain names.
    
    :param url: The product URL to analyze
    :return: Platform name (e.g., 'shein') or None if not recognized
    """
    
    url_lower = url.lower()  # Convert URL to lowercase for case-insensitive matching

    try:  # Try to parse the URL to obtain hostname for shortened-domain detection
        parsed = urlparse(url)  # Parse the URL into components to extract hostname and path
        hostname = (parsed.hostname or "").lower()  # Extract hostname and normalize to lowercase for comparisons
    except Exception:  # On any parsing error, degrade gracefully to empty hostname
        hostname = ""  # Use empty hostname when parsing fails to avoid exceptions

        return None  # Return None to indicate this URL should be skipped and not processed

    for platform_name, platform_id in PLATFORMS_MAP.items():  # Iterate through supported platforms to preserve existing substring detection logic
        if platform_id in url_lower:  # Verify if platform identifier substring exists in the URL (original behavior)
            verbose_output(
                f"{BackgroundColors.GREEN}Detected platform: {BackgroundColors.CYAN}{platform_name}{Style.RESET_ALL}"
            )  # Output verbose message when platform detected by substring
            return platform_id  # Return the platform identifier when detected by substring

    print(f"{BackgroundColors.YELLOW}Warning: Could not detect platform from URL: {url}{Style.RESET_ALL}")  # Warn when platform cannot be detected from the URL
    return None  # Return None if platform not recognized


def verify_affiliate_url_format(url: str) -> bool:
    """
    Verify if a URL uses the supported short affiliate redirect format.

    :param url: The product URL to verify
    :return: True if URL is acceptable or matches affiliate pattern, False if it fails regex validation
    """
    
    platform_id = detect_platform(url)  # Detect the platform identifier from the URL
    if platform_id is None:  # If platform not recognized, skip affiliate validation
        return True  # Accept as no affiliate-format validation required

    platform_modules = {  # Map platform ids to the imported class objects for lookup
        "shein": Shein,  # Shein handler class reference (class, not module)
    }  # End of mapping

    module_or_class = platform_modules.get(platform_id)  # Get the configured module/class for the detected platform
    if module_or_class is None:  # If platform not supported in the mapping
        return True  # Accept as there's nothing to validate for unknown platform

    pattern = getattr(module_or_class, "AFFILIATE_URL_PATTERN", None)  # Try to read AFFILIATE_URL_PATTERN from the class first
    if not pattern:  # If attribute not found on the class, attempt to retrieve it from the originating module object
        try:  # Try to locate the module object for the class to obtain module-level constants
            module_name = getattr(module_or_class, "__module__", None)  # Module name where the class is defined
            if isinstance(module_name, str):  # Ensure module_name is a valid string before using it as dict key
                    module_obj = sys.modules.get(module_name)  # Obtain the actual module object from sys.modules
                    if module_obj is not None:  # If module object was found in sys.modules
                        pattern = getattr(module_obj, "AFFILIATE_URL_PATTERN", None)  # Read AFFILIATE_URL_PATTERN from the module object
        except Exception:  # On any exception while resolving module, fallback to no pattern
            pattern = None  # Ensure pattern remains None on failure

    if not pattern:  # If after lookup no pattern is available to validate against
        return True  # Accept as there's no affiliate pattern to enforce for this platform

    full_pattern = rf"^(?:{pattern})(?:\?.*)?$"  # Build a full-match regex allowing optional querystring parameters

    matched = False  # Initialize matched to avoid possibly unbound variable error

    try:  # Attempt to compile and run a full-match using re.fullmatch for strict validation
        matched = re.fullmatch(full_pattern, url) is not None  # Boolean result of full-match validation
    except re.error:  # If the affiliate regex itself is invalid, inform the user and fail validation
        msg = f"{BackgroundColors.YELLOW}Warning: invalid affiliate regex for {platform_id}.{Style.RESET_ALL}"  # Construct invalid-regex warning
        try:  # Try to write the warning directly to the original stdout stream for visibility
            original_stdout = getattr(sys, "__stdout__", None)  # Get the original stdout if available
            if original_stdout is not None and hasattr(original_stdout, "write"):  # If original stdout supports write
                    try:  # Try to write and flush to original stdout
                        original_stdout.write(msg + "\n")  # Write message
                        if hasattr(original_stdout, "flush"):  # If flush exists on original stdout
                            original_stdout.flush()  # Flush to ensure immediate display
                    except Exception:  # If write/flush fails, fallback to print
                        print(msg)  # Print fallback
            else:  # If original stdout not available, fallback to print
                    print(msg)  # Print fallback
        except Exception:  # Catch-all fallback if attribute access fails
            print(msg)  # Print fallback
        return False  # Invalid regex should fail validation safely

    if not matched:  # If the URL does not strictly match the affiliate pattern
        clear_msg = f"{BackgroundColors.YELLOW}Warning: URL is not in the expected affiliate format for {platform_id}: {BackgroundColors.CYAN}{url}{Style.RESET_ALL}"  # Clear terminal and show warning message
        try:  # Try to write the clear warning to the original stdout for visibility above logger redirection
            original_stdout = getattr(sys, "__stdout__", None)  # Fetch the original stdout if present
            if original_stdout is not None and hasattr(original_stdout, "write"):  # If original stdout supports write
                    try:  # Attempt to write and flush the message
                        original_stdout.write(clear_msg + "\n")  # Write the clear message to original stdout
                        if hasattr(original_stdout, "flush"):  # If flush exists on original stdout
                            original_stdout.flush()  # Flush to ensure immediate output
                    except Exception:  # If write/flush fails, fallback to print
                        print(clear_msg)  # Print fallback
            else:  # If original stdout not accessible, fallback to print
                    print(clear_msg)  # Print fallback
        except Exception:  # Catch-all in case attribute access raises
            print(clear_msg)  # Print fallback

    return matched  # Return True only when the URL strictly matches the affiliate format


def resolve_local_html_path(local_html_path):
    """
    Attempts to resolve a local HTML path by trying various common variations.
    
    Tries the following variations in order:
    1. Path as provided
    2. With ./Inputs/ prefix
    3. With .zip suffix
    4. With /index.html suffix
    5. Combinations of prefix and suffixes
    6. If path ends with .html, try the base directory (without HTML filename):
       - As directory (reconstructing the full HTML path)
       - With ./Inputs/ prefix as directory
       - With .zip suffix
       - With ./Inputs/ prefix and .zip suffix
    
    :param local_html_path: The original path to resolve
    :return: Resolved path if found, original path if not found
    """
    
    if not local_html_path:  # If no path provided
        return local_html_path  # Return as-is
    
    if verify_filepath_exists(local_html_path):  # If path exists as provided
        if os.path.isdir(local_html_path):  # Verify if it's a directory
            index_html_path = os.path.join(local_html_path, "index.html")  # Construct path to index.html inside directory
            if verify_filepath_exists(index_html_path):  # If index.html exists inside directory
                verbose_output(f"{BackgroundColors.GREEN}Resolved local HTML path (directory): {BackgroundColors.CYAN}{local_html_path}{BackgroundColors.GREEN} -> {BackgroundColors.CYAN}{index_html_path}{Style.RESET_ALL}")  # Confirm resolution
                return index_html_path  # Return path to index.html inside directory
        verbose_output(f"{BackgroundColors.GREEN}Resolved local HTML path: {BackgroundColors.CYAN}{local_html_path}{Style.RESET_ALL}")  # Confirm resolution
        return local_html_path  # Return original path
    
    prefixes = ["", "./Inputs/"]  # Empty prefix (already tried) and Inputs directory prefix
    suffixes = ["", ".zip", "/index.html"]  # Empty suffix (already tried), zip extension, and index.html file
    
    for prefix in prefixes:  # Iterate through prefixes
        for suffix in suffixes:  # Iterate through suffixes
            if prefix == "" and suffix == "":  # If both prefix and suffix are empty
                continue  # Skip this combination as it's the original path
            
            test_path = f"{prefix}{local_html_path}{suffix}"  # Construct test path with prefix and suffix
            if verify_filepath_exists(test_path):  # If test path exists
                if os.path.isdir(test_path):  # Verify if the resolved path is a directory
                    index_html_path = os.path.join(test_path, "index.html")  # Construct path to index.html inside directory
                    if verify_filepath_exists(index_html_path):  # If index.html exists inside directory
                        verbose_output(f"{BackgroundColors.GREEN}Resolved local HTML path (directory): {BackgroundColors.CYAN}{local_html_path}{BackgroundColors.GREEN} -> {BackgroundColors.CYAN}{index_html_path}{Style.RESET_ALL}")  # Inform about resolution
                        return index_html_path  # Return path to index.html inside directory
                verbose_output(  # Output resolution message
                    f"{BackgroundColors.GREEN}Resolved local HTML path: {BackgroundColors.CYAN}{local_html_path}{BackgroundColors.GREEN} -> {BackgroundColors.CYAN}{test_path}{Style.RESET_ALL}"
                )  # End of verbose output call
                verbose_output(f"{BackgroundColors.GREEN}Resolved path variation: {BackgroundColors.CYAN}{test_path}{Style.RESET_ALL}")  # Inform user about resolution
                return test_path  # Return resolved path
    
    if local_html_path.lower().endswith(".html"):  # Verify if path ends with .html extension
        last_slash_idx = local_html_path.rfind("/")  # Find the last slash in the path
        if last_slash_idx != -1:  # If there's a slash, we can extract base path
            base_path = local_html_path[:last_slash_idx]  # Remove /filename.html to get base directory path
            html_filename = local_html_path[last_slash_idx + 1:]  # Extract the HTML filename for reconstruction
            
            verbose_output(  # Output verbose message about base path resolution attempt
                f"{BackgroundColors.YELLOW}HTML file not found. Attempting to resolve base path: {BackgroundColors.CYAN}{base_path}{Style.RESET_ALL}"
            )  # End of verbose output call
            
            base_variations = [  # List of base path variations to try
                base_path,  # Try as directory
                f"./Inputs/{base_path}",  # Try with Inputs prefix as directory
                f"{base_path}.zip",  # Try as zip file
                f"./Inputs/{base_path}.zip",  # Try with Inputs prefix as zip file
            ]  # End of base variations list
            
            for test_path in base_variations:  # Iterate through base path variations
                if verify_filepath_exists(test_path):  # If base path variation exists
                    if os.path.isdir(test_path):  # Verify if it's a directory
                        resolved_html_path = os.path.join(test_path, html_filename)  # Reconstruct full HTML file path
                        verbose_output(f"{BackgroundColors.GREEN}Resolved base directory: {BackgroundColors.CYAN}{test_path}{Style.RESET_ALL}")  # Inform about directory resolution
                        verbose_output(f"{BackgroundColors.GREEN}Using HTML file: {BackgroundColors.CYAN}{resolved_html_path}{Style.RESET_ALL}")  # Inform about HTML file path
                        return resolved_html_path  # Return reconstructed HTML path
                    else:  # It's a zip file
                        verbose_output(f"{BackgroundColors.GREEN}Resolved base path to zip file: {BackgroundColors.CYAN}{test_path}{Style.RESET_ALL}")  # Inform about zip resolution
                        return test_path  # Return zip file path
    
    return local_html_path  # Return original path even if not found


def split_phrases(text: str) -> list:
    """
    Split text into phrases using sentence and segment delimiters.

    :param text: Input text to split.
    :return: List of phrases.
    """
    
    verbose_output(f"{BackgroundColors.GREEN}Splitting text into phrases for deduplication...{Style.RESET_ALL}")  # Output the verbose message
    
    delimiters = [". ", "\n", "\r", ".", "! ", "? ", "• ", "- ", "– ", "— "]  # Delimiters for splitting
    segments = [text]  # Initialize with full text
    
    for delim in delimiters:  # Iterate over delimiters
        temp = []  # Temporary list for split segments
        for seg in segments:  # Iterate over current segments
            temp.extend(seg.split(delim))  # Split segment and extend temp
        segments = temp  # Update segments with split results
    
    return [s.strip() for s in segments if s.strip()]  # Return non-empty, stripped phrases


def normalize_text_field_for_product_scraping(value, field_name: str = "Field", warn_prefix: str = "") -> str:
    """
    Normalize a product text field to a string for downstream processing.

    Handles dict, list, None, and non-string types robustly, with warnings.

    :param value: The input value to normalize (any type).
    :param field_name: Name of the field for warning messages.
    :param warn_prefix: Optional prefix for warning messages (e.g., 'Description', 'Product details').
    :return: Normalized string value safe for text processing.
    """
    
    if isinstance(value, dict):  # If value is a dictionary
        if not value:  # If dict is empty
            verbose_output(f"{BackgroundColors.GREEN}[WARNING] {warn_prefix}{field_name} field is a dictionary but it's empty, converting to empty string.{Style.RESET_ALL}")  # Warn about empty dict
            return ""  # Return empty string for empty dict
        verbose_output(f"{BackgroundColors.GREEN}[WARNING] {warn_prefix}{field_name} field is a dictionary, converting to string. Value: {value}{Style.RESET_ALL}")  # Warn about dict type
        return ",\n".join(f"{str(k)}: {str(v)}" for k, v in value.items()) + ","  # Format as requested
    elif isinstance(value, list):  # If value is a list
        verbose_output(f"{BackgroundColors.GREEN}[WARNING] {warn_prefix}{field_name} field is a list, joining as string. Value: {value}{Style.RESET_ALL}")  # Warn about list type
        return " ".join(str(x) for x in value if isinstance(x, str))  # Join string elements
    elif value is None:  # If value is None
        verbose_output(f"{BackgroundColors.GREEN}[WARNING] {warn_prefix}{field_name} field is None, converting to empty string.{Style.RESET_ALL}")  # Warn about None value
        return ""  # Return empty string for None
    elif not isinstance(value, str):  # If value is not a string
        verbose_output(f"{BackgroundColors.GREEN}[WARNING] {warn_prefix}{field_name} field is not a string, skipping normalization. Type: {type(value)} Value: {value}{Style.RESET_ALL}")  # Warn about unknown type
        return str(value)  # Convert to string as fallback
    return value  # Return string as-is


def normalize_product_text_description_and_details(description: str, product_details: str) -> Tuple[str, str]:
    """
    Deduplicate repeated phrases in product description and product_details.

    :param description: Raw product description string.
    :param product_details: Raw product details string.
    :return: Tuple of (cleaned_description, cleaned_product_details).
    """
    
    verbose_output(f"{BackgroundColors.GREEN}Normalizing product description and details by deduplicating phrases...{Style.RESET_ALL}")  # Output the verbose message

    seen = set()  # Set to track unique phrases
    cleaned_description = []  # List for cleaned description
    cleaned_product_details = []  # List for cleaned product details

    desc_input = normalize_text_field_for_product_scraping(description, field_name="Description", warn_prefix="")  # Normalize description field
    details_input = normalize_text_field_for_product_scraping(product_details, field_name="Product details", warn_prefix="")  # Normalize product_details field

    desc_phrases = split_phrases(desc_input)  # Split description into phrases
    details_phrases = split_phrases(details_input)  # Split product_details into phrases

    for phrase in desc_phrases:  # Iterate over description phrases
        norm = phrase.lower().strip()  # Normalize phrase for deduplication
        if norm not in seen:  # Verify if phrase is unique
            cleaned_description.append(phrase)  # Append unique phrase to cleaned description
            seen.add(norm)  # Add normalized phrase to seen set

    for phrase in details_phrases:  # Iterate over product_details phrases
        norm = phrase.lower().strip()  # Normalize phrase for deduplication
        if norm not in seen:  # Verify if phrase is unique
            cleaned_product_details.append(phrase)  # Append unique phrase to cleaned product_details
            seen.add(norm)  # Add normalized phrase to seen set

    return (
        " ".join(cleaned_description).strip(),  # Join cleaned description phrases
        " ".join(cleaned_product_details).strip(),  # Join cleaned product_details phrases
    )


def copy_original_input_to_output(input_source, product_directory, base_output_dir=OUTPUT_DIRECTORY):
    """
    Copies the original input file or directory used for scraping into the product output directory.

    :param input_source: Path to the original input file, zip, or directory used for scraping
    :param product_directory: Relative product directory name under the base output directory
    :param base_output_dir: Base output directory where product directories are created
    :return: True if a copy was attempted/succeeded, False otherwise
    """

    if not input_source:  # If no input source provided
        return False  # Nothing to copy

    product_dir_full = os.path.join(base_output_dir, product_directory)  # Full path to the product output directory

    try:  # Try to copy the input source into the product output folder
        if not os.path.exists(product_dir_full):  # If the product output directory does not exist
            os.makedirs(product_dir_full, exist_ok=True)  # Create the product output directory

        if os.path.isfile(input_source):  # If the input source points to a file
            # If the file is an HTML file, prefer copying the originating zip or extracted folder
            if str(input_source).lower().endswith(".html"):  # If the source is an HTML file
                html_dir = os.path.dirname(input_source)  # Directory containing the HTML file
                html_dir_name = os.path.basename(html_dir)  # Basename of the directory containing HTML
                copied_any = False  # Track whether we copied any preferred artifact

                # Candidate zip locations to verify for the original archive
                candidate_zips = [
                    f"{html_dir}.zip",  # Same path with .zip appended
                    os.path.join(os.path.dirname(html_dir), f"{html_dir_name}.zip"),  # Parent dir + basename.zip
                    os.path.join(INPUT_DIRECTORY, f"{html_dir_name}.zip"),  # Inputs/{basename}.zip
                ]  # End candidate zips

                # Copy any existing zip candidates into the product folder
                for cz in candidate_zips:  # Iterate candidate zip paths
                    if os.path.exists(cz) and os.path.isfile(cz):  # If candidate zip exists and is a file
                        shutil.copy2(cz, product_dir_full)  # Copy the zip preserving metadata
                        verbose_output(f"{BackgroundColors.GREEN}Copied original zip {BackgroundColors.CYAN}{cz}{BackgroundColors.GREEN} to {BackgroundColors.CYAN}{product_dir_full}{Style.RESET_ALL}")  # Verbose copy message
                        copied_any = True  # Mark that we copied something

                # If the html is inside a directory, copy the entire directory as the extracted folder
                if os.path.isdir(html_dir):  # If the HTML's parent is a directory
                    dest_dir = os.path.join(product_dir_full, os.path.basename(html_dir))  # Destination inside product folder
                    if os.path.exists(dest_dir):  # If destination already exists
                        force_remove_path(dest_dir)  # Remove it to replace using centralized deletion
                    try:  # Attempt to copy the extracted directory
                        shutil.copytree(html_dir, dest_dir)  # Copy directory tree
                        verbose_output(f"{BackgroundColors.GREEN}Copied extracted directory {BackgroundColors.CYAN}{html_dir}{BackgroundColors.GREEN} to {BackgroundColors.CYAN}{dest_dir}{Style.RESET_ALL}")  # Verbose copy message
                        copied_any = True  # Mark that we copied something
                    except Exception:  # If copying directory fails, ignore and fallback
                        pass  # Continue to fallback behavior

                if copied_any:  # If we copied zip or extracted dir, do not copy the HTML itself
                    return True  # Indicate success

            # Fallback: copy the file itself when no zip/extracted folder found or not an HTML file
            shutil.copy2(input_source, product_dir_full)  # Copy the file preserving metadata
            verbose_output(f"{BackgroundColors.GREEN}Copied input file {BackgroundColors.CYAN}{input_source}{BackgroundColors.GREEN} to {BackgroundColors.CYAN}{product_dir_full}{Style.RESET_ALL}")  # Verbose copy message
            return True  # Indicate success

        if os.path.isdir(input_source):  # If the input source points to a directory
            dest_dir = os.path.join(product_dir_full, os.path.basename(input_source))  # Destination path inside the product folder
            if os.path.exists(dest_dir):  # If the destination already exists
                force_remove_path(dest_dir)  # Remove the existing destination to replace it using centralized deletion
            shutil.copytree(input_source, dest_dir)  # Copy the whole directory tree
            verbose_output(f"{BackgroundColors.GREEN}Copied input directory {BackgroundColors.CYAN}{input_source}{BackgroundColors.GREEN} to {BackgroundColors.CYAN}{dest_dir}{Style.RESET_ALL}")  # Verbose copy message
            return True  # Indicate success

        candidate = os.path.join(INPUT_DIRECTORY, os.path.basename(input_source))  # Candidate path inside INPUT_DIRECTORY
        if os.path.exists(candidate):  # If the candidate exists in Inputs
            if os.path.isfile(candidate):  # If the candidate is a file
                shutil.copy2(candidate, product_dir_full)  # Copy the candidate file
                verbose_output(f"{BackgroundColors.GREEN}Copied candidate input file {BackgroundColors.CYAN}{candidate}{BackgroundColors.GREEN} to {BackgroundColors.CYAN}{product_dir_full}{Style.RESET_ALL}")  # Verbose copy message
                return True  # Indicate success
            else:  # Candidate is a directory
                dest_dir = os.path.join(product_dir_full, os.path.basename(candidate))  # Destination path inside the product folder
                if os.path.exists(dest_dir):  # If destination already exists
                    force_remove_path(dest_dir)  # Remove existing destination using centralized deletion
                shutil.copytree(candidate, dest_dir)  # Copy the directory tree
                verbose_output(f"{BackgroundColors.GREEN}Copied candidate input directory {BackgroundColors.CYAN}{candidate}{BackgroundColors.GREEN} to {BackgroundColors.CYAN}{dest_dir}{Style.RESET_ALL}")  # Verbose copy message
                return True  # Indicate success

    except Exception as e:  # If an error occurs during copy
        print(f"{BackgroundColors.RED}Error copying input {BackgroundColors.CYAN}{input_source}{BackgroundColors.RED} to {BackgroundColors.CYAN}{product_dir_full}{BackgroundColors.RED}: {e}{Style.RESET_ALL}")  # Print error message
        return False  # Indicate failure

    return False  # Default: nothing copied


def parse_price_from_components(integer_part: str, decimal_part: str) -> Optional[float]:
    """
    Parse Brazilian-style split price components into a float.

    :param integer_part: Integer portion of the price (e.g., "1.000", "100", "N/A").
    :param decimal_part: Decimal portion of the price (e.g., "99", "00", "N/A").
    :return: Float price value, or None when components are absent or malformed.
    """

    int_str = str(integer_part).strip() if integer_part is not None else ""  # Normalize integer part to string
    dec_str = str(decimal_part).strip() if decimal_part is not None else ""  # Normalize decimal part to string

    if int_str in ("N/A", ""):  # Verify integer part is a valid non-absent value
        return None  # Return None when integer part is absent or explicitly N/A

    cleaned_int = int_str.replace(".", "").replace(",", "")  # Remove Brazilian thousands separators from integer part
    if not cleaned_int or not cleaned_int.isdigit():  # Verify cleaned integer contains only digit characters
        return None  # Return None when integer part is malformed or non-numeric

    if dec_str in ("N/A", "") or not dec_str.isdigit():  # Verify decimal part is a usable digit sequence
        dec_str = "0"  # Treat absent or non-numeric decimal as zero

    try:  # Attempt numeric reconstruction from validated components
        int_val = int(cleaned_int)  # Parse validated integer string to int
        dec_digits = len(dec_str)  # Compute decimal digit count for positional scaling
        dec_val = int(dec_str) / (10 ** dec_digits)  # Scale decimal digits to fractional value
        return float(int_val) + dec_val  # Reconstruct full float price from integer and decimal
    except (ValueError, ZeroDivisionError):  # Handle any numeric conversion or scaling error
        return None  # Return None when reconstruction fails


def validate_and_fix_product_prices(product_data: dict) -> dict:
    """
    Validate and correct pricing fields in product_data.

    Enforces two rules:
      1. old_price must never be lower than or equal to current_price.
         Violation: old_price fields and discount_percentage are reset to "N/A".
      2. discount_percentage must match the mathematically computed discount.
         Mismatch: discount_percentage is replaced with the correct computed value.

    :param product_data: Dictionary containing scraped product price fields.
    :return: Product data dictionary with corrected pricing fields.
    """

    if not isinstance(product_data, dict):  # Verify product_data is a valid dictionary
        return product_data  # Return unchanged when product_data is not a dictionary

    old_price_int_raw = str(product_data.get("old_price_integer", "")).strip()  # Extract raw old price integer part
    old_price_dec_raw = str(product_data.get("old_price_decimal", "")).strip()  # Extract raw old price decimal part
    cur_price_int_raw = str(product_data.get("current_price_integer", "")).strip()  # Extract raw current price integer part
    cur_price_dec_raw = str(product_data.get("current_price_decimal", "")).strip()  # Extract raw current price decimal part
    discount_raw = str(product_data.get("discount_percentage", "")).strip()  # Extract raw discount percentage string

    old_price = parse_price_from_components(old_price_int_raw, old_price_dec_raw)  # Parse old price into float
    cur_price = parse_price_from_components(cur_price_int_raw, cur_price_dec_raw)  # Parse current price into float

    if old_price is None or cur_price is None or cur_price <= 0.0:  # Verify both prices are parseable and current price is positive
        return product_data  # Return unchanged when prices cannot be validated

    if old_price < cur_price:  # Verify old price is strictly greater than current price
        print(
            f"{BackgroundColors.YELLOW}[WARNING] Invalid old price detected: "
            f"R${old_price_int_raw},{old_price_dec_raw} <= "
            f"R${cur_price_int_raw},{cur_price_dec_raw}. "
            f"Resetting old price and discount to N/A.{Style.RESET_ALL}"
        )  # Log warning for invalid old price relationship
        product_data["old_price_integer"] = "N/A"  # Reset old price integer to absent sentinel
        product_data["old_price_decimal"] = "N/A"  # Reset old price decimal to absent sentinel
        product_data["discount_percentage"] = "N/A"  # Reset discount to absent sentinel
        return product_data  # Return with invalid old price fields cleared

    computed_discount_pct = round((old_price - cur_price) / old_price * 100)  # Compute mathematically correct discount percentage
    computed_discount_str = f"{computed_discount_pct}%"  # Format computed discount as "XX%" string

    provided_discount_str = discount_raw.replace("%", "").strip()  # Strip percent symbol for numeric comparison
    provided_discount_num = None  # Initialize parsed discount numeric value

    if provided_discount_str and provided_discount_str not in ("N/A",):  # Verify provided discount is a valid numeric candidate
        try:  # Attempt to parse provided discount as a number
            provided_discount_num = round(float(provided_discount_str))  # Parse and round to integer for comparison
        except (ValueError, TypeError):  # Handle non-numeric discount strings
            provided_discount_num = None  # Treat unparseable discount as absent

    if provided_discount_num is None or provided_discount_num != computed_discount_pct:  # Verify provided discount matches computed value
        if provided_discount_num is not None:  # Verify mismatch exists before logging (non-None differs from computed)
            print(
                f"{BackgroundColors.YELLOW}[WARNING] Discount mismatch detected: "
                f"provided {discount_raw} differs from computed {computed_discount_str}. "
                f"Replacing with computed value.{Style.RESET_ALL}"
            )  # Log warning for discount mismatch and replacement
        product_data["discount_percentage"] = computed_discount_str  # Replace discount with mathematically correct value

    return product_data  # Return validated and corrected product data


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

    
def validate_product_information(product_data, product_name_safe, description_file):
    """
    Validates the product information to determine if it is likely to be a real product description or a placeholder/invalid entry.

    :param product_data: The dictionary containing the scraped product data (used to verify for missing fields or values)
    :param product_name_safe: The sanitized product name (used to verify for "Unknown Product" placeholders)
    :param description_file: The path to the description file (used to verify for placeholder file paths)
    :return: Tuple of (is_valid boolean, list of reasons for invalidity)
    """

    reasons = []  # List to store reasons why the product information might be invalid

    if not product_data:  # Verify if product data is None or empty
        reasons.append(f"{BackgroundColors.YELLOW}Product data is missing or empty{Style.RESET_ALL}")
        
    if product_name_safe == "Unknown Product":  # Verify if the product name is the default placeholder
        reasons.append(f"{BackgroundColors.YELLOW}Product name is a placeholder (Unknown Product){Style.RESET_ALL}") 
        
    if "name" not in product_data or not product_data["name"].strip():  # Verify if name is missing or empty
        reasons.append(f"{BackgroundColors.YELLOW}Product name is missing or empty{Style.RESET_ALL}")
        
    if "current_price_integer" not in product_data or not str(product_data["current_price_integer"]).strip() or product_data["current_price_integer"] == "0":  # Verify if price is missing, empty, or zero
        reasons.append(f"{BackgroundColors.YELLOW}Product price is missing, empty, or zero{Style.RESET_ALL}")
        
    if "discount_percentage" not in product_data or not str(product_data["discount_percentage"]).strip():  # Verify if discount is missing or empty
        reasons.append(f"{BackgroundColors.YELLOW}Product discount is missing or empty{Style.RESET_ALL}")
    
    if "description" not in product_data or not product_data["description"].strip():  # Verify if description is missing or empty
        reasons.append(f"{BackgroundColors.YELLOW}Product description is missing or empty{Style.RESET_ALL}")
        
    return (len(reasons) == 0), reasons  # Return True if valid (no reasons), otherwise False and the list of reasons


def read_template_content(template_path: Path) -> Optional[str]:
    """
    Read template file content safely.

    :param template_path: Path to the template file to read.
    :return: The file content string or None when read fails.
    """

    try:  # Try to ensure the template file exists before reading
        if not verify_filepath_exists(template_path):  # Verify template file exists at provided path
            return None  # Return None when file does not exist

        with open(template_path, "r", encoding="utf-8") as f:  # Open the template file for reading
            content = f.read()  # Read the entire file content into a string

        return content  # Return the read content on success
    except Exception:  # Handle unexpected exceptions during file I/O
        return None  # Return None when an exception occurs while reading


def detect_product_name(content: str) -> Optional[str]:
    """
    Detect the product name from template content.

    :param content: The template file content string.
    :return: The detected product name string or None when not found.
    """

    product_name = None  # Initialize variable for detected product name

    for line in content.splitlines():  # Iterate through each line to find a sensible title
        if line and re.search(r"[A-Za-zÀ-ž0-9]", line):  # Verify line contains visible alphanumeric characters
            product_name = line.strip()  # Use the first sensible non-empty line as product name
            break  # Stop after locating the first candidate product name

    return product_name  # Return detected product name or None


def detect_platform_indicator(content: str) -> bool:
    """
    Detect whether a platform indicator exists in the content.

    :param content: The template file content string.
    :return: True when a platform indicator is found, False otherwise.
    """

    normalized_content = re.sub(r"[^a-z0-9]+", "", content.lower())  # Normalize content to compare compact platform names regardless of spaces/punctuation

    for display_name, platform_id in PLATFORMS_MAP.items():  # Iterate platform display and id mappings
        spaced_display_name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", display_name)  # Split camel-cased platform name into spaced variant
        compact_display_name = re.sub(r"[^a-z0-9]+", "", display_name.lower())  # Compact display name for normalized comparison
        compact_platform_id = re.sub(r"[^a-z0-9]+", "", platform_id.lower())  # Compact platform id for normalized comparison

        if re.search(rf"\b{re.escape(display_name)}\b", content, re.IGNORECASE):  # Verify original display name appears in content
            return True  # Return True immediately when a platform indicator is detected

        if re.search(rf"\b{re.escape(spaced_display_name)}\b", content, re.IGNORECASE):  # Verify spaced display variant appears in content
            return True  # Return True immediately when a platform indicator is detected

        if re.search(rf"\b{re.escape(platform_id)}\b", content, re.IGNORECASE):  # Verify platform id appears in content
            return True  # Return True immediately when a platform indicator is detected

        if compact_display_name in normalized_content or compact_platform_id in normalized_content:  # Verify compact forms against normalized content as a final fallback
            return True  # Return True when compact indicator match is detected

    return False  # Return False when no known platform indicator was found


def detect_product_url(content: str) -> Optional[str]:
    """
    Detect the first HTTP/HTTPS URL in the content.

    :param content: The template file content string.
    :return: The matched URL string or None when not found.
    """

    match = re.search(r"https?://[\w\-\.\/~\?&=%#]+", content)  # Search for HTTP/HTTPS URL using existing pattern
    return match.group(0) if match else None  # Return matched URL or None


def detect_price_fields(content: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Detect price-like tokens and extract current and old prices.

    :param content: The template file content string.
    :return: Tuple(current_price, old_price, price_matches).
    """

    price_matches = re.findall(r"R\$\s*[\d\.,]+|\b[\d]{1,3}(?:[\.,][\d]{2,3})\b", content)  # Find potential price tokens using existing pattern

    current_price = None  # Initialize current price variable
    old_price = None  # Initialize old price variable

    if price_matches:  # If one or more price-like tokens were found
        por_match = re.search(r"POR APENAS\s*\*?R\$\s*([\d\.,]+)\*?", content, re.IGNORECASE)  # Try to capture current price from explicit phrase
        if por_match:  # Verify the explicit current price phrase matched
            current_price = por_match.group(1).strip()  # Extract numeric portion for current price

        de_match = re.search(r"DE\s*\*?R\$\s*([\d\.,]+)\*?", content, re.IGNORECASE)  # Try to capture old price from explicit phrase
        if de_match:  # Verify the explicit old price phrase matched
            old_price = de_match.group(1).strip()  # Extract numeric portion for old price

        if current_price is None and old_price is None and any(m.startswith("R$") for m in price_matches):  # Use currency-prefixed fallback when explicit phrases not present
            r_prices = [m for m in price_matches if m.strip().startswith("R$")]  # Collect tokens that explicitly include currency prefix
            if r_prices:  # Verify there is at least one currency-prefixed token for fallback logic
                if len(r_prices) == 1:  # If only one currency-prefixed token exists
                    current_price = re.sub(r"[^\d,\.]", "", r_prices[0]).strip()  # Normalize token into numeric string for current price
                else:  # If multiple currency-prefixed tokens exist
                    old_price = re.sub(r"[^\d,\.]", "", r_prices[0]).strip()  # Normalize first token as old price
                    current_price = re.sub(r"[^\d,\.]", "", r_prices[-1]).strip()  # Normalize last token as current price

    return current_price, old_price, price_matches  # Return extracted price values and the raw matches list


def validate_price_relationships(old_price: Optional[str], current_price: Optional[str], content: str) -> Tuple[bool, Optional[str]]:
    """
    Validate logical relationships between detected price fields.

    :param old_price: The detected old price string or None.
    :param current_price: The detected current price string or None.
    :param content: The template file content string.
    :return: Tuple(valid_flag, error_message_or_None).
    """

    try:  # Try to parse numeric strings into floats for comparison
        def parse_price(p: str) -> float:  # Define inline parser for localized numeric strings
            return float(p.replace(".", "").replace(",", "."))  # Convert Brazilian-style numeric to python float

        parsed_old = parse_price(old_price) if old_price else None  # Parse old price when present
        parsed_current = parse_price(current_price) if current_price else None  # Parse current price when present
    except Exception:  # Handle parsing exceptions gracefully
        parsed_old = None  # Reset parsed_old on parse failure
        parsed_current = None  # Reset parsed_current on parse failure

    if old_price and not current_price:  # Verify old price must not appear without a current price
        return False, "inconsistent price fields detected"  # Return invalid status and reason when old price exists alone

    discount_present = bool(re.search(r"\d{1,3}%|desconto", content, re.IGNORECASE))  # Detect discount percentage or keyword using existing pattern
    if discount_present and not old_price:  # Verify discount must not appear without old price
        return False, "inconsistent price fields detected"  # Return invalid status and reason when discount appears without old price

    if parsed_old is not None and parsed_current is not None and abs(parsed_old - parsed_current) < 1e-6:  # Verify old and current prices are not equal
        return False, "inconsistent price fields detected"  # Return invalid status when prices are equal

    return True, None  # Return valid status when all logical price verifications passed


def output_missing_fields(missing_fields: List[str]) -> bool:
    """
    Output formatted warning messages for missing mandatory fields and return true if any fields are missing.

    :param missing_fields: List of missing field names.
    :return: True if any fields are missing, False otherwise.
    """
    
    if not missing_fields:  # If the list of missing fields is empty
        return False  # Return False when no fields are missing

    for field in missing_fields:  # Iterate each missing field to create a warning message
        print(f"{BackgroundColors.RED}Template validation failed: missing mandatory field {BackgroundColors.GREEN}{field}{Style.RESET_ALL}")  # Append formatted message for the missing field
    
    return True  # Return True when any missing fields are found


def validate_template_file(template_path: Path) -> bool:
    """
    Orchestrate template validation using smaller validation functions.

    :param template_path: Path to the template file to validate.
    :return: True when template is valid, False when invalid.
    """

    content = read_template_content(template_path)  # Read template file content safely and get string or None

    if content is None:  # Verify the template content was read successfully
        print(f"{BackgroundColors.YELLOW}[WARNING] Template validation failed: missing mandatory field Template File{Style.RESET_ALL}")  # Log warning when file missing or unreadable
        return False  # Return False when content could not be read

    missing_fields: List[str] = []  # Initialize list to collect missing mandatory fields

    product_name = detect_product_name(content)  # Detect product name from content using dedicated function
    if not product_name:  # Verify product name detection result
        missing_fields.append("Product name")  # Record missing product name when detection failed

    platform_ok = detect_platform_indicator(content)  # Detect platform indicator presence using dedicated function
    if not platform_ok:  # Verify platform indicator detection result
        missing_fields.append("Platform indicator")  # Record missing platform indicator when detection failed

    product_url = detect_product_url(content)  # Detect product URL using dedicated function
    if not product_url:  # Verify product URL detection result
        missing_fields.append("Product URL")  # Record missing product URL when detection failed

    current_price, old_price, _ = detect_price_fields(content)  # Detect price fields using dedicated function
    if not current_price:  # Verify current price detection result
        missing_fields.append("Current price")  # Record missing current price when detection failed

    if missing_fields:  # If any mandatory fields are missing, build and emit warnings
        msgs = output_missing_fields(missing_fields)  # Build warning messages for missing fields
        return not msgs  # Return False when mandatory fields are missing

    valid_prices, reason = validate_price_relationships(old_price, current_price, content)  # Validate logical price relationships
    if not valid_prices:  # Verify result of price relationship validation
        print(f"{BackgroundColors.YELLOW}[WARNING] Template validation failed: {BackgroundColors.GREEN}{reason}{Style.RESET_ALL}")  # Print price inconsistency warning with color
        return False  # Return False when price relationships are invalid

    verbose_output(f"{BackgroundColors.GREEN}Template validation successful{Style.RESET_ALL}")  # Output verbose success message when validation passes

    return True  # Return True when all validations passed


def ensure_history_file_exists(history_file_path: str) -> bool:
    """
    Ensure the JSON history file exists and create it if missing.

    :param history_file_path: Path to the JSON history file.
    :return: True if the history file exists or was created successfully.
    """

    history_path = Path(history_file_path)  # Create a Path object for the history file
    if not history_path.exists():  # Verify if the history file does not exist
        try:  # Try to create an empty JSON file when missing
            with history_path.open("w", encoding="utf-8") as f:  # Open the history file for writing
                json.dump({}, f, indent=2, ensure_ascii=False)  # Initialize file with empty JSON object
        except Exception as e:  # Handle any exception during file creation
            print(f"[ERROR] Failed to create history file: {e}")  # Log the error to stdout
            return False  # Return False when file creation failed
    return True  # Return True when file already exists or was created


def read_history_for_day(day_str: str, history_file_path: str) -> dict:
    """
    Read and return the history dictionary for a given day from the JSON history file.

    :param day_str: Day string in format "DD-MM-YYYY" to read history for.
    :param history_file_path: Path to the JSON history file.
    :return: Dictionary with the history for the requested day (empty dict when none).
    """

    if not ensure_history_file_exists(history_file_path):  # Verify the history file exists or was created
        return {}  # Return empty dict when history file is unavailable

    try:  # Try to read the JSON history file
        with open(history_file_path, "r", encoding="utf-8") as f:  # Open the history file for reading
            data = json.load(f)  # Load the JSON content into a Python object
    except Exception:  # Handle JSON parsing or IO exceptions
        data = {}  # Fallback to empty dict when reading fails

    return data.get(day_str, {})  # Return the day's history or empty dict when not present


def save_history_file(history: dict, history_file_path: str) -> None:
    """
    Save the full history dictionary to the JSON history file on disk.

    :param history: Full history dictionary to persist.
    :param history_file_path: Path to the JSON history file.
    :return: None
    """

    try:  # Try to write the history data to the JSON file
        with open(history_file_path, "w", encoding="utf-8") as f:  # Open the history file for writing
            json.dump(history, f, indent=2, ensure_ascii=False)  # Persist history with readable indentation
    except Exception as e:  # Handle any exceptions during write
        print(f"[ERROR] Failed to save history file: {e}")  # Log the error to stdout
        return  # Return early on failure


def append_processed_product_to_history(day_str: str, platform_name: str, product_name: str, affiliate_url: str, old_price: str, current_price: str, discount_percent: str, history_file_path: str) -> None:
    """
    Append a processed product entry into the JSON history file under the given day and platform.

    :param day_str: Day string in format "DD-MM-YYYY" to store the entry under.
    :param platform_name: Platform name to group the entry (e.g., "Shein").
    :param product_name: Name of the product to record.
    :param affiliate_url: Affiliate or product URL to record.
    :param old_price: Old price value as string to record.
    :param current_price: Current price value as string to record.
    :param discount_percent: Discount percentage as string to record.
    :param history_file_path: Path to the JSON history file.
    :return: None
    """

    if not ensure_history_file_exists(history_file_path):  # Verify the history file exists or was created
        return  # Return early when history file cannot be ensured

    try:  # Try to read existing history content
        with open(history_file_path, "r", encoding="utf-8") as f:  # Open the history file for reading
            history = json.load(f)  # Load the existing history dictionary from file
    except Exception:  # Handle read/parse exceptions by initializing empty history
        history = {}  # Use an empty dict when existing history cannot be read

    day_records = history.get(day_str, {})  # Retrieve the day's grouped records or empty dict

    platform_records = day_records.get(platform_name, [])  # Retrieve the platform list or initialize empty list

    product_entry = {  # Build the product entry dictionary with required fields
        "Product Name": product_name,  # Store the product name
        "Affiliate URL": affiliate_url,  # Store the affiliate or product URL
        "Old Price": old_price,  # Store the old price string
        "Current Price": current_price,  # Store the current price string
        "Discount (%)": discount_percent,  # Store the discount percentage string
    }

    platform_records.append(product_entry)  # Append the new product entry to the platform list

    day_records[platform_name] = platform_records  # Update the day's records with the platform list

    history[day_str] = day_records  # Update the full history with the day's records

    save_history_file(history, history_file_path)  # Persist the updated history to disk


def remove_url_line_from_single_file(url: str, local_html_path, target_file_path: str) -> bool:
    """
    Removes a line containing the specified URL from a single target file.

    :param url: The URL to remove from the target file.
    :param local_html_path: Optional local HTML path to match for more precise removal.
    :param target_file_path: Absolute or relative path to the file to modify.
    :return: True if a line was removed, False otherwise.
    """

    try:  # Wrap file operations to avoid crashing on IO errors
        if not verify_filepath_exists(target_file_path):  # Verify if the target file exists before reading
            return False  # Indicate nothing removed when file is absent

        removed = False  # Track whether a matching line was removed
        with open(target_file_path, "r", encoding="utf-8") as f:  # Read current target file contents
            lines = f.readlines()  # Load all lines from target file

        new_lines = []  # Initialize list to collect lines to keep after removal

        for line in lines:  # Iterate over each existing line in the file
            stripped = line.strip()  # Trim whitespace from current line

            if not stripped:  # Preserve empty lines without alteration
                new_lines.append(line)  # Keep blank lines as-is
                continue  # Continue to next line

            parts = stripped.split(None, 1)  # Split into at most 2 tokens (URL and optional path)
            first_token = parts[0] if parts else ""  # Extract URL token from split result
            second_token = parts[1].strip() if len(parts) > 1 else None  # Extract optional local path when present

            if not removed and first_token == url:  # Candidate match on URL token
                if local_html_path:  # Verify if caller provided a local path for exact matching
                    if second_token and os.path.normpath(second_token) == os.path.normpath(local_html_path):  # Exact local path match against normalized paths
                        removed = True  # Mark line as removed and skip appending
                        continue  # Skip appending matched line
                    else:  # URL matches but local path differs
                        new_lines.append(line)  # Keep this line when local path does not match
                        continue  # Continue processing remaining lines
                else:  # No local path required; remove first matching URL occurrence
                    removed = True  # Mark line as removed and skip appending
                    continue  # Skip appending matched line

            new_lines.append(line)  # Keep non-matching line in output

        if removed:  # Write updated lines back to target file only when a line was removed
            tmp_path = target_file_path + ".tmp"  # Temporary file path for safe atomic write
            with open(tmp_path, "w", encoding="utf-8") as f:  # Write updated content to temp file
                f.writelines(new_lines)  # Write kept lines to temporary file
            try:  # Attempt atomic replace of target file
                os.replace(tmp_path, target_file_path)  # Replace original with temp file atomically
            except Exception:  # Fallback to non-atomic write when atomic replace fails
                with open(target_file_path, "w", encoding="utf-8") as f:  # Open original for direct overwrite
                    f.writelines(new_lines)  # Write kept lines directly to original file

        return removed  # Return whether a matching line was removed
    except Exception:  # On any error, do not fail the scraping run
        return False  # Indicate nothing removed due to exception


def remove_url_line_from_input_file(url, local_html_path=None):
    """
    Removes a line containing the specified URL from the input file and its backup. If local_html_path is provided, it will only remove the line if it matches both the URL and the local HTML path.

    :param url: The URL to remove from the input file.
    :param local_html_path: Optional local HTML path to match for more precise removal.
    :return: True if a line was removed from the primary input file, False otherwise.
    """

    verbose_output(
        f"{BackgroundColors.GREEN}Removing URL from input file: {BackgroundColors.CYAN}{url}{Style.RESET_ALL}"
    )  # Output the verbose message

    backup_file_path = INPUT_FILE.replace(".txt", "-backup.txt")  # Derive backup file path from primary input file path

    removed = remove_url_line_from_single_file(url, local_html_path, INPUT_FILE)  # Remove URL line from primary input file
    remove_url_line_from_single_file(url, local_html_path, backup_file_path)  # Synchronize removal to backup file to maintain consistency

    return removed  # Return whether a line was removed from the primary input file


def write_prompt_to_file(prompt_content: str, output_directory: str) -> bool:
    """
    Write the Gemini prompt content to Prompt.txt in the specified directory.

    :param prompt_content: The full prompt string to write.
    :param output_directory: The directory where Prompt.txt will be saved.
    :return: True if the file was written successfully, False otherwise.
    """
    
    verbose_output(f"{BackgroundColors.GREEN}Writing Prompt.txt to directory: {BackgroundColors.CYAN}{output_directory}{Style.RESET_ALL}")  # Output the verbose message

    try:
        if not os.path.isdir(output_directory):  # Verify if the output directory exists
            os.makedirs(output_directory, exist_ok=True)  # Create the output directory if it does not exist

        prompt_file_path = os.path.join(output_directory, "Prompt.txt")  # Build the full path for Prompt.txt

        with open(prompt_file_path, "w", encoding="utf-8") as f:  # Open Prompt.txt for writing with UTF-8 encoding
            f.write(prompt_content)  # Write the prompt content to Prompt.txt

        verbose_output(f"{BackgroundColors.GREEN}Prompt.txt written to: {BackgroundColors.CYAN}{prompt_file_path}{Style.RESET_ALL}")  # Log successful write
        return True  # Return True when file is written successfully
    except Exception as e:
        print(f"{BackgroundColors.YELLOW}[WARNING] Failed to write Prompt.txt: {e}{Style.RESET_ALL}")  # Log warning on failure
        return False  # Return False when file writing fails


def is_model_configuration_failure(error: PermanentApiFailureError) -> bool:
    """
    Determine whether a permanent API error represents a model selection/configuration failure.

    :param error: PermanentApiFailureError raised by the Gemini layer.
    :return: True when the error indicates invalid or unavailable model selection, otherwise False.
    """

    status_text = str(getattr(error, "status_text", "") or "").strip().upper()  # Normalize permanent status text for deterministic comparisons.
    raw_message = str(error)  # Read high-level permanent error message for keyword matching.
    original_message = str(getattr(error, "original_error", "") or "")  # Read original SDK error message for keyword matching.
    combined_text = f"{raw_message} {original_message}".lower()  # Merge both messages into a single normalized text corpus.

    has_model_token = "model" in combined_text or "models/" in combined_text  # Verify if message references model identifiers directly.
    has_not_found_hint = "not found" in combined_text or "not_found" in combined_text  # Verify if message reports missing resources.
    has_invalid_hint = "invalid model" in combined_text or "unsupported model" in combined_text or "unknown model" in combined_text  # Verify if message reports invalid model selection.
    has_api_version_mismatch_hint = "is not found for api version" in combined_text  # Verify if message reports model/version compatibility mismatch.

    if has_model_token and (has_not_found_hint or has_invalid_hint or has_api_version_mismatch_hint):  # Verify model-specific permanent failure indicators in message text.
        return True  # Return True when message clearly indicates model selection/configuration failure.

    if status_text == "NOT_FOUND" and has_model_token:  # Verify NOT_FOUND status paired with model references for deterministic fallback classification.
        return True  # Return True when NOT_FOUND status clearly maps to model lookup failure.

    return False  # Return False when permanent failure does not match model-selection failure patterns.


def generate_marketing_text(product_description, description_file, product_data=None, product_url=None,  owner_name=None, api_key=None, key_index=1, total_keys=1, model_name: str = "gemini-3.1-flash-lite"):
    """
    Generates marketing text from product description using Gemini AI.
    Uses a single API key attempt and signals quota exhaustion for caller-side key rotation.
    
    :param product_description: The raw product description text
    :param description_file: Path to the description file (used to determine output directory)
    :param product_data: Optional dictionary containing product information (e.g., is_international)
    :param product_url: Optional product URL used to apply platform-specific prompt rules
    :param api_key: Gemini API key string to use for this single generation attempt
    :param owner_name: Optional owner name label for the API key used (for logging)
    :param key_index: 1-based index of the API key being used
    :param total_keys: Total number of available API keys for log context
    :param model_name: Gemini model name for this single generation attempt
    :return: True if successful, False otherwise
    """

    if not api_key:  # Verify if a concrete API key was provided by the caller.
        print(f"{BackgroundColors.RED}Error: No Gemini API key provided for generation.{Style.RESET_ALL}")  # Report missing key for this attempt.
        return False  # Return failure when key is unavailable.
    
    is_international = product_data.get("is_international", False) if product_data else False  # Verify if product is international
    International_instruction = ""  # Initialize international instruction as empty
    if is_international:  # If the product is international, we need to add a specific instruction to the prompt
        International_instruction = "\n\n**IMPORTANT**: This product is INTERNATIONAL. You MUST add '[INTERNATIONAL PRODUCT]: ' before the product name at the beginning of the formatted text. If the product name already comes with the 'International - ' prefix, REMOVE that prefix before writing the final title. Never duplicate the international indicator."
    
    old_price_int = str(product_data.get("old_price_integer", "")).strip() if product_data else ""
    old_price_dec = str(product_data.get("old_price_decimal", "")).strip() if product_data else ""
    current_price_int = str(product_data.get("current_price_integer", "")).strip() if product_data else ""
    current_price_dec = str(product_data.get("current_price_decimal", "")).strip() if product_data else ""
    discount = str(product_data.get("discount_percentage", "")).strip() if product_data else ""
    
    no_discount_instruction = ""
    if ((old_price_int in ["N/A", ""] or old_price_dec in ["N/A", ""]) and discount in ["N/A", ""]) or (discount in ["N/A", ""] and old_price_int == current_price_int and old_price_dec == current_price_dec and current_price_int not in ["", "N/A"] and current_price_dec not in ["", "N/A"]):
        no_discount_instruction = "\n\n**IMPORTANT**: This product DOES NOT have a discount available. The price line (💰) is MANDATORY and must remain. When the old price and the current price are equal, use EXACTLY the format: 💰 FOR ONLY *R$<CURRENT_PRICE>* (without using 'FROM'). Remove ONLY the discount line (🎟️...)."

        shein_instruction = "\n**IMPORTANT**: For Amazon products, ADD IMMEDIATELY BEFORE THE LINK LINE (👉 ...) the following message IN BOLD AND UPPERCASE: *ATTENTION: LINK VALID FOR 24 HOURS. AFTER 24 HOURS, IT ONLY REMAINS VALID IF THE PRODUCT IS ADDED TO THE CART WITHIN THAT TIMEFRAME.*"
    
    prompt = GEMINI_MARKETING_PROMPT_TEMPLATE.format(product_description=product_description) + International_instruction + no_discount_instruction + shein_instruction  # Format template with all instructions

    description_dir = os.path.dirname(description_file)  # Get directory of description file.
    write_prompt_to_file(prompt, description_dir)  # Write the exact prompt to Prompt.txt before Gemini generation

    gemini = None  # Initialize Gemini client reference for safe cleanup in all execution paths.

    try:  # Try a single-key generation request and delegate key rotation to caller.
        verbose_output(  # Emit verbose key-attempt diagnostics for this single-key attempt.
            true_string=(
                f"{BackgroundColors.GREEN}Attempting to use Gemini API key {owner_name or key_index} ({key_index}/{total_keys})...{Style.RESET_ALL}"
            )
        )  # Output verbose message.

        verbose_output(  # Emit verbose model-attempt diagnostics for this single-model attempt.
            true_string=(
                f"{BackgroundColors.GREEN}Attempting Gemini model {BackgroundColors.CYAN}{model_name}{BackgroundColors.GREEN} with API key {owner_name or key_index}.{Style.RESET_ALL}"
            )
        )  # Output verbose message.

        gemini = Gemini(api_key, api_key_index=key_index, model_name=model_name)  # Create Gemini instance with numeric key index and selected model name.
        formatted_output = gemini.generate_content(prompt)  # Generate formatted marketing text with the provided key.

        if formatted_output:  # Verify if generation returned content.
            formatted_file = os.path.join(description_dir, f"Template.txt")  # Build output file path.
            gemini.write_output_to_file(formatted_output, formatted_file)  # Write output to file.
            try:  # Try to validate the generated template file immediately after writing it.
                valid_template = validate_template_file(Path(formatted_file))  # Validate generated template file and get boolean result.
                if not valid_template:  # Verify if validation failed for the generated template.
                    print(f"{BackgroundColors.YELLOW}[WARNING] Template validation failed for file: {BackgroundColors.CYAN}{formatted_file}{Style.RESET_ALL}")  # Log warning when template is invalid.
            except Exception as e:  # Handle unexpected exceptions raised by the validation function.
                print(f"{BackgroundColors.YELLOW}[WARNING] Template validation failed: {e}{Style.RESET_ALL}")  # Log warning including exception message when validation raises.

            return True  # Return success for this key attempt even if validation logged warnings.

        verbose_output(f"{BackgroundColors.YELLOW}API key {owner_name or key_index} returned empty response.{Style.RESET_ALL}")  # Report empty successful-response body.
        return False  # Return failure for empty response.
    except QuotaExceededError as e:  # Handle controlled quota exhaustion from Gemini layer.
        print(f"{BackgroundColors.YELLOW}[WARNING] API key {BackgroundColors.CYAN}{owner_name or key_index}{BackgroundColors.YELLOW} quota exhausted. Retry category: {BackgroundColors.CYAN}{e.status_text or 'QUOTA_EXHAUSTED'}{BackgroundColors.YELLOW}. Rotating to next API key.{Style.RESET_ALL}")  # Emit deterministic quota-rotation warning with retry category.
        raise e  # Re-raise controlled signal so caller can rotate without skipping URL.
    except PermanentApiFailureError as e:  # Handle permanent non-retryable API failure from Gemini layer.
        if is_model_configuration_failure(e):  # Verify if permanent error is strictly model-selection related.
            print(f"{BackgroundColors.YELLOW}[WARNING] Permanent model failure detected for model {BackgroundColors.CYAN}{model_name}{BackgroundColors.YELLOW} with key {BackgroundColors.CYAN}{owner_name or key_index}{BackgroundColors.YELLOW}. Falling back to next model.{Style.RESET_ALL}")  # Report model-specific permanent failure and allow deterministic fallback.
            return False  # Return failure for this model attempt so caller can continue fallback sequence.
        print(f"{BackgroundColors.RED}[ERROR] Permanent API failure with key {BackgroundColors.CYAN}{owner_name or key_index}{BackgroundColors.RED}: {e}{Style.RESET_ALL}")  # Report permanent failure for this key attempt.
        raise e  # Re-raise permanent failure signal so caller can abort all key rotation.
    except Exception as e:  # Handle non-quota generation failures.
        verbose_output(f"{BackgroundColors.RED}Error with API key {owner_name or key_index}: {e}{Style.RESET_ALL}")  # Report unexpected generation failure.
        return False  # Return failure for non-quota errors.
    finally:  # Guarantee client cleanup regardless of success, quota signal, or generic failure.
        if gemini is not None:  # Verify if Gemini client was instantiated before cleanup.
            gemini.close()  # Close Gemini client to release resources.


def build_expected_index_url_map(urls_to_process: list) -> Dict[int, str]:
    """
    Builds expected index-to-URL mapping from processing input.

    :param urls_to_process: List of tuples containing URL and optional local HTML path.
    :return: Dictionary mapping 1-based index to URL.
    """

    expected_map = {}  # Store expected 1-based index mapped to URL

    for index, item in enumerate(urls_to_process, 1):  # Iterate through input tuples preserving deterministic order
        url = item[0] if isinstance(item, tuple) and len(item) > 0 else str(item)  # Resolve URL field from tuple-safe structure
        expected_map[index] = url  # Persist URL for this expected row index

    return expected_map  # Return expected index-to-URL mapping


def normalize_path(path: str) -> str:
    """
    Normalizes a filesystem path into Unix-style format.

    :param path: Input filesystem path.
    :return: Normalized path using forward slashes.
    """
    
    return os.path.normpath(path).replace("\\", "/")


def to_seconds(obj):
    """
    Converts various time-like objects to seconds.
    
    :param obj: The object to convert (can be int, float, timedelta, datetime, etc.)
    :return: The equivalent time in seconds as a float, or None if conversion fails
    """
    
    if obj is None:  # None can't be converted
        return None  # Signal failure to convert
    if isinstance(obj, (int, float)):  # Already numeric (seconds or timestamp)
        return float(obj)  # Return as float seconds
    if hasattr(obj, "total_seconds"):  # Timedelta-like objects
        try:  # Attempt to call total_seconds()
            return float(obj.total_seconds())  # Use the total_seconds() method
        except Exception:
            pass  # Fallthrough on error
    if hasattr(obj, "timestamp"):  # Datetime-like objects
        try:  # Attempt to call timestamp()
            return float(obj.timestamp())  # Use timestamp() to get seconds since epoch
        except Exception:
            pass  # Fallthrough on error
    return None  # Couldn't convert


def calculate_execution_time(start_time, finish_time=None):
    """
    Calculates the execution time and returns a human-readable string.

    Accepts either:
    - Two datetimes/timedeltas: `calculate_execution_time(start, finish)`
    - A single timedelta or numeric seconds: `calculate_execution_time(delta)`
    - Two numeric timestamps (seconds): `calculate_execution_time(start_s, finish_s)`

    Returns a string like "1h 2m 3s".
    """

    if finish_time is None:  # Single-argument mode: start_time already represents duration or seconds
        total_seconds = to_seconds(start_time)  # Try to convert provided value to seconds
        if total_seconds is None:  # Conversion failed
            try:  # Attempt numeric coercion
                total_seconds = float(start_time)  # Attempt numeric coercion
            except Exception:
                total_seconds = 0.0  # Fallback to zero
    else:  # Two-argument mode: Compute difference finish_time - start_time
        st = to_seconds(start_time)  # Convert start to seconds if possible
        ft = to_seconds(finish_time)  # Convert finish to seconds if possible
        if st is not None and ft is not None:  # Both converted successfully
            total_seconds = ft - st  # Direct numeric subtraction
        else:  # Fallback to other methods
            try:  # Attempt to subtract (works for datetimes/timedeltas)
                delta = finish_time - start_time  # Try subtracting (works for datetimes/timedeltas)
                total_seconds = float(delta.total_seconds())  # Get seconds from the resulting timedelta
            except Exception:  # Subtraction failed
                try:  # Final attempt: Numeric coercion
                    total_seconds = float(finish_time) - float(start_time)  # Final numeric coercion attempt
                except Exception:  # Numeric coercion failed
                    total_seconds = 0.0  # Fallback to zero on failure

    if total_seconds is None:  # Ensure a numeric value
        total_seconds = 0.0  # Default to zero
    if total_seconds < 0:  # Normalize negative durations
        total_seconds = abs(total_seconds)  # Use absolute value

    days = int(total_seconds // 86400)  # Compute full days
    hours = int((total_seconds % 86400) // 3600)  # Compute remaining hours
    minutes = int((total_seconds % 3600) // 60)  # Compute remaining minutes
    seconds = int(total_seconds % 60)  # Compute remaining seconds

    if days > 0:  # Include days when present
        return f"{days}d {hours}h {minutes}m {seconds}s"  # Return formatted days+hours+minutes+seconds
    if hours > 0:  # Include hours when present
        return f"{hours}h {minutes}m {seconds}s"  # Return formatted hours+minutes+seconds
    if minutes > 0:  # Include minutes when present
        return f"{minutes}m {seconds}s"  # Return formatted minutes+seconds
    return f"{seconds}s"  # Fallback: only seconds


def play_sound():
    """
    Plays a sound when the program finishes and skips if the operating system is Windows.

    :param: None
    :return: None
    """

    current_os = platform.system()  # Get the current operating system
    if current_os == "Windows":  # If the current operating system is Windows
        return  # Do nothing

    if verify_filepath_exists(SOUND_FILE):  # If the sound file exists
        if current_os in SOUND_COMMANDS:  # If the platform.system() is in the SOUND_COMMANDS dictionary
            os.system(f"{SOUND_COMMANDS[current_os]} {SOUND_FILE}")  # Play the sound
        else:  # If the platform.system() is not in the SOUND_COMMANDS dictionary
            print(
                f"{BackgroundColors.RED}The {BackgroundColors.CYAN}{current_os}{BackgroundColors.RED} is not in the {BackgroundColors.CYAN}SOUND_COMMANDS dictionary{BackgroundColors.RED}. Please add it!{Style.RESET_ALL}"
            )
    else:  # If the sound file does not exist
        print(
            f"{BackgroundColors.RED}Sound file {BackgroundColors.CYAN}{SOUND_FILE}{BackgroundColors.RED} not found. Make sure the file exists.{Style.RESET_ALL}"
        )


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


def load_product_data(product_dir: str) -> Optional[dict]:
    """
    Load product_data.json from the specified product directory.

    :param product_dir: Absolute path to the product output directory.
    :return: Loaded product data dictionary or None when file is missing or unreadable.
    """

    json_path = os.path.join(product_dir, "product_data.json")  # Build full path to the product data JSON file
    product_name = os.path.basename(product_dir)  # Use directory name as product identifier for logging

    if not os.path.isfile(json_path):  # Verify if product_data.json exists before attempting to load
        print(f"{BackgroundColors.RED}[DEBUG] product_data.json not found for: {BackgroundColors.CYAN}{product_name}{Style.RESET_ALL}")  # Log missing JSON file
        return None  # Return None when file does not exist

    try:  # Try to read and parse the product data JSON file
        with open(json_path, "r", encoding="utf-8") as f:  # Open JSON file for reading with UTF-8 encoding
            product_data = json.load(f)  # Parse JSON content into dictionary
        verbose_output(true_string=f"{BackgroundColors.GREEN}[DEBUG] Loaded product_data.json for: {BackgroundColors.CYAN}{product_name}{Style.RESET_ALL}")  # Log successful JSON load
        return product_data  # Return loaded product data dictionary
    except Exception as e:  # If reading or parsing the JSON file fails
        print(f"{BackgroundColors.YELLOW}[WARNING] Failed to load product_data.json for: {BackgroundColors.CYAN}{product_name}{BackgroundColors.YELLOW}: {e}{Style.RESET_ALL}")  # Report load failure
        return None  # Return None when product data could not be loaded


def generate_and_validate_template_for_product(description_file: str, api_keys: Dict[str, str]) -> bool:
    """
    Generate and validate Template.txt for a product using its existing description file.

    :param description_file: Absolute path to the product description file.
    :param api_keys: Mapping of Gemini API owner names to API key strings.
    :return: True if generation and validation succeeded, False otherwise.
    """

    try:  # Try to read the description file content for Gemini generation
        with open(str(description_file), "r", encoding="utf-8") as f:  # Open description file with UTF-8 encoding
            product_description = f.read()  # Read full description content as generation input
    except Exception as e:  # If reading the description file fails
        print(f"{BackgroundColors.RED}Error reading description file {BackgroundColors.CYAN}{description_file}{BackgroundColors.RED}: {e}{Style.RESET_ALL}")  # Report error reading description file
        return False  # Return failure when description file cannot be read

    product_url = detect_product_url(product_description) or ""  # Detect product URL from description content for platform-specific generation instructions

    description_dir = os.path.dirname(str(description_file))  # Derive directory containing the description file for product_data loading
    product_data = load_product_data(description_dir)  # Load persisted product data from product directory for Gemini context

    success = handle_gemini_processing(product_description, description_file, product_data, product_url, api_keys)

    if not success:  # Verify if Gemini generation did not succeed
        return False  # Return failure when generation did not produce output

    template_file = os.path.join(description_dir, "Template.txt")  # Build path to the generated Template.txt file
    validate_and_fix_output_file(template_file)  # Validate and fix formatting issues in the generated template

    return True  # Return success after generation and validation complete


def generate_template_files_from_local(outputs_dir: str, api_keys: Dict[str, str]) -> None:
    """
    Traverse all timestamped output directories and generate missing Template.txt files.

    :param outputs_dir: Path to the base outputs directory to scan for timestamped run directories.
    :param api_keys: Mapping of Gemini API owner names to API key strings for generation.
    :return: None
    """

    print(f"{BackgroundColors.GREEN}Running in {BackgroundColors.CYAN}Generate Template Files from Local{BackgroundColors.GREEN} Mode.{Style.RESET_ALL}")  # Log mode activation at start of traversal

    if not os.path.isdir(outputs_dir):  # Verify if the base outputs directory exists before traversal
        print(f"{BackgroundColors.RED}Outputs directory not found: {BackgroundColors.CYAN}{outputs_dir}{Style.RESET_ALL}")  # Report missing base directory
        return  # Return early when base directory does not exist

    timestamp_pattern = re.compile(r"^\d+\. \d{4}-\d{2}-\d{2} - \d{2}h\d{2}m\d{2}s$")  # Regex matching the "{index}. YYYY-MM-DD - HHhMMmSSs" format for timestamped directories
    product_dirs = []  # List to collect valid product directory info for tqdm

    for timestamp_dir_name in sorted(os.listdir(outputs_dir)):  # Iterate timestamp directories in sorted order for deterministic processing
        timestamp_dir_path = os.path.join(outputs_dir, timestamp_dir_name)  # Build full path to the current timestamp directory

        if not os.path.isdir(timestamp_dir_path):  # Skip non-directory entries inside outputs directory
            continue  # Continue to next entry when not a directory

        if not timestamp_pattern.match(timestamp_dir_name):  # Skip directories that do not match the required timestamp format
            continue  # Continue to next entry when naming format does not match

        verbose_output(f"{BackgroundColors.GREEN}Traversing timestamp directory: {BackgroundColors.CYAN}{timestamp_dir_name}{Style.RESET_ALL}")  # Log traversal of current timestamp directory for verbose mode

        for product_dir_name in sorted(os.listdir(timestamp_dir_path)):  # Iterate product directories inside this timestamp directory in sorted order
            product_dir_path = os.path.join(timestamp_dir_path, product_dir_name)  # Build full path to the current product directory

            if not os.path.isdir(product_dir_path):  # Skip non-directory entries inside timestamp directory
                continue  # Continue to next entry when not a directory

            description_files = [  # Collect description files matching the expected naming convention
                f for f in os.listdir(product_dir_path) if f.endswith("_description.txt")
            ]  # Filter directory entries for files ending with _description.txt

            if not description_files:  # Verify if at least one description file exists in this product directory
                verbose_output(f"{BackgroundColors.YELLOW}No description file found in: {BackgroundColors.CYAN}{product_dir_name}{BackgroundColors.YELLOW}. Skipping.{Style.RESET_ALL}")  # Log missing description file for verbose mode
                continue  # Continue to next product directory when no description file is present

            template_file = os.path.join(product_dir_path, "Template.txt")  # Build expected Template.txt path for existence verification

            if os.path.exists(template_file):  # Verify if Template.txt already exists for this product
                verbose_output(f"{BackgroundColors.YELLOW}Template file already exists in: {BackgroundColors.CYAN}{product_dir_name}{BackgroundColors.YELLOW}. Skipping.{Style.RESET_ALL}")  # Log existing template file for verbose mode
                continue  # Continue to next product directory when template already exists
            product_dirs.append((product_dir_path, product_dir_name, description_files[0]))  # Collect tuple for tqdm iteration

    total = len(product_dirs)  # Compute total number of valid products to process
    
    if total == 0:  # If no valid products to process
        return  # Return early with no tqdm or further processing

    pbar = tqdm(
        product_dirs,
        desc=f"{BackgroundColors.GREEN}Generating Templates{Style.RESET_ALL}",
        unit="product",
        ncols=100,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        file=sys.__stdout__,
    )  # Initialize tqdm progress bar for product directories

    for idx, (product_dir_path, product_dir_name, description_file_name) in enumerate(pbar, 1):  # Iterate with tqdm and 1-based index
        description_file = os.path.join(product_dir_path, description_file_name)  # Select the first description file as the authoritative source
        
        template_file = os.path.join(product_dir_path, "Template.txt")  # Build expected Template.txt path for existence verification
        
        pbar.set_description(f"{BackgroundColors.GREEN}Generating {BackgroundColors.CYAN}{idx}{BackgroundColors.GREEN}/{BackgroundColors.CYAN}{total}{BackgroundColors.GREEN} - {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Update tqdm description with color and index
        
        if os.path.exists(template_file):  # Verify if Template.txt already exists for this product
            verbose_output(f"{BackgroundColors.GREEN}[DEBUG] Template.txt already exists for: {BackgroundColors.CYAN}{product_dir_name}{BackgroundColors.GREEN}. Skipping generation.{Style.RESET_ALL}")  # Log skip when template is already present
            continue  # Continue to next product directory when template already exists
        
        verbose_output(true_string=f"{BackgroundColors.GREEN}Generating Template.txt for: {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Log template generation start for this product directory
        
        success = generate_and_validate_template_for_product(description_file, api_keys)  # Generate and validate Template.txt using the extracted reusable function
        
        if success:  # Verify if generation and validation succeeded
            verbose_output(f"{BackgroundColors.GREEN}Successfully generated and validated Template.txt for: {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Log successful generation and validation
        else:  # If generation or validation failed
            print(f"{BackgroundColors.RED}Failed to generate Template.txt for: {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Log generation failure for this product


def locate_existing_prompt_file(product_dir_path: str) -> Optional[str]:
    """
    Locate an existing prompt file in the product directory using supported filename variants.

    :param product_dir_path: Absolute path to the product output directory.
    :return: Absolute prompt file path when found, otherwise None.
    """

    for prompt_file_name in ("Prompt.txt", "prompt.txt"):  # Iterate prompt filename variants for compatibility with existing and new naming styles.
        prompt_path = os.path.join(product_dir_path, prompt_file_name)  # Build absolute path for current prompt filename candidate.
        if os.path.isfile(prompt_path):  # Verify if this prompt file candidate exists as a regular file.
            return prompt_path  # Return first existing prompt file path.

    return None  # Return None when no supported prompt file exists.


def collect_products_missing_templates(outputs_dir: str) -> List[Tuple[str, str, str]]:
    """
    Collect product directories that require Template.txt generation from Prompt.txt.

    :param outputs_dir: Base outputs directory to scan.
    :return: List of tuples containing (product_dir_path, product_dir_name, prompt_file_path).
    """

    timestamp_pattern = re.compile(r"^\d+\. \d{4}-\d{2}-\d{2} - \d{2}h\d{2}m\d{2}s$")  # Verify timestamp directory format.
    product_dirs: List[Tuple[str, str, str]] = []  # Store valid product candidates.

    for timestamp_dir_name in sorted(os.listdir(outputs_dir)):  # Iterate timestamp directories deterministically.
        timestamp_dir_path = os.path.join(outputs_dir, timestamp_dir_name)  # Build full timestamp path.
        if not os.path.isdir(timestamp_dir_path):  # Verify entry is directory.
            continue  # Skip invalid entries.
        if not timestamp_pattern.match(timestamp_dir_name):  # Verify timestamp format compliance.
            continue  # Skip non-matching directories.

        verbose_output(f"{BackgroundColors.GREEN}Traversing timestamp directory: {BackgroundColors.CYAN}{timestamp_dir_name}{Style.RESET_ALL}")  # Log traversal step.

        for product_dir_name in sorted(os.listdir(timestamp_dir_path)):  # Iterate product directories.
            product_dir_path = os.path.join(timestamp_dir_path, product_dir_name)  # Build product path.
            if not os.path.isdir(product_dir_path):  # Verify directory type.
                continue  # Skip invalid entries.

            template_file = os.path.join(product_dir_path, "Template.txt")  # Define template path.

            if os.path.exists(template_file):  # Verify template already exists.
                verbose_output(f"{BackgroundColors.YELLOW}Template already exists in: {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Log skip reason.
                continue  # Skip already processed products.

            prompt_file = locate_existing_prompt_file(product_dir_path)  # Resolve prompt file.

            if prompt_file is None:  # Verify prompt existence.
                verbose_output(f"{BackgroundColors.YELLOW}Prompt not found in: {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Log missing prompt.
                continue  # Skip invalid product.

            product_dirs.append((product_dir_path, product_dir_name, prompt_file))  # Register valid product.
    return product_dirs  # Return collected product list.


def generate_template_from_prompt_content(prompt_content: str, output_directory: str, owner_name=None, api_key=None, key_index=1, total_keys=1, model_name: str = "gemini-3.1-flash-lite") -> bool:
    """
    Generate Template.txt directly from prebuilt prompt content using Gemini AI.

    :param prompt_content: Prompt text read from Prompt.txt file.
    :param output_directory: Product output directory where Template.txt will be written.
    :param owner_name: Optional owner name label for the API key used.
    :param api_key: Gemini API key string to use for this single generation attempt.
    :param key_index: 1-based index of the API key being used.
    :param total_keys: Total number of available API keys for log context.
    :param model_name: Gemini model name for this single generation attempt.
    :return: True if generation succeeded, False otherwise.
    """

    if not api_key:  # Verify if a concrete API key was provided by the caller.
        print(f"{BackgroundColors.RED}Error: No Gemini API key provided for generation.{Style.RESET_ALL}")  # Report missing key for this attempt.
        return False  # Return failure when key is unavailable.

    gemini = None  # Initialize Gemini client reference for safe cleanup in all execution paths.

    try:  # Try a single-key generation request and delegate key rotation to caller.
        verbose_output(  # Emit verbose key-attempt diagnostics for this single-key attempt.
            true_string=(
                f"{BackgroundColors.GREEN}Attempting to use Gemini API key {owner_name or key_index} ({key_index}/{total_keys})...{Style.RESET_ALL}"
            )
        )  # Output verbose message.

        verbose_output(  # Emit verbose model-attempt diagnostics for this single-model attempt.
            true_string=(
                f"{BackgroundColors.GREEN}Attempting Gemini model {BackgroundColors.CYAN}{model_name}{BackgroundColors.GREEN} with API key {owner_name or key_index}.{Style.RESET_ALL}"
            )
        )  # Output verbose message.

        gemini = Gemini(api_key, api_key_index=key_index, model_name=model_name)  # Create Gemini instance with numeric key index and selected model name.
        formatted_output = gemini.generate_content(prompt_content)  # Generate formatted marketing text using only prompt file content as input.

        if formatted_output:  # Verify if generation returned content.
            formatted_file = os.path.join(output_directory, "Template.txt")  # Build output file path.
            gemini.write_output_to_file(formatted_output, formatted_file)  # Write output to file.
            try:  # Try to validate the generated template file immediately after writing it.
                valid_template = validate_template_file(Path(formatted_file))  # Validate generated template file and get boolean result.
                if not valid_template:  # Verify if validation failed for the generated template.
                    print(f"{BackgroundColors.YELLOW}[WARNING] Template validation failed for file: {BackgroundColors.CYAN}{formatted_file}{Style.RESET_ALL}")  # Log warning when template is invalid.
            except Exception as e:  # Handle unexpected exceptions raised by the validation function.
                print(f"{BackgroundColors.YELLOW}[WARNING] Template validation failed: {e}{Style.RESET_ALL}")  # Log warning including exception message when validation raises.

            return True  # Return success for this key attempt even if validation logged warnings.

        verbose_output(f"{BackgroundColors.YELLOW}API key {owner_name or key_index} returned empty response.{Style.RESET_ALL}")  # Report empty successful-response body.
        return False  # Return failure for empty response.
    except QuotaExceededError as e:  # Handle controlled quota exhaustion from Gemini layer.
        print(f"{BackgroundColors.YELLOW}[WARNING] API key {BackgroundColors.CYAN}{owner_name or key_index}{BackgroundColors.YELLOW} quota exhausted. Retry category: {BackgroundColors.CYAN}{e.status_text or 'QUOTA_EXHAUSTED'}{BackgroundColors.YELLOW}. Rotating to next API key.{Style.RESET_ALL}")  # Emit deterministic quota-rotation warning with retry category.
        raise e  # Re-raise controlled signal so caller can rotate without skipping URL.
    except PermanentApiFailureError as e:  # Handle permanent non-retryable API failure from Gemini layer.
        if is_model_configuration_failure(e):  # Verify if permanent error is strictly model-selection related.
            print(f"{BackgroundColors.YELLOW}[WARNING] Permanent model failure detected for model {BackgroundColors.CYAN}{model_name}{BackgroundColors.YELLOW} with key {BackgroundColors.CYAN}{owner_name or key_index}{BackgroundColors.YELLOW}. Falling back to next model.{Style.RESET_ALL}")  # Report model-specific permanent failure and allow deterministic fallback.
            return False  # Return failure for this model attempt so caller can continue fallback sequence.
        print(f"{BackgroundColors.RED}[ERROR] Permanent API failure with key {BackgroundColors.CYAN}{owner_name or key_index}{BackgroundColors.RED}: {e}{Style.RESET_ALL}")  # Report permanent failure for this key attempt.
        raise e  # Re-raise permanent failure signal so caller can abort all key rotation.
    except Exception as e:  # Handle non-quota generation failures.
        verbose_output(f"{BackgroundColors.RED}Error with API key {owner_name or key_index}: {e}{Style.RESET_ALL}")  # Report unexpected generation failure.
        return False  # Return failure for non-quota errors.
    finally:  # Guarantee client cleanup regardless of success, quota signal, or generic failure.
        if gemini is not None:  # Verify if Gemini client was instantiated before cleanup.
            gemini.close()  # Close Gemini client to release resources.


def process_gemini_prompt_model_fallbacks(prompt_content: str, output_directory: str, owner: str, api_key: str, current_idx: int, total_keys: int) -> bool:
    """
    Execute deterministic Gemini model fallback attempts for prompt-based template generation.

    :param prompt_content: Prompt text read from Prompt.txt file.
    :param output_directory: Product output directory where Template.txt will be written.
    :param owner: Owner name associated with the current API key.
    :param api_key: Gemini API key used for generation attempts.
    :param current_idx: Current zero-based API key index.
    :param total_keys: Total available Gemini API keys.
    :return: True if any model succeeds, otherwise False.
    """

    for model_index, model_name in enumerate(GEMINI_MODEL_PRIORITY, 1):  # Iterate model fallback list in fixed deterministic order.
        success = generate_template_from_prompt_content(  # Execute single-key single-model Gemini generation attempt.
            prompt_content,  # Reuse same prompt content for deterministic retry behavior.
            output_directory,  # Reuse same output directory destination for deterministic retry behavior.
            owner_name=owner,  # Pass owner name for enhanced logging.
            api_key=api_key,  # Pass current key only and let caller-side logic handle rotations.
            key_index=(current_idx + 1),  # Pass numeric one-based index for Gemini client and rotation logic.
            total_keys=total_keys,  # Pass total key count for contextual logging.
            model_name=model_name,  # Pass selected model name for deterministic fallback attempt.
        )  # End single-key single-model generation call.

        if success:  # Verify whether generation succeeded for this key/model combination.
            return True  # Return success immediately after first successful fallback attempt.

        if model_index < len(GEMINI_MODEL_PRIORITY):  # Verify if another fallback model is still available.
            next_model_name = GEMINI_MODEL_PRIORITY[model_index]  # Resolve next model name using current loop position.
            print(f"{BackgroundColors.YELLOW}[WARNING] Falling back model for key {BackgroundColors.CYAN}{owner}{BackgroundColors.YELLOW}: {BackgroundColors.CYAN}{model_name}{BackgroundColors.YELLOW} -> {BackgroundColors.CYAN}{next_model_name}{Style.RESET_ALL}")  # Report deterministic model fallback transition.

    return False  # Return failure after exhausting all configured fallback models.


def generate_and_validate_template_from_prompt_for_product(prompt_file: str, api_keys: Dict[str, str]) -> bool:
    """
    Generate and validate Template.txt for a product using existing Prompt.txt content.

    :param prompt_file: Absolute path to the product prompt file.
    :param api_keys: Mapping of Gemini API owner names to API key strings.
    :return: True if generation and validation succeeded, False otherwise.
    """

    try:  # Try to read the prompt file content for Gemini generation.
        with open(str(prompt_file), "r", encoding="utf-8") as f:  # Open prompt file with UTF-8 encoding.
            prompt_content = f.read()  # Read full prompt content as generation input.
    except Exception as e:  # If reading the prompt file fails.
        print(f"{BackgroundColors.RED}Error reading prompt file {BackgroundColors.CYAN}{prompt_file}{BackgroundColors.RED}: {e}{Style.RESET_ALL}")  # Report error reading prompt file.
        return False  # Return failure when prompt file cannot be read.

    output_directory = os.path.dirname(str(prompt_file))  # Derive directory containing the prompt file for output path.

    success = handle_gemini_prompt_processing(prompt_content, output_directory, api_keys)  # Generate and validate template output using prompt-only processing path.

    if not success:  # Verify if Gemini generation did not succeed.
        return False  # Return failure when generation did not produce output.

    template_file = os.path.join(output_directory, "Template.txt")  # Build path to the generated Template.txt file.
    validate_and_fix_output_file(template_file)  # Validate and fix formatting issues in the generated template.

    return True  # Return success after generation and validation complete.


def process_template_generation_item(product_dir_path: str, product_dir_name: str, prompt_file: str, api_keys: Dict[str, str]) -> bool:
    """
    Generate and validate Template.txt for a single product directory.

    :param product_dir_path: Product directory path.
    :param product_dir_name: Product directory name.
    :param prompt_file: Prompt.txt file path.
    :param api_keys: API keys for generation.
    :return: True if successful, False otherwise.
    """

    template_file = os.path.join(product_dir_path, "Template.txt")  # Build template path.

    if os.path.exists(template_file):  # Verify template existence.
        verbose_output(f"{BackgroundColors.GREEN}[DEBUG] Template already exists for: {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Log skip.
        return True  # Treat as success because no action required.

    verbose_output(f"{BackgroundColors.GREEN}Generating Template.txt from Prompt.txt for: {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Log generation start.

    success = generate_and_validate_template_from_prompt_for_product(prompt_file, api_keys)  # Execute generation pipeline.

    if success:  # Verify success state.
        verbose_output(f"{BackgroundColors.GREEN}Successfully generated Template.txt for: {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Log success.
        return True  # Return success.

    print(f"{BackgroundColors.RED}Failed to generate Template.txt for: {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}")  # Log failure.
    return False  # Return failure.


def generate_template_files_from_prompt(outputs_dir: str, api_keys: Dict[str, str]) -> None:
    """
    Traverse all product output directories and generate missing Template.txt files from Prompt.txt.

    :param outputs_dir: Base outputs directory.
    :param api_keys: Mapping of API keys.
    :return: None
    """

    print(f"{BackgroundColors.GREEN}Running in {BackgroundColors.CYAN}Generate Template Files from Prompt{Style.RESET_ALL}")  # Log mode start.

    if not os.path.isdir(outputs_dir):  # Verify directory exists.
        print(f"{BackgroundColors.RED}Outputs directory not found: {BackgroundColors.CYAN}{outputs_dir}{Style.RESET_ALL}")  # Log error.
        return  # Exit early.

    product_dirs = collect_products_missing_templates(outputs_dir)  # Collect candidates.

    total = len(product_dirs)  # Compute workload.

    if total == 0:  # Verify empty workload.
        return  # Exit early.

    pbar = tqdm(
        product_dirs,
        desc=f"{BackgroundColors.GREEN}Generating Templates{Style.RESET_ALL}",
        unit="product",
        ncols=100,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        file=sys.__stdout__,
    )  # Initialize progress bar.

    for idx, (product_dir_path, product_dir_name, prompt_file) in enumerate(pbar, 1):  # Iterate workload.
        pbar.set_description(
            f"{BackgroundColors.GREEN}Generating {BackgroundColors.CYAN}{idx}{BackgroundColors.GREEN}/{BackgroundColors.CYAN}{total}{BackgroundColors.GREEN} - {BackgroundColors.CYAN}{product_dir_name}{Style.RESET_ALL}"
        )  # Update progress bar.

        process_template_generation_item(product_dir_path, product_dir_name, prompt_file, api_keys)  # Execute processing step.


def list_restructure_mode_target_directories(base_output_dir: str) -> List[str]:
    """
    List immediate eligible directories for standalone restructuring mode.

    :param base_output_dir: Base output directory that contains run directories.
    :return: Sorted list of absolute eligible directories excluding .staging case-insensitively.
    """

    target_directories: List[str] = []  # Initialize list for immediate eligible output directories.

    if not os.path.isdir(base_output_dir):  # Verify base output directory exists before listing entries.
        return target_directories  # Return empty list when output directory does not exist.

    for entry_name in sorted(os.listdir(base_output_dir)):  # Iterate immediate child entries in deterministic sorted order.
        if entry_name.lower() == ".staging":  # Ignore staging directory name regardless of letter casing.
            continue  # Continue to next entry when current entry is staging.

        entry_path = os.path.join(base_output_dir, entry_name)  # Build absolute path for current immediate child entry.
        if not os.path.isdir(entry_path):  # Verify current entry is a directory.
            continue  # Continue to next entry when current entry is not a directory.

        target_directories.append(entry_path)  # Append eligible immediate child directory for standalone restructuring mode.

    return target_directories  # Return collected eligible immediate directories.


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


def handle_scraping(url: str, staging_output_dir: str, local_html_path, index: int, retry_attempt: int) -> tuple:
    """
    Execute product scraping and return scrape result with retry signal.

    :param url: Product URL to scrape.
    :param staging_output_dir: Path to the staging output directory.
    :param local_html_path: Optional local HTML file path for offline mode.
    :param index: Current URL index in the processing queue.
    :param retry_attempt: Current retry attempt number.
    :return: Tuple of (scrape_result, should_retry, should_break) controlling retry flow.
    """

    verbose_output(f"{BackgroundColors.GREEN}Step 1: {BackgroundColors.CYAN}Scraping the product information{Style.RESET_ALL}")  # Step 1: Scrape the product information
    scrape_result = scrape_product(url, staging_output_dir, local_html_path)  # Scrape the product writing into staging

    if not scrape_result or len(scrape_result) != 6:  # If scraping failed or returned invalid result
        print(f"{BackgroundColors.RED}Skipping {BackgroundColors.CYAN}{url}{BackgroundColors.RED} due to scraping failure.{Style.RESET_ALL}\n")  # Notify user about skip
        try:  # Attempt to clean any partial staging output for this URL
            tmp_product_name = None  # Initialize temporary product name variable
            if isinstance(scrape_result, tuple) and scrape_result[2]:  # Verify tuple shape and product dir field
                tmp_product_name = scrape_result[2]  # Extract product directory name from scrape_result
            if tmp_product_name:  # Only proceed if we found a temporary product directory name
                tmp_path = os.path.join(staging_output_dir, tmp_product_name)  # Build staging path for that product
                if os.path.exists(tmp_path):  # Verify if the staging path exists on disk
                    force_remove_path(tmp_path)  # Remove the partial staging directory to keep staging clean using centralized deletion
        except Exception:  # Catch and ignore any errors during staging cleanup
            pass  # Ignore cleanup errors and continue

        if retry_attempt < OUTPUT_DIRECTORY_RETRY_ATTEMPTS:  # Verify if another retry attempt is still allowed
            print(f"{BackgroundColors.YELLOW}[WARNING] Output directory missing after processing URL index {index}. Retrying processing.{Style.RESET_ALL}")  # Warn and retry same URL position
            return None, True, False  # Return retry signal

        print(f"{BackgroundColors.YELLOW}[WARNING] Failed to generate output directory after retry for URL index {index}.{Style.RESET_ALL}")  # Report definitive failure after retry exhaustion
        return None, False, True  # Return break signal

    product_data = scrape_result[0]  # Extract product_data from scrape result for validation

    if not product_data:  # If scraping failed unexpectedly  # Validate product_data presence
        print(f"{BackgroundColors.RED}Skipping {BackgroundColors.CYAN}{url}{BackgroundColors.RED} due to scraping failure.{Style.RESET_ALL}\n")  # Inform about unexpected failure

        if retry_attempt < OUTPUT_DIRECTORY_RETRY_ATTEMPTS:  # Verify if another retry attempt is still allowed
            print(f"{BackgroundColors.YELLOW}[WARNING] Output directory missing after processing URL index {index}. Retrying processing.{Style.RESET_ALL}")  # Warn and retry same URL position
            return None, True, False  # Return retry signal

        print(f"{BackgroundColors.YELLOW}[WARNING] Failed to generate output directory after retry for URL index {index}.{Style.RESET_ALL}")  # Report definitive failure after retry exhaustion
        return None, False, True  # Return break signal

    return scrape_result, False, False  # Return successful scrape result with no retry or break signals


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
    verify_affiliate_url_format(url)
    
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
