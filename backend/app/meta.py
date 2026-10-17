"""Static AoE2:DE meta-data queries. Loaded from backend/app/data/*.json."""

from __future__ import annotations

import json
import re
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).with_name("data")

# Ordered upgrade chains used for availability checks and max-upgrade labels.
UNIT_LINES: dict[str, list[str]] = {
    "Archer": ["Archer", "Crossbowman", "Arbalester"],
    "Skirmisher": ["Skirmisher", "Elite Skirmisher", "Imperial Skirmisher"],
    "Scout Cavalry": ["Scout Cavalry", "Light Cavalry", "Hussar", "Winged Hussar"],
    "Knight": ["Knight", "Cavalier", "Paladin", "Savar"],
    "Camel Rider": ["Camel Rider", "Heavy Camel Rider", "Imperial Camel Rider"],
    "Battle Elephant": ["Battle Elephant", "Elite Battle Elephant"],
    "Steppe Lancer": ["Steppe Lancer", "Elite Steppe Lancer"],
    "Fire Lancer": ["Fire Lancer", "Elite Fire Lancer"],
    "Militia": ["Militia", "Man-at-Arms", "Long Swordsman", "Two-Handed Swordsman", "Champion"],
    "Spearman": ["Spearman", "Pikeman", "Halberdier"],
    "Eagle Scout": ["Eagle Scout", "Eagle Warrior", "Elite Eagle Warrior"],
    "Cavalry Archer": ["Cavalry Archer", "Heavy Cavalry Archer"],
    "Mangonel": ["Mangonel", "Onager", "Siege Onager"],
    "Scorpion": ["Scorpion", "Heavy Scorpion"],
    "Battering Ram": ["Battering Ram", "Capped Ram", "Siege Ram"],
    "Bombard Cannon": ["Bombard Cannon", "Houfnice"],
    "Hand Cannoneer": ["Hand Cannoneer"],
    "Monk": ["Monk", "Missionary", "Warrior Priest"],
    "Galley": ["Galley", "War Galley", "Galleon"],
    "Fire Galley": ["Fire Galley", "Fire Ship", "Fast Fire Ship"],
    "Demolition Raft": ["Demolition Raft", "Demolition Ship", "Heavy Demolition Ship"],
    "Cannon Galleon": ["Cannon Galleon", "Elite Cannon Galleon"],
    "Trebuchet": ["Trebuchet", "Mounted Trebuchet", "Traction Trebuchet"],
}

# Map the plural / line-style names used in counters to a unit-line base name.
COUNTER_BASE_NAMES: dict[str, list[str]] = {
    "Spearmen": ["Spearman"],
    "Knights": ["Knight"],
    "Camels": ["Camel Rider"],
    "Mangonels": ["Mangonel"],
    "Light Cavalry": ["Scout Cavalry"],
    "Archers": ["Archer"],
    "Skirmishers": ["Skirmisher"],
    "Monks": ["Monk"],
    "Eagles": ["Eagle Scout"],
    "Militia line": ["Militia"],
    "Hand Cannoneers": ["Hand Cannoneer"],
    "Scorpions": ["Scorpion"],
    "Bombard Cannons": ["Bombard Cannon"],
    "Galleys": ["Galley"],
    "Fire Galleys": ["Fire Galley"],
    "Huskarls": ["Huskarl"],
    "Camel Archers / Genitours": ["Camel Archer", "Genitour"],
}

# --- Focus-quality gates (Explore strict filter) ----------------------------
# Gate 1 — curated `focus_benefits[focus]` flag in civ_meta.json (already authored).
# Gate 2 — does the civ reach the max tier of the relevant unit line?
# Gate 3 — for {archer, infantry, cavalry}: tier-1 + tier-2 of both attack and armor
#          blacksmith upgrades in that class. The final tier (Bracer / Plate Mail /
#          Blast Furnace) is allowed to be missing — replaced by UT / bonus.
#
# Blacksmith upgrade ids (verified against aocref, fandom, and pinned upstream
# commit). Order is consistent across all sources (Feudal → Castle → Imperial).
BSMITH_REQUIRED: dict[str, tuple[int, int, int, int]] = {
    # focus: (atk_t1, atk_t2, arm_t1, arm_t2)
    "archer":   (199, 200, 211, 212),  # Fletching, Bodkin, Padded, Leather
    "infantry": ( 67,  68,  74,  76),  # Forging, Iron Casting, Scale Mail, Chain Mail
    "cavalry":  ( 67,  68,  81,  82),  # Forging, Iron Casting, Scale Barding, Chain Barding
}
# Map focus -> unit-line base name in the civ's `unit_lines` map.
FOCUS_LINE_BASE: dict[str, str] = {
    "archer":         "Archer",
    "cavalry archer": "Cavalry Archer",
    "cavalry":        "Knight",
    "infantry":       "Militia",
    "siege":          "Mangonel",
    "eagle":          "Eagle Scout",
    "camel":          "Camel Rider",
    "elephant":       "Battle Elephant",
    "naval":          "Galley",
    # monk and gunpowder have no unit-line max tier to check; only Gate 1 applies.
}
# Max-tier name that each unit line must reach for the civ to "be" that focus.
FOCUS_MAX_TIER: dict[str, str] = {
    "archer":         "Arbalester",
    "cavalry archer": "Heavy Cavalry Archer",
    "cavalry":        "Paladin",
    "infantry":       "Champion",
    "siege":          "Siege Onager",
    "eagle":          "Elite Eagle Warrior",
    "camel":          "Imperial Camel Rider",
    "elephant":       "Elite Battle Elephant",
    "naval":          "Galleon",
}


def _gate2(civ_data: dict, focus: str) -> bool | None:
    """Return True if the civ reaches the max tier of the focus's unit line.

    None means the gate is not applicable for this focus type (e.g. monk and
    gunpowder have no single production-building line)."""
    base = FOCUS_LINE_BASE.get(focus)
    max_tier = FOCUS_MAX_TIER.get(focus)
    if base is None or max_tier is None:
        return None
    return max_tier in civ_data.get("unit_lines", {}).get(base, [])


def _gate3(civ_data: dict, focus: str) -> bool | None:
    """Return True if the civ has the first two tiers of attack + armor Blacksmith
    upgrades for the focus's class. The third tier is allowed to be missing.
    None means the gate is not applicable for this focus type."""
    req = BSMITH_REQUIRED.get(focus)
    if req is None:
        return None
    techs = set(civ_data.get("techs", []))
    return all(t in techs for t in req)


def _focus_qualifies(slug: str, civ_data: dict, civ_meta_obj: dict, focus: str) -> dict:
    """Compute the three gates for `focus` on `slug`. Always returns a dict
    with keys g1/g2/g3/passes; gates that don't apply come back as None."""
    g1 = civ_meta_obj.get("focus_benefits", {}).get(focus)
    g2 = _gate2(civ_data, focus)
    g3 = _gate3(civ_data, focus)
    if focus in BSMITH_REQUIRED:
        passes = bool(g1) and g2 is True and g3 is True
    else:
        passes = bool(g1) and g2 in (True, None)
    return {"g1": g1, "g2": g2, "g3": g3, "passes": passes}


@lru_cache(maxsize=1)
def _load() -> tuple[dict, dict, dict, dict]:
    techtrees = json.loads((DATA_DIR / "techtrees.json").read_text(encoding="utf-8"))
    civ_meta = json.loads((DATA_DIR / "civ_meta.json").read_text(encoding="utf-8"))
    maps = json.loads((DATA_DIR / "maps.json").read_text(encoding="utf-8"))
    counters = json.loads((DATA_DIR / "counters.json").read_text(encoding="utf-8"))
    return techtrees, civ_meta, maps, counters


def _name_index(units_or_techs: dict[str, dict]) -> dict[str, list[int]]:
    idx: dict[str, list[int]] = {}
    for id_str, obj in units_or_techs.items():
        name = obj.get("name") or ""
        if name:
            idx.setdefault(name, []).append(int(id_str))
    return idx


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _civ_has_name(civ_data: dict, name_index: dict[str, list[int]], name: str) -> bool:
    return any(uid in civ_data["units"] for uid in name_index.get(name, []))


def _civ_has_tech_name(civ_data: dict, tech_index: dict[str, list[int]], name: str) -> bool:
    return any(tid in civ_data["techs"] for tid in tech_index.get(name, []))


def _max_line_unit(civ_data: dict, unit_index: dict[str, list[int]], base_name: str) -> str | None:
    for tier in reversed(UNIT_LINES.get(base_name, [])):
        if any(uid in civ_data["units"] for uid in unit_index.get(tier, [])):
            return tier
    return None


def _civ_can_make(civ_data: dict, unit_index: dict[str, list[int]], tech_index: dict[str, list[int]], text: str) -> bool:
    """Check whether a civ can produce/research every token in an answer like 'Siege Onager + Drill'."""
    for token in re.split(r"\s*\+\s*", text):
        token = token.strip()
        if not token:
            continue
        # Try as a unit line max upgrade, then exact unit/tech name.
        available = (
            _max_line_unit(civ_data, unit_index, token) is not None
            or _civ_has_name(civ_data, unit_index, token)
            or _civ_has_tech_name(civ_data, tech_index, token)
        )
        if not available:
            return False
    return True


def options() -> dict:
    techtrees, civ_meta, maps, counters = _load()
    tags = sorted({t for c in civ_meta.values() for t in c.get("playstyle_tags", [])})
    focus = sorted({t for c in civ_meta.values() for t in c.get("unit_focus", [])})
    unit_names = sorted({u.get("name") for u in techtrees["units"].values() if u.get("name")})
    tech_names = sorted({t.get("name") for t in techtrees["techs"].values() if t.get("name")})
    counter_units = sorted(counters["counters"].keys())
    return {
        "tags": tags,
        "unit_focus": focus,
        "units": unit_names,
        "techs": tech_names,
        "counter_units": counter_units,
        "civs": civ_list(),
    }


def civ_list() -> list[dict]:
    techtrees, civ_meta, _, _ = _load()
    out = []
    for slug, c in civ_meta.items():
        out.append({
            "slug": slug,
            "name": c["name"],
            "type_label": c["type_label"],
            "tags": c.get("playstyle_tags", []),
        })
    return sorted(out, key=lambda x: x["name"])


def civ_detail(slug: str) -> dict | None:
    techtrees, civ_meta, _, _ = _load()
    meta = civ_meta.get(slug)
    if meta is None:
        return None
    tech = techtrees["civs"].get(slug, {})
    return {**meta, "techtree": tech}


def map_info(name: str) -> dict:
    _, _, maps, _ = _load()
    if not name:
        return {"name": name or "Unknown", "type": "unknown", "tags": [], "one_liner": "", "notes": ["No notes yet."]}
    slug = _slugify(name)
    data = maps.get(slug)
    if data is None:
        # Try matching by display name or fuzzy close match.
        for key, entry in maps.items():
            if _slugify(entry.get("name", "")) == slug:
                data = entry
                break
        if data is None:
            close = get_close_matches(slug, maps.keys(), n=1, cutoff=0.6)
            if close:
                data = maps[close[0]]
    if data is None:
        return {"name": name, "type": "unknown", "tags": [], "one_liner": "", "notes": ["No notes yet for this map."]}
    return {"slug": _slugify(data["name"]), **data}


def explore(
    playstyle_tags: list[str],
    unit_focus: list[str],
    units: list[str],
    techs: list[str],
) -> list[dict]:
    """Rank civs for the Explore tab with strict focus-quality gating.

    Filters AND together across four dimensions:
      - playstyle_tags: every selected tag must be in the civ's playstyle_tags
      - unit_focus: for {archer, infantry, cavalry} every selected focus must
        pass all three quality gates; for other focuses, gates 1 + 2.
      - must-have units: civ must produce every selected unit
      - must-have techs: civ must research every selected tech

    Quality gates per focus (see _focus_qualifies):
      1. focus_benefits[focus] flag from civ_meta.json (curated, owned by the
         data file — Gate 1 is the LLMer / human call).
      2. civ reaches the max tier of the relevant unit line at its production
         building (e.g. archer line ends at Arbalester).
      3. for archer / infantry / cavalry: tier-1 + tier-2 of attack and armor
         Blacksmith upgrades both available. The third tier (Bracer / Plate
         Mail / Blast Furnace) is intentionally allowed to be missing — it's
         often replaced by a UT or unique bonus.

    When no focus filter is set, we still rank by gate quality (a passing
    civ outranks a partial civ for the same focus), but the filter is loose:
    civs are shown regardless of whether they pass — the UI uses the gate
    breakdown to explain context.

    Empty filters across the board → all 56 civs returned, alphabetically.
    """
    techtrees, civ_meta, _, _ = _load()
    unit_index = _name_index(techtrees["units"])
    tech_index = _name_index(techtrees["techs"])
    tag_set = set(playstyle_tags)
    focus_set = set(unit_focus)
    unit_set = set(units)
    tech_set = set(techs)

    results = []
    for slug, meta in civ_meta.items():
        civ_data = techtrees["civs"][slug]
        missing_units = [u for u in unit_set if not _civ_has_name(civ_data, unit_index, u)]
        missing_techs = [t for t in tech_set if not _civ_has_tech_name(civ_data, tech_index, t)]
        if missing_units or missing_techs:
            continue
        civ_tags = set(meta.get("playstyle_tags", []))
        civ_focus = set(meta.get("unit_focus", []))
        if tag_set and not tag_set.issubset(civ_tags):
            continue

        # Focus filtering — strict when the user has selected one or more
        # focuses; the gate breakdown is still returned for every focus on
        # every civ so the UI can badge the result cards.
        focus_gates = {f: _focus_qualifies(slug, civ_data, meta, f) for f in FOCUS_LINE_BASE.keys() | civ_focus}
        if focus_set:
            if not all(focus_gates[f]["passes"] for f in focus_set):
                continue

        matched_tags = sorted(tag_set & civ_tags)
        matched_focus = sorted(focus_set & civ_focus)

        # Score: playstyle tag hits + focus hits. With no tag/focus filters,
        # rank by sum of "passes" count across the civ's own unit_focus list
        # so well-rounded civs sort to the top alphabetically otherwise.
        score = len(matched_tags) + len(matched_focus)
        if not (tag_set or focus_set):
            score = sum(focus_gates[f]["passes"] for f in civ_focus)

        results.append({
            "slug": slug,
            "name": meta["name"],
            "type_label": meta["type_label"],
            "ideal_comp": meta.get("ideal_comp", ""),
            "playstyle_tags": civ_tags,
            "unit_focus": civ_focus,
            "matched_tags": matched_tags,
            "matched_focus": matched_focus,
            "score": score,
            "focus_gates": focus_gates,
        })
    results.sort(key=lambda r: (-r["score"], r["name"]))
    return results


def _resolve_counter_unit(query: str) -> str | None:
    _, _, _, counters = _load()
    keys = list(counters["counters"].keys())
    slug = _slugify(query)
    # Exact or slug match
    for k in keys:
        if k.lower() == query.lower() or _slugify(k) == slug:
            return k
    close = get_close_matches(query, keys, n=1, cutoff=0.5)
    if close:
        return close[0]
    close = get_close_matches(slug, [_slugify(k) for k in keys], n=1, cutoff=0.5)
    if close:
        sl = close[0]
        for k in keys:
            if _slugify(k) == sl:
                return k
    return None


def counters(unit_queries: list[str], civ_slugs: list[str]) -> dict:
    """Resolve counter answers for one or more enemy units across the given civs.

    Each enemy query is fuzzy-resolved independently against `counters.json`
    keys; an unresolved query appears in the response as
    `{query: "...", resolved: null, answers: []}` so the UI can show it.

    Empty `unit_queries` returns `{queries: [], resolved: [], answers: []}`
    with no error — the UI uses this as an empty-state signal when the user
    hasn't picked any enemy yet.

    For each civ the response carries an `enemies` array with one entry per
    matched enemy, so the UI can show per-enemy answer sections without
    having to re-resolve. Answers inside each enemy block keep the existing
    shape: `{answer, note, available, generic}`.
    """
    techtrees, civ_meta, _, counters_data = _load()
    unit_index = _name_index(techtrees["units"])
    tech_index = _name_index(techtrees["techs"])

    queries = [q for q in (unit_queries or []) if q]
    if not queries:
        return {"queries": [], "resolved": [], "answers": []}

    resolved_blocks: list[dict] = []
    for q in queries:
        r = _resolve_counter_unit(q)
        resolved_blocks.append({"query": q, "resolved": r, "entry": counters_data["counters"].get(r) if r else None})

    answers = []
    for slug in civ_slugs:
        meta = civ_meta.get(slug)
        civ_data = techtrees["civs"].get(slug, {})
        if meta is None or not civ_data:
            continue
        enemies: list[dict] = []
        for blk in resolved_blocks:
            entry = blk["entry"]
            if entry is None:
                enemies.append({"query": blk["query"], "resolved": blk["resolved"], "answers": []})
                continue
            enemies.append({
                "query": blk["query"],
                "resolved": blk["resolved"],
                "answers": _answers_for_entry(slug, civ_data, entry, counters_data, unit_index, tech_index),
            })
        answers.append({
            "slug": slug,
            "name": meta["name"],
            "enemies": enemies,
        })

    return {
        "queries": queries,
        "resolved": [{"query": b["query"], "resolved": b["resolved"]} for b in resolved_blocks],
        "answers": answers,
    }


def _answers_for_entry(slug: str, civ_data: dict, entry: dict, counters_data: dict,
                       unit_index, tech_index) -> list[dict]:
    """Return the answer rows for one civ against one counter entry."""
    civ_answers: list[dict] = []

    # Generic counters filtered to this civ's tech tree.
    for counter_name in entry.get("generic", []):
        base_names = COUNTER_BASE_NAMES.get(counter_name)
        if base_names is None:
            # Try to treat the whole string as a unit name (e.g. unique units).
            base_names = [counter_name]
        for base in base_names:
            max_tier = _max_line_unit(civ_data, unit_index, base)
            if max_tier is None and _civ_has_name(civ_data, unit_index, base):
                max_tier = base
            if max_tier is None:
                continue
            label = base if max_tier == base else f"{base} (max: {max_tier})"
            civ_answers.append({"answer": label, "note": "", "available": True, "generic": True})
            break  # only first available option from the slash list

    # Civ-specific answers (including wildcard '*' filtered by availability).
    for ans in entry.get("civ_answers", []):
        if ans["civ"] != "*" and ans["civ"] != slug:
            continue
        available = _civ_can_make(civ_data, unit_index, tech_index, ans["answer"])
        civ_answers.append({"answer": ans["answer"], "note": ans.get("note", ""), "available": available, "generic": False})

    # De-duplicate by answer text, preferring available ones.
    seen: dict[str, dict] = {}
    for a in civ_answers:
        key = a["answer"]
        if key not in seen or (not seen[key]["available"] and a["available"]):
            seen[key] = a
    civ_answers = list(seen.values())

    # Fallback group counter if nothing else.
    if not civ_answers and entry.get("group"):
        fallback = counters_data["fallback"].get(entry["group"], [])
        for counter_name in fallback:
            base_names = COUNTER_BASE_NAMES.get(counter_name, [counter_name])
            for base in base_names:
                max_tier = _max_line_unit(civ_data, unit_index, base)
                if max_tier is None and _civ_has_name(civ_data, unit_index, base):
                    max_tier = base
                if max_tier:
                    label = base if max_tier == base else f"{base} (max: {max_tier})"
                    civ_answers.append({"answer": label, "note": "", "available": True, "generic": True})
                    break

    return civ_answers


def civ_brief(slug: str) -> dict | None:
    """Short form attached to live match players."""
    techtrees, civ_meta, _, _ = _load()
    meta = civ_meta.get(slug)
    if meta is None:
        return None
    return {
        "slug": slug,
        "name": meta["name"],
        "type_label": meta["type_label"],
        "bonuses": meta.get("bonuses", []),
        "team_bonus": meta.get("team_bonus", ""),
        "unique_units": [u["name"] for u in meta.get("unique_units", [])],
        "unique_techs": meta.get("unique_techs", []),
        "tags": meta.get("playstyle_tags", []),
        "ideal_comp": meta.get("ideal_comp", ""),
        "watch_out": meta.get("watch_out", ""),
    }
