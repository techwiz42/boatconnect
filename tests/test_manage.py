"""Editing and deleting boats and people, and the telephone numbers boatconnect keeps."""
from fastapi.testclient import TestClient

from boatconnect.store import Store

from .conftest import ADMIN
from .test_api import BOAT, join_as_crew, window

PW = "correct horse battery"


# ---- telephone numbers ------------------------------------------------------------------------------------------------------------------------------------

def test_a_phone_number_is_required_and_checked_at_registration(app):
    anon = TestClient(app)
    base = {"email": "new@example.com", "name": "New", "password": PW}
    assert anon.post("/api/auth/register", json=base).status_code == 422
    for bad in ("", "   ", "12345", "call me", "+1 310 555 0100 ext 5", "310+5550100", "1" * 16):
        assert anon.post("/api/auth/register", json={**base, "phone": bad}).status_code == 422, bad
    reply = anon.post("/api/auth/register", json={**base, "phone": "  +1  (310) 555-0100 "})
    assert reply.status_code == 201 and reply.json()["phone"] == "+1 (310) 555-0100"


def test_a_person_changes_their_own_name_and_phone(make_person):
    sam = make_person("sam@example.com", "Sam")
    reply = sam.patch("/api/auth/profile", json={"name": " Sam  Q ", "phone": "310.555.0199"})
    assert reply.status_code == 200 and (reply.json()["name"], reply.json()["phone"]) == ("Sam Q", "310.555.0199")
    assert sam.get("/api/auth/me").json()["phone"] == "310.555.0199"
    assert sam.patch("/api/auth/profile", json={"name": "Sam", "phone": "nope"}).status_code == 422
    assert TestClient(sam.client.app).patch("/api/auth/profile", json={"name": "x", "phone": "310.555.0199"}).status_code == 401


def test_members_see_each_others_phones_and_strangers_see_none(approved_boat, make_person):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    cass.patch("/api/auth/profile", json={"name": "Cass", "phone": "310 555 0142"})
    members = skipper.get(f"/api/boats/{boat_id}").json()["members"]
    assert {m["name"]: m["phone"] for m in members}["Cass"] == "310 555 0142"
    assert "members" not in make_person("stranger@example.com", "Stranger").get(f"/api/boats/{boat_id}").json()


def test_a_database_from_before_phones_is_upgraded(tmp_path):
    from .test_store import downgrade, user
    path = str(tmp_path / "v5.db")
    who = user(Store(path), 1)
    downgrade(path, 5)
    assert Store(path).user_by_id(who)["phone"] == ""


# ---- password and own account ----------------------------------------------------------------------------------------------------------------------------

def test_changing_the_password_needs_the_current_one_and_ends_other_logins(app, make_person):
    sam = make_person("sam@example.com", "Sam")
    elsewhere = TestClient(app)
    assert elsewhere.post("/api/auth/login", json={"email": "sam@example.com", "password": PW}).status_code == 200
    assert sam.post("/api/auth/password", json={"current": "wrong wrong wrong", "password": "a brand new passphrase"}).status_code == 403
    assert sam.post("/api/auth/password", json={"current": PW, "password": "short"}).status_code == 422
    assert sam.post("/api/auth/password", json={"current": PW, "password": "a brand new passphrase"}).status_code == 200
    assert sam.get("/api/auth/me").status_code == 200                      # this login stays
    assert elsewhere.get("/api/auth/me").status_code == 401                # the other does not
    assert TestClient(app).post("/api/auth/login", json={"email": "sam@example.com", "password": "a brand new passphrase"}).status_code == 200
    assert TestClient(app).post("/api/auth/login", json={"email": "sam@example.com", "password": PW}).status_code == 401


def test_a_person_deletes_their_own_account(app, approved_boat, make_person):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    assert cass.post("/api/auth/delete-account", json={"password": "wrong wrong wrong"}).status_code == 403
    assert cass.get("/api/auth/me").status_code == 200
    assert cass.post("/api/auth/delete-account", json={"password": PW}).status_code == 200
    assert cass.get("/api/auth/me").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"email": "cass@example.com", "password": PW}).status_code == 401
    assert [m["name"] for m in skipper.get(f"/api/boats/{boat_id}").json()["members"]] == ["Sam Skipper"]
    assert make_person("cass@example.com", "Cass again").id                  # the address can be registered again


def test_the_only_owner_of_a_boat_cannot_delete_their_account(approved_boat):
    boat_id, skipper = approved_boat
    reply = skipper.post("/api/auth/delete-account", json={"password": PW})
    assert reply.status_code == 409 and "Scooter" in reply.json()["detail"]
    assert skipper.get("/api/auth/me").status_code == 200


def test_a_co_owner_may_delete_their_account_and_the_boat_goes_on_credited_to_the_other(approved_boat, make_person, admin, store):
    boat_id, skipper = approved_boat
    olly = make_person("olly@example.com", "Olly")
    request = olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner", "share_percent": 25}).json()["id"]
    admin.post(f"/api/join-requests/{request}/decision", json={"approve": True})
    olly.post(f"/api/boats/{boat_id}/bookings", json={"title": "Sail", "start": 1_800_000_000, "end": 1_800_003_600, "capacity": None, "notes": ""})
    assert skipper.post("/api/auth/delete-account", json={"password": PW}).status_code == 200        # skipper added the boat; it goes on
    assert store.get_boat(boat_id)["status"] == "approved"
    assert [m["name"] for m in olly.get(f"/api/boats/{boat_id}").json()["members"]] == ["Olly"]
    assert olly.get(f"/api/boats/{boat_id}/bookings", params=window()).json()[0]["title"] == "Sail"


# ---- boats ------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_only_owner_deletes_a_boat_with_everything_on_it(app, approved_boat, make_person, mailer):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    skipper.post(f"/api/boats/{boat_id}/bookings", json={"title": "Sail", "start": 1_800_000_000, "end": 1_800_003_600, "capacity": 4, "notes": ""})
    assert cass.delete(f"/api/boats/{boat_id}").status_code == 403
    assert make_person("stranger@example.com", "Stranger").delete(f"/api/boats/{boat_id}").status_code == 403
    assert TestClient(app).delete(f"/api/boats/{boat_id}").status_code == 401
    assert skipper.delete(f"/api/boats/{boat_id}").status_code == 200
    assert skipper.get(f"/api/boats/{boat_id}").status_code == 404
    assert skipper.get("/api/boats").json() == []
    assert skipper.delete(f"/api/boats/{boat_id}").status_code == 404
    assert mailer.to("cass@example.com") and "deleted" in mailer.to("cass@example.com")[-1].subject
    assert not mailer.to("skipper@example.com") or all("deleted" not in m.subject for m in mailer.to("skipper@example.com"))


def test_one_of_several_owners_cannot_delete_the_boat_but_the_administrator_can(approved_boat, make_person, admin):
    boat_id, skipper = approved_boat
    olly = make_person("olly@example.com", "Olly")
    request = olly.post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner", "share_percent": 25}).json()["id"]
    admin.post(f"/api/join-requests/{request}/decision", json={"approve": True})
    assert skipper.delete(f"/api/boats/{boat_id}").status_code == 403
    assert olly.delete(f"/api/boats/{boat_id}").status_code == 403
    assert olly.delete(f"/api/boats/{boat_id}/members/{olly.id}").status_code == 200       # olly leaves ...
    assert skipper.delete(f"/api/boats/{boat_id}").status_code == 200                      # ... and skipper is the only owner
    assert admin.get("/api/boats").json() == []


def test_the_administrator_deletes_a_boat_that_is_not_yet_approved(admin, make_person):
    owner = make_person("owner@example.com", "Owner")
    boat_id = owner.post("/api/boats", json=BOAT).json()["id"]
    assert admin.delete(f"/api/boats/{boat_id}").status_code == 200
    assert owner.get(f"/api/boats/{boat_id}").status_code == 404


# ---- the administrator's list of people ---------------------------------------------------------------------------------------------------------------------

def test_only_the_administrator_lists_edits_and_deletes_people(make_person, admin):
    sam = make_person("sam@example.com", "Sam")
    assert sam.get("/api/admin/users").status_code == 403
    assert sam.patch(f"/api/admin/users/{admin.id}", json={"name": "x", "email": "x@example.com", "phone": "310 555 0100"}).status_code == 403
    assert sam.delete(f"/api/admin/users/{admin.id}").status_code == 403
    listed = {u["email"]: u for u in admin.get("/api/admin/users").json()}
    assert listed["sam@example.com"]["phone"] == "+1 310 555 0100" and "password_hash" not in listed["sam@example.com"]


def test_the_administrator_edits_a_person(app, make_person, admin):
    sam = make_person("sam@example.com", "Sam")
    other = make_person("other@example.com", "Other")
    edit = {"name": "Samuel", "email": "Samuel@Example.com", "phone": "310 555 0177"}
    assert admin.patch(f"/api/admin/users/{sam.id}", json=edit).status_code == 200
    assert admin.patch(f"/api/admin/users/{sam.id}", json={**edit, "email": "other@example.com"}).status_code == 409
    assert admin.patch(f"/api/admin/users/{sam.id}", json={**edit, "email": "nope"}).status_code == 422
    assert admin.patch(f"/api/admin/users/{sam.id}", json={**edit, "phone": "x"}).status_code == 422
    assert admin.patch("/api/admin/users/nobody", json=edit).status_code == 409
    assert sam.get("/api/auth/me").status_code == 401                          # a new email ends their logins
    assert TestClient(app).post("/api/auth/login", json={"email": "samuel@example.com", "password": PW}).status_code == 200
    assert other.get("/api/auth/me").json()["name"] == "Other"
    own = {"name": "Admin", "email": "someone-else@example.com", "phone": "310 555 0100"}
    assert admin.patch(f"/api/admin/users/{admin.id}", json=own).status_code == 403          # the email is what makes the administrator
    assert admin.patch(f"/api/admin/users/{admin.id}", json={**own, "email": ADMIN}).status_code == 200


def test_the_administrator_deletes_a_person_but_not_themselves_or_a_sole_owner(app, approved_boat, make_person, admin):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    assert admin.delete(f"/api/admin/users/{admin.id}").status_code == 403
    assert admin.delete(f"/api/admin/users/{skipper.id}").status_code == 409
    assert admin.delete(f"/api/admin/users/{cass.id}").status_code == 200
    assert cass.get("/api/auth/me").status_code == 401
    assert admin.delete(f"/api/admin/users/{cass.id}").status_code == 409
    assert admin.delete(f"/api/boats/{boat_id}").status_code == 200
    assert admin.delete(f"/api/admin/users/{skipper.id}").status_code == 200
