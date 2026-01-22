"""Wyze MCP Integration for Home Assistant."""
import logging
import os

import yaml
import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT, CONF_MCP_HOST, CONF_MCP_PORT

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SWITCH, Platform.CLIMATE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Wyze MCP from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data.get(CONF_MCP_HOST, DEFAULT_HOST)
    port = entry.data.get(CONF_MCP_PORT, DEFAULT_PORT)

    # Load devices from yaml
    devices = await hass.async_add_executor_job(load_devices)

    hass.data[DOMAIN][entry.entry_id] = {
        "host": host,
        "port": port,
        "devices": devices,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


def load_devices() -> dict:
    """Load devices from devices.yaml."""
    devices_file = os.path.join(os.path.dirname(__file__), "devices.yaml")
    _LOGGER.info("Loading devices from: %s", devices_file)
    try:
        with open(devices_file, "r") as f:
            devices = yaml.safe_load(f) or {}
            _LOGGER.info("Loaded devices: %s", devices)
            return devices
    except Exception as e:
        _LOGGER.error("Failed to load devices.yaml: %s", e)
        return {}


async def call_mcp_tool(host: str, port: int, tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool via the HTTP API."""
    url = f"http://{host}:{port}/sse"

    # For MCP over SSE, we need to:
    # 1. Connect to /sse to get a session
    # 2. POST to /messages with the tool call

    async with aiohttp.ClientSession() as session:
        # Connect to SSE and get session ID
        async with session.get(url) as resp:
            # Read the first event to get the session endpoint
            async for line in resp.content:
                line = line.decode('utf-8').strip()
                if line.startswith('data:'):
                    import json
                    data = json.loads(line[5:].strip())
                    if 'endpoint' in str(data):
                        # Extract session ID from endpoint
                        # endpoint looks like /messages?sessionId=xxx
                        endpoint = data.get('endpoint', '')
                        if 'sessionId=' in endpoint:
                            session_id = endpoint.split('sessionId=')[1]
                            break

            # Now call the tool
            messages_url = f"http://{host}:{port}/messages?sessionId={session_id}"
            tool_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            async with session.post(messages_url, json=tool_request) as tool_resp:
                return await tool_resp.json()
