import { readFileSync, existsSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = join(__dirname, '..');

const defaultConfig = {
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
  if (process.env.WYZER_HTTP_PORT) config.server.httpPort = parseInt(process.env.WYZER_HTTP_PORT, 10);
  if (process.env.WYZER_HTTP_HOST) config.server.httpHost = process.env.WYZER_HTTP_HOST;

  return config;
}

let cachedConfig = null;

export function getConfig() {
  if (!cachedConfig) {
    cachedConfig = loadConfig();
  }
  return cachedConfig;
}

export function getProjectRoot() {
  return projectRoot;
}
