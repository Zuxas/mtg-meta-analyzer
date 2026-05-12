# Untapped.gg Data Pipeline

Public-data scrapers for `mtga.untapped.gg` that integrate with `mtg_meta.db`.
All endpoints used here are unauthenticated — no cookies, no session.

## Files

| Script | Purpose |
|---|---|
| `untapped_mythic_scraper.py` | Scrape mythic ladder leaderboard (top ~98 decks, snapshot per run) |
| `untapped_matchup_scraper.py` | Pull archetype-vs-archetype matchup matrix (showcase endpoint, Bo1 prev period only) |
| `untapped_meta_scraper.py` | Scrape per-rank archetype WR for ALL formats (Bo3 default) |
| `untapped_card_loader.py` | One-time / occasional pull of MTGA card db (grpid → name) |
| `untapped_replay_fetcher.py` | Fetch full game replays (raw MTGA logs) for short_ids in DB |
| `untapped_sideboard_extractor.py` | Diff multi-game replays → real Bo3 SB plans by archetype |
| `_verify_untapped.py` | Diagnostic: inspect leaderboard tables/views |
| `_verify_replays.py` | Diagnostic: inspect replay storage |
| `_analyze_replay_corpus.py` | Diagnostic: corpus stats (Bo1 vs Bo3, archetype breakdown) |
| `_check_card_schema.py` | Diagnostic: card db schema lookup |
| `_check_meta_wr.py` | Diagnostic: meta archetype WR sanity-check |
| `_show_meta_insights.py` | Diagnostic: top archetypes + skill curves + UW deep dive |

## Tables added to mtg_meta.db

```
untapped_snapshots          one row per mythic_scraper run
untapped_entries            per-(snapshot, short_id) ladder entry — has matches, WR, archetype tag
untapped_tags               archetype + theme tag dictionary, refreshed weekly
untapped_card_db            grpid → name + set + cmc + types
untapped_replays            index of fetched replays (file path + size, NOT the log)
untapped_sideboard_plans    one row per (replay, game-transition), with cards_in / cards_out
untapped_meta_periods       active meta periods (event_name + legal_sets) — Standard, Historic, etc
untapped_meta_snapshots     one row per meta_scraper format-pull
untapped_meta_archetypes    per-(snapshot, archetype, rank) WR / matches / tier_val

v_untapped_latest_archetypes        archetype rollup, latest mythic snapshot
v_untapped_latest_entries           flat per-player latest mythic snapshot
v_untapped_archetype_history        time-series across all mythic snapshots
v_untapped_replays_unfetched        short_ids in untapped_entries not yet replayed
v_untapped_replays_with_meta        replays + their leaderboard context
v_untapped_sideboard_plans_with_meta  SB plans + player/archetype context
v_untapped_meta_latest              archetype + rank for latest format-pull
untapped_matchup_snapshots  one row per matchup_scraper run
untapped_matchups           per-(snapshot, friendly, opponent) WR + match count

v_untapped_matchups_named   matchup matrix with friendly/opponent names resolved
```

## File storage

```
data\untapped\
    mythic_<stamp>.json        archive of each leaderboard pull
    tags_<stamp>.json          archive of tag pulls (occasional)
    archetype_summary.csv      latest archetype rollup
    leaderboard_decoded.csv    latest flat per-player table
    replays\
        <short_id>.json.gz     gzipped raw replay (~150 KB avg, ~1.3 MB raw)
```

## Workflow

### First-time setup
```powershell
cd <repo-root>
python scrapers\untapped_card_loader.py        # one-time, ~17 MB pull
python scrapers\untapped_mythic_scraper.py     # mythic top-98 leaderboard
python scrapers\untapped_meta_scraper.py       # all-format archetype rollup with WR by rank
python scrapers\untapped_replay_fetcher.py --all-unfetched
python scrapers\untapped_sideboard_extractor.py
```

### Daily refresh (after Task Scheduler runs the scrapers)
```powershell
python scrapers\untapped_mythic_scraper.py                   # snapshots add to time-series
python scrapers\untapped_meta_scraper.py                     # archetype WR refresh
python scrapers\untapped_replay_fetcher.py --all-unfetched   # only pulls new short_ids
python scrapers\untapped_sideboard_extractor.py              # idempotent re-extract
```

### Targeted analysis
```powershell
# All SB plans for one archetype
python scrapers\untapped_sideboard_extractor.py --archetype Azorius

# Meta breakdown for Standard Bo1 only
python scrapers\untapped_meta_scraper.py --format Ladder

# Standard Bo3 (no WR available, just match volume + tier_val)
python scrapers\untapped_meta_scraper.py --format Traditional_Ladder

# Last 7 days only (vs full meta period)
python scrapers\untapped_meta_scraper.py --last-7-days

# Pull replays only for one archetype
python scrapers\untapped_replay_fetcher.py --top 20 --archetype Mono-Green
```

## Endpoints used (all public, no auth)

```
GET  https://api.mtga.untapped.gg/api/v1/leaderboard/mythic
GET  https://api.mtga.untapped.gg/api/v1/tags
GET  https://api.mtga.untapped.gg/api/v1/upload-log/{short_id}
GET  https://api.mtga.untapped.gg/api/v1/meta-periods/active
GET  https://api.mtga.untapped.gg/api/v1/analytics/query/archetypes_by_event_scope_and_rank_v2/free?MetaPeriodId={int}&RankingClassScopeFilter=BRONZE_TO_PLATINUM
GET  https://mtgajson.untapped.gg/v1/latest/cards.json
GET  https://mtgajson.untapped.gg/v1/latest/loc_en.json
```

## Format coverage (event_name values)

| event_name | meaning |
|---|---|
| `Ladder` | Standard Bo1 |
| `Traditional_Ladder` | Standard Bo3 |
| `Historic_Ladder` / `Traditional_Historic_Ladder` | Historic Bo1/Bo3 |
| `Alchemy_Ladder` / `Traditional_Alchemy_Ladder` | Alchemy Bo1/Bo3 |
| `Explorer_Ladder` / `Traditional_Explorer_Ladder` | Explorer Bo1/Bo3 |
| `Timeless_Ladder` / `Traditional_Timeless_Ladder` | Timeless Bo1/Bo3 |
| `Play_Brawl_Historic` | Brawl |

## Known limits

- Mythic leaderboard returns ~98 decks, refreshed live
- Per-player match history endpoint is owner-only (premium-walled per-rank breakdowns too)
- **Free tier returns BRONZE_TO_PLATINUM, not mythic** for the meta endpoint. Plat is the largest tier by volume anyway.
- **Bo3 (`Traditional_*`) formats lack `winrate` field at the free tier** — only `total_matches` and `tier_val` (negative-rated relative metric). Bo1 (`Ladder`, etc.) has full WR data.
- The `upload-log` endpoint rate limits at ~50 req/min. Fetcher auto-retries on 429.
- `short_id` ROTATES when a player's "featured" deck changes — daily snapshots build a longitudinal corpus.

## Matchup data — important caveats

The `untapped_matchup_scraper.py` pulls the only public matchup endpoint:
  `GET /api/v1/analytics/query/archetype_matchups_showcase`

This endpoint:
- Takes NO parameters — returns whatever Untapped curates
- Is currently locked to ONE meta_period (681, the previous Standard Bo1 period)
- Has only 7 "showcase" opponents (Untapped picks the meta-defining decks)
- Provides matchup rows for 70-90 friendly archetypes vs those 7 opponents
- Sample sizes are HUGE (1k-19k matches per cell)

The paid `archetype_matchups_by_event_scope_and_rank` endpoint requires premium
entitlement (`mtga-global-stats-constructed-matchups`) and would let you scope
by Bo1/Bo3, rank, and any meta period. We can't access it.

**For tournament prep:** the directional signal is usually stable across set
releases. If a deck was bad vs ramp in March, it's almost certainly still bad
vs ramp in May unless the archetype changed radically. Use this for triage,
not precise WR calibration.

- Replay logs contain full raw `UnityCrossThreadLogger` output from MTGA — verbose JSON-in-JSON. Parsing into structured turn-by-turn play data is its own project (a few weeks). For now, only the deck diff (sideboard plan) is mined.
- Card db has 24,924 cards keyed on `grpid` — name resolution for any grpid in any replay deck just works.
- Storage growth: ~5-10 MB/day in compressed replays, ~1.6 GB/year. Replay files can be safely deleted; index in `untapped_replays` would still show "fetched" but with broken `file_path`.

## Notes

- Single DB (`mtg_meta.db`), namespaced tables (`untapped_*`) — joinable across sources without cross-DB attach
- Replay logs stored as gzipped files on disk, NOT in DB — single file portability stays manageable; logs are too large for SQLite to be efficient
- Card db materialized in DB rather than re-fetched each time — saves 17 MB transfer per run
- All endpoints are public, no auth needed — survives across sessions/devices
