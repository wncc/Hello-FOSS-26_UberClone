/** Mirrors backend/app/schemas.py. Money in paise, distance in metres, durations in seconds. */

export type VehicleType = 'car' | 'auto_rickshaw' | 'bike';
export type Role = 'rider' | 'driver' | 'admin';
export type RideStatus =
  | 'searching'
  | 'driver_assigned'
  | 'driver_arrived'
  | 'in_progress'
  | 'completed'
  | 'cancelled'
  | 'no_drivers';

export interface LatLng {
  lat: number;
  lng: number;
}

export interface Place extends LatLng {
  address?: string | null;
}

export interface User {
  id: string;
  phone: string;
  name: string | null;
  role: Role;
  rating: number | null;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  user: User;
}

/** [lat, lng] points along the roads. */
export type Path = [number, number][];

export interface EstimateOption {
  vehicle_type: VehicleType;
  fare_paise: number;
  distance_m: number;
  duration_s: number;
  drivers_nearby: number;
  route: Path;
}

export interface RideRoute {
  trip: Path;
  approach: Path | null;
}

export interface Party {
  id: string;
  name: string | null;
  rating: number | null;
}

export interface DriverInfo extends Party {
  vehicle_type: VehicleType;
  vehicle_number: string;
  vehicle_model: string | null;
  lat: number | null;
  lng: number | null;
}

export interface Ride {
  id: string;
  status: RideStatus;
  vehicle_type: VehicleType;
  pickup: Place;
  drop: Place;
  distance_m: number;
  duration_s: number;
  fare_estimate_paise: number;
  fare_final_paise: number | null;
  payment_method: 'cash' | 'online';
  payment_status: 'pending' | 'paid';
  pin: string | null;
  rider: Party | null;
  driver: DriverInfo | null;
  requested_at: string;
  assigned_at: string | null;
  arrived_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  cancelled_by: Role | null;
  cancel_reason: string | null;
}

export interface DriverProfile {
  user_id: string;
  vehicle_type: VehicleType;
  vehicle_number: string;
  vehicle_model: string | null;
  status: 'pending' | 'approved' | 'suspended';
  is_online: boolean;
}

/** Summary sent with ride events (never contains the PIN). */
export interface RideSummary {
  ride_id: string;
  status: RideStatus;
  vehicle_type: VehicleType;
  pickup: Place;
  drop: Place;
  distance_m: number;
  duration_s: number;
  fare_paise: number;
  payment_method: 'cash' | 'online';
}

export interface Offer extends RideSummary {
  expires_in_s?: number;
  offered_at?: string;
}

export type ServerEvent =
  | { event: 'ride:ping'; data: Offer }
  | { event: 'ride:ping_cancelled'; data: { ride_id: string; reason?: string } }
  | { event: 'ride:confirmed'; data: RideSummary }
  | { event: 'ride:taken'; data: { ride_id: string } }
  | { event: 'ride:driver_assigned'; data: RideSummary & { driver: Partial<DriverInfo> } }
  | { event: 'driver:location'; data: { ride_id: string; lat: number; lng: number; heading: number | null } }
  | { event: 'ride:driver_arrived'; data: RideSummary }
  | { event: 'ride:started'; data: RideSummary }
  | { event: 'ride:completed'; data: RideSummary & { fare_final_paise: number } }
  | { event: 'ride:cancelled'; data: RideSummary & { by: Role } }
  | { event: 'ride:driver_cancelled'; data: RideSummary & { reason: string | null } }
  | { event: 'ride:no_drivers'; data: RideSummary }
  | { event: 'pong'; data: Record<string, never> }
  | { event: 'error'; data: { message: string } };

export type EventName = ServerEvent['event'];
