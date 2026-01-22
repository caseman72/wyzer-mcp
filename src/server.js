import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import {
  discoverDevices,
  getAllDevices,
  findDevice,
  findPlug,
  findSwitch,
  findThermostat,
  findCombined,
  getDeviceStatus,
  controlPlug,
  controlSwitch,
  controlThermostat,
  controlCombinedDevice,
  getDeviceCache
} from './device-manager.js';
import { getWyzeClient } from './wyze-client.js';
import { createToolWrapper } from './request-monitor.js';

export function createMcpServer() {
  const server = new McpServer({
    name: 'wyzer-mcp',
    version: '1.0.0'
  });

  // Tool: list_devices
  server.tool(
    'list_devices',
    'List all discovered Wyze devices with their current status. Optionally filter by device type.',
    {
      type: z.enum(['plug', 'switch', 'thermostat', 'combined', 'all']).optional()
        .describe('Filter devices by type. Defaults to "all".'),
      refresh: z.boolean().optional()
        .describe('Force refresh device list from Wyze API')
    },
    createToolWrapper('list_devices', async ({ type = 'all', refresh = false }) => {
      await discoverDevices(refresh);
      const cache = getDeviceCache();

      let devices = [];
      if (type === 'all') {
        devices = getAllDevices();
      } else if (type === 'plug') {
        devices = cache.plugs;
      } else if (type === 'switch') {
        devices = cache.switches;
      } else if (type === 'thermostat') {
        devices = cache.thermostats;
      } else if (type === 'combined') {
        devices = cache.combined;
      }

      const deviceList = devices.map(d => ({
        id: d.id,
        nickname: d.nickname,
        type: d.type,
        is_online: d.is_online,
        ...(d.type === 'combined' ? {
          thermostat_id: d.thermostat.id,
          plug_id: d.plug.id
        } : {})
      }));

      return {
        content: [{
          type: 'text',
          text: JSON.stringify({
            count: deviceList.length,
            devices: deviceList,
            lastRefresh: cache.lastRefresh ? new Date(cache.lastRefresh).toISOString() : null
          }, null, 2)
        }]
      };
    })
  );

  // Tool: control_plug
  server.tool(
    'control_plug',
    'Turn a Wyze plug on or off. Use device ID or nickname to identify the plug.',
    {
      deviceId: z.string().describe('Device ID (MAC) or nickname of the plug'),
      state: z.enum(['on', 'off']).describe('Desired state: "on" or "off"')
    },
    createToolWrapper('control_plug', async ({ deviceId, state }) => {
      await discoverDevices();
      const plug = findPlug(deviceId);

      if (!plug) {
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({ error: `Plug not found: ${deviceId}` })
          }],
          isError: true
        };
      }

      const result = await controlPlug(plug, state);
      return {
        content: [{
          type: 'text',
          text: JSON.stringify(result, null, 2)
        }]
      };
    })
  );

  // Tool: control_switch
  server.tool(
    'control_switch',
    'Turn a Wyze wall switch on or off. Use device ID or nickname to identify the switch.',
    {
      deviceId: z.string().describe('Device ID (MAC) or nickname of the switch'),
      state: z.enum(['on', 'off']).describe('Desired state: "on" or "off"')
    },
    createToolWrapper('control_switch', async ({ deviceId, state }) => {
      await discoverDevices();
      const switchDevice = findSwitch(deviceId);

      if (!switchDevice) {
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({ error: `Switch not found: ${deviceId}` })
          }],
          isError: true
        };
      }

      const result = await controlSwitch(switchDevice, state);
      return {
        content: [{
          type: 'text',
          text: JSON.stringify(result, null, 2)
        }]
      };
    })
  );

  // Tool: control_thermostat
  server.tool(
    'control_thermostat',
    'Control a Wyze thermostat. For combined thermostat+plug devices, "turn_on"/"turn_off" controls the plug (heater power). Temperature actions control the thermostat.',
    {
      deviceId: z.string().describe('Device ID (MAC) or nickname of the thermostat'),
      action: z.enum(['set_heat', 'set_cool', 'set_mode', 'turn_on', 'turn_off'])
        .describe('Action to perform. turn_on/turn_off only work for combined devices.'),
      temperature: z.number().optional()
        .describe('Temperature setpoint (required for set_heat and set_cool)'),
      mode: z.enum(['heat', 'cool', 'auto', 'off']).optional()
        .describe('Thermostat mode (required for set_mode)')
    },
    createToolWrapper('control_thermostat', async ({ deviceId, action, temperature, mode }) => {
      await discoverDevices();

      // Check if this is a combined device first
      const combined = findCombined(deviceId);
      if (combined) {
        const result = await controlCombinedDevice(combined, action, { temperature, mode });
        return {
          content: [{
            type: 'text',
            text: JSON.stringify(result, null, 2)
          }]
        };
      }

      // Check for standalone thermostat
      const thermostat = findThermostat(deviceId);
      if (!thermostat) {
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({ error: `Thermostat not found: ${deviceId}` })
          }],
          isError: true
        };
      }

      // turn_on/turn_off only work for combined devices
      if (action === 'turn_on' || action === 'turn_off') {
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              error: `${action} is only supported for combined thermostat+plug devices. This thermostat does not have an associated plug.`
            })
          }],
          isError: true
        };
      }

      const result = await controlThermostat(thermostat, action, { temperature, mode });
      return {
        content: [{
          type: 'text',
          text: JSON.stringify(result, null, 2)
        }]
      };
    })
  );

  // Tool: get_device_status
  server.tool(
    'get_device_status',
    'Get detailed status of any Wyze device. Returns temperature, humidity, setpoints for thermostats; on/off state for plugs and switches.',
    {
      deviceId: z.string().describe('Device ID (MAC) or nickname of the device')
    },
    createToolWrapper('get_device_status', async ({ deviceId }) => {
      await discoverDevices();
      const device = findDevice(deviceId);

      if (!device) {
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({ error: `Device not found: ${deviceId}` })
          }],
          isError: true
        };
      }

      const status = await getDeviceStatus(device);
      return {
        content: [{
          type: 'text',
          text: JSON.stringify(status, null, 2)
        }]
      };
    })
  );

  // Tool: get_api_status
  server.tool(
    'get_api_status',
    'Get Wyze API rate limit status and key expiration. Returns remaining calls, reset time, cache info, and API key expiration.',
    {},
    createToolWrapper('get_api_status', async () => {
      const wyze = await getWyzeClient();
      const rateLimit = wyze.getRateLimitStatus();
      const apiKeyExpiry = wyze.checkApiKeyExpiry();
      const cache = getDeviceCache();

      return {
        content: [{
          type: 'text',
          text: JSON.stringify({
            rate_limit: {
              remaining: rateLimit.remaining,
              reset_by: rateLimit.resetBy ? new Date(rateLimit.resetBy).toISOString() : null,
              reset_in_seconds: rateLimit.resetIn ? Math.ceil(rateLimit.resetIn / 1000) : null
            },
            api_key: {
              expires: apiKeyExpiry.expires,
              days_remaining: apiKeyExpiry.daysRemaining,
              is_expired: apiKeyExpiry.isExpired,
              is_expiring_soon: apiKeyExpiry.isExpiringSoon
            },
            cache: {
              last_refresh: cache.lastRefresh ? new Date(cache.lastRefresh).toISOString() : null,
              device_count: getAllDevices().length
            }
          }, null, 2)
        }]
      };
    })
  );

  return server;
}
