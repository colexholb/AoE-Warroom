"""Turn a player's match history into scouting stats and plain-language insights."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

SHORT_GAME_MINUTES = 25
LONG_GAME_MINUTES = 40
DEFAULT_SPEED_FACTOR = 1.7  # "Normal" speed; in-game minutes per real minute
# Below this many games on a map, a win rate is mostly noise (2-5 can just be bad teammates).
MIN_MAP_GAMES = 10


@dataclass
class GameContext:
    """What we know about the game being scouted."""

    civ_slug: str | None
    civ_name: str | None
    map_name: str | None
    is_team_game: bool
    started: datetime | None


@dataclass
class PastGame:
    started: datetime
    won: bool | None
    civ: str
    civ_name: str
    map_name: str
    is_team_game: bool
    minutes: float | None  # in-game minutes
    rating: int | None


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _past_games(profile_id: int, matches: list[dict], before: datetime | None) -> list[PastGame]:
    games = []
    for m in matches:
        started = _parse_time(m.get("started"))
        if started is None:
            continue
        # Skip the game being scouted (and anything after it when viewing an old recording).
        if before and started >= before - timedelta(minutes=2):
            continue
        players = [(t["teamId"], p) for t in m.get("teams", []) for p in t["players"]]
        mine = next((p for _, p in players if p.get("profileId") == profile_id), None)
        if mine is None:
            continue
        finished = _parse_time(m.get("finished"))
        minutes = None
        if finished:
            speed = m.get("speedFactor") or DEFAULT_SPEED_FACTOR
            minutes = (finished - started).total_seconds() / 60 * speed
        team_sizes = Counter(team for team, _ in players)
        games.append(PastGame(
            started=started,
            won=mine.get("won"),
            civ=mine.get("civ") or "",
            civ_name=mine.get("civName") or mine.get("civ") or "?",
            map_name=m.get("mapName") or "",
            is_team_game=any(n > 1 for n in team_sizes.values()),
            minutes=minutes,
            rating=mine.get("rating"),
        ))
    games.sort(key=lambda g: g.started, reverse=True)
    return games


def _record(games: list[PastGame]) -> dict:
    decided = [g for g in games if g.won is not None]
    wins = sum(1 for g in decided if g.won)
    return {
        "games": len(decided),
        "wins": wins,
        "win_rate": round(wins / len(decided), 3) if decided else None,
    }


def _pct(rate: float | None) -> str:
    return f"{round(rate * 100)}%" if rate is not None else "?"


def _pick_leaderboard(profile: dict, is_team_game: bool) -> dict | None:
    boards = [b for b in profile.get("leaderboards", []) if b.get("games")]
    preferred = "rm_team" if is_team_game else "rm_1v1"
    for board in boards:
        if board["leaderboardId"] == preferred:
            return board
    return max(boards, key=lambda b: b["games"], default=None)


def analyze_player(profile_id: int, profile: dict, matches: list[dict], ctx: GameContext) -> dict:
    games = _past_games(profile_id, matches, ctx.started)
    decided = [g for g in games if g.won is not None]
    overall = _record(games)
    overall_wr = overall["win_rate"]
    n = len(games)

    # Form
    form = ["W" if g.won else "L" for g in decided[:10]]
    streak = 0
    for g in decided:
        if streak == 0:
            streak = 1 if g.won else -1
        elif (streak > 0) == g.won:
            streak += 1 if g.won else -1
        else:
            break

    # Civs
    by_civ: dict[str, list[PastGame]] = defaultdict(list)
    for g in games:
        by_civ[g.civ].append(g)
    top_civs = [
        {"civ": civ, "civ_name": gs[0].civ_name, **_record(gs), "share": round(len(gs) / n, 3)}
        for civ, gs in sorted(by_civ.items(), key=lambda kv: -len(kv[1]))[:6]
    ]
    current_civ = None
    if ctx.civ_slug:
        gs = by_civ.get(ctx.civ_slug, [])
        current_civ = {"civ": ctx.civ_slug, "civ_name": ctx.civ_name, **_record(gs),
                       "played": len(gs), "share": round(len(gs) / n, 3) if n else 0}

    # Map
    current_map = None
    if ctx.map_name:
        gs = [g for g in games if g.map_name.lower() == ctx.map_name.lower()]
        current_map = {"map_name": ctx.map_name, "played": len(gs), **_record(gs)}

    # Game length
    timed = [g for g in games if g.minutes is not None]
    short = [g for g in timed if g.minutes < SHORT_GAME_MINUTES]
    long = [g for g in timed if g.minutes >= LONG_GAME_MINUTES]
    length = {
        "avg_minutes": round(sum(g.minutes for g in timed) / len(timed), 1) if timed else None,
        "short": _record(short),
        "long": _record(long),
    }

    # Activity
    now = ctx.started or datetime.now(timezone.utc)
    days_since_last = (now - games[0].started).days if games else None
    games_last_week = sum(1 for g in games if now - g.started <= timedelta(days=7))
    team_share = round(sum(g.is_team_game for g in games) / n, 3) if n else None

    board = _pick_leaderboard(profile, ctx.is_team_game)
    total_games = int(profile.get("games") or 0)
    drops = int(profile.get("drops") or 0)
    rating = {
        "leaderboard": board.get("abbreviation") or board.get("leaderboardName") if board else None,
        "rating": board.get("rating") if board else None,
        "max_rating": board.get("maxRating") if board else None,
        "rank": board.get("rank") if board else None,
        "wins": board.get("wins") if board else None,
        "losses": board.get("losses") if board else None,
    }

    insights = _insights(
        ctx=ctx, n=n, overall_wr=overall_wr, streak=streak, current_civ=current_civ,
        current_map=current_map, length=length, top_civs=top_civs, by_civ_count=len(by_civ),
        team_share=team_share, total_games=total_games, drops=drops,
        days_since_last=days_since_last,
    )

    return {
        "profile_id": profile_id,
        "country": profile.get("country"),
        "clan": profile.get("clan") or None,
        "total_games": total_games,
        "drop_rate": round(drops / total_games, 3) if total_games else None,
        "rating": rating,
        "sample_size": n,
        "overall": overall,
        "form": form,
        "streak": streak,
        "top_civs": top_civs,
        "current_civ": current_civ,
        "current_map": current_map,
        "length": length,
        "team_share": team_share,
        "days_since_last": days_since_last,
        "games_last_week": games_last_week,
        "insights": insights,
        "threat": _threat(rating["rating"], current_civ, streak, form, days_since_last),
    }


def _insights(*, ctx, n, overall_wr, streak, current_civ, current_map, length, top_civs,
              by_civ_count, team_share, total_games, drops, days_since_last) -> list[dict]:
    """Plain-language tags. "weakness" = something to exploit, "strength" = something to respect."""
    out: list[dict] = []

    def add(kind: str, text: str) -> None:
        out.append({"kind": kind, "text": text})

    if n == 0:
        add("info", "No match history available (hidden profile or brand new account)")
        return out

    if current_civ:
        played, civ = current_civ["played"], current_civ["civ_name"]
        if played == 0:
            add("weakness", f"First time on {civ} in their last {n} games")
        elif played <= 2:
            add("weakness", f"Rarely plays {civ} ({played} of last {n} games)")
        elif current_civ["share"] >= 0.2 and played >= 5:
            add("strength", f"{civ} main: {played} games, {_pct(current_civ['win_rate'])} win rate")

    if streak <= -3:
        add("weakness", f"Lost {-streak} in a row, possibly tilted")
    elif streak >= 3:
        add("strength", f"On a {streak}-game win streak")

    if overall_wr is not None:
        short, long = length["short"], length["long"]
        if short["games"] >= 4 and short["win_rate"] <= overall_wr - 0.15:
            add("weakness", f"Only {_pct(short['win_rate'])} win rate in games decided before "
                            f"{SHORT_GAME_MINUTES} min. Pressure early")
        elif short["games"] >= 4 and short["win_rate"] >= overall_wr + 0.15:
            add("strength", f"Dangerous early: {_pct(short['win_rate'])} win rate in games under "
                            f"{SHORT_GAME_MINUTES} min")
        if long["games"] >= 4 and long["win_rate"] <= overall_wr - 0.15:
            add("weakness", f"Falls off late: {_pct(long['win_rate'])} win rate in "
                            f"{LONG_GAME_MINUTES}+ min games")
        elif long["games"] >= 4 and long["win_rate"] >= overall_wr + 0.15:
            add("strength", f"Strong late game: {_pct(long['win_rate'])} win rate in "
                            f"{LONG_GAME_MINUTES}+ min games")

    if current_map:
        cm = current_map
        record = f"{cm['wins']}-{cm['games'] - cm['wins']} in their last {n} games"
        if cm["games"] >= MIN_MAP_GAMES and cm["win_rate"] >= 0.6:
            add("strength", f"Good on {cm['map_name']}: {record}")
        elif cm["games"] >= MIN_MAP_GAMES and cm["win_rate"] <= 0.4:
            add("weakness", f"Struggles on {cm['map_name']}: {record}")
        elif current_map["played"] == 0 and n >= 20:
            add("info", f"Hasn't played {current_map['map_name']} in their last {n} games")

    if team_share is not None and n >= 10:
        if ctx.is_team_game and team_share < 0.3:
            add("weakness", f"Mostly a 1v1 player (only {_pct(team_share)} team games)")
        elif not ctx.is_team_game and team_share > 0.7:
            add("weakness", f"Mostly a team game player ({_pct(team_share)} team games)")

    if total_games and total_games < 50:
        add("weakness", f"Inexperienced account: {total_games} total games")

    if days_since_last is not None and days_since_last >= 21:
        add("weakness", f"Rusty: first game in {days_since_last} days")

    if total_games and drops / total_games >= 0.05:
        add("info", f"Drops {_pct(drops / total_games)} of games")

    # Skip "one-trick" when they're on that civ right now: the "main" tag already says it.
    on_main = bool(top_civs and current_civ and top_civs[0]["civ"] == current_civ["civ"])
    if top_civs and top_civs[0]["share"] >= 0.5 and n >= 10 and not on_main:
        add("info", f"One-trick: {top_civs[0]['civ_name']} in {_pct(top_civs[0]['share'])} of games")
    elif n >= 15 and by_civ_count / n >= 0.6:
        add("info", f"Plays {by_civ_count} different civs in {n} games, probably random civ")

    return out


def _threat(rating: int | None, current_civ: dict | None, streak: int, form: list[str],
            days_since_last: int | None) -> int | None:
    """Rating adjusted by situational factors. Only meaningful relative to other players."""
    if rating is None:
        return None
    score = float(rating)
    if current_civ:
        if current_civ["played"] == 0:
            score -= 60
        elif current_civ["played"] <= 2:
            score -= 30
        elif current_civ["share"] >= 0.2 and current_civ["played"] >= 5:
            score += 40
    score += max(-3, min(3, streak)) * 10
    if form:
        score += (form.count("W") / len(form) - 0.5) * 80
    if days_since_last is not None and days_since_last >= 21:
        score -= 30
    return round(score)


def team_summary(players: list[dict], my_team: int | None) -> dict:
    """Pick out who to target and who to respect among the enemies."""
    enemies = [p for p in players if not p["is_me"] and (my_team is None or p["team"] != my_team)]
    scored = [p for p in enemies if p.get("analysis") and p["analysis"].get("threat") is not None]
    avg: dict = {}
    for p in players:
        r = (p.get("analysis") or {}).get("rating", {}).get("rating")
        if r is not None and p["team"] is not None:
            avg.setdefault(p["team"], []).append(r)
    team_ratings = {str(k): round(sum(v) / len(v)) for k, v in avg.items() if len(avg) > 1}
    if not scored:
        return {"team_ratings": team_ratings, "target": None, "threat": None}
    target = min(scored, key=lambda p: p["analysis"]["threat"])
    threat = max(scored, key=lambda p: p["analysis"]["threat"])

    def reasons(p: dict, kind: str) -> list[str]:
        insights = p["analysis"]["insights"] + ((p.get("playstyle") or {}).get("insights") or [])
        found = [i["text"] for i in insights if i["kind"] == kind][:3]
        rating = p["analysis"]["rating"]["rating"]
        extreme = "Lowest" if kind == "weakness" else "Highest"
        return found or [f"{extreme} rated enemy after adjusting for civ and form ({rating} rating)"]

    return {
        "team_ratings": team_ratings,
        "target": {"number": target["number"], "name": target["name"], "reasons": reasons(target, "weakness")},
        "threat": None if threat is target else
                  {"number": threat["number"], "name": threat["name"], "reasons": reasons(threat, "strength")},
    }
