"""`db.event_hub_db.export_ics` must emit valid iCalendar (RFC 5545).

The Event Hub's "Export .ics" button has shipped since the Event Finder UX
work, but the generator was hand-rolled and skipped three requirements that
bite as soon as a real store name or title carries punctuation:

* TEXT values must escape `\\` `;` `,` and newlines (RFC 5545 s3.3.11) --
  a store called "Gamer's Haven, LLC" otherwise turns the comma into a
  value separator and clients drop or mangle everything after it;
* every VEVENT must carry DTSTAMP (s3.6.1) -- Google Calendar and Outlook
  reject or silently rewrite events without it;
* content lines are limited to 75 octets and must be folded (s3.1).

These tests pin the output against a minimal parser that unfolds and
unescapes the way a client does, so the assertions are about what a
calendar app actually reads, not about the string we happen to build.
"""
import re

import pytest

from db.event_hub_db import export_ics


def _bookmark(**over):
    b = {
        "event_id": "ev1", "title": "US RCQ | Round 1 Modern", "store_name": "Card Shop",
        "event_date": "2026-05-16", "format_tags": '["modern"]', "event_type": "rcq",
        "entry_fee_cents": 3000, "event_url": "https://example.test/e/1",
        "status": "going", "personal_notes": "",
    }
    b.update(over)
    return b


def _unfold(ics: str) -> list[str]:
    """RFC 5545 s3.1: a CRLF followed by a space/tab continues the line."""
    return re.sub(r"\r\n[ \t]", "", ics).split("\r\n")


def _props(ics: str) -> dict[str, str]:
    out = {}
    for line in _unfold(ics):
        if ":" in line:
            name, _, value = line.partition(":")
            out.setdefault(name.split(";")[0], value)
    return out


def _unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"n": "\n", "N": "\n", "\\": "\\", ";": ";", ",": ","}.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def test_structure_and_crlf():
    ics = export_ics([_bookmark()])
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.rstrip().endswith("END:VCALENDAR")
    lines = _unfold(ics)
    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") == 1
    p = _props(ics)
    assert p["DTSTART"] == "20260516T120000Z" and p["DTEND"] == "20260516T200000Z"
    assert p["UID"] == "ev1@mtg-event-hub"
    assert p["URL"] == "https://example.test/e/1"


def test_every_vevent_carries_a_dtstamp():
    ics = export_ics([_bookmark(), _bookmark(event_id="ev2")])
    stamps = [l for l in _unfold(ics) if l.startswith("DTSTAMP:")]
    assert len(stamps) == 2
    assert all(re.fullmatch(r"DTSTAMP:\d{8}T\d{6}Z", s) for s in stamps)


@pytest.mark.parametrize("field, raw", [
    ("title", "Modern RCQ, Round 1"),
    ("store_name", "Gamer's Haven, LLC"),
    ("title", "Legacy; no proxies"),
    ("store_name", r"Back\Room Games"),
])
def test_text_values_are_escaped_so_a_client_reads_them_back_verbatim(field, raw):
    ics = export_ics([_bookmark(**{field: raw})])
    prop = "SUMMARY" if field == "title" else "LOCATION"
    value = _props(ics)[prop]
    for ch in (",", ";"):
        assert ch not in value.replace("\\" + ch, "")      # every one is escaped
    assert raw in _unescape(value)


def test_notes_newlines_survive_as_escaped_newlines():
    ics = export_ics([_bookmark(personal_notes="bring dice\nsleeves, too")])
    desc = _unescape(_props(ics)["DESCRIPTION"])
    assert "bring dice\nsleeves, too" in desc
    raw_desc = next(l for l in _unfold(ics) if l.startswith("DESCRIPTION:"))
    assert "\n" not in raw_desc[len("DESCRIPTION:"):].replace("\\n", "")


def test_content_lines_are_folded_to_75_octets():
    long_title = "Regional Championship Qualifier " * 4        # ~128 chars
    ics = export_ics([_bookmark(title=long_title)])
    assert all(len(l.encode("utf-8")) <= 75 for l in ics.split("\r\n")), \
        [l for l in ics.split("\r\n") if len(l.encode("utf-8")) > 75]
    assert long_title.strip() in _unescape(_props(ics)["SUMMARY"])


def test_folding_counts_octets_not_characters():
    ics = export_ics([_bookmark(store_name="Café " + "Münchner Kartenladen " * 4)])
    assert all(len(l.encode("utf-8")) <= 75 for l in ics.split("\r\n"))
    assert "Münchner" in _unescape(_props(ics)["LOCATION"])


def test_rows_without_a_date_are_skipped_not_emitted_broken():
    ics = export_ics([_bookmark(event_date=""), _bookmark(event_id="ev2")])
    assert _unfold(ics).count("BEGIN:VEVENT") == 1


def test_empty_selection_is_still_a_valid_empty_calendar():
    ics = export_ics([])
    assert _unfold(ics) == ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MTG Event Hub//EN",
                            "CALSCALE:GREGORIAN", "END:VCALENDAR"]


def test_write_ics_puts_bare_crlf_on_disk(tmp_path):
    """Windows text mode translates '\n' -> '\r\n', so writing our CRLF output
    through open(path, 'w') produced CR CR LF on disk. The writer opens with
    newline='' so the bytes are exactly what export_ics built."""
    from db.event_hub_db import write_ics
    path = tmp_path / "cal.ics"
    n = write_ics(str(path), [_bookmark(), _bookmark(event_id="ev2", event_date="")])
    raw = path.read_bytes()
    assert b"\r\r\n" not in raw
    assert raw.count(b"\r\n") == raw.count(b"\n")
    assert raw.startswith(b"BEGIN:VCALENDAR\r\n") and raw.rstrip().endswith(b"END:VCALENDAR")
    assert n == 1                                    # the dateless row is skipped
