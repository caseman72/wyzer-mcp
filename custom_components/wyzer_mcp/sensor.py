"""Sensor platform for Wyze MCP API status."""
import logging
import json
import asyncio
from datetime import timedelta, datetime

import aiohttp

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

SCAN_INTERVAL = timedelta(seconds=60)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wyze MCP sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    host = data["host"]
    port = data["port"]

    entities = [
        WyzeMcpApiRateSensor(host, port),
        WyzeMcpApiExpirationSensor(host, port),
    ]

    async_add_entities(entities)


class WyzeMcpBaseSensor(SensorEntity):
    """Base class for Wyze MCP sensors."""

    _attr_should_poll = True

    def __init__(self, host: str, port: int):
        """Initialize the sensor."""
        self._host = host
        self._port = port
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        """Fetch initial state when entity is added to HA."""
        await super().async_added_to_hass()
        self.async_schedule_update_ha_state(True)

    async def _call_tool(self, tool_name: str, arguments: dict = None) -> dict:
        """Call an MCP tool via HTTP/SSE using aiohttp."""
        base_url = f"http://{self._host}:{self._port}"
        arguments = arguments or {}

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{base_url}/sse") as sse_resp:
                    session_id = None

                    async for line in sse_resp.content:
                        line = line.decode('utf-8').strip()
                        if line.startswith('data:'):
                            data = line[5:].strip()
                            if data.startswith('/messages/'):
                                if 'session_id=' in data:
                                    session_id = data.split('session_id=')[1]
                                    break
                            else:
                                try:
                                    parsed = json.loads(data)
                                    if isinstance(parsed, dict):
                                        endpoint = parsed.get('endpoint', '')
                                        if 'session_id=' in endpoint:
                                            session_id = endpoint.split('session_id=')[1]
                                            break
                                except json.JSONDecodeError:
                                    continue

                    if not session_id:
                        _LOGGER.error("Failed to get MCP session ID")
                        return None

                    messages_url = f"{base_url}/messages/?session_id={session_id}"

                    init_request = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "ha-wyzer-mcp", "version": "1.0.0"}
                        }
                    }

                    async with session.post(messages_url, json=init_request) as init_resp:
                        if init_resp.status != 202:
                            return None

                    await asyncio.sleep(0.1)

                    notif_request = {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized"
                    }
                    async with session.post(messages_url, json=notif_request):
                        pass

                    tool_request = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": tool_name,
                            "arguments": arguments
                        }
                    }

                    async with session.post(messages_url, json=tool_request) as tool_resp:
                        if tool_resp.status != 202:
                            return None

                    async for line in sse_resp.content:
                        line = line.decode('utf-8').strip()
                        if line.startswith('data:'):
                            try:
                                data = json.loads(line[5:].strip())
                                if isinstance(data, dict) and data.get('id') == 2:
                                    result = data.get('result', {})
                                    content = result.get('content', [])
                                    for item in content:
                                        if item.get('type') == 'text':
                                            return json.loads(item.get('text', '{}'))
                                    return result
                            except json.JSONDecodeError:
                                continue

                    return None

        except asyncio.TimeoutError:
            _LOGGER.error("MCP tool call timed out")
            return None
        except Exception as e:
            _LOGGER.error("MCP tool call failed: %s", e)
            return None


class WyzeMcpApiRateSensor(WyzeMcpBaseSensor):
    """Sensor showing Wyze API rate limit status."""

    _attr_name = "Wyze API Rate Status"
    _attr_unique_id = "wyzer_mcp_api_rate_status"
    _attr_icon = "mdi:api"

    async def async_update(self) -> None:
        """Fetch the current API status."""
        result = await self._call_tool("get_api_status")

        if result and "error" not in result:
            rate_limit = result.get("rate_limit", {})
            cache = result.get("cache", {})

            remaining = rate_limit.get("remaining")
            reset_in = rate_limit.get("reset_in_seconds")

            # Main value is remaining calls
            self._attr_native_value = remaining

            # Additional attributes
            self._attr_extra_state_attributes = {
                "remaining_calls": remaining,
                "reset_by": rate_limit.get("reset_by"),
                "reset_in_seconds": reset_in,
                "reset_in_minutes": round(reset_in / 60, 1) if reset_in else None,
                "cache_last_refresh": cache.get("last_refresh"),
                "cached_device_count": cache.get("device_count"),
            }


class WyzeMcpApiExpirationSensor(WyzeMcpBaseSensor):
    """Sensor showing Wyze API key expiration."""

    _attr_name = "Wyze API Expiration"
    _attr_unique_id = "wyzer_mcp_api_expiration"
    _attr_icon = "mdi:calendar-clock"

    async def async_update(self) -> None:
        """Fetch the current API key expiration."""
        result = await self._call_tool("get_api_status")

        if result and "error" not in result:
            api_key = result.get("api_key", {})

            expires = api_key.get("expires")
            days_remaining = api_key.get("days_remaining")

            # Main value is days remaining
            self._attr_native_value = days_remaining

            # Additional attributes
            self._attr_extra_state_attributes = {
                "expires": expires,
                "days_remaining": days_remaining,
                "is_expired": api_key.get("is_expired"),
                "is_expiring_soon": api_key.get("is_expiring_soon"),
            }
