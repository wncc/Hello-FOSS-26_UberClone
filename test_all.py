"""Run every check in the project and open the visual report.

    python test_all.py              # everything (takes ~3-5 minutes)
    python test_all.py --quick      # skip the browser end-to-end ride
    python test_all.py --no-open    # don't open the report in the browser

Checks, in order:
  1. Python tests: routing, matching, backend API (pytest)
  2. App typecheck (tsc) and lint (eslint)
  3. App unit tests (jest): formatting, ride state, socket, API client, map page with real Leaflet
  4. End-to-end ride in two browser "phones" (rider + driver) through the real UI, with
     screenshots of every step -> e2e/report/index.html
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MOBILE = ROOT / "mobile"


def check(name: str, cmd: str, cwd: Path = ROOT) -> tuple[str, bool, float]:
    print(f"\n=== {name} ===\n$ {cmd}", flush=True)
    started = time.time()
    ok = subprocess.run(cmd, shell=True, cwd=cwd).returncode == 0
    return name, ok, time.time() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="skip the end-to-end browser test")
    parser.add_argument("--no-open", action="store_true", help="don't open the report")
    args = parser.parse_args()

    results = [
        check("Python tests (routing, matching, backend)", f'"{sys.executable}" -m pytest -q -p no:warnings'),
        check("App typecheck", "npx tsc --noEmit", MOBILE),
        check("App lint", "npx eslint src app.config.ts metro.config.js", MOBILE),
        check("App unit tests", "npx jest", MOBILE),
    ]
    report = ROOT / "e2e" / "report" / "index.html"
    if not args.quick:
        results.append(check("End-to-end ride in the real UI (rider + driver)", f'"{sys.executable}" e2e/run_e2e.py'))

    print("\n" + "=" * 64)
    for name, ok, secs in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({secs:.0f}s)")
    print("=" * 64)
    if not args.quick:
        print(f"Screenshots of every step: {report}")
        if not args.no_open and report.exists():
            webbrowser.open(report.as_uri())
    failed = [n for n, ok, _ in results if not ok]
    print("ALL CHECKS PASSED" if not failed else f"FAILED: {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
