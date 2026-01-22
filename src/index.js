#!/usr/bin/env node

import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { createMcpServer } from './server.js';
import { initializeMonitoring } from './request-monitor.js';
import { discoverDevices } from './device-manager.js';

async function main() {
  try {
    initializeMonitoring();

    const server = createMcpServer();
    const transport = new StdioServerTransport();

    await server.connect(transport);

    // Initial device discovery
    try {
      await discoverDevices();
      console.error('Initial device discovery completed');
    } catch (err) {
      console.error('Initial device discovery failed:', err.message);
    }
  } catch (err) {
    console.error('Failed to start server:', err.message);
    process.exit(1);
  }
}

main();
