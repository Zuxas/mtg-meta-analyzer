"""Verify oracle text for the cards needed to update McNamara's Looting list."""
import sys, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
db = m.CardDB()

def show(name):
    c = db.get(name)
    if not c:
        print(f"\n[NOT FOUND] {name}")
        return
    print(f"\n{name}  {c.get('mana_cost','?')}  cmc={c.get('cmc')}")
    print(f"  {c.get('type_line','?')}", end='')
    if c.get('power'):
        print(f"  {c.get('power')}/{c.get('toughness')}", end='')
    print(f"  [{c.get('set','?')}]")
    for line in (c.get('oracle_text') or '').split('\n'):
        print(f"  {line}")

# The two cards the user specifically asked about
print("=" * 80)
print("USER-CALLED-OUT CARDS")
print("=" * 80)
show("Sear")
show("Spell Snare")

# Current meta threats McNamara's pre-TLA deck doesn't address
print()
print("=" * 80)
print("POST-McNAMARA META THREATS (sets: TLA, TMNT, ECL, SOS)")
print("=" * 80)

# UW Tempo / Prison cards (none of these existed yet for McNamara)
print("\n--- UW TEMPO PIECES (TLA + SOS) ---")
for c in ["Aven Interrupter", "Aang, Swift Savior", "High Noon",
          "Voice of Victory", "Floodpits Drowner", "Avatar's Wrath",
          "Skycoach Conductor", "Airbender Ascension"]:
    show(c)

# Prowess threats (mostly TMNT/ECL/SOS)
print("\n--- PROWESS UPGRADES ---")
for c in ["Slickshot Show-Off", "Cori-Steel Cutter", "Eddymurk Crab",
          "Flow State", "Stock Up", "Sleight of Hand"]:
    show(c)

# Mono-Green Landfall pieces (TLA-era, post-McNamara)
print("\n--- LANDFALL PIECES (TLA) ---")
for c in ["Sapling Nursery", "Earthbender Ascension", "Icetill Explorer",
          "Mightform Harmonizer", "Sazh's Chocobo", "Meltstrider's Resolve",
          "Esper Origins", "Ba Sing Se", "Petrified Hamlet"]:
    show(c)

# Looting-relevant new cards from recent sets
print("\n--- POSSIBLE LOOTING UPGRADES (recent sets) ---")
for c in ["Annul", "Flashfreeze", "Detect Intrusion", "Belion, the Parched",
          "Get Out", "Ral, Crackling Wit", "Iroh's Demonstration",
          "Broadside Barrage", "Fire Magic", "Chandra, Spark Hunter",
          "Pyroclasm", "Slagstorm", "Disdainful Stroke", "Negate",
          "Spell Pierce", "Wan Shi Tong, Librarian"]:
    show(c)
