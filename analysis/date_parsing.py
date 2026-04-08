"""
Natural language date range parsing for analysis queries.

Supports: "last 30 days", "feb2-mar9", "feb 2 2025", "today", ISO dates, etc.
Split from win_rates.py for reusability.
"""

import re
from datetime import datetime, timedelta



_MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10,
    'november': 11, 'december': 12,
}


def _parse_single_date(s, default_year=None):
    """
    Parse one date token into a datetime.
    Handles: "feb2", "feb 2", "feb 2 2025", "2025-02-14", "today", "now".
    """
    s = s.strip().lower()
    if s in ('today', 'now'):
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # ISO format
    try:
        return datetime.strptime(s, '%Y-%m-%d')
    except ValueError:
        pass

    # Insert space between letters and digits: "feb2" -> "feb 2", "oct25" -> "oct 25"
    s = re.sub(r'([a-z])(\d)', r'\1 \2', s)
    parts = s.split()

    if len(parts) >= 2:
        month = _MONTH_MAP.get(parts[0])
        if month is None:
            return None
        try:
            day = int(parts[1])
        except ValueError:
            return None
        year = default_year or datetime.now().year
        if len(parts) >= 3:
            try:
                year = int(parts[2])
            except ValueError:
                pass
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    return None


def parse_date_range(text):
    """
    Parse a natural language date range into (since, until) datetimes.

    Supported patterns:
      "last 30 days" / "last 2 weeks" / "last 3 months"
      "since 2025-01-01" / "since feb 2"
      "feb2-mar9"           (current year)
      "feb 2 - mar 9"
      "oct 25 2025 - today"
      "2025-01-01 - 2025-03-01"

    Returns (since_dt, until_dt) or (None, None) if unparseable.
    """
    if not text:
        return None, None

    text = text.strip().lower()
    now = datetime.now()

    # "last N days/weeks/months"
    m = re.match(r'last\s+(\d+)\s+(day|days|week|weeks|month|months)', text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if 'month' in unit:
            delta = timedelta(days=n * 30)
        elif 'week' in unit:
            delta = timedelta(weeks=n)
        else:
            delta = timedelta(days=n)
        return now - delta, now

    # "since DATE"
    m = re.match(r'since\s+(.+)', text)
    if m:
        since = _parse_single_date(m.group(1).strip())
        return since, now

    # Split range on " - " (with spaces) first
    if ' - ' in text:
        left, right = text.split(' - ', 1)
    else:
        # Try splitting on "-" where one side starts with a letter (e.g. "feb2-mar9")
        m = re.match(r'^(.+?)-([a-z].+)$', text)
        if m:
            left, right = m.group(1), m.group(2)
        else:
            left, right = text, None

    if right is not None:
        since = _parse_single_date(left.strip())
        until = _parse_single_date(right.strip())
        if since and until:
            return since, until + timedelta(days=1)  # until is inclusive
        if since:
            return since, now

    # Single token — treat as "since DATE"
    since = _parse_single_date(text)
    if since:
        return since, now

