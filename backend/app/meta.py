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


def explore(tags: list[str], units: list[str], techs: list[str]) -> list[dict]:
    techtrees, civ_meta, _, _ = _load()
    unit_index = _name_index(techtrees["units"])
    tech_index = _name_index(techtrees["techs"])
    tag_set = set(tags)
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
        score = len(tag_set & civ_tags) + len(tag_set & civ_focus) * 0.5
        matched = sorted(tag_set & civ_tags)
        results.append({
            "slug": slug,
            "name": meta["name"],
            "type_label": meta["type_label"],
            "ideal_comp": meta.get("ideal_comp", ""),
            "tags": meta.get("playstyle_tags", []),
            "matched_tags": matched,
            "score": score,
        })
    results.sort(key=lambda r: -r["score"])
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


def counters(unit_query: str, civ_slugs: list[str]) -> dict:
    techtrees, civ_meta, _, counters_data = _load()
    unit_index = _name_index(techtrees["units"])
    tech_index = _name_index(techtrees["techs"])

    resolved = _resolve_counter_unit(unit_query)
    if resolved is None:
        return {"query": unit_query, "resolved": None, "answers": []}

    entry = counters_data["counters"][resolved]
    answers = []

    for slug in civ_slugs:
        meta = civ_meta.get(slug)
        civ_data = techtrees["civs"].get(slug, {})
        if meta is None or not civ_data:
            continue
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

        answers.append({
            "slug": slug,
            "name": meta["name"],
            "answers": civ_answers,
        })

    return {"query": unit_query, "resolved": resolved, "answers": answers}


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
