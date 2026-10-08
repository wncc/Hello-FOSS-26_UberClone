import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';
import * as Location from 'expo-location';
import { useEffect, useState } from 'react';

import { LOCATION_INTERVAL_MS } from './config';
import { useSession } from './session';
import type { LatLng } from './types';

/** Map centre before GPS is known: Dadar, Mumbai (the city the road data covers). */
export const DEFAULT_CENTER: LatLng = { lat: 19.0178, lng: 72.8478 };

const FIX_TIMEOUT_MS = 15_000;

export class LocationError extends Error {}

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T | null> {
  return Promise.race([p, new Promise<null>((resolve) => setTimeout(() => resolve(null), ms))]);
}

async function ensureLocationAccess(): Promise<void> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') throw new LocationError('Location permission is off. Allow it for Expo Go in your phone settings.');
  if (!(await Location.hasServicesEnabledAsync())) throw new LocationError('Turn on location (GPS) on your phone.');
}

/**
 * Best available position: the last known fix immediately if recent, otherwise a fresh fix.
 * getCurrentPositionAsync can hang on some Android phones (indoors, no fix), so it is time-boxed.
 */
export async function currentPosition(onRough?: (p: LatLng) => void): Promise<LatLng> {
  await ensureLocationAccess();
  const last = await Location.getLastKnownPositionAsync({ maxAge: 5 * 60_000 }).catch(() => null);
  if (last) onRough?.({ lat: last.coords.latitude, lng: last.coords.longitude });
  const fresh = await withTimeout(Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }), FIX_TIMEOUT_MS)
    .catch(() => null);
  const pos = fresh ?? last;
  if (!pos) throw new LocationError('Could not get your location. Move near a window or try again.');
  return { lat: pos.coords.latitude, lng: pos.coords.longitude };
}

/** Short human label for a point using the phone's own geocoder; null if unavailable. */
export async function addressLabel(p: LatLng): Promise<string | null> {
  try {
    const [a] = await Location.reverseGeocodeAsync({ latitude: p.lat, longitude: p.lng });
    if (!a) return null;
    const parts = [a.name, a.street, a.district, a.city].filter((x): x is string => !!x);
    return [...new Set(parts)].slice(0, 3).join(', ') || null;
  } catch {
    return null;
  }
}

export function useCurrentPosition(): { position: LatLng | null; error: string | null; retry: () => void } {
  const [position, setPosition] = useState<LatLng | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    currentPosition((rough) => alive && setPosition(rough))
      .then((p) => {
        if (!alive) return;
        setPosition(p);
        setError(null);
      })
      .catch((e) => alive && setError(e instanceof LocationError ? e.message : 'Could not get your location.'));
    return () => {
      alive = false;
    };
  }, [attempt]);
  return { position, error, retry: () => setAttempt((n) => n + 1) };
}

const KEEP_AWAKE_TAG = 'driver-online';

/**
 * While `active`, streams the driver's GPS to the backend (socket, falling back to HTTP)
 * and keeps the screen awake. Foreground only: background GPS needs a development build.
 */
export function useDriverLocationReporter(active: boolean): { last: LatLng | null; error: string | null } {
  const { api, sendLive } = useSession();
  const [last, setLast] = useState<LatLng | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    let sub: Location.LocationSubscription | null = null;
    let cancelled = false;
    activateKeepAwakeAsync(KEEP_AWAKE_TAG).catch(() => {});

    (async () => {
      try {
        await ensureLocationAccess();
      } catch (e) {
        setError(e instanceof LocationError ? e.message : 'Location is needed to receive rides');
        return;
      }
      setError(null);
      const report = (pos: Location.LocationObject) => {
        const msg = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          heading: pos.coords.heading != null && pos.coords.heading >= 0 ? pos.coords.heading : null,
          speed_kmh: pos.coords.speed != null && pos.coords.speed >= 0 ? pos.coords.speed * 3.6 : null,
        };
        setLast({ lat: msg.lat, lng: msg.lng });
        if (!sendLive({ type: 'location', ...msg })) {
          api.sendLocation(msg).catch(() => setError('Could not send your location to the server'));
        }
      };
      // Indoors a fresh GPS fix can take a while; the last known position makes the driver visible at once.
      const last = await Location.getLastKnownPositionAsync().catch(() => null);
      if (last && !cancelled) report(last);
      try {
        const watch = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.High, timeInterval: LOCATION_INTERVAL_MS, distanceInterval: 0 },
          report,
        );
        if (cancelled) watch.remove();
        else sub = watch;
      } catch {
        setError('Could not start GPS tracking. Check that location is on.');
      }
    })();

    return () => {
      cancelled = true;
      sub?.remove();
      deactivateKeepAwake(KEEP_AWAKE_TAG).catch(() => {});
    };
  }, [active, api, sendLive]);

  return { last, error };
}
