"""
Did the Cub shell actually get faster between Dec 2025 and Feb 2026?
Approach: look at the deck composition shift, not theory.
  - What cards entered/left the Cub shell at each transition
  - Were the new cards faster/slower than the ones they replaced
  - Verify oracle text of the key new cards to confirm speed hypothesis
"""
import sys, sqlite3, importlib.util
from datetime import datetime
from collections import Counter, defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')

spec = importlib.util.spec_from_file_location('card_db', str(ROOT.parent / 'mtg-sim' / 'engine' / 'card_db.py'))
card_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card_db)
db = card_db.CardDB()

con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
cur = con.cursor()

def parse_date(s):
    try: return datetime.strptime(s, '%d/%m/%y')
    except:
        try: return datetime.strptime(s, '%Y-%m-%d')
        except: return datetime.min

# Pull all Badgermole Cub decks, separated into pre-Looting-death (Nov-Dec 2025)
# and post-Looting-death (Feb-Mar 2026) windows
cur.execute("""
    SELECT d.id, d.archetype, e.date
    FROM decks d JOIN events e ON d.event_id = e.id
    WHERE d.id IN (
        SELECT dc.deck_id FROM deck_cards dc
        JOIN cards c ON dc.card_id = c.id
        WHERE c.name = 'Badgermole Cub' AND dc.is_sideboard = 0 AND dc.quantity >= 2
    )
    AND LOWER(e.format) = 'standard'
""")

pre_ids = []   # Nov-Dec 2025
post_ids = []  # Feb-Mar 2026
for did, arch, dstr in cur.fetchall():
    d = parse_date(dstr)
    if d == datetime.min: continue
    if datetime(2025,11,1) <= d <= datetime(2025,12,31):
        pre_ids.append(did)
    elif datetime(2026,2,1) <= d <= datetime(2026,3,31):
        post_ids.append(did)

print(f"Pre-shift (Nov-Dec 2025) Cub decks:  {len(pre_ids)}")
print(f"Post-shift (Feb-Mar 2026) Cub decks: {len(post_ids)}")

def card_freq(deck_ids):
    """Return {card_name: (n_decks_running, total_copies)} for these decks."""
    if not deck_ids: return {}
    placeholders = ','.join('?' * len(deck_ids))
    cur.execute(f"""
        SELECT c.name, COUNT(DISTINCT dc.deck_id), SUM(dc.quantity)
        FROM deck_cards dc JOIN cards c ON dc.card_id = c.id
        WHERE dc.deck_id IN ({placeholders}) AND dc.is_sideboard = 0
        GROUP BY c.name
    """, deck_ids)
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}

pre_freq = card_freq(pre_ids)
post_freq = card_freq(post_ids)

# Compute "play rate" = decks running it / total decks in window
pre_total = len(pre_ids)
post_total = len(post_ids)

# Cards that became significantly MORE popular (gained 30+ pct points)
gained = []
lost = []
for cname in set(pre_freq) | set(post_freq):
    pre_pct = pre_freq.get(cname, (0,0))[0] / pre_total * 100 if pre_total else 0
    post_pct = post_freq.get(cname, (0,0))[0] / post_total * 100 if post_total else 0
    delta = post_pct - pre_pct
    if delta >= 30:
        gained.append((cname, pre_pct, post_pct, delta))
    elif delta <= -30:
        lost.append((cname, pre_pct, post_pct, delta))

print()
print("=" * 90)
print("CARDS GAINED in Cub shell (post-shift minus pre-shift play rate, +30pp or more)")
print("=" * 90)
gained.sort(key=lambda x: -x[3])
for cname, pre, post, delta in gained:
    card = db.get(cname)
    cost = card.get('mana_cost', '?') if card else '?'
    cmc = card.get('cmc', '?') if card else '?'
    tl = card.get('type_line', '?') if card else '?'
    print(f"  +{delta:>5.1f}pp  {pre:>5.1f}%->{post:>5.1f}%  {cname:<28s}  {cost:<10s} cmc={cmc}  {tl}")

print()
print("=" * 90)
print("CARDS LOST from Cub shell (-30pp or more)")
print("=" * 90)
lost.sort(key=lambda x: x[3])
for cname, pre, post, delta in lost:
    card = db.get(cname)
    cost = card.get('mana_cost', '?') if card else '?'
    cmc = card.get('cmc', '?') if card else '?'
    tl = card.get('type_line', '?') if card else '?'
    print(f"  {delta:>+6.1f}pp  {pre:>5.1f}%->{post:>5.1f}%  {cname:<28s}  {cost:<10s} cmc={cmc}  {tl}")

# Curve comparison: average CMC of nonland mainboard cards
def avg_curve(deck_ids):
    if not deck_ids: return None
    total_cmc = 0
    total_count = 0
    placeholders = ','.join('?' * len(deck_ids))
    cur.execute(f"""
        SELECT c.name, dc.quantity
        FROM deck_cards dc JOIN cards c ON dc.card_id = c.id
        WHERE dc.deck_id IN ({placeholders}) AND dc.is_sideboard = 0
    """, deck_ids)
    for cname, qty in cur.fetchall():
        card = db.get(cname)
        if not card: continue
        tl = card.get('type_line', '') or ''
        if 'Land' in tl: continue
        try: cmc = float(card.get('cmc', 0))
        except: cmc = 0
        total_cmc += cmc * qty
        total_count += qty
    return total_cmc / total_count if total_count else 0

pre_curve = avg_curve(pre_ids)
post_curve = avg_curve(post_ids)
print()
print("=" * 90)
print("MANA CURVE shift (avg CMC of nonland mainboard)")
print("=" * 90)
print(f"  Pre  (Nov-Dec 2025):  avg cmc = {pre_curve:.2f}")
print(f"  Post (Feb-Mar 2026):  avg cmc = {post_curve:.2f}")
print(f"  Delta:                {post_curve - pre_curve:+.2f}")

# Count cheap threats (cmc 1-2) per deck
def cheap_threat_density(deck_ids):
    """Avg # of cmc 1-2 creatures/permanents per deck."""
    if not deck_ids: return 0
    placeholders = ','.join('?' * len(deck_ids))
    total = 0
    cur.execute(f"""
        SELECT c.name, dc.quantity, dc.deck_id
        FROM deck_cards dc JOIN cards c ON dc.card_id = c.id
        WHERE dc.deck_id IN ({placeholders}) AND dc.is_sideboard = 0
    """, deck_ids)
    for cname, qty, did in cur.fetchall():
        card = db.get(cname)
        if not card: continue
        try: cmc = float(card.get('cmc', 0))
        except: cmc = 0
        tl = card.get('type_line', '') or ''
        if 'Land' in tl: continue
        if 1 <= cmc <= 2:
            total += qty
    return total / len(deck_ids)

print()
print("=" * 90)
print("Cheap threat density (avg # of 1-2 CMC nonland cards per deck)")
print("=" * 90)
print(f"  Pre  (Nov-Dec 2025):  {cheap_threat_density(pre_ids):.2f}")
print(f"  Post (Feb-Mar 2026):  {cheap_threat_density(post_ids):.2f}")

# Pull oracle text for the BIG GAINS so we can see if they're faster/more threatening
print()
print("=" * 90)
print("Oracle text for top GAINED cards (verify speed hypothesis)")
print("=" * 90)
for cname, _, _, _ in gained[:8]:
    card = db.get(cname)
    if not card: continue
    print(f"\n  {cname}  {card.get('mana_cost', '?')}  cmc={card.get('cmc')}")
    print(f"    {card.get('type_line', '?')}")
    if card.get('power'):
        print(f"    P/T: {card.get('power')}/{card.get('toughness')}")
    for line in (card.get('oracle_text') or '').split('\n'):
        print(f"    {line}")

con.close()
