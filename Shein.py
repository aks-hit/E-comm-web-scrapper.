"""
================================================================================
Shein - Shein.py
================================================================================
Description :
This script provides a Shein class for scraping product information
from Shein product pages using authenticated browser sessions. It extracts
comprehensive product details including name, prices, discount information,
descriptions, and media assets from fully rendered pages.

Key features include:
- Undetected-chromedriver sessions with an existing Chrome profile
- AI-Powered CAPTCHA solving using Gemini Vision and CDP mouse clicks
- Full page rendering with JavaScript execution
- Product name and description extraction
- Price information (current and old prices with integer and decimal parts)
- Discount percentage extraction
- Product images download
- Complete page snapshot capture (HTML + localized assets)
- Organized output in product-specific directories

Usage:
1. Import the Shein class in your main script.
2. Create an instance with a product URL:
   scraper = Shein("https://us.shein.com/product-url", driver=driver, logger=logger)
3. Call the scrape method to extract product information:
   product_data = scraper.scrape()
4. Media files are saved in ./Outputs/{Product Name}/ directory.

Outputs:
- Product data dictionary with all extracted information
- Downloaded images in ./Outputs/{Product Name}/ directory
- Complete page snapshot in ./Outputs/{Product Name}/page.html

Dependencies:
- Python >= 3.8
- undetected-chromedriver
- beautifulsoup4
- colorama
- google-genai (via Gemini.py)

Assumptions & Notes:
- Requires stable internet connection.
- Requires existing authenticated Chrome profile in ChromeProfile/ directory.
- Relies on Gemini for CAPTCHA solving.
- Website structure may change over time; CSS selectors are defined in HTML_SELECTORS.
"""
import atexit  # For playing a sound when the program finishes
import datetime  # For getting the current date and time
import json  # For parsing JSON data from script tags
import os  # For running a command in the terminal
import platform  # For getting the operating system name
import re  # For regular expressions
import shutil  # For copying local files
import subprocess  # For running ffmpeg commands
import sys  # For system-specific parameters and functions
import time  # For delays during page rendering
from bs4 import BeautifulSoup  # For parsing HTML content
from colorama import Style  # For coloring the terminal
from Logger import Logger
from Gemini import Gemini  # For logging output to both terminal and file
from pathlib import Path  # For handling file paths
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError  # For browser automation
from product_utils import normalize_product_name  # Centralized product dir name normalization
from typing import Optional, List, Tuple  # For type hints
from urllib.parse import urlparse  # For URL manipulation

# Macros:
class BackgroundColors:  # Colors for the terminal
    CYAN = "\033[96m"  # Cyan
    GREEN = "\033[92m"  # Green
    YELLOW = "\033[93m"  # Yellow
    RED = "\033[91m"  # Red
    BOLD = "\033[1m"  # Bold


# Execution Constants:
VERBOSE = False  # Set to True to output verbose messages

# Affiliate URL detection pattern (onelink short affiliate links)
AFFILIATE_URL_PATTERN = r"https?://onelink\.shein\.com/[A-Za-z0-9/]+"

# HTML Selectors Dictionary:
HTML_SELECTORS = {
    "product_name": [  # List of CSS selectors for product name in priority order
        ("span", {"class": "fsp-element"}),  # Shein product name span with specific class
        ("h1", {"class": "fsp-element"}),  # Shein product name heading with specific class (fallback)
        ("h1", {"class": re.compile(r".*product.*title.*", re.IGNORECASE)}),  # Generic product title pattern fallback
        ("h1", {}),  # Generic H1 heading as last resort fallback
    ],
    "current_price": [  # List of CSS selectors for current price in priority order
        ("div", {"id": "productMainPriceId"}),  # Shein current price container with specific ID
        ("div", {"class": "productPrice__main"}),  # Shein current price container with specific class (fallback)
        ("span", {"class": re.compile(r".*price.*current.*", re.IGNORECASE)}),  # Generic current price pattern fallback
        ("div", {"class": re.compile(r".*price.*", re.IGNORECASE)}),  # Generic price div as last resort fallback
    ],
    "old_price": [  # List of CSS selectors for old price in priority order
        ("p", {"class": "productEstimatedTagNewRetail__retail"}),  # Shein old price paragraph with specific class
        ("div", {"class": "productDiscountInfo__retail"}),  # Shein old price container with specific class (fallback)
        ("span", {"class": re.compile(r".*price.*original.*", re.IGNORECASE)}),  # Generic original price pattern fallback
        ("del", {}),  # Deleted text element for old price as last resort fallback
    ],
    "discount": [  # List of CSS selectors for discount percentage in priority order
        ("div", {"class": "productEstimatedTagNew__percent"}),  # Shein discount percentage div with specific class
        ("div", {"class": "productDiscountPercent"}),  # Shein discount percentage container with specific class (fallback)
        ("span", {"class": re.compile(r".*discount.*", re.IGNORECASE)}),  # Generic discount span fallback
        ("span", {"class": re.compile(r".*percent.*", re.IGNORECASE)}),  # Percentage span as last resort fallback
    ],
    "description": [  # List of CSS selectors for product description in priority order
        ("div", {"class": "product-intro__attr-list-text"}),  # Shein description container with specific class
        ("div", {"class": "product-intro__attr-des"}),  # Shein description container with attr-des class
        ("div", {"class": "product-intro__attr-list-text product-intro__attr-list-textMargin"}),  # Shein description container with attr-des class
        ("div", {"class": "product-intro__attr-wrap"}),  # Shein description container with attr-des class
        ("div", {"class": re.compile(r".*description.*", re.IGNORECASE)}),  # Generic description pattern fallback
        ("p", {"class": re.compile(r".*description.*", re.IGNORECASE)}),  # Paragraph element containing description as last resort fallback
    ],
    "gallery_images": [  # List of CSS selectors for product gallery images in priority order
        ("ul", {"class": re.compile(r"thumbs-picture.*one-picture__thumbs")}),  # Shein gallery thumbnails container with combined classes
        ("ul", {"class": "thumbs-picture"}),  # Shein gallery thumbnails container as fallback
        ("div", {"class": "darkreader darkreader--sync"}),  # DarkReader wrapper (when HTML saved with extension enabled)
        ("div", {"class": re.compile(r".*gallery.*", re.IGNORECASE)}),  # Generic gallery pattern as last resort fallback
    ],
    "shipping_options": [  # List of CSS selectors for shipping options in priority order
        ("div", {"class": "product-intro__size-radio"}),  # Shein shipping option radio buttons container
        ("div", {"class": re.compile(r".*shipping.*radio.*", re.IGNORECASE)}),  # Generic shipping radio pattern fallback
        ("div", {"class": re.compile(r".*envio.*", re.IGNORECASE)}),  # Portuguese "envio" (shipping) pattern as last resort fallback
    ],
}  # Dictionary containing all HTML selectors used for scraping product information

# Output Directory Constants:
OUTPUT_DIRECTORY = "./Outputs/"  # The base path to the output directory

# Browser Constants:
CHROME_PROFILE_PATH = os.getenv("CHROME_PROFILE_PATH", "")  # Path to Chrome profile
CHROME_EXECUTABLE_PATH = os.getenv("CHROME_EXECUTABLE_PATH", "")  # Path to Chrome executable
HEADLESS = os.getenv("HEADLESS", "False").lower() == "true"  # Headless mode flag
PAGE_LOAD_TIMEOUT = 120000  # 30 seconds timeout for page load
NETWORK_IDLE_TIMEOUT = 10000  # 5 seconds of network idle
SCROLL_PAUSE_TIME = 0.5  # Seconds to pause between scrolls
SCROLL_STEP = 300  # Pixels to scroll per step

# Template Constants:
PRODUCT_DESCRIPTION_TEMPLATE = """Product Name: {product_name}

Price: From R${current_price} to R${old_price} ({discount})

Description: {description}

🛒 Encontre na Shein:
👉 {url}"""  # Template for product description text file with placeholders

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

# Classes Definitions:

class Shein:
    """
    Web scraper class for extracting product information from Shein using authenticated browser sessions.

    :return: None
    """


    def __init__(self, url="", local_html_path=None, prefix="", output_directory=OUTPUT_DIRECTORY, api_keys=None):
        """
        Initializes the Shein scraper with a product URL and optional local HTML file path.

        :param url: The URL of the Shein product page to scrape
        :param local_html_path: Optional path to a local HTML file for offline scraping
        :param prefix: Optional platform prefix for output directory naming (e.g., "Shein")
        :param output_directory: Output directory path for storing scraped data (defaults to OUTPUT_DIRECTORY constant)
        :return: None
        """

        self.url = url  # Store the URL of the product page to be scraped
        self.product_url = url  # Maintain separate copy of product URL for reference
        self.local_html_path = local_html_path  # Store path to local HTML file for offline scraping
        self.html_content = None  # Store HTML content for reuse (from browser or local file)
        self.product_data = {}  # Initialize empty dictionary to store extracted product data
        self.prefix = prefix  # Store the platform prefix for directory naming
        self.output_directory = output_directory
        self.api_keys = api_keys  # Store the output directory path for this scraping session
        self.playwright = None  # Placeholder for Playwright instance
        self.browser = None  # Placeholder for browser instance
        self.page = None  # Placeholder for page object
        verbose_output(f"{BackgroundColors.GREEN}Shein scraper initialized with URL: {BackgroundColors.CYAN}{url}{Style.RESET_ALL}")
        if local_html_path:  # If local HTML file path is provided
            verbose_output(f"{BackgroundColors.GREEN}Offline mode enabled. Will read from: {BackgroundColors.CYAN}{local_html_path}{Style.RESET_ALL}")


    def launch_browser(self):
        """
        Launches an authenticated Chrome browser using existing profile.

        :return: None
        """

        verbose_output(f"{BackgroundColors.GREEN}Launching authenticated Chrome browser...{Style.RESET_ALL}")
        try:  # Attempt to launch browser with error handling
            self.playwright = sync_playwright().start()  # Start Playwright synchronous context manager
            launch_options = {"headless": HEADLESS, "args": ["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--no-sandbox"]}  # Configure browser launch options with anti-detection flags
            if CHROME_PROFILE_PATH:  # Verify if custom Chrome profile path is provided
                launch_options["args"].append(f"--user-data-dir={CHROME_PROFILE_PATH}")  # Add user data directory to browser arguments
                verbose_output(f"{BackgroundColors.GREEN}Using Chrome profile: {BackgroundColors.CYAN}{CHROME_PROFILE_PATH}{Style.RESET_ALL}")  # Log profile path being used
            if CHROME_EXECUTABLE_PATH:  # Verify if custom Chrome executable path is provided
                launch_options["executable_path"] = CHROME_EXECUTABLE_PATH  # Set custom executable path in launch options
                verbose_output(f"{BackgroundColors.GREEN}Using Chrome executable: {BackgroundColors.CYAN}{CHROME_EXECUTABLE_PATH}{Style.RESET_ALL}")  # Log executable path being used
            self.browser = self.playwright.chromium.launch(**launch_options)  # Launch Chromium browser with configured options
            if self.browser is None:  # Verify browser instance was created successfully
                raise Exception("Failed to initialize browser")  # Raise exception if browser initialization failed
            self.page = self.browser.new_page()  # Create new browser page/tab
            if self.page is None:  # Verify page instance was created successfully
                raise Exception("Failed to create page")  # Raise exception if page creation failed
            self.page.set_viewport_size({"width": 1920, "height": 1080})  # Set viewport dimensions to standard Full HD resolution
            verbose_output(f"{BackgroundColors.GREEN}Browser launched successfully.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{BackgroundColors.RED}Failed to launch browser: {e}{Style.RESET_ALL}")
            raise


    def close_browser(self):
        """
        Safely closes the browser and Playwright instances.

        :return: None
        """

        verbose_output(f"{BackgroundColors.GREEN}Closing browser...{Style.RESET_ALL}")
        try:  # Attempt to close browser resources with error handling
            if self.page:  # Verify if page instance exists before closing
                self.page.close()  # Close the browser page to release resources
            if self.browser:  # Verify if browser instance exists before closing
                self.browser.close()  # Close the browser to release resources
            if self.playwright:  # Verify if Playwright instance exists before stopping
                self.playwright.stop()  # Stop the Playwright instance
            verbose_output(f"{BackgroundColors.GREEN}Browser closed successfully.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{BackgroundColors.YELLOW}Warning during browser close: {e}{Style.RESET_ALL}")


    def load_page(self):
        """
        Loads the product page and waits for network idle.

        :return: True if successful, False otherwise
        """

        verbose_output(f"{BackgroundColors.GREEN}Loading page: {BackgroundColors.CYAN}{self.product_url}{Style.RESET_ALL}")
        if self.page is None:  # Validate that page instance exists before attempting to load
            print(f"{BackgroundColors.RED}Page instance not initialized.{Style.RESET_ALL}")  # Alert user that page is not ready
            return False  # Return failure status if page is not initialized
        try:
            self.page.goto(self.product_url, timeout=PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            self.page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
        except PlaywrightTimeoutError:
            print(f"{BackgroundColors.YELLOW}Page load or network idle timeout (possibly blocked by Captcha), checking for Captcha...{Style.RESET_ALL}")
            
        try:
            self.detect_and_solve_captcha(self.page, is_playwright=True)
            verbose_output(f"{BackgroundColors.GREEN}Page loaded successfully.{Style.RESET_ALL}")
            return True
        except Exception as e:
            print(f"{BackgroundColors.RED}Captcha solving failed: {e}{Style.RESET_ALL}")
            return True
        except Exception as e:  # Catch any other exceptions during page loading
            print(f"{BackgroundColors.RED}Failed to load page: {e}{Style.RESET_ALL}")  # Alert user about page loading failure
            return False  # Return failure status for unhandled errors


    def auto_scroll(self):
        """
        Automatically scrolls the page to trigger lazy-loaded content.

        :return: None
        """

        verbose_output(f"{BackgroundColors.GREEN}Auto-scrolling to load lazy content...{Style.RESET_ALL}")
        if self.page is None:  # Validate that page instance exists before scrolling
            print(f"{BackgroundColors.YELLOW}Warning: Page not initialized, skipping scroll.{Style.RESET_ALL}")  # Warn user that scrolling will be skipped
            return  # Exit method early if page is not initialized
        try:  # Attempt auto-scrolling with error handling
            previous_height = self.page.evaluate("document.body.scrollHeight")  # Get initial page height for comparison
            while True:  # Loop indefinitely until break condition is met
                self.page.evaluate(f"window.scrollBy(0, {SCROLL_STEP})")  # Scroll down by configured step pixels
                time.sleep(SCROLL_PAUSE_TIME)  # Pause to allow lazy content to load
                new_height = self.page.evaluate("document.body.scrollHeight")  # Get updated page height after scroll
                scroll_position = self.page.evaluate("window.pageYOffset + window.innerHeight")  # Calculate current scroll position
                if scroll_position >= new_height:  # Verify if scrolled to bottom of page
                    break  # Exit loop when bottom is reached
                if new_height == previous_height:  # Verify if page height stopped changing
                    break  # Exit loop when no new content is loaded
                previous_height = new_height  # Update previous height for next iteration
            self.page.evaluate("window.scrollTo(0, 0)")  # Scroll back to top of page
            time.sleep(SCROLL_PAUSE_TIME)  # Pause briefly after scrolling to top
            
            # Click 'Description' dropdown/accordion if it exists
            try:
                self.page.evaluate("""
                    var elements = document.querySelectorAll('div, span, button, a');
                    for (var i = 0; i < elements.length; i++) {
                        var text = elements[i].innerText || elements[i].textContent;
                        if (text && text.trim().toLowerCase() === 'description') {
                            elements[i].click();
                            break;
                        }
                    }
                """)
                time.sleep(2)
            except Exception as e:
                pass
            verbose_output(f"{BackgroundColors.GREEN}Auto-scroll completed.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{BackgroundColors.YELLOW}Warning during auto-scroll: {e}{Style.RESET_ALL}")


    def wait_full_render(self):
        """
        Waits for the page to be fully rendered with all dynamic content.

        :return: None
        """

        verbose_output(f"{BackgroundColors.GREEN}Waiting for full page render...{Style.RESET_ALL}")
        if self.page is None:  # Validate that page instance exists before waiting
            print(f"{BackgroundColors.YELLOW}Warning: Page not initialized, skipping render wait.{Style.RESET_ALL}")  # Warn user that render wait will be skipped
            return  # Exit method early if page is not initialized
        try:  # Attempt waiting for render with error handling
            selectors_to_wait = ["h1", "div[class*='price']", "img"]  # Define list of key selectors to wait for
            for selector in selectors_to_wait:  # Iterate through each selector to ensure visibility
                try:  # Attempt to wait for selector with nested error handling
                    self.page.wait_for_selector(selector, timeout=5000, state="visible")  # Wait for selector to become visible
                except:  # Silently handle timeout if selector not found
                    pass  # Continue to next selector even if current one fails
            time.sleep(2)  # Additional wait time to ensure all dynamic content is rendered
            verbose_output(f"{BackgroundColors.GREEN}Page fully rendered.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{BackgroundColors.YELLOW}Warning during render wait: {e}{Style.RESET_ALL}")


    def get_rendered_html(self):
        """
        Gets the fully rendered HTML content after JavaScript execution.

        :return: Rendered HTML string or None if failed
        """

        verbose_output(f"{BackgroundColors.GREEN}Extracting rendered HTML...{Style.RESET_ALL}")
        if self.page is None:  # Validate that page instance exists before extracting HTML
            print(f"{BackgroundColors.RED}Page instance not initialized.{Style.RESET_ALL}")  # Alert user that page is not ready
            return None  # Return None to indicate extraction failed
        try:  # Attempt HTML extraction with error handling
            html = self.page.content()  # Extract fully rendered HTML content from page
            verbose_output(f"{BackgroundColors.GREEN}Rendered HTML extracted successfully.{Style.RESET_ALL}")
            return html  # Return extracted HTML content
        except Exception as e:  # Catch any exceptions during HTML extraction
            print(f"{BackgroundColors.RED}Failed to extract HTML: {e}{Style.RESET_ALL}")  # Alert user about extraction failure
            return None  # Return None to indicate extraction failed


    def read_local_html(self):
        """
        Reads HTML content from a local file for offline scraping.

        :return: HTML content string or None if failed
        """

        verbose_output(f"{BackgroundColors.GREEN}Reading local HTML file: {BackgroundColors.CYAN}{self.local_html_path}{Style.RESET_ALL}")
        try:  # Attempt to read file with error handling
            if not self.local_html_path:  # Verify if local HTML path is not set
                print(f"{BackgroundColors.RED}No local HTML path provided.{Style.RESET_ALL}")  # Alert user that path is missing
                return None  # Return None if path doesn't exist
            if not os.path.exists(self.local_html_path):  # Verify if file doesn't exist
                print(f"{BackgroundColors.RED}\nLocal HTML file not found: {BackgroundColors.CYAN}{self.local_html_path}{Style.RESET_ALL}")  # Alert user that file is missing
                return None  # Return None if file doesn't exist
            with open(self.local_html_path, "r", encoding="utf-8") as file:  # Open file with UTF-8 encoding
                html_content = file.read()  # Read entire file content
            verbose_output(f"{BackgroundColors.GREEN}Local HTML content loaded successfully.{Style.RESET_ALL}")
            return html_content  # Return the HTML content string
        except Exception as e:  # Catch any exceptions during file reading
            print(f"{BackgroundColors.RED}Error reading local HTML file: {e}{Style.RESET_ALL}")  # Alert user about file reading error
            return None  # Return None to indicate reading failed


    def extract_product_name(self, soup=None):
        """
        Extracts the product name from the parsed HTML soup.

        :param soup: BeautifulSoup object containing the parsed HTML
        :return: Product name string or "Unknown Product" if not found
        """

        if soup is None:  # Guard against None to satisfy static verifiers and avoid attribute access on None
            return "Unknown Product"  # Return default when no soup provided
        for tag, attrs in HTML_SELECTORS["product_name"]:  # Iterate through each selector combination from centralized dictionary
            name_element = soup.find(tag, attrs if attrs else None)  # Search for element matching current selector
            if name_element:  # Verify if matching element was found
                    raw_product_name = name_element.get_text(separator=" ", strip=True)  # Extract raw text, preserve single spaces between parts
                    product_name = normalize_product_name(raw_name=raw_product_name)  # Normalize name for directory usage
                    if product_name and product_name != "":  # Validate that extracted name is not empty
                        verbose_output(f"{BackgroundColors.GREEN}Product name: {BackgroundColors.CYAN}{product_name}{Style.RESET_ALL}")  # Log successfully extracted (formatted) product name
                        return product_name  # Return the sanitized, title-cased product name immediately when found
        verbose_output(f"{BackgroundColors.YELLOW}Product name not found, using default.{Style.RESET_ALL}")  # Warn that product name could not be extracted
        return "Unknown Product"  # Return default placeholder when name extraction fails


    def normalize_brazilian_currency(self, price_text: str) -> Optional[Tuple[str, str]]:
        """
        Normalize Brazilian currency format to extract integer and decimal parts correctly.
        Handles format: R$ + optional space + digits with dots (thousands) + comma (decimal) + 2 digits.
        Example: "R$2.299,08" -> ("2299", "08").

        :param price_text: Raw price text potentially containing currency symbol and formatting
        :return: Tuple of (integer_part, decimal_part) or None if parsing fails
        """

        if not price_text:  # Validate that price text is not empty
            return None  # Return None when input is empty
        
        normalized = price_text.strip()  # Remove leading and trailing whitespace
        normalized = re.sub(r"[R$€£¥]", "", normalized)  # Remove common currency symbols from price string
        normalized = normalized.replace("\u00A0", " ").strip()  # Replace NBSP with space and strip again
        
        match = re.search(r"([0-9.]+)[,.]([0-9]{2})", normalized)  # Search for Brazilian currency pattern with dots and comma
        if not match:  # Verify if no price pattern was found
            return None  # Return None when pattern doesn't match
        
        integer_part_str = match.group(1)  # Extract the integer part with potential dots
        decimal_part = match.group(2)  # Extract the 2-digit decimal part
        
        integer_part_str = integer_part_str.replace(".", "")  # Remove all dot separators (assumed thousands separators in BR)
        integer_part_str = integer_part_str.replace(",", "")  # Remove any remaining comma separators as failsafe
        
        if not integer_part_str or not integer_part_str.isdigit():  # Verify that integer part is valid digits only
            return None  # Return None when integer part is invalid
        
        if not decimal_part.isdigit() or len(decimal_part) != 2:  # Verify decimal part is exactly 2 digits
            return None  # Return None when decimal part is invalid
        
        return integer_part_str, decimal_part  # Return normalized price components


    def extract_current_price(self, soup=None):
        """
        Extracts the current price from the parsed HTML soup.
        PRIMARY: JSON promotionInfoPrice.amountWithSymbol extraction
        FALLBACK: HTML extraction

        :param soup: BeautifulSoup object containing the parsed HTML
        :return: Tuple of (integer_part, decimal_part) for current price
        """

        if soup is None:  # Guard against None to avoid attribute access on None
            return "0", "00"  # Default price when no soup provided
        
        verbose_output(f"{BackgroundColors.GREEN}Trying JSON extraction for current price...{Style.RESET_ALL}")
        
        try:
            script_tags = soup.find_all("script", {"type": "application/json"})
            for script_tag in script_tags:
                try:
                    if not script_tag.string:  # Skip if no content
                        continue
                    
                    json_data = json.loads(script_tag.string)  # Parse JSON data
                    
                    if isinstance(json_data, dict):
                        promo_price = json_data.get("promotionInfoPrice", {})
                        if not promo_price and "detail" in json_data:
                            promo_price = json_data.get("detail", {}).get("promotionInfoPrice", {})
                        
                        amount_with_symbol = promo_price.get("amountWithSymbol", "")
                        
                        if amount_with_symbol and isinstance(amount_with_symbol, str):
                            normalized = self.normalize_brazilian_currency(amount_with_symbol)  # Normalize price to handle thousands separators and decimal format
                            if normalized:  # Verify if normalization succeeded and returned a result
                                integer_part, decimal_part = normalized  # Unpack normalized integer and decimal parts
                                verbose_output(f"{BackgroundColors.GREEN}Current price from JSON: R${integer_part},{decimal_part}{Style.RESET_ALL}")
                                return integer_part, decimal_part
                
                except (json.JSONDecodeError, AttributeError, TypeError, KeyError):
                    continue  # Skip invalid or incompatible JSON
        
        except Exception as e:
            verbose_output(f"{BackgroundColors.YELLOW}Error extracting current price from JSON: {e}{Style.RESET_ALL}")
        
        verbose_output(f"{BackgroundColors.YELLOW}JSON current price not found, trying HTML extraction...{Style.RESET_ALL}")
        
        for tag, attrs in HTML_SELECTORS["current_price"]:  # Iterate through each selector combination from centralized dictionary
            price_element = soup.find(tag, attrs if attrs else None)  # Search for element matching current selector
            if price_element:  # Verify if matching element was found
                price_text = price_element.get_text(strip=True)  # Extract and clean text content from element
                normalized = self.normalize_brazilian_currency(price_text)  # Normalize price to handle thousands separators and decimal format
                if normalized:  # Verify if normalization succeeded and returned a result
                    integer_part, decimal_part = normalized  # Unpack normalized integer and decimal parts
                    verbose_output(f"{BackgroundColors.GREEN}Current price from HTML: R${integer_part},{decimal_part}{Style.RESET_ALL}")  # Log successfully extracted current price
                    return integer_part, decimal_part  # Return price components as tuple
        
        verbose_output(f"{BackgroundColors.YELLOW}Current price not found, using default.{Style.RESET_ALL}")  # Warn that current price could not be extracted
        return "0", "00"  # Return default zero price when extraction fails


    def extract_old_price(self, soup=None, current_price_int="0", current_price_dec="00", discount_percentage="N/A"):
        """
        Extracts the old price from the parsed HTML soup.
        PRIMARY: JSON originalPrice.amountWithSymbol extraction (with optimized recursive search)
        FALLBACK 1: HTML extraction
        FALLBACK 2: Compute from current price and discount (if available)

        :param soup: BeautifulSoup object containing the parsed HTML
        :param current_price_int: Current price integer part (for computational fallback)
        :param current_price_dec: Current price decimal part (for computational fallback)
        :param discount_percentage: Discount percentage string (for computational fallback)
        :return: Tuple of (integer_part, decimal_part) for old price
        """

        if soup is None:  # Guard against None to avoid attribute access on None
            return "N/A", "N/A"  # Default old price when no soup provided
        
        verbose_output(f"{BackgroundColors.GREEN}Trying JSON extraction for old price...{Style.RESET_ALL}")
        
        try:
            script_tags = soup.find_all("script", {"type": "application/json"})
            for script_tag in script_tags:
                try:
                    if not script_tag.string:  # Skip if no content
                        continue
                    
                    if "originalPrice" not in script_tag.string:
                        continue  # Skip this script tag if it doesn't contain originalPrice
                    
                    verbose_output(f"{BackgroundColors.GREEN}Found JSON with 'originalPrice', parsing...{Style.RESET_ALL}")
                    json_data = json.loads(script_tag.string)  # Parse JSON data


                    def find_original_price(obj, depth=0, max_depth=15):
                        """Recursively search for originalPrice in nested structures"""
                        if depth > max_depth:  # Prevent infinite recursion
                            return None
                        
                        if isinstance(obj, dict):
                            if "originalPrice" in obj:
                                original_price = obj["originalPrice"]
                                if isinstance(original_price, dict):
                                    amount_with_symbol = original_price.get("amountWithSymbol", "")
                                    if amount_with_symbol and isinstance(amount_with_symbol, str):
                                        verbose_output(f"{BackgroundColors.GREEN}Found originalPrice.amountWithSymbol: {amount_with_symbol}{Style.RESET_ALL}")
                                        return amount_with_symbol
                            
                            for value in obj.values():
                                result = find_original_price(value, depth + 1, max_depth)
                                if result:
                                    return result
                        
                        elif isinstance(obj, list):
                            for item in obj:
                                result = find_original_price(item, depth + 1, max_depth)
                                if result:
                                    return result
                        
                        return None
                    
                    amount_with_symbol = find_original_price(json_data)
                    
                    if amount_with_symbol:
                        normalized = self.normalize_brazilian_currency(amount_with_symbol)  # Normalize price to handle thousands separators and decimal format
                        if normalized:  # Verify if normalization succeeded and returned a result
                            integer_part, decimal_part = normalized  # Unpack normalized integer and decimal parts
                            verbose_output(f"{BackgroundColors.GREEN}Old price from JSON: R${integer_part},{decimal_part}{Style.RESET_ALL}")
                            return integer_part, decimal_part
                
                except (json.JSONDecodeError, AttributeError, TypeError, KeyError) as e:
                    verbose_output(f"{BackgroundColors.YELLOW}Error parsing JSON script tag: {e}{Style.RESET_ALL}")
                    continue  # Skip invalid or incompatible JSON
        
        except Exception as e:
            verbose_output(f"{BackgroundColors.YELLOW}Error extracting old price from JSON: {e}{Style.RESET_ALL}")
        
        verbose_output(f"{BackgroundColors.YELLOW}JSON old price not found, trying HTML extraction...{Style.RESET_ALL}")
        
        for tag, attrs in HTML_SELECTORS["old_price"]:  # Iterate through each selector combination from centralized dictionary
            price_element = soup.find(tag, attrs if attrs else None)  # Search for element matching current selector
            if price_element:  # Verify if matching element was found
                price_text = price_element.get_text(strip=True)  # Extract and clean text content from element
                normalized = self.normalize_brazilian_currency(price_text)  # Normalize price to handle thousands separators and decimal format
                if normalized:  # Verify if normalization succeeded and returned a result
                    integer_part, decimal_part = normalized  # Unpack normalized integer and decimal parts
                    verbose_output(f"{BackgroundColors.GREEN}Old price from HTML: R${integer_part},{decimal_part}{Style.RESET_ALL}")  # Log successfully extracted old price
                    return integer_part, decimal_part  # Return price components as tuple
        
        verbose_output(f"{BackgroundColors.YELLOW}HTML old price not found, trying computational method...{Style.RESET_ALL}")
        
        if current_price_int not in ["0", "N/A"] and discount_percentage not in ["N/A", ""]:
            try:
                discount_match = re.search(r"(\d+)%", discount_percentage)
                if discount_match:
                    discount_decimal = float(discount_match.group(1)) / 100.0  # Convert percentage to decimal (20% -> 0.20)
                    
                    current_price_float = float(f"{current_price_int}.{current_price_dec}")
                    
                    if discount_decimal < 1.0:  # Ensure discount is less than 100%
                        original_price_float = current_price_float / (1.0 - discount_decimal)
                        
                        original_price_float = round(original_price_float, 2)
                        
                        integer_part = str(int(original_price_float))
                        decimal_part = str(int((original_price_float % 1) * 100)).zfill(2)
                        
                        verbose_output(f"{BackgroundColors.GREEN}Old price calculated from current price and discount: R${integer_part},{decimal_part}{Style.RESET_ALL}")
                        return integer_part, decimal_part
            
            except (ValueError, ZeroDivisionError) as e:
                verbose_output(f"{BackgroundColors.YELLOW}Error calculating old price from discount: {e}{Style.RESET_ALL}")
        
        verbose_output(f"{BackgroundColors.YELLOW}Old price not found by any method.{Style.RESET_ALL}")  # Warn that old price could not be extracted
        return "N/A", "N/A"  # Return N/A when old price is not available


    def extract_discount_percentage(self, soup=None):
        """
        Extracts the discount percentage from the parsed HTML soup.

        :param soup: BeautifulSoup object containing the parsed HTML
        :return: Discount percentage string or "N/A" if not found
        """

        if soup is None:  # Guard against None to avoid attribute access on None
            return "N/A"  # Default discount when no soup provided
        for tag, attrs in HTML_SELECTORS["discount"]:  # Iterate through each selector combination from centralized dictionary
            discount_element = soup.find(tag, attrs if attrs else None)  # Search for element matching current selector
            if discount_element:  # Verify if matching element was found
                discount_text = discount_element.get_text(strip=True)  # Extract and clean text content from element
                match = re.search(r"(\d+%)", discount_text)  # Search for discount percentage pattern
                if match:  # Verify if discount pattern was found in text
                    verbose_output(f"{BackgroundColors.GREEN}Discount: {match.group(1)}{Style.RESET_ALL}")  # Log successfully extracted discount percentage
                    return match.group(1)  # Return the discount percentage string

        try:  # Compute discount from current and old prices when possible
            old_int, old_dec = self.extract_old_price(soup)  # Get old price components
            curr_int, curr_dec = self.extract_current_price(soup)  # Get current price components
            if old_int and old_int != "N/A" and curr_int and curr_int != "0":  # Ensure we have valid numeric parts
                old_value = float(f"{old_int}.{old_dec}")  # Compose old price float value
                curr_value = float(f"{curr_int}.{curr_dec}")  # Compose current price float value
                if old_value > 0:  # Avoid division by zero
                    discount = ((old_value - curr_value) / old_value) * 100.0  # Compute discount percentage
                    discount_int = int(round(discount))  # Round to nearest integer percent
                    verbose_output(f"{BackgroundColors.GREEN}Computed discount: {discount_int}%{Style.RESET_ALL}")  # Log computed discount percentage
                    return f"{discount_int}%"  # Return formatted percentage string
        except Exception:  # Fail silently and return N/A on any error
            pass  # Continue to fallback

        return "N/A"  # Return N/A when discount is not available


    def extract_product_description(self, soup=None):
        """
        Extracts the product description from the parsed HTML soup.
        Aggregates text from multiple sources (HTML selectors, ProductIntroDescription,
        structured specification fragments in script tags and goods_desc JSON) and
        optionally returns structured attributes when ProductIntroDescription exists.

        :param soup: BeautifulSoup object containing the parsed HTML
        :return: Either a legacy string description or a dict {"text":..., "attributes":{...}}
        """

        if soup is None:  # Guard against None to avoid attribute access on None
            return "No description available"  # Default description when no soup provided

        html_description = None  # Hold first HTML-selector description found for compatibility
        combined_fragments = []  # Accumulate description fragments from all methods

        for tag, attrs in HTML_SELECTORS["description"]:  # Try selector-based HTML description first
            description_element = soup.find(tag, attrs if attrs else None)  # Safe selector lookup
            if description_element:  # If an element was found for this selector
                html_description = description_element.get_text(strip=True)  # Extract raw text from element
                html_description = html_description.capitalize()  # Normalize sentence casing for readability
                if html_description and len(html_description) > 10:  # Accept only reasonably long HTML descriptions
                    verbose_output(f"{BackgroundColors.GREEN}Description found from HTML ({len(html_description)} chars).{Style.RESET_ALL}")  # Log successful extraction
                combined_fragments.append(html_description or "")  # Add HTML description to aggregator (may be empty)
                break  # Stop after first matching selector to preserve original priority

        container = None  # Placeholder for ProductIntroDescription container if present
        try:  # Safe attempt to locate the named container in multiple possible forms
            container = soup.find("div", attrs={"class": "common-entry__container", "name": "ProductIntroDescription"}) or soup.find(attrs={"name": "ProductIntroDescription"})  # Locate by class+name or by name-only
        except Exception as exc:  # Explicit exception handling (no bare except)
            verbose_output(f"{BackgroundColors.YELLOW}Error locating ProductIntroDescription container: {exc}{Style.RESET_ALL}")  # Log container lookup error
            container = None  # Ensure container is None on failure

        container_attributes = {}  # Store attribute key/value pairs extracted from the container
        container_text = None  # Store container-derived textual description when available

        if container is not None:  # If named container exists, extract attributes + visible text
            try:  # Guard extraction so failures don't abort other methods
                for bad in container.find_all(["script", "style"]):  # Remove noisy children that would pollute text
                    bad.decompose()  # Remove node from parse tree

                for dl in container.find_all("dl"):  # Definition lists (dl -> dt/dd) provide explicit key/value pairs
                    dts = dl.find_all("dt")  # Potential attribute names
                    dds = dl.find_all("dd")  # Potential attribute values
                    for i, dt in enumerate(dts):  # Match dt -> dd by index when possible
                        dt_text = dt.get_text(" ", strip=True)  # Normalize dt text
                        dd_text = dds[i].get_text(" ", strip=True) if i < len(dds) else ""  # Safe dd lookup
                        if dt_text and dd_text and dt_text not in container_attributes:  # Validate and dedupe keys
                            container_attributes[dt_text] = dd_text  # Preserve original casing for keys

                for table in container.find_all("table"):  # Tables with two-column rows are common attribute containers
                    for tr in table.find_all("tr"):  # Iterate each table row
                        cells = tr.find_all(["td", "th"])  # Table cells that may contain key/value
                        if len(cells) >= 2:  # Need at least two cells for attribute pair
                            key = cells[0].get_text(" ", strip=True)  # Extract key text
                            val = cells[1].get_text(" ", strip=True)  # Extract value text
                            if key and val and key not in container_attributes:  # Validate and avoid duplicates
                                container_attributes[key] = val  # Store mapping preserving casing

                container_text_fragments = []  # Collect free-form text fragments found inside the container
                for row in container.find_all(["div", "li", "p", "span"]):  # Iterate common row-like tags
                    if row is container:  # Defensive: skip if same node encountered
                        continue  # Skip processing the root container node
                    label_el = None  # Placeholder for explicit label child element
                    for candidate in (row.find_all(["b", "strong", "label"], recursive=False) or []):  # Look for direct bold/label children
                        label_el = candidate  # Accept first direct child that looks like a label
                        break  # Stop after first candidate
                    if label_el is not None:  # If an explicit label element was found
                        lbl_text = label_el.get_text(" ", strip=True)  # Normalize label text
                        row_text = row.get_text(" ", strip=True)  # Normalize full row text
                        val_text = row_text.replace(lbl_text, "", 1).strip()  # Derive remaining value text after removing label
                        if lbl_text and val_text and lbl_text not in container_attributes:  # Validate and dedupe
                            container_attributes[lbl_text] = val_text  # Store label->value mapping
                            continue  # Row processed as structured attribute
                    row_text = row.get_text(" ", strip=True)  # Normalize row text for fallback detection
                    if ":" in row_text:  # Heuristic: 'Key: Value' textual pattern
                        parts = row_text.split(":", 1)  # Split into key and value at first colon
                        key_candidate = parts[0].strip()  # Candidate key text
                        val_candidate = parts[1].strip()  # Candidate value text
                        if key_candidate and val_candidate and key_candidate not in container_attributes:  # Validate and dedupe
                            container_attributes[key_candidate] = val_candidate  # Save detected pair
                            continue  # Row consumed as structured pair
                    if row_text:  # If not structured, collect as free-form fragment
                        container_text_fragments.append(row_text)  # Append visible text fragment for later joining

                for t in container.find_all(["p", "span", "li"]):  # Also include top-level paragraphs/spans inside container
                    txt = t.get_text(" ", strip=True)  # Normalize tag text
                    if txt:  # Only include non-empty fragments
                        container_text_fragments.append(txt)  # Append fragment to container fragment list

                seen_frag = {}  # Ordered dedupe helper for container fragments
                for frag in container_text_fragments:  # Iterate in discovered order
                    if frag not in seen_frag:  # Only keep first occurrence
                        seen_frag[frag] = True  # Mark fragment as seen
                container_text = "\n\n".join(seen_frag.keys()).strip() or None  # Build final container textual block
                if container_text:  # Only append non-empty container text to aggregate
                    combined_fragments.append(container_text)  # Add container text to master fragments list
            except Exception as exc:  # Handle extraction errors explicitly
                verbose_output(f"{BackgroundColors.YELLOW}Error extracting ProductIntroDescription: {exc}{Style.RESET_ALL}")  # Log and continue without failing

        try:  # Structured specification extraction from inline script fragments
            specifications = []  # Collect label:value strings found in script fragments
            script_tags = soup.find_all("script")  # Search all script tags in the document
            verbose_output(f"{BackgroundColors.GREEN}Searching through {BackgroundColors.CYAN}{len(script_tags)}{BackgroundColors.GREEN} script tags for specification table...{Style.RESET_ALL}")  # Diagnostic log
            for script_tag in script_tags:  # Iterate script tags to search for common-entry__content anchor
                if not script_tag.string:  # Skip empty or non-text script tags
                    continue  # Move to next script tag
                script_content = str(script_tag.string)  # Convert content to string for searching
                anchor_pos = script_content.find('class="common-entry__content"')  # Anchor indicating structured spec HTML
                if anchor_pos == -1:  # Continue if anchor not present in this tag
                    continue  # Try next script tag
                start_pos = max(0, anchor_pos - 100)  # Start a bit before anchor for context
                end_search = script_content.find('class="common-entry__content"', anchor_pos + 1)  # Find next occurrence if any
                end_pos = end_search if end_search != -1 else anchor_pos + 50000  # Bound extraction window to 50KB
                fragment = script_content[start_pos:end_pos]  # Slice fragment expected to contain HTML
                try:  # Parse isolated fragment safely
                    fragment_soup = BeautifulSoup(fragment, "html.parser")  # Parse fragment HTML
                    all_text_nodes = []  # Collect visible text nodes from fragment
                    for element in fragment_soup.descendants:  # Iterate descendant nodes to collect text
                        if isinstance(element, str):  # Consider only string nodes
                            text = element.strip()  # Trim whitespace
                            if text:  # Skip empty strings
                                all_text_nodes.append(text)  # Append meaningful text node
                    noise_keywords = ["Classificação", "Itens", "Seguidores", "pago", "seguido", "está navegando", "Vendas", "Avaliações"]  # Known noisy tokens
                    i = 0  # Index for sequential scan of text nodes
                    seen_labels = set()  # Track labels already consumed to avoid duplicates
                    while i < len(all_text_nodes):  # Scan through text nodes with lookahead
                        current_text = all_text_nodes[i]  # Current text node under inspection
                        if any(noise in current_text for noise in noise_keywords):  # Skip noisy nodes quickly
                            i += 1  # Advance index past noise
                            continue  # Continue scanning
                        if ":" in current_text and len(current_text) < 50:  # Likely a short label followed by value nodes
                            label = current_text.replace(":", "").strip()  # Normalize potential label
                            if label in seen_labels:  # Avoid duplicate labels
                                i += 1  # Advance index and skip
                                continue  # Continue scanning
                            if len(label) > 2:  # Require minimal label length for quality
                                value_parts = []  # Accumulate adjacent nodes that look like the value
                                j = i + 1  # Lookahead pointer
                                while j < len(all_text_nodes) and j < i + 5:  # Limit lookahead to a few nodes
                                    next_text = all_text_nodes[j]  # Candidate value part
                                    if ":" in next_text and len(next_text) < 50:  # Stop when next label is found
                                        break  # End lookahead for this label
                                    if next_text and not any(noise in next_text for noise in noise_keywords):  # Accept valid value parts
                                        value_parts.append(next_text)  # Collect part of value
                                        if len(" ".join(value_parts)) > 100:  # Prevent unbounded accumulation
                                            break  # Enough value text collected
                                    j += 1  # Advance lookahead index
                                if value_parts:  # Only accept label when a value was found
                                    specifications.append(f"{label}: {' '.join(value_parts)}")  # Store formatted pair
                                    seen_labels.add(label)  # Mark label as consumed
                                    i = j  # Advance main index past consumed value parts
                                    continue  # Continue scanning main loop
                        i += 1  # Advance index when no structured pair found
                    if specifications:  # If any structured specs were discovered
                        spec_text = "\n".join(specifications)  # Join into a block of text
                        combined_fragments.append(spec_text)  # Aggregate into master fragments list
                    break  # Stop after first matching script fragment
                except Exception as parse_error:  # Handle fragment parse errors explicitly
                    verbose_output(f"{BackgroundColors.YELLOW}Error parsing fragment: {parse_error}{Style.RESET_ALL}")  # Log parse failure and continue
                    continue  # Try next script tag
        except Exception as exc:  # Catch outer failures for structured extraction
            verbose_output(f"{BackgroundColors.YELLOW}Error extracting structured specifications: {exc}{Style.RESET_ALL}")  # Log and continue

        try:  # Goods_desc JSON extraction (aggregate text if present)
            script_tags = soup.find_all("script")  # Reuse script tag list for JSON scanning
            for script_tag in script_tags:  # Iterate all script tags
                if not script_tag.string:  # Skip empty script nodes
                    continue  # Continue to next script tag
                script_content = str(script_tag.string)  # Convert content to string for searching
                if '"goods_desc"' in script_content or "'goods_desc'" in script_content:  # Quick existence verification before attempting parse
                    try:  # Attempt to parse JSON and extract goods_desc safely
                        json_obj = json.loads(script_content)  # Parse JSON content from script tag
                        def _find_goods_desc(obj):
                            """Recursively searches a JSON object for the 'goods_desc' key."""
                            if isinstance(obj, dict):  # Dict nodes may contain the key
                                if "goods_desc" in obj and isinstance(obj["goods_desc"], str):  # Direct match
                                    return obj["goods_desc"]  # Return found string
                                for v in obj.values():  # Recurse into values
                                    res = _find_goods_desc(v)  # Recursive search
                                    if res:  # If found, bubble up
                                        return res  # Return found value
                            elif isinstance(obj, list):  # Recurse into list items
                                for item in obj:  # Iterate list items
                                    res = _find_goods_desc(item)  # Recursive search in item
                                    if res:  # If found, return
                                        return res  # Bubble up found value
                            return None  # Not found in this branch
                        goods_desc_val = _find_goods_desc(json_obj)  # Run recursive search on parsed JSON
                        if goods_desc_val and isinstance(goods_desc_val, str):  # Validate returned value
                            cleaned = re.sub(r"<[^>]+>", "", goods_desc_val).strip()  # Strip HTML tags from goods_desc
                            if cleaned:  # If non-empty after cleaning
                                combined_fragments.append(cleaned)  # Aggregate goods_desc textual content
                    except (json.JSONDecodeError, TypeError) as jex:  # Handle JSON parsing/type errors explicitly
                        continue  # Skip this script tag on parse failure
        except Exception as exc:  # Catch-all for goods_desc scanning
            verbose_output(f"{BackgroundColors.YELLOW}Error extracting goods_desc: {exc}{Style.RESET_ALL}")  # Log and continue

        dedupe = {}  # Ordered dedupe using dict insertion order
        for frag in combined_fragments:  # Iterate fragments in discovery order
            if frag and frag not in dedupe:  # Only include non-empty, unseen fragments
                dedupe[frag] = True  # Mark as seen
        combined_text = "\n\n".join(dedupe.keys()).strip()  # Join fragments with paragraph spacing

        if not combined_text:  # If no description fragments were gathered
            return "No description available"  # Maintain existing fallback

        if container_attributes:  # If we extracted structured attributes from ProductIntroDescription
            return {"text": combined_text, "attributes": container_attributes}  # Return structured result (backward-compatible addition)

        return combined_text  # Return legacy string when no structured attributes present


    def detect_international(self, soup=None) -> bool:
        """
        Detects whether the product has only international shipping available.
        Verifies for "Envio Nacional" (National Shipping) availability.
        If "Envio Nacional" is sold out or not available, and "International" is active/available, returns True.

        :param soup: BeautifulSoup object containing the parsed HTML
        :return: True if only international shipping is available, False otherwise
        """
        
        if soup is None:  # Guard against None to avoid attribute access on None
            verbose_output(f"{BackgroundColors.YELLOW}No soup provided for shipping detection.{Style.RESET_ALL}")  # Log missing soup
            return False  # Default to False

        try:  # Begin detection
            for tag, attrs in HTML_SELECTORS["shipping_options"]:  # Iterate shipping selectors
                shipping_elements = soup.find_all(tag, attrs if attrs else None)  # Find matching elements
                if not shipping_elements:  # No elements for this selector
                    continue  # Try next selector

                verbose_output(f"{BackgroundColors.GREEN}Found {len(shipping_elements)} shipping option elements.{Style.RESET_ALL}")  # Log count

                national_available = False  # Flag: national available
                national_soldout = False  # Flag: national sold out
                international_available = False  # Flag: international available
                international_soldout = False  # Flag: international sold out

                for element in shipping_elements:  # Iterate found elements
                    aria = element.get("aria-label")  # Read aria-label
                    if aria is None:  # Missing aria-label
                        continue  # Skip element

                    classes = element.get("class") or []  # Get class list
                    is_soldout = any("_soldout" in c for c in classes)  # Detect sold-out via class

                    if aria == "Envio Nacional":  # Exact match national
                        if is_soldout:  # If marked sold out
                            national_soldout = True  # Mark sold out
                            verbose_output(f"{BackgroundColors.YELLOW}Found 'Envio Nacional' marked sold out.{Style.RESET_ALL}")  # Log sold out
                        else:  # Available
                            national_available = True  # Mark available
                            verbose_output(f"{BackgroundColors.GREEN}Found available 'Envio Nacional'.{Style.RESET_ALL}")  # Log available

                    elif aria == "International":  # Exact match international
                        if is_soldout:  # If marked sold out
                            international_soldout = True  # Mark sold out
                            verbose_output(f"{BackgroundColors.YELLOW}Found 'International' marked sold out.{Style.RESET_ALL}")  # Log sold out
                        else:  # Available
                            international_available = True  # Mark available
                            verbose_output(f"{BackgroundColors.GREEN}Found available 'International'.{Style.RESET_ALL}")  # Log available

                if (not national_available) and international_available:  # National not available and international available
                    self.product_data["INTERNATIONAL_ONLY"] = True  # Set international-only
                    self.product_data.pop("OUT_OF_STOCK", None)  # Clear out_of_stock
                    verbose_output(f"{BackgroundColors.YELLOW}Product has ONLY international shipping.{Style.RESET_ALL}")  # Log result
                    return True  # Return True

                if national_available and international_available:  # Both available
                    self.product_data["INTERNATIONAL_ONLY"] = False  # Not international-only
                    self.product_data.pop("OUT_OF_STOCK", None)  # Clear out_of_stock
                    verbose_output(f"{BackgroundColors.GREEN}Product has both national and international shipping available.{Style.RESET_ALL}")  # Log result
                    return False  # Return False

                if (national_soldout or (not national_available)) and (international_soldout or (not international_available)) and (national_soldout or international_soldout):  # Both unavailable
                    self.product_data["OUT_OF_STOCK"] = True  # Mark out of stock
                    self.product_data["INTERNATIONAL_ONLY"] = False  # Clear international-only
                    verbose_output(f"{BackgroundColors.RED}Both shipping options are sold out — treating product as OUT_OF_STOCK.{Style.RESET_ALL}")  # Log out of stock
                    return False  # Return False

                if national_available:  # National available only or detected
                    self.product_data["INTERNATIONAL_ONLY"] = False  # Not international-only
                    self.product_data.pop("OUT_OF_STOCK", None)  # Clear out_of_stock
                    verbose_output(f"{BackgroundColors.GREEN}National shipping available or detected; not international-only.{Style.RESET_ALL}")  # Log national available
                    return False  # Return False

            verbose_output(f"{BackgroundColors.YELLOW}No shipping options found.{Style.RESET_ALL}")  # No shipping elements found
            return False  # Preserve behavior when missing

        except Exception as e:  # Unexpected error
            verbose_output(f"{BackgroundColors.RED}Error detecting international shipping: {e}{Style.RESET_ALL}")  # Log exception
            return False  # Default to False on error


    def print_product_info(self, product_data=None):
        """
        Prints the extracted product information in a formatted manner.

        :param product_data: Dictionary containing the scraped product data
        :return: None
        """

        if not product_data:  # Verify if product data dictionary is empty or None
            print(f"{BackgroundColors.RED}No product data to display.{Style.RESET_ALL}")  # Alert user that no data is available
            return  # Exit method early when no data to print
        verbose_output(f"{BackgroundColors.GREEN}Product information extracted successfully:{BackgroundColors.GREEN}\n  {BackgroundColors.CYAN}Name:{BackgroundColors.GREEN} {product_data.get('name', 'N/A')}\n  {BackgroundColors.CYAN}SKU:{BackgroundColors.GREEN} {product_data.get('sku', 'N/A')}\n  {BackgroundColors.CYAN}Reviews:{BackgroundColors.GREEN} {product_data.get('reviews', 'N/A')}\n  {BackgroundColors.CYAN}Sizes:{BackgroundColors.GREEN} {', '.join(product_data.get('available_sizes', []))}\n  {BackgroundColors.CYAN}Old Price:{BackgroundColors.GREEN} R${product_data.get('old_price_integer', 'N/A')},{product_data.get('old_price_decimal', 'N/A') if product_data.get('old_price_integer', 'N/A') != 'N/A' else 'N/A'}\n  {BackgroundColors.CYAN}Current Price:{BackgroundColors.GREEN} R${product_data.get('current_price_integer', 'N/A')},{product_data.get('current_price_decimal', 'N/A')}\n  {BackgroundColors.CYAN}Discount:{BackgroundColors.GREEN} {product_data.get('discount_percentage', 'N/A')}\n  {BackgroundColors.CYAN}Description:{BackgroundColors.GREEN} {product_data.get('description', 'N/A')[:100]}...{Style.RESET_ALL}")


    def extract_sku(self, soup):
        """
        Extracts the SKU from the product page HTML.

        Args:
            soup (BeautifulSoup): The parsed HTML of the product page.

        Returns:
            str: The extracted SKU or 'N/A' if not found.
        """
        try:
            sku_elem = soup.find(string=lambda text: text and 'SKU' in text and getattr(text.parent, 'name', '') not in ['script', 'style'])
            if sku_elem and sku_elem.parent:
                sku_text = sku_elem.parent.get_text(strip=True)
                if 'SKU' in sku_text:
                    return sku_text.replace("SKU", "").replace(":", "").strip()
        except Exception:
            pass
        return "N/A"

    def extract_available_sizes(self, soup):
        """
        Extracts a list of available (non-sold-out) sizes from the product page HTML.

        Args:
            soup (BeautifulSoup): The parsed HTML of the product page.

        Returns:
            list: A list of available size strings.
        """
        available_sizes = []
        try:
            size_elements = soup.find_all('div', class_=lambda c: c and 'product-intro__size-radio' in c and 'soldout' not in c)
            for s in size_elements:
                size_text = s.get('aria-label') or s.get_text(strip=True)
                if size_text and size_text not in available_sizes:
                    available_sizes.append(size_text)
        except Exception:
            pass
        return available_sizes

    def extract_reviews(self, soup):
        """
        Extracts a snippet of review or rating text from the product page HTML.

        Args:
            soup (BeautifulSoup): The parsed HTML of the product page.

        Returns:
            str: The extracted review text or 'N/A'.
        """
        try:
            # Common Shein review class
            review_elem = soup.find('div', class_=lambda c: c and ('reviews' in c.lower() or 'rate' in c.lower() or 'common-reviews' in c.lower()))
            if review_elem:
                text = review_elem.get_text(separator=' ', strip=True)
                if 'Review' in text or 'review' in text or '(' in text:
                    return text[:50] # return first 50 chars as it might be long
            
            # Alternative: search near SKU
            sku_elem = soup.find(string=lambda text: text and 'SKU' in text and getattr(text.parent, 'name', '') not in ['script', 'style'])
            if sku_elem and sku_elem.parent and sku_elem.parent.parent:
                siblings = sku_elem.parent.parent.find_next_siblings()
                for sib in siblings:
                    sib_text = sib.get_text(separator=' ', strip=True)
                    if 'Review' in sib_text or '(' in sib_text:
                        return sib_text[:50]
        except Exception:
            pass
        return "N/A"

    def scrape_product_info(self, html_content=""):
        """
        Scrapes product information from rendered HTML content.

        :param html_content: Rendered HTML string
        :return: Dictionary containing the scraped product data
        """

        verbose_output(f"{BackgroundColors.GREEN}Parsing product information...{Style.RESET_ALL}")
        try:  # Attempt to parse product information with error handling
            soup = BeautifulSoup(html_content, "html.parser")  # Parse HTML content into BeautifulSoup object
            product_name = self.extract_product_name(soup)  # Extract product name from parsed HTML
            current_price_int, current_price_dec = self.extract_current_price(soup)  # Extract current price integer and decimal parts
            discount_percentage = self.extract_discount_percentage(soup)  # Extract discount percentage value
            old_price_int, old_price_dec = self.extract_old_price(soup, current_price_int, current_price_dec, discount_percentage)  # Extract old price with computational fallback
            raw_description = self.extract_product_description(soup)  # Extract product description (may be str or structured dict)  
            if isinstance(raw_description, dict):  # If structured object returned by extractor  
                description_text = raw_description.get("text", "No description available")  # Extract textual part safely  
                description_structured = {"text": raw_description.get("text", ""), "attributes": raw_description.get("attributes", {})}  # Normalize structured dict for product_data  
            else:  # Fallback when extractor returned legacy string  
                description_text = raw_description or "No description available"  # Ensure non-empty string  
                description_structured = {"text": description_text, "attributes": {}}  # Empty attributes to preserve schema  
            is_international = self.detect_international(soup)  # Detect if product has only international shipping  
            sku = self.extract_sku(soup)
            available_sizes = self.extract_available_sizes(soup)
            reviews = self.extract_reviews(soup)
            import re as _re
            safe_name = _re.sub(r'[<>:"/\\|?*]', '', product_name)[:80].strip()  # Derive filesystem-safe product name
            self.product_data = {"name": product_name, "product_name_safe": safe_name, "sku": sku, "reviews": reviews, "available_sizes": available_sizes, "current_price_integer": current_price_int, "current_price_decimal": current_price_dec, "old_price_integer": old_price_int, "old_price_decimal": old_price_dec, "discount_percentage": discount_percentage, "description": description_text, "description_structured": description_structured, "url": self.product_url, "is_international": is_international}  # Store all extracted data in dictionary
            self.print_product_info(self.product_data)  # Display extracted product information to user
            return self.product_data  # Return complete product data dictionary
        except Exception as e:  # Catch any exceptions during parsing
            print(f"{BackgroundColors.RED}Error parsing product info: {e}{Style.RESET_ALL}")  # Alert user about parsing error
            return None  # Return None to indicate parsing failed



    def dismiss_cookie_popup(self, driver_or_page, is_playwright=False):
        """
        Dismiss the cookie consent popup using CSS selectors.
        Waits briefly for the popup to appear, then tries Shein-specific and generic selectors.
        """
        import time
        print(f"{BackgroundColors.CYAN}Checking for cookie consent popup...{Style.RESET_ALL}")
        
        # Wait briefly for the cookie popup to render (it often loads after a short delay)
        time.sleep(3)
        
        try:
            if is_playwright:
                # Playwright: try clicking "Reject All" button by text
                try:
                    reject_btn = driver_or_page.locator('button:has-text("Reject All")').first
                    if reject_btn.is_visible(timeout=3000):
                        reject_btn.click()
                        print(f"{BackgroundColors.GREEN}Cookie popup dismissed (Reject All).{Style.RESET_ALL}")
                        time.sleep(2)
                        return True
                except Exception:
                    pass
            else:
                # Selenium: use JavaScript to find and click the button
                # Broadened search: checks all clickable elements and uses .includes() for partial matching
                dismissed = driver_or_page.execute_script("""
                    // Wait helper: search all clickable elements including nested text
                    var allClickable = document.querySelectorAll('button, a, div[role="button"], span[role="button"], [class*="cookie"] button, [class*="consent"] button, [class*="privacy"] button');
                    
                    // First pass: look for "Reject All"
                    for (var i = 0; i < allClickable.length; i++) {
                        var text = (allClickable[i].innerText || allClickable[i].textContent || '').trim().toLowerCase();
                        if (text === 'reject all') {
                            allClickable[i].click();
                            return 'rejected';
                        }
                    }
                    
                    // Second pass: broader search using all elements (handles nested spans)
                    var allElements = document.querySelectorAll('*');
                    for (var i = 0; i < allElements.length; i++) {
                        var el = allElements[i];
                        // Only match leaf text nodes
                        if (el.children.length === 0 || el.tagName === 'BUTTON') {
                            var text = (el.innerText || el.textContent || '').trim().toLowerCase();
                            if (text === 'reject all') {
                                // Click the element or its closest button/link parent
                                var clickTarget = el.closest('button, a, [role="button"]') || el;
                                clickTarget.click();
                                return 'rejected';
                            }
                        }
                    }
                    
                    // Third pass: fallback to Accept All
                    for (var i = 0; i < allElements.length; i++) {
                        var el = allElements[i];
                        if (el.children.length === 0 || el.tagName === 'BUTTON') {
                            var text = (el.innerText || el.textContent || '').trim().toLowerCase();
                            if (text === 'accept all') {
                                var clickTarget = el.closest('button, a, [role="button"]') || el;
                                clickTarget.click();
                                return 'accepted';
                            }
                        }
                    }
                    
                    return null;
                """)
                if dismissed:
                    print(f"{BackgroundColors.GREEN}Cookie popup dismissed ({dismissed}).{Style.RESET_ALL}")
                    time.sleep(2)
                    return True
                else:
                    print(f"{BackgroundColors.CYAN}No cookie popup found via CSS selectors.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{BackgroundColors.YELLOW}Cookie popup dismissal error: {e}{Style.RESET_ALL}")
        return False

    def detect_and_solve_captcha(self, driver_or_page, is_playwright=False, cookie_already_dismissed=False):
        """
        Generic Captcha solver using Gemini Multimodal vision, with loop for multi-step captchas.
        Also handles cookie popups that CSS selectors missed.
        
        :param cookie_already_dismissed: If True, skip cookie popup actions (already handled by CSS selector).
        :return: True if captcha was solved or not present, False if captcha could not be solved.
        """
        if not self.api_keys:
            print(f"{BackgroundColors.YELLOW}No Gemini API key provided. Skipping Captcha Solver.{Style.RESET_ALL}")
            return True
            
        import json
        import time
        print(f"{BackgroundColors.CYAN}Checking for Captcha...{Style.RESET_ALL}")
        
        screenshot_path = "captcha_screenshot.png"
        captcha_solved = True  # Assume no captcha until proven otherwise
        
        try:
            # --- Quick CSS-based "I am human" checkbox check (no API call needed) ---
            if not is_playwright:
                try:
                    iam_human_clicked = driver_or_page.execute_script("""
                        // Look for "I am human" text in the page
                        var allElements = document.querySelectorAll('*');
                        for (var i = 0; i < allElements.length; i++) {
                            var el = allElements[i];
                            var text = (el.innerText || el.textContent || '').trim().toLowerCase();
                            if (text === 'i am human') {
                                // Find the clickable parent or sibling checkbox
                                var clickTarget = el.closest('label, div, span, button') || el;
                                // Also look for a checkbox input nearby
                                var checkbox = clickTarget.querySelector('input[type="checkbox"]');
                                if (checkbox) {
                                    checkbox.click();
                                } else {
                                    clickTarget.click();
                                }
                                return true;
                            }
                        }
                        return false;
                    """)
                    if iam_human_clicked:
                        print(f"{BackgroundColors.GREEN}Clicked 'I am human' checkbox via CSS selector.{Style.RESET_ALL}")
                        time.sleep(8)  # Wait for verification
                        # Check if it triggered a puzzle
                        # Continue to Gemini check below to handle any follow-up
                except Exception as e:
                    pass  # Fall through to Gemini vision

            api_key = next(iter(self.api_keys.values()))
            gemini = Gemini(api_key, model_name="gemini-3.1-flash-lite")
            
            prompt = """Analyze this browser screenshot. Look for:
1. A CAPTCHA blocking the page (e.g. 'click to verify you are human' checkbox, 'select all images' puzzle, 'I am human' checkbox).
2. A cookie consent popup/banner (e.g. 'Accept All', 'Reject All', 'Manage Cookies' buttons).
3. An error message requiring page refresh (e.g., 'Access timed out, please refresh the page').

Return ONLY a valid JSON object (no markdown, no code blocks) with this schema:
{
  "has_captcha": true/false,
  "has_cookie_popup": true/false,
  "needs_refresh": true/false,
  "action": "click" | "type" | "slide" | "multi_click" | "refresh",
  "target_x": 0,
  "target_y": 0,
  "clicks": [{"x": 0, "y": 0}],
  "text_to_type": ""
}

Rules:
- If there is an 'Access timed out' or 'refresh the page' error: set needs_refresh=true, action="refresh".
- If there is a CAPTCHA: set has_captcha=true and provide the action+coordinates to solve it.
  - "I am human" checkbox: action="click", target_x/target_y = center of checkbox.
  - Image grid puzzle: action="multi_click", clicks = list of center coords for each correct image + the "Verify"/"Submit" button.
- If there is a cookie popup (no captcha): set has_cookie_popup=true, has_captcha=false, action="click", target_x/target_y = center of the "Reject All" button. If no "Reject All", use "Accept All".
- If none of the above are visible: return {"has_captcha": false, "has_cookie_popup": false, "needs_refresh": false}."""

            for attempt in range(5):  # Up to 5 attempts for multi-step captchas
                if is_playwright:
                    driver_or_page.screenshot(path=screenshot_path)
                else:
                    driver_or_page.save_screenshot(screenshot_path)

                # Get screenshot dimensions and viewport dimensions for coordinate scaling
                if not is_playwright:
                    import PIL.Image
                    with PIL.Image.open(screenshot_path) as img:
                        ss_width, ss_height = img.size
                    viewport = driver_or_page.execute_script(
                        "return {width: window.innerWidth, height: window.innerHeight};"
                    )
                    vp_width = viewport["width"]
                    vp_height = viewport["height"]
                    scale_x = vp_width / ss_width if ss_width > 0 else 1.0
                    scale_y = vp_height / ss_height if ss_height > 0 else 1.0
                else:
                    scale_x = 1.0
                    scale_y = 1.0

                response_text = gemini.generate_content_from_image(prompt, screenshot_path)
                # Strip markdown wrappers if present
                response_text = response_text.replace("```json", "").replace("```", "").strip()
                
                try:
                    action_data = json.loads(response_text)
                except json.JSONDecodeError:
                    print(f"{BackgroundColors.RED}Gemini returned invalid JSON: {response_text[:200]}{Style.RESET_ALL}")
                    # Try to extract JSON from the response using regex
                    import re
                    json_match = re.search(r'\{[^{}]*\}', response_text)
                    if json_match:
                        try:
                            action_data = json.loads(json_match.group())
                        except json.JSONDecodeError:
                            print(f"{BackgroundColors.RED}Could not parse extracted JSON either. Skipping.{Style.RESET_ALL}")
                            break
                    else:
                        break
                
                if action_data.get("needs_refresh") or action_data.get("action") == "refresh":
                    print(f"{BackgroundColors.YELLOW}Error detected. Refreshing page...{Style.RESET_ALL}")
                    if is_playwright:
                        driver_or_page.reload()
                    else:
                        driver_or_page.refresh()
                    time.sleep(5)
                    continue

                if action_data.get("has_captcha") or (action_data.get("has_cookie_popup") and not cookie_already_dismissed):
                    label = "CAPTCHA" if action_data.get("has_captcha") else "COOKIE POPUP"
                    if action_data.get("has_captcha"):
                        self.captcha_encountered = True
                        captcha_solved = False  # Mark as unsolved until we break with success
                    print(f"{BackgroundColors.RED}[{label} DETECTED - Step {attempt+1}] Attempting to solve...{Style.RESET_ALL}")
                    action = action_data.get("action")
                    raw_x = action_data.get("target_x")
                    raw_y = action_data.get("target_y")
                    
                    # Scale coordinates from screenshot pixels to viewport CSS pixels
                    x = int(raw_x * scale_x) if raw_x is not None else None
                    y = int(raw_y * scale_y) if raw_y is not None else None
                    
                    if not is_playwright:
                        from selenium.webdriver.common.action_chains import ActionChains
                        def cdp_click(driver, click_x, click_y):
                            try:
                                import random
                                # Move mouse near the target first to simulate human behavior
                                start_x = max(0, click_x - random.randint(10, 50))
                                start_y = max(0, click_y - random.randint(10, 50))
                                driver.execute_cdp_cmd('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': start_x, 'y': start_y})
                                time.sleep(0.1)
                                driver.execute_cdp_cmd('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': click_x, 'y': click_y})
                                time.sleep(0.2)
                                driver.execute_cdp_cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': click_x, 'y': click_y, 'button': 'left', 'clickCount': 1})
                                time.sleep(0.1)
                                driver.execute_cdp_cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': click_x, 'y': click_y, 'button': 'left', 'clickCount': 1})
                            except Exception as e:
                                print(f"{BackgroundColors.YELLOW}CDP click failed: {e}{Style.RESET_ALL}")
                                # Fallback to absolute W3C actions
                                try:
                                    actions = ActionChains(driver)
                                    actions.w3c_actions.pointer_action.move_to_location(click_x, click_y)
                                    actions.w3c_actions.pointer_action.click()
                                    actions.perform()
                                except Exception as e2:
                                    print(f"{BackgroundColors.YELLOW}ActionChains fallback failed: {e2}{Style.RESET_ALL}")

                        if action == "click" and x is not None and y is not None:
                            cdp_click(driver_or_page, x, y)
                        elif action == "type" and x is not None and y is not None:
                            text = action_data.get("text_to_type", "")
                            cdp_click(driver_or_page, x, y)
                            time.sleep(0.5)
                            ActionChains(driver_or_page).send_keys(text).perform()
                        elif action == "multi_click":
                            clicks = action_data.get("clicks", [])
                            for click_coords in clicks:
                                cx = click_coords.get("x")
                                cy = click_coords.get("y")
                                if cx is not None and cy is not None:
                                    scaled_cx = int(cx * scale_x)
                                    scaled_cy = int(cy * scale_y)
                                    cdp_click(driver_or_page, scaled_cx, scaled_cy)
                                time.sleep(1.0)
                    else:
                        if action == "click" and x is not None and y is not None:
                            driver_or_page.mouse.click(x, y, delay=100)
                        elif action == "type" and x is not None and y is not None:
                            driver_or_page.mouse.click(x, y)
                            driver_or_page.keyboard.type(action_data.get("text_to_type", ""), delay=50)
                        elif action == "multi_click":
                            clicks = action_data.get("clicks", [])
                            for click_coords in clicks:
                                driver_or_page.mouse.click(click_coords.get("x"), click_coords.get("y"), delay=100)
                                time.sleep(1.0)
                    
                    print(f"{BackgroundColors.GREEN}Executed {label.lower()} solution step. Waiting 8 seconds...{Style.RESET_ALL}")
                    time.sleep(8)  # Wait for verification/next step
                else:
                    print(f"{BackgroundColors.GREEN}No Captcha or popup detected (or cleared successfully).{Style.RESET_ALL}")
                    captcha_solved = True
                    break  # Break out of the loop!
                    
        except Exception as e:
            print(f"{BackgroundColors.YELLOW}Captcha solver error: {e}{Style.RESET_ALL}")
            import traceback
            traceback.print_exc()
        finally:
            if os.path.exists(screenshot_path):
                pass  # Keep screenshot for debugging
        
        if not captcha_solved:
            print(f"{BackgroundColors.RED}[WARNING] Captcha could not be solved after all attempts.{Style.RESET_ALL}")
        return captcha_solved

    def scrape(self, verbose=False):
        """
        Main scraping method that orchestrates the entire scraping process.
        Supports both online scraping (via browser) and offline scraping (from local HTML file).

        :param verbose: Boolean flag to enable verbose output
        :return: Dictionary containing all scraped data and downloaded file paths
        """

        verbose_output(f"{BackgroundColors.BOLD}{BackgroundColors.GREEN}Starting {BackgroundColors.CYAN}Shein{BackgroundColors.GREEN} Scraping process...{Style.RESET_ALL}")
        try:  # Attempt scraping process with error handling
            if self.local_html_path:  # If local HTML file path is provided
                verbose_output(f"{BackgroundColors.GREEN}Using offline mode with local HTML file{Style.RESET_ALL}")
                html_content = self.read_local_html()  # Read HTML content from local file
                if not html_content:  # Verify if HTML reading failed
                    return None  # Return None if HTML is unavailable
                self.html_content = html_content  # Store HTML content for later use
            else:  # Online scraping mode
                verbose_output(f"{BackgroundColors.GREEN}Using online mode with browser automation{Style.RESET_ALL}")
                html_content = None
                self.captcha_encountered = False
                
                # --- Undetected Chromedriver Injection ---
                try:
                    import undetected_chromedriver as uc
                    verbose_output(f"{BackgroundColors.CYAN}Attempting to use undetected-chromedriver...{Style.RESET_ALL}")
                    options = uc.ChromeOptions()
                    # options.headless = True  # Disabled to avoid CAPTCHA detection
                    profile_path = __import__('os').path.abspath(__import__('os').path.join(__import__('os').getcwd(), 'ChromeProfile'))
                    options.add_argument(f"--user-data-dir={profile_path}")
                    options.add_argument("--start-minimized")
                    driver = uc.Chrome(options=options, version_main=149)
                    driver.set_page_load_timeout(120)
                    try:
                        driver.get(self.product_url)
                    except Exception as e:
                        verbose_output(f"{BackgroundColors.YELLOW}Selenium page load timeout or error, checking for Captcha...{Style.RESET_ALL}")
                    
                    # Step 1: Dismiss cookie popup via CSS selectors (fast, no API call)
                    cookie_dismissed = self.dismiss_cookie_popup(driver)
                    # Step 2: Check for actual CAPTCHA via Gemini vision
                    captcha_solved = self.detect_and_solve_captcha(driver, cookie_already_dismissed=cookie_dismissed)
                    if not captcha_solved:
                        verbose_output(f"{BackgroundColors.RED}[ABORT] Captcha unsolved. Skipping URL.{Style.RESET_ALL}")
                        driver.quit()
                        return None
                    
                    # Scroll down to trigger lazy loading
                    import time
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                    time.sleep(6)
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(6)
                    
                    # Scroll back up a bit to ensure elements in middle trigger
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
                    time.sleep(3)
                    
                    # Click 'Description' dropdown/accordion if it exists
                    try:
                        driver.execute_script("""
                            var elements = document.querySelectorAll('div, span, button, a');
                            for (var i = 0; i < elements.length; i++) {
                                var text = elements[i].innerText || elements[i].textContent;
                                if (text && text.trim().toLowerCase() === 'description') {
                                    elements[i].click();
                                    break;
                                }
                            }
                        """)
                        time.sleep(2) # Give it time to expand
                    except Exception as e:
                        verbose_output(f"{BackgroundColors.YELLOW}Could not click Description: {e}{Style.RESET_ALL}")

                    html_content = driver.page_source
                    driver.quit()
                    self.html_content = html_content
                except Exception as uc_e:
                    verbose_output(f"{BackgroundColors.YELLOW}undetected-chromedriver failed: {uc_e}. Falling back to Playwright...{Style.RESET_ALL}")
                    # --- Fallback to Original Playwright ---
                    self.launch_browser()  # Initialize and launch browser instance
                    if not self.load_page():  # Attempt to load product page
                        return None  # Return None if page loading failed
                    self.wait_full_render()  # Wait for page to fully render with dynamic content
                    self.auto_scroll()  # Scroll page to trigger lazy-loaded content
                    html_content = self.get_rendered_html()  # Extract fully rendered HTML content
                    if not html_content:  # Verify if HTML extraction failed
                        return None  # Return None if HTML is unavailable
                    self.html_content = html_content  # Store HTML content for later use
            product_info = self.scrape_product_info(html_content)  # Parse and extract product information
            if not product_info:  # Verify if product info extraction failed
                return None  # Return None if extraction failed
            verbose_output(f"{BackgroundColors.BOLD}{BackgroundColors.GREEN}Shein scraping completed successfully!{Style.RESET_ALL}")
            return product_info  # Return complete product information with downloaded files
        except Exception as e:  # Catch any exceptions during scraping process
            print(f"{BackgroundColors.RED}Scraping failed: {e}{Style.RESET_ALL}")  # Alert user about scraping failure
            return None  # Return None to indicate scraping failed
        finally:  # Always execute cleanup regardless of success or failure
            if not self.local_html_path:  # Only close browser in online mode
                self.close_browser()  # Close browser and release resources


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
















