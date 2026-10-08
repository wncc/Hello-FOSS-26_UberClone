import type {
  DriverProfile, EstimateOption, LatLng, Offer, Place, Ride, RideRoute, Tokens, User, VehicleType,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface TokenStore {
  access(): string | null;
  /** Called on 401: try the refresh token; return the new access token or null to log out. */
  refresh(): Promise<string | null>;
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH';

export class Api {
  constructor(
    private baseUrl: string,
    private tokens: TokenStore,
    private fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  async request<T>(method: Method, path: string, body?: unknown, retry = true): Promise<T> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    const token = this.tokens.access();
    if (token) headers.Authorization = `Bearer ${token}`;
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, `Can't reach the server at ${this.baseUrl}`);
    }
    if (res.status === 401 && retry && token) {
      const fresh = await this.tokens.refresh();
      if (fresh) return this.request<T>(method, path, body, false);
    }
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) throw new ApiError(res.status, errorMessage(data, res.status));
    return data as T;
  }

  // auth
  requestOtp = (phone: string) =>
    this.request<{ sent: boolean; expires_in: number; dev_code: string | null }>('POST', '/auth/otp/request', { phone });
  verifyOtp = (phone: string, code: string, role: 'rider' | 'driver') =>
    this.request<Tokens>('POST', '/auth/otp/verify', { phone, code, role });
  refresh = (refresh_token: string) => this.request<Tokens>('POST', '/auth/refresh', { refresh_token }, false);
  me = () => this.request<User>('GET', '/me');
  updateName = (name: string) => this.request<User>('PATCH', '/me', { name });

  // rider
  estimate = (pickup: Place, drop: Place) =>
    this.request<{ options: EstimateOption[] }>('POST', '/rides/estimate', { pickup, drop });
  book = (pickup: Place, drop: Place, vehicle_type: VehicleType) =>
    this.request<Ride>('POST', '/rides', { pickup, drop, vehicle_type, payment_method: 'cash' });
  activeRide = () => this.request<Ride | null>('GET', '/rides/active');
  ride = (id: string) => this.request<Ride>('GET', `/rides/${id}`);
  rideRoute = (id: string) => this.request<RideRoute>('GET', `/rides/${id}/route`);
  history = (limit = 20, offset = 0) => this.request<Ride[]>('GET', `/rides?limit=${limit}&offset=${offset}`);
  cancel = (id: string, reason?: string) => this.request<Ride>('POST', `/rides/${id}/cancel`, { reason });
  rate = (id: string, stars: number, comment?: string) =>
    this.request<{ id: string; stars: number }>('POST', `/rides/${id}/rating`, { stars, comment });

  // driver
  driverProfile = () => this.request<DriverProfile>('GET', '/drivers/me');
  saveDriverProfile = (vehicle_type: VehicleType, vehicle_number: string, vehicle_model?: string) =>
    this.request<DriverProfile>('PUT', '/drivers/me', { vehicle_type, vehicle_number, vehicle_model });
  setOnline = (online: boolean) => this.request<DriverProfile>('POST', '/drivers/me/online', { online });
  sendLocation = (loc: LatLng & { heading?: number | null; speed_kmh?: number | null }) =>
    this.request<void>('POST', '/drivers/me/location', loc);
  currentOffer = () => this.request<Offer | null>('GET', '/drivers/me/offer');
  accept = (id: string) => this.request<{ status: string }>('POST', `/rides/${id}/accept`);
  reject = (id: string) => this.request<void>('POST', `/rides/${id}/reject`);
  arrived = (id: string) => this.request<Ride>('POST', `/rides/${id}/arrived`);
  start = (id: string, pin: string) => this.request<Ride>('POST', `/rides/${id}/start`, { pin });
  complete = (id: string) => this.request<Ride>('POST', `/rides/${id}/complete`);
}

function errorMessage(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);   // FastAPI validation errors
  return `Request failed (${status})`;
}
