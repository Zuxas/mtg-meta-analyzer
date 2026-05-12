"""
Audit the proposed meta-fighting Looting build:
- Verify oracle text for new cards (Mako question, Detect Intrusion, Belion, Iroh's Demo, Roaring Furnace, Ruinous Rampage)
- Compare original vs new MAIN/SB lists
- Check what each new card adds vs what it cuts
"""
import sys, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
card_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card_db)
db = card_db.CardDB()

def show(name):
    c = db.get(name)
    if not c:
        print(f"\n[NOT FOUND] {name}")
        return
    print(f"\n{name}  {c.get('mana_cost','?')}  cmc={c.get('cmc')}")
    print(f"  {c.get('type_line','?')}", end='')
    if c.get('power'):
        print(f"  {c.get('power')}/{c.get('toughness')}", end='')
    print()
    for line in (c.get('oracle_text') or '').split('\n'):
        print(f"  {line}")

print("=" * 80)
print("MAKO QUESTION — Marauding Mako vs Tiger-Seal")
print("=" * 80)
show("Marauding Mako")
show("Tiger-Seal")

print()
print("=" * 80)
print("NEW MAIN CARDS")
print("=" * 80)
show("Winternight Stories")
show("Abrade")

print()
print("=" * 80)
print("NEW SB CARDS")
print("=" * 80)
show("Detect Intrusion")
show("Belion, the Parched")
show("Iroh's Demonstration")
show("Roaring Furnace // Steaming Sauna")
show("Ruinous Rampage")
show("Get Out")

print()
print("=" * 80)
print("UPGRADED REMOVAL OPTIONS in current Standard (verify cmc/effect)")
print("=" * 80)
for c in ["Lightning Helix", "Searing Light", "Galvanic Discharge",
          "Burst Lightning", "Lightning Strike", "Cut Down", "Fire Magic",
          "Combustion Technique", "Slagstorm", "Sunfall", "Anguished Unmaking"]:
    show(c)
