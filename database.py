"""
Database module for storing and tracking page state changes.
"""

import json
import logging
import sqlite3
from datetime import datetime
from typing import Optional, List, Tuple
from dataclasses import asdict

import config
from scraper import TableData, TableRow

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for storing page states."""
    
    def __init__(self, db_path: str = None):
        """
        Initialize the database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path or config.DATABASE_PATH
        self.conn = None
        self._connect()
        self._create_tables()
    
    def _connect(self):
        """Establish database connection."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            logger.debug(f"Connected to database: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def _create_tables(self):
        """Create the necessary database tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Table to store the current state of each monitored page
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS page_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                table_id TEXT NOT NULL,
                name TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                rows_json TEXT,
                raw_html TEXT,
                last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_changed TIMESTAMP
            )
        """)
        
        # Table to store change history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS change_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                name TEXT NOT NULL,
                old_row_count INTEGER,
                new_row_count INTEGER NOT NULL,
                change_type TEXT NOT NULL,
                details_json TEXT,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.commit()
        logger.debug("Database tables created/verified")
    
    def get_page_state(self, url: str) -> Optional[dict]:
        """
        Get the stored state for a page.
        
        Args:
            url: The page URL
            
        Returns:
            Dictionary with page state or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM page_states WHERE url = ?",
            (url,)
        )
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def update_page_state(self, table_data: TableData) -> Tuple[bool, Optional[dict]]:
        """
        Update the stored state for a page.
        
        Args:
            table_data: The current table data
            
        Returns:
            Tuple of (changed: bool, old_state: dict or None)
        """
        old_state = self.get_page_state(table_data.url)
        changed = False
        
        # Serialize rows to JSON
        rows_json = json.dumps([asdict(row) for row in table_data.rows])
        
        cursor = self.conn.cursor()
        
        if old_state is None:
            # First time seeing this page
            cursor.execute("""
                INSERT INTO page_states 
                (url, table_id, name, row_count, rows_json, raw_html, last_checked, last_changed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                table_data.url,
                table_data.table_id,
                table_data.name,
                table_data.row_count,
                rows_json,
                table_data.raw_html,
                datetime.now(),
                datetime.now()
            ))
            changed = True
            logger.info(f"New page added: {table_data.name} with {table_data.row_count} rows")
            
        elif old_state['row_count'] != table_data.row_count:
            # Row count changed
            cursor.execute("""
                UPDATE page_states
                SET row_count = ?, rows_json = ?, raw_html = ?, 
                    last_checked = ?, last_changed = ?
                WHERE url = ?
            """, (
                table_data.row_count,
                rows_json,
                table_data.raw_html,
                datetime.now(),
                datetime.now(),
                table_data.url
            ))
            changed = True
            logger.info(
                f"Change detected: {table_data.name} "
                f"({old_state['row_count']} → {table_data.row_count} rows)"
            )
            
        else:
            # No change, just update last_checked
            cursor.execute("""
                UPDATE page_states
                SET last_checked = ?
                WHERE url = ?
            """, (datetime.now(), table_data.url))
            logger.debug(f"No change: {table_data.name}")
        
        self.conn.commit()
        return changed, old_state
    
    def record_change(self, url: str, name: str, old_count: Optional[int], 
                      new_count: int, change_type: str, details: dict = None):
        """
        Record a change in the history table.
        
        Args:
            url: The page URL
            name: The page name
            old_count: Previous row count (None for new pages)
            new_count: Current row count
            change_type: Type of change (e.g., 'new', 'added', 'removed')
            details: Additional details as a dictionary
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO change_history 
            (url, name, old_row_count, new_row_count, change_type, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            url,
            name,
            old_count,
            new_count,
            change_type,
            json.dumps(details) if details else None
        ))
        self.conn.commit()
    
    def get_change_history(self, url: str = None, limit: int = 100) -> List[dict]:
        """
        Get change history, optionally filtered by URL.
        
        Args:
            url: Optional URL to filter by
            limit: Maximum number of records to return
            
        Returns:
            List of change history records
        """
        cursor = self.conn.cursor()
        
        if url:
            cursor.execute(
                "SELECT * FROM change_history WHERE url = ? ORDER BY detected_at DESC LIMIT ?",
                (url, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM change_history ORDER BY detected_at DESC LIMIT ?",
                (limit,)
            )
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_all_page_states(self) -> List[dict]:
        """Get all stored page states."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM page_states ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.debug("Database connection closed")


if __name__ == "__main__":
    # Test database operations
    logging.basicConfig(level=logging.INFO)
    
    db = Database(":memory:")  # Use in-memory database for testing
    
    # Create test data
    test_rows = [
        TableRow("Doc1", "http://example.com/file1.pdf", "PDF", "2024-01-15"),
        TableRow("Doc2", "http://example.com/file2.pdf", "PDF", "2024-01-16"),
    ]
    
    test_data = TableData(
        url="http://test.com",
        table_id="test-table",
        name="Test Page",
        row_count=2,
        rows=test_rows,
        raw_html="<table>...</table>"
    )
    
    # Test insert
    changed, old_state = db.update_page_state(test_data)
    print(f"First insert - Changed: {changed}, Old state: {old_state}")
    
    # Test no change
    changed, old_state = db.update_page_state(test_data)
    print(f"No change - Changed: {changed}")
    
    # Test change
    test_data.row_count = 3
    test_data.rows.append(TableRow("Doc3", "http://example.com/file3.pdf", "PDF", "2024-01-17"))
    changed, old_state = db.update_page_state(test_data)
    print(f"Changed - Changed: {changed}, Old count: {old_state['row_count']}")
    
    db.close()
