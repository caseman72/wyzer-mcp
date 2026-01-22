import { appendFileSync, existsSync, mkdirSync } from 'fs';
import { dirname, resolve } from 'path';
import { getConfig, getProjectRoot } from './config.js';

let logFilePath = null;
let isEnabled = false;

export function initializeMonitoring() {
  const config = getConfig();
  isEnabled = config.monitoring.enabled;

  if (!isEnabled) return;

  const logFile = config.monitoring.logFile;
  if (logFile.startsWith('./') || logFile.startsWith('../')) {
    logFilePath = resolve(getProjectRoot(), logFile);
  } else {
    logFilePath = logFile;
  }

  // Ensure log directory exists
  const logDir = dirname(logFilePath);
  if (!existsSync(logDir)) {
    mkdirSync(logDir, { recursive: true });
  }
}

export function logRequest(toolName, params, result, error = null) {
  if (!isEnabled || !logFilePath) return;

  const entry = {
    timestamp: new Date().toISOString(),
    tool: toolName,
    params,
    success: !error,
    result: error ? undefined : result,
    error: error ? error.message : undefined
  };

  try {
    appendFileSync(logFilePath, JSON.stringify(entry) + '\n');
  } catch (err) {
    console.error('Failed to write to log file:', err.message);
  }
}

export function createToolWrapper(toolName, handler) {
  return async (params) => {
    const startTime = Date.now();
    let result;
    let error;

    try {
      result = await handler(params);
      logRequest(toolName, params, { ...result, duration_ms: Date.now() - startTime });
      return result;
    } catch (err) {
      error = err;
      logRequest(toolName, params, null, err);
      throw err;
    }
  };
}
