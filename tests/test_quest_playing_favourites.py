"""Playing Favourites inventory filter."""

from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.rules.quest_effects import filter_playing_favourites_loadout


def test_playing_favourites_filters_stickers_and_stamps() -> None:
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="left_human_hand", name="Left Human Hand", level=1),
            LoadoutItem(id="sticky_plaster", name="Sticky Plaster", level=1),
            LoadoutItem(id="fav_one", name="Fav", level=1),
        ],
        stamps=[
            LoadoutItem(id="right_human_hand", name="Right Human Hand", level=1),
            LoadoutItem(id="fav_stamp", name="Fav Stamp", level=1),
            LoadoutItem(id="newspaper", name="Newspaper", level=1),
        ],
        extras={
            "challenge_game_class": "PlayingFavourites",
            "favourite_sticker_ids": "fav_one",
            "favourite_stamp_ids": "fav_stamp",
        },
    )
    filtered = filter_playing_favourites_loadout(loadout)
    sticker_ids = {s.id for s in filtered.stickers}
    stamp_ids = {s.id for s in filtered.stamps}
    assert sticker_ids == {"left_human_hand", "fav_one"}
    assert stamp_ids == {"right_human_hand", "fav_stamp"}
