import pytest

from commander_picker.colors import UnknownColorIdentityError, all_slugs, slug_for_colors


def test_mono_and_colorless():
    assert slug_for_colors("") == "colorless"
    assert slug_for_colors("R") == "mono-red"


def test_guild_order_independent():
    assert slug_for_colors("BR") == "rakdos"
    assert slug_for_colors("RB") == "rakdos"


def test_tricolor_shard_and_wedge():
    assert slug_for_colors("BRG") == "jund"
    assert slug_for_colors("WUR") == "jeskai"


def test_five_color():
    assert slug_for_colors("WUBRG") == "five-color"


def test_four_color():
    assert slug_for_colors("WUBR") == "yore-tiller"
    assert slug_for_colors("GWUB") == "witch-maw"


def test_unknown_color_letter_raises():
    with pytest.raises(UnknownColorIdentityError):
        slug_for_colors("X")


def test_all_slugs_has_32_unique_entries():
    assert len(all_slugs()) == 32
