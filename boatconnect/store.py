"""The database: users, their login sessions, boats, who belongs to each boat, join requests, bookings and who has signed on to each. SQLite, one file, mode 600.

Calls are plain blocking functions that return plain dicts; the server runs them in a thread (`Store.run`). Rules that depend on several rows (a boat's owner shares may not
add up to more than 100%, two bookings of one boat may not overlap, a booking holds at most its capacity) are checked here, inside the transaction that writes, so two
requests at once cannot both get past them. Anything the user may be told is a StoreError.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

SCHEMA_VERSION = 4

NAME_CHARS = 60
BOAT_NAME_CHARS = 80
TEXT_CHARS = 2000
MIN_BOOKING_SECONDS = 15 * 60
MAX_BOOKING_SECONDS = 30 * 24 * 3600

SCHEMA = """
CREATE TABLE users (
  id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL, created_at REAL NOT NULL,
  login_count INTEGER NOT NULL DEFAULT 0, last_login_at REAL);
CREATE TABLE auth_sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE boats (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, home_port TEXT NOT NULL, description TEXT NOT NULL, timezone TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')), created_by TEXT NOT NULL REFERENCES users(id), created_at REAL NOT NULL,
  decided_at REAL);
CREATE TABLE memberships (
  boat_id TEXT NOT NULL REFERENCES boats(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'crew')), share_percent REAL, created_at REAL NOT NULL, PRIMARY KEY (boat_id, user_id),
  CHECK ((role = 'owner' AND share_percent > 0 AND share_percent <= 100) OR (role = 'crew' AND share_percent IS NULL)));
CREATE INDEX memberships_user ON memberships(user_id);
CREATE TABLE join_requests (
  id TEXT PRIMARY KEY, boat_id TEXT NOT NULL REFERENCES boats(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'crew')), share_percent REAL, message TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'declined')), created_at REAL NOT NULL, decided_by TEXT, decided_at REAL);
CREATE UNIQUE INDEX join_requests_one_pending ON join_requests(boat_id, user_id) WHERE status = 'pending';
CREATE TABLE bookings (
  id TEXT PRIMARY KEY, boat_id TEXT NOT NULL REFERENCES boats(id) ON DELETE CASCADE, created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, start_utc REAL NOT NULL, end_utc REAL NOT NULL, capacity INTEGER, notes TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL DEFAULT 0,
  CHECK (end_utc > start_utc));
CREATE INDEX bookings_boat_time ON bookings(boat_id, start_utc);
CREATE TABLE signons (
  booking_id TEXT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at REAL NOT NULL,
  PRIMARY KEY (booking_id, user_id));
CREATE TABLE share_history (
  id INTEGER PRIMARY KEY, boat_id TEXT NOT NULL REFERENCES boats(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  old_share REAL, new_share REAL, created_at REAL NOT NULL);
CREATE INDEX share_history_boat ON share_history(boat_id, id);
CREATE TABLE calendar_feeds (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, token TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
CREATE TABLE boat_photos (
  boat_id TEXT PRIMARY KEY REFERENCES boats(id) ON DELETE CASCADE, data BLOB NOT NULL, updated_at REAL NOT NULL);
"""

# Version 2 keeps a history of owners' shares (who joined with what, who changed theirs, who left). The owners that exist when it is made start with the share they joined with.
MIGRATE_1_TO_2 = """
CREATE TABLE share_history (
  id INTEGER PRIMARY KEY, boat_id TEXT NOT NULL REFERENCES boats(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  old_share REAL, new_share REAL, created_at REAL NOT NULL);
CREATE INDEX share_history_boat ON share_history(boat_id, id);
INSERT INTO share_history (boat_id, user_id, old_share, new_share, created_at) SELECT boat_id, user_id, NULL, share_percent, created_at FROM memberships WHERE role = 'owner';
"""

# Version 3 adds the private calendar-feed links, and when each booking last changed (what the feed tells calendars).
MIGRATE_2_TO_3 = """
CREATE TABLE calendar_feeds (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, token TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
ALTER TABLE bookings ADD COLUMN updated_at REAL NOT NULL DEFAULT 0;
UPDATE bookings SET updated_at = created_at;
"""

# Version 4 adds a photo for each boat, kept in the database so the nightly backup holds it.
MIGRATE_3_TO_4 = """
CREATE TABLE boat_photos (
  boat_id TEXT PRIMARY KEY REFERENCES boats(id) ON DELETE CASCADE, data BLOB NOT NULL, updated_at REAL NOT NULL);
"""


class StoreError(Exception):
    """A request the store refuses (a duplicate email, an overlapping booking). The message is safe to show the user."""


class Store:
    def __init__(self, path: str) -> None:
        self.path = str(path)
        parent = Path(self.path).parent
        parent.mkdir(parents=True, exist_ok=True)
        if not Path(self.path).exists():
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)          # the file exists with its final permissions before anything is written to it
            os.close(fd)
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                db.executescript(SCHEMA)
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version in (1, 2, 3):
                if version == 1:
                    db.executescript(MIGRATE_1_TO_2)
                if version in (1, 2):
                    db.executescript(MIGRATE_2_TO_3)
                db.executescript(MIGRATE_3_TO_4)
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version != SCHEMA_VERSION:
                raise StoreError(f"the database has schema version {version}; this program expects {SCHEMA_VERSION}")
        os.chmod(self.path, 0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA journal_mode = WAL")
            with db:                                                          # one transaction per call
                yield db

    async def run(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run one of the blocking methods off the event loop."""
        return await asyncio.to_thread(function, *args, **kwargs)

    # ---- users and login sessions -----------------------------------------------------------------------------------------------------------------------------

    def create_user(self, email: str, name: str, password_hash: str) -> str:
        user_id = uuid.uuid4().hex
        try:
            with self._connect() as db:
                db.execute("INSERT INTO users (id, email, name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)", (user_id, email, name, password_hash, time.time()))
        except sqlite3.IntegrityError:
            raise StoreError("that email is already registered")
        return user_id

    def user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT id, email, name, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

    def count_users(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def accounts_created_since(self, since: float) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (since,)).fetchone()[0]

    def create_login(self, user_id: str, token_hash: str, lifetime_seconds: float) -> None:
        now = time.time()
        with self._connect() as db:
            db.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now,))
            db.execute("UPDATE users SET login_count = login_count + 1, last_login_at = ? WHERE id = ?", (now, user_id))
            db.execute("INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (token_hash, user_id, now, now + lifetime_seconds))

    def user_for_login(self, token_hash: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT u.id, u.email, u.name FROM auth_sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
                             (token_hash, time.time())).fetchone()
        return dict(row) if row else None

    def end_login(self, token_hash: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))

    # ---- boats ------------------------------------------------------------------------------------------------------------------------------------------------

    def create_boat(self, user_id: str, name: str, home_port: str, description: str, timezone: str, share_percent: float) -> str:
        """A new boat waits for the administrator's approval; its creator is its first owner, with the share they say they hold."""
        _check_share(share_percent)
        boat_id, now = uuid.uuid4().hex, time.time()
        with self._connect() as db:
            db.execute("INSERT INTO boats (id, name, home_port, description, timezone, status, created_by, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                       (boat_id, name, home_port, description, timezone, user_id, now))
            db.execute("INSERT INTO memberships (boat_id, user_id, role, share_percent, created_at) VALUES (?, ?, 'owner', ?, ?)", (boat_id, user_id, share_percent, now))
            _log_share(db, boat_id, user_id, None, share_percent, now)
        return boat_id

    def update_boat(self, boat_id: str, name: str, home_port: str, description: str, timezone: str) -> None:
        """Change a boat's details. Its bookings keep the moment they are at (UTC); a new time zone only changes the days and hours they are shown on."""
        with self._connect() as db:
            changed = db.execute("UPDATE boats SET name = ?, home_port = ?, description = ?, timezone = ? WHERE id = ?", (name, home_port, description, timezone, boat_id)).rowcount
        if not changed:
            raise StoreError("no such boat")

    def set_photo(self, boat_id: str, data: bytes) -> None:
        """Keep a boat's photo (already checked and re-encoded by photos.process_photo); a new one replaces the old."""
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM boats WHERE id = ?", (boat_id,)).fetchone():
                raise StoreError("no such boat")
            db.execute("INSERT INTO boat_photos (boat_id, data, updated_at) VALUES (?, ?, ?) ON CONFLICT(boat_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                       (boat_id, data, time.time()))

    def get_photo(self, boat_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT data, updated_at FROM boat_photos WHERE boat_id = ?", (boat_id,)).fetchone()
        return dict(row) if row else None

    def delete_photo(self, boat_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM boat_photos WHERE boat_id = ?", (boat_id,))

    def get_boat(self, boat_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute(_BOAT_SELECT + " WHERE b.id = ?", (boat_id,)).fetchone()
        return dict(row) if row else None

    def approved_boats(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(_BOAT_SELECT + " WHERE b.status = 'approved' ORDER BY b.name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def boats_of_user(self, user_id: str) -> List[Dict[str, Any]]:
        """Every boat the user belongs to, approved or not (their own unapproved boat is theirs to see)."""
        with self._connect() as db:
            rows = db.execute(_BOAT_SELECT + " WHERE b.id IN (SELECT boat_id FROM memberships WHERE user_id = ?) ORDER BY b.name COLLATE NOCASE", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def pending_boats(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(_BOAT_SELECT + " WHERE b.status = 'pending' ORDER BY b.created_at").fetchall()
        return [dict(r) for r in rows]

    def decide_boat(self, boat_id: str, approve: bool) -> None:
        with self._connect() as db:
            changed = db.execute("UPDATE boats SET status = ?, decided_at = ? WHERE id = ? AND status = 'pending'",
                                 ("approved" if approve else "rejected", time.time(), boat_id)).rowcount
        if not changed:
            raise StoreError("that boat is not waiting for a decision")

    def set_share(self, boat_id: str, user_id: str, share_percent: float) -> None:
        """An owner changes their own share: lower it whenever they like (that frees room for a new owner), or raise it into room nobody holds."""
        _check_share(share_percent)
        with self._connect() as db:
            row = db.execute("SELECT share_percent FROM memberships WHERE boat_id = ? AND user_id = ? AND role = 'owner'", (boat_id, user_id)).fetchone()
            if not row:
                raise StoreError("only an owner of this boat has a share")
            old = row["share_percent"]
            if abs(share_percent - old) < 1e-9:
                raise StoreError(f"your share is already {old:g}%")
            others = db.execute("SELECT COALESCE(SUM(share_percent), 0) FROM memberships WHERE boat_id = ? AND role = 'owner' AND user_id != ?", (boat_id, user_id)).fetchone()[0]
            if share_percent > 100.0 - others + 1e-9:
                raise StoreError(f"at most {100.0 - others:g}% is available to you: the other owners hold {others:g}%")
            db.execute("UPDATE memberships SET share_percent = ? WHERE boat_id = ? AND user_id = ?", (share_percent, boat_id, user_id))
            _log_share(db, boat_id, user_id, old, share_percent, time.time())

    def share_history(self, boat_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """The latest changes to the owners' shares, newest first: old is None for someone joining, new is None for someone leaving."""
        with self._connect() as db:
            rows = db.execute("SELECT h.user_id, u.name, h.old_share, h.new_share, h.created_at FROM share_history h JOIN users u ON u.id = h.user_id WHERE h.boat_id = ? "
                              "ORDER BY h.id DESC LIMIT ?", (boat_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def roles_of_user(self, user_id: str) -> Dict[str, str]:
        with self._connect() as db:
            return {r["boat_id"]: r["role"] for r in db.execute("SELECT boat_id, role FROM memberships WHERE user_id = ?", (user_id,)).fetchall()}

    def pending_requests_of_user(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(_REQUEST_SELECT + " WHERE r.user_id = ? AND r.status = 'pending'", (user_id,)).fetchall()
        return {r["boat_id"]: dict(r) for r in rows}

    def members(self, boat_id: str) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT m.user_id, u.name, m.role, m.share_percent FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.boat_id = ? "
                              "ORDER BY m.role DESC, m.share_percent DESC, u.name COLLATE NOCASE", (boat_id,)).fetchall()
        return [dict(r) for r in rows]

    def role_of(self, boat_id: str, user_id: str) -> Optional[str]:
        with self._connect() as db:
            row = db.execute("SELECT role FROM memberships WHERE boat_id = ? AND user_id = ?", (boat_id, user_id)).fetchone()
        return row["role"] if row else None

    def remove_member(self, boat_id: str, user_id: str) -> None:
        """Take a member off a boat, with their sign-ons and the bookings they made. A boat always keeps at least one owner."""
        with self._connect() as db:
            row = db.execute("SELECT role, share_percent FROM memberships WHERE boat_id = ? AND user_id = ?", (boat_id, user_id)).fetchone()
            if not row:
                raise StoreError("that person is not a member of this boat")
            if row["role"] == "owner":
                _log_share(db, boat_id, user_id, row["share_percent"], None, time.time())
            if row["role"] == "owner" and db.execute("SELECT COUNT(*) FROM memberships WHERE boat_id = ? AND role = 'owner'", (boat_id,)).fetchone()[0] == 1:
                raise StoreError("a boat must keep at least one owner")
            db.execute("DELETE FROM signons WHERE user_id = ? AND booking_id IN (SELECT id FROM bookings WHERE boat_id = ?)", (user_id, boat_id))
            db.execute("DELETE FROM bookings WHERE boat_id = ? AND created_by = ?", (boat_id, user_id))
            db.execute("DELETE FROM memberships WHERE boat_id = ? AND user_id = ?", (boat_id, user_id))

    # ---- join requests ----------------------------------------------------------------------------------------------------------------------------------------

    def request_join(self, boat_id: str, user_id: str, role: str, share_percent: Optional[float], message: str) -> str:
        if role not in ("owner", "crew"):
            raise StoreError("choose owner or crew")
        if role == "owner":
            _check_share(share_percent)
        else:
            share_percent = None
        request_id = uuid.uuid4().hex
        with self._connect() as db:
            boat = db.execute("SELECT status FROM boats WHERE id = ?", (boat_id,)).fetchone()
            if not boat or boat["status"] != "approved":
                raise StoreError("that boat is not open for requests")
            if db.execute("SELECT 1 FROM memberships WHERE boat_id = ? AND user_id = ?", (boat_id, user_id)).fetchone():
                raise StoreError("you already belong to this boat")
            try:
                db.execute("INSERT INTO join_requests (id, boat_id, user_id, role, share_percent, message, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                           (request_id, boat_id, user_id, role, share_percent, message, time.time()))
            except sqlite3.IntegrityError:
                raise StoreError("you already have a request waiting for this boat")
        return request_id

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute(_REQUEST_SELECT + " WHERE r.id = ?", (request_id,)).fetchone()
        return dict(row) if row else None

    def pending_requests(self, boat_ids: Optional[List[str]] = None, role: Optional[str] = None) -> List[Dict[str, Any]]:
        """Waiting requests, oldest first; for some boats only (None means all), and for one role only (None means both)."""
        clauses, args = ["r.status = 'pending'"], []     # type: List[str], List[Any]
        if boat_ids is not None:
            if not boat_ids:
                return []
            clauses.append("r.boat_id IN (%s)" % ",".join("?" * len(boat_ids)))
            args += boat_ids
        if role:
            clauses.append("r.role = ?")
            args.append(role)
        with self._connect() as db:
            rows = db.execute(_REQUEST_SELECT + " WHERE " + " AND ".join(clauses) + " ORDER BY r.created_at", args).fetchall()
        return [dict(r) for r in rows]

    def request_of_user(self, boat_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute(_REQUEST_SELECT + " WHERE r.boat_id = ? AND r.user_id = ? AND r.status = 'pending'", (boat_id, user_id)).fetchone()
        return dict(row) if row else None

    def decide_request(self, request_id: str, decider_id: str, approve: bool) -> None:
        """Approving makes the person a member. An owner's share must fit: the shares of a boat's owners may not add up to more than 100%."""
        with self._connect() as db:
            req = db.execute("SELECT * FROM join_requests WHERE id = ? AND status = 'pending'", (request_id,)).fetchone()
            if not req:
                raise StoreError("that request is not waiting for a decision")
            now = time.time()
            if approve:
                if db.execute("SELECT 1 FROM memberships WHERE boat_id = ? AND user_id = ?", (req["boat_id"], req["user_id"])).fetchone():
                    raise StoreError("that person already belongs to this boat")
                if req["role"] == "owner":
                    held = db.execute("SELECT COALESCE(SUM(share_percent), 0) FROM memberships WHERE boat_id = ? AND role = 'owner'", (req["boat_id"],)).fetchone()[0]
                    if held + req["share_percent"] > 100.0 + 1e-9:
                        raise StoreError(f"the owners already hold {held:g}% of this boat, so a {req['share_percent']:g}% share does not fit; "
                                         "an owner must lower their own share first")
                db.execute("INSERT INTO memberships (boat_id, user_id, role, share_percent, created_at) VALUES (?, ?, ?, ?, ?)",
                           (req["boat_id"], req["user_id"], req["role"], req["share_percent"], now))
                if req["role"] == "owner":
                    _log_share(db, req["boat_id"], req["user_id"], None, req["share_percent"], now)
            db.execute("UPDATE join_requests SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?", ("approved" if approve else "declined", decider_id, now, request_id))

    # ---- bookings and sign-ons --------------------------------------------------------------------------------------------------------------------------------

    def create_booking(self, boat_id: str, user_id: str, title: str, start: float, end: float, capacity: Optional[int], notes: str) -> str:
        """The booker is signed on to their own booking. A booking may not overlap another booking of the same boat."""
        _check_times(start, end)
        _check_capacity(capacity, 1)
        booking_id, now = uuid.uuid4().hex, time.time()
        with self._connect() as db:
            _check_no_overlap(db, boat_id, start, end, None)
            db.execute("INSERT INTO bookings (id, boat_id, created_by, title, start_utc, end_utc, capacity, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (booking_id, boat_id, user_id, title, start, end, capacity, notes, now, now))
            db.execute("INSERT INTO signons (booking_id, user_id, created_at) VALUES (?, ?, ?)", (booking_id, user_id, now))
        return booking_id

    def update_booking(self, booking_id: str, title: str, start: float, end: float, capacity: Optional[int], notes: str) -> None:
        _check_times(start, end)
        with self._connect() as db:
            row = db.execute("SELECT boat_id FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            if not row:
                raise StoreError("that booking does not exist")
            _check_capacity(capacity, db.execute("SELECT COUNT(*) FROM signons WHERE booking_id = ?", (booking_id,)).fetchone()[0])
            _check_no_overlap(db, row["boat_id"], start, end, booking_id)
            db.execute("UPDATE bookings SET title = ?, start_utc = ?, end_utc = ?, capacity = ?, notes = ?, updated_at = ? WHERE id = ?",
                       (title, start, end, capacity, notes, time.time(), booking_id))

    def delete_booking(self, booking_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))

    def get_booking(self, booking_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else None

    def bookings_between(self, boat_id: str, start: float, end: float) -> List[Dict[str, Any]]:
        """The boat's bookings that overlap [start, end), earliest first, each with the names of everyone signed on."""
        with self._connect() as db:
            rows = db.execute("SELECT b.id, b.title, b.start_utc, b.end_utc, b.capacity, b.notes, b.created_by, u.name AS created_by_name FROM bookings b "
                              "JOIN users u ON u.id = b.created_by WHERE b.boat_id = ? AND b.start_utc < ? AND b.end_utc > ? ORDER BY b.start_utc, b.id",
                              (boat_id, end, start)).fetchall()
            bookings = [dict(r) for r in rows]
            for booking in bookings:
                crew = db.execute("SELECT s.user_id, u.name FROM signons s JOIN users u ON u.id = s.user_id WHERE s.booking_id = ? ORDER BY s.created_at, u.name",
                                  (booking["id"],)).fetchall()
                booking["aboard"] = [dict(c) for c in crew]
        return bookings

    def sign_on(self, booking_id: str, user_id: str) -> None:
        with self._connect() as db:
            row = db.execute("SELECT capacity FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            if not row:
                raise StoreError("that booking does not exist")
            if db.execute("SELECT 1 FROM signons WHERE booking_id = ? AND user_id = ?", (booking_id, user_id)).fetchone():
                raise StoreError("you are already signed on")
            if row["capacity"] is not None and db.execute("SELECT COUNT(*) FROM signons WHERE booking_id = ?", (booking_id,)).fetchone()[0] >= row["capacity"]:
                raise StoreError("this trip is full")
            db.execute("INSERT INTO signons (booking_id, user_id, created_at) VALUES (?, ?, ?)", (booking_id, user_id, time.time()))
            db.execute("UPDATE bookings SET updated_at = ? WHERE id = ?", (time.time(), booking_id))

    def sign_off(self, booking_id: str, user_id: str) -> None:
        with self._connect() as db:
            booking = db.execute("SELECT created_by FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            if booking and booking["created_by"] == user_id:
                raise StoreError("the person who made a booking stays aboard it; delete the booking instead")
            if not db.execute("DELETE FROM signons WHERE booking_id = ? AND user_id = ?", (booking_id, user_id)).rowcount:
                raise StoreError("that person is not signed on")
            db.execute("UPDATE bookings SET updated_at = ? WHERE id = ?", (time.time(), booking_id))


    # ---- the private calendar feed ----------------------------------------------------------------------------------------------------------------------------

    def feed_token(self, user_id: str) -> str:
        """The secret in the person's calendar-feed address, made on first use. Anyone who holds it can read the person's trips, so it is shown only to them."""
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO calendar_feeds (user_id, token, created_at) VALUES (?, ?, ?)", (user_id, secrets.token_urlsafe(32), time.time()))
            return db.execute("SELECT token FROM calendar_feeds WHERE user_id = ?", (user_id,)).fetchone()["token"]

    def reset_feed_token(self, user_id: str) -> str:
        """A new secret; the old address stops working."""
        with self._connect() as db:
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO calendar_feeds (user_id, token, created_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET token = excluded.token, created_at = excluded.created_at",
                       (user_id, token, time.time()))
        return token

    def user_for_feed(self, token: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT u.id, u.name FROM calendar_feeds f JOIN users u ON u.id = f.user_id WHERE f.token = ?", (token,)).fetchone()
        return dict(row) if row else None

    def feed_trips(self, user_id: str, since: float, until: float) -> List[Dict[str, Any]]:
        """Trips of every approved boat the person belongs to that overlap [since, until), earliest first, each with the names aboard."""
        with self._connect() as db:
            rows = db.execute("SELECT k.id, k.boat_id, k.title, k.start_utc, k.end_utc, k.capacity, k.notes, k.updated_at, b.name AS boat_name, b.home_port, u.name AS created_by_name "
                              "FROM bookings k JOIN boats b ON b.id = k.boat_id AND b.status = 'approved' JOIN memberships m ON m.boat_id = b.id AND m.user_id = ? "
                              "JOIN users u ON u.id = k.created_by WHERE k.end_utc > ? AND k.start_utc < ? ORDER BY k.start_utc, k.id", (user_id, since, until)).fetchall()
            trips = [dict(r) for r in rows]
            for trip in trips:
                trip["aboard"] = [r["name"] for r in db.execute("SELECT u.name FROM signons s JOIN users u ON u.id = s.user_id WHERE s.booking_id = ? ORDER BY s.created_at, u.name", (trip["id"],))]
        return trips


_BOAT_SELECT = """SELECT b.id, b.name, b.home_port, b.description, b.timezone, b.status, b.created_by, b.created_at,
  (SELECT COUNT(*) FROM memberships m WHERE m.boat_id = b.id AND m.role = 'owner') AS owner_count,
  (SELECT COUNT(*) FROM memberships m WHERE m.boat_id = b.id AND m.role = 'crew') AS crew_count,
  (SELECT COALESCE(SUM(share_percent), 0) FROM memberships m WHERE m.boat_id = b.id AND m.role = 'owner') AS owner_share_total,
  (SELECT updated_at FROM boat_photos p WHERE p.boat_id = b.id) AS photo_updated
  FROM boats b"""

_REQUEST_SELECT = """SELECT r.id, r.boat_id, b.name AS boat_name, r.user_id, u.name AS user_name, r.role, r.share_percent, r.message, r.status, r.created_at
  FROM join_requests r JOIN boats b ON b.id = r.boat_id JOIN users u ON u.id = r.user_id"""


def _log_share(db: sqlite3.Connection, boat_id: str, user_id: str, old: Optional[float], new: Optional[float], when: float) -> None:
    db.execute("INSERT INTO share_history (boat_id, user_id, old_share, new_share, created_at) VALUES (?, ?, ?, ?, ?)", (boat_id, user_id, old, new, when))


def _check_share(share: Optional[float]) -> None:
    if share is None or not (0 < share <= 100):
        raise StoreError("an owner's share must be more than 0% and at most 100%")


def _check_times(start: float, end: float) -> None:
    if end - start < MIN_BOOKING_SECONDS:
        raise StoreError("a booking must last at least 15 minutes and end after it starts")
    if end - start > MAX_BOOKING_SECONDS:
        raise StoreError("a booking may last at most 30 days")


def _check_capacity(capacity: Optional[int], aboard: int) -> None:
    if capacity is not None and capacity < max(1, aboard):
        raise StoreError(f"the limit cannot be below the {max(1, aboard)} already aboard")


def _check_no_overlap(db: sqlite3.Connection, boat_id: str, start: float, end: float, ignore_id: Optional[str]) -> None:
    clash = db.execute("SELECT b.title, u.name FROM bookings b JOIN users u ON u.id = b.created_by WHERE b.boat_id = ? AND b.start_utc < ? AND b.end_utc > ? AND b.id IS NOT ? "
                       "ORDER BY b.start_utc LIMIT 1", (boat_id, end, start, ignore_id)).fetchone()
    if clash:
        raise StoreError(f"the boat is already booked then: {clash['title']} ({clash['name']})")
