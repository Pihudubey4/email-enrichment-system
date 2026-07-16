import csv
import re
import queue
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Set
import pandas as pd
from utils.logger import logger

class DataStorage(ABC):
    """
    Abstract Base Class defining the interface for reading contacts and
    saving enriched email results. Easily subclassed for SQLite/PostgreSQL/MongoDB.
    """
    @abstractmethod
    def read_contacts(self) -> List[Dict[str, str]]:
        """Reads and returns contact list containing Name, Company, Website."""
        pass

    @abstractmethod
    def write_results(self, results: List[Dict[str, Any]]) -> None:
        """Writes enriched contact list back to storage."""
        pass

    @abstractmethod
    def read_completed_identifiers(self) -> Set[Any]:
        """Returns a set of identifiers representing already processed contacts."""
        pass

    @abstractmethod
    def join_writer(self) -> None:
        """Blocks until all queued writes are completed."""
        pass


class CSVStorage(DataStorage):
    """
    CSV Implementation of storage interface.
    Reads data/contacts.csv and writes output/results.csv.
    """
    def __init__(self, input_path: Path, output_path: Path):
        self.input_path = input_path
        self.output_path = output_path

    def read_contacts(self) -> List[Dict[str, str]]:
        if not self.input_path.exists():
            # Create a sample template if not present
            self.input_path.parent.mkdir(parents=True, exist_ok=True)
            self._create_sample_template()

        contacts = []
        with open(self.input_path, mode="r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                contacts.append({
                    "Name": row.get("Name", "").strip(),
                    "Company": row.get("Company", "").strip(),
                    "Website": row.get("Website", "").strip()
                })
        return contacts

    def read_completed_identifiers(self) -> Set[Any]:
        completed = set()
        # 1. Check input file for existing emails
        if self.input_path.exists():
            try:
                with open(self.input_path, mode="r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = row.get("Name", "").strip()
                        email = row.get("Email", "").strip()
                        if name and email and "@" in email:
                            completed.add(name)
            except Exception:
                pass

        # 2. Check output file for completed results
        if not self.output_path.exists():
            return completed
        try:
            with open(self.output_path, mode="r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get("Name", "").strip()
                    if name:
                        completed.add(name)
        except Exception:
            pass
        return completed

    def write_results(self, results: List[Dict[str, Any]]) -> None:
        if not results:
            return
        
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load any existing completed records so we don't overwrite them
        existing_results = {}
        if self.output_path.exists():
            try:
                with open(self.output_path, mode="r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = row.get("Name", "")
                        if name:
                            existing_results[name] = row
            except Exception:
                pass

        # Update existing with new results
        for r in results:
            name = r.get("Name", "")
            if name:
                existing_results[name] = {
                    "Name": r.get("Name", ""),
                    "Company": r.get("Company", ""),
                    "Website": r.get("Website", ""),
                    "Email": r.get("Email", ""),
                    "Confidence": r.get("Confidence", 0.0),
                    "Validation Status": r.get("Validation Status", "Unknown"),
                    "Processing Time": f"{r.get('Processing Time', 0.0):.2f}s"
                }

        headers = [
            "Name", "Company", "Website", "Email", 
            "Confidence", "Validation Status", "Processing Time"
        ]
        
        with open(self.output_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for r in existing_results.values():
                writer.writerow(r)

    def join_writer(self) -> None:
        """Blocks until all queued writes are completed. No-op for CSV."""
        pass

    def _create_sample_template(self) -> None:
        headers = ["Name", "Company", "Website"]
        with open(self.input_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerow(["John Doe", "Google", "https://www.google.com"])
            writer.writerow(["Jane Smith", "Microsoft", "https://www.microsoft.com"])
            writer.writerow(["Alice Johnson", "OpenAI", "https://openai.com"])


class ExcelStorage(DataStorage):
    """
    Excel Implementation of storage interface for processing contacts_export.xlsx.
    Maps NPI, Name, Address, Specialty to virtual Name, Company, Website.
    Writes results back to an Excel spreadsheet in-place preserving other sheets.
    """
    PUBLIC_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com"}

    def __init__(self, input_path: Path, output_path: Path):
        self.input_path = input_path
        self.output_path = output_path
        self.original_df = None
        self.all_sheets = {}
        self._write_queue = queue.Queue()
        self._writer_thread = None
        self._writer_lock = threading.Lock()

    def read_contacts(self) -> List[Dict[str, str]]:
        if not self.input_path.exists():
            raise FileNotFoundError(f"Input Excel file not found: {self.input_path}")
        
        # Load all sheets to preserve them when writing back later
        try:
            xl = pd.ExcelFile(self.input_path)
            self.all_sheets = {name: xl.parse(name) for name in xl.sheet_names}
        except Exception as e:
            logger.error(f"Error loading sheets from Excel file: {e}")
            self.all_sheets = {}

        if "Investor Contacts" in self.all_sheets:
            self.original_df = self.all_sheets["Investor Contacts"]
        else:
            self.original_df = pd.read_excel(
                self.input_path, sheet_name="Investor Contacts", engine="openpyxl"
            )
            self.all_sheets["Investor Contacts"] = self.original_df

        contacts = []
        for idx, row in self.original_df.iterrows():
            # Construct standard fields
            first = str(row.get("First name", "")).strip()
            if first == "nan" or first == ".": first = ""
            last = str(row.get("Last name", "")).strip()
            if last == "nan" or last == ".": last = ""
            cred = str(row.get("Credential", "")).strip()
            if cred == "nan": cred = ""
            
            # Clean name of any surrounding punctuation
            name = f"{first} {last}".strip()
            name = re.sub(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9)]+$", "", name).strip()
            if cred:
                name += f", {cred}"

            specialty = str(row.get("Specialty name", "")).strip()
            if specialty == "nan": specialty = ""
            city = str(row.get("City", "")).strip()
            if city == "nan": city = ""
            state = str(row.get("State", "")).strip()
            if state == "nan": state = ""
            
            # Construct a workplace description if specialty/location is available
            company = f"{name} ({specialty} practice in {city}, {state})"
            
            # Try to extract website domain from existing website column first, then email if available
            website = str(row.get("Source Website", "")).strip()
            if not website or website == "nan":
                website = ""
                email = str(row.get("Email", "")).strip()
                if email and "@" in email and email != "nan":
                    try:
                        _, domain = email.split("@", 1)
                        if domain.lower() not in self.PUBLIC_DOMAINS:
                            if domain.lower().startswith("direct."):
                                domain = domain[7:]
                            website = f"https://www.{domain}"
                    except ValueError:
                        pass

            # Read existing Email and Phone to support fast-path validation
            existing_email = str(row.get("Email", "")).strip()
            if existing_email == "nan": existing_email = ""
            existing_phone = str(row.get("Phone", "")).strip()
            if existing_phone == "nan": existing_phone = ""

            contacts.append({
                "Name": name,
                "Company": company,
                "Website": website,
                "Email": existing_email,
                "Phone": existing_phone,
                "index": idx
            })
            
        return contacts

    def read_completed_identifiers(self) -> Set[Any]:
        completed = set()
        
        # Check input file for existing email verification status
        if self.input_path.exists():
            try:
                # We read the specific sheet to check where Email verification is already filled
                df = pd.read_excel(
                    self.input_path, sheet_name="Investor Contacts", engine="openpyxl",
                    usecols=["Email verification"]
                )
                for idx, row in df.iterrows():
                    status = str(row.get("Email verification", "")).strip()
                    if status and status != "nan" and status != "":
                        completed.add(idx)
            except Exception as e:
                logger.error(f"Error checking input file for completed contacts: {e}")
        return completed

    def _start_writer_thread(self) -> None:
        with self._writer_lock:
            if self._writer_thread is None or not self._writer_thread.is_alive():
                self._writer_thread = threading.Thread(target=self._bg_writer_worker, daemon=True)
                self._writer_thread.start()

    def _bg_writer_worker(self) -> None:
        while True:
            try:
                item = self._write_queue.get(timeout=10)
                if item is None:
                    self._write_queue.task_done()
                    break
                
                self._write_to_disk()
                self._write_queue.task_done()
            except queue.Empty:
                with self._writer_lock:
                    self._writer_thread = None
                break
            except Exception as e:
                logger.error(f"Error in background writer thread: {e}", exc_info=True)
                self._write_queue.task_done()

    def _write_to_disk(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.all_sheets["Investor Contacts"] = self.original_df
        with pd.ExcelWriter(self.output_path, engine="openpyxl") as writer:
            for sheet_name, df in self.all_sheets.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        logger.info(f"Successfully saved updated Excel file to {self.output_path}")

    def write_results(self, results: List[Dict[str, Any]]) -> None:
        if self.original_df is None:
            self.read_contacts()

        result_map = {r["index"]: r for r in results if "index" in r}

        # Cast target columns to object dtype to avoid dtype errors (e.g. LossySetitemError) on newer pandas versions
        target_cols = [
            "Email", "Email confidence", "Email verification", "Email verification confidence",
            "Email verified at", "Phone", "Phone verification", "Phone verification confidence",
            "Phone verified at", "Source Website", "Updated"
        ]
        for col in target_cols:
            if col in self.original_df.columns:
                self.original_df[col] = self.original_df[col].astype(object)

        # Update matching indices
        for idx in self.original_df.index:
            if idx in result_map:
                res = result_map[idx]
                
                # Write Email fields
                if res.get("Email"):
                    self.original_df.at[idx, "Email"] = res["Email"]
                if res.get("Confidence") is not None:
                    confidence_pct = int(res["Confidence"] * 100)
                    self.original_df.at[idx, "Email confidence"] = confidence_pct
                    self.original_df.at[idx, "Email verification confidence"] = confidence_pct
                if res.get("Validation Status"):
                    self.original_df.at[idx, "Email verification"] = res["Validation Status"].lower()
                    self.original_df.at[idx, "Email verified at"] = pd.Timestamp.now().isoformat()
                
                # Write Phone fields
                if res.get("Phone"):
                    self.original_df.at[idx, "Phone"] = res["Phone"]
                    self.original_df.at[idx, "Phone verification"] = "valid"
                    phone_conf = int(res.get("Phone Confidence", 1.0) * 100)
                    self.original_df.at[idx, "Phone verification confidence"] = phone_conf
                    self.original_df.at[idx, "Phone verified at"] = pd.Timestamp.now().isoformat()
                else:
                    self.original_df.at[idx, "Phone verification"] = "not_found"
                    self.original_df.at[idx, "Phone verification confidence"] = 0
                    self.original_df.at[idx, "Phone verified at"] = pd.Timestamp.now().isoformat()

                # Write Source Website
                if res.get("Source Website"):
                    self.original_df.at[idx, "Source Website"] = res["Source Website"]
                elif res.get("Website"):
                    self.original_df.at[idx, "Source Website"] = res["Website"]
                
                self.original_df.at[idx, "Updated"] = pd.Timestamp.now().isoformat()

        # Queue write request
        self._write_queue.put(True)
        self._start_writer_thread()

    def join_writer(self) -> None:
        logger.info("Stopping background writer thread and finishing file saves...")
        self._write_queue.put(None)
        with self._writer_lock:
            if self._writer_thread is not None and self._writer_thread.is_alive():
                self._writer_thread.join()
        logger.info("Background writer thread stopped. Excel files saved.")
