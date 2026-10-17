#!/usr/bin/env python3
"""Heuristic seed of playstyle tags, unit focus, ideal comp and watch-out for every civ.

Run after fetch_techtree.py, then hand-review and edit backend/app/data/civ_meta.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "app" / "data"

TAGS_VOCABULARY = [
    "rush", "boom", "turtle", "aggressive", "defensive",
    "cavalry", "cavalry archers", "archers", "infantry", "siege",
    "naval", "gunpowder", "monks", "elephants", "camels", "eagles",
    "unique unit", "late game", "early game", "mobility", "eco",
]

FOCUS_VOCABULARY = [
    "archer", "cavalry archer", "cavalry", "infantry", "siege",
    "monk", "gunpowder", "elephant", "camel", "eagle", "naval", "defensive",
]


def load() -> tuple[dict, dict]:
    techtrees = json.loads((DATA_DIR / "techtrees.json").read_text(encoding="utf-8"))
    civ_meta = json.loads((DATA_DIR / "civ_meta.json").read_text(encoding="utf-8"))
    return techtrees, civ_meta


def has_line(civ_techtree: dict, base_name: str) -> bool:
    return base_name in civ_techtree.get("unit_lines", {})


def max_in_line(civ_techtree: dict, base_name: str) -> str | None:
    return civ_techtree.get("unit_lines", {}).get(base_name, [None])[-1]


def type_tags(type_label: str) -> list[str]:
    label = type_label.lower()
    mapping = [
        ("foot archer", "archers"),
        ("cavalry archer", "cavalry archers"),
        ("gunpowder", "gunpowder"),
        ("defensive", "defensive"),
        ("naval", "naval"),
        ("infantry", "infantry"),
        ("siege", "siege"),
        ("cavalry", "cavalry"),
        ("camel", "camels"),
        ("elephant", "elephants"),
        ("monk", "monks"),
        ("archer", "archers"),
        ("counter-units", "defensive"),
    ]
    tags: list[str] = []
    for phrase, tag in mapping:
        if re.search(r"\b" + re.escape(phrase) + r"\b", label):
            tags.append(tag)
    return tags


def unique_unit_tags(uu: dict) -> list[str]:
    name = uu["name"].lower()
    kind = uu.get("kind", "").lower()
    tags: list[str] = []
    if "mounted archer" in kind or name in {"mangudai", "kipchak", "camel archer", "war chariot", "xianbei raider"}:
        tags.append("cavalry archers")
    if "cavalry" in kind and "mounted archer" not in kind and "siege" not in kind:
        tags.append("cavalry")
    if "infantry" in kind:
        tags.append("infantry")
    if "foot archer" in kind:
        tags.append("archers")
    if "gunpowder" in kind:
        tags.append("gunpowder")
    if "siege" in kind:
        tags.append("siege")
    if name in {"war elephant", "battle elephant", "ballista elephant", "elephant archer"}:
        tags.append("elephants")
    if name in {"camel archer", "imperial camel rider", "camel scout", "mameluke", "flaming camel"}:
        tags.append("camels")
    if name in {"eagle scout", "eagle warrior", "plumed archer"}:
        tags.append("eagles")
    if name in {"monk", "missionary", "warrior priest"}:
        tags.append("monks")
    if name in {"longship", "turtle ship", "caravel", "dragon ship", "thirisadai", "dromon", "lou chuan", "catapult galleon", "war hulk"}:
        tags.append("naval")
    tags.append("unique unit")
    return tags


def seed_civ(slug: str, meta: dict, techtree: dict) -> dict:
    type_label = meta["type_label"]
    bonuses = " ".join(meta["bonuses"]).lower()
    uus = meta["unique_units"]

    tags: list[str] = []
    tags += type_tags(type_label)
    for uu in uus:
        tags += unique_unit_tags(uu)

    # Pacing / style hints from bonuses
    if any(b in bonuses for b in ["town center", "villager", "farm", "fish trap", "age is +", "age costs", "economic upgrades"]):
        tags.append("boom")
    if any(b in bonuses for b in ["military units train", "attack +", "hp starting", "cost -", "move +", "work +"]):
        tags.append("aggressive")
    if "defensive" in tags or any(b in bonuses for b in ["buildings +", "garrison", "heal", "walls", "fortified"]):
        tags.append("turtle")
    if "cavalry archers" in tags or "cavalry" in tags or "eagles" in tags or "camels" in tags:
        tags.append("mobility")
    if "boom" in tags or "turtle" in tags:
        tags.append("late game")
    if "aggressive" in tags and ("cavalry" in tags or "eagles" in tags or "infantry" in tags):
        tags.append("rush")

    seen = set()
    tags = [t for t in tags if not (t in seen or seen.add(t))]
    tags = [t for t in tags if t in TAGS_VOCABULARY]

    # Unit focus from tags + strong generic lines
    focus: list[str] = []
    focus_map = {
        "archers": "archer",
        "cavalry archers": "cavalry archer",
        "cavalry": "cavalry",
        "infantry": "infantry",
        "siege": "siege",
        "naval": "naval",
        "gunpowder": "gunpowder",
        "monks": "monk",
        "elephants": "elephant",
        "camels": "camel",
        "eagles": "eagle",
        "defensive": "defensive",
    }
    for t in tags:
        if focus_map.get(t):
            focus.append(focus_map[t])
    if has_line(techtree, "Knight") and "cavalry" not in focus:
        focus.append("cavalry")
    if has_line(techtree, "Archer") and "archer" not in focus:
        focus.append("archer")
    if has_line(techtree, "Militia") and "infantry" not in focus:
        focus.append("infantry")
    if has_line(techtree, "Mangonel") and "siege" not in focus:
        focus.append("siege")
    seen = set()
    focus = [f for f in focus if not (f in seen or seen.add(f))]
    focus = focus[:4]

    # Ideal composition
    unique_names = [u["name"] for u in uus]
    # Pick the most relevant unique units (up to 2)
    picked_uus = unique_names[:2]
    comp: list[str] = []

    def add_unique():
        comp.extend(picked_uus)

    def add_knight():
        if has_line(techtree, "Knight"):
            m = max_in_line(techtree, "Knight")
            if m and m not in comp:
                comp.append(m)

    def add_archer():
        if has_line(techtree, "Archer"):
            m = max_in_line(techtree, "Archer")
            if m and m not in comp:
                comp.append(m)

    def add_halb():
        if has_line(techtree, "Spearman"):
            m = max_in_line(techtree, "Spearman")
            if m and m not in comp:
                comp.append(m)

    def add_cav_archer():
        if has_line(techtree, "Cavalry Archer"):
            m = max_in_line(techtree, "Cavalry Archer")
            if m and m not in comp:
                comp.append(m)

    def add_siege():
        if has_line(techtree, "Mangonel") and max_in_line(techtree, "Mangonel") == "Siege Onager":
            comp.append("Siege Onager")
        elif has_line(techtree, "Scorpion") and max_in_line(techtree, "Scorpion") == "Heavy Scorpion":
            comp.append("Heavy Scorpion")
        elif has_line(techtree, "Mangonel"):
            comp.append("Mangonel-line")

    if "cavalry archers" in tags:
        add_unique()
        add_knight()
        add_siege()
    elif "cavalry" in tags and "cavalry archers" not in tags:
        add_unique()
        add_knight()
        add_cav_archer()
    elif "archers" in tags:
        add_unique()
        add_archer()
        add_halb()
        add_siege()
    elif "infantry" in tags:
        add_unique()
        if has_line(techtree, "Militia"):
            m = max_in_line(techtree, "Militia")
            if m and m not in comp:
                comp.append(m)
        add_siege()
        add_halb()
    elif "elephants" in tags:
        add_unique()
        comp.append("Skirmishers")
    elif "gunpowder" in tags:
        add_unique()
        if has_line(techtree, "Hand Cannoneer"):
            comp.append("Hand Cannoneer")
        if has_line(techtree, "Bombard Cannon"):
            comp.append("Bombard Cannon")
        add_halb()
    elif "siege" in tags:
        add_unique()
        add_siege()
        add_halb()
    elif "naval" in tags:
        add_unique()
        if has_line(techtree, "Galley"):
            comp.append("Galleon")
    else:
        add_unique()
        add_knight()

    # De-duplicate while preserving order
    seen = set()
    comp = [c for c in comp if c and not (c in seen or seen.add(c))]
    ideal_comp = "; ".join(comp) if comp else "mixed army"

    # Watch-out
    watch_opts: list[str] = []
    if "elephants" in tags:
        watch_opts.append("Monks and Halberdiers shut down elephants")
    if "cavalry" in tags or "cavalry archers" in tags:
        watch_opts.append("Halberdiers and Camel Riders counter your core")
    if "archers" in tags:
        watch_opts.append("cavalry raids and Skirmishers are a threat")
    if "infantry" in tags:
        watch_opts.append("archers and Hand Cannoneers kite your infantry")
    if "gunpowder" in tags:
        watch_opts.append("Onagers and Skirmishers punish grouped gunpowder")
    if "eagles" in tags:
        watch_opts.append("infantry and Hand Cannoneers beat Eagles")
    if "siege" in tags and "cavalry" not in tags and "cavalry archers" not in tags:
        watch_opts.append("mobile units can pick off siege if unguarded")
    if not watch_opts:
        watch_opts.append("identify and exploit the enemy's counter-unit window")
    watch_out = "; ".join(watch_opts[:2])

    return {
        **meta,
        "playstyle_tags": tags[:6],
        "unit_focus": focus,
        "ideal_comp": ideal_comp,
        "watch_out": watch_out,
    }


def main() -> None:
    techtrees, civ_meta = load()
    for slug, meta in civ_meta.items():
        civ_meta[slug] = seed_civ(slug, meta, techtrees["civs"][slug])
    (DATA_DIR / "civ_meta.json").write_text(json.dumps(civ_meta, indent=2), encoding="utf-8")
    print(f"Seeded {len(civ_meta)} civs")


if __name__ == "__main__":
    main()
