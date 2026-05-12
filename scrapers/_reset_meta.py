"""Reset meta tables and re-pull. Run once after schema change."""
import sys, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(str(ROOT / 'data' / 'mtg_meta.db'))
con.execute("PRAGMA foreign_keys = ON")
cur = con.cursor()
cur.execute("DROP VIEW IF EXISTS v_untapped_meta_skill_curve")
cur.execute("DROP VIEW IF EXISTS v_untapped_meta_latest")
cur.execute("DROP TABLE IF EXISTS untapped_meta_archetypes")
cur.execute("DROP TABLE IF EXISTS untapped_meta_snapshots")
cur.execute("DROP TABLE IF EXISTS untapped_meta_periods")
con.commit()
con.close()
print("[OK] Dropped meta tables. Now run untapped_meta_scraper.py again.")
