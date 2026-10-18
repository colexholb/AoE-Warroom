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

Turn on **Record game** in AoE2 settings: games then show up on the loading screen. Without it,
Warroom still finds them through aoe2companion, about 10–35 seconds into the game.

## How it works

- `backend/app/live.py` finds new games two ways, whichever is first:
  - it watches `%USERPROFILE%\Games\Age of Empires 2 DE\*\savegame` for new `.aoe2record` files,
    which the game creates as soon as a match starts;
  - `backend/app/ongoing.py` listens on aoe2companion's live-match websocket, which announces your
    games with their players, civs, colors and teams, and says when they end.
- `backend/app/record_header.py` reads players, civs, colors, teams, map and start time straight
  from the recording header (own minimal reader; the `mgz` library breaks on current patches).
- `backend/app/aoe2companion.py` pulls each player's profile and last 300 matches from the public
  aoe2companion API (cached for 5 min).
- `backend/app/stats.py` turns history into stats, insight tags and a threat score.
- `backend/app/replay.py` reads the first 35 minutes of a recording's action stream (via `mgz`'s
  fast operation parser) and works out each player's opening (Drush, Scouts, Archers, M@A, FC,
  tower rush…), age-up times, Town Centers by minute 25, main Castle Age army, and pocket vs flank
  (from where their early houses and camps went up).
- `backend/app/replay_store.py` downloads players' recent replays from the official replay server
  (`aoe.ms/replay`), analyzes them and caches the results in `%LOCALAPPDATA%\AoE Warroom\cache\warroom.db`. Your own
  finished recordings are indexed too (not with `AOE_DETECT=api`), which covers lobby games the API
  doesn't list.
- `backend/app/playstyle.py` turns up to 10 analyzed games per player into tendencies ("Opens FC in
  7/10 games", "Big boomer", "Usually plays pocket", "Weak on flank: 1-4") with counter advice for
  enemies. Collapsed cards show at-a-glance stats (Rush potential = Feudal military units, TCs by
  25 min, castles by 25 min, army mix + what to build, premade) plus Danger / Exploit tiles
  listing the red and green tags. The verdicts below are in the expanded card:
  - **Boom or rush**: TCs by minute 25 and military made in Feudal Age → Boomer / Mixed / Rusher.
  - **Castle Age**: what they do in the 5 minutes after reaching Castle Age (2+ new TCs or 3+ TCs by
    25 = boom, 10+ military = army), castles placed by minute 25, and whether a castle went down
    closer to an enemy base than their own (forward castle) or they made 8+ unique units (UU rush).
  - **Army**: their Castle Age unit mix (share of ranged / cavalry / infantry / siege / monks) and
    what to build against it ("Build: Skirmishers + Mangonels"; "Weak to: …" on your own team),
    from the hand-curated table in `backend/app/counters.py`. Unique units only count from past
    games on the civ they're playing now.
  - **Comms**: anyone in the lobby who was their teammate in 2+ of their last 10 games.

**Fair play:** only past games are analyzed. The recording of the game in progress is never read
past its header (the lobby info you see on the loading screen anyway), and nothing that started
after it is used.
- `backend/app/static/` is the UI: plain Preact + htm, no build step. Updates arrive over
  server-sent events (`/api/events`).

## Tabs

- **Scout** — the original live/last-match view. Above the player cards you'll see a match
  briefing with the map write-up and a chip for each civilization (click to expand bonuses,
  unique units/techs, ideal comp and watch-outs).
- **Players** — look up any AoE2:DE player by name, profile id or `aoe2companion.com/profile/<id>`
  link. Shows the same scouting card as Scout for that player, plus a panel with their ELO on
  RM 1v1 Ranked, RM Team Ranked, and Team Quick Play. Deep-link any search:
  `http://localhost:8000/#/players?q=<profile_id>`.
- **Explore** — before queueing, pick playstyle tags, must-have units and technologies to get a
  ranked list of recommended civilizations.
- **Counter** — during a game, type an enemy unit (e.g. "Scorpion") and see concrete counters
  filtered to what your team's civs can actually build or research.

## Data

Static AoE2:DE meta data lives in `backend/app/data/`:

- `techtrees.json` — generated from SiegeEngineers/aoe2techtree (commit pinned in
  `data/SOURCES.md`).
- `civ_meta.json` — civilization bonuses, unique units/techs (from official game strings) plus
  hand-curated playstyle tags, ideal compositions and watch-outs.
- `maps.json` — hand-curated notes for the common map pool.
- `counters.json` — generic and civ-specific counter answers; loaded by `backend/app/counters.py`.

To refresh after a game patch, re-run `tools/fetch_techtree.py`, review the diff, and edit the
hand-curated files. See `backend/app/data/SOURCES.md` for full attribution.

## Settings (environment variables)

| Variable | Default | |
|---|---|---|
| `AOE_PROFILE_ID` | auto-detected | Your profile id (the player present in all your recordings) |
| `AOE_SAVEGAME_DIR` | auto-detected | Folder to watch |
| `AOE_DETECT` | both | How to find new games: `folder` (recordings), `api` (aoe2companion websocket only; reads no local recordings at all, like a hosted server) or `both` |
| `AOE_HISTORY_SIZE` | 300 | Matches pulled per player (max 300) |
| `AOE_LIVE_TIMEOUT` | 90 | Seconds without writes before a game counts as finished |

## Roadmap

1. ✅ Live lobby detection + match-history scouting
2. ✅ Replay parsing for strategy: openings, age-up times, TC count (booms), main army,
   pocket vs flank
3. Track opponents you meet repeatedly (head-to-head record, notes)
4. (Secondary) Meta stats: civ / map / matchup win rates for the current patch at your Elo.
   aoestats.io stopped updating in Feb 2026 and aoe2insights' stats API is off-limits to bots
   (`robots.txt`), so the plan is to sample ~100 players near your rating from the aoe2companion
   RM Team leaderboard weekly and compute it ourselves. Openings come after replay parsing.

## Legal

Age of Empires II © Microsoft Corporation. AoE Warroom was created under Microsoft's
"[Game Content Usage Rules](https://www.xbox.com/en-US/developers/rules)" using assets from
Age of Empires II, and it is not endorsed by or affiliated with Microsoft.
