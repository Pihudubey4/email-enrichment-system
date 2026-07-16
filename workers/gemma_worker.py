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

    def run(self, company: str, website: str, scraped_data: Dict[str, Any], tui: Any = None) -> Tuple[str, str, float, float, str, str]:
        """
        Queries local Ollama using the loaded prompt template.
        Expects a structured JSON response from Gemma.
        
        Args:
            company (str): Name of the target company or contact.
            website (str): Company website.
            scraped_data (Dict[str, Any]): Dictionary containing scraped text and fast path candidates.
            
        Returns:
            Tuple[str, str, float, float, str, str]: A tuple of (email, phone, email_confidence, phone_confidence, reason, source_url).
        """
        scraped_text = scraped_data.get("text", "")
        fast_email = scraped_data.get("fast_email", "")
        fast_phone = scraped_data.get("fast_phone", "")
        source_url = scraped_data.get("source_url", "")

        if not scraped_text.strip():
            logger.warning(f"Empty scraped text received for {company}. Skipping AI worker.")
            return fast_email, fast_phone, 0.5 if fast_email else 0.0, 0.5 if fast_phone else 0.0, "No source text available to analyze.", source_url

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
                    "Extract the most probable business email and phone number for {company} / {website}.\n"
                    "Return JSON: {{\"email\":\"\",\"phone\":\"\",\"email_confidence\":0.0,\"phone_confidence\":0.0,\"reason\":\"\"}}\n\n"
                    "Context:\n{context}"
                )
            prompt = template.format(company=company, website=website, context=scraped_text)

        payload = {
            "model": config.MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,  # Keep extraction deterministic
                "num_predict": 256,  # Force stop after 256 tokens (stops infinite loops)
                "num_ctx": 4096      # Keep context size optimized for speed
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
                        phone = str(data.get("phone", "")).strip()
                        email_confidence = float(data.get("email_confidence", data.get("confidence", 0.0)))
                        phone_confidence = float(data.get("phone_confidence", data.get("confidence", 0.0)))
                        reason = str(data.get("reason", "")).strip()

                        # If LLM failed to extract, use regex fallbacks
                        if not email and fast_email:
                            email = fast_email
                            email_confidence = 0.8
                            reason += " (Used regex fast-path email)"
                        if not phone and fast_phone:
                            phone = fast_phone
                            phone_confidence = 0.8
                            reason += " (Used regex fast-path phone)"

                        return email, phone, email_confidence, phone_confidence, reason, source_url
                    except (json.JSONDecodeError, TypeError, ValueError) as je:
                        logger.error(f"Failed to parse JSON response from Gemma: {response_text}. Error: {je}")
                        # Regular expression fallback parsing
                        email_match = re.search(r'"email"\s*:\s*"([^"]*)"', response_text)
                        phone_match = re.search(r'"phone"\s*:\s*"([^"]*)"', response_text)
                        email_conf_match = re.search(r'"email_confidence"\s*:\s*([0-9.]+)', response_text)
                        phone_conf_match = re.search(r'"phone_confidence"\s*:\s*([0-9.]+)', response_text)
                        
                        email = email_match.group(1) if email_match else fast_email
                        phone = phone_match.group(1) if phone_match else fast_phone
                        email_confidence = float(email_conf_match.group(1)) if email_conf_match else (0.8 if email else 0.0)
                        phone_confidence = float(phone_conf_match.group(1)) if phone_conf_match else (0.8 if phone else 0.0)
                        reason = "Regex fallback parsed."
                        return email, phone, email_confidence, phone_confidence, reason, source_url
                else:
                    logger.warning(f"Ollama returned non-200 code: {response.status_code}")
            except Exception as e:
                is_timeout = isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ReadTimeout))
                if is_timeout and tui is not None:
                    try:
                        tui.increment_metric("ollama_timeouts")
                    except Exception:
                        pass
                logger.error(f"Error querying Ollama API: {e}. Retries left: {retries - 1}")
                
            retries -= 1
            time.sleep(1.0)
            
        return fast_email, fast_phone, 0.7 if fast_email else 0.0, 0.7 if fast_phone else 0.0, "Ollama request failed. Used regex fast-path.", source_url
