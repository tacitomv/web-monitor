#!/usr/bin/env python3
"""
Main monitoring script for table-change and uptime targets.
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List

import config
from database import Database
from notifier import (
    ChangeDetails,
    UptimeAlertDetails,
    notify_change_for_target,
    notify_uptime,
    send_daily_reports,
    send_greeting_email,
    send_test_email,
)
from scraper import check_uptime, get_monitored_targets, scrape_monitored_url

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""

    del signum, frame
    global running
    logger.info("Shutdown signal received, stopping monitor...")
    running = False


def create_daily_stats(monitored_targets: List[dict]) -> Dict[str, dict]:
    """Create per-target daily stats containers."""

    return {
        target["id"]: {
            "id": target["id"],
            "name": target["name"],
            "url": target["url"],
            "type": target["type"],
            "checks": 0,
            "successful_checks": 0,
            "failed_checks": 0,
            "change_count": 0,
            "up_checks": 0,
            "down_checks": 0,
            "events": [],
        }
        for target in monitored_targets
    }


def add_daily_event(daily_stats: Dict[str, dict], target: dict, summary: str):
    """Append one event entry to a target's daily stats."""

    daily_stats[target["id"]]["events"].append(
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "summary": summary,
        }
    )


def process_table_target(db: Database, target: dict, daily_stats: Dict[str, dict]) -> List[dict]:
    """Process one table-monitor target."""

    notifications = []
    stats = daily_stats[target["id"]]
    stats["checks"] += 1

    table_data, status_code, error_message = scrape_monitored_url(target)
    if table_data is None:
        stats["failed_checks"] += 1
        db.update_monitor_status(
            target["id"],
            target,
            is_up=status_code == 200,
            status_code=status_code,
            error_message=error_message,
        )
        logger.warning("Table check failed for %s: %s", target["name"], error_message or "unknown error")
        return notifications

    stats["successful_checks"] += 1
    changed, old_state = db.update_table_state(target["id"], target, table_data)
    if not changed:
        return notifications

    old_count = old_state["row_count"] if old_state and old_state["row_count"] is not None else 0
    if old_state and table_data.row_count > old_count:
        new_rows = table_data.rows[old_count:]
    elif not old_state:
        new_rows = table_data.rows
    else:
        new_rows = []

    change_type = "new" if not old_state else ("added" if table_data.row_count > old_count else "removed")
    db.record_event(
        target["id"],
        target,
        event_type=change_type,
        old_count=old_count if old_state else None,
        new_count=table_data.row_count,
        details={"new_rows": [row.__dict__ for row in new_rows]} if new_rows else None,
    )

    stats["change_count"] += 1
    add_daily_event(daily_stats, target, f"Table rows changed from {old_count} to {table_data.row_count}")

    notifications.append(
        {
            "kind": "change",
            "recipients": target["recipients"],
            "payload": ChangeDetails(
                name=table_data.name,
                url=table_data.url,
                old_row_count=old_count,
                new_row_count=table_data.row_count,
                new_rows=new_rows,
            ),
        }
    )

    logger.info("Change detected: %s - %s -> %s rows", table_data.name, old_count, table_data.row_count)
    return notifications


def process_uptime_target(db: Database, target: dict, daily_stats: Dict[str, dict]) -> List[dict]:
    """Process one uptime-monitor target."""

    notifications = []
    stats = daily_stats[target["id"]]
    stats["checks"] += 1

    uptime_result = check_uptime(target)
    if uptime_result.is_up:
        stats["up_checks"] += 1
    else:
        stats["down_checks"] += 1

    event_type, old_state = db.update_uptime_state(target["id"], target, uptime_result)
    if not event_type:
        return notifications

    db.record_event(
        target["id"],
        target,
        event_type=event_type,
        status_code=uptime_result.status_code,
        details={"error_message": uptime_result.error_message} if uptime_result.error_message else None,
    )

    if event_type == "down":
        status_text = uptime_result.error_message or f"HTTP {uptime_result.status_code}"
        summary = f"Site became unavailable ({status_text})"
    else:
        previous_status = old_state["last_http_status"] if old_state else None
        if previous_status:
            summary = f"Site recovered from HTTP {previous_status}"
        else:
            summary = "Site recovered"

    add_daily_event(daily_stats, target, summary)

    notifications.append(
        {
            "kind": "uptime",
            "recipients": target["recipients"],
            "payload": UptimeAlertDetails(
                name=uptime_result.name,
                url=uptime_result.url,
                status_code=uptime_result.status_code,
                error_message=uptime_result.error_message,
                event_type=event_type,
            ),
        }
    )

    logger.info("Uptime event detected for %s: %s", uptime_result.name, event_type)
    return notifications


def check_for_changes(db: Database, monitored_targets: List[dict],
                      daily_stats: Dict[str, dict]) -> List[dict]:
    """Run one monitoring cycle across all configured targets."""

    notifications = []

    for target in monitored_targets:
        if target["type"] == "table":
            notifications.extend(process_table_target(db, target, daily_stats))
        elif target["type"] == "uptime":
            notifications.extend(process_uptime_target(db, target, daily_stats))
        else:
            logger.warning("Unsupported monitor type '%s' for %s", target["type"], target["name"])

    return notifications


def send_notifications(notifications: List[dict]):
    """Dispatch notifications generated during a check cycle."""

    for notification in notifications:
        if notification["kind"] == "change":
            notify_change_for_target(notification["payload"], notification["recipients"])
        elif notification["kind"] == "uptime":
            notify_uptime(notification["payload"], notification["recipients"])


def next_daily_report_at(reference: datetime) -> datetime:
    """Return the next scheduled daily report time."""

    report_hour, report_minute = map(int, config.DAILY_REPORT_TIME.split(":"))
    scheduled = reference.replace(hour=report_hour, minute=report_minute, second=0, microsecond=0)
    if reference >= scheduled:
        scheduled += timedelta(days=1)
    return scheduled


def run_once():
    """Run a single check cycle."""

    logger.info("Running single check...")

    monitored_targets = get_monitored_targets()
    db = Database()
    try:
        notifications = check_for_changes(db, monitored_targets, create_daily_stats(monitored_targets))

        if notifications:
            logger.info("Found %s notification event(s), sending notifications...", len(notifications))
            send_notifications(notifications)
        else:
            logger.info("No changes or uptime events detected")
    finally:
        db.close()

    return notifications


def run_continuous():
    """Run continuous monitoring loop."""

    global running

    monitored_targets = get_monitored_targets()
    logger.info("Starting continuous monitoring...")
    logger.info("Check interval: %s seconds", config.CHECK_INTERVAL)
    logger.info("Monitoring %s target(s)", len(monitored_targets))

    if config.DAILY_REPORT_ENABLED:
        logger.info("Daily report scheduled for: %s", config.DAILY_REPORT_TIME)

    logger.info("Sending startup greeting email...")
    send_greeting_email(monitored_targets, config.CHECK_INTERVAL)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    db = Database()
    daily_stats = create_daily_stats(monitored_targets)
    daily_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    next_report_time = next_daily_report_at(datetime.now())

    def reset_daily_stats():
        nonlocal daily_stats, daily_start_time
        daily_stats = create_daily_stats(monitored_targets)
        daily_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        while running:
            logger.info("Starting check cycle at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            try:
                notifications = check_for_changes(db, monitored_targets, daily_stats)

                if notifications:
                    logger.info("Found %s notification event(s), sending notifications...", len(notifications))
                    send_notifications(notifications)
                else:
                    logger.info("No changes or uptime events detected")

                if config.DAILY_REPORT_ENABLED and datetime.now() >= next_report_time:
                    logger.info("Sending daily report...")
                    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    send_daily_reports(monitored_targets, daily_stats, daily_start_time, end_time)
                    reset_daily_stats()
                    next_report_time = next_daily_report_at(datetime.now())
            except Exception as exc:
                logger.error("Error during check cycle: %s", exc, exc_info=True)

            if running:
                logger.debug("Sleeping for %s seconds...", config.CHECK_INTERVAL)
                for _ in range(config.CHECK_INTERVAL):
                    if not running:
                        break
                    time.sleep(1)
    finally:
        if config.DAILY_REPORT_ENABLED and any(stat["checks"] > 0 for stat in daily_stats.values()):
            logger.info("Sending final daily report before shutdown...")
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            send_daily_reports(monitored_targets, daily_stats, daily_start_time, end_time)

        db.close()
        logger.info("Monitor stopped")


def show_status():
    """Show current monitoring status."""

    db = Database()
    try:
        states = db.get_all_monitor_states()

        if not states:
            print("No targets are currently being monitored.")
            return

        print("\n=== Monitored Targets Status ===\n")
        for state in states:
            print(f"Monitor: {state['name']}")
            print(f"  URL: {state['url']}")
            print(f"  Type: {state['monitor_type']}")
            if state["monitor_type"] == "table":
                print(f"  Table ID: {state['table_id']}")
                print(f"  Current Rows: {state['row_count']}")
            else:
                print(f"  Current Status: {'UP' if state['is_up'] else 'DOWN'}")
                print(f"  Last HTTP Status: {state['last_http_status']}")
                if state["last_error"]:
                    print(f"  Last Error: {state['last_error']}")
            print(f"  Last Checked: {state['last_checked']}")
            print(f"  Last Changed: {state['last_changed']}")
            print()

        history = db.get_event_history(limit=10)
        if history:
            print("\n=== Recent Events ===\n")
            for event in history:
                if event["monitor_type"] == "table":
                    print(
                        f"[{event['detected_at']}] {event['name']}: "
                        f"{event['old_row_count']} -> {event['new_row_count']} rows "
                        f"({event['event_type']})"
                    )
                else:
                    print(
                        f"[{event['detected_at']}] {event['name']}: "
                        f"{event['event_type']} ({event['status_code']})"
                    )
    finally:
        db.close()


def test_scrape():
    """Test targets without sending notifications."""

    logger.info("Testing monitoring targets...")
    monitored_targets = get_monitored_targets()

    if not monitored_targets:
        print("No monitor targets configured. Check config.py")
        return

    for target in monitored_targets:
        print(f"\n=== {target['name']} ===")
        print(f"URL: {target['url']}")
        print(f"Type: {target['type']}")

        if target["type"] == "table":
            result, status_code, error_message = scrape_monitored_url(target)
            print(f"HTTP Status: {status_code}")
            if result is None:
                print(f"Error: {error_message}")
                continue

            print(f"Table ID: {result.table_id}")
            print(f"Rows Found: {result.row_count}")
            print("\nTable Contents:")
            print("-" * 80)
            print(f"{'Doc Name':<30} {'Type':<15} {'Date':<15}")
            print("-" * 80)
            for row in result.rows:
                print(f"{row.doc_name[:30]:<30} {row.doc_type[:15]:<15} {row.date[:15]:<15}")
            print("-" * 80)
        elif target["type"] == "uptime":
            result = check_uptime(target)
            print(f"HTTP Status: {result.status_code}")
            print(f"State: {'UP' if result.is_up else 'DOWN'}")
            if result.error_message:
                print(f"Error: {result.error_message}")
        else:
            print(f"Unsupported monitor type: {target['type']}")


def main():
    """Main entry point."""

    parser = argparse.ArgumentParser(
        description="Web Monitor - Track table changes and uptime"
    )
    parser.add_argument(
        "--once",
        "-o",
        action="store_true",
        help="Run a single check and exit",
    )
    parser.add_argument(
        "--status",
        "-s",
        action="store_true",
        help="Show monitoring status and recent events",
    )
    parser.add_argument(
        "--test-scrape",
        "-t",
        action="store_true",
        help="Test configured targets without database updates or notifications",
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Send a test email to verify SMTP configuration",
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