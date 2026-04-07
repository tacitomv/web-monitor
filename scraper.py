"""
Web scraper module for extracting table data and checking uptime.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)


DEFAULT_MONITOR_TYPE = "table"


@dataclass
class TableRow:
    """Represents a row from the monitored table."""
    doc_name: str
    file_link: str
    doc_type: str
    date: str


@dataclass
class TableData:
    """Represents the extracted table data."""
    url: str
    table_id: str
    name: str
    row_count: int
    rows: List[TableRow]
    raw_html: str


@dataclass
class UptimeResult:
    """Represents the result of an uptime-only check."""
    url: str
    name: str
    status_code: Optional[int]
    is_up: bool
    error_message: Optional[str] = None


def build_monitor_id(url_config: Dict) -> str:
    """Build a stable ID for a monitor target."""
    explicit_id = url_config.get("id")
    if explicit_id:
        return explicit_id

    monitor_type = url_config.get("type", DEFAULT_MONITOR_TYPE).lower()
    table_id = url_config.get("table_id", "")
    key = f"{monitor_type}|{url_config['url']}|{table_id}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"{monitor_type}-{digest}"


def get_default_recipients() -> List[str]:
    """Return the fallback recipients for targets that omit them."""
    recipients = getattr(config, "DEFAULT_RECIPIENT_EMAILS", None)
    if recipients is None:
        recipients = getattr(config, "RECIPIENT_EMAILS", [])
    return list(dict.fromkeys(recipients))


def get_monitored_targets() -> List[Dict]:
    """Return normalized monitor targets from config."""
    source_targets = getattr(config, "MONITORED_TARGETS", None)
    if source_targets is None:
        source_targets = getattr(config, "MONITORED_URLS", [])

    normalized_targets = []
    default_recipients = get_default_recipients()

    for target in source_targets:
        normalized = dict(target)
        normalized["type"] = normalized.get("type", DEFAULT_MONITOR_TYPE).lower()
        normalized["recipients"] = list(dict.fromkeys(normalized.get("recipients") or default_recipients))
        normalized["id"] = build_monitor_id(normalized)
        normalized_targets.append(normalized)

    return normalized_targets


def fetch_page(url: str) -> Tuple[Optional[requests.Response], Optional[str]]:
    """
    Fetch the HTML content of a page.
    
    Args:
        url: The URL to fetch
        
    Returns:
        A tuple of (response, error_message)
    """
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=config.REQUEST_TIMEOUT
        )
        return response, None
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None, str(e)


def extract_table_data(html: str, table_id: str, url: str, name: str) -> Optional[TableData]:
    """
    Extract data from a specific table in the HTML.
    
    Args:
        html: The HTML content
        table_id: The ID of the table to extract
        url: The source URL (for reference)
        name: The friendly name for this monitored page
        
    Returns:
        TableData object containing the extracted data, or None if extraction failed
    """
    try:
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', id=table_id)
        
        if table is None:
            logger.warning(f"Table with id '{table_id}' not found at {url}")
            return None
        
        rows = []
        # Find all data rows (skip header row if present)
        tbody = table.find('tbody')
        if tbody:
            row_elements = tbody.find_all('tr')
        else:
            # If no tbody, get all tr elements except the first (header)
            all_rows = table.find_all('tr')
            row_elements = all_rows[1:] if len(all_rows) > 1 else all_rows
        
        for tr in row_elements:
            cells = tr.find_all(['td', 'th'])
            if len(cells) >= 4:
                # Extract doc name
                doc_name = cells[0].get_text(strip=True)
                
                # Extract file link
                link_elem = cells[1].find('a')
                file_link = cells[1].get_text(strip=True)
                if link_elem:
                    href = link_elem.get('href')
                    file_link = str(href or file_link)
                
                # Extract doc type
                doc_type = cells[2].get_text(strip=True)
                
                # Extract date
                date = cells[3].get_text(strip=True)
                
                rows.append(TableRow(
                    doc_name=doc_name,
                    file_link=file_link,
                    doc_type=doc_type,
                    date=date
                ))
        
        return TableData(
            url=url,
            table_id=table_id,
            name=name,
            row_count=len(rows),
            rows=rows,
            raw_html=str(table)
        )
        
    except Exception as e:
        logger.error(f"Failed to extract table data from {url}: {e}")
        return None


def scrape_monitored_url(url_config: Dict) -> Tuple[Optional[TableData], Optional[int], Optional[str]]:
    """
    Scrape a single monitored URL and extract table data.
    
    Args:
        url_config: Dictionary containing 'url', 'table_id', and 'name'
        
    Returns:
        Tuple of (TableData or None, HTTP status code, error message)
    """
    url = url_config["url"]
    table_id = url_config["table_id"]
    name = url_config["name"]
    
    logger.info(f"Scraping {name} ({url})")
    
    response, error_message = fetch_page(url)
    if response is None:
        return None, None, error_message

    if response.status_code != 200:
        message = f"HTTP {response.status_code}"
        logger.warning(f"Failed to scrape {name}: {message}")
        return None, response.status_code, message
    
    table_data = extract_table_data(response.text, table_id, url, name)
    if table_data is None:
        return None, response.status_code, f"Table '{table_id}' not found"

    return table_data, response.status_code, None


def check_uptime(url_config: Dict) -> UptimeResult:
    """Check whether a monitored URL is returning HTTP 200."""
    url = url_config["url"]
    name = url_config["name"]

    logger.info(f"Checking uptime for {name} ({url})")

    response, error_message = fetch_page(url)
    if response is None:
        return UptimeResult(
            url=url,
            name=name,
            status_code=None,
            is_up=False,
            error_message=error_message,
        )

    is_up = response.status_code == 200
    return UptimeResult(
        url=url,
        name=name,
        status_code=response.status_code,
        is_up=is_up,
        error_message=None if is_up else f"HTTP {response.status_code}",
    )


def scrape_all() -> List[TableData]:
    """
    Scrape all monitored URLs.
    
    Returns:
        List of TableData objects for successfully scraped pages
    """
    results = []
    
    for url_config in get_monitored_targets():
        if url_config["type"] != "table":
            continue

        table_data, _, _ = scrape_monitored_url(url_config)
        if table_data:
            results.append(table_data)
            logger.info(f"Scraped {table_data.name}: {table_data.row_count} rows found")
        else:
            logger.warning(f"Failed to scrape {url_config['name']}")
    
    return results


if __name__ == "__main__":
    # Test scraping
    logging.basicConfig(level=logging.INFO)
    results = scrape_all()
    for result in results:
        print(f"\n{result.name}: {result.row_count} rows")
        for row in result.rows:
            print(f"  - {row.doc_name} | {row.doc_type} | {row.date}")
