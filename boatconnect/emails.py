"""What boatconnect's emails say. Plain functions: facts in, a `Mail` out. Everything a user typed (names, boat names, titles, notes) is HTML-escaped in the HTML part and
kept on one line in subjects. Every link points at PUBLIC_URL, never at anything a user supplied."""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Optional
from zoneinfo import ZoneInfo

from .mail import Mail, one_line


def share(percent: Optional[float]) -> str:
    return f"{round(percent, 6):g}%" if percent else ""


def when(start: float, end: float, timezone: str) -> str:
    zone = ZoneInfo(timezone)
    a, b = datetime.fromtimestamp(start, zone), datetime.fromtimestamp(end, zone)
    day = lambda d: f"{d.strftime('%a %b')} {d.day}"
    time = lambda d: f"{d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"
    span = f"{day(a)}, {time(a)} to {time(b)}" if a.date() == b.date() else f"{day(a)} {time(a)} to {day(b)} {time(b)}"
    return f"{span} ({timezone.replace('_', ' ')})"


def _page(heading: str, paragraphs: list, button: Optional[tuple] = None, footer: str = "") -> str:
    body = "".join(f'<p style="margin:0 0 12px">{p}</p>' for p in paragraphs)
    link = f'<p style="margin:18px 0"><a href="{escape(button[1], quote=True)}" style="background:#0b4f7c;color:#fff;padding:9px 16px;border-radius:6px;text-decoration:none;font-weight:600">{escape(button[0])}</a></p>' if button else ""
    foot = f'<p style="color:#566877;font-size:13px;margin-top:22px">{footer}</p>' if footer else ""
    return (f'<div style="font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#14232f;max-width:34rem">'
            f'<h2 style="margin:0 0 14px;font-size:18px">{escape(heading)}</h2>{body}{link}{foot}</div>')


def _text(lines: list, link: Optional[str] = None, footer: str = "") -> str:
    parts = list(lines)
    if link:
        parts += ["", link]
    if footer:
        parts += ["", "--", footer]
    return "\n".join(parts) + "\n"


FOOTER = "You are getting this because you have a boatconnect account."


def boat_waiting(boat: str, creator: str, base: str) -> Mail:
    url = f"{base}/inbox"
    return Mail(one_line(f"New boat waiting for your approval: {boat}"),
                _text([f'{creator} added a boat, "{boat}", and it waits for your approval.'], url, FOOTER),
                _page("A boat is waiting for approval", [f"<strong>{escape(creator)}</strong> added a boat, <strong>{escape(boat)}</strong>, and it waits for your approval."], ("Review it", url), escape(FOOTER)))


def join_request(requester: str, boat: str, role: str, share_percent: Optional[float], note: str, base: str) -> Mail:
    url = f"{base}/inbox"
    asks = f"as an owner with a {share(share_percent)} share" if role == "owner" else "as crew"
    lines = [f'{requester} asks to join "{boat}" {asks}.'] + ([f'They wrote: "{note}"'] if note else [])
    paras = [f"<strong>{escape(requester)}</strong> asks to join <strong>{escape(boat)}</strong> {escape(asks)}."] + ([f"They wrote: &ldquo;{escape(note)}&rdquo;"] if note else [])
    return Mail(one_line(f"{requester} asks to join {boat}"), _text(lines, url, FOOTER), _page("A request to join a boat", paras, ("Decide", url), escape(FOOTER)))


def request_decision(boat: str, role: str, approved: bool, base: str, boat_id: str) -> Mail:
    url = f"{base}/boats/{boat_id}"
    verdict = f'You have been approved to join "{boat}" as {role}.' if approved else f'Your request to join "{boat}" as {role} was declined.'
    subject = f"You are in: {boat}" if approved else f"Your request to join {boat}"
    return Mail(one_line(subject), _text([verdict], url if approved else None, FOOTER),
                _page("Your request to join a boat", [escape(verdict)], ("Open the boat", url) if approved else None, escape(FOOTER)))


def boat_decision(boat: str, approved: bool, base: str, boat_id: str) -> Mail:
    url = f"{base}/boats/{boat_id}"
    verdict = f'Your boat "{boat}" was approved and now appears in the list.' if approved else f'Your boat "{boat}" was not approved.'
    return Mail(one_line(f"Your boat {boat} was {'approved' if approved else 'not approved'}"), _text([verdict], url if approved else None, FOOTER),
                _page("Your boat", [escape(verdict)], ("Open the boat", url) if approved else None, escape(FOOTER)))


def trip_notice(kind: str, actor: str, boat: str, title: str, span: str, base: str, boat_id: str, unsubscribe: str, page: str) -> Mail:
    """kind is "booked", "changed" or "cancelled"."""
    url = f"{base}/boats/{boat_id}"
    line = f'{actor} {kind} a trip on {boat}: "{title}", {span}.'
    footer = f"{FOOTER} To stop emails about trips, open: {page}"
    html_footer = f'{escape(FOOTER)} <a href="{escape(page, quote=True)}">Stop emails about trips</a>.'
    return Mail(one_line(f"{boat}: {title} {kind}"), _text([line], url, footer),
                _page(f"A trip was {kind}", [f"<strong>{escape(actor)}</strong> {escape(kind)} a trip on <strong>{escape(boat)}</strong>:", f"<strong>{escape(title)}</strong><br>{escape(span)}"],
                      ("Open the calendar", url), html_footer), unsubscribe_url=unsubscribe)


def password_reset(name: str, url: str) -> Mail:
    text = _text([f"Hello {name},", "",
                  "Someone asked to reset the password of your boatconnect account. If it was you, use this link within an hour; it works once:",
                  "", url, "",
                  "If it was not you, ignore this email: your password stays as it is."], None, FOOTER)
    html = _page("Reset your password", [f"Hello {escape(name)},",
                                         "Someone asked to reset the password of your boatconnect account. If it was you, use the button within an hour; it works once.",
                                         "If it was not you, ignore this email: your password stays as it is."], ("Choose a new password", url), escape(FOOTER))
    return Mail("Reset your boatconnect password", text, html)
