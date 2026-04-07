"""
Email notification module for sending alerts and summary reports.
"""

import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Tuple

import config
from scraper import TableRow

logger = logging.getLogger(__name__)


@dataclass
class ChangeDetails:
    """Details about a detected table change."""

    name: str
    url: str
    old_row_count: int
    new_row_count: int
    new_rows: List[TableRow]


@dataclass
class UptimeAlertDetails:
    """Details about a detected uptime issue or recovery."""

    name: str
    url: str
    status_code: Optional[int]
    error_message: Optional[str]
    event_type: str


def get_default_recipients() -> List[str]:
    """Return the configured fallback recipients."""

    recipients = getattr(config, "DEFAULT_RECIPIENT_EMAILS", None)
    if recipients is None:
        recipients = getattr(config, "RECIPIENT_EMAILS", [])
    return list(dict.fromkeys(recipients))


def get_target_recipients(target: Dict) -> List[str]:
    """Return recipients assigned to a target."""

    return list(dict.fromkeys(target.get("recipients") or get_default_recipients()))


def group_targets_by_recipients(monitored_targets: List[Dict]) -> Dict[Tuple[str, ...], List[Dict]]:
    """Group monitor targets so each recipient set gets one summary email."""

    grouped_targets: Dict[Tuple[str, ...], List[Dict]] = {}

    for target in monitored_targets:
        recipients = tuple(get_target_recipients(target))
        if not recipients:
            logger.warning("No recipients configured for monitor target: %s", target["name"])
            continue
        grouped_targets.setdefault(recipients, []).append(target)

    return grouped_targets


def group_targets_by_recipient(monitored_targets: List[Dict]) -> Dict[str, List[Dict]]:
    """Group monitor targets so each recipient has a single target list."""

    grouped_targets: Dict[str, List[Dict]] = {}

    for target in monitored_targets:
        recipients = get_target_recipients(target)
        if not recipients:
            logger.warning("No recipients configured for monitor target: %s", target["name"])
            continue

        for recipient in recipients:
            grouped_targets.setdefault(recipient, []).append(target)

    return grouped_targets


def format_target_label(target: Dict) -> str:
    """Return a human-readable label for the target type."""

    if target["type"] == "table":
        return f"Table monitor ({target.get('table_id', 'no table_id')})"
    return "Uptime monitor"


def format_change_email(change: ChangeDetails) -> str:
    """Format the email body for a table change notification."""

    row_diff = change.new_row_count - change.old_row_count
    diff_text = f"{row_diff:+d}"

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #2c5aa0;">Web Monitor Alert: Change Detected</h2>

        <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <p><strong>Page:</strong> {change.name}</p>
            <p><strong>URL:</strong> <a href="{change.url}">{change.url}</a></p>
            <p><strong>Row Count Change:</strong> {change.old_row_count} -&gt; {change.new_row_count} ({diff_text})</p>
        </div>
    """

    if change.new_rows:
        html += """
        <h3 style="color: #2c5aa0;">New or Updated Rows</h3>
        <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
            <thead>
                <tr style="background-color: #2c5aa0; color: white;">
                    <th style="padding: 10px; border: 1px solid #ddd;">Doc Name</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Link</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Type</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Date</th>
                </tr>
            </thead>
            <tbody>
        """

        for row in change.new_rows:
            if row.file_link.startswith("http"):
                link_html = f'<a href="{row.file_link}">Download</a>'
            else:
                link_html = row.file_link

            html += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">{row.doc_name}</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{link_html}</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{row.doc_type}</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{row.date}</td>
                </tr>
            """

        html += """
            </tbody>
        </table>
        """

    html += """
        <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
        <p style="color: #666; font-size: 12px;">
            This is an automated notification from Web Monitor.<br>
            Visit the URL above to view the full page.
        </p>
    </body>
    </html>
    """

    return html


def format_uptime_email(alert: UptimeAlertDetails) -> str:
    """Format the email body for an uptime notification."""

    heading = "Uptime Issue Detected" if alert.event_type == "down" else "Uptime Restored"
    accent_color = "#c0392b" if alert.event_type == "down" else "#1e8449"
    status_text = alert.error_message or (f"HTTP {alert.status_code}" if alert.status_code else "Request failed")

    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: {accent_color};">{heading}</h2>

        <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <p><strong>Site:</strong> {alert.name}</p>
            <p><strong>URL:</strong> <a href="{alert.url}">{alert.url}</a></p>
            <p><strong>Status:</strong> {status_text}</p>
        </div>

        <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
        <p style="color: #666; font-size: 12px;">
            This is an automated notification from Web Monitor.
        </p>
    </body>
    </html>
    """


def send_email(subject: str, body_html: str, recipients: Optional[List[str]] = None) -> bool:
    """Send an email notification."""

    if recipients is None:
        recipients = get_default_recipients()

    if not recipients:
        logger.warning("No recipients configured for email notification")
        return False

    if not config.SMTP_SERVER or not config.SMTP_USERNAME or not config.SMTP_PASSWORD or not config.SENDER_EMAIL:
        logger.warning("SMTP not configured - skipping email notification")
        logger.info("Would have sent email: %s", subject)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.SENDER_EMAIL
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body_html, "html"))

        if config.SMTP_USE_TLS:
            server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT)

        server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        server.sendmail(config.SENDER_EMAIL, recipients, msg.as_string())
        server.quit()

        logger.info("Email sent successfully to %s recipient(s)", len(recipients))
        return True
    except smtplib.SMTPException as exc:
        logger.error("SMTP error sending email: %s", exc)
        return False
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return False


def notify_change_for_target(change: ChangeDetails, recipients: List[str]) -> bool:
    """Send a table change notification to the recipients assigned to a target."""

    subject = f"[Web Monitor] Change Detected: {change.name}"
    body = format_change_email(change)
    return send_email(subject, body, recipients)


def notify_uptime(alert: UptimeAlertDetails, recipients: List[str]) -> bool:
    """Send an uptime alert or recovery notification."""

    if alert.event_type == "down":
        subject = f"[Web Monitor] Uptime Alert: {alert.name}"
    else:
        subject = f"[Web Monitor] Uptime Restored: {alert.name}"

    body = format_uptime_email(alert)
    return send_email(subject, body, recipients)


def send_test_email() -> bool:
    """Send a test email to verify configuration."""

    subject = "[Web Monitor] Test Email"
    body = """
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2>Web Monitor Test Email</h2>
        <p>This is a test email to verify your SMTP configuration is working correctly.</p>
        <p>If you received this email, your notification system is properly configured.</p>
    </body>
    </html>
    """
    return send_email(subject, body)


def send_greeting_email(monitored_targets: List[Dict], check_interval: int) -> bool:
    """Send one startup email per recipient listing that recipient's targets."""

    from datetime import datetime

    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    interval_text = f"{check_interval // 60} minutes" if check_interval >= 60 else f"{check_interval} seconds"
    sent_any = False

    for recipient, targets in group_targets_by_recipient(monitored_targets).items():
        targets_html = ""
        for target in targets:
            targets_html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;">{target['name']}</td>
                <td style="padding: 8px; border: 1px solid #ddd;"><a href="{target['url']}">{target['url']}</a></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{format_target_label(target)}</td>
            </tr>
            """

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #2c5aa0;">Web Monitor Started</h2>

            <div style="background-color: #e8f4e8; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #4CAF50;">
                <p style="margin: 0;"><strong>Monitoring is now active.</strong></p>
                <p style="margin: 5px 0 0 0;">Started at: {start_time}</p>
            </div>

            <h3 style="color: #2c5aa0;">Configuration</h3>
            <ul>
                <li><strong>Check Interval:</strong> {interval_text}</li>
                <li><strong>Targets Monitored:</strong> {len(targets)}</li>
            </ul>

            <h3 style="color: #2c5aa0;">Assigned Targets</h3>
            <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
                <thead>
                    <tr style="background-color: #2c5aa0; color: white;">
                        <th style="padding: 10px; border: 1px solid #ddd;">Name</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">URL</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">Type</th>
                    </tr>
                </thead>
                <tbody>
                    {targets_html}
                </tbody>
            </table>

            <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
            <p style="color: #666; font-size: 12px;">
                You will receive notifications only for the targets listed in this email.
            </p>
        </body>
        </html>
        """

        subject = f"[Web Monitor] Monitoring Started - {len(targets)} target(s)"
        sent_any = send_email(subject, body, [recipient]) or sent_any

    return sent_any


def format_daily_report(target_summaries: List[dict], start_time: str, end_time: str) -> str:
    """Format the daily summary report email."""

    total_checks = sum(summary["checks"] for summary in target_summaries)
    total_alerts = sum(len(summary["events"]) for summary in target_summaries)

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #2c5aa0;">Web Monitor Daily Report</h2>

        <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <p><strong>Report Period:</strong> {start_time} - {end_time}</p>
            <p><strong>Total Checks:</strong> {total_checks}</p>
            <p><strong>Total Alerts:</strong> {total_alerts}</p>
        </div>
    """

    for summary in target_summaries:
        html += f"""
        <div style="margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 6px;">
            <h3 style="color: #2c5aa0; margin-top: 0;">{summary['name']}</h3>
            <p><strong>URL:</strong> <a href="{summary['url']}">{summary['url']}</a></p>
            <p><strong>Type:</strong> {summary['type'].title()}</p>
            <p><strong>Checks:</strong> {summary['checks']}</p>
        """

        if summary["type"] == "uptime":
            uptime_percentage = 0.0
            if summary["checks"]:
                uptime_percentage = (summary["up_checks"] / summary["checks"]) * 100
            html += f"""
            <p><strong>Up Checks:</strong> {summary['up_checks']}</p>
            <p><strong>Down Checks:</strong> {summary['down_checks']}</p>
            <p><strong>Uptime:</strong> {uptime_percentage:.2f}%</p>
            """
        else:
            html += f"""
            <p><strong>Successful Checks:</strong> {summary['successful_checks']}</p>
            <p><strong>Failed Checks:</strong> {summary['failed_checks']}</p>
            <p><strong>Changes Detected:</strong> {summary['change_count']}</p>
            """

        if summary["events"]:
            html += """
            <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
                <thead>
                    <tr style="background-color: #2c5aa0; color: white;">
                        <th style="padding: 10px; border: 1px solid #ddd;">Time</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">Event</th>
                    </tr>
                </thead>
                <tbody>
            """
            for event in summary["events"]:
                html += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">{event['time']}</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{event['summary']}</td>
                </tr>
                """
            html += """
                </tbody>
            </table>
            """
        else:
            html += """
            <p style="color: #666;">No alerts for this target during the report window.</p>
            """

        html += """
        </div>
        """

    html += """
        <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
        <p style="color: #666; font-size: 12px;">
            This is an automated daily report from Web Monitor.
        </p>
    </body>
    </html>
    """

    return html


def send_daily_reports(monitored_targets: List[Dict], daily_stats: Dict[str, dict],
                       start_time: str, end_time: str) -> int:
    """Send daily summary reports batched so each recipient gets one email."""

    from datetime import datetime

    date_str = datetime.now().strftime("%Y-%m-%d")
    sent_count = 0

    for recipient, targets in group_targets_by_recipient(monitored_targets).items():
        target_summaries = [daily_stats[target["id"]] for target in targets if target["id"] in daily_stats]
        if not target_summaries:
            continue

        total_checks = sum(summary["checks"] for summary in target_summaries)
        total_alerts = sum(len(summary["events"]) for summary in target_summaries)
        subject = f"[Web Monitor] Daily Report - {date_str} ({total_alerts} alerts, {total_checks} checks)"
        body = format_daily_report(target_summaries, start_time, end_time)
        if send_email(subject, body, [recipient]):
            sent_count += 1

    return sent_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Sending test email...")
    send_test_email()