"""
Email notification module for sending alerts when changes are detected.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from dataclasses import dataclass

import config
from scraper import TableData, TableRow

logger = logging.getLogger(__name__)


@dataclass
class ChangeDetails:
    """Details about a detected change."""
    name: str
    url: str
    old_row_count: int
    new_row_count: int
    new_rows: List[TableRow]


def format_change_email(change: ChangeDetails) -> str:
    """
    Format the email body for a change notification.
    
    Args:
        change: The change details
        
    Returns:
        Formatted HTML email body
    """
    row_diff = change.new_row_count - change.old_row_count
    diff_text = f"+{row_diff}" if row_diff > 0 else str(row_diff)
    
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #2c5aa0;">🔔 Web Monitor Alert: Change Detected</h2>
        
        <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <p><strong>Page:</strong> {change.name}</p>
            <p><strong>URL:</strong> <a href="{change.url}">{change.url}</a></p>
            <p><strong>Row Count Change:</strong> {change.old_row_count} → {change.new_row_count} ({diff_text})</p>
        </div>
    """
    
    if change.new_rows:
        html += """
        <h3 style="color: #2c5aa0;">New/Updated Rows:</h3>
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
            link_html = f'<a href="{row.file_link}">Download</a>' if row.file_link.startswith('http') else row.file_link
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


def send_email(subject: str, body_html: str, recipients: Optional[List[str]] = None) -> bool:
    """
    Send an email notification.
    
    Args:
        subject: Email subject line
        body_html: HTML email body
        recipients: List of recipient emails (uses config default if not provided)
        
    Returns:
        True if email was sent successfully, False otherwise
    """
    if recipients is None:
        recipients = config.RECIPIENT_EMAILS
    
    if not recipients:
        logger.warning("No recipients configured for email notification")
        return False
    
    # Check if SMTP is configured with real values
    if "example.com" in config.SMTP_SERVER or "your_" in config.SMTP_USERNAME:
        logger.warning("SMTP not configured - skipping email notification")
        logger.info(f"Would have sent email: {subject}")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = config.SENDER_EMAIL
        msg['To'] = ', '.join(recipients)
        
        # Attach HTML body
        msg.attach(MIMEText(body_html, 'html'))
        
        # Connect and send
        if config.SMTP_USE_TLS:
            server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(config.SMTP_SERVER, config.SMTP_PORT)
        
        server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        server.sendmail(config.SENDER_EMAIL, recipients, msg.as_string())
        server.quit()
        
        logger.info(f"Email sent successfully to {len(recipients)} recipient(s)")
        return True
        
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending email: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def notify_change(change: ChangeDetails) -> bool:
    """
    Send a notification about a detected change.
    
    Args:
        change: The change details
        
    Returns:
        True if notification was sent successfully
    """
    subject = f"[Web Monitor] Change Detected: {change.name}"
    body = format_change_email(change)
    return send_email(subject, body)


def notify_changes(changes: List[ChangeDetails]) -> int:
    """
    Send notifications for multiple changes.
    
    Args:
        changes: List of change details
        
    Returns:
        Number of notifications sent successfully
    """
    sent_count = 0
    for change in changes:
        if notify_change(change):
            sent_count += 1
    return sent_count


def send_test_email() -> bool:
    """Send a test email to verify configuration."""
    subject = "[Web Monitor] Test Email"
    body = """
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2>🧪 Web Monitor Test Email</h2>
        <p>This is a test email to verify your SMTP configuration is working correctly.</p>
        <p>If you received this email, your notification system is properly configured!</p>
    </body>
    </html>
    """
    return send_email(subject, body)


def send_greeting_email(monitored_urls: List[dict], check_interval: int) -> bool:
    """
    Send a greeting email when the monitor starts.
    
    Args:
        monitored_urls: List of URLs being monitored
        check_interval: Check interval in seconds
        
    Returns:
        True if sent successfully
    """
    from datetime import datetime
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    urls_html = ""
    for url_config in monitored_urls:
        urls_html += f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">{url_config['name']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;"><a href="{url_config['url']}">{url_config['url'][:50]}...</a></td>
            <td style="padding: 8px; border: 1px solid #ddd;">{url_config['table_id']}</td>
        </tr>
        """
    
    interval_text = f"{check_interval // 60} minutes" if check_interval >= 60 else f"{check_interval} seconds"
    
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #2c5aa0;">👋 Web Monitor Started</h2>
        
        <div style="background-color: #e8f4e8; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #4CAF50;">
            <p style="margin: 0;"><strong>✅ Monitoring is now active!</strong></p>
            <p style="margin: 5px 0 0 0;">Started at: {start_time}</p>
        </div>
        
        <h3 style="color: #2c5aa0;">Configuration:</h3>
        <ul>
            <li><strong>Check Interval:</strong> {interval_text}</li>
            <li><strong>Pages Monitored:</strong> {len(monitored_urls)}</li>
        </ul>
        
        <h3 style="color: #2c5aa0;">Monitored Pages:</h3>
        <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
            <thead>
                <tr style="background-color: #2c5aa0; color: white;">
                    <th style="padding: 10px; border: 1px solid #ddd;">Name</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">URL</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Table ID</th>
                </tr>
            </thead>
            <tbody>
                {urls_html}
            </tbody>
        </table>
        
        <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
        <p style="color: #666; font-size: 12px;">
            You will receive notifications when changes are detected.<br>
            To stop monitoring, terminate the script on the server.
        </p>
    </body>
    </html>
    """
    
    subject = f"[Web Monitor] 👋 Monitoring Started - {len(monitored_urls)} page(s)"
    return send_email(subject, body)


def format_daily_report(check_count: int, change_count: int, changes_details: List[dict],
                        start_time: str, end_time: str) -> str:
    """
    Format the daily summary report email.
    
    Args:
        check_count: Total number of checks performed today
        change_count: Total number of changes detected today
        changes_details: List of change details for the day
        start_time: When monitoring started
        end_time: Current time (report time)
        
    Returns:
        Formatted HTML email body
    """
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #2c5aa0;">📊 Web Monitor Daily Report</h2>
        
        <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <p><strong>Report Period:</strong> {start_time} - {end_time}</p>
            <p><strong>Total Checks:</strong> {check_count}</p>
            <p><strong>Changes Detected:</strong> {change_count}</p>
        </div>
    """
    
    if change_count == 0:
        html += """
        <p style="color: #666;">✅ No changes were detected during this monitoring period.</p>
        """
    else:
        html += f"""
        <h3 style="color: #2c5aa0;">Changes Summary ({change_count} total):</h3>
        <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
            <thead>
                <tr style="background-color: #2c5aa0; color: white;">
                    <th style="padding: 10px; border: 1px solid #ddd;">Time</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Page</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Change</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for change in changes_details:
            diff = change['new_count'] - change['old_count']
            diff_text = f"+{diff}" if diff > 0 else str(diff)
            html += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">{change['time']}</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{change['name']}</td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{change['old_count']} → {change['new_count']} ({diff_text} rows)</td>
                </tr>
            """
        
        html += """
            </tbody>
        </table>
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


def send_daily_report(check_count: int, change_count: int, changes_details: List[dict],
                      start_time: str, end_time: str) -> bool:
    """
    Send the daily summary report.
    
    Args:
        check_count: Total checks performed
        change_count: Total changes detected
        changes_details: List of change details
        start_time: Monitoring start time
        end_time: Report time
        
    Returns:
        True if sent successfully
    """
    from datetime import datetime
    date_str = datetime.now().strftime('%Y-%m-%d')
    subject = f"[Web Monitor] Daily Report - {date_str} ({change_count} changes, {check_count} checks)"
    body = format_daily_report(check_count, change_count, changes_details, start_time, end_time)
    return send_email(subject, body)


if __name__ == "__main__":
    # Test email sending
    logging.basicConfig(level=logging.INFO)
    print("Sending test email...")
    send_test_email()
