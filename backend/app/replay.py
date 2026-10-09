"""Extract each player's opening, age-up times, boom size and map position from a recording.

Only ever run on finished, past games. Reading the action stream of the game you're
currently playing would reveal what opponents are doing right now, which is cheating.
"""

from __future__ import annotations

import io
import math
import struct
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from statistics import median

from mgz.fast import Action, Operation, meta, operation

from .record_header import RecordInfo, object_name, parse_record_bytes

# Only the opening matters, so stop reading after this much game time.
CUTOFF_SECONDS = 35 * 60
BOOM_CHECK_SECONDS = 25 * 60

FEUDAL, CASTLE, IMPERIAL = 101, 102, 103
# Base research times (seconds). Close enough for every civ to place the age-up.
AGE_RESEARCH_SECONDS = {FEUDAL: 130, CASTLE: 160, IMPERIAL: 190}

TOWN_CENTERS = {109, 71, 141, 142, 621}
TOWERS = {79}
# Buildings placed near your own base early on (walls, towers and forward buildings are skipped).
HOME_BUILDINGS = {70, 562, 584, 68, 50}

# Unit ids -> opening category.
UNIT_CATEGORY = {
    74: "maa", 75: "maa", 77: "maa",          # militia line
    93: "spears",
    4: "archers", 24: "archers",
    7: "skirms",
    448: "scouts", 546: "scouts", 751: "scouts", 1370: "scouts",  # incl. eagles, steppe lancers
    38: "knights", 329: "camels", 39: "cav_archers",
    125: "monks", 280: "siege", 1258: "siege",
}
CATEGORY_LABEL = {
    "maa": "Men-at-Arms", "spears": "Spears", "archers": "Archers", "skirms": "Skirms",
    "scouts": "Scouts", "knights": "Knights", "camels": "Camels", "cav_archers": "Cav Archers",
    "monks": "Monks", "siege": "Siege",
}
# Name fragments for units missing from UNIT_CATEGORY (unique units, regional variants).
NAME_CATEGORY = [("Militia", "maa"), ("Man-at-Arms", "maa"), ("Spear", "spears"), ("Pike", "spears"),
                 ("Skirm", "skirms"), ("Scout", "scouts"), ("Archer", "archers"), ("Knight", "knights")]
NOT_ARMY = ("Villager", "Fishing", "Trade", "Transport", "Cart", "King", "Cog")


def unit_category(unit_id: int) -> str | None:
    if unit_id in UNIT_CATEGORY:
        return UNIT_CATEGORY[unit_id]
    name = object_name(unit_id) or ""
    return next((cat for fragment, cat in NAME_CATEGORY if fragment in name), None)


def is_army(unit_id: int) -> bool:
    name = object_name(unit_id)
    return bool(name) and not any(word in name for word in NOT_ARMY)


def plural(name: str) -> str:
    if name.endswith(("s", "x", "ia", "ry")):
        return name
    if name.endswith("man"):
        return name[:-3] + "men"
    return name + "s"


@dataclass
class PlayerTimeline:
    number: int
    age_clicks: dict[int, int] = field(default_factory=dict)  # tech id -> first click (s)
    tc_positions: list[tuple[float, float, int]] = field(default_factory=list)
    towers_before: list[int] = field(default_factory=list)
    units: list[tuple[int, str, int]] = field(default_factory=list)  # (time, category, amount)
    army: list[tuple[int, int, int]] = field(default_factory=list)  # (time, unit id, amount)
    home_builds: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class PlayerStrategy:
    number: int
    profile_id: int | None
    name: str
    civ: str
    civ_slug: str
    team: int | None
    feudal: int | None  # in-game seconds the age was reached (click + research time)
    castle: int | None
    imperial: int | None
    opening: str
    drush: bool
    fast_castle: bool
    tower_rush: bool
    tcs_by_25: int
    first_military: str | None
    main_army: list[str]
    first_military_time: int | None
    position: str | None  # "pocket" / "flank" / None
    base: tuple[float, float] | None


def _read_timelines(body: io.BytesIO, numbers: set[int]) -> tuple[dict[int, PlayerTimeline], int]:
    timelines = {n: PlayerTimeline(n) for n in numbers}
    now_ms = 0
    meta(body)
    while now_ms < CUTOFF_SECONDS * 1000:
        try:
            op, payload = operation(body)
        except (EOFError, struct.error, ValueError):
            break
        if op is Operation.SYNC:
            now_ms += payload[0]
            continue
        if op is Operation.POSTGAME:
            break
        if op is not Operation.ACTION:
            continue
        action, p = payload
        tl = timelines.get(p.get("player_id"))
        if tl is None:
            continue
        now = now_ms // 1000
        if action is Action.RESEARCH:
            tech = p.get("technology_id")
            if tech in AGE_RESEARCH_SECONDS and tech not in tl.age_clicks:
                tl.age_clicks[tech] = now
        elif action is Action.BUILD:
            building, x, y = p.get("building_id"), p.get("x"), p.get("y")
            if building in TOWN_CENTERS:
                tl.tc_positions.append((x, y, now))
            if building in TOWERS:
                tl.towers_before.append(now)
            if building in HOME_BUILDINGS and now < 6 * 60 and len(tl.home_builds) < 12:
                tl.home_builds.append((x, y))
        elif action is Action.DE_QUEUE:
            unit_id, amount = p.get("unit_id"), p.get("amount") or 0
            if amount <= 0 or not is_army(unit_id):
                continue
            tl.army.append((now, unit_id, amount))
            category = unit_category(unit_id)
            if category:
                tl.units.append((now, category, amount))
    return timelines, now_ms // 1000


def _age_reached(tl: PlayerTimeline, tech: int) -> int | None:
    click = tl.age_clicks.get(tech)
    return click + AGE_RESEARCH_SECONDS[tech] if click is not None else None


def _classify(tl: PlayerTimeline, game_seconds: int) -> dict:
    feudal = _age_reached(tl, FEUDAL)
    castle_click = tl.age_clicks.get(CASTLE)
    castle = _age_reached(tl, CASTLE)

    dark_end = feudal if feudal is not None else min(game_seconds, 15 * 60)
    dark_units = Counter()
    for t, cat, n in tl.units:
        if t < dark_end:
            dark_units[cat] += n
    drush = dark_units["maa"] >= 3

    # Feudal window: from reaching feudal until the castle click (or 8 minutes, whichever first).
    feudal_units: Counter[str] = Counter()
    first_feudal_unit: dict[str, int] = {}
    if feudal is not None:
        window_end = min(castle_click if castle_click is not None else 10 ** 9, feudal + 8 * 60)
        for t, cat, n in tl.units:
            if feudal - 60 <= t < window_end:  # units queued just before the age-up count too
                feudal_units[cat] += n
                first_feudal_unit.setdefault(cat, t)

    fast_castle = (
        feudal is not None and castle_click is not None
        and castle_click - feudal <= 4 * 60 and sum(feudal_units.values()) < 4
    )
    tower_rush = feudal is not None and sum(1 for t in tl.towers_before if t < feudal + 6 * 60) >= 2

    parts = []
    if drush:
        parts.append("Drush")
    if tower_rush:
        parts.append("Tower rush")
    if fast_castle:
        parts.append("FC")
    elif feudal_units:
        ranked = sorted(feudal_units.items(), key=lambda kv: (-kv[1], first_feudal_unit[kv[0]]))
        top, top_n = ranked[0]
        label = CATEGORY_LABEL[top]
        if len(ranked) > 1 and ranked[1][1] >= max(3, top_n * 0.5):
            first, second = sorted(ranked[:2], key=lambda kv: first_feudal_unit[kv[0]])
            label = f"{CATEGORY_LABEL[first[0]]} → {CATEGORY_LABEL[second[0]]}"
        parts.append(label)
    elif feudal is not None:
        parts.append("Eco Feudal")  # reached Feudal without making an army: straight boom
    if not parts:
        parts.append("Unknown")

    tcs = 1 + _distinct_positions([(x, y) for x, y, t in tl.tc_positions if t < BOOM_CHECK_SECONDS])
    military = sorted((t, unit) for t, unit, _ in tl.army)
    after_castle: Counter[int] = Counter()
    for t, unit, n in tl.army:
        if castle is not None and t >= castle - 60:
            after_castle[unit] += n
    main_army = [plural(object_name(u)) for u, n in after_castle.most_common(2) if n >= 5]
    return {
        "feudal": feudal,
        "castle": castle,
        "imperial": _age_reached(tl, IMPERIAL),
        "opening": " → ".join(parts),  # e.g. "Drush → FC", "Scouts", "Archers → Skirms"
        "drush": drush,
        "fast_castle": fast_castle,
        "tower_rush": tower_rush,
        "tcs_by_25": tcs,
        "first_military": object_name(military[0][1]) if military else None,
        "main_army": main_army,
        "first_military_time": military[0][0] if military else None,
    }


def _distinct_positions(points: list[tuple[float, float]], min_gap: float = 4.0) -> int:
    """Re-placed or re-queued foundations at the same spot count once."""
    kept: list[tuple[float, float]] = []
    for x, y in points:
        if all(math.dist((x, y), k) >= min_gap for k in kept):
            kept.append((x, y))
    return len(kept)


def _base(tl: PlayerTimeline) -> tuple[float, float] | None:
    if len(tl.home_builds) < 3:
        return None
    return (median(x for x, _ in tl.home_builds), median(y for _, y in tl.home_builds))


def _positions(record: RecordInfo, bases: dict[int, tuple[float, float] | None]) -> dict[int, str]:
    """Flank = closest to the enemy along the team's line; pocket = sheltered middle."""
    if record.map_name and "nomad" in record.map_name.lower():
        return {}
    teams: dict[int, list[int]] = defaultdict(list)
    for p in record.players:
        if p.team is not None:
            teams[p.team].append(p.number)
    if len(teams) != 2 or any(len(m) < 3 for m in teams.values()):
        return {}  # pocket/flank only means something in 3v3 and 4v4
    out: dict[int, str] = {}
    for team, members in teams.items():
        enemies = [bases[n] for t, ms in teams.items() if t != team for n in ms if bases.get(n)]
        located = [(n, bases[n]) for n in members if bases.get(n)]
        if not enemies or len(located) < len(members):
            continue
        nearest = sorted(located, key=lambda nb: min(math.dist(nb[1], e) for e in enemies))
        n_flanks = 2
        for i, (n, _) in enumerate(nearest):
            out[n] = "flank" if i < n_flanks else "pocket"
    return out


def analyze_recording(raw: bytes) -> tuple[RecordInfo, list[PlayerStrategy], int]:
    """Returns the header, each player's strategy, and how many seconds were read (capped)."""
    record = parse_record_bytes(raw)
    header_len = struct.unpack_from("<I", raw, 0)[0]
    body = io.BytesIO(raw)
    body.seek(header_len)
    numbers = {p.number for p in record.players}
    timelines, game_seconds = _read_timelines(body, numbers)
    bases = {n: _base(tl) for n, tl in timelines.items()}
    positions = _positions(record, bases)
    out = []
    for p in record.players:
        c = _classify(timelines[p.number], game_seconds)
        out.append(PlayerStrategy(
            number=p.number, profile_id=p.profile_id, name=p.name, civ=p.civ, civ_slug=p.civ_slug,
            team=p.team, position=positions.get(p.number), base=bases[p.number], **c,
        ))
    return record, out, game_seconds


def strategy_dict(s: PlayerStrategy) -> dict:
    return asdict(s)
