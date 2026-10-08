import { useEffect, useState } from 'react';

import { useSession } from './session';
import type { RideRoute, RideStatus } from './types';

/**
 * Road geometry for a ride: the trip (pickup -> drop) and, while the driver is on the way,
 * their path to the pickup. Refetched whenever the ride's status changes.
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

  return route;
}
