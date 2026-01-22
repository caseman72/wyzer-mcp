import Wyze from '@caseman72/wyzer-api';

let wyzeInstance = null;
let isInitialized = false;

export async function getWyzeClient() {
  if (wyzeInstance && isInitialized) {
    return wyzeInstance;
  }

  // wyzer-api 1.2+ reads credentials from .env.local in:
  // - Current working directory
  // - ~/.config/wyze/.env.local
  // - ~/.wyze.env.local
  wyzeInstance = new Wyze({ quiet: true });

  await wyzeInstance.login();
  isInitialized = true;

  return wyzeInstance;
}

export async function refreshWyzeClient() {
  isInitialized = false;
  wyzeInstance = null;
  return getWyzeClient();
}
