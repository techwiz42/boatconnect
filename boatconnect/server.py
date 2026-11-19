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

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import auth, emails, ical, photos
from .config import Settings
from .mail import Mail, Mailer, NoMailer, SmtpMailer
from .store import BOAT_NAME_CHARS, NAME_CHARS, TEXT_CHARS, Store, StoreError

logger = logging.getLogger(__name__)

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
COOKIE = "boatconnect_session"
MAX_BODY_BYTES = 100_000
MAX_PHOTO_BYTES = 900_000                        # the browser scales a photo down before sending it; the web server in front allows 1 MB
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


class BoatEdit(BaseModel):
    name: str = Field(min_length=1, max_length=BOAT_NAME_CHARS)
    home_port: str = Field(min_length=1, max_length=BOAT_NAME_CHARS)
    description: str = Field(default="", max_length=TEXT_CHARS)
    timezone: str = Field(max_length=64)

    _tz = field_validator("timezone")(lambda cls, v: _zone(v))

    @field_validator("name", "home_port")
    @classmethod
    def _squash(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("this cannot be blank")
        return value


class BoatIn(BoatEdit):
    share_percent: float = Field(gt=0, le=100)


class ShareIn(BaseModel):
    share_percent: float = Field(gt=0, le=100)


class ForgotIn(BaseModel):
    email: str = Field(max_length=320)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=500)


class PreferencesIn(BaseModel):
    email_trips: bool


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


def create_app(store: Optional[Store] = None, cookie_secure: bool = False, admin_emails: Tuple[str, ...] = (), mailer: Optional[Mailer] = None,
               public_url: str = "https://boatconnect.org") -> FastAPI:
    login_failures = auth.Throttle(limit=5, window_seconds=15 * 60)         # per email
    address_failures = auth.Throttle(limit=30, window_seconds=15 * 60)      # per address
    registrations = auth.Throttle(limit=20, window_seconds=3600)            # per address
    boats_added = auth.Throttle(limit=5, window_seconds=24 * 3600)          # per user
    requests_made = auth.Throttle(limit=20, window_seconds=24 * 3600)       # per user
    bookings_made = auth.Throttle(limit=60, window_seconds=24 * 3600)       # per user
    photos_sent = auth.Throttle(limit=30, window_seconds=24 * 3600)         # per user
    feed_misses = auth.Throttle(limit=30, window_seconds=15 * 60)           # wrong feed addresses, per address
    forgot_by_address = auth.Throttle(limit=8, window_seconds=3600)         # password-reset requests, per address
    forgot_by_email = auth.Throttle(limit=3, window_seconds=3600)           # ... and per account, so one person cannot be flooded with reset mail
    reset_misses = auth.Throttle(limit=10, window_seconds=15 * 60)          # wrong or used reset links, per address
    unsubscribe_misses = auth.Throttle(limit=30, window_seconds=15 * 60)    # wrong unsubscribe links, per address

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.store is None:
            settings = Settings.from_env()
            app.state.store = Store(str(settings.data_dir / "boatconnect.db"))
            app.state.cookie_secure = settings.cookie_secure
            app.state.admin_emails = settings.admin_emails
            app.state.public_url = settings.public_url
            app.state.mailer = SmtpMailer(settings.mail_host, settings.mail_port, settings.mail_from, settings.mail_reply_to or None, starttls=settings.mail_starttls, username=settings.mail_user, password=settings.mail_password) if settings.mail_host else NoMailer()
        yield

    app = FastAPI(title="boatconnect", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.cookie_secure = cookie_secure
    app.state.admin_emails = tuple(e.lower() for e in admin_emails)
    app.state.mailer = mailer or NoMailer()
    app.state.public_url = public_url.rstrip("/")

    @app.middleware("http")
    async def protect(request: Request, call_next):
        declared = request.headers.get("content-length")
        allowed = MAX_PHOTO_BYTES if request.method == "PUT" and request.url.path.endswith("/photo") else MAX_BODY_BYTES
        if declared and declared.isdigit() and int(declared) > allowed:
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
        return {"id": user["id"], "email": user["email"], "name": user["name"], "is_admin": is_admin(user), "email_trips": bool(user.get("email_trips", 1))}

    def queue(background: BackgroundTasks, addresses: Any, mail: Mail) -> None:
        """Send after the response has gone, so a slow mail server never holds a request up; nothing happens when no relay is configured."""
        if app.state.mailer.enabled and addresses:
            background.add_task(app.state.mailer.send, list(addresses), mail)

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

    @app.patch("/api/auth/preferences", dependencies=[Depends(same_origin)])
    async def preferences(body: PreferencesIn, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
        await app.state.store.run(app.state.store.set_email_trips, user["id"], body.email_trips)
        return {**person(user), "email_trips": body.email_trips}

    @app.post("/api/unsubscribe/{token}")
    async def unsubscribe(token: str, request: Request) -> Dict[str, bool]:
        """The one-click link in a trip email (a mail program may post to it without anyone logging in): the secret in the address says whose emails to stop."""
        where = address(request)
        if unsubscribe_misses.blocked(where):
            raise HTTPException(status_code=429, detail="too many wrong links", headers={"Retry-After": str(unsubscribe_misses.retry_after(where))})
        if not await app.state.store.run(app.state.store.unsubscribe_trips, token):
            unsubscribe_misses.add(where)
            raise HTTPException(status_code=404, detail="that link is not valid")
        return {"ok": True}

    @app.post("/api/auth/forgot", status_code=202, dependencies=[Depends(same_origin)])
    async def forgot_password(body: ForgotIn, request: Request, background: BackgroundTasks) -> Dict[str, bool]:
        """Mail a link to choose a new password. The answer is the same whether or not the address has an account, so this cannot be used to find out who is registered."""
        if not app.state.mailer.enabled:
            raise HTTPException(status_code=503, detail="email is not set up here, so passwords cannot be reset by email; ask the administrator")
        where = address(request)
        limit(forgot_by_address, where, "password-reset requests from here")
        forgot_by_address.add(where)
        try:
            email = auth.normalize_email(body.email)
        except auth.AuthError:
            return {"ok": True}
        if forgot_by_email.blocked(email):
            return {"ok": True}                                                    # quietly: do not tell a stranger that this address was asked about already
        forgot_by_email.add(email)
        account = await app.state.store.run(app.state.store.user_by_email, email)
        if account:
            token, hashed = auth.new_token()
            await app.state.store.run(app.state.store.create_password_reset, account["id"], hashed, 3600)
            queue(background, [account["email"]], emails.password_reset(account["name"], f"{app.state.public_url}/reset?token={token}"))
        return {"ok": True}

    @app.post("/api/auth/reset", dependencies=[Depends(same_origin)])
    async def reset_password(body: ResetIn, request: Request) -> Dict[str, bool]:
        where = address(request)
        limit(reset_misses, where, "wrong reset links")
        try:
            auth.check_password(body.password)
        except auth.AuthError as error:
            raise HTTPException(status_code=422, detail=str(error))
        new_hash = await asyncio.to_thread(auth.hash_password, body.password)
        try:
            await app.state.store.run(app.state.store.reset_password, auth.hash_token(body.token), new_hash)
        except StoreError as error:
            reset_misses.add(where)
            raise HTTPException(status_code=409, detail=str(error))
        return {"ok": True}

    # ---- boats -------------------------------------------------------------------------------------------------------------------------------------------------

    async def describe(boat: Dict[str, Any], user: Optional[Dict[str, Any]], roles: Optional[Dict[str, str]] = None, waiting: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """A boat as the viewer may see it: public facts, and the viewer's own standing with it."""
        if user and roles is None:
            roles = await app.state.store.run(app.state.store.roles_of_user, user["id"])
            waiting = await app.state.store.run(app.state.store.pending_requests_of_user, user["id"])
        request = (waiting or {}).get(boat["id"])
        return {"id": boat["id"], "name": boat["name"], "home_port": boat["home_port"], "description": boat["description"], "timezone": boat["timezone"],
                "status": boat["status"], "owner_count": boat["owner_count"], "crew_count": boat["crew_count"],
                "photo": {"version": int(boat["photo_updated"])} if boat["photo_updated"] else None,        # the picture is at /api/boats/{id}/photo?v=<version>
                "unallocated_percent": max(0.0, round(100.0 - boat["owner_share_total"], 6)),           # how much of the boat no owner holds yet: room for a new owner
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
    async def add_boat(body: BoatIn, background: BackgroundTasks, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, str]:
        limit(boats_added, user["id"], "boats")
        boat_id = await db(app.state.store.create_boat, user["id"], body.name, body.home_port, body.description, body.timezone, body.share_percent)
        boats_added.add(user["id"])
        queue(background, [a for a in app.state.admin_emails if a != user["email"]], emails.boat_waiting(body.name, user["name"], app.state.public_url))
        return {"id": boat_id}

    @app.get("/api/boats/{boat_id}")
    async def boat_page(boat_id: str, user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
        boat = await visible_boat(boat_id, user)
        out = await describe(boat, user)
        if out["my_role"] or is_admin(user):
            out["members"] = await app.state.store.run(app.state.store.members, boat_id)         # who belongs, and the owners' shares, is for members only
            out["share_history"] = await app.state.store.run(app.state.store.share_history, boat_id)
        return out

    @app.patch("/api/boats/{boat_id}", dependencies=[Depends(same_origin)])
    async def edit_boat(boat_id: str, body: BoatEdit, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        """Only an owner changes the boat's details (even before it is approved). Crew, strangers and the administrator may not."""
        await visible_boat(boat_id, user)
        if await app.state.store.run(app.state.store.role_of, boat_id, user["id"]) != "owner":
            raise HTTPException(status_code=403, detail="only an owner may change the boat's details")
        await db(app.state.store.update_boat, boat_id, body.name, body.home_port, body.description, body.timezone)
        return {"ok": True}

    @app.patch("/api/boats/{boat_id}/my-share", dependencies=[Depends(same_origin)])
    async def change_my_share(boat_id: str, body: ShareIn, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        """An owner changes their own share: lowering it makes room for another owner (who is then approved as usual); raising it only takes room nobody holds."""
        await visible_boat(boat_id, user)
        await db(app.state.store.set_share, boat_id, user["id"], body.share_percent)
        return {"ok": True}

    async def owner_of(boat_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        boat = await visible_boat(boat_id, user)
        if await app.state.store.run(app.state.store.role_of, boat_id, user["id"]) != "owner":
            raise HTTPException(status_code=403, detail="only an owner may change the boat's photo")
        return boat

    @app.put("/api/boats/{boat_id}/photo", dependencies=[Depends(same_origin)])
    async def put_photo(boat_id: str, request: Request, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
        """An owner sets the boat's photo: the request body is the image file. It is checked and re-encoded as a small JPEG before it is kept."""
        await owner_of(boat_id, user)
        limit(photos_sent, user["id"], "photo uploads")
        body = bytearray()
        async for chunk in request.stream():                                      # read with a ceiling, whatever the request claims about its size
            body += chunk
            if len(body) > MAX_PHOTO_BYTES:
                raise HTTPException(status_code=413, detail="that photo is too large; choose a smaller one")
        try:
            data = await asyncio.to_thread(photos.process_photo, bytes(body))
        except photos.PhotoError as error:
            raise HTTPException(status_code=422, detail=str(error))
        await db(app.state.store.set_photo, boat_id, data)
        photos_sent.add(user["id"])
        stored = await app.state.store.run(app.state.store.get_photo, boat_id)
        return {"version": int(stored["updated_at"])}

    @app.delete("/api/boats/{boat_id}/photo", dependencies=[Depends(same_origin)])
    async def delete_photo(boat_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        await owner_of(boat_id, user)
        await app.state.store.run(app.state.store.delete_photo, boat_id)
        return {"ok": True}

    @app.get("/api/boats/{boat_id}/photo")
    async def get_photo(boat_id: str, request: Request, user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Response:
        """The photo of an approved boat is public (the boat list shows it); a boat that is not approved shows its photo only to its members and the administrator."""
        await visible_boat(boat_id, user)
        photo = await app.state.store.run(app.state.store.get_photo, boat_id)
        if photo is None:
            raise HTTPException(status_code=404, detail="no photo")
        etag = f'"{int(photo["updated_at"])}-{len(photo["data"])}"'
        headers = {"ETag": etag, "Cache-Control": "public, max-age=3600"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(content=photo["data"], media_type="image/jpeg", headers=headers)

    @app.post("/api/boats/{boat_id}/join-requests", status_code=201, dependencies=[Depends(same_origin)])
    async def join(boat_id: str, body: JoinIn, background: BackgroundTasks, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, str]:
        limit(requests_made, user["id"], "requests")
        boat = await visible_boat(boat_id, user)
        request_id = await db(app.state.store.request_join, boat_id, user["id"], body.role, body.share_percent, body.message.strip())
        requests_made.add(user["id"])
        if body.role == "owner":
            deciders = list(app.state.admin_emails)                                  # a new owner is the administrator's to approve
        else:
            deciders = [o["email"] for o in await app.state.store.run(app.state.store.boat_owners, boat_id)]       # a new crew member, the owners'
        queue(background, [a for a in deciders if a != user["email"]], emails.join_request(user["name"], boat["name"], body.role, body.share_percent, body.message.strip(), app.state.public_url))
        return {"id": request_id}

    @app.delete("/api/boats/{boat_id}/members/{member_id}", dependencies=[Depends(same_origin)])
    async def remove_member(boat_id: str, member_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        """A member may leave. An owner may remove crew. An owner leaves only by their own choice: another owner cannot remove them, only the administrator can."""
        await visible_boat(boat_id, user)
        if member_id != user["id"] and not is_admin(user):
            mine = await app.state.store.run(app.state.store.role_of, boat_id, user["id"])
            theirs = await app.state.store.run(app.state.store.role_of, boat_id, member_id)
            if not (mine == "owner" and theirs == "crew"):
                raise HTTPException(status_code=403, detail="an owner may remove crew; an owner leaves only by their own choice, or the administrator removes them")
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
    async def decide_boat(boat_id: str, body: Decision, background: BackgroundTasks, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        if not is_admin(user):
            raise HTTPException(status_code=403, detail="only the administrator approves boats")
        await db(app.state.store.decide_boat, boat_id, body.approve)
        boat = await app.state.store.run(app.state.store.get_boat, boat_id)
        maker = await app.state.store.run(app.state.store.user_by_id, boat["created_by"]) if boat else None
        if maker and maker["id"] != user["id"]:
            queue(background, [maker["email"]], emails.boat_decision(boat["name"], body.approve, app.state.public_url, boat_id))
        return {"ok": True}

    @app.post("/api/join-requests/{request_id}/decision", dependencies=[Depends(same_origin)])
    async def decide_request(request_id: str, body: Decision, background: BackgroundTasks, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
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
        asker = await store.run(store.user_by_id, req["user_id"])
        if asker and asker["id"] != user["id"]:
            queue(background, [asker["email"]], emails.request_decision(req["boat_name"], req["role"], body.approve, app.state.public_url, req["boat_id"]))
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
    async def book(boat_id: str, body: BookingIn, background: BackgroundTasks, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, str]:
        role = await member_of(boat_id, user)
        if role != "owner":
            raise HTTPException(status_code=403, detail="only an owner books the boat; crew sign on to an owner's trip")
        limit(bookings_made, user["id"], "bookings")
        booking_id = await db(app.state.store.create_booking, boat_id, user["id"], body.title, body.start, body.end, body.capacity, body.notes.strip())
        bookings_made.add(user["id"])
        await trip_mail(background, "booked", user, boat_id, body.title, body.start, body.end)
        return {"id": booking_id}

    async def trip_mail(background: BackgroundTasks, kind: str, actor: Dict[str, Any], boat_id: str, title: str, start: float, end: float) -> None:
        """Tell the other members who want to hear about trips that this one was booked, changed or cancelled; each gets a mail with their own unsubscribe link."""
        if not app.state.mailer.enabled:
            return
        store, base = app.state.store, app.state.public_url
        boat = await store.run(store.get_boat, boat_id)
        span = emails.when(start, end, boat["timezone"])
        for r in await store.run(store.trip_recipients, boat_id, actor["id"]):
            queue(background, [r["email"]], emails.trip_notice(kind, actor["name"], boat["name"], title, span, base, boat_id,
                                                               f"{base}/api/unsubscribe/{r['mail_token']}", f"{base}/unsubscribe?token={r['mail_token']}"))

    async def booking_for(booking_id: str, user: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        booking = await app.state.store.run(app.state.store.get_booking, booking_id)
        if not booking:
            raise HTTPException(status_code=404, detail="no such booking")
        return booking, await member_of(booking["boat_id"], user)

    @app.patch("/api/bookings/{booking_id}", dependencies=[Depends(same_origin)])
    async def change_booking(booking_id: str, body: BookingIn, background: BackgroundTasks, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        booking, role = await booking_for(booking_id, user)
        if booking["created_by"] != user["id"] and role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="only the person who made it, or an owner, may change this booking")
        await db(app.state.store.update_booking, booking_id, body.title, body.start, body.end, body.capacity, body.notes.strip())
        if (booking["title"], booking["start_utc"], booking["end_utc"]) != (body.title, body.start, body.end):            # a change to the notes or the limit alone is not worth an email
            await trip_mail(background, "changed", user, booking["boat_id"], body.title, body.start, body.end)
        return {"ok": True}

    @app.delete("/api/bookings/{booking_id}", dependencies=[Depends(same_origin)])
    async def cancel_booking(booking_id: str, background: BackgroundTasks, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, bool]:
        booking, role = await booking_for(booking_id, user)
        if booking["created_by"] != user["id"] and role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="only the person who made it, or an owner, may cancel this booking")
        await app.state.store.run(app.state.store.delete_booking, booking_id)
        await trip_mail(background, "cancelled", user, booking["boat_id"], booking["title"], booking["start_utc"], booking["end_utc"])
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

    # ---- the private calendar feed ----------------------------------------------------------------------------------------------------------------------------

    FEED_PAST_SECONDS = 30 * 24 * 3600
    FEED_FUTURE_SECONDS = 400 * 24 * 3600

    @app.get("/api/calendar-feed")
    async def calendar_feed_link(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, str]:
        """The path of this person's private feed (made on first use). A calendar app cannot log in, so the secret is in the address."""
        token = await app.state.store.run(app.state.store.feed_token, user["id"])
        return {"path": f"/api/calendar/{token}.ics"}

    @app.post("/api/calendar-feed/reset", dependencies=[Depends(same_origin)])
    async def calendar_feed_reset(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, str]:
        token = await app.state.store.run(app.state.store.reset_feed_token, user["id"])
        return {"path": f"/api/calendar/{token}.ics"}

    @app.get("/api/calendar/{filename}")
    async def calendar_feed(filename: str, request: Request) -> PlainTextResponse:
        """The feed itself: the trips of every boat the person belongs to, as an .ics file. No login; the secret in the address is the proof."""
        where = address(request)
        if feed_misses.blocked(where):
            raise HTTPException(status_code=429, detail="too many wrong addresses", headers={"Retry-After": str(feed_misses.retry_after(where))})
        token = filename[:-4] if filename.endswith(".ics") else ""
        user = await app.state.store.run(app.state.store.user_for_feed, token) if 20 <= len(token) <= 100 else None
        if user is None:
            feed_misses.add(where)
            raise HTTPException(status_code=404, detail="no such calendar")
        now = time.time()
        trips = await app.state.store.run(app.state.store.feed_trips, user["id"], now - FEED_PAST_SECONDS, now + FEED_FUTURE_SECONDS)
        base = f"{request.url.scheme}://{request.headers.get('host', 'boatconnect.org')}"
        return PlainTextResponse(ical.build_calendar(trips, base), media_type="text/calendar; charset=utf-8",
                                 headers={"Cache-Control": "private, max-age=600", "Content-Disposition": 'inline; filename="boatconnect.ics"'})

    @app.get("/api/healthz")
    async def healthz() -> Dict[str, bool]:
        return {"ok": True}

    if WEB_DIST.is_dir():                         # the built frontend, when there is one
        app.mount("/", WebFiles(directory=WEB_DIST, html=True), name="web")
    return app


app = create_app()
