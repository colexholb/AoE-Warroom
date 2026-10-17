# Data sources and attribution

The static data files in this directory ship with AoE Warroom and are committed to the
repository so the app works offline.

## `techtrees.json`

Generated from **SiegeEngineers/aoe2techtree** `data/data.json` and
`data/locales/en/strings.json`.

- Repository: https://github.com/SiegeEngineers/aoe2techtree
- Pinned upstream commit: `3bb43b1439eef88dfe7fe892d7f7dc41ac9dd76f`
- License: code is MIT; in-game text and numeric values are official Age of Empires II:
  Definitive Edition data, used under Microsoft's Game Content Usage Rules.
- Generation tool: `tools/fetch_techtree.py`

## `civ_meta.json`

- `type_label`, `bonuses`, `team_bonus`, `unique_units`, `unique_techs` are extracted from
  the official civilization help strings in aoe2techtree's `strings.json`.
- `playstyle_tags`, `unit_focus`, `ideal_comp` and `watch_out` are hand-curated by the
  project owner in their own words.

## `maps.json`

Hand-curated map notes written by the project owner. Map names are matched against the
canonical list in the bundled `aocref` dataset (`datasets/100.json`).

## `counters.json`

Migrates and extends the hand-curated counter table that previously lived in
`backend/app/counters.py`. Generic counter knowledge is common AoE2 community understanding;
civ-specific answers are written by the project owner.

## Microsoft Game Content Usage Rules

Age of Empires II © Microsoft Corporation. AoE Warroom was created under Microsoft's
"Game Content Usage Rules" (https://www.xbox.com/en-US/developers/rules) using assets from
Age of Empires II, and it is not endorsed by or affiliated with Microsoft.
