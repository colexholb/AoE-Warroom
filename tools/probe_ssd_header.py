"""Check the SSD team header: comms and ELOs share one line when they fit,
and split onto two lines when they do not."""

import asyncio
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
USER_DATA = Path(os.environ.get("TEMP") or ".") / "aoe-warroom-edge-probe-ssd2"
WIDTHS = [320, 375, 520, 768, 912, 1280, 1920]

DIAG = r"""(() => {
    const heads = [...document.querySelectorAll('.ssd-team-head')].map(h => {
      const row = h.querySelector('.ssd-team-info');
      const c = h.querySelector('.ssd-comms');
      const e = h.querySelector('.ssd-elos');
      const rect = (el) => el ? el.getBoundingClientRect() : null;
      const cr = rect(c), er = rect(e);
      return {
        title: h.querySelector('h2').textContent,
        split: h.classList.contains('split'),
        commsTop: cr ? Math.round(cr.top) : null,
        elosTop: er ? Math.round(er.top) : null,
        commsBottom: cr ? Math.round(cr.bottom) : null,
        elosBottom: er ? Math.round(er.bottom) : null,
        elosHeight: er ? Math.round(er.height) : null,
        rowW: row ? Math.round(row.clientWidth) : null,
        commsW: c ? Math.round(c.scrollWidth) : null,
        elosW: e ? Math.round(e.scrollWidth) : null,
        overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });
    // ELO grid geometry per tile
    const tiles = [...document.querySelectorAll('.ssd-tile')].map(t => {
      const g = t.querySelector('.ssd-elo-grid');
      const k = t.querySelector('.ssd-kpis');
      const gr = g.getBoundingClientRect(), kr = k.getBoundingClientRect();
      return {
        name: t.querySelector('.ssd-name').textContent,
        filled: [...g.children].filter(c => !c.classList.contains('empty')).length,
        slots: g.children.length,
        gridH: Math.round(gr.height),
        kpiOffset: Math.round(kr.top - gr.top),
      };
    });
    return JSON.stringify({heads, tiles, overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth});
})()"""


async def main() -> int:
    USER_DATA.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={USER_DATA}", "--remote-debugging-port=9226", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:9226/json/list", timeout=1) as r:
                    for t in json.loads(r.read()):
                        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                            ws_url = t["webSocketDebuggerUrl"]
                            break
            except Exception:
                pass
            await asyncio.sleep(0.3)
        if not ws_url:
            print("could not attach to Edge")
            return 1

        async with await websockets.connect(ws_url, max_size=2 ** 22, ping_interval=None) as ws:
            pending: dict[int, asyncio.Future] = {}
            loop = asyncio.get_event_loop()
            mid = [1]

            async def reader():
                try:
                    async for raw in ws:
                        m = json.loads(raw)
                        if "id" in m and m["id"] in pending:
                            pending.pop(m["id"]).set_result(m)
                except Exception:
                    pass

            asyncio.create_task(reader())

            async def send(method, params=None):
                m_id = mid[0]
                mid[0] += 1
                await ws.send(json.dumps({"id": m_id, "method": method, "params": params or {}}))
                fut = loop.create_future()
                pending[m_id] = fut
                r = await fut
                if "error" in r:
                    raise RuntimeError(repr(r["error"]))
                return r

            await send("Runtime.enable")
            await send("Page.enable")
            await send("Emulation.setDeviceMetricsOverride",
                       {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})
            await send("Page.navigate", {"url": f"http://localhost:{PORT}/#/ssd"})
            await asyncio.sleep(7)

            failures = []
            for width in WIDTHS:
                await send("Emulation.setDeviceMetricsOverride",
                           {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 500})
                await asyncio.sleep(1.5)
                r = await send("Runtime.evaluate", {"expression": DIAG, "returnByValue": True})
                d = json.loads(r["result"]["result"]["value"])
                print(f"\n=== {width}px === overflowX={d['overflowX']}")
                for h in d["heads"]:
                    same_line = h["commsTop"] is not None and h["elosTop"] is not None \
                        and abs(h["commsTop"] - h["elosTop"]) < 6
                    print(f"  team {h['title']!r}: split={h['split']} "
                          f"commsW={h['commsW']} elosW={h['elosW']} rowW={h['rowW']} "
                          f"sameLine={same_line} elosH={h['elosHeight']}")
                    # the ELO row must not overflow the header
                    if h["elosW"] and h["rowW"] and h["elosW"] > h["rowW"] + 2:
                        failures.append(f"{width}px team {h['title']}: ELO row overflows "
                                        f"({h['elosW']}px in {h['rowW']}px)")
                    # when split, comms and ELOs must be on different lines
                    if h["split"] and same_line:
                        failures.append(f"{width}px team {h['title']}: split but still on one line")
                    # when not split, they must fit on one line
                    if not h["split"] and not same_line:
                        failures.append(f"{width}px team {h['title']}: not split but on two lines")
                # every tile: same ELO grid height and same KPI offset
                if d["tiles"]:
                    heights = {t["gridH"] for t in d["tiles"]}
                    offsets = {t["kpiOffset"] for t in d["tiles"]}
                    print(f"  tiles: gridH={heights} kpiOffset={offsets} "
                          f"filled={[t['filled'] for t in d['tiles']]}")
                    if len(heights) > 1:
                        failures.append(f"{width}px: ELO grids have different heights {heights}")
                    if len(offsets) > 1:
                        failures.append(f"{width}px: KPI rows sit at different offsets {offsets}")
                    for t in d["tiles"]:
                        if t["slots"] != 4:
                            failures.append(f"{width}px tile {t['name']}: {t['slots']} ELO slots, want 4")
                if d["overflowX"] > 1:
                    failures.append(f"{width}px: horizontal overflow {d['overflowX']}px")

            print("\n--- result ---")
            if failures:
                for f in failures:
                    print("FAIL:", f)
                return 1
            print("PASS: header split + fixed tile geometry")
            return 0
    finally:
        p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:
            p.kill()


if __name__ == "__main__":
    timer = threading.Timer(240, lambda: os._exit(4))
    timer.daemon = True
    timer.start()
    rc = asyncio.run(main())
    timer.cancel()
    sys.exit(rc)
