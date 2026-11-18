"""The calendar feed as an iCalendar (.ics) file, which Google, Apple and Outlook calendars can subscribe to.

Standard library only. Lines end in CRLF, are folded at 75 bytes (never inside a multi-byte character), and text is escaped as RFC 5545 asks. Every time is written in UTC, so
the subscribing calendar shows each trip at the right hour wherever its owner is.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

PRODID = "-//boatconnect//shared boat calendar//EN"


def escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def fold(line: str) -> str:
    """Wrap a content line at 75 bytes; each continuation starts with one space (which counts toward its 75)."""
    out: List[str] = []
    current, size = "", 0
    for ch in line:
        width = len(ch.encode("utf-8"))
        if size + width > 75:
            out.append(current)
            current, size = " ", 1
        current += ch
        size += width
    out.append(current)
    return "\r\n".join(out)


def utc(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def description(trip: Dict[str, Any]) -> str:
    aboard = trip.get("aboard") or []
    limit = f" of {trip['capacity']}" if trip.get("capacity") else ""
    parts = [f"Booked by {trip['created_by_name']}", f"Aboard ({len(aboard)}{limit}): " + (", ".join(aboard) if aboard else "no one yet")]
    if trip.get("notes"):
        parts += ["", trip["notes"]]
    return "\n".join(parts)


def build_calendar(trips: Iterable[Dict[str, Any]], base_url: str, name: str = "boatconnect") -> str:
    """One VEVENT per trip. A trip keeps its UID for life, so a calendar updates it in place when it is changed and drops it when it is cancelled."""
    host = base_url.split("://", 1)[-1].split("/", 1)[0] or "boatconnect"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{escape(name)}", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    for trip in trips:
        stamp = utc(trip["updated_at"])
        lines += [
            "BEGIN:VEVENT",
            f"UID:{trip['id']}@{host}",
            f"DTSTAMP:{stamp}",
            f"LAST-MODIFIED:{stamp}",
            f"DTSTART:{utc(trip['start_utc'])}",
            f"DTEND:{utc(trip['end_utc'])}",
            f"SUMMARY:{escape(trip['boat_name'] + ': ' + trip['title'])}",
            f"LOCATION:{escape(trip['home_port'])}",
            f"DESCRIPTION:{escape(description(trip))}",
            f"URL:{base_url}/boats/{trip['boat_id']}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
