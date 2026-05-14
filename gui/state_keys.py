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

# Palette recents
PALETTE_RECENTS = "palette_recents"
