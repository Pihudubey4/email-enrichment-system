<<<<<<< HEAD
# Local Windows AI Email Enrichment System

A modular, production-ready contact email enrichment pipeline utilizing **Ollama** and **Gemma 4B** (with seamless configuration-only upgrades to 12B/32B). It reads contacts from a CSV file, searches the web, extracts target email addresses using local LLM inference, validates them, and logs runtime metrics.

## Features
- **Search Worker**: Uses DuckDuckGo search + BeautifulSoup web scraping to find contact info.
- **AI Worker**: Configurable Ollama interface with local Gemma support.
- **Validation Worker**: Formats check via regex and matches email domain with the corporate domain.
- **Robust Orchestrator**: Multithreaded execution, rate-limiting delays, graceful per-contact error recovery.
- **Architecture Scalability**: Storage is abstracted via custom interfaces (`DataStorage`) for easy migration to databases (PostgreSQL/SQLite) or message brokers.

---

## Getting Started

### 1. Prerequisites & Installation
Ensure you have **Python 3.11+** installed on your Windows system.

Clone or download this repository, navigate to the `email-enrichment` folder, and install dependencies:
```bash
pip install -r requirements.txt
```

### 2. Install and Setup Ollama
1. Download Ollama for Windows from [Ollama's Official Website](https://ollama.com).
2. Install and launch the Ollama application.
3. Open your terminal (PowerShell/CMD) and pull the Gemma model:
   ```bash
   ollama pull gemma:4b
   ```
   *Note: For larger models, use `ollama pull gemma:12b` or `ollama pull gemma:32b`.*

---

## Configuration

Modify configurations in the `.env` file or directly in the environment:

| Variable | Description | Default |
| --- | --- | --- |
| `OLLAMA_URL` | Base URL for Ollama instance | `http://localhost:11434` |
| `MODEL_NAME` | Ollama model tag | `gemma:4b` |
| `BATCH_SIZE` | Size of concurrent batches | `5` |
| `MAX_WORKERS` | Max concurrent worker threads | `3` |
| `RETRY_COUNT` | Max retry attempts for API/Web requests | `3` |
| `SEARCH_DELAY` | Sleep time between web scraping steps (seconds) | `1.5` |
| `HTTP_TIMEOUT` | Network timeout limit for HTTP requests | `10` |

---

## Running the Pipeline

1. Add your list of companies to search in `data/contacts.csv` following this header format:
   ```csv
   Name,Company,Website
   John Doe,Google,google.com
   Jane Smith,Microsoft,microsoft.com
   ```
2. Run the main script:
   ```bash
   python main.py
   ```
3. Check the output at `output/results.csv` and detailed logs in `logs/process.log`.

---

## Troubleshooting

- **Ollama Connection Refused**: Verify Ollama is running in the background. You can check this by visiting `http://localhost:11434` in your browser.
- **Model not found**: Ensure you ran `ollama pull gemma:4b` (or whichever model is configured in `.env`).
- **DDG Rate Limits / Blocking**: Increase `SEARCH_DELAY` in `.env` to make queries less frequent.
- **Missing Input File**: If `data/contacts.csv` is missing, running `main.py` once will automatically generate a sample template.
=======
# email-enrichment-system
A modular AI-powered email enrichment system built with Python, Ollama, and Gemma for extracting and validating business emails from public web content.
>>>>>>> 472ced9fa6a030a58f828a8b71394a7ae0cf4f35
