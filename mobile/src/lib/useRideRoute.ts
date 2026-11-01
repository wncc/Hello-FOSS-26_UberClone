import { useEffect, useState } from 'react';

import { useServerEvents, useSession } from './session';
import type { RideRoute, RideStatus } from './types';

/**
 * Road geometry for a ride: the trip (pickup -> drop) and, while the driver is on the way,
 * their path to the pickup and live ETA. Refetched whenever the ride's status changes.
 */
export function useRideRoute(rideId: string, status: RideStatus | undefined): RideRoute | null {
  const { api } = useSession();
  const [route, setRoute] = useState<RideRoute | null>(null);

  useEffect(() => {
    if (!status) return;
    let alive = true;
    api.rideRoute(rideId)
      .then((r) => alive && setRoute(r))
      .catch(() => {});   // the map falls back to a straight placeholder line
    return () => {
      alive = false;
    };
  }, [api, rideId, status]);

  useServerEvents((e) => {
    if (e.event === 'driver:location' && e.data.ride_id === rideId && e.data.approach_duration_s != null) {
      const duration = e.data.approach_duration_s;
      setRoute((r) => (r ? { ...r, approach_duration_s: duration } : { trip: [], approach: null, approach_duration_s: duration }));
    }
  });

  return route;
}