const API_BASE_URL = (
  import.meta.env.VITE_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

const ACCESS_KEY = "admin.auth.access";
const REFRESH_KEY = "admin.auth.refresh";

export interface AdminUser {
  id: string;
  phone: string;
  name: string;
  role: "rider" | "driver" | "admin";
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: AdminUser;
}

export interface Driver {
  user_id: string;
  vehicle_type: string;
  vehicle_number: string;
  vehicle_model: string;
  status: "pending" | "approved" | "suspended";
  is_online: boolean;
}

export interface Ride {
  id: string;
  status:
    | "searching"
    | "driver_assigned"
    | "driver_arrived"
    | "in_progress"
    | "completed"
    | "cancelled"
    | "no_drivers";
  vehicle_type: string;
  pickup: {
    lat: number;
    lng: number;
    address: string;
  };
  drop: {
    lat: number;
    lng: number;
    address: string;
  };
  fare_estimate_paise: number;
  fare_final_paise: number | null;
  payment_method: string;
  payment_status: string;
  requested_at: string;
  rider: { id: string; name: string; rating: number } | null;
  driver: {
    id: string;
    name: string;
    rating: number;
    vehicle_type: string;
    vehicle_number: string;
    vehicle_model: string;
    lat: number | null;
    lng: number | null;
  } | null;
}

export interface AdminMapDriver {
  user_id: string;
  vehicle_type: string;
  vehicle_number: string;
  lat: number;
  lng: number;
}

export interface AdminMapRide {
  id: string;
  status: Ride["status"];
  vehicle_type: string;
  pickup: {
    lat: number;
    lng: number;
    address?: string | null;
  };
  drop: {
    lat: number;
    lng: number;
    address?: string | null;
  };
  driver_id: string | null;
  requested_at: string;
}

export interface AdminMapData {
  drivers: AdminMapDriver[];
  rides: AdminMapRide[];
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function readError(data: unknown, status: number): string {
  if (typeof data === "object" && data !== null) {
    const detail = (data as { detail?: unknown }).detail;

    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return "Please check the submitted information.";
  }

  return `Request failed (${status})`;
}

export function saveTokens(tokens: AuthTokens): void {
  localStorage.setItem(ACCESS_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function hasAccessToken(): boolean {
  return Boolean(localStorage.getItem(ACCESS_KEY));
}

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = localStorage.getItem(REFRESH_KEY);

  if (!refreshToken) return false;

  try {
    const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      clearTokens();
      return false;
    }

    const tokens = (await response.json()) as AuthTokens;
    saveTokens(tokens);
    return true;
  } catch {
    // Keep the session so a temporary network failure does not log the user out.
    return false;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

  const accessToken = localStorage.getItem(ACCESS_KEY);
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
    });
  } catch {
    throw new ApiError(
      `Cannot reach ${API_BASE_URL}. Check that the backend is running.`,
      0,
    );
  }

  if (response.status === 401 && retry) {
    const refreshed = await refreshAccessToken();

    if (refreshed) {
      return request<T>(path, options, false);
    }

    clearTokens();
  }

  const text = await response.text();
  let data: unknown = undefined;

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    throw new ApiError(readError(data, response.status), response.status);
  }

  return data as T;
}

export async function requestOtp(phone: string): Promise<{
  sent: boolean;
  expires_in: number;
  dev_code?: string | null;
}> {
  return request("/auth/otp/request", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export async function verifyOtp(
  phone: string,
  code: string,
): Promise<AuthTokens> {
  // The backend determines admin access from ADMIN_PHONES.
  // Requesting the rider role does not grant admin privileges.
  return request("/auth/otp/verify", {
    method: "POST",
    body: JSON.stringify({ phone, code, role: "rider", admin_login: true }),
  });
}

export function getDrivers(): Promise<Driver[]> {
  return request("/admin/drivers");
}

export function getRides(): Promise<Ride[]> {
  return request("/admin/rides?limit=200");
}

export function updateDriverStatus(
  userId: string,
  action: "approve" | "suspend",
): Promise<Driver> {
  return request(`/admin/drivers/${encodeURIComponent(userId)}/${action}`, {
    method: "POST",
  });
}

export function getAdminMap(): Promise<AdminMapData> {
  return request("/admin/map");
}