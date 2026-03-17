# Web Monitor

A Python-based web monitoring tool that tracks changes in web page tables and sends email notifications when changes are detected.

## Features

- **Table Monitoring**: Tracks HTML tables by ID and detects row count changes
- **Email Notifications**: Sends formatted HTML email alerts when changes occur
- **Change History**: SQLite database stores all detected changes for review
- **Multiple URLs**: Monitor multiple pages with different table IDs
- **Configurable Intervals**: Set your own check frequency
- **Graceful Shutdown**: Handles SIGINT/SIGTERM for clean stops

## Installation

```bash
# Clone or download this repository
cd web-monitor

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Edit `config.py` to set up your monitoring:

### SMTP Email Settings

Fill in your email server credentials:

```python
SMTP_SERVER = "smtp.gmail.com"             # Your SMTP server
SMTP_PORT = 587                             # Port (587 for TLS, 465 for SSL)
SMTP_USERNAME = "your_email@gmail.com"      # Your email
SMTP_PASSWORD = "your_app_password"         # App-specific password
SMTP_USE_TLS = True                         # Use TLS encryption

SENDER_EMAIL = "your_email@gmail.com"
RECIPIENT_EMAILS = ["recipient@example.com"]
```

**Note for Gmail users**: You'll need to create an [App Password](https://support.google.com/accounts/answer/185833) if you have 2FA enabled.

### Monitored URLs

Add or modify the URLs to monitor:

```python
MONITORED_URLS = [
    {
        "url": "https://www.scf3.sebrae.com.br/PortalCf/Licitacoes/Detalhe?Id=14581",
        "table_id": "tblArquivosLicitacao",
        "name": "Sebrae Licitacao 14581",
    },
    # Add more URLs here
]
```

### Other Settings

```python
CHECK_INTERVAL = 300    # Check every 5 minutes (in seconds)
DATABASE_PATH = "monitor_state.db"
LOG_FILE = "monitor.log"
```

## Usage

### Test Scraping

Test that the scraper can access the page and extract table data:

```bash
python monitor.py --test-scrape
```

### Test Email

Verify your SMTP configuration:

```bash
python monitor.py --test-email
```

### Run Once

Perform a single check and exit:

```bash
python monitor.py --once
```

### View Status

Show monitored pages and recent changes:

```bash
python monitor.py --status
```

### Continuous Monitoring

Run the monitor continuously:

```bash
python monitor.py
```

To stop, press `Ctrl+C` or send SIGTERM.

### Run as Background Service

```bash
# Using nohup
nohup python monitor.py > /dev/null 2>&1 &

# Or with screen
screen -S webmonitor
python monitor.py
# Press Ctrl+A, D to detach
```

## Table Structure

The monitor expects the table (`tblArquivosLicitacao`) to have 4 columns:
1. **Doc Name** - Document name/title
2. **Link** - Link to download the file
3. **Type** - Type of document
4. **Date** - Publication date

## Files

| File | Description |
|------|-------------|
| `config.py` | Configuration settings (SMTP, URLs, intervals) |
| `scraper.py` | Web scraping module using BeautifulSoup |
| `notifier.py` | Email notification module using SMTP |
| `database.py` | SQLite database for storing page states |
| `monitor.py` | Main monitoring script |
| `requirements.txt` | Python dependencies |

## Email Notification Example

When a change is detected, you'll receive an email like:

> **🔔 Web Monitor Alert: Change Detected**
>
> **Page:** Sebrae Licitacao 14581  
> **URL:** https://www.scf3.sebrae.com.br/PortalCf/Licitacoes/Detalhe?Id=14581  
> **Row Count Change:** 5 → 7 (+2)
>
> | Doc Name | Link | Type | Date |
> |----------|------|------|------|
> | New Document 1 | [Download] | PDF | 2024-01-20 |
> | New Document 2 | [Download] | PDF | 2024-01-20 |

## Requirements

- Python 3.8+
- Internet connection
- SMTP email account (Gmail, Outlook, etc.)

## Troubleshooting

### "Table not found" error
- Verify the table ID is correct using browser Developer Tools
- The page might require JavaScript rendering (not supported)

### "SMTP not configured" warning
- Fill in real values in `config.py`
- For Gmail, use an App Password instead of your regular password

### No changes detected
- First run always records the current state
- Changes are only detected on subsequent runs

## License

MIT License - Feel free to use and modify as needed.
