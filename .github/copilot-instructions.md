# Web Monitor Project

## Overview
This is a Python-based web monitoring tool that tracks changes in web pages (specifically table data) and sends email notifications when changes are detected.

## Project Structure
- `config.py` - Configuration settings including SMTP email credentials (placeholders)
- `scraper.py` - Web scraping module using BeautifulSoup
- `notifier.py` - Email notification module using SMTP
- `database.py` - SQLite database for storing page states
- `monitor.py` - Main monitoring script
- `requirements.txt` - Python dependencies

## Running the Monitor
```bash
# Install dependencies
pip install -r requirements.txt

# Run the monitor
python monitor.py
```

## Configuration
Edit `config.py` to set up:
- SMTP email settings (server, port, username, password)
- Email recipients
- Monitored URLs

## Development Guidelines
- Use Python 3.8+
- Follow PEP 8 style guidelines
- Handle exceptions gracefully
- Log all monitoring activity
