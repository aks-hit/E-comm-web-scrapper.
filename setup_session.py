"""
================================================================================
Setup Session - setup_session.py
================================================================================
Description :
A manual intervention module that launches a persistent Chrome session.
It is used during the 'Session Warmup' phase or as a fallback when the AI solver fails,
allowing a human operator to solve complex CAPTCHAs manually. The session cookies
are saved to the ChromeProfile directory for the automated scraper to use.
"""
import undetected_chromedriver as uc
import os
import time

def setup_browser_session(test_url=None):
    """
    Initializes a manual browser session using undetected_chromedriver.
    This gives the user an opportunity to manually solve any initial CAPTCHAs
    or log into the target site before the automated scraping begins.
    """
    profile_path = os.path.abspath(os.path.join(os.getcwd(), 'ChromeProfile'))
    print(f"\n{'-'*60}")
    print(f"Setting up Chrome Profile at: {profile_path}")
    print("Launching browser...")

    try:
        options = uc.ChromeOptions()
        # Make sure to specify the profile directory
        options.add_argument(f"--user-data-dir={profile_path}")
        
        # Launch browser (version 145 to match installed chrome)
        driver = uc.Chrome(options=options, version_main=149)
        
        if test_url is None:
            # Fallback if no URL provided
            test_url = "https://us.shein.com/Women-Tops-c-1771.html"
            
        print(f"Navigating to {test_url}")
        driver.get(test_url)
        
        print("\n" + "="*60)
        print("ACTION REQUIRED: CAPTCHA REFRESH")
        print("1. If you see a CAPTCHA, please solve it manually in the browser window.")
        print("2. Wait until the actual product page loads fully.")
        print("3. Once the product is visible and the CAPTCHA is gone, come back here and press ENTER.")
        print("="*60 + "\n")
        
        input("Press ENTER here after solving the CAPTCHA... ")
        
        print("Saving session data and closing browser...")
        time.sleep(2)  # Give it a moment to ensure cookies are saved
        driver.quit()
        print(f"Session successfully saved! Continuing with scraping...\n{'-'*60}\n")
        
    except Exception as e:
        print(f"An error occurred during session setup: {e}")

if __name__ == "__main__":
    setup_browser_session()
