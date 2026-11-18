"""Fills a local boatconnect server with sample people, boats and trips, so there is something to look at.

    DATA_DIR=/tmp/bc-data ADMIN_EMAILS=admin@example.com .venv/bin/uvicorn boatconnect.server:app --port 8001
    .venv/bin/python scripts/seed-demo.py            # then open http://127.0.0.1:8001 and log in as sam@example.com (password: correct horse battery)

Only for a fresh, empty database on your own machine: it registers fixed accounts with a known password.
"""
import os, sys, datetime as dt
from zoneinfo import ZoneInfo
import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:8001")
LA = ZoneInfo("America/Los_Angeles")
PW = "correct horse battery"

def person(email, name):
    c = httpx.Client(base_url=BASE)
    r = c.post("/api/auth/register", json={"email": email, "name": name, "password": PW})
    assert r.status_code == 201, r.text
    return c

def epoch(y, m, d, h, mi=0):
    return int(dt.datetime(y, m, d, h, mi, tzinfo=LA).timestamp())

admin = person("admin@example.com", "Site Admin")
sam, olly, cass, dan = person("sam@example.com", "Sam Skipper"), person("olly@example.com", "Olly Owner"), person("cass@example.com", "Cass Crew"), person("dan@example.com", "Dan Deckhand")

def boat(c, name, port, desc, share, approve=True):
    r = c.post("/api/boats", json={"name": name, "home_port": port, "description": desc, "timezone": "America/Los_Angeles", "share_percent": share}); assert r.status_code == 201, r.text
    bid = r.json()["id"]
    if approve: assert admin.post(f"/api/boats/{bid}/decision", json={"approve": True}).status_code == 200
    return bid

scooter = boat(sam, "Scooter", "Marina del Rey, CA", "J/35, 1985. Berth B-12. Spinnaker and full racing sail inventory; cruises to Catalina most summers.", 50)
boat(olly, "Wind Dancer", "Newport Beach, CA", "Beneteau 40 shared by four families. Weekend cruising.", 25)
boat(dan, "Sea Biscuit", "San Diego, CA", "Catalina 30 looking for owners to share costs.", 100, approve=False)

r = olly.post(f"/api/boats/{scooter}/join-requests", json={"role": "owner", "share_percent": 30, "message": "Co-owner since 2024"}); assert r.status_code == 201, r.text
assert admin.post(f"/api/join-requests/{r.json()['id']}/decision", json={"approve": True}).status_code == 200
for c in (cass,):
    r = c.post(f"/api/boats/{scooter}/join-requests", json={"role": "crew", "message": "Keen to learn"}); assert r.status_code == 201
    assert sam.post(f"/api/join-requests/{r.json()['id']}/decision", json={"approve": True}).status_code == 200
r = dan.post(f"/api/boats/{scooter}/join-requests", json={"role": "crew", "message": "Happy to crew weekends"}); assert r.status_code == 201   # left waiting

def trip(c, title, a, b, cap=None, notes=""):
    r = c.post(f"/api/boats/{scooter}/bookings", json={"title": title, "start": a, "end": b, "capacity": cap, "notes": notes})
    assert r.status_code == 201, r.text
    return r.json()["id"]

today = dt.datetime.now(LA)                 # the trips fall in the current month and the next, whichever they are
Y, M = today.year, today.month
NY, NM = (Y + 1, 1) if M == 12 else (Y, M + 1)
t1 = trip(sam, "Catalina weekend", epoch(Y, M, 6, 8), epoch(Y, M, 8, 17), 6, "Leaving the dock at 8. Bring warm layers.")
trip(olly, "Sunset sail", epoch(Y, M, 12, 16), epoch(Y, M, 12, 19), 4)
trip(sam, "Race practice", epoch(Y, M, 14, 9), epoch(Y, M, 14, 12), 8, "Spinnaker work")
trip(sam, "Maintenance", epoch(Y, M, 14, 13), epoch(Y, M, 14, 15))
trip(olly, "Lunch cruise", epoch(Y, M, 14, 16), epoch(Y, M, 14, 17))
trip(sam, "Evening sail", epoch(Y, M, 14, 18), epoch(Y, M, 14, 20))
trip(olly, "Thanksgiving week", epoch(Y, M, 24, 10), epoch(Y, M, 29, 16), 6, "Down the coast and back")
trip(sam, "Channel Islands", epoch(NY, NM, 3, 7), epoch(NY, NM, 6, 18), 6)
cass.post(f"/api/bookings/{t1}/signon")
print("seeded; boat", scooter)
