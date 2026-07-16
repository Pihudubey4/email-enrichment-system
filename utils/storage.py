import csv
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Set
import pandas as pd

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
    Writes results back to an Excel spreadsheet.
    """
    PUBLIC_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com"}

    def __init__(self, input_path: Path, output_path: Path):
        self.input_path = input_path
        self.output_path = output_path
        self.original_df = None

    def read_contacts(self) -> List[Dict[str, str]]:
        if not self.input_path.exists():
            raise FileNotFoundError(f"Input Excel file not found: {self.input_path}")
        
        # Read only the columns we need for speed — avoids loading all 43 columns
        needed_cols = ["First name", "Middle name", "Last name", "Credential",
                       "Specialty name", "City", "State", "Email"]
        self.original_df = pd.read_excel(
            self.input_path, engine="openpyxl",
            usecols=lambda c: c in needed_cols
        )
        contacts = []

        for idx, row in self.original_df.iterrows():
            # Construct standard fields
            first = str(row.get("First name", "")).strip()
            last = str(row.get("Last name", "")).strip()
            cred = str(row.get("Credential", "")).strip()
            name = f"{first} {last}"
            if cred and cred != "nan":
                name += f", {cred}"

            specialty = str(row.get("Specialty name", "")).strip()
            city = str(row.get("City", "")).strip()
            state = str(row.get("State", "")).strip()
            
            # Construct a workplace description if specialty/location is available
            company = f"{name} ({specialty} practice in {city}, {state})"
            
            # Try to extract website domain from existing email if available
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

            contacts.append({
                "Name": name,
                "Company": company,
                "Website": website,
                "index": idx
            })
            
        return contacts

    def read_completed_identifiers(self) -> Set[Any]:
        completed = set()
        
        # 1. Check input file for existing emails (already in memory from read_contacts)
        if self.original_df is not None:
            try:
                email_col = self.original_df.get("Email") if hasattr(self.original_df, 'get') else self.original_df["Email"] if "Email" in self.original_df.columns else None
                if email_col is not None:
                    for idx, email in email_col.items():
                        e = str(email).strip().lower()
                        if e and e != "nan" and "@" in e:
                            completed.add(idx)
            except Exception as e:
                logger.error(f"Error checking input file for existing emails: {e}")

        # 2. Check output file — only read the 'Email verification' column for speed
        if not self.output_path.exists():
            return completed
        try:
            df = pd.read_excel(
                self.output_path, engine="openpyxl",
                usecols=["Email verification"]
            )
            for idx, row in df.iterrows():
                status = str(row.get("Email verification", "")).strip()
                if status and status != "nan" and status != "":
                    completed.add(idx)
        except Exception:
            pass
        return completed

    def write_results(self, results: List[Dict[str, Any]]) -> None:
        # Lazy load: if we only have the slim dataframe from startup, reload the full one now
        has_full_df = (self.original_df is not None and
                       len(self.original_df.columns) > 8)

        # Load or reload the dataframe from output or input (full columns needed for writing)
        if self.output_path.exists():
            try:
                self.original_df = pd.read_excel(self.output_path)
            except Exception as e:
                logger.error(f"Error reading output Excel file {self.output_path}: {e}. Falling back to input file.")
                try:
                    self.output_path.unlink(missing_ok=True)
                except Exception:
                    pass
                self.original_df = pd.read_excel(self.input_path)
        elif not has_full_df:
            self.original_df = pd.read_excel(self.input_path)

        result_map = {r["index"]: r for r in results if "index" in r}

        # Update matching indices
        for idx in self.original_df.index:
            if idx in result_map:
                res = result_map[idx]
                if res.get("Email"):
                    self.original_df.at[idx, "Email"] = res["Email"]
                if res.get("Confidence"):
                    self.original_df.at[idx, "Email confidence"] = int(res["Confidence"] * 100)
                if res.get("Validation Status"):
                    self.original_df.at[idx, "Email verification"] = res["Validation Status"].lower()
                self.original_df.at[idx, "Updated"] = pd.Timestamp.now().isoformat()

        # Save to output path
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.original_df.to_excel(self.output_path, index=False)
