import { describe, expect, test } from '@jest/globals';
import { applyRiderEvent, driverHome, secondsLeft, type DriverHome } from '../rideState';
import type { Offer, Ride, ServerEvent } from '../types';

const summary = {
  ride_id: 'R1', status: 'searching' as const, vehicle_type: 'car' as const,
  pickup: { lat: 12.97, lng: 77.59 }, drop: { lat: 12.93, lng: 77.62 },
  distance_m: 5000, duration_s: 900, fare_paise: 20000, payment_method: 'cash' as const,
};

const ride: Ride = {
  id: 'R1', status: 'searching', vehicle_type: 'car', pickup: summary.pickup, drop: summary.drop,
  distance_m: 5000, duration_s: 900, fare_estimate_paise: 20000, fare_final_paise: null, payment_method: 'cash',
  payment_status: 'pending', pin: '1234', rider: null, driver: null, requested_at: '', assigned_at: null,
  arrived_at: null, started_at: null, completed_at: null, cancelled_at: null, cancelled_by: null, cancel_reason: null,
};

describe('rider events', () => {
  test('full progression', () => {
    let r = applyRiderEvent(ride, { event: 'ride:driver_assigned', data: { ...summary, driver: { id: 'D1', name: 'Ravi', lat: 1, lng: 2 } } });
    expect(r.status).toBe('driver_assigned');
    expect(r.driver?.name).toBe('Ravi');
    r = applyRiderEvent(r, { event: 'driver:location', data: { ride_id: 'R1', lat: 3, lng: 4, heading: null } });
    expect([r.driver?.lat, r.driver?.lng]).toEqual([3, 4]);
    r = applyRiderEvent(r, { event: 'ride:driver_arrived', data: summary });
    expect(r.status).toBe('driver_arrived');
    r = applyRiderEvent(r, { event: 'ride:started', data: summary });
    expect(r.status).toBe('in_progress');
    r = applyRiderEvent(r, { event: 'ride:completed', data: { ...summary, fare_final_paise: 21000 } });
    expect([r.status, r.fare_final_paise]).toEqual(['completed', 21000]);
  });

  test('driver cancelling sends the ride back to searching', () => {
    const assigned = applyRiderEvent(ride, { event: 'ride:driver_assigned', data: { ...summary, driver: { id: 'D1' } } });
    const r = applyRiderEvent(assigned, { event: 'ride:driver_cancelled', data: { ...summary, reason: null } });
    expect([r.status, r.driver]).toEqual(['searching', null]);
  });

  test('events for other rides are ignored', () => {
    const r = applyRiderEvent(ride, { event: 'ride:started', data: { ...summary, ride_id: 'OTHER' } });
    expect(r).toBe(ride);
  });
});

describe('driver home', () => {
  const offer: Offer = { ...summary, expires_in_s: 20 };
  const ping: ServerEvent = { event: 'ride:ping', data: offer };
  const idle: DriverHome = { mode: 'idle' };

  test('ping, accept, confirmed', () => {
    let s = driverHome(idle, { type: 'event', event: ping, now: 0 });
    expect(s.mode).toBe('offered');
    expect(secondsLeft(s, 5_000)).toBe(15);
    s = driverHome(s, { type: 'accepted' });
    expect(s.mode).toBe('confirming');
    s = driverHome(s, { type: 'event', event: { event: 'ride:confirmed', data: summary }, now: 1 });
    expect(s).toEqual({ mode: 'assigned', rideId: 'R1' });
  });

  test('lost the ride to a nearer driver', () => {
    let s = driverHome(idle, { type: 'event', event: ping, now: 0 });
    s = driverHome(s, { type: 'accepted' });
    s = driverHome(s, { type: 'event', event: { event: 'ride:taken', data: { ride_id: 'R1' } }, now: 1 });
    expect(s.mode).toBe('idle');
  });

  test('ping expires locally and on the server', () => {
    const s = driverHome(idle, { type: 'event', event: ping, now: 0 });
    expect(driverHome(s, { type: 'tick', now: 19_999 }).mode).toBe('offered');
    expect(driverHome(s, { type: 'tick', now: 20_000 }).mode).toBe('idle');
    expect(driverHome(s, { type: 'event', event: { event: 'ride:ping_cancelled', data: { ride_id: 'R1' } }, now: 1 }).mode).toBe('idle');
  });

  test('ignores pings while offline or busy, and a second ping while one is shown', () => {
    expect(driverHome({ mode: 'offline' }, { type: 'event', event: ping, now: 0 }).mode).toBe('offline');
    const s = driverHome(idle, { type: 'event', event: ping, now: 0 });
    const second = driverHome(s, { type: 'event', event: { event: 'ride:ping', data: { ...offer, ride_id: 'R2' } }, now: 1 });
    expect(second).toBe(s);
  });

  test('going offline clears everything', () => {
    const s = driverHome(idle, { type: 'event', event: ping, now: 0 });
    expect(driverHome(s, { type: 'online', online: false })).toEqual({ mode: 'offline' });
    expect(driverHome({ mode: 'offline' }, { type: 'online', online: true })).toEqual({ mode: 'idle' });
  });
});
