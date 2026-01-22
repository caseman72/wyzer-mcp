import Wyze from '@caseman72/wyzer-api';
import { getConfig } from './config.js';

let wyzeInstance = null;
let isInitialized = false;

export async function getWyzeClient() {
  if (wyzeInstance && isInitialized) {
    return wyzeInstance;
  }

  const config = getConfig();

  wyzeInstance = new Wyze({
    email: config.wyze.email,
    passwordHash: config.wyze.passwordHash,
    keyId: config.wyze.keyId,
    apiKey: config.wyze.apiKey,
    authApiKey: config.wyze.authApiKey,
    apiKeyExpires: config.wyze.apiKeyExpires,
    quiet: true
  });

  await wyzeInstance.login();
  isInitialized = true;

  return wyzeInstance;
}

export async function refreshWyzeClient() {
  isInitialized = false;
  wyzeInstance = null;
  return getWyzeClient();
}
