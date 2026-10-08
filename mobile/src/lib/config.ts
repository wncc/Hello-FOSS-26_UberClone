import Constants from 'expo-constants';

export type AppVariant = 'rider' | 'driver';

/** Which app this build is. Set EXPO_PUBLIC_APP_VARIANT=driver to run the driver app. */
export const APP_VARIANT: AppVariant = process.env.EXPO_PUBLIC_APP_VARIANT === 'driver' ? 'driver' : 'rider';

/**
 * Backend URL. Defaults to port 8000 on the machine serving the JS bundle, so a phone
 * running Expo Go on the same Wi-Fi reaches the dev backend without extra setup.
 */
export function apiBaseUrl(): string {
  if (process.env.EXPO_PUBLIC_API_URL) return process.env.EXPO_PUBLIC_API_URL.replace(/\/$/, '');
  const host = Constants.expoConfig?.hostUri?.split(':')[0] ?? 'localhost';
  return `http://${host}:8000`;
}

export function wsUrl(token: string, base = apiBaseUrl()): string {
  return `${base.replace(/^http/, 'ws')}/ws?token=${encodeURIComponent(token)}`;
}

/** Driver GPS reporting cadence while online (backend treats > 60 s silence as offline). */
export const LOCATION_INTERVAL_MS = 4000;
