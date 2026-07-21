import pytest

from commander_picker import favorites, store


@pytest.fixture
def conn(tmp_path):
    return store.connect(db_path=tmp_path / "sessions.db")


def test_set_favorite_status_owned(conn):
    entry = favorites.set_favorite_status(conn, "Rakdos, Lord of Riots", "owned")
    assert entry.commander_name == "Rakdos, Lord of Riots"
    assert entry.status == "owned"
    assert favorites.favorites_by_name(conn, ["Rakdos, Lord of Riots"]) == {"Rakdos, Lord of Riots": "owned"}


def test_set_favorite_status_wishlist(conn):
    favorites.set_favorite_status(conn, "Prosper, Tome-Bound", "wishlist")
    assert favorites.favorites_by_name(conn, ["Prosper, Tome-Bound"]) == {"Prosper, Tome-Bound": "wishlist"}


def test_set_favorite_status_is_idempotent_and_overwrites(conn):
    favorites.set_favorite_status(conn, "Rakdos, Lord of Riots", "wishlist")
    favorites.set_favorite_status(conn, "Rakdos, Lord of Riots", "owned")  # not additive -- full overwrite
    assert favorites.favorites_by_name(conn, ["Rakdos, Lord of Riots"]) == {"Rakdos, Lord of Riots": "owned"}


def test_set_favorite_status_rejects_unknown_status(conn):
    with pytest.raises(favorites.SessionError):
        favorites.set_favorite_status(conn, "Rakdos, Lord of Riots", "loved")


def test_clear_favorite_removes_the_row(conn):
    favorites.set_favorite_status(conn, "Rakdos, Lord of Riots", "owned")
    favorites.clear_favorite(conn, "Rakdos, Lord of Riots")
    assert favorites.favorites_by_name(conn, ["Rakdos, Lord of Riots"]) == {}


def test_clear_favorite_on_never_favorited_name_is_a_no_op(conn):
    favorites.clear_favorite(conn, "Never Favorited")  # must not raise


def test_favorites_by_name_only_returns_matching_names(conn):
    favorites.set_favorite_status(conn, "Rakdos, Lord of Riots", "owned")
    favorites.set_favorite_status(conn, "Prosper, Tome-Bound", "wishlist")

    result = favorites.favorites_by_name(conn, ["Rakdos, Lord of Riots", "Prosper, Tome-Bound", "Never Favorited"])
    assert result == {"Rakdos, Lord of Riots": "owned", "Prosper, Tome-Bound": "wishlist"}


def test_favorites_by_name_empty_list_returns_empty_dict(conn):
    assert favorites.favorites_by_name(conn, []) == {}
