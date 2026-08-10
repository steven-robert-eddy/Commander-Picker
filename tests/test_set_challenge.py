import pytest

from commander_picker import set_challenge, store

KNOWN_SETS = [
    {"slug": "sos", "name": "Secrets of Strixhaven"},
    {"slug": "akh", "name": "Amonkhet"},
]


@pytest.fixture
def conn(tmp_path):
    return store.connect(db_path=tmp_path / "sessions.db")


def test_get_tracker_returns_one_entry_per_known_set_defaulted(conn):
    entries = set_challenge.get_tracker(conn, KNOWN_SETS)
    assert len(entries) == 2
    assert all(e.status == "not_started" for e in entries)
    assert all(e.commanders == [] for e in entries)
    sos = next(e for e in entries if e.slug == "sos")
    assert sos.name == "Secrets of Strixhaven"


def test_set_status_overwrites_status_and_notes(conn):
    set_challenge.set_status(conn, KNOWN_SETS, "sos", "planning", "eyeing Prosper")
    sos = next(e for e in set_challenge.get_tracker(conn, KNOWN_SETS) if e.slug == "sos")
    assert sos.status == "planning"
    assert sos.notes == "eyeing Prosper"

    set_challenge.set_status(conn, KNOWN_SETS, "sos", "building", None)
    sos = next(e for e in set_challenge.get_tracker(conn, KNOWN_SETS) if e.slug == "sos")
    assert sos.status == "building"
    assert sos.notes is None  # full overwrite, not a partial patch


def test_set_status_rejects_unknown_slug(conn):
    with pytest.raises(set_challenge.SessionError):
        set_challenge.set_status(conn, KNOWN_SETS, "not-a-real-slug", "planning")


def test_set_status_rejects_unknown_status(conn):
    with pytest.raises(set_challenge.SessionError):
        set_challenge.set_status(conn, KNOWN_SETS, "sos", "vibing")


def test_add_commander_appends_and_is_idempotent(conn):
    set_challenge.add_commander(conn, KNOWN_SETS, "sos", "Prosper, Tome-Bound")
    set_challenge.add_commander(conn, KNOWN_SETS, "sos", "Rakdos, Lord of Riots")
    set_challenge.add_commander(conn, KNOWN_SETS, "sos", "Prosper, Tome-Bound")  # duplicate, no-op

    entry = next(e for e in set_challenge.get_tracker(conn, KNOWN_SETS) if e.slug == "sos")
    names = [c.name for c in entry.commanders]
    assert names == ["Prosper, Tome-Bound", "Rakdos, Lord of Riots"]
    assert all(not c.is_chosen for c in entry.commanders)


def test_add_commander_rejects_unknown_slug(conn):
    with pytest.raises(set_challenge.SessionError):
        set_challenge.add_commander(conn, KNOWN_SETS, "not-a-real-slug", "Prosper, Tome-Bound")


def test_remove_commander_removes_one_only(conn):
    set_challenge.add_commander(conn, KNOWN_SETS, "sos", "Prosper, Tome-Bound")
    set_challenge.add_commander(conn, KNOWN_SETS, "sos", "Rakdos, Lord of Riots")

    set_challenge.remove_commander(conn, KNOWN_SETS, "sos", "Prosper, Tome-Bound")

    entry = next(e for e in set_challenge.get_tracker(conn, KNOWN_SETS) if e.slug == "sos")
    assert [c.name for c in entry.commanders] == ["Rakdos, Lord of Riots"]


def test_choose_commander_marks_exactly_one_at_a_time(conn):
    set_challenge.add_commander(conn, KNOWN_SETS, "sos", "Prosper, Tome-Bound")
    set_challenge.add_commander(conn, KNOWN_SETS, "sos", "Rakdos, Lord of Riots")

    set_challenge.choose_commander(conn, KNOWN_SETS, "sos", "Prosper, Tome-Bound")
    entry = next(e for e in set_challenge.get_tracker(conn, KNOWN_SETS) if e.slug == "sos")
    assert [c.name for c in entry.commanders if c.is_chosen] == ["Prosper, Tome-Bound"]

    set_challenge.choose_commander(conn, KNOWN_SETS, "sos", "Rakdos, Lord of Riots")
    entry = next(e for e in set_challenge.get_tracker(conn, KNOWN_SETS) if e.slug == "sos")
    assert [c.name for c in entry.commanders if c.is_chosen] == ["Rakdos, Lord of Riots"]  # previous choice un-marked


def test_choose_commander_requires_existing_candidate(conn):
    with pytest.raises(set_challenge.SessionError):
        set_challenge.choose_commander(conn, KNOWN_SETS, "sos", "Not Added Yet")


def test_entries_are_scoped_to_the_known_sets_passed_in(conn):
    # A set dropped from known_sets (e.g. update-data re-tags it as
    # all-reprints) still has stored rows, but no longer reads back --
    # same "known_sets is the source of truth for which slugs exist"
    # contract as get_tracker's synthesize-at-read-time behavior.
    set_challenge.add_commander(conn, KNOWN_SETS, "sos", "Prosper, Tome-Bound")
    entries = set_challenge.get_tracker(conn, [{"slug": "akh", "name": "Amonkhet"}])
    assert [e.slug for e in entries] == ["akh"]
