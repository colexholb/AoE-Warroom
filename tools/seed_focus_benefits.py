#!/usr/bin/env python3
"""Write/refresh `focus_benefits` for every civ in backend/app/data/civ_meta.json.

For each civ, sets a boolean per unit-focus family indicating whether at least
one bonus OR unique technology explicitly benefits that focus family.

This is Gate 1 of the strict-3-gates Explore filter (the other two — full unit
line tier and tier-1/2 blacksmith upgrades — are derived from `techtrees.json`
at query time in `meta.py`).

Run after fetch_techtree.py and seed_civ_meta.py, then hand-review and edit
backend/app/data/civ_meta.json for any patches that change which civs specialize
in what.

    .venv\\Scripts\\python tools\\seed_focus_benefits.py

To regenerate only one civ:

    .venv\\Scripts\\python tools\\seed_focus_benefits.py --only britons
"""
from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "app" / "data"

# Hand-reviewed mapping for all 56 DE civs as of 2026-10-16.
# True iff at least one bonus OR unique tech explicitly benefits that focus family.
# See aoe2-meta-data.md Known Edge Cases / "focus_benefits" for the per-civ reasoning.
FOCUS_BENEFITS: dict[str, dict[str, bool]] = {
    "armenians":   {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": True,  "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": True},
    "aztecs":      {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": True,  "gunpowder": False, "camel": False, "elephant": False, "eagle": True,  "naval": False},
    "bengalis":    {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": False, "monk": True,  "gunpowder": False, "camel": False, "elephant": True,  "eagle": False, "naval": True},
    "berbers":     {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": True,  "elephant": False, "eagle": False, "naval": True},
    "bohemians":   {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": False, "siege": True,  "monk": False, "gunpowder": True,  "camel": False, "elephant": False, "eagle": False, "naval": False},
    "britons":     {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": False, "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "bulgarians":  {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "burgundians": {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "burmese":     {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": True,  "siege": False, "monk": True,  "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "byzantines":  {"archer": True,  "cavalry archer": False, "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": True,  "elephant": False, "eagle": False, "naval": True},
    "celts":       {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "chinese":     {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": False, "siege": False, "monk": False, "gunpowder": True,  "camel": False, "elephant": False, "eagle": False, "naval": True},
    "cumans":      {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "danes":       {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": True},
    "dravidians":  {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": True},
    "ethiopians":  {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "franks":      {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "georgians":   {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "goths":       {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "gurjaras":    {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": True,  "elephant": False, "eagle": False, "naval": False},
    "hindustanis": {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": True,  "camel": True,  "elephant": False, "eagle": False, "naval": False},
    "huns":        {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "incas":       {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": True,  "naval": False},
    "italians":    {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": False, "siege": False, "monk": False, "gunpowder": True,  "camel": False, "elephant": False, "eagle": False, "naval": True},
    "japanese":    {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "jurchens":    {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": True,  "monk": False, "gunpowder": True,  "camel": False, "elephant": False, "eagle": False, "naval": False},
    "khitans":     {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": True,  "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "khmer":       {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": False, "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": True,  "eagle": False, "naval": False},
    "koreans":     {"archer": True,  "cavalry archer": True,  "cavalry": False, "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": True},
    "lithuanians": {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": False, "siege": False, "monk": True,  "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "magyars":     {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "malay":       {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": True},
    "malians":     {"archer": True,  "cavalry archer": False, "cavalry": True,  "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "mapuche":     {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "mayans":      {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": True,  "naval": False},
    "mongols":     {"archer": True,  "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "muisca":      {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": True,  "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "persians":    {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": True,  "eagle": False, "naval": False},
    "poles":       {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "portuguese":  {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": False, "siege": True,  "monk": False, "gunpowder": True,  "camel": False, "elephant": False, "eagle": False, "naval": True},
    "romans":      {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": True},
    "saracens":    {"archer": True,  "cavalry archer": False, "cavalry": True,  "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": True,  "elephant": False, "eagle": False, "naval": True},
    "saxons":      {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "shu":         {"archer": True,  "cavalry archer": True,  "cavalry": False, "infantry": True,  "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "sicilians":   {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "slavs":       {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "spanish":     {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": False, "siege": False, "monk": True,  "gunpowder": True,  "camel": False, "elephant": False, "eagle": False, "naval": False},
    "tatars":      {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": True,  "monk": False, "gunpowder": False, "camel": True,  "elephant": False, "eagle": False, "naval": False},
    "teutons":     {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": True,  "siege": False, "monk": True,  "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "tupi":        {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "turks":       {"archer": False, "cavalry archer": False, "cavalry": False, "infantry": False, "siege": True,  "monk": False, "gunpowder": True,  "camel": False, "elephant": False, "eagle": False, "naval": False},
    "varangians":  {"archer": False, "cavalry archer": False, "cavalry": True,  "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": True},
    "vietnamese":  {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": False, "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": True,  "eagle": False, "naval": False},
    "vikings":     {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": True},
    "wei":         {"archer": False, "cavalry archer": True,  "cavalry": True,  "infantry": False, "siege": True,  "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": False},
    "wu":          {"archer": True,  "cavalry archer": False, "cavalry": False, "infantry": True,  "siege": False, "monk": False, "gunpowder": False, "camel": False, "elephant": False, "eagle": False, "naval": True},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Only update the listed civ slugs (space-separated)")
    args = parser.parse_args()
    only = set(args.only.split()) if args.only else None

    path = DATA_DIR / "civ_meta.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=OrderedDict)

    missing = [slug for slug in data if slug not in FOCUS_BENEFITS]
    if missing:
        raise SystemExit(f"Missing focus_benefits entries for: {missing}")

    written = 0
    for slug, civ in data.items():
        if only and slug not in only:
            continue
        civ["focus_benefits"] = FOCUS_BENEFITS[slug]
        written += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote focus_benefits for {written} civs")


if __name__ == "__main__":
    main()
