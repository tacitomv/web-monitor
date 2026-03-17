#!/usr/bin/env python3
"""
Main monitoring script - runs the web monitor to track page changes.
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime
from typing import List

import config
from scraper import scrape_all, TableData
from database import Database
from notifier import ChangeDetails, notify_change, send_test_email, send_daily_report, send_greeting_email

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    logger.info("Shutdown signal received, stopping monitor...")
    running = False


def check_for_changes(db: Database) -> List[ChangeDetails]:
    """
    Check all monitored URLs for changes.
    
    Args:
        db: Database instance
        
    Returns:
        List of ChangeDetails for detected changes
    """
    changes = []
    
    # Scrape all monitored URLs
    results = scrape_all()
    
    for table_data in results:
        changed, old_state = db.update_page_state(table_data)
        
        if changed:
            old_count = old_state['row_count'] if old_state else 0
            
            # Determine new rows (simple comparison based on count)
            new_rows = []
            if old_state and table_data.row_count > old_count:
                # Get the newest rows (assuming new rows are added at the end)
                new_rows = table_data.rows[old_count:]
            elif not old_state:
                # First time - all rows are "new"
                new_rows = table_data.rows
            
            # Record change in database
            change_type = 'new' if not old_state else ('added' if table_data.row_count > old_count else 'removed')
            db.record_change(
                url=table_data.url,
                name=table_data.name,
                old_count=old_count if old_state else None,
                new_count=table_data.row_count,
                change_type=change_type,
                details={'new_rows': [r.__dict__ for r in new_rows]} if new_rows else None
            )
            
            # Create change notification
            change = ChangeDetails(
                name=table_data.name,
                url=table_data.url,
                old_row_count=old_count,
                new_row_count=table_data.row_count,
                new_rows=new_rows
            )
            changes.append(change)
            
            logger.info(
                f"Change detected: {table_data.name} - "
                f"{old_count} → {table_data.row_count} rows"
            )
    
    return changes


def run_once():
    """Run a single check cycle."""
    logger.info("Running single check...")
    
    db = Database()
    try:
        changes = check_for_changes(db)
        
        if changes:
            logger.info(f"Found {len(changes)} change(s), sending notifications...")
            for change in changes:
                notify_change(change)
        else:
            logger.info("No changes detected")
            
    finally:
        db.close()
    
    return changes


def run_continuous():
    """Run continuous monitoring loop."""
    global running
    
    logger.info("Starting continuous monitoring...")
    logger.info(f"Check interval: {config.CHECK_INTERVAL} seconds")
    logger.info(f"Monitoring {len(config.MONITORED_URLS)} URL(s)")
    
    if config.DAILY_REPORT_ENABLED:
        logger.info(f"Daily report scheduled for: {config.DAILY_REPORT_TIME}")
    
    # Send greeting email on startup
    logger.info("Sending startup greeting email...")
    send_greeting_email(config.MONITORED_URLS, config.CHECK_INTERVAL)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    db = Database()
    
    # Daily tracking stats
    daily_check_count = 0
    daily_change_count = 0
    daily_changes_details = []
    daily_start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    last_report_date = datetime.now().date()
    
    def reset_daily_stats():
        nonlocal daily_check_count, daily_change_count, daily_changes_details, daily_start_time
        daily_check_count = 0
        daily_change_count = 0
        daily_changes_details = []
        daily_start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    def should_send_daily_report():
        """Check if it's time to send the daily report."""
        if not config.DAILY_REPORT_ENABLED:
            return False
        
        now = datetime.now()
        report_hour, report_minute = map(int, config.DAILY_REPORT_TIME.split(':'))
        
        # Check if we're within the report time window (within CHECK_INTERVAL seconds)
        current_minutes = now.hour * 60 + now.minute
        report_minutes = report_hour * 60 + report_minute
        
        return (current_minutes >= report_minutes and 
                current_minutes < report_minutes + (config.CHECK_INTERVAL // 60) + 1)
    
    try:
        while running:
            logger.info(f"Starting check cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            try:
                changes = check_for_changes(db)
                daily_check_count += 1
                
                if changes:
                    logger.info(f"Found {len(changes)} change(s), sending notifications...")
                    for change in changes:
                        notify_change(change)
                        daily_change_count += 1
                        daily_changes_details.append({
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'name': change.name,
                            'old_count': change.old_row_count,
                            'new_count': change.new_row_count
                        })
                else:
                    logger.info("No changes detected")
                
                # Check if it's time for daily report
                if should_send_daily_report() and datetime.now().date() >= last_report_date:
                    logger.info("Sending daily report...")
                    end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    send_daily_report(
                        daily_check_count,
                        daily_change_count,
                        daily_changes_details,
                        daily_start_time,
                        end_time
                    )
                    last_report_date = datetime.now().date() + __import__('datetime').timedelta(days=1)
                    reset_daily_stats()
                    
            except Exception as e:
                logger.error(f"Error during check cycle: {e}", exc_info=True)
            
            # Wait for next cycle
            if running:
                logger.debug(f"Sleeping for {config.CHECK_INTERVAL} seconds...")
                # Use small sleep intervals to allow for graceful shutdown
                for _ in range(config.CHECK_INTERVAL):
                    if not running:
                        break
                    time.sleep(1)
                    
    finally:
        # Send final report on shutdown if there were any checks
        if daily_check_count > 0 and config.DAILY_REPORT_ENABLED:
            logger.info("Sending final daily report before shutdown...")
            end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            send_daily_report(
                daily_check_count,
                daily_change_count,
                daily_changes_details,
                daily_start_time,
                end_time
            )
        
        db.close()
        logger.info("Monitor stopped")


def show_status():
    """Show current monitoring status."""
    db = Database()
    try:
        states = db.get_all_page_states()
        
        if not states:
            print("No pages are currently being monitored.")
            return
        
        print("\n=== Monitored Pages Status ===\n")
        for state in states:
            print(f"Page: {state['name']}")
            print(f"  URL: {state['url']}")
            print(f"  Table ID: {state['table_id']}")
            print(f"  Current Rows: {state['row_count']}")
            print(f"  Last Checked: {state['last_checked']}")
            print(f"  Last Changed: {state['last_changed']}")
            print()
        
        # Show recent changes
        history = db.get_change_history(limit=10)
        if history:
            print("\n=== Recent Changes ===\n")
            for change in history:
                print(f"[{change['detected_at']}] {change['name']}: "
                      f"{change['old_row_count']} → {change['new_row_count']} rows "
                      f"({change['change_type']})")
                      
    finally:
        db.close()


def test_scrape():
    """Test scraping without sending notifications."""
    logger.info("Testing scrape functionality...")
    
    results = scrape_all()
    
    if not results:
        print("No data scraped. Check the URLs and table IDs in config.py")
        return
    
    for result in results:
        print(f"\n=== {result.name} ===")
        print(f"URL: {result.url}")
        print(f"Table ID: {result.table_id}")
        print(f"Rows Found: {result.row_count}")
        print("\nTable Contents:")
        print("-" * 80)
        print(f"{'Doc Name':<30} {'Type':<15} {'Date':<15}")
        print("-" * 80)
        for row in result.rows:
            print(f"{row.doc_name[:30]:<30} {row.doc_type[:15]:<15} {row.date[:15]:<15}")
        print("-" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Web Monitor - Track changes in web page tables'
    )
    parser.add_argument(
        '--once', '-o',
        action='store_true',
        help='Run a single check and exit'
    )
    parser.add_argument(
        '--status', '-s',
        action='store_true',
        help='Show monitoring status and recent changes'
    )
    parser.add_argument(
        '--test-scrape', '-t',
        action='store_true',
        help='Test scraping without database updates or notifications'
    )
    parser.add_argument(
        '--test-email',
        action='store_true',
        help='Send a test email to verify SMTP configuration'
    )
    
    args = parser.parse_args()
    
    if args.status:
        show_status()
    elif args.test_scrape:
        test_scrape()
    elif args.test_email:
        print("Sending test email...")
        if send_test_email():
            print("Test email sent successfully!")
        else:
            print("Failed to send test email. Check config.py and logs.")
    elif args.once:
        run_once()
    else:
        run_continuous()


if __name__ == "__main__":
    main()
