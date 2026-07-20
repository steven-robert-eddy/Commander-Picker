import pytest

from commander_picker import challenge, store


@pytest.fixture
def conn(tmp_path):
    return store.connect(db_path=tmp_path / "sessions.db")


def test_get_challenge_tracker_returns_all_32_defaulted(conn):
    entries = challenge.get_challenge_tracker(conn)
    assert len(entries) == 32
    assert all(e.status == "not_started" for e in entries)
    assert all(e.commanders == [] for e in entries)
    rakdos = next(e for e in entries if e.slug == "rakdos")
    assert rakdos.colors == "BR"


def test_set_challenge_status_overwrites_status_and_notes(conn):
    challenge.set_challenge_status(conn, "rakdos", "planning", "eyeing an aristocrats build")
    entry = challenge.get_challenge_tracker(conn)
    rakdos = next(e for e in entry if e.slug == "rakdos")
    assert rakdos.status == "planning"
    assert rakdos.notes == "eyeing an aristocrats build"

    challenge.set_challenge_status(conn, "rakdos", "building", None)
    rakdos = next(e for e in challenge.get_challenge_tracker(conn) if e.slug == "rakdos")
    assert rakdos.status == "building"
    assert rakdos.notes is None  # full overwrite, not a partial patch


def test_set_challenge_status_rejects_unknown_slug(conn):
    with pytest.raises(challenge.SessionError):
        challenge.set_challenge_status(conn, "not-a-real-slug", "planning")


def test_set_challenge_status_rejects_unknown_status(conn):
    with pytest.raises(challenge.SessionError):
        challenge.set_challenge_status(conn, "rakdos", "vibing")


def test_add_challenge_commander_appends_and_is_idempotent(conn):
    challenge.add_challenge_commander(conn, "rakdos", "Rakdos, Lord of Riots")
    challenge.add_challenge_commander(conn, "rakdos", "Prosper, Tome-Bound")
    challenge.add_challenge_commander(conn, "rakdos", "Rakdos, Lord of Riots")  # duplicate, no-op

    entry = next(e for e in challenge.get_challenge_tracker(conn) if e.slug == "rakdos")
    names = [c.name for c in entry.commanders]
    assert names == ["Rakdos, Lord of Riots", "Prosper, Tome-Bound"]
    assert all(not c.is_chosen for c in entry.commanders)


def test_remove_challenge_commander_removes_one_only(conn):
    challenge.add_challenge_commander(conn, "rakdos", "Rakdos, Lord of Riots")
    challenge.add_challenge_commander(conn, "rakdos", "Prosper, Tome-Bound")

    challenge.remove_challenge_commander(conn, "rakdos", "Rakdos, Lord of Riots")

    entry = next(e for e in challenge.get_challenge_tracker(conn) if e.slug == "rakdos")
    assert [c.name for c in entry.commanders] == ["Prosper, Tome-Bound"]


def test_choose_challenge_commander_marks_exactly_one_at_a_time(conn):
    challenge.add_challenge_commander(conn, "rakdos", "Rakdos, Lord of Riots")
    challenge.add_challenge_commander(conn, "rakdos", "Prosper, Tome-Bound")

    challenge.choose_challenge_commander(conn, "rakdos", "Rakdos, Lord of Riots")
    entry = next(e for e in challenge.get_challenge_tracker(conn) if e.slug == "rakdos")
    chosen = [c.name for c in entry.commanders if c.is_chosen]
    assert chosen == ["Rakdos, Lord of Riots"]

    challenge.choose_challenge_commander(conn, "rakdos", "Prosper, Tome-Bound")
    entry = next(e for e in challenge.get_challenge_tracker(conn) if e.slug == "rakdos")
    chosen = [c.name for c in entry.commanders if c.is_chosen]
    assert chosen == ["Prosper, Tome-Bound"]  # previous choice un-marked


def test_choose_challenge_commander_requires_existing_candidate(conn):
    with pytest.raises(challenge.SessionError):
        challenge.choose_challenge_commander(conn, "rakdos", "Not Added Yet")


def test_challenge_slug_for_commander_matches_slug_for_colors():
    from commander_picker import colors

    assert challenge.challenge_slug_for_commander("BR") == colors.slug_for_colors("BR")


