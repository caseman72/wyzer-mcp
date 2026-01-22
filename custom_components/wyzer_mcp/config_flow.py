"""Config flow for Wyze MCP integration."""
import logging
import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DEFAULT_HOST, DEFAULT_PORT, CONF_MCP_HOST, CONF_MCP_PORT

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_MCP_HOST, default=DEFAULT_HOST): str,
    vol.Required(CONF_MCP_PORT, default=DEFAULT_PORT): int,
})


async def validate_connection(host: str, port: int) -> bool:
    """Test if we can connect to the MCP SSE endpoint."""
    try:
        async with aiohttp.ClientSession() as session:
            # Connect to SSE endpoint - if we get a response, it's working
            async with session.get(
                f"http://{host}:{port}/sse",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                # SSE endpoint returns 200 and starts streaming
                return resp.status == 200
    except Exception as e:
        _LOGGER.error("Failed to connect to MCP server: %s", e)
        return False


class WyzeMcpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wyze MCP."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_MCP_HOST]
            port = user_input[CONF_MCP_PORT]

            if await validate_connection(host, port):
                return self.async_create_entry(
                    title="Wyze MCP",
                    data=user_input
                )
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )
