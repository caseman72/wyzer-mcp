"""Fan platform for Wyze MCP air purifiers."""
import logging
import json
import asyncio
from datetime import timedelta

import aiohttp

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

SCAN_INTERVAL = timedelta(seconds=60)

_LOGGER = logging.getLogger(__name__)

PRESET_MODES = ["auto", "sleep", "min", "mid", "max", "turbo"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wyze MCP air purifier fans from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    devices = data.get("devices", {})
    host = data["host"]
    port = data["port"]

    entities = []
    purifiers = devices.get("purifiers", [])
    _LOGGER.debug("Setting up %d purifiers from config", len(purifiers))
    for purifier_config in purifiers:
        _LOGGER.debug("Adding purifier: %s", purifier_config)
        entities.append(
            WyzeMcpPurifierFan(
                purifier_id=purifier_config["id"],
                name=purifier_config["name"],
                device_id=purifier_config["device_id"],
                host=host,
                port=port,
            )
        )

    async_add_entities(entities)


class WyzeMcpPurifierFan(FanEntity):
    """A fan entity that controls a Wyze air purifier via MCP."""

    _attr_should_poll = True
    _attr_icon = "mdi:air-purifier"
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = PRESET_MODES

    def __init__(self, purifier_id: str, name: str, device_id: str, host: str, port: int):
        """Initialize the purifier fan."""
        self._purifier_id = purifier_id
        self._attr_name = name
        self._device_id = device_id
        self._host = host
        self._port = port
        self._attr_unique_id = f"wyzer_mcp_{purifier_id}"
        self._attr_is_on = None
        self._attr_preset_mode = None
        self._attr_available = True
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        """Fetch initial state when entity is added to HA."""
        _LOGGER.debug("Purifier entity added to HA: %s", self._attr_name)
        await super().async_added_to_hass()
        self.async_schedule_update_ha_state(True)

    async def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool via HTTP/SSE using aiohttp."""
        base_url = f"http://{self._host}:{self._port}"

        _LOGGER.debug("Calling MCP tool %s with %s", tool_name, arguments)

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Connect to SSE endpoint to get session ID
                async with session.get(f"{base_url}/sse") as sse_resp:
                    session_id = None

                    # Read SSE events to find the endpoint
                    async for line in sse_resp.content:
                        line = line.decode('utf-8').strip()
                        if line.startswith('data:'):
                            data = line[5:].strip()
                            # Handle both JSON and plain string formats
                            if data.startswith('/messages/'):
                                # Plain endpoint string: /messages/?session_id=xxx
                                if 'session_id=' in data:
                                    session_id = data.split('session_id=')[1]
                                    break
                            else:
                                # Try JSON format
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

                    # Initialize the session
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
                            _LOGGER.error("MCP initialize failed: %s", await init_resp.text())
                            return None

                    # Wait for init response via SSE
                    await asyncio.sleep(0.1)

                    # Send initialized notification
                    notif_request = {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized"
                    }
                    async with session.post(messages_url, json=notif_request):
                        pass

                    # Call the tool
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
                            _LOGGER.error("MCP tool call failed: %s", await tool_resp.text())
                            return None

                    # Read the response from SSE stream
                    async for line in sse_resp.content:
                        line = line.decode('utf-8').strip()
                        if line.startswith('data:'):
                            try:
                                data = json.loads(line[5:].strip())
                                # Look for the tool result (id: 2)
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

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs) -> None:
        """Turn the purifier on, optionally with a preset mode."""
        arguments = {
            "deviceId": self._device_id,
            "state": "on"
        }
        if preset_mode:
            arguments["fanMode"] = preset_mode
        result = await self._call_tool("control_purifier", arguments)
        if result and "error" not in result:
            self._attr_is_on = True
            if preset_mode:
                self._attr_preset_mode = preset_mode
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the purifier off."""
        result = await self._call_tool("control_purifier", {
            "deviceId": self._device_id,
            "state": "off"
        })
        if result and "error" not in result:
            self._attr_is_on = False
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the purifier fan mode."""
        result = await self._call_tool("control_purifier", {
            "deviceId": self._device_id,
            "fanMode": preset_mode
        })
        if result and "error" not in result:
            self._attr_preset_mode = preset_mode
            self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch the current state."""
        _LOGGER.debug("async_update called for %s", self._attr_name)
        result = await self._call_tool("get_device_status", {
            "deviceId": self._device_id
        })
        _LOGGER.debug("MCP result for %s: %s", self._attr_name, result)
        if result and "error" not in result:
            is_online = result.get("is_online")
            if is_online is not None:
                self._attr_available = is_online

            is_on = result.get("is_on")
            if is_on is not None:
                self._attr_is_on = is_on in (True, "on", 1, "1")

            fan_mode = result.get("fan_mode")
            if fan_mode in PRESET_MODES:
                self._attr_preset_mode = fan_mode

            self._attr_extra_state_attributes = {
                "aqi": result.get("aqi"),
            }
