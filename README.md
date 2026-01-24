# Bryant/Carrier Infinity HVAC Controller

A Python CLI tool for monitoring and controlling Bryant Evolution, Carrier Infinity, and ICP Ion HVAC systems via the Carrier cloud API.

## Features

- View current temperatures, humidity, and system status
- Monitor and log HVAC data to CSV for historical analysis
- Control temperature setpoints with hold functionality
- Set system mode (heat, cool, auto, off, fan only)
- Multi-zone support

## Requirements

- Python 3.10+
- A Bryant/Carrier/ICP account with a connected thermostat

## Installation

1. Clone the repository and set up a virtual environment:

```bash
cd bryant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create your configuration file:

```bash
mkdir -p ~/.config/bryant
cat > ~/.config/bryant/config.ini << 'EOF'
[credentials]
username = your_username
password = your_password
EOF
```

Use the same credentials you use to log into:
- Bryant: https://www.myevolutionconnex.bryant.com
- Carrier: https://www.myinfinitytouch.carrier.com
- ICP: https://www.ioncomfort.com

## Usage

### View Status

```bash
python3 bryant.py status
```

Output:
```
=== System: 5219W105864 ===
Outdoor Temperature: 19.0°F
Mode: heat

Zones (2):
  Upstairs: 70.0°F / 39.0% RH | Activity: home | Heat: 70.0°F Cool: 76.0°F | Fan: off | Status: idle
  Downstairs: 69.0°F / 39.0% RH | Activity: home | Heat: 69.0°F Cool: 76.0°F | Fan: off | Status: active_heat
```

### Log to CSV

Single log entry:
```bash
python3 bryant.py log
```

Continuous monitoring (default: every 60 seconds):
```bash
python3 bryant.py monitor
python3 bryant.py monitor --interval 300  # every 5 minutes
```

### Set Temperature

Set heating setpoint for zone 1 (Upstairs):
```bash
python3 bryant.py set-temp --zone 1 --heat 72
```

Set both heating and cooling setpoints:
```bash
python3 bryant.py set-temp --zone 2 --heat 68 --cool 76
```

Set with a hold until specific time:
```bash
python3 bryant.py set-temp --zone 1 --heat 72 --hold-until 18:00
```

### Set System Mode

```bash
python3 bryant.py set-mode --mode heat
python3 bryant.py set-mode --mode cool
python3 bryant.py set-mode --mode auto
python3 bryant.py set-mode --mode off
python3 bryant.py set-mode --mode fanonly
```

## Command Reference

| Command | Description |
|---------|-------------|
| `status` | Display current system status (default) |
| `log` | Append one reading to CSV file |
| `monitor` | Continuously log readings |
| `set-temp` | Set temperature setpoints |
| `set-mode` | Set system mode |

### Options

| Option | Description |
|--------|-------------|
| `--zone ID` | Zone ID (1, 2, etc.) for set-temp |
| `--heat TEMP` | Heating setpoint in °F |
| `--cool TEMP` | Cooling setpoint in °F |
| `--mode MODE` | System mode: off, heat, cool, auto, fanonly |
| `--hold-until HH:MM` | Hold until time (omit for indefinite) |
| `--interval SECS` | Polling interval for monitor (default: 60) |
| `--csv FILE` | CSV output file (default: hvac_status.csv) |

## CSV Format

The CSV file contains the following columns:

```
timestamp, outdoor_temp, zone1_name, zone1_temp, zone1_status, zone1_activity, zone1_heat_sp, zone1_cool_sp, zone2_name, zone2_temp, zone2_status, zone2_activity, zone2_heat_sp, zone2_cool_sp
```

Example:
```
01-23-2026 23:08,19,Upstairs,70,idle,home,70,76,Downstairs,69,active_heat,home,69,76
```

## API Details

This tool uses the Carrier Infinity API with OAuth 1.0a authentication. It's based on the reverse-engineering work done by the [homebridge-carrier-infinity](https://github.com/grivkees/homebridge-carrier-infinity) project.

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/users/authenticated` | Login and get access token |
| `/users/{username}/locations` | List systems |
| `/users/{username}/activateSystems` | Keepalive signal |
| `/systems/{serial}/profile` | System info, zone configuration |
| `/systems/{serial}/status` | Real-time temperatures and status |
| `/systems/{serial}/config` | Configuration (read/write) |

## Troubleshooting

### SSL Certificate Errors

If you see SSL certificate errors, make sure you have the required packages:

```bash
pip install certifi truststore
```

### Login Failed

- Verify your credentials at the Bryant/Carrier/ICP web portal
- Check that your config file is at `~/.config/bryant/config.ini`
- Ensure username and password have no extra whitespace

### No Systems Found

- Make sure your thermostat is registered and connected to your account
- Try logging into the web portal to verify the connection

## License

MIT
