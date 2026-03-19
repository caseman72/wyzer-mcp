import { getWyzeClient } from './wyze-client.js';
import { getConfig } from './config.js';

const DEVICE_TYPES = {
  PLUG: 'Plug',
  SWITCH: 'Common',
  THERMOSTAT: 'Thermostat'
};

let deviceCache = {
  plugs: [],
  switches: [],
  thermostats: [],
  combined: [],
  lastRefresh: null
};

function normalizeNickname(nickname) {
  return (nickname || '').toLowerCase().trim();
}

function shouldRefresh() {
  if (!deviceCache.lastRefresh) return true;
  const config = getConfig();
  const refreshInterval = config.devices.refreshIntervalMinutes * 60 * 1000;
  return Date.now() - deviceCache.lastRefresh > refreshInterval;
}

export async function discoverDevices(forceRefresh = false) {
  if (!forceRefresh && !shouldRefresh()) {
    return deviceCache;
  }

  const wyze = await getWyzeClient();
  const allDevices = await wyze.getDevices(forceRefresh);

  const plugs = [];
  const switches = [];
  const thermostats = [];

  for (const device of allDevices) {
    const deviceInfo = {
      id: device.mac,
      nickname: device.nickname,
      product_model: device.product_model,
      product_type: device.product_type,
      is_online: device.conn_state === 1,
      raw: device
    };

    if (device.product_type === DEVICE_TYPES.PLUG) {
      plugs.push({ ...deviceInfo, type: 'plug' });
    } else if (device.product_type === DEVICE_TYPES.SWITCH) {
      switches.push({ ...deviceInfo, type: 'switch' });
    } else if (device.product_type === DEVICE_TYPES.THERMOSTAT) {
      thermostats.push({ ...deviceInfo, type: 'thermostat' });
    }
  }

  // Build combined devices (thermostat + plug with same nickname)
  const combined = [];
  const usedPlugIds = new Set();

  for (const thermostat of thermostats) {
    const normalizedName = normalizeNickname(thermostat.nickname);
    const matchingPlug = plugs.find(
      p => normalizeNickname(p.nickname) === normalizedName
    );

    if (matchingPlug) {
      combined.push({
        id: `combined_${thermostat.id}`,
        nickname: thermostat.nickname,
        type: 'combined',
        thermostat: thermostat,
        plug: matchingPlug,
        is_online: thermostat.is_online && matchingPlug.is_online
      });
      usedPlugIds.add(matchingPlug.id);
    }
  }

  // Filter out plugs that are part of combined devices
  const standaloneplugs = plugs.filter(p => !usedPlugIds.has(p.id));

  deviceCache = {
    plugs: standaloneplugs,
    switches,
    thermostats,
    combined,
    lastRefresh: Date.now()
  };

  return deviceCache;
}

export function getAllDevices() {
  return [
    ...deviceCache.plugs,
    ...deviceCache.switches,
    ...deviceCache.thermostats,
    ...deviceCache.combined
  ];
}

export function findDevice(idOrName, type = null) {
  const allDevices = getAllDevices();
  const normalizedSearch = normalizeNickname(idOrName);

  return allDevices.find(device => {
    const matchesId = device.id === idOrName;
    const matchesName = normalizeNickname(device.nickname) === normalizedSearch;
    const matchesType = !type || device.type === type;
    return (matchesId || matchesName) && matchesType;
  });
}

export function findPlug(idOrName) {
  // Check standalone plugs first
  let device = findDevice(idOrName, 'plug');
  if (device) return device;

  // Check combined devices for plug
  const combined = findDevice(idOrName, 'combined');
  if (combined) return combined.plug;

  return null;
}

export function findThermostat(idOrName) {
  let device = findDevice(idOrName, 'thermostat');
  if (device) return device;

  // Check combined devices for thermostat
  const combined = findDevice(idOrName, 'combined');
  if (combined) return combined.thermostat;

  return null;
}

export function findSwitch(idOrName) {
  return findDevice(idOrName, 'switch');
}

export function findCombined(idOrName) {
  return findDevice(idOrName, 'combined');
}

export async function getDeviceStatus(device) {
  const wyze = await getWyzeClient();

  if (device.type === 'plug') {
    const state = await wyze.getPlugState(device.id, device.product_model);
    const props = state.raw?.property_list || [];
    // P5 is connection status (1=online, 0=offline), updates more frequently than device list
    const connProp = props.find(p => p.pid === 'P5');
    const isOnline = connProp?.value === '1';
    // P1612 is RSSI signal strength
    const rssiProp = props.find(p => p.pid === 'P1612');
    const rssi = rssiProp ? parseInt(rssiProp.value, 10) : null;
    const lastSeen = connProp ? new Date(connProp.ts).toISOString() : null;
    return {
      id: device.id,
      nickname: device.nickname,
      type: device.type,
      is_online: isOnline,
      is_on: state.switch_state,
      rssi: rssi,
      last_seen: lastSeen
    };
  }

  if (device.type === 'switch') {
    const state = await wyze.getSwitchState(device.id);
    return {
      id: device.id,
      nickname: device.nickname,
      type: device.type,
      is_online: device.is_online,
      is_on: state['switch-power']
    };
  }

  if (device.type === 'thermostat') {
    const info = await wyze.getThermostat(device.id);
    return {
      id: device.id,
      nickname: device.nickname,
      type: device.type,
      is_online: info.connected,
      temperature: info.temperature,
      humidity: info.humidity,
      mode: info.mode,
      heat_setpoint: info.heatSetpoint,
      cool_setpoint: info.coolSetpoint,
      fan_mode: info.fanMode,
      working_state: info.workingState,
      temp_unit: info.tempUnit,
      scenario: info.scenario
    };
  }

  if (device.type === 'combined') {
    const [thermostatStatus, plugStatus] = await Promise.all([
      getDeviceStatus(device.thermostat),
      getDeviceStatus(device.plug)
    ]);

    return {
      id: device.id,
      nickname: device.nickname,
      type: 'combined',
      thermostat: thermostatStatus,
      plug: plugStatus,
      is_on: plugStatus.is_on
    };
  }

  throw new Error(`Unknown device type: ${device.type}`);
}

export async function controlPlug(device, state) {
  const wyze = await getWyzeClient();
  const turnOn = state === 'on' || state === true;

  if (turnOn) {
    await wyze.plugOn(device.id, device.product_model);
  } else {
    await wyze.plugOff(device.id, device.product_model);
  }

  return { success: true, device: device.nickname, state: turnOn ? 'on' : 'off' };
}

export async function controlSwitch(device, state) {
  const wyze = await getWyzeClient();
  const turnOn = state === 'on' || state === true;

  if (turnOn) {
    await wyze.switchOn(device.id, device.product_model);
  } else {
    await wyze.switchOff(device.id, device.product_model);
  }

  return { success: true, device: device.nickname, state: turnOn ? 'on' : 'off' };
}

export async function controlThermostat(device, action, params = {}) {
  const wyze = await getWyzeClient();

  switch (action) {
    case 'set_heat':
      if (params.temperature === undefined) {
        throw new Error('temperature is required for set_heat');
      }
      await wyze.setHeatTemp(device.id, params.temperature, device.product_model);
      return { success: true, device: device.nickname, action, temperature: params.temperature };

    case 'set_cool':
      if (params.temperature === undefined) {
        throw new Error('temperature is required for set_cool');
      }
      await wyze.setCoolTemp(device.id, params.temperature, device.product_model);
      return { success: true, device: device.nickname, action, temperature: params.temperature };

    case 'set_mode':
      if (!params.mode) {
        throw new Error('mode is required for set_mode (heat, cool, auto, off)');
      }
      await wyze.setThermostatMode(device.id, params.mode, device.product_model);
      return { success: true, device: device.nickname, action, mode: params.mode };

    default:
      throw new Error(`Unknown thermostat action: ${action}`);
  }
}

export async function controlCombinedDevice(device, action, params = {}) {
  // For combined devices, turn_on/turn_off control the plug (heater power)
  // Temperature actions control the thermostat
  switch (action) {
    case 'turn_on':
      return controlPlug(device.plug, 'on');

    case 'turn_off':
      return controlPlug(device.plug, 'off');

    case 'set_heat':
    case 'set_cool':
    case 'set_mode':
      return controlThermostat(device.thermostat, action, params);

    default:
      throw new Error(`Unknown combined device action: ${action}`);
  }
}

export function getDeviceCache() {
  return deviceCache;
}
