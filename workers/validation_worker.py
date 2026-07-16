import sys
import re
import socket
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, Any, Optional, Tuple

# Add root folder to path to allow importing config & utilities
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from utils.logger import logger

class ValidationWorker:
    """
    Validation Worker validates extracted emails using regex, domain checks, 
    disposable domain lists, and domain resolution.
    """
    # Standard email regex pattern
    EMAIL_REGEX = re.compile(
        r'^(?![_.-])((?![_.-][_.-])[a-zA-Z0-9._+-]){1,64}'
        r'@'
        r'[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,24}$'
    )
    
    # Common disposable email provider domains to reject
    DISPOSABLE_DOMAINS = {
        "mailinator.com", "yopmail.com", "tempmail.com", "10minutemail.com",
        "trashmail.com", "guerrillamail.com", "sharklasers.com", "dispostable.com",
        "getairmail.com", "maildrop.cc", "mintemail.com"
    }

    # Directory / Aggregator / Portal domains to skip for domain validation check
    DIRECTORY_DOMAINS = {
        "zoominfo.com", "rocketreach.co", "linkedin.com", "npidb.org",
        "npiprofile.com", "doximity.com", "healthgrades.com", "vitals.com",
        "npino.com", "npi-lookup.org", "nationalprovider.org", "npinumberlookup.org",
        "cms.gov", "medicare.gov", "data.cms.gov", "sec.gov", "bloomberg.com",
        "bbb.org", "npi.gov", "health.ny.gov", "ncbi.nlm.nih.gov", "healthcare.gov",
        "nppes.cms.hhs.gov", "opencorporates.com", "crunchbase.com", "preqin.com",
        "adviserinfo.sec.gov", "wikipedia.org", "facebook.com", "twitter.com",
        "instagram.com", "youtube.com", "yelp.com", "tripadvisor.com"
    }

    def run(self, email: str, website: str, enforce_domain_match: bool = True) -> Dict[str, Any]:
        """
        Validates the email and returns a structured validation report.
        
        Args:
            email (str): Email address to validate.
            website (str): Target website for domain matching check.
            
        Returns:
            Dict[str, Any]: {
                "email": str,
                "status": "Valid" | "Invalid" | "Unknown",
                "reason": str,
                "domain": str
            }
        """
        email = (email or "").strip().lower()
        result = {
            "email": email,
            "status": "Unknown",
            "reason": "",
            "domain": ""
        }

        # 1. Check if email is empty
        if not email:
            result["status"] = "Unknown"
            result["reason"] = "No email address extracted."
            return result

        # 2. Regex and format validation
        if not self.EMAIL_REGEX.match(email):
            logger.info(f"Email '{email}' failed format/regex check.")
            result["status"] = "Invalid"
            result["reason"] = "Malformed email format."
            return result

        # 3. Domain extraction
        try:
            _, email_domain = email.split('@', 1)
            result["domain"] = email_domain
        except ValueError:
            result["status"] = "Invalid"
            result["reason"] = "Could not extract domain."
            return result

        # 4. Reject disposable domains
        if email_domain in self.DISPOSABLE_DOMAINS:
            logger.info(f"Email '{email}' uses a disposable domain: {email_domain}")
            result["status"] = "Invalid"
            result["reason"] = "Disposable email domain."
            return result

        # 5. Check domain existence/resolution
        if not self._check_domain_exists(email_domain):
            logger.info(f"Email domain '{email_domain}' does not resolve.")
            result["status"] = "Invalid"
            result["reason"] = "Domain does not exist or has no DNS records."
            return result

        # 6. Perform optional MX record lookup
        mx_valid, mx_reason = self._check_mx_records(email_domain)
        if not mx_valid:
            result["status"] = "Unknown"
            result["reason"] = f"MX records check inconclusive: {mx_reason}"
            return result

        # 7. Compare with target website domain if provided (if website is not a directory portal)
        if website:
            web_domain = self._extract_domain(website)
            if web_domain:
                # If target website is a known directory/aggregator domain or a .gov site, do not enforce matching.
                is_directory = web_domain.endswith(".gov") or any(d in web_domain or web_domain.endswith(f".{d}") for d in self.DIRECTORY_DOMAINS)
                if is_directory or not enforce_domain_match:
                    result["status"] = "Valid"
                    result["reason"] = f"Valid format and domain resolves successfully ({email_domain})."
                    return result
                
                if email_domain == web_domain or email_domain.endswith(f".{web_domain}"):
                    result["status"] = "Valid"
                    result["reason"] = "Email format is valid and domain matches target website."
                    return result
                else:
                    logger.info(f"Email domain '{email_domain}' does not match website '{web_domain}'.")
                    # It might still be a valid business email but not directly matching website
                    result["status"] = "Unknown"
                    result["reason"] = f"Valid format, but domain does not match website ({web_domain})."
                    return result

        result["status"] = "Valid"
        result["reason"] = "Valid format and domain resolves successfully."
        return result

    def _check_domain_exists(self, domain: str) -> bool:
        """Checks if a domain resolved to an IP address (A/AAAA records check)."""
        try:
            socket.gethostbyname(domain)
            return True
        except socket.gaierror:
            return False

    def _check_mx_records(self, domain: str) -> Tuple[bool, str]:
        """
        Optionally verifies MX records using dnspython if installed.
        Falls back to socket lookup if dnspython is unavailable.
        """
        try:
            import dns.resolver
            try:
                answers = dns.resolver.resolve(domain, 'MX')
                if answers:
                    return True, "MX records found."
            except Exception as e:
                logger.debug(f"MX lookup failed for {domain} using dns.resolver: {e}")
                # Fallback to checking A record (most SMTP servers accept A records if MX is missing)
                return True, "No MX records, falling back to A record."
        except ImportError:
            # dnspython not installed, fallback to standard socket name resolution
            return True, "dnspython not installed, resolved domain via socket."

        return False, "Failed to resolve MX records."

    def _extract_domain(self, url: str) -> str:
        """Helper to extract domain name from various URL formats."""
        url = url.strip().lower()
        if not url.startswith("http"):
            url = "http://" + url
            
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc
            if ":" in netloc:
                netloc = netloc.split(":")[0]
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return netloc
        except Exception:
            return ""
