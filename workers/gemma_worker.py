import sys
import json
import requests
import re
import time
import threading
from pathlib import Path
from typing import Dict, Any, Tuple

# Add root folder to path to allow importing config & utilities
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from utils.logger import logger

class GemmaWorker:
    """
    Gemma Worker interfaces with the local Ollama instance to extract contact emails.
    Utilizes configurable models and temperature parameters.
    """
    # Lock to prevent overloading local Ollama with concurrent requests
    _ollama_lock = threading.Lock()
    def __init__(self) -> None:
        self.endpoint = f"{config.OLLAMA_URL.rstrip('/')}/api/generate"
        self.prompt_template_path = config.PROMPTS_DIR / "email_extraction.txt"

    def run(self, company: str, website: str, scraped_text: str) -> Tuple[str, float, str]:
        """
        Queries local Ollama using the loaded prompt template.
        Expects a structured JSON response from Gemma.
        
        Args:
            company (str): Name of the target company or contact.
            website (str): Company website.
            scraped_text (str): Extracted web content text.
            
        Returns:
            Tuple[str, float, str]: A tuple of (email, confidence, reason).
        """
        if not scraped_text.strip():
            logger.warning(f"Empty scraped text received for {company}. Skipping AI worker.")
            return "", 0.0, "No source text available to analyze."

        # Fast path: if regex already extracted an email in the search worker, skip Ollama entirely
        if scraped_text.startswith("FAST_EMAIL_FOUND:"):
            first_line = scraped_text.split("\n")[0]
            email = first_line.replace("FAST_EMAIL_FOUND:", "").strip()
            if email and "@" in email:
                logger.info(f"Fast-path bypass for {company}: using pre-extracted email {email}")
                return email, 0.85, "Directly extracted via regex from scraped page."

        # Build prompt using the unified prompt builder function
        try:
            from prompts.prompt_builder import get_email_extraction_prompt
            prompt = get_email_extraction_prompt(name=company, company=company, website=website, context=scraped_text)
        except ImportError:
            # Fallback to file template if imports fail
            if self.prompt_template_path.exists():
                with open(self.prompt_template_path, "r", encoding="utf-8") as f:
                    template = f.read()
            else:
                template = (
                    "Extract the most probable business email for {company} / {website}.\n"
                    "Return JSON: {{\"email\":\"\",\"confidence\":0.0,\"reason\":\"\"}}\n\n"
                    "Context:\n{context}"
                )
            prompt = template.format(company=company, website=website, context=scraped_text)

        payload = {
            "model": config.MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0  # Keep extraction deterministic
            },
            "format": "json"  # Instruct Ollama to output valid JSON
        }

        retries = config.RETRY_COUNT
        while retries > 0:
            try:
                logger.info(f"Sending prompt to Ollama ({config.MODEL_NAME}) for {company}")
                with self._ollama_lock:
                    response = requests.post(
                        self.endpoint,
                        json=payload,
                        timeout=config.HTTP_TIMEOUT
                    )
                
                if response.status_code == 200:
                    result = response.json()
                    response_text = result.get("response", "").strip()
                    logger.debug(f"Ollama raw response: {response_text}")
                    
                    # Parse JSON safely
                    try:
                        data = json.loads(response_text)
                        email = str(data.get("email", "")).strip()
                        confidence = float(data.get("confidence", 0.0))
                        reason = str(data.get("reason", "")).strip()
                        return email, confidence, reason
                    except (json.JSONDecodeError, TypeError, ValueError) as je:
                        logger.error(f"Failed to parse JSON response from Gemma: {response_text}. Error: {je}")
                        # Regular expression fallback parsing
                        email_match = re.search(r'"email"\s*:\s*"([^"]*)"', response_text)
                        conf_match = re.search(r'"confidence"\s*:\s*([0-9.]+)', response_text)
                        reason_match = re.search(r'"reason"\s*:\s*"([^"]*)"', response_text)
                        
                        email = email_match.group(1) if email_match else ""
                        confidence = float(conf_match.group(1)) if conf_match else 0.0
                        reason = reason_match.group(1) if reason_match else "Regex fallback parsed."
                        return email, confidence, reason
                else:
                    logger.warning(f"Ollama returned non-200 code: {response.status_code}")
            except Exception as e:
                logger.error(f"Error querying Ollama API: {e}. Retries left: {retries - 1}")
                
            retries -= 1
            time.sleep(1.0)
            
        return "", 0.0, "Ollama request failed after retries."
