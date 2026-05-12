"""Verify card mechanics for the Izzet Looting list using local Scryfall DB."""
import sys, os, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
# Load card_db.py directly to skip engine/__init__.py chain that pulls in 'requests'
spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
card_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card_db)
CardDB = card_db.CardDB

db = CardDB()
print()
print("=" * 80)

cards = [
    "Duelist of the Mind",
    "Fear of Missing Out",
    "Tiger-Seal",
    "Frostcliff Siege",
    "Quantum Riddler",
    "Winternight Stories",
    "Into the Flood Maw",
    "Stormchaser's Talent",
    "Boomerang Basics",
    "Torch the Tower",
    "Burst Lightning",
    "Spell Snare",
    "Ghost Vacuum",
]

for name in cards:
    card = db.get(name)
    if not card:
        print(f"\n[NOT FOUND] {name}\n")
        continue
    print(f"\n{name}")
    print(f"  Cost: {card.get('mana_cost', '?')}    CMC: {card.get('cmc', '?')}")
    print(f"  Type: {card.get('type_line', '?')}")
    pt = ''
    if card.get('power'):
        pt = f"  P/T: {card.get('power')}/{card.get('toughness')}"
    if pt: print(pt)
    print(f"  Oracle:")
    for line in (card.get('oracle_text') or '').split('\n'):
        print(f"    {line}")
