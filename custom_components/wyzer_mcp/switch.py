"""Switch platform for Wyze MCP."""
import logging
import json
import asyncio
from datetime import timedelta

import aiohttp

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

SCAN_INTERVAL = timedelta(seconds=30)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wyze MCP switches from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    devices = data.get("devices", {})
    host = data["host"]
    port = data["port"]

    entities = []
    switches = devices.get("switches", [])
    _LOGGER.debug("Setting up %d switches from config", len(switches))
    for switch_config in switches:
        _LOGGER.debug("Adding switch: %s", switch_config)
        entities.append(
            WyzeMcpSwitch(
                switch_id=switch_config["id"],
                name=switch_config["name"],
                device_id=switch_config["device_id"],
                device_type=switch_config.get("device_type", "plug"),
                host=host,
                port=port,
            )
        )

    # Add heater switches for combined thermostat devices
    thermostats = devices.get("thermostats", [])
    for thermo_config in thermostats:
        if thermo_config.get("plug_id"):
            _LOGGER.debug("Adding heater switch for: %s", thermo_config["name"])
            entities.append(
                WyzeMcpHeaterSwitch(
                    switch_id=f"{thermo_config['id']}_heater",
                    name=f"{thermo_config['name']} Heater",
                    device_id=thermo_config["device_id"],
                    plug_id=thermo_config["plug_id"],
                    host=host,
                    port=port,
                )
            )

    _LOGGER.debug("Adding %d entities to HA", len(entities))
    async_add_entities(entities)


class WyzeMcpSwitch(SwitchEntity):
    """A switch entity that controls a Wyze plug via MCP."""

    _attr_should_poll = True

    def __init__(self, switch_id: str, name: str, device_id: str, device_type: str, host: str, port: int):
        """Initialize the switch."""
        self._switch_id = switch_id
        self._attr_name = name
        self._device_id = device_id
        self._device_type = device_type  # "plug" or "switch"
        self._host = host
        self._port = port
        self._attr_unique_id = f"wyzer_mcp_{switch_id}"
        self._attr_is_on = None
        self._attr_available = True

    async def async_added_to_hass(self) -> None:
        """Fetch initial state when entity is added to HA."""
        _LOGGER.debug("Entity added to HA: %s", self._attr_name)
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
                    async with session.post(messages_url, json=notif_request) as notif_resp:
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

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        tool = "control_switch" if self._device_type == "switch" else "control_plug"
        result = await self._call_tool(tool, {
            "deviceId": self._device_id,
            "state": "on"
        })
        if result and "error" not in result:
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        tool = "control_switch" if self._device_type == "switch" else "control_plug"
        result = await self._call_tool(tool, {
            "deviceId": self._device_id,
            "state": "off"
        })
        if result and "error" not in result:
            self._attr_is_on = False
            self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch the current state."""
        _LOGGER.debug("async_update called for %s", self._attr_name)
        result = await self._call_tool("get_device_status", {
            "deviceId": self._device_id
        })
        _LOGGER.debug("MCP result for %s: %s", self._attr_name, result)
        if result and "error" not in result:
            # Check online status
            is_online = result.get("is_online")
            if is_online is not None:
                self._attr_available = is_online

            # Check each key explicitly - can't use 'or' because False is falsy
            state = result.get("is_on")
            if state is None:
                state = result.get("switch_state")
            if state is None:
                state = result.get("state")
            if state is not None:
                self._attr_is_on = state in (True, "on", 1, "1")

            _LOGGER.debug("Updated %s state: %s, available: %s", self._attr_name, self._attr_is_on, self._attr_available)


class WyzeMcpHeaterSwitch(SwitchEntity):
    """A switch entity that controls the heater plug in a combined thermostat device."""

    _attr_should_poll = True
    _attr_icon = "mdi:radiator"

    def __init__(self, switch_id: str, name: str, device_id: str, plug_id: str, host: str, port: int):
        """Initialize the heater switch."""
        self._switch_id = switch_id
        self._attr_name = name
        self._device_id = device_id  # Combined device ID
        self._plug_id = plug_id
        self._host = host
        self._port = port
        self._attr_unique_id = f"wyzer_mcp_{switch_id}"
        self._attr_is_on = None
        self._attr_available = True

    async def async_added_to_hass(self) -> None:
        """Fetch initial state when entity is added to HA."""
        _LOGGER.debug("Heater entity added to HA: %s", self._attr_name)
        await super().async_added_to_hass()
        self.async_schedule_update_ha_state(True)

    async def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool via HTTP/SSE using aiohttp."""
        base_url = f"http://{self._host}:{self._port}"

        _LOGGER.debug("Calling MCP tool %s with %s", tool_name, arguments)

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
                            _LOGGER.error("MCP initialize failed: %s", await init_resp.text())
                            return None

                    await asyncio.sleep(0.1)

                    notif_request = {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized"
                    }
                    async with session.post(messages_url, json=notif_request) as notif_resp:
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
                            _LOGGER.error("MCP tool call failed: %s", await tool_resp.text())
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

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the heater on."""
        result = await self._call_tool("control_thermostat", {
            "deviceId": self._device_id,
            "action": "turn_on"
        })
        if result and "error" not in result:
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the heater off."""
        result = await self._call_tool("control_thermostat", {
            "deviceId": self._device_id,
            "action": "turn_off"
        })
        if result and "error" not in result:
            self._attr_is_on = False
            self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch the current state."""
        result = await self._call_tool("get_device_status", {
            "deviceId": self._device_id
        })
        if result and "error" not in result:
            # Get plug status from combined device
            plug_data = result.get("plug", {})

            is_online = plug_data.get("is_online")
            if is_online is not None:
                self._attr_available = is_online

            is_on = plug_data.get("is_on")
            if is_on is not None:
                self._attr_is_on = is_on in (True, "on", 1, "1")
