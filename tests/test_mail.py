"""Email: what is sent, to whom, and what is never revealed. The server is given a fake mailer that records messages; the SMTP sender is tested with a fake SMTP server."""
import asyncio
import smtplib

import pytest
from fastapi.testclient import TestClient

from boatconnect import mail
from boatconnect.mail import Mail, SmtpMailer, build_message
from boatconnect.server import create_app

from .conftest import ADMIN, HOUR, T0
from .test_api import BOAT, TRIP, join_as_crew

SAMPLE = Mail("Subject", "plain text", "<p>html</p>")


# ---- the messages and the SMTP sender --------------------------------------------------------------------------------------------------------------------

def test_a_message_has_the_right_headers_and_both_text_and_html():
    message = build_message("boatconnect <noreply@boatconnect.org>", "j35.scooter@gmail.com", "ann@example.com", Mail("Hi", "text", "<b>html</b>", unsubscribe_url="https://boatconnect.org/api/unsubscribe/tok"))
    assert (message["From"], message["To"], message["Reply-To"], message["Subject"]) == ("boatconnect <noreply@boatconnect.org>", "ann@example.com", "j35.scooter@gmail.com", "Hi")
    assert message["List-Unsubscribe"] == "<https://boatconnect.org/api/unsubscribe/tok>" and message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert message["Auto-Submitted"] == "auto-generated" and message["Message-ID"].endswith("@boatconnect.org>")
    assert message.get_body(("plain",)).get_content().strip() == "text" and "<b>html</b>" in message.get_body(("html",)).get_content()


def test_mail_with_no_unsubscribe_link_has_no_such_header():
    message = build_message("noreply@boatconnect.org", None, "ann@example.com", SAMPLE)
    assert message["List-Unsubscribe"] is None and message["Reply-To"] is None


def test_text_a_user_wrote_cannot_add_headers():
    message = build_message("noreply@boatconnect.org", None, "ann@example.com", Mail("Trip\r\nBcc: evil@example.com\nX-Evil: 1", "t", "<p>t</p>"))
    assert "\n" not in message["Subject"] and message["Bcc"] is None and message["X-Evil"] is None
    assert mail.one_line("a\x00b‮c\td") == "a b c d"


class FakeSmtp:
    """Stands in for smtplib.SMTP: records the conversation."""
    instances = []
    refuse = set()

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout, self.started, self.messages, self.logged_in = host, port, timeout, False, [], None
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.started = True

    def ehlo_or_helo_if_needed(self):
        pass

    def auth_login(self, challenge=None):
        pass

    def auth(self, mechanism, authobject, *, initial_response_ok=True):
        assert self.started, "must not log in before the connection is encrypted"
        assert mechanism == "LOGIN" and initial_response_ok is False
        self.logged_in = (self.user, self.password)

    def send_message(self, message):
        if message["To"] in FakeSmtp.refuse:
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no such user")})
        self.messages.append(message)


@pytest.fixture
def smtp(monkeypatch):
    FakeSmtp.instances, FakeSmtp.refuse = [], set()
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    return FakeSmtp


def test_the_smtp_sender_encrypts_then_sends_one_message_each(smtp):
    sender = SmtpMailer("smtp-relay.gmail.com", 587, "boatconnect <noreply@boatconnect.org>", "j35.scooter@gmail.com")
    asyncio.run(sender.send(["b@example.com", "a@example.com", "a@example.com", "", "not-an-address"], SAMPLE))
    [conversation] = smtp.instances
    assert (conversation.host, conversation.port, conversation.started) == ("smtp-relay.gmail.com", 587, True)
    assert [m["To"] for m in conversation.messages] == ["a@example.com", "b@example.com"]         # deduplicated, junk dropped, nobody sees another's address
    assert all(m["Reply-To"] == "j35.scooter@gmail.com" for m in conversation.messages)


def test_one_refused_recipient_does_not_stop_the_others(smtp):
    smtp.refuse = {"bad@example.com"}
    asyncio.run(SmtpMailer("h", 587, "noreply@boatconnect.org").send(["bad@example.com", "good@example.com"], SAMPLE))
    assert [m["To"] for m in smtp.instances[0].messages] == ["good@example.com"]


def test_a_mail_server_that_is_down_is_logged_and_does_not_raise(monkeypatch, caplog):
    def refuse(*a, **k):
        raise ConnectionRefusedError("down")
    monkeypatch.setattr(smtplib, "SMTP", refuse)
    asyncio.run(SmtpMailer("h", 587, "noreply@boatconnect.org").send(["a@example.com"], SAMPLE))
    assert "could not be sent" in caplog.text and "a@example.com" not in caplog.text                # the address of someone is not written to the log


def test_with_no_recipients_nothing_is_even_connected(smtp):
    asyncio.run(SmtpMailer("h", 587, "noreply@boatconnect.org").send([], SAMPLE))
    assert smtp.instances == []


# ---- who is told what ----------------------------------------------------------------------------------------------------------------------------------------

def test_the_administrator_is_told_of_a_new_boat_but_not_of_their_own(mailer, make_person, admin):
    sam = make_person("sam@example.com", "Sam")
    sam.post("/api/boats", json={**BOAT, "name": "Scooter <b>"})
    [note] = mailer.to(ADMIN)
    assert "waiting for your approval" in note.subject and "Scooter &lt;b&gt;" in note.html and "https://boatconnect.test/inbox" in note.text
    mailer.sent.clear()
    admin.post("/api/boats", json=BOAT)
    assert mailer.sent == []


def test_crew_requests_are_mailed_to_the_owners_and_owner_requests_to_the_administrator(mailer, approved_boat, make_person):
    boat_id, skipper = approved_boat
    mailer.sent.clear()
    make_person("cass@example.com", "Cass").post(f"/api/boats/{boat_id}/join-requests", json={"role": "crew", "message": "Keen to <learn>"})
    assert [r for r, _ in mailer.sent] == [["skipper@example.com"]]                                    # the owner, not the administrator
    note = mailer.sent[0][1]
    assert note.subject == "Cass asks to join Scooter" and "as crew" in note.text and "Keen to &lt;learn&gt;" in note.html
    mailer.sent.clear()
    make_person("olly@example.com", "Olly").post(f"/api/boats/{boat_id}/join-requests", json={"role": "owner", "share_percent": 25})
    assert [r for r, _ in mailer.sent] == [[ADMIN]] and "25%" in mailer.sent[0][1].text


def test_the_person_who_asked_is_told_the_decision(mailer, approved_boat, make_person):
    boat_id, skipper = approved_boat
    cass, dan = make_person("cass@example.com", "Cass"), make_person("dan@example.com", "Dan")
    yes = cass.post(f"/api/boats/{boat_id}/join-requests", json={"role": "crew"}).json()["id"]
    no = dan.post(f"/api/boats/{boat_id}/join-requests", json={"role": "crew"}).json()["id"]
    mailer.sent.clear()
    skipper.post(f"/api/join-requests/{yes}/decision", json={"approve": True})
    skipper.post(f"/api/join-requests/{no}/decision", json={"approve": False})
    assert "approved to join" in mailer.to("cass@example.com")[0].text and "declined" in mailer.to("dan@example.com")[0].text
    assert "https://boatconnect.test/boats/" in mailer.to("cass@example.com")[0].text


def test_the_creator_is_told_when_their_boat_is_decided(mailer, admin, make_person):
    sam = make_person("sam@example.com", "Sam")
    boat_id = sam.post("/api/boats", json=BOAT).json()["id"]
    mailer.sent.clear()
    admin.post(f"/api/boats/{boat_id}/decision", json={"approve": True})
    [note] = mailer.to("sam@example.com")
    assert "was approved" in note.subject


def members_of_a_busy_boat(approved_boat, make_person):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    dan = join_as_crew(boat_id, skipper, make_person, "dan@example.com", "Dan")
    return boat_id, skipper, cass, dan


def test_a_new_trip_is_mailed_to_the_other_members_who_want_it(mailer, approved_boat, make_person):
    boat_id, skipper, cass, dan = members_of_a_busy_boat(approved_boat, make_person)
    dan.patch("/api/auth/preferences", json={"email_trips": False})
    mailer.sent.clear()
    skipper.post(f"/api/boats/{boat_id}/bookings", json={**TRIP, "title": "Catalina <weekend>"})
    assert [r for r, _ in mailer.sent] == [["cass@example.com"]]                                       # not the booker, not Dan who opted out
    note = mailer.sent[0][1]
    assert note.subject == "Scooter: Catalina <weekend> booked" and "Catalina &lt;weekend&gt;" in note.html
    assert "Sam Skipper booked a trip on Scooter" in note.text and "America/Los Angeles" in note.text
    assert note.unsubscribe_url.startswith("https://boatconnect.test/api/unsubscribe/") and "/unsubscribe?token=" in note.text


def test_changing_the_time_or_cancelling_is_mailed_but_changing_the_notes_is_not(mailer, approved_boat, make_person):
    boat_id, skipper, cass, _ = members_of_a_busy_boat(approved_boat, make_person)
    trip_id = skipper.post(f"/api/boats/{boat_id}/bookings", json=TRIP).json()["id"]
    mailer.sent.clear()
    skipper.patch(f"/api/bookings/{trip_id}", json={**TRIP, "notes": "bring a hat"})
    assert mailer.sent == []
    skipper.patch(f"/api/bookings/{trip_id}", json={**TRIP, "start": T0 + HOUR, "end": T0 + 9 * HOUR})
    assert "changed" in mailer.to("cass@example.com")[-1].subject
    skipper.delete(f"/api/bookings/{trip_id}")
    assert "cancelled" in mailer.to("cass@example.com")[-1].subject and "Catalina" in mailer.to("cass@example.com")[-1].text


def test_each_member_gets_their_own_unsubscribe_link(mailer, approved_boat, make_person):
    boat_id, skipper, cass, dan = members_of_a_busy_boat(approved_boat, make_person)
    mailer.sent.clear()
    skipper.post(f"/api/boats/{boat_id}/bookings", json=TRIP)
    links = {r[0]: m.unsubscribe_url for r, m in mailer.sent}
    assert set(links) == {"cass@example.com", "dan@example.com"} and len(set(links.values())) == 2


def test_everything_still_works_with_no_mail_set_up(store, admin_emails=(ADMIN,)):
    app = create_app(store=store, admin_emails=admin_emails)                                          # no mailer: nothing is sent, nothing breaks
    sam = TestClient(app)
    assert sam.post("/api/auth/register", json={"email": "sam@example.com", "name": "Sam", "password": "correct horse battery"}).status_code == 201
    assert sam.post("/api/boats", json=BOAT).status_code == 201
    assert sam.post("/api/auth/forgot", json={"email": "sam@example.com"}).status_code == 503


# ---- unsubscribing and preferences ---------------------------------------------------------------------------------------------------------------------------

def test_a_person_can_turn_trip_emails_off_and_on(make_person):
    sam = make_person("sam@example.com", "Sam")
    assert sam.get("/api/auth/me").json()["email_trips"] is True
    assert sam.patch("/api/auth/preferences", json={"email_trips": False}).json()["email_trips"] is False
    assert sam.get("/api/auth/me").json()["email_trips"] is False
    sam.patch("/api/auth/preferences", json={"email_trips": True})
    assert sam.get("/api/auth/me").json()["email_trips"] is True


def test_the_one_click_link_works_without_a_login(app, mailer, approved_boat, make_person):
    boat_id, skipper = approved_boat
    cass = join_as_crew(boat_id, skipper, make_person)
    mailer.sent.clear()
    skipper.post(f"/api/boats/{boat_id}/bookings", json=TRIP)
    link = mailer.sent[0][1].unsubscribe_url
    assert TestClient(app).post(link.replace("https://boatconnect.test", ""), data={"List-Unsubscribe": "One-Click"}).status_code == 200      # a mail program's post
    assert cass.get("/api/auth/me").json()["email_trips"] is False
    assert TestClient(app).post("/api/unsubscribe/wrong-token").status_code == 404
    codes = [TestClient(app).post(f"/api/unsubscribe/guess-{i}").status_code for i in range(35)]
    assert 429 in codes


# ---- forgotten passwords -------------------------------------------------------------------------------------------------------------------------------------

def reset_token_from(note):
    import re
    return re.search(r"/reset\?token=([\w-]+)", note.text).group(1)


def test_forgot_and_reset_end_to_end(app, mailer, make_person):
    sam = make_person("sam@example.com", "Sam")
    assert sam.get("/api/auth/me").status_code == 200                                                 # logged in with the old password
    anon = TestClient(app)
    assert anon.post("/api/auth/forgot", json={"email": "SAM@example.com"}).status_code == 202
    [note] = mailer.to("sam@example.com")
    assert note.subject == "Reset your boatconnect password" and "https://boatconnect.test/reset?token=" in note.text and "within an hour" in note.text
    token = reset_token_from(note)
    assert anon.post("/api/auth/reset", json={"token": token, "password": "a brand new password"}).status_code == 200
    assert sam.get("/api/auth/me").status_code == 401                                                 # the old login is ended
    assert anon.post("/api/auth/login", json={"email": "sam@example.com", "password": "correct horse battery"}).status_code == 401
    assert anon.post("/api/auth/login", json={"email": "sam@example.com", "password": "a brand new password"}).status_code == 200
    again = anon.post("/api/auth/reset", json={"token": token, "password": "yet another password!"})
    assert again.status_code == 409 and "already used" in again.json()["detail"]                       # works once


def test_asking_about_an_unknown_address_gives_the_same_answer_and_sends_nothing(app, mailer, make_person):
    make_person("sam@example.com", "Sam")
    anon = TestClient(app)
    known, unknown = anon.post("/api/auth/forgot", json={"email": "sam@example.com"}), anon.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()) == (202, {"ok": True})
    assert anon.post("/api/auth/forgot", json={"email": "not an address"}).status_code == 202
    assert [r for r, _ in mailer.sent] == [["sam@example.com"]]


def test_a_bad_or_expired_link_or_a_weak_password_changes_nothing(app, store, mailer, make_person):
    sam = make_person("sam@example.com", "Sam")
    anon = TestClient(app)
    assert anon.post("/api/auth/reset", json={"token": "made-up", "password": "a brand new password"}).status_code == 409
    anon.post("/api/auth/forgot", json={"email": "sam@example.com"})
    token = reset_token_from(mailer.to("sam@example.com")[0])
    assert anon.post("/api/auth/reset", json={"token": token, "password": "short"}).status_code == 422
    assert anon.post("/api/auth/reset", json={"token": token, "password": "a brand new password"}).status_code == 200             # the weak try did not use the link up
    store.create_password_reset(sam.id, __import__("boatconnect.auth", fromlist=["hash_token"]).hash_token("stale-link"), -5)
    assert anon.post("/api/auth/reset", json={"token": "stale-link", "password": "another new password"}).status_code == 409


def test_one_account_cannot_be_flooded_with_reset_mail(app, mailer, make_person):
    make_person("sam@example.com", "Sam")
    anon = TestClient(app)
    codes = [anon.post("/api/auth/forgot", json={"email": "sam@example.com"}).status_code for _ in range(6)]
    assert codes == [202] * 6                                                                          # never says so ...
    assert len(mailer.to("sam@example.com")) == 3                                                       # ... but only three were sent


def test_requests_from_one_address_are_limited(app):
    anon = TestClient(app)
    codes = [anon.post("/api/auth/forgot", json={"email": f"user{i}@example.com"}).status_code for i in range(10)]
    assert codes[:8] == [202] * 8 and 429 in codes[8:]


def test_reset_requests_from_another_site_are_refused(app, make_person):
    make_person("sam@example.com", "Sam")
    assert TestClient(app).post("/api/auth/forgot", json={"email": "sam@example.com"}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_a_mailbox_login_is_used_only_after_encryption(smtp):
    asyncio.run(SmtpMailer("smtp.gmail.com", 587, "noreply@x.org", username="noreply@x.org", password="app pass").send(["a@example.com"], SAMPLE))
    assert smtp.instances[0].logged_in == ("noreply@x.org", "app pass")


def test_a_relay_without_a_login_is_not_asked_to_log_in(smtp):
    asyncio.run(SmtpMailer("smtp-relay.gmail.com", 587, "noreply@x.org").send(["a@example.com"], SAMPLE))
    assert smtp.instances[0].logged_in is None
