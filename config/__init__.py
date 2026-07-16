import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file in the root directory
# __file__ is config/__init__.py, so parent.parent is email-enrichment/
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# ==============================================================================
# Base Directories
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data'
OUTPUT_DIR = BASE_DIR / 'output'
LOG_DIR = BASE_DIR / 'logs'
PROMPTS_DIR = BASE_DIR / 'prompts'

# Automatically create project structure directories on startup
for directory in [DATA_DIR, OUTPUT_DIR, LOG_DIR, PROMPTS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# ==============================================================================
# Ollama Configuration
# ==============================================================================
# Base URL for the local Ollama instance
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Model name tag to use for enrichment (e.g. gemma:4b, gemma:12b, gemma:32b)
MODEL_NAME = os.getenv("MODEL_NAME", "gemma4:31b")

# ==============================================================================
# Pipeline & Network Configuration
# ==============================================================================
# Timeout in seconds for HTTP and API requests
TIMEOUT = int(os.getenv("TIMEOUT", os.getenv("HTTP_TIMEOUT", "300")))
HTTP_TIMEOUT = TIMEOUT  # Alias for backward compatibility

# Maximum retry attempts for failed search queries or model generation calls
MAX_RETRIES = int(os.getenv("MAX_RETRIES", os.getenv("RETRY_COUNT", "3")))
RETRY_COUNT = MAX_RETRIES  # Alias for backward compatibility

# Maximum worker threads to process contacts concurrently in the pipeline
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))

# Size of batch processing when executing in steps
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))

# Fast-path configurations for performance optimization
VALIDATE_EXISTING_DATA = os.getenv("VALIDATE_EXISTING_DATA", "true").lower() == "true"
SKIP_LLM_ON_FAST_PATH_MATCH = os.getenv("SKIP_LLM_ON_FAST_PATH_MATCH", "true").lower() == "true"

# Sleep duration in seconds between web scraper actions to prevent rate-limiting/blocking
SEARCH_DELAY = float(os.getenv("SEARCH_DELAY", "1.5"))

# Optional limit of rows to process during testing and validation runs
ROW_LIMIT = os.getenv("ROW_LIMIT", None)
if ROW_LIMIT:
    try:
        ROW_LIMIT = int(ROW_LIMIT)
    except ValueError:
        ROW_LIMIT = None

# ==============================================================================
# Storage Configuration
# ==============================================================================
# Target file containing contact sources
excel_path_env = os.getenv("EXCEL_PATH")
if excel_path_env:
    excel_path = Path(excel_path_env)
else:
    excel_path = BASE_DIR / 'us_investors_export_1_enriched.xlsx'
    if not excel_path.exists():
        excel_path = BASE_DIR / 'contacts_export (1).xlsx'

if excel_path.exists():
    INPUT_FILE = excel_path
    OUTPUT_FILE = excel_path  # Write back to original file in-place
else:
    INPUT_FILE = DATA_DIR / 'contacts.csv'
    OUTPUT_FILE = OUTPUT_DIR / 'results.csv'

# Output log path
LOG_FILE = LOG_DIR / 'process.log'

# ==============================================================================
# Database / Future Scale Configuration
# ==============================================================================
# Database connection string for PostgreSQL or SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Switch to toggle relational DB storage mode
USE_DATABASE = os.getenv("USE_DATABASE", "false").lower() == "true"
