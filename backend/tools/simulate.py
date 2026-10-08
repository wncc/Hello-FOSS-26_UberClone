"""Simulated driver or rider, for trying one app without a second phone.

    # A driver near Dadar who accepts every ride, drives the roads to the pickup, asks you for the
    # rider's PIN (shown in the rider app), drives to the drop and completes:
    python -m backend.tools.simulate driver --near 19.0178,72.8478 --vehicle auto_rickshaw

    # A rider who books Dadar -> BKC and prints the PIN for the driver app:
    python -m backend.tools.simulate rider --pickup 19.0178,72.8478 --drop 19.0607,72.8636 --vehicle auto_rickshaw

Dev backend only (uses the dev OTP returned by /auth/otp/request).
"""
from __future__ import annotations

import argparse
import random
import time

import httpx


def latlng(text: str) -> tuple[float, float]:
    lat, lng = (float(x) for x in text.split(","))
    return lat, lng


class Client:
    def __init__(self, api: str, phone: str, role: str, name: str):
        self.http = httpx.Client(base_url=api.rstrip("/"), timeout=10)
        code = self.call("POST", "/auth/otp/request", {"phone": phone})["dev_code"]
        if not code:
            raise SystemExit("backend is not in dev mode (no dev OTP)")
        tokens = self.call("POST", "/auth/otp/verify", {"phone": phone, "code": code, "role": role})
        self.http.headers["Authorization"] = f"Bearer {tokens['access_token']}"
        if not tokens["user"]["name"]:
            self.call("PATCH", "/me", {"name": name})
        print(f"logged in as {role} {phone}")

    def call(self, method: str, path: str, body: dict | None = None, ok=(200, 201, 202, 204)):
        res = self.http.request(method, path, json=body)
        if res.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {res.status_code}: {res.text}")
        return res.json() if res.content else None


def drive(c: Client, path: list[tuple[float, float]], seconds: float) -> None:
    """Report positions along a road path (from GET /rides/{id}/route), about every 2 s."""
    if len(path) < 2:
        return
    steps = max(2, int(seconds / 2))
    for i in range(1, steps + 1):
        lat, lng = path[min(len(path) - 1, round(i * (len(path) - 1) / steps))]
        c.call("POST", "/drivers/me/location", {"lat": lat, "lng": lng})
        time.sleep(seconds / steps)


def run_driver(args) -> None:
    c = Client(args.api, args.phone, "driver", "Sim Driver")
    profile = c.call("GET", "/drivers/me", ok=(200, 404))
    if profile is None or profile.get("vehicle_type") != args.vehicle:
        c.call("POST", "/drivers/me/online", {"online": False}, ok=(200, 403, 409))
        c.call("PUT", "/drivers/me", {"vehicle_type": args.vehicle, "vehicle_number": "KA01SIM" + args.phone[-3:],
                                      "vehicle_model": "Simulator"})
    here = (args.near[0] + random.uniform(-0.004, 0.004), args.near[1] + random.uniform(-0.004, 0.004))
    c.call("POST", "/drivers/me/location", {"lat": here[0], "lng": here[1]})
    c.call("POST", "/drivers/me/online", {"online": True})
    print(f"online as {args.vehicle} at {here[0]:.5f},{here[1]:.5f}; waiting for pings (Ctrl+C to stop)")
    active = c.call("GET", "/rides/active")
    if active:                                                   # resume a trip left over from a previous run
        print(f"resuming ride {active['id']} ({active['status']})")
        here = do_trip(c, active, here, args.speed)

    last_beat = 0.0
    try:
        while True:
            if time.time() - last_beat > 10:                     # keep GPS fresh while idle
                c.call("POST", "/drivers/me/location", {"lat": here[0], "lng": here[1]})
                last_beat = time.time()
            offer = c.call("GET", "/drivers/me/offer")
            if offer:
                print(f"ping: {offer['ride_id']} fare Rs {offer['fare_paise'] / 100:.0f} -> accepting")
                c.call("POST", f"/rides/{offer['ride_id']}/accept", ok=(202, 409))
                ride = wait_for_assignment(c, offer["ride_id"])
                if ride:
                    here = do_trip(c, ride, here, args.speed)
            time.sleep(1)
    except KeyboardInterrupt:
        c.call("POST", "/drivers/me/online", {"online": False}, ok=(200, 409))
        print("offline")


def wait_for_assignment(c: Client, ride_id: str, timeout: float = 15) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        active = c.call("GET", "/rides/active")
        if active and active["id"] == ride_id:
            print("confirmed: driving to pickup")
            return active
        time.sleep(1)
    print("another driver got the ride")
    return None


def do_trip(c: Client, ride: dict, here: tuple[float, float], speed: float) -> tuple[float, float]:
    pickup = (ride["pickup"]["lat"], ride["pickup"]["lng"])
    drop = (ride["drop"]["lat"], ride["drop"]["lng"])
    if ride["status"] == "driver_assigned":
        approach = c.call("GET", f"/rides/{ride['id']}/route")["approach"] or [here, pickup]
        drive(c, [tuple(p) for p in approach], 10 / speed)
        if c.call("GET", f"/rides/{ride['id']}")["status"] == "cancelled":
            print("rider cancelled")
            return pickup
        c.call("POST", f"/rides/{ride['id']}/arrived")
    while c.call("GET", f"/rides/{ride['id']}")["status"] == "driver_arrived":
        pin = input("arrived. Enter the PIN shown in the rider app: ").strip()
        try:
            c.call("POST", f"/rides/{ride['id']}/start", {"pin": pin})
            break
        except RuntimeError as e:
            print(e)
    status = c.call("GET", f"/rides/{ride['id']}")["status"]
    if status != "in_progress":
        print(f"ride is {status}")
        return pickup
    print("trip started")
    trip = c.call("GET", f"/rides/{ride['id']}/route")["trip"]
    drive(c, [tuple(p) for p in trip], 15 / speed)
    done = c.call("POST", f"/rides/{ride['id']}/complete")
    print(f"completed: collect Rs {done['fare_final_paise'] / 100:.0f} cash")
    c.call("POST", f"/rides/{ride['id']}/rating", {"stars": 5}, ok=(201, 409))
    return drop


def run_rider(args) -> None:
    c = Client(args.api, args.phone, "rider", "Sim Rider")
    ride = c.call("GET", "/rides/active") or c.call("POST", "/rides", {
        "pickup": {"lat": args.pickup[0], "lng": args.pickup[1], "address": "Sim pickup"},
        "drop": {"lat": args.drop[0], "lng": args.drop[1], "address": "Sim drop"},
        "vehicle_type": args.vehicle})
    print(f"ride {ride['id']}: fare Rs {ride['fare_estimate_paise'] / 100:.0f}, PIN {ride['pin']}")
    status = None
    while status not in ("completed", "cancelled", "no_drivers"):
        ride = c.call("GET", f"/rides/{ride['id']}")
        if ride["status"] != status:
            status = ride["status"]
            driver = f" ({ride['driver']['name']}, {ride['driver']['vehicle_number']})" if ride["driver"] else ""
            print(f"status: {status}{driver}" + (f"  -> tell the driver PIN {ride['pin']}" if status == "driver_arrived" else ""))
        time.sleep(2)
    if status == "completed":
        c.call("POST", f"/rides/{ride['id']}/rating", {"stars": 5}, ok=(201, 409))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default="http://localhost:8000")
    sub = p.add_subparsers(dest="role", required=True)
    d = sub.add_parser("driver")
    d.add_argument("--phone", default="9000000101")
    d.add_argument("--near", type=latlng, default=(19.0178, 72.8478))           # Dadar
    d.add_argument("--vehicle", default="car", choices=["car", "auto_rickshaw", "bike"])
    d.add_argument("--speed", type=float, default=1.0, help="simulation speed-up")
    r = sub.add_parser("rider")
    r.add_argument("--phone", default="9000000201")
    r.add_argument("--pickup", type=latlng, default=(19.0178, 72.8478))         # Dadar
    r.add_argument("--drop", type=latlng, default=(19.0607, 72.8636))           # BKC
    r.add_argument("--vehicle", default="car", choices=["car", "auto_rickshaw", "bike"])
    args = p.parse_args()
    (run_driver if args.role == "driver" else run_rider)(args)


if __name__ == "__main__":
    main()
