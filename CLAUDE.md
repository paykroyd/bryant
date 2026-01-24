# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python CLI tool for monitoring and controlling Bryant Evolution, Carrier Infinity, and ICP Ion HVAC systems via the Carrier cloud API. Uses OAuth 1.0a authentication.

## Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Running
python3 bryant.py status                           # View current status (default)
python3 bryant.py log                              # Single CSV log entry
python3 bryant.py monitor                          # Continuous monitoring (60s default)
python3 bryant.py monitor --interval 300           # Custom interval
python3 bryant.py set-temp --zone 1 --heat 72 --cool 76
python3 bryant.py set-temp --zone 1 --heat 72 --hold-until 18:00
python3 bryant.py set-mode --mode heat             # heat, cool, auto, off, fanonly
```

## Architecture

Single-file implementation (`bryant.py`, ~660 lines):

- **CarrierInfinityClient** - Main class handling OAuth 1.0a authentication and API communication
- **Zone dataclass** - Encapsulates zone data (temp, humidity, setpoints, status)
- **CLI** - argparse-based command interface at bottom of file

## API Details

- **Base URL**: `https://www.app-api.ing.carrier.com`
- **Format**: XML (JSON only for login endpoint)
- **Auth quirk**: OAuth signature uses `http://` in base string even though HTTPS is used
- **Hold state management**: Requires two-step process (turn off then on) with 3-second delay between

## Configuration

Credentials stored in `~/.config/bryant/config.ini`:
```ini
[credentials]
username = your_username
password = your_password
```

## Development Notes

- No test framework configured
- No linting configuration
- Type hints used throughout (Python 3.10+ style)
- CSV logging assumes exactly 2 zones (legacy format)
- Multi-zone support filters by "present" zones only
