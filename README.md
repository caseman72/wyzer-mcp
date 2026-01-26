# Wyzer MCP Server

A Node.js MCP (Model Context Protocol) server that exposes Wyze smart home devices (plugs, switches, thermostats) for control via Claude Desktop or Home Assistant.

## Features

- **Device Discovery**: Automatically discovers all Wyze plugs, switches, and thermostats
- **Combined Devices**: Intelligently combines thermostats and plugs with the same nickname for unified control
- **Online Detection**: Tracks device availability based on last-seen timestamps (2-day threshold)
- **Dual Transport**: Supports both stdio (Claude Desktop) and HTTP/SSE (Home Assistant)
- **Request Logging**: Optional logging of all tool calls for debugging

## Installation

```bash
cd wyzer-mcp
npm install
```

## Configuration

### Wyze Credentials

Wyze API credentials are managed by [@caseman72/wyzer-api](https://github.com/caseman72/wyzer-api) via `.env.local`. The file is searched in:

1. Current working directory
2. `~/.config/wyze/.env.local`
3. `~/.wyze.env.local`

Create a `.env.local` file with your Wyze credentials:

```bash
WYZE_EMAIL=your-wyze-email@example.com
WYZE_PASSWORD_HASH=your-password-md5-hash
WYZE_KEY_ID=your-api-key-id
WYZE_API_KEY=your-api-key
WYZE_AUTH_API_KEY=your-auth-api-key
```

Visit the [Wyze Developer Portal](https://developer-api-console.wyze.com/) to create your API credentials. The password hash is the MD5 hash of your Wyze account password.

### Server Configuration (Optional)

Copy `config.example.json` to `config.json` to customize server settings:

```json
{
  "server": {
    "transport": "stdio",
    "httpPort": 8000,
    "httpHost": "127.0.0.1"
  },
  "devices": {
    "refreshIntervalMinutes": 60
  },
  "monitoring": {
    "enabled": false,
    "logFile": "./wyzer-mcp-requests.log"
  }
}
```

Environment variable overrides:
- `WYZER_HTTP_PORT` - HTTP server port (default: 8000)
- `WYZER_HTTP_HOST` - HTTP server host (default: 127.0.0.1)

## Usage

### stdio Transport (Claude Desktop)

```bash
node src/index.js
```

### HTTP Transport (Home Assistant)

The HA custom component requires the MCP server to be exposed over HTTP/SSE. Use `mcp-proxy` to bridge the stdio server.

#### Install mcp-proxy

```bash
brew install mcp-proxy
```

#### Start the proxy

```bash
# Binds to all interfaces so Docker can reach it
mcp-proxy --port 8081 --host 0.0.0.0 -- node /path/to/wyzer-mcp/src/index.js
```

### Home Assistant Integration

Tested with Home Assistant **2026.1.3**.

1. Copy the custom component to your HA config directory:
   ```bash
   cp -r custom_components/wyzer_mcp ~/.home-assistant/custom_components/
   ```

2. Restart Home Assistant

3. Add the integration: Settings → Devices & Services → Add Integration → "Wyze MCP"

4. Enter connection details:
   - Host: `host.docker.internal` (for Docker) or your Mac's IP
   - Port: `8081`

#### Optional: Card-Mod and Theme

This repo includes a [card-mod](https://github.com/thomasloven/lovelace-card-mod) JS file and a clean theme for customizing the HA frontend. To install:

```bash
# Copy card-mod.js to HA www directory
mkdir -p ~/.home-assistant/www
cp card-mod.js ~/.home-assistant/www/

# Copy the clean theme
mkdir -p ~/.home-assistant/themes
cp themes/clean.yaml ~/.home-assistant/themes/
```

Then add to your `configuration.yaml`:

```yaml
frontend:
  themes: !include_dir_merge_named themes
  extra_module_url:
    - /local/card-mod.js
```

The included `configuration.yaml` shows a complete example with template sensors.

#### Configure Devices

Edit `custom_components/wyzer_mcp/devices.yaml` to define which devices appear in HA:

```yaml
switches:
  # Plugs
  - id: my_plug
    name: My Plug
    device_id: "XXXXXXXXXXXX"    # Wyze device ID (MAC address)
    device_type: plug

  # Wall Switches
  - id: my_switch
    name: My Switch
    device_id: "LD_SS1_XXXXXXXXXXXX"
    device_type: switch

thermostats:
  # Combined thermostat + plug (for space heaters)
  - id: my_thermostat
    name: My Thermostat
    device_id: "combined_CO_EA1_XXXXXXXXXXXXXXXXXXXXXXXX"
    plug_id: "XXXXXXXXXXXX"    # Creates a separate heater switch entity
```

**Notes:**
- Use the device ID (MAC address) rather than nickname for stability
- `device_type` must be `plug` or `switch` to call the correct control API
- For combined thermostats with `plug_id`, a separate "Heater" switch entity is created

#### Entity Types

The integration creates the following entity types:

| Type | Platform | Description |
|------|----------|-------------|
| Plugs | `switch` | On/off control for Wyze plugs |
| Wall Switches | `switch` | On/off control for Wyze wall switches |
| Thermostats | `climate` | Temperature control, HVAC mode |
| Heater Switches | `switch` | On/off control for plug in combined devices |
| API Status | `sensor` | Shows API rate limit info |

#### Device Availability

Devices show as "Unavailable" in HA if they haven't reported to Wyze in over 2 days. This is determined by the RSSI timestamp from the Wyze API.

#### Auto-start mcp-proxy with launchd

Create `~/Library/LaunchAgents/com.wyzer.mcp-proxy.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.wyzer.mcp-proxy</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/mcp-proxy</string>
        <string>--port</string>
        <string>8081</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--</string>
        <string>/opt/homebrew/bin/node</string>
        <string>/path/to/wyzer-mcp/src/index.js</string>
    </array>
    <!-- Required: allows Wyze API to write token cache -->
    <key>WorkingDirectory</key>
    <string>/path/to/wyzer-mcp</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/wyzer-mcp-proxy.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/wyzer-mcp-proxy.err</string>
</dict>
</plist>
```

Then load it:
```bash
launchctl load ~/Library/LaunchAgents/com.wyzer.mcp-proxy.plist
```

To stop/unload:
```bash
launchctl unload ~/Library/LaunchAgents/com.wyzer.mcp-proxy.plist
```

#### Managing the service

```bash
# Check status
launchctl list | grep wyzer

# View logs
tail -f /tmp/wyzer-mcp-proxy.err

# Restart
launchctl unload ~/Library/LaunchAgents/com.wyzer.mcp-proxy.plist
launchctl load ~/Library/LaunchAgents/com.wyzer.mcp-proxy.plist

# Stop
launchctl unload ~/Library/LaunchAgents/com.wyzer.mcp-proxy.plist
```

### Claude Desktop Integration

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "wyzer": {
      "command": "node",
      "args": ["/path/to/wyzer-mcp/src/index.js"],
      "env": {}
    }
  }
}
```

## MCP Tools

### `list_devices`

List all discovered Wyze devices with their current status.

**Parameters:**
- `type` (optional): Filter by device type - `plug`, `switch`, `thermostat`, `combined`, or `all`
- `refresh` (optional): Force refresh device list from Wyze API

### `control_plug`

Turn a Wyze plug on or off.

**Parameters:**
- `deviceId`: Device ID (MAC) or nickname of the plug
- `state`: `on` or `off`

### `control_switch`

Turn a Wyze wall switch on or off.

**Parameters:**
- `deviceId`: Device ID (MAC) or nickname of the switch
- `state`: `on` or `off`

### `control_thermostat`

Control a Wyze thermostat. For combined thermostat+plug devices, `turn_on`/`turn_off` controls the plug (heater power).

**Parameters:**
- `deviceId`: Device ID (MAC) or nickname of the thermostat
- `action`: `set_heat`, `set_cool`, `set_mode`, `turn_on`, or `turn_off`
- `temperature` (optional): Temperature setpoint (required for `set_heat` and `set_cool`)
- `mode` (optional): Thermostat mode (required for `set_mode`) - `heat`, `cool`, `auto`, or `off`

### `get_device_status`

Get detailed status of any Wyze device. Returns online status, last seen timestamp, and current state.

**Parameters:**
- `deviceId`: Device ID (MAC) or nickname of the device

**Response includes:**
- `is_online`: Whether device has reported within 2 days
- `last_seen`: ISO timestamp of last device report
- `rssi`: Signal strength (for plugs)
- `is_on`: Current on/off state
- Temperature/humidity/setpoints (for thermostats)

### `get_api_status`

Get Wyze API rate limit status. Returns remaining calls, reset time, and cache info.

## Combined Devices

When a thermostat and plug share the same nickname (case-insensitive), they are automatically combined into a single "combined" device. This is useful for space heaters controlled by smart plugs with thermostats for temperature sensing.

For combined devices:
- `turn_on`/`turn_off` actions control the plug (heater power)
- `set_heat`/`set_cool`/`set_mode` actions control the thermostat

## Request Monitoring

Enable request logging in config.json:

```json
{
  "monitoring": {
    "enabled": true,
    "logFile": "./wyzer-mcp-requests.log"
  }
}
```

Logs are written in JSON Lines format with timestamps, tool names, parameters, and results.

## License

MIT
