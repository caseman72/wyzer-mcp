import { readFileSync, existsSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = join(__dirname, '..');

const defaultConfig = {
  wyze: {
    email: '',
    passwordHash: '',
    keyId: '',
    apiKey: '',
    authApiKey: '',
    apiKeyExpires: ''
  },
  server: {
    transport: 'stdio',
    httpPort: 8000,
    httpHost: '127.0.0.1'
  },
  devices: {
    refreshIntervalMinutes: 60
  },
  monitoring: {
    enabled: false,
    logFile: './wyzer-mcp-requests.log'
  }
};

function deepMerge(target, source) {
  const result = { ...target };
  for (const key of Object.keys(source)) {
    if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
      result[key] = deepMerge(target[key] || {}, source[key]);
    } else {
      result[key] = source[key];
    }
  }
  return result;
}

function loadConfig() {
  const configPaths = [
    join(projectRoot, 'config.json'),
    join(projectRoot, 'config.local.json')
  ];

  let config = { ...defaultConfig };

  for (const configPath of configPaths) {
    if (existsSync(configPath)) {
      try {
        const fileContent = readFileSync(configPath, 'utf-8');
        const fileConfig = JSON.parse(fileContent);
        config = deepMerge(config, fileConfig);
      } catch (err) {
        console.error(`Error loading config from ${configPath}:`, err.message);
      }
    }
  }

  // Allow environment variable overrides
  if (process.env.WYZE_EMAIL) config.wyze.email = process.env.WYZE_EMAIL;
  if (process.env.WYZE_PASSWORD_HASH) config.wyze.passwordHash = process.env.WYZE_PASSWORD_HASH;
  if (process.env.WYZE_KEY_ID) config.wyze.keyId = process.env.WYZE_KEY_ID;
  if (process.env.WYZE_API_KEY) config.wyze.apiKey = process.env.WYZE_API_KEY;
  if (process.env.WYZE_AUTH_API_KEY) config.wyze.authApiKey = process.env.WYZE_AUTH_API_KEY;
  if (process.env.WYZE_API_KEY_EXPIRES) config.wyze.apiKeyExpires = process.env.WYZE_API_KEY_EXPIRES;
  if (process.env.WYZER_HTTP_PORT) config.server.httpPort = parseInt(process.env.WYZER_HTTP_PORT, 10);
  if (process.env.WYZER_HTTP_HOST) config.server.httpHost = process.env.WYZER_HTTP_HOST;

  return config;
}

function validateConfig(config) {
  const errors = [];

  if (!config.wyze.email) errors.push('wyze.email is required');
  if (!config.wyze.passwordHash) errors.push('wyze.passwordHash is required');
  if (!config.wyze.keyId) errors.push('wyze.keyId is required');
  if (!config.wyze.apiKey) errors.push('wyze.apiKey is required');
  if (!config.wyze.authApiKey) errors.push('wyze.authApiKey is required');

  if (errors.length > 0) {
    throw new Error(`Configuration errors:\n${errors.join('\n')}`);
  }

  return config;
}

let cachedConfig = null;

export function getConfig() {
  if (!cachedConfig) {
    cachedConfig = validateConfig(loadConfig());
  }
  return cachedConfig;
}

export function getProjectRoot() {
  return projectRoot;
}
