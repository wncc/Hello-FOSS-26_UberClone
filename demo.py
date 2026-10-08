"""Phone demo: backend + automatic drivers, so you can watch a whole ride on your phone.

    python demo.py                               # drivers near Dadar, Mumbai
    python demo.py --near 19.0596,72.8295        # drivers near your own location (lat,lng)

Then, in another window:  cd mobile ; npm run start:rider   and scan the QR code with Expo Go.
Book a ride near the drivers (within ~4 km). A simulated cab, auto and bike driver is online;
the one for the vehicle you book accepts, drives the roads to you, starts the trip on its own
(no PIN typing), drives to the drop and completes. Ctrl+C stops everything.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8000   # the apps look for the backend on port 8000 of this computer
DRIVERS = [("car", "9000000111"), ("auto_rickshaw", "9000000112"), ("bike", "9000000113")]


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_backend(proc: subprocess.Popen, port: int, timeout: float = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2)
            return
        except OSError:
            if proc.poll() is not None:
                raise SystemExit("backend stopped; see the messages above")
            time.sleep(1)
    raise SystemExit("backend did not start")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--near", default="19.0178,72.8478", help="lat,lng where the drivers wait (default Dadar)")
    parser.add_argument("--speed", type=float, default=1.0, help="how fast the drivers move (2 = twice as fast)")
    parser.add_argument("--port", type=int, default=PORT, help="backend port (the apps expect 8000)")
    args = parser.parse_args()
    port = args.port
    if port_in_use(port):
        raise SystemExit(
            f"Port {port} is already in use, probably by a backend you started earlier. "
            "Stop it (Ctrl+C in its window) and run demo.py again; the demo starts its own backend.")

    env = {**os.environ, "APP_ENV": "dev", "PYTHONIOENCODING": "utf-8"}
    print(f"Starting the backend on port {port} (loading Mumbai roads takes ~20 s) ...")
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0",
                                "--port", str(port)], cwd=ROOT, env=env)
    procs = [backend]
    try:
        wait_for_backend(backend, port)
        for vehicle, phone in DRIVERS:
            procs.append(subprocess.Popen(
                [sys.executable, "-u", "-m", "backend.tools.simulate", "--api", f"http://localhost:{port}", "driver",
                 "--phone", phone, "--vehicle", vehicle, "--near", args.near, "--speed", str(args.speed),
                 "--auto-pin"], cwd=ROOT, env=env))
        print("\n" + "=" * 70)
        print(f" Demo running. Simulated cab, auto and bike drivers are online near {args.near}.")
        print(" Next: open another window ->  cd mobile ; npm run start:rider")
        print(" Scan the QR code with Expo Go, book a ride near the drivers, and watch.")
        print(" Ctrl+C here stops the backend and the drivers.")
        print("=" * 70 + "\n")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(procs):
            p.terminate()
        print("demo stopped")


if __name__ == "__main__":
    main()
