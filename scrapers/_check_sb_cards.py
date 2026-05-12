"""Verify oracle text for SB flex slot decision."""
import sys, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

out_path = str(Path(__file__).parent / '_sb_cards.txt')
f = open(out_path, 'w', encoding='utf-8')

spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
db = m.CardDB()

def show(name):
    c = db.get(name)
    if not c:
        f.write(f"\n[NOT FOUND] {name}\n")
        return
    f.write(f"\n{name}  {c.get('mana_cost','?')}  cmc={c.get('cmc')}  set={c.get('set','?')}\n")
    f.write(f"  Type: {c.get('type_line','?')}")
    if c.get('power'):
        f.write(f"   P/T: {c.get('power')}/{c.get('toughness')}")
    if c.get('loyalty'):
        f.write(f"   Loyalty: {c.get('loyalty')}")
    f.write("\n")
    for line in (c.get('oracle_text') or '').split('\n'):
        f.write(f"    {line}\n")

# The 3 flex SB slot options
for c in ["Tishana's Tidebinder", "Wan Shi Tong, Librarian",
          "Kaito, Cunning Infiltrator"]:
    show(c)

f.close()
print("done")
