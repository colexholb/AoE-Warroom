"""Summarize a player's analyzed replays into tendencies you can plan around."""

from __future__ import annotations

from collections import Counter
from statistics import median

from .replay import BOOM_CHECK_SECONDS

# What beats each opening, phrased as a quick call-out.
COUNTERS = {
    "Scouts": "spears and walls shut it down",
    "Archers": "skirms, or rams/knights punish it",
    "Men-at-Arms": "archers behind walls beat it",
    "Skirms": "they're playing defensively; boom or go up fast",
    "Spears": "they're playing defensively; boom or go up fast",
    "FC": "punish with early Feudal pressure",
    "Tower rush": "keep villagers ready to counter-tower",
    "Eco Feudal": "no early army, so they're open to Feudal pressure",
}


def _clock(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    s = round(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _counter_for(opening: str) -> str | None:
    last = opening.split(" → ")[-1]
    return COUNTERS.get(last)


def summarize(games: list[dict], current_civ: str | None, enemy: bool = True) -> dict:
    """`games` items: {"strategy": per-player dict from replay.py, "won": bool | None,
    "game_seconds": int, "map_name": str}. Most recent first. Counter advice only for enemies."""
    n = len(games)
    if n == 0:
        return {"games": 0, "insights": []}
    strategies = [g["strategy"] for g in games]

    openings = Counter(s["opening"] for s in strategies if s["opening"] != "Unknown")
    top_openings = [{"label": label, "count": c, "share": round(c / n, 3)}
                    for label, c in openings.most_common(4)]
    civ_openings = Counter(s["opening"] for s in strategies
                           if current_civ and s["civ_slug"] == current_civ and s["opening"] != "Unknown")

    def med(field: str) -> float | None:
        values = [s[field] for s in strategies if s[field] is not None]
        return median(values) if len(values) >= 2 else None

    long_games = [s for g, s in zip(games, strategies) if g["game_seconds"] >= BOOM_CHECK_SECONDS]
    avg_tcs = round(sum(s["tcs_by_25"] for s in long_games) / len(long_games), 1) if long_games else None
    boom3 = sum(1 for s in long_games if s["tcs_by_25"] >= 3)
    boom4 = sum(1 for s in long_games if s["tcs_by_25"] >= 4)

    positions = Counter(s["position"] for s in strategies if s["position"])
    position_record = {}
    for pos in ("pocket", "flank"):
        decided = [g["won"] for g, s in zip(games, strategies) if s["position"] == pos and g["won"] is not None]
        position_record[pos] = {"games": positions[pos], "wins": sum(decided), "decided": len(decided)}

    armies = Counter(s["main_army"][0] for s in strategies if s.get("main_army"))

    summary = {
        "games": n,
        "openings": top_openings,
        "drush": sum(s["drush"] for s in strategies),
        "fast_castle": sum(s["fast_castle"] for s in strategies),
        "feudal": _clock(med("feudal")),
        "castle": _clock(med("castle")),
        "imperial": _clock(med("imperial")),
        "avg_tcs_by_25": avg_tcs,
        "long_games": len(long_games),
        "boom3": boom3,
        "boom4": boom4,
        "positions": position_record,
        "armies": [{"unit": u, "count": c} for u, c in armies.most_common(3)],
        "civ_openings": [{"label": label, "count": c} for label, c in civ_openings.most_common(2)],
    }
    summary["insights"] = _insights(summary, med("feudal"), med("castle"), enemy)
    return summary


def _insights(s: dict, feudal: float | None, castle: float | None, enemy: bool) -> list[dict]:
    out: list[dict] = []
    n = s["games"]

    def add(kind: str, text: str) -> None:
        out.append({"kind": kind, "text": text})

    if s["civ_openings"] and s["civ_openings"][0]["count"] >= 2:
        top = s["civ_openings"][0]
        counter = _counter_for(top["label"]) if enemy else None
        add("tendency", f"On this civ they open {top['label']} ({top['count']} games)"
                        + (f": {counter}" if counter else ""))
    elif s["openings"] and n >= 3 and s["openings"][0]["share"] >= 0.5:
        top = s["openings"][0]
        counter = _counter_for(top["label"]) if enemy else None
        add("tendency", f"Opens {top['label']} in {top['count']}/{n} games"
                        + (f": {counter}" if counter else ""))

    if n >= 3 and s["drush"] / n >= 0.4:
        add("tendency", f"Drushes in {s['drush']}/{n} games"
                        + (": loom up and keep villagers tight" if enemy else ""))

    if s["long_games"] >= 3:
        if s["boom4"] / s["long_games"] >= 0.4:
            add("weakness", f"Big boomer: 4+ TCs by 25 min in {s['boom4']}/{s['long_games']} games"
                            + (". Hit them early" if enemy else ""))
        elif s["boom3"] / s["long_games"] >= 0.5:
            add("tendency", f"Booms to 3+ TCs in {s['boom3']}/{s['long_games']} games")

    if feudal is not None and n >= 3:
        if feudal >= 13 * 60:
            add("weakness", f"Slow to Feudal (usually ~{s['feudal']})")
        elif feudal <= 9 * 60 + 30:
            add("strength", f"Fast Feudal (usually ~{s['feudal']})")
    if castle is not None and n >= 3:
        if castle <= 15 * 60:
            add("strength", f"Fast Castle Age (usually ~{s['castle']})")
        elif castle >= 21 * 60:
            add("weakness", f"Slow to Castle Age (usually ~{s['castle']})")

    pocket, flank = s["positions"]["pocket"], s["positions"]["flank"]
    placed = pocket["games"] + flank["games"]
    if placed >= 4:
        main = "pocket" if pocket["games"] >= flank["games"] else "flank"
        share = s["positions"][main]["games"] / placed
        if share >= 0.7:
            add("tendency", f"Usually plays {main} ({s['positions'][main]['games']}/{placed} games)")
        for pos, rec in (("pocket", pocket), ("flank", flank)):
            if rec["decided"] >= 3:
                rate = rec["wins"] / rec["decided"]
                losses = rec["decided"] - rec["wins"]
                if rate <= 0.3:
                    add("weakness", f"Weak on {pos}: {rec['wins']}-{losses}")
                elif rate >= 0.7:
                    add("strength", f"Strong on {pos}: {rec['wins']}-{losses}")

    if s["armies"] and n >= 3 and s["armies"][0]["count"] >= max(2, n * 0.4):
        add("tendency", f"Castle Age army is usually {s['armies'][0]['unit']}")
    return out
