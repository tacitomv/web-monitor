"""
Database module for storing and tracking monitor state changes.
"""

import logging
import sqlite3
import json
from datetime import datetime
from typing import Any, List, Optional, Tuple
from dataclasses import asdict

import config
from scraper import TableData, UptimeResult

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for storing monitor states."""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path or config.DATABASE_PATH
        self.conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._create_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """Return the active database connection."""
        if self.conn is None:
            raise RuntimeError("Database connection has not been initialized")
        return self.conn
    
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
        cursor = self._get_connection().cursor()
        
        # Table to store the current state of each monitored target
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitor_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                name TEXT NOT NULL,
                monitor_type TEXT NOT NULL,
                table_id TEXT,
                row_count INTEGER,
                rows_json TEXT,
                raw_html TEXT,
                is_up INTEGER,
                last_http_status INTEGER,
                last_error TEXT,
                last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_changed TIMESTAMP
            )
        """)
        
        # Table to store monitor event history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id TEXT NOT NULL,
                url TEXT NOT NULL,
                name TEXT NOT NULL,
                monitor_type TEXT NOT NULL,
                event_type TEXT NOT NULL,
                old_row_count INTEGER,
                new_row_count INTEGER,
                status_code INTEGER,
                details_json TEXT,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self._get_connection().commit()
        logger.debug("Database tables created/verified")
    
    def get_monitor_state(self, monitor_id: str) -> Optional[dict]:
        """
        Get the stored state for a page.
        
        Args:
            monitor_id: The monitor ID
            
        Returns:
            Dictionary with page state or None if not found
        """
        cursor = self._get_connection().cursor()
        cursor.execute(
            "SELECT * FROM monitor_states WHERE monitor_id = ?",
            (monitor_id,)
        )
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def update_monitor_status(self, monitor_id: str, target: dict, is_up: bool,
                              status_code: Optional[int] = None,
                              error_message: Optional[str] = None):
        """Update status information for a monitor without changing content state."""
        old_state = self.get_monitor_state(monitor_id)
        cursor = self._get_connection().cursor()

        if old_state is None:
            cursor.execute("""
                INSERT INTO monitor_states
                (monitor_id, url, name, monitor_type, table_id, is_up, last_http_status,
                 last_error, last_checked, last_changed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                monitor_id,
                target["url"],
                target["name"],
                target["type"],
                target.get("table_id"),
                int(is_up),
                status_code,
                error_message,
                datetime.now(),
                datetime.now(),
            ))
        else:
            cursor.execute("""
                UPDATE monitor_states
                SET name = ?, monitor_type = ?, table_id = ?, is_up = ?,
                    last_http_status = ?, last_error = ?, last_checked = ?
                WHERE monitor_id = ?
            """, (
                target["name"],
                target["type"],
                target.get("table_id"),
                int(is_up),
                status_code,
                error_message,
                datetime.now(),
                monitor_id,
            ))

        self._get_connection().commit()

    def update_table_state(self, monitor_id: str, target: dict,
                           table_data: TableData) -> Tuple[bool, Optional[dict]]:
        """
        Update the stored state for a page.
        
        Args:
            monitor_id: The monitor ID
            target: The monitor configuration
            table_data: The current table data
            
        Returns:
            Tuple of (changed: bool, old_state: dict or None)
        """
        old_state = self.get_monitor_state(monitor_id)
        changed = False
        
        # Serialize rows to JSON
        rows_json = json.dumps([asdict(row) for row in table_data.rows])
        
        cursor = self._get_connection().cursor()
        
        if old_state is None:
            # First time seeing this monitor
            cursor.execute("""
                INSERT INTO monitor_states
                (monitor_id, url, name, monitor_type, table_id, row_count, rows_json, raw_html,
                 is_up, last_http_status, last_error, last_checked, last_changed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                monitor_id,
                table_data.url,
                table_data.name,
                target["type"],
                table_data.table_id,
                table_data.row_count,
                rows_json,
                table_data.raw_html,
                1,
                200,
                None,
                datetime.now(),
                datetime.now()
            ))
            changed = True
            logger.info(f"New monitor added: {table_data.name} with {table_data.row_count} rows")
            
        elif old_state['row_count'] != table_data.row_count:
            # Row count changed
            cursor.execute("""
                UPDATE monitor_states
                SET name = ?, monitor_type = ?, table_id = ?, row_count = ?, rows_json = ?, raw_html = ?,
                    is_up = ?, last_http_status = ?, last_error = ?, last_checked = ?, last_changed = ?
                WHERE monitor_id = ?
            """, (
                table_data.name,
                target["type"],
                table_data.table_id,
                table_data.row_count,
                rows_json,
                table_data.raw_html,
                1,
                200,
                None,
                datetime.now(),
                datetime.now(),
                monitor_id
            ))
            changed = True
            logger.info(
                f"Change detected: {table_data.name} "
                f"({old_state['row_count']} → {table_data.row_count} rows)"
            )
            
        else:
            # No change, just update last_checked
            cursor.execute("""
                UPDATE monitor_states
                SET name = ?, monitor_type = ?, table_id = ?, rows_json = ?, raw_html = ?,
                    is_up = ?, last_http_status = ?, last_error = ?, last_checked = ?
                WHERE monitor_id = ?
            """, (
                table_data.name,
                target["type"],
                table_data.table_id,
                rows_json,
                table_data.raw_html,
                1,
                200,
                None,
                datetime.now(),
                monitor_id,
            ))
            logger.debug(f"No change: {table_data.name}")
        
        self._get_connection().commit()
        return changed, old_state

    def update_uptime_state(self, monitor_id: str, target: dict,
                            uptime_result: UptimeResult) -> Tuple[Optional[str], Optional[dict]]:
        """Update the stored uptime state for a target."""
        old_state = self.get_monitor_state(monitor_id)
        event_type = None
        cursor = self._get_connection().cursor()

        if old_state is None:
            cursor.execute("""
                INSERT INTO monitor_states
                (monitor_id, url, name, monitor_type, table_id, is_up, last_http_status,
                 last_error, last_checked, last_changed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                monitor_id,
                uptime_result.url,
                uptime_result.name,
                target["type"],
                target.get("table_id"),
                int(uptime_result.is_up),
                uptime_result.status_code,
                uptime_result.error_message,
                datetime.now(),
                datetime.now(),
            ))
            if not uptime_result.is_up:
                event_type = "down"
        else:
            was_up = bool(old_state['is_up']) if old_state['is_up'] is not None else None
            if was_up != uptime_result.is_up:
                event_type = "recovered" if uptime_result.is_up else "down"

            cursor.execute("""
                UPDATE monitor_states
                SET name = ?, monitor_type = ?, table_id = ?, is_up = ?, last_http_status = ?,
                    last_error = ?, last_checked = ?, last_changed = ?
                WHERE monitor_id = ?
            """, (
                uptime_result.name,
                target["type"],
                target.get("table_id"),
                int(uptime_result.is_up),
                uptime_result.status_code,
                uptime_result.error_message,
                datetime.now(),
                datetime.now() if event_type else old_state['last_changed'],
                monitor_id,
            ))

        self._get_connection().commit()
        return event_type, old_state
    
    def record_event(self, monitor_id: str, target: dict, event_type: str,
                     old_count: Optional[int] = None, new_count: Optional[int] = None,
                     status_code: Optional[int] = None, details: Optional[dict[str, Any]] = None):
        """
        Record a change in the history table.
        
        Args:
            monitor_id: The monitor ID
            target: The monitor configuration
            old_count: Previous row count (None for new pages)
            new_count: Current row count
            event_type: Type of event (e.g., 'new', 'added', 'removed', 'down')
            details: Additional details as a dictionary
        """
        cursor = self._get_connection().cursor()
        cursor.execute("""
            INSERT INTO monitor_events
            (monitor_id, url, name, monitor_type, event_type, old_row_count, new_row_count,
             status_code, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            monitor_id,
            target["url"],
            target["name"],
            target["type"],
            event_type,
            old_count,
            new_count,
            status_code,
            json.dumps(details) if details else None
        ))
        self._get_connection().commit()
    
    def get_event_history(self, monitor_id: Optional[str] = None, limit: int = 100) -> List[dict]:
        """
        Get change history, optionally filtered by URL.
        
        Args:
            monitor_id: Optional monitor ID to filter by
            limit: Maximum number of records to return
            
        Returns:
            List of change history records
        """
        cursor = self._get_connection().cursor()
        
        if monitor_id:
            cursor.execute(
                "SELECT * FROM monitor_events WHERE monitor_id = ? ORDER BY detected_at DESC LIMIT ?",
                (monitor_id, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM monitor_events ORDER BY detected_at DESC LIMIT ?",
                (limit,)
            )
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_all_monitor_states(self) -> List[dict]:
        """Get all stored page states."""
        cursor = self._get_connection().cursor()
        cursor.execute("SELECT * FROM monitor_states ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.debug("Database connection closed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db = Database(":memory:")
    print("Database initialized successfully")
    db.close()
