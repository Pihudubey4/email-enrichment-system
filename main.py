import time
import sys
from pathlib import Path
from typing import Dict, Any, List, Type
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import warnings
# Ironclad suppression of all console warnings to prevent terminal dashboard corruption
def _silence_warnings(*args, **kwargs):
    pass
warnings.showwarning = _silence_warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Add root folder to path to allow importing config & utilities
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from utils.logger import logger, log_process_event
from utils.tui import TerminalUI
from utils.storage import DataStorage, CSVStorage, ExcelStorage
from workers.search_worker import SearchWorker
from workers.gemma_worker import GemmaWorker
from workers.validation_worker import ValidationWorker

class PipelineOrchestrator:
    """
    Orchestrates the email enrichment pipeline by combining Search, AI, and Validation Workers.
    Utilizes dependency injection for modularity, ease of testing, and future upgrades (e.g. database, async).
    """
    def __init__(
        self, 
        storage: DataStorage,
        search_worker_cls: Type[SearchWorker] = SearchWorker,
        gemma_worker_cls: Type[GemmaWorker] = GemmaWorker,
        validation_worker_cls: Type[ValidationWorker] = ValidationWorker
    ) -> None:
        """
        Initializes the pipeline orchestrator.
        
        Args:
            storage (DataStorage): Storage interface implementation.
            search_worker_cls (Type[SearchWorker]): Search worker class.
            gemma_worker_cls (Type[GemmaWorker]): Gemma worker class.
            validation_worker_cls (Type[ValidationWorker]): Validation worker class.
        """
        self.storage = storage
        self.search_worker_cls = search_worker_cls
        self.gemma_worker_cls = gemma_worker_cls
        self.validation_worker_cls = validation_worker_cls

    def process_contact(self, contact: Dict[str, str]) -> Dict[str, Any]:
        """
        Enriches a single contact. Catches exceptions to ensure pipeline continuity.
        
        Args:
            contact (Dict[str, str]): Contact data with keys 'Name', 'Company', 'Website'.
            
        Returns:
            Dict[str, Any]: Enriched contact result dictionary.
        """
        name = contact.get("Name", "")
        company = contact.get("Company", "")
        website = contact.get("Website", "")
        
        start_time = time.time()
        
        # Initialize default result structure
        result: Dict[str, Any] = {
            "Name": name,
            "Company": company,
            "Website": website,
            "Email": "",
            "Confidence": 0.0,
            "Validation Status": "Unknown",
            "Processing Time": 0.0,
            "Reason": ""
        }
        if "index" in contact:
            result["index"] = contact["index"]
            
        error_occurred = None
        retries = 0
        
        try:
            # Instantiate workers (dependency injected)
            search_worker = self.search_worker_cls()
            gemma_worker = self.gemma_worker_cls()
            validation_worker = self.validation_worker_cls()

            # Step 1: Scrape target website / DDG search results
            logger.info(f"Starting search worker for: {company}")
            scraped_text = search_worker.run(company, website)
            
            # Step 2: Query Gemma via local Ollama API
            logger.info(f"Starting Gemma worker for: {company}")
            email, confidence, reason = gemma_worker.run(company, website, scraped_text)
            
            # Step 3: Validate the extracted email format and domain
            logger.info(f"Starting validation worker for: {email}")
            validation_report = validation_worker.run(email, website)
            
            # Populate result fields
            result["Email"] = email
            result["Confidence"] = confidence
            result["Validation Status"] = validation_report["status"]
            result["Reason"] = reason
            
        except Exception as e:
            error_occurred = str(e)
            logger.error(f"Error occurred while processing contact '{name}' ({company}): {e}", exc_info=True)
            result["Validation Status"] = "Unknown"
            result["Reason"] = f"Pipeline execution error: {error_occurred}"
            
        end_time = time.time()
        duration = end_time - start_time
        result["Processing Time"] = duration
        
        # Log structured metric entry
        log_process_event(
            start_time=start_time,
            end_time=end_time,
            worker="PipelineOrchestrator",
            company=company,
            duration=duration,
            errors=error_occurred,
            retry_attempts=retries
        )
        
        # Update TUI if enabled
        if getattr(self, "tui", None) is not None:
            self.tui.update(
                name=name,
                email=result["Email"],
                status=result["Validation Status"],
                error_msg=error_occurred
            )
            
        return result

    def run_pipeline(self) -> None:
        """
        Executes the enrichment pipeline over all loaded contacts in parallel 
        using a thread pool, displaying progress with tqdm.
        """
        try:
            contacts = self.storage.read_contacts()
        except Exception as e:
            logger.critical(f"Failed to read input contacts: {e}", exc_info=True)
            return

        if not contacts:
            logger.warning("No contacts found in input storage.")
            return

        # Check for completed contacts to support pipeline checkpointing/resuming
        try:
            completed_ids = self.storage.read_completed_identifiers()
            logger.info(f"Found {len(completed_ids)} already processed contacts in target destination.")
        except Exception as e:
            logger.warning(f"Could not load completed checkpoints: {e}. Starting fresh.")
            completed_ids = set()

        contacts_to_process = []
        for contact in contacts:
            ident = contact.get("index") if "index" in contact else contact.get("Name")
            if ident not in completed_ids:
                contacts_to_process.append(contact)

        # Apply ROW_LIMIT to unprocessed contacts only if configured for testing/debugging
        if getattr(config, "ROW_LIMIT", None) is not None:
            logger.info(f"Applying ROW_LIMIT: Slicing to first {config.ROW_LIMIT} unprocessed contacts.")
            contacts_to_process = contacts_to_process[:config.ROW_LIMIT]

        if not contacts_to_process:
            logger.info("All contacts are already processed. Pipeline is complete.")
            return

        logger.info(f"Loaded {len(contacts_to_process)} remaining contacts to process. "
                    f"Starting pipeline execution (workers={config.MAX_WORKERS})...")
        
        enriched_results: List[Dict[str, Any]] = []
        batch_counter = 0

        # Initialize TUI
        self.tui = TerminalUI(
            filename=config.INPUT_FILE.name,
            total_contacts=len(contacts_to_process),
            max_workers=config.MAX_WORKERS,
            total_missing_init=len(contacts_to_process)
        )

        # Process contacts concurrently with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            futures = {executor.submit(self.process_contact, contact): contact for contact in contacts_to_process}
            
            for future in as_completed(futures):
                contact = futures[future]
                try:
                    res = future.result()
                    enriched_results.append(res)
                    
                    # Incremental save every BATCH_SIZE results to limit memory usage and prevent loss
                    batch_counter += 1
                    if batch_counter >= config.BATCH_SIZE:
                        self.storage.write_results(enriched_results)
                        enriched_results.clear()
                        batch_counter = 0
                except Exception as exc:
                    logger.error(f"Worker thread exception for contact {contact.get('Name')}: {exc}", exc_info=True)

        # Save any remaining results
        if enriched_results:
            try:
                self.storage.write_results(enriched_results)
            except Exception as e:
                logger.critical(f"Failed to write final results: {e}", exc_info=True)
        else:
            logger.info("Pipeline finished. All batches completed.")

def main() -> None:
    logger.info("Initializing Local AI Email Enrichment System...")
    
    # 1. Resolve storage driver dynamically based on input format
    if config.INPUT_FILE.suffix in [".xlsx", ".xls"]:
        storage = ExcelStorage(config.INPUT_FILE, config.OUTPUT_FILE)
    else:
        storage = CSVStorage(config.INPUT_FILE, config.OUTPUT_FILE)

    # 2. Inject storage and worker dependencies into the pipeline
    orchestrator = PipelineOrchestrator(
        storage=storage,
        search_worker_cls=SearchWorker,
        gemma_worker_cls=GemmaWorker,
        validation_worker_cls=ValidationWorker
    )

    # 3. Run
    orchestrator.run_pipeline()

if __name__ == "__main__":
    main()
