import pytest
from fastapi.testclient import TestClient

from boatconnect import auth
from boatconnect.mail import Mailer
from boatconnect.server import create_app
from boatconnect.store import Store

ADMIN = "admin@example.com"


@pytest.fixture(autouse=True)
def cheap_passwords(monkeypatch):
    """scrypt is meant to be slow; the tests make many accounts."""
    monkeypatch.setattr(auth, "SCRYPT_N", 2 ** 4)


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


class FakeMailer(Mailer):
    """Records what would have been sent: a list of (recipients, Mail)."""
    enabled = True

    def __init__(self):
        self.sent = []

    async def send(self, to, mail):
        self.sent.append((list(to), mail))

    def to(self, address):
        return [mail for recipients, mail in self.sent if address in recipients]


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def app(store, mailer):
    return create_app(store=store, admin_emails=(ADMIN,), mailer=mailer, public_url="https://boatconnect.test")


class Person:
    """One browser: its own cookie jar, signed in as someone."""

    def __init__(self, app, email, name):
        self.client = TestClient(app)
        self.email, self.name = email, name
        reply = self.client.post("/api/auth/register", json={"email": email, "name": name, "password": "correct horse battery"})
        assert reply.status_code == 201, reply.text
        self.id = reply.json()["id"]

    def get(self, *a, **k):
        return self.client.get(*a, **k)

    def post(self, *a, **k):
        return self.client.post(*a, **k)

    def patch(self, *a, **k):
        return self.client.patch(*a, **k)

    def put(self, *a, **k):
        return self.client.put(*a, **k)

    def delete(self, *a, **k):
        return self.client.delete(*a, **k)


@pytest.fixture
def make_person(app):
    return lambda email, name: Person(app, email, name)


@pytest.fixture
def admin(make_person):
    return make_person(ADMIN, "Site Admin")


HOUR = 3600
DAY = 24 * HOUR
T0 = 1_800_000_000          # an arbitrary start, in the future of the test's mind: all that matters is differences


@pytest.fixture
def approved_boat(admin, make_person):
    """A boat approved by the administrator, with one owner who holds 50%."""
    skipper = make_person("skipper@example.com", "Sam Skipper")
    reply = skipper.post("/api/boats", json={"name": "Scooter", "home_port": "Marina del Rey", "description": "J/35", "timezone": "America/Los_Angeles", "share_percent": 50})
    assert reply.status_code == 201, reply.text
    boat_id = reply.json()["id"]
    assert admin.post(f"/api/boats/{boat_id}/decision", json={"approve": True}).status_code == 200
    return boat_id, skipper
