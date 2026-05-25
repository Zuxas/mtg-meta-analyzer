"""Central registry of UIState dotted-path keys.

All tabs reference state via these constants instead of hardcoded strings,
so the path namespace is discoverable, renamable, and typo-safe.
"""

# Global state
LAST_ACTIVE_TAB_PATH = "global.last_active_tab_path"
GLOBAL_FORMAT = "global.format"  # written by palette format actions; read by open_archetype_detail

# Dashboard
DASHBOARD_TIMEFRAME = "tabs.dashboard.timeframe"
DASHBOARD_SELECTED_ARCHETYPE = "tabs.dashboard.selected_archetype"  # reserved; not yet wired

# My Decks
MY_DECKS_SELECTED_DECK_ID = "tabs.my_decks.selected_deck_id"

# Charts
CHARTS_TIMEFRAME = "tabs.charts.timeframe"
CHARTS_CHART_TYPE = "tabs.charts.chart_type"
CHARTS_FORMAT = "tabs.charts.format"
CHARTS_TOP_N = "tabs.charts.top_n"
CHARTS_COMPARE_ARCHETYPES = "tabs.charts.compare_archetypes"

# Matchup Data (heatmap_tab.py)
MATCHUP_DATA_FORMAT = "tabs.matchup_data.format"
MATCHUP_DATA_TIMEFRAME = "tabs.matchup_data.timeframe"

# Scout
SCOUT_DAYS = "tabs.scout.days"
SCOUT_FORMAT = "tabs.scout.format"
SCOUT_TOP = "tabs.scout.top"
SCOUT_TARGET_ARCHETYPES = "tabs.scout.target_archetypes"

# Match History replay viewer
MATCH_HISTORY_REPLAY_VIEWER_MODE = "tabs.match_history.replay_viewer_mode"  # "full" | "classic"

# Palette recents
PALETTE_RECENTS = "palette_recents"

# Matchup overlay (transparent always-on-top window over MTGA)
OVERLAY_GEOMETRY = "overlay.geometry"  # [x, y, w, h]
OVERLAY_LOCKED = "overlay.locked"       # bool (default True = click-through)
OVERLAY_COMPACT = "overlay.compact"     # bool (default False)
OVERLAY_NOTES_OPEN = "overlay.notes_open"  # bool (default True)
OVERLAY_DECKLIST_OPEN = "overlay.decklist_open"  # bool (default False)
OVERLAY_OPACITY = "overlay.opacity"  # float [0.30, 1.00], default 0.95
OVERLAY_OPP_OVERRIDE = "overlay.opp_override"  # str, empty => Auto
OVERLAY_DECK_OVERRIDE = "overlay.deck_override"  # int deck_id, 0 => Auto
