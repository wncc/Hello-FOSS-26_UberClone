/** Pure state updates from server events, shared by screens and unit-tested. */
import type { Offer, Ride, ServerEvent } from './types';

/** Rider side: apply a live event to the ride being shown. Events for other rides are ignored. */
export function applyRiderEvent(ride: Ride, e: ServerEvent): Ride {
  if (!('data' in e) || !e.data || (e.data as { ride_id?: string }).ride_id !== ride.id) return ride;
  switch (e.event) {
    case 'ride:driver_assigned': {
      const d = e.data.driver;
      return {
        ...ride, status: 'driver_assigned',
        driver: {
          id: d.id ?? '', name: d.name ?? null, rating: d.rating ?? null, vehicle_type: ride.vehicle_type,
          vehicle_number: d.vehicle_number ?? '', vehicle_model: d.vehicle_model ?? null,
          lat: d.lat ?? null, lng: d.lng ?? null,
        },
      };
    }
    case 'driver:location':
      return ride.driver ? { ...ride, driver: { ...ride.driver, lat: e.data.lat, lng: e.data.lng } } : ride;
    case 'ride:driver_arrived':
      return { ...ride, status: 'driver_arrived' };
    case 'ride:started':
      return { ...ride, status: 'in_progress' };
    case 'ride:completed':
      return { ...ride, status: 'completed', fare_final_paise: e.data.fare_final_paise };
    case 'ride:driver_cancelled':
      return { ...ride, status: 'searching', driver: null };
    case 'ride:no_drivers':
      return { ...ride, status: 'no_drivers' };
    default:
      return ride;
  }
}

/** Driver home screen: offline / waiting / looking at a ping / waiting for the match to be confirmed. */
export type DriverHome =
  | { mode: 'offline' }
  | { mode: 'idle' }
  | { mode: 'offered'; offer: Offer; expiresAt: number }
  | { mode: 'confirming'; offer: Offer }
  | { mode: 'assigned'; rideId: string };

export type DriverAction =
  | { type: 'online'; online: boolean }
  | { type: 'event'; event: ServerEvent; now: number }
  | { type: 'accepted' }
  | { type: 'rejected' }
  | { type: 'tick'; now: number }
  | { type: 'trip_done' };

export const DEFAULT_PING_SECONDS = 20;

export function driverHome(state: DriverHome, action: DriverAction): DriverHome {
  switch (action.type) {
    case 'online':
      return action.online ? (state.mode === 'offline' ? { mode: 'idle' } : state) : { mode: 'offline' };
    case 'accepted':
      return state.mode === 'offered' ? { mode: 'confirming', offer: state.offer } : state;
    case 'rejected':
      return state.mode === 'offered' ? { mode: 'idle' } : state;
    case 'tick':
      return state.mode === 'offered' && action.now >= state.expiresAt ? { mode: 'idle' } : state;
    case 'trip_done':
      return state.mode === 'assigned' ? { mode: 'idle' } : state;
    case 'event':
      return onDriverEvent(state, action.event, action.now);
  }
}

function onDriverEvent(state: DriverHome, e: ServerEvent, now: number): DriverHome {
  const currentRide = state.mode === 'offered' || state.mode === 'confirming' ? state.offer.ride_id : null;
  switch (e.event) {
    case 'ride:ping':
      if (state.mode !== 'idle') return state;
      return { mode: 'offered', offer: e.data, expiresAt: now + (e.data.expires_in_s ?? DEFAULT_PING_SECONDS) * 1000 };
    case 'ride:confirmed':
      return currentRide === e.data.ride_id || state.mode === 'idle' ? { mode: 'assigned', rideId: e.data.ride_id } : state;
    case 'ride:taken':
    case 'ride:ping_cancelled':
      return currentRide === e.data.ride_id ? { mode: 'idle' } : state;
    default:
      return state;
  }
}

export function secondsLeft(state: DriverHome, now: number): number {
  return state.mode === 'offered' ? Math.max(0, Math.ceil((state.expiresAt - now) / 1000)) : 0;
}
