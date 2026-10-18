"""Smoke-test the Player Search tab with Edge over DevTools.

Spawns headless Edge on port 8001, exercises the page, captures console output and
a screenshot. Run with no args for a deep-link probe (`#/players?q=17861064`);
pass `--search` to test the search-widget click flow instead.

Per the project's CLAUDE.md, plain `--screenshot` captures before the JS stream
delivers state, so we drive Edge via DevTools and wait a few seconds before capture.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8001
URL_DEEPLINK = f"http://localhost:{PORT}/#/players?q=17861064"
URL_BLANK_PLAYERS = f"http://localhost:{PORT}/#/players"
USER_DATA = Path(os.environ.get("TEMP") or ".") / "aoe-warroom-edge-probe"
SCREENSHOT = Path(os.environ.get("TEMP") or ".") / "aoe-warroom-players-page.png"


async def main() -> int:
    if "--deeplink" in sys.argv:
        return await _probe(URL_DEEPLINK, expect_card_within=8,
                            probe_search=False)
    if "--search" in sys.argv:
        return await _probe(URL_BLANK_PLAYERS, expect_card_within=8,
                            probe_search=True)
    return await _probe(URL_DEEPLINK, expect_card_within=8,
                        probe_search=True)


async def _probe(url: str, expect_card_within: int, probe_search: bool) -> int:
    USER_DATA.mkdir(parents=True, exist_ok=True)
    SCREENSHOT.unlink(missing_ok=True)
    port = 9222
    proc = subprocess.Popen(
        [EDGE,
         "--headless=new",
         "--disable-gpu",
         "--no-first-run",
         "--no-default-browser-check",
         f"--user-data-dir={USER_DATA}",
         f"--remote-debugging-port={port}",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = await _wait_for_ws(port)
        return await _session(ws, url, expect_card_within, proc, probe_search)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _session(ws, url: str, wait_s: int, proc, probe_search: bool) -> int:
    console: list[str] = []
    exceptions: list[str] = []
    pending: dict[int, asyncio.Future] = {}
    loop = asyncio.get_event_loop()

    async def reader():
        async for raw in ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in pending:
                pending.pop(msg["id"]).set_result(msg)
                continue
            if msg.get("method") == "Runtime.exceptionThrown":
                details = msg["params"].get("exceptionDetails", {})
                ex = details.get("exception", {})
                desc = ex.get("description") or ex.get("value") or details.get("text")
                exceptions.append(f"{desc}\n{json.dumps(details, indent=2)[:2000]}")
            elif msg.get("method") == "Runtime.consoleAPICalled":
                kind = msg["params"]["type"]
                args = " ".join(a.get("value", "") for a in msg["params"].get("args", []))
                console.append(f"[{kind}] {args}")

    reader_task = asyncio.create_task(reader())
    msg_id = [1]
    async def send(method: str, params: dict | None = None) -> dict:
        mid = msg_id[0]; msg_id[0] += 1
        await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        fut = loop.create_future()
        pending[mid] = fut
        resp = await fut
        if "error" in resp:
            raise RuntimeError(f"CDP {method} errored: {resp['error']}")
        return resp

    await send("Runtime.enable")
    await send("Page.enable")
    await send("Log.enable")
    await send("Page.navigate", {"url": url})
    await asyncio.sleep(wait_s)

    if probe_search:
        # Type into the search input and click the first result. Exercises the search
        # widget's debounce + result-row click.
        await send("Runtime.evaluate", {"expression": """(() => {
            const inp = document.querySelector('.players-search .picker-input');
            if (!inp) return 'NO_INPUT';
            inp.focus();
            inp.value = 'The Law';
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            return 'TYPED';
        })()""", "returnByValue": True})
        await asyncio.sleep(1)  # debounce + fetch
        # Click the first non-current result row.
        await send("Runtime.evaluate", {"expression": """(() => {
            const rows = document.querySelectorAll('.players-search .picker-row');
            if (!rows.length) return 'NO_ROWS';
            rows[0].click();
            return 'CLICKED ' + rows[0].textContent.slice(0, 80);
        })()""", "returnByValue": True})
        await asyncio.sleep(wait_s)  # scout + a few playstyle snapshots

    diag = await send("Runtime.evaluate", {
        "expression": """(() => {
            const has = (sel) => !!document.querySelector(sel);
            const errEl = document.querySelector('.error');
            const rows = document.querySelectorAll('.players-search .picker-row');
            const ratings = document.querySelectorAll('.ratings-cell').length;
            const cardHeads = Array.from(document.querySelectorAll('.card .name'))
                .map(h => h.textContent?.trim() ?? '?');
            return JSON.stringify({
                hash: location.hash,
                hasPageTitle: has('.page-title'),
                hasPicker: has('.players-search'),
                hasCard: has('.card'),
                hasRatings: has('.ratings-grid'),
                ratingCount: ratings,
                cardNames: cardHeads,
                rowCount: rows.length,
                rowTexts: Array.from(rows).slice(0, 3).map(r => r.textContent.slice(0, 100)),
                hasPlaystyle: !!document.body.textContent.includes('Boom or rush'),
                errText: errEl ? errEl.textContent.slice(0, 300) : null,
            });
        })()""",
        "returnByValue": True})
    print("diag:", diag["result"]["result"].get("value"))

    resp = await send("Page.captureScreenshot", {"format": "png"})
    SCREENSHOT.write_bytes(base64.b64decode(resp["result"]["data"]))

    reader_task.cancel()
    try:
        await reader_task
    except (asyncio.CancelledError, Exception):
        pass

    if exceptions:
        print("\n!!! RUNTIME EXCEPTIONS:")
        for e in exceptions:
            print(e)
        return 1
    # Console errors that look like 4xx network failures (from the page's <img>s).
    bad_console = [c for c in console if c.startswith("[error]") or "Uncaught" in c]
    if bad_console:
        print("\n=== full console ===")
        for line in console:
            print(" ", line)
        return 1

    h = json.loads(diag["result"]["result"]["value"])
    must = ["hasPageTitle", "hasPicker", "hasCard", "hasRatings", "hasPlaystyle"]
    missing = [k for k in must if not h.get(k)]
    if missing:
        print(f"!! missing: {missing}")
        print(f"   full diag: {h}")
        return 2
    if not h.get("cardNames"):
        print(f"!! no card names found")
        return 2
    print(f"OK card={h['cardNames']!r} rows={h['rowCount']} ratings={h['ratingCount']} — {SCREENSHOT}")
    return 0


async def _wait_for_ws(port: int):
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as r:
                targets = json.loads(r.read())
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return await websockets.connect(
                        t["webSocketDebuggerUrl"], max_size=2 ** 20, ping_interval=None)
        except Exception:
            pass
        await asyncio.sleep(0.3)
    raise RuntimeError("Edge didn't expose a page DevTools target in 15 s")


if __name__ == "__main__":
    threading.Timer(60, lambda: (print("!! hard-timeout"), os._exit(4))).start()
    sys.exit(asyncio.run(main()))
