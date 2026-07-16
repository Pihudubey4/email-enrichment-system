import warnings
def _silence_warnings(*args, **kwargs):
    pass
warnings.showwarning = _silence_warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import time
import sys
import re
import threading
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from typing import List, Dict, Any, Optional, Tuple

# Suppress SSL verification warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add root folder to path to allow importing config & utilities
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from utils.logger import logger

class SearchWorker:
    """
    Search Worker responsible for querying search engines and scraping targeted web pages.
    Extracts plain text content and associated metadata from search results.
    Designed for synchronous flow but easily adaptable to async (e.g. HTTPX or aiohttp).
    """
    # Thread-safe class level search results cache
    _cache: Dict[str, Dict[str, Any]] = {}
    _lock = threading.Lock()
    # Lock to prevent concurrent search hits to DuckDuckGo/Bing
    _search_lock = threading.Lock()

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

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/115.0.0.0 Safari/537.36"
            )
        })

    # Common fake/generic emails to reject
    _FAKE_EMAIL_PATTERN = re.compile(
        r'(example|noreply|no-reply|support|webmaster|admin|info@example|test@|user@|email@|\bname@)',
        re.IGNORECASE
    )
    # Email regex for extraction
    _EMAIL_RE = re.compile(
        r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
    )
    # Phone regex for extraction
    _PHONE_RE = re.compile(
        r'\(?[2-9][0-9]{2}\)?[-. ]?[0-9]{3}[-. ]?[0-9]{4}'
    )
    # Trusted medical TLDs / domains that indicate professional email
    _MEDICAL_KEYWORDS = [
        '.edu', '.org', '.gov', 'health', 'medical', 'clinic', 'hospital',
        'care', 'practice', 'physician', 'doctor', 'therapy', 'dental',
        'ortho', 'psych', 'neuro', 'cardio', 'peds', 'surg', 'md.', '.md'
    ]

    def run(self, company: str, website: str, tui: Any = None) -> Dict[str, Any]:
        """
        Main entrypoint matching orchestrator requirements.
        Performs queries, scrapes pages, and aggregates everything into a single text block.
        Extracts candidate emails and phone numbers via regex.
        Returns a dictionary of scraped data.
        """
        cache_key = f"{company.strip().lower()}|{website.strip().lower()}"
        
        with self._lock:
            if cache_key in self._cache:
                logger.info(f"Cache hit for search data: {company} / {website}")
                return self._cache[cache_key]

        scraped_pages = self.search_and_scrape(company, website, tui)
        if not scraped_pages:
            return {"text": "", "fast_email": "", "fast_phone": "", "source_url": ""}
        
        # Extract candidate emails and phones
        all_emails_found = []
        all_phones_found = []
        for page in scraped_pages:
            text = page.get('text', '')
            url = page.get('url', '')
            
            if text.startswith('Explicit Mailto Links Found:'):
                first_line = text.split('\n')[0]
                for email in self._EMAIL_RE.findall(first_line):
                    if not self._FAKE_EMAIL_PATTERN.search(email):
                        all_emails_found.append((email, 'mailto', url))
            for email in self._EMAIL_RE.findall(text):
                if not self._FAKE_EMAIL_PATTERN.search(email):
                    all_emails_found.append((email, 'text', url))
            
            for phone in self._PHONE_RE.findall(text):
                all_phones_found.append((phone.strip(), url))
        
        # Pick the best email
        best_email = ""
        best_email_source = ""
        if all_emails_found:
            mailto_hits = [e for e in all_emails_found if e[1] == 'mailto']
            if mailto_hits:
                best_email = mailto_hits[0][0]
                best_email_source = mailto_hits[0][2]
            else:
                medical_hits = [e for e in all_emails_found if any(kw in e[0].lower() for kw in self._MEDICAL_KEYWORDS)]
                if medical_hits:
                    best_email = medical_hits[0][0]
                    best_email_source = medical_hits[0][2]
                else:
                    best_email = all_emails_found[0][0]
                    best_email_source = all_emails_found[0][2]

        # Pick the best phone
        best_phone = ""
        best_phone_source = ""
        if all_phones_found:
            best_phone = all_phones_found[0][0]
            best_phone_source = all_phones_found[0][1]

        result_text = self._build_context(scraped_pages)
        source_url = best_email_source or best_phone_source or (scraped_pages[0]['url'] if scraped_pages else "")
        
        res = {
            "text": result_text,
            "fast_email": best_email,
            "fast_phone": best_phone,
            "source_url": source_url
        }

        with self._lock:
            self._cache[cache_key] = res

        return res

    def _build_context(self, scraped_pages: List[Dict[str, str]]) -> str:
        """Combine scraped pages into a single context string for Gemma."""
        combined = []
        for page in scraped_pages:
            combined.append(
                f"Source URL: {page['url']}\n"
                f"Page Title: {page['title']}\n"
                f"Content:\n{page['text']}"
            )
        return "\n\n=== NEW PAGE ===\n\n".join(combined)

    def search_and_scrape(self, company: str, website: str, tui: Any = None) -> List[Dict[str, str]]:
        """
        Executes DuckDuckGo queries for the company, extracts candidate URLs, 
        scrapes the target pages, and extracts clean text and metadata.
        
        Args:
            company (str): Target company name.
            website (str): Target company website.
            
        Returns:
            List[Dict[str, str]]: A list of dictionaries containing keys:
                                  'url', 'title', 'query', 'text'.
        """
        # Extract name from the combined company description if present
        name = company
        location_specialty = ""
        if " (" in company:
            name, rest = company.split(" (", 1)
            location_specialty = rest.rstrip(")")
            
        urls_to_scrape: Dict[str, str] = {}  # URL -> query used
        
        # Check if website is a directory/portal domain
        is_directory = False
        if website:
            web_domain = ""
            try:
                from urllib.parse import urlparse
                parsed = urlparse(website if website.startswith("http") else f"http://{website}")
                web_domain = parsed.netloc.lower()
                if web_domain.startswith("www."):
                    web_domain = web_domain[4:]
            except Exception:
                pass
            if web_domain:
                is_directory = any(d in web_domain or web_domain.endswith(f".{d}") for d in self.DIRECTORY_DOMAINS)

        # 1. Add primary website directly (query labeled as 'direct') if it's not a directory
        if website and not is_directory:
            if not website.startswith("http"):
                website = "https://" + website
            urls_to_scrape[website] = "direct_input"

        # 2. Define the search queries targeting name and keywords
        name_clean = name.strip()
        name_clean = re.sub(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9)]+$", "", name_clean).strip()
        if "," in name_clean:
            name_clean = name_clean.split(",", 1)[0].strip()

        city = ""
        state = ""
        if location_specialty:
            match = re.search(r"practice in\s+([^,]+),\s*([A-Z]{2})", location_specialty, re.IGNORECASE)
            if match:
                city = match.group(1).strip()
                state = match.group(2).strip()

        if city and state:
            primary_query = f'"{name_clean}" {city} {state} email'
        else:
            primary_query = f'"{name_clean}" email'

        # 3. Query DuckDuckGo for candidate links (only 1 primary query first)
        logger.info(f"Querying DuckDuckGo: '{primary_query}'")
        if tui is not None:
            try:
                tui.increment_metric("ddg_queries")
            except Exception:
                pass
        candidate_links = self._search_query_with_retry(primary_query)
        
        skipped_domains = list(self.DIRECTORY_DOMAINS) + [
            "doubleclick.net", "baidu.com", "wikimedia.org", "wikidata.org",
            "stackexchange.com", "stackoverflow.com", "github.com",
            "microsoft.com", "answers.microsoft.com", "support.microsoft.com",
            "apple.com", "docs.google.com", "mozilla.org",
            "bbc.com", "cnn.com", "nytimes.com", "theguardian.com",
            "reuters.com", "apnews.com", "nbcnews.com", "foxnews.com",
            "usatoday.com", "washingtonpost.com",
            "forbes.com", "businessinsider.com", "huffpost.com",
            "imdb.com", "netflix.com", "hulu.com", "disneyplus.com",
            "spotify.com", "gaana.com", "pandora.com", "soundcloud.com",
            "m.imdb.com", "amazon.com", "ebay.com",
            "acmilan.com", "espn.com", "nfl.com", "nba.com", "fifa.com",
            "dominos.com", "ubereats.com", "grubhub.com", "doordash.com",
            "fciqms.in", "aucklandpethospital.co.nz", "semanticscholar.org",
            "researchgate.net", "elevenforum.com", "dorothyonfire.com"
        ]

        for link in candidate_links:
            link_lower = link.lower()
            if any(domain in link_lower for domain in skipped_domains):
                continue
            if link not in urls_to_scrape:
                urls_to_scrape[link] = primary_query
        time.sleep(config.SEARCH_DELAY)

        # 3b. Fallback query if no links found and we used location-specific query
        if not urls_to_scrape and city and state:
            fallback_query = f'"{name_clean}" email'
            logger.info(f"Primary query yielded no links. Trying fallback query: '{fallback_query}'")
            if tui is not None:
                try:
                    tui.increment_metric("ddg_queries")
                except Exception:
                    pass
            candidate_links = self._search_query_with_retry(fallback_query)
            for link in candidate_links:
                link_lower = link.lower()
                if any(domain in link_lower for domain in skipped_domains):
                    continue
                if link not in urls_to_scrape:
                    urls_to_scrape[link] = fallback_query
            time.sleep(config.SEARCH_DELAY)

        # 4. Scrape the accumulated links (limit to top 3 pages for speed)
        scraped_results: List[Dict[str, str]] = []
        target_links = list(urls_to_scrape.keys())[:3]
        
        for url in target_links:
            query_used = urls_to_scrape[url]
            logger.info(f"Scraping URL: {url} (found via query: '{query_used}')")
            
            scraped_content = self._scrape_url_with_retry(url)
            if scraped_content:
                title, clean_text = scraped_content
                scraped_results.append({
                    "url": url,
                    "title": title,
                    "query": query_used,
                    "text": clean_text
                })
            time.sleep(config.SEARCH_DELAY)

        return scraped_results

    def _search_query_with_retry(self, query: str) -> List[str]:
        """Runs a DDG search query with retry and error handling (serialized)."""
        retries = config.RETRY_COUNT
        links: List[str] = []
        
        with self._search_lock:
            # Stagger searches to prevent IP rate-limiting blocks
            time.sleep(0.5)
            while retries > 0:
                try:
                    with DDGS() as ddgs:
                        # Retrieve top 3 search results for the query
                        results = ddgs.text(query, max_results=3)
                        for r in results:
                            href = r.get("href")
                            if href:
                                links.append(href)
                    break
                except Exception as e:
                    retries -= 1
                    logger.error(f"DuckDuckGo search error for query '{query}': {e}. Retries left: {retries}")
                    time.sleep(config.SEARCH_DELAY)
        return links

    def _scrape_url_with_retry(self, url: str) -> Optional[Tuple[str, str]]:
        """Downloads a URL with retry logic, returning (title, clean_text)."""
        retries = config.RETRY_COUNT
        while retries > 0:
            try:
                response = self.session.get(url, timeout=15, verify=False)
                if response.status_code == 200:
                    return self._parse_html(response.text)
                else:
                    logger.warning(f"Failed to scrape {url}. HTTP Status: {response.status_code}")
                    return None
            except Exception as e:
                retries -= 1
                logger.error(f"Network error scraping URL {url}: {e}. Retries left: {retries}")
                time.sleep(config.SEARCH_DELAY)
        return None

    def _parse_html(self, html_content: str) -> Tuple[str, str]:
        """Parses HTML content, extracting title, mailto addresses, and clean text."""
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Extract title
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            
        # Extract and parse explicit mailto: link targets
        mailto_emails = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith("mailto:"):
                email = href[7:].split("?")[0].strip()
                if email:
                    mailto_emails.append(email)
            
        # Decompose styling & script elements (keep header and footer which contain critical email data)
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
            
        # Extract plain text
        text = soup.get_text(separator=" ")
        
        # Clean lines and spacing
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = "\n".join(chunk for chunk in chunks if chunk)
        
        # Prepend explicit mailto links to clean text for LLM visibility
        if mailto_emails:
            clean_text = "Explicit Mailto Links Found: " + ", ".join(set(mailto_emails)) + "\n\n" + clean_text
            
        return title, clean_text[:4000]
