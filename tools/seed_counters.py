#!/usr/bin/env python3
"""Build backend/app/data/counters.json from the curated counters.py table."""

from __future__ import annotations

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.counters import GROUP_COUNTERS, UNIT_COUNTERS  # noqa: E402
from app.replay import UNIT_GROUPS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backend" / "app" / "data" / "counters.json"

# Map a unit name to its broad group for fallback counter advice.
NAME_TO_GROUP = {name: group for group, names in UNIT_GROUPS.items() for name in names}

# Extra civ-specific answers for the most-searched enemy units.
CIV_ANSWERS: dict[str, list[dict]] = {
    "Scorpion": [
        {"civ": "mongols", "answer": "Mangudai", "note": "outrange and hit-and-run"},
        {"civ": "mongols", "answer": "Siege Onager + Drill", "note": "Drill lets siege catch them"},
        {"civ": "*", "answer": "Bombard Cannon", "note": "outranges if it can sit still"},
    ],
    "Mangonel": [
        {"civ": "*", "answer": "Bombard Cannon", "note": "outranges Onagers"},
        {"civ": "britons", "answer": "Yeomen Longbowman", "note": "extra range kites Mangonels"},
    ],
    "Onager": [
        {"civ": "*", "answer": "Bombard Cannon", "note": "outranges and kills quickly"},
        {"civ": "mongols", "answer": "Siege Onager + Drill", "note": "faster trade if you have it too"},
    ],
    "Siege Onager": [
        {"civ": "*", "answer": "Bombard Cannon", "note": "outranges the Onager"},
        {"civ": "mongols", "answer": "Mangudai", "note": "outrange and micro down"},
    ],
    "Knight": [
        {"civ": "aztecs", "answer": "Monks", "note": "Aztec monks are especially strong"},
        {"civ": "byzantines", "answer": "Camel Riders", "note": "cheap anti-cavalry"},
        {"civ": "goths", "answer": "Huskarl", "note": "pierce armor shrugs off knights"},
    ],
    "Paladin": [
        {"civ": "*", "answer": "Halberdier", "note": "cost-efficient counter"},
        {"civ": "aztecs", "answer": "Monks", "note": "Monk + siege answers Paladin"},
        {"civ": "saracens", "answer": "Mameluke", "note": "ranged melee anti-cavalry"},
    ],
    "Arbalester": [
        {"civ": "goths", "answer": "Huskarl", "note": "pierce armor floods archers"},
        {"civ": "koreans", "answer": "War Wagon", "note": "tanky mounted archer"},
        {"civ": "britons", "answer": "Yeomen Longbowman", "note": "outrange enemy Arbalesters"},
    ],
    "Halberdier": [
        {"civ": "aztecs", "answer": "Jaguar Warrior", "note": "infantry bonus damage"},
        {"civ": "byzantines", "answer": "Cataphract", "note": "tramples infantry"},
        {"civ": "*", "answer": "Hand Cannoneer", "note": "melts massed Halberdiers"},
    ],
    "Hussar": [
        {"civ": "*", "answer": "Halberdier", "note": "spear line counters all scout-line"},
        {"civ": "*", "answer": "Camel Rider", "note": "fast anti-cavalry"},
    ],
    "Bombard Cannon": [
        {"civ": "*", "answer": "Hussar", "note": "snipes the cannon"},
        {"civ": "*", "answer": "Eagle Warrior", "note": "fast, high pierce armor"},
        {"civ": "huns", "answer": "Tarkan", "note": "high pierce armor anti-building cavalry"},
    ],
    "Monk": [
        {"civ": "*", "answer": "Light Cavalry", "note": "resistant to conversion"},
        {"civ": "*", "answer": "Eagle Warrior", "note": "conversion resistant"},
        {"civ": "aztecs", "answer": "Eagle Warrior", "note": "fast and monk-resistant"},
    ],
    "War Elephant": [
        {"civ": "*", "answer": "Halberdier", "note": "cheap counter"},
        {"civ": "*", "answer": "Monk", "note": "converts the expensive unit"},
        {"civ": "aztecs", "answer": "Halberdier + Monk", "note": "Aztec monks convert quickly"},
    ],
    "Teutonic Knight": [
        {"civ": "*", "answer": "Hand Cannoneer", "note": "ignores melee armor"},
        {"civ": "*", "answer": "Archers", "note": "kite the slow knight"},
        {"civ": "*", "answer": "Monks", "note": "conversion works despite resistance"},
    ],
    "Cavalry Archer": [
        {"civ": "*", "answer": "Elite Skirmisher", "note": "anti-archer ranged unit"},
        {"civ": "*", "answer": "Camel Rider", "note": "catches and kills"},
        {"civ": "mongols", "answer": "Mangudai", "note": "faster fire and mobility"},
    ],
    "Scout Cavalry": [
        {"civ": "*", "answer": "Spearman", "note": "classic counter"},
        {"civ": "*", "answer": "Camel Rider", "note": "cavalry trade"},
    ],
    "Archer": [
        {"civ": "*", "answer": "Skirmisher", "note": "anti-archer"},
        {"civ": "*", "answer": "Scout Cavalry", "note": "raids the Archery Range"},
    ],
    "Eagle Scout": [
        {"civ": "*", "answer": "Militia-line", "note": "infantry beats eagles"},
        {"civ": "*", "answer": "Knight", "note": "if your civ has it"},
    ],
    "Eagle Warrior": [
        {"civ": "*", "answer": "Militia-line", "note": "infantry beats eagles"},
        {"civ": "*", "answer": "Hand Cannoneer", "note": "high damage"},
    ],
    "Battle Elephant": [
        {"civ": "*", "answer": "Halberdier", "note": "bonus damage"},
        {"civ": "*", "answer": "Monk", "note": "convert the expensive elephant"},
    ],
    "Camel Rider": [
        {"civ": "*", "answer": "Spearman", "note": "spear line counters camels"},
        {"civ": "*", "answer": "Archers", "note": "kite from range"},
    ],
    "Militia": [
        {"civ": "*", "answer": "Archer", "note": "kite infantry"},
        {"civ": "*", "answer": "Scorpion", "note": "pass-through damage"},
    ],
    "Spearman": [
        {"civ": "*", "answer": "Archer", "note": "ranged units punish spears"},
        {"civ": "*", "answer": "Militia-line", "note": "swords beat spears"},
    ],
}


def main() -> None:
    data: dict[str, dict] = {}
    for name, counters in UNIT_COUNTERS.items():
        data[name] = {
            "generic": counters,
            "group": NAME_TO_GROUP.get(name),
            "civ_answers": CIV_ANSWERS.get(name, []),
        }

    OUT.write_text(json.dumps({"counters": data, "fallback": GROUP_COUNTERS}, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} ({len(data)} entries)")


if __name__ == "__main__":
    main()
