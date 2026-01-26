"""Climate platform for Wyze MCP thermostats."""
import logging
import json
import asyncio
from datetime import timedelta

import aiohttp

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

SCAN_INTERVAL = timedelta(seconds=30)

_LOGGER = logging.getLogger(__name__)

HVAC_MODE_MAP = {
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "auto": HVACMode.HEAT_COOL,
    "off": HVACMode.OFF,
}

HVAC_MODE_REVERSE = {v: k for k, v in HVAC_MODE_MAP.items()}

HVAC_ACTION_MAP = {
    "heating": HVACAction.HEATING,
    "cooling": HVACAction.COOLING,
    "idle": HVACAction.IDLE,
    "off": HVACAction.OFF,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wyze MCP thermostats from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    devices = data.get("devices", {})
    host = data["host"]
    port = data["port"]

    entities = []
    thermostats = devices.get("thermostats", [])
    _LOGGER.info("Setting up %d thermostats from config", len(thermostats))
    for thermostat_config in thermostats:
        _LOGGER.info("Adding thermostat: %s", thermostat_config)
        plug_id = thermostat_config.get("plug_id")
        entities.append(
            WyzeMcpThermostat(
                thermostat_id=thermostat_config["id"],
                name=thermostat_config["name"],
                device_id=thermostat_config["device_id"],
                host=host,
                port=port,
                is_combined=plug_id is not None,
                plug_id=plug_id,
            )
        )

    _LOGGER.info("Adding %d climate entities to HA", len(entities))
    async_add_entities(entities)


class WyzeMcpThermostat(ClimateEntity):
    """A climate entity that controls a Wyze thermostat via MCP."""

    _attr_should_poll = True
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT

    def __init__(self, thermostat_id: str, name: str, device_id: str, host: str, port: int, is_combined: bool = False, plug_id: str = None):
        """Initialize the thermostat."""
        self._thermostat_id = thermostat_id
        self._attr_name = name
        self._device_id = device_id
        self._host = host
        self._port = port
        self._is_combined = is_combined
        self._plug_id = plug_id
        self._attr_unique_id = f"wyzer_mcp_{thermostat_id}"

        # State attributes
        self._attr_current_temperature = None
        self._attr_current_humidity = None
        self._attr_target_temperature = None
        self._attr_target_temperature_high = None
        self._attr_target_temperature_low = None
        self._attr_hvac_mode = None
        self._attr_hvac_action = None
        self._is_online = None  # Track thermostat connectivity

    @property
    def available(self) -> bool:
        """Return True if entity is available (thermostat is connected)."""
        # If we haven't fetched state yet, assume available
        if self._is_online is None:
            return True
        return self._is_online

    async def async_added_to_hass(self) -> None:
        """Fetch initial state when entity is added to HA."""
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

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        mode = HVAC_MODE_REVERSE.get(hvac_mode, "off")
        result = await self._call_tool("control_thermostat", {
            "deviceId": self._device_id,
            "action": "set_mode",
            "mode": mode
        })
        if result and "error" not in result:
            self._attr_hvac_mode = hvac_mode
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        if ATTR_TEMPERATURE in kwargs:
            temp = kwargs[ATTR_TEMPERATURE]
            result = await self._call_tool("control_thermostat", {
                "deviceId": self._device_id,
                "action": "set_heat",
                "temperature": temp
            })
            if result and "error" not in result:
                self._attr_target_temperature = temp
                self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch the current state."""
        result = await self._call_tool("get_device_status", {
            "deviceId": self._device_id
        })
        if result and "error" not in result:
            # Handle combined device (nested thermostat data) or direct thermostat
            thermo_data = result.get("thermostat", result)
            plug_data = result.get("plug", {})

            # Track thermostat connectivity for availability
            self._is_online = thermo_data.get("is_online", True)

            # Current temperature and humidity
            self._attr_current_temperature = thermo_data.get("temperature")
            self._attr_current_humidity = thermo_data.get("humidity")

            # HVAC mode
            mode = thermo_data.get("mode", "off")
            self._attr_hvac_mode = HVAC_MODE_MAP.get(mode, HVACMode.OFF)

            # HVAC action (what it's currently doing)
            working_state = thermo_data.get("working_state", "idle")
            self._attr_hvac_action = HVAC_ACTION_MAP.get(working_state, HVACAction.IDLE)

            # Temperature setpoints
            heat_setpoint = thermo_data.get("heat_setpoint")
            self._attr_target_temperature = heat_setpoint

            # Temperature unit
            temp_unit = thermo_data.get("temp_unit", "F")
            if temp_unit == "C":
                self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            else:
                self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT

            _LOGGER.debug(
                "Updated %s: temp=%s, mode=%s, action=%s, target=%s",
                self._attr_name,
                self._attr_current_temperature,
                self._attr_hvac_mode,
                self._attr_hvac_action,
                self._attr_target_temperature
            )
