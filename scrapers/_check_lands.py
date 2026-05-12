import sys, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
db = m.CardDB()

for c in ['Multiversal Passage', 'Riverpyre Verge', 'Roaring Furnace', 'Steaming Sauna', 'Spirebluff Canal']:
    card = db.get(c)
    if not card:
        print(f"\n[NOT FOUND] {c}")
        continue
    print(f"\n{c}")
    print(f"  Type: {card.get('type_line','?')}")
    for line in (card.get('oracle_text') or '').split('\n'):
        print(f"  {line}")
