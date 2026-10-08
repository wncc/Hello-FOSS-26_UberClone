"""End-to-end test: a full ride through the real rider and driver apps, in a browser.

    python e2e/run_e2e.py [--skip-build] [--headed] [--slow-mo 300]

What it does:
  1. starts the backend (fresh database, Mumbai road data if data/roads.pkl exists)
  2. builds both apps for the browser (Expo web) and serves them
  3. opens two phone-sized browsers, a rider and a driver, with GPS set in Mumbai
  4. plays a complete ride through the actual UI, checking what is on screen at every step
     (texts, map tiles loaded, road route drawn, driver's path to the pickup, PIN, fare, ...)
  5. writes e2e/report/index.html with a screenshot of both phones after every step

Exit code 0 = every step passed.
"""
from __future__ import annotations

import argparse
import html
import http.server
import json
import os
import random
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "e2e" / ".build"
REPORT = ROOT / "e2e" / "report"
API_PORT, RIDER_PORT, DRIVER_PORT = 8790, 8791, 8792
API = f"http://localhost:{API_PORT}"

PICKUP_GPS = {"latitude": 19.0178, "longitude": 72.8478}     # Dadar, Mumbai
DRIVER_GPS = {"latitude": 19.0215, "longitude": 72.8440}     # ~550 m away
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}
STEP_TIMEOUT_MS = 45_000


# --------------------------------------------------------------------------- #
# Infrastructure
# --------------------------------------------------------------------------- #

def run(cmd: str, env: dict | None = None, cwd: Path = ROOT) -> None:
    print(f"$ {cmd}")
    subprocess.run(cmd, shell=True, check=True, cwd=cwd, env={**os.environ, **(env or {})})


def build_apps() -> None:
    for variant in ("rider", "driver"):
        out = BUILD / variant
        shutil.rmtree(out, ignore_errors=True)
        run(f'npx expo export --platform web --clear --output-dir "{out}"', cwd=ROOT / "mobile",
            env={"EXPO_PUBLIC_API_URL": API, "EXPO_PUBLIC_APP_VARIANT": variant, "CI": "1"})


class SpaHandler(http.server.SimpleHTTPRequestHandler):
    """Static files, falling back to index.html for client-side routes."""

    def translate_path(self, path):
        full = super().translate_path(path)
        return full if os.path.exists(full) else os.path.join(self.directory, "index.html")

    def log_message(self, *args):
        pass


def serve(directory: Path, port: int) -> socketserver.TCPServer:
    socketserver.TCPServer.allow_reuse_address = True
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), partial(SpaHandler, directory=str(directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def start_backend() -> subprocess.Popen:
    db = BUILD / f"e2e-{int(time.time())}.db"
    log = open(BUILD / "backend.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", str(API_PORT)], cwd=ROOT,
        env={**os.environ, "APP_ENV": "dev", "DATABASE_URL": f"sqlite+aiosqlite:///{db.as_posix()}"},
        stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{API}/health", timeout=2)
            return proc
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(f"backend exited; see {BUILD / 'backend.log'}")
            time.sleep(1)
    proc.kill()
    raise RuntimeError("backend did not start within 120 s")


# --------------------------------------------------------------------------- #
# Steps and report
# --------------------------------------------------------------------------- #

@dataclass
class Step:
    name: str
    ok: bool = True
    detail: str = ""
    checks: list[str] = field(default_factory=list)
    shots: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0


class Run:
    def __init__(self, phones: dict[str, Page]):
        self.phones = phones
        self.steps: list[Step] = []

    def step(self, name: str, fn) -> bool:
        print(f"• {name} ...", end=" ", flush=True)
        s = Step(name)
        started = time.time()
        try:
            fn(s)
        except Exception as e:  # noqa: BLE001  (record any failure and stop)
            s.ok, s.detail = False, f"{type(e).__name__}: {str(e).splitlines()[0][:400]}"
            (REPORT / f"error-{len(self.steps)}.txt").write_text(traceback.format_exc(), encoding="utf-8")
        s.seconds = time.time() - started
        for who, page in self.phones.items():
            path = REPORT / f"{len(self.steps):02d}-{who}.png"
            try:
                page.screenshot(path=str(path))
                s.shots[who] = path.name
            except Exception:  # noqa: BLE001
                pass
        self.steps.append(s)
        print("ok" if s.ok else f"FAILED: {s.detail}")
        return s.ok

    def write_report(self) -> Path:
        rows = []
        for i, s in enumerate(self.steps):
            shots = "".join(f'<figure><img src="{html.escape(f)}" loading="lazy"><figcaption>{w}</figcaption></figure>'
                            for w, f in s.shots.items())
            checks = "".join(f"<li>{html.escape(c)}</li>" for c in s.checks)
            rows.append(f'''<section class="{'ok' if s.ok else 'fail'}">
  <h2>{i + 1}. {html.escape(s.name)} <span>{'PASS' if s.ok else 'FAIL'} · {s.seconds:.1f}s</span></h2>
  {f'<p class="err">{html.escape(s.detail)}</p>' if s.detail else ''}<ul>{checks}</ul><div class="shots">{shots}</div>
</section>''')
        passed = sum(s.ok for s in self.steps)
        page = f'''<!doctype html><meta charset="utf-8"><title>Ride E2E report</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#f9fafb;color:#111827}}
h1{{margin:0 0 4px}} .sum{{margin:0 0 24px;color:#374151}}
section{{background:#fff;border-radius:12px;padding:16px;margin:0 0 16px;border-left:6px solid #10b981}}
section.fail{{border-left-color:#dc2626}} h2{{font-size:18px;margin:0 0 8px}} h2 span{{font-weight:400;color:#6b7280;font-size:14px}}
.err{{color:#dc2626;font-family:monospace;white-space:pre-wrap}} ul{{margin:4px 0 12px;color:#374151}}
.shots{{display:flex;gap:16px;flex-wrap:wrap}} figure{{margin:0}} img{{width:260px;border:1px solid #e5e7eb;border-radius:16px}}
figcaption{{text-align:center;color:#6b7280;font-size:13px}}
</style>
<h1>Ride end-to-end test</h1>
<p class="sum">{passed}/{len(self.steps)} steps passed · {time.strftime('%Y-%m-%d %H:%M')} · backend {API}</p>
{''.join(rows)}'''
        out = REPORT / "index.html"
        out.write_text(page, encoding="utf-8")
        (REPORT / "summary.json").write_text(json.dumps(
            [{"step": s.name, "ok": s.ok, "detail": s.detail, "checks": s.checks} for s in self.steps], indent=2),
            encoding="utf-8")
        return out


# --------------------------------------------------------------------------- #
# Page helpers
# --------------------------------------------------------------------------- #

def text(page: Page, s: str):
    return page.get_by_text(s, exact=False).first


def button(page: Page, name: str):
    return page.get_by_role("button", name=name).first


def see(step: Step, page: Page, s: str, timeout: int = STEP_TIMEOUT_MS) -> None:
    expect(text(page, s)).to_be_visible(timeout=timeout)
    step.checks.append(f"shows “{s}”")


def map_frame(page: Page):
    return page.frame_locator("iframe[title=map]").last


def map_ready(step: Step, page: Page) -> None:
    frame = map_frame(page)
    expect(frame.locator(".leaflet-container")).to_be_visible(timeout=STEP_TIMEOUT_MS)
    expect(frame.locator("img.leaflet-tile-loaded").first).to_be_visible(timeout=STEP_TIMEOUT_MS)
    step.checks.append("map loaded with tiles")


def path_points(page: Page) -> list[int]:
    """Number of points in each line drawn on the map (Leaflet SVG paths, markers excluded)."""
    ds = map_frame(page).locator("path.leaflet-interactive").evaluate_all("els => els.map(e => e.getAttribute('d'))")
    return sorted((len(re.findall(r"[ML]", d or "")) for d in ds if d and "a" not in d), reverse=True)


def expect_road_route(step: Step, page: Page, min_lines: int = 1, label: str = "route") -> None:
    deadline = time.time() + 20
    lines = []
    while time.time() < deadline:
        lines = [n for n in path_points(page) if n > 2]
        if len(lines) >= min_lines:
            break
        time.sleep(0.5)
    if len(lines) < min_lines:
        raise AssertionError(f"expected {min_lines} road line(s) on the map, found point counts {path_points(page)}")
    step.checks.append(f"{label}: {len(lines)} road line(s) drawn, {lines} points (a straight line would be 2)")
    route_in_view(step, page)


def route_in_view(step: Step, page: Page) -> None:
    """The drawn lines must be inside the visible map, not zoomed past or off to a side."""
    time.sleep(1.0)                                              # let Leaflet's zoom animation settle
    frame = map_frame(page)
    view = frame.locator(".leaflet-container").bounding_box()
    boxes = [b for b in (frame.locator("path.leaflet-interactive").nth(i).bounding_box()
                         for i in range(frame.locator("path.leaflet-interactive").count())) if b]
    if not boxes:
        raise AssertionError("no lines on the map")
    left, top = min(b["x"] for b in boxes), min(b["y"] for b in boxes)
    right, bottom = max(b["x"] + b["width"] for b in boxes), max(b["y"] + b["height"] for b in boxes)
    inside = left >= view["x"] - 2 and right <= view["x"] + view["width"] + 2 and top >= view["y"] - 2
    if not inside:
        raise AssertionError(f"route not fully in view: lines span x {left:.0f}-{right:.0f}, "
                             f"map is x {view['x']:.0f}-{view['x'] + view['width']:.0f}")
    step.checks.append("whole route is inside the visible map")


def login(page: Page, port: int, phone: str, name: str, step: Step) -> None:
    page.goto(f"http://localhost:{port}/")
    page.get_by_placeholder("98450 12345").fill(phone)
    button(page, "Send code").click()
    see(step, page, "Development mode: the code is")
    button(page, "Verify").click()
    page.get_by_placeholder("Full name").fill(name)
    button(page, "Continue").click()


# --------------------------------------------------------------------------- #
# The scenario
# --------------------------------------------------------------------------- #

def scenario(run_: Run, rider: Page, driver: Page) -> None:
    ride = {}
    phones = [f"9{random.randint(600000000, 999999999)}" for _ in range(2)]

    def rider_login(s):
        login(rider, RIDER_PORT, phones[0], "Asha Rider", s)
        see(s, rider, "PICKUP")
        map_ready(s, rider)
    if not run_.step("Rider logs in with OTP and sets a name", rider_login):
        return

    def driver_login(s):
        login(driver, DRIVER_PORT, phones[1], "Ravi Driver", s)
        see(s, driver, "Riders see these details")             # first login -> vehicle setup
        text(driver, "Auto").click()
        driver.get_by_placeholder("KA 01 AB 1234").fill("MH01AB1234")
        button(driver, "Save").click()
        see(s, driver, "you’re offline")
    if not run_.step("Driver logs in and registers an auto rickshaw", driver_login):
        return

    def driver_online(s):
        button(driver, "Go online").click()
        see(s, driver, "Finding rides near you")
        map_ready(s, driver)
    if not run_.step("Driver goes online", driver_online):
        return

    def set_pickup_and_drop(s):
        button(rider, "Confirm pickup").click()
        see(s, rider, "DROP")
        box = rider.locator("iframe[title=map]").last.bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        for _ in range(2):                                        # drag the map so the drop is ~2 km north-east
            rider.mouse.move(cx, cy)
            rider.mouse.down()
            rider.mouse.move(cx - 120, cy + 160, steps=12)
            rider.mouse.up()
            time.sleep(0.6)
        s.checks.append("dragged the map to place the drop pin")
        button(rider, "Confirm drop").click()
        for label in ("Bike", "Auto", "Cab"):
            see(s, rider, label)
        expect_road_route(s, rider, label="fare preview route")
    if not run_.step("Rider sets pickup and drop; fares and road route appear", set_pickup_and_drop):
        return

    def book(s):
        text(rider, "Auto").click()
        button(rider, "Book Auto · Cash").click()
        see(s, rider, "Finding you a driver")
    if not run_.step("Rider books an auto (cash)", book):
        return

    def driver_pinged(s):
        see(s, driver, "New ride")
        s.checks.append("ping shows fare, pickup, drop and a countdown")
        button(driver, "Accept").click()
        see(s, driver, "Pick up at")                              # confirmed -> trip screen
        expect_road_route(s, driver, label="trip route")
    if not run_.step("Driver is pinged, accepts and is confirmed", driver_pinged):
        return

    def rider_sees_driver(s):
        see(s, rider, "Driver is on the way")
        see(s, rider, "Ravi Driver")
        see(s, rider, "MH01AB1234")
        match = re.search(r"PIN\s*(\d{4})", rider.locator("body").inner_text())
        if not match:
            raise AssertionError("PIN not shown to the rider")
        ride["pin"] = match.group(1)
        s.checks.append(f"rider sees PIN {ride['pin']}")
        expect_road_route(s, rider, min_lines=2, label="trip route + driver's way to the pickup")
    if not run_.step("Rider sees the driver, the PIN and both routes", rider_sees_driver):
        return

    def arrive_and_start(s):
        button(driver, "I've arrived").click()
        see(s, driver, "Ask the rider for their 4-digit PIN")
        see(s, rider, "Driver has arrived")
        wrong = "0000" if ride["pin"] != "0000" else "1111"
        driver.get_by_placeholder("PIN").fill(wrong)
        button(driver, "Start trip").click()
        see(s, driver, "wrong PIN")
        driver.get_by_placeholder("PIN").fill(ride["pin"])
        button(driver, "Start trip").click()
        see(s, driver, "Drop at")
        see(s, rider, "On the trip")
    if not run_.step("Driver arrives; wrong PIN rejected, right PIN starts the trip", arrive_and_start):
        return

    def complete(s):
        button(driver, "Complete trip").click()
        see(s, driver, "in cash")
        see(s, rider, "Trip completed")
        fare = re.search(r"Pay\s*(₹[\d,]+)", rider.locator("body").inner_text())
        s.checks.append(f"rider is asked to pay {fare.group(1) if fare else '?'} in cash")
    if not run_.step("Driver completes; both see the fare", complete):
        return

    def rate(s):
        rider.get_by_label("5 stars").click()
        button(rider, "Submit").click()
        see(s, rider, "PICKUP")                                   # back to booking
        driver.get_by_label("4 stars").click()
        button(driver, "Done").click()
        see(s, driver, "Finding rides near you")
    if not run_.step("Both rate each other and return home", rate):
        return

    def history(s):
        text(rider, "Rides").click()
        see(s, rider, "Completed")
        text(driver, "Earnings").click()
        see(s, driver, "Today’s earnings")
        see(s, driver, "Completed")
    run_.step("Ride appears in rider history and driver earnings", history)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-build", action="store_true", help="reuse e2e/.build from the last run")
    parser.add_argument("--headed", action="store_true", help="show the browser windows")
    parser.add_argument("--slow-mo", type=int, default=0, help="ms pause between actions (with --headed)")
    args = parser.parse_args()

    BUILD.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(REPORT, ignore_errors=True)
    REPORT.mkdir(parents=True)
    if not (ROOT / "data" / "roads.pkl").exists():
        print("note: data/roads.pkl missing; routes will be straight lines and the route checks will fail")
    if not args.skip_build or not (BUILD / "rider" / "index.html").exists():
        build_apps()

    backend = start_backend()
    servers = [serve(BUILD / "rider", RIDER_PORT), serve(BUILD / "driver", DRIVER_PORT)]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed, slow_mo=args.slow_mo)
            phones = {}
            for who, gps in (("rider", PICKUP_GPS), ("driver", DRIVER_GPS)):
                ctx = browser.new_context(**PHONE, geolocation=gps, permissions=["geolocation"])
                phones[who] = ctx.new_page()
            run_ = Run(phones)
            scenario(run_, phones["rider"], phones["driver"])
            browser.close()
    finally:
        for s in servers:
            s.shutdown()
        backend.terminate()

    report = run_.write_report()
    passed = sum(s.ok for s in run_.steps)
    print(f"\n{passed}/{len(run_.steps)} steps passed. Report: {report}")
    return 0 if run_.steps and all(s.ok for s in run_.steps) else 1


if __name__ == "__main__":
    sys.exit(main())
