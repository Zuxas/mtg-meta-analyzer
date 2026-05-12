"""Verify every card I need to reason about for the SB plans doc.
Loads card_db ONCE, dumps everything to a single file."""
import sys, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

out_path = str(Path(__file__).parent / '_verified_sb_cards.txt')
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
    f.write(f"\n{name}  cost={c.get('mana_cost','?')}  cmc={c.get('cmc')}  set={c.get('set','?')}\n")
    f.write(f"  Type: {c.get('type_line','?')}")
    if c.get('power'):
        f.write(f"   P/T: {c.get('power')}/{c.get('toughness')}")
    if c.get('loyalty'):
        f.write(f"   Loy: {c.get('loyalty')}")
    f.write(f"   banned_standard={c.get('banned_in_standard', '?')}\n")
    for line in (c.get('oracle_text') or '').split('\n'):
        f.write(f"    {line}\n")

# ============ OUR DECK ============
f.write("=" * 80 + "\nOUR DECK\n" + "=" * 80 + "\n")
for c in ["Duelist of the Mind", "Fear of Missing Out", "Tiger-Seal",
          "Quantum Riddler", "Stormchaser's Talent", "Boomerang Basics",
          "Torch the Tower", "Into the Flood Maw", "Burst Lightning",
          "Spell Snare", "Frostcliff Siege", "Ghost Vacuum",
          "Steam Vents", "Spirebluff Canal", "Riverpyre Verge",
          "Multiversal Passage", "Agna Qel'a", "Starting Town",
          # SB
          "Pyroclasm", "Abrade", "Annul", "Flashfreeze", "Sear",
          "Disdainful Stroke", "Soul-Guide Lantern", "Tishana's Tidebinder"]:
    show(c)

# ============ OPPONENT CARDS BY MATCHUP ============
f.write("\n" + "=" * 80 + "\nIZZET LESSONS / MONUMENT\n" + "=" * 80 + "\n")
for c in ["Gran-Gran", "Artist's Talent", "Monument to Endurance",
          "Accumulate Wisdom", "Firebending Lesson", "Abandon Attachments",
          "Combustion Technique", "It'll Quench Ya!", "Iroh's Demonstration",
          "Three Steps Ahead", "Spider-Sense",
          "The Unagi of Kyoshi Island", "Ral, Crackling Wit"]:
    show(c)

f.write("\n" + "=" * 80 + "\nIZZET PROWESS (post-Cori-Steel)\n" + "=" * 80 + "\n")
for c in ["Slickshot Show-Off", "Cori-Steel Cutter",
          "Flow State", "Stock Up", "Opt", "Sleight of Hand",
          "Eddymurk Crab", "Roaring Furnace", "Steaming Sauna",
          "Roaring Furnace // Steaming Sauna",
          "Colorstorm Stallion", "Secret Identity"]:
    show(c)

f.write("\n" + "=" * 80 + "\nMONO-GREEN LANDFALL / SELESNYA LANDFALL\n" + "=" * 80 + "\n")
for c in ["Sapling Nursery", "Earthbender Ascension", "Icetill Explorer",
          "Mightform Harmonizer", "Sazh's Chocobo", "Badgermole Cub",
          "Llanowar Elves", "Bristly Bill, Spine Sower", "Mossborn Hydra",
          "Esper Origins", "Esper Origins // Summon: Esper Maduin",
          "Seam Rip", "Hunter's Talent", "Lumbering Worldwagon",
          "Sheltered by Ghosts", "Royal Treatment",
          "Fabled Passage", "Promising Vein", "Ba Sing Se"]:
    show(c)

f.write("\n" + "=" * 80 + "\nUW TEMPO\n" + "=" * 80 + "\n")
for c in ["Aven Interrupter", "Aang, Swift Savior", "High Noon",
          "Voice of Victory", "Floodpits Drowner", "Skycoach Conductor",
          "Avatar's Wrath", "Airbender Ascension", "Spell Pierce", "Negate"]:
    show(c)

f.write("\n" + "=" * 80 + "\nSULTAI REANIMATOR\n" + "=" * 80 + "\n")
for c in ["Bringer of the Last Gift", "Overlord of the Balemurk",
          "Superior Spider-Man", "Formidable Speaker", "Oblivious Bookworm",
          "Wistfulness", "Ardyn, the Usurper", "Craterhoof Behemoth",
          "Deceit", "Awaken the Honored Dead", "Bitter Triumph",
          "Analyze the Pollen", "Requiting Hex"]:
    show(c)

f.write("\n" + "=" * 80 + "\nJUND LEYLINE / GRUUL LEYLINE / MONO RED\n" + "=" * 80 + "\n")
for c in ["Leyline of Resonance", "Callous Sell-Sword",
          "Emberheart Challenger", "Frantic Scapegoat", "Stadium Headliner",
          "Full Bore", "Turn Inside Out", "Dreadmaw's Ire",
          "Might of the Meek", "Snakeskin Veil", "Questing Druid",
          "Fire Magic", "Pawpatch Recruit", "Felonious Rage",
          "Heritage Reclamation", "Monstrous Rage", "Heartfire Hero",
          "Screaming Nemesis"]:
    show(c)

f.write("\n" + "=" * 80 + "\nFLEX OPTIONS WE'VE DISCUSSED\n" + "=" * 80 + "\n")
for c in ["Wan Shi Tong, Librarian", "Kaito, Cunning Infiltrator",
          "Detect Intrusion", "Belion, the Parched", "Get Out",
          "Hydro-Man, Fluid Felon", "Winternight Stories",
          "Spider-Sense", "Broadside Barrage", "Fresh Start",
          "Chandra, Spark Hunter", "Ruinous Rampage"]:
    show(c)

f.close()
print("done")
