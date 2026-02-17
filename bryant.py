#!/usr/bin/env python3
"""
Bryant/Carrier Infinity HVAC API Client

Connects to the Carrier Infinity API to read HVAC status and control temperature.
Based on the homebridge-carrier-infinity project.
"""

import base64
import configparser
import hashlib
import hmac
import os
import random
import string
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import xml.etree.ElementTree as ET

# Register the Atom namespace to preserve the 'atom' prefix when serializing XML
ET.register_namespace('atom', 'http://www.w3.org/2005/Atom')

import certifi
import requests
import truststore
truststore.inject_into_ssl()

# API Settings (from homebridge-carrier-infinity)
API_BASE_URL = 'https://www.app-api.ing.carrier.com'
CONSUMER_KEY = '8j30j19aj103911h'
CONSUMER_SECRET = '0f5ur7d89sjv8d45'

CONFIG_PATH = os.path.expanduser('~/.config/bryant/config.ini')


def load_config():
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_PATH}\n"
            f"Please create it with [credentials] section containing username and password."
        )
    config.read(CONFIG_PATH)
    return config


def resolve_zone(config, zone_arg: str) -> str:
    """Resolve zone alias to zone ID. Returns the input if no alias found."""
    if config.has_section('zones'):
        for alias, zone_id in config.items('zones'):
            if alias.lower() == zone_arg.lower():
                return zone_id
    return zone_arg


@dataclass
class Zone:
    id: str
    name: str
    temp: float
    humidity: float
    activity: str
    heat_setpoint: float
    cool_setpoint: float
    fan: str
    conditioning: str

    def __str__(self) -> str:
        return (f"{self.name}: {self.temp}°F / {self.humidity}% RH | "
                f"Activity: {self.activity} | Heat: {self.heat_setpoint}°F Cool: {self.cool_setpoint}°F | "
                f"Fan: {self.fan} | Status: {self.conditioning}")


class CarrierInfinityClient:
    """Client for the Carrier Infinity API using OAuth 1.0a authentication."""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.access_token = ''
        self.session = requests.Session()
        self.session.verify = certifi.where()
        self.session.headers.update({
            'featureset': 'CONSUMER_PORTAL',
            'Accept': 'application/xml',
        })
        self._systems: list[str] = []

    def _generate_nonce(self) -> str:
        """Generate a random nonce for OAuth."""
        return base64.b64encode(os.urandom(12)).decode('utf-8')

    def _generate_oauth_signature(self, method: str, url: str, params: dict) -> str:
        """Generate HMAC-SHA1 signature for OAuth 1.0a."""
        # Sort and encode parameters
        sorted_params = sorted(params.items())
        param_string = '&'.join(f'{urllib.parse.quote(str(k), safe="")}={urllib.parse.quote(str(v), safe="")}'
                                for k, v in sorted_params)

        # Create signature base string
        # Note: The API expects http:// in the signature base even though we use https://
        sig_url = 'http://' + url.replace('https://', '').replace('http://', '')
        base_string = '&'.join([
            method.upper(),
            urllib.parse.quote(sig_url, safe=''),
            urllib.parse.quote(param_string, safe='')
        ])

        # Create signing key
        signing_key = f'{CONSUMER_SECRET}&{self.access_token}'

        # Generate signature
        signature = hmac.new(
            signing_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha1
        ).digest()

        return base64.b64encode(signature).decode('utf-8')

    def _get_oauth_header(self, method: str, url: str, body_params: Optional[dict] = None) -> str:
        """Generate the OAuth Authorization header."""
        timestamp = str(int(time.time()))
        nonce = self._generate_nonce()

        oauth_params = {
            'oauth_consumer_key': CONSUMER_KEY,
            'oauth_token': self.username,
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': timestamp,
            'oauth_nonce': nonce,
            'oauth_version': '1.0',
        }

        # Combine with body params for signature
        sig_params = dict(oauth_params)
        if body_params:
            sig_params.update(body_params)

        signature = self._generate_oauth_signature(method, url, sig_params)

        # Build header
        header_parts = [f'realm={urllib.parse.quote(url.replace("https://", "").replace("http://", ""), safe="")}']
        for k, v in oauth_params.items():
            header_parts.append(f'{k}={v}')
        header_parts.append(f'oauth_signature={urllib.parse.quote(signature, safe="")}')

        return 'OAuth ' + ','.join(header_parts)

    def _request(self, method: str, path: str, data: Optional[str] = None,
                 headers: Optional[dict] = None, _retry: bool = True) -> requests.Response:
        """Make an authenticated request to the API.

        Automatically retries with re-authentication on 401/403 errors.
        """
        url = API_BASE_URL + path

        # Parse body params for signature if present
        body_params = None
        if data:
            body_params = {}
            for pair in data.split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    body_params[k] = urllib.parse.unquote(v)

        auth_header = self._get_oauth_header(method, url, body_params)

        req_headers = {'Authorization': auth_header}
        if headers:
            req_headers.update(headers)

        if method.upper() == 'GET':
            resp = self.session.get(url, headers=req_headers)
        else:
            req_headers['Content-Type'] = 'application/x-www-form-urlencoded'
            resp = self.session.post(url, data=data, headers=req_headers)

        # Handle auth failures by re-authenticating and retrying once
        # API returns 401 with "<error>...<message>signature doesn't match</message>..." when token expires
        if resp.status_code == 401 and _retry:
            print('Auth token expired, re-authenticating...')
            if self.login():
                return self._request(method, path, data, headers, _retry=False)

        return resp

    def login(self) -> bool:
        """Authenticate and get access token."""
        print('Logging in...')

        # Build credentials XML
        creds_xml = f'<credentials><username>{self.username}</username><password>{self.password}</password></credentials>'
        data = f'data={urllib.parse.quote(creds_xml)}'

        resp = self._request('POST', '/users/authenticated', data=data,
                             headers={'Accept': 'application/json'})

        if resp.status_code == 200:
            result = resp.json()
            if 'result' in result and 'accessToken' in result['result']:
                self.access_token = result['result']['accessToken']
                print('Login successful!')
                return True
            else:
                print(f'Login failed: {result}')
                return False
        else:
            print(f'Login failed: {resp.status_code} {resp.text}')
            return False

    def activate(self) -> bool:
        """Send activation/keepalive signal."""
        resp = self._request('POST', f'/users/{self.username}/activateSystems',
                             headers={'Accept': 'application/json'})
        return resp.status_code == 200

    def get_systems(self) -> list[str]:
        """Get list of system serial numbers."""
        if self._systems:
            return self._systems

        resp = self._request('GET', f'/users/{self.username}/locations')
        if resp.status_code != 200:
            print(f'Failed to get locations: {resp.status_code}')
            return []

        root = ET.fromstring(resp.text)
        systems = []

        # Parse XML to find system links
        for link in root.iter('{http://www.w3.org/2005/Atom}link'):
            href = link.get('href', '')
            if '/systems/' in href:
                serial = href.split('/systems/')[-1].split('/')[0]
                if serial:
                    systems.append(serial)

        self._systems = systems
        return systems

    def get_status(self, serial: str) -> Optional[ET.Element]:
        """Get system status XML."""
        self.activate()
        resp = self._request('GET', f'/systems/{serial}/status')
        if resp.status_code == 200:
            return ET.fromstring(resp.text)
        return None

    def get_config(self, serial: str) -> Optional[ET.Element]:
        """Get system config XML."""
        self.activate()
        resp = self._request('GET', f'/systems/{serial}/config')
        if resp.status_code == 200:
            return ET.fromstring(resp.text)
        return None

    def get_outdoor_temp(self, serial: str) -> Optional[float]:
        """Get outdoor temperature."""
        status = self.get_status(serial)
        if status is not None:
            oat = status.find('oat')
            if oat is not None and oat.text:
                return float(oat.text)
        return None

    def get_mode(self, serial: str) -> Optional[str]:
        """Get current system mode."""
        status = self.get_status(serial)
        if status is not None:
            mode = status.find('mode')
            if mode is not None:
                raw_mode = mode.text
                # Normalize mode names
                if raw_mode in ('gasheat', 'electric', 'hpheat'):
                    return 'heat'
                elif raw_mode == 'dehumidify':
                    return 'cool'
                return raw_mode
        return None

    def get_profile(self, serial: str) -> Optional[ET.Element]:
        """Get system profile XML."""
        self.activate()
        resp = self._request('GET', f'/systems/{serial}/profile')
        if resp.status_code == 200:
            return ET.fromstring(resp.text)
        return None

    def get_present_zones(self, serial: str) -> set[str]:
        """Get set of zone IDs that are present/configured."""
        profile = self.get_profile(serial)
        if profile is None:
            return set()

        present = set()
        zones_elem = profile.find('zones')
        if zones_elem is not None:
            for z in zones_elem.findall('zone'):
                present_elem = z.find('present')
                if present_elem is not None and present_elem.text == 'on':
                    present.add(z.get('id', ''))
        return present

    def get_zones(self, serial: str) -> list[Zone]:
        """Get all zone information."""
        status = self.get_status(serial)
        config = self.get_config(serial)
        if status is None:
            return []

        # Get which zones are actually present
        present_zones = self.get_present_zones(serial)

        zones = []
        zones_elem = status.find('zones')
        if zones_elem is None:
            return []

        config_zones = {}
        if config is not None:
            config_zones_elem = config.find('zones')
            if config_zones_elem is not None:
                for z in config_zones_elem.findall('zone'):
                    zid = z.get('id', '')
                    name_elem = z.find('name')
                    config_zones[zid] = name_elem.text if name_elem is not None else f'Zone {zid}'

        for zone_elem in zones_elem.findall('zone'):
            zone_id = zone_elem.get('id', '')

            # Skip zones that aren't present
            if present_zones and zone_id not in present_zones:
                continue

            # Get values with defaults
            def get_text(elem_name: str, default: str = '') -> str:
                elem = zone_elem.find(elem_name)
                return elem.text if elem is not None and elem.text else default

            def get_float(elem_name: str, default: float = 0.0) -> float:
                try:
                    return float(get_text(elem_name, str(default)))
                except ValueError:
                    return default

            zone = Zone(
                id=zone_id,
                name=config_zones.get(zone_id, f'Zone {zone_id}'),
                temp=get_float('rt'),
                humidity=get_float('rh'),
                activity=get_text('currentActivity', 'unknown'),
                heat_setpoint=get_float('htsp'),
                cool_setpoint=get_float('clsp'),
                fan=get_text('fan', 'auto'),
                conditioning=get_text('zoneconditioning', 'idle'),
            )
            zones.append(zone)

        return zones

    def set_temperature(self, serial: str, zone_id: str, heat_setpoint: Optional[float] = None,
                        cool_setpoint: Optional[float] = None, hold_until: Optional[str] = None) -> bool:
        """
        Set temperature setpoints for a zone.

        Args:
            serial: System serial number
            zone_id: Zone ID (e.g., '1', '2')
            heat_setpoint: Heating setpoint in Fahrenheit (optional)
            cool_setpoint: Cooling setpoint in Fahrenheit (optional)
            hold_until: Hold until time in HH:MM format, or empty for indefinite hold

        Returns:
            True if successful, False otherwise
        """
        config = self.get_config(serial)
        if config is None:
            print('Failed to get current config')
            return False

        # Find the zone
        zones_elem = config.find('zones')
        if zones_elem is None:
            print('No zones found in config')
            return False

        zone_elem = None
        for z in zones_elem.findall('zone'):
            if z.get('id') == zone_id:
                zone_elem = z
                break

        if zone_elem is None:
            print(f'Zone {zone_id} not found')
            return False

        # Find or create manual activity settings
        activities = zone_elem.find('activities')
        if activities is None:
            print('No activities found')
            return False

        manual_activity = None
        for act in activities.findall('activity'):
            if act.get('id') == 'manual':
                manual_activity = act
                break

        if manual_activity is None:
            print('Manual activity not found')
            return False

        # Check if hold is already on - if so, we need to clear it first
        # The thermostat only reads holdActivity when hold transitions from off to on
        hold = zone_elem.find('hold')
        if hold is None:
            hold = ET.SubElement(zone_elem, 'hold')

        was_hold_on = hold.text == 'on'

        if was_hold_on:
            # First, turn off hold to reset the state
            hold.text = 'off'
            # Also clear holdActivity
            hold_activity_elem = zone_elem.find('holdActivity')
            if hold_activity_elem is not None:
                hold_activity_elem.text = ''

            xml_str = '<?xml version="1.0"?>' + ET.tostring(config, encoding='unicode')
            data = f'data={urllib.parse.quote(xml_str, safe="")}'
            resp = self._request('POST', f'/systems/{serial}/config', data=data)

            if resp.status_code != 200:
                print(f'Failed to clear hold: {resp.status_code}')
                return False

            # Wait for thermostat to process the hold=off change
            time.sleep(3)

            # Re-fetch config to get fresh state with new timestamp
            config = self.get_config(serial)
            if config is None:
                print('Failed to get config after clearing hold')
                return False

            # Re-find the zone and elements
            zones_elem = config.find('zones')
            zone_elem = None
            for z in zones_elem.findall('zone'):
                if z.get('id') == zone_id:
                    zone_elem = z
                    break

            activities = zone_elem.find('activities')
            manual_activity = None
            for act in activities.findall('activity'):
                if act.get('id') == 'manual':
                    manual_activity = act
                    break

            hold = zone_elem.find('hold')

        # Now set the new values - holdActivity element may exist but be empty
        hold_activity = zone_elem.find('holdActivity')
        if hold_activity is None:
            hold_activity = ET.SubElement(zone_elem, 'holdActivity')
        hold_activity.text = 'manual'

        # Update setpoints on the freshly fetched config
        if heat_setpoint is not None:
            htsp = manual_activity.find('htsp')
            if htsp is None:
                htsp = ET.SubElement(manual_activity, 'htsp')
            htsp.text = f'{heat_setpoint:.1f}'

        if cool_setpoint is not None:
            clsp = manual_activity.find('clsp')
            if clsp is None:
                clsp = ET.SubElement(manual_activity, 'clsp')
            clsp.text = f'{cool_setpoint:.1f}'

        otmr = zone_elem.find('otmr')
        if otmr is None:
            otmr = ET.SubElement(zone_elem, 'otmr')
        otmr.text = hold_until or ''

        # Enable hold
        hold.text = 'on'

        # Update timestamp
        timestamp_elem = config.find('timestamp')
        if timestamp_elem is not None:
            timestamp_elem.text = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + f'{datetime.now(timezone.utc).microsecond // 1000:03d}Z'

        # Push the config
        xml_str = '<?xml version="1.0"?>' + ET.tostring(config, encoding='unicode')
        data = f'data={urllib.parse.quote(xml_str, safe="")}'

        resp = self._request('POST', f'/systems/{serial}/config', data=data)

        if resp.status_code == 200:
            # Call activate to trigger thermostat sync
            self.activate()
            print(f'Temperature set successfully for zone {zone_id}')
            return True
        else:
            print(f'Failed to set temperature: {resp.status_code} {resp.text}')
            return False

    def set_mode(self, serial: str, mode: str) -> bool:
        """
        Set system mode.

        Args:
            serial: System serial number
            mode: One of 'off', 'cool', 'heat', 'auto', 'fanonly'

        Returns:
            True if successful, False otherwise
        """
        config = self.get_config(serial)
        if config is None:
            print('Failed to get current config')
            return False

        mode_elem = config.find('mode')
        if mode_elem is not None:
            mode_elem.text = mode

        # Update timestamp
        timestamp_elem = config.find('timestamp')
        if timestamp_elem is not None:
            timestamp_elem.text = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + f'{datetime.now(timezone.utc).microsecond // 1000:03d}Z'

        xml_str = '<?xml version="1.0"?>' + ET.tostring(config, encoding='unicode')
        data = f'data={urllib.parse.quote(xml_str, safe="")}'

        resp = self._request('POST', f'/systems/{serial}/config', data=data)

        if resp.status_code == 200:
            print(f'Mode set to {mode}')
            return True
        else:
            print(f'Failed to set mode: {resp.status_code} {resp.text}')
            return False


def print_status(client: CarrierInfinityClient):
    """Print current HVAC status."""
    systems = client.get_systems()
    if not systems:
        print('No systems found')
        return

    for serial in systems:
        print(f'\n=== System: {serial} ===')

        outdoor_temp = client.get_outdoor_temp(serial)
        if outdoor_temp is not None:
            print(f'Outdoor Temperature: {outdoor_temp}°F')

        mode = client.get_mode(serial)
        if mode:
            print(f'Mode: {mode}')

        zones = client.get_zones(serial)
        print(f'\nZones ({len(zones)}):')
        for zone in zones:
            print(f'  {zone}')


def update_csv(client: CarrierInfinityClient, filename: str = 'hvac_status.csv'):
    """Update CSV file with current status (legacy compatible format)."""
    systems = client.get_systems()
    if not systems:
        return

    serial = systems[0]
    outdoor_temp = client.get_outdoor_temp(serial)
    zones = client.get_zones(serial)

    if len(zones) < 2:
        print('Expected at least 2 zones')
        return

    z1, z2 = zones[0], zones[1]
    timestamp = datetime.now().strftime('%m-%d-%Y %H:%M')

    values = [
        timestamp,
        str(int(outdoor_temp)) if outdoor_temp else '',
        z1.name, str(int(z1.temp)), z1.conditioning, z1.activity,
        str(int(z1.heat_setpoint)), str(int(z1.cool_setpoint)),
        z2.name, str(int(z2.temp)), z2.conditioning, z2.activity,
        str(int(z2.heat_setpoint)), str(int(z2.cool_setpoint)),
    ]

    with open(filename, 'a') as f:
        f.write(','.join(values) + '\n')

    print(f'Logged: {timestamp} | Outdoor: {outdoor_temp}°F | '
          f'{z1.name}: {z1.temp}°F | {z2.name}: {z2.temp}°F')


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Bryant/Carrier Infinity HVAC Controller')
    parser.add_argument('command', nargs='?', default='status',
                        choices=['status', 'log', 'monitor', 'set-temp', 'set-mode'],
                        help='Command to run')
    parser.add_argument('--zone', type=str, default='1', help='Zone ID for set-temp')
    parser.add_argument('--heat', type=float, help='Heat setpoint (°F)')
    parser.add_argument('--cool', type=float, help='Cool setpoint (°F)')
    parser.add_argument('--mode', type=str, choices=['off', 'cool', 'heat', 'auto', 'fanonly'],
                        help='System mode for set-mode')
    parser.add_argument('--hold-until', type=str, help='Hold until time (HH:MM) or empty for indefinite')
    parser.add_argument('--interval', type=int, default=60, help='Polling interval in seconds for monitor')
    parser.add_argument('--csv', type=str, default='hvac_status.csv', help='CSV file for logging')

    args = parser.parse_args()

    # Load config
    config = load_config()
    username = config.get('credentials', 'username')
    password = config.get('credentials', 'password')

    # Create client and login
    client = CarrierInfinityClient(username, password)
    if not client.login():
        print('Failed to login')
        return 1

    systems = client.get_systems()
    if not systems:
        print('No systems found')
        return 1

    serial = systems[0]

    if args.command == 'status':
        print_status(client)

    elif args.command == 'log':
        update_csv(client, args.csv)

    elif args.command == 'monitor':
        print(f'Monitoring HVAC status every {args.interval} seconds. Press Ctrl+C to stop.')
        try:
            while True:
                update_csv(client, args.csv)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print('\nStopped.')

    elif args.command == 'set-temp':
        if args.heat is None and args.cool is None:
            print('Please specify --heat and/or --cool setpoint')
            return 1
        zone_id = resolve_zone(config, args.zone)
        client.set_temperature(serial, zone_id, args.heat, args.cool, args.hold_until)

    elif args.command == 'set-mode':
        if args.mode is None:
            print('Please specify --mode')
            return 1
        client.set_mode(serial, args.mode)

    return 0


if __name__ == '__main__':
    sys.exit(main())
