from cursed_words_solver.capture import screen_relative_origin
from cursed_words_solver.config import Region


def test_screen_relative_origin():
    region = Region(x=619, y=111, width=684, height=692)
    rel_x, rel_y = screen_relative_origin(region, 0, 0)
    assert rel_x == 619
    assert rel_y == 111

    rel_x2, rel_y2 = screen_relative_origin(region, 512, 0)
    assert rel_x2 == 107
    assert rel_y2 == 111
