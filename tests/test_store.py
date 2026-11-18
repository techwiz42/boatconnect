import pytest

from boatconnect.store import StoreError

from .conftest import DAY, HOUR, T0


def user(store, n):
    return store.create_user(f"u{n}@example.com", f"User {n}", "hash")


def boat(store, owner, share=50):
    return store.create_boat(owner, "Scooter", "Marina", "", "UTC", share)


def test_duplicate_email_is_refused(store):
    user(store, 1)
    with pytest.raises(StoreError, match="already registered"):
        user(store, 1)


def test_the_creator_is_the_first_owner_and_the_boat_waits(store):
    owner = user(store, 1)
    b = boat(store, owner, 40)
    assert store.get_boat(b)["status"] == "pending"
    assert store.members(b) == [{"user_id": owner, "name": "User 1", "role": "owner", "share_percent": 40}]
    assert store.approved_boats() == [] and [x["id"] for x in store.pending_boats()] == [b]


@pytest.mark.parametrize("share", [0, -5, 100.5, None])
def test_an_owners_share_must_be_between_0_and_100(store, share):
    with pytest.raises(StoreError, match="share"):
        boat(store, user(store, 1), share)


def test_owner_shares_may_not_exceed_100(store):
    first, second, third = user(store, 1), user(store, 2), user(store, 3)
    b = boat(store, first, 60)
    store.decide_boat(b, True)
    ok = store.request_join(b, second, "owner", 40, "")
    too_much = store.request_join(b, third, "owner", 1, "")
    store.decide_request(ok, first, True)
    with pytest.raises(StoreError, match="does not fit"):
        store.decide_request(too_much, first, True)
    assert store.get_request(too_much)["status"] == "pending"        # a refused approval changes nothing


def test_requests_need_an_approved_boat_and_one_at_a_time(store):
    owner, other = user(store, 1), user(store, 2)
    b = boat(store, owner)
    with pytest.raises(StoreError, match="not open"):
        store.request_join(b, other, "crew", None, "")
    store.decide_boat(b, True)
    store.request_join(b, other, "crew", None, "")
    with pytest.raises(StoreError, match="already have a request"):
        store.request_join(b, other, "crew", None, "")
    with pytest.raises(StoreError, match="already belong"):
        store.request_join(b, owner, "crew", None, "")


def test_approving_crew_makes_a_member_and_declining_does_not(store):
    owner, a, b2 = user(store, 1), user(store, 2), user(store, 3)
    b = boat(store, owner)
    store.decide_boat(b, True)
    yes, no = store.request_join(b, a, "crew", 99, ""), store.request_join(b, b2, "crew", None, "")
    store.decide_request(yes, owner, True)
    store.decide_request(no, owner, False)
    assert store.role_of(b, a) == "crew" and store.role_of(b, b2) is None
    assert [m["share_percent"] for m in store.members(b) if m["role"] == "crew"] == [None]       # crew hold no share, whatever was sent
    with pytest.raises(StoreError, match="not waiting"):
        store.decide_request(yes, owner, True)


def test_bookings_may_touch_but_not_overlap(store):
    owner = user(store, 1)
    b = boat(store, owner)
    store.create_booking(b, owner, "Morning", T0, T0 + 4 * HOUR, None, "")
    store.create_booking(b, owner, "Afternoon", T0 + 4 * HOUR, T0 + 8 * HOUR, None, "")            # starts exactly when the other ends
    with pytest.raises(StoreError, match="already booked then: Morning"):
        store.create_booking(b, owner, "Clash", T0 + 3 * HOUR, T0 + 5 * HOUR, None, "")
    with pytest.raises(StoreError, match="already booked then"):
        store.create_booking(b, owner, "Swallows both", T0 - HOUR, T0 + 9 * HOUR, None, "")
    other_boat = boat(store, owner)
    store.create_booking(other_boat, owner, "Elsewhere", T0, T0 + 4 * HOUR, None, "")             # another boat is another calendar


def test_a_booking_may_be_moved_over_its_own_old_time(store):
    owner = user(store, 1)
    b = boat(store, owner)
    booking = store.create_booking(b, owner, "Trip", T0, T0 + 4 * HOUR, None, "")
    store.update_booking(booking, "Trip", T0 + HOUR, T0 + 5 * HOUR, None, "")
    assert store.get_booking(booking)["start_utc"] == T0 + HOUR


@pytest.mark.parametrize("start,end", [(T0, T0), (T0, T0 + 600), (T0 + 10, T0), (T0, T0 + 31 * DAY)])
def test_booking_lengths_are_sane(store, start, end):
    owner = user(store, 1)
    with pytest.raises(StoreError):
        store.create_booking(boat(store, owner), owner, "Bad", start, end, None, "")


def test_signing_on_respects_capacity_and_the_maker_stays_aboard(store):
    owner, a, b2 = user(store, 1), user(store, 2), user(store, 3)
    b = boat(store, owner)
    trip = store.create_booking(b, owner, "Trip", T0, T0 + 4 * HOUR, 2, "")
    store.sign_on(trip, a)
    with pytest.raises(StoreError, match="full"):
        store.sign_on(trip, b2)
    with pytest.raises(StoreError, match="already signed on"):
        store.sign_on(trip, a)
    with pytest.raises(StoreError, match="stays aboard"):
        store.sign_off(trip, owner)
    store.sign_off(trip, a)
    store.sign_on(trip, b2)
    assert [c["name"] for c in store.bookings_between(b, T0, T0 + DAY)[0]["aboard"]] == ["User 1", "User 3"]


def test_capacity_cannot_drop_below_who_is_aboard(store):
    owner, a = user(store, 1), user(store, 2)
    b = boat(store, owner)
    trip = store.create_booking(b, owner, "Trip", T0, T0 + 4 * HOUR, None, "")
    store.sign_on(trip, a)
    with pytest.raises(StoreError, match="already aboard"):
        store.update_booking(trip, "Trip", T0, T0 + 4 * HOUR, 1, "")


def test_only_bookings_that_overlap_the_range_are_listed(store):
    owner = user(store, 1)
    b = boat(store, owner)
    store.create_booking(b, owner, "Before", T0 - 2 * DAY, T0 - 2 * DAY + HOUR, None, "")
    inside = store.create_booking(b, owner, "Inside", T0, T0 + HOUR, None, "")
    long_trip = store.create_booking(b, owner, "Spans the end", T0 + 12 * HOUR, T0 + 2 * DAY, None, "")
    store.create_booking(b, owner, "After", T0 + 2 * DAY, T0 + 2 * DAY + HOUR, None, "")
    assert [x["id"] for x in store.bookings_between(b, T0, T0 + DAY)] == [inside, long_trip]      # a trip that runs on past the range still shows in it


def test_the_last_owner_cannot_leave_and_leaving_takes_ones_bookings_along(store):
    owner, second, crew = user(store, 1), user(store, 2), user(store, 3)
    b = boat(store, owner, 50)
    store.decide_boat(b, True)
    store.decide_request(store.request_join(b, second, "owner", 50, ""), owner, True)
    store.decide_request(store.request_join(b, crew, "crew", None, ""), owner, True)
    trip = store.create_booking(b, second, "Mine", T0, T0 + HOUR, None, "")
    store.sign_on(trip, crew)
    store.remove_member(b, second)
    assert store.get_booking(trip) is None
    with pytest.raises(StoreError, match="at least one owner"):
        store.remove_member(b, owner)
    store.remove_member(b, crew)
