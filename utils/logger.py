import logging
import time
from pathlib import Path
from typing import Optional
import sys
from pathlib import Path

# Add root folder to path to allow importing config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# Set up logging directories and formats
log_file = config.LOG_FILE
log_file.parent.mkdir(parents=True, exist_ok=True)

# Create file handler to write all info logs
file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setLevel(logging.INFO)

# Create stream handler to print only warnings and errors to console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[file_handler, console_handler]
)

logger = logging.getLogger("EmailEnrichment")

def log_process_event(
    start_time: float,
    end_time: float,
    worker: str,
    company: str,
    duration: float,
    errors: Optional[str] = None,
    retry_attempts: int = 0
):
    """
    Writes a structured process log entry to the log file.
    Format: Start time, End time, Worker, Company, Processing duration, Errors, Retry attempts
    """
    import datetime
    start_str = datetime.datetime.fromtimestamp(start_time).isoformat()
    end_str = datetime.datetime.fromtimestamp(end_time).isoformat()
    error_str = errors if errors else "None"
    
    # We can write a special line prefix for structured process logs
    log_msg = (
        f"[METRIC] Start: {start_str} | End: {end_str} | Worker: {worker} | "
        f"Company: {company} | Duration: {duration:.2f}s | "
        f"Errors: {error_str} | Retries: {retry_attempts}"
    )
    logger.info(log_msg)
