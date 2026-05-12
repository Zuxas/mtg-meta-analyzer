"""
scrapers/player_handles.py -- Player Twitter/X handle discovery and content fetching

Three layers:
  1. handle_db.json        -- persistent store: player_name -> handle + metadata
  2. discover(names)       -- finds handles via Google, Moxfield, guides DB
  3. fetch_content(handle) -- pulls recent MTG tweets from a known handle

Usage:
    from scrapers.player_handles import HandleDB
    db = HandleDB()
    db.discover(['christopher kral', 'devon straub'])
    tweets = db.fetch_content('christopherkral_mtg')
"""

import json
import re
import time
import sqlite3
from pathlib import Path
from urllib.parse import quote_plus

ROOT     = Path(__file__).resolve().parent.parent
DB_PATH  = ROOT / 'data' / 'player_handles.json'
META_DB  = ROOT / 'data' / 'mtg_meta.db'


class HandleDB:
    def __init__(self):
        self.db_path = DB_PATH
        self.data = self._load()

    def _load(self):
        if self.db_path.exists():
            with open(self.db_path) as f:
                return json.load(f)
        return {'players': {}, 'handles': {}}

    def save(self):
        with open(self.db_path, 'w') as f:
            json.dump(self.data, f, indent=2)

    def add(self, player_name: str, handle: str, source: str = 'manual'):
        """Register a confirmed player -> handle mapping."""
        key = player_name.lower().strip()
        handle = handle.lstrip('@').strip()
        self.data['players'][key] = {
            'handle':  handle,
            'player':  player_name,
            'source':  source,
        }
        self.data['handles'][handle.lower()] = key
        self.save()
        print(f'  Added: {player_name} -> @{handle}  ({source})')

    def get(self, player_name: str):
        return self.data['players'].get(player_name.lower().strip())

    def all_players(self):
        return self.data['players']

    # ------------------------------------------------------------------
    # Discovery: pull handles from guides DB
    # ------------------------------------------------------------------

    def seed_from_guides_db(self):
        """
        Pull all Twitter handles already scraped in the guides table.
        Maps handle -> author name (not player name -- needs manual confirm).
        Stores as unconfirmed candidates in handles dict.
        """
        conn = sqlite3.connect(META_DB)
        rows = conn.execute(
            "SELECT url, author, archetype FROM guides "
            "WHERE url LIKE '%x.com%' OR url LIKE '%twitter.com%'"
        ).fetchall()
        conn.close()

        candidates = self.data.setdefault('candidates', {})
        added = 0
        for url, author, arch in rows:
            m = re.search(r'(?:twitter|x)\.com/([A-Za-z0-9_]{2,50})(?:/|$)', url)
            if not m:
                continue
            handle = m.group(1)
            skip = {'intent', 'share', 'search', 'hashtag', 'i', 'home',
                    'messages', 'status', 'compose', 'notifications'}
            if handle.lower() in skip:
                continue
            if handle.lower() not in candidates:
                candidates[handle.lower()] = {
                    'handle': handle,
                    'author': author or handle,
                    'archetypes': [],
                }
                added += 1
            if arch and arch not in candidates[handle.lower()]['archetypes']:
                candidates[handle.lower()]['archetypes'].append(arch)

        self.save()
        print(f'Seeded {added} new candidates from guides DB ({len(candidates)} total)')
        return candidates

    def match_candidates_to_players(self, player_names: list):
        """
        Try to match unconfirmed candidates to player names by substring.
        Returns dict of likely matches for human review.
        """
        candidates = self.data.get('candidates', {})
        already_mapped = {v['handle'].lower() for v in self.data['players'].values()}
        suggestions = {}

        for player in player_names:
            if self.get(player):
                continue  # already mapped
            p_lower = player.lower()
            parts   = [w for w in p_lower.split() if len(w) > 3]
            for handle_key, info in candidates.items():
                if handle_key in already_mapped:
                    continue
                author = (info.get('author') or '').lower()
                score  = sum(1 for part in parts
                             if part in handle_key or part in author)
                if score >= 1:
                    suggestions.setdefault(player, []).append({
                        'handle':  info['handle'],
                        'author':  info['author'],
                        'score':   score,
                        'archetypes': info.get('archetypes', []),
                    })

        # Sort each player's suggestions by score desc
        for player in suggestions:
            suggestions[player].sort(key=lambda x: -x['score'])

        return suggestions

    # ------------------------------------------------------------------
    # Discovery: Google search for handle
    # ------------------------------------------------------------------

    def search_google(self, player_name: str, fetch_fn=None):
        """
        Search Google for '{player_name} mtg twitter' and extract @handles.
        fetch_fn: a callable(url, prompt) -> str  (e.g. WebFetch wrapper).
        Returns list of candidate handles found.
        """
        if fetch_fn is None:
            return []
        query   = quote_plus(f'"{player_name}" mtg twitter OR x.com')
        url     = f'https://www.google.com/search?q={query}&num=5'
        prompt  = (f'Find any Twitter or X.com handles (@username) for a Magic: The Gathering '
                   f'player named {player_name}. Return only the handles you find, one per line, '
                   f'starting with @. If none found, say NONE.')
        try:
            result = fetch_fn(url, prompt)
            handles = re.findall(r'@([A-Za-z0-9_]{2,50})', result)
            return list(set(handles))
        except Exception as e:
            print(f'  Google search failed for {player_name}: {e}')
            return []

    # ------------------------------------------------------------------
    # Content fetching: pull tweets from a known handle
    # ------------------------------------------------------------------

    def fetch_content(self, handle: str, fetch_fn=None, topic: str = 'mtg standard'):
        """
        Fetch recent tweets from a handle about a topic.
        Uses nitter.poast.org as fallback since x.com blocks scraping.
        Returns list of tweet strings.
        """
        handle = handle.lstrip('@')
        if fetch_fn is None:
            return []

        # Try nitter instances in order
        nitter_instances = [
            'https://nitter.poast.org',
            'https://nitter.privacydev.net',
            'https://nitter.1d4.us',
        ]

        for base in nitter_instances:
            url    = f'{base}/{handle}'
            prompt = (f'List all recent tweets from this user about Magic: The Gathering, '
                      f'decklists, sideboard plans, tournament reports, or {topic}. '
                      f'For each tweet include the text and approximate date. '
                      f'If the page is unavailable say UNAVAILABLE.')
            try:
                result = fetch_fn(url, prompt)
                if 'UNAVAILABLE' not in result.upper() and len(result) > 100:
                    return result
            except Exception:
                continue

        return f'Could not fetch content for @{handle} -- all nitter instances unavailable'

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    def discover_batch(self, player_names: list, fetch_fn=None, delay: float = 1.5):
        """
        Run full discovery for a list of player names:
          1. Check existing mappings
          2. Try Google search for unmapped players
          3. Return summary
        """
        results = {'mapped': {}, 'found': {}, 'not_found': []}

        for player in player_names:
            existing = self.get(player)
            if existing:
                results['mapped'][player] = existing['handle']
                continue

            handles = self.search_google(player, fetch_fn)
            if handles:
                results['found'][player] = handles
                print(f'  {player}: found candidates {handles}')
            else:
                results['not_found'].append(player)

            time.sleep(delay)

        return results

    def report(self):
        """Print current handle DB status."""
        players  = self.data['players']
        cands    = self.data.get('candidates', {})
        print(f'Handle DB: {len(players)} confirmed | {len(cands)} candidates')
        print()
        if players:
            print('Confirmed player -> handle mappings:')
            for player, info in sorted(players.items()):
                print(f'  {player:<35} @{info["handle"]}  ({info["source"]})')
