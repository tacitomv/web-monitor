"""
Web scraper module for extracting table data from monitored pages.
"""

import logging
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)


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


def fetch_page(url: str) -> Optional[str]:
    """
    Fetch the HTML content of a page.
    
    Args:
        url: The URL to fetch
        
    Returns:
        The HTML content as a string, or None if the request failed
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
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


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
                file_link = link_elem.get('href', '') if link_elem else cells[1].get_text(strip=True)
                
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


def scrape_monitored_url(url_config: Dict) -> Optional[TableData]:
    """
    Scrape a single monitored URL and extract table data.
    
    Args:
        url_config: Dictionary containing 'url', 'table_id', and 'name'
        
    Returns:
        TableData object or None if scraping failed
    """
    url = url_config["url"]
    table_id = url_config["table_id"]
    name = url_config["name"]
    
    logger.info(f"Scraping {name} ({url})")
    
    html = fetch_page(url)
    if html is None:
        return None
    
    return extract_table_data(html, table_id, url, name)


def scrape_all() -> List[TableData]:
    """
    Scrape all monitored URLs.
    
    Returns:
        List of TableData objects for successfully scraped pages
    """
    results = []
    
    for url_config in config.MONITORED_URLS:
        table_data = scrape_monitored_url(url_config)
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
