"""Regression check for the SSD tab (Simplified Scout Dev).

Drives headless Edge over the DevTools protocol so it can set the viewport width
(hence the phone layouts) and wait for the SSE stream to deliver state before
looking at the DOM.

Checks:
  * the SSD tab exists and renders,
  * one tile per player, with name / color / civ,
  * every ELO is labeled and unlogged modes are skipped (no bare numbers, no "-"),
  * the four KPIs are present,
  * the team header shows comms + the team average ELO (nulls excluded),
  * no civ meta, map briefing, expandable details or recommendations,
  * no horizontal overflow at 320 / 375 / 768 / 1280 px,
  * player names are colored to match their in-game color.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8001
USER_DATA = Path(os.environ.get("TEMP") or ".") / "aoe-warroom-edge-probe-ssd"

WIDTHS = [320, 375, 520, 768, 912, 1024, 1280, 1440, 1920]

DIAG = r"""(() => {
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null);
    const tiles = [...document.querySelectorAll('.ssd-tile')].map((t) => ({
        name: txt(t.querySelector('.ssd-name')),
        nameColor: t.querySelector('.ssd-name')?.style.color || '',
        sub: txt(t.querySelector('.ssd-sub')),
        elos: [...t.querySelectorAll('.ssd-elo-grid .ssd-elo')].map((e) => ({
            label: txt(e.querySelector('.ssd-elo-label')),
            value: txt(e.querySelector('.ssd-elo-value')),
            empty: e.classList.contains('empty'),
        })),
        eloGridCols: getComputedStyle(t.querySelector('.ssd-elo-grid')).gridTemplateColumns.split(' ').length,
        eloOverflow: (() => {
            const g = t.querySelector('.ssd-elo-grid');
            return g.scrollWidth > g.clientWidth + 1;
        })(),
        kpis: [...t.querySelectorAll('.ssd-kpis .tile')].map((k) => ({
            title: txt(k.querySelector('.tile-title')),
            label: txt(k.querySelector('.tile-label')),
            detail: txt(k.querySelector('.tile-detail')),
        })),
        army: txt(t.querySelector('.ssd-army')),
        armyItems: [...t.querySelectorAll('.ssd-army-item')].map((a) => txt(a)),
        armyHasBar: !!t.querySelector('.group-bar'),
        hasChevron: !!t.querySelector('.chevron'),
        hasTagTile: !!t.querySelector('.tag-tile'),
        hasCounter: !!t.querySelector('.tile-counter'),
        hasDetails: !!t.querySelector('.details'),
        hasDot: !!t.querySelector('.dot'),
        hasSwatch: !!t.querySelector('.ssd-swatch'),
        gridH: Math.round(t.querySelector('.ssd-elo-grid').getBoundingClientRect().height),
        kpiOffset: Math.round(
            t.querySelector('.ssd-kpis').getBoundingClientRect().top
            - t.querySelector('.ssd-elo-grid').getBoundingClientRect().top),
        armyH: Math.round(t.querySelector('.ssd-army').getBoundingClientRect().height),
    }));
    const heads = [...document.querySelectorAll('.ssd-team-head')].map((h) => ({
        title: txt(h.querySelector('h2')),
        h2Color: getComputedStyle(h.querySelector('h2')).color,
        comms: txt(h.querySelector('.ssd-comms')),
        commsNames: [...h.querySelectorAll('.ssd-comms .ssd-name')].map((n) => n.textContent.trim()),
        elos: [...h.querySelectorAll('.ssd-elos .ssd-elo')].map((e) => ({
            label: txt(e.querySelector('.ssd-elo-label')),
            text: txt(e),
            cls: e.className,
            arrow: txt(e.querySelector('.ssd-arrow')),
        })),
    }));
    const grids = [...document.querySelectorAll('.ssd-grid')].map((g) => ({
        cols: Number(g.style.getPropertyValue('--cols')),
        tiles: g.children.length,
        renderedCols: getComputedStyle(g).gridTemplateColumns.split(' ').length,
        rowHeights: (() => {
            const tops = new Set();
            for (const c of g.children) tops.add(Math.round(c.getBoundingClientRect().top));
            return [...tops].length;
        })(),
        rowTops: [...new Set([...g.children].map((c) => Math.round(c.getBoundingClientRect().top)))],
        tileTops: [...g.children].map((c) => Math.round(c.getBoundingClientRect().top)),
        tileHeights: [...g.children].map((c) => Math.round(c.getBoundingClientRect().height)),
    }));
    return JSON.stringify({
        rendered: !!document.querySelector('.ssd-teams'),
        waiting: !!document.querySelector('.empty'),
        tiles,
        heads,
        grids,
        toggle: txt(document.querySelector('.ssd-toggle')),
        toggleInTopbar: !!document.querySelector('.topbar .ssd-toggle'),
        strayToolbar: !!document.querySelector('.ssd-toolbar'),
        briefing: !!document.querySelector('.briefing'),
        plan: !!document.querySelector('.plan'),
        civChips: document.querySelectorAll('.briefing-civ').length,
        overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    });
})()"""


async def main() -> int:
    USER_DATA.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(
        [EDGE,
         "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={USER_DATA}", "--remote-debugging-port=9224", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:9224/json/list", timeout=1) as r:
                    targets = json.loads(r.read())
                for t in targets:
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        ws_url = t["webSocketDebuggerUrl"]
                        break
            except Exception:
                pass
            await asyncio.sleep(0.3)
        if not ws_url:
            print("could not attach to Edge")
            return 1

        async with await websockets.connect(ws_url, max_size=2 ** 20, ping_interval=None) as ws:
            pending: dict[int, asyncio.Future] = {}
            loop = asyncio.get_event_loop()
            exceptions: list[str] = []

            async def reader():
                try:
                    async for raw in ws:
                        m = json.loads(raw)
                        if "id" in m and m["id"] in pending:
                            pending.pop(m["id"]).set_result(m)
                            continue
                        if m.get("method") == "Runtime.exceptionThrown":
                            exceptions.append(json.dumps(m["params"].get("exceptionDetails", {}))[:600])
                except Exception:
                    pass  # Edge closed the socket when the probe tore down.

            asyncio.create_task(reader())
            mid = [1]

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
            await asyncio.sleep(6)  # let the SSE stream deliver the state

            failures: list[str] = []
            data = None
            for width in WIDTHS:
                await send("Emulation.setDeviceMetricsOverride",
                           {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 500})
                await asyncio.sleep(1.2)
                r = await send("Runtime.evaluate", {"expression": DIAG, "returnByValue": True})
                data = json.loads(r["result"]["result"]["value"])
                print(f"\n=== {width}px ===")
                print(f"rendered={data['rendered']} tiles={len(data['tiles'])} "
                      f"heads={len(data['heads'])} overflowX={data['overflowX']}")
                for g in data["grids"]:
                    print(f"  grid cols={g['cols']} rendered={g['renderedCols']} "
                          f"tiles={g['tiles']} rows={g['rowHeights']} heights={g['tileHeights']}")
                if width == 1280:
                    print(json.dumps(data, indent=1)[:1500])
                if not data["rendered"]:
                    failures.append(f"{width}px: SSD tab did not render")
                if data["overflowX"] > 1:
                    failures.append(f"{width}px: horizontal overflow ({data['overflowX']}px)")

            print("[probe] width loop done", flush=True)
            tiles = data["tiles"]
            heads = data["heads"]

            # -- one tile per player, with name / color / civ
            if not tiles:
                failures.append("no tiles rendered")
            for t in tiles:
                if not t["name"]:
                    failures.append("tile without a name")
                if not t["sub"] or " · " not in t["sub"]:
                    failures.append(f"tile {t['name']}: missing civ/color line ({t['sub']!r})")
                if not t["nameColor"]:
                    failures.append(f"tile {t['name']}: name is not colored")

            # -- ELOs: a 2-column grid, labeled, no bare numbers / placeholders.
            #    The grid always has all four slots; modes the player has not
            #    ranked are blank placeholders (so the KPIs and army row below
            #    stay in the same place on every tile).
            for t in tiles:
                if not t["elos"]:
                    continue
                if t["eloGridCols"] != 2:
                    failures.append(f"tile {t['name']}: ELO grid has {t['eloGridCols']} columns, want 2")
                if t["eloOverflow"]:
                    failures.append(f"tile {t['name']}: ELO grid overflows horizontally")
                if len(t["elos"]) != 4:
                    failures.append(f"tile {t['name']}: {len(t['elos'])} ELO slots, want 4")
                for e in t["elos"]:
                    label = e["label"] or ""
                    value = e["value"] or ""
                    if e["empty"]:
                        # a blank slot must be truly blank
                        if label or value:
                            failures.append(f"tile {t['name']}: empty ELO slot shows {e}")
                        continue
                    if not label:
                        failures.append(f"tile {t['name']}: unlabeled ELO {e}")
                    if not value.isdigit():
                        failures.append(f"tile {t['name']}: placeholder ELO {e}")
                    # only the four modes the owner kept
                    if label not in ("RM 1v1", "RM Team", "QP Team", "Unranked"):
                        failures.append(f"tile {t['name']}: unexpected ELO mode {label!r}")

            # -- the four KPIs
            for t in tiles:
                titles = [k["title"] for k in t["kpis"]]
                if len(t["kpis"]) != 3:
                    failures.append(f"tile {t['name']}: expected 3 KPI tiles, got {titles}")
                if t["army"] is None:
                    failures.append(f"tile {t['name']}: no army section at all")
                elif t["army"] == "…":
                    # No replays for this player: the KPI/army values are legitimately
                    # unknown. The tile must show a placeholder, not a stale number.
                    if any(k["label"] not in ("…", "–") for k in t["kpis"]):
                        failures.append(f"tile {t['name']}: KPIs show values but army is unknown")
                else:
                    # KPI titles must name the metric, not a verdict ("Rush"/"Boom").
                    for k in t["kpis"]:
                        if k["title"] in ("Rush", "Boom"):
                            failures.append(f"tile {t['name']}: KPI title {k['title']!r} is a "
                                            "verdict, not a metric name")
                        if not k["detail"]:
                            failures.append(f"tile {t['name']}: KPI {k['title']} has no unit")

            # -- army composition: spelled out, descending, no colors
            for t in tiles:
                if t["armyHasBar"]:
                    failures.append(f"tile {t['name']}: army still uses the colored bar")
                items = t["armyItems"]
                shares = []
                for it in items:
                    m = re.search(r"(\d+(?:\.\d+)?)\s*%", it)
                    if not m:
                        failures.append(f"tile {t['name']}: army item {it!r} has no percentage")
                    else:
                        shares.append(float(m.group(1)))
                if not items:
                    # No replays for this player: the army section must still say
                    # something, not sit empty.
                    if "…" not in (t["army"] or ""):
                        failures.append(f"tile {t['name']}: army section is empty")
                elif len(shares) == 1 and shares[0] == 100:
                    pass  # a one-type army (Cavalry 100%) is legitimate
                elif len(items) < 2:
                    failures.append(f"tile {t['name']}: army lists only {items}")
                if shares != sorted(shares, reverse=True):
                    failures.append(f"tile {t['name']}: army shares not descending: {shares}")

            # -- every tile must put its assets in the same place, no matter how
            #    many ELOs the player has or how their army is composed
            if tiles:
                grid_heights = {t["gridH"] for t in tiles}
                kpi_offsets = {t["kpiOffset"] for t in tiles}
                army_heights = {t["armyH"] for t in tiles}
                if len(grid_heights) > 1:
                    failures.append(f"tiles have different ELO grid heights {grid_heights}")
                if len(kpi_offsets) > 1:
                    failures.append(f"tiles put their KPI row at different offsets {kpi_offsets}")
                if len(army_heights) > 1:
                    failures.append(f"tiles have different army section heights {army_heights}")

            # -- balanced rows: every row is full, or at least half full
            for g in data["grids"]:
                cols = g["cols"]
                if cols < 1:
                    failures.append(f"grid: bad column count {cols}")
                    continue
                if g["renderedCols"] != cols:
                    failures.append(f"grid: --cols={cols} but rendered {g['renderedCols']} columns")
                rem = g["tiles"] % cols
                if rem and rem * 2 < cols:
                    failures.append(f"grid: {g['tiles']} tiles in {cols} columns leaves a "
                                    "stranded row of fewer than half")
                if g["tiles"] and len(set(g["tileHeights"])) > 1:
                    # Only tiles that share a row have to match in height; with one
                    # column each tile is its own row and may differ.
                    for top in set(g["tileTops"]):
                        same_row = [h for t, h in zip(g["tileTops"], g["tileHeights"]) if t == top]
                        if len(set(same_row)) > 1:
                            failures.append(f"grid: tiles in one row have different heights {same_row}")
            # -- nothing that the request excluded
            for t in tiles:
                if t["hasChevron"]:
                    failures.append(f"tile {t['name']}: has an expand chevron")
                if t["hasTagTile"]:
                    failures.append(f"tile {t['name']}: has danger/exploit tag tiles")
                if t["hasCounter"]:
                    failures.append(f"tile {t['name']}: has counter/recommendation advice")
                if t["hasDetails"]:
                    failures.append(f"tile {t['name']}: has the expanded details block")
                if t["hasDot"]:
                    failures.append(f"tile {t['name']}: still uses the colored dot")
                if not t["hasSwatch"]:
                    failures.append(f"tile {t['name']}: no color swatch")
            if data["briefing"]:
                failures.append("map briefing panel is present")
            if data["plan"]:
                failures.append("Attack first / Biggest threat plan panel is present")
            if data["civChips"]:
                failures.append("civ-specific chips are present")

            # -- team header: comms + team average ELO
            if not heads:
                failures.append("no team header rendered")
            for h in heads:
                comms = h["comms"] or ""
                if not comms.startswith("Comms:"):
                    failures.append(f"team {h['title']}: no comms segment ({comms!r})")
                if not h["elos"]:
                    failures.append(f"team {h['title']}: no team average ELO")
                # a comms pair must not be listed twice (symmetric data)
                if len(h["commsNames"]) != len(set(h["commsNames"])):
                    failures.append(f"team {h['title']}: comms names repeated: {h['commsNames']}")
                # every team ELO carries a comparison arrow
                for e in h["elos"]:
                    if e["arrow"] not in ("▲", "▼", "●"):
                        failures.append(f"team {h['title']}: ELO {e['text']!r} has no arrow")
                # team headings must be neutral, not a player colour
                if h["h2Color"] not in ("rgb(155, 144, 129)", "rgb(236, 228, 214)",
                                        "rgb(217, 164, 65)", "rgb(255, 255, 255)"):
                    failures.append(f"team {h['title']}: heading colour {h['h2Color']} is not neutral")

            # -- the two teams' arrows must be mirrored (we are up where they are down)
            if len(heads) == 2:
                mine = next((h for h in heads if "enemy" not in h["title"].lower()), None)
                theirs = next((h for h in heads if "enemy" in h["title"].lower()), None)
                if mine and theirs:
                    m = {e["label"]: e["arrow"] for e in mine["elos"]}
                    t = {e["label"]: e["arrow"] for e in theirs["elos"]}
                    for label in set(m) & set(t):
                        if m[label] == "●" or t[label] == "●":
                            if m[label] != t[label]:
                                failures.append(f"ELO {label}: even mismatch {m[label]}/{t[label]}")
                            continue
                        if m[label] == t[label]:
                            failures.append(f"ELO {label}: arrows not mirrored "
                                            f"(ours {m[label]}, theirs {t[label]})")

            # -- the hide/show toggle
            if not data["toggle"] or "team" not in data["toggle"].lower():
                failures.append(f"toggle button missing or mislabelled ({data['toggle']!r})")
            if not data["toggleInTopbar"]:
                failures.append("the hide/show toggle is not in the top bar")
            if data["strayToolbar"]:
                failures.append("the old .ssd-toolbar band is still rendered")

            print("\n--- result ---")
            print(f"tiles={len(tiles)} heads={len(heads)}")
            if exceptions:
                failures.append(f"{len(exceptions)} runtime exception(s)")
                for e in exceptions[:3]:
                    print("exception:", e)
            if failures:
                for f in failures:
                    print("FAIL:", f)
                return 1
            print("PASS: SSD tab checks all green")
            return 0
    finally:
        p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:
            p.kill()


if __name__ == "__main__":
    # Hard stop in case the DevTools socket wedges. `os._exit` skips cleanup, so it
    # must not fire after main() has already returned.
    timer = threading.Timer(300, lambda: os._exit(4))
    timer.daemon = True
    timer.start()
    rc = asyncio.run(main())
    timer.cancel()
    sys.exit(rc)
