"""Verify Aven Interrupter and Aang mechanics - the UW Tempo cards that punish Looting."""
import sys, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
card_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card_db)
db = card_db.CardDB()

for cname in ['Aven Interrupter', 'Aang, Swift Savior', 'High Noon', 'Voice of Victory', 'Floodpits Drowner', 'Avatar\'s Wrath']:
    card = db.get(cname)
    if not card:
        print(f"\n[NOT FOUND] {cname}")
        continue
    print(f"\n{cname}  {card.get('mana_cost', '?')}")
    print(f"  Type: {card.get('type_line', '?')}")
    if card.get('power'):
        print(f"  P/T: {card.get('power')}/{card.get('toughness')}")
    for line in (card.get('oracle_text') or '').split('\n'):
        print(f"  {line}")
