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
    _cache: Dict[str, str] = {}
    _lock = threading.Lock()
    # Lock to prevent concurrent search hits to DuckDuckGo/Bing
    _search_lock = threading.Lock()

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
    # Trusted medical TLDs / domains that indicate professional email
    _MEDICAL_KEYWORDS = [
        '.edu', '.org', '.gov', 'health', 'medical', 'clinic', 'hospital',
        'care', 'practice', 'physician', 'doctor', 'therapy', 'dental',
        'ortho', 'psych', 'neuro', 'cardio', 'peds', 'surg', 'md.', '.md'
    ]

    def run(self, company: str, website: str) -> str:
        """
        Main entrypoint matching orchestrator requirements.
        Performs queries, scrapes pages, and aggregates everything into a single text block.
        First attempts direct regex email extraction from scraped pages.
        Only passes context to Gemma if emails are ambiguous or multiple candidates exist.
        Includes a thread-safe cache lookup step.
        """
        cache_key = f"{company.strip().lower()}|{website.strip().lower()}"
        
        with self._lock:
            if cache_key in self._cache:
                logger.info(f"Cache hit for search data: {company} / {website}")
                return self._cache[cache_key]

        scraped_pages = self.search_and_scrape(company, website)
        if not scraped_pages:
            return ""
        
        # Fast path: extract all email candidates via regex across all pages
        all_emails_found = []
        for page in scraped_pages:
            text = page.get('text', '')
            mailto_prefix = ''
            if text.startswith('Explicit Mailto Links Found:'):
                first_line = text.split('\n')[0]
                for email in self._EMAIL_RE.findall(first_line):
                    if not self._FAKE_EMAIL_PATTERN.search(email):
                        all_emails_found.append((email, 'mailto', page['url']))
            for email in self._EMAIL_RE.findall(text):
                if not self._FAKE_EMAIL_PATTERN.search(email):
                    all_emails_found.append((email, 'text', page['url']))
        
        # Prioritise mailto: emails, then medical-domain emails
        if all_emails_found:
            mailto_hits = [e for e in all_emails_found if e[1] == 'mailto']
            if mailto_hits:
                best = mailto_hits[0][0]
                logger.info(f"Fast-path mailto email found for {company}: {best}")
                result = f"FAST_EMAIL_FOUND: {best}\n\n" + self._build_context(scraped_pages)
                with self._lock:
                    self._cache[cache_key] = result
                return result
            # Prefer medical-domain emails over generic
            medical_hits = [e for e in all_emails_found if any(kw in e[0].lower() for kw in self._MEDICAL_KEYWORDS)]
            if medical_hits:
                best = medical_hits[0][0]
                logger.info(f"Fast-path medical email found for {company}: {best}")
                result = f"FAST_EMAIL_FOUND: {best}\n\n" + self._build_context(scraped_pages)
                with self._lock:
                    self._cache[cache_key] = result
                return result

        result_text = self._build_context(scraped_pages)
        
        with self._lock:
            self._cache[cache_key] = result_text

        return result_text

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

    def search_and_scrape(self, company: str, website: str) -> List[Dict[str, str]]:
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
        
        # 1. Add primary website directly (query labeled as 'direct')
        if website:
            if not website.startswith("http"):
                website = "https://" + website
            urls_to_scrape[website] = "direct_input"

        # 2. Define the search queries targeting name and keywords
        name_clean = name.strip()
        if "," in name_clean:
            name_clean = name_clean.split(",", 1)[0].strip()
            
        queries = [
            f'"{name_clean}" email',
            f'"{name_clean}" contact',
        ]
        if location_specialty:
            keywords = location_specialty.replace(" practice in ", " ").replace(",", " ")
            queries.append(f'"{name_clean}" {keywords} email')
            queries.append(f'"{name_clean}" {keywords} contact')
        else:
            queries.append(f'"{name_clean}" about')
            queries.append(f'"{name_clean}" leadership')

        # 3. Query DuckDuckGo for candidate links
        for query in queries:
            logger.info(f"Querying DuckDuckGo: '{query}'")
            candidate_links = self._search_query_with_retry(query)
            for link in candidate_links:
                # Skip known bot-blocking or non-business directories to target actual clinics
                link_lower = link.lower()
                skipped_domains = [
                    # Directory / profile aggregators
                    "zoominfo.com", "rocketreach.co", "linkedin.com", "npidb.org",
                    "npiprofile.com", "doximity.com", "healthgrades.com", "vitals.com",
                    "npino.com", "npi-lookup.org", "nationalprovider.org", "npinumberlookup.org",
                    "cms.gov", "medicare.gov", "data.cms.gov",
                    # Social media
                    "facebook.com", "instagram.com", "youtube.com", "twitter.com",
                    "tiktok.com", "pinterest.com", "reddit.com", "tumblr.com",
                    # Search / ads / tracking
                    "google.com", "bing.com", "yahoo.com", "doubleclick.net",
                    "duckduckgo.com", "baidu.com",
                    # Tech / dev / Q&A
                    "wikipedia.org", "wikimedia.org", "wikidata.org",
                    "stackexchange.com", "stackoverflow.com", "github.com",
                    "microsoft.com", "answers.microsoft.com", "support.microsoft.com",
                    "apple.com", "docs.google.com", "mozilla.org",
                    # News / media
                    "bbc.com", "cnn.com", "nytimes.com", "theguardian.com",
                    "reuters.com", "apnews.com", "nbcnews.com", "foxnews.com",
                    "usatoday.com", "washingtonpost.com", "bloomberg.com",
                    "forbes.com", "businessinsider.com", "huffpost.com",
                    # Entertainment / streaming
                    "imdb.com", "netflix.com", "hulu.com", "disneyplus.com",
                    "spotify.com", "gaana.com", "pandora.com", "soundcloud.com",
                    "m.imdb.com", "amazon.com", "ebay.com",
                    # Sports / misc
                    "acmilan.com", "espn.com", "nfl.com", "nba.com", "fifa.com",
                    # Knowledge bases / encyclopedias
                    "britannica.com", "merriam-webster.com", "dictionary.com",
                    # Food / lifestyle
                    "dominos.com", "yelp.com", "tripadvisor.com", "doordash.com",
                    "ubereats.com", "grubhub.com",
                    # General aggregators that don't have emails
                    "yellowpages.com", "whitepages.com", "spokeo.com", "beenverified.com",
                    "usphonebook.com", "truepeoplesearch.com", "fastpeoplesearch.com",
                    # Indian / irrelevant international portals showing up
                    "fciqms.in", "aucklandpethospital.co.nz", "semanticscholar.org",
                    "researchgate.net", "elevenforum.com", "dorothyonfire.com",
                ]
                if any(domain in link_lower for domain in skipped_domains):
                    continue
                # Deduplicate links, prioritizing the first query that found it
                if link not in urls_to_scrape:
                    urls_to_scrape[link] = query
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
