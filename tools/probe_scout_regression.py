"""Regression check for the Scout tab after Player Search work:
open #/, ensure Scout loads cleanly with all four tabs present, no runtime errors.
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
USER_DATA = Path(os.environ.get("TEMP") or ".") / "aoe-warroom-edge-probe-scout"


async def main() -> int:
    USER_DATA.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(
        [EDGE,
         "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={USER_DATA}", "--remote-debugging-port=9223", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:9223/json/list", timeout=1) as r:
                    targets = json.loads(r.read())
                for t in targets:
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        ws_url = t["webSocketDebuggerUrl"]; break
            except Exception:
                pass
            await asyncio.sleep(0.3)

        async with await websockets.connect(ws_url, max_size=2 ** 20, ping_interval=None) as ws:
            pending: dict[int, asyncio.Future] = {}
            loop = asyncio.get_event_loop()
            console: list[str] = []
            exceptions: list[str] = []

            async def reader():
                async for raw in ws:
                    m = json.loads(raw)
                    if "id" in m and m["id"] in pending:
                        pending.pop(m["id"]).set_result(m); continue
                    if m.get("method") == "Runtime.exceptionThrown":
                        exceptions.append(json.dumps(m["params"].get("exceptionDetails", {}))[:1000])
                    elif m.get("method") == "Runtime.consoleAPICalled":
                        console.append(f"[{m['params']['type']}] "
                                       + " ".join(a.get("value", "") for a in m["params"].get("args", [])))

            asyncio.create_task(reader())
            mid = [1]
            async def send(method, params=None):
                m_id = mid[0]; mid[0] += 1
                await ws.send(json.dumps({"id": m_id, "method": method, "params": params or {}}))
                fut = loop.create_future(); pending[m_id] = fut
                r = await fut
                if "error" in r:
                    raise RuntimeError(repr(r["error"]))
                return r

            await send("Runtime.enable"); await send("Page.enable"); await send("Log.enable")
            await send("Page.navigate", {"url": f"http://localhost:{PORT}/"})
            await asyncio.sleep(4)

            diag = await send("Runtime.evaluate", {
                "expression": """(() => {
                    const has = (s) => !!document.querySelector(s);
                    const tabs = Array.from(document.querySelectorAll('.tabs a')).map(a => ({
                        href: a.getAttribute('href'), text: a.textContent, active: a.classList.contains('active'),
                    }));
                    return JSON.stringify({
                        tabs,
                        scoutRendered: has('.teams') || has('.plan') || has('.empty'),
                        playersRendered: has('.players-search'),
                        meBtn: !!document.querySelector('.me-btn'),
                    });
                })()""",
                "returnByValue": True})
            print("diag:", diag["result"]["result"]["value"])
            print("exceptions:", len(exceptions))
            for c in console:
                if "Error" in c or "[error]" in c.lower():
                    print("console:", c)

            out = json.loads(diag["result"]["result"]["value"])
            tabs = {t["href"]: t["text"] for t in out["tabs"]}
            must = {"#/": "Scout", "#/players": "Players", "#/explore": "Explore", "#/counter": "Counter"}
            ok = all(tabs.get(h) == n for h, n in must.items())
            ok = ok and out["scoutRendered"]
            ok = ok and out["meBtn"]
            ok = ok and not exceptions
            return 0 if ok else 1
    finally:
        p.terminate()
        try: p.wait(timeout=3)
        except Exception: p.kill()


if __name__ == "__main__":
    threading.Timer(45, lambda: os._exit(4)).start()
    sys.exit(asyncio.run(main()))
