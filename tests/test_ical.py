"""The calendar feed file: escaping, folding, UTC times, and a check by an independent parser (the icalendar package) that what we write is a valid calendar."""
import pytest

from boatconnect import ical

from .conftest import HOUR, T0


def trip(**over):
    base = {"id": "abc123", "boat_id": "boat9", "boat_name": "Scooter", "title": "Catalina weekend", "home_port": "Marina del Rey, CA", "start_utc": T0, "end_utc": T0 + 8 * HOUR,
            "updated_at": T0 - 3600, "capacity": 6, "notes": "", "created_by_name": "Sam Skipper", "aboard": ["Sam Skipper", "Cass Crew"]}
    base.update(over)
    return base


def unfold(text):
    return text.replace("\r\n ", "")


def test_text_is_escaped_as_the_standard_asks():
    assert ical.escape("a,b;c\\d\nnext") == "a\\,b\;c\\\\d\\nnext"
    assert ical.escape("line1\r\nline2") == "line1\\nline2"


def test_long_lines_fold_at_75_bytes_without_splitting_a_character():
    line = "DESCRIPTION:" + "é" * 80                                                      # two bytes each
    folded = ical.fold(line)
    parts = folded.split("\r\n")
    assert len(parts) > 1 and all(len(p.encode("utf-8")) <= 75 for p in parts) and all(p.startswith(" ") for p in parts[1:])
    assert "".join([parts[0]] + [p[1:] for p in parts[1:]]) == line                      # nothing lost, nothing broken


def test_times_are_written_in_utc():
    assert ical.utc(0) == "19700101T000000Z"
    assert ical.utc(T0) == "20270115T080000Z"


def test_the_calendar_has_one_event_per_trip_with_its_facts():
    text = ical.build_calendar([trip(), trip(id="def456", title="Sunset sail")], "https://boatconnect.org")
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == 2
    body = unfold(text)
    assert "UID:abc123@boatconnect.org" in body and "UID:def456@boatconnect.org" in body
    assert "DTSTART:20270115T080000Z" in body and "DTEND:20270115T160000Z" in body
    assert "SUMMARY:Scooter: Catalina weekend" in body
    assert "LOCATION:Marina del Rey\\, CA" in body
    assert "URL:https://boatconnect.org/boats/boat9" in body
    assert "Booked by Sam Skipper\\nAboard (2 of 6): Sam Skipper\\, Cass Crew" in body


def test_notes_and_a_trip_with_no_one_listed():
    body = unfold(ical.build_calendar([trip(notes="Bring a hat;\nand water", aboard=[], capacity=None)], "https://boatconnect.org"))
    assert "Aboard (0): no one yet" in body and "Bring a hat\\;\\nand water" in body


def test_an_empty_feed_is_still_a_calendar():
    text = ical.build_calendar([], "https://boatconnect.org")
    assert "BEGIN:VCALENDAR" in text and "VEVENT" not in text


def test_an_independent_parser_reads_what_we_write():
    icalendar = pytest.importorskip("icalendar")
    cal = icalendar.Calendar.from_ical(ical.build_calendar([trip(notes="Bring a hat, and water; please")], "https://boatconnect.org"))
    [event] = [c for c in cal.walk() if c.name == "VEVENT"]
    assert str(event["SUMMARY"]) == "Scooter: Catalina weekend"
    assert event["DTSTART"].dt.isoformat() == "2027-01-15T08:00:00+00:00" and event["DTEND"].dt.isoformat() == "2027-01-15T16:00:00+00:00"
    assert str(event["LOCATION"]) == "Marina del Rey, CA"
    assert "Bring a hat, and water; please" in str(event["DESCRIPTION"])
    assert str(event["UID"]) == "abc123@boatconnect.org"
