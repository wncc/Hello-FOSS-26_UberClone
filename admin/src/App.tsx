import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  CarFront,
  CheckCircle2,
  Clock3,
  LayoutDashboard,
  LogOut,
  MapPinned,
  Menu,
  RefreshCw,
  Search,
  ShieldCheck,
  Users,
  XCircle,
} from "lucide-react";
import {
  ApiError,
  clearTokens,
  getAdminMap,
  getDrivers,
  getRides,
  hasAccessToken,
  requestOtp,
  saveTokens,
  updateDriverStatus,
  verifyOtp,
  type AdminMapData,
  type Driver,
  type Ride,
} from "./lib/api";
import "./App.css";
import LiveMap from "./components/LiveMap";

type Section = "Overview" | "Drivers" | "Rides" | "Live Map";

const navigation: { label: Section; icon: typeof LayoutDashboard }[] = [
  { label: "Overview", icon: LayoutDashboard },
  { label: "Drivers", icon: Users },
  { label: "Rides", icon: CarFront },
  { label: "Live Map", icon: MapPinned },
];

const rideStatusLabels: Record<string, string> = {
  searching: "Requested",
  driver_assigned: "Driver Assigned",
  driver_arrived: "Driver Arrived",
  in_progress: "In Progress",
  completed: "Completed",
  cancelled: "Cancelled",
  no_drivers: "No Drivers",
};

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatMoney(paise: number | null | undefined) {
  if (paise == null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(paise / 100);
}

function formatTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("en-IN", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function Badge({ value }: { value: string }) {
  const className = value.toLowerCase().replaceAll(" ", "-");
  return <span className={`badge ${className}`}>{value}</span>;
}

function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [otpRequested, setOtpRequested] = useState(false);
  const [devCode, setDevCode] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState("");

  const [section, setSection] = useState<Section>("Overview");
  const [driverFilter, setDriverFilter] = useState("All");
  const [rideFilter, setRideFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [mobileMenu, setMobileMenu] = useState(false);

  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [rides, setRides] = useState<Ride[]>([]);
  const [dataLoading, setDataLoading] = useState(false);
  const [dataError, setDataError] = useState("");
  const [actionBusy, setActionBusy] = useState<string | null>(null);

  const [mapData, setMapData] = useState<AdminMapData>({
    drivers: [],
    rides: [],
  });
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState("");
  const [mapFitRequest, setMapFitRequest] = useState(0);

  const loadDashboard = useCallback(async () => {
    setDataLoading(true);
    setDataError("");

    try {
      const [driverData, rideData] = await Promise.all([
        getDrivers(),
        getRides(),
      ]);
      setDrivers(driverData);
      setRides(rideData);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        clearTokens();
        setAuthenticated(false);
        setLoginError("This account does not have admin permission.");
      } else {
        setDataError(errorMessage(error));
      }
    } finally {
      setDataLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      if (!hasAccessToken()) {
        if (!cancelled) setCheckingSession(false);
        return;
      }

      try {
        const [driverData, rideData] = await Promise.all([
          getDrivers(),
          getRides(),
        ]);

        if (!cancelled) {
          setDrivers(driverData);
          setRides(rideData);
          setAuthenticated(true);
        }
      } catch (error) {
        if (cancelled) return;

        if (
          error instanceof ApiError &&
          (error.status === 401 || error.status === 403)
        ) {
          clearTokens();
          setLoginError(
            error.status === 403
              ? "This account does not have admin permission."
              : "Your session expired. Please sign in again.",
          );
        } else {
          setLoginError(errorMessage(error));
        }
      } finally {
        if (!cancelled) setCheckingSession(false);
      }
    }

    void restoreSession();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!authenticated || section !== "Live Map") return;

    let cancelled = false;

    async function refreshMap() {
      if (!cancelled) setMapLoading(true);

      try {
        const result = await getAdminMap();

        if (!cancelled) {
          setMapData(result);
          setMapError("");
        }
      } catch (error) {
        if (!cancelled) {
          setMapError(errorMessage(error));

          if (
            error instanceof ApiError &&
            (error.status === 401 || error.status === 403)
          ) {
            clearTokens();
            setAuthenticated(false);
            setLoginError(
              error.status === 403
                ? "This account does not have admin permission."
                : "Your session expired. Please sign in again.",
            );
          }
        }
      } finally {
        if (!cancelled) setMapLoading(false);
      }
    }

    void refreshMap();

    const intervalId = window.setInterval(() => {
      void refreshMap();
    }, 10_000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [authenticated, section]);

  async function handleRequestOtp(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginError("");
    setDevCode("");
    setLoginBusy(true);

    try {
      const result = await requestOtp(phone.trim());
      setOtpRequested(true);
      if (result.dev_code) setDevCode(result.dev_code);
    } catch (error) {
      setLoginError(errorMessage(error));
    } finally {
      setLoginBusy(false);
    }
  }

  async function handleVerifyOtp(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginError("");
    setLoginBusy(true);

    try {
      const tokens = await verifyOtp(phone.trim(), otp.trim());

      if (tokens.user.role !== "admin") {
        setLoginError(
          "This phone number is not configured as an admin. Ask the backend administrator to check ADMIN_PHONES.",
        );
        return;
      }

      saveTokens(tokens);
      setAuthenticated(true);
      setOtpRequested(false);
      setOtp("");
      await loadDashboard();
    } catch (error) {
      setLoginError(errorMessage(error));
    } finally {
      setLoginBusy(false);
    }
  }

  function handleLogout() {
    clearTokens();
    setAuthenticated(false);
    setDrivers([]);
    setRides([]);
    setOtp("");
    setOtpRequested(false);
    setDevCode("");
    setLoginError("");
  }

  async function handleDriverAction(
    userId: string,
    action: "approve" | "suspend",
  ) {
    setActionBusy(`${userId}:${action}`);
    setDataError("");

    try {
      await updateDriverStatus(userId, action);
      await loadDashboard();
    } catch (error) {
      setDataError(errorMessage(error));
    } finally {
      setActionBusy(null);
    }
  }

  const visibleDrivers = useMemo(
    () =>
      drivers.filter((driver) => {
        const status = titleCase(driver.status);
        const matchesFilter = driverFilter === "All" || status === driverFilter;
        const haystack = [
          driver.user_id,
          driver.vehicle_number,
          driver.vehicle_model,
          driver.vehicle_type,
          driver.status,
        ]
          .join(" ")
          .toLowerCase();

        return matchesFilter && haystack.includes(search.toLowerCase());
      }),
    [drivers, driverFilter, search],
  );

  const visibleRides = useMemo(
    () =>
      rides.filter((ride) => {
        const status = rideStatusLabels[ride.status] ?? titleCase(ride.status);
        const matchesFilter = rideFilter === "All" || status === rideFilter;
        const haystack = [
          ride.id,
          ride.rider?.name,
          ride.rider?.id,
          ride.driver?.name,
          ride.driver?.id,
          ride.status,
          ride.pickup?.address,
          ride.drop?.address,
        ]
          .join(" ")
          .toLowerCase();

        return matchesFilter && haystack.includes(search.toLowerCase());
      }),
    [rides, rideFilter, search],
  );

  const pendingDrivers = drivers.filter(
    (driver) => driver.status === "pending",
  ).length;
  const activeRides = rides.filter((ride) =>
    ["searching", "driver_assigned", "driver_arrived", "in_progress"].includes(
      ride.status,
    ),
  ).length;
  const completedRides = rides.filter(
    (ride) => ride.status === "completed",
  ).length;
  const revenuePaise = rides.reduce(
    (sum, ride) =>
      sum +
      (ride.fare_final_paise ??
        (ride.status === "completed" ? ride.fare_estimate_paise : 0)),
    0,
  );

  if (checkingSession) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <CarFront size={34} />
          <h1>RideFlow Admin</h1>
          <p>Checking your session…</p>
        </div>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="auth-screen">
        <form
          className="auth-card"
          onSubmit={otpRequested ? handleVerifyOtp : handleRequestOtp}
        >
          <div className="auth-brand-icon">
            <CarFront size={26} />
          </div>
          <p className="auth-eyebrow">SECURE ADMIN ACCESS</p>
          <h1>RideFlow Admin</h1>
          <p className="auth-description">
            Sign in with the phone number configured for your administrator
            account.
          </p>

          <label className="auth-label" htmlFor="admin-phone">
            Phone number
          </label>
          <input
            id="admin-phone"
            className="auth-input"
            type="tel"
            autoComplete="tel"
            placeholder="+91 98765 43210"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            required
            disabled={otpRequested || loginBusy}
          />

          {otpRequested && (
            <>
              <label className="auth-label" htmlFor="admin-otp">
                One-time password (OTP)
              </label>
              <input
                id="admin-otp"
                className="auth-input"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="Enter OTP"
                value={otp}
                onChange={(event) => setOtp(event.target.value)}
                minLength={4}
                maxLength={8}
                required
              />
              {devCode && (
                <p className="dev-code-note">
                  Development OTP from backend: <strong>{devCode}</strong>
                </p>
              )}
            </>
          )}

          {loginError && (
            <p className="auth-error" role="alert">
              {loginError}
            </p>
          )}

          <button className="auth-submit" type="submit" disabled={loginBusy}>
            {loginBusy
              ? "Please wait…"
              : otpRequested
                ? "Verify OTP and sign in"
                : "Request OTP"}
          </button>

          {otpRequested && (
            <button
              className="auth-back"
              type="button"
              onClick={() => {
                setOtpRequested(false);
                setOtp("");
                setDevCode("");
                setLoginError("");
              }}
            >
              Use a different phone number
            </button>
          )}

          <div className="auth-security">
            <ShieldCheck size={16} /> Admin access is checked by the backend
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="app-shell">
      {mobileMenu && (
        <button
          className="mobile-overlay"
          aria-label="Close menu"
          onClick={() => setMobileMenu(false)}
        />
      )}
      <aside className={`sidebar ${mobileMenu ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-icon">
            <CarFront size={23} />
          </div>
          <div>
            <strong>RideFlow</strong>
            <span>ADMIN CONSOLE</span>
          </div>
          <button
            className="close-menu"
            onClick={() => setMobileMenu(false)}
            aria-label="Close menu"
          >
            <XCircle size={20} />
          </button>
        </div>

        <div className="workspace-label">WORKSPACE</div>
        <nav className="nav-list">
          {navigation.map(({ label, icon: Icon }) => (
            <button
              key={label}
              className={`nav-item ${section === label ? "active" : ""}`}
              onClick={() => {
                setSection(label);
                setMobileMenu(false);
              }}
            >
              <Icon size={19} />
              <span>{label}</span>
              {label === "Drivers" && pendingDrivers > 0 && (
                <span className="nav-count">{pendingDrivers}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="secure-note">
            <ShieldCheck size={18} />
            <div>
              <strong>Secure workspace</strong>
              <span>Admin access only</span>
            </div>
          </div>
          <button className="profile-row" onClick={handleLogout}>
            <div className="avatar">AD</div>
            <div className="profile-info">
              <strong>Administrator</strong>
              <span>Sign out</span>
            </div>
            <LogOut size={17} />
          </button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <button
            className="menu-toggle"
            onClick={() => setMobileMenu(true)}
            aria-label="Open menu"
          >
            <Menu size={22} />
          </button>
          <div className="breadcrumb">
            Workspace <span>/</span> <strong>{section}</strong>
          </div>
          <div className="topbar-right">
            <button
              className="refresh-button"
              onClick={() => void loadDashboard()}
              disabled={dataLoading}
              aria-label="Refresh data"
              title="Refresh data"
            >
              <RefreshCw size={16} />
            </button>
            <span className="system-status">
              <i /> Backend connected
            </span>
            <div className="avatar top-avatar">AD</div>
          </div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">LIVE BACKEND DATA</div>
              <h1>
                {section === "Overview" ? "Good afternoon, Admin" : section}
              </h1>
              <p>
                {section === "Overview"
                  ? "Here's what's happening across your ride network."
                  : `Monitor and manage ${section.toLowerCase()} across your network.`}
              </p>
            </div>
            <div className="heading-actions">
              <span className="date-chip">
                <Clock3 size={15} /> Live operations
              </span>
            </div>
          </div>

          {dataError && (
            <div className="data-error" role="alert">
              {dataError}
            </div>
          )}
          {dataLoading && (
            <div className="loading-note">Loading the latest backend data…</div>
          )}

          {section === "Overview" && (
            <>
              <div className="stats-grid">
                <StatCard
                  label="Total drivers"
                  value={String(drivers.length)}
                  change="Live data"
                  icon={<Users />}
                  tone="blue"
                  note="registered driver profiles"
                />
                <StatCard
                  label="Active rides"
                  value={String(activeRides)}
                  change="Live data"
                  icon={<CarFront />}
                  tone="green"
                  note="currently unfinished rides"
                />
                <StatCard
                  label="Pending approvals"
                  value={String(pendingDrivers)}
                  change="Needs review"
                  icon={<Clock3 />}
                  tone="amber"
                  note="drivers awaiting review"
                />
                <StatCard
                  label="Completed ride fares"
                  value={formatMoney(revenuePaise)}
                  change="Live data"
                  icon={<Activity />}
                  tone="purple"
                  note={`${completedRides} completed rides in loaded records`}
                />
              </div>

              <div className="content-grid">
                <section className="panel activity-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Ride activity</h2>
                      <p>Current ride status breakdown</p>
                    </div>
                    <span className="subtle-chip">Live data</span>
                  </div>
                  <div className="chart-summary">
                    <strong>{rides.length}</strong>
                    <span>
                      <Activity size={15} /> Loaded
                    </span>
                    <small>rides returned by backend</small>
                  </div>
                  <div className="status-breakdown">
                    {Object.entries(rideStatusLabels).map(([status, label]) => {
                      const count = rides.filter(
                        (ride) => ride.status === status,
                      ).length;
                      const width = rides.length
                        ? `${(count / rides.length) * 100}%`
                        : "0%";
                      return (
                        <div className="status-breakdown-row" key={status}>
                          <span>{label}</span>
                          <div className="status-breakdown-track">
                            <i style={{ width }} />
                          </div>
                          <strong>{count}</strong>
                        </div>
                      );
                    })}
                  </div>
                </section>

                <section className="panel status-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Network status</h2>
                      <p>Driver availability</p>
                    </div>
                    <Activity size={19} className="muted-icon" />
                  </div>
                  <div className="network-total">
                    <strong>{drivers.length}</strong>
                    <span>registered driver profiles</span>
                  </div>
                  <div className="progress-track">
                    <span
                      style={{
                        width: `${drivers.length ? (drivers.filter((driver) => driver.is_online).length / drivers.length) * 100 : 0}%`,
                      }}
                    />
                    <span
                      style={{
                        width: `${drivers.length ? (drivers.filter((driver) => !driver.is_online && driver.status === "approved").length / drivers.length) * 100 : 0}%`,
                      }}
                    />
                    <span
                      style={{
                        width: `${drivers.length ? (pendingDrivers / drivers.length) * 100 : 0}%`,
                      }}
                    />
                  </div>
                  <div className="legend-row">
                    <i className="dot green-dot" />
                    <span>Online</span>
                    <strong>
                      {drivers.filter((driver) => driver.is_online).length}
                    </strong>
                  </div>
                  <div className="legend-row">
                    <i className="dot blue-dot" />
                    <span>Offline / approved</span>
                    <strong>
                      {
                        drivers.filter(
                          (driver) =>
                            !driver.is_online && driver.status === "approved",
                        ).length
                      }
                    </strong>
                  </div>
                  <div className="legend-row">
                    <i className="dot gray-dot" />
                    <span>Pending</span>
                    <strong>{pendingDrivers}</strong>
                  </div>
                  <button
                    className="text-action"
                    onClick={() => setSection("Drivers")}
                  >
                    Manage drivers <ArrowDownRight size={16} />
                  </button>
                </section>
              </div>

              <section className="panel table-panel">
                <div className="panel-heading">
                  <div>
                    <h2>Recent rides</h2>
                    <p>Latest activity returned by the backend</p>
                  </div>
                  <button
                    className="text-action"
                    onClick={() => setSection("Rides")}
                  >
                    View all rides <ArrowDownRight size={16} />
                  </button>
                </div>
                <RideTable rows={toRideRows(rides.slice(0, 5))} />
              </section>
            </>
          )}

          {section === "Drivers" && (
            <section className="panel table-panel">
              <div className="panel-heading">
                <div>
                  <h2>Driver management</h2>
                  <p>Review driver accounts and access status</p>
                </div>
                <span className="subtle-chip">
                  {visibleDrivers.length} records
                </span>
              </div>
              <div className="filters-row">
                <div className="filter-group">
                  {["All", "Pending", "Approved", "Suspended"].map((filter) => (
                    <button
                      key={filter}
                      className={`filter-btn ${driverFilter === filter ? "selected" : ""}`}
                      onClick={() => setDriverFilter(filter)}
                    >
                      {filter}
                    </button>
                  ))}
                </div>
                <SearchBox value={search} onChange={setSearch} />
              </div>
              <DriverTable
                rows={visibleDrivers}
                busy={actionBusy}
                onStatusChange={handleDriverAction}
              />
              <p className="data-footnote">
                Driver details and status are loaded from the backend. Driver
                names and phone numbers are not included in the admin driver
                response.
              </p>
            </section>
          )}

          {section === "Rides" && (
            <section className="panel table-panel">
              <div className="panel-heading">
                <div>
                  <h2>Ride management</h2>
                  <p>Review trips and current statuses</p>
                </div>
                <span className="subtle-chip">
                  {visibleRides.length} records
                </span>
              </div>
              <div className="filters-row">
                <div className="filter-group">
                  {[
                    "All",
                    "Requested",
                    "Driver Assigned",
                    "Driver Arrived",
                    "In Progress",
                    "Completed",
                    "Cancelled",
                    "No Drivers",
                  ].map((filter) => (
                    <button
                      key={filter}
                      className={`filter-btn ${rideFilter === filter ? "selected" : ""}`}
                      onClick={() => setRideFilter(filter)}
                    >
                      {filter}
                    </button>
                  ))}
                </div>
                <SearchBox value={search} onChange={setSearch} />
              </div>
              <RideTable rows={toRideRows(visibleRides)} />
            </section>
          )}

          {section === "Live Map" && (
            <section className="panel map-panel">
              <div className="panel-heading">
                <div>
                  <h2>Live network map</h2>
                  <p>
                    Online drivers and active rides · Refreshes every 10 seconds
                  </p>
                </div>
                <button
                  className="refresh-button"
                  onClick={() => {
                    void getAdminMap()
                      .then((result) => {
                        setMapData(result);
                        setMapError("");
                      })
                      .catch((error: unknown) => {
                        setMapError(errorMessage(error));
                      });
                  }}
                  disabled={mapLoading}
                >
                  <RefreshCw size={16} />
                  Refresh
                </button>
                <button
                  className="refresh-button"
                  onClick={() => setMapFitRequest((value) => value + 1)}
                >
                  <MapPinned size={16} />
                  Fit map
                </button>
              </div>

              {mapError && (
                <div className="data-error" role="alert">
                  {mapError}
                </div>
              )}

              {mapLoading && (
                <div className="loading-note">Updating map data…</div>
              )}

              <div className="map-legend">
                <span>
                  <i className="dot green-dot" /> Online drivers
                </span>
                <span>
                  <i className="dot blue-dot" /> Ride pickup / route
                </span>
                <span>
                  <i className="dot" style={{ background: "#fb923c" }} />{" "}
                  Drop-off
                </span>
              </div>

              <LiveMap data={mapData} fitRequest={mapFitRequest} />

              <div className="map-footer">
                <span>
                  Online drivers: <strong>{mapData.drivers.length}</strong>
                </span>
                <span>
                  Active rides: <strong>{mapData.rides.length}</strong>
                </span>
                <span>Automatic refresh: 10 seconds</span>
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}

function toRideRows(items: Ride[]) {
  return items.map((ride) => ({
    id: ride.id,
    rider:
      ride.rider?.name ||
      (ride.rider?.id ? `Rider ${ride.rider.id.slice(0, 8)}` : "Unknown rider"),
    driver:
      ride.driver?.name ||
      (ride.driver?.id ? `Driver ${ride.driver.id.slice(0, 8)}` : "Unassigned"),
    vehicle: ride.driver?.vehicle_type || ride.vehicle_type || "—",
    fare: formatMoney(ride.fare_final_paise ?? ride.fare_estimate_paise),
    status: rideStatusLabels[ride.status] ?? titleCase(ride.status),
    time: formatTime(ride.requested_at),
  }));
}

function StatCard({
  label,
  value,
  change,
  icon,
  tone,
  note,
}: {
  label: string;
  value: string;
  change: string;
  icon: React.ReactNode;
  tone: string;
  note: string;
}) {
  return (
    <section className="stat-card">
      <div className={`stat-icon ${tone}`}>{icon}</div>
      <div className="stat-label">{label}</div>
      <strong className="stat-value">{value}</strong>
      <div className="stat-bottom">
        <span
          className={tone === "amber" ? "neutral-change" : "positive-change"}
        >
          {change}
        </span>
        <span>{note}</span>
      </div>
    </section>
  );
}

function SearchBox({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="search-box">
      <Search size={17} />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Search records..."
      />
    </label>
  );
}

type RideRow = {
  id: string;
  rider: string;
  driver: string;
  vehicle: string;
  fare: string;
  status: string;
  time: string;
};

function RideTable({ rows }: { rows: RideRow[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Ride ID</th>
            <th>Rider / Driver</th>
            <th>Vehicle</th>
            <th>Fare</th>
            <th>Status</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((ride) => (
            <tr key={ride.id}>
              <td>
                <strong className="ride-id">{ride.id.slice(0, 12)}</strong>
              </td>
              <td>
                <strong>{ride.rider}</strong>
                <small className="cell-subtitle">Driver: {ride.driver}</small>
              </td>
              <td>{ride.vehicle}</td>
              <td className="fare">{ride.fare}</td>
              <td>
                <Badge value={ride.status} />
              </td>
              <td className="time-cell">{ride.time}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <div className="empty-state">No rides match your search.</div>
      )}
    </div>
  );
}

function DriverTable({
  rows,
  busy,
  onStatusChange,
}: {
  rows: Driver[];
  busy: string | null;
  onStatusChange: (userId: string, action: "approve" | "suspend") => void;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Driver account</th>
            <th>Vehicle</th>
            <th>Online</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((driver) => {
            const pendingApprove = busy === `${driver.user_id}:approve`;
            const pendingSuspend = busy === `${driver.user_id}:suspend`;
            return (
              <tr key={driver.user_id}>
                <td>
                  <div className="driver-cell">
                    <div className="driver-avatar">
                      {driver.vehicle_type.slice(0, 2).toUpperCase()}
                    </div>
                    <div>
                      <strong>{driver.user_id.slice(0, 12)}</strong>
                      <small className="cell-subtitle">
                        ID: {driver.user_id}
                      </small>
                    </div>
                  </div>
                </td>
                <td>
                  <strong>
                    {driver.vehicle_model || "Model not provided"}
                  </strong>
                  <small className="cell-subtitle">
                    {driver.vehicle_type} · {driver.vehicle_number}
                  </small>
                </td>
                <td>{driver.is_online ? "Online" : "Offline"}</td>
                <td>
                  <Badge value={titleCase(driver.status)} />
                </td>
                <td>
                  <div className="row-actions">
                    {driver.status !== "approved" && (
                      <button
                        className="approve-btn"
                        disabled={Boolean(busy)}
                        onClick={() =>
                          onStatusChange(driver.user_id, "approve")
                        }
                      >
                        <CheckCircle2 size={15} />{" "}
                        {pendingApprove ? "Approving…" : "Approve"}
                      </button>
                    )}
                    {driver.status !== "suspended" && (
                      <button
                        className="suspend-btn"
                        disabled={Boolean(busy)}
                        onClick={() =>
                          onStatusChange(driver.user_id, "suspend")
                        }
                      >
                        <XCircle size={15} />{" "}
                        {pendingSuspend ? "Suspending…" : "Suspend"}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length === 0 && (
        <div className="empty-state">No drivers match your search.</div>
      )}
    </div>
  );
}

export default App;
