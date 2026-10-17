#!/usr/bin/env python3
"""Fetch AoE2:DE tech-tree data from SiegeEngineers/aoe2techtree and generate
backend/app/data/techtrees.json plus a seeded civ_meta.json.

Run manually after a game patch; the app never executes this at runtime.
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import aocref

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "backend" / "app" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

COMMIT = "3bb43b1439eef88dfe7fe892d7f7dc41ac9dd76f"
DATA_URL = f"https://raw.githubusercontent.com/SiegeEngineers/aoe2techtree/{COMMIT}/data/data.json"
STRINGS_URL = f"https://raw.githubusercontent.com/SiegeEngineers/aoe2techtree/{COMMIT}/data/locales/en/strings.json"

BULLET = "\u2022"

# Unit lines we expose in the tech tree and counter logic.
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


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:  # noqa: S310
        return json.load(resp)


def normalize(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"‹[^‹›]*›", "", s)
    return s


def collapse(s: str) -> str:
    return " ".join(s.split())


def split_lines(raw: str) -> list[str]:
    text = normalize(raw)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def build_name_maps(strings: dict[str, str]):
    """Map unit/tech names to their official descriptions from strings.json."""
    unit_help: dict[str, str] = {}
    tech_help: dict[str, str] = {}
    for val in strings.values():
        if not isinstance(val, str):
            continue
        val = normalize(val)
        m = re.search(r"Create\s+([^()]+?)\s*\(\s*[^)]*\)\s*(.+)", val, re.I)
        if m:
            name = m.group(1).strip()
            desc = m.group(2).strip()
            unit_help.setdefault(name, desc)
        m = re.search(r"Research\s+([^()]+?)\s*\(\s*[^)]*\)\s*(.+)", val, re.I)
        if m:
            name = m.group(1).strip()
            desc = m.group(2).strip()
            tech_help.setdefault(name, desc)
    return unit_help, tech_help


def parse_help(raw: str, unit_help: dict[str, str], tech_help: dict[str, str]) -> dict:
    text = normalize(raw)
    lines = split_lines(raw)

    type_label = collapse(lines[0]) if lines else ""

    # Split the text into labeled blocks.
    def after_label(label: str) -> str:
        pat = re.compile(re.escape(label) + r"\s*:?\s*(.*)$", re.S)
        m = pat.search(text)
        return m.group(1).strip() if m else ""

    rest = after_label(type_label)

    def find_label(label: str) -> int:
        m = re.search(r"\b" + re.escape(label) + r"s?:", rest, re.I)
        return m.start() if m else -1

    uu_start = find_label("Unique Unit")
    ut_start = find_label("Unique Tech")
    tb_start = find_label("Team Bonus")

    bonus_block = rest[:uu_start] if uu_start != -1 else rest
    bonuses = [collapse(ln[1:]) for ln in bonus_block.splitlines() if ln.strip().startswith(BULLET)]

    uu_block = rest[uu_start:ut_start] if uu_start != -1 and ut_start != -1 else ""
    ut_block = rest[ut_start:tb_start] if ut_start != -1 and tb_start != -1 else ""
    tb_block = rest[tb_start:] if tb_start != -1 else ""

    # Unique units
    unique_units: list[dict] = []
    uu_body = re.sub(r"^Unique Units?\s*:?\s*", "", uu_block, flags=re.I).strip()
    for part in uu_body.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(.+?)\s*\(([^)]+)\)", part)
        name = collapse(m.group(1)) if m else collapse(part)
        kind = collapse(m.group(2)) if m else ""
        desc = collapse(unit_help.get(name, ""))
        unique_units.append({"name": name, "kind": kind, "desc": desc})

    # Unique techs
    unique_techs: list[dict] = []
    ut_body = re.sub(r"^Unique Techs?\s*:?\s*", "", ut_block, flags=re.I).strip()
    for ln in ut_body.splitlines():
        ln = ln.strip()
        if not ln.startswith(BULLET):
            continue
        ln = ln[1:].strip()
        m = re.match(r"(.+?)\s*\(([^)]+)\)", ln)
        name = collapse(m.group(1)) if m else collapse(ln)
        desc = collapse(m.group(2)) if m else collapse(tech_help.get(name, ""))
        age = "Castle" if len(unique_techs) == 0 else "Imperial"
        unique_techs.append({"name": name, "age": age, "desc": desc})

    team_bonus = collapse(re.sub(r"^Team Bonus\s*:?\s*", "", tb_block, flags=re.I))

    return {
        "type_label": type_label,
        "bonuses": bonuses,
        "team_bonus": team_bonus,
        "unique_units": unique_units,
        "unique_techs": unique_techs,
    }


def aocref_dataset() -> dict:
    path = Path(aocref.__file__).parent / "data" / "datasets" / "100.json"
    return json.loads(path.read_text(encoding="utf-8"))


def civ_slug(name: str) -> str:
    # Mirror record_header logic without importing the whole module.
    return {"Maya": "mayans"}.get(name, name.lower().replace(" ", ""))


def main() -> None:
    ds = aocref_dataset()
    object_name = ds["objects"].get
    tech_name = ds["technologies"].get

    data = fetch_json(DATA_URL)
    strings = fetch_json(STRINGS_URL)
    unit_help, tech_help = build_name_maps(strings)

    aoe_units = data["data"]["Unit"]
    aoe_techs = data["data"]["Tech"]
    aoe_buildings = data["data"]["Building"]
    unit_upgrades = data["data"]["unit_upgrades"]

    # Build a quick name -> list of ids index for the aoe2techtree ids.
    name_to_ids: dict[str, list[int]] = {}
    for uid_str, u in aoe_units.items():
        uid = int(uid_str)
        name = object_name(str(uid)) or ""
        if not name:
            # Fall back to display string if aocref misses it.
            name = normalize(strings.get(str(u.get("LanguageNameId")), ""))
        if name:
            name_to_ids.setdefault(name, []).append(uid)

    units_out: dict[str, dict] = {}
    for uid_str, u in aoe_units.items():
        uid = int(uid_str)
        name = object_name(str(uid))
        if not name:
            name = normalize(strings.get(str(u.get("LanguageNameId")), ""))
        units_out[uid_str] = {"name": name or u["internal_name"], "cost": u.get("Cost", {})}

    techs_out: dict[str, dict] = {}
    for tid_str, t in aoe_techs.items():
        tid = int(tid_str)
        name = tech_name(str(tid)) or normalize(strings.get(str(t.get("LanguageNameId")), ""))
        techs_out[tid_str] = {"name": name or t["internal_name"], "cost": t.get("Cost", {})}

    civs_out: dict[str, dict] = {}
    civ_meta: dict[str, dict] = {}

    for civ_name, civ_data in data["civs"].items():
        slug = civ_slug(civ_name)
        civ_units = set(civ_data["Unit"])
        civ_techs = set(civ_data["Tech"])
        civ_buildings = set(civ_data["Building"])

        unit_lines: dict[str, list[str]] = {}
        for base_name, tiers in UNIT_LINES.items():
            chain = []
            for tier_name in tiers:
                for uid in name_to_ids.get(tier_name, []):
                    if uid in civ_units:
                        chain.append(tier_name)
                        break
            if chain:
                unit_lines[base_name] = chain

        civs_out[slug] = {
            "name": civ_name,
            "units": sorted(civ_units),
            "techs": sorted(civ_techs),
            "buildings": sorted(civ_buildings),
            "unit_lines": unit_lines,
        }

        help_text = strings.get(str(civ_data["help_string_id"]), "")
        parsed = parse_help(help_text, unit_help, tech_help)
        civ_meta[slug] = {
            "name": civ_name,
            "type_label": parsed["type_label"],
            "bonuses": parsed["bonuses"],
            "team_bonus": parsed["team_bonus"],
            "unique_units": parsed["unique_units"],
            "unique_techs": parsed["unique_techs"],
            "playstyle_tags": [],
            "unit_focus": [],
            "ideal_comp": "",
            "watch_out": "",
        }

    techtrees = {
        "patch": str(data.get("patch", "")),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "upstream_commit": COMMIT,
        "civs": civs_out,
        "units": units_out,
        "techs": techs_out,
        "unit_upgrades": unit_upgrades,
    }

    (OUT_DIR / "techtrees.json").write_text(json.dumps(techtrees, indent=2), encoding="utf-8")
    (OUT_DIR / "civ_meta.json").write_text(json.dumps(civ_meta, indent=2), encoding="utf-8")

    print(f"Wrote {OUT_DIR / 'techtrees.json'} ({len(civs_out)} civs)")
    print(f"Wrote {OUT_DIR / 'civ_meta.json'}")


if __name__ == "__main__":
    main()
