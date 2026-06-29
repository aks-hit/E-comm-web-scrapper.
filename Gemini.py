"""
================================================================================
Gemini API Scraper - Gemini.py
================================================================================

Description :
    Wrapper for interacting with Google's Gemini (google.genai) SDK.
    This module provides the `Gemini` class used by the scraper to:
    1. Detect and solve CAPTCHAs via the Vision API (`generate_content_from_image`).
    2. Generate marketing templates/descriptions from scraped product data.

    It implements robust retry/backoff logic for transient API failures, quota
    management, and automatic key rotation signaling.

Usage:
    Import the `Gemini` class in your scripts and initialize it with your API key.

Dependencies:
    - Python >= 3.8
    - google-genai
"""


from colorama import Style  # For coloring the terminal
from Logger import Logger  # For logging output to both terminal and file
from pathlib import Path  # For handling file paths
import sys
import os
import time


# Macros:
class BackgroundColors:  # Colors for the terminal
    CYAN = "\033[96m"  # Cyan
    GREEN = "\033[92m"  # Green
    YELLOW = "\033[93m"  # Yellow
    RED = "\033[91m"  # Red
    BOLD = "\033[1m"  # Bold


# Execution Constants:
VERBOSE = False  # Set to True to output verbose messages
MAX_RETRIES = 3  # Maximum number of retry rounds for retryable Gemini API failures
RETRY_BASE_DELAY_SECONDS = 15  # Base delay in seconds used for exponential backoff
RETRYABLE_API_ERROR_KEYWORDS = (
    "503",
    "429",
    "unavailable",
    "temporary",
    "temporarily",
    "service unavailable",
    "high demand",
    "rate",
    "quota",
    "limit",
    "resource_exhausted",
    "too many requests",
    "timeout",
    "timed out",
    "connection",
    "deadline exceeded",
    "internal",
    "server error",
    "bad gateway",
    "gateway timeout",
)  # Keywords used to classify transient Gemini API failures for retry

PERMANENT_API_ERROR_STATUS_CODES = (
    400,
    401,
    403,
    404,
    405,
    422,
)  # HTTP status codes that classify API responses as permanent non-retryable failures

PERMANENT_API_ERROR_KEYWORDS = (
    "not_found",
    "invalid_argument",
    "permission_denied",
    "unauthenticated",
    "unauthorized",
    "forbidden",
    "unimplemented",
    "failed_precondition",
    "api_key_invalid",
    "invalid api key",
    "api key not valid",
    "bad request",
    "method not allowed",
    "unprocessable entity",
)  # Keywords used to classify permanent non-retryable Gemini API failures that abort all key rotation

QUOTA_EXHAUSTED_API_ERROR_KEYWORDS = (
    "429",
    "resource_exhausted",
    "quota",
    "too many requests",
    "rate limit",
    "ratelimitexceeded",
    "usage limit",
    "usage_limit_exceeded",
    "daily limit",
    "per-minute",
    "per_minute",
    "per-day",
    "per_day",
    "insufficient_quota",
    "billing",
    "token limit",
    "capacity exhausted",
)  # Keywords used to identify API quota, resource, and capacity exhaustion errors that require immediate key rotation

# File Path Constants:
INPUT_DIRECTORY = "./Inputs/"  # The path to the input directory
INPUT_FILE = f"{INPUT_DIRECTORY}input.txt"  # The path to the input file
OUTPUT_DIRECTORY = "./Outputs/"  # The path to the output directory
OUTPUT_FILE = f"{OUTPUT_DIRECTORY}output.txt"  # The path to the output file

# Logger Setup:
logger = Logger(f"./Logs/{Path(__file__).stem}.log", clean=True)  # Create a Logger instance
sys.stdout = logger  # Redirect stdout to the logger
sys.stderr = logger  # Redirect stderr to the logger

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




class QuotaExceededError(Exception):
    """
    Represents a quota exhaustion signal for a specific Gemini API key.

    :param message: Error message describing the quota exhaustion event.
    :param key_index: 1-based API key index that became exhausted.
    :param status_code: Optional numeric HTTP-like status code.
    :param status_text: Optional status text such as RESOURCE_EXHAUSTED.
    :param original_error: Original exception object raised by the SDK.
    :return: None
    """

    def __init__(self, message, key_index=None, status_code=None, status_text=None, original_error=None):
        super().__init__(message)  # Initialize base Exception with provided message.
        self.key_index = key_index  # Store the 1-based API key index for upstream rotation.
        self.status_code = status_code  # Store parsed status code when available.
        self.status_text = status_text  # Store parsed status text when available.
        self.original_error = original_error  # Store original SDK exception for diagnostics.


class PermanentApiFailureError(Exception):
    """
    Represents a permanent non-retryable failure signal for a Gemini API request.

    :param message: Error message describing the permanent failure event.
    :param key_index: 1-based API key index that encountered the failure.
    :param status_code: Optional numeric HTTP-like status code.
    :param status_text: Optional status text such as NOT_FOUND.
    :param original_error: Original exception object raised by the SDK.
    :return: None
    """

    def __init__(self, message, key_index=None, status_code=None, status_text=None, original_error=None):
        super().__init__(message)  # Initialize base Exception with provided message.
        self.key_index = key_index  # Store the 1-based API key index for upstream abort signal.
        self.status_code = status_code  # Store parsed status code when available.
        self.status_text = status_text  # Store parsed status text when available.
        self.original_error = original_error  # Store original SDK exception for diagnostics.


class Gemini:
    """
    Class for interacting with Google's Gemini AI model.
    
    This class provides methods to configure the model, read input files,
    start chat sessions, send messages, and write outputs using the google.genai SDK.
    """


    def __init__(self, api_key, api_key_index=None, model_name: str = "gemini-3.1-flash-lite"):
        """
        Initialize the Gemini class with an API key.
        
        :param api_key: The API key for Google's Gemini AI.
        :param api_key_index: Optional 1-based API key index used for controlled quota signaling.
        :param model_name: Gemini model name used by chat and content generation calls.
        :return: None.
        """
        
        verbose_output(true_string=f"{BackgroundColors.GREEN}Initializing Gemini Client...{Style.RESET_ALL}")
        
        self.api_key = api_key  # Store the API key.
        self.api_key_index = api_key_index  # Store the 1-based key index for quota signaling.
        self.client = genai.Client(api_key=api_key)  # Create the Gemini client.
        self.model = model_name  # Default model; can be overridden in method calls if needed. Read: https://aistudio.google.com/rate-limit?timeRange=last-28-days for current rate limits and available models.
        self.chat = None  # Placeholder for chat session.
        self.quota_exhausted = False  # Track if quota is exhausted for this API key.
    
    
    def verify_api_quota_state(self) -> tuple:
        """
        Verifies if quota is available and if retry is allowed.

        :return: Tuple (quota_available, retry_allowed)

        """
        if self.quota_exhausted:  # If quota is already exhausted
            return (False, False)  # Return quota unavailable, retry not allowed
        return (True, True)  # Return quota available, retry allowed


    def read_input_file(self, file_path=INPUT_FILE):
        """
        Reads the input file.
        
        :param file_path: The path to the input file.
        :return: The content of the file.
        """
        
        verbose_output(true_string=f"{BackgroundColors.GREEN}Reading the input file...{Style.RESET_ALL}")
        
        if not os.path.exists(file_path):  # If the input file does not exist
            print(
                f"{BackgroundColors.RED}Input file {BackgroundColors.CYAN}{file_path}{BackgroundColors.RED} not found.{Style.RESET_ALL}"
            )
            sys.exit(1)  # Exit the program
        
        with open(file_path, "r") as file:  # Open the input file
            content = file.read()  # Read the content of the file
        
        return content  # Return the content of the file


    def is_retryable_api_error(self, error):
        """
        Determines whether an API error should be retried.

        :param error: The exception raised during an API request.
        :return: True if the error appears temporary/retryable, False otherwise.
        """

        error_text = str(error).lower()  # Convert exception message to lowercase for keyword matching
        return any(keyword in error_text for keyword in RETRYABLE_API_ERROR_KEYWORDS)  # Return True when any retryable keyword is present


    def is_quota_exhausted_api_error(self, error):
        """
        Determines whether an API error indicates key quota exhaustion.

        :param error: The exception raised during an API request.
        :return: True if the error indicates exhausted key quota, otherwise False.
        """

        error_text = str(error).lower()  # Convert exception text to lowercase for deterministic keyword matching.
        return any(keyword in error_text for keyword in QUOTA_EXHAUSTED_API_ERROR_KEYWORDS)  # Return True when any quota exhaustion keyword is present in the error text.


    def create_quota_exhausted_error(self, error):
        """
        Creates a structured quota exhaustion exception for caller-side key rotation.

        :param error: Original exception raised by the Gemini SDK request.
        :return: QuotaExceededError containing parsed key and status metadata.
        """

        error_text = str(error)  # Store original error text for message propagation.
        error_text_lower = error_text.lower()  # Normalize text for status/code extraction.
        status_code = 429 if "429" in error_text_lower else None  # Parse HTTP 429 status code when present in message text.

        if "resource_exhausted" in error_text_lower:  # Verify explicit RESOURCE_EXHAUSTED status label for classification.
            status_text = "RESOURCE_EXHAUSTED"  # Assign canonical SDK status label for deterministic downstream identification.
        elif "billing" in error_text_lower:  # Verify billing quota exhaustion indicator for classification.
            status_text = "BILLING_QUOTA_EXCEEDED"  # Assign billing quota status label for deterministic downstream identification.
        elif "daily" in error_text_lower and ("limit" in error_text_lower or "quota" in error_text_lower):  # Verify daily limit or daily quota exhaustion indicator.
            status_text = "DAILY_QUOTA_EXCEEDED"  # Assign daily quota status label for deterministic downstream identification.
        elif "per-minute" in error_text_lower or "per_minute" in error_text_lower:  # Verify per-minute quota exhaustion indicator.
            status_text = "PER_MINUTE_QUOTA_EXCEEDED"  # Assign per-minute quota status label for deterministic downstream identification.
        elif "per-day" in error_text_lower or "per_day" in error_text_lower:  # Verify per-day quota exhaustion indicator.
            status_text = "PER_DAY_QUOTA_EXCEEDED"  # Assign per-day quota status label for deterministic downstream identification.
        elif "rate limit" in error_text_lower or "ratelimitexceeded" in error_text_lower:  # Verify rate limit exhaustion indicator.
            status_text = "RATE_LIMIT_EXCEEDED"  # Assign rate limit status label for deterministic downstream identification.
        elif "too many requests" in error_text_lower:  # Verify too-many-requests indicator for classification.
            status_text = "TOO_MANY_REQUESTS"  # Assign too-many-requests status label for deterministic downstream identification.
        elif "usage limit" in error_text_lower or "usage_limit_exceeded" in error_text_lower:  # Verify usage limit exhaustion indicator.
            status_text = "USAGE_LIMIT_EXCEEDED"  # Assign usage limit status label for deterministic downstream identification.
        elif "token limit" in error_text_lower:  # Verify token limit exhaustion indicator.
            status_text = "TOKEN_LIMIT_EXCEEDED"  # Assign token limit status label for deterministic downstream identification.
        elif "capacity" in error_text_lower:  # Verify capacity exhaustion indicator.
            status_text = "CAPACITY_EXHAUSTED"  # Assign capacity exhaustion status label for deterministic downstream identification.
        elif "quota" in error_text_lower:  # Verify general quota exhaustion indicator as fallback.
            status_text = "QUOTA_EXCEEDED"  # Assign general quota exceeded status label for deterministic downstream identification.
        else:  # Default status label when no specific category matches.
            status_text = "QUOTA_EXHAUSTED"  # Assign default quota exhausted status label for deterministic downstream identification.

        key_index = self.api_key_index if self.api_key_index is not None else 0  # Use known key index or zero when unavailable.
        message = f"Gemini API key {key_index} quota exhausted ({status_text}): {error_text}"  # Build deterministic upstream-facing error message with category label.
        return QuotaExceededError(message, key_index=key_index, status_code=status_code, status_text=status_text, original_error=error)  # Return structured quota exhaustion signal.


    def is_permanent_api_error(self, error):
        """
        Determines whether an API error indicates a permanent non-retryable failure.

        :param error: The exception raised during an API request.
        :return: True if the error indicates a permanent failure, False otherwise.
        """

        error_text = str(error).lower()  # Convert exception message to lowercase for keyword matching
        return any(keyword in error_text for keyword in PERMANENT_API_ERROR_KEYWORDS)  # Return True when any permanent failure keyword is present in the error text


    def create_permanent_api_failure_error(self, error):
        """
        Creates a structured permanent failure exception for caller-side abort.

        :param error: Original exception raised by the Gemini SDK request.
        :return: PermanentApiFailureError containing parsed key and status metadata.
        """

        error_text = str(error)  # Store original error text for message propagation.
        error_text_lower = error_text.lower()  # Normalize text for status/code extraction.
        status_code = None  # Initialize status_code as absent until a match is found.

        for code in PERMANENT_API_ERROR_STATUS_CODES:  # Iterate permanent status codes to find a match in error text
            if str(code) in error_text_lower:  # Verify if this status code number appears in the error text
                status_code = code  # Assign matched status code for structured error propagation
                break  # Stop at first matched status code

        status_text = None  # Initialize status_text as absent until a known label is matched.
        permanent_status_labels = ("NOT_FOUND", "INVALID_ARGUMENT", "PERMISSION_DENIED", "UNAUTHENTICATED", "UNIMPLEMENTED", "FAILED_PRECONDITION")  # Define known permanent gRPC status labels for extraction

        for label in permanent_status_labels:  # Iterate permanent status labels to find a match
            if label.lower() in error_text_lower:  # Verify if this label appears in the normalized error text
                status_text = label  # Assign matched status label for structured error propagation
                break  # Stop at first matched label

        key_index = self.api_key_index if self.api_key_index is not None else 0  # Use known key index or zero when unavailable.
        message = f"Gemini API key {key_index} permanent failure: {error_text}"  # Build deterministic upstream-facing error message.
        return PermanentApiFailureError(message, key_index=key_index, status_code=status_code, status_text=status_text, original_error=error)  # Return structured permanent failure signal.


    def execute_with_retry(self, request_callable, operation_name="gemini_request"):
        """
        Executes a Gemini API callable with exponential backoff retry on temporary failures.

        :param request_callable: Callable that performs the API request and returns a response.
        :param operation_name: Label used in logs to identify the API operation.
        :return: The API response object if successful.
        """

        quota_available, retry_allowed = self.verify_api_quota_state()  # Get quota and retry state
        if not quota_available:  # If quota is exhausted
            raise QuotaExceededError("Quota already exhausted for this API key.")  # Raise quota exhaustion error

        retry_count = 0  # Initialize retry counter for transient failures

        while True:  # Continue attempts until success or retry limit reached
            try:  # Attempt API call and return immediately when successful
                return request_callable()  # Execute the provided Gemini API request callable
            except Exception as e:  # Capture request exceptions for retry decision
                if self.is_quota_exhausted_api_error(e):  # If this failure represents exhausted key quota
                    self.quota_exhausted = True  # Mark quota as exhausted for this API key.
                    quota_signal = self.create_quota_exhausted_error(e)  # Build structured quota exhaustion signal with parsed category metadata.
                    print(f"{BackgroundColors.YELLOW}[WARNING] Gemini API quota exhaustion detected for API key {self.api_key_index or 0}. Category: {BackgroundColors.CYAN}{quota_signal.status_text}{BackgroundColors.YELLOW}. Triggering immediate key rotation.{Style.RESET_ALL}")  # Emit deterministic log when API key is marked as exhausted with rotation reason.
                    raise quota_signal  # Raise structured quota signal so caller can rotate immediately without retrying.

                if self.is_permanent_api_error(e):  # If this failure represents a permanent non-retryable API error
                    raise self.create_permanent_api_failure_error(e)  # Raise permanent failure signal to abort all key rotation immediately

                if not self.is_retryable_api_error(e):  # Stop retry flow for non-transient exceptions
                    raise  # Re-raise non-retryable error so caller can handle it

                if self.quota_exhausted:  # If quota is now exhausted
                    raise QuotaExceededError("Quota already exhausted for this API key.")  # Raise quota exhaustion error

                if retry_count >= MAX_RETRIES:  # Stop retry flow when maximum retry budget is exhausted
                    print(f"{BackgroundColors.YELLOW}[WARNING] Gemini API temporary failure persisted after {MAX_RETRIES} retries during {operation_name}.{Style.RESET_ALL}")  # Log terminal warning when retries are exhausted
                    raise  # Re-raise the final transient exception after retry exhaustion

                retry_count += 1  # Increment retry counter for this transient failure
                wait_seconds = RETRY_BASE_DELAY_SECONDS * (2 ** (retry_count - 1))  # Compute exponential backoff delay for current retry
                verbose_output(true_string=f"{BackgroundColors.YELLOW}[WARNING] Gemini API temporary failure. Retrying in {wait_seconds} seconds (attempt {retry_count}/{MAX_RETRIES}).{Style.RESET_ALL}")  # Log retry schedule with attempt index
                time.sleep(wait_seconds)  # Wait before retrying the same request


    def start_chat_session(self):
        """
        Start a chat session with the model.
        
        :return: The chat session.
        """
        
        verbose_output(true_string=f"{BackgroundColors.GREEN}Starting the chat session...{Style.RESET_ALL}")
        
        self.chat = self.client.chats.create(model=self.model)  # Create a new chat session
        return self.chat  # Return the chat session


    def send_message(self, message, config=None):
        """
        Send a message in the chat session and get the output.

        :param message: The user message to send.
        :param config: Optional configuration (temperature, max_output_tokens, etc.).
        :return: The output text.
        """

        quota_available, retry_allowed = self.verify_api_quota_state()  # Get quota and retry state
        if not quota_available:  # If quota is exhausted
            raise QuotaExceededError("Quota already exhausted for this API key.")  # Raise quota exhaustion error

        verbose_output(true_string=f"{BackgroundColors.GREEN}Sending the message...{Style.RESET_ALL}")

        if self.chat is None:  # If the chat session has not been started
            self.start_chat_session()  # Start the chat session

        assert self.chat is not None  # Ensure chat is initialized
        chat_session = self.chat  # Store non-null chat session reference for type-safe lambda usage
        response = self.execute_with_retry(lambda: chat_session.send_message(message), operation_name="send_message")  # Send message with retry for transient API failures
        return response.text  # Return the output text


    def generate_content(self, prompt, config=None):
        """
        Generate content without maintaining chat history (stateless).

        :param prompt: The prompt to send to the model.
        :param config: Optional configuration (temperature, system_instruction, etc.).
        :return: The generated text.
        """

        quota_available, retry_allowed = self.verify_api_quota_state()  # Get quota and retry state
        
        if not quota_available:  # If quota is exhausted
            raise QuotaExceededError("Quota already exhausted for this API key.")  # Raise quota exhaustion error

        verbose_output(true_string=f"{BackgroundColors.GREEN}Generating content...{Style.RESET_ALL}")

        response = self.execute_with_retry(
            lambda: self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config
            ),
            operation_name="generate_content",
        )  # Generate content with retry for transient API failures
        return response.text  # Return the generated text


    def generate_content_from_image(self, prompt, image_path, config=None):
        """
        Generate content from a multimodal input (image + text prompt).

        :param prompt: The text prompt to send alongside the image.
        :param image_path: Path to the image file.
        :param config: Optional configuration (temperature, system_instruction, etc.).
        :return: The generated text.
        """

        import PIL.Image

        quota_available, retry_allowed = self.verify_api_quota_state()  # Get quota and retry state

        if not quota_available:  # If quota is exhausted
            raise QuotaExceededError("Quota already exhausted for this API key.")  # Raise quota exhaustion error

        verbose_output(true_string=f"{BackgroundColors.GREEN}Generating content from image...{Style.RESET_ALL}")

        image = PIL.Image.open(image_path)

        response = self.execute_with_retry(
            lambda: self.client.models.generate_content(
                model=self.model,
                contents=[image, prompt],
                config=config
            ),
            operation_name="generate_content_from_image",
        )  # Generate multimodal content with retry for transient API failures
        return response.text  # Return the generated text

    def write_output_to_file(self, output, file_path=OUTPUT_FILE):
        """
        Writes the chat output to a specified file.
        
        :param output: The output to write.
        :param file_path: The path to the file.
        :return: None
        """
        
        verbose_output(true_string=f"{BackgroundColors.GREEN}Writing the output to the file...{Style.RESET_ALL}")
        
        with open(file_path, "w", encoding="utf-8") as file:  # Open the file for writing with UTF-8
            file.write(output)  # Write the output to the file


    def close(self):
        """
        Close the client to release resources.
        
        :return: None
        """
        
        try:  # Close the client
            self.client.close()  # Close the client
        except Exception:  # Fail silently
            pass  # Silent



