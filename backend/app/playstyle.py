"""Summarize a player's analyzed replays into tendencies you can plan around."""

from __future__ import annotations

from collections import Counter
from statistics import median

from .counters import combined_counters, counters_for
from .record_header import object_name
from .replay import BOOM_CHECK_SECONDS, castle_plan, is_unique_unit, plural, unit_group

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
        "civ_openings": [{"label": label, "count": c} for label, c in civ_openings.most_common(2)],
        "army_by_age": _army_by_age(strategies),
    }
    summary["insights"] = _insights(summary, med("feudal"), med("castle"), enemy)
    summary["avg_feudal_army"] = _avg_feudal_army(strategies)
    summary["tempo"] = _tempo(strategies, avg_tcs)
    summary["castle_plan"] = _castle_tendency(strategies)
    summary["army"] = _army_verdict(strategies, current_civ, summary["army_by_age"])
    return summary


# ---- the four "how should we play against them" verdicts -------------------------------------

RUSH_OPENINGS = ("Drush", "Scouts", "Archers", "Men-at-Arms", "Tower rush", "Knights", "Camels", "Cav Archers")
GROUP_LABEL = {"ranged": "Ranged", "cavalry": "Cavalry", "infantry": "Infantry", "siege": "Siege",
               "monk": "Monks", "navy": "Navy", "other": "Other"}
AGES = ("feudal", "castle", "imperial")


def _avg_feudal_army(strategies: list[dict]) -> float | None:
    """Rush potential: military units made in Feudal Age, averaged over games that reached it."""
    reached = [s for s in strategies if s["feudal"] is not None]
    return round(sum(s.get("feudal_army", 0) for s in reached) / len(reached), 1) if reached else None


def _tempo(strategies: list[dict], avg_tcs: float | None) -> dict:
    """Boom or rush: will they pressure in Feudal Age?"""
    feudal_army = _avg_feudal_army(strategies) or 0
    rushes = sum(1 for s in strategies if any(o in s["opening"] for o in RUSH_OPENINGS))
    n = len(strategies)
    detail = f"{avg_tcs if avg_tcs is not None else '?'} TCs by 25 min · {feudal_army:g} Feudal units/game"
    if rushes / n >= 0.5 or feudal_army >= 10:
        return {"label": "Rusher", "level": "danger", "detail": detail,
                "advice": f"Expect Feudal pressure (rushed in {rushes}/{n} games)"}
    if feudal_army < 4:
        return {"label": "Boomer", "level": "safe", "detail": detail,
                "advice": "Little Feudal pressure: they invest in eco" if (avg_tcs or 0) >= 3
                          else "Little Feudal pressure: they go straight for Castle Age"}
    return {"label": "Mixed", "level": "warn", "detail": detail,
            "advice": "Some Feudal army; don't over-boom against them"}


def _castle_tendency(strategies: list[dict]) -> dict:
    """What they do once they hit Castle Age: boom, army, or a castle/UU push."""
    plan_of = [castle_plan(s) for s in strategies]
    played = [p for p in plan_of if p != "No Castle by 25"]
    plans = Counter(played)
    castles = [s.get("castles_by_25", 0) for s in strategies]
    avg_castles = round(sum(castles) / len(castles), 1) if castles else 0
    aggressive = plans["Forward castle"] + plans["UU rush"]
    late = len(strategies) - len(played)
    breakdown = [{"label": label, "count": c} for label, c in plans.most_common()]
    if late:
        breakdown.append({"label": "No Castle by 25", "count": late})
    base = {"avg_castles_by_25": avg_castles, "breakdown": breakdown, "games": len(strategies)}
    if not played:
        return {**base, "label": "Late Castle", "level": "safe",
                "detail": f"No Castle Age by 25 min in {late}/{len(strategies)} games",
                "advice": "Won't forward castle or UU rush early"}
    top, top_n = plans.most_common(1)[0]
    detail = f"{top} in {top_n}/{len(played)} · {avg_castles:g} castles by 25 min"
    if aggressive >= 2 and aggressive / len(played) >= 0.3:
        kinds = " / ".join(k for k in ("Forward castle", "UU rush") if plans[k])
        otherwise = next((k for k, _ in plans.most_common() if k not in ("Forward castle", "UU rush")), None)
        return {**base, "label": "Castle push", "level": "danger",
                "detail": f"{kinds} in {aggressive}/{len(played)} · {avg_castles:g} castles by 25 min",
                "advice": "Scout for a castle drop or unique-unit push"
                          + (f" (otherwise: {otherwise.lower()})" if otherwise else "")}
    if top in ("Army", "Boom + army"):
        return {**base, "label": "FC → army", "level": "warn", "detail": detail,
                "advice": "Expect a Castle Age army soon after they click up"}
    return {**base, "label": "FC → boom" if top == "Boom" else top, "level": "safe", "detail": detail,
            "advice": "Unlikely to forward castle or UU rush" if avg_castles < 1
                      else "Builds castles, but at home"}


def _army_by_age(strategies: list[dict]) -> dict:
    """Share of each unit group, per age, summed over all their games."""
    out = {}
    for age in AGES:
        totals: Counter[str] = Counter()
        games_in_age = 0
        for s in strategies:
            groups = (s.get("army_by_age") or {}).get(age)
            if groups:
                games_in_age += 1
                totals.update(groups)
        total = sum(totals.values())
        if total:
            out[age] = {
                "units_per_game": round(total / games_in_age),
                "groups": [{"group": g, "label": GROUP_LABEL.get(g, g), "share": round(n / total, 3)}
                           for g, n in totals.most_common() if n / total >= 0.05],
            }
    return out


def _unit_mix(strategies: list[dict], current_civ: str | None) -> tuple[str | None, list[dict]]:
    """Which units they build in Castle Age (or Feudal if they rarely reach Castle by minute 35).

    Unique units only count from games on the civ they're playing now: Mangudai from a Mongols
    game say nothing about what they'll make as Franks."""
    for age in ("castle", "feudal"):
        totals: Counter[int] = Counter()
        games = 0
        for s in strategies:
            start, end = (s.get("castle"), s.get("imperial")) if age == "castle" else (s.get("feudal"), s.get("castle"))
            if start is None:
                continue
            same_civ = current_civ is not None and s["civ_slug"] == current_civ
            counted = False
            for t, unit, n in s.get("army_events") or []:
                if t < start - 60 or (end is not None and t >= end):
                    continue
                if is_unique_unit(unit) and not same_civ:
                    continue
                totals[unit] += n
                counted = True
            games += counted
        total = sum(totals.values())
        if total >= 5:
            mix = []
            for unit, n in totals.most_common():
                share = n / total
                if share < 0.08 or len(mix) == 5:
                    break
                name = object_name(unit) or f"Unit {unit}"
                group = unit_group(unit)
                mix.append({"unit": plural(name), "group": group, "share": round(share, 3),
                            "per_game": round(n / games, 1), "counters": counters_for(name, group),
                            "unique": is_unique_unit(unit), "_name": name})
            return age, mix
    return None, []


def _army_verdict(strategies: list[dict], current_civ: str | None, by_age: dict) -> dict:
    """What they build, and what to build against it."""
    age, mix = _unit_mix(strategies, current_civ)
    if not mix:
        return {"label": "Unknown", "detail": "No army data yet", "counter": None, "units": [],
                "groups": [], "by_age": by_age}
    groups: Counter[str] = Counter()
    for u in mix:
        groups[u["group"]] += u["share"]
    covered = sum(groups.values())
    group_shares = [{"group": g, "label": GROUP_LABEL.get(g, g), "share": round(v / covered, 3)}
                    for g, v in groups.most_common()]
    top = group_shares[0]
    counter = combined_counters([(u["_name"], u["group"], u["share"]) for u in mix[:3]])
    for u in mix:
        del u["_name"]
    return {
        "label": f"{top['label']} {round(top['share'] * 100)}%",
        "detail": f"{age.title()} Age: " + ", ".join(f"{u['unit']} {round(u['share'] * 100)}%" for u in mix[:2]),
        "counter": " + ".join(counter) if counter else None,
        "units": mix,
        "groups": group_shares,
        "by_age": by_age,
    }


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

    return out
