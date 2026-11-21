"""A member writing to the others on a boat."""
from fastapi.testclient import TestClient

from boatconnect.emails import crew_message
from boatconnect.mail import build_message

from .test_api import join_as_crew


def test_a_member_messages_everyone_else_and_replies_go_to_them(approved_boat, make_person, mailer):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    skipper.patch("/api/auth/preferences", json={"email_trips": False})                    # a trip-email opt-out does not stop what a shipmate writes
    mailer.sent.clear()
    reply = cass.post(f"/api/boats/{boat_id}/messages", json={"subject": " Fuel  dock ", "body": "Who is bringing\\nthe fuel?"})
    assert reply.status_code == 200 and reply.json() == {"sent": 1}
    (recipients, mail), = mailer.sent
    assert recipients == ["skipper@example.com"] and mail.subject == "[Scooter] Fuel dock"
    assert mail.reply_to == "Cass <cass@example.com>" and mail.from_person
    assert "Who is bringing" in mail.text and "cass@example.com" not in mail.text and "cass@example.com" not in mail.html


def test_the_message_is_escaped_and_headers_cannot_be_injected(approved_boat, make_person):
    boat_id, skipper = approved_boat
    mail = crew_message("Cass\r\nBcc: x@example.com", "cass@example.com", "Scooter", "Hi\r\nBcc: y@example.com", "<script>alert(1)</script>\nline two", "https://boatconnect.test", boat_id)
    assert "<script>" not in mail.html and "&lt;script&gt;" in mail.html and "<br>line two" in mail.html
    message = build_message("boatconnect <pete@example.com>", None, "skipper@example.com", mail)
    assert message["Bcc"] is None and "\n" not in message["Subject"] and "\n" not in message["Reply-To"]
    assert message["Auto-Submitted"] is None                                               # a person wrote it, so replies and autoresponders are welcome
    assert message["Reply-To"].endswith("<cass@example.com>")


def test_only_members_may_message_and_the_input_is_checked(app, approved_boat, make_person, admin, mailer):
    boat_id, skipper = approved_boat
    join_as_crew(boat_id, skipper, make_person)
    mailer.sent.clear()
    stranger = make_person("stranger@example.com", "Stranger")
    assert stranger.post(f"/api/boats/{boat_id}/messages", json={"body": "hi"}).status_code == 403
    assert admin.post(f"/api/boats/{boat_id}/messages", json={"body": "hi"}).status_code == 403
    assert TestClient(app).post(f"/api/boats/{boat_id}/messages", json={"body": "hi"}).status_code == 401
    assert skipper.post(f"/api/boats/{boat_id}/messages", json={"body": "   "}).status_code == 422
    assert skipper.post(f"/api/boats/{boat_id}/messages", json={"body": "x" * 2001}).status_code == 422
    assert skipper.post(f"/api/boats/{boat_id}/messages", json={"subject": "s" * 101, "body": "hi"}).status_code == 422
    assert mailer.sent == []


def test_a_message_to_an_empty_boat_and_the_daily_limit(approved_boat, make_person, mailer):
    boat_id, skipper = approved_boat
    assert skipper.post(f"/api/boats/{boat_id}/messages", json={"body": "anyone?"}).status_code == 409
    join_as_crew(boat_id, skipper, make_person)
    for _ in range(20):
        assert skipper.post(f"/api/boats/{boat_id}/messages", json={"body": "hello"}).status_code == 200
    assert skipper.post(f"/api/boats/{boat_id}/messages", json={"body": "hello"}).status_code == 429


def test_without_mail_set_up_it_says_so(store, make_person_for=None):
    from boatconnect.server import create_app
    app = create_app(store=store, admin_emails=("admin@example.com",))
    from .conftest import Person
    skipper, admin = Person(app, "skipper@example.com", "Skipper"), Person(app, "admin@example.com", "Admin")
    boat_id = skipper.post("/api/boats", json={"name": "Scooter", "home_port": "MdR", "description": "", "timezone": "UTC", "share_percent": 50}).json()["id"]
    admin.post(f"/api/boats/{boat_id}/decision", json={"approve": True})
    reply = skipper.post(f"/api/boats/{boat_id}/messages", json={"body": "hi"})
    assert reply.status_code == 503 and "not set up" in reply.json()["detail"]
