import pytest

from boatconnect.store import Store, StoreError

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


def test_a_boats_details_can_be_changed(store):
    owner = user(store, 1)
    b = boat(store, owner)
    store.update_boat(b, "Scooter II", "Newport", "Re-rigged", "America/Los_Angeles")
    got = store.get_boat(b)
    assert (got["name"], got["home_port"], got["description"], got["timezone"], got["status"]) == ("Scooter II", "Newport", "Re-rigged", "America/Los_Angeles", "pending")
    with pytest.raises(StoreError, match="no such boat"):
        store.update_boat("missing", "x", "y", "", "UTC")


def test_changing_the_time_zone_keeps_the_moment_of_a_booking(store):
    owner = user(store, 1)
    b = boat(store, owner)
    trip = store.create_booking(b, owner, "Trip", T0, T0 + HOUR, None, "")
    store.update_boat(b, "Scooter", "Marina", "", "Pacific/Auckland")
    assert store.get_booking(trip)["start_utc"] == T0


# ---- owners' shares over time ----------------------------------------------------------------------------------------------------------------------------

def owners_boat(store, share=100):
    first = user(store, 1)
    b = boat(store, first, share)
    store.decide_boat(b, True)
    return b, first


def test_an_owner_lowers_their_share_and_that_makes_room_for_a_new_owner(store):
    b, first = owners_boat(store)                                                            # the first owner holds all of it
    newcomer = user(store, 2)
    request = store.request_join(b, newcomer, "owner", 25, "")
    with pytest.raises(StoreError, match="must lower their own share first"):
        store.decide_request(request, first, True)
    store.set_share(b, first, 75)
    store.decide_request(request, first, True)
    assert {m["name"]: m["share_percent"] for m in store.members(b)} == {"User 1": 75, "User 2": 25}


def test_an_owner_may_raise_their_share_only_into_room_nobody_holds(store):
    b, first = owners_boat(store, 40)
    second = user(store, 2)
    store.decide_request(store.request_join(b, second, "owner", 30, ""), first, True)        # 40 + 30: 30% unallocated
    store.set_share(b, first, 70)                                                            # takes all of it
    with pytest.raises(StoreError, match="at most 30% is available"):                        # the other owner holds 70, so 30 is the most that is left for them
        store.set_share(b, second, 31)
    with pytest.raises(StoreError, match="at most 70% is available"):
        store.set_share(b, first, 71)
    store.set_share(b, first, 60)
    store.set_share(b, second, 40)                                                           # 60 + 40 = 100


@pytest.mark.parametrize("share", [0, -1, 100.5])
def test_a_share_must_be_between_0_and_100(store, share):
    b, first = owners_boat(store, 50)
    with pytest.raises(StoreError, match="share"):
        store.set_share(b, first, share)


def test_a_share_that_is_unchanged_or_not_an_owners_is_refused(store):
    b, first = owners_boat(store, 50)
    crew = user(store, 2)
    store.decide_request(store.request_join(b, crew, "crew", None, ""), first, True)
    with pytest.raises(StoreError, match="already 50%"):
        store.set_share(b, first, 50)
    with pytest.raises(StoreError, match="only an owner"):
        store.set_share(b, crew, 10)
    with pytest.raises(StoreError, match="only an owner"):
        store.set_share(b, user(store, 3), 10)


def test_the_share_history_records_joining_changing_and_leaving(store):
    b, first = owners_boat(store, 60)
    second = user(store, 2)
    store.decide_request(store.request_join(b, second, "owner", 40, ""), first, True)
    store.set_share(b, first, 50)
    store.remove_member(b, second)
    crew = user(store, 3)
    store.decide_request(store.request_join(b, crew, "crew", None, ""), first, True)             # crew hold no share: nothing to record
    history = [(h["name"], h["old_share"], h["new_share"]) for h in reversed(store.share_history(b))]
    assert history == [("User 1", None, 60), ("User 2", None, 40), ("User 1", 60, 50), ("User 2", 40, None)]


def test_a_database_from_before_the_share_history_is_upgraded(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    first = Store(path)
    owner = user(first, 1)
    b = boat(first, owner, 70)
    with sqlite3.connect(path) as db:                                                         # turn it back into a version-1 database
        db.execute("DROP TABLE share_history")
        db.execute("DROP TABLE calendar_feeds")
        db.execute("DROP TABLE boat_photos")
        db.execute("ALTER TABLE bookings DROP COLUMN updated_at")
        db.execute("PRAGMA user_version = 1")
    upgraded = Store(path)
    assert [(h["name"], h["old_share"], h["new_share"]) for h in upgraded.share_history(b)] == [("User 1", None, 70)]
    upgraded.set_share(b, owner, 65)                                                          # and it works as a new one
    assert len(upgraded.share_history(b)) == 2


# ---- the calendar feed ----------------------------------------------------------------------------------------------------------------------------------------

def test_a_feed_token_is_made_once_and_reset_replaces_it(store):
    owner = user(store, 1)
    first = store.feed_token(owner)
    assert len(first) >= 40 and store.feed_token(owner) == first                          # asking again does not change the address
    assert store.user_for_feed(first)["id"] == owner
    second = store.reset_feed_token(owner)
    assert second != first and store.user_for_feed(first) is None and store.user_for_feed(second)["id"] == owner
    assert store.user_for_feed("nope") is None


def test_the_feed_holds_the_trips_of_the_boats_a_person_belongs_to_only(store):
    sam, ann, cat = user(store, 1), user(store, 2), user(store, 3)
    mine, theirs, waiting = boat(store, sam), boat(store, cat), boat(store, sam)
    store.decide_boat(mine, True)
    store.decide_boat(theirs, True)                                                       # `waiting` stays unapproved
    store.decide_request(store.request_join(mine, ann, "crew", None, ""), sam, True)
    own = store.create_booking(mine, sam, "Mine", T0, T0 + HOUR, 4, "bring a hat")
    store.create_booking(theirs, cat, "Not mine", T0, T0 + HOUR, None, "")
    store.create_booking(waiting, sam, "Unapproved boat", T0, T0 + HOUR, None, "")
    store.sign_on(own, ann)
    trips = store.feed_trips(sam, T0 - DAY, T0 + DAY)
    assert [t["title"] for t in trips] == ["Mine"]
    assert trips[0]["boat_name"] == "Scooter" and trips[0]["home_port"] == "Marina" and trips[0]["created_by_name"] == "User 1"
    assert trips[0]["aboard"] == ["User 1", "User 2"] and trips[0]["notes"] == "bring a hat"
    assert [t["title"] for t in store.feed_trips(ann, T0 - DAY, T0 + DAY)] == ["Mine"]          # crew see the boat's trips too
    assert [t["title"] for t in store.feed_trips(cat, T0 - DAY, T0 + DAY)] == ["Not mine"]


def test_the_feed_window_and_a_removed_member(store):
    sam, crew = user(store, 1), user(store, 2)
    b = boat(store, sam)
    store.decide_boat(b, True)
    store.decide_request(store.request_join(b, crew, "crew", None, ""), sam, True)
    store.create_booking(b, sam, "Soon", T0, T0 + HOUR, None, "")
    store.create_booking(b, sam, "Far off", T0 + 500 * DAY, T0 + 500 * DAY + HOUR, None, "")
    assert [t["title"] for t in store.feed_trips(crew, T0 - DAY, T0 + 400 * DAY)] == ["Soon"]
    store.remove_member(b, crew)
    assert store.feed_trips(crew, T0 - DAY, T0 + 400 * DAY) == []                        # leaving the boat takes its trips out of the feed


def test_a_trips_last_change_moves_when_it_or_its_crew_change(store):
    import time
    sam, crew = user(store, 1), user(store, 2)
    b = boat(store, sam)
    trip = store.create_booking(b, sam, "Trip", T0, T0 + HOUR, None, "")
    stamp = lambda: store.get_booking(trip)["updated_at"]
    first = stamp()
    time.sleep(0.02)
    store.sign_on(trip, crew)
    second = stamp()
    time.sleep(0.02)
    store.update_booking(trip, "Trip renamed", T0, T0 + HOUR, None, "")
    third = stamp()
    time.sleep(0.02)
    store.sign_off(trip, crew)
    assert first < second < third < stamp()


def test_a_database_from_before_the_calendar_feed_is_upgraded(tmp_path):
    import sqlite3
    path = str(tmp_path / "v2.db")
    first = Store(path)
    owner = user(first, 1)
    b = boat(first, owner)
    trip = first.create_booking(b, owner, "Old trip", T0, T0 + HOUR, None, "")
    created = first.get_booking(trip)["created_at"]
    with sqlite3.connect(path) as db:                                                     # turn it back into a version-2 database
        db.execute("DROP TABLE calendar_feeds")
        db.execute("DROP TABLE boat_photos")
        db.execute("ALTER TABLE bookings DROP COLUMN updated_at")
        db.execute("PRAGMA user_version = 2")
    upgraded = Store(path)
    assert upgraded.get_booking(trip)["updated_at"] == created                            # an existing trip's last change starts as its creation
    token = upgraded.feed_token(owner)
    assert upgraded.user_for_feed(token)["id"] == owner


# ---- boat photos ------------------------------------------------------------------------------------------------------------------------------------------

def test_a_boats_photo_is_kept_replaced_and_removed(store):
    owner = user(store, 1)
    b = boat(store, owner)
    assert store.get_photo(b) is None and store.get_boat(b)["photo_updated"] is None
    store.set_photo(b, b"first")
    first = store.get_photo(b)
    assert first["data"] == b"first" and store.get_boat(b)["photo_updated"] == first["updated_at"]
    store.set_photo(b, b"second")
    assert store.get_photo(b)["data"] == b"second"
    store.delete_photo(b)
    assert store.get_photo(b) is None
    with pytest.raises(StoreError, match="no such boat"):
        store.set_photo("missing", b"x")


def test_the_boat_list_says_which_boats_have_a_photo(store):
    owner = user(store, 1)
    with_photo, without = boat(store, owner), boat(store, owner)
    for b in (with_photo, without):
        store.decide_boat(b, True)
    store.set_photo(with_photo, b"x")
    listed = {b["id"]: b["photo_updated"] for b in store.approved_boats()}
    assert listed[with_photo] is not None and listed[without] is None


def test_a_database_from_before_boat_photos_is_upgraded(tmp_path):
    import sqlite3
    path = str(tmp_path / "v3.db")
    first = Store(path)
    owner = user(first, 1)
    b = boat(first, owner)
    with sqlite3.connect(path) as db:                                                     # turn it back into a version-3 database
        db.execute("DROP TABLE boat_photos")
        db.execute("PRAGMA user_version = 3")
    upgraded = Store(path)
    assert upgraded.get_boat(b)["photo_updated"] is None
    upgraded.set_photo(b, b"x")
    assert upgraded.get_photo(b)["data"] == b"x"
