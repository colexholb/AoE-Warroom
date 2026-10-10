"""What to build against each unit. Hand-curated from common AoE2 counter knowledge.

Keys are the base unit names that appear in replays (a queue action for a Paladin is recorded
as "Knight"), so each entry covers the whole unit line. Counters name one unit per line too:
"Spearmen" means the spear line, "Militia line" the swordsmen, "Knights" the knight line.
"""

from __future__ import annotations

# unit -> counters, best first
UNIT_COUNTERS: dict[str, list[str]] = {
    # --- generic ranged
    "Archer": ["Skirmishers", "Mangonels", "Knights"],
    "Skirmisher": ["Knights", "Militia line", "Scorpions"],
    "Hand Cannoneer": ["Skirmishers", "Mangonels", "Knights"],
    "Cavalry Archer": ["Skirmishers", "Camel Archers / Genitours"],
    "Slinger": ["Knights", "Archers"],
    "Genitour": ["Knights", "Archers"],
    "Elephant Archer": ["Spearmen", "Monks", "Skirmishers"],
    # --- generic cavalry
    "Scout Cavalry": ["Spearmen", "Camels"],
    "Knight": ["Spearmen", "Camels", "Monks"],
    "Camel Rider": ["Spearmen", "Archers", "Militia line"],
    "Camel Scout": ["Spearmen", "Archers"],
    "Battle Elephant": ["Monks", "Spearmen"],
    "War Elephant": ["Monks", "Spearmen"],
    "Steppe Lancer": ["Spearmen", "Camels"],
    "Fire Lancer": ["Spearmen", "Archers"],
    # --- generic infantry
    "Militia": ["Archers", "Scorpions", "Hand Cannoneers"],
    "Flemish Militia": ["Archers", "Scorpions", "Hand Cannoneers"],
    "Spearman": ["Archers", "Militia line", "Scorpions"],
    "Eagle Scout": ["Militia line", "Knights"],
    "Champi Scout": ["Militia line", "Knights"],
    # --- siege
    "Scorpion": ["Knights", "Mangonels"],
    "Mangonel": ["Knights", "Light Cavalry"],
    "Battering Ram": ["Militia line", "Knights"],
    "Bombard Cannon": ["Knights", "Light Cavalry"],
    "Trebuchet": ["Knights", "Light Cavalry"],
    "Traction Trebuchet": ["Knights", "Light Cavalry"],
    "Mounted Trebuchet": ["Knights", "Light Cavalry"],
    "Organ Gun": ["Knights", "Mangonels"],
    "Ballista Elephant": ["Spearmen", "Monks", "Mangonels"],
    "Rocket Cart": ["Knights", "Light Cavalry"],
    "Armored Elephant": ["Spearmen", "Militia line"],
    "Siege Elephant": ["Spearmen", "Militia line"],
    "Petard": ["Archers", "Light Cavalry"],
    "Siege Tower": ["Knights", "Militia line"],
    # --- monks
    "Monk": ["Light Cavalry", "Eagles"],
    "Missionary": ["Light Cavalry", "Eagles"],
    "Warrior Priest": ["Archers", "Light Cavalry"],
    # --- unique ranged
    "Chu Ko Nu": ["Skirmishers", "Mangonels"],
    "Longbowman": ["Skirmishers", "Mangonels", "Knights"],
    "Mangudai": ["Skirmishers", "Camel Archers / Genitours"],
    "Janissary": ["Archers", "Mangonels", "Huskarls"],
    "Genoese Crossbowman": ["Skirmishers", "Mangonels", "Militia line"],
    "Conquistador": ["Skirmishers", "Camels"],
    "Camel Archer": ["Skirmishers", "Genitours"],
    "Rattan Archer": ["Mangonels", "Militia line", "Eagles"],
    "Mounted Crossbowman": ["Skirmishers", "Camels"],
    "Gbeto": ["Archers", "Knights"],
    "War Wagon": ["Camels", "Militia line", "Bombard Cannons"],
    "Hussite Wagon": ["Militia line", "Mangonels", "Knights"],
    "Bolas Rider": ["Skirmishers", "Camels"],
    "Composite Bowman": ["Knights", "Mangonels"],
    "Throwing Axeman": ["Archers", "Knights"],
    "Chakram Thrower": ["Archers", "Knights"],
    "Grenadier": ["Knights", "Skirmishers"],
    "Plumed Archer": ["Skirmishers", "Mangonels", "Eagles"],
    "Blackwood Archer": ["Skirmishers", "Mangonels", "Knights"],
    "Ratha": ["Skirmishers", "Spearmen"],
    "Fire Archer": ["Skirmishers", "Mangonels", "Knights"],
    "Kipchak": ["Skirmishers", "Camel Archers / Genitours"],
    "Xianbei Raider": ["Skirmishers", "Camels"],
    "War Chariot": ["Skirmishers", "Spearmen"],
    "Arambai": ["Skirmishers", "Archers"],
    # --- unique cavalry
    "Magyar Huszar": ["Spearmen", "Camels"],
    "Boyar": ["Spearmen", "Camels", "Monks"],
    "Tarkan": ["Spearmen", "Camels", "Archers"],
    "Monaspa": ["Spearmen", "Camels"],
    "Mameluke": ["Militia line", "Archers"],
    "Cataphract": ["Militia line", "Archers", "Monks"],
    "Leitis": ["Camels", "Spearmen", "Monks"],
    "Shrivamsha Rider": ["Spearmen", "Camels"],
    "Iron Pagoda": ["Spearmen", "Monks"],
    "Konnik": ["Spearmen", "Camels"],
    "Keshik": ["Spearmen", "Camels"],
    "Tiger Cavalry": ["Spearmen", "Camels"],
    "Centurion": ["Spearmen", "Camels"],
    "Coustillier": ["Spearmen", "Camels"],
    "Jarl": ["Spearmen", "Camels"],
    "Winged Hussar": ["Spearmen", "Camels"],
    "Savar": ["Spearmen", "Camels"],
    "Lancer": ["Spearmen", "Camels"],
    # --- unique infantry
    "Huskarl": ["Knights", "Militia line", "Hand Cannoneers"],
    "Varangian Guard": ["Knights", "Militia line"],
    "Jomsviking": ["Archers", "Knights"],
    "Samurai": ["Archers", "Knights"],
    "Condottiero": ["Archers", "Knights"],
    "Kamayuk": ["Archers", "Militia line"],
    "Woad Raider": ["Archers", "Knights"],
    "Shotel Warrior": ["Archers", "Knights"],
    "Teutonic Knight": ["Archers", "Monks", "Hand Cannoneers"],
    "Obuch": ["Archers", "Knights"],
    "Berserk": ["Archers", "Knights"],
    "Jaguar Warrior": ["Archers", "Knights"],
    "Karambit Warrior": ["Archers", "Mangonels", "Scorpions"],
    "Ghulam": ["Knights", "Militia line"],
    "Serjeant": ["Archers", "Knights"],
    "Urumi Swordsman": ["Archers", "Knights"],
    "Temple Guard": ["Archers", "Knights"],
    "Hearth Troop": ["Archers", "Knights"],
    "White Feather Guard": ["Archers", "Knights"],
    "Liao Dao": ["Archers", "Knights"],
    "Guecha Warrior": ["Archers", "Knights"],
    "Kona": ["Archers", "Knights"],
    "Dismounted Konnik": ["Archers", "Knights"],
    "Legionary": ["Archers", "Knights"],
    "Jian Swordsman": ["Archers", "Knights"],
}

# Fallback when a unit isn't in the table (new DLC units etc.).
GROUP_COUNTERS: dict[str, list[str]] = {
    "ranged": ["Skirmishers", "Mangonels", "Knights"],
    "cavalry": ["Spearmen", "Camels", "Monks"],
    "infantry": ["Archers", "Scorpions"],
    "siege": ["Knights", "Light Cavalry"],
    "monk": ["Light Cavalry", "Eagles"],
    "navy": ["Galleys", "Fire Galleys"],
}


def counters_for(unit_name: str, group: str) -> list[str]:
    return UNIT_COUNTERS.get(unit_name) or GROUP_COUNTERS.get(group, [])


def combined_counters(units: list[tuple[str, str, float]], limit: int = 2) -> list[str]:
    """Best answers to a mix of (unit name, group, share): counters that hit more of the mix win."""
    score: dict[str, float] = {}
    for name, group, share in units:
        for rank, counter in enumerate(counters_for(name, group)):
            score[counter] = score.get(counter, 0) + share * (1.0 - 0.3 * rank)
    return [c for c, _ in sorted(score.items(), key=lambda kv: -kv[1])[:limit]]
