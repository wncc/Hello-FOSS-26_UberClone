import type { LatLng, RideStatus, VehicleType } from './types';

/** ₹ with Indian digit grouping (1,50,000), without relying on the device's Intl support. */
export function formatFare(paise: number): string {
  const sign = paise < 0 ? '-' : '';
  const abs = Math.abs(Math.round(paise));
  const rupees = groupIndian(String(Math.floor(abs / 100)));
  const rest = abs % 100;
  return `${sign}₹${rupees}${rest ? `.${String(rest).padStart(2, '0')}` : ''}`;
}

function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const last3 = digits.slice(-3);
  const head = digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  return `${head},${last3}`;
}

export function formatDistance(m: number): string {
  return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
}

export function formatDuration(s: number): string {
  const min = Math.max(1, Math.round(s / 60));
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  return min % 60 ? `${h} h ${min % 60} min` : `${h} h`;
}

export const VEHICLE_LABEL: Record<VehicleType, string> = {
  bike: 'Bike',
  auto_rickshaw: 'Auto',
  car: 'Cab',
};

export const VEHICLE_ICON: Record<VehicleType, string> = {
  bike: '🏍️',
  auto_rickshaw: '🛺',
  car: '🚗',
};

export const VEHICLE_ORDER: VehicleType[] = ['bike', 'auto_rickshaw', 'car'];

export function riderStatusText(status: RideStatus): string {
  switch (status) {
    case 'searching': return 'Finding you a driver…';
    case 'driver_assigned': return 'Driver is on the way';
    case 'driver_arrived': return 'Driver has arrived';
    case 'in_progress': return 'On the trip';
    case 'completed': return 'Trip completed';
    case 'cancelled': return 'Ride cancelled';
    case 'no_drivers': return 'No drivers available right now';
  }
}

export function isFinished(status: RideStatus): boolean {
  return status === 'completed' || status === 'cancelled' || status === 'no_drivers';
}

/** Accepts 10-digit Indian mobiles with optional +91 / 0 / spaces; returns +91XXXXXXXXXX or null. */
export function normalizeIndianPhone(raw: string): string | null {
  let digits = raw.replace(/\D/g, '');
  if (digits.length === 12 && digits.startsWith('91')) digits = digits.slice(2);
  if (digits.length === 11 && digits.startsWith('0')) digits = digits.slice(1);
  return /^[6-9]\d{9}$/.test(digits) ? `+91${digits}` : null;
}

export function directionsUrl(dest: LatLng): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${dest.lat},${dest.lng}&travelmode=driving`;
}

export function shortAddress(lat: number, lng: number, label?: string | null): string {
  return label?.trim() || `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}
