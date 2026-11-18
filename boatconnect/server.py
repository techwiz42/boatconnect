"""The web service: accounts, boats, join requests, bookings and sign-ons, all under /api, and the built frontend for every other address.

Who may do what:
  * anyone may read the list of approved boats;
  * a registered user may add a boat (it waits for the administrator) and ask to join an approved one, as owner or as crew;
  * the administrator (ADMIN_EMAILS) approves boats and owner requests; the owners of a boat approve its crew requests (the administrator may too);
  * a member of a boat sees its calendar; only an owner makes a booking; any member signs on to one.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import auth
from .config import Settings
from .store import BOAT_NAME_CHARS, NAME_CHARS, TEXT_CHARS, Store, StoreError

logger = logging.getLogger(__name__)

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
COOKIE = "boatconnect_session"
MAX_BODY_BYTES = 100_000
MAX_CALENDAR_SPAN_SECONDS = 100 * 24 * 3600

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                               "form-action 'self'; frame-ancestors 'none'; object-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


class WebFiles(StaticFiles):
    """The built frontend. A page that is not a file (/boats/abc, /login) is the app's own route, so it gets index.html; the hashed files under /assets are kept for a
    year, everything else is re-checked on every load so a deploy shows up on a plain reload."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except Exception:
            response = None
        if response is None or response.status_code == 404:
            if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
                raise HTTPException(status_code=404)
            response = FileResponse(WEB_DIST / "index.html")
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return response


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=500)


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=NAME_CHARS)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("enter your name")
        return value


def _zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError("that is not a time zone name such as America/Los_Angeles")
    return value


class BoatIn(BaseModel):
    name: str = Field(min_length=1, max_length=BOAT_NAME_CHARS)
    home_port: str = Field(min_length=1, max_length=BOAT_NAME_CHARS)
    description: str = Field(default="", max_length=TEXT_CHARS)
    timezone: str = Field(max_length=64)
    share_percent: float = Field(gt=0, le=100)

    _tz = field_validator("timezone")(lambda cls, v: _zone(v))

    @field_validator("name", "home_port")
    @classmethod
    def _squash(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("this cannot be blank")
        return value


class JoinIn(BaseModel):
    role: str = Field(pattern="^(owner|crew)$")
    share_percent: Optional[float] = Field(default=None, gt=0, le=100)
    message: str = Field(default="", max_length=500)


class Decision(BaseModel):
    approve: bool


class BookingIn(BaseModel):
    title: str = Field(min_length=1, max_length=BOAT_NAME_CHARS)
    start: float
    end: float
    capacity: Optional[int] = Field(default=None, ge=1, le=100)
    notes: str = Field(default="", max_length=1000)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("give the trip a title")
        return value


def create_app(store: Optional[Store] = None, cookie_secure: bool = False, admin_emails: Tuple[str, ...] = ()) -> FastAPI:
    login_failures = auth.Throttle(limit=5, window_seconds=15 * 60)         # per email
    address_failures = auth.Throttle(limit=30, window_seconds=15 * 60)      # per address
    registrations = auth.Throttle(limit=20, window_seconds=3600)            # per address
    boats_added = auth.Throttle(limit=5, window_seconds=24 * 3600)          # per user
    requests_made = auth.Throttle(limit=20, window_seconds=24 * 3600)       # per user
    bookings_made = auth.Throttle(limit=60, window_seconds=24 * 3600)       # per user

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.store is None:
            settings = Settings.from_env()
            app.state.store = Store(str(settings.data_dir / "boatconnect.db"))
            app.state.cookie_secure = settings.cookie_secure
            app.state.admin_emails = settings.admin_emails
        yield

    app = FastAPI(title="boatconnect", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.cookie_secure = cookie_secure
    app.state.admin_emails = tuple(e.lower() for e in admin_emails)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            response: Response = Response(status_code=413, content='{"detail":"request too large"}', media_type="application/json")
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if app.state.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    # ---- guards ------------------------------------------------------------------------------------------------------------------------------------------------

    def same_origin(request: Request) -> None:
        """A browser sends Origin on a cross-site request; it must be this server's own address."""
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host", ""):
            raise HTTPException(status_code=403, detail="cross-origin request refused")

    async def optional_user(request: Request) -> Optional[Dict[str, Any]]:
        token = request.cookies.get(COOKIE)
        return await app.state.store.run(app.state.store.user_for_login, auth.hash_token(token)) if token else None

    async def current_user(user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
        if user is None:
            raise HTTPException(status_code=401, detail="log in first")
        return user

    def is_admin(user: Optional[Dict[str, Any]]) -> bool:
        return bool(user) and user["email"] in app.state.admin_emails

    def address(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def limit(throttle: auth.Throttle, key: str, what: str) -> None:
        if throttle.blocked(key):
            raise HTTPException(status_code=429, detail=f"you have made too many {what} today; try again tomorrow", headers={"Retry-After": str(throttle.retry_after(key))})

    async def db(function, *args, **kwargs):
        """Run a store call; what the store refuses becomes a 409 whose message the user may read."""
        try:
            return await app.state.store.run(function, *args, **kwargs)
        except StoreError as error:
            raise HTTPException(status_code=409, detail=str(error))

    def start_login(response: Response, token: str) -> None:
        response.set_cookie(COOKIE, token, max_age=int(auth.LOGIN_LIFETIME_SECONDS), httponly=True, samesite="strict", secure=app.state.cookie_secure, path="/")

    def person(user: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": user["id"], "email": user["email"], "name": user["name"], "is_admin": is_admin(user)}

    # ---- accounts ----------------------------------------------------------------------------------------------------------------------------------------------

    @app.post("/api/auth/register", status_code=201, dependencies=[Depends(same_origin)])
    async def register(body: Registration, request: Request, response: Response) -> Dict[str, Any]:
        where = address(request)
        limit(registrations, where, "registrations from here")
        try:
            email = auth.normalize_email(body.email)
            auth.check_password(body.password)
        except auth.AuthError as error:
            raise HTTPException(status_code=422, detail=str(error))
        password_hash = await asyncio.to_thread(auth.hash_password, body.password)
        user_id = await db(app.state.store.create_user, email, body.name, password_hash)
        registrations.add(where)
        token, hashed = auth.new_token()
        await app.state.store.run(app.state.store.create_login, user_id, hashed, auth.LOGIN_LIFETIME_SECONDS)
        start_login(response, token)
        return person({"id": user_id, "email": email, "name": body.name})

    @app.post("/api/auth/login", dependencies=[Depends(same_origin)])
    async def login(body: Credentials, request: Request, response: Response) -> Dict[str, Any]:
        where = address(request)
        try:
            email = auth.normalize_email(body.email)
        except auth.AuthError:
            raise HTTPException(status_code=401, detail="wrong email or password")
        for throttle, key in ((login_failures, email), (address_failures, where)):
            if throttle.blocked(key):
                raise HTTPException(status_code=429, detail="too many failed attempts; try again later", headers={"Retry-After": str(throttle.retry_after(key))})
        user = await app.state.store.run(app.state.store.user_by_email, email)
        ok = await asyncio.to_thread(auth.verify_password, body.password, user["password_hash"] if user else None)
        if not (ok and user):
            login_failures.add(email)
            address_failures.add(where)
            raise HTTPException(status_code=401, detail="wrong email or password")
        login_failures.clear(email)
        token, hashed = auth.new_token()
        await app.state.store.run(app.state.store.create_login, user["id"], hashed, auth.LOGIN_LIFETIME_SECONDS)
        start_login(response, token)
        return person(user)

    @app.post("/api/auth/logout", dependencies=[Depends(same_origin)])
    async def logout(request: Request, response: Response) -> Dict[str, bool]:
        token = request.cookies.get(COOKIE)
        if token:
            await app.state.store.run(app.state.store.end_login, auth.hash_token(token))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    async def me(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
        return person(user)

    # ---- boats -------------------------------------------------------------------------------------------------------------------------------------------------

    async def describe(boat: Dict[str, Any], user: Optional[Dict[str, Any]], roles: Optional[Dict[str, str]] = None, waiting: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """A boat as the viewer may see it: public facts, and the viewer's own standing with it."""
        if user and roles is None:
            roles = await app.state.store.run(app.state.store.roles_of_user, user["id"])
            waiting = await app.state.store.run(app.state.store.pending_requests_of_user, user["id"])
        request = (waiting or {}).get(boat["id"])
        return {"id": boat["id"], "name": boat["name"], "home_port": boat["home_port"], "description": boat["description"], "timezone": boat["timezone"],
                "status": boat["status"], "owner_count": boat["owner_count"], "crew_count": boat["crew_count"],
                "my_role": (roles or {}).get(boat["id"]),
                "my_request": {"id": request["id"], "role": request["role"], "share_percent": request["share_percent"]} if request else None}

    async def visible_boat(boat_id: str, user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """An approved boat is public. One that is not is seen only by its members and the administrator; to anyone else it does not exist."""
        boat = await app.state.store.run(app.state.store.get_boat, boat_id)
        if boat and boat["status"] != "approved":
            if not (is_admin(user) or (user and await app.state.store.run(app.state.store.role_of, boat_id, user["id"]))):
                boat = None
        if not boat:
            raise HTTPException(status_code=404, detail="no such boat")
        return boat

    @app.get("/api/boats")
    async def list_boats(user: Optional[Dict[str, Any]] = Depends(optional_user)) -> List[Dict[str, Any]]:
        store = app.state.store
        boats = await store.run(store.approved_boats)
        roles = waiting = None
        if user:
            roles, waiting = await store.run(store.roles_of_user, user["id"]), await store.run(store.pending_requests_of_user, user["id"])
            seen = {b["id"] for b in boats}
            boats += [b for b in await store.run(store.boats_of_user, user["id"]) if b["id"] not in seen]       # the user's own boats that are not approved yet
        return [await describe(b, user, roles or {}, waiting or {}) for b in boats]

    @app.post("/api/boats", status_code=201, dependencies=[Depends(same_origin)])
    async def add_boat(body: BoatIn, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, str]:
        limit(boats_added, user["id"], "boats")
        boat_id = await db(app.state.store.create_boat, user["id"], body.name, body.home_port, body.description, body.timezone, body.share_percent)
        boats_added.add(user["id"])
        return {"id": boat_id}

    @app.get("/api/boats/{boat_id}")
    async def boat_page(boat_id: str, user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
        boat = await visible_boat(boat_id, user)
        out = await describe(boat, user)
        if out["my_role"] or is_admin(user):
            out["members"] = await app.state.store.run(app.state.store.members, boat_id)         # who belongs, and the owners' shares, is for members only
        return out

    @app.post("/api/boats/{boat_id}/join-requests", status_code=201, dependencies=[Depends(same_origin)])
    async def join(boat_id: str, body: JoinIn, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, str]:
        limit(requests_made, user["id"], "requests")
        await visible_boat(boat_id, user)
        request_id = await db(app.state.store.request_join, boat_id, user["id"], body.role, body.share_percent, body.message.strip())
        requests_made.add(user["id"])
        return {"id": request_id}

    @app.delete("/api/boats/{boat_id}/members/{member_id}", dependencies=[Depends(same_origin)])
    async def remove_member(boat_id: str, member_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        await visible_boat(boat_id, user)
        mine = await app.state.store.run(app.state.store.role_of, boat_id, user["id"])
        if member_id != user["id"] and mine != "owner" and not is_admin(user):
            raise HTTPException(status_code=403, detail="only an owner may remove someone from the boat")
        await db(app.state.store.remove_member, boat_id, member_id)
        return {"ok": True}

    # ---- decisions: the administrator's and the owners' ---------------------------------------------------------------------------------------------------------

    @app.get("/api/inbox")
    async def inbox(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
        """What waits for this person to decide: for the administrator, new boats and every request; for an owner, the crew requests for their boats."""
        store = app.state.store
        if is_admin(user):
            boats = [{"id": b["id"], "name": b["name"], "home_port": b["home_port"], "description": b["description"], "timezone": b["timezone"]} for b in await store.run(store.pending_boats)]
            requests = await store.run(store.pending_requests)
        else:
            roles = await store.run(store.roles_of_user, user["id"])
            boats, requests = [], await store.run(store.pending_requests, [b for b, r in roles.items() if r == "owner"], "crew")
        return {"boats": boats, "requests": requests}

    @app.post("/api/boats/{boat_id}/decision", dependencies=[Depends(same_origin)])
    async def decide_boat(boat_id: str, body: Decision, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        if not is_admin(user):
            raise HTTPException(status_code=403, detail="only the administrator approves boats")
        await db(app.state.store.decide_boat, boat_id, body.approve)
        return {"ok": True}

    @app.post("/api/join-requests/{request_id}/decision", dependencies=[Depends(same_origin)])
    async def decide_request(request_id: str, body: Decision, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        store = app.state.store
        req = await store.run(store.get_request, request_id)
        if not req:
            raise HTTPException(status_code=404, detail="no such request")
        if req["role"] == "owner":
            allowed = is_admin(user)                                                 # a new owner is the administrator's to approve
        else:
            allowed = is_admin(user) or await store.run(store.role_of, req["boat_id"], user["id"]) == "owner"
        if not allowed:
            raise HTTPException(status_code=403, detail="you may not decide this request")
        await db(store.decide_request, request_id, user["id"], body.approve)
        return {"ok": True}

    # ---- the calendar ------------------------------------------------------------------------------------------------------------------------------------------

    async def member_of(boat_id: str, user: Dict[str, Any]) -> str:
        boat = await visible_boat(boat_id, user)
        role = await app.state.store.run(app.state.store.role_of, boat_id, user["id"])
        if not role and not is_admin(user):
            raise HTTPException(status_code=403, detail="the calendar is for the boat's members")
        if boat["status"] != "approved":
            raise HTTPException(status_code=409, detail="this boat is waiting for approval")
        return role or "admin"

    def booking_json(b: Dict[str, Any], user: Dict[str, Any], role: str) -> Dict[str, Any]:
        mine = any(a["user_id"] == user["id"] for a in b["aboard"])
        return {"id": b["id"], "title": b["title"], "start": b["start_utc"], "end": b["end_utc"], "capacity": b["capacity"], "notes": b["notes"],
                "created_by": b["created_by"], "created_by_name": b["created_by_name"], "aboard": b["aboard"], "i_am_aboard": mine,
                "can_edit": b["created_by"] == user["id"] or role in ("owner", "admin")}

    @app.get("/api/boats/{boat_id}/bookings")
    async def bookings(boat_id: str, start: float = Query(), end: float = Query(), user: Dict[str, Any] = Depends(current_user)) -> List[Dict[str, Any]]:
        role = await member_of(boat_id, user)
        if not 0 < end - start <= MAX_CALENDAR_SPAN_SECONDS:
            raise HTTPException(status_code=422, detail="ask for at most 100 days at a time")
        rows = await app.state.store.run(app.state.store.bookings_between, boat_id, start, end)
        return [booking_json(b, user, role) for b in rows]

    @app.post("/api/boats/{boat_id}/bookings", status_code=201, dependencies=[Depends(same_origin)])
    async def book(boat_id: str, body: BookingIn, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, str]:
        role = await member_of(boat_id, user)
        if role != "owner":
            raise HTTPException(status_code=403, detail="only an owner books the boat; crew sign on to an owner's trip")
        limit(bookings_made, user["id"], "bookings")
        booking_id = await db(app.state.store.create_booking, boat_id, user["id"], body.title, body.start, body.end, body.capacity, body.notes.strip())
        bookings_made.add(user["id"])
        return {"id": booking_id}

    async def booking_for(booking_id: str, user: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        booking = await app.state.store.run(app.state.store.get_booking, booking_id)
        if not booking:
            raise HTTPException(status_code=404, detail="no such booking")
        return booking, await member_of(booking["boat_id"], user)

    @app.patch("/api/bookings/{booking_id}", dependencies=[Depends(same_origin)])
    async def change_booking(booking_id: str, body: BookingIn, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        booking, role = await booking_for(booking_id, user)
        if booking["created_by"] != user["id"] and role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="only the person who made it, or an owner, may change this booking")
        await db(app.state.store.update_booking, booking_id, body.title, body.start, body.end, body.capacity, body.notes.strip())
        return {"ok": True}

    @app.delete("/api/bookings/{booking_id}", dependencies=[Depends(same_origin)])
    async def cancel_booking(booking_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        booking, role = await booking_for(booking_id, user)
        if booking["created_by"] != user["id"] and role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="only the person who made it, or an owner, may cancel this booking")
        await app.state.store.run(app.state.store.delete_booking, booking_id)
        return {"ok": True}

    @app.post("/api/bookings/{booking_id}/signon", dependencies=[Depends(same_origin)])
    async def sign_on(booking_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        booking, role = await booking_for(booking_id, user)
        if role == "admin":
            raise HTTPException(status_code=403, detail="only the boat's owners and crew sign on to trips")
        await db(app.state.store.sign_on, booking_id, user["id"])
        return {"ok": True}

    @app.delete("/api/bookings/{booking_id}/signon/{member_id}", dependencies=[Depends(same_origin)])
    async def sign_off(booking_id: str, member_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        booking, role = await booking_for(booking_id, user)
        if member_id != user["id"] and booking["created_by"] != user["id"] and role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="you may sign yourself off; the trip's maker or an owner may sign others off")
        await db(app.state.store.sign_off, booking_id, member_id)
        return {"ok": True}

    @app.get("/api/healthz")
    async def healthz() -> Dict[str, bool]:
        return {"ok": True}

    if WEB_DIST.is_dir():                         # the built frontend, when there is one
        app.mount("/", WebFiles(directory=WEB_DIST, html=True), name="web")
    return app


app = create_app()
