# e2e/

A browser robot that plays **a complete ride through the real rider and driver apps**, checking each screen and saving screenshots of both "phones" at every step. Full documentation: [docs/TESTING.md](../docs/TESTING.md).

```powershell
python e2e/run_e2e.py                          # headless; writes e2e/report/index.html
python e2e/run_e2e.py --headed --slow-mo 400   # watch it in real browser windows
python e2e/run_e2e.py --skip-build             # reuse the last app build (faster)
```

It starts its own backend (ports 8790–8792, with a fresh database) and builds both apps for the browser. It needs `data/roads.pkl` for the route checks. `e2e/.build/` and `e2e/report/` are generated and not committed.

To add a scenario, follow `scenario()` in `run_e2e.py`: each `run_.step(...)` checks what's on screen with `see(...)` and gets a screenshot.
