# Web Monitor

A Python-based monitoring tool that tracks HTML table changes and uptime, then sends email notifications to the recipients assigned to each target.

## Features

- Table monitoring for HTML tables identified by `table_id`
- Uptime monitoring that treats only HTTP 200 as up
- Per-target recipient lists so different sites notify different people
- Daily summary emails with per-target checks, alerts, and uptime or downtime totals
- SQLite-backed monitor state and event history
- Configurable check intervals and graceful shutdown handling

## Installation

```bash
cd web-monitor
pip install -r requirements.txt
```

## Configuration

Edit `config.py` to set up SMTP and monitor targets.

### SMTP Settings

```python
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "your_email@gmail.com"
SMTP_PASSWORD = "your_app_password"
SMTP_USE_TLS = True

SENDER_EMAIL = "your_email@gmail.com"
DEFAULT_RECIPIENT_EMAILS = ["fallback@example.com"]
```

For Gmail with 2FA, use an app password.

### Monitor Targets

Use `MONITORED_TARGETS` to mix table monitors and uptime-only monitors:

```python
MONITORED_TARGETS = [
    {
        "url": "https://example.com/procurement",
        "table_id": "documents-table",
        "name": "Procurement Documents",
        "type": "table",
        "recipients": ["procurement@example.com"],
    },
    {
        "url": "https://status.example.com/health",
        "name": "Public Status Page",
        "type": "uptime",
        "recipients": ["ops@example.com"],
    },
]
```

`type="table"` requires `table_id` and watches the table row count for changes.

`type="uptime"` only checks whether the URL returns HTTP 200.

### Other Settings

```python
CHECK_INTERVAL = 300
DAILY_REPORT_ENABLED = True
DAILY_REPORT_TIME = "18:00"
DATABASE_PATH = "monitor_state.db"
LOG_FILE = "monitor.log"
```

## Usage

### Test Configured Targets

```bash
python monitor.py --test-scrape
```

### Test Email

```bash
python monitor.py --test-email
```

### Run Once

```bash
python monitor.py --once
```

### View Status

```bash
python monitor.py --status
```

### Continuous Monitoring

```bash
python monitor.py
```

Recipients receive notifications only for the targets assigned to them.

At the configured daily report time, each recipient group receives a summary covering only its own targets.

## Monitor Types

### Table Monitors

The current implementation expects a target table with four columns:

1. Doc Name
2. Link
3. Type
4. Date

Table alerts are triggered when the row count changes.

### Uptime Monitors

Uptime monitors request the URL and treat only HTTP 200 as up.

If the target returns any other status code, or the request fails entirely, Web Monitor sends an alert immediately.

When the target returns to HTTP 200, Web Monitor sends a recovery notification.

The daily report includes total checks, up checks, down checks, and uptime percentage for each uptime target.

## Files

| File | Description |
|------|-------------|
| `config.py` | SMTP settings, monitor targets, and runtime configuration |
| `scraper.py` | Table extraction, uptime checks, and target normalization |
| `notifier.py` | Immediate alerts, startup emails, and daily reports |
| `database.py` | SQLite persistence for current monitor state and event history |
| `monitor.py` | Main runtime loop and CLI entrypoint |
| `requirements.txt` | Python dependencies |

## Troubleshooting

### Table not found

- Verify the configured `table_id`
- The page may require JavaScript rendering, which this tool does not support

### SMTP not configured

- Fill in real SMTP values in `config.py`
- For Gmail, use an app password instead of your normal password

### Too many uptime failures in the daily report

- Immediate uptime emails are sent on state transitions only: when a site goes down, and when it recovers
- The daily report still shows the full up and down check counts for the report window

## Requirements

- Python 3.8+
- Internet connection
- SMTP email account