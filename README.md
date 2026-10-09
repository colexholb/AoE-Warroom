# AoE Warroom

Local scouting app for Age of Empires II: DE. Start it, open the page, queue up. The moment a
game starts, the page shows every player with civ history, form, map record and plain-language
weaknesses and strengths, plus who to attack first.

## Run

```
run.bat         # http://localhost:8000, this PC only
run.bat lan     # also reachable by friends on your network at http://<your-PC-IP>:8000
```

The first run creates `.venv` and installs dependencies. Windows may ask to allow Python through
the firewall for `lan` mode; allow it on private networks.

Requires **Record game** to be on in AoE2 settings.

## How it works

- `backend/app/live.py` watches `%USERPROFILE%\Games\Age of Empires 2 DE\*\savegame` for new
  `.aoe2record` files. The game creates one as soon as a match starts.
- `backend/app/record_header.py` reads players, civs, colors, teams, map and start time straight
  from the recording header (own minimal reader; the `mgz` library breaks on current patches).
- `backend/app/aoe2companion.py` pulls each player's profile and last 300 matches from the public
  aoe2companion API (cached for 5 min).
- `backend/app/stats.py` turns history into stats, insight tags and a threat score.
- `backend/app/static/` is the UI: plain Preact + htm, no build step. Updates arrive over
  server-sent events (`/api/events`).

## Settings (environment variables)

| Variable | Default | |
|---|---|---|
| `AOE_PROFILE_ID` | auto-detected | Your profile id (the player present in all your recordings) |
| `AOE_SAVEGAME_DIR` | auto-detected | Folder to watch |
| `AOE_HISTORY_SIZE` | 300 | Matches pulled per player (max 300) |
| `AOE_LIVE_TIMEOUT` | 90 | Seconds without writes before a game counts as finished |

## Roadmap

1. ✅ Live lobby detection + match-history scouting
2. Replay parsing for strategy: openings (drush / scouts / archers / FC), age-up times, TC count
   (booms), pocket vs flank from start positions
3. Persisting history locally (SQLite) to track opponents you meet repeatedly
4. (Secondary) Meta stats: civ / map / matchup win rates for the current patch at your Elo.
   aoestats.io stopped updating in Feb 2026 and aoe2insights' stats API is off-limits to bots
   (`robots.txt`), so the plan is to sample ~100 players near your rating from the aoe2companion
   RM Team leaderboard weekly and compute it ourselves. Openings come after replay parsing.
