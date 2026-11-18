from .conftest import ADMIN, DAY, HOUR, T0

BOAT = {"name": "Scooter", "home_port": "Marina del Rey", "description": "J/35", "timezone": "America/Los_Angeles", "share_percent": 50}
TRIP = {"title": "Catalina", "start": T0, "end": T0 + 8 * HOUR, "capacity": 4, "notes": ""}


def window(**extra):
    return {"start": T0 - DAY, "end": T0 + 30 * DAY, **extra}


# ---- accounts ----------------------------------------------------------------------------------------------------------------------------------------------

def test_register_login_me_logout(app, make_person):
    sam = make_person("sam@example.com", "Sam")
    assert sam.get("/api/auth/me").json() == {"id": sam.id, "email": "sam@example.com", "name": "Sam", "is_admin": False}
    assert sam.post("/api/auth/logout").status_code == 200
    assert sam.get("/api/auth/me").status_code == 401
    reply = sam.post("/api/auth/login", json={"email": "SAM@example.com", "password": "correct horse battery"})
    assert reply.status_code == 200 and sam.get("/api/auth/me").json()["name"] == "Sam"


def test_bad_registrations_and_logins(app, make_person):
    make_person("sam@example.com", "Sam")
    from fastapi.testclient import TestClient
    anon = TestClient(app)
    assert anon.post("/api/auth/register", json={"email": "sam@example.com", "name": "Again", "password": "correct horse battery"}).status_code == 409
    assert anon.post("/api/auth/register", json={"email": "new@example.com", "name": "New", "password": "short"}).status_code == 422
    assert anon.post("/api/auth/register", json={"email": "not-an-email", "name": "New", "password": "correct horse battery"}).status_code == 422
    assert anon.post("/api/auth/register", json={"email": "new@example.com", "name": "   ", "password": "correct horse battery"}).status_code == 422
    assert anon.post("/api/auth/login", json={"email": "sam@example.com", "password": "wrong password!!"}).status_code == 401
    assert anon.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong password!!"}).status_code == 401


def test_the_administrator_is_known_by_email(admin):
    assert admin.get("/api/auth/me").json()["is_admin"] is True


def test_login_is_throttled(app, make_person):
    make_person("sam@example.com", "Sam")
    from fastapi.testclient import TestClient
    anon = TestClient(app)
    codes = [anon.post("/api/auth/login", json={"email": "sam@example.com", "password": "wrong password!!"}).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


def test_a_request_from_another_site_is_refused(app, make_person):
    sam = make_person("sam@example.com", "Sam")
    reply = sam.post("/api/boats", json=BOAT, headers={"Origin": "https://evil.example"})
    assert reply.status_code == 403


def test_every_answer_carries_the_security_headers(app):
    from fastapi.testclient import TestClient
    headers = TestClient(app).get("/api/healthz").headers
    assert headers["x-frame-options"] == "DENY" and "default-src 'self'" in headers["content-security-policy"]


# ---- boats ------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_new_boat_is_hidden_until_the_administrator_approves_it(app, make_person, admin):
    from fastapi.testclient import TestClient
    sam, other = make_person("sam@example.com", "Sam"), make_person("other@example.com", "Other")
    boat_id = sam.post("/api/boats", json=BOAT).json()["id"]
    assert TestClient(app).get("/api/boats").json() == []                                   # the public sees nothing
    assert other.get("/api/boats").json() == [] and other.get(f"/api/boats/{boat_id}").status_code == 404
    mine = sam.get("/api/boats").json()
    assert [(b["id"], b["status"], b["my_role"]) for b in mine] == [(boat_id, "pending", "owner")]
    assert [b["id"] for b in admin.get("/api/inbox").json()["boats"]] == [boat_id]
    assert other.post(f"/api/boats/{boat_id}/decision", json={"approve": True}).status_code == 403          # only the administrator decides
    assert admin.post(f"/api/boats/{boat_id}/decision", json={"approve": True}).status_code == 200
    public = TestClient(app).get("/api/boats").json()
    assert [(b["name"], b["owner_count"], b["crew_count"], b["my_role"]) for b in public] == [("Scooter", 1, 0, None)]
    assert admin.post(f"/api/boats/{boat_id}/decision", json={"approve": True}).status_code == 409      # already decided


def test_boat_details_are_validated(make_person):
    sam = make_person("sam@example.com", "Sam")
    assert sam.post("/api/boats", json={**BOAT, "timezone": "Mars/Olympus"}).status_code == 422
    assert sam.post("/api/boats", json={**BOAT, "share_percent": 150}).status_code == 422
    assert sam.post("/api/boats", json={**BOAT, "name": "  "}).status_code == 422
    from fastapi.testclient import TestClient
    assert TestClient(sam.client.app).post("/api/boats", json=BOAT).status_code == 401


def test_only_members_see_who_belongs(approved_boat, make_person, admin):
    boat_id, skipper = approved_boat
    stranger = make_person("stranger@example.com", "Stranger")
    assert "members" not in stranger.get(f"/api/boats/{boat_id}").json()
    members = skipper.get(f"/api/boats/{boat_id}").json()["members"]
    assert [(m["name"], m["role"], m["share_percent"]) for m in members] == [("Sam Skipper", "owner", 50)]
    assert "members" in admin.get(f"/api/boats/{boat_id}").json()


# ---- joining ------------------------------------------------------------------------------------------------------------------------------------------------

def test_crew_requests_go_to_the_owners_and_owner_requests_to_the_administrator(approved_boat, make_person, admin):
    boat_id, skipper = approved_boat
    cass, olly = make_person("cass@example.com", "Cass"), make_person("olly@example.com", "Olly")
    crew_req = cass.post(f"/api/boats/{boat_id}/join-requests", json={"role": "crew", "message": "Keen"}).json()["id"]
    owner_req = olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner", "share_percent": 25, "message": "I co-own it"}).json()["id"]

    assert cass.get(f"/api/boats/{boat_id}").json()["my_request"]["role"] == "crew"
    assert [r["id"] for r in skipper.get("/api/inbox").json()["requests"]] == [crew_req]             # the owner is asked about crew only
    assert {r["id"] for r in admin.get("/api/inbox").json()["requests"]} == {crew_req, owner_req}
    assert skipper.post(f"/api/join-requests/{owner_req}/decision", json={"approve": True}).status_code == 403
    assert cass.post(f"/api/join-requests/{crew_req}/decision", json={"approve": True}).status_code == 403       # nor may a stranger decide

    assert skipper.post(f"/api/join-requests/{crew_req}/decision", json={"approve": True}).status_code == 200
    assert admin.post(f"/api/join-requests/{owner_req}/decision", json={"approve": True}).status_code == 200
    roles = {m["name"]: (m["role"], m["share_percent"]) for m in skipper.get(f"/api/boats/{boat_id}").json()["members"]}
    assert roles == {"Sam Skipper": ("owner", 50), "Olly": ("owner", 25), "Cass": ("crew", None)}
    assert cass.get(f"/api/boats/{boat_id}").json()["my_role"] == "crew"


def test_an_owner_share_that_does_not_fit_is_refused_at_approval(approved_boat, make_person, admin):
    boat_id, _ = approved_boat
    olly = make_person("olly@example.com", "Olly")
    request = olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner", "share_percent": 60}).json()["id"]
    reply = admin.post(f"/api/join-requests/{request}/decision", json={"approve": True})
    assert reply.status_code == 409 and "does not fit" in reply.json()["detail"]


def test_join_request_rules(approved_boat, make_person):
    boat_id, skipper = approved_boat
    olly = make_person("olly@example.com", "Olly")
    assert olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner"}).status_code == 409          # an owner names a share
    assert olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "captain"}).status_code == 422
    assert olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "crew"}).status_code == 201
    assert olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "crew"}).status_code == 409          # one at a time
    assert skipper.post(f"/api/boats/{boat_id}/join-requests", json={"role": "crew"}).status_code == 409       # already a member


def test_owners_may_remove_crew_and_members_may_leave(approved_boat, make_person):
    boat_id, skipper = approved_boat
    cass = make_person("cass@example.com", "Cass")
    request = cass.post(f"/api/boats/{boat_id}/join-requests", json={"role": "crew"}).json()["id"]
    skipper.post(f"/api/join-requests/{request}/decision", json={"approve": True})
    other = make_person("other@example.com", "Other")
    assert other.delete(f"/api/boats/{boat_id}/members/{cass.id}").status_code == 403
    assert cass.delete(f"/api/boats/{boat_id}/members/{skipper.id}").status_code == 403
    assert cass.delete(f"/api/boats/{boat_id}/members/{cass.id}").status_code == 200                         # leaving is one's own right
    assert skipper.delete(f"/api/boats/{boat_id}/members/{skipper.id}").status_code == 409                    # the last owner stays


# ---- the calendar ---------------------------------------------------------------------------------------------------------------------------------------------

def join_as_crew(boat_id, skipper, make_person, email="cass@example.com", name="Cass"):
    person = make_person(email, name)
    request = person.post(f"/api/boats/{boat_id}/join-requests", json={"role": "crew"}).json()["id"]
    assert skipper.post(f"/api/join-requests/{request}/decision", json={"approve": True}).status_code == 200
    return person


def test_the_calendar_is_for_members(approved_boat, make_person, admin):
    boat_id, skipper = approved_boat
    stranger = make_person("stranger@example.com", "Stranger")
    assert stranger.get(f"/api/boats/{boat_id}/bookings", params=window()).status_code == 403
    assert skipper.get(f"/api/boats/{boat_id}/bookings", params=window()).json() == []
    assert admin.get(f"/api/boats/{boat_id}/bookings", params=window()).status_code == 200
    assert skipper.get(f"/api/boats/{boat_id}/bookings", params={"start": 0, "end": 1000 * DAY}).status_code == 422


def test_an_owner_books_and_is_aboard(approved_boat):
    boat_id, skipper = approved_boat
    booking_id = skipper.post(f"/api/boats/{boat_id}/bookings", json=TRIP).json()["id"]
    [b] = skipper.get(f"/api/boats/{boat_id}/bookings", params=window()).json()
    assert (b["id"], b["title"], b["created_by_name"], b["i_am_aboard"], b["can_edit"]) == (booking_id, "Catalina", "Sam Skipper", True, True)
    assert [a["name"] for a in b["aboard"]] == ["Sam Skipper"]


def test_crew_cannot_book_but_can_sign_on(approved_boat, make_person):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    assert cass.post(f"/api/boats/{boat_id}/bookings", json=TRIP).status_code == 403
    booking_id = skipper.post(f"/api/boats/{boat_id}/bookings", json=TRIP).json()["id"]
    assert cass.post(f"/api/bookings/{booking_id}/signon").status_code == 200
    assert cass.post(f"/api/bookings/{booking_id}/signon").status_code == 409
    [b] = cass.get(f"/api/boats/{boat_id}/bookings", params=window()).json()
    assert b["i_am_aboard"] is True and b["can_edit"] is False and [a["name"] for a in b["aboard"]] == ["Sam Skipper", "Cass"]
    assert cass.delete(f"/api/bookings/{booking_id}/signon/{cass.id}").status_code == 200
    assert cass.patch(f"/api/bookings/{booking_id}", json=TRIP).status_code == 403
    assert cass.delete(f"/api/bookings/{booking_id}").status_code == 403


def test_overlapping_bookings_are_refused_with_who_has_the_slot(approved_boat):
    boat_id, skipper = approved_boat
    skipper.post(f"/api/boats/{boat_id}/bookings", json=TRIP)
    clash = skipper.post(f"/api/boats/{boat_id}/bookings", json={**TRIP, "title": "Clash", "start": T0 + HOUR, "end": T0 + 2 * HOUR})
    assert clash.status_code == 409 and "Catalina (Sam Skipper)" in clash.json()["detail"]
    assert skipper.post(f"/api/boats/{boat_id}/bookings", json={**TRIP, "title": "Next", "start": T0 + 8 * HOUR, "end": T0 + 9 * HOUR}).status_code == 201


def test_a_full_trip_turns_crew_away(approved_boat, make_person):
    boat_id, skipper = approved_boat
    first, second = join_as_crew(boat_id, skipper, make_person), join_as_crew(boat_id, skipper, make_person, "dan@example.com", "Dan")
    booking_id = skipper.post(f"/api/boats/{boat_id}/bookings", json={**TRIP, "capacity": 2}).json()["id"]
    assert first.post(f"/api/bookings/{booking_id}/signon").status_code == 200
    reply = second.post(f"/api/bookings/{booking_id}/signon")
    assert reply.status_code == 409 and "full" in reply.json()["detail"]


def test_an_owner_may_change_anothers_trip_and_the_maker_may_sign_crew_off(approved_boat, make_person, admin):
    boat_id, skipper = approved_boat
    olly = make_person("olly@example.com", "Olly")
    request = olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner", "share_percent": 25}).json()["id"]
    admin.post(f"/api/join-requests/{request}/decision", json={"approve": True})
    cass = join_as_crew(boat_id, skipper, make_person)
    booking_id = skipper.post(f"/api/boats/{boat_id}/bookings", json=TRIP).json()["id"]
    cass.post(f"/api/bookings/{booking_id}/signon")
    assert olly.patch(f"/api/bookings/{booking_id}", json={**TRIP, "title": "Renamed"}).status_code == 200
    assert skipper.delete(f"/api/bookings/{booking_id}/signon/{cass.id}").status_code == 200
    assert olly.delete(f"/api/bookings/{booking_id}").status_code == 200
    assert skipper.get(f"/api/boats/{boat_id}/bookings", params=window()).json() == []


def test_booking_input_is_validated(approved_boat):
    boat_id, skipper = approved_boat
    assert skipper.post(f"/api/boats/{boat_id}/bookings", json={**TRIP, "end": T0}).status_code == 409
    assert skipper.post(f"/api/boats/{boat_id}/bookings", json={**TRIP, "title": " "}).status_code == 422
    assert skipper.post(f"/api/boats/{boat_id}/bookings", json={**TRIP, "capacity": 0}).status_code == 422


def test_a_boat_waiting_for_approval_has_no_calendar(app, make_person):
    sam = make_person("sam@example.com", "Sam")
    boat_id = sam.post("/api/boats", json=BOAT).json()["id"]
    assert sam.get(f"/api/boats/{boat_id}/bookings", params=window()).status_code == 409


# ---- editing a boat ------------------------------------------------------------------------------------------------------------------------------------------

EDIT = {"name": "Scooter II", "home_port": "Newport Beach", "description": "Re-rigged", "timezone": "America/Denver"}


def test_an_owner_edits_the_boat_and_everyone_sees_it(approved_boat, make_person):
    boat_id, skipper = approved_boat
    assert skipper.patch(f"/api/boats/{boat_id}", json=EDIT).status_code == 200
    seen = make_person("anyone@example.com", "Anyone").get(f"/api/boats/{boat_id}").json()
    assert (seen["name"], seen["home_port"], seen["description"], seen["timezone"], seen["status"]) == ("Scooter II", "Newport Beach", "Re-rigged", "America/Denver", "approved")


def test_the_administrator_may_not_edit_a_boat_they_do_not_own(approved_boat, admin):
    boat_id, _ = approved_boat
    assert admin.patch(f"/api/boats/{boat_id}", json=EDIT).status_code == 403
    assert admin.get(f"/api/boats/{boat_id}").json()["name"] == "Scooter"


def test_any_owner_may_edit_not_only_the_first(approved_boat, make_person, admin):
    boat_id, _ = approved_boat
    olly = make_person("olly@example.com", "Olly")
    request = olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner", "share_percent": 25}).json()["id"]
    admin.post(f"/api/join-requests/{request}/decision", json={"approve": True})
    assert olly.patch(f"/api/boats/{boat_id}", json=EDIT).status_code == 200


def test_crew_and_strangers_may_not_edit(approved_boat, make_person):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    stranger = make_person("stranger@example.com", "Stranger")
    assert cass.patch(f"/api/boats/{boat_id}", json=EDIT).status_code == 403
    assert stranger.patch(f"/api/boats/{boat_id}", json=EDIT).status_code == 403
    from fastapi.testclient import TestClient
    assert TestClient(skipper.client.app).patch(f"/api/boats/{boat_id}", json=EDIT).status_code == 401
    assert skipper.get(f"/api/boats/{boat_id}").json()["name"] == "Scooter"                          # nothing changed


def test_an_owner_may_edit_a_boat_that_is_still_waiting_for_approval(make_person):
    sam = make_person("sam@example.com", "Sam")
    boat_id = sam.post("/api/boats", json=BOAT).json()["id"]
    assert sam.patch(f"/api/boats/{boat_id}", json=EDIT).status_code == 200
    assert sam.get(f"/api/boats/{boat_id}").json()["status"] == "pending"                            # editing is not approval


def test_a_boat_nobody_may_see_cannot_be_edited_by_a_stranger(make_person):
    sam, other = make_person("sam@example.com", "Sam"), make_person("other@example.com", "Other")
    boat_id = sam.post("/api/boats", json=BOAT).json()["id"]
    assert other.patch(f"/api/boats/{boat_id}", json=EDIT).status_code == 404


def test_edits_are_validated(approved_boat):
    boat_id, skipper = approved_boat
    assert skipper.patch(f"/api/boats/{boat_id}", json={**EDIT, "timezone": "Mars/Olympus"}).status_code == 422
    assert skipper.patch(f"/api/boats/{boat_id}", json={**EDIT, "name": "   "}).status_code == 422
    assert skipper.patch(f"/api/boats/{boat_id}", json={**EDIT, "name": "x" * 81}).status_code == 422
    assert skipper.patch(f"/api/boats/{boat_id}", json={**EDIT, "share_percent": 5}).status_code == 200      # a share sent along is ignored, not applied
    assert skipper.get(f"/api/boats/{boat_id}").json()["members"][0]["share_percent"] == 50


# ---- owners' shares over time ----------------------------------------------------------------------------------------------------------------------------

def test_the_way_to_add_a_fractional_owner_is_that_an_owner_lowers_their_share_first(app, admin, make_person):
    sam = make_person("sam@example.com", "Sam")
    boat_id = sam.post("/api/boats", json={**BOAT, "share_percent": 100}).json()["id"]
    admin.post(f"/api/boats/{boat_id}/decision", json={"approve": True})
    assert sam.get(f"/api/boats/{boat_id}").json()["unallocated_percent"] == 0
    olly = make_person("olly@example.com", "Olly")
    request = olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner", "share_percent": 25}).json()["id"]
    refused = admin.post(f"/api/join-requests/{request}/decision", json={"approve": True})
    assert refused.status_code == 409 and "lower their own share first" in refused.json()["detail"]

    assert sam.patch(f"/api/boats/{boat_id}/my-share", json={"share_percent": 75}).status_code == 200
    from fastapi.testclient import TestClient
    assert TestClient(app).get("/api/boats").json()[0]["unallocated_percent"] == 25               # anyone can see there is room, not who holds what
    assert admin.post(f"/api/join-requests/{request}/decision", json={"approve": True}).status_code == 200
    shares = {m["name"]: m["share_percent"] for m in sam.get(f"/api/boats/{boat_id}").json()["members"]}
    assert shares == {"Sam": 75, "Olly": 25}
    assert sam.get(f"/api/boats/{boat_id}").json()["unallocated_percent"] == 0


def test_an_owner_cannot_take_more_than_is_free_or_change_anothers_share(approved_boat, make_person, admin):
    boat_id, skipper = approved_boat                                                            # holds 50%
    olly = make_person("olly@example.com", "Olly")
    request = olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner", "share_percent": 30}).json()["id"]
    admin.post(f"/api/join-requests/{request}/decision", json={"approve": True})
    over = skipper.patch(f"/api/boats/{boat_id}/my-share", json={"share_percent": 71})          # 20% is free: at most 70
    assert over.status_code == 409 and "at most 70%" in over.json()["detail"]
    assert skipper.patch(f"/api/boats/{boat_id}/my-share", json={"share_percent": 70}).status_code == 200
    assert skipper.patch(f"/api/boats/{boat_id}/my-share", json={"share_percent": 0}).status_code == 422
    members = {m["name"]: m["share_percent"] for m in olly.get(f"/api/boats/{boat_id}").json()["members"]}
    assert members["Olly"] == 30                                                                # Sam's changes never touch Olly's share


def test_only_an_owner_has_a_share_to_change(approved_boat, make_person, admin):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    for who in (cass, admin, make_person("stranger@example.com", "Stranger")):
        reply = who.patch(f"/api/boats/{boat_id}/my-share", json={"share_percent": 10})
        assert reply.status_code == 409 and "only an owner" in reply.json()["detail"]
    from fastapi.testclient import TestClient
    assert TestClient(skipper.client.app).patch(f"/api/boats/{boat_id}/my-share", json={"share_percent": 10}).status_code == 401


def test_the_share_history_is_for_members(approved_boat, make_person):
    boat_id, skipper = approved_boat
    skipper.patch(f"/api/boats/{boat_id}/my-share", json={"share_percent": 40})
    history = skipper.get(f"/api/boats/{boat_id}").json()["share_history"]
    assert [(h["name"], h["old_share"], h["new_share"]) for h in history] == [("Sam Skipper", 50, 40), ("Sam Skipper", None, 50)]
    assert "share_history" not in make_person("stranger@example.com", "Stranger").get(f"/api/boats/{boat_id}").json()
